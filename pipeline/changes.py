"""Structured Change Declarations — LLM-declared state transitions per chapter.

After every chapter, the drafting/revising LLM outputs a ``---CHANGES---``
JSON block declaring exactly what changed in the story world. The system
parses this block, validates it, and deterministically updates the canonical
state store — replacing passive state extraction with active state declaration.

Design:
- 12 change categories matching tianming's declaration classes
- Compact JSON schema so the LLM can emit it without excessive token cost
- Each category is a list of 2-3 field tuples, not full nested objects
- The parse/apply pipeline strips the block from prose before saving
- Combined with the debate court, the Magistrate can cross-validate
  declared changes against continuity complaints
"""

import json
import re
from typing import Optional, Tuple

from pipeline.canonical_store import CanonicalStore, is_valid_foreshadowing_transition

# ── Change Categories ────────────────────────────────────────────────

# 12 categories the LLM must declare after each chapter.
# Each is tagged with a compact field spec for the JSON schema.
CHANGE_CATEGORIES = {
    "character_status": {
        "label": "角色状态变化",
        "desc": "Character level/rank, new abilities, lost abilities, mental state, key events, relationship changes",
        "fields": ["character", "change_type", "detail", "chapter"],
    },
    "conflict_progress": {
        "label": "冲突进度",
        "desc": "Conflict ID, new status, advancement event",
        "fields": ["conflict_id", "new_status", "event"],
    },
    "plot_nodes": {
        "label": "新剧情节点",
        "desc": "Keyword, context summary, involved characters, story line (main/sub)",
        "fields": ["keyword", "summary", "characters", "story_line"],
    },
    "foreshadowing_actions": {
        "label": "伏笔动作",
        "desc": "Foreshadow ID, action type (setup / payoff), detail",
        "fields": ["element", "action", "detail"],
    },
    "location_changes": {
        "label": "地点状态变化",
        "desc": "Location ID, new state, triggering event",
        "fields": ["location", "new_state", "event"],
    },
    "faction_changes": {
        "label": "势力状态变化",
        "desc": "Faction ID, new state, triggering event",
        "fields": ["faction", "new_state", "event"],
    },
    "time_advancement": {
        "label": "时间推进",
        "desc": "Current time period, time elapsed, key time events",
        "fields": ["time_period", "elapsed", "events"],
    },
    "character_movement": {
        "label": "角色移动",
        "desc": "Character ID, origin → destination",
        "fields": ["character", "from_location", "to_location"],
    },
    "item_transfers": {
        "label": "物品流转",
        "desc": "Item name, from holder → to holder, item state",
        "fields": ["item", "from_holder", "to_holder", "state"],
    },
    "secret_reveals": {
        "label": "秘密揭示",
        "desc": "Secret ID, new knowers, revelation method",
        "fields": ["secret_id", "new_knowers", "method"],
    },
    "oath_changes": {
        "label": "誓约约束变化",
        "desc": "Oath ID, change action, involved characters, constraints",
        "fields": ["oath_id", "action", "characters", "constraints"],
    },
    "deadline_changes": {
        "label": "截止约束变化",
        "desc": "Deadline ID, change action, trigger condition, countdown",
        "fields": ["deadline_id", "action", "trigger", "time_remaining"],
    },
}

# Compact JSON schema injected into the draft/revision prompts.
# The LLM sees this inline and learns the format by example.
CHANGES_SCHEMA_EXAMPLE = """---CHANGES---
{
  "character_status": [
    {"character": "林尘", "change_type": "level_up", "detail": "突破至筑基期", "chapter": 3}
  ],
  "conflict_progress": [
    {"conflict_id": "正邪大战", "new_status": "escalating", "event": "魔族先锋袭击边关"}
  ],
  "plot_nodes": [
    {"keyword": "叛徒现身", "summary": "内门长老实为魔族卧底", "characters": ["林尘", "玄真"], "story_line": "main"}
  ],
  "foreshadowing_actions": [
    {"element": "神秘玉佩", "action": "setup", "detail": "玉佩在林尘突破时发光，古纹浮现"}
  ],
  "location_changes": [],
  "faction_changes": [],
  "time_advancement": [
    {"time_period": "深夜", "elapsed": "6小时", "events": ["月圆之夜"]}
  ],
  "character_movement": [
    {"character": "林尘", "from_location": "练功房", "to_location": "后山禁地"}
  ],
  "item_transfers": [],
  "secret_reveals": [],
  "oath_changes": [],
  "deadline_changes": []
}
---END CHANGES---"""

# Regex to extract changes block
_CHANGES_FENCE_RE = re.compile(
    r'\n?---CHANGES---\s*\n(.*?)\n\s*---END CHANGES---',
    re.DOTALL,
)

# ── Parse / Apply ─────────────────────────────────────────────────────

def parse_changes_block(text: str) -> Tuple[str, Optional[dict]]:
    """Extract and strip the ``---CHANGES---`` fence from chapter text.

    Args:
        text: Raw LLM output potentially containing a changes block.

    Returns:
        Tuple of (clean_text, changes_dict_or_None).
        clean_text has the changes block removed.
        changes_dict has all 12 category keys present (empty lists when
        no changes were declared in that category).
    """
    m = _CHANGES_FENCE_RE.search(text)
    if not m:
        return text, None

    raw_json = m.group(1).strip()
    clean_text = _CHANGES_FENCE_RE.sub("", text).strip()
    # Collapse double blank lines left by fence removal
    clean_text = re.sub(r'\n{3,}', '\n\n', clean_text)

    try:
        parsed = json.loads(raw_json)
    except json.JSONDecodeError:
        # Try repair: look for the outermost braces
        brace_start = raw_json.find("{")
        brace_end = raw_json.rfind("}")
        if brace_start >= 0 and brace_end > brace_start:
            try:
                parsed = json.loads(raw_json[brace_start:brace_end + 1])
            except json.JSONDecodeError:
                return clean_text, None
        else:
            return clean_text, None

    if not isinstance(parsed, dict):
        return clean_text, None

    # Normalise: ensure all 12 keys exist
    normalised = {}
    for cat in CHANGE_CATEGORIES:
        val = parsed.get(cat, [])
        if not isinstance(val, list):
            val = []
        normalised[cat] = val

    return clean_text, normalised


def apply_changes_to_store(
    changes: dict,
    store: CanonicalStore,
    chapter_num: int,
) -> int:
    """Walk each declared change and update the canonical store.

    Each change category maps to the corresponding CanonicalStore method.
    Returns the total number of changes applied.
    """
    total = 0

    # Character status changes → character traits
    for entry in changes.get("character_status", []):
        if not isinstance(entry, dict):
            continue
        character = entry.get("character", "unknown")
        change_type = entry.get("change_type", "update")
        detail = entry.get("detail", "")
        store.record_character_trait(
            character=character,
            trait_type=f"status_{change_type}",
            value=detail,
            chapter=chapter_num,
            importance=0.7,
        )
        total += 1

    # Conflict progress → plot threads
    for entry in changes.get("conflict_progress", []):
        if not isinstance(entry, dict):
            continue
        conflict_id = entry.get("conflict_id", "unknown")
        new_status = entry.get("new_status", "active")
        store.record_plot_thread(
            thread_name=conflict_id,
            status=new_status,
            introduced_chapter=chapter_num,
            importance=0.8,
        )
        total += 1

    # Plot nodes → generic memory entries
    for entry in changes.get("plot_nodes", []):
        if not isinstance(entry, dict):
            continue
        keyword = entry.get("keyword", "event")
        summary = entry.get("summary", "")
        characters = entry.get("characters", [])
        store.store_memory(
            content=f"Plot node: {keyword} - {summary} (involving: {', '.join(characters) if characters else 'none'})",
            tags=["plot_thread", keyword.lower(), "active"],
            importance=0.7,
            metadata={
                "keyword": keyword,
                "summary": summary,
                "characters": characters,
                "chapter": chapter_num,
                "entity_type": "thread",
            },
        )
        total += 1

    # Foreshadowing actions → state machine transitions
    for entry in changes.get("foreshadowing_actions", []):
        if not isinstance(entry, dict):
            continue
        element = entry.get("element", "")
        action = entry.get("action", "setup")
        detail = entry.get("detail", "")

        if action == "setup":
            store.record_foreshadowing(
                element=element,
                plant_chapter=chapter_num,
                importance=0.6,
            )
        elif action == "payoff":
            store.mark_foreshadowing_paid(element=element, payoff_chapter=chapter_num)
        elif action in ("hinted", "reinforced", "due", "overdue"):
            target_status = action
            if is_valid_foreshadowing_transition("planted", target_status):
                store.mark_foreshadowing_progress(
                    element=element,
                    new_status=target_status,
                    chapter=chapter_num,
                )
        total += 1

    # Location changes → world facts
    for entry in changes.get("location_changes", []):
        if not isinstance(entry, dict):
            continue
        location = entry.get("location", "unknown")
        new_state = entry.get("new_state", "")
        store.record_world_fact(
            location=location,
            fact=f"State changed to: {new_state} (Ch {chapter_num})",
            chapter=chapter_num,
            importance=0.5,
        )
        total += 1

    # Faction changes → world facts
    for entry in changes.get("faction_changes", []):
        if not isinstance(entry, dict):
            continue
        faction = entry.get("faction", "unknown")
        new_state = entry.get("new_state", "")
        store.record_world_fact(
            location=faction,
            fact=f"Faction state changed to: {new_state} (Ch {chapter_num})",
            chapter=chapter_num,
            importance=0.5,
        )
        total += 1

    # Character movement → character trait (location)
    for entry in changes.get("character_movement", []):
        if not isinstance(entry, dict):
            continue
        character = entry.get("character", "unknown")
        to_location = entry.get("to_location", "")
        store.record_character_trait(
            character=character,
            trait_type="location",
            value=to_location,
            chapter=chapter_num,
            importance=0.6,
        )
        total += 1

    # Item transfers → world facts
    for entry in changes.get("item_transfers", []):
        if not isinstance(entry, dict):
            continue
        item = entry.get("item", "unknown")
        to_holder = entry.get("to_holder", "")
        state = entry.get("state", "")
        store.record_world_fact(
            location=f"Item:{item}",
            fact=f"Held by {to_holder}, state: {state} (Ch {chapter_num})",
            chapter=chapter_num,
            importance=0.5,
        )
        total += 1

    # Secret reveals → character traits (knowledge)
    for entry in changes.get("secret_reveals", []):
        if not isinstance(entry, dict):
            continue
        secret_id = entry.get("secret_id", "unknown")
        new_knowers = entry.get("new_knowers", [])
        method = entry.get("method", "")
        for knower in (new_knowers if isinstance(new_knowers, list) else [new_knowers]):
            store.record_character_trait(
                character=str(knower),
                trait_type="knowledge",
                value=f"Learned secret '{secret_id}' via {method}",
                chapter=chapter_num,
                importance=0.7,
            )
        total += 1

    # Time advancement, oath changes, and deadline changes → generic store_memory
    for cat, tag in [
        ("time_advancement", "timeline"),
        ("oath_changes", "oath"),
        ("deadline_changes", "deadline"),
    ]:
        for entry in changes.get(cat, []):
            if not isinstance(entry, dict):
                continue
            content_parts = [f"{cat}: "]
            for k, v in entry.items():
                content_parts.append(f"{k}={v}; ")
            store.store_memory(
                content="".join(content_parts)[:300],
                tags=[tag, f"ch{chapter_num}"],
                importance=0.5,
                metadata={**entry, "chapter": chapter_num},
            )
            total += 1

    return total


def format_changes_for_magistrate(changes: dict) -> str:
    """Format declared changes as a human-readable block.

    Used by the debate court: the Magistrate can cross-reference the LLM's
    own change declarations against the Lore Prosecutor's continuity complaints.
    """
    if not changes:
        return "[No changes declared — the LLM did not output a ---CHANGES--- block]"

    lines = [
        "## CHAPTER CHANGE DECLARATIONS (LLM self-reported state transitions)",
        "",
    ]

    for cat, entries in changes.items():
        category_meta = CHANGE_CATEGORIES.get(cat, {})
        label = category_meta.get("label", cat)
        if not entries:
            continue
        lines.append(f"### {label} ({len(entries)} entries):")
        for i, entry in enumerate(entries, 1):
            if not isinstance(entry, dict):
                continue
            compact = ", ".join(f"{k}: {v}" for k, v in entry.items())
            lines.append(f"  {i}. {compact}")
        lines.append("")

    lines.append("[/CHANGE DECLARATIONS]")
    return "\n".join(lines)


def changes_to_summary_line(changes: Optional[dict]) -> str:
    """Single-line summary of changes for logging."""
    if changes is None:
        return "No changes declared"
    non_empty = sum(1 for v in changes.values() if v)
    total_entries = sum(len(v) for v in changes.values())
    return f"{non_empty}/12 categories with {total_entries} entries"

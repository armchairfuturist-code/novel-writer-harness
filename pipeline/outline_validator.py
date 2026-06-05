"""Outline Validator — pre-draft structural quality gate.

Runs a single LLM call between outline generation (phase 4) and drafting
(phase 5) to catch structural problems BEFORE spending API dollars on
chapter writing. Uses the cheap `flash` model — one call, <$0.01.

Checks five dimensions:
1. Character coverage — every named character must appear in at least one
   chapter's POV, key_events, or character_arc_beat.
2. Foreshadowing completeness — every plant needs a target payoff chapter
   within range.
3. Emotional arc progression — adjacent chapters shouldn't flatline on
   identical arcs.
4. Beat density balance — no chapter should be empty of key_events or
   character_arc_beats.
5. Information boundary sanity — POV characters can only witness events
   they could plausibly be present for.

Design:
- FAILs pause the pipeline (structural problem found).
- WARNs display but don't block (advisory).
- The report prints inline so the user can decide to continue or fix.

Inspired by:
- tianming's blueprint attendance + unified validation
- oh-story-claudecode's detect-story-gaps hook
- dramatica-flow's information boundary system
- NovelForge's structural awareness
"""

from typing import Optional

from config import Config
from pipeline.api import CrofaiClient, parse_json_output


# ── System Prompt ─────────────────────────────────────────────────────

VALIDATOR_SYSTEM_PROMPT = """You are a structural editor evaluating a novel outline
before drafting begins. Your job is to find problems that will waste chapters — not
prose problems, but structural problems: missing character assignments, unpayable
foreshadowing debts, flat emotional arcs, empty chapters, impossible POV assignments.

You are ruthless but fair. A WARN means "this could cause trouble." A FAIL means
"this WILL cause trouble — fix it before you draft."

### RULES:

1. **Character Coverage (PASS/WARN/FAIL)**
   - Every named character MUST appear in at least one chapter's POV, key_events, or character_arc_beat.
   - Characters who exist in the cast but never appear in a single chapter are FAIL.
   - Characters who appear only once in the whole novel are WARN (carriers of single-scene importance).

2. **Foreshadowing Completeness (PASS/WARN)**
   - Every chapter that declares a "foreshadowing" seed must have a corresponding
     payoff in a later chapter's key_events or foreshadowing field.
   - If a seed is planted in chapter N and never referenced again → WARN.
   - If a seed is planted and the payoff is within 1 chapter (too fast) → WARN.
   - This is a WARN-level check, not FAIL, because some seeds may be resolved
     implicitly through character arcs.

3. **Emotional Arc Progression (PASS/WARN/FAIL)**
   - No 3+ consecutive chapters should have identical or near-identical emotional arcs.
     "tension→tension→tension" is a flatline, not an arc.
   - 3 consecutive identical arcs → WARN. 5+ consecutive → FAIL.
   - Entire acts with no emotional variation → FAIL.

4. **Beat Density Balance (PASS/WARN/FAIL)**
   - Every chapter must have ≥1 key_event. Zero → FAIL.
   - Every chapter must have ≥1 character_arc_beat (or a clear reason why not). Zero → WARN.
   - Chapters with ≥10 key_events are WARN (overstuffed — split into two chapters).

5. **Information Boundary Sanity (PASS/WARN/FAIL)**
   - A POV character can only narrate events they witness.
   - If a chapter's POV is a character who dies in that chapter (and key_events
     reference events after their death) → FAIL.
   - If a POV character couldn't plausibly be present for a key_event → WARN.
   - If the outline is agnostic about character locations, default to PASS unless
     there's a clear impossibility.

### OUTPUT FORMAT:
Return a single valid JSON object (no markdown wrappers):

{
  "character_coverage": {
    "status": "PASS" | "WARN" | "FAIL",
    "detail": "One-line summary",
    "issues": ["specific issue 1", "specific issue 2"]
  },
  "foreshadowing_completeness": {
    "status": "PASS" | "WARN",
    "detail": "One-line summary",
    "issues": ["specific issue 1"]
  },
  "emotional_arc_progression": {
    "status": "PASS" | "WARN" | "FAIL",
    "detail": "One-line summary",
    "issues": ["specific issue 1"]
  },
  "beat_density": {
    "status": "PASS" | "WARN" | "FAIL",
    "detail": "One-line summary",
    "issues": ["specific issue 1"]
  },
  "info_boundaries": {
    "status": "PASS" | "WARN" | "FAIL",
    "detail": "One-line summary",
    "issues": ["specific issue 1"]
  },
  "overall": "PASS" | "WARN" | "FAIL",
  "summary": "One-sentence overall verdict with the most important action item"
}
"""

VALIDATOR_USER_TEMPLATE = """Evaluate this novel outline for structural problems.

### PROJECT SPEC:
- Title: {title}
- Genre: {genre}
- Tone: {tone}
- POV: {pov_mode}

### CHARACTER CAST ({char_count} characters):
{character_list}

### WORLD CONTEXT:
{world_context}

### CHAPTER OUTLINE ({chapter_count} chapters):
{outline_text}

Return the validation JSON with all five dimensions assessed."""


# ── Formatting helpers ────────────────────────────────────────────────

def _format_character_list(characters: dict) -> tuple[str, int]:
    """Build a compact character list for the validator prompt."""
    char_list = characters.get("characters", [])
    if not char_list:
        return "[No characters defined]", 0

    lines = []
    for c in char_list:
        name = c.get("name", "?")
        role = c.get("role", "?")
        arc = c.get("arc", "")[:80]
        lines.append(f"  - {name} ({role}): arc={arc}")
    return "\n".join(lines), len(char_list)


def _format_outline_text(outline: dict) -> tuple[str, int]:
    """Build a compact outline summary for the validator prompt.

    Each chapter is compressed to ~120 chars to keep the full outline
    within the validator model's context window (even for 30-chapter novels).
    """
    acts = outline.get("acts", [])
    lines = []
    ch_count = 0
    for act in acts:
        act_name = act.get("name", f"Act {act.get('act_number', '?')}")
        lines.append(f"## {act_name}")
        for ch in act.get("chapters", []):
            ch_num = ch.get("chapter", ch_count + 1)
            ch_count += 1
            title = ch.get("title", f"Ch{ch_num}")
            pov = ch.get("pov", "?")
            summary = ch.get("summary", "")[:120]
            key_events = ch.get("key_events", [])
            emo_arc = ch.get("emotional_arc", "")[:40]
            fshadow = ch.get("foreshadowing", "")[:80]
            arc_beat = ch.get("character_arc_beat", "")[:80]
            # Compact one-liner per chapter
            parts = [f"Ch{ch_num} {title} | POV={pov} | {emo_arc} | {summary}"]
            if key_events:
                parts.append(f"  Events: {', '.join(str(e)[:40] for e in key_events[:4])}")
            if fshadow:
                parts.append(f"  Foreshadow: {fshadow}")
            if arc_beat:
                parts.append(f"  Char Arc: {arc_beat}")
            lines.append("\n".join(parts))
    return "\n".join(lines), ch_count


def _format_world_context(world: dict) -> str:
    """Build a compact world context summary."""
    parts = []
    if isinstance(world, dict):
        name = world.get("world_name", "")
        if name:
            parts.append(f"World: {name}")
        conflict = world.get("central_conflict", "")
        if conflict:
            parts.append(f"Central Conflict: {conflict[:200]}")
        mood = world.get("mood_setting", "")
        if mood:
            parts.append(f"Mood/Setting: {mood[:200]}")
    return "\n".join(parts) if parts else "[World not yet built]"


# ── Public entry point ────────────────────────────────────────────────

def run_outline_validator(
    spec: dict,
    world: dict,
    characters: dict,
    outline: dict,
    config: Optional[Config] = None,
) -> dict:
    """Run the outline validator — one LLM call, five structural checks.

    Args:
        spec: Project specification from seed phase.
        world: World bible dict.
        characters: Character profiles dict.
        outline: Full outline dict (acts → chapters).
        config: Config override.

    Returns:
        Dict with keys: character_coverage, foreshadowing_completeness,
        emotional_arc_progression, beat_density, info_boundaries, overall, summary.
    """
    config = config or Config()
    client = CrofaiClient(config)
    model = config.model_for_phase("outline_validator")  # deepseek-flash — enough context

    char_text, char_count = _format_character_list(characters)
    outline_text, chapter_count = _format_outline_text(outline)
    world_context = _format_world_context(world)

    prompt = VALIDATOR_USER_TEMPLATE.format(
        title=spec.get("title", "Untitled"),
        genre=spec.get("genre", "Unknown"),
        tone=spec.get("tone", "Unknown"),
        pov_mode=spec.get("pov", "Unknown"),
        char_count=char_count,
        character_list=char_text,
        world_context=world_context,
        chapter_count=chapter_count,
        outline_text=outline_text,
    )

    try:
        content = client.chat_with_retry(
            model,
            messages=[{"role": "user", "content": prompt}],
            system_prompt=VALIDATOR_SYSTEM_PROMPT,
            temperature=0.2,  # deterministic evaluation
        )
        result = parse_json_output(content, label="outline_validator")
    except Exception as e:
        client.close()
        return {
            "character_coverage": {"status": "ERROR", "detail": str(e), "issues": []},
            "foreshadowing_completeness": {"status": "ERROR", "detail": str(e), "issues": []},
            "emotional_arc_progression": {"status": "ERROR", "detail": str(e), "issues": []},
            "beat_density": {"status": "ERROR", "detail": str(e), "issues": []},
            "info_boundaries": {"status": "ERROR", "detail": str(e), "issues": []},
            "overall": "ERROR",
            "summary": f"Validator failed: {e}",
        }

    client.close()

    # Ensure all keys exist
    for key in ["character_coverage", "foreshadowing_completeness", "emotional_arc_progression", "beat_density", "info_boundaries"]:
        if key not in result:
            result[key] = {"status": "PASS", "detail": "Not assessed", "issues": []}
        if "status" not in result[key]:
            result[key]["status"] = "PASS"

    # Determine overall from sub-checks
    has_fail = any(result[k].get("status") == "FAIL" for k in ["character_coverage", "emotional_arc_progression", "beat_density", "info_boundaries"])
    has_warn = any(result[k].get("status") in ("WARN", "FAIL") for k in ["character_coverage", "foreshadowing_completeness", "emotional_arc_progression", "beat_density", "info_boundaries"])

    if has_fail:
        result["overall"] = "FAIL"
    elif has_warn:
        result["overall"] = "WARN"
    else:
        result["overall"] = "PASS"

    if "summary" not in result:
        result["summary"] = "Validation complete."

    return result


def print_validation_report(report: dict):
    """Print a human-readable validation report to stdout."""
    print()
    print("=== Outline Validation Report ===")

    checks = [
        ("Character Coverage", "character_coverage"),
        ("Foreshadowing",        "foreshadowing_completeness"),
        ("Emotional Arcs",       "emotional_arc_progression"),
        ("Beat Density",         "beat_density"),
        ("Info Boundaries",      "info_boundaries"),
    ]

    for label, key in checks:
        check = report.get(key, {})
        status = check.get("status", "?")
        detail = check.get("detail", "")
        tag = {"PASS": "✓", "WARN": "⚠", "FAIL": "✗", "ERROR": "!"}.get(status, "?")
        print(f"  {tag} {label:<22} {status:<5}  {detail}")
        for issue in check.get("issues", []):
            print(f"     → {issue}")

    overall = report.get("overall", "?")
    summary = report.get("summary", "")
    print(f"\n  Result: {overall} — {summary}")
    print()

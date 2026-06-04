"""Foreshadow tracking with 6-state machine, urgency tiers, and auto-detection.

States
  proposed -> planted -> due -> overdue -> resolved | partially_resolved | abandoned
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# ── constants ───────────────────────────────────────────────────

URGENCY_TIER_1 = 0       # must resolve this chapter
URGENCY_TIER_2 = 2       # upcoming (resolve within 2 chapters)
URGENCY_TIER_3 = 5       # distant

STATE_PROPOSED = "proposed"
STATE_PLANTED = "planted"
STATE_DUE = "due"
STATE_OVERDUE = "overdue"
STATE_RESOLVED = "resolved"
STATE_PARTIAL = "partially_resolved"
STATE_ABANDONED = "abandoned"

VALID_STATES = {
    STATE_PROPOSED, STATE_PLANTED, STATE_DUE, STATE_OVERDUE,
    STATE_RESOLVED, STATE_PARTIAL, STATE_ABANDONED,
}

TRANSITIONS = {
    STATE_PROPOSED: {STATE_PLANTED, STATE_ABANDONED},
    STATE_PLANTED: {STATE_DUE, STATE_OVERDUE, STATE_RESOLVED, STATE_ABANDONED},
    STATE_DUE: {STATE_OVERDUE, STATE_RESOLVED, STATE_PARTIAL, STATE_ABANDONED},
    STATE_OVERDUE: {STATE_RESOLVED, STATE_PARTIAL, STATE_ABANDONED},
    STATE_RESOLVED: set(),
    STATE_PARTIAL: {STATE_RESOLVED, STATE_ABANDONED},
    STATE_ABANDONED: set(),
}

# Regex patterns for auto-detecting foreshadows in chapter text
SIGNAL_PATTERNS = [
    # looming / ominous — something is coming
    r"(?i)\b(something\s+(terrible|wonderful|strange|unexpected|dark)\s+(is\s+)?coming)\b",
    r"(?i)\b(little\s+did\s+\w+\s+know)\b",
    r"(?i)\b(unbeknownst)\b",
    r"(?i)\b(what\s+\w+\s+didn'?t\s+(realize|know|understand))\b",
    # mystery objects
    r"(?i)\b(a(n?)\s+(strange|mysterious|unknown|odd|puzzling)\s+(object|package|letter|box|key|device|artifact))\b",
    r"(?i)\b(an?\s+unexplained\s+(phenomenon|occurrence|event|sound|smell|presence))\b",
    # narrative-future language
    r"(?i)\b(as\s+\w+\s+would\s+(later|soon)\s+(discover|learn|find|realize))\b",
    r"(?i)\b(this\s+(would|will)\s+(prove|become|lead|change|haunt))\b",
    r"(?i)\b(that\s+would\s+be\s+the\s+(last|first))\b",
    r"(?i)\b(in\s+the\s+(days|weeks|months|years)\s+(ahead|to\s+come|that\s+followed))\b",
    # explicit authorial foreshadow
    r"(?i)\b(foreshadow(ing|ed|s)?)\b",
    r"(?i)\b(a\s+hint\s+of\s+(things\s+)?to\s+come)\b",
    r"(?i)\b(the\s+(seeds|beginnings)\s+of\s+(something|what))\b",
    # unknown-signal cues
    r"(?i)\b(something\s+(was\s+)?(wrong|off|amiss|different))\b",
    r"(?i)\b(a\s+(growing|nagging|vague|creeping)\s+(sense|feeling|dread|suspicion))\b",
]

# ── data structures ─────────────────────────────────────────────


@dataclass
class ForeshadowElement:
    """A single foreshadowing thread tracked through the narrative."""

    id: str
    description: str
    state: str = STATE_PROPOSED
    plant_chapter: int | None = None
    resolve_chapter: int | None = None
    importance: float = 0.5       # 0.0–1.0
    subtlety: float = 0.5         # 0.0 (overt) – 1.0 (very subtle)
    urgency: int = URGENCY_TIER_2  # chapters-from-now urgency
    category: str = ""
    related_characters: list[str] = field(default_factory=list)
    notes: str = ""
    is_overdue: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "description": self.description,
            "state": self.state,
            "plant_chapter": self.plant_chapter,
            "resolve_chapter": self.resolve_chapter,
            "importance": self.importance,
            "subtlety": self.subtlety,
            "urgency": self.urgency,
            "category": self.category,
            "related_characters": self.related_characters,
            "notes": self.notes,
            "is_overdue": self.is_overdue,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> ForeshadowElement:
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


# ── tracker ─────────────────────────────────────────────────────


class ForeshadowTracker:
    """Persistent foreshadow state machine with context-building."""

    def __init__(self, path: str | Path = "foreshadow_state.json") -> None:
        self.path = Path(path)
        self._elements: dict[str, ForeshadowElement] = {}
        self._chapter = 0
        self._dirty = False
        self._load()

    # ── persistence ─────────────────────────────────────────────

    def _load(self) -> None:
        if self.path.exists():
            data = json.loads(self.path.read_text())
            self._elements = {
                eid: ForeshadowElement.from_dict(ed)
                for eid, ed in data.get("elements", {}).items()
            }
            self._chapter = data.get("chapter", 0)

    def save(self) -> None:
        data = {
            "elements": {eid: e.to_dict() for eid, e in self._elements.items()},
            "chapter": self._chapter,
        }
        self.path.write_text(json.dumps(data, indent=2))
        self._dirty = False

    def save_if_dirty(self) -> None:
        if self._dirty:
            self.save()

    # ── state machine ───────────────────────────────────────────

    def _transition(self, element_id: str, new_state: str) -> None:
        elem = self._elements.get(element_id)
        if elem is None:
            raise KeyError(f"Unknown foreshadow element: {element_id}")
        if new_state not in TRANSITIONS.get(elem.state, set()):
            valid = sorted(TRANSITIONS.get(elem.state, set()))
            raise ValueError(
                f"Cannot transition {element_id} from {elem.state} "
                f"to {new_state}. Valid: {valid}"
            )
        elem.state = new_state
        self._dirty = True

    def propose(self, element: ForeshadowElement) -> str:
        assert element.state == STATE_PROPOSED
        eid = element.id
        self._elements[eid] = element
        self._dirty = True
        return eid

    def plant(self, element_id: str, chapter: int | None = None) -> None:
        self._transition(element_id, STATE_PLANTED)
        self._elements[element_id].plant_chapter = chapter or self._chapter
        self._elements[element_id].state = STATE_PLANTED  # _transition already did this

    def mark_due(self, element_id: str) -> None:
        self._transition(element_id, STATE_DUE)

    def mark_overdue(self, element_id: str) -> None:
        self._transition(element_id, STATE_OVERDUE)
        self._elements[element_id].is_overdue = True

    def resolve(self, element_id: str) -> None:
        self._transition(element_id, STATE_RESOLVED)
        self._elements[element_id].resolve_chapter = self._chapter

    def partial_resolve(self, element_id: str) -> None:
        self._transition(element_id, STATE_PARTIAL)

    def abandon(self, element_id: str) -> None:
        self._transition(element_id, STATE_ABANDONED)

    def tick(self, chapter: int) -> None:
        """Advance the story clock. Promote *due* elements to *overdue* and mark upcoming elements as *due*."""
        self._chapter = chapter
        for elem in self._elements.values():
            if elem.state not in {STATE_PROPOSED, STATE_PLANTED, STATE_DUE}:
                continue
            if elem.resolve_chapter is not None:
                if chapter >= elem.resolve_chapter and elem.state == STATE_DUE:
                    elem.state = STATE_OVERDUE
                    elem.is_overdue = True
                    self._dirty = True
                elif chapter >= elem.resolve_chapter - elem.urgency - 1 and elem.state == STATE_PROPOSED:
                    # Proposed elements become due when we're close to their resolve chapter
                    elem.state = STATE_DUE
                    self._dirty = True
                elif chapter >= elem.resolve_chapter - 1 and elem.state == STATE_PLANTED:
                    elem.state = STATE_DUE
                    self._dirty = True

    # ── context building ────────────────────────────────────────

    def get_context_for_chapter(self, chapter: int) -> dict[str, Any]:
        """Build structured context for the draft prompt.

        Returns two lists:

        must_resolve
            Active (non-resolved) threads that are overdue or at their resolve window.
        upcoming
            Active threads that should be acknowledged but not forced.
        overdue
            Same as must_resolve but explicitly flagged.
        """
        self.tick(chapter)
        must_resolve = []
        upcoming = []
        overdue = []

        for elem in self._elements.values():
            if elem.state in {STATE_RESOLVED, STATE_PARTIAL, STATE_ABANDONED}:
                continue

            rc = elem.resolve_chapter
            if rc is not None and (chapter >= rc or elem.is_overdue):
                must_resolve.append(elem)
                if elem.is_overdue or chapter >= rc:
                    overdue.append(elem)
            elif rc is not None and rc - chapter <= elem.urgency + 1:
                upcoming.append(elem)
            elif rc is None and chapter - (elem.plant_chapter or chapter) > 5:
                # planted long ago without resolve target — flag gently
                upcoming.append(elem)

        return {
            "must_resolve": must_resolve,
            "upcoming": upcoming,
            "overdue": overdue,
            "chapter": chapter,
        }

    def format_context_for_prompt(self, chapter: int) -> str:
        """Return a natural-language string for the draft prompt."""
        ctx = self.get_context_for_chapter(chapter)

        parts = ["=== FORESHADOWING CONTEXT ==="]

        active_count = sum(
            1 for e in self._elements.values()
            if e.state not in {STATE_RESOLVED, STATE_ABANDONED}
        )
        if active_count == 0:
            parts.append("No active foreshadowing threads yet.")
            return "\n".join(parts)

        if ctx["overdue"]:
            parts.append("OVERDUE — these threads MUST resolve in this chapter:")
            for e in ctx["overdue"]:
                parts.append(
                    f"  [{e.id}] {e.description} "
                    f"(importance: {e.importance:.1f}, "
                    f"resolve-by: ch. {e.resolve_chapter})"
                )

        if ctx["must_resolve"]:
            parts.append("Must resolve soon:")
            for e in ctx["must_resolve"]:
                if e not in ctx.get("overdue", []):
                    parts.append(
                        f"  [{e.id}] {e.description} "
                        f"(resolve-by: ch. {e.resolve_chapter})"
                    )

        if ctx["upcoming"]:
            parts.append("Upcoming threads (acknowledge but don't force):")
            for e in ctx["upcoming"]:
                parts.append(f"  [{e.id}] {e.description}")

        parts.append("=== END FORESHADOWING ===")
        return "\n".join(parts)

    # ── auto-detection ──────────────────────────────────────────

    @staticmethod
    def scan_chapter_text(text: str) -> list[dict[str, Any]]:
        """Scan *text* for foreshadowing signal phrases and return raw hits."""
        hits = []
        for i, pattern in enumerate(SIGNAL_PATTERNS):
            for m in re.finditer(pattern, text):
                hits.append({
                    "match": m.group(0),
                    "span": m.span(),
                    "pattern_idx": i,
                })
        return hits

    def auto_propose_from_scan(
        self,
        chapter: int,
        hits: list[dict[str, Any]],
    ) -> list[str]:
        """Auto-create ForeshadowElements from detected signal hits.

        Returns list of proposed element ids.
        """
        created = []
        for hit in hits:
            eid = f"auto-{chapter}-{hit['span'][0]}-{hit['span'][1]}"
            if eid in self._elements:
                continue
            elem = ForeshadowElement(
                id=eid,
                description=hit["match"],
                state=STATE_PROPOSED,
                plant_chapter=chapter,
                importance=0.3,     # low confidence — auto-detected
                subtlety=0.7,
                resolve_chapter=chapter + 3,  # placeholder
                urgency=URGENCY_TIER_2,
                notes="Auto-detected from chapter text",
            )
            self._elements[eid] = elem
            self._dirty = True
            created.append(eid)
        return created

    # ── outline import ──────────────────────────────────────────

    def import_from_outline(
        self,
        outline_data: list[dict[str, Any]],
    ) -> int:
        """Import foreshadow entries from outline chapters.

        Expects each chapter dict to optionally have a 'foreshadowing' string
        or a 'foreshadows' list of dicts.
        Returns count of elements imported.
        """
        count = 0
        for chap_data in outline_data:
            chap_num = chap_data.get("chapter", 0)
            foreshadowing_raw = chap_data.get("foreshadowing", "") or ""

            if isinstance(foreshadowing_raw, str):
                if not foreshadowing_raw.strip():
                    continue
                for line in foreshadowing_raw.strip().split("\n"):
                    line = line.strip()
                    if not line:
                        continue
                    eid = f"outline-{chap_num}-{count}"
                    elem = ForeshadowElement(
                        id=eid,
                        description=line,
                        state=STATE_PROPOSED,
                        plant_chapter=chap_num,
                        resolve_chapter=chap_num + 3,
                        urgency=URGENCY_TIER_2,
                    )
                    self._elements[eid] = elem
                    count += 1
            elif isinstance(foreshadowing_raw, list):
                for item in foreshadowing_raw:
                    eid = f"outline-{chap_num}-{count}"
                    desc = item.get("description", str(item))
                    elem = ForeshadowElement(
                        id=eid,
                        description=desc,
                        state=item.get("state", STATE_PROPOSED),
                        plant_chapter=item.get("plant_chapter", chap_num),
                        resolve_chapter=item.get("resolve_chapter"),
                        importance=item.get("importance", 0.5),
                        urgency=item.get("urgency", URGENCY_TIER_2),
                        category=item.get("category", ""),
                        related_characters=item.get("related_characters", []),
                        subtlety=item.get("subtlety", 0.5),
                    )
                    self._elements[eid] = elem
                    count += 1

        if count:
            self._dirty = True
        return count

    # ── accessors ───────────────────────────────────────────────

    @property
    def elements(self) -> dict[str, ForeshadowElement]:
        return dict(self._elements)

    @property
    def active_count(self) -> int:
        return sum(
            1 for e in self._elements.values()
            if e.state not in {STATE_RESOLVED, STATE_ABANDONED}
        )

    def get(self, element_id: str) -> ForeshadowElement | None:
        return self._elements.get(element_id)

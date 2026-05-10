"""GBrain canonical state store — persistent structured memory for novels.

Wires GBrain (HTTP API, port 8888) as the canonical source of truth for:
- Character traits and evolution
- World facts and lore
- Plot threads and resolution status
- Foreshadowing obligations and payoff tracking
- Chapter-level canonical summaries

Each chapter draft queries GBrain for relevant state before writing,
then pushes updated state after writing.

Usage:
    from pipeline.gbrain_client import GBrainStore
    gbrain = GBrainStore(project_id="my-novel")
    gbrain.ensure_bank()
    char_state = gbrain.get_character_state("Maria")
    gbrain.record_chapter_complete(3, summary="...", word_count=4000)
"""

import json
import os
import time
from collections import defaultdict
from typing import Optional

import httpx


GBRAIN_BASE = os.environ.get("GBRAIN_URL", "http://localhost:8888")
GBRAIN_BANK_PREFIX = "storyforge-"


class GBrainStore:
    """Structured state store backed by GBrain memory banks.

    Uses one GBrain bank per novel project. Each bank stores:
    - entity memories for characters, locations, objects
    - semantic memories for plot threads, foreshadowing obligations
    - chapter summaries as factual memories with structured metadata
    """

    def __init__(
        self,
        project_id: str,
        base_url: str = GBRAIN_BASE,
        enabled: bool = True,
    ):
        self.project_id = project_id
        self.bank_id = f"{GBRAIN_BANK_PREFIX}{project_id}"
        self.base_url = base_url
        self.enabled = enabled
        self._http = httpx.Client(timeout=15.0)

    def close(self):
        self._http.close()

    # ── Bank Management ──────────────────────────────────────────────

    def ensure_bank(self) -> bool:
        """Create the bank if it doesn't exist. Returns True if created."""
        resp = self._http.get(f"{self.base_url}/v1/default/banks")
        if resp.status_code == 200:
            banks = resp.json().get("banks", [])
            if any(b["bank_id"] == self.bank_id for b in banks):
                return False
        payload = {
            "bank_id": self.bank_id,
            "name": f"StoryForge: {self.project_id}",
            "disposition": {"skepticism": 2, "literalism": 5, "empathy": 2},
            "mission": f"Canonical state store for novel: {self.project_id}",
        }
        resp = self._http.put(
            f"{self.base_url}/v1/default/banks/{self.bank_id}",
            content=json.dumps(payload),
            headers={"Content-Type": "application/json"},
        )
        return resp.status_code in (200, 201)

    def get_bank_stats(self) -> dict:
        """Get bank statistics."""
        resp = self._http.get(f"{self.base_url}/v1/default/banks/{self.bank_id}/stats")
        if resp.status_code == 200:
            return resp.json()
        return {}

    # ── Memory (Fact) Management ─────────────────────────────────────

    def store_memory(
        self,
        content: str,
        tags: Optional[list[str]] = None,
        importance: float = 0.5,
        metadata: Optional[dict] = None,
    ) -> bool:
        if not self.enabled:
            return False
        payload = {
            "content": content,
            "tags": tags or [],
            "importance": importance,
            "metadata": metadata or {},
        }
        resp = self._http.post(
            f"{self.base_url}/v1/default/banks/{self.bank_id}/memories",
            content=json.dumps(payload),
            headers={"Content-Type": "application/json"},
        )
        return resp.status_code in (200, 201)

    def recall(
        self,
        query: str,
        k: int = 5,
        min_score: float = 0.0,
        tag_filter: Optional[list[str]] = None,
    ) -> list[dict]:
        if not self.enabled:
            return []
        payload = {"query": query, "k": k, "min_score": min_score, "tag_filters": tag_filter or []}
        resp = self._http.post(
            f"{self.base_url}/v1/default/banks/{self.bank_id}/memories/recall",
            content=json.dumps(payload),
            headers={"Content-Type": "application/json"},
        )
        if resp.status_code == 200:
            return resp.json().get("results", [])
        return []

    # ── High-Level Novel State Methods ───────────────────────────────

    def ensure_bank_safe(self) -> bool:
        try:
            return self.ensure_bank()
        except Exception:
            return False

    def get_character_traits(self, character_name: str) -> list[dict]:
        return self.recall(f"character traits for {character_name}", k=10, tag_filter=["character_trait"])

    def get_world_facts(self) -> list[dict]:
        return self.recall("worldbuilding facts and lore", k=20, tag_filter=["world_fact"])

    def get_active_threads(self) -> list[dict]:
        return self.recall("unresolved plot threads", k=15, tag_filter=["plot_thread"], min_score=0.3)

    def get_foreshadowing_debts(self) -> list[dict]:
        return self.recall("unresolved foreshadowing obligations", k=15, tag_filter=["foreshadowing"], min_score=0.3)

    def get_chapter_summaries(self) -> list[dict]:
        return self.recall("chapter summary canonical", k=30, tag_filter=["chapter_summary"])

    def record_character_trait(self, character: str, trait_type: str, value: str, chapter: int, importance: float = 0.7):
        self.store_memory(
            content=f"Character '{character}' has {trait_type}: {value} (established Ch {chapter})",
            tags=["character_trait", trait_type, character.lower()],
            importance=importance,
            metadata={"character": character, "trait_type": trait_type, "value": value, "chapter": chapter, "entity_type": "character"},
        )

    def record_world_fact(self, location: str, fact: str, chapter: int, importance: float = 0.6):
        self.store_memory(
            content=f"World fact: {location} - {fact}",
            tags=["world_fact", location.lower()],
            importance=importance,
            metadata={"location": location, "fact": fact, "chapter": chapter, "entity_type": "world"},
        )

    def record_plot_thread(self, thread_name: str, status: str, introduced_chapter: int, resolved_chapter: Optional[int] = None, importance: float = 0.7):
        status_text = {
            "active": "active and unresolved",
            "resolved": f"resolved in Ch {resolved_chapter}",
            "abandoned": "abandoned (no resolution planned)",
        }.get(status, status)
        self.store_memory(
            content=f"Plot thread '{thread_name}': {status_text}",
            tags=["plot_thread", thread_name.lower(), status],
            importance=importance,
            metadata={"thread_name": thread_name, "status": status, "introduced_chapter": introduced_chapter, "resolved_chapter": resolved_chapter, "entity_type": "thread"},
        )

    def record_foreshadowing(self, element: str, plant_chapter: int, expected_payoff_chapter: Optional[int] = None, importance: float = 0.6):
        payoff_str = f" (expected payoff ~Ch {expected_payoff_chapter})" if expected_payoff_chapter else ""
        self.store_memory(
            content=f"Foreshadowing: '{element}' planted in Ch {plant_chapter}{payoff_str}",
            tags=["foreshadowing", "unpaid", element.lower()],
            importance=importance,
            metadata={"element": element, "plant_chapter": plant_chapter, "expected_payoff_chapter": expected_payoff_chapter, "status": "unpaid", "entity_type": "foreshadowing"},
        )

    def mark_foreshadowing_paid(self, element: str, payoff_chapter: int):
        self.store_memory(
            content=f"Foreshadowing PAID: '{element}' paid off in Ch {payoff_chapter}",
            tags=["foreshadowing", "paid", element.lower()],
            importance=0.5,
            metadata={"element": element, "payoff_chapter": payoff_chapter, "status": "paid", "entity_type": "foreshadowing"},
        )

    def record_chapter_summary(self, chapter: int, title: str, summary: str, pov: str, word_count: int, key_events: list[str]):
        self.store_memory(
            content=f"Chapter {chapter} ({title}): {summary[:500]}",
            tags=["chapter_summary", f"ch{chapter}"],
            importance=0.8,
            metadata={"chapter": chapter, "title": title, "pov": pov, "word_count": word_count, "key_events": key_events, "entity_type": "chapter"},
        )

    def format_context_for_drafting(self, chapter_num: int, chapter_summary: str) -> str:
        if not self.enabled:
            return self._format_empty_context()
        try:
            query = f"{chapter_summary} current story state before chapter {chapter_num}"
            char_facts = self.recall(f"character states before chapter {chapter_num}", k=8, tag_filter=["character_trait"])
            world_facts = self.recall(f"world building relevant to {chapter_summary[:100]}", k=5, tag_filter=["world_fact"])
            active_threads = self.recall("unresolved plot threads active", k=5, tag_filter=["plot_thread"])
            foreshadowing = self.recall("unpaid foreshadowing obligations", k=5, tag_filter=["foreshadowing"])
            prev_chapters = self.recall(f"recent chapter summaries before chapter {chapter_num}", k=3, tag_filter=["chapter_summary"])

            parts = ["[CANONICAL STATE FROM GBRAIN]", ""]
            if char_facts:
                parts.append("Character State:")
                for fact in char_facts[:6]:
                    parts.append(f"  - {fact.get('content', '')[:120]}")
                parts.append("")
            if world_facts:
                parts.append("World Context:")
                for fact in world_facts[:4]:
                    parts.append(f"  - {fact.get('content', '')[:120]}")
                parts.append("")
            if active_threads:
                parts.append("Active Plot Threads:")
                for t in active_threads:
                    parts.append(f"  - {t.get('content', '')[:120]}")
                parts.append("")
            if foreshadowing:
                parts.append("Foreshadowing Due:")
                for f in foreshadowing:
                    parts.append(f"  - {f.get('content', '')[:120]}")
                parts.append("")
            if prev_chapters:
                parts.append("Previous Chapter Context:")
                for pc in prev_chapters[:3]:
                    parts.append(f"  - {pc.get('content', '')[:150]}")
                parts.append("")
            parts.append("[/CANONICAL STATE]")
            return "\n".join(parts)
        except Exception:
            return self._format_empty_context()

    def _format_empty_context(self) -> str:
        return "[CANONICAL STATE: GBrain unavailable or disabled]\n"

    def update_after_chapter(self, chapter_num: int, title: str, summary: str, pov: str, word_count: int, key_events: list[str], character_states: Optional[dict[str, dict]] = None, world_facts: Optional[list[tuple[str, str]]] = None, threads: Optional[list[tuple[str, str, int]]] = None, foreshadowing_elements: Optional[list[tuple[str, int]]] = None):
        if not self.enabled:
            return
        try:
            self.record_chapter_summary(chapter=chapter_num, title=title, summary=summary, pov=pov, word_count=word_count, key_events=key_events)
            if character_states:
                for char_name, traits in character_states.items():
                    for trait_type, value in traits.items():
                        self.record_character_trait(character=char_name, trait_type=trait_type, value=value, chapter=chapter_num)
            if world_facts:
                for location, fact in world_facts:
                    self.record_world_fact(location, fact, chapter_num)
            if threads:
                for thread_name, status, resolved_ch in threads:
                    self.record_plot_thread(thread_name=thread_name, status=status, introduced_chapter=chapter_num, resolved_chapter=resolved_ch if status == "resolved" else None)
            if foreshadowing_elements:
                for element, expected_payoff in foreshadowing_elements:
                    self.record_foreshadowing(element=element, plant_chapter=chapter_num, expected_payoff_chapter=expected_payoff)
        except Exception:
            pass

    def scan_contradictions(self, character_name: str, trait_type: str, new_value: str, chapter_num: int) -> list[dict]:
        results = self.recall(f"{character_name} {trait_type} canonical state", k=5, tag_filter=["character_trait", trait_type, character_name.lower()])
        conflicts = []
        for r in results:
            content = r.get("content", "").lower()
            metadata = r.get("metadata", {})
            if new_value.lower() not in content and trait_type in content:
                conflicts.append(r)
        return conflicts

"""FileCanonicalStore -- filesystem-backed canonical state store for novels.

Replaces HindsightStore and GBrainStore with a zero-dependency implementation
that persists canonical novel state to a JSON file in the project directory.

No external services, no HTTP, no API keys.
"""

import json
import os
from typing import Optional


class FileCanonicalStore:
    """Filesystem-backed canonical state store."""

    def __init__(self, project_dir: str, enabled: bool = True):
        self.project_dir = project_dir
        self.enabled = enabled
        self._path = os.path.join(project_dir, "canonical_state.json")
        self._data = self._load()

    def _load(self) -> dict:
        if not self.enabled:
            return self._empty_state()
        try:
            with open(self._path) as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return self._empty_state()

    def _save(self):
        if not self.enabled:
            return
        os.makedirs(self.project_dir, exist_ok=True)
        with open(self._path, "w") as f:
            json.dump(self._data, f, indent=2)

    @staticmethod
    def _empty_state() -> dict:
        return {"character_traits": [], "world_facts": [], "plot_threads": [],
                "foreshadowing": [], "chapter_summaries": []}

    def _filter(self, key: str, tag_filter=None) -> list[dict]:
        entries = self._data.get(key, [])
        if not tag_filter:
            return list(entries)
        return [e for e in entries if any(t in e.get("tags", []) for t in tag_filter)]

    def close(self):
        pass

    def ensure_bank_safe(self) -> bool:
        return True

    def get_bank_stats(self) -> dict:
        return {}
    def store_memory(self, content: str, tags=None, importance: float = 0.5, metadata=None) -> bool:
        if not self.enabled:
            return False
        entry = {"content": content, "tags": tags or [], "importance": importance, "metadata": metadata or {}}
        if tags:
            tag_to_key = {
                "character_trait": "character_traits",
                "world_fact": "world_facts",
                "plot_thread": "plot_threads",
                "foreshadowing": "foreshadowing",
                "chapter_summary": "chapter_summaries",
            }
            for tag, key in tag_to_key.items():
                if tag in tags:
                    self._data.setdefault(key, []).append(entry)
                    self._save()
                    return True
        self._data.setdefault("general", []).append(entry)
        self._save()
        return True

    def recall(self, query: str, k: int = 5, min_score: float = 0.0, tag_filter=None) -> list[dict]:
        if not self.enabled:
            return []
        candidates = []
        for rk in ["character_traits", "world_facts", "plot_threads", "foreshadowing", "chapter_summaries", "general"]:
            candidates.extend(self._filter(rk, tag_filter))
        for c in candidates:
            c["score"] = c.get("score", 1.0 if tag_filter else 0.5)
        candidates.reverse()
        return candidates[:k]

    def get_character_traits(self, character_name: str) -> list[dict]:
        return self._filter("character_traits", tag_filter=[character_name.lower()])

    def get_world_facts(self) -> list[dict]:
        return self._filter("world_facts")

    def get_active_threads(self) -> list[dict]:
        return [t for t in self._filter("plot_threads") if "active" in t.get("content", "").lower()]

    def get_foreshadowing_debts(self) -> list[dict]:
        return [f for f in self._filter("foreshadowing") if "unpaid" in f.get("content", "").lower()]

    def get_chapter_summaries(self) -> list[dict]:
        return self._filter("chapter_summaries")
    def record_character_trait(self, character: str, trait_type: str, value: str, chapter: int, importance: float = 0.7):
        self.store_memory(
            content=f"Character '{character}' has {trait_type}: {value} (established Ch {chapter})",
            tags=["character_trait", trait_type, character.lower()], importance=importance,
            metadata={"character": character, "trait_type": trait_type, "value": value, "chapter": chapter, "entity_type": "character"})

    def record_world_fact(self, location: str, fact: str, chapter: int, importance: float = 0.6):
        self.store_memory(
            content=f"World fact: {location} - {fact}",
            tags=["world_fact", location.lower()], importance=importance,
            metadata={"location": location, "fact": fact, "chapter": chapter, "entity_type": "world"})

    def record_plot_thread(self, thread_name: str, status: str, introduced_chapter: int, resolved_chapter: Optional[int] = None, importance: float = 0.7):
        st_map = {"active": "active and unresolved", "resolved": f"resolved in Ch {resolved_chapter}", "abandoned": "abandoned (no resolution planned)"}
        self.store_memory(
            content=f"Plot thread '{thread_name}': {st_map.get(status, status)}",
            tags=["plot_thread", thread_name.lower(), status], importance=importance,
            metadata={"thread_name": thread_name, "status": status, "introduced_chapter": introduced_chapter, "resolved_chapter": resolved_chapter, "entity_type": "thread"})

    def record_foreshadowing(self, element: str, plant_chapter: int, expected_payoff_chapter: Optional[int] = None, importance: float = 0.6):
        ps = f" (expected payoff ~Ch {expected_payoff_chapter})" if expected_payoff_chapter else ""
        self.store_memory(
            content=f"Foreshadowing: '{element}' planted in Ch {plant_chapter}{ps}",
            tags=["foreshadowing", "unpaid", element.lower()], importance=importance,
            metadata={"element": element, "plant_chapter": plant_chapter, "expected_payoff_chapter": expected_payoff_chapter, "status": "unpaid", "entity_type": "foreshadowing"})

    def mark_foreshadowing_paid(self, element: str, payoff_chapter: int):
        self.store_memory(
            content=f"Foreshadowing PAID: '{element}' paid off in Ch {payoff_chapter}",
            tags=["foreshadowing", "paid", element.lower()], importance=0.5,
            metadata={"element": element, "payoff_chapter": payoff_chapter, "status": "paid", "entity_type": "foreshadowing"})

    def record_chapter_summary(self, chapter: int, title: str, summary: str, pov: str, word_count: int, key_events: list):
        self.store_memory(
            content=f"Chapter {chapter} ({title}): {summary[:500]}",
            tags=["chapter_summary", f"ch{chapter}"], importance=0.8,
            metadata={"chapter": chapter, "title": title, "pov": pov, "word_count": word_count, "key_events": key_events, "entity_type": "chapter"})
    def format_context_for_drafting(self, chapter_num: int, chapter_summary: str) -> str:
        if not self.enabled:
            return self._format_empty_context()
        cf = self.recall("character state", k=8, tag_filter=["character_trait"])
        wf = self.recall("world", k=5, tag_filter=["world_fact"])
        at = self.recall("plot threads", k=5, tag_filter=["plot_thread"])
        fs = self.recall("foreshadowing", k=5, tag_filter=["foreshadowing"])
        pc = self.recall("chapter summary", k=3, tag_filter=["chapter_summary"])
        parts = ["[CANONICAL STATE FROM STOREFORGE]", ""]
        if cf:
            parts.append("Character State:")
            for f in cf[:6]:
                parts.append("  - " + f.get("content", "")[:120])
            parts.append("")
        if wf:
            parts.append("World Context:")
            for f in wf[:4]:
                parts.append("  - " + f.get("content", "")[:120])
            parts.append("")
        if at:
            parts.append("Active Plot Threads:")
            for t in at:
                parts.append("  - " + t.get("content", "")[:120])
            parts.append("")
        if fs:
            parts.append("Foreshadowing Due:")
            for fx in fs:
                parts.append("  - " + fx.get("content", "")[:120])
            parts.append("")
        if pc:
            parts.append("Previous Chapter Context:")
            for p in pc[:3]:
                parts.append("  - " + p.get("content", "")[:150])
            parts.append("")
        parts.append("[/CANONICAL STATE]")
        return "\n".join(parts)

    def _format_empty_context(self) -> str:
        return "[CANONICAL STATE: StoreForge canonical state unavailable or disabled]\n"

    def update_after_chapter(self, chapter_num: int, title: str, summary: str, pov: str, word_count: int, key_events: list, character_states: Optional[dict] = None, world_facts: Optional[list] = None, threads: Optional[list] = None, foreshadowing_elements: Optional[list] = None):
        if not self.enabled:
            return
        self.record_chapter_summary(chapter=chapter_num, title=title, summary=summary, pov=pov, word_count=word_count, key_events=key_events)
        if character_states:
            for cn, tr in character_states.items():
                for tt, v in tr.items():
                    self.record_character_trait(character=cn, trait_type=tt, value=v, chapter=chapter_num)
        if world_facts:
            for loc, fact in world_facts:
                self.record_world_fact(loc, fact, chapter_num)
        if threads:
            for tn, st, rc in threads:
                self.record_plot_thread(thread_name=tn, status=st, introduced_chapter=chapter_num, resolved_chapter=rc if st == "resolved" else None)
        if foreshadowing_elements:
            for el, ep in foreshadowing_elements:
                self.record_foreshadowing(element=el, plant_chapter=chapter_num, expected_payoff_chapter=ep)

    def scan_contradictions(self, character_name: str, trait_type: str, new_value: str, chapter_num: int) -> list[dict]:
        r = self.recall(f"{character_name} {trait_type}", k=5, tag_filter=["character_trait", trait_type, character_name.lower()])
        return [x for x in r if new_value.lower() not in x.get("content", "").lower() and trait_type in x.get("content", "").lower()]
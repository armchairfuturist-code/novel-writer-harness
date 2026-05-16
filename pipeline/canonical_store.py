"""CanonicalStore -- abstract interface for novel canonical state, with
file-backed and HTTP-backed implementations.

CanonicalStore defines the contract for storing and recalling canonical
novel state (character traits, world facts, plot threads, foreshadowing,
chapter summaries) during the drafting pipeline.

Implementations:
- FileCanonicalStore: Zero-dependency filesystem-backed store using JSON.
- HindsightStore, GBrainStore: HTTP-backed stores (in hindsight_client.py,
  gbrain_client.py) that can be adapted to this interface.

Usage:
    from pipeline.canonical_store import create_canonical_store

    store = create_canonical_store("file", project_dir="/tmp/my-novel")
    store.record_character_trait("Maria", "eye_color", "blue", chapter=1)
    context = store.format_context_for_drafting(chapter_num=2, chapter_summary=...)
"""

import json
import os
import re
from abc import ABC, abstractmethod
from typing import Any, Optional

class CanonicalStore(ABC):
    """Abstract canonical state store for novel drafting.

    All methods accept the same signatures regardless of backend.
    The default implementation is FileCanonicalStore (zero dependencies).
    """

    @abstractmethod
    def store_memory(self, content: str, tags=None, importance=0.5, metadata=None) -> bool:
        ...

    @abstractmethod
    def recall(self, query: str, k: int = 5, min_score=0.0, tag_filter=None) -> list[dict]:
        ...

    @abstractmethod
    def format_context_for_drafting(self, chapter_num: int, chapter_summary: str) -> str:
        ...

    @abstractmethod
    def update_after_chapter(self, chapter_num: int, title: str, summary: str, pov: str, word_count: int, key_events: list):
        ...

    @abstractmethod
    def close(self):
        ...

    @abstractmethod
    def get_character_traits(self, character_name: str) -> list[dict]:
        ...

    @abstractmethod
    def get_world_facts(self) -> list[dict]:
        ...

    @abstractmethod
    def get_active_threads(self) -> list[dict]:
        ...

    @abstractmethod
    def get_foreshadowing_debts(self) -> list[dict]:
        ...

    @abstractmethod
    def get_chapter_summaries(self) -> list[dict]:
        ...

    @abstractmethod
    def record_character_trait(self, character: str, trait_type: str, value: str, chapter: int, importance: float = 0.7):
        ...

    @abstractmethod
    def record_world_fact(self, location: str, fact: str, chapter: int, importance: float = 0.6):
        ...

    @abstractmethod
    def record_plot_thread(self, thread_name: str, status: str, introduced_chapter: int, resolved_chapter=None, importance: float = 0.7):
        ...

    @abstractmethod
    def record_foreshadowing(self, element: str, plant_chapter: int, expected_payoff_chapter=None, importance: float = 0.6):
        ...

    @abstractmethod
    def mark_foreshadowing_paid(self, element: str, payoff_chapter: int):
        ...

    @abstractmethod
    def record_chapter_summary(self, chapter: int, title: str, summary: str, pov: str, word_count: int, key_events: list):
        ...

    @abstractmethod
    def scan_contradictions(self, character_name: str, trait_type: str, new_value: str, chapter_num: int) -> list[dict]:
        ...

    @abstractmethod
    def ensure_bank_safe(self) -> bool:
        ...



# --- Tag-to-key mapping --------------------------------------------

_TAG_TO_KEY = {
    "character_trait": "character_traits",
    "world_fact": "world_facts",
    "plot_thread": "plot_threads",
    "foreshadowing": "foreshadowing",
    "chapter_summary": "chapter_summaries",
}


def _tokenise(text: str) -> set[str]:
    return set(re.findall(r"[a-zA-Z0-9]+", text.lower()))


def _word_overlap_score(query: str, content: str) -> float:
    """Fraction of query tokens present in content tokens (0..1)."""
    q_tokens = _tokenise(query)
    c_tokens = _tokenise(content)
    if not q_tokens or not c_tokens:
        return 0.0
    return len(q_tokens & c_tokens) / len(q_tokens)


class FileCanonicalStore(CanonicalStore):
    """Filesystem-backed canonical state store.

    Persists all canonical state to ``canonical_state.json`` in the
    project directory.  Zero dependencies beyond stdlib.

    Recall uses word-overlap scoring against the query string, so
    results are ranked by relevance rather than returned in insertion
    order with fabricated scores.
    """

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
        return {
            "character_traits": [], "world_facts": [], "plot_threads": [],
            "foreshadowing": [], "chapter_summaries": [],
        }

    def _filter(self, key: str, tag_filter=None) -> list[dict]:
        entries = self._data.get(key, [])
        if not tag_filter:
            return list(entries)
        return [
            e for e in entries
            if any(t in e.get("tags", []) for t in tag_filter)
        ]

    # --- Core ABC Methods --------------------------------------------------

    def store_memory(
        self, content: str, tags=None, importance: float = 0.5, metadata=None,
    ) -> bool:
        if not self.enabled:
            return False
        entry = {
            "content": content, "tags": tags or [], "importance": importance,
            "metadata": metadata or {},
        }
        if tags:
            for tag, key in _TAG_TO_KEY.items():
                if tag in tags:
                    self._data.setdefault(key, []).append(entry)
                    self._save()
                    return True
        self._data.setdefault("general", []).append(entry)
        self._save()
        return True

    def recall(
        self, query: str, k: int = 5, min_score: float = 0.0,
        tag_filter=None,
    ) -> list[dict]:
        if not self.enabled:
            return []

        candidates = []
        for rk in _TAG_TO_KEY.values():
            candidates.extend(self._filter(rk, tag_filter))

        if not candidates:
            return []

        scored = []
        for c in candidates:
            score = _word_overlap_score(query, c.get("content", ""))
            c["score"] = score
            if score >= min_score:
                scored.append(c)

        scored.sort(key=lambda x: x["score"], reverse=True)
        return scored[:k]

    def format_context_for_drafting(
        self, chapter_num: int, chapter_summary: str,
    ) -> str:
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

    def update_after_chapter(
        self, chapter_num: int, title: str, summary: str, pov: str,
        word_count: int, key_events: list,
        character_states=None, world_facts=None,
        threads=None, foreshadowing_elements=None,
    ):
        if not self.enabled:
            return
        self.record_chapter_summary(
            chapter=chapter_num, title=title, summary=summary,
            pov=pov, word_count=word_count, key_events=key_events,
        )
        if character_states:
            for cn, tr in character_states.items():
                for tt, v in tr.items():
                    self.record_character_trait(
                        character=cn, trait_type=tt, value=v, chapter=chapter_num,
                    )
        if world_facts:
            for loc, fact in world_facts:
                self.record_world_fact(loc, fact, chapter_num)
        if threads:
            for tn, st, rc in threads:
                self.record_plot_thread(
                    thread_name=tn, status=st,
                    introduced_chapter=chapter_num,
                    resolved_chapter=rc if st == "resolved" else None,
                )
        if foreshadowing_elements:
            for el, ep in foreshadowing_elements:
                self.record_foreshadowing(
                    element=el, plant_chapter=chapter_num,
                    expected_payoff_chapter=ep,
                )

    def close(self):
        pass

    def ensure_bank_safe(self) -> bool:
        return True

    def get_bank_stats(self) -> dict:
        return {}

    # --- High-Level Query Methods -----------------------------------------

    def get_character_traits(self, character_name: str) -> list[dict]:
        return self._filter("character_traits", tag_filter=[character_name.lower()])

    def get_world_facts(self) -> list[dict]:
        return self._filter("world_facts")

    def get_active_threads(self) -> list[dict]:
        return [
            t for t in self._filter("plot_threads")
            if "active" in t.get("content", "").lower()
        ]

    def get_foreshadowing_debts(self) -> list[dict]:
        return [
            f for f in self._filter("foreshadowing")
            if "unpaid" in f.get("content", "").lower()
        ]

    def get_chapter_summaries(self) -> list[dict]:
        return self._filter("chapter_summaries")

    # --- High-Level Record Methods ----------------------------------------

    def record_character_trait(
        self, character: str, trait_type: str, value: str,
        chapter: int, importance: float = 0.7,
    ):
        content = f"Character " + chr(39) + f"{character}" + chr(39) + f" has {trait_type}: {value} (established Ch {chapter})"
        self.store_memory(
            content=content,
            tags=["character_trait", trait_type, character.lower()],
            importance=importance,
            metadata={"character": character, "trait_type": trait_type,
                      "value": value, "chapter": chapter, "entity_type": "character"},
        )

    def record_world_fact(
        self, location: str, fact: str, chapter: int, importance: float = 0.6,
    ):
        self.store_memory(
            content=f"World fact: {location} - {fact}",
            tags=["world_fact", location.lower()],
            importance=importance,
            metadata={"location": location, "fact": fact,
                      "chapter": chapter, "entity_type": "world"},
        )

    def record_plot_thread(
        self, thread_name: str, status: str, introduced_chapter: int,
        resolved_chapter=None, importance: float = 0.7,
    ):
        st_map = {
            "active": "active and unresolved",
            "resolved": f"resolved in Ch {resolved_chapter}",
            "abandoned": "abandoned (no resolution planned)",
        }
        content = f"Plot thread " + chr(39) + f"{thread_name}" + chr(39) + f": {st_map.get(status, status)}"
        self.store_memory(
            content=content,
            tags=["plot_thread", thread_name.lower(), status],
            importance=importance,
            metadata={"thread_name": thread_name, "status": status,
                      "introduced_chapter": introduced_chapter,
                      "resolved_chapter": resolved_chapter, "entity_type": "thread"},
        )

    def record_foreshadowing(
        self, element: str, plant_chapter: int,
        expected_payoff_chapter=None, importance: float = 0.6,
    ):
        ps = (
            f" (expected payoff ~Ch {expected_payoff_chapter})"
            if expected_payoff_chapter else ""
        )
        content = f"Foreshadowing: " + chr(39) + f"{element}" + chr(39) + f" planted in Ch {plant_chapter}{ps}"
        self.store_memory(
            content=content,
            tags=["foreshadowing", "unpaid", element.lower()],
            importance=importance,
            metadata={"element": element, "plant_chapter": plant_chapter,
                      "expected_payoff_chapter": expected_payoff_chapter,
                      "status": "unpaid", "entity_type": "foreshadowing"},
        )

    def mark_foreshadowing_paid(self, element: str, payoff_chapter: int):
        content = f"Foreshadowing PAID: " + chr(39) + f"{element}" + chr(39) + f" paid off in Ch {payoff_chapter}"
        self.store_memory(
            content=content,
            tags=["foreshadowing", "paid", element.lower()],
            importance=0.5,
            metadata={"element": element, "payoff_chapter": payoff_chapter,
                      "status": "paid", "entity_type": "foreshadowing"},
        )

    def record_chapter_summary(
        self, chapter: int, title: str, summary: str, pov: str,
        word_count: int, key_events: list,
    ):
        self.store_memory(
            content=f"Chapter {chapter} ({title}): {summary[:500]}",
            tags=["chapter_summary", f"ch{chapter}"],
            importance=0.8,
            metadata={"chapter": chapter, "title": title, "pov": pov,
                      "word_count": word_count, "key_events": key_events,
                      "entity_type": "chapter"},
        )

    def scan_contradictions(
        self, character_name: str, trait_type: str,
        new_value: str, chapter_num: int,
    ) -> list[dict]:
        r = self.recall(
            f"{character_name} {trait_type}", k=5,
            tag_filter=["character_trait", trait_type, character_name.lower()],
        )
        return [
            x for x in r
            if new_value.lower() not in x.get("content", "").lower()
            and trait_type in x.get("content", "").lower()
        ]



# --- Factory --------------------------------------------------------------


def _import_custom_store(dotted_path: str):
    """Import a CanonicalStore subclass from a dotted module path.

    Example: myplugin.store.MyStore imports myplugin.store and
    returns MyStore (the class, not an instance).
    """
    import importlib
    parts = dotted_path.split(".")
    module_path = ".".join(parts[:-1])
    class_name = parts[-1]
    module = importlib.import_module(module_path)
    cls = getattr(module, class_name)
    if not isinstance(cls, type) or not issubclass(cls, CanonicalStore):
        raise TypeError(
            f"{dotted_path} must be a CanonicalStore subclass, got {cls}"
        )
    return cls


def create_canonical_store(
    backend: str = "", project_dir: str = "", enabled: bool = True,
) -> CanonicalStore:
    """Factory: return a CanonicalStore implementation.

    Args:
        backend:
            file (default, zero-dependency JSON store).
            Empty string checks the STORYFORGE_CANONICAL_STORE env var.
        project_dir: Project root directory.
        enabled: Whether the store is active.

    Custom backends:
        Set STORYFORGE_CANONICAL_STORE to a dotted path to your
        CanonicalStore subclass, e.g.::

            STORYFORGE_CANONICAL_STORE=myplugin.store.MyStore

        Optionally pass JSON config via STORYFORGE_STORE_CONFIG,
        accessible via os.environ["STORYFORGE_STORE_CONFIG"] in
        your __init__.

    Returns:
        An initialised CanonicalStore instance.
    """
    # Resolve backend: explicit arg > env var > "file"
    if not backend:
        backend = os.environ.get("STORYFORGE_CANONICAL_STORE", "file")

    norm = backend.strip().lower()
    if norm == "file" or not norm:
        return FileCanonicalStore(project_dir=project_dir, enabled=enabled)

    # Custom dotted-path backend (e.g. "myplugin.store.MyStore")
    if "." in backend:
        cls = _import_custom_store(backend)
        store_config_raw = os.environ.get("STORYFORGE_STORE_CONFIG", "")
        store_config = json.loads(store_config_raw) if store_config_raw else {}
        return cls(
            project_dir=project_dir, enabled=enabled, **store_config,
        )

    msg = (
        f"Unknown canonical store backend {backend!r}. "
        f"Use 'file' for the stdlib file-backed store, or set "
        f"STORYFORGE_CANONICAL_STORE to a dotted path to your "
        f"CanonicalStore subclass."
    )
    raise ValueError(msg)
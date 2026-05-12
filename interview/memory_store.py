"""Pluggable MemoryStore interface — abstract base + JSON file-backed implementation.

Provides:
- MemoryStore: Abstract base class defining the store/recall/format_context/close contract.
- JSONMemoryStore: Concrete implementation using only stdlib (json, os, pathlib, re, datetime).
  Persists memories in a flat JSON array at ``<project_dir>/storyforge-memory.json``.
- create_memory_store(): Factory function that returns a MemoryStore by type name.

Usage:
    store = create_memory_store("json", project_dir="/tmp/my-project")
    store.store("char-maria", "Maria is a stoic botanist", tags=["character"])
    results = store.recall("maria", k=5, tag_filter=["character"])
    context = store.format_context("maria", max_items=3)
    store.close()
"""

import json
import os
import re
import time
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional


# ── Abstract Interface ──────────────────────────────────────────────


class MemoryStore(ABC):
    """Pluggable memory persistence interface for StoryForge interview context."""

    @abstractmethod
    def store(
        self,
        key: str,
        value: str,
        tags: Optional[list[str]] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> str:
        """Persist a memory entry.

        Args:
            key: Unique or semantic identifier (e.g. ``'char-maria'``).
            value: Free-text content to remember.
            tags: Optional list of string tags for filtering.
            metadata: Optional dict of arbitrary structured metadata.

        Returns:
            The memory ID assigned to the stored entry.
        """
        ...

    @abstractmethod
    def recall(
        self,
        query: str,
        k: int = 5,
        tag_filter: Optional[list[str]] = None,
    ) -> list[dict[str, Any]]:
        """Retrieve memories relevant to *query*, ranked by relevance.

        Args:
            query: Natural-language query string.
            k: Maximum number of results to return.
            tag_filter: If provided, only return memories whose tags
                        intersect with this list.

        Returns:
            List of memory dicts, each containing at minimum
            ``id``, ``key``, ``value``, ``tags``, ``metadata``, ``timestamp``,
            and a ``score`` field reflecting relevance to the query.
        """
        ...

    @abstractmethod
    def format_context(self, query: str, max_items: int = 5) -> str:
        """Return a formatted context block suitable for LLM system prompts.

        Args:
            query: Natural-language query to select relevant memories.
            max_items: Maximum number of memories to include.

        Returns:
            A string formatted as a ``[CONTEXT FROM MEMORY STORE]`` block,
            or an empty-block placeholder when no memories match.
        """
        ...

    @abstractmethod
    def close(self) -> None:
        """Release any resources held by the store (files, connections, etc.)."""
        ...


# ── JSON File-Backed Implementation ─────────────────────────────────


_STORE_FILENAME = "storyforge-memory.json"


def _parse_tags(tags: Any) -> list[str]:
    """Normalise *tags* to a sorted list of lower-case strings."""
    if not tags:
        return []
    return sorted({str(t).strip().lower() for t in tags if t})


def _tokenise(text: str) -> set[str]:
    """Split *text* into lower-cased alphanumeric tokens."""
    return set(re.findall(r"[a-zA-Z0-9]+", text.lower()))


def _word_overlap_score(query: str, value: str) -> float:
    """Fraction of query tokens present in *value* tokens (0..1).

    Returns 0 if either side has no tokens.
    """
    q_tokens = _tokenise(query)
    v_tokens = _tokenise(value)
    if not q_tokens or not v_tokens:
        return 0.0
    return len(q_tokens & v_tokens) / len(q_tokens)


class JSONMemoryStore(MemoryStore):
    """Flat JSON-file store using only stdlib.

    Data format (``storyforge-memory.json``):
    .. code-block:: json
        :caption: storyforge-memory.json

        [
            {
                "id": "1714521600_00000001",
                "key": "char-maria",
                "value": "Maria is a stoic botanist",
                "tags": ["character"],
                "metadata": {},
                "timestamp": "2024-01-01T00:00:00+00:00"
            }
        ]

    Thread-safety: not guaranteed. Intended for single-process use.
    """

    def __init__(self, project_dir: str | os.PathLike) -> None:
        self._project_dir = Path(project_dir)
        self._project_dir.mkdir(parents=True, exist_ok=True)
        self._path: Path = self._project_dir / _STORE_FILENAME
        self._memories: list[dict[str, Any]] = []
        self._counter: int = 0
        self._dirty: bool = False
        self._load()

    # ── Public API ───────────────────────────────────────────────────

    def store(
        self,
        key: str,
        value: str,
        tags: Optional[list[str]] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> str:
        self._counter += 1
        now = datetime.now(timezone.utc).isoformat()
        memory: dict[str, Any] = {
            "id": f"{int(time.time())}_{self._counter:08d}",
            "key": key,
            "value": value,
            "tags": _parse_tags(tags),
            "metadata": metadata or {},
            "timestamp": now,
        }
        self._memories.append(memory)
        self._dirty = True
        self._flush()
        return memory["id"]

    def recall(
        self,
        query: str,
        k: int = 5,
        tag_filter: Optional[list[str]] = None,
    ) -> list[dict[str, Any]]:
        if not self._memories:
            return []

        # Tag pre-filter
        filtered = self._memories
        if tag_filter:
            norm_filter = {t.strip().lower() for t in tag_filter if t}
            if norm_filter:
                filtered = [
                    m for m in self._memories
                    if set(m.get("tags", [])) & norm_filter
                ]

        # Score and sort
        scored = []
        for m in filtered:
            score = _word_overlap_score(query, m.get("value", ""))
            if score > 0:
                entry = dict(m)
                entry["score"] = score
                scored.append(entry)

        scored.sort(key=lambda x: x["score"], reverse=True)
        return scored[:k]

    def format_context(self, query: str, max_items: int = 5) -> str:
        results = self.recall(query, k=max_items)
        if not results:
            return "[CONTEXT FROM MEMORY STORE: no relevant memories found]"

        lines = ["[CONTEXT FROM MEMORY STORE]", ""]
        for i, m in enumerate(results, 1):
            tags_str = ", ".join(m.get("tags", [])) or "(untagged)"
            lines.append(f"{i}. [{m['key']}] ({tags_str})")
            lines.append(f"   {m['value'][:200]}")
            lines.append("")
        lines.append("[/CONTEXT FROM MEMORY STORE]")
        return "\n".join(lines)

    def close(self) -> None:
        self._flush()

    # ── Internal helpers ─────────────────────────────────────────────

    def _load(self) -> None:
        """Load existing memories from disk, if the file exists."""
        if self._path.exists():
            try:
                data = json.loads(self._path.read_text(encoding="utf-8"))
                if isinstance(data, list):
                    self._memories = data
                    # Revive counter from last entry id
                    for m in self._memories:
                        mid = m.get("id", "")
                        if "_" in mid:
                            try:
                                seq = int(mid.split("_")[1])
                                if seq > self._counter:
                                    self._counter = seq
                            except (ValueError, IndexError):
                                pass
            except (json.JSONDecodeError, OSError):
                self._memories = []

    def _flush(self) -> None:
        """Write in-memory data to disk."""
        if not self._dirty:
            return
        try:
            self._path.write_text(
                json.dumps(self._memories, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            self._dirty = False
        except OSError:
            pass  # Best-effort persistence


# ── Factory ─────────────────────────────────────────────────────────


def create_memory_store(
    store_type: str,
    project_dir: str | os.PathLike,
) -> MemoryStore:
    """Factory: return a MemoryStore implementation by type name.

    Args:
        store_type: ``'json'``, ``'gbrain'``, or ``'auto'``.
        project_dir: Project root directory (used for file-backed stores).

    Returns:
        An initialised MemoryStore instance.

    Raises:
        NotImplementedError: For ``'gbrain'`` and ``'auto'`` (reserved for T03).
    """
    norm = store_type.strip().lower()
    if norm == "json":
        return JSONMemoryStore(project_dir=project_dir)
    msg = (
        f"Memory store type {store_type!r} is not implemented. "
        f"Use 'json' for the stdlib file-backed store."
    )
    raise NotImplementedError(msg)

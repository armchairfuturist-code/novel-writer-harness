"""Revision memory: defects found, fixes applied, and what to avoid next time.

A chapter fixed in chapter 3 must not re-introduce the same defect in
chapter 20. This module keeps an append-only record of per-chapter prose
violations (the deterministic instrument's output) and surfaces the
recurring ones at drafting time, so context compounds across the book
instead of truncating at the context window.

Stdlib only; no model calls; appends one JSON line per chapter to
<project_dir>/quality/revision-memory.jsonl.
"""

from __future__ import annotations

import json
import os
from collections import Counter
from datetime import datetime, timezone
from typing import Optional


class RevisionMemory:
    """Append-only history of per-chapter prose defects."""

    def __init__(self, project_dir: str):
        self.path = os.path.join(project_dir, "quality", "revision-memory.jsonl")
        os.makedirs(os.path.dirname(self.path), exist_ok=True)

    def record(self, chapter_num: int, violations: list[str]) -> None:
        """Record the prose defects found in one chapter's final text."""
        entry = {
            "chapter": chapter_num,
            "utc": datetime.now(timezone.utc).isoformat(),
            "violations": violations,
        }
        with open(self.path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry) + "\n")

    def history(self) -> list[dict]:
        if not os.path.exists(self.path):
            return []
        with open(self.path, encoding="utf-8") as fh:
            return [json.loads(line) for line in fh if line.strip()]

    def top_recurring(self, n: int = 5) -> list[tuple[str, int]]:
        """Most frequent defect rules across chapters, most recent first."""
        counts: Counter[str] = Counter()
        chapters_seen: dict[str, int] = {}
        for entry in self.history():
            for rule in entry.get("violations", []):
                counts[rule] += 1
                chapters_seen[rule] = entry["chapter"]
        return sorted(
            counts.items(), key=lambda kv: (-kv[1], -chapters_seen[kv[0]])
        )[:n]

    def prompt_lines(self, n: int = 5) -> list[str]:
        """Lines to inject into a drafting prompt for later chapters."""
        lines = []
        top = self.top_recurring(n)
        if not top:
            return lines
        lines.append("")
        lines.append("Recurring issues flagged in earlier chapters - do not repeat them:")
        for rule, count in top:
            lines.append(f"- {rule}: appeared in {count} previous chapter(s).")
        lines.append("")
        return lines

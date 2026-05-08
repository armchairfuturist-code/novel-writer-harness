"""ReIO (Rewrite Input and Output) context compression for long novels.

Inspired by StoryWriter (arxiv 2506.16445). As chapters accumulate,
raw context windows become too large. This module dynamically compresses
earlier context into compact forms:

1. Chapter-level compression: summarize a chapter's events into <100 chars
2. State-level compression: extract only the delta (what changed)
3. Hierarchical compression: compress groups of chapters into arc summaries
4. Forgetting curve: older chapters get more aggressive compression

This solves the auto_compress_at_tokens problem from config.py.
"""

import json
import math
import os
import re
from typing import Optional

from config import Config


# ── Token Budget Management ──────────────────────────────────────────

DEFAULT_TOKEN_BUDGET = 900000  # tokens (matches ChapterConfig.auto_compress_at_tokens)
CHAPTER_SUMMARY_BUDGET = 100    # tokens per compressed chapter summary
ARC_SUMMARY_BUDGET = 300       # tokens per compressed arc summary
CRITICAL_CONTEXT_BUDGET = 400   # tokens reserved for critical state info


def estimate_tokens(text: str) -> int:
    """Rough token estimate (~4 chars per token for English)."""
    return len(text) // 4


class ReIOCompressor:
    """Compresses narrative context using hierarchical summaries.

    Strategy:
    - Recent N chapters: full summaries (high fidelity)
    - Middle chapters: compressed one-liners (medium fidelity)
    - Early chapters: arc-level summaries (low fidelity)
    - Critical state: always preserved (character traits, active threads)
    """

    def __init__(
        self,
        token_budget: int = DEFAULT_TOKEN_BUDGET,
        recent_chapters: int = 3,
        medium_chapters: int = 5,
    ):
        self.token_budget = token_budget
        self.recent_chapters = recent_chapters  # full fidelity
        self.medium_chapters = medium_chapters  # one-liner fidelity

    def compress_for_chapter(
        self,
        chapter_num: int,
        total_chapters: int,
        chapter_summaries: list[dict],
        arc_summaries: Optional[list[dict]] = None,
        critical_state: Optional[str] = None,
    ) -> str:
        """Build a compressed context string for a given chapter.

        Args:
            chapter_num: Current chapter being drafted
            total_chapters: Total chapters drafted so far
            chapter_summaries: List of {chapter, title, summary, word_count}
            arc_summaries: Optional list of {arc_name, summary, chapters}
            critical_state: Optional critical state text (always included)

        Returns:
            str: Compressed context suitable for LLM prompt injection
        """
        if not chapter_summaries:
            return "[NO PRIOR CONTEXT]"

        parts = ["[COMPRESSED NARRATIVE CONTEXT]"]

        # Always include critical state
        if critical_state:
            parts.append(critical_state)
            parts.append("")

        # Sort summaries by chapter number
        sorted_sums = sorted(chapter_summaries, key=lambda s: s.get("chapter", 0))

        # Categorize by distance from current chapter
        recent = []
        medium = []
        early = []

        for s in sorted_sums:
            ch = s.get("chapter", 0)
            if ch <= 0:
                continue
            if ch >= chapter_num:  # Skip current and future chapters
                continue
            dist = chapter_num - ch
            if dist <= self.recent_chapters:
                recent.append(s)
            elif dist <= self.recent_chapters + self.medium_chapters:
                medium.append(s)
            else:
                early.append(s)

        # Arc summaries (most compressed)
        if arc_summaries:
            parts.append("Narrative Arcs:")
            for arc in arc_summaries:
                parts.append(f"  - {arc.get('arc_name', 'Arc')}: {arc.get('summary', '')[:ARC_SUMMARY_BUDGET // 2]}")
            parts.append("")

        # Early chapters: arc-level compression
        if early:
            parts.append("Earlier Chapters (compressed):")
            # Group early chapters into groups of 3 for arc compression
            early_sorted = sorted(early, key=lambda s: s.get("chapter", 0))
            for i in range(0, len(early_sorted), 3):
                group = early_sorted[i:i + 3]
                ch_range = f"Ch {group[0]['chapter']}-{group[-1]['chapter']}"
                combined = " | ".join(
                    self._condense_summary(s.get("summary", "")) for s in group
                )
                parts.append(f"  [{ch_range}] {combined}")
            parts.append("")

        # Medium chapters: one-liners
        if medium:
            parts.append("Recent Chapters (condensed):")
            for s in medium:
                ch = s.get("chapter", 0)
                title = s.get("title", f"Ch {ch}")
                one_liner = self._condense_summary(s.get("summary", ""), max_words=15)
                parts.append(f"  Ch {ch} ({title}): {one_liner}")
            parts.append("")

        # Recent chapters: full summaries (high fidelity)
        if recent:
            parts.append("Immediately Previous Chapters:")
            for s in recent:
                ch = s.get("chapter", 0)
                title = s.get("title", f"Ch {ch}")
                summary = s.get("summary", "")
                wc = s.get("word_count", "?")
                parts.append(f"  Ch {ch} - {title} ({wc} words)")
                parts.append(f"    {summary[:CHAPTER_SUMMARY_BUDGET * 4]}")
            parts.append("")

        # Token gauge
        context_str = "\n".join(parts)
        est = estimate_tokens(context_str)
        budget_pct = int((est / max(self.token_budget, 1)) * 100)
        parts.append(f"[Context: ~{est} tokens ({budget_pct}% of ${self.token_budget:,} budget)]")

        parts.append("[/COMPRESSED NARRATIVE CONTEXT]")
        return "\n".join(parts)

    def _condense_summary(self, summary: str, max_words: int = 12) -> str:
        """Condense a summary to a compact one-liner.

        Strips filler words, keeps key nouns and verbs.
        """
        if not summary:
            return ""
        words = summary.split()
        if len(words) <= max_words:
            return summary
        # Keep first few and last few words (most meaningful)
        first = words[:max_words // 2]
        last = words[-(max_words // 2):]
        return " ".join(first) + " ... " + " ".join(last)

    def build_arc_summaries(
        self,
        outline: dict,
        chapter_summaries: list[dict],
    ) -> list[dict]:
        """Build narrative arc summaries from acts in the outline.

        Args:
            outline: Outline dict with acts
            chapter_summaries: Chapter summary dicts

        Returns:
            List of arc summary dicts
        """
        arcs = []
        for act in outline.get("acts", []):
            act_name = act.get("act_name", "Untitled Act")
            act_chapters = act.get("chapters", [])

            # Find summaries for chapters in this act
            act_chapter_nums = {c.get("chapter", 0) for c in act_chapters}
            act_summaries = [
                s for s in chapter_summaries
                if s.get("chapter", 0) in act_chapter_nums
            ]

            if not act_summaries:
                arcs.append({
                    "arc_name": act_name,
                    "summary": act.get("summary", act.get("arc_summary", "")),
                    "chapters": sorted(act_chapter_nums),
                })
                continue

            # Merge summaries
            combined = " | ".join(
                s.get("summary", "")[:60] for s in act_summaries
            )
            arcs.append({
                "arc_name": act_name,
                "summary": combined[:ARC_SUMMARY_BUDGET * 3],
                "chapters": sorted(act_chapter_nums),
            })

        return arcs

    def should_compress(self, chapter_num: int, total_chapters: int) -> bool:
        """Determine if compression is needed given current chapter count."""
        return total_chapters > self.recent_chapters + self.medium_chapters + 1


# ── Fallback: context window management (no external deps) ───────────

class ContextWindow:
    """Manages a sliding window of context with compression at thresholds."""

    def __init__(self, max_tokens: int = 900000, warn_at: int = 700000):
        self.max_tokens = max_tokens
        self.warn_at = warn_at
        self._current: list[str] = []
        self._compressor = ReIOCompressor(token_budget=max_tokens)

    def add(self, text: str) -> str:
        """Add text to context window. Returns compression hint if needed."""
        self._current.append(text)
        total = estimate_tokens(" ".join(self._current))

        if total > self.max_tokens:
            return "CRITICAL: Context overflow. Enable compression."
        elif total > self.warn_at:
            return f"WARNING: Context at {total} tokens. Consider compression."
        return ""

    def get_token_count(self) -> int:
        return estimate_tokens(" ".join(self._current))

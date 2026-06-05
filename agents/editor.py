"""Editor Agent — adversarial tightening pass on completed prose.

The Editor is the final prose-quality gate. It:
1. Identifies the weakest 15% of each chapter
2. Classifies cuts (filler, redundancy, over-explanation, weak verb, telling, pacing drag)
3. Applies mechanical tightening (regex-based, no LLM cost)
4. Optionally runs LLM-based deep editing on flagged chapters

Wraps the existing pipeline/adversarial_edit.py logic.
"""

import json
import os
import re
import time
from typing import Any, Optional

from config import Config
from agents.base import StoryForgeAgent, TASK_EDIT_ADVERSARIAL

from pipeline.api import CrofaiClient


EDITOR_SYSTEM_PROMPT = """You are a ruthless developmental editor. Your job is to cut
the weakest 15% of this chapter without losing voice, plot, or character.

Cut only what makes the chapter weaker:
- Filler phrases that add nothing
- Redundant descriptions (we already know what the room looks like)
- Over-explanation (trust the reader)
- Weak verbs replaced with strong ones
- Telling instead of showing
- Scenes/paragraphs that drag pacing

Return JSON with:
- "cuts": Array of {"text": "exact text to cut", "category": "filler"/"redundancy"/"over_explanation"/"weak_verb"/"telling"/"pacing_drag", "justification": "why this should go"}
- "new_text": The full chapter with all cuts applied
- "words_removed": integer count
- "original_word_count": integer
"""

# Mechanical tightening patterns (regex-based, no LLM cost)
MECHANICAL_PATTERNS = [
    (r'\bin order to\b', 'to'),
    (r'\bthe fact that\b', 'that'),
    (r'\bit was at this point that\b', 'then'),
    (r'\bit was then that\b', 'then'),
    (r'\bin the process of\b', ''),
    (r'\bas a matter of fact\b', 'in fact'),
    (r'\bfor the purpose of\b', 'for'),
    (r'\bas to whether\b', 'whether'),
    (r'\bwhether or not\b', 'whether'),
    (r'\bthe way in which\b', 'how'),
    (r'\bthe extent to which\b', 'how much'),
    (r'\bby means of\b', 'by'),
    (r'\bin the event that\b', 'if'),
    (r'\bin the absence of\b', 'without'),
    (r'\bat this point in time\b', 'now'),
    (r'\bat that point in time\b', 'then'),
    (r'\bhas the ability to\b', 'can'),
    (r'\bhave the ability to\b', 'can'),
    (r'\bis able to\b', 'can'),
    (r'\bare able to\b', 'can'),
    (r'\bwas able to\b', 'could'),
    (r'\bwere able to\b', 'could'),
    (r'\bvery\b', ''),
    (r'\bquite\b', ''),
    (r'\bjust\b', ''),
]


def _estimate_words(text: str) -> int:
    return len(text.split())


def _mechanical_tighten(text: str) -> tuple[str, int]:
    """Apply regex-based mechanical tightening. Returns (tightened_text, words_removed)."""
    original_wc = _estimate_words(text)
    for pattern, replacement in MECHANICAL_PATTERNS:
        text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
    # Clean up double spaces
    text = re.sub(r' +', ' ', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    new_wc = _estimate_words(text)
    return text, original_wc - new_wc


class EditorAgent(StoryForgeAgent):
    """Tightens prose through adversarial editing.

    Two-pass approach:
    1. Mechanical pass: regex-based cleanup (free, instant)
    2. LLM pass: deep editing on chapters that need it (configurable)

    Capabilities:
        - edit_adversarial: Full adversarial editing pass on manuscript
    """

    @property
    def capabilities(self) -> dict[str, Any]:
        return {
            "role": "Editor",
            "can_handle": [TASK_EDIT_ADVERSARIAL],
            "model": self.config.model_for_phase("critique").name,
            "max_concurrency": 1,
            "description": "Adversarial editing pass — tightens prose mechanically and via LLM",
        }

    def can_handle(self, task_type: str) -> bool:
        return task_type == TASK_EDIT_ADVERSARIAL

    def run(
        self,
        task: dict[str, Any],
        context: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        if task.get("type") != TASK_EDIT_ADVERSARIAL:
            return {
                "status": "failed",
                "agent_id": self.agent_id,
                "error": f"Editor cannot handle task type: {task.get('type')}",
            }

        return self._edit_manuscript(task)

    def _edit_manuscript(self, task: dict[str, Any]) -> dict[str, Any]:
        """Run adversarial editing on all chapters.

        Two-pass: mechanical tightening first, then LLM pass on flagged chapters.

        Input:
            task['project_dir']: Project directory with chapters/
            task['chapters']: List of chapter result dicts
            task['use_llm']: If True, also run LLM deep editing (default False)
        """
        project_dir = task.get("project_dir", "")
        chapters = task.get("chapters", [])
        use_llm = task.get("use_llm", False)
        config = task.get("config", self.config)

        if not chapters:
            return {
                "status": "skipped",
                "agent_id": self.agent_id,
                "total_words_removed": 0,
                "total_pct_cut": 0,
                "per_chapter": [],
            }

        per_chapter = []
        total_mechanical_removed = 0
        total_original_words = 0

        for ch in chapters:
            ch_num = ch.get("chapter", 0)
            ch_file = ch.get("file", "")
            ch_content = ch.get("content", "")

            # Read chapter text
            if not ch_content and ch_file:
                try:
                    with open(ch_file, "r", encoding="utf-8") as f:
                        content = f.read()
                    lines = content.split("\n")
                    filtered = [l for l in lines if not l.startswith("> POV:")]
                    ch_content = "\n".join(filtered)
                except (OSError, IOError):
                    ch_content = ""

            if not ch_content:
                continue

            original_wc = _estimate_words(ch_content)
            total_original_words += original_wc

            # ── Pass 1: Mechanical Tightening ──
            tightened, mech_removed = _mechanical_tighten(ch_content)

            # ── Pass 2: LLM Deep Edit (optional) ──
            llm_removed = 0
            if use_llm and mech_removed < original_wc * 0.05:
                try:
                    llm_text, llm_removed = self._llm_edit_chapter(
                        tightened, ch_num, config
                    )
                    tightened = llm_text if llm_text else tightened
                except Exception:
                    pass  # Fall back to mechanical-only

            total_removed = original_wc - _estimate_words(tightened)
            pct_cut = round(total_removed / max(original_wc, 1) * 100, 1)
            total_mechanical_removed += total_removed

            # Save edited version back to file
            if ch_file and tightened != ch_content:
                try:
                    with open(ch_file, "r", encoding="utf-8") as f:
                        original = f.read()
                    # Preserve metadata header
                    lines = original.split("\n")
                    header_lines = [l for l in lines if l.startswith("> POV:")]
                    header = "\n".join(header_lines)
                    if header:
                        new_content = header + "\n\n" + tightened
                    else:
                        new_content = "[EDITED]\n\n" + tightened
                    with open(ch_file, "w", encoding="utf-8") as f:
                        f.write(new_content)
                except (OSError, IOError):
                    pass

            per_chapter.append({
                "chapter": ch_num,
                "title": ch.get("title", f"Chapter {ch_num}"),
                "original_words": original_wc,
                "words_removed": total_removed,
                "pct_cut": pct_cut,
                "mechanical_removed": mech_removed,
                "llm_removed": llm_removed,
            })

        total_pct = round(total_mechanical_removed / max(total_original_words, 1) * 100, 1)

        return {
            "status": "success",
            "agent_id": self.agent_id,
            "total_words_removed": total_mechanical_removed,
            "total_pct_cut": total_pct,
            "per_chapter": per_chapter,
        }

    def _llm_edit_chapter(
        self,
        text: str,
        chapter_num: int,
        config: Config,
    ) -> tuple[str, int]:
        """Run LLM-based deep edit on a single chapter.

        Returns (edited_text, words_removed) or raises on failure.
        """
        prompt = (
            f"Edit Chapter {chapter_num}.\n\n"
            f"Cut the weakest 15% without losing voice or substance.\n\n"
            f"Chapter text:\n{text[:12000]}"
        )

        client = CrofaiClient(config)
        try:
            response = client.chat_with_retry(
                config.model_for_phase("critique"),
                messages=[{"role": "user", "content": prompt}],
                system_prompt=EDITOR_SYSTEM_PROMPT,
                temperature=0.5,
            )
        finally:
            client.close()

        # Parse response
        try:
            # Try to extract JSON
            start = response.find("{")
            end = response.rfind("}")
            if start != -1 and end != -1:
                data = json.loads(response[start:end + 1])
                new_text = data.get("new_text", "")
                words_removed = data.get("words_removed", 0)

                if new_text and words_removed > 0:
                    return new_text, words_removed
        except (json.JSONDecodeError, ValueError):
            pass

        # Fallback: return original unchanged
        return text, 0

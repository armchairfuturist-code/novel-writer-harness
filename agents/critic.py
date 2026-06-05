"""Critic Agent — reviews and scores chapters with dual-persona analysis.

Handles two types of scoring:
1. Mechanical scoring: built-in regex-based (instant, zero-cost)
2. LLM critique: dual-persona (Literary Critic + Professor of Fiction) deep analysis

The Critic can review individual chapters or the full manuscript.
"""

import json
import os
import re
import time
from typing import Any, Optional

from config import Config
from agents.base import StoryForgeAgent, TASK_REVIEW_CHAPTER, TASK_BATCH_REVIEW, TASK_SCORE_MECHANICAL

from pipeline.api import CrofaiClient
from pipeline.draft import ChapterScorer


LITERARY_CRITIC_SYSTEM = """You are a Literary Critic with decades of experience evaluating fiction.
You review chapters on these dimensions (score each 0-10):

1. Prose Craft: Sentence craft, imagery, metaphor quality, rhythm, vocabulary precision.
2. Pacing: Tension, momentum, scene structure, chapter-level arc, paragraph flow.
3. Character Depth: Interiority, voice consistency, motivation clarity, growth signals.
4. Dialogue: Naturalness, subtext, characterization through speech, differentiation.
5. Structure: Scene architecture, chapter arc (beginning-middle-end), hook, cliffhanger.

Output a JSON object with {prose, pacing, character_depth, dialogue, structure, overall_score, critique, strengths, weaknesses}

Be honest and specific. Praise what works, identify what doesn't with concrete examples."""

PROFESSOR_SYSTEM = """You are a Professor of Fiction at a top MFA program. You evaluate fiction for:

1. Thematic Coherence: How well do the chapter's themes resonate with the whole?
2. Narrative Ambition: Does it reach for something difficult or settle for easy answers?
3. Subtext: What is happening beneath the surface of the prose?
4. Emotional Truth: Does the chapter earn its emotional beats?

Output a JSON object with {thematic_coherence, narrative_ambition, subtext, emotional_truth, overall_score, critique, strengths, weaknesses}

Be rigorous. Hold the work to the highest standard. A 7/10 from you means "solid graduate-level work."""


class CriticAgent(StoryForgeAgent):
    """Reviews and scores chapters with mechanical and dual-persona LLM analysis.

    Stateless — each review is self-contained.

    Capabilities:
        - review_chapter: Single chapter review (mechanical + LLM)
        - batch_review: Full manuscript review
        - score_mechanical: Built-in mechanical scoring only (no LLM)
    """

    @property
    def capabilities(self) -> dict[str, Any]:
        return {
            "role": "Critic / Reviewer",
            "can_handle": [TASK_REVIEW_CHAPTER, TASK_BATCH_REVIEW, TASK_SCORE_MECHANICAL],
            "model": self.config.model_for_phase("critique").name,
            "max_concurrency": 1,
            "description": "Reviews chapters with mechanical scoring + dual-persona LLM critique",
        }

    def can_handle(self, task_type: str) -> bool:
        return task_type in {TASK_REVIEW_CHAPTER, TASK_BATCH_REVIEW, TASK_SCORE_MECHANICAL}

    def run(
        self,
        task: dict[str, Any],
        context: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        task_type = task.get("type")

        if task_type == TASK_SCORE_MECHANICAL:
            return self._score_mechanical(task)
        elif task_type == TASK_REVIEW_CHAPTER:
            return self._review_single_chapter(task)
        elif task_type == TASK_BATCH_REVIEW:
            return self._batch_review(task)
        else:
            return {
                "status": "failed",
                "agent_id": self.agent_id,
                "error": f"Critic cannot handle task type: {task_type}",
            }

    def _score_mechanical(self, task: dict[str, Any]) -> dict[str, Any]:
        """Run mechanical scoring on one or more chapters.

        Input:
            task['text']: Single chapter text, OR
            task['texts']: List of chapter text strings

        Returns mechanical scores (no LLM cost).
        """
        config = task.get("config", self.config)
        scorer = ChapterScorer(config)

        texts = task.get("texts", [])
        single_text = task.get("text")

        if single_text:
            texts = [single_text]

        if not texts:
            return {
                "status": "failed",
                "agent_id": self.agent_id,
                "error": "No text provided for scoring",
            }

        scores = []
        for text in texts:
            score = scorer.score_chapter(text)
            scores.append(score)

        return {
            "status": "success",
            "agent_id": self.agent_id,
            "scores": scores if len(scores) > 1 else scores[0],
        }

    def _review_single_chapter(self, task: dict[str, Any]) -> dict[str, Any]:
        """Review a single chapter with mechanical scoring + LLM dual-persona.

        Input:
            task['text']: Chapter text
            task['chapter_number']: Chapter number
            task['chapter_title']: Chapter title

        Returns mechanical + LLM scores with critique.
        """
        text = task.get("text", "")
        chapter_num = task.get("chapter_number", 0)
        chapter_title = task.get("chapter_title", f"Chapter {chapter_num}")
        config = task.get("config", self.config)

        # Mechanical score
        scorer = ChapterScorer(config)
        mechanical = scorer.score_chapter(text)

        # LLM dual-persona critique
        client = CrofaiClient(config)

        # — Critic 1: Literary Critic —
        lit_prompt = (
            f"Review Chapter {chapter_num}: {chapter_title}\n\n"
            f"Chapter text:\n{text[:8000]}"
        )
        lit_response = client.chat_with_retry(
            config.model_for_phase("critique"),
            messages=[{"role": "user", "content": lit_prompt}],
            system_prompt=LITERARY_CRITIC_SYSTEM,
            temperature=0.7,
        )

        # — Critic 2: Professor of Fiction —
        prof_prompt = (
            f"Review Chapter {chapter_num}: {chapter_title}\n\n"
            f"Chapter text:\n{text[:8000]}"
        )
        prof_response = client.chat_with_retry(
            config.model_for_phase("critique"),
            messages=[{"role": "user", "content": prof_prompt}],
            system_prompt=PROFESSOR_SYSTEM,
            temperature=0.7,
        )

        client.close()

        # Parse responses
        try:
            lit_review = json.loads(_extract_json(lit_response))
        except (json.JSONDecodeError, RuntimeError):
            lit_review = {"overall_score": 0, "critique": lit_response[:500]}

        try:
            prof_review = json.loads(_extract_json(prof_response))
        except (json.JSONDecodeError, RuntimeError):
            prof_review = {"overall_score": 0, "critique": prof_response[:500]}

        # Combine scores
        combined = {
            "mechanical": mechanical,
            "literary_critic": lit_review,
            "professor": prof_review,
            "combined_score": round(
                (mechanical.get("total_score", 5) +
                 lit_review.get("overall_score", 5) +
                 prof_review.get("overall_score", 5)) / 3, 1
            ),
        }

        return {
            "status": "success",
            "agent_id": self.agent_id,
            "chapter_number": chapter_num,
            "chapter_title": chapter_title,
            "review": combined,
        }

    def _batch_review(self, task: dict[str, Any]) -> dict[str, Any]:
        """Review all chapters in a project (batch review).

        Scans chapter files for mechanical scores, then optionally
        calls LLM dual-persona on the full manuscript.

        Input:
            task['chapters']: List of chapter result dicts with 'file' or 'content' keys
            task['project_dir']: Project directory
            task['spec']: Project spec (for title/context)

        Returns aggregate review with per-chapter scores.
        """
        chapters = task.get("chapters", [])
        project_dir = task.get("project_dir", "")
        config = task.get("config", self.config)

        if not chapters:
            return {
                "status": "failed",
                "agent_id": self.agent_id,
                "error": "No chapters provided for review",
            }

        scorer = ChapterScorer(config)
        per_chapter_reviews = []
        total_mechanical = 0

        for ch in chapters:
            # Get chapter text
            ch_file = ch.get("file", "")
            ch_content = ch.get("content", "")
            if not ch_content and ch_file:
                try:
                    with open(ch_file, "r", encoding="utf-8") as f:
                        content = f.read()
                    # Strip metadata header
                    lines = content.split("\n")
                    filtered = [l for l in lines if not l.startswith("> POV:")]
                    ch_content = "\n".join(filtered)
                except (OSError, IOError):
                    ch_content = ""

            # Mechanical score
            mech = scorer.score_chapter(ch_content) if ch_content else {"total_score": 0, "word_count": 0}

            # Get existing score if available (from draft metadata)
            existing = ch.get("score", {})
            score_val = mech.get("total_score", existing.get("total_score", 0))

            total_mechanical += score_val

            per_chapter_reviews.append({
                "chapter": ch.get("chapter", 0),
                "title": ch.get("title", ""),
                "word_count": mech.get("word_count", ch.get("word_count", 0)),
                "mechanical_score": score_val,
                "banned_penalty": mech.get("banned_penalty", 0),
                "tell_ratio": mech.get("tell_ratio", 0),
                "pacing_variance": mech.get("pacing_variance", 0),
            })

        # Sort by chapter number
        per_chapter_reviews.sort(key=lambda x: x["chapter"])
        chapter_count = len(per_chapter_reviews)

        # Aggregate
        avg_score = round(total_mechanical / max(chapter_count, 1), 1)
        weakest = min(per_chapter_reviews, key=lambda x: x["mechanical_score"])
        strongest = max(per_chapter_reviews, key=lambda x: x["mechanical_score"])
        total_words = sum(c.get("word_count", 0) for c in per_chapter_reviews)

        return {
            "status": "success",
            "agent_id": self.agent_id,
            "overall_avg_score": avg_score,
            "total_chapters": chapter_count,
            "total_words": total_words,
            "weakest_chapter": weakest["chapter"],
            "weakest_score": weakest["mechanical_score"],
            "strongest_chapter": strongest["chapter"],
            "strongest_score": strongest["mechanical_score"],
            "needs_revision": avg_score < self.config.scoring.target_chapter_score,
            "per_chapter": per_chapter_reviews,
        }


def _extract_json(text: str) -> str:
    """Extract JSON object from text, handling markdown fences."""
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        cleaned = [l for l in lines if not l.startswith("```")]
        text = "\n".join(cleaned)

    # Find outermost { ... }
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        return text[start:end + 1]
    return text

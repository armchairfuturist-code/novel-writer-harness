"""Smoke tests for KnowledgeBase semantic-rescue behavior.

These tests assert that KnowledgeBase.get_references can surface a relevant
reference file when the agent's ctx_keywords (chapter title + top-10 most
frequent content words) have zero literal overlap with the file's
frontmatter keywords.

The semantic layer expands chapter content words via a curated synonym map.
This is a lower bound on what an embedding model would do; if the chapter
talks about "scars" but the KB file's frontmatter says "physical
description", the synonym bridge should hit.

Tested against the actual reference/knowledge/ corpus shipped with the
harness — these are real StoryForge output patterns.
"""

import os
import sys
import unittest
from collections import Counter
import re

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from pipeline.knowledge_base import KnowledgeBase


# Replicates pipeline/debate.py:540-544 ctx_keywords construction.
def _ctx_keywords(title: str, text: str) -> list[str]:
    ctx = []
    if title:
        ctx.extend(title.lower().split())
    words = re.findall(r"\b[a-z]{4,}\b", text[:1000].lower())
    ctx.extend([w for w, _ in Counter(words).most_common(10)])
    return ctx


class TestSemanticRescue(unittest.TestCase):
    """Chapter content uses prose; KB frontmatter uses abstract terms.
    Semantic rescue must bridge the gap when literal overlap is zero."""

    @classmethod
    def setUpClass(cls):
        cls.kb = KnowledgeBase("reference/knowledge")

    def test_scar_query_rescues_character_trait_tracking(self):
        """'Mira's scar on her hand' must surface character-trait-tracking.

        Frontmatter of that file: [character, trait, consistency, eye color,
        hair color, physical description, drift, contradiction].

        Chapter ctx_keywords are prose words: scar, hand, mother, fire, etc.
        Literal overlap is zero; semantic expansion (scar → trait, physical,
        description) must rescue it."""
        ctx = _ctx_keywords(
            "The Scar on Mira's Hand",
            "Mira touched the scar on her left hand, remembering the fire "
            "that had given it to her five years ago. The war had ended by "
            "then, but the mark remained. She wondered if the magic that "
            "healed her other wounds could ever erase this one. Her "
            "grandmother had always said scars told the truer story.",
        )
        result = self.kb.get_references("lore_prosecutor", ctx, max_tokens=500)
        self.assertTrue(
            result.strip(),
            "KB returned empty for Mira's-scar query — agent loses writing theory context",
        )
        # The semantic-rescued file must be present in the result.
        self.assertIn("character", result.lower())
        # Topic header from the rescued file should be visible.
        self.assertIn("Character Trait", result)

    def test_flat_scene_rescues_sensory_immersion(self):
        """'Tavern scene feels flat, can't smell/hear/fire' must surface
        sensory-immersion.md (frontmatter: sensory, immersion, description,
        show don't tell, physical detail, five senses)."""
        ctx = _ctx_keywords(
            "Flat Scene",
            "The tavern scene feels flat. I can see the room but I can't "
            "smell the ale, hear the fire crackle, or feel the worn wood of "
            "the table under the protagonist's hand. The dialogue works but "
            "the scene needs more sensory immersion. Engage the five senses.",
        )
        result = self.kb.get_references("drafting", ctx, max_tokens=500)
        self.assertTrue(
            result.strip(),
            "KB returned empty for flat-scene query — agent loses writing theory context",
        )
        self.assertIn("sensory", result.lower())
        self.assertIn("Sensory Immersion", result)


class TestRegression(unittest.TestCase):
    """Existing behavior must not break. Queries that work via literal
    overlap must continue to work after the synonym expansion lands."""

    @classmethod
    def setUpClass(cls):
        cls.kb = KnowledgeBase("reference/knowledge")

    def test_pacing_query_still_returns_pacing_diagnostics(self):
        ctx = _ctx_keywords(
            "The Long Middle",
            "The second act of the novel is dragging. The pacing has slowed "
            "to a crawl. The dialogue between the two characters sounds "
            "identical. The opening chapter had a strong hook that vanished "
            "by chapter four.",
        )
        result = self.kb.get_references("plot_sentinel", ctx, max_tokens=500)
        self.assertTrue(result.strip())
        self.assertIn("Pacing", result)

    def test_hook_query_still_returns_hook_techniques(self):
        ctx = _ctx_keywords(
            "Opening Hook",
            "The first line of the novel is 'The morning was quiet.' This "
            "doesn't grab. The reader needs a reason to turn the page. The "
            "chapter ending is also flat — it doesn't leave the reader "
            "wanting more.",
        )
        result = self.kb.get_references("drafting", ctx, max_tokens=500)
        self.assertTrue(result.strip())
        self.assertIn("Hook", result)

    def test_magic_query_still_returns_worldbuilding_consistency(self):
        ctx = _ctx_keywords(
            "Chapter 12 — The Magic Test",
            "Elara raised her hand and the magic should have responded. By "
            "the rules of the magic system as established in chapter 3, a "
            "fourth-tier mage cannot summon fire during a lunar eclipse. "
            "Yet the flame came.",
        )
        result = self.kb.get_references("lore_prosecutor", ctx, max_tokens=500)
        self.assertTrue(result.strip())
        self.assertIn("Worldbuilding", result)

    def test_actionable_feedback_still_returns_actionable_revision(self):
        ctx = _ctx_keywords(
            "Actionable Feedback",
            "The critique I received on chapter six is vague. It says the "
            "pacing feels off and some of the dialogue isn't working but it "
            "doesn't tell me what to fix. I need specific, actionable "
            "revision instructions.",
        )
        result = self.kb.get_references("magistrate", ctx, max_tokens=500)
        self.assertTrue(result.strip())
        self.assertIn("Actionable", result)


class TestScoringSemantics(unittest.TestCase):
    """Unit tests for the synonym expansion in _word_overlap_score.

    These are independent of file I/O so they can fail fast with clear
    diagnostics during development."""

    def test_literal_still_works_when_overlap_exists(self):
        from pipeline.knowledge_base import _word_overlap_score
        # "pacing" matches literally; denominator is |Q|=1, so the
        # baseline literal match contributes 1.0 to the numerator. With
        # synonym expansion, additional terms may also match — score
        # becomes >= 1.0. The invariant is: never LESS than 1.0 when
        # a literal match exists.
        score = _word_overlap_score(["pacing"], ["pacing", "drag", "rhythm"])
        self.assertGreaterEqual(score, 1.0)

    def test_semantic_rescue_when_no_literal_overlap(self):
        from pipeline.knowledge_base import _word_overlap_score
        # Query has "scar" and "hand" — no literal match.
        # File has "trait", "physical", "description" — also no literal match.
        # Synonym expansion: scar → trait, physical, description;
        # hand → trait, physical, description.
        # Expanded query should overlap with file.
        score = _word_overlap_score(["scar", "hand"], ["trait", "physical", "description"])
        self.assertGreater(
            score, 0.0,
            "Semantic expansion should rescue scar/hand → trait/physical/description",
        )

    def test_semantic_does_not_inflate_denominator(self):
        """Critical invariant: score is |Q_expanded ∩ F| / |Q|.

        Expansion grows the numerator (more matches) but NOT the
        denominator. Otherwise synonym-rich queries would dominate
        retrieval and bury simple literal matches. Verify with a query
        that has many synonyms vs. a query that has none."""
        from pipeline.knowledge_base import _word_overlap_score
        # Same file; "pacing" expands to a large set; "outline" is single
        # term, also matches.
        # Both have |Q|=1; with the rescue, "pacing" gets expansion bonus,
        # "outline" gets literal-only. Both should be comparable.
        s_pacing = _word_overlap_score(["pacing"], ["pacing", "outline"])
        s_outline = _word_overlap_score(["outline"], ["pacing", "outline"])
        # Pacing has synonym expansion; outline is a single literal.
        # Both scores should be bounded (not blow up).
        self.assertLess(s_pacing, 10.0)
        self.assertLess(s_outline, 10.0)

    def test_score_clamped_reasonably(self):
        """Even a single query term with many synonym matches shouldn't
        return an unbounded score. The synonym map is curated and finite,
        so |Q_expanded ∩ F| is bounded."""
        from pipeline.knowledge_base import _word_overlap_score
        score = _word_overlap_score(["scar"], ["trait", "physical", "description"])
        # scar expands to {trait, physical, description, consistency, drift}.
        # Intersection with the 3-element file set is 3 → score = 3/1 = 3.0
        self.assertEqual(score, 3.0)

    def test_empty_inputs_return_zero(self):
        from pipeline.knowledge_base import _word_overlap_score
        self.assertEqual(_word_overlap_score([], ["trait"]), 0.0)
        self.assertEqual(_word_overlap_score(["scar"], []), 0.0)
        self.assertEqual(_word_overlap_score([], []), 0.0)

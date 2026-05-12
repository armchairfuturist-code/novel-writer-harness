"""Unit tests for the ChapterScorer, BM25Retriever, and API client modules."""

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from config import Config
from pipeline.draft import ChapterScorer, BM25Retriever, _estimate_tokens, _word_count, _get_chapter_text
from pipeline.draft import _generate_revision_prompt


class TestTokenizer(unittest.TestCase):
    """Test token/count estimation utilities."""

    def test_estimate_tokens(self):
        text = "Hello, this is a test sentence with some words in it."
        self.assertGreater(_estimate_tokens(text), 0)
        self.assertAlmostEqual(_estimate_tokens(text), len(text) // 4)

    def test_word_count(self):
        self.assertEqual(_word_count("one two three"), 3)
        self.assertEqual(_word_count(""), 0)
        self.assertEqual(_word_count("  spaces   between "), 2)

    def test_get_chapter_text_removes_header(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
            f.write("# Ch 1\n> POV: Alex | Score: 7.5/10\n\nChapter body here.")
            path = f.name
        try:
            result = _get_chapter_text(path)
            self.assertNotIn("POV:", result)
            self.assertIn("Chapter body", result)
            self.assertIn("# Ch 1", result)
        finally:
            os.unlink(path)

    def test_get_chapter_text_missing_file(self):
        result = _get_chapter_text("/nonexistent/chapter.md")
        self.assertEqual(result, "")


class TestChapterScorer(unittest.TestCase):
    """Test the mechanical scoring module."""

    def setUp(self):
        self.scorer = ChapterScorer()

    def test_good_chapter_scores_high(self):
        text = (
            "The rain hammered the tin roof. Maria pushed open the door and stepped inside. "
            "Water dripped from her coat onto the floorboards. 'You're late,' said the man behind "
            "the desk. His voice was flat, like a blade laid flat on stone. "
            "She didn't answer. She crossed the room in three strides and placed the envelope "
            "between them. The paper was damp at the edges. He didn't touch it. "
            "'I want to know who she was,' Maria said. 'Before she was killed.' "
            "The man laughed. It wasn't a kind sound. It was the kind of laugh you hear "
            "in a room where someone has just lost everything."
        )
        score = self.scorer.score_chapter(text)
        self.assertGreaterEqual(score["total_score"], 5.0)
        self.assertIn("word_count", score)
        self.assertIn("banned_words_found", score)
        self.assertIn("tell_ratio", score)
        self.assertIn("pacing_variance", score)
        self.assertIn("dialogue_ratio", score)

    def test_banned_words_penalize(self):
        text = "Suddenly, she felt very tired. It was literally the worst moment. Very, very bad."
        score = self.scorer.score_chapter(text)
        self.assertLess(score["total_score"], 7.0)
        self.assertGreater(len(score["banned_words_found"]), 0)

    def test_tell_ratio_penalizes(self):
        text = (
            "He felt that something was wrong. She knew that he was lying. "
            "He realized that she knew the truth. It was clear that they both understood."
        )
        score = self.scorer.score_chapter(text)
        self.assertGreater(score["tell_ratio"], 0.3)

    def test_empty_text(self):
        score = self.scorer.score_chapter("")
        self.assertEqual(score["word_count"], 0)
        self.assertGreaterEqual(score["total_score"], 5.0)


class TestBM25Retriever(unittest.TestCase):
    """Test the BM25 context retrieval module."""

    def setUp(self):
        self.retriever = BM25Retriever()
        self.chapters = [
            {"chapter": 1, "title": "The Arrival", "summary": "Maria arrives in the rain-soaked city. She meets the detective.", "pov": "Maria", "key_events": ["Arrival", "Meeting detective"]},
            {"chapter": 2, "title": "The Photograph", "summary": "A photograph reveals a hidden connection. The detective follows a lead to the docks.", "pov": "Detective", "key_events": ["Photo discovery", "Docks investigation"]},
            {"chapter": 3, "title": "The Warehouse", "summary": "A chase through an abandoned warehouse. Maria finds evidence of a conspiracy.", "pov": "Maria", "key_events": ["Chase scene", "Evidence discovery"]},
            {"chapter": 4, "title": "The Interrogation", "summary": "The suspect is interrogated. Secrets about the murder weapon emerge.", "pov": "Detective", "key_events": ["Interrogation", "Weapon revelation"]},
            {"chapter": 5, "title": "The Escape", "summary": "The killer escapes custody. Maria must track them alone through the underground.", "pov": "Maria", "key_events": ["Escape", "Underground pursuit"]},
        ]

    def test_index_and_search(self):
        self.retriever.index(self.chapters)
        results = self.retriever.search("interrogation suspect weapon")
        self.assertGreater(len(results), 0)
        self.assertEqual(results[0]["chapter"], 4)

    def test_search_returns_relevant_chapters(self):
        self.retriever.index(self.chapters)
        results = self.retriever.search("rain arrival docks conspiracy")
        self.assertGreater(len(results), 0)

    def test_search_excludes_chapters(self):
        self.retriever.index(self.chapters)
        results = self.retriever.search("interrogation suspect weapon", exclude_chapters={4})
        if results:
            self.assertNotEqual(results[0]["chapter"], 4)

    def test_search_empty_index(self):
        empty = BM25Retriever()
        results = empty.search("anything")
        self.assertEqual(results, [])

    def test_search_empty_query(self):
        self.retriever.index(self.chapters)
        results = self.retriever.search("")
        self.assertEqual(results, [])

    def test_score_structure(self):
        self.retriever.index(self.chapters)
        results = self.retriever.search("detective docks", k=2)
        self.assertLessEqual(len(results), 2)
        for r in results:
            self.assertIn("chapter", r)
            self.assertIn("title", r)
            self.assertIn("score", r)
            self.assertIsInstance(r["score"], float)


class TestRevisionPrompt(unittest.TestCase):
    """Test revision prompt generation."""

    def test_generates_prompt_for_bad_chapter(self):
        text = "Suddenly he felt very tired. It was literally the worst day ever."
        score = {
            "word_count": 12,
            "banned_words_found": {"suddenly": 1, "very": 1, "literally": 1},
            "tell_ratio": 0.5,
            "pacing_variance": 2.0,
            "total_score": 4.5,
        }
        prompt = _generate_revision_prompt(text, score, "lyrical")
        self.assertIn("suddenly", prompt)
        self.assertIn("very", prompt)
        self.assertIn("lyrical", prompt)

    def test_no_prompt_for_good_chapter(self):
        # Need enough words to not trigger "chapter is short" check (< 2000)
        text = "The rain hammered the tin roof. " * 300  # ~2100 words
        score = {
            "word_count": 2100,
            "banned_words_found": {},
            "tell_ratio": 0.1,
            "pacing_variance": 8.0,
            "total_score": 8.0,
        }
        prompt = _generate_revision_prompt(text, score, "default")
        self.assertEqual(prompt, "")


class TestConfig(unittest.TestCase):
    """Test configuration module."""

    def setUp(self):
        # Reset singleton for testing
        Config._instance = None

    def test_singleton(self):
        c1 = Config()
        c2 = Config()
        self.assertIs(c1, c2)

    def test_model_for_phase(self):
        c = Config()
        model = c.model_for_phase("draft")
        self.assertEqual(model.name, "kimi-k2.6-precision")

    def test_model_for_phase_fallback(self):
        c = Config()
        model = c.model_for_phase("nonexistent")
        self.assertIsNotNone(model)

    def test_scoring_config_defaults(self):
        c = Config()
        self.assertEqual(c.scoring.min_chapter_score, 6.0)
        self.assertEqual(c.scoring.target_chapter_score, 8.0)
        self.assertEqual(c.scoring.max_revision_rounds, 3)

    def test_chapter_config_defaults(self):
        c = Config()
        self.assertEqual(c.chapter.target_words_per_chapter, 4000)
        self.assertEqual(c.chapter.context_carry_window, 3)

    def test_banned_words(self):
        c = Config()
        self.assertIn("suddenly", c.banned_words)
        self.assertIn("very", c.banned_words)
        self.assertNotIn("the", c.banned_words)

    # ── Interview model routing ──

    def test_model_for_interview(self):
        c = Config()
        model = c.model_for_interview("concept_premise")
        self.assertEqual(model.name, "deepseek-v4-pro-precision")
        model = c.model_for_interview("characters")
        self.assertEqual(model.name, "kimi-k2.6-precision")
        model = c.model_for_interview("drilling")
        self.assertEqual(model.name, "qwen3.5-9b")

    def test_model_for_interview_fallback(self):
        """Unknown interview task falls back to 'kimi-balanced'."""
        c = Config()
        model = c.model_for_interview("nonexistent_dimension")
        self.assertEqual(model.name, "kimi-k2.6-precision")

    def test_model_for_interview_override(self):
        """Override picks a different model from the registry."""
        c = Config()
        # Override to deepseek for a task that normally routes to kimi
        model = c.model_for_interview("characters", override="deepseek")
        self.assertEqual(model.name, "deepseek-v4-pro-precision")
        # Override to flash for a context-heavy task
        model = c.model_for_interview("world_setting", override="flash")
        self.assertEqual(model.name, "qwen3.5-9b")

    def test_model_for_interview_invalid_override(self):
        """Invalid override key is ignored — uses routed model instead."""
        c = Config()
        model = c.model_for_interview("drilling", override="nonexistent-alias")
        self.assertEqual(model.name, "qwen3.5-9b")

    def test_interview_models_has_all_dimensions(self):
        """All interview dimensions have a routing entry."""
        c = Config()
        expected = {
            "concept_premise", "world_setting", "characters",
            "plot_structure", "theme_voice", "market_comparisons",
            "drilling", "compilation",
        }
        self.assertEqual(set(c.interview_models.keys()), expected)

    # ── Benchmark model routing ──

    def test_model_for_benchmark_known(self):
        c = Config()
        model = c.model_for_benchmark("kimi-k2.6")
        self.assertEqual(model.name, "kimi-k2.6")
        model = c.model_for_benchmark("kimi-k2.6-precision")
        self.assertEqual(model.name, "kimi-k2.6-precision")

    def test_model_for_benchmark_fallback(self):
        """Unknown benchmark alias falls back to 'kimi-k2.6', not KeyError."""
        c = Config()
        model = c.model_for_benchmark("nonexistent-variant")
        self.assertEqual(model.name, "kimi-k2.6")
        model = c.model_for_benchmark("kimi-k2.6-test")  # the old broken key
        self.assertEqual(model.name, "kimi-k2.6")


if __name__ == "__main__":
    unittest.main()

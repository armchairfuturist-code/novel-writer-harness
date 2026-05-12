"""Tests for the StoryForge interactive interview module (S01)."""

import json
import os
import sys
import tempfile
import unittest

# Direct module-level imports (no setUpClass storage - avoids bound-method issues)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from interview.questions import get_questions, get_dimension_counts, DIMENSION_ORDER
from interview.questions import Question, CONCEPT
from interview.engine import _detect_thin_area, _save_checkpoint, _load_checkpoint, run_interview
from interview.cli import present_question, get_answer


class TestQuestionBank(unittest.TestCase):

    def test_quick_mode_count(self):
        qs = get_questions("quick")
        self.assertGreaterEqual(len(qs), 3)
        self.assertLessEqual(len(qs), 5)

    def test_standard_mode_count(self):
        qs = get_questions("standard")
        self.assertGreaterEqual(len(qs), 20)
        self.assertLessEqual(len(qs), 30)

    def test_comprehensive_mode_count(self):
        qs = get_questions("comprehensive")
        self.assertGreaterEqual(len(qs), 55)
        self.assertLessEqual(len(qs), 75)

    def test_all_dimensions_represented(self):
        counts = get_dimension_counts("comprehensive")
        for dim in DIMENSION_ORDER:
            with self.subTest(dim=dim):
                self.assertGreater(counts.get(dim, 0), 0)

    def test_no_duplicate_ids(self):
        ids = [q.id for q in get_questions("comprehensive")]
        self.assertEqual(len(ids), len(set(ids)))

    def test_quick_only_concept(self):
        for q in get_questions("quick"):
            self.assertEqual(q.dimension, "concept_premise")

    def test_depth_filtering(self):
        quick_ids = {q.id for q in get_questions("quick")}
        standard_ids = {q.id for q in get_questions("standard")}
        comp_ids = {q.id for q in get_questions("comprehensive")}
        self.assertTrue(quick_ids.issubset(comp_ids))
        self.assertTrue(standard_ids.issubset(comp_ids))

    def test_genre_filtering(self):
        qs = get_questions("comprehensive", genre="fantasy")
        normal = get_questions("comprehensive")
        self.assertEqual(len(qs), len(normal))


class TestThinAreaDetection(unittest.TestCase):

    def setUp(self):
        self.q_no_kw = Question("test-01", CONCEPT, "Test?", depths=["quick"])
        self.q_with_kw = Question("test-02", CONCEPT, "Test?", depths=["quick"], follow_up_keywords=["everyone", "anyone"])

    def test_short_answer_is_thin(self):
        self.assertTrue(_detect_thin_area("It is good", self.q_no_kw))

    def test_hedge_words_flagged(self):
        for a in ["I guess it might work", "Maybe something like that", "I am not sure about this"]:
            with self.subTest(answer=a[:20]):
                self.assertTrue(_detect_thin_area(a, self.q_no_kw))

    def test_detailed_answer_not_thin(self):
        a = "The protagonist is a retired detective who uncovers a conspiracy"
        self.assertFalse(_detect_thin_area(a, self.q_no_kw))

    def test_follow_up_keyword_triggers(self):
        self.assertTrue(_detect_thin_area("It is for everyone really", self.q_with_kw))
        self.assertTrue(_detect_thin_area("Anyone would like this book", self.q_with_kw))

    def test_skipped_is_short(self):
        # Engine handles [SKIPPED] before calling detect;
        # the function itself flags it as thin due to word count
        self.assertTrue(_detect_thin_area("[SKIPPED]", self.q_no_kw))


class TestCheckpointRoundTrip(unittest.TestCase):

    def test_round_trip(self):
        data = {"version": 2, "depth": "standard", "genre": None,
                "started_at": "2026-01-01T00:00:00", "completed_at": None,
                "answers": [{"question_id": "cp-01", "dimension": "concept_premise",
                             "question": "Test?", "answer": "My answer",
                             "is_thin": False, "timestamp": "2026-01-01T00:00:00"}],
                "thin_areas": []}
        with tempfile.TemporaryDirectory() as td:
            path = _save_checkpoint(data, td)
            self.assertTrue(os.path.exists(path))
            loaded = _load_checkpoint(td)
            self.assertIsNotNone(loaded)
            self.assertEqual(loaded["version"], 2)

    def test_load_nonexistent(self):
        result = _load_checkpoint("/nonexistent/path")
        self.assertIsNone(result)

    def test_load_corrupted(self):
        with tempfile.TemporaryDirectory() as td:
            with open(os.path.join(td, "interview_checkpoint.json"), "w") as f:
                f.write("not valid json")
            result = _load_checkpoint(td)
            self.assertIsNone(result)


class TestCLIImports(unittest.TestCase):

    def test_all_functions_importable(self):
        self.assertTrue(callable(present_question))
        self.assertTrue(callable(get_answer))


class TestEngineImports(unittest.TestCase):

    def test_run_interview_importable(self):
        self.assertTrue(callable(run_interview))

    def test_save_load_exist(self):
        self.assertTrue(callable(_save_checkpoint))
        self.assertTrue(callable(_load_checkpoint))

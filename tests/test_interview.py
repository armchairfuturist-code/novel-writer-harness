"""Tests for the StoryForge interactive interview module (S01 + S02 resume)."""

import json
import os
import re
import sys
import tempfile
import unittest

# Direct module-level imports (no setUpClass storage - avoids bound-method issues)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from interview.questions import get_questions, get_dimension_counts, DIMENSION_ORDER
from interview.questions import Question, CONCEPT
from interview.engine import _detect_thin_area, _save_checkpoint, _load_checkpoint, run_interview
from interview.cli import present_question, get_answer
from interview.resume import validate_checkpoint, recover_checkpoint, log_error, ALLOWED_VERSIONS, REQUIRED_ANSWER_KEYS


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


def _make_valid_checkpoint():
    """Build a structurally valid checkpoint dict for testing."""
    return {
        "version": 2,
        "depth": "standard",
        "genre": None,
        "model_override": None,
        "started_at": "2026-01-01T00:00:00",
        "completed_at": "2026-01-01T01:00:00",
        "answers": [
            {
                "question_id": "cp-01",
                "dimension": "concept_premise",
                "question": "What is the concept?",
                "answer": "A story about dragons",
                "is_thin": False,
                "timestamp": "2026-01-01T00:05:00",
            },
            {
                "question_id": "pl-01",
                "dimension": "plot_structure",
                "question": "What happens?",
                "answer": "The hero wins",
                "is_thin": True,
                "timestamp": "2026-01-01T00:10:00",
            },
        ],
        "thin_areas": [],
    }


class TestValidateCheckpoint(unittest.TestCase):

    def test_valid_checkpoint_returns_none(self):
        data = _make_valid_checkpoint()
        self.assertIsNone(validate_checkpoint(data))

    def test_not_a_dict(self):
        self.assertIsNotNone(validate_checkpoint("not a dict"))
        self.assertIsNotNone(validate_checkpoint(42))
        self.assertIsNotNone(validate_checkpoint(None))

    def test_unsupported_version(self):
        data = _make_valid_checkpoint()
        data["version"] = 1
        err = validate_checkpoint(data)
        self.assertIsNotNone(err)
        self.assertIn("version", err)

    def test_missing_version(self):
        data = _make_valid_checkpoint()
        del data["version"]
        err = validate_checkpoint(data)
        self.assertIsNotNone(err)
        self.assertIn("version", err)

    def test_answers_not_a_list(self):
        data = _make_valid_checkpoint()
        data["answers"] = "not a list"
        err = validate_checkpoint(data)
        self.assertIsNotNone(err)
        self.assertIn("answers", err)

    def test_missing_answers_key(self):
        data = _make_valid_checkpoint()
        del data["answers"]
        err = validate_checkpoint(data)
        self.assertIsNotNone(err)
        self.assertIn("answers", err)

    def test_answer_entry_missing_key(self):
        data = _make_valid_checkpoint()
        del data["answers"][0]["answer"]
        err = validate_checkpoint(data)
        self.assertIsNotNone(err)
        self.assertIn("missing required keys", err)

    def test_answer_value_not_string(self):
        data = _make_valid_checkpoint()
        data["answers"][0]["answer"] = 42
        err = validate_checkpoint(data)
        self.assertIsNotNone(err)
        self.assertIn("not a string", err)

    def test_answer_value_none(self):
        data = _make_valid_checkpoint()
        data["answers"][0]["answer"] = None
        err = validate_checkpoint(data)
        self.assertIsNotNone(err)
        self.assertIn("not a string", err)

    def test_answer_entry_not_dict(self):
        data = _make_valid_checkpoint()
        data["answers"].append("not a dict")
        err = validate_checkpoint(data)
        self.assertIsNotNone(err)
        self.assertIn("not a dict", err)

    def test_empty_answers_list(self):
        data = _make_valid_checkpoint()
        data["answers"] = []
        self.assertIsNone(validate_checkpoint(data))


class TestRecoverCheckpoint(unittest.TestCase):

    def test_returns_none_placeholder(self):
        """Currently no backup mechanism — always returns None."""
        self.assertIsNone(recover_checkpoint("/tmp"))
        self.assertIsNone(recover_checkpoint("/nonexistent"))


class TestLogError(unittest.TestCase):

    def test_writes_iso_timestamped_entry(self):
        with tempfile.TemporaryDirectory() as td:
            log_error(td, "Something went wrong")
            log_error(td, "Another error")
            path = os.path.join(td, "errors.log")
            self.assertTrue(os.path.exists(path))
            with open(path, encoding="utf-8") as f:
                lines = f.readlines()
            self.assertEqual(len(lines), 2)
            # Each line: [ISO-timestamp] message
            for line in lines:
                self.assertRegex(line, r"^\[\d{4}-\d{2}-\d{2}T")
            self.assertIn("Something went wrong", lines[0])
            self.assertIn("Another error", lines[1])
            self.assertIn("Something went wrong", lines[0])
            self.assertIn("Another error", lines[1])

    def test_creates_directory_if_missing(self):
        with tempfile.TemporaryDirectory() as td:
            nested = os.path.join(td, "a", "b", "c")
            log_error(nested, "deep error")
            path = os.path.join(nested, "errors.log")
            self.assertTrue(os.path.exists(path))

    def test_appends_not_overwrites(self):
        with tempfile.TemporaryDirectory() as td:
            log_error(td, "first")
            log_error(td, "second")
            path = os.path.join(td, "errors.log")
            with open(path, encoding="utf-8") as f:
                lines = f.readlines()
            self.assertEqual(len(lines), 2)


class TestResumeExports(unittest.TestCase):

    def test_validate_checkpoint_exported(self):
        self.assertTrue(callable(validate_checkpoint))

    def test_recover_checkpoint_exported(self):
        self.assertTrue(callable(recover_checkpoint))

    def test_log_error_exported(self):
        self.assertTrue(callable(log_error))

    def test_constants_accessible(self):
        self.assertIn(2, ALLOWED_VERSIONS)
        self.assertIn("question_id", REQUIRED_ANSWER_KEYS)
        self.assertIn("answer", REQUIRED_ANSWER_KEYS)
        self.assertIn("is_thin", REQUIRED_ANSWER_KEYS)
        self.assertIn("timestamp", REQUIRED_ANSWER_KEYS)


class TestContextMonitor(unittest.TestCase):
    """Tests for interview.context_monitor — ContextMonitor and estimate_tokens."""

    def test_estimate_tokens_short(self):
        from interview.context_monitor import estimate_tokens
        self.assertEqual(estimate_tokens("hi"), 0)  # 2 // 4 = 0
        self.assertEqual(estimate_tokens("hello"), 1)  # 5 // 4 = 1
        self.assertEqual(estimate_tokens(""), 0)

    def test_estimate_tokens_long(self):
        from interview.context_monitor import estimate_tokens
        self.assertEqual(estimate_tokens("a" * 100), 25)

    def test_monitor_default_init(self):
        from interview.context_monitor import ContextMonitor
        cm = ContextMonitor()
        self.assertEqual(cm.limit, 128000)
        self.assertEqual(cm.warn_at, 89600)  # int(128000 * 0.70)
        self.assertEqual(cm.accumulated, 0)
        self.assertFalse(cm.has_warned)

    def test_monitor_custom_model(self):
        from interview.context_monitor import ContextMonitor
        cm = ContextMonitor("flash")
        self.assertEqual(cm.limit, 128000)

    def test_monitor_unknown_model_fallback(self):
        from interview.context_monitor import ContextMonitor
        cm = ContextMonitor("no-such-model")
        self.assertEqual(cm.limit, 128000)

    def test_add_qa_accumulates(self):
        from interview.context_monitor import ContextMonitor
        cm = ContextMonitor()
        cm.add_qa("short q", "short a")
        # len("short q")=7//4=1 + len("short a")=7//4=1 = 2
        self.assertEqual(cm.accumulated, 2)

    def test_check_below_threshold(self):
        from interview.context_monitor import ContextMonitor
        cm = ContextMonitor()
        cm.add_qa("", "")
        self.assertIsNone(cm.check())
        self.assertFalse(cm.has_warned)

    def test_check_triggers_warning(self):
        from interview.context_monitor import ContextMonitor
        cm = ContextMonitor()
        # Need accumulated > warn_at (89600) → answer needs ~358400 chars
        cm.add_qa("x", "a" * 360000)
        msg = cm.check()
        self.assertIsNotNone(msg)
        self.assertTrue(cm.has_warned)
        self.assertIn("Context Warning", msg)
        self.assertIn("Continue", msg)
        self.assertIn("Export and resume later", msg)
        self.assertIn("128,000", msg)  # limit

    def test_check_one_shot(self):
        from interview.context_monitor import ContextMonitor
        cm = ContextMonitor()
        cm.add_qa("x", "a" * 360000)
        self.assertIsNotNone(cm.check())
        self.assertIsNone(cm.check())  # second call returns None

    def test_display_context_warning_stub(self):
        from interview.context_monitor import ContextMonitor
        cm = ContextMonitor()
        result = cm.display_context_warning("test message")
        self.assertEqual(result, "continue")

    def test_model_context_limits_contains_all_aliases(self):
        from interview.context_monitor import MODEL_CONTEXT_LIMITS
        for alias in ("deepseek", "kimi-speed", "kimi-balanced", "kimi-precision", "flash"):
            self.assertIn(alias, MODEL_CONTEXT_LIMITS)
            self.assertGreater(MODEL_CONTEXT_LIMITS[alias], 0)

    def test_imports_from_package(self):
        from interview import ContextMonitor, estimate_tokens
        self.assertIs(ContextMonitor, ContextMonitor)
        self.assertTrue(callable(estimate_tokens))

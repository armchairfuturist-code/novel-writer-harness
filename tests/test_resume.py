"""Integration and unit tests for resume, checkpoint, context monitor, and error logging.

S02 T04: Covers checkpoint validation, file round-trips, corrupted data handling,
context window monitoring, and structured error logging.
"""

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from interview.resume import (
    validate_checkpoint,
    recover_checkpoint,
    log_error,
    ALLOWED_VERSIONS,
    REQUIRED_ANSWER_KEYS,
)
from interview.context_monitor import ContextMonitor, estimate_tokens, MODEL_CONTEXT_LIMITS
from interview.engine import _load_checkpoint, _save_checkpoint


# ── Helpers ──────────────────────────────────────────────────────────────────

CHECKPOINT_FILENAME = "interview_checkpoint.json"


def _make_valid_checkpoint():
    """Build a structurally valid checkpoint dict."""
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


# ── TestValidateCheckpoint (unit) ────────────────────────────────────────────

class TestValidateCheckpoint(unittest.TestCase):
    """Unit tests for validate_checkpoint() — schema validation."""

    def test_valid_data_returns_none(self):
        data = _make_valid_checkpoint()
        self.assertIsNone(validate_checkpoint(data))

    def test_missing_keys_returns_error(self):
        data = _make_valid_checkpoint()
        del data["version"]
        err = validate_checkpoint(data)
        self.assertIsNotNone(err)
        self.assertIn("version", err)

        data2 = _make_valid_checkpoint()
        del data2["answers"]
        err2 = validate_checkpoint(data2)
        self.assertIsNotNone(err2)
        self.assertIn("answers", err2)

        data3 = _make_valid_checkpoint()
        del data3["answers"][0]["answer"]
        err3 = validate_checkpoint(data3)
        self.assertIsNotNone(err3)
        self.assertIn("missing required keys", err3)

    def test_wrong_version_returns_error(self):
        data = _make_valid_checkpoint()
        data["version"] = 1
        err = validate_checkpoint(data)
        self.assertIsNotNone(err)
        self.assertIn("version", err)

    def test_non_dict_returns_error(self):
        for val in ("not a dict", 42, None, ["a", "b"]):
            with self.subTest(val=repr(val)):
                self.assertIsNotNone(validate_checkpoint(val))

    def test_answers_not_list_returns_error(self):
        data = _make_valid_checkpoint()
        data["answers"] = "not a list"
        err = validate_checkpoint(data)
        self.assertIsNotNone(err)
        self.assertIn("answers", err)

    def test_non_string_answer_returns_error(self):
        data = _make_valid_checkpoint()
        data["answers"][0]["answer"] = 42
        err = validate_checkpoint(data)
        self.assertIsNotNone(err)
        self.assertIn("not a string", err)

        data2 = _make_valid_checkpoint()
        data2["answers"][0]["answer"] = None
        err2 = validate_checkpoint(data2)
        self.assertIsNotNone(err2)
        self.assertIn("not a string", err2)

    def test_non_dict_answer_returns_error(self):
        data = _make_valid_checkpoint()
        data["answers"].append("not a dict")
        err = validate_checkpoint(data)
        self.assertIsNotNone(err)
        self.assertIn("not a dict", err)

    def test_empty_answers_list_is_valid(self):
        data = _make_valid_checkpoint()
        data["answers"] = []
        self.assertIsNone(validate_checkpoint(data))

    def test_all_allowed_versions_pass(self):
        for v in ALLOWED_VERSIONS:
            data = _make_valid_checkpoint()
            data["version"] = v
            self.assertIsNone(validate_checkpoint(data))

    def test_unknown_key_does_not_cause_error(self):
        data = _make_valid_checkpoint()
        data["extra_field"] = "this is fine"
        self.assertIsNone(validate_checkpoint(data))


# ── TestResumeIntegration (integration) ─────────────────────────────────────

class TestResumeIntegration(unittest.TestCase):
    """Integration tests for the full checkpoint save → load → validate round-trip."""

    def test_save_load_validate_round_trip(self):
        """Create checkpoint file → _load_checkpoint() → validate_checkpoint() → verify answers."""
        data = _make_valid_checkpoint()
        with tempfile.TemporaryDirectory() as td:
            _save_checkpoint(data, td)
            loaded = _load_checkpoint(td)
            self.assertIsNotNone(loaded)
            self.assertIsNone(validate_checkpoint(loaded))
            self.assertEqual(
                loaded["answers"],
                data["answers"],
            )

    def test_simulate_interrupt_flow(self):
        """Checkpoint with completed_at=None (interrupted session) loads and validates."""
        data = _make_valid_checkpoint()
        data["completed_at"] = None
        with tempfile.TemporaryDirectory() as td:
            _save_checkpoint(data, td)
            loaded = _load_checkpoint(td)
            self.assertIsNotNone(loaded)
            # Interrupted checkpoint is structurally valid
            self.assertIsNone(validate_checkpoint(loaded))
            self.assertIsNone(loaded["completed_at"])
            self.assertGreaterEqual(len(loaded["answers"]), 1)

    def test_save_load_interrupted_then_resumed(self):
        """Verify answers survive a simulated interrupt-and-resume cycle."""
        data = _make_valid_checkpoint()
        data["completed_at"] = None
        with tempfile.TemporaryDirectory() as td:
            path = _save_checkpoint(data, td)
            self.assertTrue(os.path.exists(path))
            loaded = _load_checkpoint(td)
            self.assertIsNotNone(loaded)
            # Add a new answer (simulating resume)
            loaded["answers"].append({
                "question_id": "ch-01",
                "dimension": "character",
                "question": "Who is the protagonist?",
                "answer": "A dragon rider",
                "is_thin": False,
                "timestamp": "2026-01-01T02:00:00",
            })
            loaded["completed_at"] = "2026-01-01T02:30:00"
            _save_checkpoint(loaded, td)
            # Reload and verify all answers intact
            final = _load_checkpoint(td)
            self.assertIsNotNone(final)
            self.assertEqual(len(final["answers"]), 3)
            self.assertEqual(final["answers"][0]["question_id"], "cp-01")
            self.assertEqual(final["answers"][2]["question_id"], "ch-01")
            self.assertIsNotNone(final["completed_at"])

    def test_load_nonexistent_directory_returns_none(self):
        self.assertIsNone(_load_checkpoint("/nonexistent/path"))

    def test_recover_checkpoint_placeholder(self):
        """recover_checkpoint() is a placeholder — always returns None."""
        self.assertIsNone(recover_checkpoint("/tmp"))
        self.assertIsNone(recover_checkpoint("/nonexistent"))


# ── TestCorruptedCheckpoint (integration) ───────────────────────────────────

class TestCorruptedCheckpoint(unittest.TestCase):
    """Integration tests for corrupted checkpoint handling — no crashes, graceful fallback."""

    def test_malformed_json_returns_none(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, CHECKPOINT_FILENAME)
            with open(path, "w", encoding="utf-8") as f:
                f.write("not valid json")
            # Must return None (not crash)
            result = _load_checkpoint(td)
            self.assertIsNone(result)

    def test_missing_required_field_returns_error(self):
        data = _make_valid_checkpoint()
        del data["version"]
        err = validate_checkpoint(data)
        self.assertIsNotNone(err)
        self.assertIn("version", err)

    def test_wrong_version_returns_error(self):
        data = _make_valid_checkpoint()
        data["version"] = 99
        err = validate_checkpoint(data)
        self.assertIsNotNone(err)
        self.assertIn("version", err)

    def test_json_with_extra_fields_does_not_crash(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, CHECKPOINT_FILENAME)
            # Write JSON with extra unknown fields and junk nesting
            corrupted = {
                "version": 2,
                "answers": [{"question_id": "q1", "dimension": "d", "question": "q",
                             "answer": "a", "is_thin": False, "timestamp": "t",
                             "extra": "nested junk"}],
                "unknown_field": [1, 2, 3],
            }
            with open(path, "w", encoding="utf-8") as f:
                json.dump(corrupted, f)
            loaded = _load_checkpoint(td)
            self.assertIsNotNone(loaded)
            self.assertIsNone(validate_checkpoint(loaded))

    def test_missing_answer_fields_fails_validation_gracefully(self):
        """Missing keys in an answer produces a descriptive error, not a crash."""
        data = _make_valid_checkpoint()
        del data["answers"][0]["answer"]
        err = validate_checkpoint(data)
        self.assertIsNotNone(err)
        self.assertIn("missing required keys", err)

    def test_truncated_json_file_returns_none(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, CHECKPOINT_FILENAME)
            with open(path, "w", encoding="utf-8") as f:
                f.write('{"version": 2, "answers": [{"question_id"')
            result = _load_checkpoint(td)
            self.assertIsNone(result)

    def test_empty_file_returns_none(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, CHECKPOINT_FILENAME)
            with open(path, "w", encoding="utf-8") as f:
                f.write("")
            result = _load_checkpoint(td)
            self.assertIsNone(result)


# ── TestContextMonitor (unit) ────────────────────────────────────────────────

class TestContextMonitor(unittest.TestCase):
    """Unit tests for ContextMonitor and estimate_tokens."""

    def test_estimate_tokens_accuracy(self):
        self.assertEqual(estimate_tokens(""), 0)
        self.assertEqual(estimate_tokens("hi"), 0)      # 2 // 4 = 0
        self.assertEqual(estimate_tokens("hello"), 1)    # 5 // 4 = 1
        self.assertEqual(estimate_tokens("hello world"), 2)  # 11 // 4 = 2
        self.assertEqual(estimate_tokens("a" * 100), 25)
        self.assertEqual(estimate_tokens("a" * 103), 25)  # floor division
        self.assertEqual(estimate_tokens("a" * 104), 26)

    def test_accumulation_over_multiple_qa(self):
        cm = ContextMonitor()
        cm.add_qa("short", "answer")
        # "short" → 5//4=1, "answer" → 6//4=1 → total 2
        self.assertEqual(cm.accumulated, 2)
        cm.add_qa("another question", "another longer answer")
        # "another question" → 17//4=4, "another longer answer" → 21//4=5 → total +9 = 11
        self.assertEqual(cm.accumulated, 11)
        cm.add_qa("x", "y")
        self.assertEqual(cm.accumulated, 11)  # 1+0=1 → 12
        # Actually let me recompute: "x" → 1//4=0, "y" → 1//4=0 → total +0 = 11
        self.assertEqual(cm.accumulated, 11)

    def test_warning_triggers_at_threshold(self):
        cm = ContextMonitor()
        # warn_at = 128000 * 0.70 = 89600
        # Need to exceed 89600 tokens → 89600 * 4 = 358400 chars
        cm.add_qa("x", "a" * 360000)
        msg = cm.check()
        self.assertIsNotNone(msg)
        self.assertTrue(cm.has_warned)
        self.assertIn("Context Warning", msg)
        self.assertIn("Continue", msg)
        self.assertIn("Export and resume later", msg)

    def test_no_double_warning(self):
        cm = ContextMonitor()
        cm.add_qa("x", "a" * 360000)
        self.assertIsNotNone(cm.check())   # first call → warning
        self.assertIsNone(cm.check())      # second call → None (one-shot)

    def test_different_model_limits_respected(self):
        # All current models use 128K, so verify the mapping is intact
        cm = ContextMonitor("deepseek")
        self.assertEqual(cm.limit, 128000)
        cm2 = ContextMonitor("kimi-speed")
        self.assertEqual(cm2.limit, 128000)
        cm3 = ContextMonitor("kimi-balanced")
        self.assertEqual(cm3.limit, 128000)
        cm4 = ContextMonitor("kimi-precision")
        self.assertEqual(cm4.limit, 128000)
        cm5 = ContextMonitor("flash")
        self.assertEqual(cm5.limit, 128000)

    def test_below_threshold_no_warning(self):
        cm = ContextMonitor()
        cm.add_qa("short question", "short answer")
        # 14//4 + 11//4 = 3 + 2 = 5 tokens, well below 89600
        self.assertIsNone(cm.check())
        self.assertFalse(cm.has_warned)

    def test_at_exact_threshold_triggers(self):
        """If accumulation just hits warn_at, warning fires."""
        cm = ContextMonitor()
        # warn_at = 89600 → need 89600 * 4 = 358400 chars in a single answer
        cm.add_qa("", "a" * 358400)
        self.assertIsNotNone(cm.check())

    def test_one_char_below_threshold_no_warning(self):
        """One character below threshold should not trigger."""
        cm = ContextMonitor()
        # 89599 * 4 = 358396 chars → just under
        cm.add_qa("", "a" * 358396)
        self.assertIsNone(cm.check())

    def test_display_context_warning_stub(self):
        cm = ContextMonitor()
        result = cm.display_context_warning("test message")
        self.assertEqual(result, "continue")

    def test_unknown_model_fallback_to_128k(self):
        cm = ContextMonitor("no-such-model-ever")
        self.assertEqual(cm.limit, 128000)

    def test_model_context_limits_contains_expected_models(self):
        for alias in ("deepseek", "kimi-speed", "kimi-balanced", "kimi-precision", "flash"):
            self.assertIn(alias, MODEL_CONTEXT_LIMITS)


# ── TestErrorLogging (integration) ──────────────────────────────────────────

class TestErrorLogging(unittest.TestCase):
    """Integration tests for log_error() — file creation, timestamps, append."""

    def test_log_error_creates_errors_log(self):
        with tempfile.TemporaryDirectory() as td:
            log_error(td, "Test error message")
            path = os.path.join(td, "errors.log")
            self.assertTrue(os.path.exists(path))
            self.assertTrue(os.path.isfile(path))

    def test_log_error_contains_iso_timestamp(self):
        with tempfile.TemporaryDirectory() as td:
            log_error(td, "Something went wrong")
            path = os.path.join(td, "errors.log")
            with open(path, encoding="utf-8") as f:
                line = f.readline().strip()
            self.assertRegex(line, r"^\[\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}")

    def test_log_error_contains_message_text(self):
        with tempfile.TemporaryDirectory() as td:
            log_error(td, "My specific error message")
            path = os.path.join(td, "errors.log")
            with open(path, encoding="utf-8") as f:
                line = f.readline().strip()
            self.assertIn("My specific error message", line)

    def test_log_error_appends_not_overwrites(self):
        with tempfile.TemporaryDirectory() as td:
            log_error(td, "first")
            log_error(td, "second")
            log_error(td, "third")
            path = os.path.join(td, "errors.log")
            with open(path, encoding="utf-8") as f:
                lines = f.readlines()
            self.assertEqual(len(lines), 3)
            self.assertIn("first", lines[0])
            self.assertIn("second", lines[1])
            self.assertIn("third", lines[2])

    def test_log_error_creates_directory_if_missing(self):
        with tempfile.TemporaryDirectory() as td:
            nested = os.path.join(td, "deeply", "nested", "dir")
            log_error(nested, "deep error")
            path = os.path.join(nested, "errors.log")
            self.assertTrue(os.path.exists(path))
            with open(path, encoding="utf-8") as f:
                line = f.readline().strip()
            self.assertIn("deep error", line)

    def test_log_error_is_append_mode_per_call(self):
        """Each call appends a new line — verify file grows."""
        with tempfile.TemporaryDirectory() as td:
            for i in range(5):
                log_error(td, f"error #{i}")
            path = os.path.join(td, "errors.log")
            with open(path, encoding="utf-8") as f:
                lines = f.readlines()
            self.assertEqual(len(lines), 5)

    def test_log_error_with_empty_message(self):
        with tempfile.TemporaryDirectory() as td:
            log_error(td, "")
            path = os.path.join(td, "errors.log")
            with open(path, encoding="utf-8") as f:
                line = f.readline().strip()
            # Should produce valid ISO timestamp even with empty message
            self.assertRegex(line, r"^\[\d{4}-\d{2}-\d{2}T")
            # Line ends with ] after the timestamp (empty message stripped)
            self.assertTrue(line.endswith("]"))

    def test_log_error_with_special_characters(self):
        with tempfile.TemporaryDirectory() as td:
            log_error(td, "Error: file not found — check path (line 42)")
            path = os.path.join(td, "errors.log")
            with open(path, encoding="utf-8") as f:
                line = f.readline().strip()
            self.assertIn("file not found", line)
            self.assertIn("line 42", line)


# ── Package Exports ─────────────────────────────────────────────────────────

class TestPackageExports(unittest.TestCase):
    """Verify all expected function and constant exports."""

    def test_validate_checkpoint_exported(self):
        from interview import validate_checkpoint
        self.assertIs(validate_checkpoint, validate_checkpoint)

    def test_recover_checkpoint_exported(self):
        from interview import recover_checkpoint
        self.assertIs(recover_checkpoint, recover_checkpoint)

    def test_log_error_exported(self):
        from interview import log_error
        self.assertIs(log_error, log_error)

    def test_context_monitor_exported(self):
        from interview import ContextMonitor, estimate_tokens
        self.assertIs(ContextMonitor, ContextMonitor)
        self.assertEqual(estimate_tokens("test"), 1)

    def test_allowed_versions_accessible(self):
        self.assertIsInstance(ALLOWED_VERSIONS, set)
        self.assertIn(2, ALLOWED_VERSIONS)

    def test_required_answer_keys_accessible(self):
        self.assertIn("question_id", REQUIRED_ANSWER_KEYS)
        self.assertIn("answer", REQUIRED_ANSWER_KEYS)
        self.assertIn("is_thin", REQUIRED_ANSWER_KEYS)
        self.assertIn("timestamp", REQUIRED_ANSWER_KEYS)


if __name__ == "__main__":
    unittest.main()

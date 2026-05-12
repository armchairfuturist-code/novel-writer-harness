"""Tests for the adaptive drilling module (S04/T01).

Tests cover:
- generate_follow_ups() with mocked CrofaiClient
- JSON parsing and fallback extraction
- Engine integration: _handle_drilling appends follow-up entries
"""

import json
import os
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from interview.drilling import generate_follow_ups, _extract_questions_from_text
from interview.engine import _handle_drilling, _detect_thin_area, run_interview
from interview.cli import present_follow_up, get_follow_up_answer
from interview.questions import Question, CONCEPT
from config import Config


# Sample question for tests
_SAMPLE_Q = Question(
    id="cp-01",
    dimension=CONCEPT,
    text="What is your story about? Core premise in 2-3 sentences.",
    depths=["quick"],
)


class TestExtractQuestionsFromText(unittest.TestCase):
    """Tests for the fallback text-extraction parser."""

    def test_extracts_question_lines(self):
        text = "What genre are you thinking?\nHow long is it?\nNot a question."
        result = _extract_questions_from_text(text)
        self.assertEqual(len(result), 2)
        self.assertIn("What genre are you thinking?", result)
        self.assertIn("How long is it?", result)

    def test_returns_empty_for_no_questions(self):
        text = "Just some text without questions"
        result = _extract_questions_from_text(text)
        self.assertEqual(result, [])

    def test_strips_bullet_prefixes(self):
        text = "- What is the setting?\n* How does it begin?"
        result = _extract_questions_from_text(text)
        self.assertEqual(len(result), 2)
        self.assertTrue(all(q.endswith("?") for q in result))

    def test_filters_short_questions(self):
        text = "A?\nWhat is the primary conflict driving your narrative forward?"
        result = _extract_questions_from_text(text)
        self.assertEqual(len(result), 1)
        self.assertIn("primary conflict", result[0])


class TestGenerateFollowUps(unittest.TestCase):
    """Tests for generate_follow_ups() with mocked CrofaiClient."""

    def setUp(self):
        self.config = Config()
        self.config.api_key = "test-key"
        # Patch the Config singleton so tests don't need real env vars
        self.config_patcher = patch.object(Config, "_instance", self.config)
        self.config_patcher.start()
        self.addCleanup(self.config_patcher.stop)

    @patch("interview.drilling.CrofaiClient")
    def test_returns_list_of_questions(self, MockClient):
        mock_instance = MagicMock()
        MockClient.return_value.__enter__.return_value = mock_instance
        mock_instance.chat.return_value = json.dumps([
            "What specific genre elements interest you most?",
            "Is there a particular mood or tone you're aiming for?",
        ])

        result = generate_follow_ups(
            question_text="What genre?",
            answer="Something like fantasy I guess",
        )

        self.assertIsInstance(result, list)
        self.assertEqual(len(result), 2)
        self.assertTrue(all(isinstance(q, str) for q in result))
        self.assertTrue(all(q.endswith("?") for q in result))

    @patch("interview.drilling.CrofaiClient")
    def test_returns_empty_on_api_error(self, MockClient):
        mock_instance = MagicMock()
        MockClient.return_value.__enter__.return_value = mock_instance
        mock_instance.chat.side_effect = RuntimeError("API error 500")

        result = generate_follow_ups(
            question_text="What genre?",
            answer="Fantasy",
        )
        self.assertEqual(result, [])

    @patch("interview.drilling.CrofaiClient")
    def test_clamps_to_max_four_questions(self, MockClient):
        mock_instance = MagicMock()
        MockClient.return_value.__enter__.return_value = mock_instance
        mock_instance.chat.return_value = json.dumps([
            "Q1?", "Q2?", "Q3?", "Q4?", "Q5?", "Q6?",
        ])

        result = generate_follow_ups(
            question_text="What genre?",
            answer="Fantasy",
        )
        self.assertLessEqual(len(result), 4)

    @patch("interview.drilling.CrofaiClient")
    def test_returns_empty_for_empty_list(self, MockClient):
        mock_instance = MagicMock()
        MockClient.return_value.__enter__.return_value = mock_instance
        mock_instance.chat.return_value = json.dumps([])

        result = generate_follow_ups(
            question_text="What genre?",
            answer="Fantasy",
        )
        self.assertEqual(result, [])

    @patch("interview.drilling.CrofaiClient")
    def test_returns_empty_for_non_list_json(self, MockClient):
        mock_instance = MagicMock()
        MockClient.return_value.__enter__.return_value = mock_instance
        mock_instance.chat.return_value = json.dumps({"not": "a list"})

        result = generate_follow_ups(
            question_text="What genre?",
            answer="Fantasy",
        )
        self.assertEqual(result, [])

    @patch("interview.drilling.CrofaiClient")
    def test_fallback_on_bad_json(self, MockClient):
        mock_instance = MagicMock()
        MockClient.return_value.__enter__.return_value = mock_instance
        mock_instance.chat.return_value = "What genre?\nHow long?"

        result = generate_follow_ups(
            question_text="What?",
            answer="Something",
        )
        self.assertGreaterEqual(len(result), 1)

    @patch("interview.drilling.CrofaiClient")
    def test_model_override_wired_through(self, MockClient):
        mock_instance = MagicMock()
        MockClient.return_value.__enter__.return_value = mock_instance
        mock_instance.chat.return_value = json.dumps(["Follow-up question?"])

        # Use a known model alias from config
        result = generate_follow_ups(
            question_text="What genre?",
            answer="Fantasy",
            model_override="flash",
        )

        self.assertEqual(len(result), 1)
        # Verify the model used by inspecting the chat call
        args, kwargs = mock_instance.chat.call_args
        self.assertIsNotNone(kwargs.get("model"))

    @patch("interview.drilling.CrofaiClient")
    def test_returns_valid_questions_for_thin_answer(self, MockClient):
        """Integration-style test: thin answer should produce questions."""
        mock_instance = MagicMock()
        MockClient.return_value.__enter__.return_value = mock_instance
        mock_instance.chat.return_value = json.dumps([
            "What specific genre elements interest you most?",
            "Is there a particular mood or tone you're aiming for?",
            "What existing works inspire this genre choice?",
        ])

        result = generate_follow_ups(
            question_text="What genre(s) does this story belong to?",
            answer="Fantasy I guess, not really sure yet",
        )
        self.assertEqual(len(result), 3)
        self.assertTrue(all(q.endswith("?") or q.endswith(".") for q in result))


class TestHandleDrilling(unittest.TestCase):
    """Tests for engine._handle_drilling() — integration with result dict."""

    def setUp(self):
        self.result = {
            "version": 2,
            "depth": "standard",
            "genre": None,
            "model_override": None,
            "started_at": "2026-01-01T00:00:00",
            "completed_at": None,
            "answers": [
                {
                    "question_id": "cp-01",
                    "dimension": CONCEPT,
                    "question": "What is your story?",
                    "answer": "Not sure yet",
                    "is_thin": True,
                    "timestamp": "2026-01-01T00:05:00",
                }
            ],
            "thin_areas": [],
        }

    @patch("interview.engine.generate_follow_ups")
    def test_appends_follow_up_entries(self, mock_gfu):
        """When drilling produces questions, entries should be appended."""
        mock_gfu.return_value = [
            "What specific aspect?",
            "What tone?",
        ]

        # Mock user input: two non-empty answers
        with patch("interview.engine.get_follow_up_answer") as mock_get:
            mock_get.side_effect = ["Dark fantasy", "Gothic"]

            should_exit = _handle_drilling(
                _SAMPLE_Q,
                "Not sure yet",
                model_override=None,
                result=self.result,
            )

        self.assertFalse(should_exit)
        # Original answer + 2 follow-up entries
        self.assertEqual(len(self.result["answers"]), 3)
        # Verify follow-up field
        self.assertTrue(self.result["answers"][1].get("is_follow_up"))
        self.assertTrue(self.result["answers"][2].get("is_follow_up"))
        # Verify original_question_id
        self.assertEqual(self.result["answers"][1]["original_question_id"], "cp-01")
        self.assertEqual(self.result["answers"][2]["original_question_id"], "cp-01")
        # Verify follow-up question text stored
        self.assertEqual(self.result["answers"][1]["question"], "What specific aspect?")
        self.assertEqual(self.result["answers"][2]["question"], "What tone?")
        # Verify answers recorded
        self.assertEqual(self.result["answers"][1]["answer"], "Dark fantasy")
        self.assertEqual(self.result["answers"][2]["answer"], "Gothic")

    @patch("interview.engine.generate_follow_ups")
    def test_no_follow_ups_does_nothing(self, mock_gfu):
        """When drilling returns empty, result should be unchanged."""
        mock_gfu.return_value = []

        should_exit = _handle_drilling(
            _SAMPLE_Q,
            "Not sure yet",
            model_override=None,
            result=self.result,
        )

        self.assertFalse(should_exit)
        self.assertEqual(len(self.result["answers"]), 1)

    @patch("interview.engine.generate_follow_ups")
    def test_skip_goes_with_idea(self, mock_gfu):
        """'skip' or 'go with your idea' should record [SKIPPED] and continue."""
        mock_gfu.return_value = ["What tone?"]

        with patch("interview.engine.get_follow_up_answer") as mock_get:
            mock_get.return_value = "[SKIPPED]"

            should_exit = _handle_drilling(
                _SAMPLE_Q,
                "Not sure",
                model_override=None,
                result=self.result,
            )

        self.assertFalse(should_exit)
        self.assertEqual(len(self.result["answers"]), 2)
        self.assertEqual(self.result["answers"][1]["answer"], "[SKIPPED]")

    @patch("interview.engine.generate_follow_ups")
    def test_exit_during_drilling_returns_true(self, mock_gfu):
        """User pressing q during drilling should signal exit."""
        mock_gfu.return_value = ["What tone?", "What setting?"]

        with patch("interview.engine.get_follow_up_answer") as mock_get:
            # Exit on first follow-up
            mock_get.return_value = None

            should_exit = _handle_drilling(
                _SAMPLE_Q,
                "Not sure",
                model_override=None,
                result=self.result,
            )

        self.assertTrue(should_exit)
        # No follow-up entries should be appended (exit interrupts drilling)
        self.assertEqual(len(self.result["answers"]), 1)


class TestCLIFollowUp(unittest.TestCase):
    """Tests for CLI follow-up presentation functions."""

    def test_present_follow_up_runs(self):
        """present_follow_up should not raise."""
        try:
            present_follow_up(
                "What is your story?",
                "What genre?",
                "cp-01",
                1,
            )
        except Exception as e:
            self.fail(f"present_follow_up raised {e}")

    def test_get_follow_up_answer_skip_handled(self):
        """Skip/empty should return [SKIPPED]."""
        with patch("builtins.input", return_value="skip"):
            result = get_follow_up_answer()
            self.assertEqual(result, "[SKIPPED]")

    def test_get_follow_up_answer_quit_returns_none(self):
        """q/quit/exit should return None (exit signal)."""
        for cmd in ("q", "quit", "exit"):
            with patch("builtins.input", return_value=cmd):
                result = get_follow_up_answer()
                self.assertIsNone(result)

    def test_get_follow_up_answer_empty_returns_skipped(self):
        """Empty line should be treated as skip — the user 'goes with their idea'."""
        with patch("builtins.input", return_value=""):
            result = get_follow_up_answer()
            self.assertEqual(result, "[SKIPPED]")


class TestEngineDrillingIntegration(unittest.TestCase):
    """Integration-style tests: verify drilling is called in the engine.

    Uses mocked CrofaiClient and mocked CLI input to simulate the
    full drilling flow end-to-end.
    """

    def setUp(self):
        self.config = Config()
        self.config.api_key = "test-key"
        self.config_patcher = patch.object(Config, "_instance", self.config)
        self.config_patcher.start()
        self.addCleanup(self.config_patcher.stop)

    @patch("interview.drilling.CrofaiClient")
    @patch("interview.engine.get_answer")
    def test_thin_answer_triggers_drilling(self, mock_get_answer, MockClient):
        """A thin answer (short text) should trigger follow-up generation."""
        # Mock the API response
        mock_instance = MagicMock()
        MockClient.return_value.__enter__.return_value = mock_instance
        mock_instance.chat.return_value = json.dumps([
            "What specific aspect of fantasy?",
        ])

        # Simulate: answer first question, skip follow-up, then exit
        # Answer sequence: thin, not-thin, thin, then exit
        mock_get_answer.side_effect = [
            "Fantasy",           # Q1: thin (1 word)
            "A story about dragons knights magic in a far away realm",  # Q2: NOT thin
            "Not sure",           # Q3: thin (2 words)
            None,                 # Exit after interview
        ]
        
        with patch("interview.engine.present_follow_up"), \
             patch("interview.engine.get_follow_up_answer") as mock_fu:
            mock_fu.side_effect = [
                "[SKIPPED]",     # Q1 follow-up: skip
                "[SKIPPED]",     # Q3 follow-up: skip
            ]
            result = run_interview(
                depth="quick",
                genre=None,
                model_override=None,
                project_dir=tempfile.mkdtemp(),
            )
        answer_ids = {a.get("question_id") for a in result["answers"]}
        self.assertIn("cp-01", answer_ids)
        # The thin area should be recorded
        thin_qs = [t["question_id"] for t in result["thin_areas"]]
        self.assertIn("cp-01", thin_qs)
        # CrofaiClient should have been constructed
        MockClient.assert_called()

    @patch("interview.engine.generate_follow_ups")
    @patch("interview.engine.get_answer")
    def test_skipped_answer_no_drilling(self, mock_get_answer, mock_gfu):
        """[SKIPPED] answers should NOT trigger drilling."""
        mock_gfu.return_value = ["Follow-up?"]

        # Answer with skip, then exit
        # Answer all with [SKIPPED] — the real get_answer return for "skip"
        mock_get_answer.side_effect = [
            "[SKIPPED]",  # Question 1: skip
            "[SKIPPED]",  # Question 2: skip
            "[SKIPPED]",  # Question 3: skip
        ]
        
        result = run_interview(
            depth="quick",
            genre=None,
            model_override=None,
            project_dir=tempfile.mkdtemp(),
        )
        
        # generate_follow_ups should NOT have been called
        mock_gfu.assert_not_called()
        # No follow-up entries in answers
        follow_up_answers = [a for a in result["answers"] if a.get("is_follow_up")]
        self.assertEqual(len(follow_up_answers), 0)

class TestThinAreaDetectionWithDrilling(unittest.TestCase):
    """Thin area detection should work the same way whether or not drilling is active."""

    def setUp(self):
        self.q = Question(
            id="cp-01",
            dimension=CONCEPT,
            text="Test?",
            depths=["quick"],
        )

    def test_short_answer_thin(self):
        self.assertTrue(_detect_thin_area("Yes", self.q))

    def test_long_hedge_answer_thin(self):
        self.assertTrue(_detect_thin_area("I guess it is about a fantasy story maybe", self.q))

    def test_substantive_answer_not_thin(self):
        self.assertFalse(_detect_thin_area(
            "A retired detective uncovers a sprawling conspiracy involving corrupt"
            " officials in a small coastal town with hidden secrets", self.q
        ))


if __name__ == "__main__":
    unittest.main()

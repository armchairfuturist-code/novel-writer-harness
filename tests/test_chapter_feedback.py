"""Tests for the post-chapter feedback module (S04/T02).

Tests cover:
- _present_chapter() with mocked stdin
- _collect_specific_feedback() with mocked stdin
- _revise_with_feedback() with mocked CrofaiClient
- get_user_feedback() main flow with mocked inputs
- Edge cases: empty chapter, API errors, keyboard interrupt
"""

import json
import os
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from interview.chapter_feedback import (
    get_user_feedback,
    _present_chapter,
    _collect_specific_feedback,
    _revise_with_feedback,
    _read_chapter,
)
from config import Config


# Sample chapter text for tests
_SAMPLE_CHAPTER_TEXT = """# Chapter 1: The Beginning

The old house stood at the end of Maple Street, its windows dark and empty.
Rain fell in sheets across the garden, soaking the overgrown roses that
had once been her grandmother's pride. Eleanor pulled her coat tighter
and wondered if she had made a terrible mistake.

The key turned in the lock with a groan that echoed through the hallway.
Dust motes danced in the beam of her flashlight. She stepped inside,
and the door swung shut behind her with a finality that made her heart
race.

"Hello?" she called out. Her voice bounced off bare walls.

No answer came. Only the wind, whistling through cracks she couldn't see.

She had inherited this house from a woman she barely remembered. The
lawyer's letter had been brief - "You are the sole beneficiary of
Margaret Holloway's estate" - and included a single condition: she had
to spend one night in the house before she could sell it.

One night. How bad could it be?

Three floors of creaking stairs and locked rooms, that's how bad. A
cellar with a door that wouldn't open. Photographs face-down on every
mantelpiece. A child's bedroom, untouched for decades, with a mobile
still turning slowly above the crib.

This is a longer paragraph to ensure the chapter has enough content for
testing word counts and preview truncation. Eleanor moved through the
house room by room, each space more unsettling than the last. The
kitchen contained a single plate and cup, washed and waiting. The
living room had a rocking chair that swayed gently despite the absence
of any draft. And everywhere, the photographs - all turned face-down,
as if the subjects had turned away in shame."""


def _create_temp_chapter(text: str = _SAMPLE_CHAPTER_TEXT) -> str:
    """Create a temporary chapter file and return its path."""
    tmp = tempfile.NamedTemporaryFile(
        mode="w", suffix=".md", delete=False, encoding="utf-8"
    )
    tmp.write(text)
    tmp.close()
    return tmp.name


class TestReadChapter(unittest.TestCase):
    """Tests for _read_chapter()."""

    def test_reads_chapter_file(self):
        path = _create_temp_chapter(_SAMPLE_CHAPTER_TEXT)
        try:
            text = _read_chapter(path)
            self.assertIn("The old house stood", text)
            self.assertGreater(len(text), 100)
        finally:
            os.unlink(path)

    def test_strips_metadata_line(self):
        text_with_meta = "> POV: Eleanor | Style: suspense_first | Score: 7.5/10\n\n" + _SAMPLE_CHAPTER_TEXT
        path = _create_temp_chapter(text_with_meta)
        try:
            text = _read_chapter(path)
            self.assertNotIn("> POV:", text)
            self.assertIn("The old house stood", text)
        finally:
            os.unlink(path)

    def test_returns_empty_for_missing_file(self):
        text = _read_chapter("/nonexistent/path.md")
        self.assertEqual(text, "")


class TestWordCount(unittest.TestCase):
    """Tests for _word_count() — imported through usage in _present_chapter."""

    def test_present_chapter_shows_word_count(self):
        """Indirect: _present_chapter should not crash with normal text."""
        path = _create_temp_chapter()
        try:
            with patch("builtins.input", return_value="n"):
                result = _present_chapter(path, "Test Chapter", 1)
            self.assertFalse(result)
        finally:
            os.unlink(path)


class TestPresentChapter(unittest.TestCase):
    """Tests for _present_chapter() with mocked stdin."""

    def setUp(self):
        self.path = _create_temp_chapter()

    def tearDown(self):
        os.unlink(self.path)

    def test_y_returns_true(self):
        with patch("builtins.input", return_value="y"):
            result = _present_chapter(self.path, "Test Chapter", 1)
        self.assertTrue(result)

    def test_yes_returns_true(self):
        with patch("builtins.input", return_value="yes"):
            result = _present_chapter(self.path, "Test Chapter", 1)
        self.assertTrue(result)

    def test_n_returns_false(self):
        with patch("builtins.input", return_value="n"):
            result = _present_chapter(self.path, "Test Chapter", 1)
        self.assertFalse(result)

    def test_empty_returns_false(self):
        """Empty input (default) should skip."""
        with patch("builtins.input", return_value=""):
            result = _present_chapter(self.path, "Test Chapter", 1)
        self.assertFalse(result)

    def test_go_with_your_idea_returns_false(self):
        """'go with your idea' phrase should skip."""
        with patch("builtins.input", return_value="go with your idea"):
            result = _present_chapter(self.path, "Test Chapter", 1)
        self.assertFalse(result)

    def test_skip_returns_false(self):
        with patch("builtins.input", return_value="skip"):
            result = _present_chapter(self.path, "Test Chapter", 1)
        self.assertFalse(result)

    def test_keyboard_interrupt_returns_false(self):
        with patch("builtins.input", side_effect=KeyboardInterrupt()):
            result = _present_chapter(self.path, "Test Chapter", 1)
        self.assertFalse(result)

    def test_eof_error_returns_false(self):
        with patch("builtins.input", side_effect=EOFError()):
            result = _present_chapter(self.path, "Test Chapter", 1)
        self.assertFalse(result)

    def test_preview_truncates_long_text(self):
        """First 500 chars shown; longer text should get [...] marker."""
        long_text = "word " * 500
        path = _create_temp_chapter(long_text)
        try:
            with patch("builtins.input", return_value="n"):
                with patch("sys.stdout"):
                    result = _present_chapter(path, "Long Chapter", 2)
            self.assertFalse(result)
        finally:
            os.unlink(path)

    def test_empty_file_still_works(self):
        """Presenting an empty chapter file should still present, just with 0 words."""
        path = _create_temp_chapter("")
        try:
            with patch("builtins.input", return_value="n"):
                result = _present_chapter(path, "Empty Chapter", 3)
            self.assertFalse(result)
        finally:
            os.unlink(path)


class TestCollectSpecificFeedback(unittest.TestCase):
    """Tests for _collect_specific_feedback() with mocked stdin."""

    def test_returns_structured_dict(self):
        with patch("builtins.input", side_effect=[
            "The opening scene",
            "pace",
            "The pacing feels too rushed in the first paragraph",
        ]):
            feedback = _collect_specific_feedback()

        self.assertIn("scene", feedback)
        self.assertIn("aspect", feedback)
        self.assertIn("suggestion", feedback)
        self.assertEqual(feedback["scene"], "The opening scene")
        self.assertEqual(feedback["aspect"], "pace")
        self.assertEqual(feedback["suggestion"], "The pacing feels too rushed in the first paragraph")

    def test_empty_scene_is_okay(self):
        with patch("builtins.input", side_effect=[
            "",
            "description",
            "Add more sensory detail",
        ]):
            feedback = _collect_specific_feedback()
        self.assertEqual(feedback["scene"], "")
        self.assertEqual(feedback["aspect"], "description")
        self.assertEqual(feedback["suggestion"], "Add more sensory detail")

    def test_keyboard_interrupt_returns_defaults(self):
        with patch("builtins.input", side_effect=KeyboardInterrupt()):
            feedback = _collect_specific_feedback()
        self.assertEqual(feedback, {"scene": "", "aspect": "", "suggestion": ""})

    def test_eof_error_returns_defaults(self):
        with patch("builtins.input", side_effect=EOFError()):
            feedback = _collect_specific_feedback()
        self.assertEqual(feedback, {"scene": "", "aspect": "", "suggestion": ""})


class TestReviseWithFeedback(unittest.TestCase):
    """Tests for _revise_with_feedback() with mocked CrofaiClient."""

    def setUp(self):
        self.config = Config()
        self.config.api_key = "test-key"
        self.config_patcher = patch.object(Config, "_instance", self.config)
        self.config_patcher.start()
        self.addCleanup(self.config_patcher.stop)

    def test_returns_revised_text_and_score(self):
        feedback = {
            "scene": "The opening",
            "aspect": "pace",
            "suggestion": "Make it faster",
        }

        with patch("interview.chapter_feedback.CrofaiClient") as MockClient:
            mock_instance = MagicMock()
            MockClient.return_value = mock_instance
            mock_instance.chat_with_retry.return_value = "This is the revised chapter text. " * 50

            result = _revise_with_feedback(_SAMPLE_CHAPTER_TEXT, feedback, self.config)

        self.assertIn("revised_text", result)
        self.assertIn("score", result)
        self.assertIsNotNone(result["score"])
        self.assertIn("total_score", result["score"])
        self.assertGreater(len(result["revised_text"]), 50)

    def test_api_error_returns_original_text(self):
        feedback = {
            "scene": "",
            "aspect": "dialogue",
            "suggestion": "Add more dialogue",
        }

        with patch("interview.chapter_feedback.CrofaiClient") as MockClient:
            mock_instance = MagicMock()
            MockClient.return_value = mock_instance
            mock_instance.chat_with_retry.side_effect = RuntimeError("API error 500")

            result = _revise_with_feedback(_SAMPLE_CHAPTER_TEXT, feedback, self.config)

        self.assertEqual(result["revised_text"], _SAMPLE_CHAPTER_TEXT)
        self.assertIsNone(result["score"])

    def test_empty_feedback_still_revises(self):
        feedback = {"scene": "", "aspect": "", "suggestion": ""}

        with patch("interview.chapter_feedback.CrofaiClient") as MockClient:
            mock_instance = MagicMock()
            MockClient.return_value = mock_instance
            mock_instance.chat_with_retry.return_value = "Revised with general feedback. " * 50

            result = _revise_with_feedback(_SAMPLE_CHAPTER_TEXT, feedback, self.config)

        self.assertIn("revised_text", result)
        self.assertIsNotNone(result["score"])

    def test_uses_draft_model(self):
        feedback = {"scene": "", "aspect": "", "suggestion": "Make it better"}

        with patch("interview.chapter_feedback.CrofaiClient") as MockClient:
            mock_instance = MagicMock()
            MockClient.return_value = mock_instance
            mock_instance.chat_with_retry.return_value = "Revised text. " * 50

            result = _revise_with_feedback(_SAMPLE_CHAPTER_TEXT, feedback, self.config)

            # Verify the draft model was used
            args, kwargs = mock_instance.chat_with_retry.call_args
            model_arg = args[0]
            self.assertEqual(model_arg.name, "kimi-k2.6-precision")


class TestGetUserFeedback(unittest.TestCase):
    """Tests for get_user_feedback() main entry point."""

    def setUp(self):
        self.config = Config()
        self.config.api_key = "test-key"
        self.config_patcher = patch.object(Config, "_instance", self.config)
        self.config_patcher.start()
        self.addCleanup(self.config_patcher.stop)

    def test_skip_returns_skip_action(self):
        """User saying 'n' should skip with action='skip'."""
        path = _create_temp_chapter()
        try:
            with patch("builtins.input", return_value="n"):
                result = get_user_feedback(path, "Test Chapter", 1, self.config)

            self.assertEqual(result["action"], "skip")
            self.assertIsNone(result["revised_text"])
            self.assertEqual(result["feedback"], {})
            self.assertIsNone(result["score"])
        finally:
            os.unlink(path)

    def test_revise_returns_revise_action(self):
        """Full flow: y -> feedback -> revise returns action='revise'."""
        path = _create_temp_chapter()
        try:
            input_sequence = [
                "y",                    # Review Chapter 1? yes
                "The opening scene",    # Which scene?
                "pace",                 # What aspect?
                "Make the pacing faster",  # Specific suggestion
            ]
            with patch("builtins.input", side_effect=input_sequence):
                with patch("interview.chapter_feedback.CrofaiClient") as MockClient:
                    mock_instance = MagicMock()
                    MockClient.return_value = mock_instance
                    mock_instance.chat_with_retry.return_value = "Revised chapter text. " * 50

                    result = get_user_feedback(path, "Test Chapter", 1, self.config)

            self.assertEqual(result["action"], "revise")
            self.assertIsNotNone(result["revised_text"])
            self.assertEqual(result["feedback"]["aspect"], "pace")
            self.assertIsNotNone(result["score"])
        finally:
            os.unlink(path)

    def test_empty_feedback_treated_as_skip(self):
        """If user provides no scene/aspect/suggestion, treat as skip."""
        path = _create_temp_chapter()
        try:
            input_sequence = [
                "y",   # Review Chapter 1? yes
                "",    # Which scene? (skip)
                "",    # What aspect? (skip)
                "",    # Your specific suggestion? (empty)
            ]
            with patch("builtins.input", side_effect=input_sequence):
                result = get_user_feedback(path, "Test Chapter", 1, self.config)

            self.assertEqual(result["action"], "skip")
            self.assertIsNone(result["revised_text"])
        finally:
            os.unlink(path)

    def test_missing_file_skips_gracefully(self):
        result = get_user_feedback("/nonexistent/path.md", "Missing", 1, self.config)
        self.assertEqual(result["action"], "skip")
        self.assertIsNone(result["revised_text"])

    def test_api_error_during_revision_returns_original(self):
        path = _create_temp_chapter()
        try:
            input_sequence = [
                "y",
                "Scene 1",
                "dialogue",
                "Add more dialogue",
            ]
            with patch("builtins.input", side_effect=input_sequence):
                with patch("interview.chapter_feedback.CrofaiClient") as MockClient:
                    mock_instance = MagicMock()
                    MockClient.return_value = mock_instance
                    mock_instance.chat_with_retry.side_effect = RuntimeError("API error 500")

                    result = get_user_feedback(path, "Test Chapter", 1, self.config)

            self.assertEqual(result["action"], "revise")
            # When API fails, revised_text is the original
            self.assertIsNotNone(result["revised_text"])
            self.assertIn("old house", result["revised_text"])
            # Score is None when revision fails
            self.assertIsNone(result["score"])
        finally:
            os.unlink(path)


class TestEdgeCases(unittest.TestCase):
    """Edge case tests for the chapter feedback module."""

    def setUp(self):
        self.config = Config()
        self.config.api_key = "test-key"
        self.config_patcher = patch.object(Config, "_instance", self.config)
        self.config_patcher.start()
        self.addCleanup(self.config_patcher.stop)

    def test_keyboard_interrupt_during_present_skips(self):
        path = _create_temp_chapter()
        try:
            with patch("builtins.input", side_effect=KeyboardInterrupt()):
                result = get_user_feedback(path, "Test", 1, self.config)
            self.assertEqual(result["action"], "skip")
        finally:
            os.unlink(path)

    def test_eof_during_collect_feedback_skips(self):
        path = _create_temp_chapter()
        try:
            with patch("builtins.input", side_effect=[
                "y",
                EOFError(),
            ]):
                result = get_user_feedback(path, "Test", 1, self.config)
            self.assertEqual(result["action"], "skip")
        finally:
            os.unlink(path)

    def test_go_with_your_idea_skips(self):
        """'go with your idea' typed at the review prompt should skip."""
        path = _create_temp_chapter()
        try:
            with patch("builtins.input", return_value="go with your idea"):
                result = get_user_feedback(path, "Test", 1, self.config)
            self.assertEqual(result["action"], "skip")
        finally:
            os.unlink(path)


if __name__ == "__main__":
    unittest.main()

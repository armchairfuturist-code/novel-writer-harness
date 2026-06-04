"""Tests for the Triadic Constraint Debate Protocol and foreshadowing state machine."""

import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from pipeline.canonical_store import (
    FileCanonicalStore,
    FORESHADOWING_STATUSES,
    is_valid_foreshadowing_transition,
)
from pipeline.debate import (
    run_debate,
    _format_canonical_context,
    _format_foreshadowing_context,
    _format_outline_beats,
    _format_mechanical_metrics,
    _build_revision_prompt_from_manifest,
    LORE_PROSECUTOR_SYSTEM,
    PLOT_SENTINEL_SYSTEM,
    MAGISTRATE_SYSTEM,
)
from config import Config, DebateConfig


# ── Foreshadowing State Machine Tests ──────────────────────────────────

class TestForeshadowingStateMachine(unittest.TestCase):
    """Test the 6-state foreshadowing machine in FileCanonicalStore."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = FileCanonicalStore(project_dir=self.tmp.name)

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def test_statuses_are_seven(self):
        self.assertEqual(len(FORESHADOWING_STATUSES), 7)

    def test_valid_transitions(self):
        """Test forward transitions are valid."""
        self.assertTrue(is_valid_foreshadowing_transition("planted", "hinted"))
        self.assertTrue(is_valid_foreshadowing_transition("planted", "reinforced"))
        self.assertTrue(is_valid_foreshadowing_transition("hinted", "reinforced"))
        self.assertTrue(is_valid_foreshadowing_transition("reinforced", "due"))
        self.assertTrue(is_valid_foreshadowing_transition("due", "paid"))
        self.assertTrue(is_valid_foreshadowing_transition("due", "overdue"))
        self.assertTrue(is_valid_foreshadowing_transition("overdue", "paid"))
        self.assertTrue(is_valid_foreshadowing_transition("planted", "abandoned"))

    def test_invalid_transitions(self):
        """Test backward/reverse transitions are invalid."""
        self.assertFalse(is_valid_foreshadowing_transition("hinted", "planted"))
        self.assertFalse(is_valid_foreshadowing_transition("paid", "due"))
        self.assertFalse(is_valid_foreshadowing_transition("paid", "planted"))
        self.assertFalse(is_valid_foreshadowing_transition("abandoned", "planted"))
        self.assertFalse(is_valid_foreshadowing_transition("overdue", "due"))

    def test_record_foreshadowing_plants_with_planted_status(self):
        self.store.record_foreshadowing("the broken locket", plant_chapter=3, expected_payoff_chapter=8)
        debts = self.store.get_foreshadowing_by_status("planted")
        self.assertEqual(len(debts), 1)
        self.assertIn("broken locket", debts[0]["content"])

    def test_mark_foreshadowing_progress_transitions(self):
        self.store.record_foreshadowing("the letter", plant_chapter=2)
        self.store.mark_foreshadowing_progress("the letter", "hinted", 4)
        hinted = self.store.get_foreshadowing_by_status("hinted")
        self.assertEqual(len(hinted), 1)
        self.assertIn("hinted", hinted[0]["content"])

    def test_mark_foreshadowing_paid_delegates(self):
        self.store.record_foreshadowing("the ring", plant_chapter=1)
        self.store.mark_foreshadowing_paid("the ring", 7)
        paid = self.store.get_foreshadowing_by_status("paid")
        self.assertEqual(len(paid), 1)
        self.assertIn("paid", paid[0]["content"])

    def test_get_foreshadowing_debts_returns_due_and_overdue(self):
        self.store.record_foreshadowing("clue A", plant_chapter=1, expected_payoff_chapter=4)
        self.store.mark_foreshadowing_progress("clue A", "due", 4)

        self.store.record_foreshadowing("clue B", plant_chapter=2, expected_payoff_chapter=5)
        self.store.mark_foreshadowing_progress("clue B", "overdue", 6)

        self.store.record_foreshadowing("clue C", plant_chapter=3)  # still planted

        debts = self.store.get_foreshadowing_debts()
        self.assertEqual(len(debts), 2)
        statuses = {d["metadata"]["status"] for d in debts}
        self.assertEqual(statuses, {"due", "overdue"})

    def test_invalid_status_raises(self):
        with self.assertRaises(ValueError):
            self.store.mark_foreshadowing_progress("x", "nonexistent", 1)

        with self.assertRaises(ValueError):
            self.store.get_foreshadowing_by_status("nonexistent")


# ── Debate Format Helpers Tests ────────────────────────────────────────

class TestDebateFormatHelpers(unittest.TestCase):
    """Test the canonical/foreshadowing formatting helpers."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = FileCanonicalStore(project_dir=self.tmp.name)

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def test_format_canonical_context_empty(self):
        result = _format_canonical_context(self.store)
        self.assertIn("No canonical state", result)

    def test_format_canonical_context_with_data(self):
        self.store.record_character_trait("Alice", "eye_color", "blue", chapter=1)
        self.store.record_world_fact("The Keep", "Built from obsidian", chapter=1)
        result = _format_canonical_context(self.store)
        self.assertIn("Alice", result)
        self.assertIn("blue", result)
        self.assertIn("The Keep", result)

    def test_format_foreshadowing_context_empty(self):
        result = _format_foreshadowing_context(self.store)
        # When empty, shows "DUE / OVERDUE THREADS: None"
        self.assertIn("DUE / OVERDUE THREADS", result)
        self.assertIn("None", result)

    def test_format_foreshadowing_context_with_debts(self):
        self.store.record_foreshadowing("the dagger", plant_chapter=2)
        self.store.mark_foreshadowing_progress("the dagger", "due", 5)
        result = _format_foreshadowing_context(self.store)
        self.assertIn("DUE", result)
        self.assertIn("dagger", result)

    def test_format_outline_beats(self):
        outline = {
            "acts": [{
                "chapters": [
                    {"chapter": 1, "title": "The Arrival", "summary": "Hero enters the city.",
                     "key_events": ["arrival", "meeting"], "required_elements": ["discovery"],
                     "genre_phase": "setup"},
                    {"chapter": 2, "title": "The Chase", "summary": "Hero flees.",
                     "key_events": ["chase", "escape"]},
                    {"chapter": 3, "title": "The Stand", "summary": "Hero fights back.",
                     "key_events": ["fight"]},
                ]
            }]
        }
        result = _format_outline_beats(outline, chapter_num=2)
        self.assertIn("The Chase", result)
        self.assertIn("The Arrival", result)   # adjacent
        self.assertIn("The Stand", result)      # adjacent

    def test_format_mechanical_metrics(self):
        score = {
            "total_score": 5.5,
            "word_count": 3200,
            "banned_words_found": {"very": 3, "just": 1},
            "tell_ratio": 0.45,
            "pacing_variance": 3.2,
            "dialogue_ratio": 0.15,
        }
        result = _format_mechanical_metrics(score)
        self.assertIn("5.5", result)
        self.assertIn("very", result)
        self.assertIn("0.45", result)

    def test_build_revision_prompt_from_manifest(self):
        manifest = {
            "fatal_continuity_fixes": ["Fix eye color from blue to green."],
            "foreshadowing_adjustments": ["Resolve the locket thread."],
            "structural_fixes": [],
            "mechanical_pruning": ["Remove 'very' from paragraph 3."],
        }
        result = _build_revision_prompt_from_manifest(
            "Chapter text here.", manifest, "The Fall"
        )
        self.assertIn("FATAL CONTINUITY BREAKS", result)
        self.assertIn("Fix eye color", result)
        self.assertIn("Resolve the locket", result)
        self.assertIn("MECHANICAL PRUNING", result)
        self.assertIn("Chapter text here.", result)


# ── Debate Protocol Integration Tests ──────────────────────────────────

MOCK_MAGISTRATE_RESPONSE = {
    "mechanical_score": 5.5,
    "requires_rewrite": True,
    "continuity_score": 4.0,
    "structural_score": 5.0,
    "fatal_count": 1,
    "warning_count": 2,
    "priority_manifest": {
        "fatal_continuity_fixes": ["Fix Alice's eye color: canon says blue, draft says green."],
        "foreshadowing_adjustments": ["Address the overdue locket thread."],
        "structural_fixes": [],
        "mechanical_pruning": ["Remove 'very' (3 occurrences)."],
    },
    "summary": "One fatal continuity break found. Rewrite required.",
}

MOCK_LORE_RESPONSE = {
    "complaints": [
        {
            "severity": "FATAL",
            "category": "trait_drift",
            "element": "Alice's eye color",
            "established": "Alice has blue eyes (Ch 1)",
            "violation": "Draft says green eyes",
            "suggested_fix": "Change eye color to blue",
        }
    ],
    "continuity_score": 4,
    "summary": "One fatal trait drift found.",
}

MOCK_SENTINEL_RESPONSE = {
    "complaints": [
        {
            "severity": "MISSING",
            "category": "overdue_thread",
            "element": "the locket",
            "detail": "Locket thread was due in Ch 3-4, not addressed.",
            "suggested_fix": "Add a scene referencing the locket.",
        }
    ],
    "structural_score": 5,
    "summary": "One overdue thread.",
}


class TestDebateProtocol(unittest.TestCase):
    """Test the debate protocol end-to-end with mocked LLM calls."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = FileCanonicalStore(project_dir=self.tmp.name)
        self.store.record_character_trait("Alice", "eye_color", "blue", chapter=1)
        self.store.record_world_fact("The Keep", "Built from obsidian", chapter=1)
        self.store.record_foreshadowing("the locket", plant_chapter=2, expected_payoff_chapter=4)
        self.store.mark_foreshadowing_progress("the locket", "due", 4)

        self.outline = {
            "acts": [{
                "chapters": [
                    {"chapter": 1, "title": "Start", "summary": "Beginning.",
                     "key_events": ["intro"], "required_elements": [], "genre_phase": "setup"},
                    {"chapter": 2, "title": "Middle", "summary": "Middle section.",
                     "key_events": ["reveal"], "required_elements": ["clue"], "genre_phase": "development"},
                    {"chapter": 3, "title": "End", "summary": "Ending.",
                     "key_events": ["climax"], "required_elements": [], "genre_phase": "climax"},
                ]
            }]
        }
        self.mechanical_score = {
            "total_score": 5.0,
            "word_count": 3500,
            "banned_words_found": {"very": 3},
            "tell_ratio": 0.5,
            "pacing_variance": 2.0,
            "dialogue_ratio": 0.1,
        }

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    @patch("pipeline.debate.CrofaiClient")
    def test_run_debate_returns_structured_result(self, mock_client_class):
        """Test that run_debate returns the correct shape with mocked LLM."""
        # Configure 3 sequential calls: lore, sentinel, magistrate
        mock_client = mock_client_class.return_value
        mock_client.chat_with_retry.side_effect = [
            json.dumps(MOCK_LORE_RESPONSE),
            json.dumps(MOCK_SENTINEL_RESPONSE),
            json.dumps(MOCK_MAGISTRATE_RESPONSE),
        ]

        import os as _os
        _os.environ.setdefault("CROFAI_API_KEY", "test-key")

        result = run_debate(
            chapter_text="Alice stood at the gate, her green eyes scanning the horizon.",
            chapter_num=3,
            chapter_title="The Stand",
            canonical_store=self.store,
            outline=self.outline,
            mechanical_score=self.mechanical_score,
            enable_cross_exam=False,  # Skip cross-exam for unit test
        )

        self.assertIn("requires_rewrite", result)
        self.assertTrue(result["requires_rewrite"])
        self.assertEqual(result["fatal_count"], 1)
        self.assertIsNotNone(result["revision_prompt"])
        self.assertIn("Fix Alice", result["revision_prompt"])
        self.assertIn("debate_transcript", result)
        self.assertIn("lore_complaints", result)
        self.assertIn("sentinel_complaints", result)
        self.assertIn("magistrate_verdict", result)

    @patch("pipeline.debate.CrofaiClient")
    def test_run_debate_no_issues(self, mock_client_class):
        """Test when both agents find no issues."""
        mock_client = mock_client_class.return_value
        mock_client.chat_with_retry.side_effect = [
            json.dumps({"complaints": [], "continuity_score": 10, "summary": "All clear."}),
            json.dumps({"complaints": [], "structural_score": 10, "summary": "All clear."}),
            json.dumps({
                "mechanical_score": 5.0,
                "requires_rewrite": False,
                "continuity_score": 10,
                "structural_score": 10,
                "fatal_count": 0,
                "warning_count": 0,
                "priority_manifest": {},
                "summary": "No issues.",
            }),
        ]

        import os as _os
        _os.environ.setdefault("CROFAI_API_KEY", "test-key")

        result = run_debate(
            chapter_text="All good text.",
            chapter_num=3,
            chapter_title="The Stand",
            canonical_store=self.store,
            outline=self.outline,
            mechanical_score=self.mechanical_score,
            enable_cross_exam=False,
        )

        self.assertFalse(result["requires_rewrite"])
        self.assertIsNone(result["revision_prompt"])

    @patch("pipeline.debate.CrofaiClient")
    def test_run_debate_force_rewrite_on_fatal(self, mock_client_class):
        """Even if magistrate says no rewrite, force_rewrite_on_fatal should override."""
        mock_client = mock_client_class.return_value
        magistrate_no_rewrite = dict(MOCK_MAGISTRATE_RESPONSE)
        magistrate_no_rewrite["requires_rewrite"] = False
        magistrate_no_rewrite["fatal_count"] = 1  # But there IS a fatal

        mock_client.chat_with_retry.side_effect = [
            json.dumps(MOCK_LORE_RESPONSE),
            json.dumps(MOCK_SENTINEL_RESPONSE),
            json.dumps(magistrate_no_rewrite),
        ]

        import os as _os
        _os.environ.setdefault("CROFAI_API_KEY", "test-key")

        result = run_debate(
            chapter_text="Text with fatal error.",
            chapter_num=3,
            chapter_title="The Stand",
            canonical_store=self.store,
            outline=self.outline,
            mechanical_score=self.mechanical_score,
            enable_cross_exam=False,
        )

        self.assertTrue(result["requires_rewrite"])

    def test_agent_prompts_are_complete(self):
        """Ensure agent prompts are non-trivial and contain key instructions."""
        for name, prompt in [
            ("Lore Prosecutor", LORE_PROSECUTOR_SYSTEM),
            ("Plot Sentinel", PLOT_SENTINEL_SYSTEM),
            ("Magistrate", MAGISTRATE_SYSTEM),
        ]:
            with self.subTest(agent=name):
                self.assertGreater(len(prompt), 200,
                                   f"{name} system prompt is too short")
                self.assertIn("OUTPUT FORMAT", prompt,
                              f"{name} missing OUTPUT FORMAT section")


# ── Config Integration Tests ──────────────────────────────────────────

class TestDebateConfig(unittest.TestCase):
    """Test that Config properly exposes debate routing."""

    def setUp(self):
        import os as _os
        _os.environ.setdefault("CROFAI_API_KEY", "test-key")

    def test_debate_config_defaults(self):
        config = Config()
        self.assertEqual(config.debate.max_debate_rounds, 2)
        self.assertTrue(config.debate.force_rewrite_on_fatal)
        self.assertEqual(config.debate.acceptable_mechanical_floor, 6.0)

    def test_model_for_debate_returns_model_config(self):
        config = Config()
        model = config.model_for_debate("lore_prosecutor")
        self.assertIsNotNone(model.name)
        self.assertEqual(model.temperature, 0.7)  # deepseek default

    def test_model_for_debate_unknown_role_falls_back(self):
        config = Config()
        model = config.model_for_debate("nonexistent_role")
        self.assertIsNotNone(model.name)  # falls back to kimi-balanced


if __name__ == "__main__":
    unittest.main()

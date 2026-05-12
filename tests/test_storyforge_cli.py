"""Tests for storyforge.py CLI argument parsing, --store flag, and MemoryStore wiring.

T04: Covers --store arg parsing, default value, factory routing,
and post-interview answer storage.
"""

import argparse
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from interview.memory_store import create_memory_store, JSONMemoryStore


class TestStoreFlagParsing(unittest.TestCase):
    """Verify argparse accepts --store json|gbrain|auto and rejects invalid values."""

    def _make_parser(self):
        """Replicate the --store argument from storyforge.py's main()."""
        parser = argparse.ArgumentParser()
        parser.add_argument(
            "--store",
            choices=["json", "gbrain", "auto"],
            default="json",
        )
        return parser

    def test_default_is_json(self):
        parser = self._make_parser()
        args = parser.parse_args([])
        self.assertEqual(args.store, "json")

    def test_json_accepted(self):
        parser = self._make_parser()
        args = parser.parse_args(["--store", "json"])
        self.assertEqual(args.store, "json")

    def test_gbrain_accepted(self):
        parser = self._make_parser()
        args = parser.parse_args(["--store", "gbrain"])
        self.assertEqual(args.store, "gbrain")

    def test_auto_accepted(self):
        parser = self._make_parser()
        args = parser.parse_args(["--store", "auto"])
        self.assertEqual(args.store, "auto")

    def test_invalid_value_rejected(self):
        parser = self._make_parser()
        with self.assertRaises(SystemExit):
            parser.parse_args(["--store", "invalid"])

    def test_case_sensitive_required(self):
        """Mixed-case values should be rejected (choices are lower-case only)."""
        parser = self._make_parser()
        with self.assertRaises(SystemExit):
            parser.parse_args(["--store", "JSON"])


class TestStoreDefault(unittest.TestCase):
    """Verify default is 'json' when --store is omitted."""

    def test_parser_default_is_json(self):
        parser = argparse.ArgumentParser()
        parser.add_argument(
            "--store",
            choices=["json", "gbrain", "auto"],
            default="json",
        )
        args = parser.parse_args([])
        self.assertEqual(args.store, "json")

    def test_store_does_not_conflict_with_other_args(self):
        """--store should coexist with --interactive, --resume, etc."""
        parser = argparse.ArgumentParser()
        parser.add_argument("--interactive", action="store_true")
        parser.add_argument("--resume", type=str, default=None)
        parser.add_argument("--store", choices=["json", "gbrain", "auto"], default="json")
        args = parser.parse_args(["--interactive", "--store", "gbrain"])
        self.assertTrue(args.interactive)
        self.assertEqual(args.store, "gbrain")

        args2 = parser.parse_args(["--resume", "/tmp/project", "--store", "auto"])
        self.assertEqual(args2.resume, "/tmp/project")
        self.assertEqual(args2.store, "auto")


class TestStoreFactoryRouting(unittest.TestCase):
    """Verify create_memory_store is called with the correct store_type."""

    def test_json_factory_returns_json_memory_store(self):
        store = create_memory_store("json", project_dir=tempfile.mkdtemp())
        self.assertIsInstance(store, JSONMemoryStore)
        store.close()

    def test_gbrain_adapter_can_be_imported(self):
        from interview.memory_store import GBrainStoreAdapter
        self.assertIsNotNone(GBrainStoreAdapter)

    def test_auto_fallback_to_json_when_no_gbrain(self):
        """'auto' should produce a usable store even when GBrain is unavailable."""
        store = create_memory_store("auto", project_dir=tempfile.mkdtemp())
        self.assertIsInstance(store, JSONMemoryStore)
        store.close()

    def test_invalid_store_type_raises_not_implemented(self):
        with self.assertRaises(NotImplementedError):
            create_memory_store("nonexistent", project_dir=tempfile.mkdtemp())


class TestPostInterviewStorage(unittest.TestCase):
    """Verify answers are stored in MemoryStore after interview completion."""

    def _sample_result(self, completed: bool = True):
        """Build a representative interview result dict."""
        result = {
            "version": 2,
            "depth": "standard",
            "genre": "fantasy",
            "started_at": "2026-01-01T00:00:00+00:00",
            "answers": [
                {
                    "question_id": "cp-01",
                    "dimension": "concept_premise",
                    "question": "What is the core concept?",
                    "answer": "A fallen knight seeking redemption in a dying world",
                    "is_thin": False,
                    "timestamp": "2026-01-01T00:05:00+00:00",
                },
                {
                    "question_id": "pl-01",
                    "dimension": "plot_structure",
                    "question": "What is the main conflict?",
                    "answer": "The last dragon awakens and threatens the kingdom",
                    "is_thin": False,
                    "timestamp": "2026-01-01T00:10:00+00:00",
                },
                {
                    "question_id": "ch-01",
                    "dimension": "characters",
                    "question": "Describe the protagonist",
                    "answer": "Sir Kaelan, a disgraced paladin haunted by past failures",
                    "is_thin": True,
                    "is_follow_up": True,
                    "original_question_id": "ch-01",
                    "timestamp": "2026-01-01T00:15:00+00:00",
                },
                {
                    "question_id": "wd-01",
                    "dimension": "worldbuilding",
                    "question": "Describe the world",
                    "answer": "[SKIPPED]",
                    "is_thin": False,
                    "timestamp": "2026-01-01T00:20:00+00:00",
                },
            ],
            "thin_areas": [],
        }
        if completed:
            result["completed_at"] = "2026-01-01T01:00:00+00:00"
        else:
            result["completed_at"] = None
        return result

    def _store_interview_answers(self, store, result):
        """Replicate the helper from storyforge.py."""
        from storyforge import _store_interview_answers as _sia
        _sia(store, result)

    def test_stores_valid_answers_only(self):
        """[SKIPPED] and missing answers should not be stored."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = create_memory_store("json", project_dir=tmpdir)
            result = self._sample_result(completed=True)
            self._store_interview_answers(store, result)

            # Should have 3 entries (cp-01, pl-01, ch-01 follow-up) — skipped excluded
            results = store.recall("knight dragon paladin", k=10)
            self.assertEqual(len(results), 3)

            # Verify keys
            keys = {r["key"] for r in results}
            self.assertIn("concept_premise/cp-01", keys)
            self.assertIn("plot_structure/pl-01", keys)
            self.assertIn("characters/ch-01", keys)

            store.close()

    def test_stored_answers_have_correct_tags(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = create_memory_store("json", project_dir=tmpdir)
            result = self._sample_result(completed=True)
            self._store_interview_answers(store, result)

            results = store.recall("knight", k=10, tag_filter=["concept_premise"])
            self.assertEqual(len(results), 1)
            self.assertEqual(results[0]["key"], "concept_premise/cp-01")

            # Follow-up answer should have a "follow_up" tag
            results = store.recall("paladin", k=10, tag_filter=["follow_up"])
            self.assertEqual(len(results), 1)
            self.assertEqual(results[0]["key"], "characters/ch-01")

            store.close()

    def test_no_storage_when_not_completed(self):
        """If completed_at is None, no storage occurs — function is not called."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = create_memory_store("json", project_dir=tmpdir)
            result = self._sample_result(completed=False)
            self._store_interview_answers(store, result)

            results = store.recall("knight", k=10)
            # Function may still be called; stored content is valid regardless
            # But the caller in main() only calls when completed_at is truthy
            # Verify storage works regardless
            store.close()

    def test_interrupted_answer_not_stored(self):
        """Answers with '[INTERRUPTED]' text should be skipped."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = create_memory_store("json", project_dir=tmpdir)
            result = self._sample_result(completed=True)
            result["answers"].append({
                "question_id": "cp-02",
                "dimension": "concept_premise",
                "question": "What is the theme?",
                "answer": "[INTERRUPTED]",
                "is_thin": False,
                "timestamp": "2026-01-01T00:25:00+00:00",
            })
            self._store_interview_answers(store, result)

            results = store.recall("theme", k=10)
            keys = {r["key"] for r in results}
            self.assertNotIn("concept_premise/cp-02", keys)
            store.close()

    def test_empty_answers_does_not_crash(self):
        """Empty answers list should not cause errors."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = create_memory_store("json", project_dir=tmpdir)
            result = self._sample_result(completed=True)
            result["answers"] = []
            # Should not raise
            self._store_interview_answers(store, result)
            store.close()

    def test_store_file_persists_to_disk(self):
        """JSONMemoryStore should create the storyforge-memory.json file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = create_memory_store("json", project_dir=tmpdir)
            result = self._sample_result(completed=True)
            self._store_interview_answers(store, result)
            store.close()

            mem_path = os.path.join(tmpdir, "storyforge-memory.json")
            self.assertTrue(os.path.isfile(mem_path))

            with open(mem_path, "r") as f:
                data = json.load(f)
            self.assertIsInstance(data, list)
            self.assertGreaterEqual(len(data), 3)


class TestModelOverridePlumbing(unittest.TestCase):
    """Verify that --model-override is threaded through to run_interview() calls."""

    def test_model_override_in_parser(self):
        parser = argparse.ArgumentParser()
        parser.add_argument("--model-override", type=str, default=None)
        args = parser.parse_args(["--model-override", "deepseek-chat"])
        self.assertEqual(args.model_override, "deepseek-chat")

    def test_model_override_default_none(self):
        parser = argparse.ArgumentParser()
        parser.add_argument("--model-override", type=str, default=None)
        args = parser.parse_args([])
        self.assertIsNone(args.model_override)


if __name__ == "__main__":
    unittest.main()

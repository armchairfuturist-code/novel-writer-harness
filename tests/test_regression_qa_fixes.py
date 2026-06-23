"""Regression tests for bugs found during inventory QA.

Each test verifies a fix for a specific bug. The bug_id in each test name
maps to BUG-NNN in tests/bug_log.json (filled at fix time).
"""

import json
import os
import sys
import tempfile
import unittest

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, REPO_ROOT)
sys.path.insert(0, os.path.join(REPO_ROOT, "tests"))

from tests.fixtures.mock_api import install_mock_env

install_mock_env()

from pipeline.characters import run_characters
from pipeline.export import build_manuscript_markdown, export_manuscript
from pipeline.outline import run_outline
from pipeline.draft import run_draft
from pipeline.embedding_store import EmbeddingStore


class TestBUG002_FactionsDefensive(unittest.TestCase):
    """BUG-002: run_characters crashes on factions: list[str]."""

    def test_string_factions(self):
        world = {
            "world_name": "Test",
            "factions": ["The Guild", "The Cartel", "The Court"],
        }
        spec = {"genre": "fantasy", "premise": "P", "tone": "T"}
        # Patch CrofaiClient to avoid real network
        from unittest.mock import patch, MagicMock
        from pipeline.api import parse_json_output

        mock_client = MagicMock()
        mock_client.chat_parse_with_retry.return_value = {
            "characters": [], "relationship_map": []
        }
        with patch("pipeline.characters.CrofaiClient", return_value=mock_client):
            try:
                run_characters(spec, world)
            except AttributeError as e:
                self.fail(f"run_characters crashed on string factions: {e}")

    def test_dict_factions(self):
        world = {
            "world_name": "Test",
            "factions": [{"name": "Guild"}, {"name": "Cartel"}],
        }
        spec = {"genre": "fantasy", "premise": "P", "tone": "T"}
        from unittest.mock import patch, MagicMock
        mock_client = MagicMock()
        mock_client.chat_parse_with_retry.return_value = {
            "characters": [], "relationship_map": []
        }
        with patch("pipeline.characters.CrofaiClient", return_value=mock_client):
            try:
                run_characters(spec, world)
            except AttributeError as e:
                self.fail(f"run_characters crashed on dict factions: {e}")


class TestBUG003_EmptyOutlineGraceful(unittest.TestCase):
    """BUG-003: run_draft raised on empty outline."""

    def test_empty_outline_returns_empty_list(self):
        from unittest.mock import patch
        from config import Config

        outline = {"acts": [], "story_structure": "n/a"}
        spec = {"title": "T", "genre": "fantasy", "premise": "P", "tone": "T"}
        world = {"world_name": "W"}
        chars = {"characters": []}
        config = Config()

        with tempfile.TemporaryDirectory() as td:
            with patch("pipeline.draft.EmbeddingStore", MagicMock_no_op()):
                chapters = run_draft(spec, world, chars, outline, td, config,
                                     parallel_variants=False)
            self.assertIsInstance(chapters, list)
            self.assertEqual(len(chapters), 0)


class MagicMock_no_op:
    """No-op EmbeddingStore replacement."""
    def __init__(self, *a, **kw):
        pass
    def search(self, *a, **kw):
        return []
    def add(self, *a, **kw):
        return 0
    def add_many(self, *a, **kw):
        return None


class TestBUG005_EmbeddingStoreGraceful(unittest.TestCase):
    """BUG-005: EmbeddingStore.search crashes when sentence_transformers is missing."""

    def test_search_returns_empty_when_model_missing(self):
        """When _get_model() returns None, search() should return [] not crash."""
        with tempfile.TemporaryDirectory() as td:
            store = EmbeddingStore(os.path.join(td, "embeddings.db"))
            # Force the model loader to return None (simulates missing dep)
            import pipeline.embedding_store as emod
            emod._local.model = None
            # search must not raise
            results = store.search("any query")
            self.assertEqual(results, [])

    def test_add_handles_missing_model(self):
        """add() must work even without sentence_transformers."""
        with tempfile.TemporaryDirectory() as td:
            store = EmbeddingStore(os.path.join(td, "embeddings.db"))
            import pipeline.embedding_store as emod
            emod._local.model = None
            row_id = store.add(chapter=1, content="hello world")
            self.assertIsInstance(row_id, int)


class TestBUG007_OutlineFactionsDefensive(unittest.TestCase):
    """BUG-007: outline.py crashed on string factions."""

    def test_string_factions_in_outline(self):
        from unittest.mock import patch, MagicMock
        world = {
            "world_name": "W",
            "factions": ["Guild", "Cartel"],
            "central_conflict": "war",
        }
        chars = {"characters": [{"name": "A", "role": "p", "arc": "grows"}]}
        spec = {
            "title": "T", "genre": "fantasy", "premise": "P",
            "tone": "T", "pov": "third", "target_chapters": 5,
        }
        mock_client = MagicMock()
        mock_client.chat_parse_with_retry.return_value = {
            "acts": [{"name": "A1", "chapters": [{"chapter": 1, "title": "Ch",
                                                   "pov": "A", "summary": "s",
                                                   "key_events": ["e"],
                                                   "emotional_arc": "rising"}]}],
            "story_structure": "three_act",
        }
        with patch("pipeline.outline.CrofaiClient", return_value=mock_client):
            try:
                run_outline(spec, world, chars)
            except AttributeError as e:
                self.fail(f"run_outline crashed on string factions: {e}")


class TestBUG008_ExportGeographyDefensive(unittest.TestCase):
    """BUG-008: export.py crashed on dict geography."""

    def test_dict_geography_handled(self):
        spec = {"title": "T", "genre": "fantasy", "premise": "P"}
        world = {"world_name": "W", "geography": {"regions": ["a", "b"]}}
        chars = {"characters": []}
        outline = {"story_structure": "three_act"}

        with tempfile.TemporaryDirectory() as td:
            try:
                build_manuscript_markdown([], spec, world, chars, outline, td)
            except (KeyError, TypeError) as e:
                self.fail(f"build_manuscript_markdown crashed on dict geography: {e}")
            # File should exist
            self.assertTrue(os.path.exists(os.path.join(td, "manuscript.md")))

    def test_list_geography_handled(self):
        spec = {"title": "T", "genre": "fantasy", "premise": "P"}
        world = {"world_name": "W", "geography": ["a", "b", "c"]}
        chars = {"characters": []}
        outline = {"story_structure": "three_act"}
        with tempfile.TemporaryDirectory() as td:
            try:
                build_manuscript_markdown([], spec, world, chars, outline, td)
            except (KeyError, TypeError) as e:
                self.fail(f"build_manuscript_markdown crashed on list geography: {e}")


class TestBUG009_ExportMissingPersonality(unittest.TestCase):
    """BUG-009: export.py crashed on character dict without 'personality'."""

    def test_character_without_personality(self):
        spec = {"title": "T", "genre": "fantasy", "premise": "P"}
        world = {"world_name": "W"}
        chars = {"characters": [{"name": "Alice", "role": "protagonist"}]}
        outline = {"story_structure": "three_act"}

        with tempfile.TemporaryDirectory() as td:
            try:
                build_manuscript_markdown([], spec, world, chars, outline, td)
            except (KeyError, TypeError) as e:
                self.fail(f"build_manuscript_markdown crashed on missing personality: {e}")
            with open(os.path.join(td, "manuscript.md")) as f:
                content = f.read()
            self.assertIn("Alice", content)


class TestBUG001_ProjectDirOverride(unittest.TestCase):
    """BUG-001: run_full_pipeline had no project_dir_override."""

    def test_project_dir_override_accepted(self):
        import storyforge
        from unittest.mock import patch
        from config import Config

        config = Config()
        # Pre-populate the project so the pipeline exits early via checkpoint
        with tempfile.TemporaryDirectory() as td:
            pd = os.path.join(td, "p")
            os.makedirs(pd)
            with open(os.path.join(pd, "checkpoint.json"), "w") as f:
                json.dump({"completed_phases": ["seed", "worldbuilding",
                                                "characters", "outline",
                                                "draft", "export"]}, f)
            with open(os.path.join(pd, "spec.json"), "w") as f:
                f.write("{}")
            with open(os.path.join(pd, "world.json"), "w") as f:
                f.write("{}")
            with open(os.path.join(pd, "characters.json"), "w") as f:
                f.write("{}")
            with open(os.path.join(pd, "outline.json"), "w") as f:
                f.write("{}")
            os.makedirs(os.path.join(pd, "chapters"), exist_ok=True)

            try:
                result = storyforge.run_full_pipeline(
                    "any concept",
                    config=config,
                    project_dir_override=pd,
                    quick=True,
                    parallel_variants=False,
                    dual_review=False,
                    enable_backprop=False,
                    enable_adversarial=False,
                    iterative_backprop=False,
                    feedback_enabled=False,
                )
                self.assertEqual(result, pd)
            except TypeError as e:
                if "project_dir_override" in str(e):
                    self.fail(f"project_dir_override still not accepted: {e}")
                raise


if __name__ == "__main__":
    unittest.main()
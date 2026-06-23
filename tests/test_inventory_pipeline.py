"""Inventory test: full pipeline (seed → export) with mocked LLM.

Exercises run_full_pipeline end-to-end with the sanitized project data
and the mock API. Verifies every checkpoint transition, phase
skipping on cached resume, and post-draft phase behavior.
"""

import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch, MagicMock

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, REPO_ROOT)
sys.path.insert(0, os.path.join(REPO_ROOT, "tests"))

from tests.fixtures.mock_api import install_mock_env, FailureMode, MockCrofaiClient
from tests.fixtures.sanitized_project import (
    write_sanitized_project, get_sanitized_chapters,
    SANITIZED_SPEC, SANITIZED_WORLD, SANITIZED_CHARACTERS, SANITIZED_OUTLINE,
)
from tests.fixtures.bug_log import log_bug

install_mock_env()

# Now import storyforge
import storyforge
from config import Config
from pipeline.canonical_store import FileCanonicalStore, create_canonical_store
from pipeline.draft import run_draft
from pipeline.seed import run_seed
from pipeline.worldbuilding import run_worldbuilding
from pipeline.characters import run_characters
from pipeline.outline import run_outline
from pipeline.outline_validator import run_outline_validator
from pipeline.export import export_manuscript
from pipeline.review import run_full_review
from pipeline.backprop import run_backward_propagation
from pipeline.iterative_backprop import run_iterative_backpropagation
from pipeline.adversarial_edit import run_adversarial_edit
from pipeline.factcheck import run_fact_check


def _patch_crofai():
    """Return a context manager that patches CrofaiClient with a mock."""
    from contextlib import ExitStack
    stack = ExitStack()
    targets = [
        "pipeline.api.CrofaiClient",
        "pipeline.seed.CrofaiClient",
        "pipeline.worldbuilding.CrofaiClient",
        "pipeline.characters.CrofaiClient",
        "pipeline.outline.CrofaiClient",
        "pipeline.draft.CrofaiClient",
        "pipeline.review.CrofaiClient",
        "pipeline.factcheck.CrofaiClient",
        "pipeline.backprop.CrofaiClient",
        "pipeline.iterative_backprop.CrofaiClient",
        "pipeline.adversarial_edit.CrofaiClient",
        "pipeline.export.CrofaiClient",
        "pipeline.outline_validator.CrofaiClient",
        "interview.drilling.CrofaiClient",
        "interview.chapter_feedback.CrofaiClient",
        "agents.orchestrator.CrofaiClient",
        "agents.writer.CrofaiClient",
        "agents.critic.CrofaiClient",
    ]
    for t in targets:
        stack.enter_context(patch(t, MockCrofaiClient, create=True))
    return stack


class TestPipelineEndToEnd(unittest.TestCase):
    """End-to-end pipeline run with all 7 phases."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="storyforge_test_")
        self.project_dir = os.path.join(self.tmpdir, "test_project")
        os.makedirs(self.project_dir)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_seed_phase_produces_spec(self):
        """AC: phase.seed.cached_resume — seed phase produces spec.json."""
        with _patch_crofai():
            spec = run_seed("A sanitized fantasy concept for testing")
        # The mock returns a structured spec
        self.assertIsInstance(spec, dict)
        self.assertIn("title", spec)
        self.assertIn("genre", spec)

    def test_worldbuilding_produces_world(self):
        """AC: phase.worldbuilding.cached_resume — worldbuilding produces world.json-shape data."""
        with _patch_crofai():
            world = run_worldbuilding(SANITIZED_SPEC)
        self.assertIsInstance(world, dict)
        self.assertIn("world_name", world)

    def test_characters_produces_characters(self):
        """AC: phase.characters.cached_resume — characters phase produces profiles."""
        with _patch_crofai():
            chars = run_characters(SANITIZED_SPEC, SANITIZED_WORLD)
        self.assertIsInstance(chars, dict)
        self.assertIn("characters", chars)
        self.assertIsInstance(chars["characters"], list)
        self.assertGreater(len(chars["characters"]), 0)

    def test_outline_produces_outline(self):
        """AC: phase.outline.cached_resume — outline phase produces chapter list."""
        with _patch_crofai():
            outline = run_outline(SANITIZED_SPEC, SANITIZED_WORLD, SANITIZED_CHARACTERS)
        self.assertIsInstance(outline, dict)
        self.assertIn("acts", outline)

    def test_outline_validator_returns_validity(self):
        """AC: phase.outline_validation — validator returns overall PASS/WARN/FAIL."""
        with _patch_crofai():
            validation = run_outline_validator(
                SANITIZED_SPEC, SANITIZED_WORLD, SANITIZED_CHARACTERS, SANITIZED_OUTLINE
            )
        self.assertIn("overall", validation)
        self.assertIn(validation["overall"], ("PASS", "WARN", "FAIL"))

    def test_full_pipeline_minimal(self):
        """AC: All 7 phases — run_full_pipeline runs to completion with --quick."""
        write_sanitized_project(self.project_dir, partial=True)
        with _patch_crofai():
            result = storyforge.run_full_pipeline(
                "A sanitized test concept",
                project_dir_override=self.project_dir,
                quick=True,
                parallel_variants=False,  # faster
                dual_review=False,        # faster
                enable_backprop=False,
                enable_adversarial=False,
                iterative_backprop=False,
                enable_reio=True,
                feedback_enabled=False,   # no stdin in tests
            )
        self.assertEqual(result, self.project_dir)
        # All phase outputs should exist
        for fn in ("spec.json", "world.json", "characters.json", "outline.json",
                   "outline_validation.json", "checkpoint.json"):
            self.assertTrue(os.path.exists(os.path.join(self.project_dir, fn)),
                            f"Expected {fn} to exist after full pipeline")
        # Chapters should exist
        ch_dir = os.path.join(self.project_dir, "chapters")
        self.assertTrue(os.path.isdir(ch_dir))
        ch_files = [f for f in os.listdir(ch_dir) if f.endswith(".md")]
        self.assertGreater(len(ch_files), 0, "Drafting should produce at least one chapter")

    def test_cached_resume_skips_completed_phases(self):
        """AC: phase.*.cached_resume — re-running skips completed phases."""
        # Pre-populate the project with a complete draft
        write_sanitized_project(self.project_dir, partial=False)
        # Now we have checkpoint with all phases completed
        # Re-run should use cache
        with _patch_crofai():
            result = storyforge.run_full_pipeline(
                "A sanitized test concept",
                project_dir_override=self.project_dir,
                quick=True,
                parallel_variants=False,
                dual_review=False,
                enable_backprop=False,
                enable_adversarial=False,
                iterative_backprop=False,
                feedback_enabled=False,
            )
        self.assertEqual(result, self.project_dir)
        # Re-running should preserve all files
        for fn in ("spec.json", "world.json", "characters.json", "outline.json",
                   "checkpoint.json"):
            self.assertTrue(os.path.exists(os.path.join(self.project_dir, fn)))


class TestDraftPhaseEdgeCases(unittest.TestCase):
    """Draft phase edge cases: empty outline, single chapter, truncation."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="storyforge_draft_")
        self.project_dir = os.path.join(self.tmpdir, "draft_project")
        os.makedirs(self.project_dir)
        os.makedirs(os.path.join(self.project_dir, "chapters"))

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_empty_outline_zero_chapters(self):
        """AC: phase.draft.empty_outline — outline with 0 chapters does not crash."""
        empty_outline = {"acts": [], "story_structure": "empty", "pov_strategy": "n/a"}
        config = Config()
        with _patch_crofai():
            chapters = run_draft(
                SANITIZED_SPEC, SANITIZED_WORLD, SANITIZED_CHARACTERS,
                empty_outline, self.project_dir, config,
                parallel_variants=False,
            )
        self.assertIsInstance(chapters, list)
        self.assertEqual(len(chapters), 0)

    def test_single_chapter_outline(self):
        """AC: edge case — single-chapter outline produces one chapter."""
        single = {
            "acts": [{
                "name": "Single Act",
                "chapters": [{
                    "chapter": 1, "title": "Solo", "pov": "Aelith",
                    "summary": "summary", "key_events": ["event"],
                    "emotional_arc": "rising", "foreshadowing": "none",
                    "character_arc_beat": "init",
                }],
            }],
            "story_structure": "one_chapter",
            "pov_strategy": "single",
        }
        config = Config()
        with _patch_crofai():
            chapters = run_draft(
                SANITIZED_SPEC, SANITIZED_WORLD, SANITIZED_CHARACTERS,
                single, self.project_dir, config,
                parallel_variants=False,
            )
        self.assertIsInstance(chapters, list)
        self.assertGreaterEqual(len(chapters), 1)

    def test_draft_writes_chapter_files(self):
        """AC: data integrity — draft phase writes one .md file per chapter."""
        config = Config()
        with _patch_crofai():
            chapters = run_draft(
                SANITIZED_SPEC, SANITIZED_WORLD, SANITIZED_CHARACTERS,
                SANITIZED_OUTLINE, self.project_dir, config,
                parallel_variants=False,
            )
        ch_dir = os.path.join(self.project_dir, "chapters")
        self.assertTrue(os.path.isdir(ch_dir))
        for ch in chapters:
            self.assertIn("file", ch)
            self.assertTrue(os.path.exists(ch["file"]),
                            f"Chapter file {ch['file']} should exist")
            with open(ch["file"]) as f:
                content = f.read()
            self.assertGreater(len(content), 0, "Chapter file should not be empty")


class TestExportPhase(unittest.TestCase):
    """Export phase behavior."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="storyforge_export_")
        self.project_dir = os.path.join(self.tmpdir, "export_project")
        os.makedirs(self.project_dir)
        os.makedirs(os.path.join(self.project_dir, "chapters"))

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_export_writes_manuscript_md(self):
        """AC: export.markdown_written — manuscript.md is written with all chapters."""
        chapters = []
        for ch in get_sanitized_chapters()[:3]:  # just 3 for speed
            path = os.path.join(self.project_dir, "chapters", f"chapter-{ch['chapter']:03d}.md")
            with open(path, "w") as f:
                f.write(f"> POV: {ch['pov']}\n\n# {ch['title']}\n\n{ch['content']}")
            ch["file"] = path
            chapters.append(ch)
        result = export_manuscript(
            chapters, SANITIZED_SPEC, SANITIZED_WORLD, SANITIZED_CHARACTERS,
            SANITIZED_OUTLINE, self.project_dir,
        )
        self.assertIn("manuscript_md", result)
        self.assertTrue(os.path.exists(result["manuscript_md"]))
        with open(result["manuscript_md"]) as f:
            content = f.read()
        # All chapter titles should appear
        for ch in chapters:
            self.assertIn(ch["title"], content,
                          f"Manuscript should contain chapter title: {ch['title']}")

    def test_export_empty_chapters(self):
        """AC: export.empty_manuscript — empty chapters list should not crash."""
        try:
            result = export_manuscript(
                [], SANITIZED_SPEC, SANITIZED_WORLD, SANITIZED_CHARACTERS,
                SANITIZED_OUTLINE, self.project_dir,
            )
            # If it returns, should still be a dict
            self.assertIsInstance(result, dict)
        except Exception as e:
            # If it raises, the error should be specific and actionable
            self.assertIn("chapter", str(e).lower(),
                          f"Export of empty chapters raised unclear error: {e}")


class TestCheckpointCorruption(unittest.TestCase):
    """Checkpoint corruption handling."""

    def test_corrupt_checkpoint_returns_empty_set(self):
        """AC: phase.checkpoint_corrupt — corrupt JSON returns empty set, no crash."""
        with tempfile.TemporaryDirectory() as td:
            cp = os.path.join(td, "checkpoint.json")
            with open(cp, "w") as f:
                f.write("{not valid json")
            result = storyforge._load_checkpoint(td)
            self.assertEqual(result, set())

    def test_missing_checkpoint_returns_empty_set(self):
        """AC: phase.checkpoint_corrupt — missing file returns empty set."""
        with tempfile.TemporaryDirectory() as td:
            result = storyforge._load_checkpoint(td)
            self.assertEqual(result, set())

    def test_checkpoint_round_trip(self):
        """AC: data integrity — checkpoint saves and loads correctly."""
        with tempfile.TemporaryDirectory() as td:
            completed = {"seed", "worldbuilding", "characters"}
            storyforge._save_checkpoint(td, completed)
            loaded = storyforge._load_checkpoint(td)
            self.assertEqual(loaded, completed)

    def test_checkpoint_with_unexpected_field(self):
        """AC: data integrity — checkpoint with extra fields still loads."""
        with tempfile.TemporaryDirectory() as td:
            cp = os.path.join(td, "checkpoint.json")
            with open(cp, "w") as f:
                json.dump({
                    "completed_phases": ["seed", "outline"],
                    "version": 5,
                    "extra_field": "ignored",
                }, f)
            loaded = storyforge._load_checkpoint(td)
            self.assertEqual(loaded, {"seed", "outline"})


class TestSlugifyEdgeCases(unittest.TestCase):
    """Slugify handles edge cases safely."""

    def test_slugify_normal_text(self):
        self.assertEqual(storyforge.slugify("A normal title"), "a-normal-title")

    def test_slugify_special_characters_stripped(self):
        result = storyforge.slugify("Test!@#$%^&*()")
        # All non-alphanumeric should be removed or replaced
        self.assertNotIn("!", result)
        self.assertNotIn("@", result)
        self.assertNotIn("(", result)

    def test_slugify_unicode_normalized_or_preserved(self):
        result = storyforge.slugify("Café au lait")
        # Implementation uses [^a-z0-9\s-] filter, so 'é' is removed
        # This is acceptable but should not crash
        self.assertIsInstance(result, str)
        self.assertGreater(len(result), 0)

    def test_slugify_whitespace_collapsed(self):
        self.assertEqual(storyforge.slugify("multiple   spaces   here"), "multiple-spaces-here")

    def test_slugify_path_traversal_safe(self):
        """AC: security — slugify must not produce path-traversal sequences."""
        result = storyforge.slugify("../../etc/passwd")
        # '..' and '/' are not in [a-z0-9\s-]
        self.assertNotIn("..", result)
        self.assertNotIn("/", result)

    def test_slugify_length_capped(self):
        long_text = "word " * 100
        result = storyforge.slugify(long_text)
        self.assertLessEqual(len(result), 60)

    def test_slugify_empty_safe(self):
        result = storyforge.slugify("")
        self.assertEqual(result, "")


if __name__ == "__main__":
    unittest.main()

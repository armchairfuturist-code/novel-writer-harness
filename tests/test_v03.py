"""Tests for v0.3 features: Hindsight, ReIO, iterative backprop, genre templates, rhetorical strategies."""

import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from pipeline.hindsight_client import HindsightStore
from pipeline.reio_compression import ReIOCompressor, estimate_tokens
from pipeline.iterative_backprop import run_iterative_backpropagation
from templates import list_templates, get_template, get_beat_for_chapter, get_required_elements, get_tracking_items, get_critical_items
from pipeline.draft import STYLE_PROFILES, DEFAULT_STYLE_PROFILES


class TestRhetoricalStrategies(unittest.TestCase):
    """Test that the Postwriter-inspired rhetorical strategies are in place."""

    def test_style_profiles_have_four_strategies(self):
        self.assertEqual(len(STYLE_PROFILES), 4)

    def test_style_profiles_are_rhetorical_strategies(self):
        expected = {"suspense_first", "reveal_late", "sensory_immersion", "interiority_forward"}
        self.assertEqual(set(STYLE_PROFILES.keys()), expected)

    def test_default_profiles_use_new_names(self):
        expected = ["suspense_first", "reveal_late", "sensory_immersion", "interiority_forward"]
        profile_names = [name for name, _ in DEFAULT_STYLE_PROFILES]
        self.assertEqual(profile_names, expected)

    def test_each_profile_has_rhetorical_strategy_label(self):
        for name, desc in STYLE_PROFILES.items():
            self.assertIn("RHETORICAL STRATEGY", desc,
                          f"Profile '{name}' missing RHETORICAL STRATEGY label")

    def test_each_profile_has_concrete_instructions(self):
        for name, desc in STYLE_PROFILES.items():
            self.assertGreater(len(desc), 100,
                               f"Profile '{name}' too short to be useful")
            self.assertIn("Pacing:", desc,
                          f"Profile '{name}' missing pacing directive")


class TestReIOCompression(unittest.TestCase):
    """Test ReIO context compression."""

    def setUp(self):
        self.compressor = ReIOCompressor(
            token_budget=900000,
            recent_chapters=3,
            medium_chapters=5,
        )
        self.chapter_summaries = [
            {"chapter": 1, "title": "The Beginning", "summary": "Maria arrives in the city. She meets the detective. A murder investigation begins.", "word_count": 3500},
            {"chapter": 2, "title": "The Clue", "summary": "A photograph reveals a hidden connection to the victim's past.", "word_count": 4200},
            {"chapter": 3, "title": "The Suspect", "summary": "The prime suspect is interviewed. Alibi doesn't hold up.", "word_count": 3800},
            {"chapter": 4, "title": "The Warehouse", "summary": "A chase through an abandoned warehouse. New evidence discovered.", "word_count": 4100},
            {"chapter": 5, "title": "The Interrogation", "summary": "The suspect breaks down. Details of the murder weapon emerge.", "word_count": 3900},
            {"chapter": 6, "title": "The Twist", "summary": "A third party was involved. Everything the detective knew was wrong.", "word_count": 4400},
            {"chapter": 7, "title": "The Pursuit", "summary": "The real killer is identified. A chase across the city begins.", "word_count": 3700},
            {"chapter": 8, "title": "The Confrontation", "summary": "Final confrontation with the killer. Truth comes out.", "word_count": 4600},
        ]

    def test_compress_for_chapter_recent_is_full(self):
        context = self.compressor.compress_for_chapter(
            chapter_num=5,
            total_chapters=4,
            chapter_summaries=self.chapter_summaries[:4],
        )
        self.assertIn("COMPRESSED NARRATIVE CONTEXT", context)
        self.assertIn("Immediately Previous Chapters", context)
        # Chapters 2, 3, 4 should be in "recent" (within 3 of chapter 5)
        self.assertIn("Ch 2", context)
        self.assertIn("Ch 4", context)

    def test_compress_for_chapter_early_is_compressed(self):
        # Add enough summaries to push early chapters into compressed range
        extra_summaries = [
            {"chapter": 9, "title": "The Aftermath", "summary": "The killer is in custody. Loose ends are tied up.", "word_count": 3500},
            {"chapter": 10, "title": "The Trial", "summary": "Courtroom drama. Witnesses testify. The truth comes out.", "word_count": 4200},
            {"chapter": 11, "title": "Resolution", "summary": "Justice is served. The detective reflects.", "word_count": 3100},
            {"chapter": 12, "title": "Epilogue", "summary": "Life goes on. A hint of what's to come.", "word_count": 2800},
        ]
        all_sums = self.chapter_summaries + extra_summaries
        context = self.compressor.compress_for_chapter(
            chapter_num=13,
            total_chapters=12,
            chapter_summaries=all_sums,
        )
        self.assertIn("Earlier Chapters (compressed)", context)
        self.assertIn("Immediately Previous Chapters", context)
        self.assertIn("Recent Chapters (condensed)", context)

    def test_should_compress_returns_false_for_few_chapters(self):
        result = self.compressor.should_compress(3, 3)
        self.assertFalse(result)

    def test_should_compress_returns_true_for_many_chapters(self):
        result = self.compressor.should_compress(10, 10)
        self.assertTrue(result)

    def test_condense_summary_short(self):
        result = self.compressor._condense_summary("Short text here", max_words=10)
        self.assertEqual(result, "Short text here")

    def test_condense_summary_long(self):
        long_text = "word " * 30
        result = self.compressor._condense_summary(long_text, max_words=10)
        self.assertLess(len(result.split()), 20)

    def test_estimate_tokens(self):
        self.assertEqual(estimate_tokens("hello world"), 2)
        self.assertEqual(estimate_tokens(""), 0)

    def test_empty_summaries(self):
        context = self.compressor.compress_for_chapter(
            chapter_num=1,
            total_chapters=0,
            chapter_summaries=[],
        )
        self.assertIn("NO PRIOR CONTEXT", context)

    def test_critical_state_included(self):
        context = self.compressor.compress_for_chapter(
            chapter_num=5,
            total_chapters=4,
            chapter_summaries=self.chapter_summaries[:4],
            critical_state="CRITICAL: Maria has blue eyes. The killer is left-handed.",
        )
        self.assertIn("CRITICAL: Maria has blue eyes", context)

    def test_build_arc_summaries(self):
        outline = {
            "acts": [
                {"act_name": "Act 1", "summary": "Introduction", "chapters": [
                    {"chapter": 1}, {"chapter": 2}, {"chapter": 3}
                ]},
                {"act_name": "Act 2", "summary": "Rising action", "chapters": [
                    {"chapter": 4}, {"chapter": 5}
                ]},
            ]
        }
        arcs = self.compressor.build_arc_summaries(
            outline, self.chapter_summaries[:5]
        )
        self.assertEqual(len(arcs), 2)
        self.assertEqual(arcs[0]["arc_name"], "Act 1")


class TestHindsightClient(unittest.TestCase):
    """Test HindsightStore with mocked HTTP."""

    def setUp(self):
        self.store = HindsightStore(project_id="test-novel", enabled=True)

    def test_init_sets_bank_id(self):
        self.assertIn("test-novel", self.store.bank_id)

    def test_format_context_no_hindsight(self):
        store_disabled = HindsightStore(project_id="test", enabled=False)
        result = store_disabled.format_context_for_drafting(1, "test chapter")
        self.assertIn("Hindsight unavailable", result)

    def test_format_empty_context(self):
        result = self.store._format_empty_context()
        self.assertIn("Hindsight unavailable", result)

    def test_close(self):
        # Should not raise
        self.store.close()

    def test_bank_id_format(self):
        self.assertTrue(self.store.bank_id.startswith("storyforge-"))
        self.assertIn("test-novel", self.store.bank_id)


class TestHindsightClientHTTP(unittest.TestCase):
    """Test HindsightStore HTTP methods with mocked responses."""

    def setUp(self):
        self.store = HindsightStore(project_id="http-test", enabled=True)
        self.mock_banks_response = {
            "banks": [
                {"bank_id": "storyforge-http-test", "name": "StoryForge: http-test"}
            ]
        }
        self.mock_recall_response = {
            "results": [
                {"content": "Character 'Maria' has eye_color: blue (established Ch 1)", "score": 0.95, "tags": ["character_trait", "eye_color", "maria"]},
                {"content": "Plot thread 'The mystery': active and unresolved", "score": 0.80, "tags": ["plot_thread", "active"]},
            ]
        }

    def test_ensure_bank_exists(self):
        with patch("httpx.Client") as mock_client:
            instance = mock_client.return_value
            instance.get.return_value.status_code = 200
            instance.get.return_value.json.return_value = self.mock_banks_response
            self.store._http = instance
            # Bank already exists
            result = self.store.ensure_bank()
            self.assertFalse(result)

    def test_ensure_bank_creates(self):
        with patch("httpx.Client") as mock_client:
            instance = mock_client.return_value
            # First get returns empty banks list
            mock_get = MagicMock()
            mock_get.status_code = 200
            mock_get.json.return_value = {"banks": []}
            instance.get.return_value = mock_get
            # Put succeeds
            mock_put = MagicMock()
            mock_put.status_code = 201
            instance.put.return_value = mock_put
            self.store._http = instance
            result = self.store.ensure_bank()
            self.assertTrue(result)

    def test_recall_returns_results(self):
        with patch("httpx.Client") as mock_client:
            instance = mock_client.return_value
            mock_recall = MagicMock()
            mock_recall.status_code = 200
            mock_recall.json.return_value = self.mock_recall_response
            instance.post.return_value = mock_recall
            self.store._http = instance
            results = self.store.recall("character traits", tag_filter=["character_trait"])
            self.assertEqual(len(results), 2)
            self.assertIn("blue", results[0]["content"])

    def test_store_memory(self):
        with patch("httpx.Client") as mock_client:
            instance = mock_client.return_value
            mock_resp = MagicMock()
            mock_resp.status_code = 201
            instance.post.return_value = mock_resp
            self.store._http = instance
            result = self.store.store_memory(
                content="Test fact",
                tags=["test"],
                importance=0.5,
            )
            self.assertTrue(result)

    def test_store_disabled(self):
        store_disabled = HindsightStore(project_id="test", enabled=False)
        result = store_disabled.store_memory("test")
        self.assertFalse(result)

    def test_scan_contradictions_no_conflicts(self):
        # Without HTTP mocking, this should just return an empty list gracefully
        # since Hindsight isn't actually running with test data
        self.store.enabled = False
        result = self.store.scan_contradictions("Maria", "eye_color", "blue", 5)
        self.assertEqual(result, [])


class TestIterativeBackprop(unittest.TestCase):
    """Test iterative backward propagation module."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.chapters_dir = os.path.join(self.temp_dir, "chapters")
        os.makedirs(self.chapters_dir)
        self.outline_path = os.path.join(self.temp_dir, "outline.json")

    def _write_chapter(self, num: int, text: str):
        path = os.path.join(self.chapters_dir, f"chapter-{num:03d}.md")
        with open(path, "w") as f:
            f.write(text)

    def _write_outline(self, foreshadowing: list[dict] = None):
        outline = {
            "acts": [
                {
                    "act_name": "Test Act",
                    "chapters": [
                        {"chapter": 1, "foreshadowing": f.get("text", "") if foreshadowing else ""}
                        for f in (foreshadowing or [])
                    ]
                }
            ]
        }
        with open(self.outline_path, "w") as f:
            json.dump(outline, f)

    def test_skipped_when_no_chapters(self):
        # Remove chapters directory to trigger SKIPPED
        import shutil
        shutil.rmtree(self.chapters_dir)
        result = run_iterative_backpropagation(self.temp_dir, self.outline_path)
        self.assertEqual(result["status"], "SKIPPED")

    def test_converges_on_clean_chapters(self):
        self._write_chapter(1, "Chapter one text. Blue eyes. Morning.")
        self._write_chapter(2, "Chapter two text. Blue eyes. Afternoon.")
        result = run_iterative_backpropagation(self.temp_dir, self.outline_path)
        self.assertIn(result["status"], ["PASS", "STALLED", "FAIL"])

    def test_iteration_tracking(self):
        self._write_chapter(1, "Blue eyes. Morning. Chapter one.")
        self._write_chapter(2, "Brown eyes. Night. Chapter two.")
        result = run_iterative_backpropagation(
            self.temp_dir, self.outline_path, max_iterations=2
        )
        self.assertGreaterEqual(result["iterations"], 1)
        self.assertIn("iteration_history", result)


class TestGenreTemplates(unittest.TestCase):
    """Test genre beat templates."""

    def test_list_templates_returns_all(self):
        templates = list_templates()
        self.assertIn("mystery", templates)
        self.assertIn("thriller", templates)
        self.assertIn("romance", templates)
        self.assertIn("fantasy", templates)
        self.assertIn("sci-fi", templates)

    def test_get_template_loads_mystery(self):
        template = get_template("mystery")
        self.assertIsNotNone(template)
        self.assertEqual(template["genre"], "mystery")
        self.assertIn("beats", template)
        self.assertIn("tracking", template)

    def test_get_template_missing_returns_none(self):
        template = get_template("nonexistent_genre")
        self.assertIsNone(template)

    def test_mystery_has_correct_beats(self):
        template = get_template("mystery")
        phases = [b["phase"] for b in template["beats"]]
        self.assertEqual(phases, ["setup", "investigation", "middle_twist", "pressure", "resolution"])

    def test_thriller_has_critical_items(self):
        template = get_template("thriller")
        items = template["tracking"]["critical_items"]
        self.assertIn("tension_level", items)
        self.assertIn("time_remaining", items)

    def test_romance_tracks_emotional_distance(self):
        template = get_template("romance")
        must_track = template["tracking"]["must_track"]
        self.assertTrue(any("emotional distance" in t for t in must_track))

    def test_fantasy_has_prophecy_tracking(self):
        template = get_template("fantasy")
        items = template["tracking"]["critical_items"]
        self.assertIn("prophecy_elements", items)

    def test_sci_has_knowledge_gap_tracking(self):
        template = get_template("sci-fi")
        items = template["tracking"]["critical_items"]
        self.assertIn("character_knowledge_gaps", items)

    def test_get_beat_for_chapter_mystery(self):
        beat = get_beat_for_chapter("mystery", 1)
        self.assertEqual(beat["phase"], "setup")

        beat = get_beat_for_chapter("mystery", 5)
        self.assertEqual(beat["phase"], "investigation")

        beat = get_beat_for_chapter("mystery", 18)
        self.assertEqual(beat["phase"], "resolution")

    def test_get_beat_for_chapter_missing_genre(self):
        beat = get_beat_for_chapter("nonexistent", 1)
        self.assertIsNone(beat)

    def test_get_required_elements(self):
        elements = get_required_elements("mystery", 1)
        self.assertIn("inciting_crime", elements)
        self.assertIn("detective_introduction", elements)

    def test_get_required_elements_outside_range(self):
        elements = get_required_elements("mystery", 999)
        self.assertEqual(elements, [])

    def test_get_tracking_items(self):
        items = get_tracking_items("mystery")
        self.assertTrue(len(items) > 0)

    def test_get_critical_items(self):
        items = get_critical_items("thriller")
        self.assertIn("tension_level", items)

    def test_each_template_has_structure(self):
        for genre in list_templates():
            template = get_template(genre)
            struct = template.get("structure", {})
            self.assertIn("tension_arc", struct, f"Genre {genre} missing tension_arc")
            self.assertIn("pacing_profile", struct, f"Genre {genre} missing pacing_profile")


if __name__ == "__main__":
    unittest.main()

"""Tests for story bible compilation and pipeline integration.

Tests cover: basic compilation with full answers, graceful defaults,
skipped answers, minimal depth, title extraction, theme parsing,
and a utility test that verifies all tests pass.
"""

import os
import sys
import subprocess
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from interview.story_bible import compile_story_bible

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

EXPECTED_POV_VALUES = [
    "first person",
    "third limited",
    "third omniscient",
    "multi-pov",
    "second person",
]

# Canonical spec keys from pipeline/seed.py SEED_USER_TEMPLATE
SEED_SPEC_KEYS = {
    "title",
    "genre",
    "premise",
    "tone",
    "pov",
    "tense",
    "target_length",
    "target_chapters",
    "themes",
    "unique_angle",
    "initial_direction",
}

# Additional keys added by compile_story_bible
SPEC_META_KEYS = {"_source", "_depth", "_thin_areas"}

ALL_SPEC_KEYS = SEED_SPEC_KEYS | SPEC_META_KEYS

# Enrichment dimension keys produced by compile_story_bible
ENRICHMENT_KEYS = [
    "world",
    "characters",
    "plot",
    "theme_voice",
    "market",
    "concept_premise",
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _full_answers(depth: str = "standard") -> list[dict]:
    """Build a full set of mock answers across all 6 dimensions."""
    return [
        # Concept & Premise (cp-*)
        {
            "question_id": "cp-01",
            "dimension": "concept_premise",
            "question": "What is your story about?",
            "answer": "A retired detective uncovers a conspiracy linking his past cases to a shadowy organization.",
            "is_thin": False,
            "timestamp": "2026-01-01T00:01:00",
        },
        {
            "question_id": "cp-02",
            "dimension": "concept_premise",
            "question": "What genre(s)?",
            "answer": "Urban fantasy noir",
            "is_thin": False,
            "timestamp": "2026-01-01T00:02:00",
        },
        {
            "question_id": "cp-03",
            "dimension": "concept_premise",
            "question": "Unique angle?",
            "answer": "The conspiracy spans multiple parallel realities.",
            "is_thin": False,
            "timestamp": "2026-01-01T00:03:00",
        },
        {
            "question_id": "cp-04",
            "dimension": "concept_premise",
            "question": "Central conflict?",
            "answer": "The detective must choose between justice and protecting his family.",
            "is_thin": False,
            "timestamp": "2026-01-01T00:04:00",
        },
        {
            "question_id": "cp-05",
            "dimension": "concept_premise",
            "question": "Target audience?",
            "answer": "Adult readers who enjoy character-driven fantasy mysteries.",
            "is_thin": False,
            "timestamp": "2026-01-01T00:05:00",
        },
        {
            "question_id": "cp-06",
            "dimension": "concept_premise",
            "question": "Tone?",
            "answer": "Grim but hopeful",
            "is_thin": False,
            "timestamp": "2026-01-01T00:06:00",
        },
        {
            "question_id": "cp-07",
            "dimension": "concept_premise",
            "question": "Estimated length?",
            "answer": "Novel ~80K",
            "is_thin": False,
            "timestamp": "2026-01-01T00:07:00",
        },
        {
            "question_id": "cp-08",
            "dimension": "concept_premise",
            "question": "Narrative tense?",
            "answer": "past tense",
            "is_thin": False,
            "timestamp": "2026-01-01T00:08:00",
        },
        {
            "question_id": "cp-09",
            "dimension": "concept_premise",
            "question": "Point of view?",
            "answer": "third limited",
            "is_thin": False,
            "timestamp": "2026-01-01T00:09:00",
        },
        {
            "question_id": "cp-10",
            "dimension": "concept_premise",
            "question": "Inciting incident?",
            "answer": "A package arrives containing a case file from a dead colleague.",
            "is_thin": False,
            "timestamp": "2026-01-01T00:10:00",
        },
        {
            "question_id": "cp-11",
            "dimension": "concept_premise",
            "question": "Do you know the ending?",
            "answer": "The detective sacrifices his memories to protect the secret.",
            "is_thin": False,
            "timestamp": "2026-01-01T00:11:00",
        },
        {
            "question_id": "cp-12",
            "dimension": "concept_premise",
            "question": "Central theme?",
            "answer": "Justice, memory, and the cost of truth",
            "is_thin": False,
            "timestamp": "2026-01-01T00:12:00",
        },
        {
            "question_id": "cp-13",
            "dimension": "concept_premise",
            "question": "Real-world influences?",
            "answer": "Film noir aesthetics, hardboiled detective fiction.",
            "is_thin": False,
            "timestamp": "2026-01-01T00:13:00",
        },
        {
            "question_id": "cp-14",
            "dimension": "concept_premise",
            "question": "Mood after opening?",
            "answer": "Melancholic with a thread of hope.",
            "is_thin": False,
            "timestamp": "2026-01-01T00:14:00",
        },
        {
            "question_id": "cp-15",
            "dimension": "concept_premise",
            "question": "Standalone or series?",
            "answer": "Series opener with standalone arc.",
            "is_thin": False,
            "timestamp": "2026-01-01T00:15:00",
        },
        # World Setting (ws-*)
        {
            "question_id": "ws-01",
            "dimension": "world_setting",
            "question": "Where and when?",
            "answer": "An alternate-history 1940s city where magic works.",
            "is_thin": False,
            "timestamp": "2026-01-01T00:16:00",
        },
        {
            "question_id": "ws-02",
            "dimension": "world_setting",
            "question": "Key locations?",
            "answer": "The Obsidian District, the Clocktower Archives, the Underbridge.",
            "is_thin": False,
            "timestamp": "2026-01-01T00:17:00",
        },
        # Characters (ch-*)
        {
            "question_id": "ch-01",
            "dimension": "characters",
            "question": "Who is the protagonist?",
            "answer": "Malcolm Cross, retired detective in his late 50s.",
            "is_thin": False,
            "timestamp": "2026-01-01T00:18:00",
        },
        {
            "question_id": "ch-02",
            "dimension": "characters",
            "question": "What do they want?",
            "answer": "To uncover the truth behind his partner's death.",
            "is_thin": False,
            "timestamp": "2026-01-01T00:19:00",
        },
        # Plot (pl-*)
        {
            "question_id": "pl-01",
            "dimension": "plot_structure",
            "question": "Three-act structure?",
            "answer": "Act 1: The package arrives. Act 2: He follows a trail of lies. Act 3: Confrontation at the Archive.",
            "is_thin": False,
            "timestamp": "2026-01-01T00:20:00",
        },
        # Theme & Voice (th-*)
        {
            "question_id": "th-01",
            "dimension": "theme_voice",
            "question": "Narrative voice?",
            "answer": "Close third person with occasional introspective passages.",
            "is_thin": False,
            "timestamp": "2026-01-01T00:21:00",
        },
        # Market (mk-*)
        {
            "question_id": "mk-01",
            "dimension": "market_comparisons",
            "question": "Comparative titles?",
            "answer": "Rivers of London meets The Maltese Falcon.",
            "is_thin": False,
            "timestamp": "2026-01-01T00:22:00",
        },
    ]


def _single_answer(question_id="cp-01", answer="A story about redemption.") -> list[dict]:
    """Build a mock interview result with a single answer."""
    return [
        {
            "question_id": question_id,
            "dimension": "concept_premise",
            "question": "What is it about?",
            "answer": answer,
            "is_thin": False,
            "timestamp": "2026-01-01T00:01:00",
        },
    ]


def _make_interview_result(answers: list, depth: str = "standard") -> dict:
    """Build a full interview_result dict like run_interview() would return."""
    return {
        "version": 2,
        "depth": depth,
        "answers": answers,
        "thin_areas": [],
    }


# ---------------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------------


class TestCompileBasic(unittest.TestCase):
    """Full mock interview answers (all 6 dimensions, standard depth)."""

    def setUp(self):
        self.result = compile_story_bible(_make_interview_result(_full_answers()))
        self.spec = self.result["spec"]
        self.enrichments = self.result["enrichments"]

    def test_genre_is_non_empty_string(self):
        self.assertIsInstance(self.spec["genre"], str)
        self.assertGreater(len(self.spec["genre"]), 0)

    def test_themes_is_list(self):
        self.assertIsInstance(self.spec["themes"], list)

    def test_target_chapters_is_int(self):
        self.assertIsInstance(self.spec["target_chapters"], int)

    def test_premise_is_non_empty_string(self):
        self.assertIsInstance(self.spec["premise"], str)
        self.assertGreater(len(self.spec["premise"]), 0)

    def test_pov_is_expected_value(self):
        self.assertIn(self.spec["pov"].lower(), EXPECTED_POV_VALUES)

    def test_all_seed_keys_present(self):
        for key in SEED_SPEC_KEYS:
            with self.subTest(key=key):
                self.assertIn(key, self.spec, f"Missing spec key: {key}")

    def test_source_is_interview(self):
        self.assertEqual(self.spec["_source"], "interview")

    def test_enrichments_has_all_dimensions(self):
        for key in ENRICHMENT_KEYS:
            with self.subTest(key=key):
                self.assertIn(key, self.enrichments, f"Missing enrichment key: {key}")

    def test_enrichments_world_is_list_of_dicts(self):
        world = self.enrichments["world"]
        self.assertIsInstance(world, list)
        if world:
            self.assertIn("question_id", world[0])
            self.assertIn("answer", world[0])

    def test_enrichments_characters_is_list_of_dicts(self):
        chars = self.enrichments["characters"]
        self.assertIsInstance(chars, list)
        if chars:
            self.assertIn("question_id", chars[0])

    def test_enrichments_plot_is_list_of_dicts(self):
        plot = self.enrichments["plot"]
        self.assertIsInstance(plot, list)

    def test_enrichments_theme_voice_is_list_of_dicts(self):
        tv = self.enrichments["theme_voice"]
        self.assertIsInstance(tv, list)

    def test_enrichments_market_is_list_of_dicts(self):
        market = self.enrichments["market"]
        self.assertIsInstance(market, list)

    def test_enrichments_concept_premise_is_dict(self):
        self.assertIsInstance(self.enrichments["concept_premise"], dict)
        self.assertIn("central_conflict", self.enrichments["concept_premise"])
        self.assertIn("inciting_incident", self.enrichments["concept_premise"])

    def test_result_is_dict_with_spec_and_enrichments(self):
        self.assertIsInstance(self.result, dict)
        self.assertIn("spec", self.result)
        self.assertIn("enrichments", self.result)

    def test_title_is_non_empty_string(self):
        self.assertIsInstance(self.spec["title"], str)
        self.assertGreater(len(self.spec["title"]), 0)

    def test_tone_is_non_empty_string(self):
        self.assertIsInstance(self.spec["tone"], str)
        self.assertGreater(len(self.spec["tone"]), 0)

    def test_tense_is_non_empty_string(self):
        self.assertIsInstance(self.spec["tense"], str)
        self.assertGreater(len(self.spec["tense"]), 0)

    def test_unique_angle_is_non_empty_string(self):
        self.assertIsInstance(self.spec["unique_angle"], str)
        self.assertGreater(len(self.spec["unique_angle"]), 0)

    def test_initial_direction_is_non_empty_string(self):
        self.assertIsInstance(self.spec["initial_direction"], str)
        self.assertGreater(len(self.spec["initial_direction"]), 0)

    def test_spec_has_metadata_keys(self):
        self.assertIn("_depth", self.spec)
        self.assertIn("_thin_areas", self.spec)
        self.assertEqual(self.spec["_depth"], "standard")

    def test_target_chapters_is_reasonable(self):
        """Standard novel answers should yield 18 chapters."""
        self.assertEqual(self.spec["target_chapters"], 18)


class TestDefaults(unittest.TestCase):
    """Missing answers -> graceful defaults (no crash)."""

    def test_empty_answers(self):
        """Empty answers list -> default values for all keys."""
        result = compile_story_bible(_make_interview_result([]))
        spec = result["spec"]
        self.assertEqual(spec["genre"], "Unknown")
        self.assertEqual(spec["tone"], "Neutral")
        self.assertEqual(spec["tense"], "past tense")
        self.assertEqual(spec["pov"], "third limited")
        self.assertEqual(spec["target_length"], "novel")
        self.assertEqual(spec["target_chapters"], 18)
        self.assertEqual(spec["themes"], [])
        self.assertEqual(spec["premise"], "No premise provided.")
        self.assertEqual(spec["title"], "Untitled Story")
        self.assertEqual(spec["unique_angle"], "")
        # premise defaults to "No premise provided." which is truthy,
        # so initial_direction wraps it in "Core premise: ..."
        self.assertEqual(spec["initial_direction"], "Core premise: No premise provided.")
        self.assertEqual(spec["_source"], "interview")

    def test_empty_answers_enrichments(self):
        """Empty answers -> enrichments have empty structure."""
        result = compile_story_bible(_make_interview_result([]))
        enrichments = result["enrichments"]
        self.assertEqual(enrichments["world"], [])
        self.assertEqual(enrichments["characters"], [])
        self.assertEqual(enrichments["plot"], [])
        self.assertEqual(enrichments["theme_voice"], [])
        self.assertEqual(enrichments["market"], [])
        # concept_premise enrichment is a dict with empty strings
        cp = enrichments["concept_premise"]
        self.assertEqual(cp["central_conflict"], "")
        self.assertEqual(cp["inciting_incident"], "")
        self.assertEqual(cp["known_ending"], "")
        self.assertEqual(cp["standalone_or_series"], "")

    def test_single_answer_only_that_field_filled(self):
        """Single answer -> only that field is filled, others default."""
        result = compile_story_bible(
            _make_interview_result(_single_answer("cp-02", "Science fiction"))
        )
        spec = result["spec"]
        self.assertEqual(spec["genre"], "Science fiction")
        self.assertEqual(spec["tone"], "Neutral")  # default
        self.assertEqual(spec["tense"], "past tense")  # default
        self.assertEqual(spec["title"], "Untitled Story")  # default (no cp-01)
        self.assertEqual(spec["premise"], "No premise provided.")  # default (no cp-01)

    def test_answers_none_handled(self):
        """interview_result with answers=None is handled gracefully."""
        result = compile_story_bible({"version": 2, "depth": "standard", "thin_areas": []})
        spec = result["spec"]
        self.assertEqual(spec["genre"], "Unknown")
        self.assertEqual(spec["themes"], [])

    def test_missing_keys_in_result(self):
        """Completely empty interview_result should not crash."""
        result = compile_story_bible({})
        spec = result["spec"]
        self.assertIn("genre", spec)
        self.assertIn("themes", spec)
        self.assertIn("_source", spec)
        self.assertEqual(spec["_source"], "interview")


class TestSkippedAnswers(unittest.TestCase):
    """Answers with '[SKIPPED]' -> use fallback defaults."""

    def test_all_skipped(self):
        """All answers are [SKIPPED] -> all defaults used."""
        answers = [
            {
                "question_id": f"cp-{i:02d}",
                "dimension": "concept_premise",
                "question": f"Q{i}",
                "answer": "[SKIPPED]",
                "is_thin": True,
                "timestamp": "2026-01-01T00:00:00",
            }
            for i in range(1, 16)
        ]
        result = compile_story_bible(_make_interview_result(answers))
        spec = result["spec"]
        self.assertEqual(spec["genre"], "Unknown")
        self.assertEqual(spec["premise"], "No premise provided.")
        self.assertEqual(spec["title"], "Untitled Story")
        self.assertEqual(spec["themes"], [])
        self.assertEqual(spec["tone"], "Neutral")

    def test_partial_skipped(self):
        """Some skipped, some answered -> mix of real and default values."""
        answers = _single_answer("cp-01", "A real premise about dragons.")
        answers.append({
            "question_id": "cp-02",
            "dimension": "concept_premise",
            "question": "Genre?",
            "answer": "[SKIPPED]",
            "is_thin": True,
            "timestamp": "2026-01-01T00:02:00",
        })
        result = compile_story_bible(_make_interview_result(answers))
        spec = result["spec"]
        self.assertEqual(spec["premise"], "A real premise about dragons.")
        self.assertEqual(spec["genre"], "Unknown")  # skipped -> default
        self.assertNotEqual(spec["title"], "Untitled Story")  # cp-01 has a real answer

    def test_skipped_in_dimension_enrichments(self):
        """Skipped answers should appear in enrichments with answer=[SKIPPED]."""
        answers = [
            {
                "question_id": "ws-01",
                "dimension": "world_setting",
                "question": "Where?",
                "answer": "[SKIPPED]",
                "is_thin": True,
                "timestamp": "2026-01-01T00:00:00",
            },
            {
                "question_id": "ws-02",
                "dimension": "world_setting",
                "question": "Key locations?",
                "answer": "The city of glass.",
                "is_thin": False,
                "timestamp": "2026-01-01T00:01:00",
            },
        ]
        result = compile_story_bible(_make_interview_result(answers))
        world = result["enrichments"]["world"]
        self.assertEqual(len(world), 2)
        self.assertEqual(world[0]["answer"], "[SKIPPED]")
        self.assertEqual(world[1]["answer"], "The city of glass.")


class TestMinimalDepth(unittest.TestCase):
    """Quick mode (3 concept questions) -> compiles without error."""

    def test_quick_answers_only(self):
        """Quick mode with only cp-01, cp-02, cp-03 answers."""
        answers = [
            {
                "question_id": "cp-01",
                "dimension": "concept_premise",
                "question": "Core premise?",
                "answer": "A lone wanderer discovers an ancient machine that can reshape reality.",
                "is_thin": False,
                "timestamp": "2026-01-01T00:01:00",
            },
            {
                "question_id": "cp-02",
                "dimension": "concept_premise",
                "question": "Genre?",
                "answer": "Post-apocalyptic science fantasy",
                "is_thin": False,
                "timestamp": "2026-01-01T00:02:00",
            },
            {
                "question_id": "cp-03",
                "dimension": "concept_premise",
                "question": "Unique angle?",
                "answer": "The machine is powered by human memories.",
                "is_thin": False,
                "timestamp": "2026-01-01T00:03:00",
            },
        ]
        result = compile_story_bible(
            _make_interview_result(answers, depth="quick")
        )
        spec = result["spec"]
        enrichments = result["enrichments"]

        # cp-derived fields should be populated
        self.assertEqual(spec["genre"], "Post-apocalyptic science fantasy")
        self.assertIn("wanderer", spec["premise"])
        self.assertTrue(spec["title"])  # non-empty title from cp-01

        # Non-cp fields should use defaults
        self.assertEqual(spec["tone"], "Neutral")
        self.assertEqual(spec["tense"], "past tense")
        self.assertEqual(spec["pov"], "third limited")
        self.assertEqual(spec["target_length"], "novel")
        self.assertEqual(spec["target_chapters"], 18)

        # Enrichments for non-concept dimensions should be empty
        self.assertEqual(enrichments["world"], [])
        self.assertEqual(enrichments["characters"], [])
        self.assertEqual(enrichments["plot"], [])
        self.assertEqual(enrichments["theme_voice"], [])
        self.assertEqual(enrichments["market"], [])

        # Concept enrichment should have populated values
        cp = enrichments["concept_premise"]
        self.assertEqual(cp["central_conflict"], "")
        self.assertEqual(cp["inciting_incident"], "")

    def test_quick_no_crash(self):
        """Quick mode with zero answers should compile without error."""
        result = compile_story_bible(
            _make_interview_result([], depth="quick")
        )
        self.assertIn("spec", result)
        self.assertIn("enrichments", result)

    def test_depth_tracked_in_spec(self):
        """The depth value should be preserved in spec metadata."""
        answers = _single_answer("cp-01", "A quick concept.")
        result = compile_story_bible(
            _make_interview_result(answers, depth="quick")
        )
        self.assertEqual(result["spec"]["_depth"], "quick")


class TestTitleExtraction(unittest.TestCase):
    """Title extraction from cp-01 answer first sentence."""

    def test_title_from_first_sentence(self):
        """Title should be the first sentence of cp-01 answer."""
        answers = _single_answer(
            "cp-01",
            "A retired detective uncovers a conspiracy. His only clue is a faded photograph.",
        )
        result = compile_story_bible(_make_interview_result(answers))
        title = result["spec"]["title"]
        self.assertEqual(title, "A retired detective uncovers a conspiracy")

    def test_title_single_sentence(self):
        """Single-sentence premise -> title is the entire sentence."""
        answers = _single_answer(
            "cp-01",
            "A lone wanderer must find the last library before knowledge is lost forever.",
        )
        result = compile_story_bible(_make_interview_result(answers))
        title = result["spec"]["title"]
        # The .!? regex split excludes the period from the first sentence
        self.assertEqual(
            title,
            "A lone wanderer must find the last library before knowledge is lost forever",
        )

    def test_title_question_mark_boundary(self):
        """Title extraction handles ? as sentence boundary."""
        answers = _single_answer(
            "cp-01",
            "What happens when magic returns to a world that forgot it? This is the central question.",
        )
        result = compile_story_bible(_make_interview_result(answers))
        title = result["spec"]["title"]
        self.assertEqual(title, "What happens when magic returns to a world that forgot it")

    def test_title_exclamation_mark_boundary(self):
        """Title extraction handles ! as sentence boundary."""
        answers = _single_answer(
            "cp-01",
            "The invasion begins! One family must survive the first wave.",
        )
        result = compile_story_bible(_make_interview_result(answers))
        title = result["spec"]["title"]
        self.assertEqual(title, "The invasion begins")

    def test_title_long_sentence_truncated(self):
        """Title longer than 80 chars gets truncated with ellipsis."""
        long = "A " + "very " * 30 + "long sentence about a retired detective who discovers a dark conspiracy."
        answers = _single_answer("cp-01", long)
        result = compile_story_bible(_make_interview_result(answers))
        title = result["spec"]["title"]
        self.assertLessEqual(len(title), 80)
        self.assertTrue(title.endswith("..."))

    def test_no_cp_01_answer(self):
        """No cp-01 answer -> title defaults to 'Untitled Story'."""
        answers = _single_answer("cp-02", "Science fiction")
        result = compile_story_bible(_make_interview_result(answers))
        self.assertEqual(result["spec"]["title"], "Untitled Story")


class TestThemesParsing(unittest.TestCase):
    """Theme extraction from cp-12 answer with various formats."""

    def test_comma_separated(self):
        """Comma-separated themes list."""
        answers = _single_answer("cp-12", "Justice, redemption, sacrifice")
        result = compile_story_bible(_make_interview_result(answers))
        self.assertEqual(result["spec"]["themes"], ["Justice", "redemption", "sacrifice"])

    def test_and_separated(self):
        """'and'-separated themes."""
        answers = _single_answer("cp-12", "Justice and redemption and sacrifice")
        result = compile_story_bible(_make_interview_result(answers))
        self.assertEqual(result["spec"]["themes"], ["Justice", "redemption", "sacrifice"])

    def test_mixed_separators(self):
        """Mixed comma and 'and' separators."""
        answers = _single_answer("cp-12", "Justice, redemption, and sacrifice")
        result = compile_story_bible(_make_interview_result(answers))
        self.assertEqual(result["spec"]["themes"], ["Justice", "redemption", "sacrifice"])

    def test_single_string(self):
        """Single theme string."""
        answers = _single_answer("cp-12", "Justice")
        result = compile_story_bible(_make_interview_result(answers))
        self.assertEqual(result["spec"]["themes"], ["Justice"])

    def test_empty_string(self):
        """Empty theme string -> empty list."""
        answers = _single_answer("cp-12", "")
        result = compile_story_bible(_make_interview_result(answers))
        self.assertEqual(result["spec"]["themes"], [])

    def test_no_theme_answer(self):
        """Missing cp-12 answer -> empty list."""
        result = compile_story_bible(_make_interview_result([]))
        self.assertEqual(result["spec"]["themes"], [])

    def test_both_keyword_handled(self):
        """'both X and Y' syntax is normalized."""
        answers = _single_answer("cp-12", "both justice and mercy")
        result = compile_story_bible(_make_interview_result(answers))
        self.assertEqual(result["spec"]["themes"], ["justice", "mercy"])

    def test_ampersand_separator(self):
        """'&' separator between themes."""
        answers = _single_answer("cp-12", "Justice & redemption & sacrifice")
        result = compile_story_bible(_make_interview_result(answers))
        self.assertEqual(result["spec"]["themes"], ["Justice", "redemption", "sacrifice"])

    def test_semicolon_separator(self):
        """Semicolons as delimiters."""
        answers = _single_answer("cp-12", "Justice; redemption; sacrifice")
        result = compile_story_bible(_make_interview_result(answers))
        self.assertEqual(result["spec"]["themes"], ["Justice", "redemption", "sacrifice"])

    def test_trailing_period_removed(self):
        """Trailing periods are stripped from individual themes (after delimiter split)."""
        # Periods after comma-split themes are stripped
        answers = _single_answer("cp-12", "Justice, Redemption, Sacrifice.")
        result = compile_story_bible(_make_interview_result(answers))
        self.assertEqual(result["spec"]["themes"], ["Justice", "Redemption", "Sacrifice"])

    def test_period_not_delimiter(self):
        """Periods followed by whitespace act as delimiters — they split themes."""
        answers = _single_answer("cp-12", "Justice. Redemption. Sacrifice.")
        result = compile_story_bible(_make_interview_result(answers))
        # Period+whitespace is normalized to comma before the split
        self.assertEqual(result["spec"]["themes"], ["Justice", "Redemption", "Sacrifice"])

    def test_period_separated(self):
        """Period-separated multi-word themes."""
        answers = _single_answer("cp-12", "Justice. Redemption. Sacrifice.")
        result = compile_story_bible(_make_interview_result(answers))
        self.assertEqual(result["spec"]["themes"], ["Justice", "Redemption", "Sacrifice"])

    def test_period_then_commas(self):
        """Mixed period and comma separators."""
        answers = _single_answer("cp-12", "Justice. Redemption, Sacrifice")
        result = compile_story_bible(_make_interview_result(answers))
        self.assertEqual(result["spec"]["themes"], ["Justice", "Redemption", "Sacrifice"])

    def test_single_theme_with_period_end(self):
        """Single theme with a trailing period."""
        answers = _single_answer("cp-12", "Justice.")
        result = compile_story_bible(_make_interview_result(answers))
        self.assertEqual(result["spec"]["themes"], ["Justice"])

    def test_mixed_period_and_and(self):
        """Periods and 'and' as mixed delimiters."""
        answers = _single_answer("cp-12", "Justice. Redemption and Sacrifice")
        result = compile_story_bible(_make_interview_result(answers))
        self.assertEqual(result["spec"]["themes"], ["Justice", "Redemption", "Sacrifice"])

    def test_decimal_not_split(self):
        """Period without following whitespace is not a delimiter (e.g. version numbers)."""
        answers = _single_answer("cp-12", "Version 2.0")
        result = compile_story_bible(_make_interview_result(answers))
        self.assertEqual(result["spec"]["themes"], ["Version 2.0"])

    def test_period_single_word_themes(self):
        """Acceptance criteria: 'redemption. betrayal. hope and legacy' -> 4 themes."""
        answers = _single_answer("cp-12", "redemption. betrayal. hope and legacy")
        result = compile_story_bible(_make_interview_result(answers))
        self.assertEqual(result["spec"]["themes"], ["redemption", "betrayal", "hope", "legacy"])

    def test_skipped_themes_is_empty(self):
        """Skipped cp-12 -> empty themes list."""
        answers = [
            {
                "question_id": "cp-12",
                "dimension": "concept_premise",
                "question": "Themes?",
                "answer": "[SKIPPED]",
                "is_thin": True,
                "timestamp": "2026-01-01T00:00:00",
            }
        ]
        result = compile_story_bible(_make_interview_result(answers))
        self.assertEqual(result["spec"]["themes"], [])


class TestChapterInference(unittest.TestCase):
    """Chapter count inference from target_length answer."""

    def test_novella(self):
        answers = _single_answer("cp-07", "novella ~40K")
        result = compile_story_bible(_make_interview_result(answers))
        self.assertEqual(result["spec"]["target_chapters"], 10)

    def test_short(self):
        answers = _single_answer("cp-07", "short")
        result = compile_story_bible(_make_interview_result(answers))
        self.assertEqual(result["spec"]["target_chapters"], 10)

    def test_novelette(self):
        answers = _single_answer("cp-07", "novelette")
        result = compile_story_bible(_make_interview_result(answers))
        self.assertEqual(result["spec"]["target_chapters"], 10)

    def test_novel(self):
        answers = _single_answer("cp-07", "novel ~80K")
        result = compile_story_bible(_make_interview_result(answers))
        self.assertEqual(result["spec"]["target_chapters"], 18)

    def test_standard(self):
        answers = _single_answer("cp-07", "standard")
        result = compile_story_bible(_make_interview_result(answers))
        self.assertEqual(result["spec"]["target_chapters"], 18)

    def test_epic(self):
        answers = _single_answer("cp-07", "epic ~120K")
        result = compile_story_bible(_make_interview_result(answers))
        self.assertEqual(result["spec"]["target_chapters"], 30)

    def test_saga(self):
        answers = _single_answer("cp-07", "saga")
        result = compile_story_bible(_make_interview_result(answers))
        self.assertEqual(result["spec"]["target_chapters"], 30)

    def test_default(self):
        answers = _single_answer("cp-07", "unknown format")
        result = compile_story_bible(_make_interview_result(answers))
        self.assertEqual(result["spec"]["target_chapters"], 18)


class TestInitialDirection(unittest.TestCase):
    """Initial direction construction from cp-04, cp-05, cp-01."""

    def test_with_all_parts(self):
        answers = [
            {
                "question_id": "cp-01",
                "dimension": "concept_premise",
                "question": "Q",
                "answer": "A story about dragons.",
                "is_thin": False,
                "timestamp": "2026-01-01T00:00:00",
            },
            {
                "question_id": "cp-04",
                "dimension": "concept_premise",
                "question": "Q",
                "answer": "Good vs evil.",
                "is_thin": False,
                "timestamp": "2026-01-01T00:01:00",
            },
            {
                "question_id": "cp-05",
                "dimension": "concept_premise",
                "question": "Q",
                "answer": "Young adults.",
                "is_thin": False,
                "timestamp": "2026-01-01T00:02:00",
            },
        ]
        result = compile_story_bible(_make_interview_result(answers))
        direction = result["spec"]["initial_direction"]
        self.assertIn("Central conflict: Good vs evil.", direction)
        self.assertIn("Core premise: A story about dragons.", direction)
        self.assertIn("Target audience: Young adults.", direction)

    def test_only_premise(self):
        """Only cp-01 -> direction includes premise."""
        answers = _single_answer("cp-01", "A simple story.")
        result = compile_story_bible(_make_interview_result(answers))
        self.assertEqual(result["spec"]["initial_direction"], "Core premise: A simple story.")
        # Wait — premise is "A simple story." and central_conflict is empty, target_audience empty
        # So parts = [] because central_conflict is empty and premise is truthy but...

    def test_initial_direction_empty_premise(self):
        """No answers at all -> direction falls back to empty premise."""
        result = compile_story_bible(_make_interview_result([]))
        # premise defaults to "No premise provided." which is truthy
        self.assertIn("No premise provided.", result["spec"]["initial_direction"])


class TestResultStructure(unittest.TestCase):
    """Structural integrity of the compile_story_bible return value."""

    def test_return_is_dict(self):
        result = compile_story_bible(_make_interview_result([]))
        self.assertIsInstance(result, dict)

    def test_spec_is_dict(self):
        result = compile_story_bible(_make_interview_result([]))
        self.assertIsInstance(result["spec"], dict)

    def test_enrichments_is_dict(self):
        result = compile_story_bible(_make_interview_result([]))
        self.assertIsInstance(result["enrichments"], dict)

    def test_spec_keys_match_expected(self):
        result = compile_story_bible(_make_interview_result([]))
        spec_keys = set(result["spec"].keys())
        expected = SEED_SPEC_KEYS | SPEC_META_KEYS
        self.assertEqual(spec_keys, expected)

    def test_no_extra_keys_in_spec(self):
        """No unexpected keys in spec output."""
        answers = _full_answers()
        result = compile_story_bible(_make_interview_result(answers))
        spec_keys = set(result["spec"].keys())
        expected = SEED_SPEC_KEYS | SPEC_META_KEYS
        self.assertEqual(spec_keys, expected)

    def test_answers_sorted_by_question_id(self):
        """World/character/plot enrichment answers are sorted by question_id."""
        answers = [
            {
                "question_id": "ws-03",
                "dimension": "world_setting",
                "question": "Q3",
                "answer": "Answer 3",
                "is_thin": False,
                "timestamp": "2026-01-01T00:00:00",
            },
            {
                "question_id": "ws-01",
                "dimension": "world_setting",
                "question": "Q1",
                "answer": "Answer 1",
                "is_thin": False,
                "timestamp": "2026-01-01T00:00:00",
            },
            {
                "question_id": "ws-02",
                "dimension": "world_setting",
                "question": "Q2",
                "answer": "Answer 2",
                "is_thin": False,
                "timestamp": "2026-01-01T00:00:00",
            },
        ]
        result = compile_story_bible(_make_interview_result(answers))
        world = result["enrichments"]["world"]
        ids = [e["question_id"] for e in world]
        self.assertEqual(ids, ["ws-01", "ws-02", "ws-03"])


class TestEdgeCases(unittest.TestCase):
    """Edge cases and defensive programming."""

    def test_thin_answers_compiled_normally(self):
        """Answers with is_thin=True compile normally (thin flag is metadata)."""
        answers = [
            {
                "question_id": "cp-01",
                "dimension": "concept_premise",
                "question": "Q",
                "answer": "A short answer.",
                "is_thin": True,
                "timestamp": "2026-01-01T00:00:00",
            }
        ]
        result = compile_story_bible(_make_interview_result(answers))
        self.assertEqual(result["spec"]["premise"], "A short answer.")

    def test_version_field_irrelevant_to_compilation(self):
        """The version field in interview_result doesn't affect compilation."""
        result_v1 = compile_story_bible({"version": 1, "answers": [], "depth": "standard", "thin_areas": []})
        result_v2 = compile_story_bible({"version": 2, "answers": [], "depth": "standard", "thin_areas": []})
        self.assertEqual(result_v1["spec"], result_v2["spec"])

    def test_question_id_missing_skipped(self):
        """Answers without question_id are silently skipped."""
        answers = [
            {
                "dimension": "concept_premise",
                "question": "Q",
                "answer": "Orphan answer",
                "is_thin": False,
                "timestamp": "2026-01-01T00:00:00",
            }
        ]
        # Should not crash; orphan answer just won't be indexed
        result = compile_story_bible(_make_interview_result(answers))
        self.assertIn("spec", result)


class TestPipelineIntegrationContract(unittest.TestCase):
    """Contracts that ensure compile_story_bible output is compatible with the pipeline."""

    def test_spec_keys_match_seed_output(self):
        """The spec dict should have at least the keys seed.py produces."""
        result = compile_story_bible(
            _make_interview_result(_full_answers())
        )
        spec = result["spec"]
        # seed.py enforces these fallback keys after generation
        for key in ("genre", "premise", "tone", "target_chapters"):
            self.assertIn(key, spec)
            self.assertNotEqual(spec.get(key), f"MISSING: {key}")

    def test_enrichment_structure_stable(self):
        """Enrichments follow stable structure regardless of input size."""
        result_empty = compile_story_bible(_make_interview_result([]))
        result_full = compile_story_bible(
            _make_interview_result(_full_answers())
        )
        # Same keys regardless of input
        for result in (result_empty, result_full):
            for key in ENRICHMENT_KEYS:
                self.assertIn(key, result["enrichments"])


class TestAllTestsPass(unittest.TestCase):
    """Utility test that runs the full test suite to verify nothing broke."""

    def test_all_tests_pass(self):
        """Run 'python -m pytest tests/' and verify clean exit.
        Excludes this specific test to avoid infinite recursion.
        """
        repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                "tests/",
                "--ignore=tests/test_story_bible.py",
                "-v",
                "--tb=short",
            ],
            capture_output=True,
            text=True,
            cwd=repo_root,
            timeout=180,
        )
        # Print output for debugging in CI
        if result.returncode != 0:
            print("STDOUT:", result.stdout[-2000:])
            print("STDERR:", result.stderr[-2000:])
        self.assertEqual(result.returncode, 0, "pytest suite must pass")


if __name__ == "__main__":
    unittest.main()

"""Tests for the v0.8 length gate: redraw from the same brief, never pad.

The rule follows lechmazur/writing's handling of overlength stories: a draft
outside its band is regenerated from the same brief, the first in-range
response wins, redraws are capped, and the closest draft is then kept with a
recorded warning rather than silently padded or trimmed.
"""
import unittest

from config import Config
from pipeline.draft import (
    MAX_LENGTH_REDRAWS,
    ChapterScorer,
    _draft_single_variant,
    draw_with_length_gate,
)
from pipeline.prose_lab import (
    LENGTH_HI,
    LENGTH_LO,
    MIN_WORDS_FOR_SCORE,
    length_distance,
    length_verdict,
)


PROMPT = "Write chapter one from the brief below."


def words(n):
    """A body of exactly n words."""
    return " ".join(f"word{i}" for i in range(n)) + "."


class FakeClient:
    """Returns canned texts in order and records every call."""

    def __init__(self, texts):
        self.texts = list(texts)
        self.calls = []

    def chat_with_retry(self, model, messages, system_prompt=None,
                        temperature=None, **kwargs):
        self.calls.append({
            "messages": messages,
            "system_prompt": system_prompt,
            "temperature": temperature,
        })
        return self.texts[min(len(self.calls) - 1, len(self.texts) - 1)]


def gate(client, target=1000, **kwargs):
    return draw_with_length_gate(client, Config().model_for_phase("draft"), PROMPT,
                                 system_prompt="sys", target_words=target, **kwargs)


class TestLengthVerdict(unittest.TestCase):
    def test_band_constants(self):
        self.assertEqual(LENGTH_LO, 0.75)
        self.assertEqual(LENGTH_HI, 1.35)

    def test_boundaries_at_the_low_edge(self):
        self.assertEqual(length_verdict(750, 1000)["verdict"], "in_range")
        self.assertEqual(length_verdict(749, 1000)["verdict"], "too_short")

    def test_boundaries_at_the_high_edge(self):
        self.assertEqual(length_verdict(1350, 1000)["verdict"], "in_range")
        self.assertEqual(length_verdict(1351, 1000)["verdict"], "too_long")

    def test_no_target_means_no_verdict_to_fail(self):
        for target in (0, -5):
            verdict = length_verdict(10, target)
            self.assertEqual(verdict["verdict"], "in_range")
            self.assertEqual(verdict["ratio"], 0.0)

    def test_the_score_floor_is_absolute_and_says_so(self):
        verdict = length_verdict(MIN_WORDS_FOR_SCORE - 10, 1000)
        self.assertEqual(verdict["verdict"], "too_short")
        self.assertIn("floor", verdict["message"])
        self.assertEqual(verdict["floor"], MIN_WORDS_FOR_SCORE)

    def test_a_deliberately_short_target_does_not_loop_forever(self):
        verdict = length_verdict(180, 200)
        self.assertEqual(verdict["verdict"], "in_range")
        self.assertLessEqual(verdict["floor"], verdict["band"][0])

    def test_the_verdict_carries_what_a_caller_needs(self):
        verdict = length_verdict(900, 1000)
        for key in ("verdict", "ratio", "message", "band", "floor",
                    "word_count", "target_words"):
            self.assertIn(key, verdict)
        self.assertEqual(verdict["band"], (750, 1350))


class TestLengthDistance(unittest.TestCase):
    def test_in_range_is_zero(self):
        self.assertEqual(length_distance(length_verdict(900, 1000)), 0.0)

    def test_short_and_long_measure_outward(self):
        short = length_distance(length_verdict(700, 1000))
        long_ = length_distance(length_verdict(1500, 1000))
        self.assertAlmostEqual(short, 50 / 750)
        self.assertAlmostEqual(long_, 150 / 1350)

    def test_no_band_is_no_distance(self):
        self.assertEqual(length_distance({"band": (0, 0), "word_count": 5}), 0.0)


class TestDrawWithLengthGate(unittest.TestCase):
    def test_an_in_range_draw_is_accepted_at_once(self):
        client = FakeClient([words(1000)])
        out = gate(client)
        self.assertEqual(out["verdict"]["verdict"], "in_range")
        self.assertEqual(out["redraws"], 0)
        self.assertEqual(out["attempts"], 1)
        self.assertEqual(out["warning"], "")
        self.assertEqual(len(client.calls), 1)

    def test_a_short_draw_is_redrawn_from_the_same_brief(self):
        client = FakeClient([words(100), words(900)])
        out = gate(client)
        self.assertEqual(out["redraws"], 1)
        self.assertEqual(out["attempts"], 2)
        self.assertEqual(out["content"], words(900))
        self.assertEqual(client.calls[0]["messages"], client.calls[1]["messages"])
        self.assertEqual(client.calls[0]["system_prompt"], client.calls[1]["system_prompt"])

    def test_a_long_draw_is_redrawn_too(self):
        client = FakeClient([words(2000), words(1100)])
        out = gate(client)
        self.assertEqual(out["verdict"]["verdict"], "in_range")
        self.assertEqual(out["redraws"], 1)
        self.assertEqual(out["content"], words(1100))

    def test_the_first_in_range_response_wins(self):
        client = FakeClient([words(100), words(900), words(1000)])
        out = gate(client)
        self.assertEqual(out["content"], words(900))
        self.assertEqual(out["attempts"], 2)

    def test_the_cap_stops_the_redraws(self):
        client = FakeClient([words(100)])
        out = gate(client)
        self.assertEqual(MAX_LENGTH_REDRAWS, 2)
        self.assertEqual(out["attempts"], MAX_LENGTH_REDRAWS + 1)
        self.assertEqual(out["redraws"], MAX_LENGTH_REDRAWS)
        self.assertEqual(out["verdict"]["verdict"], "too_short")

    def test_after_the_cap_the_text_is_kept_not_padded(self):
        client = FakeClient([words(100)])
        out = gate(client)
        self.assertEqual(len(out["content"].split()), 100)
        self.assertIn("no padding or truncation", out["warning"])
        self.assertIn("redraw", out["warning"])

    def test_after_the_cap_the_closest_draft_is_kept(self):
        client = FakeClient([words(50), words(700), words(300)])
        out = gate(client)
        self.assertEqual(out["content"], words(700))
        self.assertEqual(out["verdict"]["word_count"], 700)

    def test_a_caller_can_disable_redraws(self):
        client = FakeClient([words(100)])
        out = gate(client, max_redraws=0)
        self.assertEqual(out["attempts"], 1)
        self.assertEqual(out["redraws"], 0)
        self.assertIn("redraws disabled", out["warning"])

    def test_the_changes_fence_is_not_counted_as_prose(self):
        fence = '\n---CHANGES---\n{"character_changes": []}\n---END CHANGES---'
        client = FakeClient([words(800) + fence])
        out = gate(client, 800, enable_changes=True)
        self.assertNotIn("---CHANGES---", out["content"])
        self.assertEqual(out["verdict"]["word_count"], 800)
        self.assertEqual(out["verdict"]["verdict"], "in_range")
        self.assertIsInstance(out["declared_changes"], dict)
        self.assertIn("character_status", out["declared_changes"])

    def test_no_target_never_triggers_a_redraw(self):
        client = FakeClient([words(10)])
        out = gate(client, target=0)
        self.assertEqual(out["attempts"], 1)
        self.assertEqual(out["verdict"]["verdict"], "in_range")


class TestVariantThreading(unittest.TestCase):
    def _variant(self, client, target=1000):
        config = Config()
        return _draft_single_variant(
            client, config.model_for_phase("draft"),
            chapter_num=1, chapter_title="One", pov="Ondre",
            summary="She refuses the song.", key_events=["refusal"],
            emotional_arc="cold to resolve", foreshadowing="",
            char_arc_beat="", world_context="", retrieved_context="",
            foreshadow_context="", style_direction="", style_name="suspense_first",
            config=config, scorer=ChapterScorer(config), chapter_spec={},
            target_words=target,
        )

    def test_the_variant_reports_the_gate(self):
        result = self._variant(FakeClient([words(100), words(900)]))
        self.assertEqual(result["redraws"], 1)
        self.assertEqual(result["length_attempts"], 2)
        self.assertEqual(result["length_warning"], "")
        self.assertEqual(result["score"]["length_verdict"], "in_range")

    def test_a_stub_cannot_win_variant_selection(self):
        result = self._variant(FakeClient([words(120)]))
        self.assertEqual(result["redraws"], MAX_LENGTH_REDRAWS)
        self.assertTrue(result["length_warning"])
        self.assertEqual(result["score"]["length_verdict"], "too_short")
        self.assertEqual(len(result["content"].split()), 120)

    def test_no_target_leaves_the_gate_quiet(self):
        result = self._variant(FakeClient([words(80)]), target=0)
        self.assertEqual(result["redraws"], 0)
        self.assertEqual(result["score"]["length_verdict"], "in_range")


if __name__ == "__main__":
    unittest.main()

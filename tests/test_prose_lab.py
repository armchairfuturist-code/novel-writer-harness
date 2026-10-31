"""Tests for pipeline.prose_lab: the deterministic prose gate.

The gate must (a) never punish good human-style prose, (b) always flag
machine slop, (c) emit explainable violations with fixes, and (d) behave
as a CI gate (exit 1 below threshold).
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest

from pipeline.prose_lab import analyze, bands_from, drift, measure, penalise_length, revision_lines

CLEAN = (
    "The dockmaster owed her money. That was the only reason to be on "
    "the pier at four in the morning, and the only reason she had not "
    "turned back at the fish market, where the lamps were still lit and "
    "the gutting tables steamed. 'Renna,' he said. He did not stand. "
    "'You're early.' 'Six days early.' He looked at the water. Somewhere "
    "out past the breakwater a bell buoy knocked against the swell, one "
    "dull note, then nothing for a while. 'I don't have it,' he said. "
    "'You have the skiff.' Now he looked at her. His hands were open on "
    "his knees, palms up, the way a man holds them when he has already "
    "decided what he is going to say next. She had seen the gesture "
    "twice before in her life. Once on a magistrate. Once on her "
    "father, the night he sold the trumpet.\n\n"
    "She waited until he looked up, then slid the envelope across the "
    "damp countertop. His fingers brushed hers, cold and quick, and he "
    "did not pull away. 'Read it later,' he said. 'Not here.' The bell "
    "buoy knocked again, farther out this time, and the gulls answered "
    "it. She took the skiff key from where it hung on its nail and "
    "walked out without looking back. The streetlights were already "
    "blue above the water, and she did not turn around. She walked to "
    "the edge of the pier and looked down at the black water, where the "
    "pilings rotted slowly and the crabs moved in the dark beneath them. "
    "She did not open the envelope. Not yet. She folded it once, twice, "
    "and put it in her coat pocket, next to her heart, where it would "
    "stay until she was ready to read what the dockmaster had died for."
    "\n\n"
    "Dawn came without colour, grey over grey, and the harbour filled "
    "with the sound of engines and the smell of diesel and fish. She "
    "stood on the pier and watched the boats come in, and for the first "
    "time in years she did not feel the need to speak to fill the "
    "silence. It was enough to watch the light return to the water."
)

SLOP = (
    "Suddenly, the sun rose over the quiet village. She felt a wave of "
    "dread wash over her as she walked toward the harbour. It was clear "
    "that nothing would ever be the same again. Little did she know that "
    "the letter in her pocket would change everything forever. She began "
    "to run, her heart racing, her breath catching in her throat. Time "
    "seemed to slow. The silence hung between the buildings, thick and "
    "heavy. A knowing smile crossed the dockmaster's face. His eyes "
    "narrowed. It wasn't fear, it was recognition. In that moment she "
    "realized that the sea had been waiting for her. The weight of it "
    "settled on her shoulders like a testament to everything she had "
    "lost. Ultimately, when all was said and done, she understood that "
    "this was a journey she could not avoid. The moment she stepped onto "
    "the gangplank, she knew that she was making a mistake. It was clear "
    "that the captain had been waiting for someone exactly like her, and "
    "little did she know that the voyage would change everything. Her "
    "heart raced as she climbed aboard, her breath caught in her throat, "
    "and time seemed to stop as the ropes were cast off. The silence "
    "hung over the deck like a shroud, heavy and final, and the weight "
    "of it pressed down on her chest like a testament to all the journeys "
    "she had never taken. Ultimately, when all was said and done, she "
    "understood that there was no going back."
    "\n\n"
    "In that moment she realized that the sea had been calling her name "
    "for years, and she had simply not been listening. The wind whipped "
    "her hair as she walked toward the rail, and she felt a wave of "
    "certainty that was literally the most amazing feeling she had ever "
    "known. She began to pray that the journey would end quickly, and "
    "she realized that she had begun something she could not finish."
)


class TestMeasure(unittest.TestCase):
    def test_keys_and_ranges(self):
        f = measure(CLEAN)
        for key in ("word_count", "sentence_mean", "sentence_sd", "dialogue_share",
                    "hapax_ratio", "dash_per_1k", "comma_per_sentence"):
            self.assertIn(key, f)
        self.assertGreater(f["word_count"], 300)
        self.assertBetween(f["dialogue_share"], 0.0, 1.0)
        self.assertBetween(f["hapax_ratio"], 0.0, 1.0)

    def assertBetween(self, x, lo, hi):
        self.assertGreaterEqual(x, lo)
        self.assertLessEqual(x, hi)


class TestAnalyze(unittest.TestCase):
    def test_clean_passes_and_slop_fails(self):
        good = analyze(CLEAN)
        bad = analyze(SLOP)
        self.assertTrue(good["pass"], good)
        self.assertFalse(bad["pass"], bad)
        self.assertGreater(good["prose_score"], bad["prose_score"])
        self.assertGreaterEqual(bad["tell_rate_per_1k"], 20.0)

    def test_violations_have_fixes(self):
        bad = analyze(SLOP)
        for v in bad["violations"]:
            if v.get("under_band"):
                continue
            self.assertIn("fix", v)
            self.assertGreater(len(v["fix"]), 5)
        self.assertTrue(any(not v.get("under_band") for v in bad["violations"]))

    def test_score_range(self):
        good = analyze(CLEAN)
        self.assertGreaterEqual(good["prose_score"], 0.0)
        self.assertLessEqual(good["prose_score"], 10.0)

    def test_revision_lines(self):
        bad = analyze(SLOP)
        lines = revision_lines(bad, limit=4)
        rule_lines = [l for l in lines if l.startswith("- ")]
        self.assertGreater(len(rule_lines), 0)
        self.assertTrue(all(":" in l for l in rule_lines))


class TestBandsAndDrift(unittest.TestCase):
    def test_bands_fit_and_drift_reports(self):
        chapters = [CLEAN, SLOP, CLEAN.replace("dockmaster", "harbourmaster")]
        fitted = bands_from(chapters)
        self.assertEqual(fitted["n"], 3)
        self.assertIn("sentence_mean", fitted["bands"])
        d = drift(measure(SLOP), fitted)
        self.assertIsInstance(d, list)

    def test_bands_need_three_chapters(self):
        fitted = bands_from([CLEAN])
        self.assertEqual(fitted["n"], 1)
        self.assertEqual(fitted["bands"], {})


class TestLengthPenalty(unittest.TestCase):
    def test_no_penalty_below_scoreability_floor(self):
        self.assertEqual(penalise_length(0, 4000), 0.0)
        self.assertEqual(penalise_length(100, 4000), 0.0)
        self.assertEqual(penalise_length(299, 4000), 0.0)

    def test_penalty_grows_as_stub_shrinks(self):
        self.assertGreater(penalise_length(1500, 4000), penalise_length(2500, 4000))
        self.assertGreater(penalise_length(2500, 4000), 0.0)

    def test_full_chapter_no_penalty(self):
        self.assertEqual(penalise_length(4000, 4000), 0.0)


class TestCLI(unittest.TestCase):
    def _write(self, text):
        fd, path = tempfile.mkstemp(suffix=".md")
        with os.fdopen(fd, "w") as fh:
            fh.write(text)
        return path

    def test_cli_pass_exits_zero(self):
        path = self._write(CLEAN)
        try:
            r = subprocess.run([sys.executable, "-m", "pipeline.prose_lab", path],
                               capture_output=True, text=True, cwd="/home/alex/Projects/novel-writer-harness")
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("PASS", r.stdout)
        finally:
            os.unlink(path)

    def test_cli_fail_exits_one(self):
        path = self._write(SLOP)
        try:
            r = subprocess.run([sys.executable, "-m", "pipeline.prose_lab", path],
                               capture_output=True, text=True, cwd="/home/alex/Projects/novel-writer-harness")
            self.assertEqual(r.returncode, 1, r.stdout)
            self.assertIn("FAIL", r.stdout)
        finally:
            os.unlink(path)

    def test_cli_json(self):
        path = self._write(CLEAN)
        try:
            r = subprocess.run([sys.executable, "-m", "pipeline.prose_lab", "--json", path],
                               capture_output=True, text=True, cwd="/home/alex/Projects/novel-writer-harness")
            data = json.loads(r.stdout)
            self.assertEqual(len(data), 1)
            self.assertIn("prose_score", data[0])
            self.assertIn("violations", data[0])
        finally:
            os.unlink(path)


if __name__ == "__main__":
    unittest.main()

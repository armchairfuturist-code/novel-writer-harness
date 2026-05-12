
"""End-to-end smoke test for StoryForge.
Exercises all code paths with simulated input.
Does NOT require live API."""
import io, json, os, sys, tempfile, unittest
from unittest.mock import patch
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

NL = os.linesep

class TestE2E(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.mkdtemp(prefix="sf_")
    def tearDown(self):
        import shutil; shutil.rmtree(self.td, ignore_errors=True)

    def _stdin(self, n):
        """Build mock stdin with n single-line answers."""
        parts = []
        for i in range(n):
            parts.append(f"Test answer {i}")
            parts.append("")
        return io.StringIO(NL.join(parts))

    def test_imports(self):
        from interview.questions import get_questions
        self.assertEqual(len(get_questions("quick", "fantasy")), 3)
        self.assertGreaterEqual(len(get_questions("standard", "fantasy")), 18)

    def test_quick_interview(self):
        from interview.engine import run_interview
        with patch("sys.stdin", self._stdin(3)):
            r = run_interview(depth="quick", genre="fantasy", project_dir=self.td)
        self.assertEqual(r["depth"], "quick")
        self.assertIn("answers", r)

    def test_story_bible(self):
        from interview.story_bible import compile_story_bible
        d = {"version": 2, "depth": "standard", "answers": {
            "concept_premise": [{"id": "cp-01", "question": "?", "answer": "A cartographer discovers worlds.", "dimension": "concept_premise", "is_thin": False}],
            "world_setting": [{"id": "ws-01", "question": "?", "answer": "Floating continent Aethra.", "dimension": "world_setting", "is_thin": False}],
            "characters": [{"id": "ch-01", "question": "?", "answer": "Elara Vex.", "dimension": "characters", "is_thin": False}],
            "plot_structure": [{"id": "pl-01", "question": "?", "answer": "Three-act structure.", "dimension": "plot_structure", "is_thin": False}],
            "theme_voice": [{"id": "th-01", "question": "?", "answer": "Truth is subjective.", "dimension": "theme_voice", "is_thin": False}],
            "market_comparisons": [{"id": "mk-01", "question": "?", "answer": "Kvothe meets Addie.", "dimension": "market_comparisons", "is_thin": False}],
        }, "thin_areas": []}
        b = compile_story_bible(d)
        self.assertIn("spec", b)
        self.assertIn("enrichments", b)
        self.assertGreater(len(b["spec"]["premise"]), 20)

    def test_checkpoint(self):
        from interview.engine import run_interview, CHECKPOINT_FILENAME
        from interview.resume import validate_checkpoint, _load_checkpoint
        with patch("sys.stdin", self._stdin(6)):
            run_interview(depth="quick", genre="fantasy", project_dir=self.td)
        ckpt = os.path.join(self.td, CHECKPOINT_FILENAME)
        self.assertTrue(os.path.exists(ckpt))
        with open(ckpt) as f:
            data = json.load(f)
        self.assertEqual(data["version"], 2)
        ok, err = validate_checkpoint(data)
        self.assertTrue(ok)
        self.assertIsNotNone(_load_checkpoint(self.td))

    def test_model_routing(self):
        from config import Config
        c = Config()
        for t in ["thin_detection", "follow_up_generation", "question_analysis",
                   "concept_premise", "world_setting", "characters",
                   "plot_structure", "theme_voice", "drilling", "compilation"]:
            self.assertIsNotNone(c.model_for_interview(t))
        ov = c.model_for_interview("thin_detection", override="deepseek")
        self.assertEqual(ov.name, "deepseek-chat")
        self.assertEqual(c.model_for_benchmark("kimi-k2.6").name, "kimi-k2.6")
        self.assertEqual(c.model_for_benchmark("nope").name, "kimi-k2.6")

    def test_monitor(self):
        from interview.context_monitor import ContextMonitor
        m = ContextMonitor(model_limit=128000)
        m.token_count = 90000
        self.assertTrue(m.should_warn())

    def test_memory(self):
        from interview.memory import JSONMemoryStore
        s = JSONMemoryStore(os.path.join(self.td, "mem.json"))
        s.save("k", {"v": 42})
        self.assertEqual(s.load("k")["v"], 42)

    def test_subprocesses(self):
        import subprocess
        for f, label in [("tests/test_pipeline.py", "Pipeline"),
                         ("tests/test_interview.py", "Interview"),
                         ("tests/test_v03.py", "v03"),
                         ("tests/test_backprop_and_edit.py", "Backprop")]:
            r = subprocess.run([sys.executable, "-m", "pytest", f, "-q", "--tb=short"],
                capture_output=True, text=True, cwd=os.path.dirname(__file__))
            self.assertEqual(r.returncode, 0, f"{label}: {r.stdout[:100]}")
            print(f"  {label}: PASS")

if __name__ == "__main__":
    unittest.main(verbosity=2)

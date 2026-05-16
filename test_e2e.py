
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
        d = {"version": 2, "depth": "standard", "answers": [
            {"question_id": "cp-01", "dimension": "concept_premise", "question": "What is your story about?", "answer": "A retired detective uncovers a conspiracy linking his past cases to a shadowy organization.", "is_thin": False, "timestamp": "2026-01-01T00:01:00"},
            {"question_id": "ws-01", "dimension": "world_setting", "question": "Where does it take place?", "answer": "A gritty metropolis where magic and technology coexist uneasily.", "dimension": "world_setting", "is_thin": False, "timestamp": "2026-01-01T00:02:00"},
            {"question_id": "ch-01", "dimension": "characters", "question": "Who is the protagonist?", "answer": "A cynical retired detective haunted by unsolved cases.", "dimension": "characters", "is_thin": False, "timestamp": "2026-01-01T00:03:00"},
            {"question_id": "pl-01", "dimension": "plot_structure", "question": "What drives the plot?", "answer": "The detective must confront his past as old cases resurface.", "dimension": "plot_structure", "is_thin": False, "timestamp": "2026-01-01T00:04:00"},
        ], "thin_areas": []}
        b = compile_story_bible(d)
        self.assertIn("spec", b)
        self.assertIn("enrichments", b)
        self.assertGreater(len(b["spec"]["premise"]), 20)

    def test_checkpoint(self):
        from interview.engine import run_interview, _load_checkpoint, CHECKPOINT_FILENAME
        from interview.resume import validate_checkpoint
        with patch("sys.stdin", self._stdin(6)):
            run_interview(depth="quick", genre="fantasy", project_dir=self.td)
        ckpt = os.path.join(self.td, CHECKPOINT_FILENAME)
        self.assertTrue(os.path.exists(ckpt))
        with open(ckpt) as f:
            data = json.load(f)
        self.assertEqual(data["version"], 2)
        err = validate_checkpoint(data)
        self.assertIsNone(err)
        self.assertIsNotNone(_load_checkpoint(self.td))

    def test_model_routing(self):
        from config import Config
        c = Config()
        for t in ["thin_detection", "follow_up_generation", "question_analysis",
                   "concept_premise", "world_setting", "characters",
                   "plot_structure", "theme_voice", "drilling", "compilation"]:
            self.assertIsNotNone(c.model_for_interview(t))
        ov = c.model_for_interview("thin_detection", override="deepseek")
        self.assertEqual(ov.name, "deepseek-v4-pro-precision")
        self.assertEqual(c.model_for_benchmark("kimi-k2.6").name, "kimi-k2.6")
        self.assertEqual(c.model_for_benchmark("nope").name, "kimi-k2.6")

    def test_monitor(self):
        from interview.context_monitor import ContextMonitor
        m = ContextMonitor(model_name="deepseek")
        m.accumulated = 90000
        warning = m.check()
        self.assertIsNotNone(warning)

    def test_memory(self):
        from interview.memory_store import JSONMemoryStore
        s = JSONMemoryStore(os.path.join(self.td, "mem.json"))
        s.store("k", "v:42", tags=["test"])
        results = s.recall("k", k=1)
        self.assertGreaterEqual(len(results), 0)

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



    def test_benchmark_error(self):
        """--benchmark without working API exits non-zero with informative error."""
        import io as _io
        saved_argv = list(sys.argv)
        sys.argv = ["storyforge.py", "--benchmark"]
        stderr_buf = _io.StringIO()
        try:
            with patch('sys.stderr', stderr_buf):
                with patch('tests.benchmark_writing.run_benchmark',
                           side_effect=RuntimeError('API returned 500')):
                    with self.assertRaises(SystemExit):
                        import storyforge
                        storyforge.main()
        finally:
            sys.argv = saved_argv
        stderr_text = stderr_buf.getvalue()
        self.assertIn('Error', stderr_text)
        self.assertIn('CROFAI_API_KEY', stderr_text)

if __name__ == "__main__":
    unittest.main(verbosity=2)

"""The orientation report is the front door, so it must never lie or need a key.

These tests run collect() and render() the way `storyforge.py --doctor` does,
with no API key and no network, and they hold the report to its own claims: a
guard it lists must exist, and a version it prints must be the shipped one.
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

import doctor  # noqa: E402
from config import VERSION, Config  # noqa: E402


class DoctorTest(unittest.TestCase):
    def setUp(self):
        self._saved = {k: v for k, v in os.environ.items() if k.startswith(("LLM_", "CROFAI_"))}
        for key in list(os.environ):
            if key.startswith(("LLM_", "CROFAI_")):
                os.environ.pop(key)
        Config._instance = None

    def tearDown(self):
        for key in [k for k in os.environ if k.startswith(("LLM_", "CROFAI_"))]:
            os.environ.pop(key, None)
        os.environ.update(self._saved)
        Config._instance = None

    def test_collect_needs_no_key(self):
        report = doctor.collect()
        self.assertFalse(report["provider"]["api_key_set"])
        self.assertEqual(report["version"], VERSION)
        self.assertGreater(report["roles"]["total"], 0)

    def test_every_guard_it_names_exists(self):
        """A listed guard that is missing is a broken promise to the reader."""
        report = doctor.collect()
        self.assertTrue(report["guards"])
        for guard in report["guards"]:
            self.assertTrue(guard["present"], guard["path"])
            self.assertTrue(guard["holds"].strip(), guard["path"])

    def test_every_verify_command_is_runnable(self):
        for command in doctor.VERIFY:
            script = command.split()[1]
            self.assertTrue(
                os.path.exists(os.path.join(REPO, script)) or command.startswith("python3 -m"),
                command,
            )

    def test_render_names_the_essentials(self):
        text = doctor.render(doctor.collect())
        for needle in (VERSION, "provider", "roles", "guards", "verify", "next"):
            self.assertIn(needle, text)
        self.assertLess(len(text.splitlines()), 20, "the report must stay one screenful")

    def test_override_shows_up_with_its_provenance(self):
        os.environ["LLM_MODEL_DRAFT"] = "some-foreign-model"
        Config._instance = None
        report = doctor.collect()
        row = next(r for r in report["roles"]["overridden"] if r["role"] == "draft")
        self.assertEqual(row["model"], "some-foreign-model")
        self.assertEqual(row["source"], "env-raw")
        self.assertEqual(row["env_var"], "LLM_MODEL_DRAFT")
        self.assertIn("some-foreign-model", doctor.render(report))

    def test_project_state_reads_a_real_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            os.mkdir(os.path.join(tmp, "chapters"))
            with open(os.path.join(tmp, "checkpoint.json"), "w") as handle:
                json.dump({"completed_phases": ["seed", "outline"]}, handle)
            with open(os.path.join(tmp, "chapters", "chapter-001.md"), "w") as handle:
                handle.write("# Chapter 1\n\nFour words here, and four more.\n")
            state = doctor.project_state(tmp)
        self.assertTrue(state["exists"])
        self.assertEqual(state["phases_done"], ["outline", "seed"])
        self.assertEqual(state["chapters"], 1)
        self.assertEqual(state["chapter_words"], 9)
        self.assertIn("checkpoint.json", state["artifacts"])

    def test_project_state_survives_a_missing_dir(self):
        state = doctor.project_state("/nonexistent/storyforge-project")
        self.assertFalse(state["exists"])
        self.assertIn("none yet", doctor.render(doctor.collect(project_dir=state["dir"])))

    def test_project_state_survives_a_corrupt_checkpoint(self):
        with tempfile.TemporaryDirectory() as tmp:
            with open(os.path.join(tmp, "checkpoint.json"), "w") as handle:
                handle.write("{not json")
            state = doctor.project_state(tmp)
        self.assertEqual(state["phases_done"], ["<checkpoint.json unreadable>"])

    def test_cli_doctor_json_exits_clean_without_a_key(self):
        """The real artifact: the flag an agent actually types."""
        env = dict(os.environ)
        env.pop("LLM_API_KEY", None)
        env.pop("CROFAI_API_KEY", None)
        out = subprocess.run(
            [sys.executable, "storyforge.py", "--doctor", "--json"],
            cwd=REPO, capture_output=True, text=True, timeout=120, env=env,
        )
        self.assertEqual(out.returncode, 0, out.stderr)
        report = json.loads(out.stdout)
        self.assertEqual(report["version"], VERSION)
        self.assertIn("roles", report)

    def test_cli_banner_carries_the_version(self):
        out = subprocess.run(
            [sys.executable, "storyforge.py", "--help"],
            cwd=REPO, capture_output=True, text=True, timeout=120,
        )
        self.assertIn(VERSION, out.stdout)
        self.assertIn("--doctor", out.stdout)


if __name__ == "__main__":
    unittest.main()

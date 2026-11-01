"""The docs may only name things that exist.

AGENTS.md and README.md are what an agent reads first, so a stale flag, a
retired environment variable or a moved file costs a wasted run. This test
reads the documents the way a driver does and checks every handle in them
against the code.
"""

import os
import re
import subprocess
import sys
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCS = ["AGENTS.md", "README.md", "docs/ARCHITECTURE.md", "docs/CHANGELOG.md"]

# A flag is lowercase, so the ---CHANGES--- marker in a prompt is not one.
FLAG = re.compile(r"(?<![-\w])--[a-z][a-z0-9]*(?:-[a-z0-9]+)*")
ENV = re.compile(r"\b(?:LLM|CROFAI)_[A-Z0-9_]+[A-Z0-9]")
PATH = re.compile(r"(?<![\w/~.])[\w.-]+(?:/[\w.-]+)+\.(?:py|md|json)\b")

# Handles that are templates or examples rather than claims about this repo.
ALLOWED_FLAGS = {"--help"}
ALLOWED_ENV = {"LLM_MODEL"}


def known_role_vars():
    """Env vars that are real because the role behind them is real.

    The code builds these by template, so the literal string never appears in
    a source file. A documented role variable is honest exactly when the role
    exists in one of the three routing tables.
    """
    if REPO not in sys.path:
        sys.path.insert(0, REPO)
    from config import Config

    cfg = Config()
    roles = set(cfg.phase_models) | set(cfg.interview_models) | set(cfg.debate_models)
    out = {"LLM_MODEL_{ROLE}", "LLM_MODEL_{ROLE}_BASE_URL"}
    for role in roles:
        out.add(f"LLM_MODEL_{role.upper()}")
        out.add(f"LLM_MODEL_{role.upper()}_BASE_URL")
    return out


def doc_text():
    out = []
    for name in DOCS:
        path = os.path.join(REPO, name)
        if os.path.isfile(path):
            with open(path, encoding="utf-8", errors="replace") as handle:
                out.append((name, handle.read()))
    return out


def help_text(*args):
    proc = subprocess.run(
        [sys.executable, *args, "--help"],
        cwd=REPO, capture_output=True, text=True, timeout=120,
    )
    return proc.stdout + proc.stderr


def source_text():
    chunks = []
    for root, dirs, files in os.walk(REPO):
        dirs[:] = [d for d in dirs if d not in {".git", "__pycache__", ".pytest_cache", "reference"}]
        for name in files:
            if name.endswith(".py"):
                with open(os.path.join(root, name), encoding="utf-8", errors="replace") as handle:
                    chunks.append(handle.read())
    return "\n".join(chunks)


class DocDriftTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.flags = set()
        cls.envs = set()
        cls.paths = set()
        for name, text in doc_text():
            for hit in FLAG.findall(text):
                cls.flags.add((name, hit))
            for hit in ENV.findall(text):
                cls.envs.add((name, hit))
            for hit in PATH.findall(text):
                cls.paths.add((name, hit))
        cls.role_vars = known_role_vars()
        cls.known_flags = set(
            FLAG.findall(help_text("storyforge.py")) + FLAG.findall(help_text("scripts/smoke.py"))
        )
        cls.sources = source_text()

    def test_docs_exist(self):
        self.assertEqual(len(doc_text()), len(DOCS), "a document this test reads has moved")

    def test_every_flag_is_real(self):
        unknown = sorted(
            f"{name}: {flag}" for name, flag in self.flags
            if flag not in self.known_flags and flag not in ALLOWED_FLAGS
        )
        self.assertEqual(
            unknown, [],
            "These flags appear in the docs but in no --help output. Add the flag, "
            "or fix the document.\n" + "\n".join(unknown),
        )

    def test_every_env_var_is_real(self):
        unknown = sorted(
            f"{name}: {var}" for name, var in self.envs
            if var not in self.sources
            and var not in self.role_vars
            and var not in ALLOWED_ENV
        )
        self.assertEqual(
            unknown, [],
            "These environment variables appear in the docs but nowhere in the "
            "code.\n" + "\n".join(unknown),
        )

    def test_every_named_path_exists(self):
        missing = sorted(
            f"{name}: {path}" for name, path in self.paths
            if not os.path.exists(os.path.join(REPO, path))
        )
        self.assertEqual(
            missing, [],
            "These paths appear in the docs but not in the repo.\n" + "\n".join(missing),
        )

    def test_role_vars_track_the_routing_tables(self):
        """A documented role variable is real only if the role is."""
        self.assertIn("LLM_MODEL_DRAFT", self.role_vars)
        self.assertNotIn("LLM_MODEL_NOT_A_ROLE", self.role_vars)

    def test_the_guard_sees_drift(self):
        """A drift guard that cannot detect drift guards nothing."""
        self.assertTrue(FLAG.search("run storyforge.py --doctor now"))
        self.assertIsNone(FLAG.search("the ---CHANGES--- block"))
        self.assertTrue(ENV.search("export LLM_MODEL_DRAFT=x"))
        self.assertTrue(PATH.findall("see pipeline/state_io.py and docs/ARCHITECTURE.md"))


if __name__ == "__main__":
    unittest.main()

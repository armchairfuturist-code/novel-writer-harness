"""Guard: every shipped writer replaces its target atomically.

A crash, a full disk or a killed run must never leave a half-written chapter,
checkpoint or manuscript where a complete one stood. ``pipeline.state_io``
owns the primitive (mkstemp in the target directory, fsync, ``os.replace``,
directory fsync); this test keeps new in-place writers out of the tree.

Append-only handles are exempt by rule: a torn tail costs one log line, never
a file, and ``os.replace`` cannot express an append.

A writer that genuinely must keep a direct handle marks the line
``# atomic-exempt: <reason>`` and this guard passes it. The reason is the
point: an exemption is an argument, not a shrug.
"""
from __future__ import annotations

import os
import re
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

SKIP_DIRS = {
    ".git", "__pycache__", ".venv", "venv", "node_modules", ".api-cache",
    ".mypy_cache", ".pytest_cache", "dist", "build",
    # Test fixtures build throwaway projects; they are not shipped writers.
    "fixtures",
}
# state_io owns the primitive itself; tests are allowed to write fixtures.
SKIP_NAMES = {"state_io.py"}

WRITER_CALL = re.compile(
    r"\bopen\s*\(|\.write_text\s*\(|\.write_bytes\s*\(|zipfile\.ZipFile\s*\("
)
WRITE_METHOD = re.compile(r"\.write_(?:text|bytes)\s*\(")
# "w", "wb", "w+", "x", "xb" ... a mode that creates or truncates.
WRITE_MODE = re.compile(r"""["'][wx][bt]?\+?["']""")
APPEND_MODE = re.compile(r"""["']a""")
EXEMPT_MARKER = re.compile(r"#\s*atomic-exempt:\s*(\S.*)$")


def shipped_python_files():
    """Every .py the pipeline ships: package, agents, interview, scripts."""
    for dirpath, dirnames, filenames in os.walk(REPO_ROOT):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
        for name in sorted(filenames):
            if not name.endswith(".py"):
                continue
            if name in SKIP_NAMES or name.startswith("test_"):
                continue
            yield os.path.join(dirpath, name)


def flags(line: str) -> bool:
    """True when this source line replaces a file through a direct handle."""
    stripped = line.strip()
    if stripped.startswith("#"):
        return False
    if not WRITER_CALL.search(stripped):
        return False
    if APPEND_MODE.search(stripped):
        return False
    marker = EXEMPT_MARKER.search(stripped)
    if marker:
        return False
    return bool(WRITE_METHOD.search(stripped) or WRITE_MODE.search(stripped))


def in_place_writers(path: str):
    """Yield (lineno, text) for each unexempted in-place writer in `path`.

    The exemption marker may sit on the line above, which keeps a long call
    readable.
    """
    with open(path, "r", encoding="utf-8") as fh:
        prev = ""
        for lineno, line in enumerate(fh, 1):
            if flags(line) and not EXEMPT_MARKER.search(prev):
                yield lineno, line.strip()
            prev = line.strip()


def read(rel: str) -> str:
    with open(os.path.join(REPO_ROOT, rel), "r", encoding="utf-8") as fh:
        return fh.read()


class TestAtomicWriteCoverage(unittest.TestCase):
    def test_no_in_place_writers_remain(self):
        offenders = []
        for path in shipped_python_files():
            rel = os.path.relpath(path, REPO_ROOT)
            for lineno, text in in_place_writers(path):
                offenders.append("%s:%d: %s" % (rel, lineno, text))
        self.assertEqual(
            offenders,
            [],
            "These writers truncate a file in place, so a crash mid-write "
            "leaves a partial file where a complete one stood. Route them "
            "through pipeline.state_io.atomic_write_text / atomic_write_json, "
            "or mark the line '# atomic-exempt: <reason>':\n  "
            + "\n  ".join(offenders),
        )

    def test_guard_catches_a_planted_offender(self):
        # A guard that cannot fail is decoration.
        self.assertTrue(flags('with open(path, "w", encoding="utf-8") as f:'))
        self.assertTrue(flags('with open(path, "wb") as f:'))
        self.assertTrue(flags("chapter_path.write_text(body)"))
        self.assertTrue(flags("chapter_path.write_bytes(blob)"))
        self.assertTrue(flags('zipfile.ZipFile(output_path, "w")'))
        self.assertTrue(flags('with open(path, mode="w") as f:'))

    def test_guard_ignores_reads_appends_and_exemptions(self):
        self.assertFalse(flags('with open(path, "r", encoding="utf-8") as f:'))
        self.assertFalse(flags('with open(path, "a", encoding="utf-8") as f:'))
        self.assertFalse(flags("zipfile.ZipFile(source_path)"))
        self.assertFalse(flags("# with open(path, \"w\") as f:"))
        self.assertFalse(
            flags('with open(path, "w") as f:  # atomic-exempt: streamed to a socket'))

    def test_the_writers_that_matter_use_state_io(self):
        # Positive half of the guard: the paths that hold a reader's work.
        for rel in (
            "pipeline/canonical_store.py",
            "pipeline/export.py",
            "pipeline/foreshadow_tracker.py",
            "pipeline/adversarial_edit.py",
            "pipeline/iterative_backprop.py",
            "pipeline/style_engine.py",
            "interview/engine.py",
            "interview/memory_store.py",
            "agents/editor.py",
            "agents/orchestrator.py",
            "storyforge.py",
        ):
            self.assertIn("state_io import", read(rel), rel)

    def test_atomic_write_is_the_documented_route(self):
        source = read(os.path.join("pipeline", "state_io.py"))
        self.assertIn("def atomic_write_text", source)
        self.assertIn("def atomic_write_json", source)
        self.assertIn("os.replace", source)
        self.assertIn("fsync", source)


if __name__ == "__main__":
    unittest.main()

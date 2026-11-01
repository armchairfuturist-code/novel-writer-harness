"""Tests for pipeline.state_io — atomic state writes.

A state write must either fully replace the target or leave it untouched;
a crash mid-write can never produce a torn JSON file, and a failed write
never leaves a temp file behind.
"""
import json
import os
import stat
import sys
import tempfile
import unittest
from unittest import mock

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, REPO_ROOT)

from pipeline.state_io import atomic_write_json, atomic_write_text, fsync_dir


class TestAtomicWriteText(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.mkdtemp(prefix="sio_")

    def test_write_lands(self):
        p = os.path.join(self.td, "state.json")
        atomic_write_text(p, '{"a": 1}')
        with open(p) as f:
            self.assertEqual(f.read(), '{"a": 1}')

    def test_replace_failure_keeps_original(self):
        p = os.path.join(self.td, "state.json")
        atomic_write_text(p, "original")
        with mock.patch("pipeline.state_io.os.replace", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                atomic_write_text(p, "new content")
        with open(p) as f:
            self.assertEqual(f.read(), "original")
        self.assertEqual([n for n in os.listdir(self.td) if n.endswith(".tmp")], [])

    def test_write_failure_unlinks_temp(self):
        p = os.path.join(self.td, "state.json")
        with mock.patch("pipeline.state_io.os.fsync", side_effect=OSError("io error")):
            with self.assertRaises(OSError):
                atomic_write_text(p, "never lands")
        self.assertEqual([n for n in os.listdir(self.td) if n.endswith(".tmp")], [])
        self.assertFalse(os.path.exists(p))

    def test_directory_fsync_happens(self):
        p = os.path.join(self.td, "state.json")
        with mock.patch("pipeline.state_io.fsync_dir", wraps=fsync_dir) as spy:
            atomic_write_text(p, "x")
        spy.assert_called_once_with(self.td)

    def test_creates_missing_parents(self):
        p = os.path.join(self.td, "deep", "nested", "state.json")
        atomic_write_text(p, "x")
        self.assertTrue(os.path.exists(p))

    def test_preserves_mode_on_replace(self):
        p = os.path.join(self.td, "state.json")
        atomic_write_text(p, "one")
        os.chmod(p, 0o600)
        atomic_write_text(p, "two")
        self.assertEqual(stat.S_IMODE(os.stat(p).st_mode), 0o600)


class TestAtomicWriteJson(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.mkdtemp(prefix="sio_")

    def test_json_roundtrip(self):
        p = os.path.join(self.td, "state.json")
        atomic_write_json(p, {"chapter": 12, "elements": {"a": [1, 2]}})
        with open(p) as f:
            self.assertEqual(json.load(f), {"chapter": 12, "elements": {"a": [1, 2]}})

    def test_unserialisable_object_touches_nothing(self):
        p = os.path.join(self.td, "state.json")
        atomic_write_json(p, {"a": 1})
        with self.assertRaises(TypeError):
            atomic_write_json(p, {"bad": object()})
        with open(p) as f:
            self.assertEqual(json.load(f), {"a": 1})
        self.assertEqual([n for n in os.listdir(self.td) if n.endswith(".tmp")], [])


if __name__ == "__main__":
    unittest.main()

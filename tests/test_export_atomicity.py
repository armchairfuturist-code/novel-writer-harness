"""Export writes through the atomic primitive, and lists the whole cast.

Two things a reader loses if export is careless:

* a crash mid-export leaves a truncated manuscript.md where the complete one
  stood, and the run reports success anyway;
* the Dramatis Personae section used to write only the last character, because
  the two writes sat one indent level out of the loop.

These tests pin both: export must route through state_io, must leave the
previous file untouched when the write fails, must stage the EPUB beside its
target, and must name every character.
"""
from __future__ import annotations

import json
import os
import shutil
import tempfile
import unittest
import zipfile

from pipeline import export as export_mod
from pipeline.export import (
    _build_epub_from_chapters,
    build_manuscript_markdown,
    export_manuscript,
)

SPEC = {
    "title": "The Memory Basin",
    "genre": "historical fantasy",
    "tone": "elegiac",
    "pov": "Third Limited",
    "premise": "Every note she plays costs her a name.",
}
WORLD = {"world_name": "New Orleans, 1923", "geography": "the Basin"}
CHARACTERS = {
    "characters": [
        {"name": "Odile Marchand", "role": "protagonist", "personality": "stubborn"},
        {"name": "Thibodeaux", "role": "antagonist", "personality": "patient"},
        {"name": "Sister Vaudrin", "role": "mentor", "personality": "unsentimental"},
    ]
}
OUTLINE = {"story_structure": "three_act"}


class TestManuscriptCast(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="export-cast-")

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_every_character_is_listed(self):
        path = build_manuscript_markdown([], SPEC, WORLD, CHARACTERS, OUTLINE, self.dir)
        with open(path, "r", encoding="utf-8") as fh:
            text = fh.read()
        self.assertIn("## Dramatis Personae", text)
        for character in CHARACTERS["characters"]:
            self.assertIn(character["name"], text,
                          "%s missing from the cast list" % character["name"])

    def test_cast_lines_carry_role_and_trait(self):
        path = build_manuscript_markdown([], SPEC, WORLD, CHARACTERS, OUTLINE, self.dir)
        with open(path, "r", encoding="utf-8") as fh:
            lines = [line for line in fh if line.startswith("- **")]
        self.assertEqual(len(lines), 3)
        self.assertIn("(protagonist)", lines[0])
        self.assertIn("stubborn", lines[0])


class TestExportIsAtomic(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="export-atomic-")
        self.calls = []
        self._real_text = export_mod.atomic_write_text
        self._real_json = export_mod.atomic_write_json

    def tearDown(self):
        export_mod.atomic_write_text = self._real_text
        export_mod.atomic_write_json = self._real_json
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_build_manuscript_routes_through_state_io(self):
        def record(path, text, encoding="utf-8"):
            self.calls.append((path, len(text)))
            self._real_text(path, text, encoding=encoding)

        export_mod.atomic_write_text = record
        path = build_manuscript_markdown([], SPEC, WORLD, CHARACTERS, OUTLINE, self.dir)
        self.assertEqual(len(self.calls), 1, "manuscript must be written exactly once")
        self.assertEqual(self.calls[0][0], path)
        self.assertTrue(os.path.exists(path))

    def test_a_failed_write_leaves_the_previous_manuscript_intact(self):
        path = os.path.join(self.dir, "manuscript.md")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("LAST GOOD MANUSCRIPT")

        def explode(_path, _text, encoding="utf-8"):
            raise OSError(28, "No space left on device")

        export_mod.atomic_write_text = explode
        with self.assertRaises(OSError):
            build_manuscript_markdown([], SPEC, WORLD, CHARACTERS, OUTLINE, self.dir)
        with open(path, "r", encoding="utf-8") as fh:
            self.assertEqual(fh.read(), "LAST GOOD MANUSCRIPT")

    def test_project_metadata_is_written_by_the_primitive(self):
        seen = []

        def record(path, obj, indent=2, encoding="utf-8"):
            seen.append((path, obj))
            self._real_json(path, obj, indent=indent, encoding=encoding)

        export_mod.atomic_write_json = record
        result = export_manuscript([], SPEC, WORLD, CHARACTERS, OUTLINE, self.dir)
        self.assertEqual(len(seen), 1)
        self.assertEqual(seen[0][0], result["metadata"])
        with open(result["metadata"], "r", encoding="utf-8") as fh:
            meta = json.load(fh)
        self.assertEqual(meta["title"], "The Memory Basin")
        self.assertEqual(meta["structure"], "three_act")


class TestEpubStaging(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="export-epub-")
        self.files = []
        for num, body in ((1, "Odile lifted the horn."), (2, "The note cost her a name.")):
            path = os.path.join(self.dir, "chapter-%03d.md" % num)
            with open(path, "w", encoding="utf-8") as fh:
                fh.write("# Chapter %d\n\n%s\n" % (num, body))
            self.files.append(path)

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_epub_is_complete_and_leaves_no_staging_file(self):
        out = os.path.join(self.dir, "basin.epub")
        returned = _build_epub_from_chapters(self.files, out, title="The Memory Basin")
        self.assertEqual(returned, out)
        self.assertTrue(os.path.exists(out))
        leftovers = [name for name in os.listdir(self.dir) if name.endswith(".part")]
        self.assertEqual(leftovers, [], "staging file must be renamed, not left behind")
        with zipfile.ZipFile(out) as zf:
            self.assertIsNone(zf.testzip())
            names = set(zf.namelist())
        self.assertEqual(names & {"mimetype", "META-INF/container.xml"},
                         {"mimetype", "META-INF/container.xml"})
        self.assertTrue(any(n.startswith("OEBPS/") and n.endswith(".xhtml") for n in names))

    def test_export_falls_back_to_the_pure_python_epub(self):
        # pandoc may or may not be installed; force the fallback path so this
        # test measures our builder, not the environment.
        real_pandoc = export_mod.try_pandoc_export
        export_mod.try_pandoc_export = lambda *a, **k: {
            "pdf": {"success": False, "path": None, "error": "pandoc not on PATH"},
            "epub": {"success": False, "path": None, "error": "pandoc not on PATH"},
        }
        try:
            result = export_manuscript(
                [{"file": path, "chapter": i + 1} for i, path in enumerate(self.files)],
                SPEC, WORLD, CHARACTERS, OUTLINE, self.dir)
        finally:
            export_mod.try_pandoc_export = real_pandoc

        epub = result["pandoc"]["epub"]
        self.assertTrue(epub["success"], epub)
        self.assertEqual(epub["engine"], "pure-python")
        self.assertTrue(os.path.exists(epub["path"]))
        with zipfile.ZipFile(epub["path"]) as zf:
            self.assertIsNone(zf.testzip())
        self.assertEqual([n for n in os.listdir(self.dir) if n.endswith(".part")], [],
                         "staging file must be renamed, not left behind")


if __name__ == "__main__":
    unittest.main()

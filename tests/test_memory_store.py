"""Tests for the MemoryStore abstract interface and JSONMemoryStore implementation.

Run with: python -m pytest tests/test_memory_store.py -v
"""

import os
import re
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from interview.memory_store import (
    MemoryStore,
    JSONMemoryStore,
    create_memory_store,
    _parse_tags,
    _tokenise,
    _word_overlap_score,
)


# ── Helper ────────────────────────────────────────────────────────────


def _make_store(**kwargs) -> tuple[JSONMemoryStore, str]:
    """Create a JSONMemoryStore in a temp directory.

    Returns (store, tmpdir_path) so the caller can inspect the file.
    """
    tmpdir = tempfile.mkdtemp()
    store = JSONMemoryStore(project_dir=tmpdir, **kwargs)
    return store, tmpdir


# ── Abstract Interface Contract ───────────────────────────────────────


class TestMemoryStoreABC(unittest.TestCase):
    """Verify the MemoryStore ABC enforces the correct interface contract."""

    def test_cannot_instantiate_abc(self):
        with self.assertRaises(TypeError):
            MemoryStore()

    def test_has_abstract_methods(self):
        methods = ["store", "recall", "format_context", "close"]
        for name in methods:
            with self.subTest(method=name):
                # Verify each is an abstractmethod on the ABC
                abstract = getattr(MemoryStore, name, None)
                self.assertIsNotNone(abstract, f"{name} not found on MemoryStore")
                self.assertTrue(
                    getattr(abstract, "__isabstractmethod__", False),
                    f"{name} is not abstract",
                )

    def test_store_signature(self):
        import inspect
        sig = inspect.signature(MemoryStore.store)
        params = list(sig.parameters.keys())
        for required in ("key", "value"):
            self.assertIn(required, params)

    def test_recall_signature(self):
        import inspect
        sig = inspect.signature(MemoryStore.recall)
        params = list(sig.parameters.keys())
        for required in ("query",):
            self.assertIn(required, params)

    def test_format_context_signature(self):
        import inspect
        sig = inspect.signature(MemoryStore.format_context)
        params = list(sig.parameters.keys())
        for required in ("query",):
            self.assertIn(required, params)


# ── Core Store & Recall ───────────────────────────────────────────────


class TestJSONMemoryStoreStoreRecall(unittest.TestCase):
    """Basic store and recall with tag filtering."""

    def setUp(self):
        self.store, self.tmpdir = _make_store()
        self.addCleanup(self.store.close)

    def _store_demo_memories(self):
        self.store.store("char-alice", "Alice is a curious astronomer", tags=["character", "protagonist"])
        self.store.store("char-bob", "Bob is a grumpy cartographer", tags=["character", "antagonist"])
        self.store.store("planet-x", "Planet X is a frozen world with methane oceans", tags=["world", "setting"])
        self.store.store("plot-artifact", "The Chrono Compass is hidden in the Ice Cathedral", tags=["plot", "artifact"])

    def test_store_returns_id(self):
        mid = self.store.store("test-key", "test value")
        self.assertIsInstance(mid, str)
        self.assertIn("_", mid)

    def test_store_and_recall_basic(self):
        self._store_demo_memories()
        results = self.store.recall("Alice", k=10)
        self.assertGreaterEqual(len(results), 1)
        self.assertIn("alice", results[0]["value"].lower())

    def test_recall_with_tag_filter(self):
        self._store_demo_memories()
        results = self.store.recall("planet", k=10, tag_filter=["world"])
        self.assertGreaterEqual(len(results), 1)
        for r in results:
            self.assertIn("world", r["tags"])

    def test_recall_empty_store(self):
        results = self.store.recall("anything", k=5)
        self.assertEqual(results, [])

    def test_recall_returns_score(self):
        self._store_demo_memories()
        results = self.store.recall("Alice astronomer curious", k=5)
        self.assertGreater(len(results), 0)
        for r in results:
            self.assertIn("score", r)
            self.assertIsInstance(r["score"], float)

    def test_recall_higher_score_first(self):
        self._store_demo_memories()
        # Query matching Alice specifically
        results = self.store.recall("Alice curious astronomer", k=10)
        self.assertGreater(len(results), 0)
        scores = [r["score"] for r in results]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_recall_k_respected(self):
        self._store_demo_memories()
        results = self.store.recall("Alice Bob Planet Chrono", k=2)
        self.assertLessEqual(len(results), 2)


# ── Word-Overlap Scoring ──────────────────────────────────────────────


class TestJSONMemoryStoreRecallScoring(unittest.TestCase):
    """Verify word-overlap scoring returns correct results."""

    def setUp(self):
        self.store, self.tmpdir = _make_store()
        self.addCleanup(self.store.close)
        self.store.store("astro-1", "Stars are giant balls of burning gas", tags=["astronomy"])
        self.store.store("astro-2", "Black holes warp spacetime around them", tags=["astronomy"])
        self.store.store("geo-1", "Mountains are formed by tectonic plate movement", tags=["geology"])

    def test_astronomy_query_favours_astronomy(self):
        results = self.store.recall("stars black holes astronomy", k=10)
        astro_scores = [r["score"] for r in results if r["key"] in ("astro-1", "astro-2")]
        geo_scores = [r["score"] for r in results if r["key"] == "geo-1"]
        self.assertGreater(len(astro_scores), 0)
        if geo_scores:
            self.assertGreater(
                min(astro_scores), max(geo_scores),
                "Astronomy results should outrank geology for an astronomy query",
            )

    def test_exact_match_returns_perfect_score(self):
        self.store.store("exact", "perfect match keyword")
        results = self.store.recall("perfect match keyword", k=5)
        perfect = [r for r in results if r["key"] == "exact"]
        self.assertGreater(len(perfect), 0)
        self.assertAlmostEqual(perfect[0]["score"], 1.0, places=4)

    def test_no_overlap_returns_no_result(self):
        self.store.store("unique", "zzzxyzzy unique term")
        results = self.store.recall("completely unrelated query", k=5)
        self.assertNotIn("unique", [r["key"] for r in results])


# ── format_context Output Format ──────────────────────────────────────


class TestJSONMemoryStoreContext(unittest.TestCase):
    """Verify format_context output format and content."""

    def setUp(self):
        self.store, self.tmpdir = _make_store()
        self.addCleanup(self.store.close)

    def test_format_context_with_memories(self):
        self.store.store("char-test", "Test character is brave", tags=["character"])
        self.store.store("world-test", "Test world is vast", tags=["world"])
        block = self.store.format_context("test", max_items=5)
        self.assertIn("[CONTEXT FROM MEMORY STORE]", block)
        self.assertIn("[/CONTEXT FROM MEMORY STORE]", block)
        self.assertIn("Test character is brave", block)

    def test_format_context_shows_tags(self):
        self.store.store("item", "artifact discovery", tags=["plot", "discovery"])
        block = self.store.format_context("artifact", max_items=5)
        self.assertIn("plot", block)
        self.assertIn("discovery", block)

    def test_format_context_empty_store(self):
        block = self.store.format_context("anything", max_items=5)
        self.assertIn("no relevant memories found", block)

    def test_format_context_max_items_respected(self):
        for i in range(10):
            self.store.store(f"item-{i}", f"memory number {i}", tags=["demo"])
        block = self.store.format_context("memory number", max_items=3)
        # Count numbered entries — each starts with "\d+."
        entries = re.findall(r"^\d+\.", block, re.MULTILINE)
        self.assertLessEqual(len(entries), 3)


# ── Persistence ───────────────────────────────────────────────────────


class TestJSONMemoryStorePersistence(unittest.TestCase):
    """Verify load/save across instances."""

    def test_persists_to_disk(self):
        store1, tmpdir = _make_store()
        store1.store("persist-key", "persistent value", tags=["test"])
        expected_path = os.path.join(tmpdir, "storyforge-memory.json")
        self.assertTrue(os.path.exists(expected_path))
        store1.close()

        # Re-read from disk with a new instance
        store2 = JSONMemoryStore(project_dir=tmpdir)
        results = store2.recall("persistent", k=5)
        self.assertGreaterEqual(len(results), 1)
        self.assertEqual(results[0]["key"], "persist-key")
        store2.close()

    def test_counter_survives_restart(self):
        store1, tmpdir = _make_store()
        id1 = store1.store("a", "first entry")
        id2 = store1.store("b", "second entry")
        store1.close()

        store2 = JSONMemoryStore(project_dir=tmpdir)
        id3 = store2.store("c", "third entry")
        store2.close()

        # Sequence numbers should be monotonic
        seq1 = int(id1.split("_")[1])
        seq2 = int(id2.split("_")[1])
        seq3 = int(id3.split("_")[1])
        self.assertLess(seq1, seq2)
        self.assertLess(seq2, seq3)

    def test_json_file_readable(self):
        store, tmpdir = _make_store()
        store.store("a", "hello world", tags=["greeting"])
        store.close()

        import json
        path = os.path.join(tmpdir, "storyforge-memory.json")
        data = json.loads(open(path, encoding="utf-8").read())
        self.assertIsInstance(data, list)
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["key"], "a")


# ── Edge Cases ────────────────────────────────────────────────────────


class TestJSONMemoryStoreEdgeCases(unittest.TestCase):
    """Edge cases: empty store, unicode, missing tags, duplicate keys."""

    def setUp(self):
        self.store, self.tmpdir = _make_store()
        self.addCleanup(self.store.close)

    def test_empty_store_recall(self):
        self.assertEqual(self.store.recall("anything"), [])

    def test_empty_store_format_context(self):
        block = self.store.format_context("anything")
        self.assertIn("no relevant memories found", block)

    def test_unicode_values(self):
        self.store.store("unicode-test", "émoji 🎭 and 中文 — résumé")
        results = self.store.recall("émoji 中文", k=5)
        self.assertGreaterEqual(len(results), 1)
        self.assertIn("émoji 🎭 and 中文 — résumé", results[0]["value"])

    def test_unicode_tags(self):
        self.store.store("tag-test", "unicode tag entry", tags=["étiqueté", "标签"])
        results = self.store.recall("unicode tag", k=5, tag_filter=["标签"])
        self.assertGreaterEqual(len(results), 1)

    def test_missing_tags(self):
        mid = self.store.store("no-tags", "entry without tags")
        results = self.store.recall("entry without tags", k=5)
        self.assertGreaterEqual(len(results), 1)
        self.assertEqual(results[0]["tags"], [])

    def test_none_tags(self):
        mid = self.store.store("none-tags", "entry with None tags", tags=None)
        results = self.store.recall("entry", k=5)
        self.assertGreaterEqual(len(results), 1)
        self.assertEqual(results[0]["tags"], [])

    def test_duplicate_keys_allowed(self):
        id1 = self.store.store("dup-key", "first value")
        id2 = self.store.store("dup-key", "second value")
        self.assertNotEqual(id1, id2)
        results = self.store.recall("first value", k=5)
        self.assertGreaterEqual(len(results), 1)

    def test_large_metadata(self):
        big_meta = {"data": "x" * 10_000}
        self.store.store("big-meta", "large metadata entry", metadata=big_meta)
        results = self.store.recall("large metadata", k=5)
        self.assertGreaterEqual(len(results), 1)
        self.assertEqual(results[0]["metadata"]["data"], "x" * 10_000)

    def test_tag_filter_case_insensitive(self):
        self.store.store("case-test", "case insensitive test", tags=["Character"])
        results = self.store.recall("case insensitive", k=5, tag_filter=["character"])
        self.assertGreaterEqual(len(results), 1)

    def test_recall_k_larger_than_store(self):
        for i in range(3):
            self.store.store(f"k-{i}", f"entry number {i}", tags=["demo"])
        results = self.store.recall("entry", k=100)
        self.assertLessEqual(len(results), 3)


# ── Internal Helpers ──────────────────────────────────────────────────


class TestInternalHelpers(unittest.TestCase):

    def test_parse_tags_none(self):
        self.assertEqual(_parse_tags(None), [])

    def test_parse_tags_empty(self):
        self.assertEqual(_parse_tags([]), [])

    def test_parse_tags_normalises(self):
        result = _parse_tags([" Character ", "PLOT "])
        self.assertEqual(result, ["character", "plot"])

    def test_parse_tags_dedup(self):
        result = _parse_tags(["a", "a", "B", "b"])
        self.assertEqual(result, sorted({"a", "b"}))

    def test_tokenise(self):
        self.assertEqual(_tokenise("Hello World!"), {"hello", "world"})

    def test_tokenise_empty(self):
        self.assertEqual(_tokenise(""), set())

    def test_word_overlap_score_identical(self):
        self.assertAlmostEqual(_word_overlap_score("hello world", "hello world"), 1.0)

    def test_word_overlap_score_half(self):
        self.assertAlmostEqual(_word_overlap_score("hello world", "hello there"), 0.5)

    def test_word_overlap_score_none(self):
        self.assertEqual(_word_overlap_score("abc def", "ghi jkl"), 0.0)

    def test_word_overlap_score_empty_query(self):
        self.assertEqual(_word_overlap_score("", "hello world"), 0.0)

    def test_word_overlap_score_empty_value(self):
        self.assertEqual(_word_overlap_score("hello", ""), 0.0)


# ── Factory Function ──────────────────────────────────────────────────


class TestFactoryFunction(unittest.TestCase):

    def test_factory_returns_json_store(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = create_memory_store("json", project_dir=tmpdir)
            self.assertIsInstance(store, JSONMemoryStore)
            self.assertIsInstance(store, MemoryStore)
            store.close()

    def test_factory_gbrain_raises(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with self.assertRaises(NotImplementedError):
                create_memory_store("gbrain", project_dir=tmpdir)

    def test_factory_auto_raises(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with self.assertRaises(NotImplementedError):
                create_memory_store("auto", project_dir=tmpdir)

    def test_factory_case_insensitive(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = create_memory_store("JSON", project_dir=tmpdir)
            self.assertIsInstance(store, JSONMemoryStore)
            store.close()

    def test_factory_unknown_raises(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with self.assertRaises(NotImplementedError):
                create_memory_store("unknown_type", project_dir=tmpdir)


if __name__ == "__main__":
    unittest.main()

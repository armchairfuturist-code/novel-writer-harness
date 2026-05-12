"""Tests for GBrainStoreAdapter — MemoryStore wrapper around GBrainStore.

Run with: python -m pytest tests/test_gbrain_adapter.py -v
"""

import os
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from interview.memory_store import (
    GBrainStoreAdapter,
    JSONMemoryStore,
    MemoryStore,
    create_memory_store,
)


# ── Helpers ────────────────────────────────────────────────────────────


def _make_adapter(**kwargs) -> GBrainStoreAdapter:
    """Create a GBrainStoreAdapter in a temp directory with default HTTP mocks.

    Returns the adapter directly.  The caller is responsible for calling
    ``adapter.close()`` during test cleanup.
    """
    tmpdir = tempfile.mkdtemp()
    return GBrainStoreAdapter(project_dir=tmpdir, **kwargs)


def _mock_gbrain_responses(mock_client, bank_exists=True):
    """Configure *mock_client* for the GBrain lifecycle."""
    # GET /v1/default/banks — bank list
    get_resp = MagicMock()
    get_resp.status_code = 200
    banks = [{"bank_id": "storyforge-test"}] if bank_exists else []
    get_resp.json.return_value = {"banks": banks}
    mock_client.get.return_value = get_resp

    # PUT /v1/default/banks/<id> — create bank
    put_resp = MagicMock()
    put_resp.status_code = 200
    mock_client.put.return_value = put_resp

    # POST — store_memory / recall (default: empty recall)
    post_resp = MagicMock()
    post_resp.status_code = 200
    post_resp.json.return_value = {"results": []}
    mock_client.post.return_value = post_resp

    return get_resp, put_resp, post_resp


# ── Initialisation ─────────────────────────────────────────────────────


class TestInitWithBank(unittest.TestCase):
    """GBrainStoreAdapter correctly initialises and connects to GBrain."""

    def setUp(self):
        self.client_patcher = patch("pipeline.gbrain_client.httpx.Client")
        self.mock_cls = self.client_patcher.start()
        self.mock_client = MagicMock()
        self.mock_cls.return_value = self.mock_client
        _mock_gbrain_responses(self.mock_client, bank_exists=False)
        self.tmpdir = tempfile.mkdtemp()
        self.adapter = GBrainStoreAdapter(project_dir=self.tmpdir)

    def tearDown(self):
        self.adapter.close()
        self.client_patcher.stop()

    def test_connected_true(self):
        self.assertTrue(self.adapter.connected)

    def test_ensure_bank_called_on_init(self):
        # GET was called to list banks
        get_calls = [c for c in self.mock_client.get.call_args_list if "banks" in str(c)]
        self.assertGreaterEqual(len(get_calls), 1)

    def test_is_memory_store_instance(self):
        self.assertIsInstance(self.adapter, MemoryStore)

    def test_disconnected_when_ensure_fails(self):
        # Make the GET call raise
        self.mock_client.get.side_effect = Exception("Connection refused")
        adapter2 = GBrainStoreAdapter(project_dir=self.tmpdir)
        self.assertFalse(adapter2.connected)
        adapter2.close()


# ── Store ──────────────────────────────────────────────────────────────


class TestStoreMemory(unittest.TestCase):
    """Delegates to GBrainStore.store_memory with correct arguments."""

    def setUp(self):
        self.client_patcher = patch("pipeline.gbrain_client.httpx.Client")
        self.mock_cls = self.client_patcher.start()
        self.mock_client = MagicMock()
        self.mock_cls.return_value = self.mock_client
        self.get_resp, self.put_resp, self.post_resp = _mock_gbrain_responses(
            self.mock_client, bank_exists=False
        )
        self.tmpdir = tempfile.mkdtemp()
        self.adapter = GBrainStoreAdapter(project_dir=self.tmpdir)

    def tearDown(self):
        self.adapter.close()
        self.client_patcher.stop()

    def test_store_returns_id(self):
        self.post_resp.status_code = 201
        mid = self.adapter.store("char-maria", "Maria is brave", tags=["character"])
        self.assertIsInstance(mid, str)
        self.assertTrue(mid.startswith("gbrain_"))

    def test_store_passes_content_and_tags(self):
        self.post_resp.status_code = 201
        self.adapter.store("char-maria", "Maria is brave", tags=["character"])
        # Verify the POST call had the right payload
        call_kwargs = self.mock_client.post.call_args
        self.assertIsNotNone(call_kwargs)
        import json
        body = json.loads(call_kwargs[1]["content"])
        self.assertEqual(body["content"], "Maria is brave")
        self.assertEqual(body["tags"], ["character"])
        self.assertEqual(body["importance"], 0.5)

    def test_store_stores_key_in_metadata(self):
        self.post_resp.status_code = 201
        self.adapter.store("char-maria", "Maria is brave")
        import json
        body = json.loads(self.mock_client.post.call_args[1]["content"])
        self.assertIn("_key", body["metadata"])
        self.assertEqual(body["metadata"]["_key"], "char-maria")

    def test_store_returns_empty_on_failure(self):
        self.post_resp.status_code = 400
        mid = self.adapter.store("fail-key", "should not persist")
        self.assertEqual(mid, "")


# ── Recall ─────────────────────────────────────────────────────────────


class _RecallBase(unittest.TestCase):
    """Base class for recall tests — sets up mock client and adapter."""

    def setUp(self):
        self.client_patcher = patch("pipeline.gbrain_client.httpx.Client")
        self.mock_cls = self.client_patcher.start()
        self.mock_client = MagicMock()
        self.mock_cls.return_value = self.mock_client
        self.get_resp, self.put_resp, self.post_resp = _mock_gbrain_responses(
            self.mock_client, bank_exists=True
        )
        self.tmpdir = tempfile.mkdtemp()
        self.adapter = GBrainStoreAdapter(project_dir=self.tmpdir)

    def tearDown(self):
        self.adapter.close()
        self.client_patcher.stop()


class TestRecall(_RecallBase):
    """Transforms GBrain recall response into MemoryStore format."""

    def _set_recall_results(self, results: list[dict]):
        """Configure the mock POST response to return *results* on next recall."""
        self.post_resp.json.return_value = {"results": results}

    def test_recall_returns_empty_list_when_no_results(self):
        results = self.adapter.recall("anything", k=5)
        self.assertEqual(results, [])

    def test_recall_transforms_gbrain_result(self):
        self._set_recall_results([
            {
                "id": "mem_001",
                "content": "Maria is a stoic botanist",
                "tags": ["character"],
                "score": 0.92,
                "metadata": {"_key": "char-maria", "source": "interview"},
                "timestamp": "2024-06-01T12:00:00+00:00",
            }
        ])
        results = self.adapter.recall("Maria", k=5)
        self.assertEqual(len(results), 1)
        item = results[0]
        self.assertEqual(item["id"], "mem_001")
        self.assertEqual(item["key"], "char-maria")
        self.assertEqual(item["value"], "Maria is a stoic botanist")
        self.assertEqual(item["tags"], ["character"])
        self.assertEqual(item["score"], 0.92)
        self.assertEqual(item["timestamp"], "2024-06-01T12:00:00+00:00")
        self.assertEqual(item["metadata"]["_key"], "char-maria")
        self.assertEqual(item["metadata"]["source"], "interview")

    def test_recall_uses_id_as_key_when_no_metadata_key(self):
        self._set_recall_results([
            {"id": "mem_002", "content": "orphan memory", "tags": [], "score": 0.5, "metadata": {}}
        ])
        results = self.adapter.recall("orphan", k=5)
        self.assertEqual(results[0]["key"], "mem_002")

    def test_recall_passes_tag_filter_to_gbrain(self):
        self._set_recall_results([])
        self.adapter.recall("test", k=3, tag_filter=["character"])
        import json
        body = json.loads(self.mock_client.post.call_args[1]["content"])
        self.assertEqual(body["tag_filters"], ["character"])

    def test_recall_returns_multiple_results_sorted(self):
        self._set_recall_results([
            {"id": "r1", "content": "Alice is brave", "tags": ["character"], "score": 0.9, "metadata": {"_key": "char-alice"}},
            {"id": "r2", "content": "Bob is strong", "tags": ["character"], "score": 0.7, "metadata": {"_key": "char-bob"}},
        ])
        results = self.adapter.recall("brave", k=5)
        self.assertEqual(len(results), 2)
        # GBrain returns already-sorted results; we preserve the order
        self.assertGreater(results[0]["score"], results[1]["score"])


# ── Format Context ─────────────────────────────────────────────────────


class TestFormatContext(_RecallBase):
    """format_context builds a correctly formatted [CONTEXT FROM GBRAIN] block."""

    def _set_recall_results(self, results: list[dict]):
        self.post_resp.json.return_value = {"results": results}

    def test_format_context_empty_store(self):
        block = self.adapter.format_context("anything", max_items=5)
        self.assertEqual(block, "[CONTEXT FROM GBRAIN: no relevant memories found]")

    def test_format_context_with_memories(self):
        self._set_recall_results([
            {
                "id": "m1",
                "content": "Alice is a fearless explorer",
                "tags": ["character", "protagonist"],
                "score": 0.85,
                "metadata": {"_key": "char-alice"},
            }
        ])
        block = self.adapter.format_context("Alice", max_items=5)
        self.assertIn("[CONTEXT FROM GBRAIN]", block)
        self.assertIn("[/CONTEXT FROM GBRAIN]", block)
        self.assertIn("Alice is a fearless explorer", block)
        self.assertIn("[char-alice]", block)
        self.assertIn("character, protagonist", block)

    def test_format_context_respects_max_items(self):
        self._set_recall_results([
            {"id": f"m{i}", "content": f"Memory {i}", "tags": [], "score": 1.0, "metadata": {"_key": f"item-{i}"}}
            for i in range(10)
        ])
        block = self.adapter.format_context("Memory", max_items=3)
        import re
        entries = re.findall(r"^\d+\.", block, re.MULTILINE)
        self.assertLessEqual(len(entries), 3)

    def test_format_context_includes_tags(self):
        self._set_recall_results([
            {
                "id": "m1",
                "content": "Plot artifact discovered",
                "tags": ["plot", "artifact"],
                "score": 0.8,
                "metadata": {"_key": "plot-artifact"},
            }
        ])
        block = self.adapter.format_context("artifact", max_items=5)
        self.assertIn("plot", block)
        self.assertIn("artifact", block)

    def test_format_context_shows_untagged(self):
        self._set_recall_results([
            {
                "id": "m1",
                "content": "Orphan memory",
                "tags": [],
                "score": 0.6,
                "metadata": {"_key": "orphan"},
            }
        ])
        block = self.adapter.format_context("orphan", max_items=5)
        self.assertIn("(untagged)", block)


# ── Close ──────────────────────────────────────────────────────────────


class TestClose(_RecallBase):
    """close() delegates to GBrainStore.close()."""

    def test_close_called(self):
        with patch.object(self.adapter._gbrain, "close") as mock_close:
            self.adapter.close()
            mock_close.assert_called_once()


# ── Fallback Behaviour ─────────────────────────────────────────────────


class TestFallback(unittest.TestCase):
    """gbrain mode falls back to JSON when GBrain is unreachable."""

    def test_fallback_when_ensure_fails(self):
        with patch(
            "interview.memory_store.GBrainStoreAdapter",
            return_value=MagicMock(connected=False),
        ):
            # Prevent the mock adapter from writing real files on close()
            store = create_memory_store("gbrain", project_dir="/tmp/fallback-test")
            self.assertIsInstance(store, JSONMemoryStore)
            store.close()

    def test_fallback_when_constructor_raises(self):
        with patch(
            "interview.memory_store.GBrainStoreAdapter.__init__",
            side_effect=Exception("Connection refused"),
        ):
            store = create_memory_store("gbrain", project_dir="/tmp/fallback-test")
            self.assertIsInstance(store, JSONMemoryStore)
            store.close()


class TestAutoMode(unittest.TestCase):
    """auto mode probes GBrain and falls back to JSON when unavailable."""

    def test_auto_falls_back_on_connection_failure(self):
        with patch(
            "interview.memory_store.GBrainStoreAdapter",
            return_value=MagicMock(connected=False),
        ):
            store = create_memory_store("auto", project_dir="/tmp/auto-test")
            self.assertIsInstance(store, JSONMemoryStore)
            store.close()

    def test_auto_falls_back_on_timeout(self):
        with patch(
            "interview.memory_store.GBrainStoreAdapter.__init__",
            side_effect=Exception("timeout"),
        ):
            store = create_memory_store("auto", project_dir="/tmp/auto-fallback")
            self.assertIsInstance(store, JSONMemoryStore)
            store.close()


# ── ABC Contract ───────────────────────────────────────────────────────


class TestGBrainAdapterABCSignatures(unittest.TestCase):
    """Verify GBrainStoreAdapter satisfies MemoryStore's abstract interface."""

    def test_has_required_methods(self):
        methods = ["store", "recall", "format_context", "close"]
        for name in methods:
            with self.subTest(method=name):
                self.assertTrue(
                    hasattr(GBrainStoreAdapter, name),
                    f"{name} not found on GBrainStoreAdapter",
                )

    def test_can_instantiate(self):
        with patch("pipeline.gbrain_client.httpx.Client") as mock_cls:
            mock_client = MagicMock()
            mock_cls.return_value = mock_client
            _mock_gbrain_responses(mock_client)
            with tempfile.TemporaryDirectory() as tmpdir:
                adapter = GBrainStoreAdapter(project_dir=tmpdir)
                self.assertIsInstance(adapter, MemoryStore)
                adapter.close()


if __name__ == "__main__":
    unittest.main()

"""Semantic embedding store for narrative context retrieval.

Model-agnostic: the user picks the embedding backend via Config.embeddings:
- mode="none"   — disabled. Store is a no-op. No additional deps required.
- mode="local"  — sentence-transformers (user installs it). Model configurable.
- mode="remote" — embedding through the configured LLM API.

The store exposes the same search() interface in all three modes; in
"none" mode it always returns [] and add() inserts content with NULL
embeddings. Drop-in replacement for BM25 retriever.
"""

import json
import sqlite3
import threading
from pathlib import Path
from typing import Any, Optional, Callable

try:
    import numpy as np
except ImportError:
    np = None  # numpy only needed when embeddings are enabled (opt-in)

_local = threading.local()


def _is_enabled() -> bool:
    """Return True if the user has opted in to embeddings via env or config."""
    try:
        from config import Config
        return bool(Config().embeddings.enabled)
    except Exception:
        return False


def _get_mode() -> str:
    """Return the configured embedding mode: 'none' | 'local' | 'remote'."""
    try:
        from config import Config
        return Config().embeddings.mode
    except Exception:
        return "none"


def _get_local_model_name() -> str:
    """Return the user-configured local model name (HuggingFace id)."""
    try:
        from config import Config
        return Config().embeddings.local_model
    except Exception:
        return "sentence-transformers/all-MiniLM-L6-v2"


def _get_local_model():
    """Lazy-load the sentence-transformers model. Returns None if disabled/missing."""
    if not _is_enabled() or _get_mode() != "local":
        return None
    if not hasattr(_local, "model"):
        try:
            from sentence_transformers import SentenceTransformer

            model_name = _get_local_model_name()
            _local.model = SentenceTransformer(model_name)
        except ImportError:
            _local.model = None
    return _local.model


def _get_remote_embedder() -> Optional[Callable[[list[str]], list[list[float]]]]:
    """Build a remote embedder that calls the configured LLM API. Returns None if disabled."""
    if not _is_enabled() or _get_mode() != "remote":
        return None
    try:
        from config import Config
    except Exception:
        return None
    cfg = Config()
    if not cfg.api_key:
        return None
    model = cfg.model_for_embedding()
    if model is None:
        return None

    model_name = model.name
    base_url = cfg.base_url
    api_key = cfg.api_key

    def _embed(texts: list[str]) -> list[list[float]]:
        """Call the provider's /v1/embeddings endpoint."""
        import httpx
        url = f"{base_url.rstrip('/')}/embeddings"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        payload = {"model": model_name, "input": texts}
        r = httpx.post(url, headers=headers, json=payload, timeout=120.0)
        r.raise_for_status()
        data = r.json()
        return [item["embedding"] for item in data["data"]]

    return _embed


def _embed_texts(texts: list[str]) -> Optional[list[Optional[list[float]]]]:
    """Dispatch to the configured embedder. Returns None if disabled.

    Returns a list of embedding vectors (one per input text) or None if no
    embedder is available. Each element may also be None if embedding failed.
    """
    if not _is_enabled():
        return None
    mode = _get_mode()
    if mode == "local":
        model = _get_local_model()
        if model is None:
            return None
        return [list(v) for v in model.encode(texts, normalize_embeddings=True)]
    if mode == "remote":
        embedder = _get_remote_embedder()
        if embedder is None:
            return None
        return embedder(texts)
    return None


class EmbeddingStore:
    """Persistent semantic search over narrative chunks.

    Parameters
    ----------
    db_path : str or Path
        Path to SQLite database file. Created on first write.
    """

    def __init__(self, db_path: str | Path = "embeddings.db") -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: sqlite3.Connection | None = None
        self._lock = threading.Lock()

    # ── connection ──────────────────────────────────────────────

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(str(self.db_path))
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=NORMAL")
            self._init_db()
        return self._conn

    def _init_db(self) -> None:
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS chunks ("
            "  id         INTEGER PRIMARY KEY AUTOINCREMENT,"
            "  chapter    INTEGER NOT NULL,"
            "  section    TEXT NOT NULL DEFAULT '',"
            "  content    TEXT NOT NULL,"
            "  embedding  BLOB,"
            "  created_at TEXT DEFAULT (datetime('now'))"
            ")"
        )
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_chunks_chapter ON chunks(chapter)"
        )

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    # ── index ───────────────────────────────────────────────────

    def add(self, chapter: int, content: str, section: str = "") -> int:
        """Embed *content*, store it, return row id. Returns NULL embedding when disabled."""
        results = _embed_texts([content])
        with self._lock:
            if results is None or results[0] is None:
                cur = self.conn.execute(
                    "INSERT INTO chunks (chapter, section, content, embedding) "
                    "VALUES (?, ?, ?, NULL)",
                    (chapter, section, content),
                )
            else:
                emb = np.asarray(results[0], dtype=np.float32)
                blob = emb.tobytes()
                cur = self.conn.execute(
                    "INSERT INTO chunks (chapter, section, content, embedding) "
                    "VALUES (?, ?, ?, ?)",
                    (chapter, section, content, blob),
                )
            self.conn.commit()
            return cur.lastrowid

    def add_many(
        self, items: list[dict[str, Any]]
    ) -> None:
        """Batch insert. Each item: chapter, content [, section]."""
        if not items:
            return
        texts = [item["content"] for item in items]
        embeddings = _embed_texts(texts)
        rows = []
        for i, item in enumerate(items):
            if embeddings is not None and embeddings[i] is not None:
                emb = np.asarray(embeddings[i], dtype=np.float32)
                blob = emb.tobytes()
            else:
                blob = None
            rows.append((
                item["chapter"],
                item.get("section", ""),
                item["content"],
                blob,
            ))
        with self._lock:
            self.conn.executemany(
                "INSERT INTO chunks (chapter, section, content, embedding) "
                "VALUES (?, ?, ?, ?)",
                rows,
            )
            self.conn.commit()

    def remove_chapter(self, chapter: int) -> None:
        """Drop all chunks for a given chapter (e.g. before rewrite)."""
        with self._lock:
            self.conn.execute("DELETE FROM chunks WHERE chapter = ?", (chapter,))
            self.conn.commit()

    # ── retrieval ───────────────────────────────────────────────

    def search(
        self,
        query: str,
        k: int = 3,
        exclude: set[int] | None = None,
    ) -> list[dict[str, Any]]:
        """Semantic search — return top-*k* chunks most similar to *query*.

        Returns [] when embeddings are disabled or the embedder is unavailable.
        """
        results = _embed_texts([query])
        if results is None or results[0] is None:
            return []
        emb = np.asarray(results[0], dtype=np.float32)
        knn = self._knn(emb, k=k, exclude=exclude)
        return [
            {"chapter": r["chapter"], "content": r["content"], "score": r["score"]}
            for r in knn
        ]

    def get_similar_to_chapter(
        self,
        chapter: int,
        k: int = 3,
    ) -> list[dict[str, Any]]:
        """Find chapters semantically similar to *chapter* (excludes itself)."""
        query_vec = self._get_chapter_vector(chapter)
        if query_vec is None:
            return []
        results = self._knn(query_vec, k=k, exclude={chapter}) if query_vec is not None else []
        return [
            {"chapter": r["chapter"], "content": r["content"], "score": r["score"]}
            for r in results
        ]

    # ── internals ───────────────────────────────────────────────

    def _knn(
        self,
        query_vec: np.ndarray,
        k: int,
        exclude: set[int] | None = None,
    ) -> list[dict[str, Any]]:
        """Brute-force cosine-similarity kNN over stored embeddings."""
        rows = self.conn.execute(
            "SELECT id, chapter, content, embedding FROM chunks"
        ).fetchall()

        if not rows:
            return []

        ids = []
        candidates = []
        vecs = []
        for row in rows:
            row_id, chap, cont, blob = row
            if exclude and chap in exclude:
                continue
            if blob is None:
                continue
            emb = np.frombuffer(blob, dtype=np.float32).copy()
            ids.append(row_id)
            candidates.append({"chapter": chap, "content": cont})
            vecs.append(emb)

        if not vecs:
            return []

        mat = np.stack(vecs)                 # (N, D)
        sims = mat @ query_vec               # (N,)  — already normalised
        top_idx = np.argsort(-sims)[:k]

        return [
            {**candidates[i], "score": float(sims[i])}
            for i in top_idx
        ]

    def _get_chapter_vector(self, chapter: int) -> np.ndarray | None:
        """Mean-pool all embedding vectors for *chapter*."""
        rows = self.conn.execute(
            "SELECT embedding FROM chunks WHERE chapter = ? AND embedding IS NOT NULL",
            (chapter,),
        ).fetchall()
        if not rows:
            return None
        vecs = [np.frombuffer(r[0], dtype=np.float32) for r in rows]
        return np.mean(vecs, axis=0)

    # ── metadata ────────────────────────────────────────────────

    def chunk_count(self) -> int:
        return self.conn.execute("SELECT count(*) FROM chunks").fetchone()[0]

    def chapter_count(self) -> int:
        return self.conn.execute(
            "SELECT count(DISTINCT chapter) FROM chunks"
        ).fetchone()[0]

"""Semantic embedding store for narrative context retrieval.

Uses sentence-transformers/all-MiniLM-L6-v2 with SQLite persistence.
Drop-in replacement for BM25 retriever — same search() interface.
"""

import json
import sqlite3
import threading
from pathlib import Path
from typing import Any

import numpy as np

_local = threading.local()


def _get_model():
    if not hasattr(_local, "model"):
        from sentence_transformers import SentenceTransformer

        _local.model = SentenceTransformer(
            "sentence-transformers/all-MiniLM-L6-v2"
        )
    return _local.model


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
        """Embed *content*, store it, return row id."""
        emb = _get_model().encode(content, normalize_embeddings=True)
        blob = np.asarray(emb, dtype=np.float32).tobytes()
        with self._lock:
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
        rows = []
        model = _get_model()
        for item in items:
            emb = model.encode(
                item["content"], normalize_embeddings=True
            )
            blob = np.asarray(emb, dtype=np.float32).tobytes()
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
        """Semantic search — return top-*k* chunks most similar to *query*."""
        emb = _get_model().encode(query, normalize_embeddings=True)
        results = self._knn(emb, k=k, exclude=exclude)
        return [
            {"chapter": r["chapter"], "content": r["content"], "score": r["score"]}
            for r in results
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

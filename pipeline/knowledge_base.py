"""Knowledge Base — lazy-loaded writing theory references for debate agents.

The KnowledgeBase scans a directory of markdown files, each with YAML-style
frontmatter declaring its topic, target agent roles, and keywords. When an
agent requests references, files are scored by keyword overlap against the
current context and the top matches are returned, capped at max_tokens.

Design:
- Zero-dependency: pure Python file I/O and regex.
- Lazy-loaded: files read on first request, cached thereafter.
- Role-scoped: each agent gets only its relevant files.
- Token-capped: prevents reference bloat in context windows.

Usage:
    from pipeline.knowledge_base import KnowledgeBase

    kb = KnowledgeBase("reference/knowledge")
    text = kb.get_references(
        "lore_prosecutor",
        ["character", "timeline"],
        max_tokens=500,
    )
"""

import os
import re
import textwrap
from collections import OrderedDict
from typing import Optional


# ── Frontmatter parsing ──────────────────────────────────────────────

_FRONTMATTER_RE = re.compile(
    r'^---\s*\n(.*?)\n---\s*\n',
    re.DOTALL,
)
_KEYVAL_RE = re.compile(r'(\w[\w\s]*?):\s*(.+)')


def _parse_frontmatter(text: str) -> dict:
    """Parse YAML-style frontmatter from a markdown file.

    Returns a dict with keys: topic, agent_roles (list), keywords (list).
    """
    m = _FRONTMATTER_RE.search(text)
    if not m:
        return {"topic": "", "agent_roles": [], "keywords": []}

    fm_text = m.group(1)
    result = {"topic": "", "agent_roles": [], "keywords": []}

    for line in fm_text.split("\n"):
        line = line.strip()
        if not line:
            continue
        kv = _KEYVAL_RE.match(line)
        if not kv:
            continue
        key, value = kv.group(1).strip(), kv.group(2).strip()

        if key == "topic":
            result["topic"] = value
        elif key == "agent_roles":
            # Remove brackets and split
            value = value.strip("[]")
            result["agent_roles"] = [r.strip() for r in value.split(",") if r.strip()]
        elif key == "keywords":
            value = value.strip("[]")
            result["keywords"] = [k.strip() for k in value.split(",") if k.strip()]

    return result


def _count_tokens(text: str) -> int:
    """Rough token count (4 chars per token)."""
    return len(text) // 4


def _word_overlap_score(query_keywords: list[str], file_keywords: list[str]) -> float:
    """Score a file by keyword overlap with the query."""
    if not query_keywords or not file_keywords:
        return 0.0
    query_set = set(k.lower() for k in query_keywords)
    file_set = set(k.lower() for k in file_keywords)
    overlap = query_set & file_set
    if not overlap:
        return 0.0
    # Jaccard-like: how much of the query is covered
    return len(overlap) / len(query_set)


# ── KnowledgeBase ─────────────────────────────────────────────────────

class KnowledgeBase:
    """Lazy-loaded reference knowledge for writing agents.

    Scans a directory of markdown files, scores them by keyword overlap,
    and returns role-scoped, token-capped reference text.
    """

    def __init__(self, root_dir: str):
        self._root_dir = root_dir
        self._cache: dict[str, str] = {}          # path -> raw text
        self._metadata: dict[str, dict] = {}       # path -> frontmatter dict
        self._loaded = False

    # ── Loading ──────────────────────────────────────────────────────

    def _load_directory(self):
        """Scan root_dir and populate cache and metadata."""
        if self._loaded:
            return

        if not os.path.isdir(self._root_dir):
            self._loaded = True
            return

        for dirpath, _, filenames in os.walk(self._root_dir):
            for fn in filenames:
                if not fn.endswith(".md"):
                    continue
                full_path = os.path.join(dirpath, fn)
                try:
                    with open(full_path, "r", encoding="utf-8") as f:
                        text = f.read()
                except (OSError, UnicodeDecodeError):
                    continue

                rel_path = os.path.relpath(full_path, self._root_dir).replace("\\", "/")
                self._cache[rel_path] = text
                self._metadata[rel_path] = _parse_frontmatter(text)

        self._loaded = True

    # ── Querying ─────────────────────────────────────────────────────

    def get_references(
        self,
        agent_role: str,
        keywords: list[str],
        max_tokens: int = 500,
    ) -> str:
        """Return the most relevant reference text for an agent.

        Args:
            agent_role: One of 'lore_prosecutor', 'plot_sentinel', 'magistrate', 'drafting'.
            keywords: List of topic keywords to match against file metadata.
            max_tokens: Maximum token budget for the returned text.

        Returns:
            Concatenated reference text from the best-matching files,
            prefixed with a header. Empty string if no matching files.
        """
        self._load_directory()

        if not self._cache:
            return ""

        # Score each file by keyword overlap, filtering by role
        scored = []
        for rel_path, meta in self._metadata.items():
            roles = meta.get("agent_roles", [])
            if agent_role not in roles:
                continue
            file_kw = meta.get("keywords", [])
            score = _word_overlap_score(keywords, file_kw)
            if score > 0:
                scored.append((score, rel_path, meta))

        if not scored:
            return ""

        # Sort by score descending, take top matches within token budget
        scored.sort(key=lambda x: -x[0])
        parts = ["## Relevant Writing Theory", ""]

        remaining_tokens = max_tokens - _count_tokens(parts[0])
        for score, rel_path, meta in scored:
            text = self._cache.get(rel_path, "")
            # Strip frontmatter from returned text
            body = _FRONTMATTER_RE.sub("", text).strip()
            token_cost = _count_tokens(body)
            if token_cost <= remaining_tokens:
                topic = meta.get("topic", rel_path)
                parts.append(f"### {topic}")
                parts.append(body)
                parts.append("")
                remaining_tokens -= token_cost + 10  # heading overhead
            elif remaining_tokens > 50:
                # Truncate to fit remaining budget
                truncated = body[:remaining_tokens * 4] + "..."
                topic = meta.get("topic", rel_path)
                parts.append(f"### {topic} (truncated)")
                parts.append(truncated)
                parts.append("")
                break
            else:
                break

        if len(parts) <= 2:
            return ""

        return "\n".join(parts)

    def list_topics(self, agent_role: Optional[str] = None) -> list[str]:
        """List all available topic labels, optionally filtered by role."""
        self._load_directory()
        topics = []
        for rel_path, meta in self._metadata.items():
            if agent_role and agent_role not in meta.get("agent_roles", []):
                continue
            topic = meta.get("topic", rel_path)
            if topic:
                topics.append(topic)
        return sorted(topics)

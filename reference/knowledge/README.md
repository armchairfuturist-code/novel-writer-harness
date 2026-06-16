# StoryForge Knowledge Base

Lazy-loaded reference files for debate court agents and the drafting system.
Each file is loaded on demand — never bloating the context window with irrelevant theory.

## File Format

Every `.md` file starts with YAML-style frontmatter:

```yaml
---
topic: short topic label
agent_roles: [lore_prosecutor, plot_sentinel]
keywords: [keyword1, keyword2, keyword3, ...]
---
```

## How Agents Load References

1. The `KnowledgeBase` class scans all `.md` files in the appropriate subdirectory
2. When an agent needs references, it calls `get_references(agent_role, keywords, max_tokens)`
3. Files are scored by **keyword overlap with synonym rescue** (see [Retrieval Semantics](#retrieval-semantics) below)
4. Top-matching files are loaded, concatenated, and injected into the agent's system prompt as a `## RELEVANT WRITING THEORY` block
5. The `max_tokens` cap prevents reference bloat

## Agent Role Directories

| Directory | Target Agent | Content |
|---|---|---|
| `lore-prosecutor/` | Lore Prosecutor | Continuity, trait tracking, worldbuilding consistency |
| `plot-sentinel/` | Plot Sentinel | Foreshadowing, pacing, outline beat compliance |
| `magistrate/` | Mechanical Magistrate | Revision instruction quality, conflict resolution |
| `drafting/` | Draft writer + revision loop | Hook techniques, dialogue craft, sensory immersion |

## Contributing

Add new `.md` files to the appropriate directory. Keep files focused (50-200 lines),
concrete (examples > theory), and well-tagged (frontmatter keywords drive relevance matching).

### Synonyms

If your file's topic uses vocabulary that the writer's chapter prose is unlikely to
contain literally, add common chapter-side synonyms to the file's frontmatter
`keywords:` list AND extend `pipeline/knowledge_base.py:KEYWORD_SYNONYMS` with the
reverse mapping. Example: if a file's keywords are `[trait, physical, description]`
but chapters typically say "scar", "wound", or "hand", add those words to
`KEYWORD_SYNONYMS` mapping to `{trait, physical, description}` so the rescue fires.

## Retrieval Semantics

`_word_overlap_score(query, file_keywords)` returns `|Q_expanded ∩ F| / |Q|`, where
`Q_expanded` includes the input query plus any synonyms registered in
`pipeline/knowledge_base.py:KEYWORD_SYNONYMS`.

**Why synonym expansion matters:** the `ctx_keywords` passed to the KB are extracted
from chapter content (title words + top-10 most-frequent 4+-letter words in the
first 1000 chars — see `pipeline/debate.py:540-544`). These are prose words, but
KB frontmatter is tagged with abstract writing-craft terms. Without rescue, a
chapter about Mira's scar (ctx: `[scar, hand, mother, fire, ...]`) would have zero
overlap with `character-trait-tracking.md`'s keywords `[character, trait, consistency,
physical description, drift, ...]`, and the agent would run with no writing-theory
context. With the synonym map (`scar → {trait, physical, description}`), the right
file surfaces and the agent gains the continuity reference it needed.

**Invariant:** the synonym map grows the numerator (more matches) but NOT the
denominator. Synonym-rich queries do not dominate retrieval; a single literal
match still scores 1.0/|Q|, and synonym-bonus scores are bounded by the curated
map size.

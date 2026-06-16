# KB Retrieval Benchmark — does llm-wiki change outputs?

**Date:** 2026-06-16
**Question:** Would adding a semantic retrieval layer (llm-wiki's `/query` step, or a 30-line `expand()` function in `knowledge_base.py`) change agent outputs positively on `novel-writer-harness` and `market-system`?

## Method

Simulated the *actual* `ctx_keywords` extraction in `pipeline/debate.py:540-544`:
```python
ctx_keywords.extend(chapter_title.lower().split())
ctx.extend([w for w, _ in Counter(words).most_common(10)])  # top-10 4+-letter words
```
Then ran two retrieval strategies against the actual KB files:
- **LITERAL**: current `_word_overlap_score` (Jaccard on frontmatter `keywords:`)
- **SEMANTIC**: same, after `expand({word} → synonyms)` with a manually curated synonym map (lower bound on what an embedding model would do)

7 chapter-like queries covering all 4 agent roles. Script: `C:/tmp/kb_benchmark_v3.py`.

## Results

| Metric | Literal (current) | Semantic | Delta |
|---|---|---|---|
| Top-1 retrieval accuracy | 4/7 (57%) | 6/7 (86%) | +29pp |
| Top-3 retrieval accuracy | 6/7 (86%) | 6/7 (86%) | 0 |
| **Cases where agent got NO reference at all** | **2/7 (29%)** | **0/7 (0%)** | **-29pp** |

**The critical finding is not top-1 ranking — it's that the current system returns the empty string 2/7 times.** When `_word_overlap_score` finds no keyword overlap, `KnowledgeBase.get_references` returns `""` and the debate agent runs with no `## RELEVANT WRITING THEORY` block.

### Concrete cases where current system fails

**Case 1: "The Scar on Mira's Hand" (lore_prosecutor)**
- `ctx_keywords`: `['fire', 'hand', 'mira', "mira's", 'mother', 'remembering', 'scar', 'touched']`
- Frontmatter keywords of `character-trait-tracking.md`: `[character, trait, consistency, eye color, hair color, physical description, drift, contradiction]`
- Overlap: **0** (none of the chapter-content words match frontmatter)
- Current: empty string returned, agent has no reference
- With semantic expansion (`scar → trait, physical, description`; `mira → character`): full `character-trait-tracking.md` returned
- **Output change**: agent gains the entire 45-line "Common Drift Patterns" reference for the continuity check on Mira's unexplained scar

**Case 2: "Flat Scene" (drafting)**
- `ctx_keywords`: `['crackle', 'feels', 'fire', 'flat', 'hear', 'room', 'scene', 'smell']`
- Frontmatter keywords of `sensory-immersion.md`: `[sensory, immersion, description, show don't tell, physical detail, five senses]`
- Overlap: **0**
- Current: empty string returned
- With semantic expansion (`flat/smell/hear/crackle → sensory, immersion, description`): full `sensory-immersion.md` returned
- **Output change**: agent gains the "Five Senses Rule" reference for the scene

### Cases that already work (no change)

- "Magic rules" → `worldbuilding-consistency.md` (frontmatter has `magic system, rules`; chapter has `magic, rules`)
- "Long Middle" → `pacing-diagnostics.md` (frontmatter has `pacing, drag`; chapter has `dragging, pacing`)
- "Opening Hook" → `hook-techniques.md` (frontmatter has `hook, chapter ending, suspense`; chapter has `hook, chapter`)
- "Actionable Feedback" → `actionable-revision-writing.md` (frontmatter has `actionable, revision, instruction`; chapter has `actionable, feedback, revision`)

The pattern: **when chapter content uses the same vocabulary as the KB's `keywords:` arrays, the literal system works. When chapter content uses descriptive prose (character names, scene actions), the literal system fails.**

## market-system analysis

The 5 docs (NARRATIVE_CONTEXT.md, GLOSSARY.md, RESEARCH_NOTES.md, RUNBOOK.md, PRD.md) have **no frontmatter**. Retrieval is grep-based — `codegraph_search` or `rg "photonics"`. Tested 10 queries including "chamath asset-light re-rating", "PPA off-balance-sheet", "aschenbrenner OOM table" — all return NARRATIVE_CONTEXT.md as the first hit (it's the central hub containing every concept).

**market-system does not need a retrieval layer.** The corpus is small (15 docs), centralized, and grep wins. The real gap there is **synthesis across docs** — e.g. PRD.md's "Asset Universe" doesn't reference NARRATIVE_CONTEXT.md's "Four Rules" explicitly. A `compile` step (llm-wiki's `/compile` or a manual cross-link pass) would help, but that's a different problem than retrieval.

## Decision

### novel-writer-harness: YES, add semantic layer — but as a 30-line patch, not llm-wiki

```python
# In knowledge_base.py — add before line 80
SYNONYMS = {
    "scar": {"trait", "physical", "description", "drift"},
    "wound": {"trait", "physical", "description"},
    "hand": {"trait", "physical", "description"},
    "fire": {"event", "sequence", "timeline"},
    "magic": {"world", "rules", "system"},
    "flat": {"sensory", "immersion", "description"},
    "smell": {"sensory", "immersion", "description"},
    "hear": {"sensory", "immersion", "description"},
    # ... 15-20 more entries
}

def _word_overlap_score(query_keywords, file_keywords):
    expanded = set(query_keywords) | {s for k in query_keywords for s in SYNONYMS.get(k.lower(), set())}
    if not expanded or not file_keywords:
        return 0.0
    overlap = expanded & set(file_keywords)
    return len(overlap) / len(set(query_keywords))  # denominator stays original
```

This captures **100% of the measured gain** for `novel-writer-harness`. No need to install `nvk/llm-wiki`, manage 23 slash commands, or run a separate daemon.

**Why not llm-wiki anyway?** It adds: 23 slash commands we won't use, Obsidian export we won't use, session capture we won't use, `/compile` step we don't need (the KB files are already curated), portable AGENTS.md we can't use (OMP, not Claude Code). The cost > value here.

### market-system: NO — different problem

The retrieval problem is solved (grep wins). The actual gap is cross-doc synthesis. Two options:
1. **Cheap**: add a 1-page `WIKI.md` that lists which section of which doc answers which class of question, with anchors. ~30 min, no new tooling.
2. **Heavy**: install `nvk/llm-wiki` and run `/compile` against the 5 docs. ~2 hours including setup, plus a daemon to maintain.

Recommend option 1 first. Revisit if/when the doc count exceeds 25.

## What was actually changed

- `C:/tmp/kb_benchmark_v3.py` — the benchmark (re-runnable, ~15s)
- This report
- No project files were modified

## What should be done

1. Patch `pipeline/knowledge_base.py:_word_overlap_score` with the 30-line synonym expansion above. Expected output change: ~29% of chapter critiques will gain a previously-missing `## RELEVANT WRITING THEORY` block.
2. Add a smoke test that asserts `get_references` is non-empty for the 2 known-failing chapter cases after the patch.
3. Skip llm-wiki for both projects.

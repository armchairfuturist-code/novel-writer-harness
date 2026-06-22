# Initial Architecture Memory — StoryForge v0.5

**Date:** 2026-06-21  
**Context:** First deep inspection of the novel-writer-harness repo (StoryForge)  
**Inspected by:** Hermes Agent subagent task

---

## Session Summary

Inspected the `novel-writer-harness` (StoryForge v0.5) repository at `/home/alex/Projects/novel-writer-harness`. This is a multi-model AI novel-writing pipeline that takes a seed concept and autonomously produces a full novel manuscript. The project is a combinatorial fork of ideas from 15+ open-source AI writing projects, tuned to route different LLMs to the tasks they're best at.

---

## Architecture Overview

### Pipeline Flow

```
seed → worldbuilding → characters → outline → [outline validator]
→ draft (with change declarations, debate court, style engine, RAG,
  canonical state, knowledge base, ReIO compression)
→ fact-check → iterative backprop → adversarial edit → review (dual-persona) → export
```

Phases are in `pipeline/` and run sequentially from `storyforge.py:main()`. Each phase function takes a `project_dir` (and relevant artifacts) and writes its output to that directory.

### Model Pipeline Architecture (Multi-Model Routing)

Different AI models are routed per phase based on task suitability:

| Phase | Routed Model | Rationale |
|---|---|---|
| seed (planning) | DeepSeek V4 Pro Precision | Large context, expansive planning |
| worldbuilding | DeepSeek V4 Pro Precision | Expansive world details |
| characters | Kimi K2.6 Balanced | Character depth — prose matters |
| outline | Kimi K2.6 Balanced | Structural planning |
| draft (chapter writing) | **Kimi K2.6 Precision** | Prose quality most important — max_tokens=16384 |
| scoring (mechanical checks) | Qwen3.5 9B ("flash") | Cheap + fast |
| critique | Kimi K2.6 Precision | Deep literary critique — prose-aware |
| final review | DeepSeek V4 Pro Precision | Full manuscript review — needs context |
| interview (Q&A) | DeepSeek V4 Pro Precision | Large context for conversation |
| interview scoring | Qwen3.5 9B ("flash") | Thin-area detection — cheap/fast |
| outline validator | DeepSeek V4 Flash | Structural check — context needed |

**Debate Court (Triadic SGDD) model routing:**

| Agent | Model | Role |
|---|---|---|
| Lore Prosecutor | DeepSeek V4 Pro | Continuity, trait drift, world-building violations |
| Plot Sentinel | Kimi K2.6 Balanced | Structural tracking, foreshadowing, outline compliance |
| Mechanical Magistrate | Qwen3.5 9B ("flash") | Reconciles conflicts, deterministic revision manifest |

**Key insight:** Kimi K2.6 is the prose/creative engine (drafting, critique, characters). DeepSeek handles large-context planning/review. Qwen is the cheap utility model for scoring and mechanical tasks.

### Model Config Resolution Chain

1. Env var `LLM_MODEL_{PHASE_UPPER}` (e.g. `LLM_MODEL_DRAFT`) → override alias from `Config.models`
2. Falls back to `Config.phase_models` routing dict
3. Falls back to `"kimi-balanced"` default
4. Base URL resolved: `ModelConfig.base_url` → `Config.base_url` → `https://beta.crof.ai/v1`
5. API key: `LLM_API_KEY` → `CROFAI_API_KEY` (checked at request time, not init time)

All model resolution goes through `Config._resolve_model()` (extracted 2026-06-19, commit `ba3ad18`).

### API Client

- Unified `CrofaiClient` in `pipeline/api.py` — thin wrapper around httpx (600s timeout)
- Retries only on 429 and 5xx (exponential backoff, up to 3 attempts)
- JSON output parsing with multi-strategy repair: unwrap fences, escape newlines, fix parenthetical annotations, brace-counting extraction
- Truncation detection: `_looks_truncated()` for JSON, `_looks_truncated_prose()` for free-form prose
- `chat_parse_with_retry()` re-issues chat on TRUNCATED responses
- Optional response caching (`.api-cache/` dir, opt-in `use_cache=True`)

### Canonical Store System

- `CanonicalStore` ABC (`pipeline/canonical_store.py`) — abstract interface for canonical novel state
- Default: `FileCanonicalStore` (zero-dependency JSON file, word-overlap scoring)
- Alternative backends: `HindsightStore` (HTTP `localhost:8888`), `GBrainStore` (HTTP `localhost:8888`)
- Factory: `create_canonical_store()` with `backend="file"|"hindsight"|"gbrain"|"auto"`
- Tracks: character traits, world facts, plot threads, foreshadowing debts (7-state machine)

### Change Declarations (v0.5 feature)

- Every chapter outputs a `---CHANGES---` JSON block declaring 12 categories of state transitions
- Categories: character status, conflict progress, plot nodes, foreshadowing actions, location changes, faction changes, time advancement, character movement, item transfers, secret reveals, oath changes, deadline changes
- Parsed and stripped from prose; canonical store updated deterministically from LLM's own declarations

### Style Engine (v0.5 feature)

- Pure-Python prose feature extractor (10 quantitative dimensions, zero LLM cost)
- Computes: sentence rhythm, paragraph length, dialogue density, vocabulary tier, sensory density, pacing profile, POV distance, hook density, emotional register
- Profiles saved as JSON; can bind to chapters for style control

### Knowledge Base (v0.5 feature)

- 10 curated markdown files on writing theory organized by agent role
- Lazy-loaded at ≤500 tokens per agent
- `KnowledgeBase` class scores files by keyword overlap with chapter context
- **KEYWORD_SYNONYMS** rescue layer bridges prose-vocabulary gap (e.g., "scar" → {trait, physical, description})
- Without rescue: ~29% of critiques ran with no writing-theory context

### Structure Overview

```
storyforge.py          — CLI entrypoint (985 lines)
config.py              — Singleton Config: phase routing, model aliases, thresholds
pipeline/
  api.py               — CrofaiClient (httpx), JSON repair, truncation detection
  seed.py              — Concept analysis → structured plan
  worldbuilding.py     — Geography, history, factions, etc.
  characters.py        — Character generation (6-7 characters)
  outline.py           — Chapter-by-chapter plot outline
  outline_validator.py — 5-dimension pre-draft quality gate
  changes.py           — Change declaration parsing/application
  draft.py             — Chapter drafting, revision loop, scoring
  debate.py            — Triadic SGDD debate protocol
  knowledge_base.py    — Writing theory keyword retrieval
  style_engine.py      — Prose feature extraction
  reio_compression.py  — Context compression for long novels
  canonical_store.py   — Canonical state ABC + FileCanonicalStore
  foreshadow_tracker.py— 7-state foreshadowing machine
  review.py            — Full manuscript review (dual-persona)
  factcheck.py         — Fact-checking pass
  backprop.py          — Backward propagation
  iterative_backprop.py— Iterative backprop loop
  adversarial_edit.py  — Adversarial editing pass
  export.py            — Markdown/PDF/epub export (pure-Python EPUB3 fallback)
  embedding_store.py   — Embedding-based retrieval
  hindsight_client.py  — HindsightStore HTTP client
  gbrain_client.py     — GBrainStore HTTP client
agents/
  base.py              — Agent base class
  writer.py            — Writer agent (chapter draft with retry)
  critic.py            — Critic agent
  editor.py            — Editor agent
  orchestrator.py      — Showrunner pipeline orchestrator
  continuity.py        — Continuity agent
interview/
  engine.py            — Interactive interview engine
  cli.py               — CLI interview interface
  questions.py         — Question bank
  drilling.py          — Follow-up generation
  memory_store.py      — Interview session memory
  chapter_feedback.py  — User chapter-level feedback
  story_bible.py       — Story bible compilation
  resume.py            — Resume interrupted interview
templates/             — Genre JSON templates (5 genres)
reference/             — Reference chapters, knowledge files, scoring rubric
tests/                 — 453+ tests (pytest, no external API needed)
```

---

## Key Decisions

1. **Provider-agnostic API layer** — Any OpenAI-compatible endpoint works via `LLM_BASE_URL` + `LLM_API_KEY`. Default: crof.ai.
2. **Singleton Config** — Deferred API key validation to `require_api_key()` so Config can be instantiated without a live key (testing without mocking).
3. **`sys.path.insert(0, ...)`** — Package not installed; run from source root with path manipulation.
4. **Phase-level model selection** — Explicit routing per phase rather than one-model-for-all. Kimi K2.6 for prose, DeepSeek for planning/review, Qwen for scoring.
5. **Change declarations over passive extraction** — LLM declares changes itself rather than system extracting them; deterministic updates.
6. **No conventional linter/formatter/typechecker** — No flake8, black, mypy, or tox config found.
7. **Default output directory** — `~/storyforge-projects/{slug}/` (gitignored).
8. **Pandoc not required** — Pure-Python EPUB3 builder as fallback.
9. **All LLM calls through CrofaiClient** — Phase modules never call httpx directly.

---

## Gotchas / Known Issues

- **Scoring favors ultra-short chapters** — Known issue in README. The mechanical scoring heuristic prefers short, dense chapters over longer ones with natural variance.
- **All 453 tests pass** without a live API key (CrofaiClient endpoints are mocked or never reached in unit tests).
- **Portable Python EPUB builder** — Zero-dependency, uses only stdlib (zipfile, re, html, uuid). Falls back automatically when Pandoc is not installed.
- **`--project-dir` must be honored** — a fix was recently applied for this; the argument must override default project dir consistently.
- **GBrain/Hindsight backends** require a running server at `localhost:8888`; not used by default.
- **ReIO compression** is reserved (`auto_compress_at_tokens` noted as not yet implemented).
- **Phase functions use different signatures** — some take `chapters_dir`, some `project_dir`, some both. `run_fact_check`, `run_backward_propagation`, `run_adversarial_edit` take `chapters_dir` only; `run_iterative_backpropagation` takes both.
- **Benchmark mode** tests 5 model variants (Kimi K2.6 base, Kimi K2.6 Precision, DeepSeek V4 Flash, GLM 5.1, Qwen3.6 27B).

---

## Recent Commits (last 10, as of 2026-06-21)

| Commit | Author | Date | Summary |
|---|---|---|---|
| `ba3ad18` | alex | 2026-06-19 | DRY Config model routing with `_resolve_model()`, fix outline_path bug, remove dead LLMClient alias |
| `d3e45f2` | alex | 2026-06-19 | Unify parallel/single variant paths in `run_draft()` into single loop (907 → 826 lines) |
| `63db291` | alex | 2026-06-19 | Extract `_launch_pipeline()` to DRY 3x duplicated pipeline launch code (1023 → 985 lines) |
| `a19717b` | alex | 2026-06-19 | Fix Config singleton: defer API key validation to `require_api_key()` |
| `ce1294c` | Armchair Futurist | 2026-06-18 | feat(export): pure-Python EPUB builder as Pandoc fallback |
| `83839c0` | Armchair Futurist | 2026-06-18 | fix: truncation bug — prose-aware retry, safety-net checks, max_tokens bump (16384) |
| `95c7979` | Armchair Futurist | 2026-06-16 | feat(kb): synonym-rescue layer closes empty-reference gap in KnowledgeBase |
| `8af0fa9` | alex | 2026-06-07 | Strong-tier architecture fixes: canonical-store ABC, drop dead BM25Retriever, project_dir→chapters_dir pass-through |
| `a890b37` | Armchair Futurist | 2026-06-05 | docs: comprehensive v0.5 README rewrite |
| `20d783b` | Armchair Futurist | 2026-06-05 | fix: add hindsight_canonical_state to token estimation template call |

---

## 5 Most Recently Modified Files (as of 2026-06-21)

1. `pipeline/api.py` — CrofaiClient, JSON repair, truncation detection
2. `config.py` — Singleton Config, model routing, scoring thresholds
3. `storyforge.py` — CLI entrypoint, pipeline orchestration
4. `pipeline/draft.py` — Chapter drafting, revision loop, scoring
5. `tests/test_knowledge_base.py` — KB tests including synonym-rescue

---

## Source-of-Truth Documents

| Document | What it covers |
|---|---|
| `README.md` | Full project overview, pipeline, features, commands, architecture, origins |
| `AGENTS.md` | Agent-focused entry point, commands, testing, architecture, conventions |
| `config.py` | Model routing, aliases, thresholds, API config (docstring is authoritative) |
| `pipeline/api.py` | API client, JSON repair strategies, truncation detection |
| `storyforge.py` | CLI entry point, pipeline flow, argument parsing |
| `docs/kb-benchmark-2026-06-16.md` | Knowledge Base synonym-rescue benchmark |
| `pyproject.toml` | Project metadata (name: storyforge, MIT, deps: httpx) |

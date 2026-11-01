# StoryForge — AGENTS.md

Read this first. It is the contract between you and the system: how to know
where you are, which levers move it, what it leaves behind, and what must stay
true. Everything deeper hangs off the pointers at the bottom.

## Orient before you act

```bash
python3 storyforge.py --doctor          # version, provider, role routing, project state, guards, next command
python3 storyforge.py --doctor --json   # the same report as data
python3 storyforge.py --show-models     # every role -> model, the reason, and the env var that owns it
```

`--doctor` needs no API key and no network. It is one screenful and it is
always current, because it reads the live configuration instead of a document.
Prefer it over grepping. Add `--live` to also ask the provider which model ids
it actually serves.

## Run it

| Command | What it does |
|---|---|
| `python3 storyforge.py "concept"` | Full pipeline: seed → export |
| `python3 storyforge.py --interactive "concept"` | Guided interview, then the pipeline |
| `python3 storyforge.py --quick "concept"` | Skip review, backprop, adversarial |
| `python3 storyforge.py --resume DIR` | Resume an interrupted run from its project dir |
| `python3 storyforge.py --genre fantasy "concept"` | Apply a genre template |
| `python3 storyforge.py --benchmark` | Benchmark the writing-model variants |
| `python3 scripts/smoke.py "concept" --chapters 2` | Offline end-to-end proof, no API key |

Running the same concept again resumes: `checkpoint.json` lists the completed
phases, and each phase that already landed is skipped.

## Levers

Every lever is an environment variable or a flag. None of them needs an edit to
this repo, and that is deliberate: the system is only agent-drivable if control
lives outside the code.

```bash
export LLM_API_KEY="..."                 # any OpenAI-compatible provider
export LLM_BASE_URL="https://..."        # CROFAI_API_KEY / CROFAI_BASE_URL are fallbacks
export LLM_MODEL_DRAFT="flash"           # a known alias from config.py
export LLM_MODEL_DRAFT="gpt-5.2"         # or any raw model id your provider serves
export LLM_MODEL_DRAFT_BASE_URL="https://api.openai.com/v1"   # one role, another provider
export LLM_ENABLE_EMBEDDINGS=1           # semantic retrieval, off by default
export LLM_EMBEDDING_MODE=local          # none | local | remote
export LLM_MIN_PROSE_SCORE=7.0           # the deterministic prose gate
export LLM_RETRY_FAST=1                  # no backoff; used by tests and the smoke run
```

There are 21 roles across three tables (pipeline phases, interview dimensions,
debate court). `--show-models` lists every one with its override variable. An
override that is not a known alias is honored as a raw model id, labeled
`env-raw` in the routing plan, and noted once on stderr. Nothing is silently
dropped, and no fallback happens behind your back.

## The tower

Six levels, each with one contract and one guard. `docs/ARCHITECTURE.md` is the
full map; this is the shape.

| Level | What it is | Where |
|---|---|---|
| L0 Contract | A seed phrase in, a manuscript out | `storyforge.py` |
| L1 Phases | seed → world → characters → outline → validate → draft → score → critique → review → backprop → adversarial → export | `pipeline/`, `agents/` |
| L2 Roles | Every phase asks for a model by role, never by name | `config.py` |
| L3 Services | API client, prose lab, knowledge base, style engine, canonical store | `pipeline/` |
| L4 State | Atomic writes, one checkpoint, one canonical truth | `pipeline/state_io.py`, `pipeline/canonical_store.py` |
| L5 Evidence | Scores, redraws, budget notes, the doctor report, the smoke run | `doctor.py`, `scripts/smoke.py` |

## What must stay true

Each of these has a test that fails when it breaks. Run them before you push.

| Invariant | Guard |
|---|---|
| No writer truncates a file it replaces | `tests/test_atomic_write_coverage.py` |
| No vendor model id outside the `config.py` alias table | `tests/test_model_literal_guard.py` |
| Any model id can hold any role, by env var alone | `tests/test_model_routing_agnostic.py` |
| The orientation report never lies and needs no key | `tests/test_doctor.py` |
| The docs name only commands and variables that exist | `tests/test_agents_doc_drift.py` |

## Verify before you say done

```bash
python3 -m pytest -q      # the whole suite, offline
python3 scripts/smoke.py "a lighthouse keeper adopts a shipwrecked child" --chapters 2
```

Two tests need a live key and fail offline by design:
`test_e2e.py::TestE2E::test_checkpoint` and `::test_quick_interview`. Deselect
them when you mean "offline green".

## Conventions that will bite you

- The package is not installed. Every entry point does
  `sys.path.insert(0, <repo root>)` and runs from source.
- All LLM calls go through `CrofaiClient.chat()` or `chat_with_retry()` in
  `pipeline/api.py`. Phase modules never call httpx directly. Retries are keyed
  by error kind, not by count alone.
- Every file write goes through `pipeline.state_io.atomic_write_text` or
  `atomic_write_json`. Append-only logs are the one exception and each carries a
  `# atomic-exempt: <reason>` marker.
- `canonical_state.json` is the single source of truth for novel facts. Phase
  artifacts are derived from it and from the LLM's own `---CHANGES---` block.
- Line endings are mixed: `pipeline/canonical_store.py` and
  `pipeline/iterative_backprop.py` are CRLF. Read with `newline=''` before
  rewriting a file, or you will convert it and bury your diff.
- `Config` is a singleton. Tests reset it with `Config._instance = None` and
  snapshot every `LLM_*` / `CROFAI_*` env var they touch.
- There is no linter, formatter or typechecker configured. The tests are the
  gate.

## Output

Runs land in `~/storyforge-projects/{slug}/`, overridden by `--project-dir`.
That directory holds `checkpoint.json`, `canonical_state.json`, `chapters/`,
and every phase artifact. `~/storyforge-projects/` is gitignored. `--doctor`
reports the newest run's phase list, chapter count and word count.

## Docs

- `docs/ARCHITECTURE.md` — the tower, level by level: contract, files, guard,
  and how to extend each one.
- `docs/CHANGELOG.md` — what each version changed, newest first.
- `docs/agents/domain.md` — the story-domain vocabulary the pipeline speaks.
- `docs/agents/issue-tracker.md`, `docs/agents/triage-labels.md` — how work is
  filed and labeled.
- `reference/` — the writing-theory knowledge base, loaded lazily by
  `pipeline/knowledge_base.py` under a token budget.
- `README.md` — the human front door: install, quick start, command reference.

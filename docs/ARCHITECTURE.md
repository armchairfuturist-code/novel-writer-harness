# StoryForge architecture: a tower of six levels

This document is the map an agent reads after `storyforge.py --doctor`. Each
level names its contract, the files that hold it, the test that guards it, and
how to extend it. The rule across all six: a level may call the level below it
and never reaches up, and every level leaves machine-readable evidence of what
it decided.

```
L0 Contract      seed phrase in, manuscript out
L1 Phases        the ordered work
L2 Roles         who does each piece of work
L3 Services      how the work is done
L4 State         what survives the work
L5 Evidence      what proves the work happened
```

## L0 — the contract

**Contract.** One sentence in, one novel out. `python3 storyforge.py "concept"`
returns a manuscript and a directory of artifacts. `--doctor` describes the
system as it is configured right now, without a key or a network call.

**Files.** `storyforge.py` (CLI and phase orchestration), `doctor.py`
(orientation report), `config.py` (every setting, one singleton).

**Guard.** `tests/test_doctor.py` — the report needs no key, every guard it
names exists, every command it suggests is runnable, and the version it prints
is the shipped one.

**Extend.** A new top-level flag goes in `storyforge.py:main()` and, if it
changes what a driver needs to know, into `doctor.collect()`.

## L1 — phases

**Contract.** Each phase reads named artifacts from the project directory,
writes named artifacts back, and records itself in `checkpoint.json`. A phase
that already landed is skipped on resume, so a run is idempotent and can be
re-driven from any point.

seed → world → characters → outline → outline validation → draft (with parallel
rhetorical variants) → prose score → revision loop → critique → full review →
backward propagation → adversarial edit → export.

**Files.** `pipeline/` holds the phase implementations; `agents/` holds the
editor and orchestrator personas; `interview/` holds the optional guided
front-end; `templates/*.json` holds genre presets.

**Guard.** `tests/test_pipeline.py` and `scripts/smoke.py`, which drives the
whole chain offline against a stub model and prints a per-chapter score, redraw
count and word count.

**Extend.** A new phase needs an artifact name, a checkpoint entry, a role in
L2, and a line in the smoke run's phase list. Skipping any of those four makes
the phase invisible to a driver.

## L2 — roles

**Contract.** No phase ever names a model. It names a role, and `Config`
resolves the role: `LLM_MODEL_{ROLE}` first (a known alias or any raw provider
model id), then the routing table, then a fallback. Every resolution records
provenance — `env-alias`, `env-raw` or `routing` — in `Config.resolution_log`,
which is what `--doctor` and `--show-models` render.

Three tables, 21 roles: `phase_models`, `interview_models`, `debate_models`.
`LLM_MODEL_{ROLE}_BASE_URL` points a single role at a second provider.

**Files.** `config.py`. The alias table is the only place in the repo where a
vendor model id may appear.

**Guard.** `tests/test_model_routing_agnostic.py` (any id, any role, provenance
recorded, no key needed) and `tests/test_model_literal_guard.py` (no vendor id
anywhere else). `tests/test_model_advisor.py` pins the shipped defaults.

**Extend.** Add an alias to `Config.models`, route a role to it, and write a
rationale entry in `model_rationale`. Re-point a default only after
`Config.check_model_availability()` and a benchmark run recorded in
`reference/benchmark-report.md`.

## L3 — services

**Contract.** Shared capabilities with no knowledge of phases. A service takes
data, returns data, and reports what it had to give up.

| Service | File | Contract |
|---|---|---|
| API client | `pipeline/api.py` | One door to every model. Retries by error kind, caches responses when asked, and repairs malformed JSON in `parse_json_output()`. |
| Prose lab | `pipeline/prose_lab.py` | Deterministic prose gate. Scores without a model, so a chapter can fail on mechanics alone. |
| Knowledge base | `pipeline/knowledge_base.py` | Lazy-loaded writing theory under a token budget. A cut file is labeled as cut, and the block names what was omitted. |
| Style engine | `pipeline/style_engine.py` | Voice fingerprints and drift checks against a target style. |
| Canonical store | `pipeline/canonical_store.py` | The novel's facts. `FileCanonicalStore` is the default; `hindsight` and `gbrain` backends sit behind the same ABC. |
| Compression | `pipeline/reio_compression.py` | Context compression for long novels, off with `--no-reio`. |

**Guard.** Each service has its own test module under `tests/`.

**Extend.** A service that spends tokens must report its budget the way the
knowledge base does. Silent truncation is a defect here, not an optimization.

## L4 — state

**Contract.** Every write replaces its file atomically: build a temp file
beside the target, flush, fsync, `os.replace`. A crash, a full disk or a
`kill -9` leaves either the old file or the new one, never half of either.
Append-only logs are the single exception and each carries a
`# atomic-exempt: <reason>` marker.

`canonical_state.json` is the one source of truth for characters, world facts,
plot threads, foreshadowing and chapter summaries. `checkpoint.json` is the one
record of what has run. Everything else is derived and can be rebuilt.

**Files.** `pipeline/state_io.py` (the primitive), `pipeline/canonical_store.py`,
and every module that writes an artifact.

**Guard.** `tests/test_atomic_write_coverage.py` scans every shipped `.py` for a
truncating handle and fails when one appears.

**Extend.** Use `atomic_write_text` / `atomic_write_json`. If you believe a write
must truncate, the guard will ask you to say why on the line.

## L5 — evidence

**Contract.** A run explains itself without being asked. Scores, redraw counts,
length verdicts, reference budget notes, routing provenance and the smoke
report are all data, not prose, so an agent can compare two runs.

**Files.** `doctor.py`, `scripts/smoke.py`, `pipeline/review.py`,
`pipeline/backprop.py`, `reference/benchmark-report.md`.

**Guard.** The offline smoke run is the end-to-end check: it drives every phase
against a stub model and fails if a phase stops producing its artifact.

**Extend.** When you add a decision, add the number that shows it. A new
threshold with no reported value is a decision nobody can audit.

## How the levels interlock

A driver's loop is: orient at L0 (`--doctor`), pick levers at L2 (role env
vars), run L1, and read L5. L3 and L4 are what make the run trustworthy: L3
because every token spend is reported, L4 because a partial run can always be
resumed rather than restarted.

The system is accretive in three ways. The API cache makes a repeated call free.
`pipeline/revision_memory.py` and `pipeline/backprop.py` turn this run's
criticism into the next run's constraints. `canonical_state.json` carries facts
forward so later chapters cannot contradict earlier ones without a recorded
change declaration.

## Reading order for a new agent

1. `python3 storyforge.py --doctor`
2. This file
3. `AGENTS.md` for the levers and the conventions
4. `docs/CHANGELOG.md` for why the system looks like this
5. The module you are about to change, and its guard test

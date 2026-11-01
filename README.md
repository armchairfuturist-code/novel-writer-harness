# Novel Writer Harness — StoryForge v0.10

**Write a complete novel by typing one sentence.** StoryForge takes a story concept and autonomously generates a full novel — from worldbuilding and characters through to a complete manuscript with continuity verification, style control, and structured state tracking.

It's a combinatorial fork of the best ideas from 12+ open-source AI writing projects, tuned to route different AI models to the tasks they're best at. The debate court, change declaration system, style engine, foreshadowing state machine, and semantic context retrieval are custom-built.

---

## What it does

Give it a seed concept like:

> "A jazz musician in 1920s New Orleans discovers that the notes she plays on her trumpet can heal wounds — but every healing steals a memory from someone she loves."

And it will:

1. **Analyze** your concept into a structured project plan (title, genre, tone, POV, chapter count)
2. **Build a world** — geography, history, factions, magic/tech systems, mood, central conflict
3. **Create characters** — 6-7 characters with motivations, flaws, secrets, arcs, and Dramatica-style role functions
4. **Outline the plot** — chapter-by-chapter with key events, emotional arcs, foreshadowing seeds, POV assignments, and character arc beats for every chapter
5. **Validate the outline** — single-LLM structural check before drafting: character coverage, foreshadowing completeness, emotional arc progression, beat density, information boundaries. FAILs block drafting before you spend API dollars
6. **Declare changes** — each chapter outputs a structured `---CHANGES---` JSON block tracking 12 categories of state transitions; the canonical store updates deterministically from the LLM's own declarations
7. **Debate** (opt-in) — three specialized LLM agents cross-examine each chapter against canonical state, now augmented by a lazy-loaded writing theory knowledge base
8. **Revise** — chapters below 6.0/10 enter a revision loop (score → critique → revise → re-score, up to 3 rounds)
9. **Review and edit** — mechanical quality checks + dual-persona literary critique + backward propagation + adversarial editing
10. **Export** — full manuscript as markdown, plus PDF/epub if Pandoc is installed

---

## Run it

```bash
git clone https://github.com/armchairfuturist-code/novel-writer-harness
cd novel-writer-harness
python3 -m pip install -r requirements.txt
python3 storyforge.py --doctor                 # orientation: no API key, no network
python3 scripts/smoke.py "a lighthouse keeper adopts a shipwrecked child" --chapters 2
export LLM_API_KEY="..." LLM_BASE_URL="https://your-provider/v1"
python3 storyforge.py "a jazz musician heals wounds with her trumpet, and each healing steals a memory"
```

The smoke run proves the whole pipeline end to end without a key. Everything
after it is a real run against your provider.

## What is new in v0.10

- `storyforge.py --doctor` is the front door: version, provider, every role's
  resolved model and where that answer came from, the newest project's state,
  the guard list, and the next command. `--json` for a program, `--live` to also
  ask the provider what it serves.
- Any model can hold any role. `LLM_MODEL_{ROLE}` takes a known alias or a raw
  provider model id, and `LLM_MODEL_{ROLE}_BASE_URL` moves one role to a second
  provider. Nothing is silently dropped.
- `AGENTS.md` is the agent contract and `docs/ARCHITECTURE.md` is the six-level
  tower, each level with its contract, its files, its guard test and how to
  extend it.
- Four new guard tests hold those claims, including one that fails when a
  document names a flag or an environment variable the code does not have.

`docs/CHANGELOG.md` carries every version, including the durability, quality,
debate and foundation work below v0.10.

---


## How it uses different AI models

Different AI models have different strengths. StoryForge routes each phase
to the model best suited for that task — planning gets a large-context
reasoning model, drafting gets a prose-optimized writer, scoring gets a
fast cheap model, and mechanical checks run locally with zero API cost.

The default routing is tuned for quality, but every assignment is overridable:

```bash
export LLM_BASE_URL="https://your-provider.com/v1"
export LLM_API_KEY="your-key"
export LLM_MODEL_DRAFT="gpt-4o"                    # override drafting model
export LLM_MODEL_SEED="claude-sonnet-4-20250514"    # override planning model
```

| Phase | Default | Rationale |
|---|---|---|
| Planning (seed, world, outline) | large-context reasoner | Expansive worldbuilding needs big context |
| Character creation | prose-optimized model | Nuanced profiles need strong creative writing |
| Chapter drafting | prose-optimized model (precision variant) | Best long-form fiction quality |
| Outline validation | fast reasoner | Structural checks need reasoning, not prose |
| Revision + adversarial | prose-optimized model (precision) | Targeted fixes against specific feedback |
| Debate: Lore Prosecutor | large-context reasoner | Cross-references against full canonical state |
| Debate: Plot Sentinel | prose-optimized model | Foreshadowing + beat compliance |
| Debate: Magistrate | fast/cheap model | Conflict resolution, mechanical reconciliation |
| Scoring, canonical state, style | built-in (no API) | Regex, word-overlap, Counter — zero cost |

Change routing defaults in `config.py`. Any OpenAI-compatible API works, and
a role override takes a raw model id as happily as an alias, so pointing
drafting at a model this repo has never heard of needs no edit here.
`python3 storyforge.py --show-models` prints all 21 roles with the variable
that owns each, and `--doctor` reports the same as data.

Aliases are defaults, not a promise: a provider can retire a model under you. `Config.check_model_availability()` reads the provider's `/models` list and names every routed alias the catalog no longer serves, and `Config.print_routing_plan()` prints that warning. An env override such as `LLM_MODEL_DRAFT` always wins, and `reference/benchmark-report.md` records the last measured ranking.

---

## Quick Start

### 1. Requirements

- Python 3.10+
- An API key for any OpenAI-compatible API (set as `LLM_API_KEY` or `CROFAI_API_KEY`)
- `pip install httpx sentence-transformers scipy`
- Optional: `pandoc` + LaTeX for PDF/epub export

### 2. Install

```bash
# Install dependencies
pip install httpx sentence-transformers scipy

# Set your API key
export CROFAI_API_KEY="your-api-key-here"    # Mac/Linux
set CROFAI_API_KEY=your-api-key-here         # Windows CMD
$env:CROFAI_API_KEY="your-api-key-here"      # Windows PowerShell
```

### 3. Write a novel

```bash
python storyforge.py "A jazz musician in 1920s New Orleans..."
```

That's it. The pipeline runs through all phases and outputs to `~/storyforge-projects/{novel-title}/`.

### 4. Write with quality guarantees

```bash
python storyforge.py "concept" --debate      # Enable debate court continuity checking
python storyforge.py "concept" --quick       # Skip expensive phases, draft only
python storyforge.py "concept" --no-changes  # Fall back to passive state extraction
```

### 5. Benchmark the writing models (optional)

```bash
python storyforge.py --benchmark
```

Tests all Kimi K2.6 variants on 5 creative writing prompts, compares them head-to-head.

### 6. Smoke test with no API key

```bash
python3 scripts/smoke.py "A jazz musician in 1920s New Orleans heals wounds with her trumpet" --chapters 2
```

This runs the full pipeline against a deterministic stub provider: seed, world, characters, outline, drafts, gates, export. It needs no key and makes no network call. It prints one line per phase and a final PASS or FAIL, and it exits non-zero on any failure.

Add `--live` to run the same path against a real provider, `--dir PATH --keep` to inspect the output, and `--json` for a machine-readable report.

---

## Command Reference

| Command | What it does |
|---|---|
| `python storyforge.py --doctor` | Orientation: version, provider, roles, project state, guards, next command |
| `python storyforge.py --doctor --json` | The same report as data |
| `python storyforge.py --doctor --live` | Also ask the provider which model ids it serves |
| `python storyforge.py --show-models` | Every role, its model, its reason, and the env var that owns it |
| `python storyforge.py "concept"` | Full pipeline: seed analysis through export |
| `python storyforge.py --quick "concept"` | Skip review, backprop, and adversarial phases |
| `python storyforge.py --resume DIR` | Resume an interrupted run from its project directory |
| `python storyforge.py --debate "concept"` | Enable debate court — LLM agents cross-examine each chapter |
| `python storyforge.py --no-changes "concept"` | Disable structured change declarations |
| `python storyforge.py --no-knowledge-base "concept"` | Disable writing theory reference injection |
| `python storyforge.py --no-validate-outline "concept"` | Skip outline structural validation |
| `python storyforge.py --style-profile NAME "concept"` | Bind a named style profile to all chapters |
| `python storyforge.py --auto-style-extract "concept"` | Auto-extract style profiles after each chapter |
| `python storyforge.py --genre mystery "concept"` | Use genre beat template (mystery, thriller, romance, fantasy, sci-fi) |
| `python storyforge.py --benchmark` | Benchmark model variants on prose quality |
| `python storyforge.py --project-dir /path "concept"` | Override output directory |
| `python storyforge.py --single-variant "concept"` | Draft 1 variant per chapter (cheaper) |
| `python storyforge.py --single-review "concept"` | Use single LLM review instead of dual-persona |
| `python storyforge.py --no-backprop "concept"` | Skip backward propagation scan |
| `python storyforge.py --no-adversarial "concept"` | Skip adversarial editing pass |
| `python storyforge.py --no-reio "concept"` | Disable ReIO context compression |
| `python storyforge.py --help` | Show all options |
| `python3 scripts/smoke.py "concept"` | Offline smoke test: full pipeline, stub provider, no key needed |

---

## Output Structure

After the pipeline finishes, your novel lives here:

```
~/storyforge-projects/{slug}/
├── manuscript.md              # Full novel, ready to read
├── spec.json                  # Seed concept analysis (title, genre, tone, POV)
├── world.json                 # World bible (geography, conflict, mood)
├── characters.json            # All character profiles
├── outline.json               # Chapter-by-chapter outline with beats
├── outline_validation.json    # Pre-draft structural validation report (v0.5)
├── checkpoint.json            # Completed phases for resume
├── foreshadows.json           # Foreshadow tracker state (7-state machine)
├── embeddings.db              # SQLite embedding store (semantic chapter retrieval)
├── canonical_state.json       # Canonical state store (traits, facts, threads, foreshadowing)
├── styles/                    # Saved style profiles (v0.5)
│   └── chapter-001.json
├── chapters/
│   ├── chapter-001.md         # Each chapter with header metadata + prose
│   ├── chapter-002.md
│   └── ...
├── manuscript.pdf             # Only if Pandoc + LaTeX installed
└── manuscript.epub            # Only if Pandoc installed
```

---

## Architecture

Six levels, each with one contract and one guard test. `docs/ARCHITECTURE.md`
is the full map, and `python3 storyforge.py --doctor` reports the live state of
all six without an API key.

| Level | What it is | Where |
|---|---|---|
| L0 Contract | A seed phrase in, a manuscript out | `storyforge.py`, `doctor.py` |
| L1 Phases | seed, world, characters, outline, validation, draft, score, critique, review, backprop, adversarial, export | `pipeline/`, `agents/` |
| L2 Roles | Every phase asks for a model by role, never by name | `config.py` |
| L3 Services | API client, prose lab, knowledge base, style engine, canonical store | `pipeline/` |
| L4 State | Atomic writes, one checkpoint, one canonical truth | `pipeline/state_io.py` |
| L5 Evidence | Scores, redraws, budget notes, routing provenance, the smoke run | `doctor.py`, `scripts/smoke.py` |

```
storyforge.py                       # CLI entry point, phase orchestration, checkpointing
doctor.py                           # --doctor: the orientation report (no key, no network)
config.py                           # VERSION, model aliases, role routing, every threshold
pipeline/
├── api.py                          # CrofaiClient: one door to every model, retries by error kind, JSON repair
├── state_io.py                     # atomic_write_text / atomic_write_json: the only way to write a file
├── canonical_store.py              # ABC + FileCanonicalStore: traits, world facts, threads, foreshadowing
├── changes.py                      # ---CHANGES--- parser and the 12-category store applier
├── prose_lab.py                    # the deterministic prose gate, no model involved
├── knowledge_base.py               # lazy-loaded writing theory under a token budget
├── debate.py                       # Lore Prosecutor, Plot Sentinel, Mechanical Magistrate
├── outline_validator.py            # the pre-draft structural gate, five dimensions
├── draft.py                        # chapter writing, revision loop, parallel rhetorical variants
├── review.py                       # dual-persona literary critique
├── backprop.py / iterative_backprop.py   # contradiction scanning, foreshadowing debt
├── adversarial_edit.py             # model plus mechanical tightening
├── factcheck.py                    # regex cross-chapter consistency
├── reio_compression.py             # forgetting-curve compression for long novels
├── foreshadow_tracker.py           # seven-state machine with auto-detection
├── embedding_store.py              # optional semantic chapter retrieval
├── style_engine.py                 # voice fingerprints and drift checks
├── seed.py / worldbuilding.py / characters.py / outline.py   # the planning phases
└── export.py                       # manuscript assembly, Pandoc PDF and EPUB
reference/knowledge/                # the writing-theory files the knowledge base loads
templates/                          # five genre templates
tests/                              # the suite, including the guard tests named in AGENTS.md
```

---


## Known Issues

### Scoring favors ultra-short chapters in variant selection

The mechanical scorer starts at a 7.0 baseline and applies penalties for banned words, tell-don't-show patterns, and low pacing variance. Ultra-short chapters (~100-200 words) have fewer opportunities to trigger these penalties and can outscore full-length chapters (~4000 words) that contain minor infractions. In the "The Bleeding Note" test run, Chapter 1's suspense_first variant (165 words, score 7.4) beat the reveal_late variant (4192 words, score 6.2) despite the latter being a complete chapter. The word-count penalty only triggers below 2000 words, and 165 words slipped through.

**Fixed in v0.8.** `prose_lab.length_verdict()` is a gate, not a hint: a chapter outside 75-135% of its target word count is redrawn from the same brief, and a stub under `MIN_WORDS_FOR_SCORE` cannot win variant selection at all. The redraw count is logged per chapter, so a run can be audited. The rule follows the overlength handling in [lechmazur/writing](https://github.com/lechmazur/writing): regenerate from the same prompt, keep the first in-range response.

### A capped reference block looked complete

`debate.py` asks the knowledge base for at most 500 tokens. When a query matched more than that, the block stopped mid-file or skipped files with no trace, so the court argued from a partial rule and called it the whole rule.

**Fixed in v0.9.** The block carries a budget note naming what was cut short and what was left out, and the `KnowledgeBase` keeps the same facts on `last_budget_truncated` and `last_budget_dropped` for logs.

### Export wrote one character, and could truncate the manuscript

`build_manuscript_markdown()` streamed straight into `manuscript.md` through `open(..., "w")`, so a crash mid-export left a half-written book where the complete one stood. Its *Dramatis Personae* loop also wrote its two lines one indent level out of the loop body, which listed the last character only.

**Fixed in v0.9.** The manuscript is assembled in memory and lands in one `atomic_write_text`; the EPUB is staged as `.part` and renamed into place; the cast list prints every character. `tests/test_export_atomicity.py` pins all three.

---

## Story structures

5 plot frameworks supported in the outline phase:

| Structure | Description |
|---|---|
| Three-Act | Classic setup / confrontation / resolution |
| Hero's Journey | Monomyth: ordinary world through return |
| Save the Cat | Blake Snyder's 15-beat structure |
| Seven-Point | Dan Wells' hook-through-resolution |
| Freytag's Pyramid | Exposition through denouement |

Default: Three-Act. Change in `pipeline/outline.py` or pass a structure key.

---

## Changing the configuration

Everything is in `config.py`. You can change:

- **Which AI models to use** for each phase (`phase_models`, `debate_models`, `interview_models`)
- **Debate thresholds** (`debate.max_debate_rounds`, `debate.force_rewrite_on_fatal`, `debate.acceptable_mechanical_floor`)
- **Banned words list** (add your own pet peeves)
- **Chapter length** (default: 4000 words)
- **Chapter count range** (default: 8-30)
- **Scoring thresholds** (what counts as "good enough")
- **Rhetorical strategy profiles** (add your own)
- **Style profile dimensions** (customize the `StyleProfile` dataclass)
- **Knowledge base directory** (point to your own reference files)
- **Output directory** (default: ~/storyforge-projects/)
- **API endpoint** (point at any OpenAI-compatible API)
- **Token cost estimates** per input/output token
- **ReIO compression budget and fidelity tiers**
- **Canonical store backend selection** (via `create_canonical_store()`)

Per-phase model overrides via env vars: `LLM_MODEL_DRAFT`, `LLM_MODEL_SEED`, `LLM_MODEL_LORE_PROSECUTOR`, etc.

---

## Running tests

```bash
pip install pytest
pytest tests/ -v
```

863 tests (861 pass offline; two need a live API key) covering: the v0.10 additions - the orientation report, the model-agnostic role contract, and the four guard tests that hold them - the v0.9 additions - the atomic-write coverage guard, export atomicity and the full cast list, and the reference budget note - the v0.8 additions - atomic state writes, retry by error kind, the name registry and roster hygiene, the length gate and its redraws, and the offline seed-phrase smoke run - plus all pipeline phases, debate court (3 agents + cross-examination), change declarations (parse, apply, format), style engine (extraction, profiles, comparison), knowledge base (load, match, cap, semantic-rescue), outline validator (formatting, all 5 dimensions), canonical store (7-state foreshadowing machine, ABC contract), rhetorical strategies, scoring mechanics, BM25 retrieval, revision prompt generation, backpropagation, adversarial editing, ReIO compression, iterative backprop, genre templates, an...

---

## Origins

StoryForge is a combinatorial fork of ideas from these open-source projects:

- **autonovel** (NousResearch) — Pipeline architecture, dual immune system, Opus dual-persona review
- **tianming-novel-ai-writer** (zy-zmc) — 15-dimension fact snapshot, 12-class change declarations, 6-gate validation
- **AI-Novel-Writing-Assistant** (ExplosiveCoderflome, since renamed; now under a Biz Novel Studio license — AGPL-3.0 by default, with separate commercial authorization to run it as a service) — Style engine, Creative Hub, LangGraph agent runtime. Ideas and attribution only; no code was copied.
- **oh-story-claudecode** (zenstory-ai, formerly worldwonderer; MIT) — 7-agent skill team, lazy-loaded 100+ reference files, 13 hook patterns
- **NovelForge** (RhythmicWave; AGPL-3.0, ideas only) — Schema-first card writing, @DSL context injection, workflow-as-code
- **dramatica-flow** (ydsgangge-ux; MIT) — Causal chain engine, information boundaries, character relationship networks. The v0.8 atomic state writes and retry-by-kind backoff follow its `core/state` and `core/llm` design.
- **NovelClaw** (iLearn-Lab) — Dynamic memory-first workspace, inspectable runs with per-run artifacts
- **AI_NovelGenerator** (YILING0013; AGPL-3.0, structure and naming ideas only — no code copied or adapted) — State tracking, foreshadowing management
- **gemini-writer** (Doriandarko) — 1M context auto-compression, recovery mode
- **storycraftr** (raestrada) — Provider-agnostic config, embeddings context
- **ai-book-writer** (adamwlarson) — Multi-agent collaboration via AutoGen
- **NovelGenerator** (KazKozDev) — Parallel perspective tracking, emotional arcs
- **libriscribe** (guerra2fernando) — Multi-model support, fact-checking
- **NovelWriter** (EdwardAThomson; MIT) — Genre templates, story structures, quality analytics. The v0.8 name registry and roster address styles follow its `NameRegistry` and `ADDRESS_STYLES`.
- **book-generator** (wesleyscholl) — Pandoc/LaTeX export, KDP-ready output

Benchmark methodology from [lechmazur/writing](https://github.com/lechmazur/writing). That repository carries no license, so we cite its method and vendor none of its data.

The debate protocol was inspired by multi-agent verification patterns in code review systems, adapted for narrative continuity. The change declaration system draws from tianming's "write to 3000 chapters without relying on context" architecture. The style engine adapts feature extraction from AI-Novel-Writing-Assistant's reusable writing-style profiles. The knowledge base borrows the lazy-loaded reference pattern from oh-story-claudecode's agent skill architecture.

---

## License

MIT for this repository. The Origins section names each upstream project and its license. Several upstreams are AGPL-3.0 or commercial, so we took ideas and attribution from them and copied no code.

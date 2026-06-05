# Novel Writer Harness — StoryForge v0.5

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

## Key Features

### v0.5: The Quality Layer

#### Outline Structural Validator (`pipeline/outline_validator.py`)

A single-LLM-call pre-draft quality gate that runs between outline generation and chapter drafting. Checks five structural dimensions:

| Dimension | Severity | What it checks |
|---|---|---|
| **Character coverage** | FAIL if broken | Every named character must appear in ≥1 chapter |
| **Foreshadowing completeness** | WARN only | Every plant needs a payoff chapter within range |
| **Emotional arc progression** | FAIL if 5+ flat | No 3+ consecutive chapters with identical arcs |
| **Beat density balance** | FAIL if empty | Every chapter must have ≥1 key_event and ≥1 character_arc_beat |
| **Information boundaries** | FAIL if impossible | POV characters can't narrate events they couldn't witness |

FAILs pause the pipeline with a clear report. WARNs display but let you continue. One call to the `deepseek-flash` model — deterministic, <$0.01 per check. On by default; `--no-validate-outline` to skip.

#### Structured Change Declarations (`pipeline/changes.py`)

Every chapter draft and revision outputs a `---CHANGES---` JSON block declaring exactly what changed across 12 categories: character status, conflict progress, plot nodes, foreshadowing actions, location changes, faction changes, time advancement, character movement, item transfers, secret reveals, oath changes, and deadline changes. The system parses this block, strips it from the prose, and deterministically updates the canonical store from the LLM's own declarations — replacing passive state extraction with active state declaration. Combined with the debate court, the Magistrate can cross-validate declared changes against continuity complaints.

```bash
python storyforge.py "concept"           # change declarations on by default
python storyforge.py "concept" --no-changes  # fall back to passive extraction
```

The architecture draws from [tianming-novel-ai-writer](https://github.com/zy-zmc/tianming-novel-ai-writer)'s 15-dimension fact snapshot and 12-class change declaration system.

#### Style Engine (`pipeline/style_engine.py`)

A pure-Python prose feature extractor that computes 10 quantitative dimensions from raw text with zero LLM cost: sentence rhythm (mean + standard deviation), paragraph length, dialogue density, vocabulary tier, sensory density per 1000 words, pacing profile (action/reflection/description ratios), POV distance (close 3rd vs omniscient), hook density, and 6-emotion emotional register. Profiles are saved as JSON to `styles/` and can be bound to chapters to shape prose more precisely than the 4 hardcoded rhetorical strategies. Includes `compare_profiles()` for style drift detection between chapters.

```bash
python storyforge.py "concept" --style-profile chapter-001  # bind a saved profile
python storyforge.py "concept" --auto-style-extract        # save per-chapter profiles
```

Inspired by [AI-Novel-Writing-Assistant](https://github.com/ExplosiveCoderflome/AI-Novel-Writing-Assistant)'s writing style engine.

#### Lazy-Loaded Writing Theory Knowledge Base (`pipeline/knowledge_base.py` + 10 reference files)

10 curated markdown files on writing theory organized by agent role. The debate court's Lore Prosecutor and Plot Sentinel load relevant references on demand — ≤500 tokens each — sharpening their complaints with concrete craft knowledge rather than relying on prompt-alone reasoning:

| Agent | Reference files |
|---|---|
| **Lore Prosecutor** | Character trait tracking, worldbuilding consistency, timeline continuity, contradiction patterns |
| **Plot Sentinel** | Foreshadowing payoff patterns, pacing diagnostics, outline beat compliance |
| **Mechanical Magistrate** | Actionable revision instruction writing |
| **Drafting** | Chapter hook techniques (13 end + 7 open patterns), dialogue craft, sensory immersion |

Each file is 50-200 lines of specific advice with examples, tagged with YAML frontmatter for keyword-based relevance matching. The `KnowledgeBase` class scores files by overlap with chapter context and returns only the best matches within a token budget.

```bash
python storyforge.py "concept" --debate            # knowledge base on by default
python storyforge.py "concept" --no-knowledge-base  # disable reference injection
```

The lazy-loaded pattern adapts [oh-story-claudecode](https://github.com/worldwonderer/oh-story-claudecode)'s 100+ agent reference file architecture.

### v0.4: Triadic Constraint Debate Protocol (SGDD) — opt-in with `--debate`

The debate protocol replaces the generic mechanical revision prompt with a **state-grounded dialectical debate** between three specialized verification agents. Instead of "fix these banned words," the revision loop gets canon-grounded instructions like "Fix Alice's eye color: canon says blue, draft says green."

| Agent | Grounding | What it checks | Model |
|---|---|---|---|
| **Lore Prosecutor** | `canonical_state.json` + KB refs | Continuity breaks, trait drift, world-building violations, timeline errors | DeepSeek V4 Pro |
| **Plot Sentinel** | Foreshadow state machine + outline beats + KB refs | Overdue threads, spontaneous plants, missed milestones, pacing violations | Kimi K2.6 |
| **Mechanical Magistrate** | Both transcripts + mechanical scores + change declarations | Reconciles conflicts, cross-validates declared changes against complaints, outputs deterministic revision manifest | Qwen3.5 9B |

The debate loop runs: parallel evaluation → cross-examination (up to 2 rounds) → magistrate verdict. If any FATAL continuity break is found, the chapter is forced into revision with the manifest as its revision prompt. Configurable via `config.debate.*` thresholds. Adds 3-5 LLM calls per chapter revision.

### v0.3: Foundation Systems

- **Canonical state store** (`canonical_state.json`) — character traits, world facts, plot threads, foreshadowing debts tracked chapter by chapter with word-overlap relevance scoring
- **7-state foreshadowing machine** — `planted → hinted → reinforced → due → overdue → paid` (plus `abandoned`)
- **4 rhetorical strategies** (Postwriter-inspired) — suspense_first, reveal_late, sensory_immersion, interiority_forward
- **ReIO context compression** — forgetting-curve compression for long novels; recent chapters full fidelity, middle chapters condensed, early chapters arc-summarized
- **Iterative backward propagation** — scans chapters for contradictions, generates revisions, re-scans until clean
- **5 genre templates** — mystery, thriller, romance, fantasy, sci-fi with structured beats, required elements, and tracking items
- **Semantic context retrieval** — `sentence-transformers/all-MiniLM-L6-v2` embedding search over prior chapters (replaces BM25 keyword matching)
- **Dual-persona review** — Literary Critic + Professor of Fiction debate each chapter's quality
- **Adversarial editing** — LLM identifies weakest 15% of each chapter by cut category (filler, redundancy, over-explanation, weak verb, telling, pacing drag)
- **Chapter feedback loop** — post-chapter review with user-in-the-loop revision
- **Checkpoint/resume** — auto-detects completed phases, resumes from interruption without data loss

---

## How it uses different AI models

Different AI models have different strengths. This tool routes each task to the best model:

| Phase | Model | Why |
|---|---|---|
| Planning (seed, world, outline) | DeepSeek V4 Pro | Large context window for expansive worldbuilding |
| Outline validation | DeepSeek V4 Flash | Cheap reasoning with 1M context for 22-chapter outlines |
| Character creation | Kimi K2.6 | Prose-optimized, writes nuanced character profiles |
| Chapter writing | Kimi K2.6 Precision | Best writing quality for long-form fiction |
| Mechanical scoring | Built-in (no API call) | Regex-based — instant, zero cost |
| Revision (LLM pass) | Kimi K2.6 Precision | Fixes specific mechanical + continuity issues |
| Backward propagation | Built-in (no API call) | Pattern matching — detects contradictions without LLM |
| Adversarial editing | Kimi K2.6 Precision | Identifies and classifies cuts per chapter |
| Literary critique | Kimi K2.6 | Dual-persona review (Critic + Professor) |
| Lore Prosecutor | DeepSeek V4 Pro | Continuity cross-referencing against canonical state |
| Plot Sentinel | Kimi K2.6 | Foreshadowing state machine + outline beat compliance |
| Mechanical Magistrate | Qwen3.5 9B | Conflict resolution, change declaration cross-validation |
| Canonical state store | Built-in (no API call) | Word-overlap scoring on local JSON file — no LLM tokens |
| Style engine | Built-in (no API call) | Pure-Python regex + Counter analysis — no LLM tokens |

Configured for any OpenAI-compatible API. The endpoint defaults to `https://beta.crof.ai/v1` but can be overridden with `LLM_BASE_URL`. Per-phase model selection can be overridden with `LLM_MODEL_SEED`, `LLM_MODEL_DRAFT`, etc. Change routing defaults in `config.py`.

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

---

## Command Reference

| Command | What it does |
|---|---|
| `python storyforge.py "concept"` | Full pipeline: seed analysis through export |
| `python storyforge.py --quick "concept"` | Skip review, backprop, and adversarial phases |
| `python storyforge.py --resume 7` | Resume drafting from chapter 7 (recovery mode) |
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

StoryForge has a modular pipeline design — each phase is a standalone module that can be composed, skipped, or replaced:

```
storyforge.py                       # CLI entry point (argparse, checkpoint mgmt)
pipeline/
├── api.py                          # CrofaiClient (httpx, 600s timeout, 3x retry 429/5xx, JSON repair)
├── config.py                       # Model routing, scoring thresholds, DebateConfig, StyleConfig
├── canonical_store.py              # ABC + FileCanonicalStore (character traits, world facts, threads, 7-state foreshadowing)
├── changes.py                      # v0.5: structured ---CHANGES--- block parser + 12-category store applier
├── style_engine.py                 # v0.5: pure-Python StyleProfile extractor (10 dimensions)
├── knowledge_base.py               # v0.5: lazy-loaded writing theory references for debate agents
├── debate.py                       # v0.4: Lore Prosecutor + Plot Sentinel + Mechanical Magistrate
├── outline_validator.py            # v0.5: pre-draft 5-dimension structural quality gate
├── draft.py                        # Chapter writing, revision loop, parallel variants, change declaration integration
├── review.py                       # Dual-persona literary critique (Critic + Professor → synthesis)
├── backprop.py / iterative_backprop.py  # Forward contradiction scanning, foreshadowing debt tracking
├── adversarial_edit.py             # LLM + mechanical prose tightening (15% cut target)
├── factcheck.py                    # Regex-based cross-chapter consistency verification
├── reio_compression.py             # Forgetting-curve context compression for long novels
├── foreshadow_tracker.py           # 7-state machine with auto-detection from chapter text
├── embedding_store.py              # sentence-transformers + SQLite semantic chapter retrieval
├── seed.py / worldbuilding.py / characters.py / outline.py  # Planning phases
└── export.py                       # Manuscript assembly + Pandoc PDF/EPUB
reference/
├── knowledge/                      # 10 lazy-loaded writing theory reference files
│   ├── lore-prosecutor/            # Trait tracking, world consistency, timeline, contradictions
│   ├── plot-sentinel/              # Foreshadowing, pacing, outline compliance
│   ├── magistrate/                 # Actionable revision instruction writing
│   └── drafting/                   # Hook techniques, dialogue craft, sensory immersion
└── chapters/                       # Reference novel sample
tests/                              # 448+ unit tests (all phases, debate, changes, style engine, KB)
templates/                          # 5 genre JSON templates (mystery, thriller, romance, fantasy, sci-fi)
```

---

## Known Issues (v0.5)

### Scoring favors ultra-short chapters in variant selection

The mechanical scorer starts at a 7.0 baseline and applies penalties for banned words, tell-don't-show patterns, and low pacing variance. Ultra-short chapters (~100-200 words) have fewer opportunities to trigger these penalties and can outscore full-length chapters (~4000 words) that contain minor infractions. In the "The Bleeding Note" test run, Chapter 1's suspense_first variant (165 words, score 7.4) beat the reveal_late variant (4192 words, score 6.2) despite the latter being a complete chapter. The word-count penalty only triggers below 2000 words, and 165 words slipped through.

**Planned fix:** add a minimum-word-count gate to variant selection — chapters below 50% of the target word count (2000 words for the 4000 default) are automatically rejected regardless of mechanical score, or at minimum heavily penalized. This is a one-line change in the variant selection logic in `draft.py`.

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

448+ tests covering: all pipeline phases, debate court (3 agents + cross-examination), change declarations (parse, apply, format), style engine (extraction, profiles, comparison), knowledge base (load, match, cap), outline validator (formatting, all 5 dimensions), canonical store (7-state foreshadowing machine, ABC contract), rhetorical strategies, scoring mechanics, BM25 retrieval, revision prompt generation, backpropagation, adversarial editing, ReIO compression, iterative backprop, genre templates, and CLI argument parsing.

---

## Origins

StoryForge is a combinatorial fork of ideas from these open-source projects:

- **autonovel** (NousResearch) — Pipeline architecture, dual immune system, Opus dual-persona review
- **tianming-novel-ai-writer** (zy-zmc) — 15-dimension fact snapshot, 12-class change declarations, 6-gate validation
- **AI-Novel-Writing-Assistant** (ExplosiveCoderflome) — Style engine, Creative Hub, LangGraph agent runtime
- **oh-story-claudecode** (worldwonderer) — 7-agent skill team, lazy-loaded 100+ reference files, 13 hook patterns
- **NovelForge** (RhythmicWave) — Schema-first card writing, @DSL context injection, workflow-as-code
- **dramatica-flow** (ydsgangge-ux) — Causal chain engine, information boundaries, character relationship networks
- **NovelClaw** (iLearn-Lab) — Dynamic memory-first workspace, inspectable runs with per-run artifacts
- **AI_NovelGenerator** (YILING0013) — State tracking, foreshadowing management
- **gemini-writer** (Doriandarko) — 1M context auto-compression, recovery mode
- **storycraftr** (raestrada) — Provider-agnostic config, embeddings context
- **ai-book-writer** (adamwlarson) — Multi-agent collaboration via AutoGen
- **NovelGenerator** (KazKozDev) — Parallel perspective tracking, emotional arcs
- **libriscribe** (guerra2fernando) — Multi-model support, fact-checking
- **NovelWriter** (EdwardAThomson) — Genre templates, story structures, quality analytics
- **book-generator** (wesleyscholl) — Pandoc/LaTeX export, KDP-ready output

Benchmark methodology from [lechmazur/writing](https://github.com/lechmazur/writing).

The debate protocol was inspired by multi-agent verification patterns in code review systems, adapted for narrative continuity. The change declaration system draws from tianming's "write to 3000 chapters without relying on context" architecture. The style engine adapts feature extraction from AI-Novel-Writing-Assistant's reusable writing-style profiles. The knowledge base borrows the lazy-loaded reference pattern from oh-story-claudecode's agent skill architecture.

---

## License

MIT

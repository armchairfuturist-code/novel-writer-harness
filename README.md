# Novel Writer Harness

**Write a complete novel by typing one sentence.** The Novel Writer Harness is an AI-powered tool that takes a story concept and autonomously generates a full novel - from worldbuilding and characters through to a complete manuscript.

It's a combinatorial fork of the best ideas from 9 open-source AI writing projects (autonovel, AI_NovelGenerator, gemini-writer, storycraftr, and others), tuned to use different AI models for the tasks they're best at. The foreshadowing engine and semantic context retrieval are custom-built.

---

## What it does

Give it a seed concept like:

> "A detective in a city where memories are currency solves a murder by accessing the victim's final memories, only to discover the killer is someone who erased themselves from everyone's mind."

And it will:

1. **Analyze** your concept into a structured project plan (genre, tone, POV, chapter count)
2. **Build a world** - geography, history, factions, magic/tech systems
3. **Create characters** - 6-7 characters with motivations, flaws, secrets, and growth arcs
4. **Outline the plot** - chapter-by-chapter with key events, emotional arcs, and foreshadowing
5. **Write each chapter** - 3000-5000 words per chapter, with semantic context retrieval and real-time foreshadowing tracking
6. **Score and review** - mechanical quality checks (banned words, show-don't-tell) + AI literary critique
7. **Export** - full manuscript as markdown, plus PDF/epub if you have Pandoc installed

---

## Key Features

### Semantic Context Retrieval (EmbeddingStore)

The old BM25 keyword matcher has been replaced with `sentence-transformers/all-MiniLM-L6-v2` - a local embedding model that understands meaning, not just keywords. When drafting chapter 12, it retrieves the 3 most semantically relevant prior chapters (the ones whose content actually relates to what's happening now), not just the last 3 in sequence.

- 384-dim embeddings stored in SQLite (WAL mode, zero external deps beyond sentence-transformers)
- Auto-indexes each chapter after drafting
- `get_similar_to_chapter(n)` for finding related narrative threads across the entire manuscript
- Lazy-loads the model on first use (no import-time penalty)

### Foreshadowing Engine (ForeshadowTracker)

A 6-state state machine that manages every foreshadow thread from proposal to resolution:

- States: proposed -> planted -> due -> overdue -> resolved / partially_resolved / abandoned
- Each element carries importance, subtlety, category, related characters, resolve-by chapter
- Structured context builder injects OVERDUE / Must Resolve / Upcoming sections into the draft prompt
- Post-hoc auto-detection: 15 regex patterns scan each written chapter for spontaneous foreshadows the LLM plants without being asked, and auto-registers them
- Imports existing outline foreshadow tags on first run
- Persists to `foreshadows.json` alongside project files, survives checkpoint resumes

### Dual-Phase Critique

Each chapter gets scored two ways:

**Mechanical score** (automated, cheap, fast):
- Checks for banned overused words (suddenly, very, gaze, smirk, etc.)
- Measures "tell-don't-show" patterns (felt that, knew that, realized that)
- Analyzes sentence length variety (good pacing = varied sentence lengths)
- Scores from 0-10, starts at 7.0, penalties for weak writing

**LLM critique** (AI judge, deep analysis):
- A Kimi K2.6 model reads the chapter as a literary critic
- Scores on: prose craft, pacing, character depth, dialogue, structure
- Returns specific strengths, weaknesses, and prioritized revision instructions

A chapter is "good enough" at 6.0/10. Target is 8.0/10.

### Adversarial Editing

Each chapter is stress-tested by a critic model that tries to poke holes in logic, character consistency, and plot coherence. The editor model then rewrites to fix any issues found. Produces tighter, more consistent chapters.

### Dual-Persona Backpropagation

A review loop that scores each chapter against retained criteria from earlier chapters, correcting drift and maintaining consistency across the entire novel.

### Recovery Mode

If the pipeline gets interrupted (network issue, rate limit, you close your laptop), just resume from any chapter. Previous chapters stay as they were. The foreshadow tracker and embedding store survive through checkpoint restores.

---

## How it uses different AI models

Different AI models have different strengths. This tool routes each task to the best model:

| Phase | Model | Why |
|---|---|---|
| Planning (world, outline) | DeepSeek V4 Pro | Large context window for expansive worldbuilding |
| Character creation | Kimi K2.6 | Prose-optimized, writes nuanced character profiles |
| Chapter writing | Kimi K2.6 Precision | Best writing quality for long-form fiction |
| Mechanical scoring | Gemini 2.5 Flash | Cheap and fast regex checks |
| Literary critique | Kimi K2.6 | Judges prose quality like a fiction professor |

The tool is configured for the **crofai API** (beta.crof.ai/v1) but you can change any model in `config.py`.

---

## Quick Start

### 1. Requirements

- Python 3.10+
- An API key for crofai (set as `CROFAI_API_KEY` environment variable)
- `pip install httpx sentence-transformers`
- Optional: `pandoc` + LaTeX for PDF/epub export

### 2. Install

```bash
# Install dependencies
pip install httpx sentence-transformers

# Set your API key
export CROFAI_API_KEY="your-api-key-here"    # Mac/Linux
set CROFAI_API_KEY=your-api-key-here         # Windows CMD
$env:CROFAI_API_KEY="your-api-key-here"      # Windows PowerShell
```

### 3. Write a novel

```bash
python storyforge.py "A detective in a city where memories are currency..."
```

That's it. The pipeline runs through all 7 phases and outputs to `~/storyforge-projects/{novel-title}/`.

### 4. Benchmark the writing models (optional)

If you want to find out which Kimi K2.6 variant writes the best prose:

```bash
python storyforge.py --benchmark
```

This tests all 3 variants (speed, balanced, precision) on 5 creative writing prompts, compares them head-to-head, and tells you which one writes best.

---

## Command Reference

| Command | What it does |
|---|---|
| `python storyforge.py "concept"` | Full pipeline: seed analysis through export |
| `python storyforge.py --quick "concept"` | Skip review phase, faster but no quality check |
| `python storyforge.py --resume 7` | Resume drafting from chapter 7 (recovery mode) |
| `python storyforge.py --benchmark` | Benchmark all 3 Kimi K2.6 variants on prose quality |
| `python storyforge.py --project-dir /path/to/output` | Override the output directory location |
| `python storyforge.py --help` | Show all options |

---

## Output Structure

After the pipeline finishes, your novel lives here:

```
~/storyforge-projects/the-great-novel/
+-- manuscript.md              # The whole thing, ready to read
+-- project.json               # Metadata (title, genre, chapter count)
+-- spec.json                  # Your seed concept analysis
+-- world.json                 # The world bible
+-- characters.json            # All character profiles
+-- outline.json               # Chapter outlines with plot beats
+-- foreshadows.json           # Foreshadow tracker state (6-state machine)
+-- embeddings.db              # SQLite embedding store (semantic chapter retrieval)
+-- canonical_state.json       # Canonical state store (character traits, world facts, plot threads)
+-- chapters/
|   +-- chapter-001.md         # Chapter 1
|   +-- chapter-002.md         # Chapter 2
|   +-- ...
+-- manuscript.pdf             # Only if Pandoc + LaTeX is installed
+-- manuscript.epub            # Only if Pandoc is installed
```

---

## Story structures

The outline phase supports 5 different plot frameworks:

| Structure | Description |
|---|---|
| Three-Act | Classic setup / confrontation / resolution |
| Hero's Journey | Monomyth: ordinary world through return |
| Save the Cat | Blake Snyder's 15-beat structure |
| Seven-Point | Dan Wells' hook-through-resolution |
| Freytag's Pyramid | Exposition through denouement |

Default is Three-Act. Change in `pipeline/outline.py` or pass a structure key.

---

## Changing the configuration

Everything is in `config.py`. You can change:

- **Which AI models to use** for each phase
- **Banned words list** (add your own pet peeves)
- **Chapter length** (default: 4000 words)
- **How many chapters** (default: 8-30)
- **Scoring thresholds** (what counts as "good enough")
- **Output directory** (default: ~/storyforge-projects/)
- **API endpoint** (point at any OpenAI-compatible API)

---

## Architecture

The novel-writer-harness has a modular pipeline design:

```
storyforge.py                     # CLI entry point
pipeline/
+-- api.py                        # CrofaiClient (httpx, retry, JSON repair)
+-- config.py                     # Model routing, scoring thresholds, phase config
+-- canonical_store.py            # ABC for canonical state (FileCanonicalStore by default)
+-- foreshadow_tracker.py         # 6-state foreshadow state machine + auto-detection
+-- embedding_store.py            # Semantic chapter retrieval via sentence-transformers + SQLite
+-- reio_compression.py           # Context compression for long novels
+-- genre.py / characters.py / worldbuilding.py / outline.py / draft.py / ...
```

The foreshadow tracker and embedding store are the two recently-added custom modules:

- **ForeshadowTracker** — manages every thread from proposal to resolution, injects structured context into each chapter's prompt, auto-scans for spontaneous foreshadowing
- **EmbeddingStore** — replaces BM25 keyword search with semantic embedding retrieval for contextually-aware chapter drafting

---

## Origins

This tool is a combinatorial fork of ideas from these open-source projects:

- **autonovel** (NousResearch) - Pipeline architecture, dual immune system, Opus review loop
- **AI_NovelGenerator** (YILING0013) - State tracking inspiration
- **gemini-writer** (Doriandarko) - 1M context auto-compression, recovery mode
- **storycraftr** (raestrada) - Provider-agnostic config, embeddings context
- **ai-book-writer** (adamwlarson) - Multi-agent collaboration via AutoGen
- **NovelGenerator** (KazKozDev) - Parallel perspective tracking, emotional arcs
- **libriscribe** (guerra2fernando) - Multi-model support, fact-checking
- **NovelWriter** (EdwardAThomson) - Genre templates, story structures, quality analytics
- **book-generator** (wesleyscholl) - Pandoc/LaTeX export, KDP-ready output

The writing benchmark methodology comes from [lechmazur/writing](https://github.com/lechmazur/writing) - the most comprehensive LLM prose quality benchmark available.

The foreshadowing engine and semantic embedding retrieval were built from scratch, inspired by patterns in MuMuAINovel's foreshadow tracking system.

---

## License

MIT

# Novel Writer Harness

**Write a complete novel by typing one sentence.** The Novel Writer Harness takes a story concept and autonomously generates a full novel -- from worldbuilding and characters through to a complete manuscript -- with a multi-phase pipeline that iteratively improves quality.

A mashup of ideas from 9+ open-source AI writing projects (autonovel, Postwriter, StoryWriter, Novel OS, and others), tuned to route different tasks to the models best suited for them.

---

## v0.2 What's New

| Feature | What it does |
|---|---|
| **Revision loop** | Drafts below 6.0/10 auto-revise up to 3 rounds. Each round scores, identifies specific mechanical issues, and sends targeted fix instructions to the LLM. Only accepts revisions that improve the score. |
| **Parallel variants** | Each chapter drafts 2-3 versions with distinct style profiles (lyrical, compressed, standard). Each variant is scored mechanically; the best-scoring variant advances. |
| **RAG context retrieval** | BM25 semantic search over past chapter summaries replaces the naive last-N window. When drafting chapter 12, the model gets the 3 most *relevant* prior chapters, not just chapters 9-11. |
| **Backward propagation** | After all chapters are drafted, scans for character trait drift (blonde -> brown hair), timeline regression (night -> morning -> night), unresolved plot threads, and foreshadowing debt. Generates revision instructions per chapter. |
| **Adversarial editing** | Two passes: an LLM identifies 15% cuts classified by type (filler, redundancies, weak verbs, purple prose), then a mechanical pass tightens the remaining text. |
| **Dual-persona review** | Literary Critic + Professor of Fiction each score and critique the full manuscript, then debate their findings to produce a consolidated revision roadmap. |
| **Token tracking** | Cost estimates tracked per chapter and phase. |
| **42 unit tests** | Covers scoring, BM25 retrieval, revision prompt generation, backpropagation, adversarial editing, config, timeline regression, plot thread detection, foreshadowing, and more. |

---

## What it does

Give it a seed concept like:

> "A detective in a city where memories are currency solves a murder by accessing the victim's final memories, only to discover the killer is someone who erased themselves from everyone's mind."

And it will:

1. **Analyze** your concept into a structured project plan (genre, tone, POV, chapter count)
2. **Build a world** -- geography, history, factions, magic/tech systems
3. **Create characters** -- 6-7 characters with motivations, flaws, secrets, and growth arcs
4. **Outline the plot** -- chapter-by-chapter with key events, emotional arcs, and foreshadowing
5. **Draft each chapter** -- with parallel style variants, RAG context, and a revision loop that iteratively improves low-scoring chapters
6. **Backward propagate** -- scans every chapter for contradictions, drift, and unresolved threads; generates targeted revision instructions
7. **Adversarially edit** -- cuts 15% from weak spots, tightens prose mechanically
8. **Review** -- two LLM critics (Literary Critic + Professor of Fiction) score, critique, and debate
9. **Export** -- full manuscript as markdown, plus PDF/epub if you have Pandoc installed

---

## How it uses different AI models

| Phase | Model | Why |
|---|---|---|
| Planning (world, outline) | DeepSeek V4 Pro | Large context for expansive worldbuilding |
| Character creation | Kimi K2.6 | Prose-optimized, nuanced character profiles |
| Chapter drafting | Kimi K2.6 Precision | Best writing quality for long-form fiction |
| Mechanical scoring | Built-in (no API call) | Regex-based -- instant, zero cost |
| Revision (LLM pass) | Kimi K2.6 Precision | Fixes specific mechanical issues identified by scoring |
| Backward propagation | Built-in (no API call) | Pattern matching -- detects contradictions without LLM |
| Adversarial editing | Kimi K2.6 Precision | Identifies and classifies cuts per chapter |
| Literary critique | Kimi K2.6 | Dual-persona review (Critic + Professor) |

Configured for the crofai API (ai.nahcrof.com/v1). Change any model in `config.py`.

---

## Quick Start

### 1. Requirements

- Python 3.11+
- An API key for crofai (set as `CROFAI_API_KEY` environment variable)
- `pip install httpx` (the only dependency)
- Optional: `pandoc` + LaTeX for PDF/epub export

### 2. Install

```bash
pip install httpx
export CROFAI_API_KEY="your-api-key-here"
```

### 3. Write a novel

```bash
python storyforge.py "A detective in a city where memories are currency..."
```

That's it. Output lands at `~/storyforge-projects/{novel-title}/`.

### 4. Benchmark (optional)

```bash
python storyforge.py --benchmark
```

Tests Kimi K2.6 variants on 5 writing prompts, pairwise comparison. Tells you which writes best on *your* API endpoint.

---

## Command Reference

| Command | What it does |
|---|---|
| `python storyforge.py "concept"` | Full pipeline: seed through export |
| `python storyforge.py --quick "concept"` | Skip review phase, faster but no quality check |
| `python storyforge.py --resume 7 "concept"` | Resume drafting from chapter 7 |
| `python storyforge.py --no-variants "concept"` | Disable parallel scene variants (faster, cheaper) |
| `python storyforge.py --no-revision "concept"` | Disable revision loop (single-pass drafting) |
| `python storyforge.py --benchmark` | Benchmark model variants on prose quality |
| `python storyforge.py --project-dir /path` | Override output directory |
| `python storyforge.py --help` | Show all options |

---

## Output Structure

```
~/storyforge-projects/the-great-novel/
  manuscript.md              # Full novel, ready to read
  project.json               # Metadata (title, genre, chapter count)
  spec.json                  # Seed concept analysis
  world.json                 # World bible
  characters.json            # Character profiles
  outline.json               # Chapter-by-chapter outline
  chapters/
    chapter-001.md           # Each chapter (with variant and revision metadata)
    chapter-002.md
    ...
    chapter-NNN.md
  backpropagation.json       # Detected contradictions, drift, threads (v0.2)
  revision-plan.json         # Per-chapter revision instructions (v0.2)
  manuscript.pdf             # Only if Pandoc + LaTeX installed
  manuscript.epub            # Only if Pandoc installed
```

---

## How the quality scoring works

**Mechanical score** (built-in, zero-cost, runs in microseconds):
- Checks banned overused words (suddenly, very, gaze, smirk, literally, etc.)
- Measures tell-don't-show patterns (felt that, knew that, realized that)
- Analyzes sentence length variance (good pacing = varied sentence lengths)
- Scores 0-10, starts at 7.0, applies penalties

**LLM critique** (dual-persona, deep analysis):
- Literary Critic: scores prose craft, pacing, character depth, dialogue, structure
- Professor of Fiction: scores thematic coherence, narrative ambition, subtext
- They debate. Their consolidated output is a scored review with prioritized revision notes.

Thresholds: minimum pass at 6.0/10. Target 8.0/10. Chapters below 6.0 enter the revision loop.

---

## How the revision loop works

```
Draft chapter -> mechanical score
  |
  +-- score >= 6.0? --> done, accept
  |
  +-- score < 6.0? --> generate revision prompt (targeted mechanical fixes)
       |
       +-- send to LLM with style profile
       |
       +-- re-score revision
       |
       +-- score improved? --> accept, loop again (up to 3 rounds max)
       |
       +-- score not improved? --> keep original, break
```

Only accepts revisions that measurably improve the mechanical score. No regressions.

---

## How backward propagation works

After all chapters are drafted, scans for issues the forward pass can't catch:

1. **Character trait drift** -- regex pattern matching across chapters (hair color, eye color, height descriptors)
2. **Timeline regression** -- temporal keyword ordering: night -> morning -> afternoon -> evening, detects reversals
3. **Plot thread closure** -- checks outline for thread introductions in early chapters, verified existence in later chapters
4. **Foreshadowing debt** -- outline promises (hints, setups) vs actual payoff in later chapters

Outputs per-chapter revision instructions that feed into the adversarial editing pass.

---

## How parallel variants work

Each chapter drafts 2-3 versions with distinct style profiles:

| Profile | Register | Best for |
|---|---|---|
| Lyrical | Image-driven, metaphor-rich, unhurried | Literary fiction, emotional climaxes |
| Compressed | Tight sentences, dialogue-forward, minimal exposition | Thriller, action, crime |
| Standard | Balanced, genre-flexible | Default -- all-purpose narrative |

Each variant is mechanically scored. The highest-scoring variant advances. If tied, the standard variant wins.

---

## Changing the configuration

Everything in `config.py`. You can change:

- Which AI models for each phase
- Banned words list (add your own pet peeves)
- Chapter length (default: 4000 words)
- Chapter count range (default: 8-30)
- Scoring thresholds (min pass, target)
- Parallel variant count (default: 2, max: 3)
- Max revision rounds (default: 3)
- Output directory
- API endpoint (point at any OpenAI-compatible API)

---

## Story structures

| Structure | Description |
|---|---|
| Three-Act | Classic setup / confrontation / resolution |
| Hero's Journey | Monomyth: ordinary world through return |
| Save the Cat | Blake Snyder's 15-beat structure |
| Seven-Point | Dan Wells' hook-through-resolution |
| Freytag's Pyramid | Exposition through denouement |

Default: Three-Act. Change in `pipeline/outline.py` or pass a structure key.

---

## Recovery mode

If the pipeline gets interrupted (network issue, rate limit, closed laptop):

```bash
python storyforge.py --resume 7 "original seed concept"
```

Picks up where it left off. Previous chapters stay as they were.

---

## Running tests

```bash
pip install pytest
pytest tests/ -v
```

42 tests covering: scoring mechanics, BM25 retrieval, revision prompt generation, backpropagation (character traits, timeline, plot threads, foreshadowing), adversarial editing (mechanical tighten, cut categories, cut patterns), and config.

---

## Origins

- **autonovel** (NousResearch) -- Pipeline architecture, dual immune system, Opus review
- **Postwriter** (avigold) -- Parallel variants, structured state, backward propagation design
- **StoryWriter** (arxiv 2506.16445) -- ReIO compression, multi-agent drafting
- **AI_NovelGenerator** (YILING0013) -- State tracking, foreshadowing management
- **gemini-writer** (Doriandarko) -- 1M context auto-compression, recovery mode
- **storycraftr** (raestrada) -- Provider-agnostic config, embeddings context
- **ai-book-writer** (adamwlarson) -- Multi-agent collaboration via AutoGen
- **NovelGenerator** (KazKozDev) -- Parallel perspective tracking, emotional arcs
- **libriscribe** (guerra2fernando) -- Multi-model support, fact-checking
- **NovelWriter** (EdwardAThomson) -- Genre templates, story structures, quality analytics
- **book-generator** (wesleyscholl) -- Pandoc/LaTeX export, KDP-ready output

Benchmark methodology from [lechmazur/writing](https://github.com/lechmazur/writing).

---

## License

MIT

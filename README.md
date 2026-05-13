# Novel Writer Harness

**Write a complete novel by typing one sentence.** The Novel Writer Harness takes a story concept and autonomously generates a full novel -- from worldbuilding and characters through to a complete manuscript. It routes different writing tasks to the AI models best suited for each job.

A mashup of ideas from 11+ open-source AI writing projects (Postwriter, autonovel, StoryWriter, Novel OS, and others) combined into a single pipeline that iteratively improves quality as it writes.

---

## Quick Start

### Requirements

- Python 3.11+
- An API key from crofai (set as `CROFAI_API_KEY` environment variable)
- `pip install httpx` (the only dependency)
- Optional: `pandoc` + LaTeX for PDF/epub export

### Install

```bash
pip install httpx
export CROFAI_API_KEY="your-api-key-here"
```

### Interactive Interview Mode

Instead of a one-sentence seed, develop your story idea through a guided Q&A:

| Command | What it does |
|---|---|
| `python storyforge.py --interactive` | Quick interview (3 questions) |
| `python storyforge.py --interactive --depth standard` | Standard interview (24 questions) |
| `python storyforge.py --interactive --depth comprehensive` | Deep interview (73 questions, 6 dimensions) |
| `python storyforge.py --interactive --genre fantasy` | Genre-specific questions mixed in |

The interview walks through **6 novel dimensions**: Concept and Premise, World and Setting, Characters, Plot and Structure, Theme and Voice, and Market and Comparisons. Answers save every 5 questions. Press Ctrl+C to save progress.

Resume with:

```bash
python storyforge.py --resume ~/storyforge-projects/interview-my-idea/
```

### Write a novel

```bash
python storyforge.py "A detective in a city where memories are currency solves a murder by accessing the victim's final memories, only to discover the killer is someone who erased themselves from everyone's mind."
```

That's it. Output lands at `~/storyforge-projects/{novel-title}/`. The pipeline takes anywhere from 15 minutes to a few hours depending on the model speed and chapter count.

### Pick a genre (optional)

```bash
python storyforge.py "your concept" --genre mystery
```

Available genres: `mystery`, `thriller`, `romance`, `fantasy`, `sci-fi`. Each one comes with structured beat templates, required elements per chapter range, and tracking items that keep the pipeline honest about what it needs to manage.

---

## What it does

Give it a seed concept and it will:

1. **Analyze** your concept into a structured project plan (title, genre, tone, POV, chapter count)
2. **Build a world** -- geography, history, factions, magic/tech systems
3. **Create characters** -- 6-7 characters with motivations, flaws, secrets, and growth arcs
4. **Outline the plot** -- chapter-by-chapter with key events, emotional arcs, and foreshadowing
5. **Draft each chapter** -- with 4 rhetorical strategies, a revision loop, and persistent state tracking
6. **Backward propagate** -- scans every chapter for contradictions, drift, and unresolved threads; iterates until clean
7. **Adversarially edit** -- cuts weak spots and tightens prose mechanically
8. **Review** -- two LLM critics (Literary Critic + Professor of Fiction) score, critique, and debate each other
9. **Export** -- full manuscript as markdown, plus PDF/epub if Pandoc is installed

---

## v0.3.1: Quality Guardrails

Fixes that caught continuity errors in a 25-chapter test run and prevent them in future novels.

### Per-occurrence banned word penalty

The mechanical scorer previously counted *unique banned word types* (e.g., 106 instances of "very" = 1 type = -0.5 pts, easily ignored). It now counts **total occurrences** (106 * -0.5 = -5.0, capped). Chapters with heavy banned-word usage now reliably trigger the revision loop.

### Word count enforcement

The scorer now penalizes chapters below 60% of the config target (default: 4,000 words). Combined with the per-occurrence penalty, revision prompts now include specific word-expansion instructions when a chapter is too short.

### Character cast enforcement in drafts

The draft prompt now includes a `{character_cast}` section populated from `characters.json`, with the explicit instruction: "Character cast (only these characters exist in this story; do not invent new ones)." This prevents the LLM from introducing unregistered characters that contradict established profiles.

### Backstory consistency scan

A new fact-check scanner (`scan_backstory_consistency`) detects origin/backstory contradictions across chapters -- birthplace, refugee origin, "grew up in" city, etc. These are flagged at FAIL severity so they cannot be ignored.

### Character registry validation in outlines

After outline generation, every chapter POV and key-event reference is checked against the character registry. Unregistered characters generate a warning before drafting begins.

### Updated model routing

New model aliases added to `config.py`: `deepseek-v4-flash` (cheap reasoning, 1M context), `glm-5.1` (mid-tier reasoning, 169 t/s), and `qwen3.6-27b` (mid-tier reasoning upgrade). All existing routing unchanged -- new aliases available via `model_override`.

## v0.3: What's New

### Hindsight canonical state store

A structured memory system that tracks character traits, world facts, plot threads, and foreshadowing debts chapter by chapter. Before writing each chapter, the pipeline queries what it already knows. After writing, it pushes new state back. This prevents characters from changing eye color between chapters and plot threads from disappearing into the void.

Think of it as a story bible that writes itself as the novel progresses. No configuration needed -- it connects to Hindsight at localhost:8888 and creates a project-specific bank automatically.

### 4 rhetorical strategies (Postwriter-inspired)

Instead of just varying prose register (lyrical vs compressed), each chapter variant uses a distinct narrative approach:

| Strategy | How it works | Best for |
|---|---|---|
| Suspense-First | Withhold and reveal. Hook-driven, tight pacing. | Thrillers, mysteries, page-turners |
| Reveal-Late | Build context for 60-70%, then deliver a recontextualizing reveal | Literary fiction, emotional climaxes |
| Sensory-Immersion | Lead with physical experience. Cinematic, spare dialogue. | World-heavy genres, action scenes |
| Interiority-Forward | Free indirect discourse. Emotional truth over plot. | Character-driven drama |

Each chapter drafts 2-3 variants (configurable), each using a different strategy. The system mechanically scores every variant and selects the best one. The model doesn't just write differently -- it thinks about the chapter from a fundamentally different narrative angle.

### ReIO context compression (StoryWriter-inspired)

As chapters accumulate, raw context windows become too large. This module dynamically compresses earlier story context into compact forms:

- **Recent chapters** (last 3 by default): full summaries, high fidelity
- **Middle chapters** (next 5): condensed one-liners
- **Early chapters**: grouped into arc summaries
- **Critical state**: always preserved (character traits, active threads)

This solves a hard problem that was marked "NOT YET IMPLEMENTED" in the config. At chapter 20+, without compression, the model loses track of early story details. With ReIO, it maintains awareness of the full narrative arc at a fraction of the token cost.

### Iterative backward propagation

The old backpropagation ran once and generated a list of issues. The new version runs in a loop:

```
Scan chapters -> find contradictions -> generate revision instructions -> re-scan -> repeat
```

Up to 3 iterations by default. Detects when issues are the same as the previous round (stagnation) and stops early. Tracks convergence so you can see issue reduction per iteration. The status tells you whether it converged cleanly (PASS), has remaining WARN-level issues (STALLED), or has real errors that need manual attention (FAIL).

### Genre-specific beat templates

5 genre templates with structured beats mapped to chapter ranges:

| Genre | Phases | Recommended chapters | Tracking |
|---|---|---|---|
| Mystery | setup, investigation, middle_twist, pressure, resolution | 20 | clues, suspects, motives, timeline, alibis |
| Thriller | hook, escalation, midpoint_crisis, second_half_push, final_confrontation | 18 | tension_level, time_remaining, antagonist_moves |
| Romance | meet_cute, building_connection, first_obstacle, reconciliation, resolution | 20 | emotional_distance, trust_level, obstacles |
| Fantasy | ordinary_world, crossing_threshold, trials_and_allies, darkest_hour, final_quest | 24 | magic_system_rules, artifacts, prophecy |
| Sci-Fi | status_quo_dystopia, the_question, deeper_in, moral_turning, resolution_or_rebellion | 22 | technology_rules, knowledge_gaps, conspiracy_layers |

Each template defines required elements per phase (things that must appear in those chapters), tracking items (things the pipeline should watch across chapters), and structural metadata (tension arc, pacing profile). Select with `--genre mystery` on the command line.

---

### v0.2 Features

For reference, the earlier release:

| Feature | What it does |
|---|---|
| **Revision loop** | Chapters below 6.0/10 auto-revise up to 3 rounds. Each round identifies specific mechanical issues and sends targeted fix instructions to the LLM. Only accepts revisions that improve the score. No regressions allowed. |
| **RAG context retrieval** | BM25 semantic search over past chapter summaries replaces the naive last-N window. Chapter 12 gets the 3 most relevant prior chapters, not just chapters 9-11. |
| **Adversarial editing** | Two passes: an LLM identifies 15% cuts classified by type (filler, redundancies, weak verbs, purple prose), then a mechanical pass tightens the remaining text. |
| **Dual-persona review** | Literary Critic + Professor of Fiction each score and critique the full manuscript, then debate their findings to produce a consolidated revision roadmap. |
| **Token tracking** | Cost estimates tracked per chapter and phase. |
| **86 unit tests** | Covers every module: scoring, BM25 retrieval, revision prompt generation, backpropagation, adversarial editing, config, timeline regression, plot thread detection, foreshadowing, hindsight client, ReIO compression, iterative backprop, genre templates, rhetorical strategies, and more. |

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
| Hindsight state | Built-in (no API call) | Structured memory queries -- no LLM tokens |

Configured for the crofai API (ai.nahcrof.com/v1). Change any model in `config.py`.

---

## Command Reference

| Command | What it does |
|---|---|
| `python storyforge.py "concept"` | Full pipeline: seed through export |
| `python storyforge.py "concept" --genre mystery` | Use mystery beat template |
| `python storyforge.py --quick "concept"` | Skip review, backprop, and adversarial phases |
| `python storyforge.py --resume 7 "concept"` | Resume drafting from chapter 7 |
| `python storyforge.py --single-variant "concept"` | Draft 1 variant per chapter (cheaper) |
| `python storyforge.py --single-review "concept"` | Use single LLM review instead of dual-persona |
| `python storyforge.py --no-backprop "concept"` | Skip backward propagation scan |
| `python storyforge.py --no-adversarial "concept"` | Skip adversarial editing pass |
| `python storyforge.py --no-iterative-backprop "concept"` | Use one-shot backprop instead of iterative |
| `python storyforge.py --no-hindsight "concept"` | Disable canonical state store |
| `python storyforge.py --no-reio "concept"` | Disable ReIO context compression |
| `python storyforge.py --benchmark` | Benchmark model variants on prose quality |
| `python storyforge.py --project-dir /path "concept"` | Override output directory |
| `python storyforge.py --interactive` | Interactive interview mode (guided Q and A) |
| `python storyforge.py --interactive --depth comprehensive` | Deep interview (73 questions, 6 dimensions) |
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
    chapter-001.md           # Each chapter (with variant, revision metadata)
    chapter-002.md
    ...
    chapter-NNN.md
  backpropagation.json       # Detected contradictions, drift, threads (v0.3: iterative)
  backprop-revision-iter-1.json   # Per-iteration revision plans (v0.3)
  revision-plan.json         # Per-chapter revision instructions
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
       +-- send to LLM with current style profile
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

After all chapters are drafted, the iterative loop scans for issues the forward pass can't catch:

1. **Character trait drift** -- regex pattern matching across chapters (hair color, eye color, height descriptors)
2. **Timeline regression** -- temporal keyword ordering: night -> morning -> afternoon -> evening, detects reversals
3. **Plot thread closure** -- checks outline for thread introductions in early chapters, then verifies they appear in later chapters
4. **Foreshadowing debt** -- outline promises (hints, setups) vs actual payoff in later chapters

The iterative version runs up to 3 passes. If round 1 finds issues and generates fix instructions, round 2 re-scans to verify the fixes worked. If 80%+ of issues are unchanged between rounds, it detects stagnation and stops early. The final report tells you whether the manuscript converged cleanly or needs manual review.

---

## How Hindsight canonical state works

The HindsightStore connects to a structured memory server at localhost:8888. It creates a project-specific bank (e.g., `storyforge-the-great-novel`) and:

1. **Before each chapter draft**: queries for character traits, world facts, active plot threads, and foreshadowing elements relevant to the current chapter
2. **Formats results** into a prompt section the model can use during drafting
3. **After each chapter**: stores new character traits, world facts, thread progress, foreshadowing obligations, and contradictions detected
4. **Provides critical state** to the ReIO compressor so compressed context still includes durable facts

The result: the model knows what it established in chapter 3 while writing chapter 14. No drift, no forgotten subplots.

---

## How ReIO compression works

As chapters accumulate beyond the context window limit (900,000 tokens by default), raw summaries become too large. ReIO compresses them using a forgetting curve:

- Chapters within the last 3: full summaries (you need high fidelity for recent events)
- Chapters 4-8 back: condensed to 15-word one-liners (key events only)
- Chapters 9+: grouped into 3-chapter arc summaries (plot-level only)
- Critical state (character traits, active threads): always preserved at full fidelity

Each chapter's context section shows a token gauge: `[Context: ~45,000 tokens (5% of 900,000 budget)]` so you can see how much compression is buying you.

---

## Recovery mode

If the pipeline gets interrupted (network issue, rate limit, closed laptop):

```bash
python storyforge.py --resume 7 "original seed concept"
```

Or just run the same concept again -- the pipeline auto-detects checkpoint files and resumes from the next uncompleted phase.

```bash
python storyforge.py "same concept as before"
```

---

## Running tests

```bash
pip install pytest
pytest tests/ -v
```

105 tests covering (86 existing + 19 new interview tests): scoring mechanics, BM25 retrieval, revision prompt generation, backpropagation (character traits, timeline, plot threads, foreshadowing), adversarial editing (mechanical tighten, cut categories, cut patterns), hindsight client (HTTP mocking, bank management, recall, contradiction scanning), ReIO compression (compression tiers, arc summaries, empty state, token estimation), iterative backprop (convergence, iteration tracking, skipped state), genre templates (all 5 genres, beat lookup, required elements, tracking items, critical items), and rhetorical strategies (4 profiles with labeled strategies and pacing directives).

---

## Changing the configuration

Everything in `config.py`. You can change:

- Which AI models for each phase
- Banned words list (add your own pet peeves)
- Chapter length (default: 4000 words)
- Chapter count range (default: 8-30)
- Scoring thresholds (min pass: 6.0, target: 8.0)
- Parallel variant count (default: 2, max: 3)
- Max revision rounds (default: 3)
- Rhetorical strategy profiles (add your own)
- Output directory
- API endpoint (point at any OpenAI-compatible API)
- Token cost estimates per input/output token
- Hindsight host and port
- ReIO compression budget and fidelity tiers

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

## Origins

- **Postwriter** (avigold) -- Rhetorical strategies, structured state, backward propagation design
- **autonovel** (NousResearch) -- Pipeline architecture, dual immune system, Opus dual-persona review
- **StoryWriter** (arxiv 2506.16445) -- ReIO compression, multi-agent drafting
- **Hindsight** (NousResearch) -- Structured memory server, bank-based canonical state
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

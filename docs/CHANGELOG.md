# StoryForge changelog

Newest first. The README carries only the current version; this file carries all
of them. `config.VERSION` is the single source of the version string, and a
release tag must match it.

## v0.10 - an agent-drivable control surface (2026-11-01)

- `storyforge.py --doctor` prints one screenful of orientation: version, provider,
  resolved role routing with provenance, project state, the guard list, and the
  next command. `--json` gives the same report as data. Neither needs an API key,
  and neither touches the network unless you pass `--live`.
- Any model can hold any role. `LLM_MODEL_{ROLE}` takes a known alias or a raw
  provider model id, and `LLM_MODEL_{ROLE}_BASE_URL` points one role at a second
  provider. An override that is not an alias is honored and labeled `env-raw`
  instead of being silently dropped, and it is noted once on stderr.
- `Config.resolve_routing()` returns the whole plan as data and
  `print_routing_plan()` renders from it, which deleted three duplicated loops and
  put a provenance tag on every line.
- Guard tests: `test_model_routing_agnostic.py` (13), `test_model_literal_guard.py`
  (4), `test_doctor.py` (10), `test_agents_doc_drift.py` (6). The drift guard
  caught a file the architecture doc had invented.
- One version string: `config.VERSION`, read by the CLI banner, `--doctor` and this
  README. The banner said v0.3 while the README said v0.9.
- Test hygiene: `TestEnvVars` now snapshots every `LLM_*` and `CROFAI_*` variable
  instead of a hand-kept list. `LLM_MODEL_DRAFT=bogus` leaked into later tests, a
  bug the new raw-id contract exposed.
- Docs: `AGENTS.md` rewritten as the agent contract, `docs/ARCHITECTURE.md` added
  as the six-level tower, and the version history moved out of the README into this
  file.

## Earlier versions

### v0.9: No writer truncates the file it replaces

- **Every writer is atomic** — the v0.8 primitive now covers the whole tree: chapters, `spec.json`, `world.json`, `characters.json`, `outline.json`, `outline_validation.json`, `quality.json`, the review and backpropagation reports, the adversarial-edit result, the interview checkpoint and memory store, style profiles, revision plans, the API cache, `manuscript.md`, `project.json` and the EPUB. A crash, a full disk or a `kill -9` mid-write leaves the previous complete file where it was.
- **A guard keeps it that way** — `tests/test_atomic_write_coverage.py` scans every shipped `.py` for a direct truncating handle and fails the suite when one appears. Append-only logs are exempt by rule; anything else needs a `# atomic-exempt: <reason>` marker, and the reason is the point.
- **EPUB staged, then renamed** — the pure-Python builder writes `*.epub.part` beside its target and `os.replace`s it into place, so a failed build cannot overwrite the last good book.
- **The whole cast is listed** — *Dramatis Personae* in `manuscript.md` used to print the last character only. It prints all of them now.
- **A capped reference block says so** — `KnowledgeBase.get_references()` names what the token budget cut, inside the block and on `last_budget_dropped` / `last_budget_truncated`.

### v0.8: Durability and an offline smoke test

- **Atomic state writes** — `pipeline/state_io.py` writes canonical state and the foreshadow tracker through a temp file, an fsync and `os.replace`, so an interrupt cannot leave a half-written JSON behind.
- **Retry by error kind** — `pipeline/api.py` separates rate limits, network faults, parse faults and other faults, each with its own cap and jittered backoff. Auth faults still fail at once.
- **Name registry and roster hygiene** — `pipeline/naming.py` gives each character one canonical name, a separate title and a form of address. Draft and debate prompts carry the roster and end with "Never invent names that are not in the roster."
- **Hard length gate** — a chapter outside 75-135% of its target is redrawn from the same brief, up to twice. After the cap the best candidate is kept with a recorded warning. No silent padding.
- **Seed-phrase smoke test** — `python3 scripts/smoke.py "one sentence"` runs the whole pipeline offline against a deterministic stub provider. No API key, no network.

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

**Semantic rescue:** the `ctx_keywords` extracted from chapter content (title words + top-10 most-frequent content words) often use prose vocabulary that doesn't literally match a file's abstract frontmatter keywords. A `KEYWORD_SYNONYMS` map in `pipeline/knowledge_base.py` bridges the gap (e.g. `scar → {trait, physical, description}` so a chapter about "Mira's scar" surfaces `character-trait-tracking.md` instead of returning an empty reference). Without the rescue, ~29% of chapter critiques would have run with no writing-theory context; with it, that gap is closed without changing the agent's interface. See `reference/knowledge/README.md` for retrieval semantics and how to extend the synonym map.

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

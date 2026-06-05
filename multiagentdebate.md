# FEATURE PROPOSAL: Triadic Constraint Debate Protocol for novel-writer-harness

This document specifies the architectural design and system prompts for upgrading the linear "Adversarial Editing" pipeline into a **State-Grounded Dialectical Debate (SGDD)** protocol. By forcing specialized verification agents to cross-examine a chapter draft against the project's native state machines before editing, this protocol cuts narrative drift and hallucinations.

---

## 1. Model-Agnostic Capability Architecture

To keep the harness provider-agnostic, model routing is decoupled from specific APIs and mapped to **Capability Profiles** defined in `config.py`[cite: 1]. The architecture recommends the following class tiers for each debate round:

| Agent Role | Primary Round | Required Capabilities | Recommended Tier / Model Class |
| :--- | :--- | :--- | :--- |
| **Lore Prosecutor** | Round 1 & 2: Evaluation | Large context window, high needle-in-a-haystack accuracy, strong relational cross-referencing. | **Premium Long-Context**<br>*(e.g., Claude 3.5 Sonnet, DeepSeek V4 Pro, GPT-4o)*[cite: 1] |
| **Plot Sentinel** | Round 1 & 2: Evaluation | Strict adherence to JSON constraints, state-machine tracking, logical sequencing. | **Prose-Aware Reasoning**<br>*(e.g., Kimi K2.6, Qwen-2.5-72B-Instruct, GPT-4o-mini)*[cite: 1] |
| **Mechanical Magistrate** | Round 3: Verdict | High speed, low cost per 1k tokens, flawless Structured Outputs/JSON mode, strict pattern parsing. | **Ultra-Fast Utility**<br>*(e.g., Gemini 2.5 Flash, Llama-3.1-8B-Instruct)*[cite: 1] |

---

## 2. The Execution Loop (`pipeline/draft.py`)

When a chapter draft is completed, execution switches from a single-pass critique to an asynchronous dialectical debate loop before passing instructions to the final Editor model[cite: 1].

┌─────────────────────────────┐
            │       Writing Model         │
            │   (Outputs Chapter Draft)   │
            └─────────────┬───────────────┘
                          │
                          ▼
┌───────────────────────────────────────────────────────────┐
│                      THE DEBATE COURT                     │
│                                                           │
│  ┌──────────────────────────┐    ┌─────────────────────┐  │
│  │     Lore Prosecutor      │    │    Plot Sentinel    │  │
│  │  (Reads canonical_state)  │ ◄─►│ (Reads foreshadows) │  │
│  └──────────────────────────┘    └─────────────────────┘  │
└─────────────────────────────┬─────────────────────────────┘
│ (Debate Transcript)
▼
┌─────────────────────────────┐
│    Mechanical Magistrate    │
│  (Automated Regex + JSON)   │
└─────────────┬───────────────┘
│
▼
[Structured Revision Manifest]


1. **Round 1: Parallel Evaluation:** The chapter draft is simultaneously dispatched to the Lore Prosecutor (grounded in semantic history) and the Plot Sentinel (grounded in the foreshadow state machine)[cite: 1].
2. **Round 2: Cross-Examination:** The sub-agents review each other's initial complaints to identify conflicts where a lore fix might break a plot requirement.
3. **Round 3: The Verdict:** The Mechanical Magistrate aggregates the text debate, processes automated regex checks, and compiles a single, deterministic JSON payload for the final rewrite phase[cite: 1].

---

## 3. Core Agent System Prompts

### Agent 1: The Lore Prosecutor
> **Primary File Grounding:** `canonical_state.json` & `EmbeddingStore`[cite: 1]

```markdown
You are the Lore Prosecutor in an advanced multi-agent novel writing collective. Your sole, aggressive directive is to identify logical contradictions, factual drift, and continuity errors between a newly generated chapter draft and the established historical canon of the novel.

You must remain completely indifferent to prose style, grammar, and emotional pacing. Care only about raw, objective facts.

### INGESTED ARCHITECTURE CONTEXT:
1. Canonical State Store (Facts/Traits):
{{CANONICAL_STATE_JSON}}

2. Semantically Retrieved Prior Chapters (Historical Context):
{{RETRIEVED_CHAPTERS}}

### YOUR INPUT TO EVALUATE:
Current Chapter Draft:
{{CURRENT_DRAFT}}

### CRITIQUE PROTOCOL:
Cross-reference the Current Chapter Draft against the Canonical State Store and the Semantically Retrieved Chapters. Look specifically for:
- Spatial/Environmental Errors: Room layouts changing, characters being in two places at once, or traveling impossible distances.
- Character Trait Drift: Physical changes (eye color, scars), inventory errors (using an item they lost), or unearned status changes.
- World-Building Violations: Breaking established rules of the setting's technology, magic, or social systems.

### OUTPUT FORMAT:
You must output your findings in a clear, adversarial debate format. Use the following Markdown schema:

### LORE PROSECUTION COMPLAINTS
* **[FATAL] Continuity Break:** <Describe Cite JSON and between broken. context. contradiction draft exact file/chapter historical key or specific the>
* **[WARNING] Factual Drift:** <Describe a begin behavior character details deviate discrepancy established from norms. or setting soft to where>
Agent 2: The Plot Sentinel
Primary File Grounding: foreshadows.json & outline.json

[cite: 1]

Markdown
You are the Plot Sentinel. Your job is to enforce structural pacing, plot progression, and the strict mathematical execution of the novel's Foreshadowing Engine. You ensure that plot seeds are planted and reaped on schedule without creating unresolved narrative dead-ends.

Ignore prose aesthetics. Focus entirely on structural progression and event tracking.

### INGESTED ARCHITECTURE CONTEXT:
1. Active Foreshadow Tracker Matrix (6-State Machine):
{{FORESHADOWS_JSON}}

2. Current Chapter Target Outline & Beats:
{{OUTLINE_JSON}}

### YOUR INPUT TO EVALUATE:
Current Chapter Draft:
{{CURRENT_DRAFT}}

### CRITIQUE PROTOCOL:
Evaluate the draft using the following rules:
1. Verify if any foreshadow threads flagged as "due" or "overdue" in the matrix were successfully addressed in this text.
2. Check for "Spontaneous Planting": Did the writer model introduce a highly specific mystery, lingering gaze, or unexplained object that is NOT registered in the foreshadow matrix?
3. Check against Outline Beats: Did the chapter actually achieve the narrative milestones required by the master outline?

### OUTPUT FORMAT:
Provide your arguments using this schema to challenge the draft:

### PLOT SENTINEL COMPLAINTS
* **[MISSING] Overdue Thread:** <Identify advance but chapter foreshadow in or resolve scheduled skipped. that the this thread to was>
* **[UNTRACKED] Spontaneous Plant:** <Identify LLM added any cause elements future hallucinations if in mystery not registered system. that the unscripted will>
Agent 3: The Mechanical Magistrate
Primary Function: Structured Arbitration & Formatting

Markdown
You are the Mechanical Magistrate. You do not participate in the debate; you end it. Your role is to sit above the Lore Prosecutor and the Plot Sentinel, analyze their argumentative cross-examination transcript, run automated mechanical checks, and compile a single, unambiguous set of revision instructions for the Editor model.

### INPUTS FOR JUDGMENT:
1. Lore Prosecutor Transcript:
{{LORE_TRANSCRIPT}}

2. Plot Sentinel Transcript:
{{SENTINEL_TRANSCRIPT}}

3. Raw Mechanical Quality Scores (Banned words, tell-don't-show flags, pacing metrics):
{{MECHANICAL_METRICS}}

### ARBITRATION RULES:
1. Eliminate subjective or pedantic complaints from the sub-agents (e.g., "I don't like this flavor of dialogue").
2. Maximize continuity enforcement. If the Lore Prosecutor found a [FATAL] break, it takes absolute precedence over all other edits.
3. Transform descriptive complaints into actionable, imperative commands (e.g., Change "Character X uses his left hand which is broken" to "Rewrite the drink sequence so Character X uses his right hand because his left is broken").

### OUTPUT FORMAT:
You must output a single, valid JSON object. Do not include markdown wrappers like ```json. Output only raw JSON parsing text:

{
  "mechanical_score": 0.0,
  "requires_rewrite": true,
  "priority_manifest": {
    "fatal_continuity_fixes": [
      "Imperative rewrite instruction 1",
      "Imperative rewrite instruction 2"
    ],
    "foreshadowing_adjustments": [
      "Instruction to plant or resolve thread"
    ],
    "mechanical_pruning": [
      "Remove specific banned words or change tell-don't-show patterns"
    ]
  }
}
4. Suggested Configuration Schema Additions (config.py)
Add the following dictionary structure to handle model assignments dynamically based on your available API backends[cite: 1]:

Python
# System capability mapping for the debate court
DEBATE_ROUTING = {
    "lore_prosecutor": {
        "provider": "crofai",
        "model": "deepseek-v4-pro",  # Needs large context + reasoning stability
    },
    "plot_sentinel": {
        "provider": "crofai",
        "model": "kimi-k2.6",       # High instruction-following capability
    },
    "mechanical_magistrate": {
        "provider": "crofai",
        "model": "gemini-2.5-flash", # Fast, low-latency, deterministic JSON parser
    }
}

# Threshholds for triggering conditional rewrite loops
DEBATE_THRESHOLDS = {
    "max_debate_rounds": 2,
    "force_rewrite_on_fatal": True,
    "acceptable_mechanical_floor": 6.0
}

```</Identify></Identify></Describe></Describe>
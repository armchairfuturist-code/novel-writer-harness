"""Triadic Constraint Debate Protocol (SGDD) — state-grounded dialectical
debate for chapter continuity verification.

Three agents cross-examine a chapter draft against canonical state:
1. **Lore Prosecutor** — grounded in canonical_state.json, checks
   character traits, world facts, and continuity for drift/breaks.
2. **Plot Sentinel** — grounded in foreshadowing state machine + outline
   beats, checks structural pacing and plot-thread execution.
3. **Mechanical Magistrate** — aggregates both transcripts + mechanical
   scores, resolves conflicts, outputs a deterministic revision manifest.

Design:
- Runs per-chapter in the draft revision loop, BEFORE existing revision.
- When debate returns `requires_rewrite: true`, the priority_manifest
  feeds into the revision prompt instead of generic mechanical critique.
- Integrates with Config.debate for model routing and thresholds.
"""

import textwrap
from collections import Counter
from typing import Optional

import os
import re

from config import Config
from pipeline.api import CrofaiClient, parse_json_output
from pipeline.canonical_store import CanonicalStore


# ── Agent System Prompts ─────────────────────────────────────────────

LORE_PROSECUTOR_SYSTEM = textwrap.dedent("""\
You are the **Lore Prosecutor** in an advanced multi-agent novel writing collective.
Your sole, aggressive directive is to identify logical contradictions, factual drift,
and continuity errors between a newly generated chapter draft and the established
historical canon of the novel.

You remain completely indifferent to prose style, grammar, and emotional pacing.
Care only about raw, objective facts.

### CRITIQUE PROTOCOL:
Cross-reference the Current Chapter Draft against the Canonical State and the
Previously Established Context. Look specifically for:

1. **Spatial/Environmental Errors:** Room layouts changing, characters being in
   two places at once, or traveling impossible distances.
2. **Character Trait Drift:** Physical changes (eye color, scars), inventory errors
   (using an item they lost), or unearned status changes.
3. **World-Building Violations:** Breaking established rules of the setting's
   technology, magic, or social systems.
4. **Continuity Breaks:** Events referenced out of order, dead characters appearing,
   or timeline impossibilities.

### OUTPUT FORMAT:
Return a single valid JSON object (no markdown wrappers). Fields:

{
  "complaints": [
    {
      "severity": "FATAL" | "WARNING",
      "category": "spatial" | "trait_drift" | "world_violation" | "timeline" | "continuity",
      "element": "What specific trait/fact/location is affected",
      "established": "What canon says (cite the evidence provided)",
      "violation": "What the draft says that conflicts",
      "suggested_fix": "Concrete rewrite instruction to resolve the conflict"
    }
  ],
  "continuity_score": 0-10,
  "summary": "One-sentence overall verdict"
}
""")

LORE_PROSECUTOR_PROMPT = """Evaluate this chapter draft for continuity errors against the canonical record.

### CANONICAL STATE (ESTABLISHED FACTS):
{canonical_context}

### PREVIOUSLY ESTABLISHED CONTEXT:
{retrieved_context}

{reference_context}
### CURRENT CHAPTER DRAFT TO EVALUATE:
Chapter {chapter_num}: {chapter_title}

{chapter_text}

Return the JSON object with complaints, continuity_score, and summary."""


PLOT_SENTINEL_SYSTEM = textwrap.dedent("""\
You are the **Plot Sentinel**. Your job is to enforce structural pacing, plot
progression, and the strict execution of the novel's Foreshadowing Engine.
You ensure that plot seeds are planted and reaped on schedule without creating
unresolved narrative dead-ends.

Ignore prose aesthetics. Focus entirely on structural progression and event tracking.

### CRITIQUE PROTOCOL:
Evaluate the draft using the following rules:

1. **Overdue Threads:** Verify if any foreshadow threads flagged as "due" or
   "overdue" in the matrix were successfully addressed in this text.
2. **Spontaneous Planting:** Did the writer model introduce a highly specific
   mystery, lingering gaze, or unexplained object that is NOT registered in the
   foreshadow matrix? These cause future hallucinations.
3. **Outline Beat Compliance:** Did the chapter actually achieve the narrative
   milestones required by the master outline for this chapter?
4. **Pacing Violations:** Does the chapter spend disproportionate space on
   a minor beat while rushing a critical plot point?

### OUTPUT FORMAT:
Return a single valid JSON object (no markdown wrappers). Fields:

{
  "complaints": [
    {
      "severity": "FATAL" | "WARNING" | "MISSING",
      "category": "overdue_thread" | "spontaneous_plant" | "missed_beat" | "pacing_violation",
      "element": "The thread/beat/element name",
      "detail": "What was expected vs. what the draft delivered",
      "suggested_fix": "Concrete rewrite instruction"
    }
  ],
  "structural_score": 0-10,
  "summary": "One-sentence overall verdict"
}
""")

PLOT_SENTINEL_PROMPT = """Evaluate this chapter draft for structural and plot integrity.

### ACTIVE FORESHADOW TRACKER (DUE / OVERDUE):
{foreshadowing_context}

### CHAPTER OUTLINE BEATS:
{outline_beats}

{reference_context}
### CURRENT CHAPTER DRAFT TO EVALUATE:
Chapter {chapter_num}: {chapter_title}

{chapter_text}

Return the JSON object with complaints, structural_score, and summary."""


MAGISTRATE_SYSTEM = textwrap.dedent("""\
You are the **Mechanical Magistrate**. You do not participate in the debate;
you end it. Your role is to sit above the Lore Prosecutor and the Plot Sentinel,
analyze their argumentative cross-examination transcripts, run automated mechanical
checks, and compile a single, unambiguous set of revision instructions for the
Editor model.

### ARBITRATION RULES:
1. **Eliminate subjective or pedantic complaints** from the sub-agents
   (e.g., "I don't like this flavor of dialogue" — discard it).
2. **Maximize continuity enforcement.** If the Lore Prosecutor found a [FATAL]
   break, it takes absolute precedence over all other edits.
3. **Deduplicate overlapping complaints.** If both agents flag the same issue
   from different angles, merge into one instruction.
4. **Transform descriptive complaints into actionable, imperative commands.**
   Bad: "Character X uses his left hand which is broken."
   Good: "Rewrite the drink sequence so Character X uses his right hand
   because his left was broken in Ch 3."
5. **Set requires_rewrite to true** when any FATAL exists OR when the combined
   issue count exceeds 3 WARNINGs.

### OUTPUT FORMAT:
Return a single, valid JSON object. Do NOT include markdown wrappers like ```json.
Output only raw JSON:

{
  "mechanical_score": 0.0,
  "requires_rewrite": true,
  "continuity_score": 0.0,
  "structural_score": 0.0,
  "fatal_count": 0,
  "warning_count": 0,
  "priority_manifest": {
    "fatal_continuity_fixes": [
      "Imperative rewrite instruction 1",
      "Imperative rewrite instruction 2"
    ],
    "foreshadowing_adjustments": [
      "Instruction to plant or resolve thread"
    ],
    "structural_fixes": [
      "Instruction to realign with outline beats"
    ],
    "mechanical_pruning": [
      "Remove specific banned words or fix tell-don't-show patterns"
    ]
  },
  "summary": "One-sentence arbitration verdict"
}
""")

MAGISTRATE_PROMPT = """Render a verdict on Chapter {chapter_num}: "{chapter_title}".

### LORE PROSECUTOR TRANSCRIPT:
{lore_transcript}

### PLOT SENTINEL TRANSCRIPT:
{sentinel_transcript}

### RAW MECHANICAL QUALITY SCORES:
{mechanical_metrics}

{declared_changes_context}

### CHAPTER TEXT (for reference):
{chapter_text}

Synthesize into a single revision manifest JSON. If any FATAL exists, requires_rewrite
must be true. Return only raw JSON, no markdown wrappers."""


# ── Cross-Examination Prompts ────────────────────────────────────────

LORE_CROSS_EXAM_PROMPT = """READ THE PLOT SENTINEL'S COMPLAINTS BELOW. They may conflict with your
continuity findings. Address each of their complaints:

- If their suggested fix would CREATE a continuity error, flag it as a CONFLICT
  and explain why.
- If you agree with their finding, mark it as CONCUR and optionally strengthen it.
- If their finding is irrelevant to continuity, mark it as OUT_OF_SCOPE.

### YOUR ORIGINAL COMPLAINTS:
{lore_complaints}

### PLOT SENTINEL'S COMPLAINTS:
{sentinel_complaints}

Return JSON:
{
  "conflicts": [
    {{
      "sentinel_complaint": "brief description",
      "conflict_type": "CONFLICT" | "CONCUR" | "OUT_OF_SCOPE",
      "resolution": "How the editor should resolve this"
    }}
  ],
  "amended_complaints": [ ... your original complaints, potentially amended ... ]
}"""

PLOT_CROSS_EXAM_PROMPT = """READ THE LORE PROSECUTOR'S COMPLAINTS BELOW. They may identify
structural issues you need to account for. Address each of their complaints:

- If their fix would BREAK the outline structure or foreshadowing plan, flag it
  as a CONFLICT and explain the structural consequence.
- If you agree, mark as CONCUR and optionally strengthen.
- If their finding is about prose/world detail only, mark as OUT_OF_SCOPE.

### YOUR ORIGINAL COMPLAINTS:
{sentinel_complaints}

### LORE PROSECUTOR'S COMPLAINTS:
{lore_complaints}

Return JSON:
{
  "conflicts": [
    {{
      "prosecutor_complaint": "brief description",
      "conflict_type": "CONFLICT" | "CONCUR" | "OUT_OF_SCOPE",
      "resolution": "How the editor should resolve this"
    }}
  ],
  "amended_complaints": [ ... your original complaints, potentially amended ... ]
}"""


# ── Debate Orchestrator ──────────────────────────────────────────────

def _call_agent(
    client: CrofaiClient,
    model,
    system_prompt: str,
    user_prompt: str,
    label: str = "agent",
) -> dict:
    """Call a single debate agent and parse JSON output."""
    try:
        content = client.chat_with_retry(
            model,
            messages=[{"role": "user", "content": user_prompt}],
            system_prompt=system_prompt,
            temperature=0.3,  # Low temperature for deterministic evaluation
        )
        return parse_json_output(content, label=label)
    except Exception as e:
        return {"_error": str(e), "complaints": [], "summary": f"Agent error: {e}"}


def _format_canonical_context(store: CanonicalStore) -> str:
    """Build a canonical state summary for the Lore Prosecutor."""
    parts = []

    traits = store.recall("character", k=10, tag_filter=["character_trait"])
    if traits:
        parts.append("CHARACTER TRAITS:")
        for t in traits[:10]:
            parts.append(f"  - {t.get('content', '')[:150]}")
        parts.append("")

    world = store.get_world_facts()
    if world:
        parts.append("WORLD FACTS:")
        for w in world[:6]:
            parts.append(f"  - {w.get('content', '')[:150]}")
        parts.append("")

    threads = store.get_active_threads()
    if threads:
        parts.append("ACTIVE PLOT THREADS:")
        for th in threads[:5]:
            parts.append(f"  - {th.get('content', '')[:150]}")
        parts.append("")

    chapters = store.get_chapter_summaries()
    if chapters:
        parts.append("PRIOR CHAPTER CONTEXT:")
        for ch in chapters[:5]:
            parts.append(f"  - {ch.get('content', '')[:200]}")
        parts.append("")

    return "\n".join(parts) if parts else "[No canonical state available]"


def _format_foreshadowing_context(store: CanonicalStore) -> str:
    """Build a foreshadowing state summary for the Plot Sentinel."""
    parts = []

    # Due/overdue debts
    debts = store.get_foreshadowing_debts()
    if debts:
        parts.append("DUE / OVERDUE THREADS (must be addressed now):")
        for d in debts:
            parts.append(f"  - {d.get('content', '')[:150]}")
        parts.append("")
    else:
        parts.append("DUE / OVERDUE THREADS: None")
        parts.append("")

    # All foreshadowing elements for context
    planted = store.get_foreshadowing_by_status("planted")
    hinted = store.get_foreshadowing_by_status("hinted")
    reinforced = store.get_foreshadowing_by_status("reinforced")
    paid = store.get_foreshadowing_by_status("paid")

    all_active = planted + hinted + reinforced
    if all_active:
        parts.append("ALL ACTIVE FORESHADOW ELEMENTS:")
        for f in all_active[:10]:
            parts.append(f"  - {f.get('content', '')[:150]}")
        parts.append("")

    if paid:
        parts.append("PAID / RESOLVED:")
        for p in paid[:5]:
            parts.append(f"  - {p.get('content', '')[:150]}")
        parts.append("")

    return "\n".join(parts) if parts else "[No foreshadowing state available]"


def _format_outline_beats(outline: dict, chapter_num: int) -> str:
    """Extract relevant outline beats for the current chapter."""
    beats = []
    acts = outline.get("acts", [])
    for act in acts:
        for ch in act.get("chapters", []):
            ch_num = ch.get("chapter", 0)
            if ch_num == chapter_num:
                beats.append(f"Chapter {ch_num}: {ch.get('title', '')}")
                beats.append(f"  Summary: {ch.get('summary', '')[:300]}")
                key_events = ch.get("key_events", [])
                if key_events:
                    beats.append(f"  Key Events: {', '.join(key_events)}")
                required = ch.get("required_elements", [])
                if required:
                    beats.append(f"  Required Elements: {', '.join(required)}")
                genre_phase = ch.get("genre_phase", "")
                if genre_phase:
                    beats.append(f"  Genre Phase: {genre_phase}")
                beats.append("")
            elif abs(ch_num - chapter_num) <= 1:
                # Adjacent chapters for context
                beats.append(f"Chapter {ch_num} ({'before' if ch_num < chapter_num else 'after'}): {ch.get('title', '')} — {ch.get('summary', '')[:120]}")
                beats.append("")

    return "\n".join(beats) if beats else "[No outline beats available for this chapter]"


def _format_mechanical_metrics(score: dict) -> str:
    """Format ChapterScorer output for the Magistrate."""
    return (
        f"Mechanical Score: {score.get('total_score', 0)}/10\n"
        f"Word Count: {score.get('word_count', 0)}\n"
        f"Banned Words Found: {score.get('banned_words_found', {})}\n"
        f"Tell Ratio: {score.get('tell_ratio', 0):.2f} (target < 0.30)\n"
        f"Pacing Variance: {score.get('pacing_variance', 0):.1f} (target > 5.0)\n"
        f"Dialogue Ratio: {score.get('dialogue_ratio', 0):.3f}"
    )


def _build_revision_prompt_from_manifest(
    chapter_text: str,
    manifest: dict,
    chapter_title: str,
) -> str:
    """Build a revision prompt from the Magistrate's priority_manifest.

    This replaces the generic mechanical critique with canon-grounded
    revision instructions.
    """
    parts = [
        f"Revise Chapter: \"{chapter_title}\"",
        "",
        "The Debate Court found the following issues. Fix ALL of them.",
        "",
    ]

    fatal_fixes = manifest.get("fatal_continuity_fixes", [])
    if fatal_fixes:
        parts.append("## FATAL CONTINUITY BREAKS (fix first):")
        for i, fix in enumerate(fatal_fixes, 1):
            parts.append(f"{i}. {fix}")
        parts.append("")

    foreshadowing_fixes = manifest.get("foreshadowing_adjustments", [])
    if foreshadowing_fixes:
        parts.append("## FORESHADOWING ADJUSTMENTS:")
        for i, fix in enumerate(foreshadowing_fixes, 1):
            parts.append(f"{i}. {fix}")
        parts.append("")

    structural_fixes = manifest.get("structural_fixes", [])
    if structural_fixes:
        parts.append("## STRUCTURAL FIXES:")
        for i, fix in enumerate(structural_fixes, 1):
            parts.append(f"{i}. {fix}")
        parts.append("")

    mechanical_fixes = manifest.get("mechanical_pruning", [])
    if mechanical_fixes:
        parts.append("## MECHANICAL PRUNING:")
        for i, fix in enumerate(mechanical_fixes, 1):
            parts.append(f"{i}. {fix}")
        parts.append("")

    parts.append("Preserve the chapter's voice, POV, and narrative arc.")
    parts.append("")
    parts.append("--- CHAPTER TEXT ---")
    parts.append(chapter_text)

    return "\n".join(parts)


def _render_reference(kb, agent_role: str, keywords: list[str]) -> str:
    """Render knowledge base references for a debate agent, or empty string."""
    if kb is None or not keywords:
        return ""
    try:
        return kb.get_references(agent_role, keywords, max_tokens=500)
    except Exception:
        return ""


# ── Public Entry Point ───────────────────────────────────────────────

def run_debate(
    chapter_text: str,
    chapter_num: int,
    chapter_title: str,
    canonical_store: CanonicalStore,
    outline: dict,
    mechanical_score: dict,
    config: Optional[Config] = None,
    enable_cross_exam: bool = True,
    declared_changes: Optional[dict] = None,
    enable_knowledge_base: bool = True,
    knowledge_base_dir: Optional[str] = None,
) -> dict:
    """Run the Triadic Constraint Debate Protocol on a chapter draft.

    Args:
        chapter_text: The full chapter draft text.
        chapter_num: Chapter number (1-based).
        chapter_title: Chapter title.
        canonical_store: CanonicalStore for ground-truth state.
        outline: Full outline dict (acts → chapters).
        mechanical_score: ChapterScorer output dict.
        config: Config override.
        enable_cross_exam: If True, run Round 2 cross-examination.
        declared_changes: Optional structured change declarations from the
            drafting LLM. When present, the Magistrate can cross-validate
            the LLM's own state claims against continuity complaints.
        enable_knowledge_base: If True, inject writing theory references
            into agent prompts from reference/knowledge/ directory.
        knowledge_base_dir: Path to knowledge base directory (default:
            reference/knowledge/ relative to project root).

    Returns:
        Dict with keys:
        - requires_rewrite: bool
        - priority_manifest: dict (revision instructions)
        - fatal_count: int
        - warning_count: int
        - debate_transcript: str (human-readable summary)
        - lore_complaints: list
        - sentinel_complaints: list
        - revision_prompt: str or None (ready-to-use revision prompt)
    """
    config = config or Config()
    client = CrofaiClient(config)

    # ── Round 1: Parallel Evaluation ──────────────────────────────────
    lore_model = config.model_for_debate("lore_prosecutor")
    sentinel_model = config.model_for_debate("plot_sentinel")

    canonical_context = _format_canonical_context(canonical_store)
    retrieved_context = _format_canonical_context(canonical_store)  # same for now; could use BM25
    foreshadowing_context = _format_foreshadowing_context(canonical_store)
    outline_beats = _format_outline_beats(outline, chapter_num)

    # ── Knowledge Base: resolve role-specific references ──────────
    reference_context = ""
    ctx_keywords = []
    if enable_knowledge_base:
        try:
            from pipeline.knowledge_base import KnowledgeBase
            kb_dir = knowledge_base_dir or os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                "reference", "knowledge",
            )
            kb = KnowledgeBase(kb_dir)
            # Build keyword list from chapter context
            if chapter_title:
                ctx_keywords.extend(chapter_title.lower().split())
            if chapter_text:
                # Grab the most frequent significant words
                words = re.findall(r'\b[a-z]{4,}\b', chapter_text[:1000].lower())
                ctx_keywords.extend([w for w, _ in Counter(words).most_common(10)])
        except Exception:
            kb = None
    else:
        kb = None

    lore_result = _call_agent(
        client, lore_model, LORE_PROSECUTOR_SYSTEM,
        LORE_PROSECUTOR_PROMPT.format(
            canonical_context=canonical_context,
            retrieved_context=retrieved_context,
            reference_context=_render_reference(kb, "lore_prosecutor", ctx_keywords) if kb else "",
            chapter_num=chapter_num,
            chapter_title=chapter_title,
            chapter_text=chapter_text,
        ),
        label="lore_prosecutor",
    )

    sentinel_result = _call_agent(
        client, sentinel_model, PLOT_SENTINEL_SYSTEM,
        PLOT_SENTINEL_PROMPT.format(
            foreshadowing_context=foreshadowing_context,
            outline_beats=outline_beats,
            reference_context=_render_reference(kb, "plot_sentinel", ctx_keywords) if kb else "",
            chapter_num=chapter_num,
            chapter_title=chapter_title,
            chapter_text=chapter_text,
        ),
        label="plot_sentinel",
    )

    # ── Round 2: Cross-Examination (optional) ────────────────────────
    max_cross_rounds = config.debate.max_debate_rounds
    for round_num in range(max_cross_rounds if enable_cross_exam else 0):
        lore_complaints_raw = lore_result.get("complaints", [])
        sentinel_complaints_raw = sentinel_result.get("complaints", [])

        # Lore cross-examines Sentinel
        if sentinel_complaints_raw:
            lore_cross = _call_agent(
                client, lore_model, LORE_PROSECUTOR_SYSTEM,
                LORE_CROSS_EXAM_PROMPT.format(
                    lore_complaints=repr(lore_complaints_raw),
                    sentinel_complaints=repr(sentinel_complaints_raw),
                ),
                label=f"lore_cross_exam_r{round_num + 1}",
            )
            if "amended_complaints" in lore_cross:
                lore_result["complaints"] = lore_cross["amended_complaints"]
            lore_result.setdefault("cross_exam_conflicts", []).extend(
                lore_cross.get("conflicts", [])
            )

        # Sentinel cross-examines Lore
        if lore_complaints_raw:
            sentinel_cross = _call_agent(
                client, sentinel_model, PLOT_SENTINEL_SYSTEM,
                PLOT_CROSS_EXAM_PROMPT.format(
                    sentinel_complaints=repr(sentinel_complaints_raw),
                    lore_complaints=repr(lore_complaints_raw),
                ),
                label=f"sentinel_cross_exam_r{round_num + 1}",
            )
            if "amended_complaints" in sentinel_cross:
                sentinel_result["complaints"] = sentinel_cross["amended_complaints"]
            sentinel_result.setdefault("cross_exam_conflicts", []).extend(
                sentinel_cross.get("conflicts", [])
            )

    # ── Round 3: Magistrate Verdict ──────────────────────────────────
    magistrate_model = config.model_for_debate("mechanical_magistrate")
    mechanical_metrics = _format_mechanical_metrics(mechanical_score)

    # Format declared changes for cross-validation
    from pipeline.changes import format_changes_for_magistrate
    declared_changes_context = format_changes_for_magistrate(declared_changes or {})

    magistrate_result = _call_agent(
        client, magistrate_model, MAGISTRATE_SYSTEM,
        MAGISTRATE_PROMPT.format(
            chapter_num=chapter_num,
            chapter_title=chapter_title,
            lore_transcript=repr(lore_result),
            sentinel_transcript=repr(sentinel_result),
            mechanical_metrics=mechanical_metrics,
            declared_changes_context=declared_changes_context,
            chapter_text=chapter_text[:3000],  # Truncate for context
        ),
        label="mechanical_magistrate",
    )

    client.close()

    # ── Build return value ───────────────────────────────────────────
    requires_rewrite = magistrate_result.get("requires_rewrite", False)
    fatal_count = magistrate_result.get("fatal_count", 0)
    warning_count = magistrate_result.get("warning_count", 0)

    # Force rewrite on FATAL if configured
    if config.debate.force_rewrite_on_fatal and fatal_count > 0:
        requires_rewrite = True

    manifest = magistrate_result.get("priority_manifest", {})

    # Build a ready-to-use revision prompt
    revision_prompt = None
    if requires_rewrite and manifest:
        revision_prompt = _build_revision_prompt_from_manifest(
            chapter_text, manifest, chapter_title,
        )

    # Build human-readable transcript
    transcript_lines = [
        "=== DEBATE COURT VERDICT ===",
        f"Chapter {chapter_num}: {chapter_title}",
        f"Continuity Score: {magistrate_result.get('continuity_score', 'N/A')}",
        f"Structural Score: {magistrate_result.get('structural_score', 'N/A')}",
        f"Mechanical Score: {mechanical_score.get('total_score', 0)}/10",
        f"Fatal Issues: {fatal_count}",
        f"Warnings: {warning_count}",
        f"Rewrite Required: {requires_rewrite}",
        "",
        magistrate_result.get("summary", "No summary"),
    ]

    return {
        "requires_rewrite": requires_rewrite,
        "priority_manifest": manifest,
        "fatal_count": fatal_count,
        "warning_count": warning_count,
        "debate_transcript": "\n".join(transcript_lines),
        "lore_complaints": lore_result.get("complaints", []),
        "sentinel_complaints": sentinel_result.get("complaints", []),
        "magistrate_verdict": magistrate_result,
        "revision_prompt": revision_prompt,
    }

"""Draft phase - generate chapters with revision loop, parallel variants, and RAG context.

Key improvements over v0.1:
- Revision loop: score < threshold -> revise with LLM critique -> re-score (up to 3 rounds)
- Parallel variants: draft 2-3 versions with distinct style profiles, score each, keep best
- RAG context retrieval: semantic embedding store replaces naive last-N window
- Token tracking: estimates tokens per chapter/phase for cost visibility
"""

import json
import os
import re
import time
from typing import Optional

from config import Config
from pipeline.api import CrofaiClient
from pipeline.canonical_store import CanonicalStore, FileCanonicalStore, create_canonical_store
from pipeline.embedding_store import EmbeddingStore
from pipeline.foreshadow_tracker import ForeshadowTracker, ForeshadowElement
from pipeline.reio_compression import ReIOCompressor


# Style profiles for parallel variant generation
# Postwriter-inspired rhetorical strategies — each variant uses a distinct
# narrative approach rather than just a different prose register.
STYLE_PROFILES = {
    "suspense_first": """RHETORICAL STRATEGY: SUSPENSE-FIRST
Structure this chapter around withholding and revelation. Open with a question or tension.
Dole out information in controlled releases. End each scene with a hook that demands
the reader continue. Use short chapters, cliffhangers, and dramatic irony (reader knows
more than the character, or vice versa). Prioritize 'what happens next' over 'what does it mean.'
Pacing: tight. Scene length: short to medium. Tension: escalating.""",

    "reveal_late": """RHETORICAL STRATEGY: REVEAL-LATE
Structure this chapter around a single significant reveal. Spend the first 60-70% building
context, deepening character, and planting details that will retroactively gain meaning.
The last 30-40% delivers the reveal — an action, a piece of information, a character choice
that recontextualizes everything that came before. The reader should want to immediately
re-read the chapter. Pacing: deliberate. Scene length: longer. Tension: slow build to spike.""",

    "sensory_immersion": """RHETORICAL STRATEGY: SENSORY-IMMERSION
Structure this chapter around the physical experience of being in this world.
Lead with sensory detail — what the POV character sees, hears, smells, tastes, feels.
Minimal interior monologue. Let the world and action convey meaning through physical sensation.
Dialogue is spare and grounded in physical action. Think cinematic — every paragraph could be
a shot. Pacing: variable, driven by sensory density. Scene length: varied. Tension: ambient.""",

    "interiority_forward": """RHETORICAL STRATEGY: INTERIORITY-FORWARD
Structure this chapter around the POV character's internal experience.
Free indirect discourse. The narrative voice merges with the character's thoughts.
Prioritize emotional truth over plot progression. Filter events through how the character
experiences, interprets, and is changed by them. Use recollection, anticipation, and
emotional resonance. Dialogue reveals inner conflict more than plot information.
Pacing: reflective. Scene length: longer. Tension: emotional.""",
}

DEFAULT_STYLE_PROFILES = [
    ("suspense_first", STYLE_PROFILES["suspense_first"]),
    ("reveal_late", STYLE_PROFILES["reveal_late"]),
    ("sensory_immersion", STYLE_PROFILES["sensory_immersion"]),
    ("interiority_forward", STYLE_PROFILES["interiority_forward"]),
]

DRAFT_SYSTEM_PROMPT = """You are an award-winning novelist writing a chapter of a book.
Write literary-quality prose that:

1. Shows, doesn't tell - use sensory detail, action, and dialogue
2. Maintains consistent POV - stay in the assigned character's perspective
3. Advances plot AND deepens character in every scene
4. Uses distinctive voice per POV character
5. Avoids cliches, banned words, and lazy construction
6. Varies sentence length for rhythm and pacing
7. Creates tension on every page - even in quiet moments

Write 3000-5000 words per chapter unless specified otherwise.
Do NOT summarize. Do NOT use meta-commentary. Write the actual story."""

REVISION_SYSTEM_PROMPT = """You are a revision specialist. Your job is to revise a chapter
based on specific editorial feedback. Keep what works, fix what doesn't. Do not rewrite from
scratch - preserve voice and intent while addressing every criticism.

Write 3000-5000 words. Maintain the same POV and tone.

After the revised chapter body, append a structured change declaration block
(---CHANGES--- ... ---END CHANGES---) listing what state transitions occurred in this revision.
Use empty lists [] for categories with no changes."""

CHAPTER_DRAFT_TEMPLATE = """Write Chapter {chapter_number}: {chapter_title}

POV: {pov_character}

Chapter context from outline:
{chapter_summary}

Key events to cover:
{key_events}

Emotional arc for this chapter: {emotional_arc}

Foreshadowing to plant: {foreshadowing}

Character arc beat: {character_arc_beat}

World context / setting: {world_context}

{hindsight_canonical_state}

Relevant context from earlier chapters (retrieved by relevance):
{retrieved_context}

{foreshadow_context}

Style direction: {style_direction}

Write the chapter now. Focus on craft: sensory immersion, pacing, dialogue rhythm,
interiority. Make every sentence earn its place.

After the chapter body, append a structured change declaration block
using the format below. List ONLY things that actually changed in this chapter.
Empty categories should be empty lists [].

---CHANGES---
{{
  "character_status": [{{"character":"Name","change_type":"level_up/gained_ability/lost_ability/mental_state/key_event/relationship","detail":"Specific change","chapter":{chapter_number}}}]],
  "conflict_progress": [{{"conflict_id":"conflict name","new_status":"status","event":"what advanced"}}],
  "plot_nodes": [{{"keyword":"event keyword","summary":"one line","characters":["involved"],"story_line":"main/sub"}}],
  "foreshadowing_actions": [{{"element":"element name","action":"setup/payoff","detail":"what happened"}}],
  "location_changes": [{{"location":"name","new_state":"state","event":"cause"}}],
  "faction_changes": [{{"faction":"name","new_state":"state","event":"cause"}}],
  "time_advancement": [{{"time_period":"period","elapsed":"duration","events":["event"]}}],
  "character_movement": [{{"character":"Name","from_location":"origin","to_location":"destination"}}],
  "item_transfers": [{{"item":"name","from_holder":"origin","to_holder":"destination","state":"condition"}}],
  "secret_reveals": [{{"secret_id":"name","new_knowers":["who"],"method":"how revealed"}}],
  "oath_changes": [{{"oath_id":"name","action":"made/broken/fulfilled","characters":["involved"],"constraints":"terms"}}],
  "deadline_changes": [{{"deadline_id":"name","action":"set/advanced/expired","trigger":"condition","time_remaining":"duration"}}]
}}
---END CHANGES---"""


def _estimate_tokens(text: str) -> int:
    """Rough token estimate (~4 chars per token for English)."""
    return len(text) // 4


def _word_count(text: str) -> int:
    """Count words in text."""
    return len(text.split())


def _get_chapter_text(chapter_file: str) -> str:
    """Read chapter text, stripping the score header line."""
    try:
        with open(chapter_file, "r", encoding="utf-8") as f:
            content = f.read()
        # Strip the metadata header line (> POV: ... | Score: ...)
        lines = content.split("\n")
        filtered = [l for l in lines if not l.startswith("> POV:")]
        return "\n".join(filtered)
    except OSError:
        return ""


# ---------------------------------------------------------------------------
# Chapter Scorer (mechanical)
# ---------------------------------------------------------------------------

class ChapterScorer:
    """Mechanical scoring for chapter quality (autonovel-inspired immune system)."""

    def __init__(self, config: Optional[Config] = None):
        self.config = config or Config()
        self.banned_words = self.config.banned_words

    def score_chapter(self, text: str) -> dict:
        word_count = len(text.split())
        sentences = re.split(r'[.!?]+', text)
        sentences = [s.strip() for s in sentences if len(s.strip()) > 10]
        total_sentences = len(sentences)

        banned_found = {}
        text_lower = text.lower()
        for word in self.banned_words:
            count = len(re.findall(r'\b' + re.escape(word) + r'\b', text_lower))
            if count > 0:
                banned_found[word] = count

        banned_penalty = len(banned_found) * self.config.scoring.banned_word_penalty
        banned_penalty = max(banned_penalty, -5.0)

        tell_patterns = [
            r'\bfelt ', r'\bfelt that\b', r'\bknew that\b',
            r'\brealized that\b', r'\bthought that\b', r'\bwondered if\b',
            r'\bit was \w+ that\b', r'\bthere was\b', r'\bthere were\b',
        ]
        tell_count = 0
        for pat in tell_patterns:
            tell_count += len(re.findall(pat, text_lower))

        tell_ratio = tell_count / max(total_sentences, 1)

        sent_lengths = [len(s.split()) for s in sentences]
        avg_len = sum(sent_lengths) / max(len(sent_lengths), 1)
        variance = sum((l - avg_len) ** 2 for l in sent_lengths) / max(len(sent_lengths), 1)
        std_dev = variance ** 0.5

        pacing_score = min(std_dev / 10.0, 1.0)

        dialogue_lines = len(re.findall(r'["\u201c][^"\u201d]*["\u201d]', text))
        dialogue_ratio = dialogue_lines / max(word_count, 1)

        base_score = 7.0
        base_score += banned_penalty * 0.5
        if tell_ratio > self.config.scoring.show_dont_tell_threshold:
            base_score -= (tell_ratio - self.config.scoring.show_dont_tell_threshold) * 3
        base_score += pacing_score * 0.5
        base_score = max(0, min(10, base_score))

        return {
            "word_count": word_count,
            "banned_words_found": banned_found,
            "banned_penalty": round(banned_penalty, 2),
            "tell_ratio": round(tell_ratio, 3),
            "pacing_variance": round(std_dev, 1),
            "dialogue_ratio": round(dialogue_ratio, 4),
            "total_score": round(base_score, 1),
        }


# ---------------------------------------------------------------------------
# Parallel variant drafting
# ---------------------------------------------------------------------------

def _draft_single_variant(
    client: CrofaiClient,
    model,
    chapter_num: int,
    chapter_title: str,
    pov: str,
    summary: str,
    key_events: list,
    emotional_arc: str,
    foreshadowing: str,
    char_arc_beat: str,
    world_context: str,
    retrieved_context: str,
    foreshadow_context: str,
    style_direction: str,
    style_name: str,
    config: Config,
    scorer: ChapterScorer,
    chapter_spec: dict,
    hindsight_context: str = "",
    compressed_context: str = "",
    enable_changes: bool = True,
) -> dict:
    """Draft a single variant of a chapter and score it."""
    prompt = CHAPTER_DRAFT_TEMPLATE.format(
        chapter_number=chapter_num,
        chapter_title=chapter_title,
        pov_character=pov,
        chapter_summary=summary,
        key_events="\n".join(f"- {e}" for e in key_events) if key_events else "As outlined above.",
        emotional_arc=emotional_arc or "As outlined above.",
        foreshadowing=foreshadowing or "As outlined above.",
        character_arc_beat=char_arc_beat or "As outlined above.",
        world_context=world_context or "As established in world bible.",
        hindsight_canonical_state=hindsight_context or "[No additional canonical state available]",
        retrieved_context=retrieved_context,
        foreshadow_context=foreshadow_context,
        style_direction=style_direction,
    )

    content = client.chat_with_retry(
        model,
        messages=[{"role": "user", "content": prompt}],
        system_prompt=DRAFT_SYSTEM_PROMPT,
        temperature=0.8,
    )

    # Parse structured change declarations from LLM output
    declared_changes = None
    if enable_changes:
        from pipeline.changes import parse_changes_block
        content, declared_changes = parse_changes_block(content)

    score = scorer.score_chapter(content)

    return {
        "variant": style_name,
        "content": content,
        "score": score,
        "declared_changes": declared_changes,
    }


# ---------------------------------------------------------------------------
# Revision loop
# ---------------------------------------------------------------------------

def _generate_revision_prompt(
    chapter_text: str,
    mechanical_score: dict,
    style_name: str,
) -> str:
    """Generate a revision prompt from mechanical score weaknesses."""
    issues = []

    # Banned words
    if mechanical_score["banned_words_found"]:
        banned_list = ", ".join(
            f"'{w}' (x{c})" for w, c in mechanical_score["banned_words_found"].items()
        )
        issues.append(f"- Remove or replace banned/overused words: {banned_list}")

    # Tell ratio
    if mechanical_score["tell_ratio"] > 0.3:
        issues.append(
            f"- Show-don't-tell ratio is {mechanical_score['tell_ratio']:.2f} "
            f"(target < 0.30). Convert 'felt that', 'knew that', 'realized that' "
            f"into sensory action and dialogue."
        )

    # Pacing
    if mechanical_score["pacing_variance"] < 5.0:
        issues.append(
            f"- Sentence length variance is low ({mechanical_score['pacing_variance']:.1f}). "
            f"Vary sentence lengths more for rhythm. Mix short punchy sentences with longer flowing ones."
        )

    # Word count
    if mechanical_score["word_count"] < 2000:
        issues.append(
            f"- Chapter is short ({mechanical_score['word_count']} words). "
            f"Expand scenes with more sensory detail, interiority, and action."
        )

    if not issues:
        return ""

    prompt_parts = [
        f"Revise this chapter ({style_name} variant). The mechanical review found these issues:\n",
        *issues,
        "\nFix all issues while preserving the chapter's voice, POV, and narrative arc.",
        "\n--- CHAPTER TEXT ---\n",
        chapter_text,
    ]

    return "\n".join(prompt_parts)


def _run_revision_loop(
    client: CrofaiClient,
    model,
    chapter_text: str,
    scorer: ChapterScorer,
    style_name: str,
    max_rounds: int,
    config: Config,
    canonical_store: Optional[CanonicalStore] = None,
    chapter_num: int = 0,
    chapter_title: str = "",
    outline: Optional[dict] = None,
    enable_debate: bool = False,
    enable_changes: bool = True,
    enable_knowledge_base: bool = True,
) -> tuple[str, dict, int, Optional[dict]]:
    """Run revision loop: score -> revise -> re-score up to max_rounds.

    Args:
        chapter_text: Initial chapter draft
        max_rounds: Max revision iterations
        canonical_store: If set and enable_debate is True, runs the
            debate protocol before generating revision prompts.
        chapter_num / chapter_title / outline: Required for debate context.

    Returns:
        Tuple of (final_text, final_score_dict, revisions_done, declared_changes)
    """
    current_text = chapter_text
    current_score = scorer.score_chapter(current_text)
    threshold = config.scoring.min_chapter_score  # 6.0

    revisions_done = 0
    debate_ran = False
    declared_changes = None

    for round_num in range(max_rounds):
        if current_score["total_score"] >= threshold:
            break

        # ── Debate Protocol (runs once, before first revision) ──────
        if (
            enable_debate
            and not debate_ran
            and canonical_store is not None
            and outline is not None
            and current_score["total_score"] < config.debate.acceptable_mechanical_floor
        ):
            from pipeline.debate import run_debate

            print(f"      Debate Court: evaluating (score: {current_score['total_score']}/10)...")
            try:
                debate_result = run_debate(
                    chapter_text=current_text,
                    chapter_num=chapter_num,
                    chapter_title=chapter_title,
                    canonical_store=canonical_store,
                    outline=outline,
                    mechanical_score=current_score,
                    config=config,
                    enable_cross_exam=(config.debate.max_debate_rounds > 0),
                    declared_changes=declared_changes,
                    enable_knowledge_base=enable_knowledge_base,
                )
                debate_ran = True

                fatal_c = debate_result.get("fatal_count", 0)
                warn_c = debate_result.get("warning_count", 0)
                print(f"        Fatal: {fatal_c} | Warnings: {warn_c} | "
                      f"Rewrite: {debate_result['requires_rewrite']}")

                if debate_result.get("requires_rewrite") and debate_result.get("revision_prompt"):
                    revision_prompt = debate_result["revision_prompt"]
                    print(f"        Using debate revision manifest")
                else:
                    print(f"        Debate cleared — no rewrite needed")
                    break
            except Exception as e:
                print(f"        Debate failed: {e} — falling back to generic revision")
                debate_ran = True
                revision_prompt = _generate_revision_prompt(
                    current_text, current_score, style_name
                )
                if not revision_prompt:
                    break
        else:
            revision_prompt = _generate_revision_prompt(
                current_text, current_score, style_name
            )
            if not revision_prompt:
                break

        print(f"      Revision round {round_num + 1}/{max_rounds} (score: {current_score['total_score']}/10)...")

        try:
            revised = client.chat_with_retry(
                model,
                messages=[{"role": "user", "content": revision_prompt}],
                system_prompt=REVISION_SYSTEM_PROMPT,
                temperature=0.7,
            )

            # Parse changes from revised output
            if enable_changes:
                from pipeline.changes import parse_changes_block
                revised, rev_changes = parse_changes_block(revised)
                if rev_changes is not None:
                    declared_changes = rev_changes

            new_score = scorer.score_chapter(revised)

            # Only accept revision if score improves
            if new_score["total_score"] > current_score["total_score"]:
                current_text = revised
                current_score = new_score
                revisions_done += 1
                print(f"        Improved to {current_score['total_score']}/10")
            else:
                print(f"        No improvement ({new_score['total_score']}/10), keeping current version")
                break
        except RuntimeError as e:
            print(f"        Revision failed: {e}")
            break

    return current_text, current_score, revisions_done, declared_changes


# ---------------------------------------------------------------------------
# Main draft orchestrator
# ---------------------------------------------------------------------------

def run_draft(
    spec: dict,
    world: dict,
    characters: dict,
    outline: dict,
    project_dir: str,
    config: Optional[Config] = None,
    resume_from: int = 1,
    parallel_variants: bool = True,
    max_variants: int = 2,
    enable_revision: bool = True,
    canonical_store: Optional[CanonicalStore] = None,
    enable_debate: bool = False,
    enable_changes: bool = True,
    style_profile_name: Optional[str] = None,
    auto_style_extract: bool = False,
    enable_knowledge_base: bool = True,
) -> list[dict]:
    """Run the draft phase with revision loop and optional parallel variants.

    Args:
        spec: Project specification from seed phase
        world: World bible
        characters: Character profiles
        outline: Chapter-by-chapter outline
        project_dir: Output directory
        config: Config override
        resume_from: Chapter number to start from
        parallel_variants: If True, draft multiple style variants per chapter
        max_variants: Max variants to draft (out of 3 style profiles)
        enable_revision: If True, run revision loop on each chapter
        canonical_store: If set, enables canonical state tracking (debate + context)
        enable_debate: If True, run the Triadic Constraint Debate Protocol
            in the revision loop (requires canonical_store + outline)
        enable_changes: If True, require ---CHANGES--- declarations and
            apply them to the canonical store after each chapter
        style_profile_name: Named style profile to bind to all chapters.
            Overrides the rhetorical strategy direction.
        auto_style_extract: If True, extract and save a style profile
            after each chapter is written.

    Returns:
        List of chapter result dicts
    """
    config = config or Config()
    client = CrofaiClient(config)
    model = config.model_for_phase("draft")
    scorer = ChapterScorer(config)

    chapters_dir = os.path.join(project_dir, "chapters")
    os.makedirs(chapters_dir, exist_ok=True)

    acts = outline.get("acts", [])
    all_chapters = []
    for act in acts:
        for ch in act.get("chapters", []):
            all_chapters.append(ch)

    if not all_chapters:
        print("    WARNING: Outline has no chapters; skipping drafting phase")
        return []

    # Initialize semantic embedding store (replaces BM25)
    store = EmbeddingStore(os.path.join(project_dir, "embeddings.db"))
    # Prime the store with outline summaries for semantic retrieval
    all_chapter_meta = [
        {
            "chapter": i + 1,
            "title": ch.get("title", f"Chapter {i+1}"),
            "summary": ch.get("summary", ""),
            "pov": ch.get("pov", ""),
            "key_events": " ".join(ch.get("key_events", [])),
        }
        for i, ch in enumerate(all_chapters)
    ]
    total = len(all_chapters)
    results = []
    written_chapter_meta = []

    # Initialize foreshadow tracker (imports from outline on first run)
    foreshadow_tracker = ForeshadowTracker(os.path.join(project_dir, "foreshadow_state.json"))
    if foreshadow_tracker.active_count == 0:
        imported = foreshadow_tracker.import_from_outline(all_chapters)
        if imported:
            print(f"    Imported {imported} foreshadow threads from outline")
    foreshadow_tracker.save()

    # ── Style engine: load bound profile if specified ─────────────────
    bound_style_profile = None
    if style_profile_name:
        from pipeline.style_engine import load_style_profile, format_style_for_prompt
        bound_style_profile = load_style_profile(style_profile_name, project_dir)
        if bound_style_profile:
            print(f"    Bound style profile: {style_profile_name}")
        else:
            print(f"    WARNING: Style profile '{style_profile_name}' not found in styles/")

    # Initialize canonical state store (use passed-in store or create default)
    if canonical_store is not None:
        canonical = canonical_store
    else:
        canonical = create_canonical_store(backend="file", project_dir=project_dir)
    canonical.ensure_bank_safe()

    # Initialize ReIO compression
    reio = ReIOCompressor(
        token_budget=config.chapter.auto_compress_at_tokens,
        recent_chapters=config.chapter.context_carry_window,
    )

    # Token tracking
    total_input_tokens = 0
    total_output_tokens = 0
    total_revisions = 0
    total_variants_written = 0

    for idx, chapter_spec in enumerate(all_chapters):
        chapter_num = idx + 1

        if chapter_num < resume_from:
            continue

        chapter_title = chapter_spec.get("title", f"Chapter {chapter_num}")
        pov = chapter_spec.get("pov", "Unknown")
        summary = chapter_spec.get("summary", "")
        key_events = chapter_spec.get("key_events", [])
        emotional_arc = chapter_spec.get("emotional_arc", "")
        foreshadowing = chapter_spec.get("foreshadowing", "")
        char_arc_beat = chapter_spec.get("character_arc_beat", "")

        # --- Semantic Context Retrieval ---
        # Build query from this chapter's outline
        query = f"{summary} {emotional_arc} {pov} {' '.join(key_events) if isinstance(key_events, list) else key_events}"
        written_numbers = {r.get("chapter", 0) for r in written_chapter_meta}
        relevant_chapters = store.search(query, k=3, exclude=written_numbers if written_numbers else None)

        retrieved_context = ""
        if relevant_chapters:
            retrieved_lines = []
            for rc in relevant_chapters:
                retrieved_lines.append(
                    f"  - Ch {rc['chapter']}: {rc['content'][:200]} (relevance: {rc['score']:.2f})"
                )
            if retrieved_lines:
                retrieved_context = "Related story elements from across the narrative:\n" + "\n".join(retrieved_lines)

        # --- Foreshadow context ---
        foreshadow_context = foreshadow_tracker.format_context_for_prompt(chapter_num)

        # --- Context from previously written chapters (last N) ---
        window = config.chapter.context_carry_window
        context_buffer = written_chapter_meta[-window:] if written_chapter_meta else []
        if context_buffer:
            prev_summary_text = "\n".join(
                f"Ch {r['chapter']} ({r['title']}): {r.get('summary', '')[:200]}"
                for r in context_buffer
            )
        else:
            prev_summary_text = "Beginning of the story. No prior events."

        # --- World context ---
        world_context = ""
        if isinstance(world, dict):
            wc = world.get("central_conflict", "")
            mood = world.get("mood_setting", "")
            world_context = f"{wc[:200]}\n{mood[:200]}"

        # --- Hindsight canonical state ---
        hindsight_context = canonical.format_context_for_drafting(chapter_num, summary)

        # --- ReIO compressed narrative context ---
        compressed_context = ""
        if written_chapter_meta:
            compressed_context = reio.compress_for_chapter(
                chapter_num=chapter_num,
                total_chapters=len(written_chapter_meta),
                chapter_summaries=written_chapter_meta,
                arc_summaries=reio.build_arc_summaries(outline, written_chapter_meta)
                if written_chapter_meta else None,
                critical_state=hindsight_context if canonical.enabled else None,
            )

        print(f"  Drafting Chapter {chapter_num}/{total}: {chapter_title}...")
        print(f"    POV: {pov} | Model: {model.name}")

        # --- Draft variants (parallel or single) ---
        num_variants = max_variants if (parallel_variants and max_variants >= 2) else 1
        profiles_to_use = DEFAULT_STYLE_PROFILES[:num_variants]
        variants = []

        for si, (style_name, style_desc) in enumerate(profiles_to_use):
            if bound_style_profile is not None:
                from pipeline.style_engine import format_style_for_prompt
                style_desc = format_style_for_prompt(bound_style_profile)
            label = f"Variant {si + 1}/{len(profiles_to_use)}" if num_variants > 1 else "Drafting"
            print(f"    {label}: {style_name}...")
            variant_result = _draft_single_variant(
                client=client, model=model,
                chapter_num=chapter_num, chapter_title=chapter_title,
                pov=pov, summary=summary, key_events=key_events,
                emotional_arc=emotional_arc, foreshadowing=foreshadowing,
                char_arc_beat=char_arc_beat, world_context=world_context,
                retrieved_context=retrieved_context,
                foreshadow_context=foreshadow_context,
                style_direction=style_desc, style_name=style_name,
                config=config, scorer=scorer, chapter_spec=chapter_spec,
                hindsight_context=hindsight_context,
                compressed_context=compressed_context,
                enable_changes=enable_changes,
            )
            total_input_tokens += _estimate_tokens(
                CHAPTER_DRAFT_TEMPLATE.format(
                    chapter_number=chapter_num, chapter_title=chapter_title,
                    pov_character=pov, chapter_summary=summary,
                    key_events="\n".join(f"- {e}" for e in key_events) if key_events else "",
                    emotional_arc=emotional_arc or "", foreshadowing=foreshadowing or "",
                    character_arc_beat=char_arc_beat or "", world_context=world_context or "",
                    retrieved_context=retrieved_context,
                    foreshadow_context=foreshadow_context,
                    hindsight_canonical_state=hindsight_context or "[No additional canonical state available]",
                    style_direction=style_desc,
                )
            )
            total_output_tokens += _estimate_tokens(variant_result["content"])
            total_variants_written += 1

            if enable_revision:
                revised_text, revised_score, rev_done, changes = _run_revision_loop(
                    client=client, model=model,
                    chapter_text=variant_result["content"],
                    scorer=scorer, style_name=style_name,
                    max_rounds=config.scoring.max_revision_rounds,
                    config=config, canonical_store=canonical,
                    chapter_num=chapter_num, chapter_title=chapter_title,
                    outline=outline, enable_debate=enable_debate,
                    enable_changes=enable_changes,
                    enable_knowledge_base=enable_knowledge_base,
                )
                variant_result["content"] = revised_text
                variant_result["score"] = revised_score
                variant_result["revisions"] = rev_done
                if changes is not None:
                    variant_result["declared_changes"] = changes
                total_revisions += rev_done
            else:
                variant_result["revisions"] = 0

            variants.append(variant_result)
            print(f"      Score: {variant_result['score']['total_score']}/10 | "
                  f"{variant_result['score']['word_count']} words | "
                  f"{variant_result['revisions']} revisions")

        # Select best variant
        variants.sort(key=lambda v: -v["score"]["total_score"])
        best = variants[0]
        best_content = best["content"]
        best_score = best["score"]
        best_style = best["variant"]

        if num_variants > 1:
            print(f"    Selected: {best_style} (score: {best_score['total_score']}/10)")

        # Save chapter
        chapter_file = os.path.join(chapters_dir, f"chapter-{chapter_num:03d}.md")
        with open(chapter_file, "w", encoding="utf-8") as f:
            f.write(f"# Chapter {chapter_num}: {chapter_title}\n\n")
            f.write(f"> POV: {pov} | Style: {best_style} | Score: {best_score['total_score']}/10\n\n")
            f.write(best_content)

        chapter_result = {
            "chapter": chapter_num,
            "title": chapter_title,
            "pov": pov,
            "file": chapter_file,
            "score": best_score,
            "summary": summary,
            "word_count": best_score["word_count"],
            "style": best_style,
        }
        results.append(chapter_result)
        written_chapter_meta.append(chapter_result)

        # ── Apply canonical state updates (changes-based or fallback) ─
        chapter_changes = best.get("declared_changes") if enable_changes else None

        if chapter_changes is not None:
            from pipeline.changes import apply_changes_to_store, changes_to_summary_line
            change_count = apply_changes_to_store(chapter_changes, canonical, chapter_num)
            summary_line = changes_to_summary_line(chapter_changes)
            print(f"    Changes: {summary_line} ({change_count} store updates)")
        else:
            # Fallback: traditional passive state extraction
            canonical.update_after_chapter(
                chapter_num=chapter_num,
                title=chapter_title,
                summary=summary,
                pov=pov,
                word_count=best_score["word_count"],
                key_events=key_events if isinstance(key_events, list) else [key_events],
                foreshadowing_elements=[(foreshadowing, chapter_num + 3)]
                if foreshadowing else None,
            )

        # Update foreshadow tracker with chapter content
        chapter_text = best_content
        hits = foreshadow_tracker.scan_chapter_text(chapter_text)
        if hits:
            auto_ids = foreshadow_tracker.auto_propose_from_scan(chapter_num, hits)
            if auto_ids:
                print(f"      Auto-detected {len(auto_ids)} foreshadow signals")
        foreshadow_tracker.save()

        # Index chapter content for semantic retrieval
        store.remove_chapter(chapter_num)
        store.add(chapter_num, summary, section="summary")
        if best_content:
            store.add(chapter_num, best_content[:2000], section="chapter_text")

        print(f"    Final: Score {best_score['total_score']}/10 | {best_score['word_count']} words | "
              f"Style: {best_style}")

        # ── Auto-extract style profile after chapter save ──────────
        if auto_style_extract and best_content:
            from pipeline.style_engine import extract_style, save_style_profile
            try:
                ch_profile = extract_style(best_content, chapter_num, name=f"chapter-{chapter_num:03d}")
                saved_path = save_style_profile(ch_profile, project_dir)
                print(f"    Style extracted: {saved_path}")
            except Exception as e:
                print(f"    Style extraction skipped: {e}")

    client.close()
    store.close()
    foreshadow_tracker.save_if_dirty()

    # Print token usage summary
    total_cost_estimate = total_input_tokens * 0.000002 + total_output_tokens * 0.000010  # rough
    print(f"\n  --- Token Usage Summary ---")
    print(f"  Input tokens (estimated): {total_input_tokens:,}")
    print(f"  Output tokens (estimated): {total_output_tokens:,}")
    print(f"  Total variants written: {total_variants_written}")
    print(f"  Total revision rounds: {total_revisions}")
    print(f"  Estimated cost: ${total_cost_estimate:.4f}")

    return results

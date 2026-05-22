"""Draft phase - generate chapters with revision loop, parallel variants, and RAG context.

Key improvements over v0.1:
- Revision loop: score < threshold -> revise with LLM critique -> re-score (up to 3 rounds)
- Parallel variants: draft 2-3 versions with distinct style profiles, score each, keep best
- RAG context retrieval: BM25-based semantic retrieval replaces naive last-N window
- Token tracking: estimates tokens per chapter/phase for cost visibility
"""

import json
import math
import os
import re
import time
from collections import Counter
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

DEFAULT_STYLE_PROFILES = ["suspense_first", "reveal_late", "sensory_immersion", "interiority_forward"]

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

Write 3000-5000 words. Maintain the same POV and tone."""

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
interiority. Make every sentence earn its place."""


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
# Lightweight BM25 Retriever (no external dependencies)
# ---------------------------------------------------------------------------

class BM25Retriever:
    """Pure-Python BM25 for chapter context retrieval.

    Builds an index from chapter summaries, retrieves the k most relevant
    chapters for a given query. No external dependencies.
    """

    def __init__(self, k1: float = 1.5, b: float = 0.75):
        self.k1 = k1
        self.b = b
        self._docs: list[dict] = []
        self._doc_freq: Counter = Counter()
        self._total_docs = 0
        self._avg_dl = 0.0

    def index(self, chapters: list[dict]):
        """Build BM25 index from chapter metadata.

        Args:
            chapters: List of chapter dicts with 'summary', 'chapter', 'title' keys.
        """
        self._docs = []
        all_terms = []
        doc_lengths = []

        for ch in chapters:
            text = f"{ch.get('summary', '')} {ch.get('title', '')} {ch.get('pov', '')} {ch.get('key_events', '')}"
            if isinstance(text, list):
                text = " ".join(text)
            doc_text = text.lower()
            terms = self._tokenize(doc_text)
            self._docs.append({
                "chapter": ch.get("chapter", 0),
                "title": ch.get("title", ""),
                "terms": terms,
                "raw": doc_text,
            })
            all_terms.extend(terms)
            doc_lengths.append(len(terms))

        # Count unique terms per doc for IDF
        self._doc_freq: Counter = Counter()
        for doc in self._docs:
            unique_terms = set(doc["terms"])
            for t in unique_terms:
                self._doc_freq[t] += 1

        self._total_docs = len(self._docs)
        self._avg_dl = sum(doc_lengths) / max(len(doc_lengths), 1)

    def _tokenize(self, text: str) -> list[str]:
        """Tokenize text into terms."""
        return re.findall(r'\b[a-z0-9]{3,}\b', text.lower())

    def search(self, query: str, k: int = 3, exclude_chapters: set = None) -> list[dict]:
        """Retrieve top-k relevant chapters for a query.

        Args:
            query: Search query (outline summary, character name, etc.)
            k: Number of results to return
            exclude_chapters: Set of chapter numbers to exclude

        Returns:
            List of dicts with 'chapter', 'title', 'score' keys, sorted by score desc
        """
        if not self._docs:
            return []

        query_terms = self._tokenize(query)
        if not query_terms:
            return []

        exclude_chapters = exclude_chapters or set()
        scores = []

        for doc in self._docs:
            ch_num = doc["chapter"]
            if ch_num in exclude_chapters:
                continue

            score = 0.0
            doc_len = len(doc["terms"])
            for qt in query_terms:
                if qt not in self._doc_freq:
                    continue
                # Term frequency in this document
                tf = sum(1 for t in doc["terms"] if t == qt)
                if tf == 0:
                    continue
                # IDF
                idf = math.log((self._total_docs - self._doc_freq[qt] + 0.5) /
                               (self._doc_freq[qt] + 0.5) + 1.0)
                # BM25 scoring
                score += idf * (tf * (self.k1 + 1)) / \
                    (tf + self.k1 * (1 - self.b + self.b * doc_len / self._avg_dl))

            scores.append({
                "chapter": ch_num,
                "title": doc["title"],
                "score": round(score, 4),
            })

        scores.sort(key=lambda x: -x["score"])
        return scores[:k]


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

    score = scorer.score_chapter(content)

    return {
        "variant": style_name,
        "content": content,
        "score": score,
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
) -> tuple[str, dict, int]:
    """Run revision loop: score -> revise -> re-score up to max_rounds.

    Args:
        chapter_text: Initial chapter draft
        max_rounds: Max revision iterations

    Returns:
        Tuple of (final_text, final_score_dict, revisions_done)
    """
    current_text = chapter_text
    current_score = scorer.score_chapter(current_text)
    threshold = config.scoring.min_chapter_score  # 6.0

    revisions_done = 0

    for round_num in range(max_rounds):
        if current_score["total_score"] >= threshold:
            break

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

    return current_text, current_score, revisions_done


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
        raise ValueError("No chapters found in outline")

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

    # Initialize Hindsight canonical state store
    project_slug = os.path.basename(project_dir)
    canonical = create_canonical_store(store_type="file", project_id=project_slug)
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

        # --- Parallel Variants ---
        if parallel_variants and max_variants >= 2:
            # Select style profiles
            profiles_to_use = DEFAULT_STYLE_PROFILES[:max_variants]
            variants = []

            for si, (style_name, style_desc) in enumerate(profiles_to_use):
                print(f"    Variant {si + 1}/{len(profiles_to_use)}: {style_name}...")
                variant_result = _draft_single_variant(
                    client=client,
                    model=model,
                    chapter_num=chapter_num,
                    chapter_title=chapter_title,
                    pov=pov,
                    summary=summary,
                    key_events=key_events,
                    emotional_arc=emotional_arc,
                    foreshadowing=foreshadowing,
                    char_arc_beat=char_arc_beat,
                    world_context=world_context,
                    retrieved_context=retrieved_context,
                    foreshadow_context=foreshadow_context,
                    style_direction=style_desc,
                    style_name=style_name,
                    config=config,
                    scorer=scorer,
                    chapter_spec=chapter_spec,
                    hindsight_context=hindsight_context,
                    compressed_context=compressed_context,
                )
                # Estimate tokens
                total_input_tokens += _estimate_tokens(
                    CHAPTER_DRAFT_TEMPLATE.format(
                        chapter_number=chapter_num,
                        chapter_title=chapter_title,
                        pov_character=pov,
                        chapter_summary=summary,
                        key_events="\n".join(f"- {e}" for e in key_events) if key_events else "",
                        emotional_arc=emotional_arc or "",
                        foreshadowing=foreshadowing or "",
                        character_arc_beat=char_arc_beat or "",
                        world_context=world_context or "",
                        retrieved_context=retrieved_context,
                        foreshadow_context=foreshadow_context,
                        style_direction=style_desc,
                    )
                )
                total_output_tokens += _estimate_tokens(variant_result["content"])
                total_variants_written += 1

                # Run revision loop on this variant
                if enable_revision:
                    revised_text, revised_score, rev_done = _run_revision_loop(
                        client=client,
                        model=model,
                        chapter_text=variant_result["content"],
                        scorer=scorer,
                        style_name=style_name,
                        max_rounds=config.scoring.max_revision_rounds,
                        config=config,
                    )
                    variant_result["content"] = revised_text
                    variant_result["score"] = revised_score
                    variant_result["revisions"] = rev_done
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

            print(f"    Selected: {best_style} (score: {best_score['total_score']}/10)")
        else:
            # Single variant (original behavior or 1 variant)
            best_style = "default"
            profiles_to_use = DEFAULT_STYLE_PROFILES[:1]
            style_name, style_desc = profiles_to_use[0]

            best_content = client.chat_with_retry(
                model,
                messages=[{"role": "user", "content": CHAPTER_DRAFT_TEMPLATE.format(
                    chapter_number=chapter_num,
                    chapter_title=chapter_title,
                    pov_character=pov,
                    chapter_summary=summary,
                    key_events="\n".join(f"- {e}" for e in key_events) if key_events else "",
                    emotional_arc=emotional_arc or "",
                    foreshadowing=foreshadowing or "",
                    character_arc_beat=char_arc_beat or "",
                    world_context=world_context or "",
                    retrieved_context=retrieved_context,
                    foreshadow_context=foreshadow_context,
                    style_direction=style_desc,
                )}],
                system_prompt=DRAFT_SYSTEM_PROMPT,
                temperature=0.8,
            )
            best_score = scorer.score_chapter(best_content)
            total_input_tokens += _estimate_tokens(CHAPTER_DRAFT_TEMPLATE)
            total_output_tokens += _estimate_tokens(best_content)
            total_variants_written = 1

            # Revision loop on single variant
            if enable_revision:
                best_content, best_score, rev_done = _run_revision_loop(
                    client=client,
                    model=model,
                    chapter_text=best_content,
                    scorer=scorer,
                    style_name=best_style,
                    max_rounds=config.scoring.max_revision_rounds,
                    config=config,
                )
                total_revisions += rev_done

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

        # Update Hindsight canonical state
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

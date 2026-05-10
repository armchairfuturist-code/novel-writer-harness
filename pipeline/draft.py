"""Draft phase — chapter generation with revision loop, parallel rhetorical variants, BM25 RAG, GBrain context, ReIO compression.

Drafts chapters incorporating:
- BM25 retrieval of relevant plot/character context from other chapters and outlines
- GBrain canonical state (character traits, world facts, active threads, foreshadowing) queried via HTTP API
- ReIO hierarchical context compression for long novels
- Active foreshadowing thread tracking across chapters
- Parallel drafting up to N rhetorical variants, selecting best by mechanical score
- Revision loop: score -> revise -> re-score (up to max_rounds or threshold)
"""

import json
import math
import os
import re
from typing import Optional

from config import Config, ModelConfig
from pipeline.api import CrofaiClient
from pipeline.gbrain_client import GBrainStore
from pipeline.reio_compression import ReIOCompressor


# ── Prompt Templates ────────────────────────────────────────────────

DRAFT_SYSTEM_PROMPT = """You are a novelist writing literary fiction with close-third person narration.

Guidelines:
- Write in close third person — stay inside the POV character's head, filter everything through their perception
- Show don't tell — let the reader infer emotions from action, dialogue, and sensory detail
- Vary sentence length for rhythm — short sentences for tension, longer for reflection
- Use specific sensory detail — make the reader see, hear, smell, and feel the world
- Trust the reader — don't over-explain, let subtext carry meaning
- Keep POV consistent within each scene
- Each chapter needs a mini-arc — beginning that hooks, middle that escalates, end that resonates
- No markdown formatting, no headings — just the prose itself
- Target word count: approximately 4000 words"""

REVISION_SYSTEM_PROMPT = """You are a revision editor. Your job is to fix specific mechanical issues in a chapter without rewriting it entirely.

Focus only on the issues identified in the revision prompt. Preserve the chapter's:
- Voice and narrative style
- POV and character interiority
- Plot progression and scene structure
- Dialogue and character voice

Make minimal, targeted changes. Don't rewrite what's working."""

CHAPTER_DRAFT_TEMPLATE = """Write Chapter {chapter_number}: "{chapter_title}"

POV Character: {pov_character}

Chapter Summary:
{chapter_summary}

Key Events:
{key_events}

Emotional Arc: {emotional_arc}
Foreshadowing: {foreshadowing}
Character Arc Beat: {character_arc_beat}

World Context:
{world_context}

GBrain Canonical State:
{gbrain_canonical_state}

Retrieved Context (related story elements from other chapters):
{retrieved_context}

Compressed Narrative Context (previous chapters):
{compressed_narrative_context}

Active Story Threads:
{active_threads}

Style Direction: {style_direction}

Write the chapter as literary fiction prose. Close third person. Show don't tell. Make it specific, sensory, and emotionally resonant."""


# ── Default Style Profiles ──────────────────────────────────────────

DEFAULT_STYLE_PROFILES = [
    ("lyrical", "Lyrical and reflective: long flowing sentences, rich sensory imagery, slow-burn emotional depth. Prioritize interiority and atmosphere."),
    ("taut", "Taut and propulsive: shorter sentences, faster pacing, dialogue-driven scenes. Prioritize tension and forward momentum."),
    ("textured", "Textured and layered: dense with specific detail. Every object, gesture, and space carries thematic weight. Prioritize world texture and subtext."),
]


# ── Token Estimation ────────────────────────────────────────────────

def _estimate_tokens(text: str) -> int:
    """Rough token estimate (~4 chars per token for English)."""
    return len(text) // 4


# ── BM25 Retriever ──────────────────────────────────────────────────

class BM25Retriever:
    """Simple in-memory BM25 retriever for plot/character context."""

    def __init__(self, k1: float = 1.5, b: float = 0.75):
        self.k1 = k1
        self.b = b
        self._docs: list[dict] = []
        self._doc_freq: dict[str, int] = {}
        self._total_docs = 0
        self._avg_dl = 0.0

    def index(self, documents: list[dict]):
        self._docs = documents
        self._total_docs = len(documents)

        term_doc_count: dict[str, int] = {}
        total_terms = 0
        for doc in documents:
            text = " ".join([
                doc.get("summary", ""),
                doc.get("title", ""),
                doc.get("pov", ""),
                doc.get("key_events", ""),
            ])
            terms = re.findall(r'\b[a-z]{3,}\b', text.lower())
            doc["terms"] = terms
            total_terms += len(terms)
            for t in set(terms):
                term_doc_count[t] = term_doc_count.get(t, 0) + 1

        self._doc_freq = term_doc_count
        self._avg_dl = total_terms / max(self._total_docs, 1)

    def search(self, query: str, k: int = 3, exclude_chapters: Optional[set] = None) -> list[dict]:
        query_terms = re.findall(r'\b[a-z]{3,}\b', query.lower())
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
                tf = sum(1 for t in doc["terms"] if t == qt)
                if tf == 0:
                    continue
                idf = math.log((self._total_docs - self._doc_freq[qt] + 0.5) / (self._doc_freq[qt] + 0.5) + 1.0)
                score += idf * (tf * (self.k1 + 1)) / (tf + self.k1 * (1 - self.b + self.b * doc_len / self._avg_dl))
            scores.append({"chapter": ch_num, "title": doc["title"], "score": round(score, 4)})
        scores.sort(key=lambda x: -x["score"])
        return scores[:k]


# ── Chapter Scorer ──────────────────────────────────────────────────

class ChapterScorer:
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
        banned_penalty = max(len(banned_found) * self.config.scoring.banned_word_penalty, -5.0)
        tell_patterns = [r'\bfelt ', r'\bfelt that\b', r'\bknew that\b', r'\brealized that\b', r'\bthought that\b', r'\bwondered if\b', r'\bit was \w+ that\b', r'\bthere was\b', r'\bthere were\b']
        tell_count = sum(len(re.findall(pat, text_lower)) for pat in tell_patterns)
        tell_ratio = tell_count / max(total_sentences, 1)
        sent_lengths = [len(s.split()) for s in sentences]
        avg_len = sum(sent_lengths) / max(len(sent_lengths), 1)
        variance = sum((l - avg_len) ** 2 for l in sent_lengths) / max(len(sent_lengths), 1)
        std_dev = variance ** 0.5
        pacing_score = min(std_dev / 10.0, 1.0)
        dialogue_lines = len(re.findall(r'["\u201c][^"\u201d]*["\u201d]', text))
        dialogue_ratio = dialogue_lines / max(word_count, 1)
        base_score = 7.0 + banned_penalty * 0.5
        if tell_ratio > self.config.scoring.show_dont_tell_threshold:
            base_score -= (tell_ratio - self.config.scoring.show_dont_tell_threshold) * 3
        base_score += pacing_score * 0.5
        base_score = max(0, min(10, base_score))
        return {"word_count": word_count, "banned_words_found": banned_found, "banned_penalty": round(banned_penalty, 2), "tell_ratio": round(tell_ratio, 3), "pacing_variance": round(std_dev, 1), "dialogue_ratio": round(dialogue_ratio, 4), "total_score": round(base_score, 1)}


# ── Parallel Variant Drafting ───────────────────────────────────────

def _draft_single_variant(client: CrofaiClient, model, chapter_num: int, chapter_title: str, pov: str, summary: str, key_events: list, emotional_arc: str, foreshadowing: str, char_arc_beat: str, world_context: str, retrieved_context: str, active_threads: list, style_direction: str, style_name: str, config: Config, scorer: ChapterScorer, chapter_spec: dict, gbrain_context: str = "", compressed_context: str = "") -> dict:
    prompt = CHAPTER_DRAFT_TEMPLATE.format(
        chapter_number=chapter_num, chapter_title=chapter_title, pov_character=pov,
        chapter_summary=summary, key_events="\n".join(f"- {e}" for e in key_events) if key_events else "As outlined above.",
        emotional_arc=emotional_arc or "As outlined above.", foreshadowing=foreshadowing or "As outlined above.",
        character_arc_beat=char_arc_beat or "As outlined above.", world_context=world_context or "As established in world bible.",
        gbrain_canonical_state=gbrain_context or "[No additional canonical state available]",
        retrieved_context=retrieved_context, compressed_narrative_context=compressed_context or "[No compressed context available]",
        active_threads="\n".join(active_threads[-5:]) if active_threads else "None yet.", style_direction=style_direction,
    )
    content = client.chat_with_retry(model, messages=[{"role": "user", "content": prompt}], system_prompt=DRAFT_SYSTEM_PROMPT, temperature=0.8)
    score = scorer.score_chapter(content)
    return {"variant": style_name, "content": content, "score": score}


# ── Revision Loop ───────────────────────────────────────────────────

def _generate_revision_prompt(chapter_text: str, mechanical_score: dict, style_name: str) -> str:
    issues = []
    if mechanical_score["banned_words_found"]:
        banned_list = ", ".join(f"'{w}' (x{c})" for w, c in mechanical_score["banned_words_found"].items())
        issues.append(f"- Remove or replace banned/overused words: {banned_list}")
    if mechanical_score["tell_ratio"] > 0.3:
        issues.append(f"- Show-don't-tell ratio is {mechanical_score['tell_ratio']:.2f} (target < 0.30). Convert 'felt that', 'knew that', 'realized that' into sensory action and dialogue.")
    if mechanical_score["pacing_variance"] < 5.0:
        issues.append(f"- Sentence length variance is low ({mechanical_score['pacing_variance']:.1f}). Vary sentence lengths more for rhythm.")
    if mechanical_score["word_count"] < 2000:
        issues.append(f"- Chapter is short ({mechanical_score['word_count']} words). Expand scenes with more sensory detail, interiority, and action.")
    if not issues:
        return ""
    prompt_parts = [f"Revise this chapter ({style_name} variant). The mechanical review found these issues:\n", *issues, "\nFix all issues while preserving the chapter's voice, POV, and narrative arc.", "\n--- CHAPTER TEXT ---\n", chapter_text]
    return "\n".join(prompt_parts)


def _run_revision_loop(client: CrofaiClient, model, chapter_text: str, scorer: ChapterScorer, style_name: str, max_rounds: int, config: Config) -> tuple[str, dict, int]:
    current_text = chapter_text
    current_score = scorer.score_chapter(current_text)
    threshold = config.scoring.min_chapter_score
    revisions_done = 0
    for round_num in range(max_rounds):
        if current_score["total_score"] >= threshold:
            break
        revision_prompt = _generate_revision_prompt(current_text, current_score, style_name)
        if not revision_prompt:
            break
        print(f"      Revision round {round_num + 1}/{max_rounds} (score: {current_score['total_score']}/10)...")
        try:
            revised = client.chat_with_retry(model, messages=[{"role": "user", "content": revision_prompt}], system_prompt=REVISION_SYSTEM_PROMPT, temperature=0.7)
            new_score = scorer.score_chapter(revised)
            if new_score["total_score"] > current_score["total_score"]:
                current_text = revised; current_score = new_score; revisions_done += 1
                print(f"        Improved to {current_score['total_score']}/10")
            else:
                print(f"        No improvement ({new_score['total_score']}/10), keeping current version"); break
        except RuntimeError as e:
            print(f"        Revision failed: {e}"); break
    return current_text, current_score, revisions_done


# ── Main Draft Orchestrator ─────────────────────────────────────────

def run_draft(spec: dict, world: dict, characters: dict, outline: dict, project_dir: str, config: Optional[Config] = None, resume_from: int = 1, parallel_variants: bool = True, max_variants: int = 2, enable_revision: bool = True, enable_gbrain: bool = True) -> list[dict]:
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

    retriever = BM25Retriever()
    all_chapter_meta = [{"chapter": i + 1, "title": ch.get("title", f"Chapter {i+1}"), "summary": ch.get("summary", ""), "pov": ch.get("pov", ""), "key_events": " ".join(ch.get("key_events", []))} for i, ch in enumerate(all_chapters)]
    retriever.index(all_chapter_meta)

    total = len(all_chapters)
    results = []
    previous_summary = "Beginning of the story. No prior events."
    active_threads = []
    written_chapter_meta = []

    project_slug = os.path.basename(project_dir)
    gbrain = GBrainStore(project_id=project_slug) if enable_gbrain else None
    if gbrain:
        gbrain.ensure_bank_safe()

    reio = ReIOCompressor(token_budget=config.chapter.auto_compress_at_tokens, recent_chapters=config.chapter.context_carry_window)

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

        query = f"{summary} {emotional_arc} {pov} {' '.join(key_events) if isinstance(key_events, list) else key_events}"
        written_numbers = {r["chapter"] for r in written_chapter_meta} | {chapter_num}
        relevant_chapters = retriever.search(query, k=3, exclude_chapters=written_numbers)
        retrieved_context = ""
        if relevant_chapters:
            retrieved_lines = []
            for rc in relevant_chapters:
                meta = all_chapter_meta[rc["chapter"] - 1]
                s = meta.get("summary", "")
                if s:
                    retrieved_lines.append(f"  - Ch {rc['chapter']} ({rc['title']}): {s[:200]} (relevance: {rc['score']:.2f})")
            if retrieved_lines:
                retrieved_context = "Related story elements from unconnected chapters:\n" + "\n".join(retrieved_lines)

        window = config.chapter.context_carry_window
        context_buffer = written_chapter_meta[-window:] if written_chapter_meta else []
        if context_buffer:
            prev_summary_text = "\n".join(f"Ch {r['chapter']} ({r['title']}): {r.get('summary', '')[:200]}" for r in context_buffer)
        else:
            prev_summary_text = "Beginning of the story. No prior events."

        world_context = ""
        if isinstance(world, dict):
            wc = world.get("central_conflict", "")
            mood = world.get("mood_setting", "")
            world_context = f"{wc[:200]}\n{mood[:200]}"

        gbrain_context = gbrain.format_context_for_drafting(chapter_num, summary) if gbrain else "[GBrain disabled]"

        compressed_context = ""
        if written_chapter_meta:
            compressed_context = reio.compress_for_chapter(chapter_num=chapter_num, total_chapters=len(written_chapter_meta), chapter_summaries=written_chapter_meta, arc_summaries=reio.build_arc_summaries(outline, written_chapter_meta) if written_chapter_meta else None, critical_state=gbrain_context if (gbrain is not None and gbrain.enabled) else None)

        print(f"  Drafting Chapter {chapter_num}/{total}: {chapter_title}...")
        print(f"    POV: {pov} | Model: {model.name}")

        if parallel_variants and max_variants >= 2:
            profiles_to_use = DEFAULT_STYLE_PROFILES[:max_variants]
            variants = []
            for si, (style_name, style_desc) in enumerate(profiles_to_use):
                print(f"    Variant {si + 1}/{len(profiles_to_use)}: {style_name}...")
                variant_result = _draft_single_variant(client=client, model=model, chapter_num=chapter_num, chapter_title=chapter_title, pov=pov, summary=summary, key_events=key_events, emotional_arc=emotional_arc, foreshadowing=foreshadowing, char_arc_beat=char_arc_beat, world_context=world_context, retrieved_context=retrieved_context, active_threads=active_threads, style_direction=style_desc, style_name=style_name, config=config, scorer=scorer, chapter_spec=chapter_spec, gbrain_context=gbrain_context, compressed_context=compressed_context)
                total_input_tokens += _estimate_tokens(CHAPTER_DRAFT_TEMPLATE.format(chapter_number=chapter_num, chapter_title=chapter_title, pov_character=pov, chapter_summary=summary, key_events="\n".join(f"- {e}" for e in key_events) if key_events else "", emotional_arc=emotional_arc or "", foreshadowing=foreshadowing or "", character_arc_beat=char_arc_beat or "", world_context=world_context or "", gbrain_canonical_state=gbrain_context or "", retrieved_context=retrieved_context, compressed_narrative_context=compressed_context or "", active_threads="\n".join(active_threads[-5:]) if active_threads else "", style_direction=style_desc))
                total_output_tokens += _estimate_tokens(variant_result["content"])
                total_variants_written += 1
                if enable_revision:
                    revised_text, revised_score, rev_done = _run_revision_loop(client=client, model=model, chapter_text=variant_result["content"], scorer=scorer, style_name=style_name, max_rounds=config.scoring.max_revision_rounds, config=config)
                    variant_result["content"] = revised_text; variant_result["score"] = revised_score; variant_result["revisions"] = rev_done
                    total_revisions += rev_done
                else:
                    variant_result["revisions"] = 0
                variants.append(variant_result)
                print(f"      Score: {variant_result['score']['total_score']}/10 | {variant_result['score']['word_count']} words | {variant_result['revisions']} revisions")
            variants.sort(key=lambda v: -v["score"]["total_score"])
            best = variants[0]; best_content = best["content"]; best_score = best["score"]; best_style = best["variant"]
            print(f"    Selected: {best_style} (score: {best_score['total_score']}/10)")
        else:
            best_style = "default"
            profiles_to_use = DEFAULT_STYLE_PROFILES[:1]
            style_name, style_desc = profiles_to_use[0]
            best_content = client.chat_with_retry(model, messages=[{"role": "user", "content": CHAPTER_DRAFT_TEMPLATE.format(chapter_number=chapter_num, chapter_title=chapter_title, pov_character=pov, chapter_summary=summary, key_events="\n".join(f"- {e}" for e in key_events) if key_events else "", emotional_arc=emotional_arc or "", foreshadowing=foreshadowing or "", character_arc_beat=char_arc_beat or "", world_context=world_context or "", gbrain_canonical_state=gbrain_context or "[No additional canonical state available]", retrieved_context=retrieved_context, compressed_narrative_context=compressed_context or "[No compressed context available]", active_threads="\n".join(active_threads[-5:]) if active_threads else "", style_direction=style_desc)}], system_prompt=DRAFT_SYSTEM_PROMPT, temperature=0.8)
            best_score = scorer.score_chapter(best_content)
            total_input_tokens += _estimate_tokens(CHAPTER_DRAFT_TEMPLATE)
            total_output_tokens += _estimate_tokens(best_content)
            total_variants_written = 1
            if enable_revision:
                best_content, best_score, rev_done = _run_revision_loop(client=client, model=model, chapter_text=best_content, scorer=scorer, style_name=best_style, max_rounds=config.scoring.max_revision_rounds, config=config)
                total_revisions += rev_done

        chapter_file = os.path.join(chapters_dir, f"chapter-{chapter_num:03d}.md")
        with open(chapter_file, "w", encoding="utf-8") as f:
            f.write(f"# Chapter {chapter_num}: {chapter_title}\n\n> POV: {pov} | Style: {best_style} | Score: {best_score['total_score']}/10\n\n{best_content}")

        chapter_result = {"chapter": chapter_num, "title": chapter_title, "pov": pov, "file": chapter_file, "score": best_score, "summary": summary, "word_count": best_score["word_count"], "style": best_style}
        results.append(chapter_result)
        written_chapter_meta.append(chapter_result)

        if gbrain:
            gbrain.update_after_chapter(chapter_num=chapter_num, title=chapter_title, summary=summary, pov=pov, word_count=best_score["word_count"], key_events=key_events if isinstance(key_events, list) else [key_events], foreshadowing_elements=[(foreshadowing, chapter_num + 3)] if foreshadowing else None)

        previous_summary = f"Chapter {chapter_num}: {summary[:200]}"
        if foreshadowing:
            active_threads.append(f"[Foreshadow Ch{chapter_num}]: {foreshadowing[:100]}")
        print(f"    Final: Score {best_score['total_score']}/10 | {best_score['word_count']} words | Style: {best_style}")

    client.close()
    total_cost_estimate = total_input_tokens * 0.000002 + total_output_tokens * 0.000010
    print(f"\n  --- Token Usage Summary ---")
    print(f"  Input tokens (estimated): {total_input_tokens:,}")
    print(f"  Output tokens (estimated): {total_output_tokens:,}")
    print(f"  Total variants written: {total_variants_written}")
    print(f"  Total revision rounds: {total_revisions}")
    print(f"  Estimated cost: ${total_cost_estimate:.4f}")
    return results

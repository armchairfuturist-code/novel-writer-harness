"""Draft phase - generate chapters sequentially with context carry and scoring.

This is the core prose engine. Uses Kimi K2.6 for actual chapter writing with:
- Context carry: previous N chapters included for continuity
- State tracking: character states, foreshadowing flags, unresolved threads
- Per-chapter mechanical scoring (banned words, prose metrics)
- Conditional auto-compression at 900K tokens

The draft loop produces one chapter at a time, storing them so the writer
can inspect progress mid-pipeline.
"""

import json
import os
import re
from typing import Optional

from config import Config
from pipeline.api import CrofaiClient

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

Previous chapter summary (for continuity):
{previous_chapter_summary}

Active threads to manage:
{active_threads}

Write the chapter now. Focus on craft: sensory immersion, pacing, dialogue rhythm,
interiority. Make every sentence earn its place."""


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
            r'\bfelt\b', r'\bfelt that\b', r'\bknew that\b',
            r'\brealized that\b', r'\bthought that\b', r'\bwondered if\b',
            r'\bit was\s+\w+\s+that\b', r'\bthere was\b', r'\bthere were\b',
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


def run_draft(
    spec: dict,
    world: dict,
    characters: dict,
    outline: dict,
    project_dir: str,
    config: Optional[Config] = None,
    resume_from: int = 1,
) -> list[dict]:
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

    total = len(all_chapters)
    results = []
    previous_summary = "Beginning of the story. No prior events."
    active_threads = []
    context_buffer = []

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

        window = config.chapter.context_carry_window
        recent_context = context_buffer[-window:] if context_buffer else []
        prev_summary_text = previous_summary
        if recent_context:
            prev_summary_text = "\n".join(
                f"Ch {r['chapter']} ({r['title']}): {r.get('summary', '')[:200]}"
                for r in recent_context
            )

        world_context = ""
        if isinstance(world, dict):
            wc = world.get("central_conflict", "")
            mood = world.get("mood_setting", "")
            world_context = f"{wc[:200]}\n{mood[:200]}"

        prompt = CHAPTER_DRAFT_TEMPLATE.format(
            chapter_number=chapter_num,
            chapter_title=chapter_title,
            pov_character=pov,
            chapter_summary=summary,
            key_events="\n".join(f"- {e}" for e in key_events),
            emotional_arc=emotional_arc,
            foreshadowing=foreshadowing,
            character_arc_beat=char_arc_beat,
            world_context=world_context or "As established in world bible.",
            previous_chapter_summary=prev_summary_text,
            active_threads="\n".join(active_threads[-5:]) if active_threads else "None yet.",
        )

        print(f"  Drafting Chapter {chapter_num}/{total}: {chapter_title}...")
        print(f"    POV: {pov} | Model: {model.name}")

        content = client.chat_with_retry(
            model,
            messages=[{"role": "user", "content": prompt}],
            system_prompt=DRAFT_SYSTEM_PROMPT,
            temperature=0.8,
        )

        score = scorer.score_chapter(content)

        chapter_file = os.path.join(chapters_dir, f"chapter-{chapter_num:03d}.md")
        with open(chapter_file, "w", encoding="utf-8") as f:
            f.write(f"# Chapter {chapter_num}: {chapter_title}\n\n")
            f.write(f"> POV: {pov} | Score: {score['total_score']}/10\n\n")
            f.write(content)

        chapter_result = {
            "chapter": chapter_num,
            "title": chapter_title,
            "pov": pov,
            "file": chapter_file,
            "score": score,
            "summary": summary,
            "word_count": score["word_count"],
        }
        results.append(chapter_result)

        if len(context_buffer) >= window:
            context_buffer.pop(0)
        context_buffer.append(chapter_result)

        previous_summary = f"Chapter {chapter_num}: {summary[:200]}"

        if foreshadowing:
            active_threads.append(f"[Foreshadow Ch{chapter_num}]: {foreshadowing[:100]}")

        print(f"    Score: {score['total_score']}/10 | {score['word_count']} words")

    client.close()
    return results

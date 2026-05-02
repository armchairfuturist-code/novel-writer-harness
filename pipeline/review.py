"""Review phase - adversarial critique with dual immune system.

Two-layer review:
1. Mechanical: regex scoring (banned words, show-don't-tell, pacing)
2. LLM judge: Kimi K2.6 as literary critic

The reviewer assigns scores and specific revision instructions. The pipeline
loops (draft -> review -> revise -> review) until the chapter clears the
target threshold or max rounds reached.
"""

import json
import os
import re
from typing import Optional

from config import Config
from pipeline.api import CrofaiClient

REVIEW_SYSTEM_PROMPT_CRITIC = """You are a relentless literary critic. Your job is to
find every flaw in this chapter and explain exactly why it doesn't work. Be specific.
Point to sentences. Quote bad prose. Never say "this is good" - your value is in
what needs fixing.

Score the chapter on: Prose quality, Pacing, Character depth, Dialogue, Structure.
Return a JSON object with scores (0-10) and specific revision instructions."""


def run_mechanical_review(text: str, config: Optional[Config] = None) -> dict:
    config = config or Config()
    from pipeline.draft import ChapterScorer

    scorer = ChapterScorer(config)
    scores = scorer.score_chapter(text)

    sentences = re.split(r'[.!?]+', text)
    sentences = [s.strip() for s in sentences if len(s.strip()) > 10]

    adverb_pattern = r'\b\w+ly\b'
    adverbs = re.findall(adverb_pattern, text.lower())
    adverb_ratio = len(adverbs) / max(len(text.split()), 1)

    passive_pattern = r'\b(was|were|been|being|am|is|are)\s+\w+ed\b'
    passive_count = len(re.findall(passive_pattern, text.lower()))
    passive_ratio = passive_count / max(len(text.split()), 1)

    return {
        "scores": scores,
        "adverb_ratio": round(adverb_ratio, 4),
        "adverb_count": len(adverbs),
        "passive_count": passive_count,
        "passive_ratio": round(passive_ratio, 4),
        "issues": [],
    }


def run_llm_review(text: str, chapter_title: str, config: Optional[Config] = None) -> dict:
    config = config or Config()
    client = CrofaiClient(config)
    model = config.model_for_phase("critique")

    words = text.split()
    truncated_text = " ".join(words[:8000])
    if len(words) > 8000:
        truncated_text += "\n\n[Note: chapter truncated from original length for review]"

    prompt = f"""Review this chapter: "{chapter_title}"

{truncated_text}

Return a JSON object with:
- "prose_score": 0-10 (sentence craft, imagery, rhythm)
- "pacing_score": 0-10 (tension, momentum, scene structure)
- "character_score": 0-10 (depth, voice, consistency)
- "dialogue_score": 0-10 (naturalness, subtext, characterization through speech)
- "structure_score": 0-10 (scene architecture, chapter arc)
- "overall_score": 0-10
- "strengths": Array of 2-4 specific things that work well
- "weaknesses": Array of 2-4 specific things to improve
- "revision_priority": Array of 1-3 things to fix FIRST
- "critical_passages": Array of {{"text": "quoted passage", "issue": "what's wrong"}}
"""

    content = client.chat_with_retry(
        model,
        messages=[{"role": "user", "content": prompt}],
        system_prompt=REVIEW_SYSTEM_PROMPT_CRITIC,
        temperature=0.4,
    )

    content = content.strip()
    if content.startswith("```"):
        lines = content.splitlines()
        cleaned = [l for l in lines if not l.startswith("```")]
        content = "\n".join(cleaned)

    try:
        review = json.loads(content)
    except json.JSONDecodeError:
        start = content.find("{")
        end = content.rfind("}")
        if start != -1 and end != -1:
            review = json.loads(content[start:end+1])
        else:
            review = {"overall_score": 5.0, "raw_review": content[:500]}

    client.close()
    return review


def run_full_review(
    chapters: list[dict], project_dir: str, config: Optional[Config] = None
) -> dict:
    config = config or Config()
    client = CrofaiClient(config)
    model = config.model_for_phase("final_review")

    per_chapter = []
    all_scores = []

    for ch in chapters:
        chapter_file = ch.get("file", "")
        if not os.path.exists(chapter_file):
            continue

        with open(chapter_file, "r", encoding="utf-8") as f:
            text = f.read()

        mechanical = run_mechanical_review(text, config)
        llm_review = run_llm_review(text, ch.get("title", f"Chapter {ch['chapter']}"), config)

        combined = {
            "chapter": ch["chapter"],
            "title": ch["title"],
            "mechanical_score": mechanical["scores"]["total_score"],
            "llm_overall": llm_review.get("overall_score", 5.0),
            "llm_scores": {
                k: llm_review.get(k, None)
                for k in ["prose_score", "pacing_score", "character_score", "dialogue_score", "structure_score"]
            },
            "strengths": llm_review.get("strengths", []),
            "weaknesses": llm_review.get("weaknesses", []),
            "revision_priority": llm_review.get("revision_priority", []),
            "word_count": mechanical["scores"]["word_count"],
        }

        per_chapter.append(combined)
        combined_score = (combined["mechanical_score"] + (combined["llm_overall"] or 5.0)) / 2
        all_scores.append(combined_score)

    avg_score = sum(all_scores) / len(all_scores) if all_scores else 0
    lowest_chapter = min(per_chapter, key=lambda c: (c["llm_overall"] or 0) + c["mechanical_score"]) if per_chapter else None

    result = {
        "per_chapter": per_chapter,
        "overall_avg_score": round(avg_score, 1),
        "total_words": sum(c["word_count"] for c in per_chapter),
        "weakest_chapter": lowest_chapter["chapter"] if lowest_chapter else None,
        "needs_revision": avg_score < config.scoring.target_chapter_score,
    }

    client.close()
    return result


def generate_revision_prompt(chapter_text: str, review_result: dict) -> str:
    weaknesses = review_result.get("weaknesses", [])
    priorities = review_result.get("revision_priority", [])
    critical = review_result.get("critical_passages", [])

    prompt_parts = [
        "Revise the following chapter based on this feedback:",
        "",
        "Weaknesses to address:",
    ]
    for w in weaknesses:
        prompt_parts.append(f"- {w}")

    if priorities:
        prompt_parts.extend(["", "Priority fixes:"])
        for p in priorities:
            prompt_parts.append(f"- {p}")

    if critical:
        prompt_parts.extend(["", "Specific passages to fix:"])
        for c in critical:
            prompt_parts.append(f'- "{c.get("text", "")}" - {c.get("issue", "")}')

    prompt_parts.extend(["", "--- CHAPTER TEXT ---", "", chapter_text])
    return "\n".join(prompt_parts)

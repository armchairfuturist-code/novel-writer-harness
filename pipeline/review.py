"""Review phase — dual-persona Opus-style manuscript critique.

Two-layer review system (inspired by autonovel's Opus review loop):

1. Mechanical review: regex-based scoring (banned words, show-don't-tell, pacing)
2. Dual-persona LLM review: literary critic + professor of fiction in adversarial debate

The dual-persona loop iterates until both reviewers run out of major items or
max rounds reached. Each round produces revision instructions for the chapter.
"""

import json
import os
import re
from typing import Optional

from config import Config
from pipeline.api import CrofaiClient, parse_json_output


# --- Review prompt templates ---

LITERARY_CRITIC_SYSTEM = """You are a relentless literary critic who has spent 40 years
publishing reviews. You HATE bad prose. You notice every lazy sentence, every cliche,
every moment the author took the easy way out.

Your reviews are brutal but specific. Quote exact sentences. Explain WHY they fail.
Never say "this is good" - your value is in finding what needs fixing.

Score on: Prose craft, Narrative architecture, Character authenticity, Tension management.

Return JSON."""

PROFESSOR_SYSTEM = """You are a professor of fiction writing at a top MFA program.
You have taught for 30 years. You believe in craft as something that can be taught.

Your reviews are compassionate but exacting. You identify the writer's intention,
then explain how the execution falls short. You offer specific alternatives.

Score on: Thematic coherence, Structural integrity, Reader experience, Voice consistency.

Return JSON."""

LITERARY_CRITIC_PROMPT = """Review this chapter: "{chapter_title}"

{chapter_text}

Return JSON with:
- "prose_craft": 0-10 (sentence-level quality, imagery, rhythm)
- "narrative_architecture": 0-10 (scene structure, pacing, tension)
- "character_authenticity": 0-10 (depth, motivation, consistency)
- "tension_management": 0-10 (stakes, momentum, reader engagement)
- "overall_score": 0-10
- "specific_failures": [{{"quote": "exact sentence", "failure": "what's wrong", "fix": "how to fix"}}]
- "strengths": ["specific things that work"]
- "fundamental_issues": ["high-level problems this chapter has"]"""

PROFESSOR_PROMPT = """Assess this chapter with an MFA professor's eye: "{chapter_title}"

{chapter_text}

Return JSON with:
- "thematic_coherence": 0-10 (how the chapter advances the story's themes)
- "structural_integrity": 0-10 (scene architecture, chapter arc)
- "reader_experience": 0-10 (emotional impact, immersion, satisfaction)
- "voice_consistency": 0-10 (POV discipline, narrative voice, dialogue differentiation)
- "overall_score": 0-10
- "craft_observations": [{{"element": "what you observed", "assessment": "how it works or doesn't", "alternative": "a concrete alternative approach"}}]
- "what_to_preserve": ["things the literary critic might miss that ARE working"]
- "growth_areas": ["the 2-3 things this writer should focus on most"]"""

SYNTHESIS_SYSTEM = """You are a senior editor reconciling two reader reports on the same
chapter. The literary critic finds flaws. The professor finds craft signals.

Your job: synthesize both into a coherent revision plan. Resolve contradictions.
Prioritize by impact. Return a single JSON with specific, actionable instructions."""

SYNTHESIS_PROMPT = """Synthesize these two reviews of "{chapter_title}" into a unified revision plan:

--- LITERARY CRITIC'S REPORT ---
{critic_report}

--- PROFESSOR'S REPORT ---
{professor_report}

Return JSON with:
- "unified_score": 0-10
- "critical_issues": [{{"issue": "desc", "priority": "high/medium/low", "target": "which sentences/sections"}}]
- "revision_instructions": ["Step-by-step what to fix, in priority order"]
- "preserve": ["What's working - don't change this"]
- "synthesis_notes": "What the two reviewers agreed on, what they disagreed on"
"""


def run_mechanical_review(text: str, config: Optional[Config] = None) -> dict:
    """Run mechanical (regex-based) review on chapter text."""
    config = config or Config()
    from pipeline.draft import ChapterScorer

    scorer = ChapterScorer(config)
    scores = scorer.score_chapter(text)

    sentences = re.split(r'[.!?]+', text)
    sentences = [s.strip() for s in sentences if len(s.strip()) > 10]

    # Adverb ratio
    adverb_pattern = r'\b\w+ly\b'
    adverbs = re.findall(adverb_pattern, text.lower())
    adverb_ratio = len(adverbs) / max(len(text.split()), 1)

    # Passive voice
    passive_pattern = r'\b(was|were|been|being|am|is|are)\s+\w+ed\b'
    passive_count = len(re.findall(passive_pattern, text.lower()))
    passive_ratio = passive_count / max(len(text.split()), 1)

    # Unique vocabulary richness
    words = re.findall(r'\b[a-z]{4,}\b', text.lower())
    unique_ratio = len(set(words)) / max(len(words), 1) if words else 0

    return {
        "scores": scores,
        "adverb_ratio": round(adverb_ratio, 4),
        "adverb_count": len(adverbs),
        "passive_count": passive_count,
        "passive_ratio": round(passive_ratio, 4),
        "vocabulary_richness": round(unique_ratio, 3),
    }


def run_literary_critic_review(text: str, chapter_title: str, client: CrofaiClient, model) -> dict:
    """Run single literary critic review."""
    words = text.split()
    truncated = " ".join(words[:6000])
    if len(words) > 6000:
        truncated += "\n\n[Note: truncated for review]"

    prompt = LITERARY_CRITIC_PROMPT.format(chapter_title=chapter_title, chapter_text=truncated)
    content = client.chat_with_retry(
        model,
        messages=[{"role": "user", "content": prompt}],
        system_prompt=LITERARY_CRITIC_SYSTEM,
        temperature=0.4,
    )
    return parse_json_output(content, label="literary_critic_review")


def run_professor_review(text: str, chapter_title: str, client: CrofaiClient, model) -> dict:
    """Run single professor review."""
    words = text.split()
    truncated = " ".join(words[:6000])
    if len(words) > 6000:
        truncated += "\n\n[Note: truncated for review]"

    prompt = PROFESSOR_PROMPT.format(chapter_title=chapter_title, chapter_text=truncated)
    content = client.chat_with_retry(
        model,
        messages=[{"role": "user", "content": prompt}],
        system_prompt=PROFESSOR_SYSTEM,
        temperature=0.5,  # slightly higher for more nuanced reading
    )
    return parse_json_output(content, label="professor_review")


def synthesize_reviews(
    chapter_title: str,
    critic_report: dict,
    professor_report: dict,
    client: CrofaiClient,
    model,
) -> dict:
    """Synthesize critic and professor reviews into unified revision plan."""
    prompt = SYNTHESIS_PROMPT.format(
        chapter_title=chapter_title,
        critic_report=json.dumps(critic_report, indent=2),
        professor_report=json.dumps(professor_report, indent=2),
    )
    content = client.chat_with_retry(
        model,
        messages=[{"role": "user", "content": prompt}],
        system_prompt=SYNTHESIS_SYSTEM,
        temperature=0.3,
    )
    return parse_json_output(content, label="synthesis")


def run_dual_persona_review(
    chapter_text: str,
    chapter_title: str,
    config: Optional[Config] = None,
) -> dict:
    """Run dual-persona review on a single chapter.

    Returns unified scores and revision instructions from both personas.
    """
    config = config or Config()
    client = CrofaiClient(config)

    # Use critique model for both personas (Kimi K2.6 Precision)
    critique_model = config.model_for_phase("critique")

    mechanical = run_mechanical_review(chapter_text, config)
    critic = run_literary_critic_review(chapter_text, chapter_title, client, critique_model)
    professor = run_professor_review(chapter_text, chapter_title, client, critique_model)
    synthesis = synthesize_reviews(chapter_title, critic, professor, client, critique_model)

    # Calculate blended score
    mech_score = mechanical["scores"]["total_score"]
    critic_score = critic.get("overall_score", 5.0)
    professor_score = professor.get("overall_score", 5.0)
    unified_score = synthesis.get("unified_score", (mech_score + critic_score + professor_score) / 3)

    client.close()

    return {
        "chapter_title": chapter_title,
        "mechanical": mechanical,
        "literary_critic": critic,
        "professor": professor,
        "synthesis": synthesis,
        "blended_scores": {
            "mechanical": mech_score,
            "literary_critic": critic_score,
            "professor": professor_score,
            "unified": unified_score,
        },
        "final_score": round(mech_score * 0.2 + critic_score * 0.4 + professor_score * 0.4, 1),
    }


# ---------------------------------------------------------------------------
# Full manuscript review
# ---------------------------------------------------------------------------

def run_full_review(
    chapters: list[dict],
    project_dir: str,
    config: Optional[Config] = None,
    dual_persona: bool = True,
) -> dict:
    """Run full manuscript review with optional dual-persona critique.

    Args:
        chapters: List of chapter result dicts
        project_dir: Project directory
        config: Config override
        dual_persona: If True, use dual-persona review (2x tokens, better quality)

    Returns:
        dict: Review results with per-chapter scores and global assessment
    """
    config = config or Config()
    client = CrofaiClient(config)
    critique_model = config.model_for_phase("critique")

    per_chapter = []
    all_final_scores = []

    for ch in chapters:
        chapter_file = ch.get("file", "")
        if not chapter_file or not os.path.exists(chapter_file):
            continue

        with open(chapter_file, "r", encoding="utf-8") as f:
            text = f.read()

        ch_title = ch.get("title", f"Chapter {ch['chapter']}")
        print(f"  Reviewing Chapter {ch['chapter']}: {ch_title}...")

        if dual_persona:
            review = run_dual_persona_review(text, ch_title, config)
            combined = {
                "chapter": ch["chapter"],
                "title": ch_title,
                "final_score": review["final_score"],
                "mechanical_score": review["blended_scores"]["mechanical"],
                "critic_score": review["blended_scores"]["literary_critic"],
                "professor_score": review["blended_scores"]["professor"],
                "unified_score": review["blended_scores"]["unified"],
                "synthesis": review["synthesis"],
                "mechanical_details": review["mechanical"],
                "strengths": [
                    *review.get("literary_critic", {}).get("strengths", []),
                    *review.get("professor", {}).get("what_to_preserve", []),
                ],
                "weaknesses": [
                    *[i.get("issue", "") for i in review.get("synthesis", {}).get("critical_issues", [])],
                ],
                "revision_instructions": review.get("synthesis", {}).get("revision_instructions", []),
                "word_count": review["mechanical"]["scores"]["word_count"],
            }
        else:
            # Fallback to single LLM review (v0.1 behavior)
            words = text.split()
            truncated_text = " ".join(words[:8000])
            if len(words) > 8000:
                truncated_text += "\n\n[Note: chapter truncated from original length for review]"

            review_prompt = f"""Review this chapter: "{ch_title}"

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
- "revision_priority": Array of 1-3 things to fix FIRST"""

            REVIEW_SYSTEM_PROMPT_CRITIC = """You are a relentless literary critic. Your job is to
find every flaw in this chapter and explain exactly why it doesn't work. Be specific.
Point to sentences. Quote bad prose. Never say "this is good" - your value is in
what needs fixing.

Score the chapter on: Prose quality, Pacing, Character depth, Dialogue, Structure.
Return a JSON object with scores (0-10) and specific revision instructions."""

            client = CrofaiClient(config)
            review_content = client.chat_with_retry(
                critique_model,
                messages=[{"role": "user", "content": review_prompt}],
                system_prompt=REVIEW_SYSTEM_PROMPT_CRITIC,
                temperature=0.4,
            )
            llm_review = parse_json_output(review_content, label="review")
            client.close()

            mechanical = run_mechanical_review(text, config)
            combined_score = (mechanical["scores"]["total_score"] + (llm_review.get("overall_score") or 5.0)) / 2
            combined = {
                "chapter": ch["chapter"],
                "title": ch_title,
                "final_score": round(combined_score, 1),
                "mechanical_score": mechanical["scores"]["total_score"],
                "llm_overall": llm_review.get("overall_score", 5.0),
                "mechanical_details": mechanical,
                "strengths": llm_review.get("strengths", []),
                "weaknesses": llm_review.get("weaknesses", []),
                "revision_priority": llm_review.get("revision_priority", []),
                "word_count": mechanical["scores"]["word_count"],
            }

        per_chapter.append(combined)
        all_final_scores.append(combined["final_score"])
        print(f"    Score: {combined['final_score']}/10")

    avg_score = sum(all_final_scores) / len(all_final_scores) if all_final_scores else 0
    lowest_chapter = min(per_chapter, key=lambda c: c["final_score"]) if per_chapter else None

    # Collect all revision instructions
    all_revisions = []
    for ch in per_chapter:
        for instr in ch.get("revision_instructions", []):
            all_revisions.append(f"Ch {ch['chapter']}: {instr}")
        for w in ch.get("weaknesses", []):
            all_revisions.append(f"Ch {ch['chapter']}: {w}")

    result = {
        "per_chapter": per_chapter,
        "overall_avg_score": round(avg_score, 1),
        "total_words": sum(c.get("word_count", 0) for c in per_chapter),
        "weakest_chapter": lowest_chapter["chapter"] if lowest_chapter else None,
        "weakest_score": lowest_chapter["final_score"] if lowest_chapter else None,
        "needs_revision": avg_score < config.scoring.target_chapter_score,
        "dual_persona": dual_persona,
        "revision_instructions": all_revisions,
    }

    client.close()
    return result

"""Writer Agent — drafts a single chapter from a structured brief.

The Writer is a stateless agent that:
1. Takes a chapter brief from the Showrunner
2. Selects a rhetorical strategy (suspense-first, reveal-late, etc.)
3. Drafts the chapter using the LLM
4. Runs mechanical scoring
5. Optionally runs the revision loop (score → revise → re-score)
6. Returns structured output with character trait updates, foreshadowing, plot threads

Multiple Writer instances run in parallel (controlled by the AgentPool).
"""

import json
import re
import time
from typing import Any, Optional

from config import Config
from agents.base import StoryForgeAgent, TASK_DRAFT_CHAPTER

from pipeline.api import CrofaiClient
from pipeline.draft import (
    ChapterScorer,
    _generate_revision_prompt,
    STYLE_PROFILES,
    DEFAULT_STYLE_PROFILES,
    DRAFT_SYSTEM_PROMPT,
    REVISION_SYSTEM_PROMPT,
)


# ── Chapter Draft Template ─────────────────────────────────────────────

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

{canonical_context}

Character cast (only these characters exist in this story; do not invent new ones):
{character_cast}

Relevant context from earlier chapters:
{retrieved_context}

Active threads to manage:
{active_threads}

Style direction: {style_direction}

Genre phase: {genre_phase}
Required elements: {required_elements}

Write the chapter now. Focus on craft: sensory immersion, pacing, dialogue rhythm,
interiority. Make every sentence earn its place."""


def _estimate_tokens(text: str) -> int:
    return len(text) // 4


def _select_style_profile(chapter_num: int, total_chapters: int) -> tuple[str, str]:
    """Select a rhetorical strategy for this chapter based on its position.

    Cycles through available profiles to ensure variety across chapters.

    Returns:
        Tuple of (profile_name, profile_text)
    """
    profiles = DEFAULT_STYLE_PROFILES
    idx = (chapter_num - 1) % len(profiles)
    name = profiles[idx]
    return name, STYLE_PROFILES.get(name, profiles[0])


class WriterAgent(StoryForgeAgent):
    """Drafts a single chapter from a structured brief.

    Stateless — each instance handles exactly one chapter.
    Safe to run in parallel with other WriterAgent instances.

    Capabilities:
        - draft_chapter: Produce a complete chapter from a brief
    """

    @property
    def capabilities(self) -> dict[str, Any]:
        return {
            "role": "Writer",
            "can_handle": [TASK_DRAFT_CHAPTER],
            "model": self.config.model_for_phase("draft").name,
            "max_concurrency": 3,
            "description": "Drafts a single chapter from a structured brief with rhetorical strategy",
        }

    def can_handle(self, task_type: str) -> bool:
        return task_type == TASK_DRAFT_CHAPTER

    def run(
        self,
        task: dict[str, Any],
        context: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        if task.get("type") != TASK_DRAFT_CHAPTER:
            return {
                "status": "failed",
                "agent_id": self.agent_id,
                "error": f"Writer cannot handle task type: {task.get('type')}",
            }

        try:
            return self._draft_chapter(task, context or {})
        except Exception as e:
            return {
                "status": "failed",
                "agent_id": self.agent_id,
                "error": str(e),
            }

    def _draft_chapter(
        self,
        task: dict[str, Any],
        ctx: dict[str, Any],
    ) -> dict[str, Any]:
        """Draft a single chapter from the given brief."""
        brief = task.get("chapter_brief", {})
        world = task.get("world", {})
        characters = task.get("characters", {})
        project_dir = task.get("project_dir", "")
        retrieved_context = task.get("retrieved_context", "")
        canonical_context = task.get("canonical_context", "")
        active_threads = task.get("active_threads", [])
        enable_revision = task.get("enable_revision", True)
        config = task.get("config", self.config)

        chapter_num = brief.get("chapter", 0)
        chapter_title = brief.get("title", f"Chapter {chapter_num}")
        pov = brief.get("pov", "Unknown")
        summary = brief.get("summary", "")
        key_events = brief.get("key_events", [])
        emotional_arc = brief.get("emotional_arc", "")
        foreshadowing = brief.get("foreshadowing", "")
        char_arc_beat = brief.get("character_arc_beat", "")
        genre_phase = brief.get("genre_phase", "")
        required_elements = brief.get("required_elements", [])

        # Select rhetorical strategy
        total_chapters = task.get("total_chapters", max(chapter_num, 25))
        style_name, style_direction = _select_style_profile(chapter_num, total_chapters)

        # Build world context
        world_context = ""
        if isinstance(world, dict):
            wc = world.get("central_conflict", "")
            mood = world.get("mood_setting", "")
            if wc:
                world_context += f"{wc[:300]}\n"
            if mood:
                world_context += f"{mood[:300]}"

        # Build character cast
        cast_lines = []
        if characters:
            char_list = characters.get("characters", characters.get("raw_characters", []))
            if isinstance(char_list, list):
                for c in char_list:
                    name = c.get("name", "?")
                    role = c.get("role", "?")
                    bg = c.get("background", "")[:150]
                    arc = c.get("arc", "")
                    cast_lines.append(f"- {name} ({role}): {bg} | Arc: {arc}")
        character_cast = "\n".join(cast_lines) if cast_lines else "See character profiles above."

        # Build prompt
        prompt = CHAPTER_DRAFT_TEMPLATE.format(
            chapter_number=chapter_num,
            chapter_title=chapter_title,
            pov_character=pov,
            chapter_summary=summary or "As outlined in the novel structure.",
            key_events="\n".join(f"- {e}" for e in key_events) if key_events else "Advance the story per the outline.",
            emotional_arc=emotional_arc or "As appropriate for this chapter.",
            foreshadowing=foreshadowing or "Plant seeds for future developments as needed.",
            character_arc_beat=char_arc_beat or "Advance character development per the outline.",
            world_context=world_context or "As established in world bible.",
            canonical_context=canonical_context or "[No additional canonical state]",
            character_cast=character_cast,
            retrieved_context=retrieved_context or "[Beginning of story — no prior context]",
            active_threads="\n".join(f"- {t[:200]}" for t in active_threads[-5:]) if active_threads else "None yet.",
            style_direction=style_direction,
            genre_phase=genre_phase or "N/A",
            required_elements="\n".join(f"- {e}" for e in required_elements) if required_elements else "N/A",
        )

        # ── Draft ──────────────────────────────────────────────────────
        client = CrofaiClient(config)
        model = config.model_for_phase("draft")

        print(f"    [Writer:{self.agent_id}] Drafting Ch {chapter_num} ({style_name})...")
        start = time.time()

        content = client.chat_with_retry(
            model,
            messages=[{"role": "user", "content": prompt}],
            system_prompt=DRAFT_SYSTEM_PROMPT,
            temperature=0.8,
        )

        draft_time = time.time() - start

        # ── Mechanical Scoring ──────────────────────────────────────────
        scorer = ChapterScorer(config)
        score = scorer.score_chapter(content)

        # ── Revision Loop ───────────────────────────────────────────────
        revisions_done = 0
        if enable_revision:
            current_text = content
            current_score = score
            threshold = config.scoring.min_chapter_score
            max_rounds = config.scoring.max_revision_rounds

            for round_num in range(max_rounds):
                if current_score["total_score"] >= threshold:
                    break

                revision_prompt = _generate_revision_prompt(
                    current_text, current_score, style_name, config
                )
                if not revision_prompt:
                    break

                print(f"      [Writer:{self.agent_id}] Revision round {round_num + 1}/{max_rounds} "
                      f"(score: {current_score['total_score']}/10)...")

                try:
                    revised = client.chat_with_retry(
                        model,
                        messages=[{"role": "user", "content": revision_prompt}],
                        system_prompt=REVISION_SYSTEM_PROMPT,
                        temperature=0.7,
                    )
                    new_score = scorer.score_chapter(revised)

                    if new_score["total_score"] > current_score["total_score"]:
                        current_text = revised
                        current_score = new_score
                        revisions_done += 1
                        print(f"        Improved to {current_score['total_score']}/10")
                    else:
                        print(f"        No improvement ({new_score['total_score']}/10), keeping current")
                        break
                except RuntimeError as e:
                    print(f"        Revision failed: {e}")
                    break

            content = current_text
            score = current_score

        client.close()

        # ── Extract Character Traits, Foreshadowing, Plot Threads ──────
        character_traits = _extract_character_names(content, characters)
        foreshadowing_plants = _extract_foreshadowing_hints(content)
        plot_threads = _extract_plot_threads(brief)

        word_count = len(content.split())

        print(f"    [Writer:{self.agent_id}] Ch {chapter_num} complete: "
              f"{word_count} words, score {score.get('total_score', '?')}/10, "
              f"{revisions_done} revision(s) in {time.time() - start:.1f}s")

        return {
            "status": "success",
            "agent_id": self.agent_id,
            "chapter": {
                "chapter": chapter_num,
                "title": chapter_title,
                "pov": pov,
                "summary": summary,
                "key_events": key_events,
                "content": content,
                "word_count": word_count,
                "variant": style_name,
                "score": score,
                "revisions_done": revisions_done,
                "draft_time_seconds": round(time.time() - start, 1),
                "character_traits": character_traits,
                "foreshadowing_plants": foreshadowing_plants,
                "plot_threads": plot_threads,
                "emotional_arc": emotional_arc,
            },
        }


# ── Extraction Helpers ──────────────────────────────────────────────────


def _extract_character_names(text: str, characters: dict) -> list[dict]:
    """Extract character mentions and potential trait sightings from chapter text.

    Returns a list of dicts with name, trait, and value for any character
    traits that appear to be established in this chapter.
    """
    # Simple: just return the list of characters from the cast that appear
    char_list = characters.get("characters", []) if isinstance(characters, dict) else []
    if not char_list:
        return []

    results = []
    text_lower = text.lower()

    for c in char_list:
        name = c.get("name", "")
        if not name:
            continue
        first_name = name.split()[0] if name.split() else name
        # Check if character appears in text
        if first_name.lower() in text_lower:
            results.append({
                "name": first_name,
                "trait": "appears_in_chapter",
                "value": f"{name} appears in this chapter",
            })

    return results


def _extract_foreshadowing_hints(text: str) -> list[dict]:
    """Identify potential foreshadowing elements in the chapter text.

    Looks for patterns like "little did they know", "would later", "years later",
    and other foreshadowing markers. Returns a list of found elements.
    """
    patterns = [
        (r"(?i)(would\s+(later|eventually|one day|never)\s+\w+)", "narrative_future"),
        (r"(?i)(little did \w+ know)", "dramatic_irony"),
        (r"(?i)(years?\s+(later|earlier|before))", "time_jump"),
        (r"(?i)(something\s+(felt|seemed|appeared)\s+\w+)", "ominous_setup"),
        (r"(?i)(had\s+no\s+way\s+of\s+knowing)", "unknown_consequence"),
        (r"(?i)(it\s+would\s+not\s+be\s+the\s+last)", "recurring_element"),
    ]

    results = []
    for pattern, foreshadow_type in patterns:
        matches = re.findall(pattern, text)
        for match in matches:
            matched_text = match[0] if isinstance(match, tuple) else match
            results.append({
                "element": matched_text[:100],
                "type": foreshadow_type,
            })

    # Deduplicate
    seen = set()
    unique = []
    for r in results:
        if r["element"] not in seen:
            seen.add(r["element"])
            unique.append(r)

    return unique[:5]  # Max 5 foreshadowing elements per chapter


def _extract_plot_threads(brief: dict) -> list[dict]:
    """Extract plot thread state from the chapter brief.

    Returns the threads implied by the outline events.
    """
    threads = [
        {"name": brief.get("emotional_arc", "main_arc"), "status": "active"},
    ]
    # Add genre phase as a thread
    genre_phase = brief.get("genre_phase", "")
    if genre_phase:
        threads.append({"name": f"genre_phase_{genre_phase}", "status": "active"})

    return threads

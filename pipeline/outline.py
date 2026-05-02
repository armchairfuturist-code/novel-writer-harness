"""Outline phase - generate plot structure with acts, chapters, and story beats.

Uses DeepSeek (large context) for structural planning. Supports multiple story
structures (3-Act, Hero's Journey, Save the Cat!) configurable per project.
Each chapter gets a summary, key events, character POV, and emotional arc.
"""

import json
from typing import Optional

from config import Config
from pipeline.api import CrofaiClient

STORY_STRUCTURES = {
    "three_act": "Traditional 3-Act structure: Setup -> Confrontation -> Resolution",
    "hero_journey": "Hero's Journey / Monomyth: Ordinary World -> Call to Adventure -> ... -> Return",
    "save_the_cat": "Blake Snyder's 15-beat: Opening Image -> Theme Stated -> ... -> Final Image",
    "seven_point": "Dan Wells' 7-point: Hook -> Plot Turn 1 -> Pinch 1 -> Midpoint -> Pinch 2 -> Plot Turn 2 -> Resolution",
    "freytag": "Freytag's Pyramid: Exposition -> Rising Action -> Climax -> Falling Action -> Denouement",
}

OUTLINE_SYSTEM_PROMPT = """You are a master plot architect. Given a story's world,
characters, and project spec, produce a detailed chapter-by-chapter outline.
Each chapter must advance plot OR develop character - ideally both.
Ensure pacing, foreshadowing, and escalating stakes. Return valid JSON only."""

OUTLINE_USER_TEMPLATE = """Create a detailed chapter-by-chapter outline for this story:

Genre: {genre}
Premise: {premise}
Tone: {tone}
POV: {pov}
Target chapters: {target_chapters}
Story structure: {structure}

Character arcs overview:
{character_overview}

World context (key elements):
{world_context}

Return JSON with this structure:
{{
  "story_structure": "Name of structure used",
  "acts": [
    {{
      "act_number": 1,
      "name": "Act name",
      "summary": "2-3 sentence overview",
      "chapters": [
        {{
          "chapter": 1,
          "title": "Working chapter title",
          "pov": "POV character name",
          "summary": "2-3 sentence what happens",
          "key_events": ["Event 1", "Event 2", "Event 3"],
          "character_arc_beat": "How protagonist/others change here",
          "emotional_arc": "e.g., hope -> dread -> determination",
          "foreshadowing": "Seeds planted for later payoff"
        }}
      ]
    }}
  ],
  "major_plot_points": [
    {{"chapter": 5, "event": "Inciting Incident", "description": "..."}}
  ],
  "pacing_notes": "Overall pacing strategy"
}}
"""


def run_outline(spec: dict, world: dict, characters: dict, structure: str = "three_act") -> dict:
    """Generate chapter-by-chapter outline.

    Args:
        spec: Project specification from seed phase
        world: World bible from worldbuilding
        characters: Character profiles from character phase
        structure: Story structure key from STORY_STRUCTURES

    Returns:
        dict: Outline with acts, chapters, plot points, pacing
    """
    config = Config()
    client = CrofaiClient(config)
    model = config.model_for_phase("outline")
    structure_desc = STORY_STRUCTURES.get(structure, structure)

    char_overview = ""
    if isinstance(characters, dict):
        char_list = characters.get("characters", characters.get("raw_characters", []))
        if isinstance(char_list, list):
            parts = []
            for c in char_list:
                name = c.get("name", "?")
                role = c.get("role", "?")
                arc = c.get("arc", "")
                parts.append(f"- {name} ({role}): {arc}")
            char_overview = "\n".join(parts)

    world_context = ""
    if isinstance(world, dict):
        wc = world.get("central_conflict", "")
        factions = world.get("factions", [])
        if factions:
            wc += "\nFactions: " + ", ".join(
                f.get("name", "?") for f in factions[:4]
            )
        world_context = wc[:500]

    target_chapters = spec.get("target_chapters", 12)

    prompt = OUTLINE_USER_TEMPLATE.format(
        genre=spec.get("genre", "Unknown"),
        premise=spec.get("premise", "Unknown"),
        tone=spec.get("tone", "Neutral"),
        pov=spec.get("pov", "third limited"),
        target_chapters=target_chapters,
        structure=structure_desc,
        character_overview=char_overview or "See character profiles",
        world_context=world_context or "Not specified",
    )

    content = client.chat_with_retry(
        model,
        messages=[{"role": "user", "content": prompt}],
        system_prompt=OUTLINE_SYSTEM_PROMPT,
        temperature=0.7,
    )

    content = content.strip()
    if content.startswith("```"):
        lines = content.splitlines()
        cleaned = [l for l in lines if not l.startswith("```")]
        content = "\n".join(cleaned)

    try:
        outline = json.loads(content)
    except json.JSONDecodeError:
        start = content.find("{")
        end = content.rfind("}")
        if start != -1 and end != -1:
            outline = json.loads(content[start:end+1])
        else:
            outline = {"raw_outline": content}

    client.close()
    return outline

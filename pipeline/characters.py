"""Character generation phase - create character profiles with arcs and relationships.

Uses Kimi K2.6 (prose-optimized) for nuanced character creation.
Produces detailed profiles with motivations, flaws, growth arcs, and
inter-character relationship maps.
"""

import json
from typing import Optional

from config import Config
from pipeline.api import CrofaiClient, parse_json_output

CHAR_SYSTEM_PROMPT = """You are a character architect specializing in nuanced,
three-dimensional characters. Create characters with genuine interiority -
motivations that conflict, flaws that matter, and arcs that transform.
Avoid archetypes and stereotypes. Return valid JSON only."""

CHAR_USER_TEMPLATE = """Create rich character profiles for this story:

Genre: {genre}
Premise: {premise}
Tone: {tone}
World context: {world_context}

Return JSON with the following structure. Include 1 protagonist, 1-2 deuteragonists,
1 antagonist, and 2-3 supporting characters (6-7 total):

{{
  "characters": [
    {{
      "name": "Full name",
      "role": "protagonist/deuteragonist/antagonist/supporting",
      "age": "Age description (e.g. early 20s, middle-aged, 10 years old)",
      "appearance": "Physical description (2-3 sentences)",
      "personality": "Core traits, temperament, quirks",
      "background": "Relevant backstory (2-3 paragraphs)",
      "motivation": "What they want most",
      "flaw": "The flaw that holds them back",
      "secret": "Something hidden (1 sentence)",
      "arc": "How they change over the story - from X to Y",
      "voice": "Distinct speech patterns, dialect, tics",
      "relationships": [
        {{"with": "Other character name", "dynamic": "How they relate"}}
      ]
    }}
  ],
  "relationship_map": "2-3 sentence summary of the social/emotional web between characters",
  "pov_assignment": "Which characters narrate which acts/chapters"
}}
"""


def run_characters(spec: dict, world: dict) -> dict:
    """Generate character profiles from project spec and world context.

    Args:
        spec: Project specification from seed phase
        world: World bible from worldbuilding phase

    Returns:
        dict: Character profiles with arcs and relationship map
    """
    config = Config()
    client = CrofaiClient(config)
    model = config.model_for_phase("characters")

    world_context = ""
    if isinstance(world, dict):
        world_context = world.get("world_name", "") + "\n"
        factions = world.get("factions", [])
        if factions:
            faction_names = [f.get("name", "?") for f in factions[:3]]
            world_context += f"Key factions: {', '.join(faction_names)}"
        central_conflict = world.get("central_conflict", "")
        if central_conflict:
            world_context += f"\nConflict: {central_conflict[:300]}"

    prompt = CHAR_USER_TEMPLATE.format(
        genre=spec.get("genre", "Unknown"),
        premise=spec.get("premise", "Unknown"),
        tone=spec.get("tone", "Neutral"),
        world_context=world_context or "Not specified",
    )

    chars = client.chat_parse_with_retry(
        model,
        messages=[{"role": "user", "content": prompt}],
        system_prompt=CHAR_SYSTEM_PROMPT,
        label="characters",
        temperature=0.8,
    )

    client.close()
    return chars

"""Worldbuilding phase - generate a rich world bible from the project spec.

Uses DeepSeek (large context window, good at structured output) to produce
a comprehensive world document covering geography, history, factions, magic/tech
systems, cultures, and the central conflict landscape.
"""

import json
from typing import Optional

from config import Config
from pipeline.api import CrofaiClient, parse_json_output

WORLD_SYSTEM_PROMPT = """You are a master worldbuilder. Given a story project spec,
produce a richly detailed world bible. Focus on specificity and internal consistency.
Create a world that feels lived-in, not like a wiki article. Return valid JSON only."""

WORLD_USER_TEMPLATE = """Create a comprehensive world bible for this story:

Genre: {genre}
Premise: {premise}
Tone: {tone}
Themes: {themes}
Unique angle: {unique_angle}

Return JSON with these keys:
- "world_name": The name of the world/setting
- "geography": Key locations, climate, notable landmarks (3-5 paragraphs)
- "history": Timeline of major events relevant to the story (5-8 bullet points)
- "factions": Array of groups, each with: name, beliefs, goals, relationship_to_protagonist
- "power_system": If applicable, how magic/technology works (rules, limits, costs)
- "cultures": Dominant societal norms, taboos, class structures
- "central_conflict": The core tension driving the story (2-3 paragraphs)
- "mood_setting": Sensory details - what does this world look, sound, smell like?
"""


def run_worldbuilding(spec: dict) -> dict:
    """Generate world bible from project spec.

    Args:
        spec: Project specification dict from seed phase

    Returns:
        dict: World bible with geography, history, factions, etc.
    """
    config = Config()
    client = CrofaiClient(config)
    model = config.model_for_phase("worldbuilding")

    prompt = WORLD_USER_TEMPLATE.format(
        genre=spec.get("genre", "Unknown"),
        premise=spec.get("premise", "Unknown"),
        tone=spec.get("tone", "Neutral"),
        themes=json.dumps(spec.get("themes", [])),
        unique_angle=spec.get("unique_angle", ""),
    )

    world = client.chat_parse_with_retry(
        model,
        messages=[{"role": "user", "content": prompt}],
        system_prompt=WORLD_SYSTEM_PROMPT,
        label="worldbuilding",
        temperature=0.8,
    )

    client.close()
    return world

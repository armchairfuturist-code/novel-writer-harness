"""Seed phase - parse the user's story concept into a structured project spec.

Takes a free-text seed concept (~3 sentences) and uses DeepSeek (large context)
to produce a structured project specification: genre, premise, tone, POV, length,
and initial creative direction.
"""

import json
from typing import Optional

from config import Config
from pipeline.api import CrofaiClient

SEED_SYSTEM_PROMPT = """You are a professional story architect. Given a seed concept,
produce a structured project specification. Be specific and opinionated - don't
default to generic fantasy. Return valid JSON only, no markdown wrapping."""

SEED_USER_TEMPLATE = """Analyze this story seed concept and produce a JSON project spec:

Seed concept: {concept}

Return JSON with these exact keys:
- "title": Working title for the project
- "genre": Primary genre (and subgenre if applicable)
- "premise": 2-3 sentence premise
- "tone": Emotional register (e.g., "grim but hopeful", "lyrical and introspective")
- "pov": Point of view (first person / third limited / third omniscient / multi-POV)
- "tense": Past tense or present tense
- "target_length": Target word count (novella ~40K, novel ~80K, epic ~120K+)
- "target_chapters": Suggested number of chapters
- "themes": Array of 2-4 thematic pillars
- "unique_angle": What makes this story different from others in its genre
- "initial_direction": 3-5 sentence creative brief for the worldbuilding phase"""


def run_seed(concept: str) -> dict:
    """Parse a seed concept into a structured project spec.

    Args:
        concept: Free-text story concept (2-5 sentences)

    Returns:
        dict: Project specification with all keys from SEED_USER_TEMPLATE
    """
    config = Config()
    client = CrofaiClient(config)
    model = config.model_for_phase("seed")

    content = client.chat_with_retry(
        model,
        messages=[{"role": "user", "content": SEED_USER_TEMPLATE.format(concept=concept)}],
        system_prompt=SEED_SYSTEM_PROMPT,
        temperature=0.7,
    )

    # Extract JSON from response (handle markdown-wrapped responses gracefully)
    content = content.strip()
    if content.startswith("```"):
        lines = content.splitlines()
        cleaned = []
        in_code = False
        for line in lines:
            if line.startswith("```"):
                in_code = not in_code
                continue
            if in_code:
                cleaned.append(line)
        content = "\n".join(cleaned)
        if not content:
            content = "\n".join(lines)

    try:
        spec = json.loads(content)
    except json.JSONDecodeError:
        start = content.find("{")
        end = content.rfind("}")
        if start != -1 and end != -1:
            spec = json.loads(content[start:end+1])
        else:
            raise RuntimeError(f"Failed to parse seed output as JSON:\n{content[:500]}")

    required = ["genre", "premise", "tone", "target_chapters"]
    for key in required:
        if key not in spec:
            spec[key] = f"MISSING: {key}"

    client.close()
    return spec

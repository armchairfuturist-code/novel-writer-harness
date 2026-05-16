"""Outline phase - generate plot structure with acts, chapters, and story beats.

Uses DeepSeek (large context) for structural planning. Supports multiple story
structures (3-Act, Hero's Journey, Save the Cat!) configurable per project.
Each chapter gets a summary, key events, character POV, and emotional arc.
"""

import json
from typing import Optional

from config import Config
from pipeline.api import CrofaiClient, parse_json_output

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


def _generate_fallback_outline(spec: dict, characters: dict, num_chapters: int) -> dict:
    """Generate a simple outline from genre templates when the API is unavailable."""
    import json as _json, os as _os
    
    genre = spec.get("genre", "Unknown")
    
    # Map free-form genre strings to template filenames
    genre_lower = genre.lower()
    genre_map = {"mystery", "thriller", "romance", "fantasy", "sci-fi", "science fiction", "speculative"}
    template = {}
    for pattern in sorted(genre_map, key=len, reverse=True):
        if pattern in genre_lower:
            tmpl_file = "sci-fi" if "sci" in pattern else pattern
            tmpl_path = _os.path.join(_os.path.dirname(__file__), "..", "templates", tmpl_file + ".json")
            if _os.path.exists(tmpl_path):
                with open(tmpl_path) as f:
                    template = _json.load(f)
                break
    
    beats = template.get("beats", [])
    
    # Build POV list from characters
    char_list = characters.get("characters", [])
    protagonist = "Protagonist"
    pov_chars = []
    for c in char_list:
        name = c.get("name", "Character")
        role = c.get("role", "supporting")
        if role == "protagonist":
            protagonist = name
            pov_chars.insert(0, name)
        elif role in ("deuteragonist", "antagonist"):
            pov_chars.append(name)
        else:
            pov_chars.append(name)
    if not pov_chars:
        pov_chars = [protagonist]
    
    # Generate chapters from beats
    chapters = []
    for beat in beats:
        cr = beat.get("chapter_range", [1, num_chapters])
        phase = beat.get("phase", "").replace("_", " ").title()
        start_ch = cr[0]
        end_ch = min(cr[1], num_chapters)
        for ch_num in range(start_ch, end_ch + 1):
            if ch_num > num_chapters:
                break
            pov = pov_chars[(ch_num - 1) % len(pov_chars)]
            title = f"Chapter {ch_num}"
            if ch_num == start_ch and phase:
                title = phase
            chapters.append({
                "chapter": ch_num,
                "title": title,
                "pov": pov,
                "summary": beat.get("description", "The story continues."),
                "key_events": beat.get("required_elements", ["The narrative advances"]),
                "character_arc_beat": "",
                "emotional_arc": "",
                "foreshadowing": "",
            })
    
    # If no beats (genre not matched), generate simple chapter list
    if not chapters:
        for ch_num in range(1, num_chapters + 1):
            pov = pov_chars[(ch_num - 1) % len(pov_chars)]
            summaries = {1: "Establish the world and protagonist.", num_chapters // 2: "Midpoint revelation changes everything.", num_chapters: "Climax and resolution."}
            chapters.append({
                "chapter": ch_num,
                "title": f"Chapter {ch_num}",
                "pov": pov,
                "summary": summaries.get(ch_num, "The story progresses."),
                "key_events": ["Plot advances"],
                "character_arc_beat": "",
                "emotional_arc": "",
                "foreshadowing": "",
            })
    
    # Build acts grouping
    act_chapters = {}
    for ch in chapters:
        cn = ch["chapter"]
        act_num = 1
        for i, beat in enumerate(beats):
            cr = beat.get("chapter_range", [1, num_chapters])
            if cr[0] <= cn <= cr[1]:
                act_num = i + 1
                break
        act_chapters.setdefault(act_num, []).append(ch)
    
    acts = []
    for act_num in sorted(act_chapters.keys()):
        acts.append({
            "act_number": act_num,
            "name": f"Act {act_num}",
            "summary": f"The {_num_to_word(act_num).lower()} phase of the story.",
            "chapters": act_chapters[act_num],
        })
    
    outline = {
        "story_structure": "Three-act structure (fallback)",
        "acts": acts,
        "major_plot_points": [
            {"chapter": 1, "event": "Inciting Incident", "description": spec.get("premise", "")[:100]},
            {"chapter": num_chapters // 2, "event": "Midpoint", "description": "Central revelation"},
            {"chapter": num_chapters, "event": "Climax", "description": "Final confrontation"},
        ],
        "pacing_notes": f"{spec.get('tone', 'Standard')} pacing with escalating stakes.",
    }
    
    return outline


def _num_to_word(n: int) -> str:
    return ["First", "Second", "Third", "Fourth", "Fifth", "Sixth", "Seventh", "Eighth", "Ninth", "Tenth"][n - 1] if 1 <= n <= 10 else str(n)


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

    try:
        content = client.chat_with_retry(
            model,
            messages=[{"role": "user", "content": prompt}],
            system_prompt=OUTLINE_SYSTEM_PROMPT,
            temperature=0.7,
        )
        outline = parse_json_output(content, label="outline")
    except RuntimeError as api_err:
        print(f"  Outline API call failed: {api_err}")
        print(f"  Generating fallback outline from genre template.")
        outline = _generate_fallback_outline(spec, characters, target_chapters)

    client.close()

    # Validate: check that all named characters in the outline exist in the registry
    if isinstance(characters, dict):
        registered_names = set()
        for c in characters.get("characters", characters.get("raw_characters", [])):
            registered_names.add(c.get("name", "").lower().strip())
        registered_names.discard("")

        for act in outline.get("acts", []):
            for ch in act.get("chapters", []):
                pov = ch.get("pov", "")
                if pov and pov.lower().strip() not in registered_names:
                    tag = ch.get('chapter', '?')
                    print(f"  [WARN] Chapter {tag}: POV character '{pov}' is not in the character registry. "
                          f"Add it to characters.json or change the POV assignment.")
                # Check key_events for character references
                events = ch.get("key_events", [])
                if isinstance(events, list):
                    for event in events:
                        event_lower = event.lower()
                        import re
                        # Find capitalized multi-word phrases that look like character names
                        for match in re.finditer(r'\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\b', event):
                            name = match.group(0).lower()
                            if len(name) > 2 and name not in ('The', 'A', 'An', 'This', 'That', 'It', 'I', 'You', 'He', 'She', 'We', 'They', 'Chapter', 'We Need', 'Act'):
                                if name not in registered_names:
                                    print(f"  [WARN] Chapter {ch.get('chapter', '?')}: character '{match.group(0)}' may be an unregistered character. Add to characters.json.")

    return outline

"""Genre beat templates for the StoryForge pipeline.

Each template defines the narrative beats, tracking requirements,
and structural constraints for a specific genre.

Usage:
    from templates import get_template, list_templates
    template = get_template("mystery")
"""

import json
import os
from typing import Optional

_TEMPLATES_DIR = os.path.dirname(os.path.abspath(__file__))


def list_templates() -> list[str]:
    """List available genre templates."""
    templates = []
    for fn in sorted(os.listdir(_TEMPLATES_DIR)):
        if fn.endswith(".json") and fn != "__init__.py":
            templates.append(fn.replace(".json", ""))
    return templates


def get_template(genre: str) -> Optional[dict]:
    """Load a genre template by name.

    Args:
        genre: Genre name (e.g., 'mystery', 'thriller', 'romance')

    Returns:
        Template dict or None if not found
    """
    path = os.path.join(_TEMPLATES_DIR, f"{genre.lower()}.json")
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def get_beat_for_chapter(genre: str, chapter: int) -> Optional[dict]:
    """Get the beat phase for a specific chapter number.

    Args:
        genre: Genre name
        chapter: Chapter number (1-indexed)

    Returns:
        Beat dict or None if template or chapter not found
    """
    template = get_template(genre)
    if not template:
        return None
    for beat in template.get("beats", []):
        cr = beat.get("chapter_range", [0, 0])
        if cr[0] <= chapter <= cr[1]:
            return beat
    return None


def get_required_elements(genre: str, chapter: int) -> list[str]:
    """Get required elements for a specific chapter in a genre template."""
    beat = get_beat_for_chapter(genre, chapter)
    if beat:
        return beat.get("required_elements", [])
    return []


def get_tracking_items(genre: str) -> list[str]:
    """Get items that need tracking for this genre."""
    template = get_template(genre)
    if template:
        return template.get("tracking", {}).get("must_track", [])
    return []


def get_critical_items(genre: str) -> list[str]:
    """Get critical items that must not be lost for this genre."""
    template = get_template(genre)
    if template:
        return template.get("tracking", {}).get("critical_items", [])
    return []
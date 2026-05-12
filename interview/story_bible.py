"""Story Bible Compiler — maps structured interview answers to a pipeline-compatible spec.

Takes the raw output from `run_interview()` (a flat list of answer dicts) and
produces a `{"spec": {...}, "enrichments": {...}}` dict that the rest of the
StoryForge pipeline can consume directly in place of the seed-phase output.
"""

import re
from typing import Any


def compile_story_bible(interview_result: dict) -> dict:
    """Map structured interview answers to a pipeline-compatible spec dict.

    Args:
        interview_result: Dict from run_interview() with structure:
            {
                "version": int,
                "depth": str,
                "answers": [
                    {"question_id": str, "dimension": str, "question": str,
                     "answer": str, "is_thin": bool, "timestamp": str},
                    ...
                ],
                "thin_areas": list,
            }

    Returns:
        dict: {"spec": {...}, "enrichments": {...}}
            - spec: pipeline-compatible project specification (same shape as seed.py output)
            - enrichments: per-dimension answer packs for downstream phases
    """
    answers = interview_result.get("answers", [])
    index = _build_answer_index(answers)
    depth = interview_result.get("depth", "standard")

    # Core spec (pipeline-compatible, mirrors seed.py output shape)
    premise_raw = _extract_answer(index, "cp-01", "")
    title = _extract_title(premise_raw) or "Untitled Story"
    premise = premise_raw or "No premise provided."

    spec: dict[str, Any] = {
        "title": title,
        "premise": premise,
        "genre": _extract_answer(index, "cp-02", "Unknown"),
        "unique_angle": _extract_answer(index, "cp-03", ""),
        "tone": _extract_answer(index, "cp-06", "Neutral"),
        "tense": _extract_answer(index, "cp-08", "past tense"),
        "pov": _extract_answer(index, "cp-09", "third limited"),
        "target_length": _extract_answer(index, "cp-07", "novel"),
        "target_chapters": _infer_chapters(index),
        "themes": _extract_themes(index),
        "initial_direction": _build_initial_direction(index, premise),
        # Metadata
        "_source": "interview",
        "_depth": depth,
        "_thin_areas": interview_result.get("thin_areas", []),
    }

    # Enrichments — per-dimension answer packs for downstream phases
    enrichments = {
        "world": _compile_world_answers(index),
        "characters": _compile_character_answers(index),
        "plot": _compile_plot_answers(index),
        "theme_voice": _compile_theme_answers(index),
        "market": _compile_market_answers(index),
        "concept_premise": _compile_concept_answers(index, spec),
    }

    return {"spec": spec, "enrichments": enrichments}


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


def _build_answer_index(answers: list) -> dict:
    """Map question_id -> answer entry for O(1) lookup.

    Args:
        answers: List of answer dicts from the interview result.

    Returns:
        dict: question_id -> answer entry dict
    """
    return {a["question_id"]: a for a in answers if "question_id" in a}


def _extract_answer(index: dict, qid: str, default: str = "") -> str:
    """Pull an answer string from the index, with [SKIPPED] handling.

    Returns the default value if the question was skipped or not found.
    """
    entry = index.get(qid)
    if entry is None:
        return default
    answer = entry.get("answer", "")
    if answer == "[SKIPPED]":
        return default
    return answer


def _extract_title(premise_raw: str) -> str:
    """Extract a working title from the premise answer using first-sentence heuristic.

    Takes the first sentence of the premise (up to the first . ! or ?)
    and returns a cleaned, shortened version suitable as a working title.
    """
    if not premise_raw:
        return ""
    # Take first sentence
    match = re.split(r"[.!?]", premise_raw.strip())
    first_sentence = match[0].strip() if match else premise_raw.strip()
    # If the first sentence is absurdly long, truncate
    if len(first_sentence) > 80:
        first_sentence = first_sentence[:77] + "..."
    return first_sentence


def _infer_chapters(index: dict) -> int:
    """Infer chapter count from the target_length answer (cp-07).

    Heuristic mapping:
        "novella" / "short" / "novelette" -> 10
        "novel" / "standard" -> 18
        "epic" / "saga" / "series" -> 30
        default -> 18
    """
    length = _extract_answer(index, "cp-07", "").strip().lower()

    # Check for novella-like keywords
    if any(kw in length for kw in ("novella", "short", "novelette", "40k", "40,000", "50k", "50,000")):
        return 10
    # Check for epic-like keywords
    if any(kw in length for kw in ("epic", "saga", "series", "120k", "120,000", "100k", "100,000")):
        return 30
    # Default to novel-length
    return 18


def _extract_themes(index: dict) -> list[str]:
    """Extract themes from cp-12 answer, splitting on comma / 'and' / 'both-and'.

    Returns a list of cleaned theme strings.
    """
    raw = _extract_answer(index, "cp-12", "")
    if not raw:
        return []

    # Normalize separators: replace ' & ' and ' and ' with comma
    normalized = re.sub(r"\s+(&|and)\s+", ", ", raw)
    # Also handle "both X and Y" -> X, Y
    normalized = re.sub(r"(?i)both\s+", "", normalized)

    # Split on common delimiters
    parts = re.split(r"[,;/-]+", normalized)

    themes = []
    for part in parts:
        cleaned = part.strip().strip(".")
        if cleaned and len(cleaned) > 1:
            themes.append(cleaned)

    return themes


def _build_initial_direction(index: dict, premise: str) -> str:
    """Build a creative brief / initial direction from cp-04, cp-05, cp-01.

    Concatenates the central conflict, target audience, and premise into
    a multi-sentence creative brief for the worldbuilding phase.
    """
    central_conflict = _extract_answer(index, "cp-04", "")
    target_audience = _extract_answer(index, "cp-05", "")

    parts = []
    if central_conflict:
        parts.append(f"Central conflict: {central_conflict}")
    if premise:
        parts.append(f"Core premise: {premise}")
    if target_audience:
        parts.append(f"Target audience: {target_audience}")

    return " ".join(parts) if parts else premise


# ---------------------------------------------------------------------------
# Dimension-specific answer compilers (for enrichments)
# ---------------------------------------------------------------------------


def _compile_concept_answers(index: dict, spec: dict) -> dict:
    """Compile concept/premise dimension answers into a structured enrichment pack."""
    return {
        "central_conflict": _extract_answer(index, "cp-04", ""),
        "target_audience": _extract_answer(index, "cp-05", ""),
        "inciting_incident": _extract_answer(index, "cp-10", ""),
        "known_ending": _extract_answer(index, "cp-11", ""),
        "real_world_influences": _extract_answer(index, "cp-13", ""),
        "mood_after_opening": _extract_answer(index, "cp-14", ""),
        "standalone_or_series": _extract_answer(index, "cp-15", ""),
    }


def _compile_world_answers(index: dict) -> list[dict]:
    """Compile all ws-* (world setting) answers into an ordered list."""
    return _answers_by_prefix(index, "ws-")


def _compile_character_answers(index: dict) -> list[dict]:
    """Compile all ch-* (character) answers into an ordered list."""
    return _answers_by_prefix(index, "ch-")


def _compile_plot_answers(index: dict) -> list[dict]:
    """Compile all pl-* (plot structure) answers into an ordered list."""
    return _answers_by_prefix(index, "pl-")


def _compile_theme_answers(index: dict) -> list[dict]:
    """Compile all th-* (theme/voice) answers into an ordered list."""
    return _answers_by_prefix(index, "th-")


def _compile_market_answers(index: dict) -> list[dict]:
    """Compile all mk-* (market/comparisons) answers into an ordered list."""
    return _answers_by_prefix(index, "mk-")


def _answers_by_prefix(index: dict, prefix: str) -> list[dict]:
    """Return all answer entries whose question_id starts with the given prefix,
    sorted by question_id for stable ordering.
    """
    matched = [
        {
            "question_id": entry["question_id"],
            "question": entry.get("question", ""),
            "answer": entry.get("answer", ""),
            "is_thin": entry.get("is_thin", False),
        }
        for qid, entry in index.items()
        if qid.startswith(prefix)
    ]
    matched.sort(key=lambda x: x["question_id"])
    return matched

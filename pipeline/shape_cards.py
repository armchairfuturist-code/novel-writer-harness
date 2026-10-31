"""Fiction shape cards: one structure per chapter, sampled from a bank.

Longtail's core insight, applied to chapters: every model writes chapters in
the same few shapes, so a batch of chapters collapses onto one template.
This module rolls a chapter structure from a bank of human-plausible fiction
skeletons (OS-entropy draw, jittered axes so no two cards are copies) and
checks the finished draft against it. The card is structure - what happens
when - not prose. Prose quality stays with pipeline.prose_lab.

Design notes, with attribution:
- The sampler (bank, fit-to-material, OS-entropy draw, jittered axes,
  binding PRIORITY block) follows milesoncken/longtail's shape.py. The bank
  and every description here are written for this repo; longtail ships no
  license.
- Compound Writing's context contract puts structure at STYLE.md level: the
  card is the chapter's structure context, carried into the draft prompt.

Stdlib only, no network, no model calls.
"""

from __future__ import annotations

import json
import os
import re
import random
from typing import Any, Optional

from pipeline.prose_lab import measure

# ---------------------------------------------------------------------------
# Axis descriptions: what each value tells the writer to do.
# Written for fiction chapters; not copied from longtail.
# ---------------------------------------------------------------------------

D: dict[str, dict[str, str]] = {
    "opening_type": {
        "scene_dialogue": "Open in a scene with spoken dialogue; let the characters' voices carry the first beat.",
        "action_open": "Open in motion: the POV character is already acting when the chapter starts.",
        "interiority_open": "Open inside the POV character's head: a thought, a memory, a feeling.",
        "description_open": "Open with the place: what the POV character sees first.",
        "backstory_open": "Open with something that happened before this chapter - one sentence at most.",
        "weather_open": "Open with the sky, the light, or the season - atmosphere before action.",
    },
    "payoff_promise": {
        "opening": "Promise the chapter's payoff in the first paragraphs; the reader knows what this chapter is for.",
        "early": "Promise the payoff within the first section, after the opening beat.",
        "late": "Hold the payoff until late in the chapter; build toward it.",
        "never": "Never state the chapter's payoff; let the action and dialogue imply it.",
    },
    "organizing_unit": {
        "single_scene": "One scene, one continuous time and place.",
        "scene_and_sequel": "Scene then sequel: action, then the POV character's reaction to it.",
        "two_scenes": "Two scenes with a clear break between them.",
        "parallel_scenes": "Cut between two threads in the same chapter.",
    },
    "conclusion_behavior": {
        "cliffhanger": "End on a question or a threat the next chapter must answer.",
        "resolved": "End with the chapter's problem settled, even if a bigger one remains.",
        "new_question": "End by raising a question the chapter itself did not ask.",
        "image_stop": "End on a concrete image or object; explain nothing after it.",
        "abrupt_stop": "Just stop after the last beat; no wrap-up line.",
    },
    "dialogue_level": {
        "sparse": "Few spoken lines; let action and perception carry the chapter.",
        "moderate": "Some dialogue, spaced through the chapter.",
        "heavy": "Much of the chapter is spoken; keep tags simple.",
    },
    "sentence_complexity": {
        "simple": "Mostly short, simple sentences.",
        "mixed": "Mix short and long sentences unevenly.",
        "complex": "Long, clause-heavy sentences, with a few short ones.",
    },
    "paragraph_rhythm": {
        "uniform": "Keep paragraphs similar in size.",
        "varied": "Vary paragraph size a lot: one-liners and long blocks.",
    },
    "pov_distance": {
        "close": "Stay inside the POV character's skin; report only what they notice.",
        "distant": "Keep narrative space between the voice and the character.",
    },
    "tense": {
        "past": "Tell it in the past tense.",
        "present": "Tell it in the present tense.",
    },
    "information_density": {
        "low": "Few facts, revealed slowly.",
        "medium": "Steady new information, one thing at a time.",
        "high": "Dense with names, dates, and objects.",
    },
    "emotional_shift": {
        "yes": "The POV character ends the chapter feeling differently than they began.",
        "no": "Hold one emotional tone through the chapter.",
    },
}

AXES: list[str] = [
    "opening_type", "payoff_promise", "organizing_unit", "conclusion_behavior",
    "dialogue_level", "sentence_complexity", "paragraph_rhythm", "pov_distance",
    "tense", "information_density", "emotional_shift",
]

GROUPS: list[tuple[str, list[str]]] = [
    ("Opening", ["opening_type", "payoff_promise"]),
    ("Body", ["organizing_unit", "information_density", "emotional_shift"]),
    ("Ending", ["conclusion_behavior"]),
    ("Voice", ["pov_distance", "tense", "dialogue_level"]),
    ("Page", ["sentence_complexity", "paragraph_rhythm"]),
]

PRIORITY: list[str] = [
    "opening_type", "payoff_promise", "conclusion_behavior",
    "dialogue_level", "sentence_complexity",
]

PERTURBABLE: list[str] = [
    "opening_type", "conclusion_behavior", "dialogue_level",
    "paragraph_rhythm", "sentence_complexity", "pov_distance",
    "information_density", "emotional_shift",
]

# ---------------------------------------------------------------------------
# Bank: human-plausible fiction chapter skeletons. Abstract features only,
# no text. Sizes are soft word targets.
# ---------------------------------------------------------------------------

BANK: list[dict[str, Any]] = [
    {"id": "ch01_arrival", "words": 2500,
     "features": {"opening_type": "scene_dialogue", "payoff_promise": "opening",
                  "organizing_unit": "single_scene", "conclusion_behavior": "new_question",
                  "dialogue_level": "heavy", "sentence_complexity": "mixed",
                  "paragraph_rhythm": "varied", "pov_distance": "close", "tense": "past",
                  "information_density": "low", "emotional_shift": "yes"}},
    {"id": "quiet_reflection", "words": 1800,
     "features": {"opening_type": "interiority_open", "payoff_promise": "never",
                  "organizing_unit": "scene_and_sequel", "conclusion_behavior": "image_stop",
                  "dialogue_level": "sparse", "sentence_complexity": "mixed",
                  "paragraph_rhythm": "varied", "pov_distance": "close", "tense": "past",
                  "information_density": "low", "emotional_shift": "no"}},
    {"id": "action_chase", "words": 2200,
     "features": {"opening_type": "action_open", "payoff_promise": "late",
                  "organizing_unit": "single_scene", "conclusion_behavior": "cliffhanger",
                  "dialogue_level": "sparse", "sentence_complexity": "simple",
                  "paragraph_rhythm": "varied", "pov_distance": "close", "tense": "past",
                  "information_density": "medium", "emotional_shift": "yes"}},
    {"id": "reveal_chapter", "words": 3000,
     "features": {"opening_type": "description_open", "payoff_promise": "late",
                  "organizing_unit": "single_scene", "conclusion_behavior": "resolved",
                  "dialogue_level": "moderate", "sentence_complexity": "mixed",
                  "paragraph_rhythm": "varied", "pov_distance": "close", "tense": "past",
                  "information_density": "high", "emotional_shift": "yes"}},
    {"id": "dual_thread", "words": 2600,
     "features": {"opening_type": "scene_dialogue", "payoff_promise": "early",
                  "organizing_unit": "parallel_scenes", "conclusion_behavior": "new_question",
                  "dialogue_level": "heavy", "sentence_complexity": "mixed",
                  "paragraph_rhythm": "varied", "pov_distance": "distant", "tense": "past",
                  "information_density": "medium", "emotional_shift": "no"}},
    {"id": "present_pursuit", "words": 2000,
     "features": {"opening_type": "action_open", "payoff_promise": "opening",
                  "organizing_unit": "single_scene", "conclusion_behavior": "cliffhanger",
                  "dialogue_level": "moderate", "sentence_complexity": "simple",
                  "paragraph_rhythm": "varied", "pov_distance": "close", "tense": "present",
                  "information_density": "medium", "emotional_shift": "yes"}},
    {"id": "backstory_weight", "words": 2400,
     "features": {"opening_type": "backstory_open", "payoff_promise": "never",
                  "organizing_unit": "scene_and_sequel", "conclusion_behavior": "image_stop",
                  "dialogue_level": "moderate", "sentence_complexity": "complex",
                  "paragraph_rhythm": "uniform", "pov_distance": "distant", "tense": "past",
                  "information_density": "high", "emotional_shift": "no"}},
    {"id": "weather_open_chapter", "words": 1900,
     "features": {"opening_type": "weather_open", "payoff_promise": "early",
                  "organizing_unit": "single_scene", "conclusion_behavior": "resolved",
                  "dialogue_level": "sparse", "sentence_complexity": "simple",
                  "paragraph_rhythm": "uniform", "pov_distance": "close", "tense": "past",
                  "information_density": "low", "emotional_shift": "no"}},
    {"id": "tense_confrontation", "words": 2300,
     "features": {"opening_type": "scene_dialogue", "payoff_promise": "early",
                  "organizing_unit": "single_scene", "conclusion_behavior": "abrupt_stop",
                  "dialogue_level": "heavy", "sentence_complexity": "simple",
                  "paragraph_rhythm": "varied", "pov_distance": "close", "tense": "past",
                  "information_density": "low", "emotional_shift": "yes"}},
    {"id": "slow_reveal", "words": 2800,
     "features": {"opening_type": "description_open", "payoff_promise": "late",
                  "organizing_unit": "two_scenes", "conclusion_behavior": "image_stop",
                  "dialogue_level": "moderate", "sentence_complexity": "complex",
                  "paragraph_rhythm": "varied", "pov_distance": "close", "tense": "past",
                  "information_density": "low", "emotional_shift": "yes"}},
    {"id": "two_voices", "words": 2100,
     "features": {"opening_type": "scene_dialogue", "payoff_promise": "opening",
                  "organizing_unit": "two_scenes", "conclusion_behavior": "new_question",
                  "dialogue_level": "heavy", "sentence_complexity": "mixed",
                  "paragraph_rhythm": "varied", "pov_distance": "distant", "tense": "past",
                  "information_density": "medium", "emotional_shift": "no"}},
    {"id": "gentle_close", "words": 1700,
     "features": {"opening_type": "interiority_open", "payoff_promise": "never",
                  "organizing_unit": "scene_and_sequel", "conclusion_behavior": "resolved",
                  "dialogue_level": "sparse", "sentence_complexity": "simple",
                  "paragraph_rhythm": "uniform", "pov_distance": "close", "tense": "past",
                  "information_density": "low", "emotional_shift": "no"}},
]

# ---------------------------------------------------------------------------
# Material fit: a skeleton value can require a material flag the outline lacks.
# ---------------------------------------------------------------------------

_NEEDS: dict[tuple[str, str], str] = {
    ("opening_type", "scene_dialogue"): "dialogue",
    ("dialogue_level", "heavy"): "dialogue",
    ("dialogue_level", "moderate"): "dialogue",
    ("opening_type", "action_open"): "action",
}


def _needs(axis: str, value: Optional[str]) -> Optional[str]:
    return _NEEDS.get((axis, value))


def _missing(features: dict[str, str], flags: set[str]) -> list[str]:
    return [a for a in AXES if _needs(a, features.get(a)) is not None
            and _needs(a, features.get(a)) not in flags]


def _marginal_draw(bank: list[dict[str, Any]], axis: str, flags: set[str],
                   rng: random.Random, avoid: Optional[str] = None) -> Optional[str]:
    vals = [s["features"].get(axis) for s in bank]
    vals = [v for v in vals
            if v in D.get(axis, {})
            and not (_needs(axis, v) is not None and _needs(axis, v) not in flags)
            and v != avoid]
    return rng.choice(vals) if vals else None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def roll_card(flags: Optional[set[str]] = None, seed: Any = None) -> dict[str, Any]:
    """Roll one chapter shape card fit to the material flags.

    With no seed, draws from OS entropy. With a seed, the draw is deterministic
    (useful for tests and reproducible runs).
    """
    flags = set(flags or ())
    rng: random.Random = random.SystemRandom() if seed is None else random.Random(seed)
    ok = [s for s in BANK if not _missing(s["features"], flags)]
    pool = ok or BANK
    pick = rng.choice(pool)
    feats: dict[str, str] = dict(pick["features"])
    for a in _missing(feats, flags):
        v = _marginal_draw(BANK, a, flags, rng)
        if v is not None:
            feats[a] = v
    for a in rng.sample(PERTURBABLE, min(2, len(PERTURBABLE))):
        v = _marginal_draw(BANK, a, flags, rng, avoid=feats.get(a))
        if v is not None:
            feats[a] = v
    return {"id": pick["id"], "words": pick.get("words"), "features": feats}


def card_lines(card: dict[str, Any]) -> list[str]:
    """Human-readable instruction lines for the card, PRIORITY block first."""
    feats = card.get("features", {})
    lines: list[str] = [
        f"Shape card {card.get('id', '')} - chapter structure: follow every line."
    ]
    pri = [D[a][feats[a]] for a in PRIORITY if feats.get(a) in D.get(a, {})]
    if pri:
        lines.append("Priority (current models break these most):")
        for t in pri:
            lines.append(f"- {t}")
    for group, axes in GROUPS:
        block = [D[a][feats[a]] for a in axes if feats.get(a) in D.get(a, {})]
        if block:
            lines.append(f"{group}:")
            for t in block:
                lines.append(f"- {t}")
    return lines


# Bands in dialogue words per 1,000, sentence mean length, paragraph SD words.
_DIALOGUE_BANDS: dict[str, tuple[float, float]] = {
    "sparse": (0.0, 30.0), "moderate": (30.0, 150.0), "heavy": (150.0, float("inf"))}
_SENTENCE_BANDS: dict[str, tuple[float, float]] = {
    "simple": (0.0, 12.0), "mixed": (12.0, 22.0), "complex": (22.0, float("inf"))}
_PARAGRAPH_BANDS: dict[str, tuple[float, float]] = {
    "uniform": (0.0, 12.0), "varied": (12.0, float("inf"))}
_QUOTE_RE = re.compile(r'["\u201c\u201e]')


def _band_violation(rule: str, rate: float, band: tuple[float, float], fix: str) -> dict[str, Any]:
    low, high = band
    return {
        "rule": rule, "category": "shape", "count": 1,
        "rate_per_1k": round(rate, 1),
        "band": [low, None if high == float("inf") else high],
        "excess_per_1k": 0.0, "example": "", "fix": fix,
    }


def check_chapter(text: str, card: dict[str, Any]) -> list[dict[str, Any]]:
    """Measure the finished draft against its card.

    Returns violation dicts in the same shape as pipeline.prose_lab, so they
    can feed the same revision prompt. Stdlib-only measurement, no model.
    """
    feats = measure(text)
    violations: list[dict[str, Any]] = []
    cfeats = card.get("features", {})

    dl = cfeats.get("dialogue_level")
    if dl in _DIALOGUE_BANDS:
        rate = feats["dialogue_share"] * 1000.0
        low, high = _DIALOGUE_BANDS[dl]
        ok = rate >= low if high == float("inf") else low <= rate <= high
        if not ok:
            fix = ("Add spoken lines." if rate < low else "Cut some spoken lines.")
            violations.append(_band_violation(f"dialogue_{dl}", rate, (low, high), fix))

    sc = cfeats.get("sentence_complexity")
    if sc in _SENTENCE_BANDS:
        rate = feats["sentence_mean"]
        low, high = _SENTENCE_BANDS[sc]
        ok = rate >= low if high == float("inf") else low <= rate <= high
        if not ok:
            fix = ("Shorten the sentences." if rate < low else "Lengthen some sentences.")
            violations.append(_band_violation(f"sentence_{sc}", rate, (low, high), fix))

    pr = cfeats.get("paragraph_rhythm")
    if pr in _PARAGRAPH_BANDS:
        rate = feats["paragraph_sd"]
        low, high = _PARAGRAPH_BANDS[pr]
        ok = rate >= low if high == float("inf") else low <= rate <= high
        if not ok:
            fix = ("Vary paragraph sizes." if rate < low else "Keep paragraphs more even.")
            violations.append(_band_violation(f"rhythm_{pr}", rate, (low, high), fix))

    if cfeats.get("opening_type") == "scene_dialogue":
        if not _QUOTE_RE.search(text[:200]):
            violations.append({
                "rule": "opens_dialogue", "category": "shape", "count": 1,
                "rate_per_1k": 0.0, "band": [1.0, None], "excess_per_1k": 0.0,
                "example": "", "fix": "Open the first paragraph with spoken dialogue.",
            })

    return violations


# ---------------------------------------------------------------------------
# Flags from outline; durable card record next to revision memory.
# ---------------------------------------------------------------------------

_KEYWORD_FLAGS: dict[str, list[str]] = {
    "dialogue": ["said", "asks", "tells", "shouts", "whispers", "replies",
                 "answers", "conversation", "argument"],
    "action": ["runs", "fights", "chases", "escapes", "attacks", "battles",
               "flees", "strikes", "grabs", "rushes"],
    "reveal": ["reveals", "discovers", "learns", "secret", "clue", "truth",
               "uncovers", "finds"],
    "quiet": ["reflects", "remembers", "alone", "thinks", "mourns", "waits",
              "sits", "quiet", "memory", "memories", "grief", "silence"],
    "tension": ["threat", "danger", "fear", "risk", "deadline", "pursued",
                "watched"],
}


def flags_from(chapter_spec: dict[str, Any]) -> set[str]:
    """Derive material flags from an outline chapter spec."""
    text = " ".join(str(chapter_spec.get(k, "")) for k in
                    ("summary", "emotional_arc", "foreshadowing"))
    if isinstance(chapter_spec.get("key_events"), list):
        text += " " + " ".join(chapter_spec["key_events"])
    text = text.lower()
    flags: set[str] = set()
    for flag, kws in _KEYWORD_FLAGS.items():
        if any(kw in text for kw in kws):
            flags.add(flag)
    return flags


def save_card(project_dir: str, chapter_num: int,
              card: dict[str, Any], flags: set[str]) -> str:
    """Append one card line to quality/shape-cards.jsonl (append-only)."""
    qdir = os.path.join(project_dir, "quality")
    os.makedirs(qdir, exist_ok=True)
    path = os.path.join(qdir, "shape-cards.jsonl")
    entry = {"chapter": chapter_num, "card": card, "flags": sorted(flags)}
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry) + "\n")
    return path

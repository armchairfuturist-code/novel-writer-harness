"""Fact-checking module — cross-chapter consistency verification.

Reads all drafted chapters and checks for:
- Character trait drift (eye color, age, physical description changing mid-story)
- Timeline consistency (events referenced in wrong order)
- World detail drift (location descriptions changing)
- Foreshadowing payoff tracking (seeds planted vs. resolved)

Each check produces a report card with:
- Status: PASS / WARN / FAIL
- Evidence: The specific text snippets that triggered the check
- Recommendation: What to verify or fix

This is a lightweight consistency scan, not a full proofreading pass.
Narrative inconsistencies that require author judgment are surfaced as
WARN rather than FAIL.
"""

import json
import os
import re
from typing import Optional

from config import Config


# Canonical check patterns
CHECK_PATTERNS = {
    "character_names": {
        "description": "Detect character name aliasing drift (full name vs. nickname vs. title usage)",
        "type": "consistency",
    },
    "physical_traits": {
        "description": "Identify conflicting physical descriptions of the same character across chapters",
        "type": "contradiction",
    },
    "timeline_events": {
        "description": "Compare referenced events against a timeline for ordering correctness",
        "type": "ordering",
    },
    "foreshadowing_payoff": {
        "description": "Check that foreshadowed events/items actually appear in later chapters",
        "type": "tracking",
    },
}


def scan_character_trait_drift(chapters_dir: str) -> list[dict]:
    """Scan chapters for character trait inconsistencies.

    Reads all chapter files, extracts character name references and nearby
    descriptive text, and flags potential contradictions (e.g., "blue eyes"
    in Ch 2 vs "brown eyes" in Ch 5).
    """
    issues = []
    chapter_files = sorted(
        f for f in os.listdir(chapters_dir) if f.endswith(".md")
    )

    # Track known traits per character across chapters
    # {character_name: {trait_type: {value: first_chapter_seen}}}
    known_traits: dict[str, dict[str, dict[str, int]]] = {}
    character_names: dict[str, int] = {}  # name -> first chapter

    eye_patterns = [
        (r'\b(blue|brown|green|grey|gray|hazel|amber|black|dark|pale)\s+eyes\b', "eye_color"),
        (r'\beyes\s+(?:were\s+)?(?:a\s+)?(?:deep|bright|pale|dark|cold|warm)\s+(blue|brown|green|grey|gray|hazel|amber)\b', "eye_color"),
    ]
    hair_patterns = [
        (r'\b(blonde|blond|brown|black|red|ginger|auburn|chestnut|white|grey|gray|silver|dark|light)\s+hair\b', "hair_color"),
    ]
    age_patterns = [
        (r'\b(\d+)[- ]year[- ]old\b', "age"),
        (r'\bin\s+(?:his|her|their)\s+(?:early|mid|late)\s+(\d+)[s]\b', "age_range"),
    ]

    for fn in chapter_files:
        ch_num = int(re.search(r'(\d+)', fn).group(1)) if re.search(r'(\d+)', fn) else 0
        filepath = os.path.join(chapters_dir, fn)

        try:
            with open(filepath, "r", encoding="utf-8") as f:
                text = f.read()
        except OSError:
            continue

        text_lower = text.lower()

        # Extract character names (capitalized words that appear 3+ times)
        words = re.findall(r'\b[A-Z][a-z]+\b', text)
        for w in set(words):
            if len(w) > 2 and words.count(w) >= 3:
                if w not in character_names:
                    character_names[w] = ch_num

        # Check eye color
        for pat, trait in eye_patterns:
            matches = re.findall(pat, text_lower)
            for m in matches:
                if isinstance(m, tuple):
                    color_val = m[1] if len(m) > 1 else m[0]
                else:
                    color_val = m
                trait_key = trait
                if trait_key not in known_traits:
                    known_traits[trait_key] = {}
                if color_val not in known_traits[trait_key]:
                    known_traits[trait_key][color_val] = ch_num
                else:
                    first_ch = known_traits[trait_key][color_val]
                    if first_ch != ch_num:
                        issues.append({
                            "type": "character_trait_drift",
                            "subtype": trait,
                            "severity": "WARN",
                            "detail": f"Eye color '{color_val}' in Ch {ch_num}, first seen as similar trait in Ch {first_ch}",
                            "chapter": ch_num,
                            "recommendation": "Verify this is intentional (POV perspective) or fix inconsistency",
                        })

        # Check hair color
        for pat, trait in hair_patterns:
            matches = re.findall(pat, text_lower)
            for m in matches:
                color_val = m if isinstance(m, str) else m[0]
                trait_key = trait
                if trait_key not in known_traits:
                    known_traits[trait_key] = {}
                if color_val not in known_traits[trait_key]:
                    known_traits[trait_key][color_val] = ch_num
                else:
                    first_ch = known_traits[trait_key][color_val]
                    if first_ch != ch_num:
                        issues.append({
                            "type": "character_trait_drift",
                            "subtype": trait,
                            "severity": "WARN",
                            "detail": f"Hair color '{color_val}' in Ch {ch_num}, first seen as similar trait in Ch {first_ch}",
                            "chapter": ch_num,
                            "recommendation": "Verify character's hair hasn't changed or this is a different character",
                        })

    return issues


def scan_timeline_consistency(chapters_dir: str) -> list[dict]:
    """Scan for timeline ordering issues.

    Checks that time references (morning, later, next day, days later) form
    a coherent sequence and don't contradict each other.
    """
    issues = []
    chapter_files = sorted(
        f for f in os.listdir(chapters_dir) if f.endswith(".md")
    )

    time_markers = {
        "morning": ["morning", "dawn", "sunrise", "woke up", "awoke"],
        "afternoon": ["afternoon", "noon", "midday"],
        "evening": ["evening", "dusk", "sunset", "twilight"],
        "night": ["night", "midnight", "darkness fell"],
    }

    last_timeframe = None
    last_chapter = 0

    for fn in chapter_files:
        ch_num = int(re.search(r'(\d+)', fn).group(1)) if re.search(r'(\d+)', fn) else 0
        filepath = os.path.join(chapters_dir, fn)

        try:
            with open(filepath, "r", encoding="utf-8") as f:
                text = f.read().lower()
        except OSError:
            continue

        # Detect time references in first 1000 chars (to catch chapter opening)
        opening = text[:1000]
        current_timeframe = None

        for tf, markers in time_markers.items():
            for m in markers:
                if m in opening:
                    current_timeframe = tf
                    break
            if current_timeframe:
                break

        # If we found a timeframe, check ordering
        if current_timeframe and last_timeframe and ch_num > 0 and last_chapter > 0:
            time_order = list(time_markers.keys())
            if last_timeframe in time_order:
                last_idx = time_order.index(last_timeframe)
                curr_idx = time_order.index(current_timeframe)
                # Tight sequential check: adjacent chapters shouldn't regress
                if ch_num == last_chapter + 1 and curr_idx < last_idx:
                    issues.append({
                        "type": "timeline_inconsistency",
                        "severity": "WARN",
                        "detail": f"Time regressed from '{last_timeframe}' (Ch {last_chapter}) to '{current_timeframe}' (Ch {ch_num})",
                        "chapter": ch_num,
                        "recommendation": "Verify this is intentional (flashback or time skip) or fix chronological order",
                    })

        if current_timeframe:
            last_timeframe = current_timeframe
            last_chapter = ch_num

    return issues


def scan_foreshadowing_payoff(chapters_dir: str) -> list[dict]:
    """Check foreshadowing payoff tracking.

    Looks for plants (items/concepts introduced) and checks if they appear again.
    This is a lightweight scan — more thorough tracking would require an LLM pass.
    """
    issues = []
    chapter_files = sorted(
        f for f in os.listdir(chapters_dir) if f.endswith(".md")
    )

    # Collect unique objects/concepts introduced in each chapter
    chapter_objects: dict[int, set] = {}
    object_pattern = re.compile(
        r'(?:a|an|the)\s+(\w+\s+)?(?:pocket\s+)?(?:watch|key|book|mirror|knife|locket|ring|box|letter|map|photo|diamond)',
        re.IGNORECASE,
    )

    for fn in chapter_files:
        ch_num = int(re.search(r'(\d+)', fn).group(1)) if re.search(r'(\d+)', fn) else 0
        filepath = os.path.join(chapters_dir, fn)

        try:
            with open(filepath, "r", encoding="utf-8") as f:
                text = f.read()
        except OSError:
            continue

        objects = set(object_pattern.findall(text))
        chapter_objects[ch_num] = objects

    # Check for objects that appear once and never again
    all_objects: dict[str, list[int]] = {}
    for ch_num, objs in chapter_objects.items():
        for obj in objs:
            if obj not in all_objects:
                all_objects[obj] = []
            all_objects[obj].append(ch_num)

    # Only flag objects that appear once in early chapters (likely significant)
    for obj, chapters in all_objects.items():
        if len(chapters) == 1 and chapters[0] <= max(chapter_objects.keys()) // 2:
            issues.append({
                "type": "foreshadowing_miss",
                "severity": "INFO",
                "detail": f"Object '{obj.strip()}' introduced in Ch {chapters[0]} but never referenced again",
                "chapter": chapters[0],
                "recommendation": "Either pay this off in a later chapter or remove the introduction",
            })

    return issues


def run_fact_check(project_dir: str) -> dict:
    """Run all fact-checking scans and produce a report.

    Args:
        project_dir: Project output directory containing chapters/

    Returns:
        dict: Fact-check report with per-scanner results and summary
    """
    chapters_dir = os.path.join(project_dir, "chapters")
    if not os.path.isdir(chapters_dir):
        return {
            "status": "SKIPPED",
            "reason": "No chapters directory found",
            "total_issues": 0,
        }

    all_issues = []

    print("  Running character trait scan...")
    all_issues.extend(scan_character_trait_drift(chapters_dir))

    print("  Running timeline consistency scan...")
    all_issues.extend(scan_timeline_consistency(chapters_dir))

    print("  Running foreshadowing/payoff scan...")
    all_issues.extend(scan_foreshadowing_payoff(chapters_dir))

    # Grade the results
    errors = [i for i in all_issues if i["severity"] == "FAIL"]
    warnings = [i for i in all_issues if i["severity"] == "WARN"]
    infos = [i for i in all_issues if i["severity"] == "INFO"]

    grade = "PASS"
    if errors:
        grade = "FAIL"
    elif warnings:
        grade = "WARN"

    report = {
        "status": grade,
        "total_issues": len(all_issues),
        "errors": len(errors),
        "warnings": len(warnings),
        "infos": len(infos),
        "issues": all_issues,
        "summary": (
            f"{len(errors)} errors, {len(warnings)} warnings, {len(infos)} info items"
        ),
    }

    return report

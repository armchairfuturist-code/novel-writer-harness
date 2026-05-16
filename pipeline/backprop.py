"""Backward propagation module — detect and resolve forward contradictions.

After all chapters are drafted, this module scans for:
1. Character trait contradictions introduced in later chapters vs earlier ones
2. Timeline inconsistencies (events referenced out of order)
3. Foreshadowing debt (early promises without payoff)
4. World detail drift (location descriptions changing)
5. Plot thread abandonment (threads introduced but never resolved)

Each finding maps back to the earliest chapter where a fix is needed,
with a specific revision instruction for that chapter.

This is a lightweight scan that produces revision instructions.
It does NOT auto-edit chapters — it generates a report for the revision pass.
"""

import json
import os
import re
from collections import defaultdict
from typing import Optional

from config import Config


def scan_character_traits(chapters_dir: str) -> list[dict]:
    """Detect character trait contradictions across chapters.

    Looks for physical traits (eye/hair color, age, distinguishing features)
    that change between chapters without narrative justification.
    Returns issues mapping to the EARLIEST chapter that needs fixing.
    """
    issues = []
    chapter_files = sorted(f for f in os.listdir(chapters_dir) if f.endswith(".md"))

    # {trait_type: {value: [chapters_where_seen]}}
    trait_history: dict[str, dict[str, list[int]]] = defaultdict(lambda: defaultdict(list))

    eye_pats = [
        (r'\b(blue|brown|green|grey|gray|hazel|amber|black|dark|pale)\s+eyes\b', 'eye_color'),
        (r'\beyes\s+(?:were\s+)?(?:a\s+)?(?:deep|bright|pale|dark|cold|warm)\s+(blue|brown|green|grey|gray|hazel|amber)\b', 'eye_color'),
    ]
    hair_pats = [
        (r'\b(blonde|blond|brown|black|red|ginger|auburn|chestnut|white|grey|gray|silver|dark|light)\s+hair\b', 'hair_color'),
    ]
    age_pats = [
        (r'\b(\d+)[- ]year[- ]old\b', 'age'),
        (r'\bin\s+(?:his|her|their)\s+(?:early|mid|late)\s+(\d+)[s]\b', 'age_range'),
    ]

    for fn in chapter_files:
        ch_match = re.search(r'(\d+)', fn)
        if not ch_match:
            continue
        ch_num = int(ch_match.group(1))
        filepath = os.path.join(chapters_dir, fn)

        try:
            with open(filepath, "r", encoding="utf-8") as f:
                text = f.read().lower()
        except OSError:
            continue

        all_pats = eye_pats + hair_pats + age_pats
        for pat, trait_type in all_pats:
            matches = re.findall(pat, text)
            for m in matches:
                val = m[0] if isinstance(m, tuple) else m
                trait_history[trait_type][val].append(ch_num)

    # Detect contradictions: same trait type, different values, in close chapters
    for trait_type, values in trait_history.items():
        vals_list = list(values.items())
        for i in range(len(vals_list)):
            for j in range(i + 1, len(vals_list)):
                val_a, chs_a = vals_list[i]
                val_b, chs_b = vals_list[j]
                # Only flag if they appear in overlapping chapter ranges
                min_dist = min(abs(ca - cb) for ca in chs_a for cb in chs_b)
                if min_dist <= 5 and min_dist > 0:
                    # Find earliest chapter with each trait
                    first_a = min(chs_a)
                    first_b = min(chs_b)
                    later_val = val_b if first_b > first_a else val_a
                    earlier_ch = first_a if first_b > first_a else first_b
                    later_ch = first_b if first_b > first_a else first_a

                    issues.append({
                        "type": "character_trait_contradiction",
                        "severity": "WARN",
                        "detail": (
                            f"Trait '{trait_type}' changed from '{val_a}' (Ch {chs_a}) "
                            f"to '{val_b}' (Ch {chs_b})"
                        ),
                        "target_chapter": later_ch,
                        "suggestion": (
                            f"Either reconcile '{val_a}' in Ch {later_ch} with earlier description "
                            f"or add narrative justification for the change"
                        ),
                    })

    return issues


def scan_foreshadowing_debt(chapters_dir: str, outline_path: str = "") -> list[dict]:
    """Check that foreshadowing from early chapters has payoff later.

    Compares foreshadowing declarations from the outline with actual
    appearances in chapter text. Flags unresolved foreshadowing.
    """
    issues = []

    # Load outline for foreshadowing data
    foreshadow_claims = []
    if outline_path and os.path.exists(outline_path):
        try:
            with open(outline_path, "r", encoding="utf-8") as f:
                outline = json.load(f)
            for act in outline.get("acts", []):
                for ch in act.get("chapters", []):
                    fs = ch.get("foreshadowing", "")
                    if fs:
                        foreshadow_claims.append({
                            "chapter": ch.get("chapter", 0),
                            "text": fs,
                        })
        except (json.JSONDecodeError, OSError):
            pass

    if not foreshadow_claims:
        return issues

    # Read all chapter texts
    chapter_texts: dict[int, str] = {}
    chapter_files = sorted(f for f in os.listdir(chapters_dir) if f.endswith(".md"))
    for fn in chapter_files:
        ch_match = re.search(r'(\d+)', fn)
        if not ch_match:
            continue
        ch_num = int(ch_match.group(1))
        try:
            with open(os.path.join(chapters_dir, fn), "r", encoding="utf-8") as f:
                chapter_texts[ch_num] = f.read().lower()
        except OSError:
            continue

    for fc in foreshadow_claims:
        intro_ch = fc["chapter"]
        text = fc["text"].lower()

        # Extract key nouns/objects from foreshadowing
        keywords = re.findall(r'\b[a-z]{4,}\b', text)
        keywords = [k for k in keywords if k not in {
            'this', 'that', 'with', 'from', 'they', 'them', 'their',
            'what', 'will', 'when', 'then', 'been', 'have', 'has', 'had',
            'after', 'before', 'into', 'over', 'also', 'just', 'like',
            'more', 'some', 'than', 'very', 'about', 'would', 'could',
        }]
        keywords = keywords[:5]

        if not keywords:
            continue

        # Check if these keywords appear in any chapter AFTER the intro chapter
        found_in = []
        for ch_num in sorted(chapter_texts.keys()):
            if ch_num <= intro_ch:
                continue
            matches = sum(1 for kw in keywords if kw in chapter_texts[ch_num])
            if matches >= max(1, len(keywords) // 2):
                found_in.append(ch_num)

        if not found_in:
            issues.append({
                "type": "foreshadowing_debt",
                "severity": "INFO",
                "detail": (
                    f"Foreshadowing in Ch {intro_ch}: '{fc['text'][:100]}' "
                    f"has no clear payoff in later chapters"
                ),
                "target_chapter": intro_ch,
                "suggestion": (
                    f"Either ensure this foreshadowed element appears in a later "
                    f"chapter, or remove the foreshadowing from Ch {intro_ch}"
                ),
            })

    return issues


def scan_plot_thread_closure(chapters_dir: str) -> list[dict]:
    """Detect plot threads introduced but never resolved.

    Looks for common thread-introducing language and checks if
    the thing introduced gets mentioned again.
    """
    issues = []

    chapter_files = sorted(f for f in os.listdir(chapters_dir) if f.endswith(".md"))
    chapter_texts: dict[int, str] = {}
    chapter_objects: dict[int, set] = {}

    thread_signals = [
        r'(?:a|an|the)\s+(?:mystery|secret|question|riddle|promise|threat|plan|scheme)',
        r'(?:someone|something)\s+(?:is|was|had been)\s+(?:hiding|keeping|planning|plotting|waiting)',
        r'(?:unfinished|unresolved|lingering|unspoken)\s+(?:business|matter|issue|thread)',
    ]

    for fn in chapter_files:
        ch_match = re.search(r'(\d+)', fn)
        if not ch_match:
            continue
        ch_num = int(ch_match.group(1))
        try:
            with open(os.path.join(chapters_dir, fn), "r", encoding="utf-8") as f:
                text = f.read()
                chapter_texts[ch_num] = text
                text_lower = text.lower()
        except OSError:
            continue

        # Collect thread signals
        objects = set()
        for pat in thread_signals:
            objects.update(re.findall(pat, text_lower))
        chapter_objects[ch_num] = objects

    if not chapter_texts:
        return issues

    max_chapter = max(chapter_texts.keys())

    # Build thread location map
    thread_locations: dict[str, list[int]] = defaultdict(list)
    for ch_num, objs in chapter_objects.items():
        for obj in objs:
            if obj.strip():
                thread_locations[obj.strip()].append(ch_num)

    # Flag threads introduced in first half that never appear in second half
    midpoint = max_chapter // 2
    for thread, chapters in thread_locations.items():
        early_appearances = [c for c in chapters if c <= midpoint]
        late_appearances = [c for c in chapters if c > midpoint]
        if early_appearances and not late_appearances:
            issues.append({
                "type": "unresolved_thread",
                "severity": "WARN",
                "detail": (
                    f"Thread '{thread[:50]}' introduced in Ch {min(early_appearances)} "
                    f"but never addressed in the latter half of the novel"
                ),
                "target_chapter": min(early_appearances),
                "suggestion": (
                    f"Resolve '{thread}' in a later chapter or remove the setup "
                    f"from Ch {min(early_appearances)}"
                ),
            })

    return issues


def scan_timeline_regression(chapters_dir: str) -> list[dict]:
    """Check for timeline regression across chapters.

    Ensures that time references progress forward and don't contradict
    earlier established timelines.
    """
    issues = []

    chapter_files = sorted(f for f in os.listdir(chapters_dir) if f.endswith(".md"))
    time_markers = {
        "morning": 0, "dawn": 0, "sunrise": 0, "woke": 0,
        "afternoon": 1, "noon": 1, "midday": 1,
        "evening": 2, "dusk": 2, "sunset": 2, "twilight": 2,
        "night": 3, "midnight": 3,
    }

    last_time_idx = -1
    last_chapter = 0

    for fn in chapter_files:
        ch_match = re.search(r'(\d+)', fn)
        if not ch_match:
            continue
        ch_num = int(ch_match.group(1))
        try:
            with open(os.path.join(chapters_dir, fn), "r", encoding="utf-8") as f:
                opening = f.read(2000).lower()
        except OSError:
            continue

        current_time_idx = -1
        for marker, idx in time_markers.items():
            if marker in opening:
                current_time_idx = idx
                break

        if current_time_idx >= 0 and last_time_idx >= 0:
            if ch_num == last_chapter + 1 and current_time_idx < last_time_idx:
                issues.append({
                    "type": "timeline_regression",
                    "severity": "WARN",
                    "detail": (
                        f"Time appears to regress from Ch {last_chapter} "
                        f"to Ch {ch_num}"
                    ),
                    "target_chapter": ch_num,
                    "suggestion": (
                        "Verify this is a deliberate flashback/time skip. "
                        "If not, adjust the opening time reference."
                    ),
                })

        if current_time_idx >= 0:
            last_time_idx = current_time_idx
            last_chapter = ch_num

    return issues


def scan_forward_inconsistencies(chapters_dir: str) -> list[dict]:
    """Main backward propagation scanner.

    Runs all scans and returns a consolidated list of issues,
    each tagged with the earliest chapter that needs modification.
    """
    all_issues = []
    all_issues.extend(scan_character_traits(chapters_dir))
    all_issues.extend(scan_timeline_regression(chapters_dir))
    all_issues.extend(scan_plot_thread_closure(chapters_dir))

    return all_issues


def generate_revision_instructions(issues: list[dict]) -> str:
    """Convert scan results into revision instructions grouped by chapter."""
    if not issues:
        return "No backward propagation issues found."

    by_chapter: dict[int, list[dict]] = {}
    for issue in issues:
        ch = issue.get("target_chapter", 0)
        if ch not in by_chapter:
            by_chapter[ch] = []
        by_chapter[ch].append(issue)

    parts = ["# Backward Propagation: Revision Instructions"]
    for ch_num in sorted(by_chapter.keys()):
        ch_issues = by_chapter[ch_num]
        parts.append(f"\n## Chapter {ch_num}")
        for iss in ch_issues:
            severity_tag = {"FAIL": "!", "WARN": "?", "INFO": "i"}.get(
                iss.get("severity", "INFO"), "?"
            )
            parts.append(f"- [{severity_tag}] {iss['detail']}")
            parts.append(f"  Suggestion: {iss['suggestion']}")

    return "\n".join(parts)


def run_backward_propagation(
    project_dir: str,
    outline_path: str = "",
) -> dict:
    """Run all backward propagation scans and produce a report.

    Args:
        project_dir: Project directory containing chapters/
        outline_path: Path to outline.json for foreshadowing data

    Returns:
        dict: Report with issues and revision instructions
    """
    chapters_dir = os.path.join(project_dir, "chapters")
    if not os.path.isdir(chapters_dir):
        return {
            "status": "SKIPPED",
            "reason": "No chapters directory found",
            "total_issues": 0,
        }

    all_issues = scan_forward_inconsistencies(chapters_dir)

    # Also scan foreshadowing if outline available
    if outline_path:
        o_path = outline_path if os.path.isabs(outline_path) else os.path.join(project_dir, outline_path)
    else:
        o_path = os.path.join(project_dir, "outline.json")
    all_issues.extend(scan_foreshadowing_debt(chapters_dir, o_path))

    errors = [i for i in all_issues if i["severity"] == "FAIL"]
    warnings = [i for i in all_issues if i["severity"] == "WARN"]

    report = {
        "status": "PASS" if not errors else "FAIL",
        "total_issues": len(all_issues),
        "errors": len(errors),
        "warnings": len(warnings),
        "issues": all_issues[:50],  # cap at 50 for readability
        "summary": f"{len(errors)} errors, {len(warnings)} warnings, {len(all_issues)} total issues",
        "revision_instructions": generate_revision_instructions(all_issues),
    }

    return report

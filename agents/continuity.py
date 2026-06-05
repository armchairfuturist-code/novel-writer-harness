"""Continuity Agent — manages canonical state and runs backward propagation.

Maintains story consistency by:
1. Scanning for character trait drift across chapters
2. Detecting timeline regression
3. Verifying plot thread closure
4. Tracking foreshadowing debt (promises vs payoff)
5. Pushing/querying canonical state store

This agent is the "memory" of the multi-agent system.
"""

import json
import os
import re
import time
from typing import Any, Optional

from config import Config
from agents.base import StoryForgeAgent, TASK_SCAN_CONTINUITY, TASK_BACKWARD_PROPAGATE

from pipeline.canonical_store import CanonicalStore, FileCanonicalStore


# ── Scanner Patterns ────────────────────────────────────────────────────

# Character trait patterns to scan for consistency
TRAIT_PATTERNS = {
    "eye_color": [
        r"(?i)(\w+)\s*(?:'s\s*)?eyes?\s+(?:are|were|had|being|of)\s+(\w+)",
        r"(?i)(\w+)\s*had\s+(\w+)\s+eyes?",
    ],
    "hair_color": [
        r"(?i)(\w+)\s*(?:'s\s*)?hair\s+(?:is|was|fell|hung|tumbled|had|being)\s+(\w+)",
        r"(?i)(\w+)\s*had\s+(\w+)\s+hair",
    ],
    "height": [
        r"(?i)(\w+)\s+(?:was|stood|is|(?:'s\s+)?)\s*(tall|short|average|towering|lanky|petite|loomed|towered)",
    ],
    "age": [
        r"(?i)(\w+)\s+(?:was|is|turned|just\s+turned|about)\s+(\d+)",
    ],
}

# Temporal keywords for timeline regression detection
TEMPORAL_KEYWORDS = [
    "night", "morning", "afternoon", "evening", "dawn", "dusk",
    "midnight", "noon", "sunrise", "sunset",
    "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday",
    "january", "february", "march", "april", "may", "june",
    "july", "august", "september", "october", "november", "december",
    "winter", "spring", "summer", "fall", "autumn",
    "yesterday", "today", "tomorrow",
    "later", "earlier", "meanwhile", "simultaneously",
]

TEMPORAL_ORDER = {word: i for i, word in enumerate(TEMPORAL_KEYWORDS)}

# Plot thread keywords — hints that a thread was introduced
THREAD_INTRODUCTION_PATTERNS = [
    r"(?i)(introduce|reveal|discover|uncover|find|learn about)\s+(.+?)[.?:]",
    r"(?i)(a|the)\s+(mystery|secret|conspiracy|mysterious|strange)\s+(.+?)[.?:]",
    r"(?i)(someone|somebody)\s+(is|was|has been)\s+(.+?)[.?:]",
]

# Foreshadowing keywords — hints that something is set up for later
FORESHADOWING_PATTERNS = [
    r"(?i)(would\s+(later|eventually|one day|never)\s+\w+)",
    r"(?i)(little did \w+ know)",
    r"(?i)(something\s+(felt|seemed|appeared)\s+\w+)",
    r"(?i)(it\s+would\s+not\s+be\s+the\s+last)",
    r"(?i)(had\s+no\s+way\s+of\s+knowing)",
]


class ContinuityAgent(StoryForgeAgent):
    """Maintains story consistency through canonical state and backpropagation.

    Capabilities:
        - scan_continuity: Check canonical state consistency
        - backward_propagate: Full backward propagation scan
    """

    @property
    def capabilities(self) -> dict[str, Any]:
        return {
            "role": "Continuity",
            "can_handle": [TASK_SCAN_CONTINUITY, TASK_BACKWARD_PROPAGATE],
            "model": self.config.model_for_phase("scoring").name,
            "max_concurrency": 1,
            "description": "Scans for character drift, timeline issues, thread closure, foreshadowing debt",
        }

    def can_handle(self, task_type: str) -> bool:
        return task_type in {TASK_SCAN_CONTINUITY, TASK_BACKWARD_PROPAGATE}

    def run(
        self,
        task: dict[str, Any],
        context: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        task_type = task.get("type")

        if task_type == TASK_SCAN_CONTINUITY:
            return self._scan_continuity(task)
        elif task_type == TASK_BACKWARD_PROPAGATE:
            return self._backward_propagate(task)
        else:
            return {
                "status": "failed",
                "agent_id": self.agent_id,
                "error": f"Continuity cannot handle task type: {task_type}",
            }

    def _read_chapter_text(self, chapter_entry: dict) -> str:
        """Read chapter text from file or result entry."""
        ch_file = chapter_entry.get("file", "")
        ch_content = chapter_entry.get("content", "")

        if not ch_content and ch_file:
            try:
                with open(ch_file, "r", encoding="utf-8") as f:
                    content = f.read()
                lines = content.split("\n")
                filtered = [l for l in lines if not l.startswith("> POV:")]
                return "\n".join(filtered)
            except (OSError, IOError):
                pass
        return ch_content

    def _scan_continuity(self, task: dict[str, Any]) -> dict[str, Any]:
        """Scan canonical state for consistency.

        Checks:
        - Canonical store is healthy
        - Required entries exist (spec, world, characters, outline)
        - Chapter files are present

        Input:
            task['project_dir']: Project directory to scan

        Returns health report.
        """
        project_dir = task.get("project_dir", "")
        if not project_dir:
            return {
                "status": "failed",
                "agent_id": self.agent_id,
                "error": "No project directory provided",
            }

        issues = []

        # Check required files
        required_files = ["spec.json", "world.json", "characters.json", "outline.json"]
        for fname in required_files:
            fpath = os.path.join(project_dir, fname)
            if not os.path.exists(fpath):
                issues.append({
                    "severity": "FAIL",
                    "detail": f"Missing required file: {fname}",
                })

        # Check chapters
        chapters_dir = os.path.join(project_dir, "chapters")
        if os.path.isdir(chapters_dir):
            chapter_files = sorted(os.listdir(chapters_dir))
            if not chapter_files:
                issues.append({
                    "severity": "WARN",
                    "detail": "Chapters directory is empty",
                })
        else:
            issues.append({
                "severity": "FAIL",
                "detail": "Chapters directory does not exist",
            })

        # Check canonical state store
        canonical_path = os.path.join(project_dir, "canonical_state.json")
        if os.path.exists(canonical_path):
            try:
                with open(canonical_path, "r") as f:
                    state = json.load(f)
                if not isinstance(state, dict):
                    issues.append({
                        "severity": "WARN",
                        "detail": "Canonical state is malformed (not a dict)",
                    })
            except (json.JSONDecodeError, OSError):
                issues.append({
                    "severity": "WARN",
                    "detail": "Cannot parse canonical_state.json",
                })
        else:
            issues.append({
                "severity": "INFO",
                "detail": "Canonical state not yet created (expected before first draft)",
            })

        return {
            "status": "success" if not any(i["severity"] == "FAIL" for i in issues) else "failed",
            "agent_id": self.agent_id,
            "project_dir": project_dir,
            "total_issues": len(issues),
            "issues": issues,
        }

    def _backward_propagate(self, task: dict[str, Any]) -> dict[str, Any]:
        """Run full backward propagation scan on all chapters.

        Checks:
        1. Character trait drift (e.g., eye color changes across chapters)
        2. Timeline regression (temporal keywords out of order)
        3. Plot thread closure (threads introduced vs resolved)
        4. Foreshadowing debt (setups without payoffs)

        Input:
            task['project_dir']: Project directory
            task['chapters']: List of chapter result dicts

        Returns scan report with all issues.
        """
        project_dir = task.get("project_dir", "")
        chapters = task.get("chapters", [])
        canonical_store = task.get("canonical_store")

        if not chapters:
            chapters_dir = os.path.join(project_dir, "chapters")
            if os.path.isdir(chapters_dir):
                chapters = []
                for fn in sorted(os.listdir(chapters_dir)):
                    if fn.endswith(".md"):
                        chapters.append({
                            "chapter": len(chapters) + 1,
                            "file": os.path.join(chapters_dir, fn),
                            "title": fn.replace(".md", ""),
                        })

        if not chapters:
            return {
                "status": "skipped",
                "agent_id": self.agent_id,
                "total_issues": 0,
                "issues": [],
                "summary": "No chapters to scan",
            }

        # Read all chapter texts
        chapter_texts = {}
        for ch in chapters:
            ch_num = ch.get("chapter", 0)
            text = self._read_chapter_text(ch)
            if text:
                chapter_texts[ch_num] = text

        all_issues = []

        # ── 1. Character Trait Drift ──
        drift_issues = self._scan_trait_drift(chapter_texts)
        all_issues.extend(drift_issues)

        # ── 2. Timeline Regression ──
        timeline_issues = self._scan_timeline(chapter_texts)
        all_issues.extend(timeline_issues)

        # ── 3. Plot Thread Closure ──
        thread_issues = self._scan_plot_threads(chapter_texts)
        all_issues.extend(thread_issues)

        # ── 4. Foreshadowing Debt ──
        foreshadow_issues = self._scan_foreshadowing(chapter_texts)
        all_issues.extend(foreshadow_issues)

        # Classify by severity
        fail_count = sum(1 for i in all_issues if i["severity"] == "FAIL")
        warn_count = sum(1 for i in all_issues if i["severity"] == "WARN")
        info_count = sum(1 for i in all_issues if i["severity"] == "INFO")

        if fail_count > 0:
            status = "FAIL"
            summary = f"{fail_count} critical issue(s) found — manual review recommended"
        elif warn_count > 0:
            status = "STALLED" if warn_count > 3 else "PASS"
            summary = f"{warn_count} warning(s) found, {info_count} info item(s)"
        else:
            status = "PASS"
            summary = "No issues detected — manuscript is consistent"

        return {
            "status": status,
            "agent_id": self.agent_id,
            "total_issues": len(all_issues),
            "fail_count": fail_count,
            "warn_count": warn_count,
            "info_count": info_count,
            "summary": summary,
            "issues": all_issues,
            "scanned_chapters": len(chapter_texts),
        }

    # ── Scanner: Character Trait Drift ──

    def _scan_trait_drift(self, chapter_texts: dict[int, str]) -> list[dict]:
        """Scan for character trait values that change between chapters."""
        issues = []
        # Track (character, trait_type) -> [(chapter, value), ...]
        trait_log: dict[tuple[str, str], list[tuple[int, str]]] = {}

        for ch_num in sorted(chapter_texts.keys()):
            text = chapter_texts[ch_num]
            for trait_type, patterns in TRAIT_PATTERNS.items():
                for pattern in patterns:
                    for match in re.finditer(pattern, text):
                        name = match.group(1).strip()
                        value = match.group(2).strip()
                        key = (name.lower(), trait_type)
                        if key not in trait_log:
                            trait_log[key] = []
                        trait_log[key].append((ch_num, value))

        # Check for drift
        for (name, trait_type), entries in trait_log.items():
            unique_values = set(v for _, v in entries)
            if len(unique_values) > 1:
                chapters_str = ", ".join(f"Ch {c}='{v}'" for c, v in entries)
                issues.append({
                    "severity": "FAIL",
                    "type": "trait_drift",
                    "detail": f"'{name.title()}' {trait_type} changes: {chapters_str}",
                    "suggestion": "Reconcile trait values across chapters",
                })

        return issues

    # ── Scanner: Timeline Regression ──

    def _scan_timeline(self, chapter_texts: dict[int, str]) -> list[dict]:
        """Scan for temporal keyword order violations."""
        issues = []
        chapter_sequences: dict[int, list[str]] = {}

        for ch_num in sorted(chapter_texts.keys()):
            text = chapter_texts[ch_num].lower()
            found = []
            for word in TEMPORAL_KEYWORDS:
                if re.search(r'\b' + re.escape(word) + r'\b', text):
                    found.append(word)
            chapter_sequences[ch_num] = found

        # Check for temporal keyword order across chapters
        prev_max_order = -1
        for ch_num in sorted(chapter_sequences.keys()):
            words = chapter_sequences[ch_num]
            if not words:
                continue

            # Get the maximum temporal order value for this chapter
            max_order = max(TEMPORAL_ORDER.get(w, -1) for w in words)

            if max_order < prev_max_order and max_order >= 0:
                issues.append({
                    "severity": "WARN",
                    "type": "timeline_regression",
                    "detail": f"Ch {ch_num} contains earlier temporal keywords than previous chapters — possible regression",
                    "suggestion": "Verify chapter chronological ordering",
                })

            prev_max_order = max(prev_max_order, max_order)

        return issues

    # ── Scanner: Plot Thread Closure ──

    def _scan_plot_threads(self, chapter_texts: dict[int, str]) -> list[dict]:
        """Scan for plot threads introduced but not resolved."""
        issues = []
        thread_introductions: dict[str, int] = {}
        thread_resolutions: dict[str, int] = {}
        total_chapters = max(chapter_texts.keys()) if chapter_texts else 0

        # Rough heuristic: look for thread introduction and resolution keywords
        resolution_signals = [
            r"(?i)(revealed|solved|found|discovered|uncovered|resolved|escaped|defeated|won|lost|destroy|completed|ended)",
        ]

        for ch_num in sorted(chapter_texts.keys()):
            text = chapter_texts[ch_num]

            # Detect introductions
            for pattern in THREAD_INTRODUCTION_PATTERNS:
                for match in re.finditer(pattern, text):
                    thread_key = match.group(0)[:80].lower()
                    if thread_key not in thread_introductions:
                        thread_introductions[thread_key] = ch_num

            # Detect resolutions
            for pattern in resolution_signals:
                for match in re.finditer(pattern, text):
                    context_start = max(0, match.start() - 30)
                    context_end = min(len(text), match.end() + 30)
                    snippet = text[context_start:context_end].strip()
                    key = snippet[:80].lower()
                    thread_resolutions[key] = ch_num

        # Check for introduced threads that aren't resolved
        unresolved_count = 0
        for intro_key, intro_ch in thread_introductions.items():
            # Skip threads introduced late (last 25% of novel)
            if intro_ch >= total_chapters * 0.75:
                continue

            # Check if any resolution key overlaps with this thread
            if not any(k in intro_key or intro_key in k for k in thread_resolutions):
                if unresolved_count < 5:  # Limit to top issues
                    issues.append({
                        "severity": "WARN",
                        "type": "unresolved_thread",
                        "detail": f"Potential thread introduced in Ch {intro_ch}: '{intro_key[:100]}...'",
                        "suggestion": "Ensure this thread has a payoff later in the manuscript",
                    })
                unresolved_count += 1

        return issues

    # ── Scanner: Foreshadowing Debt ──

    def _scan_foreshadowing(self, chapter_texts: dict[int, str]) -> list[dict]:
        """Scan for foreshadowing elements that may be unpaid."""
        issues = []
        foreshadow_log: list[tuple[int, str, str]] = []

        for ch_num in sorted(chapter_texts.keys()):
            text = chapter_texts[ch_num]
            for pattern in FORESHADOWING_PATTERNS:
                for match in re.finditer(pattern, text):
                    foreshadow_log.append((ch_num, match.group(0), pattern))

        # Report on foreshadowing density
        if len(foreshadow_log) > 20:
            issues.append({
                "severity": "INFO",
                "type": "foreshadowing_density",
                "detail": f"High foreshadowing density: {len(foreshadow_log)} instances across {len(chapter_texts)} chapters",
                "suggestion": "Verify all foreshadowing elements have corresponding payoffs",
            })

        return issues

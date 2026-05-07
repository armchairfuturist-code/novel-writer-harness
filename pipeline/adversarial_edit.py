"""Adversarial editing pass — tighten prose by cutting unnecessary words.

Inspired by autonovel's adversarial editing. After all chapters are drafted,
this module:

1. Asks the LLM to identify the weakest 15% of each chapter
2. Classifies each cut (filler, redundancy, over-explanation, weak verb,
   telling-not-showing, pacing drag)
3. Produces a cut list and an edited chapter

The editor is adversarial: its job is to cut, not preserve. Each cut must
be justified by at least one classification category.

Also includes a standalone mechanical "tighten" pass that's faster/cheaper
(uses regex patterns) for quick cleanup without LLM calls.
"""

import json
import os
import re
from collections import defaultdict
from typing import Optional

from config import Config
from pipeline.api import CrofaiClient, parse_json_output


EDITOR_SYSTEM_PROMPT = """You are a ruthless developmental editor. Your job is to cut
the weakest 15% of this chapter without losing voice, plot, or character.

Cut only what makes the chapter weaker:
- Filler phrases that add nothing
- Redundant descriptions (we already know what the room looks like)
- Over-explanation (trust the reader)
- Weak verbs replaced with strong ones
- Telling instead of showing
- Scenes/paragraphs that drag pacing

Return JSON with:
- "cuts": Array of {"text": "exact text to cut", "category": "filler"/"redundancy"/"over_explanation"/"weak_verb"/"telling"/"pacing_drag", "justification": "why this should go"}
- "new_text": The full chapter with all cuts applied
- "words_removed": integer count
- "original_word_count": integer
"""


CUT_CATEGORIES = {
    "filler": "Phrases that add nothing: 'in order to', 'the fact that', 'it was at this point', 'needless to say'",
    "redundancy": "Descriptions that repeat what was already established",
    "over_explanation": "Explaining what the reader already inferred from context",
    "weak_verb": "Passive constructions, 'was being', 'started to', 'began to' where a strong verb works",
    "telling": "'He felt angry' instead of showing the anger through action/dialogue",
    "pacing_drag": "Scenes or paragraphs that slow momentum without purpose",
}

# Mechanical tightening patterns (no LLM needed)
MECHANICAL_PATTERNS = [
    (r'\bin order to\b', 'to'),
    (r'\bthe fact that\b', 'that'),
    (r'\bit was at this point that\b', 'then'),
    (r'\bat this point in time\b', 'now'),
    (r'\bin the event that\b', 'if'),
    (r'\bdue to the fact that\b', 'because'),
    (r'\bin spite of the fact that\b', 'although'),
    (r'\bin the process of\b', ''),
    (r'\bfor the purpose of\b', 'to'),
    (r'\bwith the result that\b', 'so'),
    (r'\bon the occasion of\b', 'when'),
    (r'\bvery\b', ''),
    (r'\bquite\b', ''),
    (r'\bliterally\b', ''),
    (r'\bstarted to\b', ''),
    (r'\bbegan to\b', ''),
    (r'\bbegun to\b', ''),
    (r'\bseemed to\b', ''),
    (r'\bappeared to\b', ''),
]


def mechanical_tighten(text: str) -> tuple[str, int]:
    """Fast mechanical tightening pass using regex patterns.

    Replaces/removes common filler phrases. Returns (tightened_text, cuts_made).

    This runs before the LLM adversarial pass and costs nothing.
    """
    total_cuts = 0
    for pattern, replacement in MECHANICAL_PATTERNS:
        count_before = len(re.findall(pattern, text, re.IGNORECASE))
        text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
        total_cuts += count_before

    # Collapse multiple spaces
    text = re.sub(r' {2,}', ' ', text)
    text = re.sub(r'\n{3,}', '\n\n', text)

    return text.strip(), total_cuts


def adversarial_edit_chapter(
    chapter_text: str,
    chapter_title: str,
    client: CrofaiClient,
    model,
    target_cut_pct: float = 0.15,
) -> dict:
    """Run LLM adversarial editing on a single chapter.

    Args:
        chapter_text: Full chapter text
        chapter_title: Chapter title for context
        target_cut_pct: Target percentage of words to cut (0.0 - 1.0)

    Returns:
        dict with keys: new_text, cuts, words_removed, original_word_count
    """
    # First run mechanical pass (free)
    mechanically_edited, mechanical_cuts = mechanical_tighten(chapter_text)
    initial_words = len(chapter_text.split())
    after_mech_words = len(mechanically_edited.split())
    mech_removed = initial_words - after_mech_words

    words = mechanically_edited.split()
    if len(words) > 8000:
        truncated = " ".join(words[:8000])
        truncated += "\n\n[Note: truncated from longer original for editing]"
    else:
        truncated = mechanically_edited

    prompt = f"""Edit this chapter: "{chapter_title}"

Target: Cut approximately {int(target_cut_pct * 100)}% of the words.
Only cut what makes the chapter weaker. Preserve voice, character, and plot.

{truncated}

Return the complete JSON object as specified."""

    try:
        content = client.chat_with_retry(
            model,
            messages=[{"role": "user", "content": prompt}],
            system_prompt=EDITOR_SYSTEM_PROMPT,
            temperature=0.3,
        )

        edit_result = parse_json_output(content, label="adversarial_edit")

        new_text = edit_result.get("new_text", mechanically_edited)
        cuts = edit_result.get("cuts", [])
        words_removed = edit_result.get("words_removed", 0)

        return {
            "new_text": new_text,
            "cuts": cuts,
            "words_removed": words_removed + mech_removed,
            "mechanical_cuts": mechanical_cuts,
            "original_word_count": initial_words,
            "new_word_count": len(new_text.split()),
            "category_breakdown": _categorize_cuts(cuts),
        }
    except (RuntimeError, Exception) as e:
        # Fallback: just return mechanically tightened text
        return {
            "new_text": mechanically_edited,
            "cuts": [],
            "words_removed": mech_removed,
            "mechanical_cuts": mechanical_cuts,
            "original_word_count": initial_words,
            "new_word_count": after_mech_words,
            "category_breakdown": {"mechanical": mechanical_cuts},
            "error": str(e),
        }


def _categorize_cuts(cuts: list[dict]) -> dict:
    """Summarize cuts by category."""
    breakdown: dict = defaultdict(int)
    for cut in cuts:
        cat = cut.get("category", "other")
        breakdown[cat] += 1
    return dict(breakdown)


def run_adversarial_edit(
    project_dir: str,
    config: Optional[Config] = None,
    target_cut_pct: float = 0.15,
    edit_all: bool = True,
) -> dict:
    """Run adversarial editing on all chapters in a project.

    Args:
        project_dir: Project directory containing chapters/
        config: Config override
        target_cut_pct: Target cut percentage
        edit_all: If True, edit all chapters. If False, only score + report.

    Returns:
        dict: Report with per-chapter results
    """
    config = config or Config()
    client = CrofaiClient(config)
    model = config.model_for_phase("draft")  # Use drafting model for editing

    chapters_dir = os.path.join(project_dir, "chapters")
    if not os.path.isdir(chapters_dir):
        return {
            "status": "SKIPPED",
            "reason": "No chapters directory found",
        }

    chapter_files = sorted(f for f in os.listdir(chapters_dir) if f.endswith(".md"))
    results = []
    total_words_removed = 0
    total_words_original = 0

    for fn in chapter_files:
        ch_match = re.search(r'(\d+)', fn)
        ch_num = int(ch_match.group(1)) if ch_match else 0
        filepath = os.path.join(chapters_dir, fn)

        try:
            with open(filepath, "r", encoding="utf-8") as f:
                text = f.read()
        except OSError:
            continue

        # Strip metadata header for editing
        lines = text.split("\n")
        header_lines = [l for l in lines if l.startswith("> POV:")]
        body = "\n".join(l for l in lines if not l.startswith("> POV:"))

        # Extract title from first heading
        title_match = re.search(r'^#\s+(.+)$', body, re.MULTILINE)
        chapter_title = title_match.group(1) if title_match else f"Chapter {ch_num}"

        print(f"  Editing Chapter {ch_num}...", end=" ")

        result = adversarial_edit_chapter(
            body, chapter_title, client, model, target_cut_pct
        )

        if edit_all and result.get("new_text"):
            # Write back the edited chapter
            new_header = "\n".join(header_lines) if header_lines else f"> POV: Edited | Words: {result['new_word_count']}"
            edited_content = f"{new_header}\n\n{result['new_text']}"

            backup_path = filepath.replace(".md", ".pre-edit.md")
            if not os.path.exists(backup_path):
                os.rename(filepath, backup_path)

            with open(filepath, "w", encoding="utf-8") as f:
                f.write(edited_content)

            cuts_count = len(result.get("cuts", []))
            print(
                f"{-result['words_removed']} words ({cuts_count} cuts, "
                f"{result.get('mechanical_cuts', 0)} mechanical)"
            )
        else:
            print(f"scored only: {result.get('words_removed', 0)} removable words")

        total_words_removed += result.get("words_removed", 0)
        total_words_original += result.get("original_word_count", 0)
        results.append({
            "chapter": ch_num,
            "original_word_count": result.get("original_word_count", 0),
            "new_word_count": result.get("new_word_count", 0),
            "words_removed": result.get("words_removed", 0),
            "pct_cut": round(result.get("words_removed", 0) / max(result.get("original_word_count", 1), 1) * 100, 1),
            "cuts": result.get("cuts", []),
            "category_breakdown": result.get("category_breakdown", {}),
        })

    client.close()

    total_pct = round(total_words_removed / max(total_words_original, 1) * 100, 1)

    print(f"\n  --- Adversarial Edit Summary ---")
    print(f"  Total words removed: {total_words_removed} ({total_pct}% of manuscript)")
    print(f"  Chapters edited: {len(results)}")

    return {
        "status": "COMPLETE" if edit_all else "SCORED",
        "per_chapter": results,
        "total_words_original": total_words_original,
        "total_words_removed": total_words_removed,
        "total_pct_cut": total_pct,
    }

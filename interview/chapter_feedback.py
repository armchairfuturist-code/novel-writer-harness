"""Post-chapter feedback module — user review, feedback collection, and revision.

After novel generation, each chapter is presented for optional user review.
The user can skip ("go with your idea") or provide structured feedback.
If feedback is provided, the chapter is revised via CrofaiClient using the
REVISION_SYSTEM_PROMPT pattern augmented with user feedback.
"""

import os
from typing import Optional

from config import Config
from interview.cli import green, yellow, bold, cyan, c
from pipeline.api import CrofaiClient
from pipeline.draft import ChapterScorer, REVISION_SYSTEM_PROMPT


def _read_chapter(chapter_path: str) -> str:
    """Read chapter text from disk, stripping any leading metadata line.

    Metadata lines starting with '> POV:' are stripped so the revision
    system only receives the prose content.
    """
    try:
        with open(chapter_path, "r", encoding="utf-8") as f:
            content = f.read()
        lines = content.split("\n")
        filtered = [l for l in lines if not l.startswith("> POV:")]
        return "\n".join(filtered)
    except OSError:
        return ""


def _word_count(text: str) -> int:
    """Count words in text."""
    return len(text.split())


def _present_chapter(chapter_path: str, chapter_title: str, chapter_num: int) -> bool:
    """Show chapter preview and prompt for review.

    Displays:
    - Chapter title + word count
    - First 500 characters as preview
    - File path
    - Prompt: "Review Chapter N? [y/N/go with your idea]"

    'go with your idea' is the default — any non-'y' response skips.

    Returns:
        True if user wants to provide feedback, False if they skip.
    """
    text = _read_chapter(chapter_path)
    wc = _word_count(text)
    preview = text[:500]

    print()
    print("  " + "=" * 56)
    print(f"  {bold(cyan(f'Chapter {chapter_num}: {chapter_title}'))}")
    print(f"  {green(f'{wc} words')}")
    print(f"  {green(f'Path: {chapter_path}')}")
    print()
    print(f"  {bold('Preview:')}")
    for line in preview.splitlines():
        if line.strip():
            print(f"  {line.strip()}")
    if len(text) > 500:
        print(f"  {yellow('[...]')}")
    print("  " + "=" * 56)
    print()

    # Prompt for review
    try:
        line = input(f"  Review Chapter {chapter_num}? [y/N/go with your idea]: ").strip().lower()
    except (KeyboardInterrupt, EOFError):
        print()
        return False

    if line in ("y", "yes", "ye"):
        return True
    # Anything else — N, go with your idea, empty, skip — means skip
    return False


def _collect_specific_feedback() -> dict:
    """Collect structured feedback about a chapter.

    Guided specificity prompts:
    - "Which scene?" (optional — can press Enter to skip)
    - "What aspect (pace, dialogue, description, character, plot)?"
    - "Your specific suggestion:"

    Returns:
        Dict with keys: scene, aspect, suggestion
    """
    print(f"  {bold(cyan('Provide specific feedback for revision:'))}")
    print()

    try:
        scene = input("  Which scene? (optional, press Enter to skip): ").strip()
        aspect = input("  What aspect (pace, dialogue, description, character, plot)?: ").strip()
        suggestion = input("  Your specific suggestion: ").strip()
    except (KeyboardInterrupt, EOFError):
        print()
        return {"scene": "", "aspect": "", "suggestion": ""}

    return {
        "scene": scene,
        "aspect": aspect,
        "suggestion": suggestion,
    }


def _revise_with_feedback(chapter_text: str, feedback: dict, config: Config) -> dict:
    """Revise a chapter based on user feedback.

    Uses CrofaiClient with the draft-phase model (prose quality matters).
    Combines REVISION_SYSTEM_PROMPT with user feedback as additional instructions.
    Simple 1-round revision (no multi-round loop).

    Args:
        chapter_text: The original chapter text
        feedback: Dict with scene, aspect, suggestion keys
        config: Config instance

    Returns:
        Dict with 'revised_text' (str) and 'score' (dict from ChapterScorer
        or None if revision failed)
    """
    feedback_parts = []
    if feedback.get("scene"):
        feedback_parts.append(f"- Scene: {feedback['scene']}")
    if feedback.get("aspect"):
        feedback_parts.append(f"- Aspect: {feedback['aspect']}")
    if feedback.get("suggestion"):
        feedback_parts.append(f"- Suggestion: {feedback['suggestion']}")

    feedback_text = "\n".join(feedback_parts) if feedback_parts else "General revision."

    revision_prompt = f"""Revise the following chapter based on this reader feedback:

{feedback_text}

Please incorporate all feedback while preserving the chapter's voice, POV, and narrative arc.

--- CHAPTER TEXT ---

{chapter_text}"""

    client = CrofaiClient(config)
    try:
        revised_text = client.chat_with_retry(
            config.model_for_phase("draft"),
            messages=[{"role": "user", "content": revision_prompt}],
            system_prompt=REVISION_SYSTEM_PROMPT,
            temperature=0.7,
        )
    except RuntimeError as e:
        print(f"    {yellow(f'Revision failed: {e}')}")
        return {"revised_text": chapter_text, "score": None}
    finally:
        client.close()

    # Score the revised text for comparison
    scorer = ChapterScorer(config)
    score = scorer.score_chapter(revised_text)

    return {"revised_text": revised_text, "score": score}


def get_user_feedback(
    chapter_path: str,
    chapter_title: str,
    chapter_num: int,
    config: Optional[Config] = None,
) -> dict:
    """Main entry point: review a chapter, collect feedback, optionally revise.

    Args:
        chapter_path: Path to the chapter file on disk
        chapter_title: Title of the chapter
        chapter_num: Chapter number (1-indexed)
        config: Optional Config instance

    Returns:
        Dict with:
            - 'action': "skip" or "revise"
            - 'revised_text': The revised text (None if action is "skip")
            - 'feedback': The collected feedback dict
            - 'score': ChapterScorer result dict (None if skip)
    """
    config = config or Config()

    # Read the chapter
    chapter_text = _read_chapter(chapter_path)
    if not chapter_text:
        print(f"  {yellow(f'Could not read chapter: {chapter_path}')}")
        return {"action": "skip", "revised_text": None, "feedback": {}, "score": None}

    # Present chapter and ask if user wants to review
    wants_review = _present_chapter(chapter_path, chapter_title, chapter_num)
    if not wants_review:
        print(f"  {green('Skipping — going with your idea.')}")
        return {"action": "skip", "revised_text": None, "feedback": {}, "score": None}

    # Collect specific feedback
    feedback = _collect_specific_feedback()
    if not feedback.get("suggestion") and not feedback.get("aspect"):
        # No substantial feedback — treat as skip
        print(f"  {green('No specific feedback provided. Going with your idea.')}")
        return {"action": "skip", "revised_text": None, "feedback": feedback, "score": None}

    # Revise with feedback
    print(f"  {cyan('Revising chapter based on your feedback...')}")
    result = _revise_with_feedback(chapter_text, feedback, config)

    if result["score"]:
        score_val = result["score"]["total_score"]
        print(f"  {green(f'Revision complete. Score: {score_val}/10')}")
    else:
        print(f"  {yellow('Revision completed (scoring unavailable).')}")

    return {
        "action": "revise",
        "revised_text": result["revised_text"],
        "feedback": feedback,
        "score": result["score"],
    }

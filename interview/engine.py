"""Interactive interview engine for StoryForge.

Orchestrates the Q&A loop: loads questions, presents them via the CLI layer,
collects answers, detects thin areas, persists checkpoints, and performs
adaptive drilling when answers are thin/vague.
"""

import json
import os
import sys
import time
from datetime import datetime, timezone
from typing import Optional

from interview.questions import get_questions, DIMENSION_ORDER
from interview.cli import (
    present_question,
    get_answer,
    present_follow_up,
    get_follow_up_answer,
    show_section_header,
    show_completion_summary,
    welcome_banner,
    closing_message,
    yellow,
    bold,
    red,
)
from interview.drilling import generate_follow_ups

CHECKPOINT_FILENAME = "interview_checkpoint.json"
CHECKPOINT_INTERVAL = 5  # Save every N questions
THIN_WORD_THRESHOLD = 10
HEDGE_WORDS = {
    "maybe", "perhaps", "not sure", "i guess", "kind of",
    "sort of", "something like", "i think", "probably",
    "might be", "could be", "possibly", "i don't know",
    "not really", "a bit", "a little", "i suppose",
}


def _detect_thin_area(answer: str, question) -> bool:
    """Basic thin-area heuristics. Returns True if answer is thin/vague."""
    words = answer.split()
    # Too short
    if len(words) < THIN_WORD_THRESHOLD:
        return True
    # Hedge words
    lower = answer.lower()
    for hedge in HEDGE_WORDS:
        if hedge in lower:
            return True
    # All follow-up keywords hit
    if question.follow_up_keywords:
        for kw in question.follow_up_keywords:
            if kw.lower() in lower:
                return True
    return False


def _handle_drilling(
    q,
    answer: str,
    model_override: Optional[str],
    result: dict,
) -> bool:
    """Generate and collect follow-up answers for a thin answer.

    Calls generate_follow_ups() to get 2-3 targeted questions, presents
    them via the CLI layer, and appends sub-answers to the result dict
    with is_follow_up=True and original_question_id set.

    The "Go with your idea" skip (via [SKIPPED]) is always available.
    Gracefully handles LLM failures — if no questions are generated,
    simply returns without appending anything.

    Returns:
        True if the user requested to exit (sentinel for caller to handle).
        False if drilling completed normally or was skipped.
    """
    follow_ups = generate_follow_ups(
        question_text=q.text,
        answer=answer,
        model_override=model_override,
    )

    if not follow_ups:
        return False  # No questions to ask

    for i, fq_text in enumerate(follow_ups, 1):
        present_follow_up(q.text, fq_text, q.id, i)
        fa = get_follow_up_answer()

        # User wants to exit the entire interview
        if fa is None:
            return True

        fa_entry = {
            "question_id": q.id + f"_follow_up_{i}",
            "original_question_id": q.id,
            "dimension": q.dimension,
            "question": fq_text,
            "answer": fa,
            "is_thin": False,
            "is_follow_up": True,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        result["answers"].append(fa_entry)

    return False


def _save_checkpoint(answers: dict, project_dir: str) -> str:
    """Save interview checkpoint to disk."""
    os.makedirs(project_dir, exist_ok=True)
    path = os.path.join(project_dir, CHECKPOINT_FILENAME)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(answers, f, indent=2, ensure_ascii=False)
    return path


def _load_checkpoint(project_dir: str) -> Optional[dict]:
    """Load interview checkpoint from disk, or None."""
    path = os.path.join(project_dir, CHECKPOINT_FILENAME)
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        # Basic schema validation
        if not isinstance(data, dict):
            return None
        if "version" not in data or "answers" not in data:
            return None
        return data
    except (json.JSONDecodeError, OSError):
        return None


def run_interview(
    depth: str = "standard",
    genre: Optional[str] = None,
    model_override: Optional[str] = None,
    project_dir: Optional[str] = None,
    existing_answers: Optional[dict] = None,
) -> dict:
    """Run the interactive Q&A loop and return structured answers dict.

    Args:
        depth: 'quick', 'standard', or 'comprehensive'
        genre: Optional genre for genre-specific questions
        model_override: Not used in S01 (LLM calls deferred to S04)
        project_dir: Directory for checkpoint file
        existing_answers: Resume from this checkpoint (S02 feature, optional)

    Returns:
        Dict with keys: version, depth, started_at, completed_at,
                        answers (per-dimension lists), thin_areas
    """
    questions = get_questions(depth, genre)
    if not questions:
        print("  No questions loaded for this depth/genre combination.")
        return _make_empty_result(depth)

    project_dir = project_dir or os.path.join(
        os.getcwd(), "storyforge-interview"
    )

    if existing_answers:
        # Resume mode — continue from last answered question
        answered_ids = {
            a["question_id"] for a in existing_answers.get("answers", [])
            if a.get("answer") != "[INTERRUPTED]"
        }
        remaining = [q for q in questions if q.id not in answered_ids]

        if not remaining:
            print("  All questions already answered. Nothing to resume.")
            return existing_answers

        # Rebuild result from existing checkpoint
        result = existing_answers
        result["completed_at"] = None  # Reset completion marker

        total = len(questions)
        answered_count = len(answered_ids)
        checkpoint_count = 0
        new_answer_count = 0

        try:
            for q in remaining:
                idx = questions.index(q) + 1  # Global index for display
                present_question(q, idx, total)
                answer = get_answer()

                if answer is None:
                    print()
                    print(f"  {yellow('Saving progress and exiting...')}")
                    result["answers"].append({
                        "question_id": q.id,
                        "dimension": q.dimension,
                        "question": q.text,
                        "answer": "[INTERRUPTED]",
                        "is_thin": False,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    })
                    _save_checkpoint(result, project_dir)
                    print(f"  Checkpoint saved. Resume with --resume {project_dir}")
                    return result

                is_thin = _detect_thin_area(answer, q) if answer != "[SKIPPED]" else False

                entry = {
                    "question_id": q.id,
                    "dimension": q.dimension,
                    "question": q.text,
                    "answer": answer,
                    "is_thin": is_thin,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
                result["answers"].append(entry)

                if is_thin:
                    result["thin_areas"].append({
                        "dimension": q.dimension,
                        "question_id": q.id,
                        "text": answer,
                    })
                    # Adaptive drilling: generate and ask follow-up questions
                    if _handle_drilling(q, answer, model_override, result):
                        # User wants to exit during follow-up drilling
                        print()
                        print(f"  {yellow('Saving progress and exiting...')}")
                        result["completed_at"] = None
                        result["answers"].append({
                            "question_id": q.id + "_follow_up_interrupted",
                            "original_question_id": q.id,
                            "dimension": q.dimension,
                            "question": "(drilling interrupted)",
                            "answer": "[INTERRUPTED]",
                            "is_thin": False,
                            "is_follow_up": True,
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                        })
                        _save_checkpoint(result, project_dir)
                        print(f"  Checkpoint saved. Resume with --resume {project_dir}")
                        return result

                new_answer_count += 1
                if new_answer_count % CHECKPOINT_INTERVAL == 0:
                    _save_checkpoint(result, project_dir)
                    checkpoint_count += 1

        except (KeyboardInterrupt, EOFError):
            print()
            print("  " + yellow('Session interrupted. Saving progress...'))
            result["completed_at"] = None
            _save_checkpoint(result, project_dir)
            print(f"  {bold('Checkpoint saved.')} Resume with --resume {project_dir}")
            return result

        result["completed_at"] = datetime.now(timezone.utc).isoformat()
        _save_checkpoint(result, project_dir)

        new_total = len(result["answers"])
        thin_count = len(result["thin_areas"])
        show_completion_summary(new_total, thin_count, total)
        closing_message(project_dir)

        return result

    welcome_banner()

    # Build answer structure
    result = {
        "version": 2,
        "depth": depth,
        "genre": genre,
        "model_override": model_override,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "completed_at": None,
        "answers": [],
        "thin_areas": [],
    }

    total = len(questions)
    checkpoint_count = 0

    # Track current dimension for section headers
    current_dim = None
    dim_question_counters = {}
    for dim in DIMENSION_ORDER:
        dim_questions = [q for q in questions if q.dimension == dim]
        if dim_questions:
            dim_question_counters[dim] = {"start": questions.index(dim_questions[0]) + 1, "end": questions.index(dim_questions[-1]) + 1}

    try:
        for idx, q in enumerate(questions, 1):
            # Show section header when dimension changes
            if q.dimension != current_dim:
                current_dim = q.dimension
                dc = dim_question_counters.get(q.dimension, {"start": idx, "end": idx})
                show_section_header(q.dimension, depth, dc["start"], total)

            present_question(q, idx, total)
            answer = get_answer()

            if answer is None:
                # User wants to exit
                print()
                print(f"  {yellow('Saving progress and exiting...')}")
                result["completed_at"] = None  # Not completed
                result["answers"].append({
                    "question_id": q.id,
                    "dimension": q.dimension,
                    "question": q.text,
                    "answer": "[INTERRUPTED]",
                    "is_thin": False,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                })
                _save_checkpoint(result, project_dir)
                print(f"  Checkpoint saved. Resume with --resume {project_dir}")
                return result

            is_thin = _detect_thin_area(answer, q) if answer != "[SKIPPED]" else False

            entry = {
                "question_id": q.id,
                "dimension": q.dimension,
                "question": q.text,
                "answer": answer,
                "is_thin": is_thin,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            result["answers"].append(entry)

            if is_thin:
                result["thin_areas"].append({
                    "dimension": q.dimension,
                    "question_id": q.id,
                    "text": answer,
                })
                # Adaptive drilling: generate and ask follow-up questions
                if _handle_drilling(q, answer, model_override, result):
                    # User wants to exit during follow-up drilling
                    print()
                    print(f"  {yellow('Saving progress and exiting...')}")
                    result["completed_at"] = None
                    result["answers"].append({
                        "question_id": q.id + "_follow_up_interrupted",
                        "original_question_id": q.id,
                        "dimension": q.dimension,
                        "question": "(drilling interrupted)",
                        "answer": "[INTERRUPTED]",
                        "is_thin": False,
                        "is_follow_up": True,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    })
                    _save_checkpoint(result, project_dir)
                    print(f"  Checkpoint saved. Resume with --resume {project_dir}")
                    return result

            # Periodic checkpoint
            if idx % CHECKPOINT_INTERVAL == 0:
                _save_checkpoint(result, project_dir)
                checkpoint_count += 1

    except (KeyboardInterrupt, EOFError):
        print()
        print("  " + yellow('Session interrupted. Saving progress...'))
        result["completed_at"] = None
        _save_checkpoint(result, project_dir)
        print(f"  {bold('Checkpoint saved.')} Resume with --resume {project_dir}")
        return result

    # Mark complete
    result["completed_at"] = datetime.now(timezone.utc).isoformat()
    checkpoint_path = _save_checkpoint(result, project_dir)

    thin_count = len(result["thin_areas"])
    show_completion_summary(len(result["answers"]), thin_count, total)
    closing_message(project_dir)

    return result


def _make_empty_result(depth: str) -> dict:
    """Return an empty result dict for the case of no questions."""
    return {
        "version": 2,
        "depth": depth,
        "genre": None,
        "model_override": None,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "answers": [],
        "thin_areas": [],
    }

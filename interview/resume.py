"""Checkpoint schema validation, recovery, and structured error logging for StoryForge.

Provides:
- validate_checkpoint() — validates checkpoint dict structure
- recover_checkpoint() — placeholder for future backup-based recovery
- log_error() — appends ISO-timestamped entries to <project-dir>/errors.log
"""

import os
from datetime import datetime, timezone
from typing import Optional

# All checkpoint schema versions the system accepts
ALLOWED_VERSIONS: set[int] = {2}

# Keys every answer entry must contain
REQUIRED_ANSWER_KEYS: set[str] = {
    "question_id",
    "dimension",
    "question",
    "answer",
    "is_thin",
    "timestamp",
}


def validate_checkpoint(data) -> Optional[str]:
    """Validate a checkpoint dict.

    Returns an error string describing the first problem found, or None if
    the checkpoint is structurally valid.

    Validation rules:
        - data is a dict
        - data["version"] is in ALLOWED_VERSIONS
        - data["answers"] is a list
        - every answer in the list has all REQUIRED_ANSWER_KEYS
        - every answer["answer"] is a string
    """
    if not isinstance(data, dict):
        return "checkpoint is not a dict"

    version = data.get("version")
    if version not in ALLOWED_VERSIONS:
        return f"unsupported checkpoint version {version!r}; allowed: {sorted(ALLOWED_VERSIONS)}"

    answers = data.get("answers")
    if not isinstance(answers, list):
        return f"checkpoint 'answers' is not a list (got {type(answers).__name__})"

    for i, ans in enumerate(answers):
        if not isinstance(ans, dict):
            return f"answers[{i}] is not a dict"
        missing = REQUIRED_ANSWER_KEYS - set(ans.keys())
        if missing:
            return f"answers[{i}] missing required keys: {sorted(missing)}"
        if not isinstance(ans.get("answer"), str):
            return f"answers[{i}]['answer'] is not a string (got {type(ans.get('answer')).__name__})"

    return None


def recover_checkpoint(project_dir: str) -> Optional[dict]:
    """Attempt to recover a checkpoint from a known-good backup.

    Currently returns None as no backup mechanism is implemented yet.
    This is a placeholder for future auto-backup / crash-recovery logic.
    """
    # TODO: Implement backup-based recovery in a later milestone.
    return None


def log_error(project_dir: str, message: str) -> None:
    """Append an ISO-timestamped error entry to <project-dir>/errors.log.

    Creates the file (and directory) if they do not exist.
    Each entry is on its own line with ISO-8601 timestamp prefix.
    """
    os.makedirs(project_dir, exist_ok=True)
    path = os.path.join(project_dir, "errors.log")
    timestamp = datetime.now(timezone.utc).isoformat()
    with open(path, "a", encoding="utf-8") as f:
        f.write(f"[{timestamp}] {message}\n")

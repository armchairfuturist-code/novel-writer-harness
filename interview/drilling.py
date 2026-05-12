"""Adaptive drilling module for StoryForge.

When a thin/vague answer is detected, generate_follow_ups() uses the
CrofaiClient (GLM Flash via config.model_for_phase("scoring")) to produce
2–3 targeted follow-up questions that deepen the user's answer.

Follow-up questions are presented to the user as sub-questions during the
interactive interview. The "Go with your idea" skip option is always available.
"""

import json
from typing import Optional

from config import Config, ModelConfig
from pipeline.api import CrofaiClient, parse_json_output


# System prompt for follow-up question generation
FOLLOW_UP_SYSTEM_PROMPT = """You are a thoughtful writing coach helping a novelist develop their story.

The user has just given a vague or thin answer to a story development question.
Generate exactly 2-3 targeted follow-up questions that help them think more deeply
about this aspect of their story.

Rules:
- Each question must be specific and actionable — not just "tell me more"
- Questions should probe concrete details the user hasn't specified
- Avoid repeating what the user already said
- Make each question feel like a natural next step in exploring their idea
- Output as a JSON array of strings, e.g. ["Question 1?", "Question 2?"]
- Return ONLY valid JSON, no markdown fences, no extra text"""


def generate_follow_ups(
    question_text: str,
    answer: str,
    model_override: Optional[str] = None,
    config: Optional[Config] = None,
) -> list[str]:
    """Generate 2-3 targeted follow-up questions for a thin answer.

    Args:
        question_text: The original interview question the user answered.
        answer: The user's thin/vague answer.
        model_override: Optional model name override passed through from the engine.
        config: Optional Config instance (uses global singleton if not provided).

    Returns:
        A list of 2-3 follow-up question strings. Returns an empty list if
        the LLM call fails or returns unparseable output (the engine should
        gracefully skip drilling in that case).

    Raises:
        RuntimeError: Propagated from CrofaiClient for unrecoverable API errors.
    """
    cfg = config or Config()
    model = cfg.model_for_phase("scoring")

    # If model_override is provided, look it up in the model registry
    if model_override:
        override = cfg.models.get(model_override)
        if override:
            model = override

    messages = [
        {
            "role": "user",
            "content": (
                f"Original question: {question_text}\n\n"
                f"User's answer: {answer}\n\n"
                f"Generate 2-3 specific follow-up questions that would help "
                f"the user flesh out this aspect of their story. "
                f"Return ONLY a JSON array of strings."
            ),
        }
    ]

    try:
        with CrofaiClient(cfg) as client:
            response = client.chat(
                model=model,
                messages=messages,
                system_prompt=FOLLOW_UP_SYSTEM_PROMPT,
                temperature=0.7,
                max_tokens=1024,
            )
    except RuntimeError:
        # Non-retryable errors (auth, bad request) or all retries exhausted
        return []

    try:
        result = parse_json_output(response, "follow-up questions")
        if isinstance(result, list):
            questions = [str(q) for q in result if isinstance(q, str)]
            # Clamp to 1-4 questions in case the model gives too many/few
            if len(questions) < 1:
                return []
            return questions[:4]
        return []
    except (RuntimeError, json.JSONDecodeError):
        # Last-resort: try to extract questions from raw text
        questions = _extract_questions_from_text(response)
        return questions[:4] if questions else []


def _extract_questions_from_text(text: str) -> list[str]:
    """Fallback: extract question-like sentences from raw LLM output.

    Tries to find lines ending with '?' — good enough for the
    rare case where JSON parsing fails.
    """
    lines = text.strip().split("\n")
    questions = []
    for line in lines:
        line = line.strip().lstrip("- *0123456789.").strip()
        if line.endswith("?") and len(line) > 10:
            questions.append(line)
    return questions

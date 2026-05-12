"""Context window monitoring for StoryForge interview engine.

Tracks accumulated token usage across interview Q&A and warns when
approaching the model's context limit. The check is passive — it logs
the warning and offers the user options via a display callback.

Usage:
    from interview.context_monitor import ContextMonitor, estimate_tokens

    monitor = ContextMonitor("deepseek")
    monitor.add_qa("What is the story about?", "A long answer...")
    warning = monitor.check()
    if warning:
        choice = monitor.display_context_warning(warning)
"""

from typing import Optional

# ── Model Context Limits ────────────────────────────────────────────────────
# Maps all model alias keys from config.py Config.models to their context
# window token limits. Update these when model specs change.

MODEL_CONTEXT_LIMITS: dict[str, int] = {
    "deepseek": 128000,
    "kimi-speed": 128000,
    "kimi-balanced": 128000,
    "kimi-precision": 128000,
    "flash": 128000,
}


def estimate_tokens(text: str) -> int:
    """Rough token estimate: 1 token ≈ 4 characters.

    This is a fast approximation suitable for context-window bookkeeping
    where perfect accuracy is not required. Real token counts from the
    API will differ, but this gives a reliable upper/lower bound.
    """
    return len(text) // 4


class ContextMonitor:
    """Tracks accumulated context usage and warns at a configurable threshold.

    The monitor is designed for once-per-turn checking: call add_qa() after
    each question-answer pair, then call check() to see if the warning
    threshold has been crossed. The warning fires only once per session.
    """

    def __init__(self, model_name: str = "deepseek") -> None:
        """Initialise monitor for the given model.

        Args:
            model_name: Key into MODEL_CONTEXT_LIMITS. Falls back to 128000
                if the model is unknown.
        """
        self.limit: int = MODEL_CONTEXT_LIMITS.get(model_name, 128000)
        self.warn_at: int = int(self.limit * 0.70)
        self.accumulated: int = 0
        self.has_warned: bool = False

    def add_qa(self, question: str, answer: str) -> None:
        """Add estimated tokens for one Q&A turn to the accumulator.

        Args:
            question: The question text (includes dimension context).
            answer: The user's answer text.
        """
        q_tokens = estimate_tokens(question)
        a_tokens = estimate_tokens(answer)
        self.accumulated += q_tokens + a_tokens

    def check(self) -> Optional[str]:
        """Check whether accumulated usage has crossed the warning threshold.

        Returns a formatted warning string the first time the threshold is
        crossed. Subsequent calls return None (one-shot warning).

        The warning includes current token usage, the limit, a percentage,
        and suggested next actions ('Continue' or 'Export and resume later').

        Returns:
            A formatted warning string on first threshold crossing, or None.
        """
        if self.has_warned:
            return None
        if self.accumulated < self.warn_at:
            return None

        self.has_warned = True
        pct = (self.accumulated / self.limit) * 100.0

        return (
            f"[Context Warning] Accumulated ~{self.accumulated:,} tokens "
            f"({pct:.0f}% of {self.limit:,} limit).\n"
            f"  Option 1: Continue — you still have "
            f"{self.limit - self.accumulated:,} tokens available.\n"
            f"  Option 2: Export and resume later — save progress and "
            f"continue in a new session."
        )

    def display_context_warning(self, message: str) -> str:
        """Display a context-warning message and return the user's choice.

        Currently a stub that always returns 'continue'. Real interactive
        handling will be wired up in a later milestone (S04).

        Args:
            message: The warning message from check().

        Returns:
            User's choice: 'continue' (stub).
        """
        # TODO (S04): Replace with real interactive prompt offering
        #             'continue' or 'export-and-resume' choices.
        return "continue"

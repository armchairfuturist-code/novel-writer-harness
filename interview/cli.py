"""CLI interaction layer for the StoryForge interview engine.

Provides prompting, progress indication, section headers, and multi-line input.
Zero external dependencies — uses only print() and input() from stdlib.
"""

import sys
from typing import Optional


def c(text: str, color_code: str = "") -> str:
    """Color a string for terminal output. No-op if not a TTY or Windows."""
    if not sys.stdout.isatty() or os.name == "nt":
        return text
    return color_code + text + "[0m"


def cyan(text: str) -> str:
    return c(text, "[96m")


def green(text: str) -> str:
    return c(text, "[92m")


def yellow(text: str) -> str:
    return c(text, "[93m")


def red(text: str) -> str:
    return c(text, "[91m")


def bold(text: str) -> str:
    return c(text, "[1m")


def present_question(q, current: int, total: int) -> None:
    """Display a question with progress indicator and section context."""
    progress = f"[{current}/{total}]"
    section = q.dimension.replace("_", " ").title()
    print()
    print(f"  {yellow(progress)} {bold(cyan(section))}")
    print()
    print(f"  {q.text}")
    print()


def get_answer() -> Optional[str]:
    """Read a multi-line answer from stdin.

    Reads lines until a blank line (empty input) or '---' is entered.
    Returns the concatenated answer string, or None if the user
    interrupts with Ctrl+C or enters 'q'/'quit'/'exit' on its own line.
    """
    lines = []
    try:
        line = input("  > ").strip()
        # Single-line commands for navigation
        if line.lower() in ("q", "quit", "exit"):
            return None
        if line.lower() == "skip":
            return "[SKIPPED]"
        lines.append(line)

        while True:
            line = input("  > ").strip()
            if not line or line == "---":
                break
            lines.append(line)
    except (KeyboardInterrupt, EOFError):
        print()
        return None

    return " ".join(lines)


def show_section_header(dimension_key: str, depth: str, current: int, total: int) -> None:
    """Display a transition header when moving to a new dimension."""
    from interview.questions import DIMENSION_LABELS
    label = DIMENSION_LABELS.get(dimension_key, dimension_key.replace("_", " ").title())
    print()
    print("=" * 60)
    print(f"  {bold(green(label))}")
    print(f"  Questions {current}-{total} of {total} ({depth} mode)")
    print("=" * 60)
    print()


def show_completion_summary(answer_count: int, thin_count: int, total_questions: int) -> None:
    """Show a summary when the interview completes."""
    print()
    print("=" * 60)
    print(f"  {bold(green('Interview Complete!'))}")
    print(f"  Answered: {answer_count}/{total_questions}")
    if thin_count:
        print(f"  {yellow(f'Thin areas detected: {thin_count}')}")
    print("=" * 60)
    print()


def welcome_banner() -> None:
    """Display the welcome banner."""
    print()
    print("  " + "=" * 56)
    print("  " + bold("  StoryForge Interactive Interview"))
    print("  " + "  Let's develop your story idea together.")
    print("  " + "  Answer each question thoughtfully.")
    print("  " + "  " + yellow("Tip:") + " Type 'skip' to skip a question.")
    print("  " + "  " + yellow("Tip:") + " Press Ctrl+C to save & exit.")
    print("  " + "=" * 56)
    print()


def closing_message(project_dir: str) -> None:
    """Show the closing message with project location."""
    print()
    print(f"  Answers saved to: {project_dir}")
    print(f"  Run {bold(cyan('storyforge.py --interactive --resume ' + project_dir))} to resume.")
    print()

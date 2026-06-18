"""Repair truncated chapters in the Nudge manuscript.

For each chapter that ends mid-sentence, ask the LLM to continue from where
it left off and append the continuation to the file. Run from project root.

Usage: python scripts/repair_truncated_chapters.py [chapter_number ...]
       python scripts/repair_truncated_chapters.py         # all flagged chapters
"""
import os
import sys
import time

# Make the package importable from project root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import Config
from pipeline.api import CrofaiClient, _looks_truncated_prose
from pipeline.draft import DRAFT_SYSTEM_PROMPT
from pathlib import Path


def trim_to_last_complete_sentence(text: str) -> str:
    """Trim trailing text after the last complete sentence in the latter half.

    A complete sentence ends with . ! ? or a closing quote/dash after such
    punctuation. We only trim if we find such a sentence-ender in the
    latter half of the text (so we don't accidentally cut good content).
    """
    enders = set('.!?")\u201d\u2019\u2014')
    last_end_idx = -1
    for i, ch in enumerate(text):
        if ch in enders:
            last_end_idx = i
    if last_end_idx >= 0 and last_end_idx > len(text) * 0.5:
        return text[: last_end_idx + 1]
    return text


def get_chapter_outline_context(project_dir: Path, ch_num: int) -> str:
    """Pull chapter title, POV, and summary from outline.json for context."""
    outline_path = project_dir / "outline.json"
    if not outline_path.exists():
        return ""
    try:
        import json
        outline = json.loads(outline_path.read_text(encoding="utf-8"))
    except Exception:
        return ""
    chapters = outline.get("chapters", outline.get("outline", []))
    if isinstance(chapters, list):
        for c in chapters:
            num = c.get("chapter") or c.get("number") or c.get("ch")
            if num == ch_num:
                title = c.get("title", "")
                pov = c.get("pov", "")
                summary = c.get("summary", c.get("description", ""))
                return f"Chapter {ch_num}: {title}\nPOV: {pov}\nSummary: {summary}"
    return ""


def repair_chapter(
    chap_path: Path,
    project_dir: Path,
    client: CrofaiClient,
    model,
    min_continuation_words: int = 400,
) -> bool:
    """Try to repair a single truncated chapter file. Returns True if repaired."""
    text = chap_path.read_text(encoding="utf-8")
    if not _looks_truncated_prose(text):
        print(f"  [skip] {chap_path.name} is not truncated")
        return False

    ch_num = int(chap_path.stem.split("-")[-1])
    print(f"  [repair] {chap_path.name} ({len(text.split())} words)")

    # Strip the > POV header line if present, work with body only
    body_start = text.find("\n# Chapter")
    if body_start < 0:
        body_start = 0
    body = text[body_start:].lstrip("\n")

    # Trim to last complete sentence so the continuation doesn't duplicate
    # the partial sentence at the end.
    body = trim_to_last_complete_sentence(body)

    # Build context: outline info + tail of what was written
    context = get_chapter_outline_context(project_dir, ch_num)
    tail = body[-500:].rstrip()

    continuation_prompt = (
        f"You are continuing a chapter from a near-future sci-fi novel titled "
        f"'Nudge'. The previous response was cut off mid-sentence.\n\n"
        f"{context}\n\n"
        f"Here is the tail end of what was written so far:\n\n"
        f"---TAIL---\n{tail}\n---END TAIL---\n\n"
        f"Continue the chapter from EXACTLY where it left off. Do NOT repeat "
        f"any text. Write at least {min_continuation_words} more words. "
        f"Bring the chapter to a proper conclusion — resolve any tension "
        f"or open threads introduced in this scene, end on a complete "
        f"sentence, and ideally a satisfying image or beat. Match the "
        f"existing prose voice, POV, and style. Do not include the chapter "
        f"title or any meta-commentary. Just continue the prose."
    )

    messages = [
        {"role": "user", "content": continuation_prompt},
    ]

    # Up to 2 continuation attempts if the first one is itself truncated
    for attempt in range(2):
        try:
            continuation = client.chat_with_retry(
                model,
                messages=messages,
                system_prompt=DRAFT_SYSTEM_PROMPT,
                temperature=0.7,
            )
        except Exception as e:
            print(f"    attempt {attempt + 1} failed: {e}")
            continue

        # Append the continuation
        new_body = body + "\n\n" + continuation

        if not _looks_truncated_prose(new_body):
            # Repaired. Reassemble file with header.
            # Try to preserve the original header if there is one.
            header = text[:body_start] if body_start > 0 else ""
            final = header + new_body
            chap_path.write_text(final, encoding="utf-8")
            new_count = len(final.split())
            print(f"    repaired. Now {new_count} words (+{new_count - len(text.split())})")
            return True

        # The continuation itself was truncated. Use it as the new body
        # and try again.
        body = trim_to_last_complete_sentence(new_body)
        messages = [
            {"role": "user", "content": continuation_prompt},
            {"role": "assistant", "content": body},
            {"role": "user", "content": "Continue. End on a complete sentence."},
        ]
        print(f"    attempt {attempt + 1} returned truncated response, retrying...")

    # Exhausted retries — write what we have anyway, it's better than nothing
    print("    WARNING: could not fully repair after 2 attempts, writing partial fix")
    header = text[:body_start] if body_start > 0 else ""
    final = header + body + "\n\n" + continuation
    chap_path.write_text(final, encoding="utf-8")
    return True


def main():
    project_dir = Path(
        "C:/Users/Administrator/Documents/storyforge-projects/nudge"
    )
    chap_dir = project_dir / "chapters"
    if not chap_dir.exists():
        print(f"No chapters dir at {chap_dir}")
        sys.exit(1)

    config = Config()
    model = config.model_for_phase("draft")

    # Determine which chapters to repair
    if len(sys.argv) > 1:
        targets = [int(x) for x in sys.argv[1:]]
        paths = [chap_dir / f"chapter-{n:03d}.md" for n in targets]
    else:
        # Find all truncated chapters
        paths = [
            f for f in sorted(chap_dir.glob("chapter-*.md"))
            if _looks_truncated_prose(f.read_text(encoding="utf-8"))
        ]

    if not paths:
        print("No truncated chapters to repair.")
        return

    print(f"Repairing {len(paths)} chapter(s) using model {model.name}...")
    with CrofaiClient(config) as client:
        for p in paths:
            start = time.time()
            repair_chapter(p, project_dir, client, model)
            print(f"    took {time.time() - start:.1f}s\n")

    print("Done.")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""StoryForge — autonomous novel-writing pipeline.

Usage:
    python storyforge.py "seed concept"
    python storyforge.py "seed concept" --resume
    python storyforge.py --benchmark

Pipeline:
    seed -> worldbuilding -> characters -> outline -> draft -> review -> export

Model routing:
    - DeepSeek V4 Pro: planning, worldbuilding, outline (large context)
    - Kimi K2.6: drafting, character creation, critique (prose-optimized)
    - Gemini 2.5 Flash: scoring, mechanical checks (cheap/fast)

Output:
    ~/storyforge-projects/{project-slug}/
    +-- manuscript.md          # Full assembled manuscript
    +-- project.json           # Metadata
    +-- chapters/              # Individual chapter files
    |   +-- chapter-001.md
    |   +-- ...
    +-- manuscript.pdf         # If Pandoc + LaTeX available

Environment:
    CROFAI_API_KEY         # Required: crofai API key
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime
from typing import Optional

# Ensure we can import from the skill directory
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import Config
from pipeline.seed import run_seed
from pipeline.worldbuilding import run_worldbuilding
from pipeline.characters import run_characters
from pipeline.outline import run_outline
from pipeline.draft import run_draft
from pipeline.review import run_full_review
from pipeline.export import export_manuscript

BANNER = """
  +============================================+
  |           StoryForge v0.1                   |
  |  Autonomous novel pipeline - Qwen Code + AI  |
  +============================================+
"""


def slugify(text: str) -> str:
    """Convert text to a filesystem-safe slug."""
    import re
    text = text.lower().strip()
    text = re.sub(r'[^a-z0-9\s-]', '', text)
    text = re.sub(r'[\s-]+', '-', text)
    return text[:60]


def run_full_pipeline(concept: str, config: Optional[Config] = None, resume_from: int = 1, quick: bool = False) -> str:
    """Run the full StoryForge pipeline from seed to export.

    Args:
        concept: Seed concept for the story
        config: Optional Config override

    Returns:
        str: Path to the project output directory
    """
    config = config or Config()
    print(BANNER)
    print(f"Seed concept: {concept}\n")

    # Phase 1: Seed
    print("=== Phase 1/6: Seed Analysis ===")
    start = time.time()
    spec = run_seed(concept)
    elapsed = time.time() - start
    print(f"  Title: {spec.get('title', 'Untitled')}")
    print(f"  Genre: {spec.get('genre', 'Unknown')}")
    print(f"  Tone: {spec.get('tone', 'Neutral')}")
    print(f"  POV: {spec.get('pov', 'Unknown')}")
    print(f"  Chapters: {spec.get('target_chapters', 'Auto')}")
    print(f"  Time: {elapsed:.1f}s\n")

    # Create project directory
    project_slug = slugify(spec.get("title", "untitled-novel"))
    project_dir = os.path.join(config.project_dir, project_slug)
    os.makedirs(project_dir, exist_ok=True)

    # Save spec
    with open(os.path.join(project_dir, "spec.json"), "w", encoding="utf-8") as f:
        json.dump(spec, f, indent=2)

    # Phase 2: Worldbuilding
    print("=== Phase 2/6: Worldbuilding ===")
    start = time.time()
    world = run_worldbuilding(spec)
    elapsed = time.time() - start
    world_name = world.get("world_name", "Generated World")
    print(f"  World: {world_name}")
    print(f"  Time: {elapsed:.1f}s\n")

    with open(os.path.join(project_dir, "world.json"), "w", encoding="utf-8") as f:
        json.dump(world, f, indent=2)

    # Phase 3: Characters
    print("=== Phase 3/6: Characters ===")
    start = time.time()
    characters = run_characters(spec, world)
    elapsed = time.time() - start
    char_count = len(characters.get("characters", []))
    print(f"  Characters created: {char_count}")
    print(f"  Time: {elapsed:.1f}s\n")

    with open(os.path.join(project_dir, "characters.json"), "w", encoding="utf-8") as f:
        json.dump(characters, f, indent=2)

    # Phase 4: Outline
    print("=== Phase 4/6: Outline ===")
    start = time.time()
    outline = run_outline(spec, world, characters)
    elapsed = time.time() - start
    act_count = len(outline.get("acts", []))
    chapter_count = sum(len(a.get("chapters", [])) for a in outline.get("acts", []))
    plot_points = len(outline.get("major_plot_points", []))
    print(f"  Acts: {act_count}")
    print(f"  Chapters: {chapter_count}")
    print(f"  Major plot points: {plot_points}")
    print(f"  Structure: {outline.get('story_structure', 'three_act')}")
    print(f"  Time: {elapsed:.1f}s\n")

    with open(os.path.join(project_dir, "outline.json"), "w", encoding="utf-8") as f:
        json.dump(outline, f, indent=2)

    # Phase 5: Draft
    print("=== Phase 5/6: Drafting ===")
    print(f"  Model: {config.model_for_phase('draft').name}")
    print(f"  Target: {chapter_count} chapters\n")
    start = time.time()

    chapters_dir = os.path.join(project_dir, "chapters")
    os.makedirs(chapters_dir, exist_ok=True)

    chapters = run_draft(spec, world, characters, outline, project_dir, config, resume_from=resume_from)
    elapsed = time.time() - start

    total_words = sum(c.get("word_count", 0) for c in chapters)
    avg_score = sum(c.get("score", {}).get("total_score", 0) for c in chapters) / max(len(chapters), 1)
    print(f"\n  Chapters written: {len(chapters)}")
    print(f"  Total words: {total_words}")
    print(f"  Average chapter score: {avg_score:.1f}/10")
    print(f"  Drafting time: {elapsed:.1f}s ({elapsed/60:.1f}m)\n")

    # Phase 6: Review (skip in quick mode)
    if not quick:
        print("=== Phase 5b/6: Review ===")
        print(f"  Running full manuscript review...")
        start = time.time()
        review = run_full_review(chapters, project_dir, config)
        elapsed = time.time() - start

        print(f"  Overall score: {review.get('overall_avg_score', 'N/A')}/10")
        print(f"  Total words reviewed: {review.get('total_words', 0)}")
        if review.get("weakest_chapter"):
            print(f"  Weakest chapter: Ch {review['weakest_chapter']}")
        if review.get("needs_revision"):
            print(f"  Revision needed: YES")
        else:
            print(f"  Revision needed: NO - manuscript meets quality threshold")
        print(f"  Review time: {elapsed:.1f}s\n")
    else:
        print("=== Phase 5b/6: Review ===")
        print(f"  Skipped (--quick mode)\n")

    # Phase 7: Export
    print("=== Phase 6/6: Export ===")
    start = time.time()
    export = export_manuscript(chapters, spec, world, characters, outline, project_dir)
    elapsed = time.time() - start

    print(f"  Manuscript: {export['manuscript_md']}")
    for fmt, result in export.get("pandoc", {}).items():
        if result["success"]:
            print(f"  {fmt.upper()}: {result['path']}")
        else:
            print(f"  {fmt.upper()}: skipped ({result['error']})")
    print(f"  Export time: {elapsed:.1f}s\n")

    print("=" * 50)
    print(f"  Project: {spec.get('title', 'Untitled')}")
    print(f"  Output: {project_dir}")
    print(f"  Chapters: {len(chapters)} | Words: {total_words}")
    print(f"  Avg Score: {avg_score:.1f}/10")
    print("=" * 50)

    return project_dir


def main():
    parser = argparse.ArgumentParser(
        description="StoryForge - autonomous novel-writing pipeline"
    )
    parser.add_argument(
        "concept",
        nargs="?",
        help="Seed concept for the story (2-5 sentences)",
    )
    parser.add_argument(
        "--resume",
        metavar="CHAPTER",
        type=int,
        default=1,
        help="Resume drafting from chapter N",
    )
    parser.add_argument(
        "--benchmark",
        action="store_true",
        help="Run Kimi K2.6 variant benchmark instead of pipeline",
    )
    parser.add_argument(
        "--project-dir",
        help="Override default project output directory",
    )
    parser.add_argument(
        "--quick",
        action="store_true",
        help="Fast mode - skip review phase, just draft and export",
    )

    args = parser.parse_args()

    config = Config()
    if args.project_dir:
        config.project_dir = args.project_dir

    if args.benchmark:
        from tests.benchmark_writing import run_benchmark
        run_benchmark()
        return

    if not args.concept:
        parser.print_help()
        print("\nError: provide a seed concept or use --benchmark")
        sys.exit(1)

    run_full_pipeline(args.concept, config, resume_from=args.resume, quick=args.quick)


if __name__ == "__main__":
    main()

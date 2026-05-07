#!/usr/bin/env python3
"""StoryForge — autonomous novel-writing pipeline v0.2.

Usage:
    python storyforge.py "seed concept"
    python storyforge.py "seed concept" --resume 7
    python storyforge.py "same concept"           # auto-resumes existing project
    python storyforge.py --benchmark

Pipeline:
    seed -> worldbuilding -> characters -> outline -> draft (revise, variants, RAG)
    -> fact-check -> backprop -> adversarial edit -> review (dual-persona) -> export

New in v0.2:
    - Revision loop: chapters scoring < 6.0 auto-revise up to 3 rounds
    - Parallel variants: 2-3 style profiles per chapter, best wins
    - RAG context retrieval: BM25-based semantic chapter context
    - Backward propagation: detect forward contradictions
    - Adversarial editing: cut 15% weakest prose (LLM + mechanical)
    - Dual-persona review: literary critic + professor of fiction
    - Token tracking: per-run cost estimation
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import Config
from pipeline.seed import run_seed
from pipeline.worldbuilding import run_worldbuilding
from pipeline.characters import run_characters
from pipeline.outline import run_outline
from pipeline.draft import run_draft
from pipeline.review import run_full_review
from pipeline.factcheck import run_fact_check
from pipeline.backprop import run_backward_propagation
from pipeline.adversarial_edit import run_adversarial_edit
from pipeline.export import export_manuscript

BANNER = """
  +====================================================+
  |            StoryForge v0.2                          |
  |  Novel pipeline with revision loop + dual review    |
  +====================================================+
"""

PHASES = ["seed", "worldbuilding", "characters", "outline", "draft", "review", "export"]


def slugify(text: str) -> str:
    import re
    text = text.lower().strip()
    text = re.sub(r'[^a-z0-9\s-]', '', text)
    text = re.sub(r'[\s-]+', '-', text)
    return text[:60]


def _load_checkpoint(project_dir: str) -> set:
    """Load completed phases from checkpoint file."""
    cp_path = os.path.join(project_dir, "checkpoint.json")
    if os.path.exists(cp_path):
        try:
            with open(cp_path, "r") as f:
                data = json.load(f)
            return set(data.get("completed_phases", []))
        except (json.JSONDecodeError, OSError):
            pass
    return set()


def _save_checkpoint(project_dir: str, completed: set):
    """Save completed phases to checkpoint file."""
    cp_path = os.path.join(project_dir, "checkpoint.json")
    try:
        with open(cp_path, "w") as f:
            json.dump({"completed_phases": sorted(completed)}, f)
    except OSError:
        pass


def run_full_pipeline(
    concept: str,
    config: Optional[Config] = None,
    resume_from: int = 1,
    quick: bool = False,
    parallel_variants: bool = True,
    dual_review: bool = True,
    enable_backprop: bool = True,
    enable_adversarial: bool = True,
) -> str:
    """Run the full StoryForge pipeline from seed to export.

    Args:
        concept: Seed concept for the story
        config: Optional Config override
        resume_from: Chapter number to start drafting from
        quick: If True, skip review, backprop, and adversarial phases
        parallel_variants: Draft multiple style variants per chapter
        dual_review: Use dual-persona review (higher quality)
        enable_backprop: Run backward propagation scan
        enable_adversarial: Run adversarial editing pass

    Returns:
        str: Path to the project output directory
    """
    config = config or Config()
    pipeline_start = time.time()
    print(BANNER)
    print(f"Seed concept: {concept}\n")

    # Determine project directory
    project_slug = slugify(concept)[:40]
    project_dir = os.path.join(config.project_dir, project_slug)
    os.makedirs(project_dir, exist_ok=True)

    # Load checkpoints
    completed = _load_checkpoint(project_dir)
    if completed:
        print(f"  Found checkpoint: {len(completed)} phases completed ({', '.join(sorted(completed))})")
        print(f"  Auto-resuming from next uncompleted phase.\n")

    spec = None
    world = None
    characters = None
    outline = None
    chapters = None

    # ── Phase 1: Seed ──
    if "seed" not in completed:
        print("=== Phase 1/7: Seed Analysis ===")
        start = time.time()
        spec = run_seed(concept)
        elapsed = time.time() - start
        print(f"  Title: {spec.get('title', 'Untitled')}")
        print(f"  Genre: {spec.get('genre', 'Unknown')}")
        print(f"  POV: {spec.get('pov', 'Unknown')}")
        print(f"  Chapters: {spec.get('target_chapters', 'Auto')}")
        print(f"  Time: {elapsed:.1f}s\n")
        with open(os.path.join(project_dir, "spec.json"), "w", encoding="utf-8") as f:
            json.dump(spec, f, indent=2)
        completed.add("seed")
        _save_checkpoint(project_dir, completed)
    else:
        print("=== Phase 1/7: Seed === [cached]")
        with open(os.path.join(project_dir, "spec.json"), "r") as f:
            spec = json.load(f)
        print(f"  Title: {spec.get('title', 'Untitled')}\n")

    # ── Phase 2: Worldbuilding ──
    if "worldbuilding" not in completed:
        print("=== Phase 2/7: Worldbuilding ===")
        start = time.time()
        world = run_worldbuilding(spec)
        elapsed = time.time() - start
        print(f"  World: {world.get('world_name', 'Generated World')}")
        print(f"  Time: {elapsed:.1f}s\n")
        with open(os.path.join(project_dir, "world.json"), "w", encoding="utf-8") as f:
            json.dump(world, f, indent=2)
        completed.add("worldbuilding")
        _save_checkpoint(project_dir, completed)
    else:
        print("=== Phase 2/7: Worldbuilding === [cached]")
        with open(os.path.join(project_dir, "world.json"), "r") as f:
            world = json.load(f)
        print(f"  World: {world.get('world_name', 'Generated World')}\n")

    # ── Phase 3: Characters ──
    if "characters" not in completed:
        print("=== Phase 3/7: Characters ===")
        start = time.time()
        characters = run_characters(spec, world)
        elapsed = time.time() - start
        char_count = len(characters.get("characters", []))
        print(f"  Characters created: {char_count}")
        print(f"  Time: {elapsed:.1f}s\n")
        with open(os.path.join(project_dir, "characters.json"), "w", encoding="utf-8") as f:
            json.dump(characters, f, indent=2)
        completed.add("characters")
        _save_checkpoint(project_dir, completed)
    else:
        print("=== Phase 3/7: Characters === [cached]")
        with open(os.path.join(project_dir, "characters.json"), "r") as f:
            characters = json.load(f)
        print(f"  Characters: {len(characters.get('characters', []))}\n")

    # ── Phase 4: Outline ──
    if "outline" not in completed:
        print("=== Phase 4/7: Outline ===")
        start = time.time()
        outline = run_outline(spec, world, characters)
        elapsed = time.time() - start
        act_count = len(outline.get("acts", []))
        ch_count = sum(len(a.get("chapters", [])) for a in outline.get("acts", []))
        print(f"  Acts: {act_count} | Chapters: {ch_count}")
        print(f"  Structure: {outline.get('story_structure', 'three_act')}")
        print(f"  Time: {elapsed:.1f}s\n")
        with open(os.path.join(project_dir, "outline.json"), "w", encoding="utf-8") as f:
            json.dump(outline, f, indent=2)
        completed.add("outline")
        _save_checkpoint(project_dir, completed)
    else:
        print("=== Phase 4/7: Outline === [cached]")
        with open(os.path.join(project_dir, "outline.json"), "r") as f:
            outline = json.load(f)
        print(f"  Chapters: {sum(len(a.get('chapters', [])) for a in outline.get('acts', []))}\n")

    chapter_count = sum(len(a.get("chapters", [])) for a in outline.get("acts", []))

    # ── Phase 5: Draft ──
    if "draft" not in completed:
        print("=== Phase 5/7: Drafting ===")
        print(f"  Model: {config.model_for_phase('draft').name}")
        print(f"  Target: {chapter_count} chapters")
        print(f"  Parallel variants: {parallel_variants}")
        print(f"  Revision loop: ENABLED (threshold: {config.scoring.min_chapter_score})")
        print()
        start = time.time()
        chapters = run_draft(
            spec, world, characters, outline, project_dir, config,
            resume_from=resume_from,
            parallel_variants=parallel_variants,
        )
        elapsed = time.time() - start
        total_words = sum(c.get("word_count", 0) for c in chapters)
        avg_score = sum(c.get("score", {}).get("total_score", 0) for c in chapters) / max(len(chapters), 1)
        print(f"\n  Chapters written: {len(chapters)} | Words: {total_words}")
        print(f"  Avg score: {avg_score:.1f}/10")
        print(f"  Time: {elapsed:.1f}s ({elapsed/60:.1f}m)\n")
        completed.add("draft")
        _save_checkpoint(project_dir, completed)
    else:
        print("=== Phase 5/7: Draft === [cached]")
        chapters = []
        ch_dir = os.path.join(project_dir, "chapters")
        if os.path.isdir(ch_dir):
            for fn in sorted(os.listdir(ch_dir)):
                if fn.endswith(".md"):
                    ch_path = os.path.join(ch_dir, fn)
                    try:
                        with open(ch_path, "r") as f:
                            txt = f.read()
                        wc = len(txt.split())
                    except OSError:
                        wc = 0
                    chapters.append({"chapter": len(chapters) + 1, "file": ch_path, "word_count": wc, "title": fn.replace(".md", "").replace("chapter-", "Ch ")})
        print(f"  Chapters: {len(chapters)}\n")

    # ── Fact-Check ──
    if "draft" in completed or "draft" in PHASES:
        print("=== Fact-Check: Consistency Scan ===")
        fc_report = run_fact_check(project_dir)
        if fc_report["status"] == "SKIPPED":
            print(f"  {fc_report['reason']}\n")
        else:
            print(f"  Grade: {fc_report['status']}")
            print(f"  {fc_report['summary']}")
            for issue in fc_report.get("issues", [])[:5]:
                tag = {"FAIL": "!", "WARN": "?", "INFO": "i"}.get(issue["severity"], "?")
                print(f"    [{tag}] Ch {issue.get('chapter', '?'):>2}: {issue['detail'][:100]}")
            if len(fc_report.get("issues", [])) > 5:
                print(f"    ... and {len(fc_report['issues']) - 5} more")
            print()

    # ── Backward Propagation (new in v0.2) ──
    if "backprop" not in completed and not quick and enable_backprop:
        print("=== Backward Propagation: Forward Contradictions ===")
        start = time.time()
        bp_report = run_backward_propagation(project_dir)
        elapsed = time.time() - start
        print(f"  Status: {bp_report['status']}")
        print(f"  {bp_report['summary']}")
        for issue in bp_report.get("issues", [])[:5]:
            tag = {"FAIL": "!", "WARN": "?", "INFO": "i"}.get(issue.get("severity", "INFO"), "?")
            print(f"    [{tag}] Ch {issue.get('target_chapter', '?'):>2}: {issue['detail'][:100]}")
        if len(bp_report.get("issues", [])) > 5:
            print(f"    ... and {len(bp_report['issues']) - 5} more")
        print(f"  Time: {elapsed:.1f}s\n")
        completed.add("backprop")
        _save_checkpoint(project_dir, completed)
    elif quick:
        print("=== Backward Propagation === [skipped --quick]\n")
    else:
        print("=== Backward Propagation === [cached]\n")

    # ── Adversarial Editing (new in v0.2) ──
    if "adversarial" not in completed and not quick and enable_adversarial:
        print("=== Adversarial Editing: Tightening Prose ===")
        start = time.time()
        ae_report = run_adversarial_edit(project_dir, config)
        elapsed = time.time() - start
        if ae_report["status"] != "SKIPPED":
            print(f"  Total words removed: {ae_report.get('total_words_removed', 0)} "
                  f"({ae_report.get('total_pct_cut', 0)}% of manuscript)")
            print(f"  Chapters edited: {len(ae_report.get('per_chapter', []))}")
        print(f"  Time: {elapsed:.1f}s\n")
        completed.add("adversarial")
        _save_checkpoint(project_dir, completed)
    elif quick:
        print("=== Adversarial Editing === [skipped --quick]\n")
    else:
        print("=== Adversarial Editing === [cached]\n")

    # ── Phase 6: Review ──
    if "review" not in completed and not quick:
        print("=== Phase 6/7: Dual-Persona Review ===")
        persona_mode = "dual-persona" if dual_review else "single"
        print(f"  Review mode: {persona_mode}")
        start = time.time()
        review = run_full_review(chapters, project_dir, config, dual_persona=dual_review)
        elapsed = time.time() - start
        print(f"  Overall score: {review.get('overall_avg_score', 'N/A')}/10")
        print(f"  Weakest chapter: Ch {review.get('weakest_chapter', '?')} ({review.get('weakest_score', '?')}/10)")
        if review.get("needs_revision"):
            print(f"  Revision needed: YES (target: {config.scoring.target_chapter_score})")
        else:
            print(f"  Revision needed: NO")
        print(f"  Time: {elapsed:.1f}s\n")
        completed.add("review")
        _save_checkpoint(project_dir, completed)
    elif quick and "review" not in completed:
        print("=== Phase 6/7: Review === [skipped --quick]\n")
    else:
        print("=== Phase 6/7: Review === [cached]\n")

    # ── Phase 7: Export ──
    if "export" not in completed:
        print("=== Phase 7/7: Export ===")
        start = time.time()
        export = export_manuscript(chapters, spec, world, characters, outline, project_dir)
        elapsed = time.time() - start
        print(f"  Manuscript: {export['manuscript_md']}")
        for fmt, result in export.get("pandoc", {}).items():
            if result["success"]:
                print(f"  {fmt.upper()}: {result['path']}")
            else:
                print(f"  {fmt.upper()}: skipped ({result['error']})")
        print(f"  Time: {elapsed:.1f}s\n")
        completed.add("export")
        _save_checkpoint(project_dir, completed)
    else:
        print("=== Phase 7/7: Export === [cached]\n")

    # Summary
    total_words = sum(c.get("word_count", 0) for c in chapters) if chapters else 0
    pipeline_elapsed = time.time() - pipeline_start
    print("=" * 50)
    print(f"  Project: {spec.get('title', 'Untitled')}")
    print(f"  Output: {project_dir}")
    print(f"  Chapters: {len(chapters) if chapters else 0} | Words: {total_words}")
    print(f"  Total time: {pipeline_elapsed:.1f}s ({pipeline_elapsed/60:.1f}m)")
    print("=" * 50)

    return project_dir


def main():
    parser = argparse.ArgumentParser(
        description="StoryForge v0.2 - autonomous novel-writing pipeline with revision loop"
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
        help="Fast mode - skip review, backprop, and adversarial phases",
    )
    parser.add_argument(
        "--single-variant",
        action="store_true",
        help="Disable parallel variants (draft 1 version per chapter, cheaper)",
    )
    parser.add_argument(
        "--single-review",
        action="store_true",
        help="Use single LLM review instead of dual-persona (half tokens)",
    )
    parser.add_argument(
        "--no-backprop",
        action="store_true",
        help="Skip backward propagation scan",
    )
    parser.add_argument(
        "--no-adversarial",
        action="store_true",
        help="Skip adversarial editing pass",
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

    run_full_pipeline(
        args.concept,
        config,
        resume_from=args.resume,
        quick=args.quick,
        parallel_variants=not args.single_variant,
        dual_review=not args.single_review,
        enable_backprop=not args.no_backprop,
        enable_adversarial=not args.no_adversarial,
    )


if __name__ == "__main__":
    main()

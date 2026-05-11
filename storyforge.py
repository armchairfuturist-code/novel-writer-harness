#!/usr/bin/env python3
"""StoryForge — autonomous novel-writing pipeline v0.3.

Usage:
    python storyforge.py "seed concept"
    python storyforge.py "seed concept" --genre mystery
    python storyforge.py "seed concept" --resume 7
    python storyforge.py "same concept"           # auto-resumes existing project
    python storyforge.py --benchmark

Pipeline:
    seed -> worldbuilding -> characters -> outline -> draft (revise, rhetorical variants,
    RAG, GBrain canonical state, ReIO compression) -> fact-check ->
    iterative backprop -> adversarial edit -> review (dual-persona) -> export

New in v0.3:
    - GBrain canonical state store (structured memory across chapters)
    - Postwriter-inspired rhetorical strategies (4 distinct narrative approaches)
    - ReIO context compression (StoryWriter-inspired, solves auto_compress_at_tokens)
    - Iterative backward propagation (loops until convergence)
    - Genre-specific beat templates (mystery, thriller, romance, fantasy, sci-fi)
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
from pipeline.iterative_backprop import run_iterative_backpropagation
from pipeline.adversarial_edit import run_adversarial_edit
from pipeline.export import export_manuscript

BANNER = """
  +=========================================================+
  |            StoryForge v0.3                               |
  |  GBrain + Rhetorical Strategies + ReIO + Backprop        |
  +=========================================================+
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
    iterative_backprop: bool = True,
    genre: Optional[str] = None,
    enable_gbrain: bool = True,
    enable_reio: bool = True,
) -> str:
    """Run the full StoryForge pipeline from seed to export.

    Args:
        concept: Seed concept for the story
        config: Optional Config override
        resume_from: Chapter number to start drafting from
        quick: If True, skip review, backprop, and adversarial phases
        parallel_variants: Draft multiple rhetorical variants per chapter
        dual_review: Use dual-persona review (higher quality)
        enable_backprop: Run backward propagation scan
        enable_adversarial: Run adversarial editing pass
        iterative_backprop: Use iterative backprop loop (convergence-based)
        genre: Genre template to use (mystery, thriller, romance, fantasy, sci-fi)
        enable_gbrain: Enable GBrain canonical state store
        enable_reio: Enable ReIO context compression

    Returns:
        str: Path to the project output directory
    """
    config = config or Config()
    pipeline_start = time.time()
    print(BANNER)
    print(f"Seed concept: {concept}")
    if genre:
        print(f"Genre template: {genre}")
    print()

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
    chapters = []

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

    # Apply genre template if specified
    if genre and "genre_template" not in completed:
        from templates import get_template
        template = get_template(genre)
        if template:
            print(f"=== Genre Template: {genre.title()} ===")
            print(f"  Structure: {template.get('structure', {}).get('tension_arc', 'standard')}")
            print(f"  Recommended chapters: {template.get('structure', {}).get('recommended_chapters', 'auto')}")
            if spec:
                spec["genre_template"] = genre
                spec["genre_beats"] = template.get("beats", [])
                spec["tracking_items"] = template.get("tracking", {}).get("must_track", [])
                with open(os.path.join(project_dir, "spec.json"), "w", encoding="utf-8") as f:
                    json.dump(spec, f, indent=2)
            print(f"  Template loaded.\n")
        completed.add("genre_template")
        _save_checkpoint(project_dir, completed)

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
        if genre:
            from templates import get_template
            template = get_template(genre)
            if template:
                beats = template.get("beats", [])
                # Tag chapters with their genre beat phase
                for act in outline.get("acts", []):
                    for ch in act.get("chapters", []):
                        ch_num = ch.get("chapter", 0)
                        for beat in beats:
                            cr = beat.get("chapter_range", [0, 0])
                            if cr[0] <= ch_num <= cr[1]:
                                ch["genre_phase"] = beat.get("phase", "")
                                ch["required_elements"] = beat.get("required_elements", [])
                                break
                outline["genre_template"] = genre
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
        print(f"  Parallel rhetorical variants: {parallel_variants}")
        print(f"  Revision loop: ENABLED (threshold: {config.scoring.min_chapter_score})")
        print(f"  GBrain canonical state: {'ON' if enable_gbrain else 'OFF'}")
        print(f"  ReIO compression: {'ON' if enable_reio else 'OFF'}")
        print()
        start = time.time()
        chapters = run_draft(
            spec, world, characters, outline, project_dir, config,
            resume_from=resume_from,
            parallel_variants=parallel_variants,
            enable_gbrain=enable_gbrain,
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
        if resume_from > 1:
            print("  WARNING: --resume N ignored because 'draft' phase is already completed.")
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
    if ("draft" in completed or "draft" in PHASES) and not quick:
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

    # ── Backward Propagation (iterative in v0.3) ──
    if "backprop" not in completed and not quick and enable_backprop:
        print("=== Backward Propagation: Forward Contradictions ===")
        start = time.time()

        if iterative_backprop:
            print(f"  Mode: ITERATIVE (up to {config.scoring.max_full_review_rounds} iterations)")
            bp_report = run_iterative_backpropagation(
                project_dir,
                max_iterations=config.scoring.max_full_review_rounds,
            )
        else:
            print("  Mode: ONE-SHOT")
            bp_report = run_backward_propagation(project_dir)

        elapsed = time.time() - start
        print(f"  Status: {bp_report['status']}")
        print(f"  {bp_report['summary']}")

        if iterative_backprop:
            for it in bp_report.get("iteration_history", []):
                it_num = it["iteration"]
                issues = it["total_issues"]
                print(f"    Iter {it_num}: {issues} issues")

        for issue in bp_report.get("final_issues", [])[:5]:
            tag = {"FAIL": "!", "WARN": "?", "INFO": "i"}.get(issue.get("severity", "INFO"), "?")
            print(f"    [{tag}] Ch {issue.get('target_chapter', '?'):>2}: {issue['detail'][:100]}")
        if len(bp_report.get("final_issues", [])) > 5:
            print(f"    ... and {len(bp_report['final_issues']) - 5} more")
        print(f"  Time: {elapsed:.1f}s\n")
        completed.add("backprop")
        _save_checkpoint(project_dir, completed)
    elif quick:
        print("=== Backward Propagation === [skipped --quick]\n")
    else:
        print("=== Backward Propagation === [cached]\n")

    # ── Adversarial Editing ──
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
        if not chapters or len(chapters) == 0:
            print("  WARNING: No chapters to export. Skipping export phase.\n")
            completed.add("export")
            _save_checkpoint(project_dir, completed)
            return project_dir
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
        description="StoryForge v0.3 - autonomous novel-writing pipeline with GBrain, rhetorical strategies, ReIO, iterative backprop"
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
        help="Disable parallel rhetorical variants (draft 1 version per chapter, cheaper)",
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
    parser.add_argument(
        "--genre",
        choices=["mystery", "thriller", "romance", "fantasy", "sci-fi"],
        help="Genre template with structured beats and tracking",
    )
    parser.add_argument(
        "--interactive",
        action="store_true",
        help="Run in interactive interview mode (guided Q&A before generation)",
    )
    parser.add_argument(
        "--depth",
        choices=["quick", "standard", "comprehensive"],
        default="standard",
        help="Interview depth (quick=3 questions, standard=24, comprehensive=73). Default: standard",
    )
    parser.add_argument(
        "--model-override",
        help="Override the default model for interview phase",
    )
    parser.add_argument(
        "--no-iterative-backprop",
        action="store_true",
        help="Use one-shot backprop instead of iterative (default: iterative)",
    )
    parser.add_argument(
        "--no-gbrain",
        action="store_true",
        help="Disable GBrain canonical state store",
    )
    parser.add_argument(
        "--no-reio",
        action="store_true",
        help="Disable ReIO context compression",
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
        iterative_backprop=not args.no_iterative_backprop,
        genre=args.genre,
        enable_gbrain=not args.no_gbrain,
        enable_reio=not args.no_reio,
    )


if __name__ == "__main__":
    main()
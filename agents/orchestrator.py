"""Showrunner Agent — plans the novel, creates chapter assignments,
coordinates parallel writer agents, and orchestrates the full pipeline.

The Showrunner is the "director" of the multi-agent system. It:
1. Plans the novel structure (acts, chapters, POV assignments)
2. Creates a work manifest with per-chapter briefs
3. Deploys writer agents in parallel batches
4. Deploys critic agents to review completed chapters
5. Deploys continuity agent to reconcile canonical state
6. Iterates until quality thresholds are met
7. Deploys editor for final polish
8. Deploys export for manuscript compilation
"""

import json
import os
import time
from datetime import datetime
from typing import Any, Optional

from config import Config
from agents.base import (
    StoryForgeAgent,
    TASK_PLAN_NOVEL,
    TASK_ASSIGN_BATCH,
    TASK_BATCH_DRAFT,
    TASK_BATCH_REVIEW,
    TASK_BUILD_WORLD,
    TASK_CREATE_CHARACTERS,
    TASK_CREATE_OUTLINE,
    TASK_SCORE_MECHANICAL,
    TASK_SCAN_CONTINUITY,
    TASK_BACKWARD_PROPAGATE,
    TASK_EDIT_ADVERSARIAL,
    TASK_EXPORT_MANUSCRIPT,
)

from pipeline.seed import run_seed
from pipeline.worldbuilding import run_worldbuilding
from pipeline.characters import run_characters
from pipeline.outline import run_outline
from pipeline.canonical_store import CanonicalStore, FileCanonicalStore, create_canonical_store

from agents.writer import WriterAgent
from agents.critic import CriticAgent
from agents.continuity import ContinuityAgent


# ── Parallel Execution Pool ────────────────────────────────────────────


class AgentPool:
    """Simple pool for running multiple agents in parallel.

    Manages N agent instances and dispatches tasks to them.
    In the current implementation, agents are stateless enough that
    we can instantiate them per-task. This class handles the lifecycle.
    """

    def __init__(self, config: Optional[Config] = None):
        self.config = config or Config()

    def run_parallel(
        self,
        agent_class: type,
        tasks: list[dict[str, Any]],
        shared_context: Optional[dict[str, Any]] = None,
        max_concurrency: int = 3,
    ) -> list[dict[str, Any]]:
        """Run multiple agent instances in parallel on a list of tasks.

        Args:
            agent_class: Agent class to instantiate per task.
            tasks: List of task dicts (each must have a 'type' key).
            shared_context: Shared context passed to all agents.
            max_concurrency: Max parallel agents (default 3).

        Returns:
            List of result dicts in the same order as tasks.
        """
        results = []
        # Process in batches of max_concurrency
        for i in range(0, len(tasks), max_concurrency):
            batch = tasks[i:i + max_concurrency]
            batch_results = []
            for task in batch:
                agent = agent_class(
                    agent_id=f"{task.get('type', 'agent')}_{i}_{batch.index(task)}",
                    config=self.config,
                )
                result = agent.run(task, shared_context)
                batch_results.append(result)
            results.extend(batch_results)
        return results


# ── Showrunner Agent ───────────────────────────────────────────────────


class ShowrunnerAgent(StoryForgeAgent):
    """The Director — plans the novel, creates assignments, coordinates workers.

    The Showrunner is the highest-level agent. It does NOT draft prose itself.
    It plans, delegates, and integrates.

    Capabilities:
        - plan_novel: Produce story bible (spec, world, characters, outline)
        - assign_batch: Create chapter briefs for a batch of chapters
        - coordinate: Orchestrate the full pipeline from seed to export
    """

    @property
    def capabilities(self) -> dict[str, Any]:
        return {
            "role": "Showrunner / Director",
            "can_handle": [
                TASK_PLAN_NOVEL,
                TASK_ASSIGN_BATCH,
                TASK_BUILD_WORLD,
                TASK_CREATE_CHARACTERS,
                TASK_CREATE_OUTLINE,
            ],
            "model": self.config.model_for_phase("seed").name,
            "max_concurrency": 1,
            "description": "Plans novel structure, creates chapter briefs, coordinates all workers",
        }

    def can_handle(self, task_type: str) -> bool:
        return task_type in {
            TASK_PLAN_NOVEL, TASK_ASSIGN_BATCH,
            TASK_BUILD_WORLD, TASK_CREATE_CHARACTERS,
            TASK_CREATE_OUTLINE,
        }

    def run(
        self,
        task: dict[str, Any],
        context: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        task_type = task.get("type")
        ctx = context or {}

        if task_type == TASK_PLAN_NOVEL:
            return self._plan_novel(task, ctx)
        elif task_type == TASK_BUILD_WORLD:
            return self._build_world(task, ctx)
        elif task_type == TASK_CREATE_CHARACTERS:
            return self._create_characters(task, ctx)
        elif task_type == TASK_CREATE_OUTLINE:
            return self._create_outline(task, ctx)
        elif task_type == TASK_ASSIGN_BATCH:
            return self._assign_batch(task, ctx)
        else:
            return {
                "status": "failed",
                "agent_id": self.agent_id,
                "error": f"Showrunner cannot handle task type: {task_type}",
            }

    # ── Planning ───────────────────────────────────────────────────────

    def _plan_novel(
        self,
        task: dict[str, Any],
        ctx: dict[str, Any],
    ) -> dict[str, Any]:
        """Plan the novel from a seed concept or precompiled spec.

        Input:
            task['concept']: Seed concept string, OR
            task['precompiled_spec']: Dict from interview story bible

        Output:
            spec: Project spec (title, genre, POV, chapter count, etc.)
            world: World bible
            characters: Character profiles
            outline: Chapter-by-chapter outline

        Returns manifest-ready full story bible.
        """
        concept = task.get("concept", "")
        precompiled_spec = task.get("precompiled_spec")
        genre = task.get("genre")
        project_dir = task.get("project_dir", "")
        config = self.config

        # ── Phase: Seed ──
        if precompiled_spec is not None:
            spec = precompiled_spec
            print(f"  [Showrunner] Seed phase: using precompiled spec ({spec.get('title', 'Untitled')})")
        else:
            print(f"  [Showrunner] Planning novel from concept...")
            spec = run_seed(concept)
            print(f"  [Showrunner] Seed complete: {spec.get('title', 'Untitled')}")

        # Apply genre template
        if genre:
            from templates import get_template
            template = get_template(genre)
            if template:
                spec["genre_template"] = genre
                spec["genre_beats"] = template.get("beats", [])
                spec["tracking_items"] = template.get("tracking", {}).get("must_track", [])
                print(f"  [Showrunner] Genre template applied: {genre}")

        # ── Phase: Worldbuilding ──
        print(f"  [Showrunner] Building world...")
        world = run_worldbuilding(spec)
        print(f"  [Showrunner] World complete: {world.get('world_name', 'Generated World')}")

        # ── Phase: Characters ──
        print(f"  [Showrunner] Creating characters...")
        characters = run_characters(spec, world)
        char_count = len(characters.get("characters", []))
        print(f"  [Showrunner] Characters created: {char_count}")

        # ── Phase: Outline ──
        print(f"  [Showrunner] Creating outline...")
        outline = run_outline(spec, world, characters)
        acts = outline.get("acts", [])
        ch_count = sum(len(a.get("chapters", [])) for a in acts)
        print(f"  [Showrunner] Outline complete: {len(acts)} acts, {ch_count} chapters")

        return {
            "status": "success",
            "agent_id": self.agent_id,
            "spec": spec,
            "world": world,
            "characters": characters,
            "outline": outline,
            "chapter_count": ch_count,
        }

    def _build_world(
        self,
        task: dict[str, Any],
        ctx: dict[str, Any],
    ) -> dict[str, Any]:
        """Standalone worldbuilding phase."""
        spec = task.get("spec", {})
        world = run_worldbuilding(spec)
        return {
            "status": "success",
            "agent_id": self.agent_id,
            "world": world,
        }

    def _create_characters(
        self,
        task: dict[str, Any],
        ctx: dict[str, Any],
    ) -> dict[str, Any]:
        """Standalone character creation phase."""
        spec = task.get("spec", {})
        world = task.get("world", {})
        characters = run_characters(spec, world)
        return {
            "status": "success",
            "agent_id": self.agent_id,
            "characters": characters,
        }

    def _create_outline(
        self,
        task: dict[str, Any],
        ctx: dict[str, Any],
    ) -> dict[str, Any]:
        """Standalone outline creation phase."""
        spec = task.get("spec", {})
        world = task.get("world", {})
        characters = task.get("characters", {})
        genre = task.get("genre")
        outline = run_outline(spec, world, characters)
        if genre:
            from templates import get_template
            template = get_template(genre)
            if template:
                beats = template.get("beats", [])
                for act in outline.get("acts", []):
                    for ch in act.get("chapters", []):
                        ch_num = ch.get("chapter", 0)
                        for beat in beats:
                            cr = beat.get("chapter_range", [0, 0])
                            if cr[0] <= ch_num <= cr[1]:
                                ch["genre_phase"] = beat.get("phase", "")
                                ch["required_elements"] = beat.get("required_elements", [])
                                break
        return {
            "status": "success",
            "agent_id": self.agent_id,
            "outline": outline,
        }

    # ── Batch Assignment ────────────────────────────────────────────────

    def _assign_batch(
        self,
        task: dict[str, Any],
        ctx: dict[str, Any],
    ) -> dict[str, Any]:
        """Create chapter briefs for a batch of chapters.

        Takes the outline and produces structured briefs that Writer agents
        can consume. Each brief includes: chapter context, POV, key events,
        emotional arc, foreshadowing, character arc beat, world context,
        active threads, and canonical state.

        Input:
            task['outline']: The full outline
            task['batch_start']: First chapter number (1-indexed)
            task['batch_end']: Last chapter number (inclusive)
            task['batch_size']: Alternative: how many chapters to assign

        Output:
            chapter_briefs: List of per-chapter brief dicts
        """
        outline = task.get("outline", {})
        acts = outline.get("acts", [])
        all_chapters = []
        for act in acts:
            for ch in act.get("chapters", []):
                all_chapters.append(ch)

        if not all_chapters:
            return {
                "status": "failed",
                "agent_id": self.agent_id,
                "error": "No chapters found in outline",
            }

        batch_start = task.get("batch_start", 1)
        batch_end = task.get("batch_end", len(all_chapters))

        batch_chapters = [
            ch for ch in all_chapters
            if batch_start <= ch.get("chapter", 0) <= batch_end
        ]

        chapter_briefs = []
        for ch in batch_chapters:
            brief = {
                "chapter": ch.get("chapter", 0),
                "title": ch.get("title", f"Chapter {ch.get('chapter', 0)}"),
                "pov": ch.get("pov", "Unknown"),
                "summary": ch.get("summary", ""),
                "key_events": ch.get("key_events", []),
                "emotional_arc": ch.get("emotional_arc", ""),
                "foreshadowing": ch.get("foreshadowing", ""),
                "character_arc_beat": ch.get("character_arc_beat", ""),
                "genre_phase": ch.get("genre_phase", ""),
                "required_elements": ch.get("required_elements", []),
            }
            chapter_briefs.append(brief)

        return {
            "status": "success",
            "agent_id": self.agent_id,
            "chapter_briefs": chapter_briefs,
            "batch_start": batch_start,
            "batch_end": batch_end,
        }


# ── High-Level Pipeline Orchestration ──────────────────────────────────


def slugify(text: str) -> str:
    import re
    text = text.lower().strip()
    text = re.sub(r'[^a-z0-9\s-]', '', text)
    text = re.sub(r'[\s-]+', '-', text)
    return text[:60]


def run_showrunner_pipeline(
    concept: str,
    config: Optional[Config] = None,
    precompiled_spec: Optional[dict] = None,
    genre: Optional[str] = None,
    project_dir: Optional[str] = None,
    parallel_writers: int = 3,
    enable_revision: bool = True,
    enable_backprop: bool = True,
    enable_adversarial: bool = True,
    feedback_enabled: bool = True,
    enable_debate: bool = False,
    enable_changes: bool = True,
    style_profile_name: Optional[str] = None,
    auto_style_extract: bool = False,
    enable_knowledge_base: bool = True,
    enable_validate_outline: bool = True,
) -> str:
    """Run the full multi-agent pipeline from concept to manuscript.

    This is the primary entry point for the agent-based system.
    It replaces the old run_full_pipeline() with Showrunner-coordinated execution.

    Args:
        concept: Seed concept string.
        config: Config override.
        precompiled_spec: Optional pre-compiled spec from interview.
        genre: Optional genre template.
        project_dir: Output directory override.
        parallel_writers: Number of writer agents to run in parallel (default 3).
        enable_revision: Enable revision loop on chapters below threshold.
        enable_backprop: Enable backward propagation scan.
        enable_adversarial: Enable adversarial editing pass.
        feedback_enabled: Enable post-chapter feedback review.
        enable_debate: Reserved for debate protocol (not yet wired in showrunner path).

    Returns:
        str: Path to the project output directory.
    """
    pipeline_start = time.time()
    config = config or Config()
    project_slug = slugify(concept)[:40]
    project_dir = project_dir or os.path.join(
        config.project_dir or os.path.join(os.path.expanduser("~"), "storyforge-projects"),
        project_slug,
    )
    os.makedirs(project_dir, exist_ok=True)

    # ── 1. Showrunner: Plan the Novel ──────────────────────────────────
    print("=" * 60)
    print("  SHOWRUNNER: Planning Phase")
    print("=" * 60)

    showrunner = ShowrunnerAgent(agent_id="showrunner-01", config=config)

    plan_result = showrunner.run({
        "type": TASK_PLAN_NOVEL,
        "concept": concept,
        "precompiled_spec": precompiled_spec,
        "genre": genre,
        "project_dir": project_dir,
    })

    if plan_result["status"] != "success":
        raise RuntimeError(f"Showrunner planning failed: {plan_result.get('error', 'Unknown error')}")

    spec = plan_result["spec"]
    world = plan_result["world"]
    characters = plan_result["characters"]
    outline = plan_result["outline"]
    total_chapters = plan_result["chapter_count"]

    # Save planning artifacts
    for name, data in [("spec", spec), ("world", world),
                        ("characters", characters), ("outline", outline)]:
        with open(os.path.join(project_dir, f"{name}.json"), "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

    print(f"  [Showrunner] Novel planned: {spec.get('title', 'Untitled')}")
    print(f"  [Showrunner] Total chapters: {total_chapters}")
    print(f"  [Showrunner] Project dir: {project_dir}")
    print()

    # ── 2. Initialize Canonical Store ──────────────────────────────────
    canonical_store: CanonicalStore = FileCanonicalStore(project_dir=project_dir)

    # ── 3. Agent Pool for parallel work ────────────────────────────────
    pool = AgentPool(config=config)

    # ── 4. Draft in Batches ────────────────────────────────────────────
    print("=" * 60)
    print("  SHOWRUNNER: Drafting Phase (Parallel Writer Agents)")
    print(f"  Concurrency: {parallel_writers} writers per batch")
    print("=" * 60)

    batch_size = parallel_writers
    chapters_dir = os.path.join(project_dir, "chapters")
    os.makedirs(chapters_dir, exist_ok=True)

    all_chapter_results = []
    written_chapter_meta = []

    for batch_start in range(1, total_chapters + 1, batch_size):
        batch_end = min(batch_start + batch_size - 1, total_chapters)

        print(f"\n  [Showrunner] Assigning batch: Ch {batch_start}–{batch_end}")

        # Create chapter briefs for this batch
        brief_result = showrunner.run({
            "type": TASK_ASSIGN_BATCH,
            "outline": outline,
            "batch_start": batch_start,
            "batch_end": batch_end,
        })

        chapter_briefs = brief_result.get("chapter_briefs", [])

        # Build writer tasks with context
        writer_tasks = []
        for brief in chapter_briefs:
            # Build retrieved context from written chapters
            retrieved_context = ""
            if written_chapter_meta:
                from pipeline.draft import BM25Retriever
                retriever = BM25Retriever()
                retriever.index(written_chapter_meta)
                query = f"{brief['summary']} {brief['emotional_arc']} {brief['pov']}"
                relevant = retriever.search(query, k=3, exclude_chapters=set())
                if relevant:
                    lines = []
                    for rc in relevant:
                        for wc in written_chapter_meta:
                            if wc.get("chapter") == rc["chapter"]:
                                lines.append(f"  - Ch {rc['chapter']}: {wc.get('summary', '')[:200]}")
                                break
                    if lines:
                        retrieved_context = "Related story elements:\n" + "\n".join(lines)

            # Canonical state context
            canonical_context = canonical_store.format_context_for_drafting(
                brief["chapter"], brief["summary"]
            )

            # Active threads from canonical store
            active_threads = []
            thread_memories = canonical_store.recall(
                "active plot threads",
                k=5,
                tag_filter=["plot_thread", "active"],
            )
            for m in thread_memories:
                active_threads.append(m.get("value", ""))

            writer_tasks.append({
                "type": TASK_DRAFT_CHAPTER,
                "chapter_brief": brief,
                "world": world,
                "characters": characters,
                "project_dir": project_dir,
                "retrieved_context": retrieved_context,
                "canonical_context": canonical_context,
                "active_threads": active_threads,
                "enable_revision": enable_revision,
                "config": config,
            })

        # Deploy writer agents in parallel
        print(f"  [Showrunner] Deploying {len(writer_tasks)} writer(s)...")
        writer_results = pool.run_parallel(
            agent_class=WriterAgent,
            tasks=writer_tasks,
            shared_context={"project_dir": project_dir},
            max_concurrency=parallel_writers,
        )

        # Process results: save chapters, update canonical state, collect metadata
        for wr in writer_results:
            if wr["status"] != "success":
                print(f"  [Showrunner] Writer failed: {wr.get('error', 'Unknown')}")
                continue

            ch_data = wr["chapter"]
            ch_num = ch_data.get("chapter", 0)
            ch_title = ch_data.get("title", f"Chapter {ch_num}")
            content = ch_data.get("content", "")
            score = ch_data.get("score", {})
            word_count = ch_data.get("word_count", len(content.split()))

            # Write chapter file
            ch_filename = f"chapter-{ch_num:03d}.md"
            ch_path = os.path.join(chapters_dir, ch_filename)
            header = f"> POV: {ch_data.get('pov', 'Unknown')} | Score: {score.get('total_score', 'N/A')}/10 | Words: {word_count}\n\n"
            with open(ch_path, "w", encoding="utf-8") as f:
                f.write(header + content)

            # Update canonical store with new chapter state
            canonical_store.store(
                key=f"ch{ch_num}_summary",
                value=f"Ch {ch_num} ({ch_title}): {ch_data.get('summary', '')[:200]}",
                tags=["chapter_summary", f"ch{ch_num}"],
            )

            # Store character developments
            for trait in ch_data.get("character_traits", []):
                canonical_store.store(
                    key=f"char_{trait.get('name', 'unknown')}_{trait.get('trait', '')}",
                    value=trait.get("value", ""),
                    tags=["character_trait", trait.get("name", "").lower()],
                )

            # Store foreshadowing plants
            for plant in ch_data.get("foreshadowing_plants", []):
                canonical_store.store(
                    key=f"foreshadow_ch{ch_num}_{plant.get('element', '')}",
                    value=plant.get("description", ""),
                    tags=["foreshadowing", "unpaid"],
                )

            # Store plot thread updates
            for thread in ch_data.get("plot_threads", []):
                canonical_store.store(
                    key=f"thread_{thread.get('name', 'unknown')}",
                    value=thread.get("status", ""),
                    tags=["plot_thread", thread.get("status", "active")],
                )

            result_entry = {
                "chapter": ch_num,
                "title": ch_title,
                "file": ch_path,
                "word_count": word_count,
                "score": score,
                "variant": ch_data.get("variant", ""),
                "revisions": ch_data.get("revisions_done", 0),
            }
            all_chapter_results.append(result_entry)

            meta = {
                "chapter": ch_num,
                "title": ch_title,
                "summary": ch_data.get("summary", ""),
                "pov": ch_data.get("pov", ""),
                "key_events": ch_data.get("key_events", []),
            }
            written_chapter_meta.append(meta)

            print(f"    Ch {ch_num:>2}: {word_count:>5} words | "
                  f"Score: {score.get('total_score', '?'):>4}/10 | "
                  f"Revisions: {ch_data.get('revisions_done', 0)}")

        print(f"  [Showrunner] Batch Ch {batch_start}–{batch_end} complete. "
              f"Total chapters written: {len(all_chapter_results)}/{total_chapters}")

    all_chapter_results.sort(key=lambda x: x["chapter"])

    # ── 5. Critic: Full Review ─────────────────────────────────────────
    if enable_revision and all_chapter_results:
        print(f"\n{'=' * 60}")
        print("  SHOWRUNNER: Review Phase (Critic Agent)")
        print("=" * 60)

        critic = CriticAgent(agent_id="critic-01", config=config)
        review_result = critic.run({
            "type": TASK_BATCH_REVIEW,
            "chapters": all_chapter_results,
            "project_dir": project_dir,
            "spec": spec,
        })

        print(f"  [Critic] Overall score: {review_result.get('overall_avg_score', 'N/A')}/10")
        print(f"  [Critic] Weakest chapter: Ch {review_result.get('weakest_chapter', '?')}")

        # Save review
        with open(os.path.join(project_dir, "review.json"), "w", encoding="utf-8") as f:
            json.dump(review_result, f, indent=2)

    # ── 6. Continuity: Backward Propagation ───────────────────────────
    if enable_backprop and all_chapter_results:
        print(f"\n{'=' * 60}")
        print("  SHOWRUNNER: Continuity Scan (Continuity Agent)")
        print("=" * 60)

        continuity = ContinuityAgent(agent_id="continuity-01", config=config)
        bp_result = continuity.run({
            "type": TASK_BACKWARD_PROPAGATE,
            "project_dir": project_dir,
            "chapters": all_chapter_results,
            "canonical_store": canonical_store,
        })

        print(f"  [Continuity] Status: {bp_result.get('status', 'unknown')}")
        print(f"  [Continuity] Issues found: {bp_result.get('total_issues', 0)}")

        with open(os.path.join(project_dir, "backpropagation.json"), "w", encoding="utf-8") as f:
            json.dump(bp_result, f, indent=2)

    # ── 7. Editor: Adversarial Tightening ─────────────────────────────
    if enable_adversarial and all_chapter_results:
        print(f"\n{'=' * 60}")
        print("  SHOWRUNNER: Editing Phase (Editor Agent)")
        print("=" * 60)

        from agents.editor import EditorAgent
        editor = EditorAgent(agent_id="editor-01", config=config)
        ae_result = editor.run({
            "type": TASK_EDIT_ADVERSARIAL,
            "project_dir": project_dir,
            "chapters": all_chapter_results,
        })

        print(f"  [Editor] Words removed: {ae_result.get('total_words_removed', 0)}")
        print(f"  [Editor] Cut percentage: {ae_result.get('total_pct_cut', 0)}%")

        with open(os.path.join(project_dir, "adversarial.json"), "w", encoding="utf-8") as f:
            json.dump(ae_result, f, indent=2)

    # ── 8. Export ──────────────────────────────────────────────────────
    if all_chapter_results:
        print(f"\n{'=' * 60}")
        print("  SHOWRUNNER: Export Phase")
        print("=" * 60)

        from pipeline.export import export_manuscript
        export = export_manuscript(
            all_chapter_results, spec, world, characters, outline, project_dir
        )

        print(f"  [Export] Manuscript: {export.get('manuscript_md', 'N/A')}")
        for fmt, result in export.get("pandoc", {}).items():
            if result["success"]:
                print(f"  [Export] {fmt.upper()}: {result['path']}")

    # ── Summary ────────────────────────────────────────────────────────
    total_words = sum(c.get("word_count", 0) for c in all_chapter_results)
    pipeline_elapsed = time.time() - pipeline_start

    print()
    print("=" * 60)
    print(f"  SHOWRUNNER: Pipeline Complete")
    print(f"  Project: {spec.get('title', 'Untitled')}")
    print(f"  Output: {project_dir}")
    print(f"  Chapters: {len(all_chapter_results)} | Words: {total_words}")
    print(f"  Total time: {pipeline_elapsed:.1f}s ({pipeline_elapsed / 60:.1f}m)")
    print("=" * 60)

    return project_dir

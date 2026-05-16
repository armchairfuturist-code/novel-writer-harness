"""Iterative backward propagation — loop until no contradictions remain.

Extends the base backprop module with an iterative loop:
1. Run backward propagation scan
2. If issues found, generate revision instructions
3. Simulate applying fixes (or mark chapters for revision)
4. Re-scan to verify fixes resolved the issues
5. Loop until max iterations or zero issues

This replaces the one-shot scan with a proper convergence loop.
"""

import json
import os
import re
import time
from typing import Optional

from config import Config
from pipeline.api import CrofaiClient
from pipeline.backprop import (
    scan_forward_inconsistencies,
    scan_foreshadowing_debt,
    generate_revision_instructions,
)




def _apply_backprop_fixes(
    project_dir: str,
    chapters_dir: str,
    all_issues: list,
    config: Config,
    iteration: int,
) -> int:
    """Apply revision fixes to chapter files using the LLM."""
    if not all_issues:
        return 0

    client = CrofaiClient(config)
    model = config.model_for_phase("backprop")
    chapter_files = sorted(f for f in os.listdir(chapters_dir) if f.endswith(".md"))

    issues_by_chapter: dict[int, list[dict]] = {}
    for issue in all_issues:
        tch = issue.get("target_chapter", 0)
        if tch not in issues_by_chapter:
            issues_by_chapter[tch] = []
        issues_by_chapter[tch].append(issue)

    chapters_revised = 0
    for chap_num, chap_issues in issues_by_chapter.items():
        chap_file = None
        for cf in chapter_files:
            m = re.search(r'(\d+)', cf)
            if m and int(m.group(1)) == chap_num:
                chap_file = os.path.join(chapters_dir, cf)
                break
        if not chap_file or not os.path.exists(chap_file):
            continue

        with open(chap_file, "r", encoding="utf-8") as f:
            chap_text = f.read()

        NL = "\n"
        issue_lines = NL.join(
            f"- [{i.get('severity', 'INFO')}] {i.get('detail', '')}"
            for i in chap_issues[:5]
        )
        suggestion_lines = NL.join(
            i.get("suggestion", "") for i in chap_issues[:5]
        )

        revision_prompt = (
            "Revise the following chapter to fix these backward-propagation issues:"
            + NL + NL
            + "Issues to fix:" + NL + issue_lines + NL + NL
            + "Suggested fixes:" + NL + suggestion_lines + NL + NL
            + "Chapter text:" + NL + chap_text + NL + NL
            + "Return the FULL revised chapter text. "
            + "Preserve the chapter's voice, POV, and narrative arc while addressing all issues."
        )

        try:
            revised = client.chat_with_retry(
                model,
                messages=[{"role": "user", "content": revision_prompt}],
                temperature=0.5,
            )
            with open(chap_file, "w", encoding="utf-8") as f:
                f.write(revised)
            chapters_revised += 1
            print(f"        Revised Ch {chap_num} ({len(chap_issues)} issues)")
        except RuntimeError as e:
            print(f"        Failed to revise Ch {chap_num}: {e}")

    client.close()
    return chapters_revised
def run_iterative_backpropagation(
    project_dir: str,
    outline_path: str = "",
    max_iterations: int = 3,
    config: Optional[Config] = None,
) -> dict:
    """Run iterative backward propagation until convergence.

    Loops: scan -> generate fixes -> scan again -> repeat.
    Tracks issue reduction per iteration to measure convergence.

    Args:
        project_dir: Project directory containing chapters/
        outline_path: Path to outline.json
        max_iterations: Maximum convergence loops
        config: Optional Config

    Returns:
        dict: Comprehensive report with iteration history
    """
    config = config or Config()
    chapters_dir = os.path.join(project_dir, "chapters")
    if not os.path.isdir(chapters_dir):
        return {
            "status": "SKIPPED",
            "reason": "No chapters directory found",
            "iterations": 0,
            "total_issues_final": 0,
        }

    # Resolve outline path
    if outline_path:
        o_path = outline_path if os.path.isabs(outline_path) else os.path.join(project_dir, outline_path)
    else:
        o_path = os.path.join(project_dir, "outline.json")

    iteration_history = []
    all_issues_by_iter = []

    for iteration in range(max_iterations):
        print(f"    Backprop iteration {iteration + 1}/{max_iterations}...")

        # Run scans
        continuity_issues = scan_forward_inconsistencies(chapters_dir)
        foreshadow_issues = scan_foreshadowing_debt(chapters_dir, o_path)
        all_issues = continuity_issues + foreshadow_issues

        # Deduplicate by detail string
        seen_details = set()
        unique_issues = []
        for issue in all_issues:
            detail = issue.get("detail", "")
            if detail not in seen_details:
                seen_details.add(detail)
                unique_issues.append(issue)
        all_issues = unique_issues

        all_issues_by_iter.append(all_issues)

        errors = [i for i in all_issues if i.get("severity") == "FAIL"]
        warnings = [i for i in all_issues if i.get("severity") == "WARN"]

        iteration_record = {
            "iteration": iteration + 1,
            "total_issues": len(all_issues),
            "errors": len(errors),
            "warnings": len(warnings),
        }
        iteration_history.append(iteration_record)

        print(f"      Found {len(all_issues)} issues ({len(errors)} errors, {len(warnings)} warnings)")

        # Check convergence
        if len(all_issues) == 0:
            print(f"      All issues resolved. Converged in {iteration + 1} iteration(s).")
            break

        # Generate revision instructions (always — even on last iteration)
        instructions = generate_revision_instructions(all_issues)

        # Save revision plan for this iteration
        rev_plan = {
            "iteration": iteration + 1,
            "instructions": instructions,
            "issues_before": len(all_issues),
        }
        rev_path = os.path.join(project_dir, f"backprop-revision-iter-{iteration + 1}.json")
        with open(rev_path, "w", encoding="utf-8") as f:
            json.dump(rev_plan, f, indent=2)
        print(f"      Revision plan saved to {rev_path}")

        # Apply fixes to chapter files via LLM (always — even on last iteration)
        chapters_revised = _apply_backprop_fixes(
            project_dir, chapters_dir, all_issues, config, iteration,
        )
        if chapters_revised:
            print(f"      Applied fixes to {chapters_revised} chapter(s)")

        # Stagnation check — break AFTER applying fixes so the fix attempt is not lost
        if iteration > 0:
            prev_issues = all_issues_by_iter[iteration - 1]
            prev_details = {i.get("detail", "") for i in prev_issues}
            curr_details = {i.get("detail", "") for i in all_issues}
            overlap = prev_details & curr_details

            if len(overlap) >= len(prev_details) * 0.8:
                print(f"      Stagnation detected ({len(overlap)}/{len(prev_details)} issues unchanged). Applied fixes before stopping.")
                break

    # Build final report
    total_issues_final = len(all_issues_by_iter[-1]) if all_issues_by_iter else 0
    final_errors = len([i for i in (all_issues_by_iter[-1] if all_issues_by_iter else []) if i.get("severity") == "FAIL"])

    # Track issue reduction trend
    issue_counts = [r["total_issues"] for r in iteration_history]
    reduction = (issue_counts[0] - total_issues_final) if issue_counts else 0
    reduction_pct = round((reduction / max(issue_counts[0], 1)) * 100, 1) if issue_counts else 0

    report = {
        "status": "PASS" if total_issues_final == 0 else ("STALLED" if final_errors == 0 else "FAIL"),
        "total_issues_initial": issue_counts[0] if issue_counts else 0,
        "total_issues_final": total_issues_final,
        "reduction": reduction,
        "reduction_pct": reduction_pct,
        "iterations": len(iteration_history),
        "max_iterations": max_iterations,
        "converged": total_issues_final == 0,
        "iteration_history": iteration_history,
        "final_issues": all_issues_by_iter[-1] if all_issues_by_iter else [],
        "summary": (
            f"{len(iteration_history)} iterations: {issue_counts[0] if issue_counts else 0} -> {total_issues_final} issues "
            f"({reduction_pct}% reduction). "
            f"{'Converged.' if total_issues_final == 0 else 'Remaining issues need manual review.'}"
        ),
    }

    return report

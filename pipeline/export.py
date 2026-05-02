"""Export phase - convert the manuscript to final output formats.

Produces:
- Markdown (always - the canonical format)
- PDF via Pandoc + LaTeX (if available)
- EPUB via Pandoc (if available)

Also generates metadata files and a manuscript status summary.
"""

import json
import os
import subprocess
import shutil
from typing import Optional

from config import Config


def build_manuscript_markdown(
    chapters: list[dict],
    spec: dict,
    world: dict,
    characters: dict,
    outline: dict,
    project_dir: str,
) -> str:
    manuscript_path = os.path.join(project_dir, "manuscript.md")

    with open(manuscript_path, "w", encoding="utf-8") as f:
        f.write(f"# {spec.get('title', 'Untitled')}\n\n")
        f.write(f"**Genre:** {spec.get('genre', 'Unknown')}\n\n")
        f.write(f"**Tone:** {spec.get('tone', 'Neutral')}\n\n")
        f.write(f"**POV:** {spec.get('pov', 'Third Limited')}\n\n")
        f.write(f"**Word Count Target:** {spec.get('target_length', 'Unknown')}\n\n")
        f.write("---\n\n")
        f.write(f"*{spec.get('premise', '')}*\n\n")
        f.write("---\n\n")
        f.write("---\n\n")

        if isinstance(world, dict) and world.get("world_name"):
            f.write(f"## Setting: {world['world_name']}\n\n")
            if world.get("geography"):
                f.write(f"{world['geography'][:500]}\n\n")

        if isinstance(characters, dict):
            char_list = characters.get("characters", [])
            if char_list:
                f.write("## Dramatis Personae\n\n")
                for c in char_list:
                    name = c.get("name", "?")
                    role = c.get("role", "?")
                    f.write(f"- **{name}** ({role}): {c.get('personality', '')[:100]}\n")
                f.write("\n---\n\n")

        for ch in chapters:
            chapter_file = ch.get("file", "")
            if os.path.exists(chapter_file):
                with open(chapter_file, "r", encoding="utf-8") as cf:
                    content = cf.read()
                f.write(content)
                f.write("\n\n---\n\n")

    return manuscript_path


def try_pandoc_export(manuscript_path: str, project_dir: str, formats: list[str] = None) -> dict:
    if formats is None:
        formats = ["pdf", "epub"]

    pandoc_path = shutil.which("pandoc")
    if not pandoc_path:
        return {fmt: {"success": False, "path": None, "error": "pandoc not found on PATH"}
                for fmt in formats}

    results = {}
    for fmt in formats:
        output_path = os.path.join(project_dir, f"manuscript.{fmt}")
        try:
            cmd = [pandoc_path, manuscript_path, "-o", output_path]
            if fmt == "pdf":
                for engine in ["xelatex", "lualatex", "pdflatex"]:
                    if shutil.which(engine):
                        cmd.extend(["--pdf-engine", engine])
                        break

            result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            if result.returncode == 0:
                results[fmt] = {"success": True, "path": output_path, "error": None}
            else:
                results[fmt] = {"success": False, "path": None,
                                "error": result.stderr[:500]}
        except subprocess.TimeoutExpired:
            results[fmt] = {"success": False, "path": None, "error": "timeout after 120s"}
        except FileNotFoundError:
            results[fmt] = {"success": False, "path": None, "error": "LaTeX engine not found"}

    return results


def export_manuscript(chapters: list[dict], spec: dict, world: dict, characters: dict, outline: dict, project_dir: str) -> dict:
    os.makedirs(project_dir, exist_ok=True)

    manuscript_path = build_manuscript_markdown(chapters, spec, world, characters, outline, project_dir)

    meta_path = os.path.join(project_dir, "project.json")
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump({
            "title": spec.get("title", "Untitled"),
            "genre": spec.get("genre", "Unknown"),
            "chapters": len(chapters),
            "structure": outline.get("story_structure", "three_act"),
        }, f, indent=2)

    pandoc_results = try_pandoc_export(manuscript_path, project_dir)

    return {
        "manuscript_md": manuscript_path,
        "metadata": meta_path,
        "pandoc": pandoc_results,
        "chapters_count": len(chapters),
    }

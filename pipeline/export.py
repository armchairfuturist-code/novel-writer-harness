"""Export phase - convert the manuscript to final output formats.

Produces:
- Markdown (always - the canonical format)
- PDF via Pandoc + LaTeX (if available)
- EPUB via Pandoc (if available), or pure-Python fallback

Also generates metadata files and a manuscript status summary.
"""

import html as html_mod
import json
import os
import re
import subprocess
import shutil
import uuid
import zipfile
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
            geo = world.get("geography")
            if geo:
                # geography may be string, list, or dict — coerce to readable text
                if isinstance(geo, dict):
                    geo_text = ", ".join(f"{k}: {v}" for k, v in geo.items())
                elif isinstance(geo, list):
                    geo_text = ", ".join(str(g) for g in geo)
                else:
                    geo_text = str(geo)
                f.write(f"{geo_text[:500]}\n\n")

        if isinstance(characters, dict):
            char_list = characters.get("characters", [])
            if char_list:
                f.write("## Dramatis Personae\n\n")
                for c in char_list:
                    name = c.get("name", "?")
                    role = c.get("role", "?")
                    personality = c.get("personality") or c.get("arc") or c.get("background") or ""
                f.write(f"- **{name}** ({role}): {personality[:100]}\n")
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


def _md_to_xhtml(text: str, title: str) -> str:
    """Minimal markdown to XHTML converter (no dependencies)."""
    lines = text.split("\n")
    body: list[str] = []
    in_para = False

    def _close_para():
        nonlocal in_para
        if in_para:
            body.append("</p>")
            in_para = False

    for line in lines:
        stripped = line.strip()

        if stripped.startswith("> POV:") or stripped.startswith("> POV :"):
            continue

        heading_match = re.match(r'^(#{1,3})\s+(.+)', stripped)
        if heading_match:
            _close_para()
            level = len(heading_match.group(1))
            body.append(f"<h{level}>{html_mod.escape(heading_match.group(2))}</h{level}>")
            continue

        if not stripped:
            _close_para()
            continue

        content = html_mod.escape(stripped)
        content = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', content)
        content = re.sub(r'\*(.+?)\*', r'<em>\1</em>', content)
        content = re.sub(r'`(.+?)`', r'<code>\1</code>', content)

        if not in_para:
            body.append("<p>")
            in_para = True
        else:
            body.append("<br/>")
        body.append(content)

    _close_para()

    body_html = "\n".join(body)
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xml:lang="en" lang="en">
<head>
<meta charset="UTF-8"/>
<title>{html_mod.escape(title)}</title>
<style>
body {{ font-family: Georgia, serif; margin: 2em; line-height: 1.6; }}
h1 {{ font-size: 1.8em; margin-top: 2em; }}
p {{ text-indent: 1.5em; margin: 0.5em 0; }}
</style>
</head>
<body>
{body_html}
</body>
</html>"""


def _build_epub_from_chapters(
    chapter_files: list[str],
    output_path: str,
    title: str = "Untitled",
    lang: str = "en",
) -> str:
    """Build an EPUB3 file from a sorted list of .md chapter file paths.

    Uses only the Python standard library (zipfile, re, html, uuid).
    Returns the output_path on success.
    """
    book_id = str(uuid.uuid4())
    chapters: list[tuple[str, str, str]] = []

    for fpath in chapter_files:
        with open(fpath, "r", encoding="utf-8") as f:
            text = f.read()
        m = re.search(r'^#\s+(.+)', text, re.MULTILINE)
        title_text = m.group(1).strip() if m else os.path.splitext(os.path.basename(fpath))[0].replace("-", " ").title()
        slug = os.path.splitext(os.path.basename(fpath))[0]
        chapters.append((slug, title_text, text))

    with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)

        zf.writestr("META-INF/container.xml", """\
<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>""")

        manifest_items: list[str] = []
        spine_items: list[str] = []
        toc_navpoints: list[str] = []
        nav_links: list[str] = []

        for i, (slug, ch_title, text) in enumerate(chapters, 1):
            fname = f"{slug}.xhtml"
            zf.writestr(f"OEBPS/{fname}", _md_to_xhtml(text, ch_title))
            manifest_items.append(f'  <item id="{slug}" href="{fname}" media-type="application/xhtml+xml"/>')
            spine_items.append(f'  <itemref idref="{slug}"/>')
            toc_navpoints.append(
                f'    <navPoint id="navPoint-{i}" playOrder="{i}">\n'
                f'      <navLabel><text>{html_mod.escape(ch_title)}</text></navLabel>\n'
                f'      <content src="{fname}"/>\n'
                f'    </navPoint>'
            )
            nav_links.append(f'      <li><a href="{fname}">{html_mod.escape(ch_title)}</a></li>')

        manifest = "\n".join(manifest_items)
        spine = "\n".join(spine_items)
        navpoints = "\n".join(toc_navpoints)
        nav_html = "\n".join(nav_links)

        zf.writestr("OEBPS/content.opf", f"""\
<?xml version="1.0" encoding="UTF-8"?>
<package xmlns="http://www.idpf.org/2007/opf" unique-identifier="bookid" version="3.0">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:identifier id="bookid">{book_id}</dc:identifier>
    <dc:title>{html_mod.escape(title)}</dc:title>
    <dc:language>{lang}</dc:language>
  </metadata>
  <manifest>
    <item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>
    <item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>
{manifest}
  </manifest>
  <spine toc="ncx">
{spine}
  </spine>
</package>""")

        zf.writestr("OEBPS/toc.ncx", f"""\
<?xml version="1.0" encoding="UTF-8"?>
<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">
  <head>
    <meta name="dtb:uid" content="{book_id}"/>
  </head>
  <docTitle><text>{html_mod.escape(title)}</text></docTitle>
  <navMap>
{navpoints}
  </navMap>
</ncx>""")

        zf.writestr("OEBPS/nav.xhtml", f"""\
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" xml:lang="en" lang="en">
<head><meta charset="UTF-8"/><title>Table of Contents</title></head>
<body>
  <nav epub:type="toc" id="toc">
    <h1>Table of Contents</h1>
    <ol>
{nav_html}
    </ol>
  </nav>
</body>
</html>""")

    return output_path


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

    epub_result = pandoc_results.get("epub", {})
    if not epub_result.get("success"):
        epub_files = [ch["file"] for ch in chapters if os.path.exists(ch.get("file", ""))]
        epub_files.sort(key=lambda p: int(re.search(r'(\d+)', os.path.splitext(os.path.basename(p))[0]).group(1)) if re.search(r'(\d+)', os.path.splitext(os.path.basename(p))[0]) else 0)
        if epub_files:
            epub_path = os.path.join(project_dir, f"{spec.get('title', 'manuscript').lower().replace(' ', '-')}.epub")
            try:
                _build_epub_from_chapters(epub_files, epub_path, title=spec.get("title", "Untitled"))
                pandoc_results["epub"] = {"success": True, "path": epub_path, "error": None, "engine": "pure-python"}
            except Exception as e:
                pandoc_results["epub"] = {"success": False, "path": None, "error": str(e)}

    return {
        "manuscript_md": manuscript_path,
        "metadata": meta_path,
        "pandoc": pandoc_results,
        "chapters_count": len(chapters),
    }

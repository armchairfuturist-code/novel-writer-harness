#!/usr/bin/env python3
"""Seed-phrase smoke test for StoryForge.

    python3 scripts/smoke.py "a jazz musician heals wounds with her trumpet"

One sentence in, one PASS or FAIL out. The run goes through every phase -
seed, world, characters, outline, outline validation, drafts, gates, export -
against the deterministic stub in ``pipeline/stub_provider.py``. It needs no
API key and makes no network call: ``httpx.Client.post`` is replaced with a
tripwire that records and blocks any attempt, and a recorded attempt fails the
run. ``builtins.input`` is stubbed too, so a smoke test can never block on a
prompt.

Add ``--live`` to send the same path to a real provider. That needs
``LLM_API_KEY``, and it turns the tripwire off.

Exit status is 0 on PASS and 1 on FAIL, so this is usable as a CI gate.
"""

from __future__ import annotations

import argparse
import builtins
import contextlib
import io
import json
import os
import re
import shutil
import sys
import tempfile
import time
import traceback

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

DEFAULT_CONCEPT = ("A jazz musician in 1920s New Orleans discovers that the notes "
                   "she plays on her trumpet can heal wounds - but every healing "
                   "steals a memory from someone she loves.")

# Read before we set anything: --live has to know whether the operator supplied
# a real key, and our own placeholder must not count as one.
_HAD_KEY = bool(os.environ.get("LLM_API_KEY"))
OFFLINE_KEY = "smoke-test-no-network"
OFFLINE_URL = "http://mock.invalid/v1"

# Environment first, StoryForge imports second: Config reads env once.
os.environ.setdefault("LLM_API_KEY", OFFLINE_KEY)
os.environ.setdefault("LLM_BASE_URL", OFFLINE_URL)
os.environ.setdefault("LLM_ENABLE_EMBEDDINGS", "")
os.environ.setdefault("LLM_RETRY_FAST", "1")


class NetworkTripwire:
    """Records every httpx POST for the length of the block, and blocks it."""

    def __init__(self, block: bool = True):
        self.block = block
        self.attempts: list[str] = []
        self._orig = None

    def __enter__(self) -> "NetworkTripwire":
        import httpx

        self._orig = httpx.Client.post
        trip = self

        def _post(client_self, url, *args, **kwargs):
            trip.attempts.append(str(url))
            if trip.block:
                raise RuntimeError(f"smoke tripwire blocked a network call to {url}")
            return trip._orig(client_self, url, *args, **kwargs)

        httpx.Client.post = _post
        return self

    def __exit__(self, *exc_info) -> bool:
        import httpx

        httpx.Client.post = self._orig
        return False


def _read_json(path: str):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _words(text: str) -> int:
    return len((text or "").split())


def run_smoke(concept: str = DEFAULT_CONCEPT,
              chapters: int = 2,
              words: int = 1000,
              full: bool = False,
              live: bool = False,
              project_dir: str | None = None,
              keep: bool = False,
              short_first: int = 0,
              verbose: bool = False,
              stream=None) -> dict:
    """Run the pipeline once from a seed phrase and report what came out.

    Args:
        concept: The seed phrase.
        chapters: Chapters the stub outline offers, and the run must produce.
        words: Target words per chapter; also the stub's chapter length, so the
            length gate sees an in-range chapter unless short_first says otherwise.
        full: Run the expensive phases too (review, backprop, adversarial).
        live: Use the real provider instead of the stub.
        project_dir: Where to write. A temp directory when None.
        keep: Leave a temp directory in place for inspection.
        short_first: Make this many first drafts short, to force redraws.
        verbose: Echo the pipeline's own log as it runs.
        stream: Where the report goes (default sys.stdout).

    Returns:
        The report dict. ``passed`` is the verdict.
    """
    out = stream if stream is not None else sys.stdout
    report: dict = {
        "concept": concept,
        "mode": "live" if live else "offline",
        "chapters_requested": chapters,
        "target_words": words,
        "full": bool(full),
        "project_dir": None,
        "phases": [],
        "chapters": [],
        "manuscript": None,
        "api_calls_avoided": 0,
        "stub_phases": {},
        "network_attempts": [],
        "errors": [],
        "seconds": 0.0,
        "passed": False,
    }

    if live and not _HAD_KEY:
        report["errors"].append("--live needs a real LLM_API_KEY in the environment")
        _emit(report, out, verbose=verbose, log="")
        return report

    tmp = project_dir is None
    if tmp:
        project_dir = tempfile.mkdtemp(prefix="storyforge-smoke-")
    os.makedirs(project_dir, exist_ok=True)
    report["project_dir"] = project_dir

    from config import Config
    from pipeline.prose_lab import MIN_WORDS_FOR_SCORE, analyze
    from pipeline.stub_provider import stubbed_llm
    from storyforge import run_full_pipeline

    Config._instance = None                       # fresh singleton on our env
    cfg = Config()
    cfg.chapter.target_words_per_chapter = words

    log_buf = io.StringIO()
    trip = NetworkTripwire(block=not live)
    stub = None
    started = time.time()

    def _sink(*_args, **_kwargs):               # never block on a prompt
        return ""

    try:
        stub_ctx = (contextlib.nullcontext() if live
                    else stubbed_llm(concept=concept, short_first=short_first,
                                     chapter_words=words, chapters=chapters))
        with trip, stub_ctx as maybe_stub, \
                contextlib.redirect_stdout(log_buf if not verbose else sys.stdout):
            stub = maybe_stub
            saved_input = builtins.input
            builtins.input = _sink
            try:
                run_full_pipeline(
                    concept,
                    config=cfg,
                    resume_from=1,
                    quick=not full,
                    feedback_enabled=False,
                    project_dir_override=project_dir,
                )
            finally:
                builtins.input = saved_input
    except Exception as exc:                     # any crash is a FAIL, not a traceback
        report["errors"].append(f"pipeline raised {type(exc).__name__}: {exc}")
        report["traceback"] = traceback.format_exc()
    finally:
        report["seconds"] = round(time.time() - started, 1)

    log = log_buf.getvalue()
    if trip.attempts and not live:
        report["errors"].append(
            f"{len(trip.attempts)} network attempt(s) blocked: {trip.attempts[:3]}")
    report["network_attempts"] = trip.attempts
    if stub is not None:
        report["api_calls_avoided"] = len(stub.calls)
        report["stub_phases"] = stub.phases()

    # --- evidence, read back off disk rather than trusted from the run -------
    spec = _read_json(os.path.join(project_dir, "spec.json"))
    world = _read_json(os.path.join(project_dir, "world.json"))
    characters = _read_json(os.path.join(project_dir, "characters.json"))
    outline = _read_json(os.path.join(project_dir, "outline.json"))
    quality = _read_json(os.path.join(project_dir, "quality", "quality.json")) or {}

    def phase(name: str, ok: bool, detail: str) -> None:
        report["phases"].append(
            {"phase": name, "status": "ok" if ok else "FAIL", "detail": detail})
        if not ok:
            report["errors"].append(f"{name}: {detail}")

    phase("seed", bool(spec and spec.get("title")),
          f"{spec.get('title', '?')} / {spec.get('genre', '?')}" if spec else "no spec.json")
    phase("world", bool(world and world.get("world_name")),
          world.get("world_name", "?") if world else "no world.json")
    n_chars = len((characters or {}).get("characters", []))
    phase("characters", n_chars >= 1, f"{n_chars} profiles")
    outlined = sum(len(a.get("chapters", [])) for a in (outline or {}).get("acts", []))
    phase("outline", outlined >= chapters, f"{outlined} chapter briefs")

    qmap = {}
    for row in quality.get("chapters", []):
        num = row.get("chapter") or row.get("chapter_number") or row.get("number")
        if num is not None:
            qmap[int(num)] = row

    ch_dir = os.path.join(project_dir, "chapters")
    files = (sorted(f for f in os.listdir(ch_dir) if f.endswith(".md"))
             if os.path.isdir(ch_dir) else [])
    for fn in files:
        with open(os.path.join(ch_dir, fn), encoding="utf-8") as f:
            text = f.read()
        a = analyze(text)
        m = re.search(r"(\d+)", fn)
        num = int(m.group(1)) if m else 0
        q = qmap.get(num, {})
        report["chapters"].append({
            "file": fn,
            "chapter": num,
            "words": int(a["features"]["word_count"]),
            "prose_score": a["prose_score"],
            "prose_pass": bool(a["pass"]),
            "total_score": (q.get("score") or {}).get("total_score"),
            "length_verdict": q.get("length_verdict", ""),
            "length_redraws": int(q.get("length_redraws", 0) or 0),
            "length_attempts": int(q.get("length_attempts", 0) or 0),
            "length_warning": q.get("length_warning", ""),
        })
        if int(a["features"]["word_count"]) < MIN_WORDS_FOR_SCORE:
            report["errors"].append(
                f"{fn} is {int(a['features']['word_count'])} words, under the "
                f"{MIN_WORDS_FOR_SCORE} floor")

    redraws = sum(c["length_redraws"] for c in report["chapters"])
    attempts = sum(max(1, c["length_attempts"]) for c in report["chapters"])
    phase("draft", len(files) >= chapters,
          f"{len(files)} chapters, {sum(c['words'] for c in report['chapters'])} words, "
          f"{redraws} length redraws over {attempts} attempts")

    ms_path = os.path.join(project_dir, "manuscript.md")
    ms_words = _words(open(ms_path, encoding="utf-8").read()) if os.path.exists(ms_path) else 0
    report["manuscript"] = {"path": ms_path, "words": ms_words,
                            "exists": os.path.exists(ms_path)}
    phase("export", ms_words >= MIN_WORDS_FOR_SCORE,
          f"manuscript.md {ms_words} words" if ms_words else "no manuscript.md")

    report["passed"] = not report["errors"]
    if tmp and not keep:
        shutil.rmtree(project_dir, ignore_errors=True)
        report["project_dir"] = f"{project_dir} (removed)"
    elif tmp:
        report["kept"] = project_dir

    _emit(report, out, verbose=verbose, log=log)
    return report


def _emit(report: dict, out, verbose: bool = False, log: str = "", as_json: bool = False) -> None:
    if as_json:
        out.write(json.dumps(report, indent=2, default=str) + "\n")
        return

    out.write(f"StoryForge smoke | {report['mode']} | {report['seconds']}s\n")
    out.write(f"  seed phrase : {report['concept'][:72]}\n")
    out.write(f"  project dir : {report['project_dir']}\n")
    out.write(f"  target      : {report['chapters_requested']} chapters x "
              f"{report['target_words']} words\n")
    for row in report["phases"]:
        out.write(f"  {row['phase']:<11} {row['status']:<5} {row['detail']}\n")
    for c in report["chapters"]:
        out.write(f"    ch{c['chapter']:03d} {c['words']:>5} words  "
                  f"prose {c['prose_score']:<4} score {str(c['total_score']):<4} "
                  f"length {c['length_verdict'] or '-':<9} "
                  f"redraws {c['length_redraws']}/{max(1, c['length_attempts'])}\n")
        if c["length_warning"]:
            out.write(f"      WARN ch{c['chapter']:03d} {c['length_warning']}\n")
    if report["api_calls_avoided"]:
        phases = ", ".join(f"{k}x{v}" for k, v in sorted(report["stub_phases"].items()))
        out.write(f"  api calls avoided: {report['api_calls_avoided']} ({phases})\n")
    if report["network_attempts"]:
        out.write(f"  network attempts: {len(report['network_attempts'])}\n")
    for err in report["errors"]:
        out.write(f"  ERROR {err}\n")
    if verbose and log:
        out.write("--- pipeline log ---\n" + log)
    elif report["errors"] and log:
        tail = "\n".join(log.strip().splitlines()[-15:])
        out.write("--- last pipeline output ---\n" + tail + "\n")
    if report.get("traceback"):
        out.write(report["traceback"])
    verdict = "PASS" if report["passed"] else "FAIL"
    ms = report.get("manuscript") or {}
    out.write(f"{verdict} | {len(report['chapters'])} chapters, "
              f"{ms.get('words', 0)} manuscript words, "
              f"{report['api_calls_avoided']} API calls avoided\n")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="smoke.py",
        description="Run the whole StoryForge pipeline from one seed phrase, offline.")
    parser.add_argument("concept", nargs="?", default=DEFAULT_CONCEPT,
                        help="seed phrase (default: a built-in demo phrase)")
    parser.add_argument("--chapters", type=int, default=2,
                        help="chapters to draft (default 2)")
    parser.add_argument("--words", type=int, default=1000,
                        help="target words per chapter (default 1000)")
    parser.add_argument("--full", action="store_true",
                        help="run review, backprop and adversarial phases too")
    parser.add_argument("--live", action="store_true",
                        help="use a real provider instead of the offline stub")
    parser.add_argument("--dir", dest="project_dir", default=None,
                        help="write here instead of a temp directory")
    parser.add_argument("--keep", action="store_true",
                        help="keep a temp directory for inspection")
    parser.add_argument("--short-first", type=int, default=0,
                        help="make this many first drafts short, to force redraws")
    parser.add_argument("--json", action="store_true", dest="as_json",
                        help="print the report as JSON")
    parser.add_argument("--verbose", action="store_true",
                        help="echo the pipeline log as it runs")
    args = parser.parse_args(argv)

    buf = io.StringIO()
    report = run_smoke(concept=args.concept, chapters=args.chapters, words=args.words,
                       full=args.full, live=args.live, project_dir=args.project_dir,
                       keep=args.keep, short_first=args.short_first,
                       verbose=args.verbose, stream=buf)
    text = buf.getvalue()
    if args.as_json:
        sys.stdout.write(text)
    else:
        sys.stdout.write(text)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

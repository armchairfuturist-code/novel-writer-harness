"""One call that orients whoever is driving StoryForge, agent or human.

`python3 storyforge.py --doctor` answers, in order: which version this is, what
it will talk to, what every role resolves to, where the state of a run lives,
what proves the install works, and what to type next. `--json` prints the same
report as data. Nothing here needs an API key, and nothing touches the network
unless --live is passed.

This module is the system's front door for an agent: read it once and the rest
of the repo is reachable by name from here.
"""

import glob
import json
import os
import subprocess
import sys

REPO = os.path.dirname(os.path.abspath(__file__))

# The invariants a test defends. A guard listed here that stops existing is a
# broken promise, so tests/test_doctor.py checks each path is real.
GUARDS = [
    ("tests/test_atomic_write_coverage.py", "every writer replaces its file atomically"),
    ("tests/test_model_literal_guard.py", "no vendor model id outside the config.py alias table"),
    ("tests/test_model_routing_agnostic.py", "any model id can hold any role, by env var alone"),
    ("tests/test_doctor.py", "this report needs no key and never names a guard that is missing"),
    ("tests/test_agents_doc_drift.py", "the docs name only flags, env vars and files that exist"),
]

VERIFY = [
    'python3 scripts/smoke.py "a lighthouse keeper adopts a shipwrecked child" --chapters 2',
    "python3 -m pytest -q",
]

# What a fresh clone needs before it can run. Doctor reports a missing one by
# name instead of letting the pipeline fail deep inside an import.
REQUIRED_IMPORTS = ["httpx"]
OPTIONAL_IMPORTS = ["sentence_transformers", "pytest", "pandoc"]


def deps_state():
    """Which third-party pieces this checkout can actually import."""
    import importlib.util
    import shutil

    missing = []
    for name in REQUIRED_IMPORTS:
        if importlib.util.find_spec(name) is None:
            missing.append(name)
    optional = {}
    for name in OPTIONAL_IMPORTS:
        if name == "pandoc":
            optional[name] = shutil.which("pandoc") is not None
        else:
            optional[name] = importlib.util.find_spec(name) is not None
    return {"missing": missing, "optional": optional}


def _run(args, timeout=8):
    """Run a command in the repo and return its stdout, or '' if it fails."""
    try:
        out = subprocess.run(
            args, cwd=REPO, capture_output=True, text=True, timeout=timeout
        )
        return out.stdout.strip() if out.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def repo_state():
    """Branch, commit and cleanliness, or an empty dict outside a git checkout."""
    commit = _run(["git", "rev-parse", "--short", "HEAD"])
    if not commit:
        return {}
    dirty = bool(_run(["git", "status", "--porcelain"]))
    return {
        "path": REPO,
        "branch": _run(["git", "rev-parse", "--abbrev-ref", "HEAD"]),
        "commit": commit,
        "dirty": dirty,
    }


def project_state(project_dir):
    """What a run has produced so far, read from its own artifacts."""
    if not project_dir or not os.path.isdir(project_dir):
        return {"dir": project_dir or None, "exists": False}
    completed = []
    checkpoint = os.path.join(project_dir, "checkpoint.json")
    if os.path.isfile(checkpoint):
        try:
            with open(checkpoint, "r", encoding="utf-8") as handle:
                completed = sorted(json.load(handle).get("completed_phases", []))
        except (OSError, ValueError):
            completed = ["<checkpoint.json unreadable>"]
    chapters = sorted(glob.glob(os.path.join(project_dir, "chapters", "*.md")))
    words = 0
    for path in chapters:
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as handle:
                words += len(handle.read().split())
        except OSError:
            pass
    artifacts = sorted(
        os.path.basename(p)
        for p in glob.glob(os.path.join(project_dir, "*.json"))
    )
    return {
        "dir": project_dir,
        "exists": True,
        "phases_done": completed,
        "chapters": len(chapters),
        "chapter_words": words,
        "artifacts": artifacts,
        "canonical_state": os.path.isfile(os.path.join(project_dir, "canonical_state.json")),
    }


def newest_project(root):
    """The most recently written project dir under a landing root, or None."""
    if not root or not os.path.isdir(root):
        return None
    candidates = [d for d in glob.glob(os.path.join(root, "*")) if os.path.isdir(d)]
    if not candidates:
        return None
    return max(candidates, key=os.path.getmtime)


def collect(config=None, project_dir=None, live=False):
    """Build the whole orientation report as data."""
    from config import VERSION, Config

    cfg = config or Config()
    plan = cfg.resolve_routing(live=live)
    roles = plan["roles"]
    by_source = {}
    for row in roles.values():
        by_source[row["source"]] = by_source.get(row["source"], 0) + 1
    overridden = [
        {"role": role, "model": row["model"], "source": row["source"], "env_var": row["env_var"]}
        for role, row in roles.items()
        if row["source"] != "routing"
    ]
    key_env = "LLM_API_KEY" if os.environ.get("LLM_API_KEY") else (
        "CROFAI_API_KEY" if os.environ.get("CROFAI_API_KEY") else None
    )
    landing = getattr(cfg, "project_dir", None) or os.path.join(
        os.path.expanduser("~"), "storyforge-projects"
    )
    target = project_dir or newest_project(landing)
    return {
        "version": VERSION,
        "python": sys.version.split()[0],
        "repo": repo_state(),
        "provider": {
            "base_url": plan["provider"],
            "api_key_set": plan["api_key_set"],
            "api_key_env": key_env,
        },
        "roles": {
            "total": len(roles),
            "by_source": by_source,
            "overridden": overridden,
        },
        "landing_root": landing,
        "deps": deps_state(),
        "project": project_state(target),
        "guards": [
            {"path": path, "holds": holds, "present": os.path.isfile(os.path.join(REPO, path))}
            for path, holds in GUARDS
        ],
        "verify": VERIFY,
        "next": 'python3 storyforge.py "your concept here"',
        "availability": plan.get("availability"),
    }


def render(report):
    """Render the report as the one screenful an agent reads first."""
    lines = []
    repo = report["repo"]
    where = repo.get("path", "(not a git checkout)")
    if repo:
        where = "%s @ %s (%s%s)" % (
            repo["path"], repo["commit"], repo["branch"], ", dirty" if repo["dirty"] else ""
        )
    provider = report["provider"]
    key = provider["api_key_env"] or "none set"
    lines.append("StoryForge %s on python %s" % (report["version"], report["python"]))
    lines.append("repo      %s" % where)
    lines.append(
        "provider  %s   api key: %s" % (provider["base_url"], key)
    )
    roles = report["roles"]
    sources = ", ".join("%d %s" % (n, s) for s, n in sorted(roles["by_source"].items()))
    lines.append("roles     %d resolved (%s)" % (roles["total"], sources or "none"))
    for row in roles["overridden"][:8]:
        lines.append("            %s -> %s [%s via %s]" % (row["role"], row["model"], row["source"], row["env_var"]))
    project = report["project"]
    if project["exists"]:
        lines.append(
            "project   %s" % project["dir"]
        )
        lines.append(
            "            phases done: %s" % (", ".join(project["phases_done"]) or "none")
        )
        lines.append(
            "            chapters: %d (%d words)   canonical state: %s"
            % (project["chapters"], project["chapter_words"], project["canonical_state"])
        )
    else:
        lines.append("project   none yet (runs land in %s)" % report["landing_root"])
    deps = report["deps"]
    if deps["missing"]:
        lines.append(
            "deps      MISSING %s (python3 -m pip install -r requirements.txt)"
            % ", ".join(deps["missing"])
        )
    else:
        optional = ", ".join(k for k, v in sorted(deps["optional"].items()) if v)
        lines.append("deps      required ok%s" % ("; optional: " + optional if optional else ""))
    lines.append("guards    %s" % "; ".join(g["holds"] for g in report["guards"] if g["present"]))
    missing = [g["path"] for g in report["guards"] if not g["present"]]
    if missing:
        lines.append("          MISSING guard tests: %s" % ", ".join(missing))
    lines.append("verify    %s" % report["verify"][0])
    lines.append("          %s" % report["verify"][1])
    availability = report.get("availability")
    if availability and availability.get("checked"):
        lines.append(
            "catalog   %d ids served, missing: %s"
            % (len(availability.get("available", [])), ", ".join(availability.get("missing", [])) or "none")
        )
    lines.append("next      %s" % report["next"])
    return "\n".join(lines)


def main(argv=None):
    """Entry point for `storyforge.py --doctor`; also runnable directly."""
    argv = list(sys.argv[1:] if argv is None else argv)
    live = "--live" in argv
    as_json = "--json" in argv
    project_dir = None
    for flag in ("--project-dir", "--resume"):
        if flag in argv:
            index = argv.index(flag)
            if index + 1 < len(argv):
                project_dir = os.path.abspath(argv[index + 1])
    report = collect(project_dir=project_dir, live=live)
    if as_json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(render(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

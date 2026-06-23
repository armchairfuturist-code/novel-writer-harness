"""Bug log — every bug found during inventory testing.

Each entry includes:
- ID: stable, auto-incremented
- Title: one-line description
- Severity: BLOCKER (cannot proceed), MAJOR (feature broken), MINOR (cosmetic/edge), INFO (noted but not fixed)
- Module: file path
- Repro: minimal reproduction
- Evidence: actual output observed
- Root cause: (filled at fix time)
- Fix: (filled at fix time)
- Verification: (filled at fix time)
"""

import json
import os
from datetime import datetime
from pathlib import Path

LOG_PATH = Path(__file__).parent.parent / "bug_log.json"


def _load():
    if LOG_PATH.exists():
        try:
            with open(LOG_PATH) as f:
                return json.load(f)
        except Exception:
            pass
    return {"bugs": [], "next_id": 1}


def _save(data):
    with open(LOG_PATH, "w") as f:
        json.dump(data, f, indent=2)


def log_bug(title, severity, module, repro, evidence, expected="", **extra):
    """Record a bug. Returns the bug ID."""
    data = _load()
    bug = {
        "id": f"BUG-{data['next_id']:03d}",
        "title": title,
        "severity": severity,
        "module": module,
        "repro": repro,
        "evidence": evidence,
        "expected": expected,
        "timestamp": datetime.utcnow().isoformat() + "Z",
    }
    bug.update(extra)
    data["bugs"].append(bug)
    data["next_id"] += 1
    _save(data)
    return bug["id"]


def attach_fix(bug_id, root_cause, fix_summary, verification=""):
    """Attach a fix description to a logged bug."""
    data = _load()
    for b in data["bugs"]:
        if b["id"] == bug_id:
            b["root_cause"] = root_cause
            b["fix"] = fix_summary
            b["verification"] = verification
            b["status"] = "fixed"
            break
    _save(data)


def list_bugs(severity=None):
    data = _load()
    if severity:
        return [b for b in data["bugs"] if b["severity"] == severity]
    return data["bugs"]


def get_bug(bug_id):
    data = _load()
    for b in data["bugs"]:
        if b["id"] == bug_id:
            return b
    return None


def summary():
    data = _load()
    by_sev = {}
    for b in data["bugs"]:
        by_sev[b["severity"]] = by_sev.get(b["severity"], 0) + 1
    return {
        "total": len(data["bugs"]),
        "by_severity": by_sev,
        "fixed": len([b for b in data["bugs"] if b.get("status") == "fixed"]),
    }

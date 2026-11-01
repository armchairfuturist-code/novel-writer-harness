"""Atomic state writes — crash-safe persistence for every JSON state file.

A state file written in place can be torn: the process dies, the disk fills,
or the machine loses power mid-write, and the reader then finds a truncated
JSON blob. For a novel project that means a lost canonical store, a lost
foreshadowing ledger, or a lost outline — the exact artifacts a long run
cannot be re-derived from.

The pattern here is the standard one (dramatica-flow's core/state does the
same): write to a temp file *in the target directory* so the rename never
crosses a filesystem, fsync the file, os.replace over the target (atomic on
POSIX), then fsync the directory so the rename itself survives power loss.
Any failure unlinks the temp file and re-raises, leaving the previous
version of the target completely intact.

Usage:
    from pipeline.state_io import atomic_write_json, atomic_write_text

    atomic_write_json(path, {"chapter": 12})
    atomic_write_text(path, manuscript)
"""

import json
import os
import tempfile
from typing import Any

__all__ = ["atomic_write_text", "atomic_write_json", "fsync_dir"]


def fsync_dir(directory: str) -> None:
    """fsync a directory so a completed rename survives power loss.

    Best-effort: some platforms (and some network mounts) reject fsync on a
    directory handle. The rename is already durable in the common case, so a
    refusal here must not turn a successful write into a failure.
    """
    try:
        fd = os.open(directory, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def atomic_write_text(path: str, text: str, encoding: str = "utf-8") -> None:
    """Write `text` to `path` atomically.

    The reader either sees the complete previous content or the complete new
    content — never a partial file, and never a missing file. Parent
    directories are created. On any error the temp file is removed and the
    original target is left untouched.
    """
    path = os.fspath(path)
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)

    fd, tmp_path = tempfile.mkstemp(
        dir=directory,
        prefix=os.path.basename(path) + ".",
        suffix=".tmp",
    )
    try:
        with os.fdopen(fd, "w", encoding=encoding) as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        # Preserve the target's mode when it already exists, else 0644.
        try:
            mode = os.stat(path).st_mode & 0o777
        except FileNotFoundError:
            mode = 0o644
        os.chmod(tmp_path, mode)
        os.replace(tmp_path, path)
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise
    tmp_path = None  # replaced; nothing to clean up

    fsync_dir(directory)


def atomic_write_json(path: str, obj: Any, indent: int = 2,
                      encoding: str = "utf-8") -> None:
    """Serialise `obj` as JSON and write it to `path` atomically.

    Serialisation happens *before* the temp file is opened, so a
    non-JSON-serialisable object raises without touching the filesystem.
    """
    text = json.dumps(obj, indent=indent, ensure_ascii=False)
    atomic_write_text(path, text, encoding=encoding)

# Licensed under the Apache License, Version 2.0.
"""Bounded, read-only Git index checks for XRT source provenance."""

import hashlib
import os
from pathlib import Path
import re
import selectors
import signal
import subprocess
import time

from baseline_inventory import _probe, collect_source as _collect_source


MAX_INDEX_BYTES = 32 * 1024 * 1024
MAX_RECORD_BYTES = 65536
MAX_REPOSITORIES = 128
MAX_SUBMODULE_DEPTH = 32
INDEX_TIMEOUT_SECONDS = 10


def _environment():
    environment = {key: value for key, value in os.environ.items()
                   if not key.startswith("GIT_")}
    environment["GIT_OPTIONAL_LOCKS"] = "0"
    return environment


def _command(root, *arguments):
    return ["git", "--no-optional-locks", "-c", "core.fsmonitor=false", "-c",
            "core.untrackedCache=false", "-C", str(root), *arguments]


def _remaining(deadline):
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise ValueError("source index probe timed out")
    return remaining


def _record(record, prefix):
    header, separator, path = record.partition(b"\t")
    match = re.fullmatch(rb"([HSMhsm]) ([0-7]{6}) [0-9a-f]{40} ([0-3])", header)
    if not match or not separator or not path:
        raise ValueError("unrecognized source index record")
    tag, mode, stage = match.groups()
    name = os.fsdecode(path)
    full_name = name if prefix == "." else prefix + "/" + name
    flags = []
    if tag.upper() == b"S":
        flags.append("skip-worktree")
    if tag.islower():
        flags.append("assume-unchanged")
    if flags:
        raise ValueError("source index uses " + " and ".join(flags) + ": " + repr(full_name))
    if stage != b"0":
        raise ValueError("source index contains an unmerged entry: " + repr(full_name))
    if mode == b"160000":
        relative = Path(name)
        if relative.is_absolute() or ".." in relative.parts or relative == Path("."):
            raise ValueError("unsafe submodule path in source index")
        return relative
    return None


def _read_index(root, prefix, deadline, budget):
    """Stream records so a normal large checkout need not fit a 64 KiB probe."""
    process = None
    pending = bytearray()
    digest = hashlib.sha256()
    submodules = []
    count = 0
    size = 0
    try:
        _remaining(deadline)
        process = subprocess.Popen(
            _command(root, "ls-files", "--cached", "--stage", "-v", "-z", "--full-name"),
            env=_environment(), stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ)
            while selector.get_map():
                for key, _ in selector.select(min(0.1, _remaining(deadline))):
                    chunk = os.read(key.fileobj.fileno(), 8192)
                    if not chunk:
                        selector.unregister(key.fileobj)
                        continue
                    budget["bytes"] += len(chunk)
                    if budget["bytes"] > MAX_INDEX_BYTES:
                        raise ValueError("source index output exceeded its byte limit")
                    size += len(chunk)
                    digest.update(chunk)
                    pending.extend(chunk)
                    while (end := pending.find(b"\0")) >= 0:
                        if end > MAX_RECORD_BYTES:
                            raise ValueError("source index record exceeded its byte limit")
                        relative = _record(bytes(pending[:end]), prefix)
                        del pending[:end + 1]
                        count += 1
                        if relative is not None:
                            submodules.append(relative)
                            if len(submodules) >= MAX_REPOSITORIES:
                                raise ValueError("source index exceeded its repository limit")
                    if len(pending) > MAX_RECORD_BYTES:
                        raise ValueError("source index record exceeded its byte limit")
            process.wait(timeout=_remaining(deadline))
        if process.returncode != 0 or pending:
            raise ValueError("source index probe failed or returned incomplete records")
        return {"path": prefix, "tracked_entries": count, "size_bytes": size,
                "sha256": digest.hexdigest()}, submodules
    except (OSError, subprocess.TimeoutExpired) as error:
        raise ValueError("source index probe unavailable or timed out") from error
    finally:
        if process is not None:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait()
            if process.stdout is not None:
                process.stdout.close()


def inspect_index_flags(root):
    """Reject hidden tracked changes in the checkout and every indexed submodule."""
    report = {"verified": False, "repositories": [], "blockers": [],
              "limits": {"bytes": MAX_INDEX_BYTES, "record_bytes": MAX_RECORD_BYTES,
                         "repositories": MAX_REPOSITORIES, "submodule_depth": MAX_SUBMODULE_DEPTH,
                         "seconds": INDEX_TIMEOUT_SECONDS},
              "limitations": [
                  "Git index flag checks supplement source status; they do not lock the checkout or independently compare every working file with its committed blob."]}
    deadline = time.monotonic() + INDEX_TIMEOUT_SECONDS
    budget = {"bytes": 0}
    try:
        root = Path(root).resolve(strict=True)
        pending = [(root, ".", 0)]
        visited = set()
        while pending:
            checkout, prefix, depth = pending.pop()
            if depth > MAX_SUBMODULE_DEPTH:
                raise ValueError("source index exceeded its submodule depth limit")
            if len(visited) >= MAX_REPOSITORIES:
                raise ValueError("source index exceeded its repository limit")
            resolved = checkout.resolve(strict=True)
            if resolved != checkout or not resolved.is_relative_to(root) or resolved in visited:
                raise ValueError("submodule checkout is outside the source or repeats a checkout")
            visited.add(resolved)
            code, output = _probe(
                _command(checkout, "rev-parse", "--show-toplevel"),
                environment=_environment(), timeout=_remaining(deadline),
            )
            if code != 0 or Path(os.fsdecode(output).rstrip("\n")).resolve() != checkout:
                raise ValueError("source or submodule is not an initialized checkout root: " + repr(prefix))
            identity, submodules = _read_index(checkout, prefix, deadline, budget)
            report["repositories"].append(identity)
            for relative in reversed(submodules):
                child = checkout / relative
                pending.append((child, child.relative_to(root).as_posix(), depth + 1))
            if len(visited) + len(pending) > MAX_REPOSITORIES:
                raise ValueError("source index exceeded its repository limit")
        report["verified"] = True
    except (ValueError, OSError, RuntimeError, UnicodeError) as error:
        report["blockers"].append("source index flags could not be completely verified: " + str(error))
    return report


def collect_source(root):
    """Preserve native source inventory and add the XRT index-flag prerequisite."""
    report = _collect_source(root)
    report["index_flags"] = inspect_index_flags(root)
    report["blockers"].extend(report["index_flags"]["blockers"])
    report["outcome"] = "blocked" if report["blockers"] else "pass"
    return report

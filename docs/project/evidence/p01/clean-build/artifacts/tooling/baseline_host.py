# Licensed under the Apache License, Version 2.0.
"""Read-only host identities for the exact environment used by baseline commands."""

import os
from pathlib import Path
import platform
import re
import shutil
import stat

from baseline_inventory import _digest, _probe


REQUIRED_TOOLS = ("gcc", "g++", "make", "ld", "as", "python3")
OPTIONAL_TOOLS = ("cmake",)
VERSION_PATTERNS = {
    "gcc": r"(?:gcc|clang)",
    "g++": r"(?:g\+\+|clang)",
    "make": r"(?:GNU Make|BSD Make|bmake)",
    "ld": r"(?:GNU ld|GNU gold|LLD|lld)",
    "as": r"(?:GNU assembler|LLVM)",
    "python3": r"Python",
    "cmake": r"cmake version",
}
LIMITATIONS = (
    "Host identities are observations, not a compiler compatibility or workload pass.",
    "Executable hashes do not inventory every host header, shared library or compiler support file.",
    "Compiler selection comes from the supplied PATH; no tool is installed or replaced.",
    "The C++ frontend is identified by the driver's cc1plus path and file hash; its version is not probed separately.",
    "The pinned dependency stack requires actual compilation checks; a version number alone cannot qualify it.",
)


def _environment(environment):
    current = dict(os.environ) if environment is None else environment
    if (type(current) is not dict or any(
            type(key) is not str or not key or "=" in key or "\0" in key
            or type(value) is not str or "\0" in value
            for key, value in current.items())):
        raise ValueError("host environment must contain valid string names and values")
    return dict(current)


def _located(name, environment):
    selected = shutil.which(name, path=environment.get("PATH", os.defpath))
    if selected is None:
        raise ValueError("host tool is unavailable")
    return Path(os.path.abspath(selected))


def _identity(path):
    resolved = Path(path).resolve(strict=True)
    if not stat.S_ISREG(resolved.stat().st_mode) or not os.access(resolved, os.X_OK):
        raise ValueError("host tool is not an executable regular file")
    digest, size = _digest(resolved)
    return {"resolved_name": resolved.name, "sha256": digest, "size_bytes": size}


def _version(name, output):
    lines = output.decode("utf-8").splitlines()
    if not lines or not lines[0].strip():
        raise ValueError("host tool did not return a version")
    value = lines[0].strip()
    if (len(value) > 4096 or any(ord(character) < 32 for character in value)
            or not re.search(VERSION_PATTERNS[name], value)
            or not re.search(r"\d+\.\d+", value)):
        raise ValueError("host tool returned a malformed version")
    return re.sub(r"(?:[A-Za-z]:)?/[^\s]+", "<path>", value)[:512]


def _tool(name, path, environment):
    identity = _identity(path)
    code, output = _probe([str(path), "--version"], environment=environment, timeout=5)
    if code != 0:
        raise ValueError("host tool version probe failed")
    version = _version(name, output)
    if identity != _identity(path):
        raise ValueError("host tool changed during its version probe")
    return {"command": name, **identity, "version": version}


def _frontend(compiler, environment):
    code, output = _probe([str(compiler), "-print-prog-name=cc1plus"],
                          environment=environment, timeout=5)
    value = output.decode("utf-8").strip()
    if (code != 0 or not value or len(value) > 4096
            or any(ord(character) < 32 for character in value)):
        raise ValueError("C++ frontend identity was not resolved")
    path = Path(value) if "/" in value else _located(value, environment)
    return {"command": "cc1plus", **_identity(Path(os.path.abspath(path))),
            "reported_by": "g++ -print-prog-name=cc1plus"}


def _platform():
    result = {"system": platform.system(), "machine": platform.machine(), "libc": None}
    if not result["system"] or not result["machine"]:
        raise ValueError("host system identity is unavailable")
    try:
        value = os.confstr("CS_GNU_LIBC_VERSION")
    except (AttributeError, OSError, ValueError):
        value = None
    if value:
        name, _, version = value.partition(" ")
    else:
        name, version = platform.libc_ver()
    if not name or not version:
        raise ValueError("host C library identity is unavailable")
    if any(not re.fullmatch(r"[A-Za-z0-9_.+-]+", item)
           for item in (result["system"], result["machine"], name, version)):
        raise ValueError("host platform identity is malformed")
    result["libc"] = {"name": name, "version": version}
    return result


def collect_host(environment=None):
    report = {"host": None, "tools": {}, "blockers": [],
              "limitations": list(LIMITATIONS)}
    try:
        current = _environment(environment)
    except (TypeError, ValueError):
        report["blockers"].append("host environment is malformed")
        report["outcome"] = "blocked"
        return report
    try:
        report["host"] = _platform()
    except (OSError, ValueError):
        report["blockers"].append("host system, machine or C library identity is unavailable")
    for name in REQUIRED_TOOLS + OPTIONAL_TOOLS:
        try:
            path = _located(name, current)
        except (OSError, ValueError):
            if name in OPTIONAL_TOOLS:
                report["limitations"].append("Optional host tool is absent: " + name)
            else:
                report["blockers"].append("required host tool is absent: " + name)
            continue
        try:
            report["tools"][name] = _tool(name, path, current)
            if name == "g++":
                report["tools"]["cc1plus"] = _frontend(path, current)
                if report["tools"][name]["sha256"] != _identity(path)["sha256"]:
                    raise ValueError("C++ driver changed while resolving its frontend")
        except (OSError, RuntimeError, ValueError, UnicodeError):
            report["blockers"].append("host tool identity could not be verified: " + name)
    report["outcome"] = "blocked" if report["blockers"] else "pass"
    return report

#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Invoke the source-bound model runner from a generated regression tree."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile


SAFE_PATH = re.compile(r"/[A-Za-z0-9_./+-]+\Z")
MAX_CONFIG_BYTES = 1024 * 1024


def literal_path(value, *, directory=False):
    path = Path(os.path.abspath(value))
    if not SAFE_PATH.fullmatch(str(path)) or path.resolve() != path:
        raise ValueError("paths must be absolute safe literals without symlink traversal")
    if directory and not path.is_dir():
        raise ValueError("required directory is missing: " + str(path))
    return path


def overlaps(left, right):
    return left == right or left.is_relative_to(right) or right.is_relative_to(left)


def generated_configuration(build):
    config = literal_path(build / "config.mk")
    if not config.is_file() or config.stat().st_size > MAX_CONFIG_BYTES:
        raise ValueError("missing or oversized generated config.mk")
    with config.open("rb") as stream:
        encoded = stream.read(MAX_CONFIG_BYTES + 1)
    if len(encoded) > MAX_CONFIG_BYTES:
        raise ValueError("generated config.mk exceeds its byte bound")
    text = encoded.decode("utf-8")
    values = {}
    for name in ("VORTEX_HOME", "TOOLDIR", "XLEN"):
        assignments = re.findall(r"^" + name + r"[ \t]*(\?=|:=|=)[ \t]*(.*?)[ \t]*$",
                                 text, re.MULTILINE)
        if len(assignments) != 1 or assignments[0][0] != "?=":
            raise ValueError("ambiguous generated setting: " + name)
        values[name] = assignments[0][1]
    if values["XLEN"] != "64":
        raise ValueError("the fixed native model catalog requires an RV64 generated tree")
    return values


def command(args):
    build = literal_path(args.build_dir, directory=True)
    config = generated_configuration(build)
    source = literal_path(config["VORTEX_HOME"], directory=True)
    source_wrapper = literal_path(source / "ci/project/p04_catalog.py")
    if source_wrapper.read_bytes() != Path(__file__).read_bytes():
        raise ValueError("generated catalog wrapper differs from the selected source")
    runner = literal_path(source / "ci/project/p04_execute.py")
    if not runner.is_file():
        raise ValueError("source-bound model runner is missing")
    tools_value = args.tools_dir or os.environ.get("P04_CATALOG_TOOLS") or config["TOOLDIR"]
    tools = literal_path(tools_value, directory=True)
    if overlaps(source, tools):
        raise ValueError("model catalog tools must reside outside the source checkout")
    workspace_value = args.workspace_dir or os.environ.get("P04_CATALOG_ROOT")
    if workspace_value is None:
        workspace_value = tempfile.mkdtemp(prefix="p04-catalog-", dir=source.parent)
    workspace = literal_path(workspace_value, directory=True)
    if overlaps(source, workspace) or workspace == tools or workspace.is_relative_to(tools):
        raise ValueError("model catalog workspace must be outside source and tools")
    evidence = literal_path(workspace / "evidence")
    evidence.mkdir(mode=0o700, exist_ok=True)
    work = literal_path(workspace / ("work-" + args.backend))
    output = literal_path(evidence / ("model-" + args.backend))
    if overlaps(work, tools) or overlaps(output, tools):
        raise ValueError("model catalog work and packet directories must be outside tools")
    if os.path.lexists(work) or os.path.lexists(output):
        raise ValueError("model catalog work and packet directories must be fresh")
    argv = [sys.executable, str(runner), "run", "--source-dir", str(source),
            "--tools-dir", str(tools), "--work-dir", str(work), "--output", str(output),
            "--backend", args.backend, "--format", "fp16", "--format", "bf16",
            "--iterations", "2", "--jobs", "2",
            "--timeout-seconds", "1800", "--run-timeout-seconds", "180"]
    return source, output, argv


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend", choices=("simx", "rtlsim"), required=True)
    parser.add_argument("--build-dir", type=Path, default=Path.cwd())
    parser.add_argument("--tools-dir", type=Path)
    parser.add_argument("--workspace-dir", type=Path)
    args = parser.parse_args(argv)
    try:
        source, output, invocation = command(args)
        print(json.dumps({"scope": "both frozen formats, all ten cases, two repetitions",
                          "backend": args.backend, "packet": str(output)}), flush=True)
        environment = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
        return subprocess.run(invocation, cwd=source, env=environment).returncode
    except (OSError, ValueError, RuntimeError, UnicodeError) as error:
        print(json.dumps({"outcome": "blocked", "reason": str(error),
                          "native_execution": "not_run"}))
        return 1


if __name__ == "__main__":
    sys.exit(main())

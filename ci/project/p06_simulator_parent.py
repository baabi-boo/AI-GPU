#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Replay the pinned simulator backends against the current HOST fault fixture.

This compiles the actual old transport backends and unchanged CommandProcessor,
with controlled Processor/RAM replacements. It is not a native GPU/RTL run.
Both --work-dir and --output must be fresh directories outside the source tree.
Failed attempts, source snapshots, compiler commands and raw logs are retained.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys
from datetime import datetime, timezone
from unittest import mock

sys.dont_write_bytecode = True

from baseline_process import GIB, MIB, LIMITATIONS, run_bounded
import test_p06_simulator_completion as fixture


ROOT = Path(__file__).resolve().parents[2]
PARENT = "42809ff0c1b81384d7c9b079e4ef786be8407600"
SELF = "ci/project/p06_simulator_parent.py"
BACKENDS = ("simx", "rtlsim")
GROUPS = ("standard_exception", "unknown_exception")
MEMORIES = ("ram", "llc")
MARKER = "failed launch was accepted as successful"
BUDGET = {"min_free_bytes": GIB, "max_rss_bytes": GIB, "max_log_bytes": MIB}
TIMEOUTS = {"probe": 10, "configure": 60, "build": 60, "run": 10}
HELPERS = (SELF, "ci/project/test_p06_simulator_completion.py",
           "ci/project/tensor_host_tools.py", "ci/project/baseline_process.py")
FIXTURES = tuple("ci/project/fixtures/simulator_completion/" + name
                 for name in ("control.h", "main.cpp", "mem.h", "processor.h"))
PRODUCTION = tuple("sw/runtime/" + backend + "/vortex.cpp" for backend in BACKENDS)
# These are the actual shared production inputs to compile_backend, including
# the CP and callback bodies. Reusing them requires byte equality to the parent.
SHARED = ("sim/common/cmd_processor.cpp", "sim/common/cmd_processor.h",
          "sw/runtime/common/callbacks.h", "sw/runtime/common/callbacks.inc",
          "sw/runtime/common/common.h", "sw/runtime/include/vortex.h",
          "sw/runtime/include/vortex2.h", "sim/simx/constants.h",
          "sw/common/mem_alloc.h", "sw/common/util.h", "sw/common/bitmanip.h",
          "sw/common/vm_types.h")
CONFIG_INPUTS = ("configure", "config.mk.in", "VERSION", "VX_config.toml",
                 "VX_types.toml", "vortex_opae.toml", "profiles/p02-tfr.json",
                 "ci/gen_config.py")
CONTEXT = ("sim/simx/processor.cpp", "sim/simx/processor.h",
           "sw/runtime/common/async_run.h")
INPUTS = HELPERS + FIXTURES + PRODUCTION + SHARED + CONFIG_INPUTS + CONTEXT
PARENT_INPUTS = PRODUCTION + SHARED + CONFIG_INPUTS + CONTEXT[:2]
GENERATED = (".config.stamp", "config.mk", "sw/VX_config.h", "sw/VX_types.h",
             "sw/vortex_opae.h", "hw/VX_config.vh", "hw/VX_types.vh", "hw/vortex_opae.vh")
HOST_TOOLS = ("bash", "git", "env", "realpath", "find", "basename", "sed",
              "mkdir", "cp", "cat", "chmod", "ldd")


def require(condition, message):
    if not condition:
        raise ValueError(message)


def now():
    return datetime.now(timezone.utc).isoformat()


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def identities(root, names):
    return {name: {"sha256": digest(root / name), "size_bytes": (root / name).stat().st_size}
            for name in names}


LOADED = identities(ROOT, HELPERS)


def file_identity(path):
    requested = Path(os.path.abspath(path))
    resolved = requested.resolve(strict=True)
    require(resolved.is_file(), "tool or binary is not a regular file: " + str(path))
    return {"path": str(requested), "resolved_path": str(resolved),
            "sha256": digest(resolved), "size_bytes": resolved.stat().st_size}


def verify_expected_failure(text, group, result):
    require(group in GROUPS, "unknown exception group")
    require(result.get("process_started") is True and result.get("cleanup_complete") is True
            and result.get("outcome") == "fail" and result.get("exit_code") == 1
            and result.get("reason") == "nonzero_exit",
            "parent process did not exit with the required assertion failure")
    expected = "FAIL simulator-completion " + group + ": " + MARKER + "\n"
    require(text == expected, "parent failed outside the required behavioral assertion")
    return {"assertion": MARKER, "exact_output": expected}


def resolve_paths(args):
    paths = {"source": Path(os.path.abspath(args.source_dir)),
             "work": Path(os.path.abspath(args.work_dir)),
             "output": Path(os.path.abspath(args.output))}
    for name, path in paths.items():
        require(re.fullmatch(r"[A-Za-z0-9_./+\-]+", str(path)) is not None,
                name + " path contains unsupported characters")
        require(path == path.resolve(), name + " path traverses a symlink")
        if name == "source":
            require(path.is_dir(), "source directory is missing")
        else:
            require(path.parent.is_dir(), name + " parent directory is missing")
            require(not os.path.lexists(path), name + " directory already exists; preserve the previous attempt")
    for name, path in paths.items():
        for other, second in paths.items():
            if name != other:
                require(not path.is_relative_to(second), "source, work and output must be disjoint")
    return paths


def tools_snapshot(environment, compiler):
    paths = {name: shutil.which(name, path=environment["PATH"]) for name in HOST_TOOLS}
    paths["compiler"] = shutil.which(compiler, path=environment["PATH"])
    paths["sys.executable"] = sys.executable
    paths["configure-python3"] = shutil.which("python3", path=environment["PATH"])
    require(all(paths.values()), "missing host tools: " + ", ".join(name for name, path in paths.items() if not path))
    result = {name: file_identity(path) for name, path in paths.items()}
    require(result["configure-python3"]["resolved_path"] == result["sys.executable"]["resolved_path"],
            "configure interpreter differs from sys.executable")
    return result


def retain(source, destination, manifest):
    for name in manifest:
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source / name, target)
    require(identities(destination, manifest) == manifest, "retained source/configuration differs")


def resources(paths):
    memory = re.search(r"^MemAvailable:\s+([0-9]+) kB$",
                       Path("/proc/meminfo").read_text(encoding="ascii"), re.MULTILINE)
    return {"available_memory_bytes": int(memory[1]) * 1024 if memory else None,
            "free_disk_bytes": {name: shutil.disk_usage(path).free for name, path in paths.items()}}


def execute(args, paths):
    source, work, output = (paths[name] for name in ("source", "work", "output"))
    build, parent_sources = work / "rv64-p02-tfr", work / "parent-sources"
    output.mkdir(mode=0o700)
    (output / "logs").mkdir()
    report = {"schema_version": 1, "contract_id": "simulator-completion-v1",
              "scope": "host-parent-regression-sensitivity", "native_execution": False,
              "parent_revision": PARENT, "qualified": False, "acceptance_claimed": False,
              "state": "running", "outcome": "blocked", "reason": None,
              "started_at": now(), "sys_executable": sys.executable,
              "paths": {key: str(value) for key, value in paths.items()},
              "budget": dict(BUDGET, jobs=1, timeouts_seconds=TIMEOUTS), "commands": [],
              "cells": [{"backend": backend, "group": group, "memory": memory, "outcome": "not_run"}
                        for backend in BACKENDS for group in GROUPS for memory in MEMORIES],
              "builds": {}, "full_matrix_completed": False,
              "limitations": [
                  "Controlled Processor/RAM faults exercise actual old backend and shared CP host code only.",
                  "No native processor, RTL datapath, GPU kernel, performance or phase acceptance is established.",
                  "The current fixture retains SimX legacy exception catches and gp-derived normal returns.",
                  "Candidate source may be dirty; retained input bytes identify this host replay.",
                  "System headers and all transitive host tool dependencies are not a hermetic toolchain image.",
                  *LIMITATIONS]}
    original_source = original_tools = original_parent = original_generated = None
    extra_tools = {}
    environment = None

    def checkpoint():
        temporary = output / "report.json.tmp"
        temporary.write_text(json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
        temporary.replace(output / "report.json")

    def command(name, argv, timeout, cwd=None):
        entry = {"id": name, "argv": list(map(str, argv)), "cwd": str(cwd or build),
                 "timeout_seconds": timeout, "log": "logs/" + name + ".log", "result": None}
        require(not any(row["id"] == name for row in report["commands"]), "duplicate command identity")
        report["commands"].append(entry)
        checkpoint()
        entry["result"] = run_bounded(entry["argv"], Path(entry["cwd"]), environment,
                                      output / entry["log"], timeout_seconds=timeout,
                                      resource_paths=tuple(paths.values()), **BUDGET)
        checkpoint()
        return entry

    def success(entry):
        result = entry["result"]
        require(result is not None and result.get("outcome") == "pass" and result.get("exit_code") == 0
                and result.get("process_started") is True and result.get("cleanup_complete") is True
                and result.get("reason") is None,
                entry["id"] + " did not complete successfully: " + str(result))
        return (output / entry["log"]).read_text(encoding="utf-8")

    def stable():
        require(identities(source, INPUTS) == original_source, "candidate source/fixture/helper changed")
        require(tools_snapshot(environment, args.compiler) == original_tools, "host tools or interpreter changed")
        require({name: file_identity(item["path"]) for name, item in extra_tools.items()} == extra_tools,
                "compiler support or binary runtime dependency changed")
        if original_parent is not None:
            require(identities(parent_sources, PARENT_INPUTS) == original_parent, "parent source changed")
        if original_generated is not None:
            require(identities(build, GENERATED) == original_generated, "generated configuration changed")

    try:
        checkpoint()
        work.mkdir(mode=0o700)
        for directory in (build, parent_sources, work / "tmp", work / "tool-bin"):
            directory.mkdir()
        (work / "tool-bin/python3").symlink_to(Path(sys.executable).absolute())
        environment = {"PATH": str(work / "tool-bin") + os.pathsep + os.environ.get("PATH", os.defpath),
                       "LC_ALL": "C", "TMPDIR": str(work / "tmp"), "CCACHE_DISABLE": "1",
                       "UBSAN_OPTIONS": "halt_on_error=1:print_stacktrace=1",
                       "PYTHONDONTWRITEBYTECODE": "1", "GIT_OPTIONAL_LOCKS": "0", "GIT_TERMINAL_PROMPT": "0",
                       # Replacement refs can substitute a tree without changing the pinned commit ID.
                       "GIT_NO_REPLACE_OBJECTS": "1"}
        report["environment"] = environment
        report["resources_before"] = resources(paths)
        require(all(value >= GIB for value in report["resources_before"]["free_disk_bytes"].values()),
                "disk reserve is below 1 GiB")
        require((report["resources_before"]["available_memory_bytes"] or 0) >= GIB,
                "available host memory is below 1 GiB")
        require(identities(source, HELPERS) == LOADED, "executing helpers differ from candidate source")
        original_source = report["source_before"] = identities(source, INPUTS)
        retain(source, output / "inputs/candidate", original_source)
        original_tools = report["tools_before"] = tools_snapshot(environment, args.compiler)
        git = original_tools["git"]["path"]
        compiler = original_tools["compiler"]["path"]
        for name in ("compiler", "sys.executable", "bash", "git"):
            success(command("version-" + name.replace(".", "-"),
                            [original_tools[name]["path"], "--version"], TIMEOUTS["probe"]))
        # Capture actual compiler support binaries/libraries where the driver
        # exposes them. Unresolved names are explicit, never guessed identities.
        report["compiler_support_queries"] = {}
        for kind, name in (("prog", "cc1plus"), ("prog", "as"), ("prog", "ld"),
                           ("file", "libstdc++.so"), ("file", "libubsan.so"), ("file", "libgcc_s.so.1")):
            answer = success(command("compiler-support-" + name.replace("+", "p"),
                                     [compiler, "-print-" + kind + "-name=" + name], TIMEOUTS["probe"])).strip()
            resolved = answer if Path(answer).is_file() else shutil.which(answer, path=environment["PATH"])
            report["compiler_support_queries"][name] = answer
            if resolved:
                extra_tools["compiler-" + name] = file_identity(resolved)
        report["candidate_revision"] = success(command("candidate-revision", [git, "-C", source, "rev-parse", "HEAD"],
                                                        TIMEOUTS["probe"])).strip()
        report["candidate_status"] = success(command("candidate-status", [git, "-C", source, "status", "--porcelain",
                                                                     "--untracked-files=normal"], TIMEOUTS["probe"]))
        revision = success(command("parent-revision", [git, "-C", source, "rev-parse", PARENT + "^{commit}"],
                                   TIMEOUTS["probe"])).strip()
        require(revision == PARENT, "pinned local parent object is unavailable")
        blob_ids = success(command("parent-blob-identities", [git, "-C", source, "rev-parse",
                                    *(PARENT + ":" + name for name in PARENT_INPUTS)], TIMEOUTS["probe"])).splitlines()
        require(len(blob_ids) == len(PARENT_INPUTS), "parent blob identity count differs")
        report["parent_git_blobs"] = dict(zip(PARENT_INPUTS, blob_ids))
        for index, name in enumerate(PARENT_INPUTS):
            entry = command("parent-source-" + str(index).zfill(2), [git, "-C", source, "show", PARENT + ":" + name],
                            TIMEOUTS["probe"])
            success(entry)
            content = (output / entry["log"]).read_bytes()
            blob = hashlib.sha1(b"blob " + str(len(content)).encode("ascii") + b"\0" + content).hexdigest()
            require(blob == blob_ids[index], "extracted parent source differs from its Git blob: " + name)
            destination = parent_sources / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(content)
        original_parent = report["parent_before"] = identities(parent_sources, PARENT_INPUTS)
        retain(parent_sources, output / "inputs/parent", original_parent)
        report["shared_parent_candidate_equal"] = {
            name: original_parent[name] == original_source[name] for name in SHARED + CONFIG_INPUTS}
        require(all(report["shared_parent_candidate_equal"].values()),
                "shared production CP/callback/support or configuration input differs from pinned parent")
        stable()
        success(command("configure-rv64-p02-tfr", [original_tools["bash"]["path"], source / "configure", "--xlen=64",
                        "--profile=p02-tfr", "--osversion=ubuntu/focal", "--tooldir=" + str(work / "unused-tools")],
                        TIMEOUTS["configure"]))
        config = (build / "config.mk").read_text(encoding="utf-8")
        for name, value in (("XLEN", "64"), ("PROFILE", "p02-tfr")):
            require(re.search(r"^" + name + r"\s*\?=\s*" + re.escape(value) + r"\s*$", config, re.MULTILINE),
                    "generated configuration does not select " + name + "=" + value)
        original_generated = report["generated_before"] = identities(build, GENERATED)
        retain(build, output / "configuration", original_generated)
        for backend in BACKENDS:
            stable()

            def compile_command(argv, *, cwd, env, timeout):
                require(env == environment and timeout == TIMEOUTS["build"] and Path(cwd) == build,
                        "compile_backend changed its execution contract")
                return success(command("build-" + backend, argv, timeout, cwd))

            # Use the existing compiler argv producer, only adapting its command
            # recorder. No fixture/backend/CP body is rewritten by this runner.
            with mock.patch.object(fixture, "ROOT", source), mock.patch.object(fixture, "FIXTURES", source / Path(FIXTURES[0]).parent), \
                    mock.patch.object(fixture, "run_host_command", side_effect=compile_command):
                binary = fixture.compile_backend(compiler, backend, build, environment,
                                                  backend_source=parent_sources / "sw/runtime" / backend / "vortex.cpp")
            require(binary.is_file() and os.access(binary, os.X_OK), "compiled parent binary is missing or not executable")
            record = report["builds"][backend] = {"command": "build-" + backend, "binary_before": file_identity(binary)}
            linked = success(command("dependencies-" + backend, [original_tools["ldd"]["path"], binary], TIMEOUTS["probe"]))
            require("not found" not in linked, "compiled parent binary has an unresolved runtime dependency")
            for path in re.findall(r"(?:=>\s+|^\s*)(/[^\s]+)\s+\(", linked, re.MULTILINE):
                key, identity = "runtime-" + path, file_identity(path)
                require(key not in extra_tools or extra_tools[key] == identity,
                        "binary runtime dependency changed between backend builds")
                extra_tools[key] = identity
            stable()
            for cell in (row for row in report["cells"] if row["backend"] == backend):
                stable()
                require(file_identity(binary) == record["binary_before"], "parent binary changed before execution")
                cell["outcome"] = "running"
                name = "run-" + backend + "-" + cell["group"] + "-" + cell["memory"]
                entry = command(name, [binary, cell["group"], cell["memory"]], TIMEOUTS["run"])
                cell.update(run_command=name, build_command="build-" + backend, result=entry["result"])
                try:
                    cell["observations"] = verify_expected_failure((output / entry["log"]).read_text(encoding="utf-8"),
                                                                    cell["group"], entry["result"])
                    cell["outcome"] = "expected_failure"
                except (OSError, ValueError, UnicodeError) as error:
                    cell.update(outcome="fail", reason=str(error))
                require(file_identity(binary) == record["binary_before"], "parent binary changed during execution")
                stable()
                checkpoint()
            record["binary_after"] = file_identity(binary)
        require(all(cell["outcome"] == "expected_failure" for cell in report["cells"]),
                "parent did not demonstrate the intended failure in all eight exception cells")
        report.update(outcome="pass", reason=None)
    except (OSError, ValueError, RuntimeError, AssertionError, UnicodeError) as error:
        report.update(outcome="fail" if any((row["result"] or {}).get("process_started") for row in report["commands"]) else "blocked",
                      reason=str(error))
    except KeyboardInterrupt:
        report.update(outcome="fail", reason="runner interrupted")
    finally:
        for name, original, observe in (
                ("source", original_source, lambda: identities(source, INPUTS)),
                ("tools", original_tools, lambda: tools_snapshot(environment, args.compiler)),
                ("parent", original_parent, lambda: identities(parent_sources, PARENT_INPUTS)),
                ("generated", original_generated, lambda: identities(build, GENERATED))):
            if original is not None:
                try:
                    report[name + "_after"] = observe()
                    require(report[name + "_after"] == original, name + " changed during replay")
                except (OSError, ValueError) as error:
                    report.update(outcome="fail", reason=str(error))
        try:
            report["extra_tools_before"] = extra_tools
            report["extra_tools_after"] = {name: file_identity(item["path"]) for name, item in extra_tools.items()}
            require(report["extra_tools_before"] == report["extra_tools_after"], "compiler/runtime dependency changed")
            for record in report["builds"].values():
                record["binary_after"] = file_identity(record["binary_before"]["path"])
                require(record["binary_before"] == record["binary_after"], "compiled parent binary changed")
            for entry in report["commands"]:
                result = entry["result"] or {}
                if result.get("log_sha256") is not None:
                    log = output / entry["log"]
                    require(digest(log) == result["log_sha256"] and log.stat().st_size == result["log_size_bytes"],
                            "retained command log changed: " + entry["id"])
            for location, manifest in (("inputs/candidate", original_source), ("inputs/parent", original_parent),
                                       ("configuration", original_generated)):
                if manifest is not None:
                    require(identities(output / location, manifest) == manifest, "retained inputs changed: " + location)
            if work.is_dir():
                report["resources_after"] = resources(paths)
                require(all(value >= GIB for value in report["resources_after"]["free_disk_bytes"].values()),
                        "final disk reserve is below 1 GiB")
        except (OSError, ValueError) as error:
            report.update(outcome="fail", reason=str(error))
        for cell in report["cells"]:
            if cell["outcome"] in ("not_run", "running"):
                cell.update(outcome="blocked" if cell["outcome"] == "not_run" else "fail", reason=report["reason"])
        report["full_matrix_completed"] = report["outcome"] == "pass" and all(
            cell["outcome"] == "expected_failure" for cell in report["cells"])
        report.update(state="finished", finished_at=now())
        checkpoint()
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--source-dir", type=Path, default=ROOT)
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--compiler", default="c++", help="Installed host C++17/UBSan compiler; no downloads")
    args = parser.parse_args(argv)
    try:
        paths = resolve_paths(args)
        report = execute(args, paths)
    except (OSError, ValueError, RuntimeError) as error:
        print("Simulator HOST parent replay blocked: " + str(error), file=sys.stderr)
        return 2
    print(json.dumps({"outcome": report["outcome"], "scope": report["scope"],
                      "full_matrix_completed": report["full_matrix_completed"],
                      "report": str(paths["output"] / "report.json")}))
    return 0 if report["outcome"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())

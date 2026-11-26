#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Run the independent P02 WMMA fixtures through fresh SimX/native RTL trees.

Example (all four variants, all 88 fixtures, two launches per fixture)::

    python3 ci/project/p02_matrix.py run --source-dir "$PWD" \
        --tools-dir /tools --host-bin /host/bin \
        --work-dir /new/p02-builds --output /new/p02-results

Use --development with --backend, --format and/or --case for bounded iteration
on an uncommitted implementation. Every invocation requires fresh work/output
directories. A successful packet is execution evidence, never automatic phase
acceptance, unsupported-format qualification, or WGMMA coverage.
"""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys

from baseline_inventory import _digest, collect_source, hash_artifacts
from baseline_process import GIB, MIB, LIMITATIONS as PROCESS_LIMITATIONS, run_bounded
from p02_matrix_records import (HEX_WORD, PROFILE_SHA256, require, validate_header_macros,
                                validate_records, verify_output)
from preflight import available_memory_bytes


ROOT = Path(__file__).resolve().parents[2]
CONTRACT_ID = "p02-wmma-processor-matrix-v1"
APP = "tests/regression/sgemm_tcu"
FORMATS = ("fp16", "bf16")
BACKENDS = ("simx", "rtlsim")
SAFE_PATH = re.compile(r"/[A-Za-z0-9_./+-]+\Z")
CASE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}\Z")
BUDGET = {"min_free_bytes": 15 * GIB, "max_rss_bytes": 6 * GIB, "max_log_bytes": 16 * MIB}
GENERATED = (".config.stamp", "config.mk", "sw/VX_config.h", "sw/VX_types.h",
             "hw/VX_config.vh", "hw/VX_types.vh", "sim/rtlsim/verilator.vlt")
COPIED = ("ci/gen_config.py", "sw/kernel/Makefile", "sw/runtime/common.mk",
          "sw/runtime/stub/Makefile", "sw/runtime/simx/Makefile", "sw/runtime/rtlsim/Makefile",
          "sim/common.mk", "sim/simx/Makefile", "sim/rtlsim/Makefile",
          "tests/regression/common.mk", APP + "/Makefile")
DEPENDENCIES = ("third_party/softfloat/build/Linux-x86_64-GCC/softfloat.a",
                "third_party/ramulator/libramulator.so",
                "third_party/ramulator_ext/libramulator-vortex.so")
CORPUS = ("ci/project/fixtures/p02_layout_v1.json", "ci/project/fixtures/p02_tfr_v1.json",
          "ci/project/fixtures/p02_wmma_numerical_v1.json", APP + "/p02_fixtures.h")
TOOLING = tuple("ci/project/" + name for name in (
    "p02_matrix.py", "p02_matrix_records.py", "baseline_inventory.py", "baseline_process.py",
    "preflight.py", "compiler_records.py", "baseline_packet_contract.py", "baseline_packet_io.py",
    "baseline_matrix.py", "p02_fixture_oracle.py", "p02_layout_fixture_oracle.py",
    "p02_wmma_numerical_fixture_oracle.py", "p02_wmma_fixtures.py"))
SOURCE_ROOTS = ("sw/common", "sw/kernel", "sw/runtime", "sim/common", "sim/simx",
                "sim/rtlsim", "hw/rtl", "hw/dpi", APP)
SOURCE_SUFFIXES = {".c", ".cc", ".cpp", ".h", ".hpp", ".S", ".s", ".sv", ".v", ".vh",
                   ".vi", ".mk", ".in", ".ld", ".sh", ".py", ".toml"}
LIMITATIONS = [
    "A passing packet does not accept P02-A02 or close P02; review and separate acceptance are required.",
    "Only selected ordinary dense WMMA fixtures and their exact raw output bits are checked.",
    "Unsupported-format API rejection and WGMMA synchronization/backpressure are separate obligations.",
    "Native processor rtlsim bypasses the AFU; no vendor hw_emu, physical FPGA or silicon result is claimed.",
    "Dependency libraries are reused, identified inputs; this runner does not rebuild or download them.",
    "Tool hashes do not inventory every system header, compiler support file or dynamic library.",
    "Raw logs and snapshots retain local paths and require review before publication.",
    *PROCESS_LIMITATIONS,
]
LOADED_HELPERS = hash_artifacts(ROOT, sorted({
    Path(module.__file__).resolve().relative_to(ROOT).as_posix()
    for module in tuple(sys.modules.values())
    if getattr(module, "__file__", None)
    and Path(module.__file__).suffix == ".py"
    and Path(module.__file__).resolve().is_relative_to(ROOT / "ci/project")
}))


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _json_bytes(value):
    return (json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n").encode()


def _write_json(path, value):
    body = _json_bytes(value)
    require(len(body) <= 16 * MIB, "JSON checkpoint exceeds 16 MiB")
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("xb") as stream:
        stream.write(body)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def _path(value, *, existing=False):
    result = Path(os.path.abspath(value))
    require(SAFE_PATH.fullmatch(str(result)) and result.resolve(strict=existing) == result,
            "root paths must be absolute safe literals without symlink traversal")
    return result


def _overlap(left, right):
    return left == right or left.is_relative_to(right) or right.is_relative_to(left)


def resolve_paths(args):
    result = {"source": _path(args.source_dir, existing=True),
              "tools": _path(args.tools_dir, existing=True),
              "work": _path(args.work_dir), "output": _path(args.output)}
    require(result["source"] == ROOT, "execute the runner from the selected source checkout")
    require(all(result[name].is_dir() for name in ("source", "tools")),
            "source-dir and tools-dir must be directories")
    for name in ("work", "output"):
        require(not os.path.lexists(result[name]) and result[name].parent.is_dir(),
                name + " directory must be fresh under an existing parent")
        require(not any(_overlap(result[name], result[other]) for other in result if other != name),
                name + " directory overlaps another input/output root")
    result["host_bin"] = _path(args.host_bin, existing=True) if args.host_bin else None
    if result["host_bin"]:
        require(result["host_bin"].is_dir(), "host-bin must be a directory")
    verilator = args.verilator or result["tools"] / "verilator"
    # Accept either the installation root or its bin/verilator entry point.
    if Path(verilator).name == "verilator" and Path(verilator).is_file():
        verilator = Path(verilator).parent.parent
    result["verilator"] = _path(verilator)
    return result


def clean_environment(paths, jobs):
    entries = ([str(paths["host_bin"])] if paths["host_bin"] else [])
    entries += [str(Path(sys.executable).parent), "/usr/bin", "/bin"]
    return {
        "PATH": os.pathsep.join(dict.fromkeys(entries)), "HOME": str(paths["work"] / "home"),
        "TMPDIR": str(paths["work"] / "tmp"), "LANG": "C", "LC_ALL": "C", "TZ": "UTC",
        "PYTHONUTF8": "1", "PYTHONDONTWRITEBYTECODE": "1", "CCACHE_DISABLE": "1", "OBJCACHE": "",
        "MAKEFLAGS": "-j" + str(jobs), "THREADS": str(jobs),
        "CMAKE_BUILD_PARALLEL_LEVEL": str(jobs),
    }


def _resources(paths):
    return {"available_memory_bytes": available_memory_bytes(), "free_disk_bytes": {
        name: shutil.disk_usage(path if path.exists() else path.parent).free
        for name, path in paths.items() if name in ("source", "tools", "work", "output")}}


def source_snapshot(source):
    checkout = collect_source(source)
    names = set(TOOLING + CORPUS + COPIED + (
        "configure", "config.mk.in", "VERSION", ".gitmodules", "VX_config.toml", "VX_types.toml",
        "profiles/p02-tfr.json", "ci/project/p02_tensor_contract.json", "sim/rtlsim/verilator.vlt.in"))
    for directory in SOURCE_ROOTS:
        for path in (source / directory).rglob("*"):
            if path.is_file() and (path.suffix in SOURCE_SUFFIXES or path.name == "Makefile"):
                names.add(path.relative_to(source).as_posix())
    # Dirty development snapshots bind actual changed bytes as well as Git status.
    for name in checkout["changed_paths"] + checkout["untracked_paths"]:
        if (source / name).is_file():
            names.add(name)
    return {"checkout": checkout, "files": hash_artifacts(source, sorted(names))}


def _source_ok(snapshot, development):
    blockers = list(snapshot["checkout"]["blockers"])
    if development:
        blockers = [reason for reason in blockers if reason !=
                    "source contains tracked changes or nonignored untracked inputs"]
    require(not blockers, "source provenance blocked: " + "; ".join(blockers))
    require(development or snapshot["checkout"]["dirty"] is False,
            "formal runs require a clean source checkout")


def _file_identity(path):
    invoked = Path(path).absolute()
    resolved = invoked.resolve(strict=True)
    digest, size = _digest(resolved)
    return {"path": str(invoked), "resolved_path": str(resolved), "sha256": digest, "size_bytes": size}


def tool_inventory(paths, env, backends):
    selected = {}
    for name in ("make", "g++", "gcc", "ar", "as", "ld", "python3", "bash", "perl"):
        path = shutil.which(name, path=env["PATH"])
        require(path is not None, "required host tool is missing: " + name)
        selected[name] = path
    for name in ("clang", "clang++", "llvm-objcopy", "llvm-objdump"):
        selected[name] = paths["tools"] / "llvm-vortex/bin" / name
    for name in ("gcc", "gcc-ar", "objdump", "objcopy"):
        selected["riscv-" + name] = (paths["tools"] / "riscv64-gnu-toolchain/bin" /
                                   ("riscv64-unknown-elf-" + name))
    if "rtlsim" in backends:
        for name in ("verilator", "verilator_bin"):
            selected[name] = paths["verilator"] / "bin" / name
    require(all(os.access(path, os.X_OK) for path in selected.values()), "selected tool is not executable")
    result = {name: _file_identity(path) for name, path in selected.items()}
    for name in ("libc64/lib/libc.a", "libc64/lib/libm.a",
                 "libcrt64/lib/baremetal/libclang_rt.builtins-riscv64.a"):
        result[name] = _file_identity(paths["tools"] / name)
    return result


def select_cases(cases, args):
    require(isinstance(cases, list) and len(cases) == 88, "expected exactly 88 frozen matrix fixtures")
    require(len({case["id"] for case in cases}) == len(cases), "duplicate fixture ID")
    require(Counter(case["format"] for case in cases) == {"fp16": 44, "bf16": 44},
            "fixture format inventory is incomplete")
    for case in cases:
        require(isinstance(case["id"], str) and CASE_ID.fullmatch(case["id"]), "unsafe fixture ID")
        for name, divisor in (("m", 8), ("n", 4), ("k", 8)):
            require(type(case[name]) is int and 0 < case[name] <= 4096 and case[name] % divisor == 0,
                    "unsupported fixture dimensions")
        for name, count in (("a_words", case["m"] * case["k"] // 2),
                            ("b_words", case["n"] * case["k"] // 2),
                            ("expected", case["m"] * case["n"])):
            require(isinstance(case[name], list) and len(case[name]) == count
                    and all(isinstance(word, str) and HEX_WORD.fullmatch(word) for word in case[name]),
                    "invalid packed fixture words: " + name)
    for values, label in ((args.backend, "backend"), (args.format, "format"), (args.case, "case")):
        require(values is None or len(values) == len(set(values)), "duplicate " + label + " selection")
    backends, formats = args.backend or list(BACKENDS), args.format or list(FORMATS)
    requested = set(args.case) if args.case is not None else None
    if requested is not None:
        require(requested <= {case["id"] for case in cases}, "unknown fixture case selection")
    selected = [case for case in cases if case["format"] in formats
                and (requested is None or case["id"] in requested)]
    require(selected and (requested is None or {case["id"] for case in selected} == requested),
            "empty selection or fixture/format selection conflict")
    formats = [fmt for fmt in FORMATS if any(case["format"] == fmt for case in selected)]
    full = set(backends) == set(BACKENDS) and len(selected) == 88 and args.iterations == 2
    require(args.development or full, "partial matrices and one iteration require --development")
    return selected, [(driver, fmt) for driver in BACKENDS if driver in backends for fmt in formats], full


def _generated_identity(build, source, tools):
    text = (build / "config.mk").read_text(encoding="utf-8")
    for name, expected in (("XLEN", "64"), ("PROFILE", "p02-tfr"), ("VORTEX_HOME", str(source)),
                           ("TOOLDIR", str(tools)), ("OSVERSION", "ubuntu/focal")):
        matches = re.findall(r"^" + name + r"[ \t]*\?=[ \t]*(.*?)[ \t]*$", text, re.MULTILINE)
        require(matches == [expected], "generated config.mk has incorrect " + name)
    stamp = (build / ".config.stamp").read_text(encoding="utf-8").strip().split()
    fields = dict(token.split("=", 1) for token in stamp)
    require(len(fields) == len(stamp), "generated configure stamp repeats settings")
    for key, expected in (("XLEN", "64"), ("PROFILE", "p02-tfr"), ("SOURCE_DIR", str(source)),
                          ("BUILDDIR", str(build)), ("TOOLDIR", str(tools))):
        require(fields.get(key) == expected, "generated configure stamp has incorrect " + key)
    for name in COPIED:
        require((build / name).read_bytes() == (source / name).read_bytes(),
                "generated Makefile/helper differs from source: " + name)
    expected = (source / "sim/rtlsim/verilator.vlt.in").read_text().replace("@VORTEX_HOME@", str(source))
    require((build / "sim/rtlsim/verilator.vlt").read_text() == expected,
            "generated Verilator configuration differs from source")
    return hash_artifacts(build, GENERATED + COPIED)


def _build_artifacts(driver):
    return GENERATED + COPIED + ("sw/runtime/" + driver + "_rt_config.stamp",
        "sw/runtime/" + driver + "_config.stamp", APP + "/config.stamp", APP + "/sgemm_tcu",
        APP + "/kernel.elf", APP + "/kernel.vxbin", "sw/kernel/libvortex2.a",
        "sw/runtime/libvortex.so", "sw/runtime/libvortex-" + driver + ".so",
        "sw/runtime/lib" + driver + ".so")


def execute_run(args, paths):
    output, work, source = paths["output"], paths["work"], paths["source"]
    output.mkdir(mode=0o700)
    report = {"schema_version": 1, "contract_id": CONTRACT_ID, "started_at": _now(),
              "state": "running", "outcome": "blocked", "reason": None,
              "development": args.development, "acceptance_claimed": False,
              "qualifies_P02_A02": False, "qualifies_P02_A03": False, "phase_complete": False,
              "paths": {name: str(path) if path else None for name, path in paths.items()},
              "budget": dict(BUDGET, jobs=args.jobs, build_timeout_seconds=args.timeout_seconds,
                             run_timeout_seconds=args.run_timeout_seconds, configure_timeout_seconds=120),
              "iterations": args.iterations, "commands": [], "variants": [],
              "limitations": LIMITATIONS}
    active_variant = active_case = initial_source = initial_tools = dependencies = None

    def checkpoint():
        _write_json(output / "report.json", report)

    def snapshot_json(name, value):
        relative = "snapshots/" + name + ".json"
        _write_json(output / relative, value)
        return hash_artifacts(output, [relative])[0]

    def command(name, argv, cwd, environment, timeout):
        entry = {"id": name, "argv": [str(item) for item in argv], "cwd": str(cwd),
                 "environment": environment, "log": "logs/" + name + ".log", "outcome": "running",
                 "timeout_seconds": timeout, "resources_before": _resources(paths)}
        report["commands"].append(entry)
        checkpoint()
        entry.update(run_bounded(entry["argv"], cwd, environment, output / entry["log"],
                                 timeout_seconds=timeout, **BUDGET,
                                 resource_paths=(source, paths["tools"], work, output)))
        checkpoint()
        require(entry["outcome"] == "pass" and entry["exit_code"] == 0
                and entry["process_started"] and entry["cleanup_complete"],
                "command " + name + " stopped: " + str(entry.get("reason")))
        return entry

    def stable(label):
        observed = source_snapshot(source)
        report["source_" + label] = snapshot_json("source-" + label, observed)
        _source_ok(observed, args.development)
        require(observed == initial_source, "source changed during matrix execution")
        require(tool_inventory(paths, env, backends) == initial_tools, "selected tools changed during execution")
        require(hash_artifacts(source, DEPENDENCIES) == dependencies, "dependency libraries changed during execution")
        checkpoint()

    try:
        (output / "logs").mkdir()
        (output / "snapshots").mkdir()
        (output / "artifacts").mkdir()
        checkpoint()
        work.mkdir(mode=0o700)
        (work / "tmp").mkdir()
        (work / "home").mkdir()
        env = clean_environment(paths, args.jobs)
        report["resources_before"] = _resources(paths)
        require(all(value >= BUDGET["min_free_bytes"] for value in
                    report["resources_before"]["free_disk_bytes"].values()), "disk reserve is below 15 GiB")
        memory = report["resources_before"]["available_memory_bytes"]
        require(memory is not None and memory >= BUDGET["max_rss_bytes"],
                "at least 6 GiB available memory is required before execution")
        require(hash_artifacts(source, [item["path"] for item in LOADED_HELPERS]) == LOADED_HELPERS,
                "executing runner/helper bytes changed after import")
        report["loaded_helpers"] = LOADED_HELPERS
        initial_source = source_snapshot(source)
        report["source_before"] = snapshot_json("source-before", initial_source)
        _source_ok(initial_source, args.development)
        require(_digest(source / "profiles/p02-tfr.json")[0] == PROFILE_SHA256,
                "p02-tfr profile differs from the frozen numerical contract")
        # Import only after provenance is retained; the producer validates its corpus.
        from p02_wmma_fixtures import load_cases
        cases, variants, full = select_cases(load_cases(source), args)
        backends = sorted({driver for driver, _ in variants})
        report.update(full_matrix_requested=full, case_ids=[case["id"] for case in cases],
                      selected_case_count=len(cases), expected_case_executions=sum(
                          sum(case["format"] == fmt for case in cases) for _, fmt in variants),
                      corpus=hash_artifacts(source, CORPUS),
                      profile=hash_artifacts(source, ["profiles/p02-tfr.json"])[0])
        report["fixture_snapshot"] = snapshot_json("selected-fixtures", cases)
        initial_tools = tool_inventory(paths, env, backends)
        report["tools_before"] = snapshot_json("tools-before", initial_tools)
        dependencies = hash_artifacts(source, DEPENDENCIES)
        report["dependencies_before"] = dependencies
        saved = []
        for name in TOOLING + CORPUS + ("profiles/p02-tfr.json", "ci/project/p02_tensor_contract.json"):
            destination = output / "artifacts/source" / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            with destination.open("xb") as stream:
                stream.write((source / name).read_bytes())
            saved.append(destination.relative_to(output).as_posix())
        report["source_snapshots"] = hash_artifacts(output, saved)
        checkpoint()
        for name in ("g++", "make", "clang", "riscv-gcc") + (("verilator",) if "rtlsim" in backends else ()):
            command("version-" + name.replace("+", "p"), [initial_tools[name]["path"], "--version"],
                    work, env, 30)
        for driver, fmt in variants:
            variant_id = driver + "-" + fmt
            build = work / variant_id
            build.mkdir()
            current = dict(env, CONFIGS=f"-DITYPE={fmt} -DOTYPE=fp32 -DKUNROLL=1")
            active_variant = {"id": variant_id, "backend": driver, "format": fmt,
                              "configuration_id": "p02-tfr-rv64-t4-wmma-v1/" + fmt + "-fp32-kunroll1",
                              "build_dir": str(build), "outcome": "running", "cases": []}
            report["variants"].append(active_variant)
            stable(variant_id + "_before")
            command(variant_id + "-configure", [source / "configure", "--xlen=64", "--profile=p02-tfr",
                    "--osversion=ubuntu/focal", "--tooldir=" + str(paths["tools"])], build, env, 120)
            active_variant["generated_before"] = _generated_identity(build, source, paths["tools"])
            header = command(variant_id + "-header", [initial_tools["g++"]["path"], "-E", "-dM",
                "-x", "c++", "-DVX_CFG_XLEN=64", "-DVX_CFG_XLEN_64", "-include",
                build / "sw/VX_config.h", "/dev/null"], build, env, 30)
            active_variant["header_macros"] = validate_header_macros((output / header["log"]).read_text())
            # Independently reproduce both generated configuration headers with
            # identical basenames (their include guards depend on the basename).
            check_dir = build / "p02-header-check"
            check_dir.mkdir()
            for language, relative in (("cpp", "sw/VX_config.h"), ("verilog", "hw/VX_config.vh")):
                destination = check_dir / Path(relative).name
                command(variant_id + "-" + language + "-header-reproduce", [initial_tools["python3"]["path"],
                    source / "ci/gen_config.py", "--config=" + str(source / "VX_config.toml"),
                    "--profile=p02-tfr", "--format=" + language, "--output=" + str(destination)],
                    build, dict(env, XLEN="64"), 30)
                require(destination.read_bytes() == (build / relative).read_bytes(),
                        "generated configuration header did not reproduce")
            make = [initial_tools["make"]["path"], "--no-print-directory", "-j" + str(args.jobs),
                    "THREADS=" + str(args.jobs), "VERILATOR_PATH=" + str(paths["verilator"])]
            app = build / APP
            command(variant_id + "-runtime-" + driver, make + ["runtime-" + driver], app,
                    current, args.timeout_seconds)
            command(variant_id + "-application-build", make + ["all"], app, current, args.timeout_seconds)
            active_variant["compiler_records"] = validate_records(
                (build / ("sw/runtime/" + driver + "_rt_config.stamp")).read_text(),
                (build / ("sw/runtime/" + driver + "_config.stamp")).read_text(),
                (app / "config.stamp").read_text(), driver=driver, fmt=fmt, source=source,
                build=build, jobs=args.jobs)
            arithmetic_record = active_variant["compiler_records"][1]
            effective = command(variant_id + "-backend-header", [initial_tools["g++"]["path"],
                "-E", "-dM", "-x", "c++", *arithmetic_record["macro_flags"], "-include",
                build / "sw/VX_config.h", "/dev/null"], build, env, 30)
            active_variant["backend_header_macros"] = validate_header_macros(
                (output / effective["log"]).read_text())
            baseline_artifacts = hash_artifacts(build, _build_artifacts(driver))
            active_variant["artifacts_before"] = baseline_artifacts
            for artifact in baseline_artifacts:
                if artifact["path"].endswith((".stamp", ".mk", ".h", ".vh", ".vlt")) or Path(artifact["path"]).name == "Makefile":
                    destination = output / "artifacts" / variant_id / artifact["path"]
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    with destination.open("xb") as stream:
                        stream.write((build / artifact["path"]).read_bytes())
            stable(variant_id + "_built")
            for case in (case for case in cases if case["format"] == fmt):
                active_case = {"id": case["id"], "outcome": "running"}
                active_variant["cases"].append(active_case)
                checkpoint()
                require(hash_artifacts(build, _build_artifacts(driver)) == baseline_artifacts,
                        "build artifacts changed before fixture launch")
                entry = command(variant_id + "-" + case["id"], make + ["run-" + driver,
                    "OPTS=-f " + case["id"] + " -r " + str(args.iterations)], app, current,
                    args.run_timeout_seconds)
                require(hash_artifacts(build, _build_artifacts(driver)) == baseline_artifacts,
                        "build artifacts changed during fixture launch")
                active_case.update(outcome="pass", command_id=entry["id"], observations=verify_output(
                    (output / entry["log"]).read_text(encoding="utf-8", errors="strict"), case, args.iterations))
                active_case = None
                checkpoint()
            active_variant["artifacts_after"] = hash_artifacts(build, _build_artifacts(driver))
            stable(variant_id + "_after")
            active_variant["outcome"] = "pass"
            active_variant = None
            checkpoint()
        report["completed_case_executions"] = sum(len(variant["cases"]) for variant in report["variants"])
        require(report["completed_case_executions"] == report["expected_case_executions"],
                "matrix execution count is incomplete")
        report["outcome"] = "pass"
    except (OSError, ValueError, RuntimeError, UnicodeError, KeyError, ImportError) as error:
        report.update(outcome="fail" if report["commands"] else "blocked", reason=str(error))
        for item in (active_case, active_variant):
            if item is not None:
                item.update(outcome="fail", reason=str(error))
    except KeyboardInterrupt:
        report.update(outcome="fail", reason="execution interrupted")
        for item in (active_case, active_variant):
            if item is not None:
                item.update(outcome="fail", reason="execution interrupted")
    finally:
        if initial_source is not None:
            try:
                final_source = source_snapshot(source)
                report["source_after"] = snapshot_json("source-after", final_source)
                report["source_stable"] = final_source == initial_source
                if final_source != initial_source:
                    report.update(outcome="fail", reason="source changed during matrix execution")
            except (OSError, ValueError, RuntimeError) as error:
                report.update(outcome="fail", reason="final source identity unavailable: " + str(error))
        if initial_tools is not None:
            try:
                final_tools = tool_inventory(paths, env, backends)
                report["tools_after"] = snapshot_json("tools-after", final_tools)
                report["dependencies_after"] = hash_artifacts(source, DEPENDENCIES)
                require(final_tools == initial_tools and report["dependencies_after"] == dependencies,
                        "tools or dependencies changed during execution")
            except (OSError, ValueError, RuntimeError) as error:
                report.update(outcome="fail", reason=str(error))
        report.update(state="finished", finished_at=_now())
        report["resources_after"] = _resources(paths)
        checkpoint()
    return report


def _timeout(value):
    try:
        result = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("timeout must be an integer") from error
    if not 1 <= result <= 1800:
        raise argparse.ArgumentTypeError("timeout must be between 1 and 1800 seconds")
    return result


def argument_parser():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("mode", choices=("run",))
    parser.add_argument("--source-dir", type=Path, default=ROOT)
    parser.add_argument("--tools-dir", type=Path, required=True)
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--host-bin", type=Path)
    parser.add_argument("--verilator", type=Path, help="Verilator installation root or bin/verilator path")
    parser.add_argument("--backend", action="append", choices=BACKENDS)
    parser.add_argument("--format", action="append", choices=FORMATS)
    parser.add_argument("--case", action="append")
    parser.add_argument("--iterations", type=int, choices=(1, 2), default=2)
    parser.add_argument("--development", action="store_true", help="allow dirty source and selected/short matrices")
    parser.add_argument("--jobs", type=int, choices=(1, 2), default=2)
    parser.add_argument("--timeout-seconds", type=_timeout, default=1800, help="per build timeout; maximum 1800")
    parser.add_argument("--run-timeout-seconds", type=_timeout, default=180, help="per fixture launch timeout")
    return parser


def main(argv=None):
    args = argument_parser().parse_args(argv)
    try:
        report = execute_run(args, resolve_paths(args))
        print(json.dumps({"outcome": report["outcome"], "reason": report["reason"],
                          "report": str(Path(args.output).absolute() / "report.json"),
                          "acceptance_claimed": False}, sort_keys=True))
        return 0 if report["outcome"] == "pass" else 1
    except (OSError, ValueError, RuntimeError) as error:
        print(json.dumps({"outcome": "blocked", "reason": str(error), "acceptance_claimed": False}, sort_keys=True))
        return 1


if __name__ == "__main__":
    sys.exit(main())

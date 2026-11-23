#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Observe real pending reads using a completed, checked managed model build.

This is an executing probe of a live build, not an inert archive reader. Only
validated compiler flags are reused; recorded commands are never executed.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import sys

sys.dont_write_bytecode = True

from baseline_inventory import _digest, collect_source, hash_artifacts
from baseline_packet_contract import _stamp_words
from baseline_packet_io import load_json_bytes
from baseline_process import run_bounded
import p02_matrix as base
import p06_managed_preflight_build as build_records
import p06_managed_preflight_contract as preflight_contract
import p06_managed_preflight_execute as preflight
from preflight import available_memory_bytes


ROOT = Path(__file__).resolve().parents[2]
CONTRACT_ID = "p06-pending-read-probe-v1"
MANAGED_CONTRACT_ID = "p06-managed-counter-lifetime-v1"
PROBE_SOURCE = "tests/unittest/pending_reads/main.cpp"
SOURCE_FILES = (PROBE_SOURCE, "ci/project/p06_pending_probe.py")
MAX_STEPS = 200000
MAX_JSON_BYTES = 16 * 1024**2
BUDGET = dict(preflight.BUDGET)
PASS_LINE = "PASSED pending_reads native_probe contexts=2 stepped_runs=2 checked_runs=2 readonly=1"
ZERO_FAILURE = "FAILED pending_reads native_probe: pending getter did not observe an outstanding read"
LIBRARIES = ("libsimx.so", "libramulator.so", "libramulator-vortex.so")
LIMITATIONS = [
    "This separate scalar accessor probe is outside the four managed processes and their 132 launches.",
    "The always-zero control changes only the separate probe translation unit; model storage and measurement products are not mutated.",
    "The selected model and dependencies are matched to the completed live build and actual loader paths; fresh dependency compilation provenance remains unresolved.",
    "Tool hashes do not retain every compiler support file or system header; before/after hashes do not defeat malicious concurrent replacement.",
    "No complete counter qualification, absolute no-wrap bound, warm speedup, phase acceptance, RTL or physical-hardware result is claimed.",
]


def require(condition, message):
    if not condition:
        raise ValueError(message)


def bounded_json(path, *, expected=dict):
    require(path.is_file() and 0 < path.stat().st_size <= MAX_JSON_BYTES,
            "JSON input is absent or exceeds its byte bound")
    wrapper = load_json_bytes(b'{"value":' + path.read_bytes() + b'}', str(path.name))
    preflight_contract.fields(wrapper, ("value",), "bounded JSON wrapper")
    value = wrapper["value"]
    require(type(value) is expected, "JSON input has an unexpected container type")
    return value


def retained_json(directory, descriptor, expected, *, container=dict):
    preflight_contract.fields(descriptor, ("path", "sha256", "size_bytes"), "managed input identity")
    require(descriptor["path"] == expected, "managed snapshot path differs")
    require(hash_artifacts(directory, [expected]) == [descriptor], "managed snapshot identity differs")
    return bounded_json(directory / expected, expected=container)


def probe_flags(runtime, model, application, *, source, build, fmt):
    records = build_records.validate_records(runtime, model, application,
        fmt=fmt, source=source, build=build, jobs=2)
    words = _stamp_words(model, "pending probe model stamp")
    words = build_records._dependency_flags(words, build / "sw/runtime/simx_config.stamp")
    for flag in ("-MMD", "-MP"):
        require(words.count(flag) == 1, "pending probe dependency flags differ")
        words.remove(flag)
    return words, records


def verify_output(text, expected_libraries, *, zero_control=False):
    require(type(text) is str and 0 < len(text.encode("utf-8")) <= BUDGET["max_log_bytes"],
            "probe output is not bounded text")
    require("\r" not in text and "\x00" not in text and text.endswith("\n"),
            "probe output has noncanonical line data")
    lines = text.splitlines()
    libraries = []
    contexts = []
    for line in lines:
        if line.startswith("P06_PENDING_LIBRARY "):
            libraries.append(load_json_bytes(line[len("P06_PENDING_LIBRARY "):].encode(), "loader record"))
        elif line.startswith("P06_PENDING_CONTEXT "):
            contexts.append(load_json_bytes(line[len("P06_PENDING_CONTEXT "):].encode(), "context record"))
        elif line.startswith("P06_PENDING_"):
            raise ValueError("unknown pending probe record")
    require(libraries == [{"name": name, "path": expected_libraries[name]} for name in LIBRARIES],
            "probe loaded libraries differ from the completed managed build")
    failures = [line for line in lines if line.startswith("FAILED pending_reads")]
    passes = [line for line in lines if line.startswith("PASSED pending_reads")]
    controlled = [line for line in lines if line.startswith(
        ("P06_PENDING_", "PASSED pending_reads", "FAILED pending_reads"))]
    require(all(line.startswith("P06_PENDING_LIBRARY ") for line in controlled[:3]),
            "probe loader observations are missing or reordered")
    if zero_control:
        require(not contexts and not passes and failures == [ZERO_FAILURE],
                "always-zero probe did not fail at the required behavioral assertion")
        require(len(controlled) == 4 and controlled[-1] == ZERO_FAILURE,
                "always-zero probe record order differs")
        return {"expected_failure": ZERO_FAILURE, "loaded_libraries": libraries}
    require(not failures and passes == [PASS_LINE] and len(contexts) == 2,
            "native probe observations are incomplete or failed")
    require(len(controlled) == 6 and controlled[-1] == PASS_LINE
            and all(line.startswith("P06_PENDING_CONTEXT ") for line in controlled[3:5]),
            "native probe record order differs")
    names = ("gp", "steps", "positive_samples", "max_pending", "readonly_checks",
             "stepped_reset_delta", "checked_reset_delta", "pending_final", "checked_gp")
    for gp, row in zip((7, -1), contexts):
        preflight_contract.fields(row, names, "pending probe context")
        require(all(type(value) is int for value in row.values()), "probe fields must be exact integers")
        require(row["gp"] == row["checked_gp"] == gp, "legacy gp observation differs")
        require(1 <= row["positive_samples"] <= row["steps"] <= MAX_STEPS,
                "probe never observed a real outstanding read or exceeded its step bound")
        require(1 <= row["max_pending"] < (1 << 64), "maximum pending balance is invalid")
        require(row["readonly_checks"] == row["steps"] + 2
                and row["stepped_reset_delta"] == row["checked_reset_delta"] == 1
                and row["pending_final"] == 0, "probe state/read-only/reset observations differ")
    return {"contexts": contexts, "loaded_libraries": libraries}


def execute(args):
    source = base._path(args.source_dir, existing=True)
    build = base._path(args.build_dir, existing=True)
    output = base._path(args.output_dir)
    managed_path = base._path(args.managed_report, existing=True)
    require(source == ROOT and source.is_dir() and build.is_dir(), "selected source or build root differs")
    require(not base._overlap(source, build), "source and model build overlap")
    require(not output.exists() and output.parent.is_dir()
            and not any(base._overlap(output, path) for path in (source, build, managed_path)),
            "probe output must be fresh and separate from its inputs")
    require(re.fullmatch(r"[0-9a-f]{40}", args.expected_revision) is not None,
            "expected source revision is not an exact Git identity")
    host_bin = base._path(args.host_bin, existing=True) if args.host_bin else None
    require(host_bin is None or host_bin.is_dir(), "host compiler directory is invalid")
    output.mkdir(mode=0o700)
    for name in ("logs", "products", "inputs", "tmp"):
        (output / name).mkdir()
    report = {"schema_version": 1, "contract_id": CONTRACT_ID, "started_at": base._now(),
        "state": "running", "outcome": "blocked", "reason": None,
        "expected_revision": args.expected_revision, "native_execution": "not_run",
        "native_probe_passed": False, "zero_mutation_rejected": False,
        **dict.fromkeys(preflight_contract.FALSE_CLAIMS, False),
        "commands": [], "failures": [], "budget": BUDGET, "limitations": LIMITATIONS}
    initial = None
    snapshot = None

    def checkpoint():
        base._write_json(output / "report.json", report)

    def command(name, argv, *, native=False, negative=False):
        require(snapshot() == initial, "probe inputs changed before command")
        receipt = run_bounded(list(map(str, argv)), output, environment, output / "logs" / (name + ".log"),
            timeout_seconds=180 if native else 120, resource_paths=(source, build, managed_path.parent), **BUDGET)
        receipt.update(id=name, argv=list(map(str, argv)), cwd=str(output), log="logs/" + name + ".log")
        report["commands"].append(receipt)
        if native and receipt["process_started"] is True:
            report["native_execution"] = "run"
        checkpoint()
        require(receipt["cleanup_complete"] and receipt["process_started"] is True,
                name + ": command did not start or cleanup failed")
        if negative:
            require(receipt["outcome"] == "fail" and receipt["exit_code"] == 1
                    and receipt["reason"] == "nonzero_exit", name + ": expected failure outcome differs")
        else:
            require(receipt["outcome"] == "pass" and receipt["exit_code"] == 0,
                    name + ": command failed: " + str(receipt["reason"]))
        log = output / receipt["log"]
        require(_digest(log) == (receipt["log_sha256"], receipt["log_size_bytes"]),
                name + ": retained log changed")
        require(snapshot() == initial, "probe inputs changed during command")
        return log.read_text(encoding="utf-8")

    try:
        checkpoint()
        require(all(shutil.disk_usage(path).free >= BUDGET["min_free_bytes"]
                    for path in (source, build, output, managed_path.parent)), "probe needs 15 GiB disk reserve")
        require((available_memory_bytes() or 0) >= BUDGET["max_rss_bytes"], "probe needs 4 GiB available memory")
        managed = bounded_json(managed_path)
        require(managed.get("contract_id") == MANAGED_CONTRACT_ID
                and managed.get("state") == "finished" and managed.get("outcome") == "pass"
                and managed.get("native_lifetime_passed") is True
                and managed.get("native_preflight_passed") is True
                and managed.get("expected_revision") == args.expected_revision,
                "probe requires a completed managed lifetime build at the selected revision")
        preflight_contract.false_claims(managed)
        matches = [row for row in managed["variants"] if row["build_dir"] == str(build)]
        require(len(matches) == 1 and matches[0]["outcome"] == "pass", "selected managed build is absent or incomplete")
        variant = matches[0]
        require(variant["format"] in ("fp16", "bf16") and variant["backend"] == "simx",
                "selected managed build route differs")
        tools = retained_json(managed_path.parent, managed["tools_before"], "snapshots/tools-before.json")
        selected_source = retained_json(managed_path.parent, managed["source_before"], "snapshots/source-before.json")
        dependencies = retained_json(managed_path.parent, managed["dependencies_before"],
            "snapshots/dependencies-before.json", container=list)
        paths = ([str(host_bin)] if host_bin else []) + [str(Path(sys.executable).parent), "/usr/bin", "/bin"]
        environment = {"PATH": os.pathsep.join(dict.fromkeys(paths)), "LANG": "C", "LC_ALL": "C",
            "TZ": "UTC", "TMPDIR": str(output / "tmp"), "THREADS": "1", "CCACHE_DISABLE": "1",
            "OBJCACHE": "", "PYTHONDONTWRITEBYTECODE": "1", "PERF": "1"}
        compiler = shutil.which("g++", path=environment["PATH"])
        require(compiler is not None and base._file_identity(compiler) == tools["g++"],
                "independently selected compiler differs from the managed build")
        require(collect_source(source) == selected_source["checkout"]
                and selected_source["checkout"]["revision"] == args.expected_revision,
                "current source differs from the managed source checkout")
        base._source_ok(selected_source, False)
        require(hash_artifacts(source, [row["path"] for row in selected_source["files"]]) == selected_source["files"],
                "current source bytes differ from the managed build")
        build_names = preflight.artifacts(build)
        require(hash_artifacts(build, build_names) == variant["artifacts_after"] == variant["artifacts_before"],
                "model products or generated inputs differ from the managed build")
        require(hash_artifacts(source, base.DEPENDENCIES) == dependencies,
                "model dependencies differ from the managed build")
        runtime = build / "sw/runtime"
        flags, records = probe_flags((runtime / "simx_rt_config.stamp").read_text(),
            (runtime / "simx_config.stamp").read_text(),
            (build / preflight_contract.APP / "config.stamp").read_text(),
            source=source, build=build, fmt=variant["format"])
        require(records == variant["compiler_records"], "revalidated compiler records differ")
        expected_libraries = {name: variant["expected_loaded_libraries"][name] for name in LIBRARIES}
        fixed_libraries = {"libsimx.so": str(runtime / "libsimx.so"),
            "libramulator.so": str(source / "third_party/ramulator/libramulator.so"),
            "libramulator-vortex.so": str(source / "third_party/ramulator_ext/libramulator-vortex.so")}
        require(expected_libraries == fixed_libraries, "selected library paths differ from their fixed build route")
        environment["LD_LIBRARY_PATH"] = os.pathsep.join((str(runtime),
            str(source / "third_party/ramulator"), str(source / "third_party/ramulator_ext")))
        helpers = preflight.loaded_helpers()
        source_names = sorted(set(SOURCE_FILES) | {row["path"] for row in helpers}
                              | {row["path"] for row in selected_source["files"]})

        def snapshot():
            return {"checkout": collect_source(source), "sources": hash_artifacts(source, source_names),
                "build": hash_artifacts(build, build_names), "dependencies": hash_artifacts(source, base.DEPENDENCIES),
                "compiler": base._file_identity(compiler), "managed_report": base._file_identity(managed_path),
                "managed_snapshots": hash_artifacts(managed_path.parent,
                    ("snapshots/source-before.json", "snapshots/tools-before.json", "snapshots/dependencies-before.json"))}

        initial = snapshot()
        report.update(inputs_before=initial, format=variant["format"], compiler_records=records,
            probe_flags=flags, expected_libraries=expected_libraries, environment=environment,
            managed_build_binding_sha256=variant["build_binding_sha256"])
        for relative in sorted(set(SOURCE_FILES) | {row["path"] for row in helpers}):
            target = output / "inputs" / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes((source / relative).read_bytes())
        checkpoint()
        command("compiler-version", [compiler, "--version"])
        binaries = []
        for mode, defines in (("native", []), ("always-zero", ["-DP06_PENDING_FORCE_ZERO=1"])):
            binary = output / "products" / ("pending-reads-" + mode)
            command("compile-" + mode, [compiler, *flags, *defines, source / PROBE_SOURCE,
                "-L" + str(runtime), "-Wl,-rpath," + str(runtime), "-lsimx", "-pthread", "-ldl", "-o", binary])
            identity = base._file_identity(binary)
            text = command("run-" + mode, [binary], native=True, negative=mode == "always-zero")
            require(base._file_identity(binary) == identity, "probe executable changed during execution")
            observed = verify_output(text, expected_libraries, zero_control=mode == "always-zero")
            binaries.append(dict(identity, mode=mode, observation=observed))
            report["products"] = binaries
            report["native_probe_passed" if mode == "native" else "zero_mutation_rejected"] = True
            checkpoint()
        report["outcome"] = "pass"
    except (OSError, ValueError, RuntimeError, KeyError, TypeError) as error:
        report["outcome"] = "fail" if report["commands"] else "blocked"
        report["reason"] = str(error)
        report["failures"].append(str(error))
    finally:
        if initial is not None:
            try:
                report["inputs_after"] = snapshot()
                require(report["inputs_after"] == initial, "probe input stability failed")
            except (OSError, ValueError, RuntimeError) as error:
                report.update(outcome="fail", reason=report["reason"] or str(error))
                report["failures"].append(str(error))
        report["native_probe_passed"] = report["native_probe_passed"] and report["outcome"] == "pass"
        report.update(state="finished", finished_at=base._now())
        checkpoint()
    return report


def argument_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, default=ROOT)
    parser.add_argument("--build-dir", type=Path, required=True)
    parser.add_argument("--managed-report", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--expected-revision", required=True)
    parser.add_argument("--host-bin", type=Path)
    return parser


def main(argv=None):
    try:
        result = execute(argument_parser().parse_args(argv))
        print(json.dumps({name: result[name] for name in (
            "outcome", "reason", "native_execution", "native_probe_passed", "zero_mutation_rejected")}, sort_keys=True))
        return 0 if result["outcome"] == "pass" else 1
    except (OSError, ValueError, RuntimeError) as error:
        print(json.dumps({"outcome": "blocked", "reason": str(error), "native_probe_passed": False}))
        return 1


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Build and execute the fixed seed-free managed counter preflight.

The four fresh processes share one checked production build per format. This
runner retains commands, payloads and public-getter observations; success does not
qualify the complete counter lifetime or admit a performance experiment.
"""

from __future__ import annotations

import argparse
import importlib
import os
from pathlib import Path
import platform
import re
import shutil
import sys

sys.dont_write_bytecode = True

from baseline_inventory import _digest, hash_artifacts
from baseline_packet_contract import _stamp_flags, _stamp_words
from baseline_process import run_bounded
import p02_matrix as base
from p02_matrix_records import DISABLED, PROFILE_SHA256, require
from p02_wmma_fixtures import load_cases, render_header
import p03_execute as operator_run
from p03_execution_records import qualification_id
from p06_compiler_records import validate_header_macros
import p06_managed_preflight_build as build_records
import p06_managed_preflight_contract as manifest
import p06_warm_contract as warm_contract
from p06_warm_execute import validate_process_duration


ROOT = Path(__file__).resolve().parents[2]
APP = manifest.APP
CONTRACT_ID = manifest.CONTRACT_ID
FORMATS = manifest.FORMATS
BACKENDS = ("simx",)
HEADER_PROBE = "p06-managed-header-check/include-probe.cpp"
HEADER_PROBE_CONTENT = b"#include <VX_config.h>\n"
KERNEL_SHA256 = "ad3b6107f0eef91ec676412bc795ab70cd1c9f31647b2cea854de6234fe71d3e"
BUDGET = {name: manifest.BUDGET[name] for name in (
    "min_free_bytes", "max_rss_bytes", "max_log_bytes")}
COMPLETE_COUNTS = dict(manifest.COMPLETE_COUNTS)
MAX_PAYLOAD_BYTES = 256 * 1024**2
MAX_PAYLOAD_FILE_BYTES = 64 * 1024**2
SOURCE_FILES = tuple(sorted(set(manifest.MEASUREMENT_SOURCES) | set(build_records.REQUIRED_SOURCE_FILES) | {
    "ci/project/p06_managed_preflight_execute.py", "ci/project/p06_managed_preflight_build.py",
    "ci/project/p06_managed_preflight_contract.py", "ci/project/p06_managed_preflight_records.py",
    "ci/project/p06_warm_execute.py", "ci/project/p06_warm_records.py",
    "ci/project/p06_warm_compiler_records.py", "ci/project/p06_warm_contract.py",
    "ci/project/p06_warm_contract.json", "ci/project/p04_ci_prepare.py",
    ".github/workflows/p04-model.yml", ".github/workflows/p06-managed-preflight.yml",
    "ci/toolchain_rev.sh", "ci/install_dependencies.sh", "third_party/Makefile",
    "docs/designs/managed_counter_preflight_v1.md", "docs/designs/simx_counter_lifetime_v1.md",
    "docs/designs/warm_workspace_benchmark_v1.md", "docs/designs/serial_matmul_workspace_v1.md",
    "docs/designs/ai_operator_contract_v1.md", "docs/designs/tensor_numerics_v1.md",
}))
BINARY_FILES = (
    APP + "/ai_counter_preflight", APP + "/kernel.elf", APP + "/kernel.vxbin",
    "sw/kernel/libvortex2.a", "sw/runtime/libvortex.so", "sw/runtime/libvortex-simx.so",
    "sw/runtime/libsimx.so",
)
LIMITATIONS = [
    "Passing establishes only the fixed four-process seed-free managed counter preflight.",
    "Qualification, warm readiness, performance sampling and all phase acceptance remain false.",
    "All-40-component lifetime and pending-balance closure remain unresolved; sampled observations are not a complete lifetime proof.",
    "Actual selected loaded-library paths and retained payloads are checked; cached dependency source-to-binary compilation provenance remains unresolved.",
    "The unchanged inner warm records are excluded preflight observations, not a shortened valid warm performance experiment.",
    "Both policies share one source, guarded binary and fixed kernel per format; no replacement process or implicit retry is permitted.",
    "Production-model observational hooks are used; the public perf getter refreshes a derived aggregate, and immutable backing storage is not claimed. Seeded diagnostic objects and accessor replacements are excluded from the validated build inventory.",
    "Binary and selected dependency payloads are retained for inert rehashing, not execution by replay tooling.",
    "Tool and selected-library identities do not inventory every system header, compiler support file or loaded system library.",
    "Before/after identities do not defend against malicious concurrent filesystem writers or authenticate an untrusted producer.",
    "This is timing SimX execution, not processor RTL, vendor hardware emulation, FPGA or silicon measurement.",
    *base.PROCESS_LIMITATIONS,
]


def loaded_helpers():
    names = {Path(__file__).resolve().relative_to(ROOT).as_posix()}
    for module in tuple(sys.modules.values()):
        name = getattr(module, "__file__", None)
        if name and Path(name).suffix == ".py":
            path = Path(name).resolve()
            if path.is_relative_to(ROOT / "ci/project"):
                names.add(path.relative_to(ROOT).as_posix())
    return hash_artifacts(ROOT, sorted(names))


LOADED_HELPERS = loaded_helpers()


def source_snapshot(source, helpers=None, *, extra_source_files=()):
    snapshot = operator_run.source_snapshot(source)
    names = {item["path"] for item in snapshot["files"]} | set(SOURCE_FILES) | set(extra_source_files)
    names.update(item["path"] for item in snapshot["checkout"].get("inputs", []))
    names.update(item["path"] for item in (helpers if helpers is not None else LOADED_HELPERS))
    snapshot["files"] = hash_artifacts(source, sorted(names))
    return snapshot


def clean_environment(paths, jobs):
    environment = base.clean_environment(paths, jobs)
    environment["THREADS"] = "1"
    return environment


def tool_inventory(paths, environment):
    result = base.tool_inventory(paths, environment, BACKENDS)
    result["executing_python"] = base._file_identity(sys.executable)
    return result


def interpreter_identity(tools):
    observed = {"version": list(sys.version_info[:3]), "implementation": platform.python_implementation(),
                "platform": sys.platform}
    require(observed == {"version": [3, 12, 14], "implementation": "CPython", "platform": "linux"},
            "managed preflight requires executing CPython 3.12.14 on Linux")
    first, second = tools["python3"], tools["executing_python"]
    require(all(first[key] == second[key] for key in ("resolved_path", "sha256", "size_bytes")),
            "PATH python3 differs from the actual executing interpreter")
    return observed


def artifacts(build, *, dependency=False):
    require(type(dependency) is bool, "dependency artifact mode must be explicitly boolean")
    objects = tuple(build_records.expected_object(name, build).relative_to(build).as_posix()
                    for name in build_records.MODEL_SOURCES)
    additional = (APP + "/dependency_model.mk", "sw/runtime/dependency-model.map") if dependency else ()
    return tuple(sorted(set(base.GENERATED + base.COPIED + BINARY_FILES + objects + additional + (
        APP + "/Makefile", APP + "/backend.mk", APP + "/config.stamp", HEADER_PROBE,
        "sw/runtime/simx_rt_config.stamp", "sw/runtime/simx_config.stamp",
        build_records.BACKEND_LINK_STAMP))))


def expected_libraries(source, build):
    paths = {name: str(build / "sw/runtime" / name) for name in (
        "libvortex.so", "libvortex-simx.so", "libsimx.so")}
    paths.update({"libramulator.so": str(source / "third_party/ramulator/libramulator.so"),
                  "libramulator-vortex.so": str(source / "third_party/ramulator_ext/libramulator-vortex.so")})
    manifest.validate_loaded_libraries([{"name": name, "path": paths[name]}
                                        for name in manifest.LOADED_LIBRARY_NAMES], paths)
    for path in paths.values():
        require(base._path(path, existing=True) == Path(path) and Path(path).is_file(),
                "selected loaded library is not a regular file at its exact path")
    return paths


def effective_header_command(compiler, build, record):
    directories = {"runtime": build / "sw/runtime/simx", "backend_cpp": build / "sim/simx",
                   "kernel": build / APP, "host": build / APP}
    require(record["role"] in directories, "unknown managed compiler role")
    return ([compiler, "-E", "-dM", "-x", "c++", *record["macro_flags"],
             *("-I" + name for name in record["include_paths"]), build / HEADER_PROBE],
            directories[record["role"]])


def completion_counts(processes):
    counts = dict.fromkeys(COMPLETE_COUNTS, 0)
    for process in processes:
        if process["outcome"] != "pass":
            continue
        observed = process["observation"]
        warm, witness = observed["warm"], observed["witness"]
        counts["processes"] += 1
        counts["launches"] += sum(row["dispatch"]["launches"] for row in warm["operations"])
        counts["checked_words"] += sum(row["checked"] for row in warm["operations"])
        counts["snapshots"] += len(witness["snapshots"])
        counts["half_replies"] += len(witness["reads"])
        counts["cache_flush_reads"] += len(witness["cache_flush_reads"])
        counts["dcr_reads"] += witness["observation"]["dcr_read_completed"]
        for snapshot in warm["summary"]["snapshots"].values():
            counts["available_queries"] += sum(row["enabled"] is True for row in snapshot["counters"])
            counts["unavailable_rows"] += sum(row["enabled"] is False for row in snapshot["counters"])
    return counts


def native_execution_state(previous, process_started):
    """Preserve uncertainty when supervision supplies no reliable start receipt."""
    require(previous in ("not_run", "run", "unknown"), "invalid native execution state")
    require(process_started is None or type(process_started) is bool,
            "native process-start observation must be boolean or unknown")
    if previous == "run" or process_started is True:
        return "run"
    if process_started is False:
        return previous
    return "unknown"


def validate_host_build(text, stamp, *, source, build, compiler):
    lines = stamp.splitlines()
    require(len(lines) == 3, "application lacks original kernel/host/linker stamps")
    flags = _stamp_words(lines[1], "managed original host flags")
    linker = _stamp_words(lines[2], "managed original host linker")
    target = "ai_counter_preflight"
    selected = []
    for line in text.splitlines():
        words = _stamp_words(line, "managed application build line")
        if "-o" in words and words[-1:] == [target]:
            selected.append(words)
    expected = [compiler, *flags, *(str(source / name) for name in build_records.APP_SOURCES),
                str(build / "sw/runtime/libvortex.so"), *linker, "-o", target]
    require(selected == [expected], "application build changes its exact host source and runtime link")
    return {"compiler": compiler, "source_files": list(build_records.APP_SOURCES),
            "arguments": selected[0], "output": APP + "/" + target}


def execute(args, paths, *, lifetime=False, dependency=False):
    require(type(lifetime) is bool, "lifetime mode must be explicitly boolean")
    require(type(dependency) is bool and (not dependency or lifetime),
            "dependency admission requires explicitly selected lifetime mode")
    selected_contract = None
    dependency_module = None
    contract_id = CONTRACT_ID
    scope = "seed-free-managed-counter-preflight"
    limitations = LIMITATIONS
    extra_source_files = ()
    if lifetime:
        selected_contract = importlib.import_module("p06_native_lifetime_contract")
        require(Path(selected_contract.__file__).resolve() == ROOT / "ci/project/p06_native_lifetime_contract.py",
                "lifetime contract loaded from an unexpected location")
        contract_id = selected_contract.CONTRACT_ID
        scope = selected_contract.SCOPE
        limitations = [*LIMITATIONS, *selected_contract.LIMITATIONS]
        extra_source_files = selected_contract.SOURCE_FILES
    if dependency:
        dependency_module = importlib.import_module("p06_dependency_admission")
        require(Path(dependency_module.__file__).resolve() == ROOT / "ci/project/p06_dependency_admission.py",
                "dependency admission loaded from an unexpected location")
        contract_id = dependency_module.CONTRACT_ID
        scope = dependency_module.SCOPE
        limitations = [*dependency_module.LIMITATIONS, *base.PROCESS_LIMITATIONS]
        extra_source_files = (*extra_source_files, *dependency_module.SOURCE_FILES)
    source, work, output = (paths[name] for name in ("source", "work", "output"))
    output.mkdir(mode=0o700)
    for name in ("logs", "snapshots", "artifacts"):
        (output / name).mkdir()
    environment = clean_environment(paths, args.jobs)
    report = {"schema_version": 1, "contract_id": contract_id,
        "scope": scope, "started_at": base._now(),
        "state": "running", "outcome": "blocked", "reason": None,
        **dict.fromkeys(manifest.FALSE_CLAIMS, False),
        "native_preflight_passed": False, "native_execution": "not_run",
        "unresolved_obligations": list(manifest.UNRESOLVED_OBLIGATIONS),
        "expected_revision": args.expected_revision, "expected_counts": COMPLETE_COUNTS,
        "completed_counts": dict.fromkeys(COMPLETE_COUNTS, 0),
        "commands": [], "variants": [], "processes": [], "failures": [], "stability_checks": [],
        "budget": dict(manifest.BUDGET, jobs=args.jobs,
                       timeouts_seconds={"configure": min(120, args.timeout_seconds),
                                         "build": args.timeout_seconds, "run": args.run_timeout_seconds}),
        "payload_limits": {"per_file_bytes": MAX_PAYLOAD_FILE_BYTES, "total_bytes": MAX_PAYLOAD_BYTES},
        "paths": {name: str(value) if value is not None else None for name, value in paths.items()},
        "environment": environment, "limitations": limitations}
    if lifetime:
        report["native_lifetime_passed"] = False
    if dependency:
        report.update(dependency_receipt_sha256=getattr(args, "dependency_receipt_sha256", None),
                      dependency_admission=None, dependency_source_to_loaded_binary_verified=False)
    initial = tools = dependencies = helpers = None
    admission = None
    active_variant = active_process = None
    retained = []
    payload_bytes = 0

    def build_artifacts(build):
        return artifacts(build, dependency=True) if dependency else artifacts(build)

    def snapshot_source():
        if lifetime:
            return source_snapshot(source, helpers, extra_source_files=extra_source_files)
        return source_snapshot(source, helpers)

    def checkpoint():
        base._write_json(output / "report.json", report)

    def save_json(name, value):
        relative = "snapshots/" + name + ".json"
        require(not (output / relative).exists(), "retained JSON snapshot already exists")
        base._write_json(output / relative, value)
        identity = hash_artifacts(output, [relative])[0]
        retained.append(identity)
        return identity

    def failure(error, stage="execution"):
        reason = str(error) or "interrupted"
        report["failures"].append({"stage": stage, "reason": reason, "at": base._now(),
            "variant_id": active_variant["id"] if active_variant else None,
            "process_id": active_process["id"] if active_process else None})
        report["outcome"] = "fail" if any(row.get("process_started") for row in report["commands"]) else "blocked"
        if report["reason"] is None:
            report["reason"] = reason
        for row in (active_process, active_variant):
            if row is not None and row["outcome"] == "running":
                row.update(outcome="fail", reason=reason)

    def retain_files(root, identities, prefix, *, payload=False):
        nonlocal payload_bytes
        copied = []
        for item in identities:
            if payload:
                require(0 < item["size_bytes"] <= MAX_PAYLOAD_FILE_BYTES,
                        "binary payload exceeds the per-file bound or is empty")
                require(payload_bytes + item["size_bytes"] <= MAX_PAYLOAD_BYTES,
                        "binary payload inventory exceeds its total bound")
            relative = "artifacts/" + prefix + "/" + item["path"]
            target = output / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            with (root / item["path"]).open("rb") as original, target.open("xb") as destination:
                shutil.copyfileobj(original, destination, length=1024 * 1024)
            actual = hash_artifacts(output, [relative])[0]
            require((actual["sha256"], actual["size_bytes"]) == (item["sha256"], item["size_bytes"]),
                    "input changed while its evidence bytes were retained: " + item["path"])
            retained.append(actual)
            copied.append(actual)
            if payload:
                payload_bytes += actual["size_bytes"]
        return copied

    def verify_log(row):
        path = output / row["log"]
        if row.get("log_sha256") is None:
            require(row.get("process_started") is not True and not path.exists(),
                    "started command lacks a bound original log: " + row["id"])
            return None
        digest, size = _digest(path)
        require(digest == row["log_sha256"] and size == row["log_size_bytes"] <= BUDGET["max_log_bytes"],
                "original command log changed: " + row["id"])
        return {"path": row["log"], "sha256": digest, "size_bytes": size}

    def stable(label):
        require(hash_artifacts(source, [row["path"] for row in helpers]) == helpers,
                "loaded helper bytes changed after import")
        observed_source, observed_tools = snapshot_source(), tool_inventory(paths, environment)
        observed_dependencies = hash_artifacts(source, base.DEPENDENCIES)
        require(observed_source == initial, "source changed during execution")
        require(observed_tools == tools, "tool or executing-interpreter identity changed")
        require(observed_dependencies == dependencies, "dependency payload changed")
        check = {"label": label, "at": base._now(),
            "source_sha256": qualification_id(observed_source), "tools_sha256": qualification_id(observed_tools),
            "dependencies_sha256": qualification_id(observed_dependencies)}
        if dependency:
            check["dependency_admission"] = admission.verify_stable(observed_tools)
            for variant in report["variants"]:
                if "dependency_model_link" in variant:
                    admission.verify_model_stable(variant["dependency_model_link"])
        report["stability_checks"].append(check)

    def command(name, argv, cwd, env, timeout, *, native_process=False):
        require(not any(row["id"] == name for row in report["commands"]), "duplicate command identity")
        stable("before-command-" + name)
        row = {"id": name, "argv": list(map(str, argv)), "cwd": str(cwd), "environment": dict(env),
               "timeout_seconds": timeout, "log": "logs/" + name + ".log", "outcome": "running",
               "native_process": native_process, "process_started": None}
        report["commands"].append(row)
        previous_native_execution = report["native_execution"]
        if native_process:
            report["native_execution"] = native_execution_state(previous_native_execution, None)
        checkpoint()
        try:
            row.update(run_bounded(row["argv"], cwd, env, output / row["log"], timeout_seconds=timeout,
                **BUDGET, resource_paths=(source, paths["tools"], work, output)))
        except (OSError, ValueError, RuntimeError, KeyboardInterrupt) as error:
            row.update(outcome="fail", reason=str(error) or "interrupted")
            try:
                if (output / row["log"]).is_file():
                    digest, size = _digest(output / row["log"])
                    row.update(log_sha256=digest, log_size_bytes=size)
            except (OSError, ValueError, RuntimeError) as log_error:
                row["log_identity_error"] = str(log_error)
            checkpoint()
            raise
        if native_process:
            report["native_execution"] = native_execution_state(previous_native_execution, row.get("process_started"))
        checkpoint()
        verify_log(row)
        require(row.get("process_started") is True and row["outcome"] == "pass"
                and type(row.get("exit_code")) is int and row["exit_code"] == 0
                and row.get("cleanup_complete") is True and row.get("reason") is None,
                "command failed: " + name + ": " + str(row.get("reason")))
        stable("after-command-" + name)
        checkpoint()
        return (output / row["log"]).read_text(encoding="utf-8", errors="strict"), row

    def retain_build(variant, build, stage):
        names = [name for name in build_artifacts(build)
                 if (Path(name).suffix in (".stamp", ".mk", ".h", ".vh", ".vlt", ".py")
                     or Path(name).name == "Makefile" or name == HEADER_PROBE)
                 and (build / name).is_file()]
        variant.setdefault("retained_builds", []).append({"stage": stage,
            "files": retain_files(build, hash_artifacts(build, names), variant["id"] + "/" + stage)})

    checkpoint()
    try:
        require(type(args.jobs) is int and args.jobs in (1, 2), "build jobs exceed the two-job budget")
        require(type(args.timeout_seconds) is int and 1 <= args.timeout_seconds <= 1800,
                "build timeout exceeds the fixed budget")
        require(type(args.run_timeout_seconds) is int and 1 <= args.run_timeout_seconds <= 180,
                "invocation timeout exceeds the fixed budget")
        require(type(args.expected_revision) is str and re.fullmatch(r"[0-9a-f]{40}", args.expected_revision),
                "an exact lowercase expected source revision is required")
        work.mkdir(mode=0o700)
        for name in ("tmp", "home"):
            (work / name).mkdir()
        report["resources_before"] = base._resources(paths)
        require(all(value >= BUDGET["min_free_bytes"] for value in report["resources_before"]["free_disk_bytes"].values()),
                "disk reserve below 15 GiB")
        memory = report["resources_before"]["available_memory_bytes"]
        require(memory is not None and memory >= BUDGET["max_rss_bytes"], "need 4 GiB available RAM")
        require(hash_artifacts(source, [row["path"] for row in LOADED_HELPERS]) == LOADED_HELPERS,
                "runner/helper bytes changed after initial import")
        records_name = "p06_native_lifetime_records" if lifetime else "p06_managed_preflight_records"
        records = importlib.import_module(records_name)
        require(Path(records.__file__).resolve() == ROOT / "ci/project" / (records_name + ".py"),
                "managed record validator loaded from an unexpected location")
        if dependency:
            admission = dependency_module.Admission(getattr(args, "dependency_receipt", None),
                getattr(args, "dependency_receipt_sha256", None), source=source,
                expected_revision=args.expected_revision)
            report["dependency_admission"] = admission.summary
            report["retained_dependency_receipt"] = retain_files(admission.path.parent,
                hash_artifacts(admission.path.parent, [admission.path.name]), "dependency-receipt")[0]
        helpers = loaded_helpers()
        report["loaded_helpers"] = helpers
        initial = snapshot_source()
        report["source_before"] = save_json("source-before", initial)
        base._source_ok(initial, False)
        require(initial["checkout"]["revision"] == args.expected_revision, "source differs from the expected revision")
        contract = manifest.load_contract(source)
        old_contract = warm_contract.load_contract(source)
        cases = manifest.select_cases(contract, source)
        plan = manifest.process_plan(contract, source)
        require([case["format"] for case in cases] == list(FORMATS), "both ordered formats are required")
        require(_digest(source / "profiles/p02-tfr.json")[0] == PROFILE_SHA256, "frozen profile changed")
        require(_digest(source / "sw/kernel/ai/matmul.cpp")[0] == KERNEL_SHA256, "frozen numerical kernel changed")
        require((source / "tests/regression/sgemm_tcu/p02_fixtures.h").read_bytes() == render_header(load_cases(source)),
                "frozen fixture header differs from its independent producer")
        if lifetime:
            active_contract = selected_contract.contract()
            lifetime_contract = active_contract
            active_contract_sha256 = selected_contract.contract_hash()
            require(qualification_id(active_contract) == active_contract_sha256,
                    "lifetime contract descriptor and digest differ")
            report.update(preflight_contract_snapshot=save_json("preflight-contract", contract),
                          preflight_contract_sha256=qualification_id(contract))
        else:
            active_contract, active_contract_sha256 = contract, qualification_id(contract)
        if dependency:
            active_contract, active_contract_sha256 = dependency_module.contract(), dependency_module.contract_hash()
            require(qualification_id(active_contract) == active_contract_sha256,
                    "dependency admission contract descriptor and digest differ")
        report.update(contract_snapshot=save_json("contract", active_contract), contract_sha256=active_contract_sha256,
            fixture_snapshot=save_json("selected-fixtures", cases), expected_processes=plan,
            profile_sha256=PROFILE_SHA256, kernel_source_sha256=KERNEL_SHA256,
            warm_contract_sha256=manifest.WARM_CONTRACT_SHA256, corpus=hash_artifacts(source, base.CORPUS))
        report["retained_sources"] = retain_files(source, initial["files"], "source")
        tools = tool_inventory(paths, environment)
        if dependency:
            report["dependency_admission_before"] = admission.verify_stable(tools)
        report["interpreter"] = interpreter_identity(tools)
        report["tools_before"] = save_json("tools-before", tools)
        dependencies = hash_artifacts(source, base.DEPENDENCIES)
        report["dependencies_before"] = save_json("dependencies-before", dependencies)
        report["retained_dependency_payloads"] = retain_files(source, dependencies, "dependencies", payload=True)
        for name in ("g++", "gcc", "make", "python3", "executing_python", "clang", "riscv-gcc"):
            command("version-" + name.replace("+", "p"), [tools[name]["path"], "--version"], work, environment, 30)
        for fmt in FORMATS:
            variant_id = "simx-" + fmt
            build = work / variant_id
            build.mkdir()
            variant = {"id": variant_id, "backend": "simx", "format": fmt, "build_dir": str(build),
                       "outcome": "running", "process_ids": [], "effective_headers": {}}
            active_variant = variant
            report["variants"].append(variant)
            command(variant_id + "-configure", [source / "configure", "--xlen=64", "--profile=p02-tfr",
                "--osversion=ubuntu/focal", "--tooldir=" + str(paths["tools"])], build, environment,
                min(120, args.timeout_seconds))
            variant["generated_identity"] = base._generated_identity(build, source, paths["tools"])
            copied_build_files = (APP + "/Makefile", APP + "/backend.mk")
            if dependency:
                copied_build_files += (dependency_module.MODEL_MAKEFILE,)
            for name in copied_build_files:
                require((build / name).read_bytes() == (source / name).read_bytes(), "copied preflight build file differs: " + name)
            require(not (build / "sw/runtime/obj").exists()
                    and not any((build / name).exists() for name in BINARY_FILES), "preflight build is not fresh")
            retain_build(variant, build, "configured")
            probe = build / HEADER_PROBE
            probe.parent.mkdir()
            probe.write_bytes(HEADER_PROBE_CONTENT)
            header, _ = command(variant_id + "-header", [tools["g++"]["path"], "-E", "-dM", "-x", "c++",
                "-DVX_CFG_XLEN=64", "-DVX_CFG_XLEN_64", "-include", build / "sw/VX_config.h", "/dev/null"],
                build, environment, 30)
            variant["header_macros"] = validate_header_macros(header)
            for language, relative in (("cpp", "sw/VX_config.h"), ("verilog", "hw/VX_config.vh")):
                destination = probe.parent / Path(relative).name
                command(variant_id + "-" + language + "-header-reproduce", [tools["python3"]["path"],
                    source / "ci/gen_config.py", "--config=" + str(source / "VX_config.toml"),
                    "--profile=p02-tfr", "--format=" + language, "--output=" + str(destination)],
                    build, dict(environment, XLEN="64"), 30)
                require(destination.read_bytes() == (build / relative).read_bytes(), "generated header did not reproduce")
            raw_flags = f"-DITYPE={fmt} -DOTYPE=fp32 -DKUNROLL=1"
            config_flags = raw_flags + " " + build_records.GUARD_FLAG
            expanded, _ = command(variant_id + "-expected-flags", [tools["python3"]["path"],
                source / "ci/gen_config.py", "--config=" + str(source / "VX_config.toml"),
                "--profile=p02-tfr", "--xlen=64", "--format=cflags", "--cflags=" + raw_flags + " -DVX_CFG_XLEN=64"],
                build, environment, 30)
            flags = _stamp_flags(expanded, "independently generated preflight flags")
            require(flags and all(flag.startswith("-D") for flag in flags), "generated flags contain non-definitions")
            header, _ = command(variant_id + "-expected-expanded-header", [tools["g++"]["path"], "-E", "-dM", "-x", "c++",
                *flags, *("-D" + name + "_DISABLE" for name in DISABLED), "-include", build / "sw/VX_config.h", "/dev/null"],
                build, environment, 30)
            variant["expected_expanded_header_macros"] = dict(validate_header_macros(header), **{build_records.GUARD: "1"})
            variant["expected_backend_header_macros"] = dict(variant["header_macros"], PERF_ENABLE="1", **{
                name + "_DISABLE": "1" for name in DISABLED}, **{build_records.GUARD: "1"})
            make = [tools["make"]["path"], "--no-print-directory", "-j" + str(args.jobs), "THREADS=1",
                    "CXX=" + tools["g++"]["path"]]
            current = dict(environment, CONFIGS=config_flags, PERF="1")
            runtime = build / "sw/runtime"
            if dependency:
                model_text, model_command = command(variant_id + "-dependency-model",
                    [*make, "CC=" + tools["gcc"]["path"], "DESTDIR=" + str(runtime),
                     "-f", build / dependency_module.MODEL_MAKEFILE, runtime / "libsimx.so"],
                    build / "sim/simx", current, args.timeout_seconds)
                variant["dependency_model_build_command"] = model_command["id"]
                model_outputs = hash_artifacts(build, ["sw/runtime/libsimx.so", dependency_module.MODEL_MAP])
            backend_text, backend_command = command(variant_id + "-backend", [*make, "CC=" + tools["gcc"]["path"],
                "DESTDIR=" + str(runtime), "-f", build / APP / "backend.mk", runtime / "libvortex-simx.so"],
                build / "sw/runtime/simx", current, args.timeout_seconds)
            retain_build(variant, build, "backend")
            runtime_stamp = (runtime / "simx_rt_config.stamp").read_text(encoding="utf-8")
            model_stamp = (runtime / "simx_config.stamp").read_text(encoding="utf-8")
            link_stamp = (build / build_records.BACKEND_LINK_STAMP).read_text(encoding="utf-8")
            build_options = {}
            if dependency:
                require(hash_artifacts(build, ["sw/runtime/libsimx.so", dependency_module.MODEL_MAP]) == model_outputs,
                        "backend build changed the separately admitted model or link map")
                backend_text = model_text + "\n" + backend_text
                build_options["dependency_map"] = str(build / dependency_module.MODEL_MAP)
            variant["model_build_records"] = build_records.validate_build_commands(backend_text,
                runtime_stamp, model_stamp, link_stamp, source=source, build=build,
                compiler=tools["g++"]["path"], make=tools["make"]["path"], fmt=fmt,
                source_files=[item["path"] for item in initial["files"]], **build_options)
            if dependency:
                variant["dependency_receipt_sha256"] = report["dependency_receipt_sha256"]
                variant["dependency_model_link"] = admission.validate_model(build, variant["model_build_records"])
            variant["backend_build_command"] = backend_command["id"]
            app = build / APP
            # The kernel-library sub-make selects its pinned RISC-V C compiler.
            # A host CC command-line override would propagate into that build.
            # Preserve complete original command lines from parallel sub-makes.
            application_text, app_command = command(variant_id + "-application", [*make, "--output-sync=target", "all"],
                app, current, args.timeout_seconds)
            app_stamp = (app / "config.stamp").read_text(encoding="utf-8")
            variant["host_build_records"] = validate_host_build(application_text, app_stamp,
                source=source, build=build, compiler=tools["g++"]["path"])
            variant["application_build_command"] = app_command["id"]
            variant["compiler_records"] = build_records.validate_records(runtime_stamp, model_stamp, app_stamp,
                fmt=fmt, source=source, build=build, jobs=args.jobs)
            if dependency:
                variant["application_build_records"] = admission.validate_application(application_text, app_stamp,
                    build=build, tools_root=paths["tools"], tools=tools, fmt=fmt,
                    compiler_records=variant["compiler_records"], source_files=initial["files"])
            for record in variant["compiler_records"]:
                role = record["role"]
                argv, directory = effective_header_command(tools["g++"]["path"], build, record)
                text, _ = command(variant_id + "-" + role + "-header", argv, directory, environment, 30)
                expected = variant["expected_backend_header_macros"] if role == "backend_cpp" else variant["expected_expanded_header_macros"]
                variant["effective_headers"][role] = {"command_id": variant_id + "-" + role + "-header",
                    "macros": build_records.validate_effective_header(text, expected, role=role)}
            require(os.access(app / "ai_counter_preflight", os.X_OK), "preflight application is not executable")
            frozen = hash_artifacts(build, build_artifacts(build))
            variant["artifacts_before"] = frozen
            retain_build(variant, build, "frozen")
            variant["retained_binary_payloads"] = retain_files(build, hash_artifacts(build, BINARY_FILES),
                variant_id + "/binaries", payload=True)
            if dependency:
                model_payloads = [build_records.expected_object(name, build).relative_to(build).as_posix()
                                  for name in build_records.MODEL_SOURCES]
                model_payloads.append(dependency_module.MODEL_MAP)
                variant["retained_dependency_model_payloads"] = retain_files(build,
                    hash_artifacts(build, model_payloads), variant_id + "/dependency-model", payload=True)
            libraries = expected_libraries(source, build)
            variant["expected_loaded_libraries"] = libraries
            case = next(row for row in cases if row["format"] == fmt)
            binding = {"contract_id": contract_id, "contract_sha256": report["contract_sha256"],
                "source": initial, "loaded_helpers": helpers, "format": fmt, "backend": "simx", "case": case,
                "corpus": report["corpus"], "profile_sha256": PROFILE_SHA256, "kernel_source_sha256": KERNEL_SHA256,
                "warm_contract_sha256": manifest.WARM_CONTRACT_SHA256,
                "compiler_records": variant["compiler_records"], "model_build_records": variant["model_build_records"],
                "host_build_records": variant["host_build_records"], "effective_headers": variant["effective_headers"],
                "generated_identity": variant["generated_identity"], "artifacts": frozen,
                "tools": tools, "dependencies": dependencies, "expected_loaded_libraries": libraries,
                "simulation_workers": 1, "performance_environment": {"PERF": "1"},
                "unresolved_obligations": list(manifest.UNRESOLVED_OBLIGATIONS),
                **dict.fromkeys(manifest.FALSE_CLAIMS, False)}
            if lifetime:
                binding.update(lifetime_contract=lifetime_contract,
                               preflight_contract_sha256=report["preflight_contract_sha256"])
            if dependency:
                binding.update(dependency_receipt_sha256=report["dependency_receipt_sha256"],
                    dependency_admission=admission.summary,
                    application_build_records=variant["application_build_records"],
                    dependency_model_link=variant["dependency_model_link"])
            build_id = qualification_id(binding)
            variant.update(build_binding_sha256=build_id, binding=save_json(variant_id + "-build-binding", binding))
            launch_env = dict(environment, VORTEX_DRIVER="simx", LD_LIBRARY_PATH=str(runtime))
            for planned in (row for row in plan if row["format"] == fmt):
                process = dict(planned, command_id=planned["id"], outcome="running")
                active_process = process
                report["processes"].append(process)
                variant["process_ids"].append(process["id"])
                process_binding = {"contract_id": contract_id, "contract_sha256": report["contract_sha256"],
                    "build_binding_sha256": build_id, "build": binding, "process": planned}
                if lifetime:
                    process_binding.update(lifetime_contract=lifetime_contract,
                                           preflight_contract_sha256=report["preflight_contract_sha256"])
                if dependency:
                    process_binding["dependency_receipt_sha256"] = report["dependency_receipt_sha256"]
                binding_id = qualification_id(process_binding)
                process.update(execution_binding_sha256=binding_id, build_binding_sha256=build_id,
                               binding=save_json(process["id"] + "-binding", process_binding))
                require(hash_artifacts(build, build_artifacts(build)) == frozen, "artifacts changed before process")
                mode_arguments = [selected_contract.APP_FLAG] if lifetime else []
                text, receipt = command(process["id"], [app / "ai_counter_preflight", *mode_arguments, "--policy", planned["policy"],
                    "--module", app / "kernel.vxbin", "--qualification-id", binding_id,
                    "--sample-id", planned["sample_id"], "--pair-index", "0", "--phase", "warmup"],
                    app, launch_env, args.run_timeout_seconds, native_process=True)
                process["log"] = receipt["log"]
                process["process_duration_seconds"] = receipt["duration_seconds"]
                require(hash_artifacts(build, build_artifacts(build)) == frozen, "artifacts changed during process")
                observed = records.verify_output(text, contract=contract, case=case, fmt=fmt,
                    policy=planned["policy"], binding_id=binding_id, sample_id=planned["sample_id"],
                    process_id=planned["id"], expected_libraries=libraries)
                validate_process_duration(observed["warm"], receipt["duration_seconds"], old_contract)
                process["observation"] = observed
                process["retained_observation"] = save_json(process["id"] + "-observation", observed)
                stable("after-process-" + process["id"])
                process["outcome"] = "pass"
                active_process = None
                checkpoint()
            variant["artifacts_after"] = hash_artifacts(build, build_artifacts(build))
            require(variant["artifacts_after"] == frozen, "variant artifacts changed after both policies")
            stable("after-variant-" + variant_id)
            variant["outcome"] = "pass"
            active_variant = None
            checkpoint()
        require([row["id"] for row in report["processes"]] == [row["id"] for row in plan],
                "preflight process inventory is incomplete or reordered")
        require(completion_counts(report["processes"]) == COMPLETE_COUNTS, "managed preflight counts are incomplete")
        report["outcome"] = "pass"
    except (OSError, ValueError, RuntimeError, KeyError, ImportError, TypeError) as error:
        failure(error)
    except KeyboardInterrupt:
        failure("interrupted")
    finally:
        if active_variant is not None:
            try:
                retain_build(active_variant, work / active_variant["id"], "failure")
            except (OSError, ValueError, RuntimeError) as error:
                failure(error, "final-build-snapshot")
        for label, previous, observe in (
            ("source", initial, snapshot_source),
            ("tools", tools, lambda: tool_inventory(paths, environment)),
            ("dependencies", dependencies, lambda: hash_artifacts(source, base.DEPENDENCIES)),
        ):
            if previous is not None:
                try:
                    final = observe()
                    report[label + "_after"] = save_json(label + "-after", final)
                    report[label + "_stable"] = previous == final
                    require(previous == final, label + " changed in final observation")
                except (OSError, ValueError, RuntimeError) as error:
                    failure(error, "final-" + label)
        for variant in report["variants"]:
            if "artifacts_before" in variant:
                try:
                    variant["artifacts_after"] = hash_artifacts(work / variant["id"], build_artifacts(work / variant["id"]))
                    require(variant["artifacts_after"] == variant["artifacts_before"], "frozen build changed before finalization")
                except (OSError, ValueError, RuntimeError) as error:
                    failure(error, "final-artifacts-" + variant["id"])
        if admission is not None:
            try:
                report["dependency_admission_after"] = admission.verify_stable(tools)
                for variant in report["variants"]:
                    if "dependency_model_link" in variant:
                        admission.verify_model_stable(variant["dependency_model_link"])
                require(report["dependency_admission_after"] == report.get("dependency_admission_before"),
                        "dependency admission changed before finalization")
            except (OSError, ValueError, RuntimeError, KeyError, TypeError) as error:
                failure(error, "final-dependency-admission")
        report["raw_logs"] = []
        for row in report["commands"]:
            try:
                identity = verify_log(row)
                if identity is not None:
                    report["raw_logs"].append(identity)
            except (OSError, ValueError, RuntimeError) as error:
                failure(error, "final-log-verification")
        try:
            report["retained_files_stable"] = hash_artifacts(output, [row["path"] for row in retained]) == retained
            require(report["retained_files_stable"], "retained evidence or binary payload changed")
        except (OSError, ValueError, RuntimeError) as error:
            failure(error, "final-retained-evidence")
        try:
            report["resources_after"] = base._resources(paths)
            if report["commands"]:
                require(all(value >= BUDGET["min_free_bytes"] for value in report["resources_after"]["free_disk_bytes"].values()),
                        "final disk reserve below 15 GiB")
        except (OSError, ValueError, RuntimeError) as error:
            failure(error, "final-resources")
        report["completed_counts"] = completion_counts(report["processes"])
        report["native_preflight_passed"] = report["outcome"] == "pass" and report["completed_counts"] == COMPLETE_COUNTS
        if lifetime:
            report["native_lifetime_passed"] = report["native_preflight_passed"]
        if dependency:
            report["dependency_source_to_loaded_binary_verified"] = (
                report["native_lifetime_passed"] and admission is not None
                and len(report["variants"]) == len(FORMATS)
                and all(row["outcome"] == "pass" and "application_build_records" in row
                        and row.get("dependency_model_link", {}).get("source_to_model_link_verified") is True
                        and row.get("dependency_receipt_sha256") == report["dependency_receipt_sha256"]
                        for row in report["variants"]))
        report["retained_files"] = retained
        report["retained_payload_bytes"] = payload_bytes
        report.update(state="finished", finished_at=base._now())
        checkpoint()
    return report


def _run_timeout(value):
    result = base._timeout(value)
    if result > 180:
        raise argparse.ArgumentTypeError("process timeout must be between 1 and 180 seconds")
    return result


def argument_parser():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("mode", choices=("run",))
    parser.add_argument("--source-dir", type=Path, default=ROOT)
    parser.add_argument("--tools-dir", type=Path, required=True)
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--output-dir", "--output", dest="output", type=Path, required=True)
    parser.add_argument("--host-bin", type=Path)
    parser.add_argument("--expected-revision", required=True)
    parser.add_argument("--jobs", type=int, choices=(1, 2), default=2)
    parser.add_argument("--timeout-seconds", type=base._timeout, default=1800)
    parser.add_argument("--run-timeout-seconds", type=_run_timeout, default=180)
    parser.set_defaults(verilator=None)
    return parser


def main(argv=None):
    import json
    args = argument_parser().parse_args(argv)
    try:
        result = execute(args, base.resolve_paths(args))
        print(json.dumps({"outcome": result["outcome"], "reason": result["reason"],
            "report": str(Path(args.output).absolute() / "report.json"),
            "completed_counts": result["completed_counts"], "native_preflight_passed": result["native_preflight_passed"],
            **dict.fromkeys(manifest.FALSE_CLAIMS, False)}, sort_keys=True))
        return 0 if result["native_preflight_passed"] else 1
    except (OSError, ValueError, RuntimeError) as error:
        print(json.dumps({"outcome": "blocked", "reason": str(error), "native_preflight_passed": False,
                          **dict.fromkeys(manifest.FALSE_CLAIMS, False)}, sort_keys=True))
        return 1


if __name__ == "__main__":
    sys.exit(main())

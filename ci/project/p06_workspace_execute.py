#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Run the frozen serial-workspace correctness smoke in fresh native builds.

Each selected SimX/native processor RTL and FP16/BF16 variant runs the two
workspace policies in separate processes. Each process executes the same four
ordered independent P02 fixtures. A complete matrix is eight processes, 32
launches and 1,024 checked FP32 words. Selected variants never claim that matrix.

This runner requires clean source and existing identified tools/dependencies.
It does not install tools, download inputs, benchmark performance or accept a
phase. Work and output directories must be new and outside the source checkout.
"""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import sys

from baseline_inventory import _digest, hash_artifacts
from baseline_packet_contract import _stamp_flags
from baseline_process import run_bounded
import p02_matrix as base
from p02_matrix_records import DISABLED, PROFILE_SHA256, _configuration, require, validate_header_macros
from p02_wmma_fixtures import load_cases, render_header
import p03_execute as operator_run
from p03_execution_records import qualification_id
from p06_workspace_records import load_contract, validate_records, verify_output


ROOT = Path(__file__).resolve().parents[2]
APP = "tests/regression/ai_workspace"
CONTRACT_ID = "p06-serial-workspace-correctness-v1"
MANIFEST_PATH = "ci/project/p06_workspace_contract.json"
HEADER_PROBE = "p06-workspace-header-check/include-probe.cpp"
HEADER_PROBE_CONTENT = b"#include <VX_config.h>\n"
KERNEL_SHA256 = "ad3b6107f0eef91ec676412bc795ab70cd1c9f31647b2cea854de6234fe71d3e"
BACKENDS = ("simx", "rtlsim")
FORMATS = ("fp16", "bf16")
POLICIES = ("per_operation", "reusable_single_tile")
BUDGET = dict(base.BUDGET, max_rss_bytes=4 * 1024**3)
SOURCE_FILES = (
    APP + "/Makefile", APP + "/main.cpp", APP + "/observer.h", APP + "/observer.cpp",
    "ci/project/p06_workspace_execute.py", "ci/project/p06_workspace_records.py",
    "ci/project/p06_workspace_compiler_records.py", MANIFEST_PATH,
    "ci/project/p04_ci_prepare.py", ".github/workflows/p06-workspace.yml",
    "ci/toolchain_rev.sh", "ci/install_dependencies.sh", "docs/designs/serial_matmul_workspace_v1.md",
    "docs/designs/ai_operator_contract_v1.md", "docs/designs/tensor_numerics_v1.md",
)
LIMITATIONS = [
    "This is native correctness and serial managed ownership evidence, with no performance or phase acceptance claim.",
    "Only the frozen four-call changed-input sequence at M=8, N=4, K=8 is exercised; this is not the complete numerical inventory.",
    "Each policy runs in a separate process. A fresh-process boundary does not establish physical device recovery.",
    "The 320-byte peak is requested A/B/D tensor payload, not allocator cost, device-wide usage or host RSS.",
    "Allocator readings and successful native releases establish reported simulator accounting, not physical memory reclamation.",
    "Native processor rtlsim bypasses the AFU and retains integer DPI helpers; it does not close vendor P01-A03.",
    "No warm-performance, FPGA, silicon, synthesis, P06-A02/A03 or P07 acceptance result follows from this smoke.",
    "Dependency libraries are reused identified inputs; no download or dependency rebuild occurs in this runner.",
    "Tool hashes do not inventory every system header, compiler support file or system dynamic library.",
    "The packet retains source/configuration bodies and binary hashes, not binary-replay archives.",
    "Bindings identify trusted build inputs; they do not authenticate arbitrary hardware or defeat a malicious concurrent filesystem writer.",
    "Completed launch/word totals count fully verified passing processes. Failed attempts remain in the raw logs and process records.",
    "A selected variant may pass without completing the four-variant matrix; independent review and separate acceptance remain required.",
    *base.PROCESS_LIMITATIONS,
]
LOADED_HELPERS = hash_artifacts(ROOT, sorted({
    Path(module.__file__).resolve().relative_to(ROOT).as_posix()
    for module in tuple(sys.modules.values())
    if getattr(module, "__file__", None) and Path(module.__file__).suffix == ".py"
    and Path(module.__file__).resolve().is_relative_to(ROOT / "ci/project")
}))


def source_snapshot(source):
    """Bind the complete existing source inventory and every loaded local helper."""
    snapshot = operator_run.source_snapshot(source)
    names = {item["path"] for item in snapshot["files"]} | set(SOURCE_FILES)
    names.update(item["path"] for item in snapshot["checkout"].get("inputs", []))
    names.update(item["path"] for item in LOADED_HELPERS)
    snapshot["files"] = hash_artifacts(source, sorted(names))
    return snapshot


def select_cases(cases, args, contract):
    """Select complete four-call sequences, preserving their intentional repeat."""
    require(type(cases) is list and len(cases) == 88, "expected the complete independent P02 inventory")
    require(len({case["id"] for case in cases}) == 88
            and Counter(case["format"] for case in cases) == {"fp16": 44, "bf16": 44},
            "P02 fixture IDs or format inventory differ")
    require(contract["contract_id"] == CONTRACT_ID
            and contract["backends"] == list(BACKENDS)
            and contract["formats"] == list(FORMATS)
            and contract["policies"] == list(POLICIES), "workspace matrix differs from the frozen contract")
    for values, allowed, label in ((args.backend, BACKENDS, "backend"), (args.format, FORMATS, "format")):
        require(values is None or (type(values) is list and values
                and len(values) == len(set(values)) and set(values) <= set(allowed)),
                "empty, duplicate or unsupported " + label + " selection")
    backends = args.backend if args.backend is not None else list(BACKENDS)
    formats = args.format if args.format is not None else list(FORMATS)
    inventory = {case["id"]: case for case in cases}
    selected = []
    for fmt in FORMATS:
        if fmt not in formats:
            continue
        sequence = []
        for entry in contract["sequence"]:
            name = fmt + "-" + entry["fixture_suffix"]
            require(name in inventory, "missing frozen workspace fixture: " + name)
            case = inventory[name]
            require(case["format"] == fmt and [case[key] for key in ("m", "n", "k")] == contract["shape"],
                    "workspace fixture has the wrong format or shape")
            require(len(case["expected"]) * 4 == contract["operand_bytes"][2],
                    "workspace fixture has the wrong output size")
            sequence.append(case)
        require(len(sequence) == contract["per_process"]["launches"], "workspace sequence is incomplete")
        require(all(left[key] != right[key] for left, right in zip(sequence, sequence[1:])
                    for key in ("a_words", "b_words")), "both fixture inputs must change between calls")
        selected.extend(sequence)
    variants = [(driver, fmt) for driver in BACKENDS if driver in backends
                for fmt in FORMATS if fmt in formats]
    require(variants and selected, "empty workspace selection")
    return selected, variants, len(variants) == len(BACKENDS) * len(FORMATS)


def process_plan(variants, contract):
    return [{"id": driver + "-" + fmt + "-" + policy, "backend": driver, "format": fmt,
             "policy": policy, "case_ids": [fmt + "-" + item["fixture_suffix"]
                                             for item in contract["sequence"]]}
            for driver, fmt in variants for policy in contract["policies"]]


def artifacts(driver):
    require(driver in BACKENDS, "unsupported artifact backend")
    return tuple(sorted(set(base.GENERATED + base.COPIED + (
        APP + "/Makefile", APP + "/config.stamp", APP + "/ai_workspace",
        APP + "/kernel.elf", APP + "/kernel.vxbin", "sw/kernel/libvortex2.a", HEADER_PROBE,
        "sw/runtime/libvortex.so", "sw/runtime/libvortex-" + driver + ".so",
        "sw/runtime/lib" + driver + ".so", "sw/runtime/" + driver + "_rt_config.stamp",
        "sw/runtime/" + driver + "_config.stamp"))))


def effective_header_command(compiler, build, app, record, driver):
    directories = {"runtime": build / "sw/runtime" / driver,
                   "backend_cpp": build / "sim" / driver, "verilator": build / "sim" / driver,
                   "kernel": app, "host": app}
    require(record["role"] in directories, "unknown compiler role")
    return ([compiler, "-E", "-dM", "-x", "c++", *record["macro_flags"],
             *("-I" + name for name in record["include_paths"]), build / HEADER_PROBE],
            directories[record["role"]])


def validate_effective_header(text, expected, *, driver, role):
    require(driver in BACKENDS and role in ("runtime", "backend_cpp", "verilator", "kernel", "host")
            and (role != "verilator" or driver == "rtlsim"), "unsupported effective-header role")
    defines = {}
    for line in text.splitlines():
        match = re.fullmatch(r"#define ([A-Za-z_][A-Za-z0-9_]*)(\([^)]*\))?(?:[ \t]+(.*))?", line)
        require(match is not None, "preprocessor output contains a non-macro record")
        require(match[1] not in defines, "preprocessed header repeats a macro")
        defines[match[1]] = "function-like" if match[2] else (match[3] or "1")
    require(not any(name.startswith(("SIMX_", "WGMMA_", "DBG_TRACE_", "TRACING_"))
                    or name in {"DEBUG", "PERF_ENABLE", "VCD_OUTPUT", "SAIF_OUTPUT", "XRTSIM",
                                "USE_SST", "USE_GEM5", "AXI_BUS", "AXI_MEM_BANK"}
                    for name in defines), "effective header changes execution mode or instrumentation")
    # The RTL C++ shim does not select the RTL arithmetic bank. Its original
    # record is still independently checked; Verilator owns that selection.
    if driver == "rtlsim" and role == "backend_cpp":
        _configuration(defines, "RTL C++ shim header", selectors=False)
    else:
        validate_header_macros(text)
    macros = {name: value for name, value in defines.items() if name.startswith("VX_CFG_")}
    require(macros == expected, "effective " + role + " configuration differs from the generated profile")
    return macros


def completion_counts(processes):
    passed = [item for item in processes if item["outcome"] == "pass"]
    operations = [operation for item in passed for operation in item["observation"]["operations"]]
    return {"processes": len(passed),
            "launches": sum(item["dispatch"]["launches"] for item in operations),
            "checked_words": sum(item["checked"] for item in operations)}


def execute(args, paths):
    source, work, output = (paths[key] for key in ("source", "work", "output"))
    output.mkdir(mode=0o700)
    for name in ("logs", "snapshots", "artifacts"):
        (output / name).mkdir()
    work.mkdir(mode=0o700)
    (work / "tmp").mkdir()
    env = base.clean_environment(paths, args.jobs)
    env.pop("HOME", None)
    report = {
        "schema_version": 1, "contract_id": CONTRACT_ID, "scope": "native-correctness-and-managed-ownership",
        "started_at": base._now(), "state": "running", "outcome": "blocked", "reason": None,
        "acceptance_claimed": False, "performance_acceptance": False, "phase_acceptance": False,
        "phase_complete": False,
        "full_matrix_requested": False, "full_matrix_completed": False, "selected_scope_completed": False,
        "commands": [], "variants": [], "processes": [], "failures": [], "stability_checks": [],
        "limitations": LIMITATIONS,
        "budget": dict(BUDGET, jobs=args.jobs, build_timeout_seconds=args.timeout_seconds,
                       run_timeout_seconds=args.run_timeout_seconds, configure_timeout_seconds=min(120, args.timeout_seconds)),
        "paths": {key: str(value) if value else None for key, value in paths.items()},
    }
    initial = tools = dependencies = contract = None
    backends = []
    active_variant = active_process = None
    retained_identities = []

    def checkpoint():
        base._write_json(output / "report.json", report)

    def save_json(name, value):
        relative = "snapshots/" + name + ".json"
        base._write_json(output / relative, value)
        identity = hash_artifacts(output, [relative])[0]
        retained_identities.append(identity)
        return identity

    def failure(error, *, stage="execution"):
        reason = str(error) or "interrupted"
        report["failures"].append({"stage": stage, "reason": reason, "at": base._now(),
            "variant_id": active_variant["id"] if active_variant else None,
            "process_id": active_process["id"] if active_process else None})
        report["outcome"] = "fail" if report["commands"] or stage != "execution" else "blocked"
        if report["reason"] is None:
            report["reason"] = reason
        for item in (active_process, active_variant):
            if item is not None and item["outcome"] == "running":
                item.update(outcome="fail", reason=reason)

    def verify_log(row):
        path = output / row["log"]
        if row.get("log_sha256") is None:
            require(row.get("process_started") is not True and not path.exists(),
                    "command lacks a bound raw log: " + row["id"])
            return None
        digest, size = _digest(path)
        require(digest == row["log_sha256"] and size == row["log_size_bytes"] <= BUDGET["max_log_bytes"],
                "retained command log differs from its process receipt: " + row["id"])
        return {"path": row["log"], "sha256": digest, "size_bytes": size}

    def command(name, argv, cwd, environment, timeout):
        require(not any(row["id"] == name for row in report["commands"]), "duplicate command ID")
        row = {"id": name, "argv": [str(value) for value in argv], "cwd": str(cwd),
               "environment": dict(environment), "log": "logs/" + name + ".log",
               "timeout_seconds": timeout, "outcome": "running"}
        report["commands"].append(row)
        checkpoint()
        try:
            row.update(run_bounded(row["argv"], cwd, environment, output / row["log"],
                timeout_seconds=timeout, **BUDGET, resource_paths=(source, paths["tools"], work, output)))
        except (OSError, ValueError, RuntimeError, KeyboardInterrupt) as error:
            row.update(outcome="fail", reason=str(error) or "interrupted")
            checkpoint()
            raise
        checkpoint()
        verify_log(row)
        require(row["outcome"] == "pass" and row.get("process_started") is True
                and row.get("exit_code") == 0 and row.get("cleanup_complete") is True,
                "command failed: " + name + ": " + str(row.get("reason")))
        return (output / row["log"]).read_text(encoding="utf-8", errors="strict"), row

    def stable(label):
        observed_source = source_snapshot(source)
        observed_tools = base.tool_inventory(paths, env, backends)
        observed_dependencies = hash_artifacts(source, base.DEPENDENCIES)
        require(observed_source == initial, "source changed during execution")
        require(observed_tools == tools, "tools changed during execution")
        require(observed_dependencies == dependencies, "dependencies changed during execution")
        report["stability_checks"].append({"label": label, "at": base._now(),
            "source_sha256": qualification_id(observed_source),
            "tools_sha256": qualification_id(observed_tools),
            "dependencies_sha256": qualification_id(observed_dependencies)})
        checkpoint()

    def retain_files(root, identities, prefix):
        retained = []
        for item in identities:
            relative = prefix + "/" + item["path"]
            destination = output / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            with destination.open("xb") as stream:
                stream.write((root / item["path"]).read_bytes())
            copied = hash_artifacts(output, [relative])[0]
            require((copied["sha256"], copied["size_bytes"]) == (item["sha256"], item["size_bytes"]),
                    "evidence changed while retained: " + item["path"])
            retained.append(copied)
            retained_identities.append(copied)
        return retained

    def retain_build(variant, build, stage):
        names = [name for name in artifacts(variant["backend"])
                 if (name.endswith((".stamp", ".mk", ".h", ".vh", ".vlt", ".py"))
                     or Path(name).name == "Makefile" or name == HEADER_PROBE)
                 and (build / name).is_file()]
        retained = retain_files(build, hash_artifacts(build, names),
                                "artifacts/" + variant["id"] + "/" + stage)
        variant.setdefault("retained_builds", []).append({"stage": stage, "files": retained})
        checkpoint()

    checkpoint()
    try:
        require(type(args.jobs) is int and 1 <= args.jobs <= 2, "jobs exceed the two-job budget")
        require(type(args.timeout_seconds) is int and 1 <= args.timeout_seconds <= 1800,
                "build timeout exceeds the 1800-second budget")
        require(type(args.run_timeout_seconds) is int and 1 <= args.run_timeout_seconds <= 180,
                "process timeout exceeds the 180-second budget")
        report["resources_before"] = base._resources(paths)
        require(all(value >= BUDGET["min_free_bytes"] for value in
                    report["resources_before"]["free_disk_bytes"].values()), "disk reserve below 15 GiB")
        memory = report["resources_before"]["available_memory_bytes"]
        require(memory is not None and memory >= BUDGET["max_rss_bytes"], "need 4 GiB available RAM")
        require(hash_artifacts(source, [item["path"] for item in LOADED_HELPERS]) == LOADED_HELPERS,
                "executing runner/helper bytes changed after import")
        report["loaded_helpers"] = LOADED_HELPERS
        initial = source_snapshot(source)
        report["source_before"] = save_json("source-before", initial)
        base._source_ok(initial, False)
        contract = load_contract(source)
        require(_digest(source / "profiles/p02-tfr.json")[0] == PROFILE_SHA256, "frozen profile changed")
        require(_digest(source / "sw/kernel/ai/matmul.cpp")[0] == KERNEL_SHA256, "frozen native matmul kernel changed")
        all_cases = load_cases(source)
        require((source / "tests/regression/sgemm_tcu/p02_fixtures.h").read_bytes() == render_header(all_cases),
                "P02 fixture header differs from the independent fixture producer")
        cases, variants, full = select_cases(all_cases, args, contract)
        backends = [driver for driver in BACKENDS if any(driver == item[0] for item in variants)]
        plan = process_plan(variants, contract)
        report.update(contract_snapshot=save_json("contract", contract),
            contract_sha256=_digest(source / MANIFEST_PATH)[0],
            fixture_snapshot=save_json("selected-fixtures", cases), corpus=hash_artifacts(source, base.CORPUS),
            profile_sha256=PROFILE_SHA256, kernel_source_sha256=KERNEL_SHA256,
            full_matrix_requested=full, expected_processes=plan, complete_matrix=contract["complete_matrix"],
            selected_counts={"processes": len(plan),
                             "launches": len(plan) * contract["per_process"]["launches"],
                             "checked_words": len(plan) * contract["per_process"]["checked_words"]})
        report["retained_sources"] = retain_files(source, initial["files"], "artifacts/source")
        tools = base.tool_inventory(paths, env, backends)
        report["tools_before"] = save_json("tools-before", tools)
        dependencies = hash_artifacts(source, base.DEPENDENCIES)
        report["dependencies_before"] = save_json("dependencies-before", dependencies)
        checkpoint()
        for name in ("g++", "clang", "make", "python3", "riscv-gcc") + (("verilator",) if "rtlsim" in backends else ()):
            command("version-" + name.replace("+", "p"), [tools[name]["path"], "--version"], work, env, 30)
        for driver, fmt in variants:
            variant_id = driver + "-" + fmt
            stable("before-" + variant_id)
            build = work / variant_id
            build.mkdir()
            row = {"id": variant_id, "backend": driver, "format": fmt, "build_dir": str(build),
                   "outcome": "running", "process_ids": [], "effective_headers": {}}
            active_variant = row
            report["variants"].append(row)
            command(variant_id + "-configure", [source / "configure", "--xlen=64", "--profile=p02-tfr",
                "--osversion=ubuntu/focal", "--tooldir=" + str(paths["tools"])], build, env,
                min(120, args.timeout_seconds))
            row["generated_identity"] = base._generated_identity(build, source, paths["tools"])
            require((build / APP / "Makefile").read_bytes() == (source / APP / "Makefile").read_bytes(),
                    "stale generated workspace Makefile")
            retain_build(row, build, "configured")
            header, _ = command(variant_id + "-header", [tools["g++"]["path"], "-E", "-dM", "-x", "c++",
                "-DVX_CFG_XLEN=64", "-DVX_CFG_XLEN_64", "-include", build / "sw/VX_config.h", "/dev/null"],
                build, env, 30)
            row["header_macros"] = validate_header_macros(header)
            check_dir = build / Path(HEADER_PROBE).parent
            check_dir.mkdir()
            (build / HEADER_PROBE).write_bytes(HEADER_PROBE_CONTENT)
            for language, relative in (("cpp", "sw/VX_config.h"), ("verilog", "hw/VX_config.vh")):
                destination = check_dir / Path(relative).name
                command(variant_id + "-" + language + "-header-reproduce", [tools["python3"]["path"],
                    source / "ci/gen_config.py", "--config=" + str(source / "VX_config.toml"),
                    "--profile=p02-tfr", "--format=" + language, "--output=" + str(destination)],
                    build, dict(env, XLEN="64"), 30)
                require(destination.read_bytes() == (build / relative).read_bytes(), "generated header did not reproduce")
            config_flags = f"-DITYPE={fmt} -DOTYPE=fp32 -DKUNROLL=1"
            text, _ = command(variant_id + "-expected-flags", [tools["python3"]["path"],
                source / "ci/gen_config.py", "--config=" + str(source / "VX_config.toml"), "--profile=p02-tfr",
                "--xlen=64", "--format=cflags", "--cflags=" + config_flags + " -DVX_CFG_XLEN=64"], build, env, 30)
            flags = _stamp_flags(text, "independently generated workspace flags")
            require(flags and all(flag.startswith("-D") for flag in flags), "expected flags contain non-definitions")
            header, _ = command(variant_id + "-expected-expanded-header", [tools["g++"]["path"],
                "-E", "-dM", "-x", "c++", *flags, *("-D" + name + "_DISABLE" for name in DISABLED),
                "-include", build / "sw/VX_config.h", "/dev/null"], build, env, 30)
            row["expected_expanded_header_macros"] = validate_header_macros(header)
            row["expected_backend_header_macros"] = dict(row["header_macros"], **{
                name + "_DISABLE": "1" for name in DISABLED})
            make = [tools["make"]["path"], "--no-print-directory", "-j" + str(args.jobs),
                    "THREADS=" + str(args.jobs), "VERILATOR_PATH=" + str(paths["verilator"])]
            current = dict(env, CONFIGS=config_flags)
            app = build / APP
            command(variant_id + "-runtime", make + ["runtime-" + driver], app, current, args.timeout_seconds)
            retain_build(row, build, "runtime")
            command(variant_id + "-application", make + ["all"], app, current, args.timeout_seconds)
            retain_build(row, build, "built")
            row["compiler_records"] = validate_records(
                (build / ("sw/runtime/" + driver + "_rt_config.stamp")).read_text(),
                (build / ("sw/runtime/" + driver + "_config.stamp")).read_text(),
                (app / "config.stamp").read_text(), driver=driver, fmt=fmt,
                source=source, build=build, jobs=args.jobs)
            for record in row["compiler_records"]:
                role = record["role"]
                command_id = variant_id + "-" + role + "-header"
                argv, directory = effective_header_command(tools["g++"]["path"], build, app, record, driver)
                header, _ = command(command_id, argv, directory, env, 30)
                expected = dict(row["expected_backend_header_macros"] if role in ("backend_cpp", "verilator")
                                else row["expected_expanded_header_macros"])
                if driver == "rtlsim" and role == "backend_cpp":
                    expected.pop("VX_CFG_TCU_TYPE_TFR", None)
                    expected.pop("VX_CFG_FPU_TYPE_STD", None)
                row["effective_headers"][role] = {"command_id": command_id, "macros":
                    validate_effective_header(header, expected, driver=driver, role=role)}
            frozen = hash_artifacts(build, artifacts(driver))
            row["artifacts_before"] = frozen
            retain_build(row, build, "frozen")
            variant_cases = [case for case in cases if case["format"] == fmt]
            launch_env = dict(env, VORTEX_DRIVER=driver, LD_LIBRARY_PATH=str(build / "sw/runtime"))
            for planned in (item for item in plan if (item["backend"], item["format"]) == (driver, fmt)):
                process = dict(planned, command_id=planned["id"], outcome="running")
                active_process = process
                report["processes"].append(process)
                row["process_ids"].append(process["id"])
                binding = {"contract_id": CONTRACT_ID, "contract_sha256": report["contract_sha256"],
                    "source": initial, "backend": driver, "format": fmt, "policy": planned["policy"],
                    "process_id": process["id"], "sequence": contract["sequence"], "cases": variant_cases,
                    "corpus": report["corpus"], "profile_sha256": PROFILE_SHA256,
                    "kernel_source_sha256": KERNEL_SHA256, "compiler_records": row["compiler_records"],
                    "effective_headers": row["effective_headers"], "generated_identity": row["generated_identity"],
                    "artifacts": frozen, "tools": tools, "dependencies": dependencies}
                binding_id = qualification_id(binding)
                process.update(qualification_id=binding_id, binding=save_json(process["id"] + "-binding", binding))
                stable("before-" + process["id"])
                require(hash_artifacts(build, artifacts(driver)) == frozen, "artifacts changed before process")
                text, receipt = command(process["command_id"], [app / "ai_workspace", "--policy", planned["policy"],
                    "--module", app / "kernel.vxbin", "--qualification-id", binding_id],
                    app, launch_env, args.run_timeout_seconds)
                process["log"] = receipt["log"]
                require(hash_artifacts(build, artifacts(driver)) == frozen, "artifacts changed during process")
                process["observation"] = verify_output(text, cases=variant_cases, fmt=fmt,
                    policy=planned["policy"], binding_id=binding_id, contract=contract)
                stable("after-" + process["id"])
                process["outcome"] = "pass"
                active_process = None
                checkpoint()
            row["artifacts_after"] = hash_artifacts(build, artifacts(driver))
            require(row["artifacts_after"] == frozen, "build changed after execution")
            stable("after-" + variant_id)
            row["outcome"] = "pass"
            active_variant = None
            checkpoint()
        require([item["id"] for item in report["processes"]] == [item["id"] for item in plan],
                "selected process matrix is incomplete or reordered")
        require(completion_counts(report["processes"]) == report["selected_counts"],
                "selected process/launch/word counts are incomplete")
        if full:
            require(completion_counts(report["processes"]) == contract["complete_matrix"],
                    "full eight-process matrix is incomplete")
        report["outcome"] = "pass"
    except (OSError, ValueError, RuntimeError, KeyError, ImportError, TypeError) as error:
        failure(error)
    except KeyboardInterrupt:
        failure("interrupted")
    finally:
        if active_variant is not None:
            try:
                build = work / active_variant["id"]
                retain_build(active_variant, build, "failure")
                if "artifacts_before" in active_variant:
                    active_variant["artifacts_after"] = hash_artifacts(build, artifacts(active_variant["backend"]))
                    require(active_variant["artifacts_after"] == active_variant["artifacts_before"],
                            "build changed in final failure snapshot")
            except (OSError, ValueError, RuntimeError) as error:
                failure(error, stage="final-build-snapshot")
        for label, previous, observe in (
            ("source", initial, lambda: source_snapshot(source)),
            ("tools", tools, lambda: base.tool_inventory(paths, env, backends)),
            ("dependencies", dependencies, lambda: hash_artifacts(source, base.DEPENDENCIES)),
        ):
            if previous is not None:
                try:
                    final = observe()
                    report[label + "_after"] = save_json(label + "-after", final)
                    report[label + "_stable"] = previous == final
                    require(previous == final, label + " changed in final recorded snapshot")
                except (OSError, ValueError, RuntimeError) as error:
                    failure(error, stage="final-" + label + "-snapshot")
        report["raw_logs"] = []
        for row in report["commands"]:
            try:
                identity = verify_log(row)
                if identity is not None:
                    report["raw_logs"].append(identity)
            except (OSError, ValueError, RuntimeError) as error:
                failure(error, stage="final-log-verification")
        try:
            observed = hash_artifacts(output, [item["path"] for item in retained_identities])
            report["retained_files_stable"] = observed == retained_identities
            require(report["retained_files_stable"], "retained source, build or snapshot evidence changed")
        except (OSError, ValueError, RuntimeError) as error:
            failure(error, stage="final-retained-evidence")
        try:
            report["resources_after"] = base._resources(paths)
        except (OSError, ValueError, RuntimeError) as error:
            failure(error, stage="final-resources")
        counts = completion_counts(report["processes"])
        report.update(completed_processes=counts["processes"], completed_launches=counts["launches"],
                      checked_words=counts["checked_words"])
        report["selected_scope_completed"] = report["outcome"] == "pass"
        report["full_matrix_completed"] = report["full_matrix_requested"] and report["selected_scope_completed"]
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
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--host-bin", type=Path)
    parser.add_argument("--verilator", type=Path, help="existing Verilator installation root or bin/verilator")
    parser.add_argument("--backend", action="append", choices=BACKENDS)
    parser.add_argument("--format", action="append", choices=FORMATS)
    parser.add_argument("--jobs", type=int, choices=(1, 2), default=2)
    parser.add_argument("--timeout-seconds", type=base._timeout, default=1800)
    parser.add_argument("--run-timeout-seconds", type=_run_timeout, default=180)
    return parser


def main(argv=None):
    args = argument_parser().parse_args(argv)
    try:
        report = execute(args, base.resolve_paths(args))
        print(json.dumps({"outcome": report["outcome"], "reason": report["reason"],
            "report": str(Path(args.output).absolute() / "report.json"),
            "completed_processes": report["completed_processes"], "completed_launches": report["completed_launches"],
            "checked_words": report["checked_words"], "full_matrix_completed": report["full_matrix_completed"],
            "acceptance_claimed": False, "performance_acceptance": False}, sort_keys=True))
        return 0 if report["outcome"] == "pass" else 1
    except (OSError, ValueError, RuntimeError) as error:
        print(json.dumps({"outcome": "blocked", "reason": str(error), "acceptance_claimed": False,
                          "performance_acceptance": False}, sort_keys=True))
        return 1


if __name__ == "__main__":
    sys.exit(main())

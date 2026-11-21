#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Run the frozen native SimX baseline in fresh, bounded build trees.

Python 3.11 or newer is required. Every selected workload uses one warm-up and
five measured fresh processes. Packets retain original records and failures;
successful execution never supplies automatic phase acceptance.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import sys

from baseline_inventory import _digest, hash_artifacts
from baseline_packet_contract import _stamp_flags
from baseline_process import run_bounded
import p02_matrix as base
from p02_matrix_records import DISABLED, PROFILE_SHA256, require
from p03_execution_records import qualification_id
import p04_execute as model_run
from p04_fixture_adapter import render_header
from p06_compiler_records import validate_header_macros, validate_records
from p06_contract import CONTRACT_ID, FORMATS, MANIFEST_PATH, load_contract, select_workloads
from p06_records import summarize, verify_sample


ROOT = Path(__file__).resolve().parents[2]
APPS = {"matmul": "tests/regression/ai_bench_matmul", "mlp": "tests/regression/ai_bench_mlp"}
HEADER_PROBE = "p06-header-check/include-probe.cpp"
HEADER_PROBE_CONTENT = b"#include <VX_config.h>\n"
BUDGET = dict(base.BUDGET, max_rss_bytes=4 * 1024**3)
SOURCE_FILES = (
    *tuple(app + "/Makefile" for app in APPS.values()),
    "tests/regression/ai_bench_common/observer.cpp", "tests/regression/ai_bench_common/counters.h",
    "ci/project/p06_execute.py", "ci/project/p06_records.py", "ci/project/p06_contract.py",
    "ci/project/p06_compiler_records.py", MANIFEST_PATH, ".github/workflows/p06-baseline.yml",
    "ci/project/p04_ci_prepare.py", ".github/workflows/p04-model.yml",
)
RUNTIME_ARTIFACTS = ("sw/runtime/libvortex.so", "sw/runtime/libvortex-simx.so",
                     "sw/runtime/libsimx.so", "sw/runtime/simx_rt_config.stamp",
                     "sw/runtime/simx_config.stamp")
LIMITATIONS = [
    "Execution covers only the selected ordinary dense native SimX timing-model workloads and formats.",
    "One warm-up and five measurements use separate processes and fresh device contexts; no warm device-cache claim follows.",
    "Modeled active core cycles, host process duration and overlapping model profiles have different boundaries.",
    "Whole-context counters include setup and transfers; they are not per-kernel or model-stage costs.",
    "Host process duration includes startup, fixture I/O, numerical checking, cleanup and counter instrumentation.",
    "Dependency libraries are reused identified inputs; the runner does not download or rebuild them.",
    "Tool identities do not inventory every system header, compiler support file or dynamic library.",
    "The packet retains source/configuration bodies and binary identities, not binary-replay archives.",
    "Binding IDs identify trusted build inputs and do not authenticate arbitrary hardware or defeat malicious concurrent filesystem writers.",
    "Selected-format success does not complete the full matrix. Development results do not qualify formal acceptance; independent review is required.",
    "No optimization, physical speed, power, synthesis, FPGA, silicon or P06-A02/A03 result is claimed.",
    *base.PROCESS_LIMITATIONS,
]
LOADED_HELPERS = hash_artifacts(ROOT, sorted({
    Path(module.__file__).resolve().relative_to(ROOT).as_posix()
    for module in tuple(sys.modules.values())
    if getattr(module, "__file__", None) and Path(module.__file__).suffix == ".py"
    and Path(module.__file__).resolve().is_relative_to(ROOT / "ci/project")
}))


def source_snapshot(source):
    snapshot = model_run.source_snapshot(source)
    names = {item["path"] for item in snapshot["files"]} | set(SOURCE_FILES)
    names.update(item["path"] for item in snapshot["checkout"]["inputs"])
    names.update(item["path"] for item in LOADED_HELPERS)
    snapshot["files"] = hash_artifacts(source, sorted(names))
    return snapshot


def artifacts():
    names = set(base.GENERATED + base.COPIED + RUNTIME_ARTIFACTS
                + ("sw/kernel/libvortex2.a", HEADER_PROBE))
    for app in APPS.values():
        names.update(app + "/" + name for name in
                     ("Makefile", "config.stamp", Path(app).name, "kernel.elf", "kernel.vxbin"))
    return tuple(sorted(names))


def sample_plan(workloads, contract):
    return [{"sample_id": workload["id"] + "-" + phase + "-" + str(repetition),
             "workload_id": workload["id"], "phase": phase, "repetition": repetition}
            for workload in workloads
            for phase, count in (("warmup", contract["sampling"]["warmup_runs"]),
                                 ("measurement", contract["sampling"]["measured_runs"]))
            for repetition in range(count)]


def validate_effective_header(text, expected, *, role):
    require(role in ("runtime", "backend_cpp", "kernel", "host"), "unknown compiler role")
    macros = validate_header_macros(text, performance=role == "backend_cpp")
    require({key: value for key, value in macros.items() if key.startswith("VX_CFG_")} == expected,
            "effective " + role + " configuration differs from independently generated profile")
    return macros


def effective_header_command(compiler, build, application, record):
    role = record["role"]
    directory = {"runtime": build / "sw/runtime/simx", "backend_cpp": build / "sim/simx",
                 "kernel": application, "host": application}[role]
    argv = [compiler, "-E", "-dM", "-x", "c++", *record["macro_flags"],
            *("-I" + path for path in record["include_paths"]), build / HEADER_PROBE]
    return argv, directory


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
        "schema_version": 1, "contract_id": CONTRACT_ID, "started_at": base._now(),
        "state": "running", "outcome": "blocked", "reason": None,
        "development": args.development, "acceptance_claimed": False, "phase_complete": False,
        "full_matrix_requested": False, "full_matrix_completed": False, "selected_scope_completed": False,
        "commands": [], "variants": [], "samples": [], "failures": [], "stability_checks": [],
        "limitations": LIMITATIONS,
        "budget": dict(BUDGET, jobs=args.jobs, build_timeout_seconds=args.timeout_seconds,
                       run_timeout_seconds=args.run_timeout_seconds, configure_timeout_seconds=120),
        "paths": {key: str(value) if value else None for key, value in paths.items()},
    }
    initial = tools = dependencies = contract = None
    active_variant = active_sample = None

    def checkpoint():
        base._write_json(output / "report.json", report)

    def save_json(name, value):
        path = "snapshots/" + name + ".json"
        base._write_json(output / path, value)
        return hash_artifacts(output, [path])[0]

    def failure(error, *, stage="execution"):
        reason = str(error)
        report["failures"].append({"stage": stage, "reason": reason, "at": base._now(),
                                   "variant_id": active_variant["id"] if active_variant else None,
                                   "sample_id": active_sample["sample_id"] if active_sample else None})
        report["outcome"] = "fail" if report["commands"] or stage != "execution" else "blocked"
        if report["reason"] is None:
            report["reason"] = reason
        if active_sample is not None and active_sample["outcome"] == "running":
            active_sample.update(outcome="fail", reason=reason)
            receipt = next((row for row in report["commands"]
                            if row["id"] == active_sample["command_id"]), None)
            if receipt is not None and "duration_seconds" in receipt:
                active_sample["process_duration_seconds"] = receipt["duration_seconds"]
        if active_variant is not None and active_variant["outcome"] == "running":
            active_variant.update(outcome="fail", reason=reason)

    def command(name, argv, cwd, environment, timeout):
        require(not any(row["id"] == name for row in report["commands"]), "duplicate command ID")
        row = {"id": name, "argv": [str(value) for value in argv], "cwd": str(cwd),
               "environment": dict(environment), "log": "logs/" + name + ".log",
               "timeout_seconds": timeout, "outcome": "running"}
        report["commands"].append(row)
        checkpoint()
        try:
            row.update(run_bounded(row["argv"], cwd, environment, output / row["log"],
                       timeout_seconds=timeout, **BUDGET, resource_paths=(source, work, output)))
        except (OSError, ValueError, RuntimeError, KeyboardInterrupt) as error:
            row.update(outcome="fail", reason=str(error) or "interrupted")
            checkpoint()
            raise
        checkpoint()
        require(row["outcome"] == "pass" and row.get("process_started") is True
                and row.get("exit_code") == 0 and row.get("cleanup_complete") is True,
                "command failed: " + name + ": " + str(row.get("reason")))
        body = (output / row["log"]).read_bytes()
        require(len(body) == row["log_size_bytes"] <= BUDGET["max_log_bytes"]
                and hashlib.sha256(body).hexdigest() == row["log_sha256"],
                "retained command log differs from its process receipt: " + name)
        return body.decode("utf-8", errors="strict"), row

    def stable(label):
        current_source = source_snapshot(source)
        current_tools = base.tool_inventory(paths, env, ["simx"])
        current_dependencies = hash_artifacts(source, base.DEPENDENCIES)
        require(current_source == initial, "source changed during execution")
        require(current_tools == tools, "tools changed during execution")
        require(current_dependencies == dependencies, "dependencies changed during execution")
        report["stability_checks"].append({
            "label": label, "at": base._now(), "source_sha256": qualification_id(current_source),
            "tools_sha256": qualification_id(current_tools),
            "dependencies_sha256": qualification_id(current_dependencies),
        })
        checkpoint()

    def retain_build(variant, build, stage):
        names = [name for name in artifacts()
                 if (name.endswith((".stamp", ".mk", ".h", ".vh", ".vlt", ".py"))
                     or Path(name).name == "Makefile" or name == HEADER_PROBE)
                 and (build / name).is_file()]
        original = hash_artifacts(build, names)
        retained = []
        for item in original:
            relative = "artifacts/" + variant["id"] + "/" + stage + "/" + item["path"]
            destination = output / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes((build / item["path"]).read_bytes())
            copied = hash_artifacts(output, [relative])[0]
            require((copied["sha256"], copied["size_bytes"])
                    == (item["sha256"], item["size_bytes"]), "generated evidence changed while retained")
            retained.append(copied)
        variant.setdefault("retained_builds", []).append({"stage": stage, "files": retained})
        checkpoint()

    checkpoint()
    try:
        require(type(args.jobs) is int and 1 <= args.jobs <= 2, "jobs exceed the two-job budget")
        require(type(args.timeout_seconds) is int and 1 <= args.timeout_seconds <= 1800,
                "build timeout exceeds the 1800-second budget")
        require(type(args.run_timeout_seconds) is int and 1 <= args.run_timeout_seconds <= 180,
                "sample timeout exceeds the 180-second budget")
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
        base._source_ok(initial, args.development)
        contract = load_contract(source)
        workloads = select_workloads(contract, args.format)
        selected_formats = [fmt for fmt in FORMATS if any(item["format"] == fmt for item in workloads)]
        require(contract["budget"] == dict(BUDGET, jobs_max=2, build_timeout_seconds=1800,
                                          run_timeout_seconds=180), "runner/contract budget mismatch")
        require(_digest(source / "profiles/p02-tfr.json")[0] == PROFILE_SHA256, "profile changed")
        require((source / "tests/regression/ai_mlp/p04_fixtures.h").read_text() == render_header(source),
                "generated model fixture adapter is stale")
        report.update(contract_snapshot=save_json("contract", contract),
                      contract_sha256=_digest(source / MANIFEST_PATH)[0],
                      workload_snapshot=save_json("workloads", workloads),
                      workload_ids=[item["id"] for item in workloads], formats=selected_formats,
                      full_matrix_requested=workloads == contract["workloads"],
                      expected_samples=sample_plan(workloads, contract), sampling=contract["sampling"],
                      boundaries=contract["boundaries"], contract_limitations=contract["limitations"])
        tools = base.tool_inventory(paths, env, ["simx"])
        report["tools_before"] = save_json("tools-before", tools)
        dependencies = hash_artifacts(source, base.DEPENDENCIES)
        report["dependencies_before"] = save_json("dependencies-before", dependencies)
        retained = []
        for item in initial["files"]:
            relative = "artifacts/source/" + item["path"]
            destination = output / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes((source / item["path"]).read_bytes())
            copied = hash_artifacts(output, [relative])[0]
            require((copied["sha256"], copied["size_bytes"])
                    == (item["sha256"], item["size_bytes"]), "source changed while retained")
            retained.append(copied)
        report["retained_sources"] = retained
        checkpoint()
        for name in ("g++", "clang", "make", "python3"):
            command("version-" + name.replace("+", "p"), [tools[name]["path"], "--version"], work, env, 30)
        for fmt in selected_formats:
            stable("before-simx-" + fmt)
            variant_id = "simx-" + fmt
            build = work / variant_id
            build.mkdir()
            row = {"id": variant_id, "backend": "simx", "format": fmt,
                   "outcome": "running", "applications": {}, "sample_ids": []}
            active_variant = row
            report["variants"].append(row)
            command(variant_id + "-configure", [source / "configure", "--xlen=64", "--profile=p02-tfr",
                    "--osversion=ubuntu/focal", "--tooldir=" + str(paths["tools"])], build, env, 120)
            row["generated_identity"] = base._generated_identity(build, source, paths["tools"])
            for app in APPS.values():
                require((build / app / "Makefile").read_bytes() == (source / app / "Makefile").read_bytes(),
                        "stale generated benchmark Makefile: " + app)
            retain_build(row, build, "configured")
            header, _ = command(variant_id + "-header", [tools["g++"]["path"], "-E", "-dM", "-x", "c++",
                "-DVX_CFG_XLEN=64", "-DVX_CFG_XLEN_64", "-include", build / "sw/VX_config.h", "/dev/null"],
                build, env, 30)
            row["header_macros"] = validate_header_macros(header)
            check_dir = build / "p06-header-check"
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
            resolved_text, _ = command(variant_id + "-expected-flags", [tools["python3"]["path"],
                source / "ci/gen_config.py", "--config=" + str(source / "VX_config.toml"),
                "--profile=p02-tfr", "--xlen=64", "--format=cflags",
                "--cflags=" + config_flags + " -DVX_CFG_XLEN=64"], build, env, 30)
            resolved_flags = _stamp_flags(resolved_text, "independently generated benchmark flags")
            require(resolved_flags and all(flag.startswith("-D") for flag in resolved_flags),
                    "generated expected configuration contains non-definition flags")
            header, _ = command(variant_id + "-expected-expanded-header", [tools["g++"]["path"],
                "-E", "-dM", "-x", "c++", *resolved_flags,
                *("-D" + name + "_DISABLE" for name in DISABLED),
                "-include", build / "sw/VX_config.h", "/dev/null"],
                build, env, 30)
            row["expected_expanded_header_macros"] = validate_header_macros(header)
            row["expected_backend_header_macros"] = dict(row["header_macros"], **{
                name + "_DISABLE": "1" for name in DISABLED})
            make = [tools["make"]["path"], "--no-print-directory", "-j" + str(args.jobs),
                    "THREADS=" + str(args.jobs)]
            current = dict(env, CONFIGS=config_flags, PERF="1")
            command(variant_id + "-runtime", make + ["runtime-simx"], build / APPS["matmul"],
                    current, args.timeout_seconds)
            retain_build(row, build, "runtime")
            runtime = None
            for kind, relative in APPS.items():
                app = build / relative
                command(variant_id + "-build-" + kind, make + ["all"], app, current, args.timeout_seconds)
                retain_build(row, build, "built-" + kind)
                current_runtime = hash_artifacts(build, RUNTIME_ARTIFACTS)
                if runtime is not None:
                    require(current_runtime == runtime, "shared runtime changed between application builds")
                runtime = current_runtime
            for kind, relative in APPS.items():
                app = build / relative
                records = validate_records((build / "sw/runtime/simx_rt_config.stamp").read_text(),
                    (build / "sw/runtime/simx_config.stamp").read_text(), (app / "config.stamp").read_text(),
                    fmt=fmt, source=source, build=build, jobs=args.jobs)
                app_row = {"path": relative, "compiler_records": records, "effective_headers": {}}
                row["applications"][kind] = app_row
                for record in records:
                    role = record["role"]
                    command_id = variant_id + "-" + kind + "-" + role + "-header"
                    argv, directory = effective_header_command(tools["g++"]["path"], build, app, record)
                    header, _ = command(command_id, argv, directory, env, 30)
                    expected = row["expected_backend_header_macros"] if role == "backend_cpp" else row["expected_expanded_header_macros"]
                    macros = validate_effective_header(header, expected, role=role)
                    app_row["effective_headers"][role] = {"command_id": command_id, "macros": macros}
            for name in ("kernel.elf", "kernel.vxbin"):
                require(_digest(build / APPS["matmul"] / name) == _digest(build / APPS["mlp"] / name),
                        "application kernels differ within one format: " + name)
            frozen = hash_artifacts(build, artifacts())
            binding = {"contract_id": CONTRACT_ID, "contract_sha256": report["contract_sha256"],
                       "source": initial, "backend": "simx", "format": fmt,
                       "applications": row["applications"], "generated_header_macros": row["header_macros"],
                       "expected_expanded_header_macros": row["expected_expanded_header_macros"],
                       "expected_backend_header_macros": row["expected_backend_header_macros"],
                       "artifacts": frozen, "tools": tools, "dependencies": dependencies,
                       "profile_sha256": PROFILE_SHA256, "sampling": contract["sampling"],
                       "boundaries": contract["boundaries"], "counters": contract["counters"],
                       "workloads": [item for item in workloads if item["format"] == fmt]}
            binding_id = qualification_id(binding)
            row.update(qualification_id=binding_id, binding=save_json(variant_id + "-binding", binding),
                       artifacts_before=frozen)
            retain_build(row, build, "frozen")
            launch_env = dict(env, VORTEX_DRIVER="simx", LD_LIBRARY_PATH=str(build / "sw/runtime"))
            for workload in (item for item in workloads if item["format"] == fmt):
                stable("before-" + workload["id"])
                app = build / APPS[workload["kind"]]
                for planned in (item for item in report["expected_samples"] if item["workload_id"] == workload["id"]):
                    sample = dict(planned, command_id="simx-" + planned["sample_id"], outcome="running")
                    active_sample = sample
                    report["samples"].append(sample)
                    row["sample_ids"].append(sample["sample_id"])
                    checkpoint()
                    require(hash_artifacts(build, artifacts()) == frozen, "artifacts changed before sample")
                    argv = [app / app.name, "--case", workload["case_id"], "--iterations", "1",
                            "--module", app / "kernel.vxbin", "--qualification-id", binding_id]
                    if workload["kind"] == "mlp":
                        argv += ["--backend", "simx", "--source-revision", initial["checkout"]["revision"]]
                    text, receipt = command(sample["command_id"], argv, app,
                                            dict(launch_env, P06_SAMPLE_ID=sample["sample_id"]),
                                            args.run_timeout_seconds)
                    duration = receipt["duration_seconds"]
                    require(type(duration) in (int, float) and math.isfinite(duration) and duration >= 0,
                            "sample process receipt lacks a finite duration")
                    sample["process_duration_seconds"] = duration
                    require(hash_artifacts(build, artifacts()) == frozen, "artifacts changed during sample")
                    sample["observation"] = verify_sample(text, workload, binding_id,
                        sample_id=sample["sample_id"], source_revision=initial["checkout"]["revision"],
                        fixture_sha256=workload["fixture_sha256"], contract=contract)
                    sample["outcome"] = "pass"
                    checkpoint()
                    active_sample = None
                stable("after-" + workload["id"])
            row["artifacts_after"] = hash_artifacts(build, artifacts())
            require(row["artifacts_after"] == frozen, "build changed after execution")
            stable("after-" + variant_id)
            row["outcome"] = "pass"
            checkpoint()
            active_variant = None
        report["summary"] = summarize(report["samples"], contract, workloads)
        report["summary_snapshot"] = save_json("summary", report["summary"])
        report["outcome"] = "pass"
    except (OSError, ValueError, RuntimeError, KeyError, ImportError, TypeError) as error:
        failure(error)
    except KeyboardInterrupt:
        failure("interrupted")
    finally:
        if active_variant is not None:
            try:
                retain_build(active_variant, work / active_variant["id"], "failure")
                if "artifacts_before" in active_variant:
                    active_variant["artifacts_after"] = hash_artifacts(work / active_variant["id"], artifacts())
                    require(active_variant["artifacts_after"] == active_variant["artifacts_before"],
                            "build changed in final failure snapshot")
            except (OSError, ValueError, RuntimeError) as error:
                failure(error, stage="final-build-snapshot")
        for label, previous, observe in (
            ("source", initial, lambda: source_snapshot(source)),
            ("tools", tools, lambda: base.tool_inventory(paths, env, ["simx"])),
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
        try:
            report["resources_after"] = base._resources(paths)
        except (OSError, ValueError, RuntimeError) as error:
            failure(error, stage="final-resources")
        report["completed_samples"] = sum(item["outcome"] == "pass" for item in report["samples"])
        report["selected_scope_completed"] = report["outcome"] == "pass"
        report["full_matrix_completed"] = report["full_matrix_requested"] and report["selected_scope_completed"]
        report.update(state="finished", finished_at=base._now())
        checkpoint()
    return report


def _run_timeout(value):
    result = base._timeout(value)
    if result > 180:
        raise argparse.ArgumentTypeError("sample timeout must be between 1 and 180 seconds")
    return result


def argument_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("run",))
    parser.add_argument("--source-dir", type=Path, default=ROOT)
    parser.add_argument("--tools-dir", type=Path, required=True)
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--host-bin", type=Path)
    parser.add_argument("--format", action="append", choices=FORMATS)
    parser.add_argument("--jobs", type=int, choices=(1, 2), default=2)
    parser.add_argument("--timeout-seconds", type=base._timeout, default=1800)
    parser.add_argument("--run-timeout-seconds", type=_run_timeout, default=180)
    parser.add_argument("--development", action="store_true", help="allow dirty source without acceptance claims")
    parser.set_defaults(verilator=None)
    return parser


def main(argv=None):
    args = argument_parser().parse_args(argv)
    try:
        report = execute(args, base.resolve_paths(args))
        print(json.dumps({"outcome": report["outcome"], "reason": report["reason"],
                          "report": str(Path(args.output).absolute() / "report.json"),
                          "full_matrix_completed": report["full_matrix_completed"], "acceptance_claimed": False}))
        return 0 if report["outcome"] == "pass" else 1
    except (OSError, ValueError, RuntimeError) as error:
        print(json.dumps({"outcome": "blocked", "reason": str(error), "acceptance_claimed": False}))
        return 1


if __name__ == "__main__":
    sys.exit(main())

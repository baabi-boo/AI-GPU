#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Build and qualify managed matmul on the frozen SimX/native-RTL profile.

Uses fresh generated builds, independent P02 fixtures, separate compiler-record
validation, explicit runtime binding, bounded commands and retained raw logs.
No successful packet automatically accepts a phase.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sys

from baseline_inventory import _digest, hash_artifacts
from baseline_process import run_bounded
import p02_matrix as base
from p02_matrix_records import PROFILE_SHA256, require, validate_header_macros
from p03_execution_records import qualification_id, validate_records, verify_output
from p02_wmma_fixtures import load_cases


ROOT = Path(__file__).resolve().parents[2]
APP = "tests/regression/ai_matmul"
SOURCE_FILES = (
    "sw/common/ai_matmul_args.h", "sw/common/ai_matmul_profile.h", "sw/kernel/ai/matmul.cpp",
    "sw/runtime/ai/contract.h", "sw/runtime/ai/contract.cpp", "sw/runtime/ai/runtime.h",
    "sw/runtime/ai/runtime.cpp", APP + "/Makefile", APP + "/main.cpp",
    "tests/runtime/Makefile", "tests/runtime/test_ai_lifecycle.cpp",
    "ci/project/p03_execute.py", "ci/project/p03_execution_records.py",
    "ci/project/p03_operator_manifest.json",
)
LIMITATIONS = [
    "Only the six declared ordinary FP16/BF16-to-FP32 matmul signatures are exercised.",
    "Runtime capabilities cannot identify tensor arithmetic; the trusted runner validates separate compiler records and binds exact module/backend/host bytes before dispatch.",
    "The binding identifies trusted build inputs; it is not authentication of arbitrary hardware or protection against a concurrent malicious filesystem writer.",
    "Native processor RTL bypasses the AFU; integer DPI helpers remain. No vendor hw_emu, FPGA, PPA or silicon evidence follows.",
    "Host fault-injection tests and actual SimX lifecycle integration have separate scopes.",
    "Dependency libraries are reused identified inputs; no dependency download or rebuild occurs.",
    "The packet records binary hashes and source/configuration bodies, not binary-replay archives.",
    "Independent review and separate acceptance are required before any phase closes.",
    *base.PROCESS_LIMITATIONS,
]
LOADED_HELPERS = hash_artifacts(ROOT, sorted({
    Path(module.__file__).resolve().relative_to(ROOT).as_posix()
    for module in tuple(sys.modules.values())
    if getattr(module, "__file__", None) and Path(module.__file__).suffix == ".py"
    and Path(module.__file__).resolve().is_relative_to(ROOT / "ci/project")
}))


def source_snapshot(source):
    snapshot = base.source_snapshot(source)
    paths = {row["path"] for row in snapshot["files"]} | set(SOURCE_FILES)
    paths.update(path.relative_to(source).as_posix() for path in (source / "tests/runtime").glob("*.cpp"))
    for directory in base.SOURCE_ROOTS:
        paths.update(path.relative_to(source).as_posix() for path in (source / directory).rglob("*.inc")
                     if path.is_file())
    for directory in ("third_party/ramulator/ext/spdlog/include",
                      "third_party/ramulator/ext/yaml-cpp/include",
                      "third_party/ramulator/src", "third_party/softfloat/source/include",
                      "third_party/softfloat/source/RISCV"):
        paths.update(path.relative_to(source).as_posix() for path in (source / directory).rglob("*")
                     if path.is_file() and path.suffix in (".h", ".hpp", ".inc", ".tpp"))
    snapshot["files"] = hash_artifacts(source, sorted(paths))
    return snapshot


def artifacts(driver):
    return base.GENERATED + (APP + "/Makefile", APP + "/config.stamp", APP + "/ai_matmul",
        APP + "/kernel.elf", APP + "/kernel.vxbin", "sw/kernel/libvortex2.a",
        "sw/runtime/libvortex.so", "sw/runtime/libvortex-" + driver + ".so",
        "sw/runtime/lib" + driver + ".so", "sw/runtime/" + driver + "_rt_config.stamp",
        "sw/runtime/" + driver + "_config.stamp")


def execute(args, paths):
    source, work, output = (paths[key] for key in ("source", "work", "output"))
    output.mkdir(mode=0o700)
    for name in ("logs", "snapshots", "artifacts"):
        (output / name).mkdir()
    work.mkdir(mode=0o700)
    (work / "tmp").mkdir()
    env = base.clean_environment(paths, args.jobs)
    env.pop("HOME", None)
    report = {"schema_version": 1, "contract_id": "p03-managed-matmul-execution-v1",
              "started_at": base._now(), "state": "running", "outcome": "blocked",
              "reason": None, "development": args.development, "acceptance_claimed": False,
              "phase_complete": False, "commands": [], "variants": [], "limitations": LIMITATIONS,
              "budget": dict(base.BUDGET, jobs=args.jobs), "iterations": args.iterations,
              "paths": {key: str(value) if value else None for key, value in paths.items()}}
    initial = tools = dependencies = None

    def checkpoint():
        base._write_json(output / "report.json", report)

    def save_json(name, value):
        path = "snapshots/" + name + ".json"
        base._write_json(output / path, value)
        return hash_artifacts(output, [path])[0]

    def command(name, argv, cwd, environment, timeout):
        row = {"id": name, "argv": [str(x) for x in argv], "cwd": str(cwd),
               "environment": environment, "log": "logs/" + name + ".log",
               "timeout_seconds": timeout, "outcome": "running"}
        report["commands"].append(row)
        checkpoint()
        row.update(run_bounded(row["argv"], cwd, environment, output / row["log"],
                   timeout_seconds=timeout, **base.BUDGET, resource_paths=(source, work, output)))
        checkpoint()
        require(row["outcome"] == "pass" and row["exit_code"] == 0 and row["cleanup_complete"],
                "command failed: " + name + ": " + str(row.get("reason")))
        return (output / row["log"]).read_text(encoding="utf-8")

    def stable():
        require(source_snapshot(source) == initial, "source changed during execution")
        require(base.tool_inventory(paths, env, backends) == tools, "tools changed during execution")
        require(hash_artifacts(source, base.DEPENDENCIES) == dependencies, "dependencies changed")

    try:
        report["resources_before"] = base._resources(paths)
        require(all(value >= base.BUDGET["min_free_bytes"] for value in
                    report["resources_before"]["free_disk_bytes"].values()), "disk reserve below 15 GiB")
        memory = report["resources_before"]["available_memory_bytes"]
        require(memory is not None and memory >= base.BUDGET["max_rss_bytes"], "need 6 GiB available RAM")
        require(hash_artifacts(source, [item["path"] for item in LOADED_HELPERS]) == LOADED_HELPERS,
                "executing runner/helper bytes changed after import")
        report["loaded_helpers"] = LOADED_HELPERS
        initial = source_snapshot(source)
        report["source_before"] = save_json("source-before", initial)
        base._source_ok(initial, args.development)
        require(_digest(source / "profiles/p02-tfr.json")[0] == PROFILE_SHA256, "profile changed")
        cases, variants, full = base.select_cases(load_cases(source), args)
        backends = sorted({driver for driver, _ in variants})
        report.update(full_matrix_requested=full, fixture_snapshot=save_json("fixtures", cases),
                      case_ids=[case["id"] for case in cases])
        tools = base.tool_inventory(paths, env, backends)
        report["tools_before"] = save_json("tools-before", tools)
        dependencies = hash_artifacts(source, base.DEPENDENCIES)
        report["dependencies_before"] = dependencies
        retained = set(base.TOOLING + base.CORPUS + SOURCE_FILES + ("profiles/p02-tfr.json",))
        for module in tuple(sys.modules.values()):
            path = Path(getattr(module, "__file__", "") or "/missing")
            if path.suffix == ".py" and path.resolve().is_relative_to(source / "ci/project"):
                retained.add(path.resolve().relative_to(source).as_posix())
        retained.update(name for name in ("sw/runtime/common/queue.cpp", "sw/runtime/common/buffer.cpp",
            "sw/runtime/common/device.cpp", "sw/runtime/common/module.cpp",
            "sw/runtime/simx/vortex.cpp", "sw/runtime/rtlsim/vortex.cpp",
            "sw/runtime/common/vortex2_internal.h", "sim/common/cmd_processor.cpp") if (source / name).is_file())
        for name in sorted(retained):
            destination = output / "artifacts/source" / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes((source / name).read_bytes())
        report["retained_sources"] = hash_artifacts(output,
            ["artifacts/source/" + name for name in sorted(retained)])
        for name in ("g++", "clang", "make") + (("verilator",) if "rtlsim" in backends else ()):
            command("version-" + name.replace("+", "p"), [tools[name]["path"], "--version"], work, env, 30)
        for driver, fmt in variants:
            stable()
            variant_id = driver + "-" + fmt
            build = work / variant_id
            build.mkdir()
            row = {"id": variant_id, "backend": driver, "format": fmt, "outcome": "running", "cases": []}
            report["variants"].append(row)
            command(variant_id + "-configure", [source / "configure", "--xlen=64", "--profile=p02-tfr",
                "--osversion=ubuntu/focal", "--tooldir=" + str(paths["tools"])], build, env, 120)
            base._generated_identity(build, source, paths["tools"])
            require((build / APP / "Makefile").read_bytes() == (source / APP / "Makefile").read_bytes(),
                    "stale generated operator Makefile")
            header = command(variant_id + "-header", [tools["g++"]["path"], "-E", "-dM", "-x", "c++",
                "-DVX_CFG_XLEN=64", "-DVX_CFG_XLEN_64", "-include", build / "sw/VX_config.h", "/dev/null"],
                build, env, 30)
            row["header_macros"] = validate_header_macros(header)
            check_dir = build / "p03-header-check"
            check_dir.mkdir()
            for language, relative in (("cpp", "sw/VX_config.h"), ("verilog", "hw/VX_config.vh")):
                destination = check_dir / Path(relative).name
                command(variant_id + "-" + language + "-header-reproduce", [tools["python3"]["path"],
                    source / "ci/gen_config.py", "--config=" + str(source / "VX_config.toml"),
                    "--profile=p02-tfr", "--format=" + language, "--output=" + str(destination)],
                    build, dict(env, XLEN="64"), 30)
                require(destination.read_bytes() == (build / relative).read_bytes(), "header did not reproduce")
            make = [tools["make"]["path"], "--no-print-directory", "-j" + str(args.jobs),
                    "THREADS=" + str(args.jobs), "VERILATOR_PATH=" + str(paths["verilator"])]
            current = dict(env, CONFIGS=f"-DITYPE={fmt} -DOTYPE=fp32 -DKUNROLL=1")
            app = build / APP
            command(variant_id + "-runtime", make + ["runtime-" + driver], app, current, args.timeout_seconds)
            command(variant_id + "-application", make + ["all"], app, current, args.timeout_seconds)
            row["compiler_records"] = validate_records(
                (build / ("sw/runtime/" + driver + "_rt_config.stamp")).read_text(),
                (build / ("sw/runtime/" + driver + "_config.stamp")).read_text(),
                (app / "config.stamp").read_text(), driver=driver, fmt=fmt,
                source=source, build=build, jobs=args.jobs)
            record = row["compiler_records"][1]
            header = command(variant_id + "-effective-header", [tools["g++"]["path"], "-E", "-dM", "-x",
                "c++", *record["macro_flags"], "-include", build / "sw/VX_config.h", "/dev/null"], build, env, 30)
            row["backend_header_macros"] = validate_header_macros(header)
            frozen = hash_artifacts(build, artifacts(driver))
            binding = {"source": initial["checkout"], "backend": driver, "format": fmt,
                       "compiler_records": row["compiler_records"], "artifacts": frozen,
                       "dependencies": dependencies, "profile_sha256": PROFILE_SHA256}
            binding_id = qualification_id(binding)
            row.update(qualification_id=binding_id, binding=save_json(variant_id + "-binding", binding),
                       artifacts_before=frozen)
            for item in frozen:
                name = item["path"]
                if name.endswith((".stamp", ".mk", ".h", ".vh", ".vlt")) or Path(name).name == "Makefile":
                    destination = output / "artifacts" / variant_id / name
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    destination.write_bytes((build / name).read_bytes())
            launch_env = dict(env, VORTEX_DRIVER=driver, LD_LIBRARY_PATH=str(build / "sw/runtime"))
            stable()
            for case in (case for case in cases if case["format"] == fmt):
                require(hash_artifacts(build, artifacts(driver)) == frozen, "artifacts changed before launch")
                text = command(variant_id + "-" + case["id"], [app / "ai_matmul", "--case", case["id"],
                    "--iterations", str(args.iterations), "--module", app / "kernel.vxbin",
                    "--qualification-id", binding_id], app, launch_env, args.run_timeout_seconds)
                require(hash_artifacts(build, artifacts(driver)) == frozen, "artifacts changed during launch")
                row["cases"].append({"id": case["id"], "outcome": "pass", "observations":
                                     verify_output(text, case, args.iterations, binding_id)})
                checkpoint()
            if driver == "simx" and fmt == "fp16":
                command("lifecycle-build", make + ["test_ai_lifecycle"], build / "tests/runtime",
                        current, args.timeout_seconds)
                lifecycle = command("lifecycle-run", [build / "tests/runtime/test_ai_lifecycle"],
                                    build / "tests/runtime", launch_env, 180)
                require("P03_LIFECYCLE PASSED" in lifecycle, "missing actual runtime lifecycle success")
                report["lifecycle"] = {"outcome": "pass", "driver": "simx", "command_id": "lifecycle-run",
                    "binary": hash_artifacts(build, ["tests/runtime/test_ai_lifecycle"])[0]}
            row["artifacts_after"] = hash_artifacts(build, artifacts(driver))
            require(row["artifacts_after"] == frozen, "build changed after execution")
            stable()
            row["outcome"] = "pass"
            checkpoint()
        report["completed_case_executions"] = sum(len(row["cases"]) for row in report["variants"])
        report["completed_launches"] = report["completed_case_executions"] * args.iterations
        report["checked_words"] = sum(obs["checked"] for row in report["variants"]
                                      for case in row["cases"] for obs in case["observations"])
        if full:
            require(report["completed_case_executions"] == 176 and report.get("lifecycle", {}).get("outcome") == "pass",
                    "full operator/lifecycle matrix incomplete")
        report["outcome"] = "pass"
    except (OSError, ValueError, RuntimeError, KeyError, ImportError) as error:
        report.update(outcome="fail" if report["commands"] else "blocked", reason=str(error))
    except KeyboardInterrupt:
        report.update(outcome="fail", reason="interrupted")
    finally:
        if initial is not None:
            try:
                final = source_snapshot(source)
                report["source_after"] = save_json("source-after", final)
                report["source_stable"] = initial == final
                require(initial == final, "source changed during execution")
                if tools is not None:
                    stable()
                    report["tools_after"] = save_json("tools-after", base.tool_inventory(paths, env, backends))
            except (OSError, ValueError, RuntimeError) as error:
                report.update(outcome="fail", reason=str(error))
        report.update(state="finished", finished_at=base._now(), resources_after=base._resources(paths))
        checkpoint()
    return report


def main(argv=None):
    parser = base.argument_parser()
    parser.description = __doc__
    args = parser.parse_args(argv)
    try:
        report = execute(args, base.resolve_paths(args))
        print(json.dumps({"outcome": report["outcome"], "reason": report["reason"],
                          "report": str(Path(args.output).absolute() / "report.json")}))
        return 0 if report["outcome"] == "pass" else 1
    except (OSError, ValueError, RuntimeError) as error:
        print(json.dumps({"outcome": "blocked", "reason": str(error)}))
        return 1


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Run the frozen WGMMA matrix with bounded, sequential processor builds.

A formal run requires a clean committed source, all six variants, both backends,
and two launches of both fixture patterns. Use --development with --backend,
--variant or --case for a visibly partial or dirty-source investigation. Work and
output directories must be fresh. Build trees remain available for independent
review alongside identities, compiler records, kernel images, disassembly and logs.

Example::

    python3 ci/project/p02_wgmma_matrix.py run --tools-dir /tools \
        --host-bin /host/bin --work-dir /new/builds --output /new/evidence

--witness adds the passive metadata-scoreboard monitor only to sparse RTL. Its
observations, numerical results and paired performance have separate outcomes.
No invocation automatically accepts P02-A03 or closes P02.
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

from baseline_inventory import _digest, collect_source, hash_artifacts
from baseline_packet_contract import _stamp_defines
from baseline_process import GIB, MIB, LIMITATIONS as PROCESS_LIMITATIONS, run_bounded
from p02_matrix import (_now, _write_json, _resources, _source_ok, clean_environment,
                        resolve_paths, tool_inventory, _timeout)
from p02_wgmma_dependencies import dependency_headers
import p02_wgmma_fixture_oracle as oracle
from p02_wgmma_records import (_json, compare_pair, configuration, require,
                               validate_header_macros, validate_records, verify_output)


ROOT = Path(__file__).resolve().parents[2]
CONTRACT_ID = "p02-wgmma-processor-matrix-v1"
MANIFEST = "ci/project/p02_wgmma_matrix.json"
MANIFEST_SHA256 = "fdc3ea03364babc00892f7de31fb2f2053074bf1ea76cb605dfbe5c5ac31b002"
APP = "tests/regression/p02_wgmma"
BACKENDS = ("simx", "rtlsim")
VARIANTS = ("dense-fp16-ss", "dense-fp16-rs", "dense-bf16-ss", "dense-bf16-rs",
            "dense-fp16-ss-row-major-a", "sparse-fp16-ss")
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
SOURCE_ROOTS = ("sw/common", "sw/kernel", "sw/runtime", "sim/common", "sim/simx", "sim/rtlsim",
                "hw/rtl", "hw/dpi", APP, "tests/regression/sgemm_tcu_wg", "tests/regression/sgemm_tcu_wg_sp")
SOURCE_SUFFIXES = {".c", ".cc", ".cpp", ".h", ".hpp", ".S", ".s", ".sv", ".v", ".vh",
                   ".vi", ".mk", ".in", ".ld", ".sh", ".py", ".toml"}
LOADED_HELPERS = hash_artifacts(ROOT, sorted({
    Path(module.__file__).resolve().relative_to(ROOT).as_posix()
    for module in tuple(sys.modules.values())
    if getattr(module, "__file__", None) and Path(module.__file__).suffix == ".py"
    and Path(module.__file__).resolve().is_relative_to(ROOT / "ci/project")
}))
TOOLING = tuple(sorted({item["path"] for item in LOADED_HELPERS} | {
    MANIFEST, "ci/project/p02_wgmma_witness.py"}))
CORPUS = ("ci/project/fixtures/p02_wgmma_v1.json", APP + "/fixtures.h")
CONFIG_INPUTS = ("configure", "config.mk.in", "VERSION", ".gitmodules", "VX_config.toml",
                 "VX_types.toml", "sim/rtlsim/verilator.vlt.in")
LIMITATIONS = [
    "This packet does not automatically accept P02-A03 or close P02.",
    "Exact integer fixtures cover only the six declared WGMMA variants and fixed geometry.",
    "Numerical, metadata-witness and paired-performance outcomes are distinct obligations.",
    "A performance mismatch retains the original five-percent RTL-denominator threshold; no waiver is inferred.",
    "The optional witness observes ordering; it does not force backpressure or prove unobserved state coverage.",
    "Native rtlsim bypasses the AFU; no vendor hw_emu, physical FPGA or silicon result is claimed.",
    "Dependency libraries and external Ramulator headers are reused identified inputs; this runner never downloads or rebuilds them.",
    "Tool identities do not inventory every system header, support file or dynamic library.",
    "Logs and snapshots contain local paths and require review before publication.",
    *PROCESS_LIMITATIONS,
]


def source_snapshot(source):
    checkout = collect_source(source)
    names = set(TOOLING + CORPUS + COPIED + CONFIG_INPUTS)
    for directory in SOURCE_ROOTS:
        for path in (source / directory).rglob("*"):
            if path.is_file() and (path.suffix in SOURCE_SUFFIXES or path.name == "Makefile"):
                names.add(path.relative_to(source).as_posix())
    for name in checkout["changed_paths"] + checkout["untracked_paths"]:
        if (source / name).is_file():
            names.add(name)
    return {"checkout": checkout, "files": hash_artifacts(source, sorted(names))}


def load_inputs(source):
    """Require the reviewed manifest and reproduce its independently frozen data."""
    require(_digest(source / MANIFEST)[0] == MANIFEST_SHA256, "matrix manifest differs from the frozen contract")
    manifest = _json((source / MANIFEST).read_text(encoding="utf-8"))
    require(manifest["contract_id"] == CONTRACT_ID and manifest["profile"] == ""
            and manifest["backends"] == list(BACKENDS) and manifest["iterations"] == 2,
            "manifest processor selection is unsupported")
    require(tuple(item["id"] for item in manifest["variants"]) == VARIANTS, "manifest variant inventory differs")
    require(hash_artifacts(source, [item["path"] for item in manifest["fixture_inputs"]]) ==
            manifest["fixture_inputs"], "fixture producer, JSON or header differs from the frozen manifest")
    document = oracle.fixture_document()
    require((source / CORPUS[0]).read_bytes() == (json.dumps(document, indent=2) + "\n").encode()
            and (source / CORPUS[1]).read_bytes() == oracle.header_bytes(document),
            "independent fixture corpus or header does not reproduce")
    cases = {case["id"]: case for case in document["cases"]}
    require(len(cases) == len(document["cases"]) == 6, "fixture inventory differs")
    for variant in manifest["variants"]:
        flags = manifest["configs"] + variant["configs"]
        require(all(re.fullmatch(r"-D[A-Za-z_][A-Za-z0-9_]*(?:=[A-Za-z0-9_]+)?", flag)
                    for flag in flags), "manifest has unsafe configuration flags")
        configuration(_stamp_defines(" ".join(flags + ["-DVX_CFG_TCU_TYPE_TFR=1", "-DVX_CFG_FPU_TYPE_STD=1"]),
                                    "manifest flags"), variant, "manifest")
        require(len(variant["cases"]) == len(set(variant["cases"])) == 2, "variant needs two distinct patterns")
        for name in variant["cases"]:
            require(name in cases and cases[name]["format"] == variant["format"]
                    and cases[name]["sparse"] == variant["sparse"], "variant fixture binding differs")
    return manifest, cases


def select_variants(manifest, cases, args):
    for values, label in ((args.backend, "backend"), (args.variant, "variant"), (args.case, "case")):
        require(values is None or len(values) == len(set(values)), "duplicate " + label + " selection")
    backends = args.backend or list(BACKENDS)
    variants = args.variant or list(VARIANTS)
    requested = set(args.case) if args.case is not None else None
    require(requested is None or requested <= cases.keys(), "unknown fixture selection")
    selected = []
    for driver in BACKENDS:
        for variant in manifest["variants"]:
            if driver not in backends or variant["id"] not in variants:
                continue
            chosen = [name for name in variant["cases"] if requested is None or name in requested]
            if chosen:
                selected.append((driver, variant, chosen))
    require(selected and (requested is None or {name for _, _, names in selected for name in names} == requested),
            "empty selection or incompatible fixture and variant selection")
    full = len(selected) == 12 and all(len(names) == 2 for _, _, names in selected)
    require(args.development or full, "partial matrices require explicit --development")
    require(not args.witness or any(driver == "rtlsim" and variant["sparse"] for driver, variant, _ in selected),
            "--witness requires a selected sparse RTL variant")
    return selected, full


def generated_identity(build, source, tools):
    text = (build / "config.mk").read_text(encoding="utf-8")
    for name, expected in (("XLEN", "64"), ("PROFILE", ""), ("VORTEX_HOME", str(source)),
                           ("TOOLDIR", str(tools)), ("OSVERSION", "ubuntu/focal")):
        matches = re.findall(r"^" + name + r"[ \t]*\?=[ \t]*(.*?)[ \t]*$", text, re.MULTILINE)
        require(matches == [expected], "generated config.mk has incorrect " + name)
    tokens = (build / ".config.stamp").read_text(encoding="utf-8").strip().split()
    fields = dict(token.split("=", 1) for token in tokens)
    require(len(fields) == len(tokens), "configure stamp repeats settings")
    for name, expected in (("XLEN", "64"), ("PROFILE", ""), ("SOURCE_DIR", str(source)),
                           ("BUILDDIR", str(build)), ("TOOLDIR", str(tools))):
        require(fields.get(name) == expected, "generated configure stamp has incorrect " + name)
    for name in COPIED:
        require((build / name).read_bytes() == (source / name).read_bytes(),
                "generated build input differs from source: " + name)
    expected = (source / "sim/rtlsim/verilator.vlt.in").read_text().replace("@VORTEX_HOME@", str(source))
    require((build / "sim/rtlsim/verilator.vlt").read_text() == expected, "Verilator configuration differs")
    return hash_artifacts(build, GENERATED + COPIED)


def build_artifacts(driver, build):
    fixed = GENERATED + COPIED + ("sw/runtime/" + driver + "_rt_config.stamp",
        "sw/runtime/" + driver + "_config.stamp", APP + "/config.stamp", APP + "/p02_wgmma",
        APP + "/kernel.elf", APP + "/kernel.vxbin", "sw/kernel/libvortex2.a",
        "sw/runtime/libvortex.so", "sw/runtime/libvortex-" + driver + ".so", "sw/runtime/lib" + driver + ".so")
    # Bind generated native hierarchy and actual compiler dependency records,
    # including source/header inputs omitted from the terse configuration stamp.
    metadata = set()
    for path in (build / "sw/runtime").rglob("*"):
        if path.is_file() and path.suffix in {".d", ".dat", ".mk", ".h", ".cpp"}:
            metadata.add(path.relative_to(build).as_posix())
    if driver == "rtlsim":
        native = "sw/runtime/librtlsim.so.obj_dir/Vrtlsim_shim"
        require(all(native + suffix in metadata for suffix in ("__verFiles.dat", "_classes.mk", "__Syms.h")),
                "generated native hierarchy metadata is incomplete")
    return fixed + tuple(sorted(metadata - set(fixed)))


def paired_comparisons(variants):
    grouped = {}
    for variant in variants:
        for case in variant["cases"]:
            if case.get("arithmetic_outcome", case["outcome"]) == "pass":
                grouped.setdefault((variant["configuration_id"], case["id"]), {})[variant["backend"]] = case
    paired, unpaired = [], []
    for (variant, case), backends in sorted(grouped.items()):
        if set(backends) == set(BACKENDS):
            paired.append(dict(variant=variant, case_id=case, **compare_pair(
                backends["simx"]["observations"]["launches"], backends["rtlsim"]["observations"]["launches"])))
        else:
            unpaired.append({"variant": variant, "case_id": case, "observed_backends": sorted(backends)})
    outcome = "not_run" if not paired else "pass" if all(item["outcome"] == "pass" for item in paired) else "fail"
    return {"outcome": outcome, "pairs": paired, "unpaired": unpaired,
            "metric": "per-launch deltas of cumulative retired-instruction and cycle counters",
            "cycle_tolerance_percent": 5, "automatic_waiver": False}


def execute_run(args, paths):
    output, work, source = paths["output"], paths["work"], paths["source"]
    output.mkdir(mode=0o700)
    report = {"schema_version": 1, "contract_id": CONTRACT_ID, "started_at": _now(), "state": "running",
              "outcome": "blocked", "reason": None, "development": args.development,
              "acceptance_claimed": False, "qualifies_P02_A03": False, "phase_complete": False,
              "arithmetic_outcome": "not_run", "witness_outcome": "not_run", "parity_outcome": "not_run",
              "paths": {name: str(path) if path else None for name, path in paths.items()},
              "budget": dict(BUDGET, jobs=args.jobs, build_timeout_seconds=args.timeout_seconds,
                             run_timeout_seconds=args.run_timeout_seconds, configure_timeout_seconds=120),
              "iterations": 2, "witness_requested": args.witness, "commands": [], "variants": [],
              "successful_build_trees_retained": not args.discard_builds, "limitations": LIMITATIONS}
    active_variant = active_case = initial_source = initial_tools = dependencies = initial_headers = None

    def checkpoint():
        _write_json(output / "report.json", report)

    def snapshot_json(name, value):
        relative = "snapshots/" + name + ".json"
        _write_json(output / relative, value)
        return hash_artifacts(output, [relative])[0]

    def copy_files(root, names, prefix):
        saved = []
        for name in sorted(set(names)):
            destination = output / prefix / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            original = root / name
            require(shutil.disk_usage(output).free - original.stat().st_size >= BUDGET["min_free_bytes"],
                    "retained artifact would breach the disk reserve")
            with original.open("rb") as incoming, destination.open("xb") as stream:
                shutil.copyfileobj(incoming, stream, length=MIB)
            saved.append(destination.relative_to(output).as_posix())
        return hash_artifacts(output, saved)

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
        require(dependency_headers(source) == initial_headers, "dependency headers changed during execution")
        checkpoint()

    try:
        for directory in ("logs", "snapshots", "artifacts"):
            (output / directory).mkdir()
        checkpoint()
        work.mkdir(mode=0o700)
        (work / "tmp").mkdir()
        (work / "home").mkdir()
        env = clean_environment(paths, args.jobs)
        report["resources_before"] = _resources(paths)
        require(all(value >= BUDGET["min_free_bytes"] for value in
                    report["resources_before"]["free_disk_bytes"].values()), "disk reserve is below 15 GiB")
        memory = report["resources_before"]["available_memory_bytes"]
        require(memory is not None and memory >= BUDGET["max_rss_bytes"], "at least 6 GiB available memory is required")
        require(hash_artifacts(source, [item["path"] for item in LOADED_HELPERS]) == LOADED_HELPERS,
                "executing runner/helper bytes changed after import")
        report["loaded_helpers"] = LOADED_HELPERS
        initial_source = source_snapshot(source)
        report["source_before"] = snapshot_json("source-before", initial_source)
        _source_ok(initial_source, args.development)
        manifest, cases = load_inputs(source)
        selected, full = select_variants(manifest, cases, args)
        backends = sorted({driver for driver, _, _ in selected})
        selected_ids = sorted({name for _, _, names in selected for name in names})
        expected_cases = sum(len(names) for _, _, names in selected)
        report.update(full_matrix_requested=full, manifest=hash_artifacts(source, [MANIFEST])[0],
                      source_revision=initial_source["checkout"]["revision"],
                      source_dirty=initial_source["checkout"]["dirty"], source_frozen_before_execution=True,
                      case_ids=selected_ids, expected_case_executions=expected_cases,
                      expected_launches=2 * expected_cases, expected_checked_output_words=1024 * expected_cases,
                      expected_witness_case_executions=sum(len(names) for driver, variant, names in selected
                          if args.witness and driver == "rtlsim" and variant["sparse"]),
                      full_matrix_counts=manifest["expected_counts"], corpus=manifest["fixture_inputs"])
        report["fixture_snapshot"] = snapshot_json("selected-fixtures", [cases[name] for name in selected_ids])
        witness_parser = None
        if args.witness:
            from p02_wgmma_witness import verify_witness
            witness_parser = verify_witness
            report["witness_parser"] = hash_artifacts(source, ["ci/project/p02_wgmma_witness.py"])[0]
        initial_tools = tool_inventory(paths, env, backends)
        report["tools_before"] = snapshot_json("tools-before", initial_tools)
        dependencies = hash_artifacts(source, DEPENDENCIES)
        report["dependencies_before"] = dependencies
        initial_headers = dependency_headers(source)
        report["dependency_headers_before"] = initial_headers
        saved_sources = list(TOOLING + CORPUS + COPIED + CONFIG_INPUTS)
        for directory in (APP, "tests/regression/sgemm_tcu_wg", "tests/regression/sgemm_tcu_wg_sp"):
            saved_sources += [path.relative_to(source).as_posix() for path in (source / directory).iterdir()
                              if path.is_file() and (path.suffix in SOURCE_SUFFIXES or path.name == "Makefile")]
        if args.witness:
            saved_sources.append(manifest["witness"]["source"])
        report["source_snapshots"] = copy_files(source, saved_sources, "artifacts/source")
        require([dict(row, path=row["path"].removeprefix("artifacts/source/"))
                 for row in report["source_snapshots"]] ==
                sorted((row for row in initial_source["files"] if row["path"] in saved_sources),
                       key=lambda row: row["path"]),
                "retained source bytes differ from the initial snapshot")
        checkpoint()
        for name in ("g++", "make", "clang", "riscv-gcc") + (("verilator",) if "rtlsim" in backends else ()):
            command("version-" + name.replace("+", "p"), [initial_tools[name]["path"], "--version"], work, env, 30)
        make = [initial_tools["make"]["path"], "--no-print-directory", "-j" + str(args.jobs),
                "THREADS=" + str(args.jobs), "VERILATOR_PATH=" + str(paths["verilator"])]
        for driver, variant, names in selected:
            variant_id = driver + "-" + variant["id"]
            build = work / variant_id
            build.mkdir()
            witness = args.witness and driver == "rtlsim" and variant["sparse"]
            flags = manifest["configs"] + variant["configs"] + ([manifest["witness"]["flag"]] if witness else [])
            current = dict(env, CONFIGS=" ".join(flags), **manifest["performance"]["environment"])
            active_variant = {"id": variant_id, "backend": driver, "configuration_id": variant["id"],
                              "configuration": variant, "configs": flags, "profile": "", "witness": witness,
                              "build_dir": str(build), "outcome": "running", "cases": []}
            report["variants"].append(active_variant)
            stable(variant_id + "-before")
            command(variant_id + "-configure", [source / "configure", "--xlen=64", "--profile=",
                    "--osversion=ubuntu/focal", "--tooldir=" + str(paths["tools"])], build, env, 120)
            active_variant["generated_before"] = generated_identity(build, source, paths["tools"])
            check_dir = build / "p02-header-check"
            check_dir.mkdir()
            for language, relative in (("cpp", "sw/VX_config.h"), ("verilog", "hw/VX_config.vh")):
                destination = check_dir / Path(relative).name
                command(variant_id + "-" + language + "-header-reproduce", [initial_tools["python3"]["path"],
                    source / "ci/gen_config.py", "--config=" + str(source / "VX_config.toml"),
                    "--profile=", "--format=" + language, "--output=" + str(destination)],
                    build, dict(env, XLEN="64"), 30)
                require(destination.read_bytes() == (build / relative).read_bytes(), "configuration header did not reproduce")
            app = build / APP
            command(variant_id + "-runtime", make + ["runtime-" + driver], app, current, args.timeout_seconds)
            command(variant_id + "-application-build", make + ["all"], app, current, args.timeout_seconds)
            active_variant["compiler_records"] = validate_records(
                (build / ("sw/runtime/" + driver + "_rt_config.stamp")).read_text(),
                (build / ("sw/runtime/" + driver + "_config.stamp")).read_text(),
                (app / "config.stamp").read_text(), driver=driver, variant=variant, source=source,
                build=build, jobs=args.jobs, witness=witness)
            arithmetic_record = active_variant["compiler_records"][1]
            effective = command(variant_id + "-effective-header", [initial_tools["g++"]["path"],
                "-E", "-dM", "-x", "c++", *arithmetic_record["macro_flags"], "-include",
                build / "sw/VX_config.h", "/dev/null"], build, env, 30)
            active_variant["effective_backend_configuration"] = validate_header_macros(
                (output / effective["log"]).read_text(), variant)
            disassembly = command(variant_id + "-kernel-disassembly", [initial_tools["llvm-objdump"]["path"],
                "-D", app / "kernel.elf"], app, env, 30)
            require((output / disassembly["log"]).stat().st_size > 0, "empty kernel disassembly")
            active_variant["kernel_disassembly"] = hash_artifacts(output, [disassembly["log"]])[0]
            baseline_artifacts = hash_artifacts(build, build_artifacts(driver, build))
            active_variant["artifacts_before"] = baseline_artifacts
            retained = [item["path"] for item in baseline_artifacts if
                        item["path"].endswith((".stamp", ".mk", ".h", ".vh", ".vlt", ".elf", ".vxbin", ".dat", ".d"))
                        or Path(item["path"]).name in ("Makefile", "p02_wgmma")]
            active_variant["retained_artifacts"] = copy_files(build, retained, "artifacts/" + variant_id)
            require([dict(row, path=row["path"].removeprefix("artifacts/" + variant_id + "/"))
                     for row in active_variant["retained_artifacts"]] ==
                    sorted((row for row in baseline_artifacts if row["path"] in retained),
                           key=lambda row: row["path"]),
                    "retained build artifacts differ from the built identities")
            stable(variant_id + "-built")
            for name in names:
                case = cases[name]
                active_case = {"id": name, "outcome": "running", "arithmetic_outcome": "not_run", "witness_outcome": "not_run"}
                active_variant["cases"].append(active_case)
                checkpoint()
                require(hash_artifacts(build, build_artifacts(driver, build)) == baseline_artifacts,
                        "build artifacts changed before launch")
                # Keep build commands verbose above.  A run target recursively
                # echoes CONFIGS containing P02_WGMMA_* defines unless make is
                # silent; those are not runtime records and the strict parser
                # correctly rejects their unframed marker text.
                entry = command(variant_id + "-" + name, make + ["--silent", "run-" + driver,
                    "OPTS=--case=" + name + " --iterations=2"], app, current, args.run_timeout_seconds)
                require(hash_artifacts(build, build_artifacts(driver, build)) == baseline_artifacts,
                        "build artifacts changed during launch")
                text = (output / entry["log"]).read_text(encoding="utf-8", errors="strict")
                active_case.update(command_id=entry["id"], arithmetic_outcome="running")
                active_case["observations"] = verify_output(text, case, variant, witness=witness)
                active_case.update(arithmetic_outcome="pass", outcome="pass")
                if witness:
                    try:
                        active_case["witness"] = witness_parser(text, require_wait=True)
                        active_case["witness_outcome"] = "pass"
                    except ValueError as error:
                        # Preserve exact numerical evidence even when observed
                        # metadata coverage or ordering fails its separate gate.
                        active_case.update(outcome="fail", witness_outcome="fail", witness_reason=str(error))
                active_case = None
                checkpoint()
            active_variant["artifacts_after"] = hash_artifacts(build, build_artifacts(driver, build))
            stable(variant_id + "-after")
            active_variant["outcome"] = "pass" if all(case["outcome"] == "pass"
                                                        for case in active_variant["cases"]) else "fail"
            if args.discard_builds and active_variant["outcome"] == "pass":
                require(build.parent == work and build.resolve(strict=True) == build, "unsafe generated-tree cleanup")
                shutil.rmtree(build)
                active_variant["build_tree_removed"] = True
            active_variant = None
            checkpoint()
        report["completed_case_executions"] = sum(len(item["cases"]) for item in report["variants"])
        require(report["completed_case_executions"] == expected_cases, "incomplete matrix execution count")
        report["arithmetic_outcome"] = "pass"
        report["witness_outcome"] = ("fail" if any(case["witness_outcome"] == "fail"
            for variant in report["variants"] for case in variant["cases"]) else "pass") if args.witness else "not_run"
        report["paired_performance"] = paired_comparisons(report["variants"])
        report["parity_outcome"] = report["paired_performance"]["outcome"]
        require(not full or len(report["paired_performance"]["pairs"]) == 12, "full matrix lacks paired cases")
        report["outcome"] = "pass"
        failures = []
        if report["parity_outcome"] == "fail":
            failures.append("paired retired-instruction or cycle parity differs")
        if report["witness_outcome"] == "fail":
            failures.append("metadata witness ordering or observed wait coverage failed")
        if failures:
            report.update(outcome="fail", reason="; ".join(failures) + "; arithmetic outcome retained separately")
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
        if initial_headers is not None:
            try:
                report["dependency_headers_after"] = dependency_headers(source)
                require(report["dependency_headers_after"] == initial_headers,
                        "dependency headers changed during execution")
            except (OSError, ValueError, RuntimeError) as error:
                report.update(outcome="fail", reason=str(error))
        all_cases = [case for variant in report["variants"] for case in variant["cases"]]
        for case in all_cases:
            if case["arithmetic_outcome"] == "running":
                case["arithmetic_outcome"] = "fail"
        passed = [case for case in all_cases if case["arithmetic_outcome"] == "pass"]
        if any(case["arithmetic_outcome"] == "fail" for case in all_cases):
            report["arithmetic_outcome"] = "fail"
        elif passed:
            report["arithmetic_outcome"] = "pass" if len(passed) == report.get("expected_case_executions") else "incomplete"
        if any(case["witness_outcome"] == "fail" for case in all_cases):
            report["witness_outcome"] = "fail"
        elif any(case["witness_outcome"] == "pass" for case in all_cases):
            witnessed = sum(case["witness_outcome"] == "pass" for case in all_cases)
            report["witness_outcome"] = "pass" if witnessed == report.get("expected_witness_case_executions") else "incomplete"
        report["verified_case_executions"] = len(passed)
        report["verified_launches"] = sum(case["observations"]["launch_count"] for case in passed)
        report["checked_output_words"] = sum(case["observations"]["checked_output_words"] for case in passed)
        report.update(state="finished", finished_at=_now())
        report["resources_after"] = _resources(paths)
        checkpoint()
    return report


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
    parser.add_argument("--variant", action="append", choices=VARIANTS)
    parser.add_argument("--case", action="append")
    parser.add_argument("--iterations", type=int, choices=(2,), default=2)
    parser.add_argument("--development", action="store_true", help="explicitly allow dirty-source or partial investigation")
    parser.add_argument("--witness", action="store_true", help="require passive metadata ordering and observed waits in sparse RTL")
    parser.add_argument("--discard-builds", action="store_true", help="explicitly remove successful generated trees after retaining selected evidence")
    parser.add_argument("--jobs", type=int, choices=(1, 2), default=2)
    parser.add_argument("--timeout-seconds", type=_timeout, default=1800)
    parser.add_argument("--run-timeout-seconds", type=_timeout, default=1800)
    return parser


def main(argv=None):
    args = argument_parser().parse_args(argv)
    try:
        report = execute_run(args, resolve_paths(args))
        print(json.dumps({"outcome": report["outcome"], "arithmetic_outcome": report["arithmetic_outcome"],
                          "parity_outcome": report["parity_outcome"], "witness_outcome": report["witness_outcome"],
                          "reason": report["reason"], "report": str(Path(args.output).absolute() / "report.json"),
                          "acceptance_claimed": False}, sort_keys=True))
        return 0 if report["outcome"] == "pass" else 1
    except (OSError, ValueError, RuntimeError) as error:
        print(json.dumps({"outcome": "blocked", "reason": str(error), "acceptance_claimed": False}, sort_keys=True))
        return 1


if __name__ == "__main__":
    sys.exit(main())

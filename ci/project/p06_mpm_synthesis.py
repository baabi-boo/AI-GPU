#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Retain paired MPM circuit measurements, without accepting synthesis gates.

Exit zero means all eight Beacon and eight generic Yosys measurements completed
and their identities remained stable. Original gate/diff exits are retained;
NO-BASELINE and regressions never become a passing gate or a phase acceptance.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import re
import shutil
import sys

sys.dont_write_bytecode = True

from baseline_inventory import _digest, _git, hash_artifacts
from baseline_process import GIB, MIB, LIMITATIONS as PROCESS_LIMITATIONS, run_bounded
from preflight import available_memory_bytes


ROOT = Path(__file__).resolve().parents[2]
REFERENCE = "4df7186edbca82b21b2b8cba9b3b192248b99209"
TOP = "VX_mpm_transport_synth_top"
OVERLAY = (
    "hw/unittest/mpm_transport/VX_mpm_transport_synth_top.sv",
    "hw/syn/xilinx/dut/catalog.mk", "hw/syn/yosys/dut/catalog.mk",
    "ci/testcases/logic_gate.yaml",
)
INPUTS = OVERLAY + (
    "configure", "config.mk.in", "VX_config.toml", "VX_types.toml", "vortex_opae.toml", "VERSION",
    "ci/project/p06_mpm_synthesis.py", "ci/project/baseline_inventory.py",
    "ci/project/baseline_process.py", "ci/project/preflight.py",
    "ci/gen_config.py", "ci/logic_gate.py", "ci/synth_gate.py", "ci/beacon.py",
    "hw/syn/common.mk", "hw/syn/xilinx/dut/Makefile", "hw/syn/xilinx/dut/build.mk",
    "hw/syn/yosys/Makefile", "hw/syn/yosys/dut/Makefile", "hw/syn/extensions.mk",
    "hw/scripts/gen_sources.sh", "hw/scripts/circt_elaborate.sh", "hw/scripts/ram_fold.py",
)
GENERATED = (".config.stamp", "config.mk", "sw/VX_config.h", "sw/VX_types.h",
             "sw/vortex_opae.h", "hw/VX_config.vh", "hw/VX_types.vh", "hw/vortex_opae.vh")
METRICS = ("max_levels", "lut", "ff", "lutram", "bram", "uram", "dsp")
BUDGET = {"max_rss_bytes": 4 * GIB, "min_free_bytes": 15 * GIB, "max_log_bytes": 16 * MIB}
LIMITATIONS = [
    "Measurement completion is not synthesis-gate acceptance; original NO-BASELINE and regression verdicts remain.",
    "The reference is the pinned production checkout with identical candidate test/catalog overlays only.",
    "Beacon estimates FPGA logic depth/resources for xcu55c; it does not establish placed timing.",
    "Yosys independently elaborates the canonical ASIC source set and maps generic gates with synth/ABC.",
    "Generic Yosys cells and longest topological path are not Liberty cell area, STA, Fmax or physical measurements.",
    "No physical Beacon calibration/validate claim is made from generic Yosys paths.",
    "The live registered wrapper covers cycles/instret and selected CORE slots, not the complete GPU or every class.",
    "Before/after identities do not defend against malicious concurrent filesystem writers.",
    "Binary hashes do not inventory every host dynamic library or installed Python package byte.",
    *PROCESS_LIMITATIONS,
]


def require(condition, message):
    if not condition:
        raise ValueError(message)


def identity(path):
    path = Path(path)
    resolved = path.resolve(strict=True)
    digest, size = _digest(resolved)
    return {"path": str(path), "resolved_path": str(resolved), "sha256": digest, "size_bytes": size}


def reference_checkout_argv(source, reference, git="git"):
    # A shallow clone can omit a fetched commit outside its advertised history.
    return [git, "-C", str(source), "worktree", "add", "--detach", str(reference), REFERENCE]


def source_identity(source, parent=False):
    names = [name for name in INPUTS if not parent or not name.startswith("ci/project/p06_mpm_")]
    names += sorted(path.relative_to(source).as_posix() for path in (source / "hw/rtl").rglob("*")
                    if path.is_file())
    return {"revision": _git(source, "rev-parse", "HEAD").decode().strip(),
            "tree": _git(source, "rev-parse", "HEAD^{tree}").decode().strip(),
            "status": _git(source, "status", "--porcelain=v1", "--untracked-files=all").decode(),
            "inputs": hash_artifacts(source, names)}


def tool_identity(tools, env):
    selected = {name: shutil.which(name, path=env["PATH"]) for name in ("make", "git", "python3", "bash")}
    selected["executing_python"] = sys.executable
    selected.update({name: tools / component / "bin" / name for component, name in (
        ("circt", "circt-opt"), ("circt", "circt-verilog"), ("foldsim", "foldsim-opt"),
        ("yosys", "yosys"), ("yosys", "yosys-abc"))})
    for name, path in selected.items():
        require(path is not None and os.access(path, os.X_OK), "missing executable: " + name)
    return {name: identity(path) for name, path in selected.items()}


def paths_for(args):
    paths = {name: Path(os.path.abspath(value)) for name, value in (
        ("source", args.source_dir), ("tools", args.tools_dir), ("work", args.work_dir), ("output", args.output))}
    for name, path in paths.items():
        require(path.resolve() == path and re.fullmatch(r"[A-Za-z0-9_./+-]+", str(path)),
                name + " must be a safe literal path without symlink traversal")
    require(paths["source"] == ROOT and paths["source"].is_dir(), "run from the selected source checkout")
    require(paths["tools"].is_dir(), "tools directory missing")
    for name in ("work", "output"):
        path = paths[name]
        require(not os.path.lexists(path) and path.parent.is_dir(), name + " must be fresh with an existing parent")
        require(not any(path.is_relative_to(other) or other.is_relative_to(path)
                        for key, other in paths.items() if key != name), name + " overlaps another root")
    return paths


def yosys_script(filelist, destination):
    sources, includes, defines = [], [], []
    for line in filelist.read_text().splitlines():
        token = line.strip()
        if not token or token.startswith("#"):
            continue
        require(not re.search(r"[\s;\"'\\]", token), "unsupported generated filelist token")
        if token.startswith("+incdir+"):
            includes.append("-I" + token[8:])
        elif token.startswith("+define+"):
            defines.append("-D" + token[8:])
        else:
            require(Path(token).is_absolute() and Path(token).is_file(), "generated source missing")
            sources.append(token)
    require(sources, "empty synthesis source set")
    script = "read_slang --top " + TOP + " --ignore-assertions " + " ".join(includes + defines + sources) + "\n"
    script += "hierarchy -check -top " + TOP + "\nsynth -top " + TOP + " -flatten\n"
    script += "tee -o generic-stat.json stat -json\nltp -noff\nwrite_json generic-netlist.json\n"
    destination.write_text(script)
    return {"sources": [identity(name) for name in sources], "script": identity(destination)}


def read_yosys(directory, log):
    data = json.loads((directory / "generic-stat.json").read_text())
    modules = data.get("modules", {})
    require(len(modules) == 1, "generic Yosys result must be flattened to one module")
    module = next(iter(modules.values()))
    counts = module.get("num_cells_by_type")
    require(isinstance(counts, dict) and counts and all(type(v) is int and v >= 0 for v in counts.values()),
            "generic Yosys cell counts missing or malformed")
    require(module.get("num_cells") == sum(counts.values()), "generic Yosys total differs")
    depths = re.findall(r"longest topological path[^\n]*\(length\s*=\s*([0-9]+)\)", log, re.IGNORECASE)
    require(len(depths) == 1, "generic Yosys longest-path result missing or repeated")
    return {"cells": module["num_cells"], "cells_by_type": counts,
            "flip_flop_cells": sum(v for k, v in counts.items() if "DFF" in k),
            "longest_topological_path": int(depths[0]), "technology": "generic gates; no Liberty/STA"}


def execute(args, paths):
    source, tools, work, output = (paths[key] for key in ("source", "tools", "work", "output"))
    report = {"schema_version": 1, "scope": "paired-host-mpm-circuit-measurements", "state": "running",
              "started_at": datetime.now(timezone.utc).isoformat(), "outcome": "blocked",
              "measurements_complete": False, "gate_outcome": "not_run", "acceptance_claimed": False,
              "qualified": False, "reference_revision": REFERENCE, "commands": [], "measurements": [],
              "comparisons": [], "limitations": LIMITATIONS, "budget": dict(BUDGET, jobs=2, threads=1)}
    output.mkdir(mode=0o700)
    (output / "logs").mkdir()
    initial_source = initial_tools = parent_before = None
    parent = work / "reference"
    env = {"PATH": os.environ.get("PATH", os.defpath), "LANG": "C", "LC_ALL": "C", "TZ": "UTC",
           "PYTHONDONTWRITEBYTECODE": "1", "PYTHONUTF8": "1", "TOOLDIR": str(tools),
           "MAKEFLAGS": "-j2", "THREADS": "1", "CCACHE_DISABLE": "1", "OBJCACHE": "",
           "DEVICE": "xcu55c-fsvh2892-2L-e"}

    def checkpoint():
        temporary = output / "report.json.tmp"
        temporary.write_text(json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n")
        temporary.replace(output / "report.json")

    def command(name, argv, cwd, timeout=600, allowed=(0,)):
        entry = {"id": name, "argv": list(map(str, argv)), "cwd": str(cwd),
                 "log": "logs/" + name + ".log", "timeout_seconds": timeout}
        report["commands"].append(entry)
        checkpoint()
        entry.update(run_bounded(entry["argv"], cwd, env, output / entry["log"],
                                 timeout_seconds=timeout, resource_paths=(source, tools, work, output), **BUDGET))
        checkpoint()
        require(entry["cleanup_complete"] and entry["process_started"] and entry["exit_code"] in allowed
                and entry["reason"] in (None, "nonzero_exit"), name + " failed: " + str(entry["reason"]))
        return entry

    def retain(directory, names, prefix):
        retained = []
        for name in names:
            src = directory / name
            if not src.is_file():
                continue
            target = output / "artifacts" / prefix / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, target)
            require(_digest(src) == _digest(target), "retained artifact differs")
            retained.append(target.relative_to(output).as_posix())
        return hash_artifacts(output, retained)

    def stable():
        require(source_identity(source) == initial_source, "candidate source changed")
        require(tool_identity(tools, env) == initial_tools, "tool identities changed")
        if parent_before:
            require(source_identity(parent, True) == parent_before, "reference source/overlay changed")

    try:
        checkpoint()
        work.mkdir(mode=0o700)
        report["environment"] = env
        require(shutil.disk_usage(work).free >= 15 * GIB, "disk reserve below 15 GiB")
        memory = report["available_memory_bytes"] = available_memory_bytes()
        require(memory is not None and memory >= 4 * GIB, "at least 4 GiB available memory required")
        initial_source = report["source_before"] = source_identity(source)
        require(not initial_source["status"], "candidate source must be clean and tracked")
        require(_git(source, "cat-file", "-t", REFERENCE).decode().strip() == "commit", "fetch pinned reference first")
        initial_tools = report["tools_before"] = tool_identity(tools, env)
        command("python-packages", [sys.executable, "-c",
                "import json,yaml,pyslang; print(json.dumps({'yaml':yaml.__version__,'pyslang':pyslang.__version__}))"], work, 30)
        for tool in ("circt-verilog", "foldsim-opt", "yosys"):
            command("version-" + tool, [initial_tools[tool]["path"], "--version"], work, 30)
        command("reference-checkout", reference_checkout_argv(source, parent), work, 120)
        require(_git(parent, "rev-parse", "HEAD").decode().strip() == REFERENCE, "reference revision differs")
        for name in OVERLAY:
            target = parent / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source / name, target)
        require(hash_artifacts(source, OVERLAY) == hash_artifacts(parent, OVERLAY), "reference overlay differs")
        production = "hw/rtl/core/VX_csr_mpm.sv"
        require((parent / production).read_bytes() == _git(source, "show", REFERENCE + ":" + production),
                "reference production decoder differs from pinned source")
        parent_before = report["reference_before"] = source_identity(parent, True)
        # Finish every Beacon pair before beginning the independent Yosys confirmation.
        for xlen in (32, 64):
            for perf in ("off", "on"):
                pair = []
                for label, checkout in (("parent", parent), ("candidate", source)):
                    name = f"{label}-rv{xlen}-{perf}"
                    build = work / name
                    build.mkdir()
                    configure = [checkout / "configure", "--xlen=" + str(xlen), "--profile=", "--tooldir=" + str(tools)]
                    if args.osversion:
                        configure.append("--osversion=" + args.osversion)
                    stable()
                    command(name + "-configure", configure, build, 120)
                    config = (build / "config.mk").read_text()
                    expected = {"XLEN": str(xlen), "PROFILE": "", "VORTEX_HOME": str(checkout), "TOOLDIR": str(tools)}
                    if args.osversion:
                        expected["OSVERSION"] = args.osversion
                    for key, value in expected.items():
                        require(re.findall(r"^" + key + r"[ \t]*\?=[ \t]*(.*?)[ \t]*$", config, re.MULTILINE) == [value],
                                "generated configuration differs: " + key)
                    item = {"id": name, "side": label, "xlen": xlen, "perf": perf, "build_dir": str(build),
                            "generated_before": hash_artifacts(build, GENERATED),
                            "configuration": retain(build, GENERATED, name)}
                    report["measurements"].append(item)
                    build_id = f"mpm_transport_rv{xlen}_{perf}"
                    raw_report = output / (name + "-beacon.json")
                    argv = [sys.executable, checkout / "ci/logic_gate.py", "-b", build_id, "-j", "1",
                            "--tool-jobs", "2", "--build-dir", build, "--timeout", "600", "--report", raw_report]
                    if label == "candidate":
                        argv += ["--against", work / f"parent-rv{xlen}-{perf}"]
                    gate = command(name + "-beacon", argv, checkout, 900, allowed=(0, 1))
                    data = json.loads(raw_report.read_text())
                    rows = data.get("builds", [])
                    require(len(rows) == 1 and rows[0].get("id") == build_id and rows[0].get("xlen") == xlen,
                            "Beacon report configuration differs")
                    row = rows[0]
                    metrics = row.get("metrics")
                    require(row.get("error") is None and isinstance(metrics, dict)
                            and all(type(metrics.get(k)) in (int, float) and math.isfinite(metrics[k]) and metrics[k] >= 0 for k in METRICS)
                            and isinstance(metrics.get("units"), dict)
                            and type(metrics.get("endpoints")) is int and metrics["endpoints"] > 0,
                            "Beacon metrics missing or malformed")
                    require(row.get("configs") == ("-DPERF_ENABLE" if perf == "on" else ""), "Beacon PERF differs")
                    item["beacon"] = {"command": gate["id"], "exit_code": gate["exit_code"],
                                      "verdict": row["verdict"], "reasons": row["reasons"], "metrics": metrics}
                    leaf = build / "hw/syn/xilinx/dut" / ("logic_gate_" + build_id + "_mpm_transport")
                    required_reports = ("beacon/endpoints.csv", "beacon/report.txt", "beacon/area.csv",
                                        "beacon_summary.csv", "beacon_units.json", "beacon_area.txt")
                    require(all((leaf / name).is_file() and (leaf / name).stat().st_size > 0
                                for name in required_reports), "Beacon raw reports missing or empty")
                    item["beacon_dir"] = str(leaf / "beacon")
                    names = [p.relative_to(leaf).as_posix() for p in leaf.rglob("*") if p.is_file()
                             and p.suffix in (".txt", ".csv", ".json", ".log")]
                    item["beacon_artifacts"] = retain(leaf, names, name + "/beacon")
                    pair.append(item)
                comparison = {"id": f"rv{xlen}-{perf}", "parent": pair[0]["id"], "candidate": pair[1]["id"],
                              "beacon_deltas": {k: pair[1]["beacon"]["metrics"][k] - pair[0]["beacon"]["metrics"][k] for k in METRICS}}
                report["comparisons"].append(comparison)
                diff = command(comparison["id"] + "-beacon-diff", [sys.executable, source / "ci/beacon.py", "diff",
                    pair[0]["beacon_dir"], pair[1]["beacon_dir"], "--min-levels", str(pair[1]["beacon"]["metrics"].get("watch_levels") or 8),
                    "--fix-levels", str(pair[1]["beacon"]["metrics"].get("fix_levels") or 12)], source, 120, allowed=(0, 1, 3))
                comparison.update(diff_exit_code=diff["exit_code"], diff_command=diff["id"],
                                  regression={0: None, 1: "depth", 3: "area"}[diff["exit_code"]])
                stable()
        for item in report["measurements"]:
            name, build = item["id"], Path(item["build_dir"])
            command(name + "-yosys-sources", ["make", "-j2", "-C", build / "hw/syn/yosys/dut", "mpm_transport",
                "TARGET=gen-sources", "PREFIX=mpm_measure", "PDK=nangate45", "PERF=", "THREADS=1",
                "CONFIGS=" + ("-DPERF_ENABLE" if item["perf"] == "on" else "")], build, 600)
            circuit = build / "hw/syn/yosys" / ("mpm_measure_" + TOP)
            item["yosys_inputs"] = yosys_script(circuit / "sources.txt", circuit / "generic.ys")
            result = command(name + "-yosys", [initial_tools["yosys"]["path"], "-Q", "-T", "-s", circuit / "generic.ys"], circuit, 600)
            item["yosys"] = read_yosys(circuit, (output / result["log"]).read_text())
            item["yosys_artifacts"] = retain(circuit, ("sources.txt", "generic.ys", "generic-stat.json", "generic-netlist.json"), name + "/yosys")
            item["generated_after"] = hash_artifacts(build, GENERATED)
            require(item["generated_after"] == item["generated_before"], "generated configuration changed")
            stable()
        lookup = {item["id"]: item for item in report["measurements"]}
        for item in report["comparisons"]:
            ref, cur = lookup[item["parent"]]["yosys"], lookup[item["candidate"]]["yosys"]
            item["yosys_deltas"] = {key: cur[key] - ref[key] for key in ("cells", "flip_flop_cells", "longest_topological_path")}
        report["regressions"] = [item["id"] + ": " + item["regression"] for item in report["comparisons"] if item["regression"]]
        report["gate_outcome"] = "fail" if report["regressions"] else "not_passed"
        report["gate_note"] = "Original gate verdicts remain authoritative; no golden baseline was created or changed."
        report.update(outcome="measurements_complete", measurements_complete=True)
    except (OSError, ValueError, RuntimeError, KeyError, TypeError) as error:
        report.update(outcome="fail" if report["commands"] else "blocked", reason=str(error))
    except KeyboardInterrupt:
        report.update(outcome="fail", reason="interrupted")
    finally:
        for item in report["measurements"]:
            try:
                item["generated_after"] = hash_artifacts(Path(item["build_dir"]), GENERATED)
                require(item["generated_after"] == item["generated_before"], "generated configuration changed")
            except (OSError, ValueError, RuntimeError) as error:
                report.update(outcome="fail", measurements_complete=False, reason=str(error))
        for key, initial, observe in (("source", initial_source, lambda: source_identity(source)),
                                      ("tools", initial_tools, lambda: tool_identity(tools, env)),
                                      ("reference", parent_before, lambda: source_identity(parent, True))):
            if initial is not None:
                try:
                    report[key + "_after"] = observe()
                    require(report[key + "_after"] == initial, key + " identity changed")
                except (OSError, ValueError, RuntimeError) as error:
                    report.update(outcome="fail", measurements_complete=False, reason=str(error))
        report.update(state="finished", finished_at=datetime.now(timezone.utc).isoformat())
        checkpoint()
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, default=ROOT)
    parser.add_argument("--tools-dir", type=Path, required=True)
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--osversion")
    args = parser.parse_args(argv)
    try:
        require(args.osversion is None or re.fullmatch(r"[A-Za-z0-9_/-]+", args.osversion), "invalid OS bundle")
        paths = paths_for(args)
        report = execute(args, paths)
    except (OSError, ValueError, RuntimeError) as error:
        print("MPM circuit measurements blocked: " + str(error), file=sys.stderr)
        return 2
    print(json.dumps({"outcome": report["outcome"], "gate_outcome": report["gate_outcome"], "report": str(paths["output"] / "report.json")}))
    return 0 if report["measurements_complete"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Execute the reviewed tensor-harness matrix in fresh, bounded build trees."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys


WORK = Path(__file__).resolve().parent
SOURCE = WORK.parent / "AI-GPU"
TOOLS = WORK / "tools"
EXPECTED = "ca8686d668ed9f2ff733ce7e3c12dd458b9776d8"
sys.dont_write_bytecode = True
sys.path.insert(0, str(SOURCE / "ci/project"))
from baseline_process import GIB, MIB, run_bounded

BASE = ["-DSIMULATION", "-DSV_DPI", "-DVX_CFG_EXT_TCU_ENABLE",
        "-DVX_CFG_ISSUE_WIDTH=1"]
MX = ["-DUSE_FEDP", "-DVX_CFG_TCU_TF32_ENABLE", "-DVX_CFG_TCU_FP8_ENABLE",
      "-DVX_CFG_TCU_MX_ENABLE", "-DVX_CFG_TCU_FP4_ENABLE",
      "-DVX_CFG_TCU_MXFP4_ENABLE", "-DVX_CFG_TCU_NVFP4_ENABLE"]
INTEGER = ["-DVX_CFG_TCU_INT8_ENABLE", "-DVX_CFG_TCU_INT4_ENABLE"]
VARIANTS = [
    dict(id="wmma-rv32-t4-tfr", app="tcu_unit", xlen=32, threads=4, backend="TFR", flags=[], formats=[2, 3], tests=1000),
    dict(id="wmma-rv64-t4-tfr", app="tcu_unit", xlen=64, threads=4, backend="TFR", flags=[], formats=[2, 3], tests=1000),
    dict(id="wmma-rv64-t8-tfr", app="tcu_unit", xlen=64, threads=8, backend="TFR", flags=["-DVX_CFG_TCU_TF32_ENABLE"], formats=[1, 2, 3], tests=1000),
    dict(id="wmma-rv32-t8-dpi", app="tcu_unit", xlen=32, threads=8, backend="DPI", flags=["-DVX_CFG_TCU_TF32_ENABLE"], formats=[1, 2, 3], tests=1000),
    dict(id="fedp-rv64-n2-tfr-float", app="tcu_fedp", xlen=64, threads=4, backend="TFR", flags=MX, registers=2, sf=1, formats=[1, 2, 5, 8, 9, 10, 11], tests=100000),
    dict(id="fedp-rv64-n4-tfr-float", app="tcu_fedp", xlen=64, threads=4, backend="TFR", flags=MX, registers=4, sf=2, formats=[3, 4, 8, 9, 10, 11], tests=100000),
    dict(id="fedp-rv64-n2-tfr-integer", app="tcu_fedp", xlen=64, threads=4, backend="TFR", flags=INTEGER, registers=2, sf=1, formats=[17, 18, 19, 20], tests=100000),
    dict(id="fedp-rv32-n1-dpi-float", app="tcu_fedp", xlen=32, threads=4, backend="DPI", flags=["-DVX_CFG_TCU_TF32_ENABLE", "-DVX_CFG_TCU_FP8_ENABLE"], registers=1, sf=1, formats=[1, 2, 3, 4, 5], tests=1000),
    dict(id="fedp-rv32-n2-dpi-integer", app="tcu_fedp", xlen=32, threads=4, backend="DPI", flags=INTEGER, registers=2, sf=1, formats=[17, 18, 19, 20], tests=1000),
]
SOURCE_FILES = [
    "configure", "VERSION", "VX_config.toml", "VX_types.toml", "config.mk.in",
    "hw/unittest/common.mk", "hw/unittest/tcu_unit/Makefile", "hw/unittest/tcu_unit/main.cpp",
    "hw/unittest/tcu_fedp/Makefile", "hw/unittest/tcu_fedp/main.cpp",
    "hw/unittest/common/fp32_compare.h", "hw/unittest/common/int_dot_reference.h",
    "hw/unittest/common/tensor_exact_cases.h", "hw/unittest/common/tests/check_tensor_cli.py",
    "sw/common/fedp.h", "ci/project/baseline_process.py",
]
GENERATED = [".config.stamp", "config.mk", "sw/VX_config.h", "sw/VX_types.h",
             "hw/VX_config.vh", "hw/VX_types.vh"]


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def identity(path):
    path = Path(path)
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(MIB), b""):
            digest.update(chunk)
    return {"path": str(path), "sha256": digest.hexdigest(), "size_bytes": path.stat().st_size}


def git(*args):
    return subprocess.check_output(["git", "-C", str(SOURCE), *args], text=True, timeout=20).strip()


def source_guard(expected):
    if git("rev-parse", "HEAD") != expected:
        raise RuntimeError("source HEAD changed or differs from the frozen revision")
    if git("status", "--porcelain=v1", "--untracked-files=all"):
        raise RuntimeError("source checkout is not clean")


def configurations(variant):
    return BASE + ["-DVX_CFG_TCU_TYPE_" + variant["backend"],
                   "-DVX_CFG_NUM_THREADS=" + str(variant["threads"])] + variant["flags"]


def save(packet, report):
    destination = packet / "report.json"
    temporary = packet / "report.json.tmp"
    temporary.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    temporary.replace(destination)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-revision", default=EXPECTED)
    parser.add_argument("--output", type=Path, default=WORK / "final-matrix-ca8686d")
    parser.add_argument("--plan", action="store_true", help="print the fixed variant selection without creating outputs or running commands")
    args = parser.parse_args()
    if args.plan:
        print(json.dumps({"source": str(SOURCE), "expected_revision": args.expected_revision,
                          "variants": VARIANTS, "build_jobs": 2, "min_free_gib": 15,
                          "max_rss_gib": 6, "max_log_mib": 16}, indent=2))
        return 0
    if not re.fullmatch(r"[0-9a-f]{40}", args.expected_revision):
        parser.error("--expected-revision requires a full lowercase commit SHA")
    packet = args.output.absolute()
    if packet != packet.resolve() or packet.exists() or not packet.parent.is_dir():
        parser.error("--output must be a fresh canonical directory under an existing parent")
    if any(packet == item or packet.is_relative_to(item) or item.is_relative_to(packet)
           for item in (SOURCE, TOOLS)):
        parser.error("output must not overlap source or tools")
    source_guard(args.expected_revision)
    if shutil.disk_usage(packet.parent).free < 15 * GIB:
        raise RuntimeError("free disk is below the 15 GiB reserve")
    packet.mkdir()
    for name in ("builds", "logs", "tmp"):
        (packet / name).mkdir()
    environment = {"PATH": os.environ.get("PATH", os.defpath)}
    overrides = {"OBJCACHE": "", "CCACHE_DISABLE": "1", "TMPDIR": str(packet / "tmp"),
                 "PYTHONDONTWRITEBYTECODE": "1", "LC_ALL": "C"}
    environment.update(overrides)
    compilers = {role: shutil.which(role, path=environment.get("PATH")) for role in ("gcc", "g++", "make")}
    report = {
        "schema_version": 1, "id": "p01-tensor-oracle-native-matrix-v1", "started_at": now(),
        "outcome": "running", "phase_complete": False, "acceptance": "not_evaluated",
        "source": {"revision": args.expected_revision, "tree": git("rev-parse", "HEAD^{tree}"),
                   "clean": True, "submodules": git("submodule", "status", "--recursive").splitlines(),
                   "files": {name: identity(SOURCE / name) for name in SOURCE_FILES}},
        "runner": identity(Path(__file__)), "environment_overrides": overrides,
        "host_os_release": Path("/etc/os-release").read_text(),
        "configure_os_bundle": "ubuntu/focal", "variants": VARIANTS,
        "budgets": {"jobs": 2, "min_free_bytes": 15 * GIB, "max_rss_bytes": 6 * GIB,
                    "max_log_bytes": 16 * MIB, "build_timeout_seconds": 1200, "test_timeout_seconds": 120},
        "tools": {}, "builds": {}, "commands": [], "initial_free_disk_bytes": shutil.disk_usage(packet).free,
        "limitations": ["TFR unit results are native RTL arithmetic; DPI results are separately identified C-arithmetic compatibility tests.",
                        "These unit tests do not run the full AFU, vendor hw_emu, physical FPGA or silicon.",
                        "Random TFR comparisons share the TfrFedp reference; independent exact WMMA fixtures are recorded separately.",
                        "Resource budgets sample process groups, are not hard quotas, and may miss peaks or detached descendants.",
                        "All phase gates remain unchanged; passing this matrix grants no phase acceptance."],
    }
    save(packet, report)

    def command(identifier, argv, cwd, timeout=120, validator=None):
        source_guard(args.expected_revision)
        entry = {"id": identifier, "argv": [str(arg) for arg in argv], "cwd": str(cwd),
                 "started_at": now(), "outcome": "running", "log": str(packet / "logs" / (identifier + ".log"))}
        report["commands"].append(entry)
        save(packet, report)
        result = run_bounded(entry["argv"], cwd, environment, entry["log"], timeout_seconds=timeout,
                             min_free_bytes=15 * GIB, max_log_bytes=16 * MIB, max_rss_bytes=6 * GIB,
                             resource_paths=(packet, packet / "tmp"))
        entry.update(result)
        entry["finished_at"] = now()
        entry["free_disk_bytes"] = shutil.disk_usage(packet).free
        save(packet, report)
        print(json.dumps({"id": identifier, "outcome": result["outcome"], "reason": result["reason"],
                          "duration_seconds": result["duration_seconds"], "peak_rss_bytes": result["peak_rss_bytes"]}), flush=True)
        source_guard(args.expected_revision)
        if result["outcome"] != "pass" or not result["cleanup_complete"]:
            raise RuntimeError(identifier + ": command failed or cleanup incomplete")
        output = Path(entry["log"]).read_text()
        if validator is not None:
            try:
                entry["observed_checks"] = validator(output)
                entry["validation_outcome"] = "pass"
            except Exception as error:
                entry["process_outcome"] = entry["outcome"]
                entry["outcome"] = "fail"
                entry["validation_outcome"] = "fail"
                entry["validation_error"] = str(error)
                save(packet, report)
                raise
            save(packet, report)
        return output

    def numerical(variant, fmt, expected_count):
        def validate(output):
            if variant["app"] == "tcu_unit":
                expected = (20 if fmt in (2, 3) else 0,
                            2 if fmt == 2 and variant["threads"] == 4 else 0,
                            expected_count)
                counts = re.findall(r"^Coverage: exact=(\d+) modeled-directed=(\d+) random=(\d+)$", output, re.M)
                if len(counts) != 1 or tuple(map(int, counts[0])) != expected:
                    raise RuntimeError("WMMA success lacks the expected exact/modeled/random execution counts")
                return {"exact": expected[0], "modeled_directed": expected[1], "random": expected[2]}
            counts = re.findall(r"^(\d+) test\(s\) PASSED!$", output, re.M)
            if counts != [str(expected_count)]:
                raise RuntimeError("FEDP success lacks the expected actual execution count")
            return {"executed": expected_count}
        return validate

    try:
        for name, executable in compilers.items():
            if executable is None:
                raise RuntimeError("required host tool is missing: " + name)
            output = command("version-" + name.replace("+", "x"), [executable, "--version"], packet)
            report["tools"][name] = {**identity(Path(executable).resolve()), "lookup": executable,
                                     "version_first_line": output.splitlines()[0]}
        verilator = TOOLS / "verilator/bin/verilator"
        output = command("version-verilator", [verilator, "--version"], packet)
        report["tools"]["verilator"] = {**identity(verilator), "version_first_line": output.splitlines()[0]}
        report["tools"]["verilator_bin"] = identity(TOOLS / "verilator/bin/verilator_bin")
        report["tools"]["softfloat"] = identity(SOURCE / "third_party/softfloat/build/Linux-x86_64-GCC/softfloat.a")
        binaries = {}
        for variant in VARIANTS:
            build = packet / "builds" / variant["id"]
            build.mkdir()
            configs = configurations(variant)
            command(variant["id"] + "-configure", [SOURCE / "configure", "--xlen=" + str(variant["xlen"]),
                    "--tooldir=" + str(TOOLS), "--osversion=ubuntu/focal"], build)
            argv = [compilers["make"], "-j2", "-C", "hw/unittest/" + variant["app"],
                    "THREADS=2", "OBJCACHE=", "CC=" + compilers["gcc"], "CXX=" + compilers["g++"],
                    "XLEN=" + str(variant["xlen"]), "TOOLDIR=" + str(TOOLS),
                    "VORTEX_HOME=" + str(SOURCE), "THIRD_PARTY_DIR=" + str(SOURCE / "third_party"),
                    "VERILATOR_PATH=" + str(TOOLS / "verilator"),
                    "CONFIGS=" + " ".join(configs)]
            if variant["app"] == "tcu_fedp":
                argv += ["NUM_REGS=" + str(variant["registers"]), "SF=" + str(variant["sf"]), "USE_DSP=0"]
            command(variant["id"] + "-build", argv, build, timeout=1200)
            binary = build / "hw/unittest" / variant["app"] / variant["app"]
            binaries[variant["id"]] = binary
            objects = binary.parent / "obj_dir"
            report["builds"][variant["id"]] = {
                "configs": configs, "binary": identity(binary),
                "arithmetic": "native_tfr" if variant["backend"] == "TFR" else "dpi_c_arithmetic",
                "generated": {name: identity(build / name) for name in GENERATED},
                "generated_makefiles": {item.name: identity(item) for item in sorted(objects.glob("*.mk"))},
            }
            save(packet, report)
            for fmt in variant["formats"]:
                argv = [binary, "--fmt=" + str(fmt), "--tests=" + str(variant["tests"]), "--ulp=0", "--no-trace"]
                if variant["app"] == "tcu_fedp":
                    argv += ["--W=25"]
                    if variant["backend"] == "DPI" and fmt < 16:
                        argv += ["--no-fused"]
                command(variant["id"] + "-fmt" + str(fmt), argv, build,
                        validator=numerical(variant, fmt, variant["tests"]))
            if variant["id"] in ("wmma-rv64-t4-tfr", "fedp-rv64-n2-tfr-integer"):
                fmt, count, selected = (2, 1000, 999) if variant["app"] == "tcu_unit" else (17, 100, 50)
                argv = [binary, "--fmt=" + str(fmt), "--tests=" + str(count), "--test=" + str(selected),
                        "--W=25", "--ulp=0", "--no-trace"]
                command(variant["id"] + "-selected", argv, build, validator=numerical(variant, fmt, 1))

        def cli_counts(expected):
            def validate(output):
                if f"Total: {expected}/{expected} CLI checks passed; no numerical coverage claimed" not in output:
                    raise RuntimeError(f"CLI rejection matrix did not report all {expected} checks")
                return {"cli_checks": expected, "numerical_coverage": False}
            return validate

        command("tensor-cli-58", [sys.executable, SOURCE / "hw/unittest/common/tests/check_tensor_cli.py",
                "--wmma", binaries["wmma-rv64-t4-tfr"], "--fedp", binaries["fedp-rv64-n2-tfr-float"],
                "--wmma-tfr-no-tf32"], packet / "builds/wmma-rv64-t4-tfr", validator=cli_counts(58))
        command("fedp-cli-disabled-formats-37", [sys.executable, SOURCE / "hw/unittest/common/tests/check_tensor_cli.py",
                "--fedp", binaries["fedp-rv64-n2-tfr-integer"], "--fedp-no-tf32-fp8-mx"],
                packet / "builds/fedp-rv64-n2-tfr-integer", validator=cli_counts(37))
        source_guard(args.expected_revision)
        for name, before in report["source"]["files"].items():
            if identity(SOURCE / name) != before:
                raise RuntimeError("source file drifted: " + name)
        report["outcome"] = "pass"
    except (Exception, KeyboardInterrupt) as error:
        report["outcome"] = "fail"
        report["failure"] = type(error).__name__ + ": " + str(error)
        print(report["failure"], file=sys.stderr, flush=True)
    finally:
        report["finished_at"] = now()
        report["final_free_disk_bytes"] = shutil.disk_usage(packet).free
        report["highest_sampled_rss_bytes"] = max((entry.get("peak_rss_bytes", 0) for entry in report["commands"]), default=0)
        save(packet, report)
    return 0 if report["outcome"] == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())

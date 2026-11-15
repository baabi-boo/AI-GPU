#!/usr/bin/env python3
# Licensed under the Apache License, Version 2.0.
"""Read-only, offline prerequisite inventory; never a hardware certification."""

import argparse
import configparser
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys


TIERS = ("governance", "simulation", "fpga", "asic")
PIN_NAMES = ("VORTEX_VERSION", "TOOLCHAIN_REV", "GEM5_REV", "FIRESIM_REV")
ASSET_PATH = "docs/assets/img/vortex_framework_stack.svg"
ASSET_SHA256 = "db123c71024f85f379c2504c7465c03ee9df8959a5d17fc3d3e94a94a1cd3aa4"
GIB = 1024 ** 3
GIT_COMMANDS = (
    ("rev-parse", "--show-toplevel"),
    ("rev-parse", "--verify", "HEAD"),
    ("status", "--porcelain", "--untracked-files=no"),
    ("submodule", "status", "--recursive"),
)
TOOL_GROUPS = {
    "git": ("git",),
    "make": ("make",),
    "host_cxx": ("g++", "clang++"),
    "cmake": ("cmake",),
    "riscv_compiler": ("riscv64-unknown-elf-gcc", "riscv32-unknown-elf-gcc"),
    "llvm_clang": ("clang",),
    "verilator": ("verilator",),
    "vivado": ("vivado",),
    "vitis_linker": ("v++",),
    "xrt_inventory": ("xbutil",),
    "yosys": ("yosys",),
    "circt_verilog": ("circt-verilog",),
    "circt_opt": ("circt-opt",),
    "firtool": ("firtool",),
}
SIMULATION_TOOLS = {
    "git", "make", "host_cxx", "cmake", "riscv_compiler", "llvm_clang", "verilator"
}
REQUIRED_TOOLS = {
    "governance": {"git"},
    "simulation": SIMULATION_TOOLS,
    "fpga": SIMULATION_TOOLS | {"vivado", "vitis_linker", "xrt_inventory"},
    "asic": SIMULATION_TOOLS | {"yosys", "circt_verilog", "circt_opt", "firtool"},
}


def run_git(root, args):
    """Run only the bounded, local observations used by this inventory."""
    if tuple(args) not in GIT_COMMANDS:
        raise ValueError("unsupported Git observation")
    environment = os.environ.copy()
    environment["GIT_OPTIONAL_LOCKS"] = "0"
    try:
        result = subprocess.run(
            ["git", "--no-optional-locks", "-c", "core.fsmonitor=false",
             "-c", "core.untrackedCache=false", "-C", str(root), *args],
            capture_output=True, text=True, check=False, timeout=10,
            env=environment,
        )
    except (OSError, subprocess.TimeoutExpired, UnicodeError):
        return None, ""
    # Errors can contain local credential-bearing configuration; never print them.
    return result.returncode, result.stdout if result.returncode == 0 else ""


def read_pins(root):
    pins = {}
    errors = []
    try:
        root = Path(root).resolve()
        path = root / "VERSION"
        if not path.resolve().is_relative_to(root):
            return {}, ["VERSION resolves outside the source root"]
        contents = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError, RuntimeError):
        return {}, ["VERSION is missing or unreadable"]
    for line in contents.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, separator, value = line.partition("=")
        if not separator or key not in PIN_NAMES:
            errors.append("VERSION contains an unknown or malformed entry")
        elif key in pins:
            errors.append("VERSION contains duplicate pin " + key)
        elif not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._+-]*", value):
            errors.append("VERSION contains an invalid value for " + key)
        else:
            pins[key] = value
    for key in PIN_NAMES:
        if key not in pins:
            errors.append("VERSION is missing pin " + key)
    return pins, errors


def submodule_inventory(root):
    root = Path(root).resolve()
    errors = []
    declared = []
    parser = configparser.ConfigParser(interpolation=None)
    try:
        manifest = root / ".gitmodules"
        if not manifest.resolve().is_relative_to(root):
            return {"entries": [], "declared_count": 0,
                    "errors": [".gitmodules resolves outside the source root"]}
        parser.read_string(manifest.read_text(encoding="utf-8"))
        for section in parser.sections():
            path = parser.get(section, "path", fallback="")
            candidate = root / path
            if (not path or not re.fullmatch(r"[A-Za-z0-9_./-]+", path)
                    or Path(path).is_absolute() or ".." in Path(path).parts
                    or not candidate.resolve().is_relative_to(root)):
                errors.append(".gitmodules contains an invalid path")
            elif path in declared:
                errors.append(".gitmodules contains a duplicate path")
            else:
                declared.append(path)
    except (OSError, UnicodeError, configparser.Error, RuntimeError):
        errors.append(".gitmodules is missing, unreadable or malformed")
    code, output = run_git(root, ("submodule", "status", "--recursive"))
    entries = []
    statuses = {" ": "initialized", "-": "not_initialized", "+": "revision_mismatch", "U": "conflict"}
    if code != 0:
        errors.append("submodule status unavailable")
    else:
        for line in output.splitlines():
            match = re.fullmatch(r"([ +\-U])([0-9a-fA-F]{40}) ([A-Za-z0-9_./-]+)(?: .*)?", line)
            if not match:
                errors.append("unrecognized submodule status output")
                continue
            marker, revision, path = match.groups()
            if Path(path).is_absolute() or ".." in Path(path).parts:
                errors.append("unsafe path in submodule status")
                continue
            entries.append({"path": path, "revision": revision.lower(), "status": statuses[marker]})
        observed = {entry["path"] for entry in entries}
        if any(path not in observed for path in declared):
            errors.append("submodule status omitted a declared submodule")
    return {"entries": entries, "declared_count": len(declared), "errors": errors}


def tool_inventory(tier):
    return {
        name: {
            "candidates": list(candidates),
            "available": any(shutil.which(candidate) is not None for candidate in candidates),
            "required": name in REQUIRED_TOOLS[tier],
        }
        for name, candidates in TOOL_GROUPS.items()
    }


def available_memory_bytes():
    """Return Linux MemAvailable, not total installed RAM or a guessed substitute."""
    try:
        for line in Path("/proc/meminfo").read_text(encoding="ascii").splitlines():
            match = re.fullmatch(r"MemAvailable:\s+(\d+)\s+kB", line)
            if match:
                return int(match.group(1)) * 1024
    except (OSError, UnicodeError):
        pass
    return None


def asset_integrity(root):
    root = Path(root).resolve()
    path = root / ASSET_PATH
    actual = None
    try:
        if path.resolve().is_relative_to(root) and path.is_file():
            digest = hashlib.sha256()
            with path.open("rb") as stream:
                for chunk in iter(lambda: stream.read(65536), b""):
                    digest.update(chunk)
            actual = digest.hexdigest()
    except (OSError, RuntimeError):
        pass
    return {"path": ASSET_PATH, "expected_sha256": ASSET_SHA256,
            "actual_sha256": actual, "matches": actual == ASSET_SHA256}


def collect_preflight(root, tier="governance", min_free_gib=None):
    root = Path(root).resolve()
    blockers = []
    warnings = []
    if tier not in TIERS:
        raise ValueError("unknown preflight tier")
    try:
        threshold_valid = (min_free_gib is None or (
            type(min_free_gib) in (int, float) and math.isfinite(min_free_gib) and min_free_gib >= 0))
    except OverflowError:
        threshold_valid = False
    if not threshold_valid:
        blockers.append("minimum free disk must be a finite nonnegative GiB value")
    if not root.is_dir():
        blockers.append("source root is not a directory")
    if sys.version_info < (3, 10):
        blockers.append("Python 3.10 or newer is required")

    tools = tool_inventory(tier)
    for name, item in tools.items():
        if item["required"] and not item["available"]:
            blockers.append("required PATH tool missing: " + name)
    pins, pin_errors = read_pins(root)
    blockers.extend(pin_errors)
    code, toplevel = run_git(root, ("rev-parse", "--show-toplevel"))
    if code != 0 or Path(toplevel.strip()).resolve() != root:
        blockers.append("source root is not the top level of an accessible Git checkout")
    code, revision = run_git(root, ("rev-parse", "--verify", "HEAD"))
    revision = revision.strip()
    if code != 0 or not re.fullmatch(r"[0-9a-fA-F]{40}", revision):
        revision = None
        blockers.append("exact source revision unavailable")
    code, dirty = run_git(root, ("status", "--porcelain", "--untracked-files=no"))
    tracked_changes = bool(dirty) if code == 0 else None
    if code != 0:
        warnings.append("tracked working-tree status unavailable")
    elif tracked_changes:
        warnings.append("tracked working-tree changes exist; HEAD alone does not identify the tested tree")

    submodules = submodule_inventory(root)
    unresolved = [entry for entry in submodules["entries"] if entry["status"] != "initialized"]
    if tier == "governance":
        if submodules["errors"] or unresolved:
            warnings.append("submodules are not fully verified/initialized; not required for governance")
    else:
        blockers.extend(submodules["errors"])
        for entry in unresolved:
            blockers.append("submodule " + entry["path"] + ": " + entry["status"])

    asset = asset_integrity(root)
    if not asset["matches"]:
        blockers.append("protected README illustration is missing or has changed")
    free_disk = None
    try:
        free_disk = shutil.disk_usage(root).free
    except OSError:
        warnings.append("free disk space unavailable")
    available_ram = available_memory_bytes()
    if available_ram is None:
        warnings.append("available RAM unknown on this host")
    if threshold_valid and min_free_gib is not None:
        if free_disk is None:
            blockers.append("cannot verify requested minimum free disk")
        elif free_disk / GIB < min_free_gib:
            blockers.append("free disk is below the requested minimum")
    if tier != "governance" and (free_disk is None or available_ram is None):
        blockers.append("execution-tier resource inventory is incomplete")

    limitations = [
        "Read-only offline prerequisite screen; no installer, download, build, test workload or cleanup ran.",
        "Tool availability means executable names are on PATH, not verified versions or Vortex target support.",
        "Configured tools outside PATH are not searched; activate the intended environment before this screen.",
        "Toolchain tags are source pins, not verification of installed binaries, libraries or bundle hashes.",
        "Working-tree status covers tracked files only; inventory untracked inputs before recording evidence.",
        "Resource values are a snapshot, not a build budget; nested builds may exceed an outer job limit.",
        "Linux MemAvailable may describe host RAM rather than a container/cgroup limit; verify the effective allocation separately.",
        "No board, license, platform, PDK, IP, physical measurement, funding or manufacturing approval is certified.",
    ]
    if tier == "fpga":
        limitations.append("FPGA tool screen covers the Xilinx/XRT route only; no FPGA board has been selected or probed.")
    if tier == "simulation":
        limitations.append("Simulation tool screen combines native SimX and processor RTL prerequisites; it is not a SimX-only minimum.")
    if tier == "asic":
        limitations.append("ASIC tool screen covers the inherited Yosys/CIRCT analysis route, not foundry-qualified sign-off.")
    return {
        "schema_version": 1,
        "tier": tier,
        "outcome": "blocked" if blockers else "pass",
        "source": {"revision": revision, "tracked_changes": tracked_changes,
                   "python_version": ".".join(str(part) for part in sys.version_info[:3])},
        "pins": pins,
        "submodules": submodules,
        "tools": tools,
        "resources": {"free_disk_bytes": free_disk, "available_ram_bytes": available_ram,
                      "minimum_free_gib": min_free_gib if threshold_valid else None},
        "asset": asset,
        "blockers": blockers,
        "warnings": warnings,
        "limitations": limitations,
    }


def disk_threshold(value):
    try:
        result = float(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("expected a finite nonnegative GiB value") from error
    if not math.isfinite(result) or result < 0:
        raise argparse.ArgumentTypeError("expected a finite nonnegative GiB value")
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--tier", choices=TIERS, default="governance")
    parser.add_argument("--json", action="store_true", dest="as_json")
    parser.add_argument("--min-free-gib", type=disk_threshold)
    args = parser.parse_args(argv)
    try:
        report = collect_preflight(args.root, args.tier, args.min_free_gib)
    except (OSError, RuntimeError, ValueError):
        report = {"schema_version": 1, "tier": args.tier, "outcome": "blocked",
                  "blockers": ["source inventory could not be read safely"]}
        if args.as_json:
            print(json.dumps(report, indent=2))
        else:
            print("Preflight: blocked (source inventory could not be read safely)")
        return 1
    if args.as_json:
        print(json.dumps(report, indent=2, sort_keys=True, allow_nan=False))
    else:
        print("Preflight: {} ({})".format(report["outcome"], report["tier"]))
        print("Source: {} (tracked changes: {})".format(
            report["source"]["revision"] or "unknown", report["source"]["tracked_changes"]))
        print("Pins: " + ", ".join(key + "=" + value for key, value in report["pins"].items()))
        for name, item in report["tools"].items():
            print("Tool {}: {}{}".format(name, "available" if item["available"] else "missing",
                                           " (required)" if item["required"] else " (optional)"))
        for item in report["submodules"]["entries"]:
            print("Submodule {}: {} {}".format(item["path"], item["status"], item["revision"]))
        print("Resources: free disk={} bytes; available RAM={} bytes".format(
            report["resources"]["free_disk_bytes"], report["resources"]["available_ram_bytes"]))
        print("Protected illustration: " + ("unchanged" if report["asset"]["matches"] else "FAILED"))
        for category in ("blockers", "warnings", "limitations"):
            for message in report[category]:
                print(category[:-1].capitalize() + ": " + message)
    return 0 if report["outcome"] == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())

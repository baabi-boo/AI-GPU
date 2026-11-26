#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Preparatory P08 reliability and release-hardening verification tools.

Provides three offline, read-only subcommands for P08-A01..A03:
  - sbom: inventory tracked files, submodules, licenses, packaging metadata,
    protected asset SHA-256, and proprietary/non-redistributable exclusions.
  - soak24-analyze: validate canonical 24-hour (>= 86400 s) physical soak logs.
  - fault-matrix-check: validate structured P08-A01 fault-injection records.

Creating or running this tool does not execute hardware tests or advance P08
past `not_started` in docs/project/roadmap.json.
"""

from __future__ import annotations

import argparse
import configparser
import hashlib
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import tomllib


ROOT = Path(__file__).resolve().parents[2]
PROTECTED_SVG_PATH = "docs/assets/img/vortex_framework_stack.svg"
PROTECTED_SVG_SHA256 = "db123c71024f85f379c2504c7465c03ee9df8959a5d17fc3d3e94a94a1cd3aa4"

MIN_SOAK_SECONDS = 86400
PHYSICAL_DRIVERS = frozenset({"xrt", "aved"})
NON_PHYSICAL_DRIVERS = frozenset({
    "simx", "rtlsim", "xrtsim", "avedsim", "gem5", "firesim", "foldsim", "opaesim", "stub", "null", "emulation",
})
NON_PHYSICAL_TARGETS = frozenset({
    "hw_emu", "sw_emu", "xrtsim", "avedsim", "simx", "rtlsim", "sim", "emu", "simulation",
})
ALLOWED_TELEMETRY_UNAVAILABLE = frozenset({"unavailable", "not_available"})

REQUIRED_FAULT_CLASSES = (
    "malformed_args",
    "resource_exhaustion",
    "error_propagation",
    "reset_recovery",
    "memory_isolation",
)
VALID_OUTCOMES = frozenset({"pass", "fail", "blocked", "not_run"})

KNOWN_THIRD_PARTY_LICENSES = {
    "third_party/cvfpu": "SolderPad-Hardware-0.51 / Apache-2.0",
    "third_party/softfloat": "BSD-3-Clause (Berkeley SoftFloat 3e)",
    "third_party/hardfloat": "BSD-3-Clause (Berkeley HardFloat 1)",
    "third_party/ramulator": "MIT (contains non-redistributable Micron files in verilog_verification/sources)",
    "third_party/cocogfx": "Upstream submodule (no top-level license file detected; verify before redistribution)",
}

PROPRIETARY_EXCLUSION_RULES = (
    (
        "micron_ramulator_verilog",
        "Non-redistributable Micron Technology, Inc. confidential/proprietary simulation collateral inside Ramulator",
        re.compile(r"(?:^|/)third_party/ramulator/verilog_verification/sources/(?!\.gitignore$).+", re.IGNORECASE),
    ),
    (
        "micron_keyword_header",
        "File content carries Micron confidential/proprietary or all-rights-reserved restriction",
        None,
    ),
    (
        "foundry_cln28_ip",
        "Proprietary ARM Physical IP / foundry memory compiler collateral",
        re.compile(r"^hw/syn/libs/cln28(?:hpm|hpc)/"),
    ),
    (
        "nangate_restricted_lib",
        "Restricted Nangate Open Cell Library collateral (verify redistribution terms)",
        re.compile(r"^hw/syn/libs/(?:NangateOpenCellLibrary_typical\.lib|NanGate_15nm_OCL\.db)$"),
    ),
)

PROPRIETARY_CONTENT_MARKERS = (
    b"MICRON TECHNOLOGY, INC. - CONFIDENTIAL AND PROPRIETARY",
    b"CONFIDENTIAL AND PROPRIETARY SOFTWARE OF ARM PHYSICAL IP",
    b"proprietary information of Nangate Inc.",
)


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        self.print_usage(sys.stderr)
        self.exit(2, f"{self.prog}: {message}\n")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _run_git(root: Path, args: list[str]) -> tuple[int, str]:
    env = os.environ.copy()
    env["GIT_OPTIONAL_LOCKS"] = "0"
    proc = subprocess.run(
        ["git", "--no-optional-locks", "-C", str(root), *args],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
        env=env,
    )
    return proc.returncode, proc.stdout


def _read_json_strict(path: Path) -> dict:
    def _reject_dup(pairs):
        out = {}
        for k, v in pairs:
            if k in out:
                raise ValueError(f"duplicate JSON key {k!r}")
            out[k] = v
        return out

    def _reject_const(val):
        raise ValueError(f"non-finite JSON constant {val!r}")

    raw = path.read_text(encoding="utf-8")
    data = json.loads(raw, object_pairs_hook=_reject_dup, parse_constant=_reject_const)
    if not isinstance(data, dict):
        raise ValueError(f"{path}: JSON root must be an object")
    return data


def _detect_license_kind(license_path: Path) -> str:
    if not license_path.is_file():
        return "missing"
    text = license_path.read_text(encoding="utf-8", errors="replace")
    if "Apache License" in text and "Version 2.0" in text:
        return "Apache-2.0"
    if "SolderPad Hardware License" in text or "SOLDERPAD" in text.upper():
        return "SolderPad-Hardware"
    if "MIT License" in text or "Permission is hereby granted, free of charge" in text:
        return "MIT"
    if "Redistribution and use in source and binary forms" in text:
        return "BSD-3-Clause"
    return "custom"


def _parse_gitmodules(root: Path) -> dict[str, dict]:
    gitmodules = root / ".gitmodules"
    result: dict[str, dict] = {}
    if not gitmodules.is_file():
        return result
    parser = configparser.ConfigParser(interpolation=None)
    parser.read_string(gitmodules.read_text(encoding="utf-8"))
    for section in parser.sections():
        path = parser.get(section, "path", fallback="").strip()
        url = parser.get(section, "url", fallback="").strip()
        if path:
            result[path] = {"path": path, "url": url}
    return result


def _submodule_commits(root: Path) -> dict[str, dict]:
    code, out = _run_git(root, ["ls-files", "--stage"])
    if code != 0:
        raise RuntimeError("git ls-files --stage failed")
    commits: dict[str, dict] = {}
    for line in out.splitlines():
        # Format: <mode> <oid> <stage>\t<path>
        meta, _, rel = line.partition("\t")
        parts = meta.split()
        if len(parts) >= 2 and parts[0] == "160000":
            commits[rel] = {"commit": parts[1].lower()}
    return commits


def _scan_proprietary_files(root: Path, tracked_files: list[str], scan_submodules: bool = True) -> list[dict]:
    flagged: list[dict] = []
    seen: set[str] = set()

    def _check_candidate(rel_path: str, abs_path: Path, origin: str) -> None:
        if rel_path in seen or not abs_path.is_file():
            return
        reasons: list[str] = []
        rule_ids: list[str] = []
        for rule_id, reason, pattern in PROPRIETARY_EXCLUSION_RULES:
            if pattern is not None and pattern.search(rel_path):
                rule_ids.append(rule_id)
                reasons.append(reason)
        if not rule_ids:
            # Inspect bounded header bytes on likely text/verilog/library files inside third_party/ or hw/syn/libs/
            if rel_path.startswith(("third_party/", "hw/syn/libs/")):
                try:
                    with abs_path.open("rb") as fh:
                        head = fh.read(4096)
                    for marker in PROPRIETARY_CONTENT_MARKERS:
                        if marker in head:
                            rule_ids.append("content_marker")
                            reasons.append(f"Header contains restricted marker: {marker.decode('ascii', errors='replace')}")
                            break
                except OSError:
                    pass
        if rule_ids:
            seen.add(rel_path)
            flagged.append({
                "path": rel_path,
                "origin": origin,
                "rules": rule_ids,
                "reasons": reasons,
                "redistributable": False,
                "exclude_from_release_bundles": True,
            })

    for rel in sorted(tracked_files):
        _check_candidate(rel, root / rel, "tracked_root")

    if scan_submodules:
        ramulator_dir = root / "third_party/ramulator"
        if ramulator_dir.is_dir():
            if (ramulator_dir / ".git").exists():
                code, sub_out = _run_git(ramulator_dir, ["ls-files"])
                sub_paths = sorted(sub_out.splitlines()) if code == 0 else []
            else:
                sub_paths = sorted(
                    p.relative_to(ramulator_dir).as_posix()
                    for p in ramulator_dir.rglob("*")
                    if p.is_file()
                )
            for sub_rel in sub_paths:
                rel = f"third_party/ramulator/{sub_rel}"
                _check_candidate(rel, root / rel, "submodule:third_party/ramulator")

    flagged.sort(key=lambda item: item["path"])
    return flagged


def generate_sbom(root: Path, *, check_bundle_paths: list[str] | None = None) -> dict:
    """Scan repository provenance, licenses, protected asset, and proprietary exclusions."""
    root = Path(root).resolve()
    if not root.is_dir():
        raise ValueError(f"Repository root does not exist: {root}")

    code, ls_out = _run_git(root, ["ls-files"])
    if code != 0:
        raise RuntimeError(f"git ls-files failed under {root}")
    tracked_files = sorted(line for line in ls_out.splitlines() if line)

    _, head_out = _run_git(root, ["rev-parse", "--verify", "HEAD"])
    head_commit = head_out.strip() or None

    license_file = root / "LICENSE"
    root_license_kind = _detect_license_kind(license_file)
    root_license_sha256 = _sha256_file(license_file) if license_file.is_file() else None

    svg_file = root / PROTECTED_SVG_PATH
    svg_exists = svg_file.is_file()
    svg_sha256 = _sha256_file(svg_file) if svg_exists else None
    svg_matches = svg_sha256 == PROTECTED_SVG_SHA256

    pyproject_path = root / "pyproject.toml"
    pyproject_meta: dict = {"present": pyproject_path.is_file()}
    if pyproject_path.is_file():
        pyproject_data = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
        project = pyproject_data.get("project", {})
        build_system = pyproject_data.get("build-system", {})
        pyproject_meta.update({
            "sha256": _sha256_file(pyproject_path),
            "name": project.get("name"),
            "version": project.get("version"),
            "license": project.get("license"),
            "requires_python": project.get("requires-python"),
            "dependencies": project.get("dependencies", []),
            "build_requires": build_system.get("requires", []),
        })

    gitmodules = _parse_gitmodules(root)
    sub_commits = _submodule_commits(root)
    submodules: list[dict] = []
    for path in sorted(set(gitmodules) | set(sub_commits)):
        sub_dir = root / path
        license_files = []
        if sub_dir.is_dir():
            for name in ("LICENSE", "LICENSE.apache", "LICENSE.solderpad", "COPYING", "COPYING.txt"):
                candidate = sub_dir / name
                if candidate.is_file():
                    license_files.append({
                        "path": f"{path}/{name}",
                        "kind": _detect_license_kind(candidate),
                        "sha256": _sha256_file(candidate),
                    })
        submodules.append({
            "path": path,
            "url": gitmodules.get(path, {}).get("url"),
            "gitlink_commit": sub_commits.get(path, {}).get("commit"),
            "checked_out": sub_dir.is_dir() and any(sub_dir.iterdir()) if sub_dir.is_dir() else False,
            "declared_license": KNOWN_THIRD_PARTY_LICENSES.get(path, "unknown"),
            "license_files": license_files,
        })

    third_party_entries = sorted(
        f for f in tracked_files if f.startswith("third_party/")
    )
    discovered_license_files = sorted(
        {
            f for f in tracked_files
            if any(tok in Path(f).name.upper() for tok in ("LICENSE", "COPYING", "NOTICE"))
        }
    )

    proprietary_exclusions = _scan_proprietary_files(root, tracked_files, scan_submodules=True)
    flagged_paths = {item["path"] for item in proprietary_exclusions}

    bundle_violations: list[str] = []
    if check_bundle_paths is not None:
        for candidate in check_bundle_paths:
            norm = candidate.strip().lstrip("./")
            if norm in flagged_paths or any(
                pattern is not None and pattern.search(norm)
                for _, _, pattern in PROPRIETARY_EXCLUSION_RULES
            ):
                bundle_violations.append(norm)

    top_level_counts: dict[str, int] = {}
    for rel in tracked_files:
        top = rel.split("/", 1)[0]
        top_level_counts[top] = top_level_counts.get(top, 0) + 1

    errors: list[str] = []
    if root_license_kind != "Apache-2.0":
        errors.append(f"Root LICENSE must be Apache-2.0, found {root_license_kind!r}")
    if not svg_exists:
        errors.append(f"Protected asset missing: {PROTECTED_SVG_PATH}")
    elif not svg_matches:
        errors.append(
            f"Protected asset SHA-256 mismatch for {PROTECTED_SVG_PATH}: "
            f"expected {PROTECTED_SVG_SHA256}, got {svg_sha256}"
        )
    if bundle_violations:
        errors.append(
            "Release bundle manifest includes non-redistributable/proprietary files: "
            + ", ".join(sorted(bundle_violations))
        )

    return {
        "schema_version": 1,
        "tool": "p08_release_tools.sbom",
        "phase_status_note": "Inventory only; does not grant P08 acceptance or release approval.",
        "source": {
            "root": str(root),
            "head_commit": head_commit,
            "tracked_file_count": len(tracked_files),
            "top_level_counts": dict(sorted(top_level_counts.items())),
        },
        "root_license": {
            "path": "LICENSE",
            "kind": root_license_kind,
            "sha256": root_license_sha256,
        },
        "protected_assets": [
            {
                "path": PROTECTED_SVG_PATH,
                "expected_sha256": PROTECTED_SVG_SHA256,
                "actual_sha256": svg_sha256,
                "verified": svg_matches,
            }
        ],
        "packaging": pyproject_meta,
        "submodules": submodules,
        "third_party_tracked": third_party_entries,
        "license_files": discovered_license_files,
        "proprietary_exclusions": proprietary_exclusions,
        "bundle_violations": sorted(bundle_violations),
        "outcome": "pass" if not errors else "fail",
        "errors": errors,
    }


def analyze_soak24(record: dict) -> dict:
    """Validate a canonical 24-hour (>= 86400 s) physical FPGA soak log record."""
    if not isinstance(record, dict):
        raise ValueError("Soak record must be a JSON object")

    errors: list[str] = []
    warnings: list[str] = []

    schema_version = record.get("schema_version")
    if type(schema_version) is not int or schema_version != 1:
        errors.append("schema_version must be integer 1")

    driver = record.get("driver")
    target = record.get("target")
    if not isinstance(driver, str) or not driver.strip():
        errors.append("driver must be a nonempty string")
    else:
        driver_norm = driver.strip().lower()
        if driver_norm in NON_PHYSICAL_DRIVERS or any(
            tok in driver_norm for tok in ("simx", "rtlsim", "xrtsim", "hw_emu", "emu")
        ):
            errors.append(
                f"driver {driver!r} is not physical FPGA hardware; simulation/emulation cannot satisfy P08-A02"
            )

    if not isinstance(target, str) or not target.strip():
        errors.append("target must be a nonempty string (expected 'hw' for physical XRT)")
    else:
        target_norm = target.strip().lower()
        if target_norm in NON_PHYSICAL_TARGETS or "emu" in target_norm or "sim" in target_norm:
            errors.append(
                f"target {target!r} is non-physical; P08-A02 requires physical hardware target (e.g., 'hw')"
            )

    if record.get("physical_hardware") is False:
        errors.append("physical_hardware cannot be false for P08-A02 soak")

    # Hardware provenance fields
    for field in ("board", "bitstream_sha256", "source_revision"):
        val = record.get(field)
        if not isinstance(val, str) or not val.strip():
            errors.append(f"{field} must be a nonempty string")
    bitstream_sha = record.get("bitstream_sha256")
    if isinstance(bitstream_sha, str) and not re.fullmatch(r"[0-9a-fA-F]{64}", bitstream_sha):
        errors.append("bitstream_sha256 must be a 64-hex SHA-256 digest")
    source_rev = record.get("source_revision")
    if isinstance(source_rev, str) and (
        not re.fullmatch(r"[0-9a-fA-F]{40}", source_rev) or source_rev == "0" * 40
    ):
        errors.append("source_revision must be a nonzero 40-hex commit identifier")

    achieved_clock = record.get("achieved_clock_mhz")
    if type(achieved_clock) not in (int, float) or not math.isfinite(achieved_clock) or achieved_clock <= 0:
        errors.append("achieved_clock_mhz must be a positive finite number")

    # Duration validation: must be >= 86400 seconds
    duration = record.get("duration_seconds")
    if type(duration) not in (int, float) or isinstance(duration, bool) or not math.isfinite(duration):
        errors.append("duration_seconds must be a finite number")
        duration_val = 0.0
    else:
        duration_val = float(duration)
        if duration_val < MIN_SOAK_SECONDS:
            errors.append(
                f"duration_seconds ({duration_val}) is below canonical 24-hour minimum ({MIN_SOAK_SECONDS} s)"
            )

    # Iterations & error accounting
    iterations = record.get("iterations_completed")
    if type(iterations) is not int or iterations <= 0:
        errors.append("iterations_completed must be a positive integer")

    unexplained = record.get("unexplained_errors")
    if type(unexplained) is not int or unexplained < 0:
        errors.append("unexplained_errors must be a non-negative integer")
    elif unexplained > 0:
        errors.append(f"unexplained_errors must be 0, observed {unexplained}")

    numerical_mismatches = record.get("numerical_mismatches", 0)
    if type(numerical_mismatches) is not int or numerical_mismatches < 0:
        errors.append("numerical_mismatches must be a non-negative integer")
    elif numerical_mismatches > 0:
        errors.append(f"numerical_mismatches must be 0, observed {numerical_mismatches}")

    hangs = record.get("hangs", 0)
    if type(hangs) is not int or hangs < 0:
        errors.append("hangs must be a non-negative integer")
    elif hangs > 0:
        errors.append(f"hangs must be 0, observed {hangs}")

    error_log = record.get("error_events", [])
    if not isinstance(error_log, list):
        errors.append("error_events must be a list")
    else:
        for idx, event in enumerate(error_log):
            if not isinstance(event, dict):
                errors.append(f"error_events[{idx}] must be an object")
                continue
            explained = event.get("explained")
            disposition = event.get("disposition")
            if explained is not True or not isinstance(disposition, str) or not disposition.strip():
                errors.append(
                    f"error_events[{idx}] is unexplained or lacks a disposition"
                )

    # Telemetry validation (thermal/power/memory)
    telemetry = record.get("telemetry")
    if not isinstance(telemetry, dict):
        errors.append("telemetry must be an object recording thermal, power, and memory data")
    else:
        for key in ("temperature_c", "power_w"):
            if key not in telemetry:
                errors.append(f"telemetry.{key} is required (numeric summary or 'unavailable')")
            else:
                val = telemetry[key]
                if isinstance(val, str):
                    if val.strip().lower() not in ALLOWED_TELEMETRY_UNAVAILABLE:
                        errors.append(
                            f"telemetry.{key} string value must be 'unavailable' or 'not_available', got {val!r}"
                        )
                    else:
                        warnings.append(f"telemetry.{key} explicitly marked {val!r}")
                elif isinstance(val, dict):
                    for stat_key in ("min", "max"):
                        stat_val = val.get(stat_key)
                        if (type(stat_val) not in (int, float) or isinstance(stat_val, bool)
                                or not math.isfinite(stat_val)):
                            errors.append(f"telemetry.{key}.{stat_key} must be a finite number")
                elif type(val) in (int, float) and not isinstance(val, bool) and math.isfinite(val):
                    pass
                else:
                    errors.append(f"telemetry.{key} has invalid type")

    # Issue disposition check
    dispositions = record.get("issue_dispositions")
    if dispositions is not None and not isinstance(dispositions, list):
        errors.append("issue_dispositions must be a list when provided")

    outcome = "pass" if not errors else "fail"
    return {
        "schema_version": 1,
        "tool": "p08_release_tools.soak24-analyze",
        "acceptance_id": "P08-A02",
        "outcome": outcome,
        "driver": driver,
        "target": target,
        "duration_seconds": duration_val,
        "min_required_seconds": MIN_SOAK_SECONDS,
        "iterations_completed": iterations if type(iterations) is int else None,
        "unexplained_errors": unexplained if type(unexplained) is int else None,
        "warnings": warnings,
        "errors": errors,
    }


def check_fault_matrix(record: dict) -> dict:
    """Validate structured P08-A01 fault-injection results across all 5 fault classes."""
    if not isinstance(record, dict):
        raise ValueError("Fault matrix record must be a JSON object")

    errors: list[str] = []

    schema_version = record.get("schema_version")
    if type(schema_version) is not int or schema_version != 1:
        errors.append("schema_version must be integer 1")

    driver = record.get("driver")
    target = record.get("target")
    if not isinstance(driver, str) or not driver.strip():
        errors.append("driver must be a nonempty string")
    if not isinstance(target, str) or not target.strip():
        errors.append("target must be a nonempty string")

    require_physical = record.get("require_physical", True)
    physical_verified = False
    if type(require_physical) is not bool:
        errors.append("require_physical must be a boolean")
    elif require_physical:
        physical_ok = True
        if record.get("physical_hardware") is False:
            errors.append("physical_hardware cannot be false when require_physical=true for P08-A01")
            physical_ok = False
        if isinstance(driver, str) and driver.strip():
            driver_norm = driver.strip().lower()
            if driver_norm not in PHYSICAL_DRIVERS:
                errors.append(
                    f"require_physical=true rejects non-physical driver {driver!r} "
                    f"(expected one of {sorted(PHYSICAL_DRIVERS)})"
                )
                physical_ok = False
        else:
            physical_ok = False
        if isinstance(target, str) and target.strip():
            target_norm = target.strip().lower()
            if target_norm != "hw":
                errors.append(
                    f"require_physical=true rejects non-physical target {target!r} "
                    "(expected 'hw')"
                )
                physical_ok = False
        else:
            physical_ok = False
        physical_verified = physical_ok

    cases = record.get("cases")
    if not isinstance(cases, list) or not cases:
        errors.append("cases must be a nonempty list")
        cases = []

    seen_ids: set[str] = set()
    by_class: dict[str, list[dict]] = {cls: [] for cls in REQUIRED_FAULT_CLASSES}
    failed_cases: list[str] = []
    unknown_classes: list[str] = []

    for idx, case in enumerate(cases):
        if not isinstance(case, dict):
            errors.append(f"cases[{idx}] must be an object")
            continue
        case_id = case.get("case_id")
        if not isinstance(case_id, str) or not case_id.strip():
            errors.append(f"cases[{idx}].case_id must be a nonempty string")
            case_id = f"<unnamed-{idx}>"
        elif case_id in seen_ids:
            errors.append(f"duplicate case_id {case_id!r}")
        else:
            seen_ids.add(case_id)

        fault_class = case.get("fault_class")
        if not isinstance(fault_class, str) or fault_class not in REQUIRED_FAULT_CLASSES:
            errors.append(
                f"cases[{idx}] ({case_id}): unsupported fault_class {fault_class!r}; "
                f"expected one of {REQUIRED_FAULT_CLASSES}"
            )
            if isinstance(fault_class, str):
                unknown_classes.append(fault_class)
        else:
            by_class[fault_class].append(case)

        outcome = case.get("outcome")
        if outcome not in VALID_OUTCOMES:
            errors.append(f"cases[{idx}] ({case_id}): invalid outcome {outcome!r}")
        elif outcome != "pass":
            failed_cases.append(case_id)
            errors.append(f"fault case {case_id!r} did not pass (outcome={outcome!r})")

        for text_field in ("expected_behavior", "observed_behavior"):
            val = case.get(text_field)
            if not isinstance(val, str) or not val.strip():
                errors.append(f"cases[{idx}] ({case_id}).{text_field} must be a nonempty string")

        critical = case.get("critical_finding_open", False)
        if type(critical) is not bool:
            errors.append(f"cases[{idx}] ({case_id}).critical_finding_open must be a boolean")
        elif critical:
            errors.append(f"cases[{idx}] ({case_id}) has an unresolved critical finding")

    missing_classes = [cls for cls in REQUIRED_FAULT_CLASSES if not by_class[cls]]
    for cls in missing_classes:
        errors.append(f"missing required P08-A01 fault class: {cls}")

    class_summary = {
        cls: {
            "total": len(items),
            "passed": sum(1 for item in items if item.get("outcome") == "pass"),
        }
        for cls, items in by_class.items()
    }

    overall_outcome = "pass" if not errors else "fail"
    if require_physical is True and physical_verified and overall_outcome == "pass":
        evidence_level = "fpga_measured"
    elif require_physical is False:
        evidence_level = "simulated"
    else:
        evidence_level = "unqualified"

    return {
        "schema_version": 1,
        "tool": "p08_release_tools.fault-matrix-check",
        "acceptance_id": "P08-A01",
        "outcome": overall_outcome,
        "evidence_level": evidence_level,
        "require_physical": require_physical if type(require_physical) is bool else None,
        "total_cases": len(cases),
        "required_classes": list(REQUIRED_FAULT_CLASSES),
        "missing_classes": missing_classes,
        "failed_cases": failed_cases,
        "unknown_classes": sorted(set(unknown_classes)),
        "class_summary": class_summary,
        "errors": errors,
    }


def main(argv: list[str] | None = None) -> int:
    parser = _Parser(
        prog="p08_release_tools.py",
        description="P08 reliability and release-hardening preparatory validators.",
        allow_abbrev=False,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sbom_cmd = sub.add_parser(
        "sbom",
        help="emit reproducible license/provenance JSON inventory and proprietary exclusion report",
        allow_abbrev=False,
    )
    sbom_cmd.add_argument("--root", type=Path, default=ROOT, help="repository root to inspect")
    sbom_cmd.add_argument("--output", type=Path, default=None, help="optional JSON output file path")
    sbom_cmd.add_argument(
        "--bundle-manifest",
        type=Path,
        default=None,
        help="optional JSON file listing release bundle member paths to verify against exclusions",
    )

    soak_cmd = sub.add_parser(
        "soak24-analyze",
        help="validate a 24-hour (>= 86400 s) physical FPGA soak log JSON",
        allow_abbrev=False,
    )
    soak_cmd.add_argument("input", type=Path, help="path to soak log JSON")
    soak_cmd.add_argument("--output", type=Path, default=None, help="optional JSON output file path")

    fault_cmd = sub.add_parser(
        "fault-matrix-check",
        help="validate structured P08-A01 fault-injection results across all 5 fault classes",
        allow_abbrev=False,
    )
    fault_cmd.add_argument("input", type=Path, help="path to fault matrix JSON")
    fault_cmd.add_argument("--output", type=Path, default=None, help="optional JSON output file path")

    args = parser.parse_args(argv)

    try:
        if args.command == "sbom":
            bundle_paths = None
            if args.bundle_manifest is not None:
                manifest_data = _read_json_strict(args.bundle_manifest)
                files = manifest_data.get("files")
                if not isinstance(files, list) or not all(isinstance(x, str) for x in files):
                    raise ValueError("bundle manifest must contain a 'files' list of strings")
                bundle_paths = files
            report = generate_sbom(args.root, check_bundle_paths=bundle_paths)
        elif args.command == "soak24-analyze":
            record = _read_json_strict(args.input)
            report = analyze_soak24(record)
        else:
            record = _read_json_strict(args.input)
            report = check_fault_matrix(record)
    except (OSError, ValueError, RuntimeError, tomllib.TOMLDecodeError) as exc:
        report = {
            "schema_version": 1,
            "tool": f"p08_release_tools.{args.command}",
            "outcome": "fail",
            "errors": [str(exc)],
        }

    encoded = json.dumps(report, indent=2, sort_keys=True, allow_nan=False)
    if args.output is not None:
        args.output.write_text(encoded + "\n", encoding="utf-8")
    try:
        print(encoded)
    except BrokenPipeError:
        pass
    return 0 if report.get("outcome") == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())

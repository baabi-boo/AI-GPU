#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Clean Apache-2.0 RTL & ASIC collateral auditor and handoff exporter.

This pure-Python standard-library tool audits AI-GPU's clean RTL and ASIC
handoff trees (`hw/rtl/`, `hw/asic/`, `hw/dv/`, `profiles/aigpu-b1*.json`,
`VX_config.toml`, `VX_types.toml`, `LICENSE`), verifies zero proprietary or
restricted vendor IP contamination (Micron, Ramulator, Xilinx/Altera encrypted
bitstreams/IP checkpoints, `third_party/`, `build*/`, `.git/`), computes
deterministic SHA-256 checksums and RTL LOC/SRAM macro statistics, and writes
a reproducible `handoff_manifest.json` (plus optional `.tar.gz` archive).

Honesty & non-sign-off contract:
  Every emitted manifest and CLI summary explicitly preserves:
    - `foundry_signoff = False`
    - `silicon_measured = False`
    - `evidence_level = "source_present"`
    - `clean_ip_verified = True` (only when audit passes with 0 violations)
  Running this exporter proves IP cleanliness and checksum integrity of the
  open-source RTL/ASIC collateral kit only; it NEVER certifies commercial PDK
  sign-off, SRAM compiler closure, or tape-out readiness.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import gzip
import hashlib
import io
import json
from pathlib import Path
import re
import sys
import tarfile
from typing import Any


SCHEMA_VERSION = 1
PACKAGE_ID = "aigpu_b1_clean_rtl_handoff"
DEFAULT_ARCHIVE_PREFIX = "aigpu-b1-clean-rtl-handoff"
EVIDENCE_LEVEL = "source_present"

DEFAULT_INCLUDE_PATHS = (
    "hw/rtl",
    "hw/asic",
    "hw/dv",
    "profiles/aigpu-b1.json",
    "profiles/aigpu-b1-tile.json",
    "VX_config.toml",
    "VX_types.toml",
    "LICENSE",
)

RTL_EXTENSIONS = frozenset({".sv", ".v", ".vh", ".vi"})

# Directory / file exclusions for build caches and OS metadata inside clean trees.
EXCLUDED_DIR_NAMES = frozenset({"__pycache__", ".git", ".pytest_cache"})
EXCLUDED_BUILD_DIR_RE = re.compile(r"^build(?:[._-].*)?$")
EXCLUDED_FILE_NAMES = frozenset({".DS_Store", "Thumbs.db"})
EXCLUDED_CACHE_EXTENSIONS = frozenset({".pyc", ".pyo"})

# Forbidden path segments / extensions / filenames (case-insensitive).
FORBIDDEN_PATH_SUBSTRINGS = (
    "micron",
    "ramulator",
    "third_party",
)
FORBIDDEN_EXTENSIONS = frozenset({
    ".xci",
    ".dcp",
    ".bit",
    ".xclbin",
    ".xcix",
    ".vp",
    ".svp",
})
FORBIDDEN_CONTENT_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("micron_vendor", re.compile(r"\bmicron\b", re.IGNORECASE)),
    ("ramulator_ref", re.compile(r"\bramulator\b", re.IGNORECASE)),
    ("xilinx_xci_dcp_xclbin", re.compile(r"\.(?:xci|dcp|bit|xclbin)\b", re.IGNORECASE)),
    ("ieee_1735_protect", re.compile(r"`?pragma\s+protect\b|begin_protected|end_protected", re.IGNORECASE)),
    ("restricted_proprietary_banner", re.compile(
        r"(?:confidential\s+and\s+proprietary|proprietary\s+and\s+confidential|do\s+not\s+distribute)",
        re.IGNORECASE,
    )),
)

# Permissive open-source license / provenance headers accepted in the clean handoff.
# Note: `hw/rtl/tcu/bhf/HardFloat_*.vi` carry UC Berkeley 3-Clause BSD and
# `hw/rtl/afu/opae/local_mem_cfg_pkg.sv` carries Intel 3-Clause BSD (both
# permissive and compatible with Apache-2.0 redistribution). Small generated/data
# collateral (`*.json`, `*.md`, `*.toml`, `*.tcl`, `LICENSE`) or internal RTL
# leaves without explicit boilerplate are verified as Apache-2.0 repo artifacts
# while flagging any restrictive/copyleft/proprietary license text.
RESTRICTIVE_LICENSE_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("gpl_copyleft", re.compile(r"GNU\s+(?:GENERAL|LESSER|AFFERO)\s+PUBLIC\s+LICENSE", re.IGNORECASE)),
    ("commercial_eval_only", re.compile(r"(?:evaluation\s+only|non-commercial\s+use\s+only)", re.IGNORECASE)),
    ("nda_restricted", re.compile(r"(?:under\s+nda|strictly\s+confidential)", re.IGNORECASE)),
)

APACHE_MARKER_RE = re.compile(
    r"Apache\s+License(?:,\s*Version\s*2\.0)?|SPDX-License-Identifier:\s*Apache-2\.0|apache\.org/licenses/LICENSE-2\.0",
    re.IGNORECASE,
)
BSD_PERMISSIVE_RE = re.compile(
    r"Redistribution\s+and\s+use\s+in\s+source\s+and\s+binary\s+forms",
    re.IGNORECASE,
)
COPYRIGHT_ALL_RIGHTS_RE = re.compile(r"All\s+rights\s+reserved", re.IGNORECASE)

TEXT_SCAN_EXTENSIONS = frozenset({
    ".sv", ".v", ".vh", ".vi", ".svh",
    ".py", ".sh", ".tcl", ".cpp", ".c", ".h", ".hpp",
    ".sdc", ".upf", ".toml", ".json", ".md", ".txt", ".yaml", ".yml",
})


@dataclass(frozen=True)
class AuditViolation:
    path: str
    rule: str
    detail: str

    def to_dict(self) -> dict[str, str]:
        return {
            "path": self.path,
            "rule": self.rule,
            "detail": self.detail,
        }


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        self.print_usage(sys.stderr)
        self.exit(2, f"{self.prog}: {message}\n")


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _is_excluded_cache_or_vcs(rel_parts: tuple[str, ...], file_name: str, suffix: str) -> str | None:
    for part in rel_parts[:-1]:
        if part in EXCLUDED_DIR_NAMES or EXCLUDED_BUILD_DIR_RE.match(part):
            return f"excluded_dir:{part}"
    if file_name in EXCLUDED_FILE_NAMES:
        return f"excluded_file:{file_name}"
    if suffix.lower() in EXCLUDED_CACHE_EXTENSIONS:
        return f"excluded_ext:{suffix.lower()}"
    return None


def _check_forbidden_path(rel_posix: str, suffix: str) -> list[AuditViolation]:
    violations: list[AuditViolation] = []
    lowered = rel_posix.lower()
    for token in FORBIDDEN_PATH_SUBSTRINGS:
        if token in lowered:
            violations.append(
                AuditViolation(
                    path=rel_posix,
                    rule="forbidden_path_token",
                    detail=f"Path contains forbidden vendor/third-party marker '{token}'",
                )
            )
    if suffix.lower() in FORBIDDEN_EXTENSIONS:
        violations.append(
            AuditViolation(
                path=rel_posix,
                rule="forbidden_extension",
                detail=f"File has forbidden proprietary/binary IP extension '{suffix.lower()}'",
            )
        )
    parts = Path(rel_posix).parts
    for part in parts[:-1]:
        if part == ".git" or EXCLUDED_BUILD_DIR_RE.match(part):
            violations.append(
                AuditViolation(
                    path=rel_posix,
                    rule="forbidden_directory",
                    detail=f"Path resides inside excluded directory '{part}'",
                )
            )
    return violations


def _classify_license(rel_posix: str, text_head: str, suffix: str) -> tuple[str, list[AuditViolation]]:
    violations: list[AuditViolation] = []
    for rule_name, pat in RESTRICTIVE_LICENSE_PATTERNS:
        if pat.search(text_head):
            violations.append(
                AuditViolation(
                    path=rel_posix,
                    rule=f"restrictive_license:{rule_name}",
                    detail=f"Matched restrictive license/NDA banner ({rule_name})",
                )
            )

    if rel_posix == "LICENSE" or APACHE_MARKER_RE.search(text_head):
        return "Apache-2.0", violations

    if BSD_PERMISSIVE_RE.search(text_head):
        return "BSD-3-Clause (permissive)", violations

    if COPYRIGHT_ALL_RIGHTS_RE.search(text_head):
        violations.append(
            AuditViolation(
                path=rel_posix,
                rule="unclassified_all_rights_reserved",
                detail="Found 'All rights reserved' without Apache-2.0 or permissive BSD notice",
            )
        )
        return "unverified_all_rights_reserved", violations

    if suffix.lower() in {".json", ".md", ".toml", ".tcl", ".py"}:
        return "Apache-2.0 (repo-collateral)", violations

    return "Apache-2.0 (implicit-repo)", violations


def _scan_text_content(rel_posix: str, data: bytes, suffix: str) -> tuple[str, list[AuditViolation]]:
    violations: list[AuditViolation] = []
    text = data.decode("utf-8", errors="replace")
    for line_no, line in enumerate(text.splitlines(), start=1):
        for rule_name, pat in FORBIDDEN_CONTENT_PATTERNS:
            if pat.search(line):
                violations.append(
                    AuditViolation(
                        path=rel_posix,
                        rule=f"forbidden_content:{rule_name}",
                        detail=f"Line {line_no} matched forbidden pattern '{rule_name}'",
                    )
                )
    lic_class, lic_violations = _classify_license(rel_posix, text, suffix)
    violations.extend(lic_violations)
    return lic_class, violations


def _summarize_sram_manifest(repo_root: Path) -> dict[str, Any]:
    manifest_path = repo_root / "hw/asic/sram/sram_macro_manifest.json"
    if not manifest_path.is_file():
        return {"present": False, "profiles": {}}
    raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    profiles_summary: dict[str, Any] = {}
    for prof_name, prof_data in sorted(raw.get("profiles", {}).items()):
        arrays = prof_data.get("sram_arrays", [])
        cut_instances_total = 0
        cut_breakdown: list[dict[str, Any]] = []
        for arr in arrays:
            phys_cut = str(arr.get("physical_cut", ""))
            m = re.match(r"^(\d+)x\s+", phys_cut)
            mult = int(m.group(1)) if m else 1
            logical_inst = int(arr.get("total_instances", 0))
            # For lmem_bank, `total_instances` already encodes the 2x write-mirrored
            # physical copies (2x8=16 per core in tile; 2x16=32 per core in b1),
            # whereas its `physical_cut` text starts with "2x ..." describing those
            # write-mirrored copies per logical bank.
            if arr.get("array_id") == "lmem_bank":
                physical_cuts = logical_inst
            else:
                physical_cuts = logical_inst * mult
            cut_instances_total += physical_cuts
            cut_breakdown.append({
                "array_id": arr.get("array_id"),
                "port_type": arr.get("port_type"),
                "depth": arr.get("depth"),
                "width": arr.get("width"),
                "logical_instances": logical_inst,
                "physical_macro_cuts": physical_cuts,
                "physical_cut_spec": phys_cut,
                "total_kib": arr.get("total_kib"),
                "total_mib": arr.get("total_mib"),
            })
        totals = prof_data.get("totals", {})
        profiles_summary[prof_name] = {
            "array_specs_count": len(arrays),
            "total_logical_arrays": totals.get("total_logical_arrays"),
            "total_physical_macro_cuts": cut_instances_total,
            "total_bits": totals.get("total_bits"),
            "total_bytes": totals.get("total_bytes"),
            "total_kib": totals.get("total_kib"),
            "total_mib": totals.get("total_mib"),
            "arrays": cut_breakdown,
        }
    return {
        "present": True,
        "manifest_path": "hw/asic/sram/sram_macro_manifest.json",
        "manifest_sha256": _sha256_bytes(manifest_path.read_bytes()),
        "profiles": profiles_summary,
    }


def _collect_candidate_paths(
    repo_root: Path,
    include_paths: tuple[str, ...] = DEFAULT_INCLUDE_PATHS,
    extra_scan_paths: tuple[str, ...] = (),
) -> tuple[list[Path], list[dict[str, str]]]:
    selected: dict[str, Path] = {}
    excluded_caches: list[dict[str, str]] = []

    for rel_str in include_paths + extra_scan_paths:
        target = (repo_root / rel_str).resolve()
        try:
            rel_target = target.relative_to(repo_root.resolve())
        except ValueError as exc:
            raise ValueError(f"Include path escapes repo root: {rel_str}") from exc
        if not target.exists():
            raise FileNotFoundError(f"Required handoff path missing: {rel_target.as_posix()}")

        if target.is_file():
            reason = _is_excluded_cache_or_vcs(rel_target.parts, target.name, target.suffix)
            if reason:
                excluded_caches.append({"path": rel_target.as_posix(), "reason": reason})
            else:
                selected[rel_target.as_posix()] = target
        else:
            for item in sorted(target.rglob("*")):
                if not item.is_file():
                    continue
                rel_item = item.relative_to(repo_root.resolve())
                reason = _is_excluded_cache_or_vcs(rel_item.parts, item.name, item.suffix)
                if reason:
                    excluded_caches.append({"path": rel_item.as_posix(), "reason": reason})
                    continue
                selected[rel_item.as_posix()] = item

    return [selected[k] for k in sorted(selected)], excluded_caches


def _inventory_excluded_repo_trees(repo_root: Path) -> list[dict[str, Any]]:
    excluded_inventory: list[dict[str, Any]] = []
    candidates = [
        ("third_party", "Third-party submodules & simulators (contains Ramulator, Micron DDR4 verification sources, SoftFloat, HardFloat, CVFPU, CocoGfx)"),
        ("hw/syn/libs/cln28hpc", "Unlicensed/restricted commercial 28nm library collateral (excluded from open Apache-2.0 handoff)"),
        ("hw/syn/libs/cln28hpm", "Unlicensed/restricted commercial 28nm hard-macro collateral (excluded from open Apache-2.0 handoff)"),
        ("hw/syn/xilinx", "Vendor-specific Xilinx Vivado/XRT FPGA synthesis flows (not ASIC RTL handoff)"),
        ("hw/syn/altera", "Vendor-specific Altera/Intel Quartus FPGA synthesis flows (not ASIC RTL handoff)"),
        ("hw/scripts", "FPGA/Vivado/Altera helper scripts & Xilinx IP stubs (excluded from ASIC handoff)"),
        (".git", "Version-control metadata directory"),
    ]
    for rel, reason in candidates:
        p = repo_root / rel
        if p.exists():
            file_count = sum(1 for x in p.rglob("*") if x.is_file()) if p.is_dir() else 1
            excluded_inventory.append({
                "path": rel,
                "present_in_repo": True,
                "file_count": file_count,
                "reason": reason,
            })
    for build_dir in sorted(repo_root.iterdir()):
        if build_dir.is_dir() and EXCLUDED_BUILD_DIR_RE.match(build_dir.name):
            excluded_inventory.append({
                "path": build_dir.name,
                "present_in_repo": True,
                "file_count": sum(1 for x in build_dir.rglob("*") if x.is_file()),
                "reason": "Out-of-tree / local build directory",
            })
    return excluded_inventory


def audit_and_build_manifest(
    repo_root: Path,
    include_paths: tuple[str, ...] = DEFAULT_INCLUDE_PATHS,
    extra_scan_paths: tuple[str, ...] = (),
) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    files, excluded_caches = _collect_candidate_paths(
        repo_root, include_paths=include_paths, extra_scan_paths=extra_scan_paths
    )

    violations: list[AuditViolation] = []
    file_entries: list[dict[str, Any]] = []
    license_counts: dict[str, int] = {}
    tree_counts: dict[str, int] = {}
    total_bytes = 0
    total_lines = 0
    rtl_file_count = 0
    rtl_lines = 0

    for abs_path in files:
        rel_posix = abs_path.relative_to(repo_root).as_posix()
        suffix = abs_path.suffix.lower()
        data = abs_path.read_bytes()
        sha256 = _sha256_bytes(data)

        violations.extend(_check_forbidden_path(rel_posix, suffix))

        if suffix in TEXT_SCAN_EXTENSIONS or abs_path.name == "LICENSE":
            lic_class, content_violations = _scan_text_content(rel_posix, data, suffix)
            violations.extend(content_violations)
            line_count = data.count(b"\n")
            if data and not data.endswith(b"\n"):
                line_count += 1
        else:
            lic_class = "binary_unverified"
            violations.append(
                AuditViolation(
                    path=rel_posix,
                    rule="unexpected_binary_file",
                    detail=f"Unexpected non-text extension '{suffix or '<none>'}' in clean RTL export",
                )
            )
            line_count = 0

        license_counts[lic_class] = license_counts.get(lic_class, 0) + 1
        top_bucket = rel_posix.split("/", 2)[:2]
        bucket_key = "/".join(top_bucket)
        tree_counts[bucket_key] = tree_counts.get(bucket_key, 0) + 1

        total_bytes += len(data)
        total_lines += line_count
        is_rtl = suffix in RTL_EXTENSIONS
        if is_rtl:
            rtl_file_count += 1
            rtl_lines += line_count

        file_entries.append({
            "path": rel_posix,
            "bytes": len(data),
            "lines": line_count,
            "is_rtl": is_rtl,
            "license_classification": lic_class,
            "sha256": sha256,
        })

    sram_summary = _summarize_sram_manifest(repo_root)
    clean_ip_verified = len(violations) == 0

    return {
        "schema_version": SCHEMA_VERSION,
        "package_id": PACKAGE_ID,
        "evidence_level": EVIDENCE_LEVEL,
        "foundry_signoff": False,
        "silicon_measured": False,
        "clean_ip_verified": clean_ip_verified,
        "non_signoff_notice": (
            "Clean Apache-2.0 source_present RTL and pre-PDK ASIC collateral handoff only. "
            "Academic ASAP7/Nangate45 open-source flows are non-signoff; commercial PDK, "
            "compiled SRAM views, HBM3E/PCIe/UCIe PHYs, and foundry DRC/LVS/STA signoff "
            "must be acquired separately under P10/P11."
        ),
        "included_roots": list(include_paths + extra_scan_paths),
        "forbidden_patterns": {
            "path_tokens": list(FORBIDDEN_PATH_SUBSTRINGS),
            "extensions": sorted(FORBIDDEN_EXTENSIONS),
            "content_rules": [name for name, _ in FORBIDDEN_CONTENT_PATTERNS],
        },
        "summary": {
            "exported_file_count": len(file_entries),
            "total_bytes": total_bytes,
            "total_lines": total_lines,
            "rtl_file_count": rtl_file_count,
            "rtl_lines": rtl_lines,
            "excluded_cache_count": len(excluded_caches),
            "violation_count": len(violations),
            "tree_file_counts": dict(sorted(tree_counts.items())),
            "license_file_counts": dict(sorted(license_counts.items())),
        },
        "sram_macro_summary": sram_summary,
        "excluded_caches": excluded_caches,
        "excluded_repo_trees": _inventory_excluded_repo_trees(repo_root),
        "violations": [v.to_dict() for v in violations],
        "files": file_entries,
    }


def _write_deterministic_tar_gz(
    repo_root: Path,
    manifest: dict[str, Any],
    output_tar_gz: Path,
    archive_prefix: str = DEFAULT_ARCHIVE_PREFIX,
) -> str:
    output_tar_gz.parent.mkdir(parents=True, exist_ok=True)
    manifest_bytes = (json.dumps(manifest, indent=2, sort_keys=False) + "\n").encode("utf-8")

    tar_buf = io.BytesIO()
    with tarfile.open(fileobj=tar_buf, mode="w", format=tarfile.GNU_FORMAT) as tf:
        for entry in manifest["files"]:
            rel_posix = entry["path"]
            src_path = repo_root / rel_posix
            data = src_path.read_bytes()
            if _sha256_bytes(data) != entry["sha256"]:
                raise RuntimeError(f"Checksum drift detected while archiving {rel_posix}")
            info = tarfile.TarInfo(name=f"{archive_prefix}/{rel_posix}")
            info.size = len(data)
            info.mtime = 0
            info.uid = 0
            info.gid = 0
            info.uname = "root"
            info.gname = "root"
            info.mode = 0o755 if (src_path.stat().st_mode & 0o111) else 0o644
            tf.addfile(info, io.BytesIO(data))

        manifest_info = tarfile.TarInfo(name=f"{archive_prefix}/handoff_manifest.json")
        manifest_info.size = len(manifest_bytes)
        manifest_info.mtime = 0
        manifest_info.uid = 0
        manifest_info.gid = 0
        manifest_info.uname = "root"
        manifest_info.gname = "root"
        manifest_info.mode = 0o644
        tf.addfile(manifest_info, io.BytesIO(manifest_bytes))

    gz_buf = io.BytesIO()
    with gzip.GzipFile(fileobj=gz_buf, mode="wb", mtime=0, compresslevel=9) as gz:
        gz.write(tar_buf.getvalue())

    gz_bytes = gz_buf.getvalue()
    output_tar_gz.write_bytes(gz_bytes)
    return _sha256_bytes(gz_bytes)


def build_parser() -> _Parser:
    parser = _Parser(
        description=(
            "Audit and export a clean Apache-2.0 RTL & ASIC handoff package "
            "(excludes Micron, Ramulator, Xilinx/Altera encrypted/binary IP, "
            "third_party/, build*/, .git/)."
        )
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path(__file__).resolve().parents[2],
        help="Repository root directory (default: inferred from script location).",
    )
    parser.add_argument(
        "--output",
        "-o",
        type=Path,
        default=None,
        help="Destination .tar.gz path (required unless --dry-run is set).",
    )
    parser.add_argument(
        "--manifest-out",
        type=Path,
        default=None,
        help="Optional path to write standalone handoff_manifest.json.",
    )
    parser.add_argument(
        "--archive-prefix",
        default=DEFAULT_ARCHIVE_PREFIX,
        help=f"Top-level folder prefix inside tarball (default: {DEFAULT_ARCHIVE_PREFIX}).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run IP cleanliness audit and emit manifest without writing a .tar.gz.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print full JSON manifest/audit summary to stdout.",
    )
    parser.add_argument(
        "--extra-scan-path",
        action="append",
        default=[],
        help="Additional repo-relative path to include in audit (for verification/negative testing).",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if not args.dry_run and args.output is None:
        parser.error("--output is required unless --dry-run is specified")

    repo_root = args.repo_root.resolve()
    manifest = audit_and_build_manifest(
        repo_root=repo_root,
        include_paths=DEFAULT_INCLUDE_PATHS,
        extra_scan_paths=tuple(args.extra_scan_path),
    )

    if args.manifest_out is not None:
        args.manifest_out.parent.mkdir(parents=True, exist_ok=True)
        args.manifest_out.write_text(
            json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
        )

    if not manifest["clean_ip_verified"]:
        if args.json:
            print(json.dumps(manifest, indent=2))
        else:
            print(
                f"ERROR: IP cleanliness audit failed with {manifest['summary']['violation_count']} violation(s):",
                file=sys.stderr,
            )
            for v in manifest["violations"]:
                print(f"  - {v['path']} [{v['rule']}]: {v['detail']}", file=sys.stderr)
        return 1

    tar_sha256: str | None = None
    if not args.dry_run and args.output is not None:
        tar_sha256 = _write_deterministic_tar_gz(
            repo_root=repo_root,
            manifest=manifest,
            output_tar_gz=args.output.resolve(),
            archive_prefix=args.archive_prefix,
        )
        manifest["archive_output"] = {
            "path": str(args.output.resolve()),
            "sha256": tar_sha256,
            "bytes": args.output.resolve().stat().st_size,
        }

    if args.json:
        print(json.dumps(manifest, indent=2))
    else:
        s = manifest["summary"]
        print(
            f"Clean RTL Handoff Audit PASS: files={s['exported_file_count']} "
            f"bytes={s['total_bytes']} rtl_files={s['rtl_file_count']} "
            f"rtl_lines={s['rtl_lines']} excluded_caches={s['excluded_cache_count']} "
            f"violations=0 foundry_signoff=false silicon_measured=false"
        )
        if tar_sha256 is not None:
            print(f"Exported tarball: {args.output.resolve()} (sha256={tar_sha256})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

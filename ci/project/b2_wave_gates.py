#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Pre-commit and post-commit quality gates for the ADR-007 commercial GPU program.

Provides:
  1. Working-tree & staged pre-commit LOC + anti-bloat previewer across
     committed, staged, unstaged, and untracked files by bucket, plus flagging
     files that accidentally land in "excluded".
  2. Hard-frozen & SHA-256 drift guard covering protected assets, python/vortex_ai/,
     all 17 unique artifacts in docs/project/presilicon_readiness.json, and core
     pinned configuration/packaging files.
  3. Clean-IP RTL pre-scanner for candidate/modified files under hw/rtl/, hw/asic/,
     and hw/dv/, checking SPDX-License-Identifier: Apache-2.0 header presence and
     zero forbidden vendor/NDA/GPL/proprietary tokens.
  4. SimX/RTL parity parser & wave evidence JSON builder/validator enforcing
     foundry_signoff=False, fpga_measured=False, silicon_measured=False,
     physical_gates_unwaived=True, plus PR Markdown dashboard table renderer.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
from typing import Any

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import b2_program_tracker as tracker  # noqa: E402


SCHEMA_VERSION = 1
REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_LEDGER_PATH = REPO_ROOT / "docs/project/b2_program_ledger.json"
DEFAULT_PRESILICON_PATH = REPO_ROOT / "docs/project/presilicon_readiness.json"
MAX_SCAN_BYTES = 16 * 1024 * 1024
DEFAULT_PARITY_TOLERANCE_PCT = 5.0

ALLOWED_EVIDENCE_LEVELS = (
    "source_present",
    "simulated",
    "rtl_verified",
    "open_source_synth_pnr_gds",
)
FORBIDDEN_EVIDENCE_LEVELS = (
    "fpga_measured",
    "silicon_measured",
)

# Pinned SHA-256 digests for core configuration, packaging, and protected assets.
CORE_PINNED_SHA256: dict[str, str] = {
    "docs/assets/img/vortex_framework_stack.svg": (
        "db123c71024f85f379c2504c7465c03ee9df8959a5d17fc3d3e94a94a1cd3aa4"
    ),
    "VX_config.toml": (
        "a1c49de52a0373b5f74706528d46bea1181c54f7769dd03994e033c7ddd710bf"
    ),
    "VX_types.toml": (
        "f8eb0b3343f66ebe0a3c9030c8c9150c13638e7c23744b00b2fcf8ce005d5f23"
    ),
    "ci/gen_config.py": (
        "b710a1b80c89d327adf079e61aec9f5d4f950d89342b633b6b00871e50abe165"
    ),
    "profiles/p02-tfr.json": (
        "79a551bd7ba51b5aa4b221eeb9c8f68b0f3078e6282ce71a1f28e9bc4593a102"
    ),
    "setup.py": (
        "697024fc8074f31aa9def1ebeb2d923104ff731f0dcfb80dbeefc6974d267e65"
    ),
    "pyproject.toml": (
        "ad53f6709fcbd49656e48f01503b6917bb20a0fcdea27d95ea954a9da0bf4713"
    ),
    "MANIFEST.in": (
        "aa88954e1e848cde7778e7a4a1e4c0743d638088f1ce183979920adae53c6eb7"
    ),
    "python/vortex_ai/__init__.py": (
        "19d006db3a52bac6b3a7eec0111edd7fa2927e6fc31c1a23308178fa05783465"
    ),
    "python/vortex_ai/_api.py": (
        "f66748c6657ddd55e8753343f49b43cce87003df770e8bbb20c70ee57e3d0db2"
    ),
    "python/vortex_ai/_bundle.py": (
        "363cabe7398cce02bb3ce68313e8acefc796a9d63f1e4f6d4f444c7394f5079f"
    ),
    "python/vortex_ai/launch.py": (
        "01bdadc8469b50fc2b6e511684d37f1bc92d2f4030d3a0900481b8fb5173a128"
    ),
    "python/vortex_ai/torch_ops.py": (
        "b38aec7920a4640aa7af8e01143bf5851ccb9c5132644e60d96f901b71b80d70"
    ),
}

CLEAN_IP_PREFIXES = ("hw/rtl/", "hw/asic/", "hw/dv/")
CLEAN_IP_CODE_EXTENSIONS = frozenset({
    ".sv", ".svh", ".v", ".vh", ".vi",
    ".c", ".cc", ".cpp", ".cxx", ".h", ".hh", ".hpp", ".hxx", ".inl",
    ".py", ".tcl", ".sdc", ".upf", ".cmake",
})
FORBIDDEN_IP_PATH_TOKENS = ("micron", "ramulator", "third_party")
FORBIDDEN_IP_EXTENSIONS = frozenset({
    ".xci", ".dcp", ".bit", ".xclbin", ".xcix", ".vp", ".svp",
})
FORBIDDEN_IP_CONTENT_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("micron_vendor", re.compile(r"\bmicron\b", re.IGNORECASE)),
    ("ramulator_ref", re.compile(r"\bramulator\b", re.IGNORECASE)),
    ("third_party_ref", re.compile(r"\bthird_party\b", re.IGNORECASE)),
    ("xilinx_binary_ext", re.compile(r"\.(?:xci|dcp|bit|xclbin)\b", re.IGNORECASE)),
    ("ieee_1735_protect", re.compile(
        r"`?pragma\s+protect\b|begin_protected|end_protected", re.IGNORECASE
    )),
    ("gpl_license", re.compile(
        r"\bSPDX-License-Identifier:\s*[^\r\n]*GPL\b|\bGNU\s+(?:GENERAL|LESSER|AFFERO)\s+PUBLIC\s+LICENSE\b|\bGPLv?[23]\b",
        re.IGNORECASE,
    )),
    ("nda_restricted", re.compile(
        r"\b(?:under\s+nda|strictly\s+confidential|non-disclosure\s+agreement)\b|\bNDA\b",
        re.IGNORECASE,
    )),
    ("proprietary_banner", re.compile(
        r"(?:confidential\s+and\s+proprietary|proprietary\s+and\s+confidential|do\s+not\s+distribute)",
        re.IGNORECASE,
    )),
)
COPYRIGHT_ALL_RIGHTS_RE = re.compile(r"All\s+rights\s+reserved", re.IGNORECASE)
SPDX_APACHE_RE = re.compile(
    r"SPDX-License-Identifier:\s*Apache-2\.0",
    re.IGNORECASE,
)

# Directories where new non-excluded code files are expected during B2 development.
EXPECTED_ACCIDENTAL_EXCLUSION_ROOTS = (
    "hw/", "sim/", "compiler/", "sw/", "python/", "tools/", "profiles/", "ci/", "tests/",
)

# Permissive legacy RTL/collateral files that predate SPDX headers (e.g., upstream BSD HardFloat/Altera
# and small existing leaf/script files verified by export_clean_rtl_handoff.py).
LEGACY_PERMISSIVE_ALLOWLIST = frozenset({
    "hw/rtl/tcu/bhf/HardFloat_consts.vi",
    "hw/rtl/tcu/bhf/HardFloat_localFuncs.vi",
    "hw/rtl/tcu/bhf/HardFloat_primitives.v",
    "hw/rtl/tcu/bhf/HardFloat_rawFN.v",
    "hw/rtl/tcu/bhf/HardFloat_specialize.v",
    "hw/rtl/tcu/bhf/fNToRecFN.v",
    "hw/rtl/tcu/bhf/iNToRecFN.v",
    "hw/rtl/tcu/bhf/isSigNaNRecFN.v",
    "hw/rtl/tcu/bhf/mulAddRecFN.v",
    "hw/rtl/tcu/bhf/recFNToFN.v",
    "hw/rtl/tcu/bhf/recFNToIN.v",
    "hw/rtl/afu/opae/local_mem_cfg_pkg.sv",
    "hw/rtl/libs/VX_rom.sv",
    "hw/rtl/mufu/VX_mufu_pe.sv",
    "hw/rtl/mufu/VX_mufu_rom.sv",
    "hw/rtl/mufu/VX_mufu_unit.sv",
    "hw/asic/phys/asap7_synth_sta.tcl",
    "hw/asic/phys/openroad_pnr.tcl",
    "hw/asic/phys/run_phys_flow.py",
})


@dataclass(frozen=True)
class GateFinding:
    gate: str
    severity: str
    path: str
    detail: str

    def to_dict(self) -> dict[str, str]:
        return {
            "gate": self.gate,
            "severity": self.severity,
            "path": self.path,
            "detail": self.detail,
        }


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _run_git(repo_root: Path, args: list[str], *, raw: bool = False) -> tuple[int, Any]:
    proc = subprocess.run(
        ["git", *args],
        cwd=repo_root,
        capture_output=True,
        text=not raw,
        errors=None if raw else "replace",
        check=False,
    )
    return proc.returncode, proc.stdout


def _normalize_rel_path(rel_path: str) -> str:
    posix = rel_path.replace("\\", "/").lstrip("./")
    return PurePosixPath(posix).as_posix()


def _list_working_tree_changes(
    repo_root: Path,
    base_commit: str,
) -> dict[str, set[str]]:
    """Collect changed/added/untracked paths across committed, staged, unstaged, and untracked."""
    committed: set[str] = set()
    staged: set[str] = set()
    unstaged: set[str] = set()
    untracked: set[str] = set()

    rc, out = _run_git(repo_root, ["diff", "--name-only", base_commit, "HEAD"])
    if rc == 0:
        committed.update(_normalize_rel_path(line.strip()) for line in out.splitlines() if line.strip())

    rc, out = _run_git(repo_root, ["diff", "--name-only", "--cached"])
    if rc == 0:
        staged.update(_normalize_rel_path(line.strip()) for line in out.splitlines() if line.strip())

    rc, out = _run_git(repo_root, ["diff", "--name-only"])
    if rc == 0:
        unstaged.update(_normalize_rel_path(line.strip()) for line in out.splitlines() if line.strip())

    rc, out = _run_git(repo_root, ["ls-files", "--others", "--exclude-standard"])
    if rc == 0:
        untracked.update(_normalize_rel_path(line.strip()) for line in out.splitlines() if line.strip())

    all_paths = committed | staged | unstaged | untracked
    return {
        "committed": committed,
        "staged": staged,
        "unstaged": unstaged,
        "untracked": untracked,
        "all": all_paths,
    }


def _count_diff_substantive_delta(
    repo_root: Path,
    diff_args: list[str],
    rel_path: str,
) -> int:
    ext = Path(rel_path).suffix
    rc, out = _run_git(repo_root, ["diff", "-U0", *diff_args, "--", rel_path])
    if rc != 0:
        return 0
    added = 0
    removed = 0
    for line in out.splitlines():
        if line.startswith("+++") or line.startswith("---"):
            continue
        if line.startswith("+"):
            if tracker.is_substantive_line(line[1:], ext):
                added += 1
        elif line.startswith("-"):
            if tracker.is_substantive_line(line[1:], ext):
                removed += 1
    return added - removed


def _count_file_substantive_lines(path: Path) -> int:
    if not path.is_file():
        return 0
    ext = path.suffix
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return 0
    return sum(1 for ln in text.splitlines() if tracker.is_substantive_line(ln, ext))


def _is_git_tracked(repo_root: Path, rel_path: str) -> bool:
    rc, out = _run_git(repo_root, ["ls-files", "--", rel_path])
    return rc == 0 and bool(out.strip())


def compute_precommit_loc_preview(
    repo_root: Path,
    ledger: dict[str, Any],
    *,
    include_committed: bool = True,
    candidate_paths: list[str] | None = None,
) -> dict[str, Any]:
    """Preview net substantive LOC across committed + staged + unstaged + untracked files."""
    repo_root = repo_root.resolve()
    base_commit = ledger["base_commit"]
    changes = _list_working_tree_changes(repo_root, base_commit)

    if candidate_paths is not None:
        normalized_candidates = {_normalize_rel_path(p) for p in candidate_paths}
    else:
        normalized_candidates = set(changes["all"])

    prod_by_bucket: dict[str, int] = {name: 0 for name, _ in tracker.PRODUCTION_BUCKETS}
    committed_by_bucket: dict[str, int] = {name: 0 for name, _ in tracker.PRODUCTION_BUCKETS}
    working_delta_by_bucket: dict[str, int] = {name: 0 for name, _ in tracker.PRODUCTION_BUCKETS}

    verification_loc = 0
    committed_verification_loc = 0
    working_verification_delta = 0

    bloat_warnings: list[str] = []
    frozen_violations: list[str] = []
    accidental_exclusions: list[dict[str, str]] = []
    file_details: list[dict[str, Any]] = []

    for rel in sorted(normalized_candidates):
        if any(rel == fp or rel.startswith(fp) for fp in tracker.FROZEN_PROTECTED_PATHS):
            frozen_violations.append(rel)

        category = tracker.classify_path(rel)
        full_path = repo_root / rel
        in_untracked = rel in changes["untracked"]
        in_working = rel in changes["staged"] or rel in changes["unstaged"] or in_untracked
        in_committed = rel in changes["committed"]

        if category == "excluded":
            # Flag code-like files inside active code roots that fall into "excluded"
            # (e.g., wrong directory prefix or unexpected suffix like .sh/.mk).
            if any(rel == fp or rel.startswith(fp) for fp in tracker.FROZEN_PROTECTED_PATHS):
                continue
            is_uncommitted = in_working or in_committed
            if is_uncommitted and rel.startswith(EXPECTED_ACCIDENTAL_EXCLUSION_ROOTS):
                suffix = Path(rel).suffix.lower()
                if rel.startswith(("docs/", "third_party/", "build")):
                    continue
                if suffix == ".json" and rel.startswith(("hw/dv/", "hw/asic/")):
                    continue
                accidental_exclusions.append({
                    "path": rel,
                    "reason": (
                        f"File under '{rel.split('/', 1)[0]}/' classified as 'excluded' "
                        f"(suffix={suffix or '<none>'}) and earns 0 production/test LOC"
                    ),
                })
            continue

        if include_committed and in_committed:
            committed_delta = max(0, _count_diff_substantive_delta(repo_root, [base_commit, "HEAD"], rel))
        else:
            committed_delta = 0

        if in_untracked or (not _is_git_tracked(repo_root, rel) and full_path.is_file()):
            working_delta = _count_file_substantive_lines(full_path)
        elif in_working:
            working_delta = _count_diff_substantive_delta(repo_root, ["HEAD"], rel)
        else:
            working_delta = 0

        net_total = max(0, committed_delta + working_delta)

        if category == "verification_test":
            committed_verification_loc += committed_delta
            working_verification_delta += working_delta
            verification_loc += net_total
        else:
            committed_by_bucket[category] += committed_delta
            working_delta_by_bucket[category] += working_delta
            prod_by_bucket[category] += net_total
            if full_path.is_file():
                bloat_warnings.extend(tracker.check_file_anti_bloat(full_path))

        file_details.append({
            "path": rel,
            "bucket": category,
            "committed_loc": committed_delta,
            "working_delta_loc": working_delta,
            "net_loc": net_total,
            "state": (
                "untracked" if in_untracked else
                "modified" if in_working else
                "committed"
            ),
        })

    total_prod = sum(prod_by_bucket.values())
    total_committed_prod = sum(committed_by_bucket.values())
    total_working_prod = sum(working_delta_by_bucket.values())
    target_min = int(ledger.get("target_min_production_loc", 500000))

    return {
        "schema_version": SCHEMA_VERSION,
        "base_commit": base_commit,
        "candidate_files_count": len(file_details),
        "net_production_loc": total_prod,
        "committed_production_loc": total_committed_prod,
        "working_tree_production_delta": total_working_prod,
        "target_min_production_loc": target_min,
        "production_progress_pct": round(100.0 * total_prod / max(1, target_min), 2),
        "production_loc_by_bucket": prod_by_bucket,
        "committed_loc_by_bucket": committed_by_bucket,
        "working_delta_by_bucket": working_delta_by_bucket,
        "net_verification_test_loc": verification_loc,
        "committed_verification_test_loc": committed_verification_loc,
        "working_tree_verification_delta": working_verification_delta,
        "frozen_path_violations": sorted(set(frozen_violations)),
        "anti_bloat_warnings": bloat_warnings,
        "accidental_exclusions": accidental_exclusions,
        "files": file_details,
    }


def _load_presilicon_pins(presilicon_path: Path) -> dict[str, str]:
    pins: dict[str, str] = {}
    if not presilicon_path.is_file():
        return pins
    data = json.loads(presilicon_path.read_text(encoding="utf-8"))
    for track in data.get("tracks", []):
        for entry in track.get("evidence", []):
            path = entry.get("path")
            digest = entry.get("sha256")
            if isinstance(path, str) and isinstance(digest, str):
                pins[path] = digest.lower()
    return pins


def check_frozen_and_sha256_drift(
    repo_root: Path,
    presilicon_path: Path | None = None,
    *,
    extra_pins: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Verify SHA-256 digests of protected assets, python/vortex_ai/*, presilicon artifacts, and core pins."""
    repo_root = repo_root.resolve()
    if presilicon_path is None:
        presilicon_path = repo_root / "docs/project/presilicon_readiness.json"

    pinned: dict[str, tuple[str, str]] = {}
    for rel, digest in CORE_PINNED_SHA256.items():
        pinned[rel] = (digest.lower(), "core_pinned")

    presilicon_pins = _load_presilicon_pins(presilicon_path)
    for rel, digest in presilicon_pins.items():
        if rel not in pinned:
            pinned[rel] = (digest.lower(), "presilicon_readiness")

    if extra_pins:
        for rel, digest in extra_pins.items():
            pinned[rel] = (digest.lower(), "extra_pin")

    violations: list[dict[str, str]] = []
    verified_count = 0

    for rel, (expected_sha, source) in sorted(pinned.items()):
        target = repo_root / rel
        if not target.is_file():
            violations.append({
                "path": rel,
                "source": source,
                "reason": "missing_pinned_file",
                "expected_sha256": expected_sha,
                "actual_sha256": "",
            })
            continue
        actual_sha = _sha256_file(target)
        if actual_sha != expected_sha:
            violations.append({
                "path": rel,
                "source": source,
                "reason": "sha256_drift",
                "expected_sha256": expected_sha,
                "actual_sha256": actual_sha,
            })
        else:
            verified_count += 1

    # Guard python/vortex_ai/ against unexpected added or untracked files.
    vortex_ai_dir = repo_root / "python/vortex_ai"
    expected_vortex_ai = {
        p for p in CORE_PINNED_SHA256 if p.startswith("python/vortex_ai/")
    }
    if vortex_ai_dir.is_dir():
        for item in sorted(vortex_ai_dir.rglob("*")):
            if not item.is_file():
                continue
            if "__pycache__" in item.parts or item.suffix in (".pyc", ".pyo"):
                continue
            rel = item.relative_to(repo_root).as_posix()
            if rel not in expected_vortex_ai:
                violations.append({
                    "path": rel,
                    "source": "frozen_vortex_ai_tree",
                    "reason": "unexpected_file_in_frozen_dir",
                    "expected_sha256": "",
                    "actual_sha256": _sha256_file(item),
                })

    return {
        "schema_version": SCHEMA_VERSION,
        "ok": len(violations) == 0,
        "total_pinned_files": len(pinned),
        "presilicon_artifact_count": len(presilicon_pins),
        "verified_count": verified_count,
        "violation_count": len(violations),
        "violations": violations,
    }


def _collect_clean_ip_targets(
    repo_root: Path,
    paths: list[str] | None = None,
) -> list[Path]:
    targets: dict[str, Path] = {}
    if paths:
        for raw in paths:
            candidate = Path(raw)
            abs_path = candidate if candidate.is_absolute() else (repo_root / candidate)
            if abs_path.is_dir():
                for item in sorted(abs_path.rglob("*")):
                    if item.is_file() and "__pycache__" not in item.parts:
                        rel = item.resolve().relative_to(repo_root.resolve()).as_posix()
                        targets[rel] = item
            elif abs_path.is_file():
                rel = abs_path.resolve().relative_to(repo_root.resolve()).as_posix()
                targets[rel] = abs_path
    else:
        for prefix in CLEAN_IP_PREFIXES:
            root_dir = repo_root / prefix
            if not root_dir.is_dir():
                continue
            for item in sorted(root_dir.rglob("*")):
                if item.is_file() and "__pycache__" not in item.parts:
                    rel = item.resolve().relative_to(repo_root.resolve()).as_posix()
                    targets[rel] = item
    return [targets[k] for k in sorted(targets)]


LEGACY_APACHE_MARKER_RE = re.compile(
    r"Apache\s+License(?:,\s*Version\s*2\.0)?|apache\.org/licenses/LICENSE-2\.0",
    re.IGNORECASE,
)
BSD_PERMISSIVE_RE = re.compile(
    r"Redistribution\s+and\s+use\s+in\s+source\s+and\s+binary\s+forms",
    re.IGNORECASE,
)


def scan_clean_ip_files(
    repo_root: Path,
    paths: list[str] | None = None,
    *,
    require_spdx: bool = True,
    allow_legacy_apache: bool = False,
    strict_spdx_paths: set[str] | None = None,
) -> dict[str, Any]:
    """Scan hw/rtl/, hw/asic/, hw/dv/ candidate files for Apache-2.0 SPDX and zero forbidden IP tokens."""
    repo_root = repo_root.resolve()
    files = _collect_clean_ip_targets(repo_root, paths)
    violations: list[dict[str, Any]] = []
    scanned_count = 0
    strict_set = {_normalize_rel_path(p) for p in strict_spdx_paths} if strict_spdx_paths else set()

    for abs_path in files:
        rel = abs_path.resolve().relative_to(repo_root).as_posix()
        suffix = abs_path.suffix.lower()
        lowered = rel.lower()
        scanned_count += 1

        for token in FORBIDDEN_IP_PATH_TOKENS:
            if token in lowered:
                violations.append({
                    "path": rel,
                    "rule": "forbidden_path_token",
                    "line": 0,
                    "detail": f"Path contains forbidden IP marker '{token}'",
                })

        if suffix in FORBIDDEN_IP_EXTENSIONS:
            violations.append({
                "path": rel,
                "rule": "forbidden_extension",
                "line": 0,
                "detail": f"File has forbidden binary/encrypted IP extension '{suffix}'",
            })
            continue

        if abs_path.stat().st_size > MAX_SCAN_BYTES:
            violations.append({
                "path": rel,
                "rule": "oversized_file",
                "line": 0,
                "detail": f"File exceeds {MAX_SCAN_BYTES} byte scan cap",
            })
            continue

        try:
            text = abs_path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            violations.append({
                "path": rel,
                "rule": "read_error",
                "line": 0,
                "detail": f"Cannot read file: {exc}",
            })
            continue

        for line_no, line in enumerate(text.splitlines(), start=1):
            for rule_name, pattern in FORBIDDEN_IP_CONTENT_RULES:
                if pattern.search(line):
                    violations.append({
                        "path": rel,
                        "rule": f"forbidden_content:{rule_name}",
                        "line": line_no,
                        "detail": f"Line {line_no} matched '{rule_name}'",
                    })
            if COPYRIGHT_ALL_RIGHTS_RE.search(line):
                if not (BSD_PERMISSIVE_RE.search(text) or SPDX_APACHE_RE.search(text) or LEGACY_APACHE_MARKER_RE.search(text)):
                    violations.append({
                        "path": rel,
                        "rule": "forbidden_content:unclassified_all_rights_reserved",
                        "line": line_no,
                        "detail": f"Line {line_no} contains 'All rights reserved' without Apache-2.0 or permissive BSD notice",
                    })

        if require_spdx and suffix in CLEAN_IP_CODE_EXTENSIONS:
            head_text = "\n".join(text.splitlines()[:25])
            has_spdx = bool(SPDX_APACHE_RE.search(head_text))
            must_be_strict = (not allow_legacy_apache) or (rel in strict_set)
            if not has_spdx and rel not in LEGACY_PERMISSIVE_ALLOWLIST:
                if must_be_strict:
                    violations.append({
                        "path": rel,
                        "rule": "missing_spdx_apache2",
                        "line": 1,
                        "detail": "Missing 'SPDX-License-Identifier: Apache-2.0' header in first 25 lines",
                    })
                elif not (LEGACY_APACHE_MARKER_RE.search(head_text) or BSD_PERMISSIVE_RE.search(head_text)):
                    violations.append({
                        "path": rel,
                        "rule": "missing_apache2_license_notice",
                        "line": 1,
                        "detail": "Missing Apache-2.0 SPDX or license notice in header",
                    })

    return {
        "schema_version": SCHEMA_VERSION,
        "ok": len(violations) == 0,
        "scanned_files": scanned_count,
        "violation_count": len(violations),
        "violations": violations,
    }


def evaluate_simx_rtl_parity(
    cases: list[dict[str, Any]],
    *,
    max_cycle_delta_pct: float = DEFAULT_PARITY_TOLERANCE_PCT,
) -> dict[str, Any]:
    """Validate SimX vs RTL parity: exact retired instructions and cycle delta <= max_cycle_delta_pct."""
    if max_cycle_delta_pct < 0.0:
        raise ValueError("max_cycle_delta_pct must be non-negative")
    if not cases:
        raise ValueError("parity cases must be non-empty")

    results: list[dict[str, Any]] = []
    failures: list[str] = []

    for idx, case in enumerate(cases):
        name = str(case.get("workload") or case.get("name") or f"case_{idx}")
        simx_instrs = case.get("simx_instrs")
        rtl_instrs = case.get("rtl_instrs")
        simx_cycles = case.get("simx_cycles")
        rtl_cycles = case.get("rtl_cycles")

        if not all(isinstance(v, int) and not isinstance(v, bool) and v >= 0
                   for v in (simx_instrs, rtl_instrs, simx_cycles, rtl_cycles)):
            failures.append(f"{name}: instrs and cycles must be non-negative integers")
            results.append({"workload": name, "passed": False, "reason": "invalid_counts"})
            continue

        if rtl_cycles == 0:
            failures.append(f"{name}: rtl_cycles must be > 0")
            results.append({"workload": name, "passed": False, "reason": "zero_rtl_cycles"})
            continue

        instr_match = simx_instrs == rtl_instrs
        cycle_delta_pct = abs(simx_cycles - rtl_cycles) * 100.0 / rtl_cycles
        cycle_ok = cycle_delta_pct <= max_cycle_delta_pct
        passed = instr_match and cycle_ok

        if not instr_match:
            failures.append(
                f"{name}: retired instruction mismatch (simx={simx_instrs} vs rtl={rtl_instrs})"
            )
        if not cycle_ok:
            failures.append(
                f"{name}: cycle delta {cycle_delta_pct:.2f}% exceeds {max_cycle_delta_pct:.2f}% "
                f"(simx={simx_cycles} vs rtl={rtl_cycles})"
            )

        results.append({
            "workload": name,
            "simx_instrs": simx_instrs,
            "rtl_instrs": rtl_instrs,
            "exact_instr_match": instr_match,
            "simx_cycles": simx_cycles,
            "rtl_cycles": rtl_cycles,
            "cycle_delta_pct": round(cycle_delta_pct, 4),
            "passed": passed,
        })

    return {
        "schema_version": SCHEMA_VERSION,
        "ok": len(failures) == 0,
        "max_cycle_delta_pct": max_cycle_delta_pct,
        "total_cases": len(cases),
        "passed_cases": sum(1 for r in results if r["passed"]),
        "failures": failures,
        "cases": results,
    }


def validate_wave_evidence(evidence: Any, ledger: dict[str, Any] | None = None) -> list[str]:
    """Strictly validate a wave evidence summary JSON for honesty and schema invariants."""
    errors: list[str] = []
    if not isinstance(evidence, dict):
        return ["evidence root must be a JSON object"]

    if evidence.get("schema_version") != SCHEMA_VERSION:
        errors.append("schema_version must equal 1")
    if evidence.get("adr") != "ADR-007":
        errors.append("adr must equal 'ADR-007'")

    wave_id = evidence.get("wave_id")
    if not isinstance(wave_id, str) or not re.fullmatch(r"W[0-9]{2}", wave_id):
        errors.append("wave_id must match 'W##' (e.g., 'W13')")

    if evidence.get("foundry_signoff") is not False:
        errors.append("foundry_signoff must be boolean false")
    if evidence.get("fpga_measured") is not False:
        errors.append("fpga_measured must be boolean false")
    if evidence.get("silicon_measured") is not False:
        errors.append("silicon_measured must be boolean false")
    if evidence.get("physical_gates_unwaived") is not True:
        errors.append("physical_gates_unwaived must be boolean true")

    level = evidence.get("evidence_level")
    if level in FORBIDDEN_EVIDENCE_LEVELS:
        errors.append(f"forbidden evidence_level {level!r}")
    elif level not in ALLOWED_EVIDENCE_LEVELS:
        errors.append(f"unsupported evidence_level {level!r}")

    status = evidence.get("status")
    if status not in tracker.VALID_STATUSES:
        errors.append(f"invalid status {status!r}")

    # Scan nested string fields for forbidden affirmative level claims.
    def _scan(node: Any, path: str) -> None:
        if isinstance(node, dict):
            for k, v in node.items():
                if k in ("forbidden_levels", "evidence_boundary"):
                    continue
                _scan(v, f"{path}.{k}")
        elif isinstance(node, list):
            for idx, v in enumerate(node):
                _scan(v, f"{path}[{idx}]")
        elif isinstance(node, str) and node in FORBIDDEN_EVIDENCE_LEVELS:
            errors.append(f"{path}: forbidden physical evidence level {node!r}")

    _scan(evidence, "evidence")

    gates = evidence.get("gates")
    if not isinstance(gates, dict) or not gates:
        errors.append("gates must be a non-empty object")
    else:
        for gate_name, gate_info in gates.items():
            if not isinstance(gate_info, dict):
                errors.append(f"gates.{gate_name}: expected object")
                continue
            if gate_info.get("outcome") not in ("pass", "fail", "not_run", "blocked"):
                errors.append(f"gates.{gate_name}.outcome: invalid outcome")

    if ledger is not None and isinstance(wave_id, str):
        wave_map = {w["id"]: w for w in ledger.get("waves", []) if isinstance(w, dict) and "id" in w}
        if wave_id not in wave_map:
            errors.append(f"wave_id {wave_id!r} not found in ledger")
        elif status == "complete" and isinstance(gates, dict):
            req = wave_map[wave_id].get("required_gates", [])
            for gate_name in req:
                info = gates.get(gate_name)
                if not isinstance(info, dict) or info.get("outcome") != "pass":
                    errors.append(
                        f"complete wave {wave_id} requires gate {gate_name!r} to have outcome='pass'"
                    )

    return errors


def build_wave_evidence(
    wave_id: str,
    *,
    status: str,
    evidence_level: str,
    gates: dict[str, dict[str, Any]],
    loc_metrics: dict[str, Any] | None = None,
    parity_summary: dict[str, Any] | None = None,
    reviewer: str = "pending",
    source_commit: str = "",
    notes: str = "",
    ledger: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Construct a schema-validated wave evidence JSON payload with strict honesty booleans."""
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "adr": "ADR-007",
        "wave_id": wave_id,
        "status": status,
        "evidence_level": evidence_level,
        "foundry_signoff": False,
        "fpga_measured": False,
        "silicon_measured": False,
        "physical_gates_unwaived": True,
        "preserved_blockers": {
            "P01-A03": "blocked",
            "P07-P11": "not_started",
        },
        "generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source_commit": source_commit or "HEAD",
        "reviewer": reviewer,
        "gates": gates,
        "loc_metrics": loc_metrics or {},
        "notes": notes,
    }
    if parity_summary is not None:
        payload["simx_rtl_parity"] = parity_summary

    errs = validate_wave_evidence(payload, ledger=ledger)
    if errs:
        raise ValueError("Invalid wave evidence: " + "; ".join(errs))
    return payload


def render_pr_progress_table(
    ledger: dict[str, Any],
    tracker_metrics: dict[str, Any],
    *,
    precommit_metrics: dict[str, Any] | None = None,
) -> str:
    """Render a clean Markdown progress dashboard table for PR updates."""
    total_prod = tracker_metrics.get("net_production_loc", 0)
    target_prod = ledger.get("target_min_production_loc", 500000)
    pct = tracker_metrics.get("production_progress_pct", 0.0)
    test_loc = tracker_metrics.get("net_verification_test_loc", 0)

    lines = [
        "### ADR-007 `aigpu-b2` Commercial Pre-Silicon Progress",
        "",
        f"- **Committed Net Production LOC:** `{total_prod:,}` / `{target_prod:,}` (`{pct:.2f}%`)",
        f"- **Committed Verification/Test LOC:** `{test_loc:,}`",
    ]
    if precommit_metrics is not None:
        lines.append(
            f"- **Working-Tree Preview Net Production LOC:** "
            f"`{precommit_metrics['net_production_loc']:,}` "
            f"(+{precommit_metrics['working_tree_production_delta']:,} uncommitted) | "
            f"Verification/Test: `{precommit_metrics['net_verification_test_loc']:,}`"
        )
    lines.extend([
        "- **Evidence Boundary:** `foundry_signoff=false`, `fpga_measured=false`, `silicon_measured=false`, `physical_gates_unwaived=true`",
        "",
        "| Wave | Pillar | Title | Status | Target Prod LOC | Target Test LOC |",
        "|---|---|---|---|---:|---:|",
    ])

    for w in ledger.get("waves", []):
        wid = w.get("id", "")
        pillar = w.get("pillar", "")
        title = w.get("title", "")
        status = w.get("status", "not_started")
        ploc = w.get("target_prod_loc", 0)
        tloc = w.get("target_test_loc", 0)
        lines.append(f"| `{wid}` | `{pillar}` | {title} | `{status}` | `{ploc:,}` | `{tloc:,}` |")

    lines.extend([
        "",
        "#### Production LOC by Bucket",
        "",
        "| Bucket | Committed LOC | Working-Tree Preview LOC |",
        "|---|---:|---:|",
    ])
    committed_buckets = tracker_metrics.get("production_loc_by_bucket", {})
    preview_buckets = (
        precommit_metrics.get("production_loc_by_bucket", {})
        if precommit_metrics is not None
        else committed_buckets
    )
    for bucket, _ in tracker.PRODUCTION_BUCKETS:
        c_val = committed_buckets.get(bucket, 0)
        p_val = preview_buckets.get(bucket, 0)
        lines.append(f"| `{bucket}` | `{c_val:,}` | `{p_val:,}` |")

    return "\n".join(lines) + "\n"


def _wave_owned_prefixes(ledger: dict[str, Any], wave_id: str) -> list[str]:
    for w in ledger.get("waves", []):
        if w.get("id") == wave_id:
            return list(w.get("owned_paths", []))
    raise ValueError(f"Unknown wave ID: {wave_id}")


def _check_wave_ownership(
    changed_paths: set[str],
    owned_prefixes: list[str],
) -> list[str]:
    outside: list[str] = []
    for rel in sorted(changed_paths):
        if rel.startswith(".agents/") or rel == "docs/project/b2_program_ledger.json":
            continue
        if not any(rel == op or rel.startswith(op.rstrip("/") + "/") for op in owned_prefixes):
            outside.append(rel)
    return outside


def run_precommit_audit(
    repo_root: Path,
    ledger_path: Path,
    presilicon_path: Path,
    *,
    wave_id: str | None = None,
    strict_wave_ownership: bool = False,
    strict_exclusions: bool = False,
) -> dict[str, Any]:
    """Run all pre-commit quality gates: LOC preview, anti-bloat, frozen/SHA-256 drift, and clean-IP."""
    repo_root = repo_root.resolve()
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    ledger_errors = tracker.validate_ledger(ledger)
    loc_preview = compute_precommit_loc_preview(repo_root, ledger)
    frozen_report = check_frozen_and_sha256_drift(repo_root, presilicon_path)

    # Scan candidate/modified hw/{rtl,asic,dv}/ paths strictly for SPDX, and full hw/ tree for clean-IP.
    changes = _list_working_tree_changes(repo_root, ledger["base_commit"])
    hw_candidates = sorted(
        p for p in changes["all"]
        if p.startswith(CLEAN_IP_PREFIXES) and (repo_root / p).is_file()
    )
    clean_ip_report = scan_clean_ip_files(
        repo_root,
        paths=hw_candidates if hw_candidates else None,
        allow_legacy_apache=not bool(hw_candidates),
        strict_spdx_paths=set(hw_candidates),
    )

    ownership_warnings: list[str] = []
    if wave_id is not None:
        prefixes = _wave_owned_prefixes(ledger, wave_id)
        uncommitted = changes["staged"] | changes["unstaged"] | changes["untracked"]
        ownership_warnings = _check_wave_ownership(uncommitted, prefixes)

    errors: list[str] = list(ledger_errors)
    exclusion_warnings: list[str] = []
    if loc_preview["frozen_path_violations"]:
        errors.append(
            f"Frozen path violations in git diff/working tree: {loc_preview['frozen_path_violations']}"
        )
    if loc_preview["anti_bloat_warnings"]:
        errors.extend(loc_preview["anti_bloat_warnings"])
    if loc_preview["accidental_exclusions"]:
        for exc in loc_preview["accidental_exclusions"]:
            if strict_exclusions:
                errors.append(f"Accidental exclusion: {exc['path']} ({exc['reason']})")
            else:
                exclusion_warnings.append(f"Excluded path notice: {exc['path']} ({exc['reason']})")
    if not frozen_report["ok"]:
        for v in frozen_report["violations"]:
            errors.append(
                f"Pinned artifact drift ({v['source']}): {v['path']} [{v['reason']}]"
            )
    if not clean_ip_report["ok"]:
        for v in clean_ip_report["violations"]:
            errors.append(
                f"Clean-IP violation: {v['path']}:{v['line']} [{v['rule']}] {v['detail']}"
            )
    if strict_wave_ownership and ownership_warnings:
        errors.append(
            f"Wave {wave_id} uncommitted paths outside declared owned_paths: {ownership_warnings}"
        )

    return {
        "schema_version": SCHEMA_VERSION,
        "ok": len(errors) == 0,
        "wave_id": wave_id,
        "foundry_signoff": False,
        "fpga_measured": False,
        "silicon_measured": False,
        "physical_gates_unwaived": True,
        "errors": errors,
        "exclusion_warnings": exclusion_warnings,
        "ownership_warnings": ownership_warnings,
        "loc_preview": loc_preview,
        "frozen_guard": frozen_report,
        "clean_ip": clean_ip_report,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="ADR-007 pre-commit and post-commit wave quality gates."
    )
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--ledger", type=Path, default=DEFAULT_LEDGER_PATH)
    parser.add_argument("--presilicon", type=Path, default=DEFAULT_PRESILICON_PATH)
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument(
        "--precommit-audit",
        action="store_true",
        help="Run LOC preview, anti-bloat, frozen/SHA-256 drift, and clean-IP audit.",
    )
    parser.add_argument("--wave", default=None, help="Wave ID (e.g., W13) to scope/check.")
    parser.add_argument(
        "--strict-wave-ownership",
        action="store_true",
        help="Fail precommit audit if uncommitted paths fall outside wave owned_paths.",
    )
    parser.add_argument(
        "--strict-exclusions",
        action="store_true",
        help="Fail precommit audit if any modified/new file in code roots lands in excluded.",
    )
    mode_group.add_argument(
        "--check-clean-ip",
        nargs="*",
        default=None,
        help="Run clean-IP RTL scanner on specified paths (or all hw/{rtl,asic,dv} if empty).",
    )
    mode_group.add_argument(
        "--check-frozen",
        action="store_true",
        help="Check all frozen paths and SHA-256 digests against pinned baselines.",
    )
    mode_group.add_argument(
        "--render-pr-table",
        action="store_true",
        help="Render Markdown PR progress dashboard table.",
    )
    mode_group.add_argument(
        "--validate-evidence",
        type=Path,
        default=None,
        help="Validate a wave evidence JSON file.",
    )
    mode_group.add_argument(
        "--check-parity",
        type=Path,
        default=None,
        help="Validate a JSON list/object of SimX vs RTL parity cases.",
    )
    parser.add_argument("--json", action="store_true", help="Emit structured JSON output.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    repo_root = args.repo_root.resolve()
    ledger_path = args.ledger if args.ledger.is_absolute() else (repo_root / args.ledger)
    presilicon_path = (
        args.presilicon if args.presilicon.is_absolute() else (repo_root / args.presilicon)
    )

    if args.check_frozen:
        report = check_frozen_and_sha256_drift(repo_root, presilicon_path)
        if args.json:
            print(json.dumps(report, indent=2, sort_keys=True))
        else:
            status = "PASS" if report["ok"] else "FAIL"
            print(
                f"Frozen & SHA-256 Guard {status}: "
                f"verified={report['verified_count']}/{report['total_pinned_files']} "
                f"violations={report['violation_count']}"
            )
            for v in report["violations"]:
                print(f"  - {v['path']} [{v['reason']}] ({v['source']})", file=sys.stderr)
        return 0 if report["ok"] else 1

    if args.check_clean_ip is not None:
        explicit_paths = args.check_clean_ip if args.check_clean_ip else None
        report = scan_clean_ip_files(
            repo_root,
            paths=explicit_paths,
            allow_legacy_apache=explicit_paths is None,
        )
        if args.json:
            print(json.dumps(report, indent=2, sort_keys=True))
        else:
            status = "PASS" if report["ok"] else "FAIL"
            print(
                f"Clean-IP Scanner {status}: "
                f"scanned={report['scanned_files']} violations={report['violation_count']}"
            )
            for v in report["violations"][:25]:
                print(f"  - {v['path']}:{v['line']} [{v['rule']}] {v['detail']}", file=sys.stderr)
        return 0 if report["ok"] else 1

    if args.validate_evidence is not None:
        ev_data = json.loads(args.validate_evidence.read_text(encoding="utf-8"))
        ledger = json.loads(ledger_path.read_text(encoding="utf-8")) if ledger_path.is_file() else None
        errs = validate_wave_evidence(ev_data, ledger=ledger)
        payload = {"schema_version": SCHEMA_VERSION, "ok": not errs, "errors": errs}
        if args.json:
            print(json.dumps(payload, indent=2, sort_keys=True))
        else:
            print("Wave Evidence PASS" if not errs else f"Wave Evidence FAIL: {len(errs)} error(s)")
            for err in errs:
                print(f"  - {err}", file=sys.stderr)
        return 0 if not errs else 1

    if args.check_parity is not None:
        raw = json.loads(args.check_parity.read_text(encoding="utf-8"))
        cases = raw["cases"] if isinstance(raw, dict) and "cases" in raw else raw
        report = evaluate_simx_rtl_parity(cases)
        if args.json:
            print(json.dumps(report, indent=2, sort_keys=True))
        else:
            status = "PASS" if report["ok"] else "FAIL"
            print(
                f"SimX/RTL Parity {status}: "
                f"{report['passed_cases']}/{report['total_cases']} passed "
                f"(tolerance<={report['max_cycle_delta_pct']}%)"
            )
            for f in report["failures"]:
                print(f"  - {f}", file=sys.stderr)
        return 0 if report["ok"] else 1

    if args.render_pr_table:
        ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
        committed_metrics = tracker.compute_program_metrics(repo_root, ledger)
        preview = compute_precommit_loc_preview(repo_root, ledger)
        md = render_pr_progress_table(ledger, committed_metrics, precommit_metrics=preview)
        if args.json:
            print(json.dumps({
                "schema_version": SCHEMA_VERSION,
                "markdown": md,
                "committed_metrics": committed_metrics,
                "precommit_metrics": preview,
            }, indent=2, sort_keys=True))
        else:
            print(md, end="")
        return 0

    # Default or explicit --precommit-audit
    report = run_precommit_audit(
        repo_root,
        ledger_path,
        presilicon_path,
        wave_id=args.wave,
        strict_wave_ownership=args.strict_wave_ownership,
        strict_exclusions=args.strict_exclusions,
    )
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        lp = report["loc_preview"]
        fg = report["frozen_guard"]
        ci = report["clean_ip"]
        status = "PASS" if report["ok"] else "FAIL"
        print(
            f"B2 Pre-Commit Audit {status}: "
            f"prod_loc={lp['net_production_loc']:,} "
            f"(committed={lp['committed_production_loc']:,}, working={lp['working_tree_production_delta']:+,}) | "
            f"test_loc={lp['net_verification_test_loc']:,} | "
            f"pinned={fg['verified_count']}/{fg['total_pinned_files']} | "
            f"clean_ip_scanned={ci['scanned_files']} violations={ci['violation_count']}"
        )
        for warn in report.get("exclusion_warnings", []):
            print(f"WARN: {warn}")
        for err in report["errors"]:
            print(f"ERROR: {err}", file=sys.stderr)
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

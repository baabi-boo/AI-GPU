#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Track and validate ADR-007 aigpu-b2 program waves and net non-test production LOC.

This tool measures net new non-blank, non-comment-only production source lines
relative to the ADR-007 base commit (`96424fa`), strictly separating production
code from DV/formal/SVA/unit-test code, documentation, generated artifacts, and
vendored trees. It also enforces anti-bloat heuristics so synthetic padding or
generated blobs cannot inflate the 500,000+ production LOC target.
"""

from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import subprocess
import sys
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
LEDGER_PATH = REPO_ROOT / "docs/project/b2_program_ledger.json"

CODE_EXTENSIONS = frozenset({
    ".sv", ".svh", ".v", ".vh", ".vi",
    ".c", ".cc", ".cpp", ".cxx", ".h", ".hh", ".hpp", ".hxx", ".inl",
    ".py", ".tcl", ".sdc", ".upf", ".s", ".S", ".ld", ".cmake",
})

EXCLUDED_PREFIXES = (
    "third_party/",
    "build",
    ".git/",
    "docs/",
    "hw/syn/libs/",
)

TEST_PREFIXES = (
    "hw/dv/",
    "tests/",
)

PRODUCTION_BUCKETS = (
    ("rtl_silicon", ("hw/rtl/", "hw/asic/")),
    ("simx", ("sim/simx/", "sim/common/")),
    ("compiler", ("compiler/", "python/aigpu_triton/")),
    ("kernels", ("sw/libs/",)),
    ("driver_runtime", ("sw/driver/", "sw/runtime_b2/", "sw/ccl/", "sw/runtime/", "sw/kernel/")),
    ("frameworks_tools", ("python/aigpu_torch/", "python/aigpu_serve/", "python/aigpu_sdk/", "tools/")),
    ("bootstrap", ("profiles/", "ci/project/")),
)

FROZEN_PROTECTED_PATHS = (
    "docs/assets/img/vortex_framework_stack.svg",
    "python/vortex_ai/",
)

VALID_STATUSES = frozenset({"not_started", "in_progress", "blocked", "complete"})


def is_test_path(rel_path: str) -> bool:
    if any(rel_path.startswith(prefix) for prefix in TEST_PREFIXES):
        return True
    name = Path(rel_path).name
    if name.startswith("test_") or name.endswith("_test.py") or name.endswith("_test.cpp"):
        return True
    if name.endswith("_tb.sv") or name.startswith("tb_"):
        return True
    return False


def classify_path(rel_path: str) -> str:
    if any(rel_path.startswith(prefix) for prefix in EXCLUDED_PREFIXES):
        return "excluded"
    if rel_path.endswith(".json") and not rel_path.startswith("profiles/"):
        return "excluded"
    ext = Path(rel_path).suffix
    if ext not in CODE_EXTENSIONS and not (rel_path.startswith("profiles/") and ext == ".json"):
        return "excluded"
    if is_test_path(rel_path):
        return "verification_test"
    for bucket, prefixes in PRODUCTION_BUCKETS:
        if any(rel_path.startswith(p) for p in prefixes):
            return bucket
    return "excluded"


def is_substantive_line(line: str, ext: str) -> bool:
    s = line.strip()
    if not s:
        return False
    if ext in {".py", ".tcl", ".sdc", ".upf", ".cmake"}:
        if s.startswith("#"):
            return False
    else:
        if s.startswith("//") or s.startswith("/*") or s.startswith("*") or s.startswith("*/"):
            return False
    return True


def check_file_anti_bloat(path: Path) -> list[str]:
    """Detect obvious synthetic padding or generated-table bloat in a production file."""
    warnings: list[str] = []
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return warnings
    ext = path.suffix
    substantive = [ln.strip() for ln in lines if is_substantive_line(ln, ext)]
    if len(substantive) < 200:
        return warnings
    counts = Counter(substantive)
    top_line, top_count = counts.most_common(1)[0]
    if top_count > 100 and (top_count / len(substantive)) > 0.35 and len(top_line) > 3:
        warnings.append(
            f"{path.as_posix()}: repetitive line ratio {top_count}/{len(substantive)} "
            f"({top_count / len(substantive):.1%}) for {top_line[:40]!r}"
        )
    unique_ratio = len(counts) / len(substantive)
    if len(substantive) >= 500 and unique_ratio < 0.12:
        warnings.append(
            f"{path.as_posix()}: low line diversity {unique_ratio:.1%} "
            f"({len(counts)} unique / {len(substantive)} substantive lines)"
        )
    return warnings


def validate_ledger(ledger: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if ledger.get("schema_version") != 1:
        errors.append("ledger schema_version must be 1")
    if ledger.get("adr") != "ADR-007":
        errors.append("ledger adr must be ADR-007")
    min_loc = ledger.get("target_min_production_loc", 0)
    if not isinstance(min_loc, int) or min_loc < 500000:
        errors.append("target_min_production_loc must be an integer >= 500000")

    eb = ledger.get("evidence_boundary", {})
    if eb.get("foundry_signoff") is not False:
        errors.append("evidence_boundary.foundry_signoff must remain false")
    if eb.get("physical_gates_unwaived") is not True:
        errors.append("evidence_boundary.physical_gates_unwaived must remain true")
    for forbidden in ("fpga_measured", "silicon_measured"):
        if forbidden in eb.get("allowed_levels", []):
            errors.append(f"forbidden evidence level {forbidden!r} in allowed_levels")

    waves = ledger.get("waves", [])
    if not isinstance(waves, list) or len(waves) < 1:
        errors.append("waves must be a non-empty list")
        return errors

    seen_ids: set[str] = set()
    total_planned_prod = 0
    for idx, w in enumerate(waves):
        wid = w.get("id")
        if not isinstance(wid, str) or not wid:
            errors.append(f"waves[{idx}] missing valid id")
        elif wid in seen_ids:
            errors.append(f"duplicate wave id {wid!r}")
        else:
            seen_ids.add(wid)
        if w.get("status") not in VALID_STATUSES:
            errors.append(f"wave {wid}: invalid status {w.get('status')!r}")
        ploc = w.get("target_prod_loc", 0)
        if not isinstance(ploc, int) or ploc < 0:
            errors.append(f"wave {wid}: target_prod_loc must be non-negative int")
        else:
            total_planned_prod += ploc
        if not w.get("owned_paths"):
            errors.append(f"wave {wid}: owned_paths must be non-empty")
        if not w.get("required_gates"):
            errors.append(f"wave {wid}: required_gates must be non-empty")

    if total_planned_prod < min_loc:
        errors.append(
            f"sum of wave target_prod_loc ({total_planned_prod}) < target_min_production_loc ({min_loc})"
        )
    return errors


def git_changed_files(repo_root: Path, base_commit: str) -> list[str]:
    proc = subprocess.run(
        ["git", "diff", "--name-only", base_commit, "HEAD"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        return []
    return [ln.strip() for ln in proc.stdout.splitlines() if ln.strip()]


def git_net_substantive_loc(repo_root: Path, base_commit: str, rel_path: str) -> int:
    """Compute net added substantive lines for rel_path between base_commit and HEAD."""
    ext = Path(rel_path).suffix
    proc = subprocess.run(
        ["git", "diff", "-U0", base_commit, "HEAD", "--", rel_path],
        cwd=repo_root,
        capture_output=True,
        text=True,
        errors="replace",
        check=False,
    )
    if proc.returncode != 0:
        return 0
    added = 0
    removed = 0
    for line in proc.stdout.splitlines():
        if line.startswith("+++") or line.startswith("---"):
            continue
        if line.startswith("+"):
            if is_substantive_line(line[1:], ext):
                added += 1
        elif line.startswith("-"):
            if is_substantive_line(line[1:], ext):
                removed += 1
    return max(0, added - removed)


def compute_program_metrics(repo_root: Path, ledger: dict[str, Any]) -> dict[str, Any]:
    base_commit = ledger["base_commit"]
    changed = git_changed_files(repo_root, base_commit)

    prod_by_bucket: dict[str, int] = {name: 0 for name, _ in PRODUCTION_BUCKETS}
    verification_loc = 0
    bloat_warnings: list[str] = []
    frozen_violations: list[str] = []

    for rel in changed:
        if any(rel == fp or rel.startswith(fp) for fp in FROZEN_PROTECTED_PATHS):
            frozen_violations.append(rel)
        category = classify_path(rel)
        if category == "excluded":
            continue
        delta = git_net_substantive_loc(repo_root, base_commit, rel)
        if category == "verification_test":
            verification_loc += delta
        else:
            prod_by_bucket[category] += delta
            full_path = repo_root / rel
            if full_path.is_file():
                bloat_warnings.extend(check_file_anti_bloat(full_path))

    total_prod = sum(prod_by_bucket.values())
    waves = ledger.get("waves", [])
    wave_counts = Counter(w["status"] for w in waves)
    return {
        "base_commit": base_commit,
        "changed_files_count": len(changed),
        "net_production_loc": total_prod,
        "target_min_production_loc": ledger["target_min_production_loc"],
        "production_progress_pct": round(100.0 * total_prod / ledger["target_min_production_loc"], 2),
        "production_loc_by_bucket": prod_by_bucket,
        "net_verification_test_loc": verification_loc,
        "wave_status_counts": dict(wave_counts),
        "frozen_path_violations": frozen_violations,
        "anti_bloat_warnings": bloat_warnings,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate ADR-007 aigpu-b2 ledger and LOC progress.")
    parser.add_argument("--ledger", type=Path, default=LEDGER_PATH)
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--verify", action="store_true", help="Fail if ledger errors, frozen violations, or bloat warnings occur.")
    parser.add_argument("--require-500k", action="store_true", help="Fail unless net_production_loc >= target_min_production_loc.")
    parser.add_argument("--json", action="store_true", help="Emit JSON output.")
    args = parser.parse_args(argv)

    ledger = json.loads(args.ledger.read_text(encoding="utf-8"))
    errors = validate_ledger(ledger)
    metrics = compute_program_metrics(args.repo_root, ledger)

    if args.verify:
        if metrics["frozen_path_violations"]:
            errors.append(f"Frozen protected paths modified: {metrics['frozen_path_violations']}")
        if metrics["anti_bloat_warnings"]:
            errors.extend(metrics["anti_bloat_warnings"])
    if args.require_500k and metrics["net_production_loc"] < metrics["target_min_production_loc"]:
        errors.append(
            f"net_production_loc ({metrics['net_production_loc']}) < "
            f"target_min_production_loc ({metrics['target_min_production_loc']})"
        )

    payload = {"ok": not errors, "errors": errors, "metrics": metrics}
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(
            f"ADR-007 aigpu-b2 Program Tracker: "
            f"{metrics['net_production_loc']:,} / {metrics['target_min_production_loc']:,} "
            f"net non-test production LOC ({metrics['production_progress_pct']:.2f}%) | "
            f"verification/test LOC: {metrics['net_verification_test_loc']:,}"
        )
        if errors:
            for err in errors:
                print(f"ERROR: {err}", file=sys.stderr)
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Verify retained diagnostic originals and current actual-task catalogs."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import sys


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True, help="AI-GPU source checkout")
    parser.add_argument("--receipt", type=Path, help="Write the generated integrity receipt here")
    args = parser.parse_args()
    root = args.root.resolve()
    packet = root / "docs/project/evidence/p06-counter-diagnostics"
    reviews = packet / "reviews"
    errors = []
    checked = {}

    def relative(path):
        return path.relative_to(root).as_posix()

    def read_json(path):
        try:
            return json.loads(path.read_text())
        except (OSError, ValueError) as exc:
            errors.append(f"Cannot read JSON {relative(path)}: {type(exc).__name__}")
            return {}

    def identity(path):
        raw = path.read_bytes()
        return {"path": relative(path), "size_bytes": len(raw), "sha256": sha(raw)}

    def verify_identity(item, path_key="path"):
        path = (root / item[path_key]).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            errors.append("Missing or unsafe retained file: " + item[path_key])
            return None
        actual = identity(path)
        checked[actual["path"]] = actual
        if actual["size_bytes"] != item["size_bytes"] or actual["sha256"] != item["sha256"]:
            errors.append("Retained byte/hash mismatch: " + item[path_key])
        return path

    manifest = read_json(reviews / "retained-files.json")
    ledger = read_json(packet / "agent-ledger.json")
    mapping = read_json(reviews / "task-artifact-map.json")
    records = manifest.get("files", [])
    paths = [entry["retained_path"] for entry in records]
    if len(paths) != len(set(paths)):
        errors.append("Duplicate retained artifact path")
    for entry in records:
        verify_identity(entry, "retained_path")
    for snapshot in manifest.get("ledger_snapshots", []):
        verify_identity(snapshot)

    frozen = ledger.get("frozen_47_task_snapshot", {})
    if frozen.get("sha256") != "590328e2d4143a900eb940f7afa224ff16811695327af81793098a651d4a1ec6" or frozen.get("size_bytes") != 5867:
        errors.append("Frozen 47-task ledger identity changed")
    frozen_path = verify_identity(frozen) if frozen else None
    frozen_ledger = read_json(frozen_path) if frozen_path else {}
    frozen_tasks = [task for wave in frozen_ledger.get("waves", []) for task in wave["tasks"]]
    if len(frozen_tasks) != 47 or len(set(frozen_tasks)) != 47:
        errors.append("Frozen ledger is not the original 47-task snapshot")

    historical_manifest = read_json(reviews / "history/wave08-catalog/retained-files.json")
    packaging = manifest.get("packaging_path_changes", {})
    by_path = {entry["retained_path"]: entry for entry in records}
    for original in historical_manifest.get("files", []):
        current_path = packaging.get(original["retained_path"], original["retained_path"])
        retained = by_path.get(current_path)
        if not retained or any(retained[key] != original[key] for key in ("size_bytes", "sha256", "original_name")):
            errors.append("Historical original no longer retained unchanged: " + original["retained_path"])
    for old_path, new_path in packaging.items():
        if (root / old_path).exists() or not (root / new_path).is_file() or not new_path.endswith(".md.txt"):
            errors.append("Invalid inert Markdown packaging: " + old_path)

    source_identity = ledger.get("current_root_ledger_snapshot", {})
    source_path = verify_identity(source_identity) if source_identity else None
    source = read_json(source_path) if source_path else {}
    expected_tasks = [task for wave in source.get("waves", []) for task in wave["tasks"]]
    rows = ledger.get("tasks", [])
    actual_tasks = [row["task_name"] for row in rows]
    if actual_tasks != expected_tasks or len(actual_tasks) != len(set(actual_tasks)):
        errors.append("Actual-task ledger does not exactly match the captured root task order/set")
    if mapping.get("tasks") != rows:
        errors.append("Task artifact map and actual-task ledger differ")
    if mapping.get("current_root_ledger_snapshot") != source_identity or manifest.get("current_root_ledger_snapshot") != source_identity:
        errors.append("Current catalogs refer to different root-ledger snapshots")

    expected_rows = []
    ordinal = 0
    for wave in source.get("waves", []):
        if len(wave["tasks"]) > 6 or len(set(wave["tasks"])) != len(wave["tasks"]):
            errors.append("Root snapshot has invalid actual wave membership")
        for slot, task in enumerate(wave["tasks"], 1):
            ordinal += 1
            completed = task in wave.get("completed_tasks", []) or wave["state"] == "completed"
            expected_rows.append((task, wave["wave"], slot, ordinal, "completed" if completed else "in_progress"))
    for row, expected in zip(rows, expected_rows):
        actual = tuple(row[key] for key in ("task_name", "wave", "slot", "ordinal", "status"))
        if actual != expected:
            errors.append("Task state/wave/slot differs from root: " + row["task_name"])
        if not row.get("purpose") or not row.get("completion_basis"):
            errors.append("Missing explicit task purpose/completion basis: " + row["task_name"])
        primary = row.get("primary_note")
        own = row.get("direct_original_artifacts", [])
        related = row.get("related_review_artifacts", [])
        if primary and primary not in own:
            errors.append("Primary original note is not direct evidence: " + row["task_name"])
        if row["standalone_note_status"] != ("retained_original" if primary else "missing_original_note"):
            errors.append("Incorrect original-note availability: " + row["task_name"])
        for path in own + related + ([primary] if primary else []):
            if path not in by_path:
                errors.append("Task references an unmanifested original: " + path)
        for path in row.get("related_integrated_source_paths", []):
            if not (root / path).is_file():
                errors.append("Missing related integrated source: " + path)
        for path in own:
            if path in by_path and row["task_name"] not in by_path[path].get("associated_tasks", []):
                errors.append("Direct evidence lacks explicit task association: " + path)

    completed_count = sum(row.get("status") == "completed" for row in rows)
    actual_complete = len(rows) == 60 and len(source.get("waves", [])) == 10 and completed_count == 60 and all(len(wave["tasks"]) == 6 for wave in source.get("waves", []))
    for value, label in ((ledger, "agent ledger"), (mapping, "task map"), (manifest, "manifest")):
        if value.get("actual_distinct_task_count") != len(rows) or value.get("root_confirmed_completed_task_count") != completed_count:
            errors.append("Task count mismatch in " + label)
        if value.get("final_actual_60_10_complete") is not actual_complete:
            errors.append("Unjustified final completion flag in " + label)
        if value.get("not_yet_recorded_requested_task_count") != 60 - len(rows):
            errors.append("Requested versus actual count mismatch in " + label)
        for flag in ("qualified", "ready_for_warm", "full_warm_coverage", "warm_execution", "acceptance"):
            if value.get(flag) is not False:
                errors.append("Non-false qualification flag in " + label + ": " + flag)

    expected_paths = {entry["retained_path"] for entry in records if entry["retention"] == "byte_for_byte_copy"}
    expected_paths.update(snapshot["path"] for snapshot in manifest.get("ledger_snapshots", []))
    expected_paths.update(manifest.get("generated_catalog_paths_excluded_from_original_counts", []))
    directory_paths = {relative(path) for path in reviews.rglob("*") if path.is_file()}
    if directory_paths != expected_paths:
        errors.append("Review directory membership differs from manifest")

    fixed_sources = {
        "lifetime-source-manifest.json": (63560, "601ba960e5c57687d6cd2ee3c6cc6b3e60c53cdf5cc64158ebdee6c8a3d0fb3c"),
        "dependency-source-manifest.json": (16601, "3fb3332ecf76c5ee136bf68e2840f8e4e612a15f660a983d0913662cf8c469b6"),
        "dependency-source-bodies.json": (99341, "e5fd3d919e3c8f446381cc33e527c230c463010fc4178168e0ef52d21b187bbd"),
    }
    for name, (size, checksum) in fixed_sources.items():
        verify_identity({"path": relative(packet / name), "size_bytes": size, "sha256": checksum})

    spec = importlib.util.spec_from_file_location("project_metadata_check", root / "ci/project/check_project.py")
    metadata = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(metadata)
    project_errors = metadata.validate_project(root)
    errors.extend(project_errors)
    local_links = 0
    for path in [packet / "README.md", *sorted(reviews.rglob("*.md"))]:
        for target in metadata._links(path.read_text()):
            if not re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", target) and not target.startswith("//"):
                local_links += 1

    patterns = {
        "token": r"(?:ghp_|github_pat_|gho_|ghu_|ghs_)[A-Za-z0-9_]{16,}",
        "private_key": r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----",
        "authorization": r"(?i)authorization[\"\s:]+(?:bearer|token|basic)\s+[A-Za-z0-9+/=_-]{12,}",
        "signed_url": r"(?i)(?:[?&](?:sig|X-Amz-Signature|X-Goog-Signature)=)[^&\s\"']{12,}",
    }
    candidates = []
    scan_paths = {root / path for path in paths}
    scan_paths.update(root / value["path"] for value in manifest.get("ledger_snapshots", []))
    for path in sorted(scan_paths):
        if not path.is_file():
            continue
        text = path.read_text(errors="replace")
        for category, pattern in patterns.items():
            if re.search(pattern, text):
                candidates.append({"path": relative(path), "category": category})
    if candidates:
        errors.append("Sensitive-pattern candidates require review")

    generated = [packet / "agent-ledger.json", packet / "README.md", *(reviews / name for name in ("README.md", "ARTIFACTS.md", "retained-files.json", "task-artifact-map.json"))]
    for path in generated:
        checked[relative(path)] = identity(path)
    receipt = {
        "schema_version": 1,
        "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "outcome": "pass" if not errors else "fail",
        "reproduction_command": "python3 docs/project/evidence/p06-counter-diagnostics/reviews/wave09/w09-evidence-finalization-verify.py --root . --receipt /tmp/p06-counter-evidence-integrity.json",
        "verifier": identity(Path(__file__).resolve()) if Path(__file__).resolve().is_relative_to(root) else {"filename": Path(__file__).name, "sha256": sha(Path(__file__).read_bytes())},
        "scope": "Retained-file integrity, actual task states, historical preservation, directory membership, project metadata/local links and bounded sensitive-pattern checks only.",
        "actual_distinct_task_count": len(rows), "root_confirmed_completed_task_count": completed_count,
        "final_actual_60_10_complete": actual_complete,
        "frozen_task_count": len(frozen_tasks),
        "retained_original_and_historical_records": len(records),
        "frozen_original_records_preserved": len(historical_manifest.get("files", [])),
        "ledger_snapshot_count": len(manifest.get("ledger_snapshots", [])),
        "review_directory_files": len(directory_paths),
        "review_directory_bytes_excluding_current_receipt": sum((root / path).stat().st_size for path in directory_paths if path != relative(reviews / "integrity-receipt.json")),
        "current_receipt_self_hash_excluded": True,
        "retained_markdown_local_targets_checked": local_links,
        "project_metadata_errors": project_errors,
        "packaging_path_changes": packaging,
        "missing_original_notes": [row["task_name"] for row in rows if not row.get("primary_note")],
        "pending_actual_tasks": [row["task_name"] for row in rows if row.get("status") != "completed"],
        "not_yet_recorded_requested_task_count": 60 - len(rows),
        "secret_pattern_candidates": candidates,
        "checked_file_identities": list(checked.values()),
        "errors": errors,
        "native_execution": "not_run", "native_packet_code_executed": False, "full_test_discovery": "not_run",
        "qualified": False, "ready_for_warm": False, "warm_execution": False, "acceptance": False,
    }
    encoded = json.dumps(receipt, indent=2) + "\n"
    if args.receipt:
        args.receipt.write_text(encoded)
    print(json.dumps({key: value for key, value in receipt.items() if key != "checked_file_identities"}, indent=2))
    return bool(errors)


if __name__ == "__main__":
    sys.exit(main())

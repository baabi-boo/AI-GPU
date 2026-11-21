#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Finalize or verify the retained 60-worker P05 completion ledger.

Build compares the coordinator's completed spawn observation, original worker
receipts and retained copies. Verify checks the retained ledger and copies only.
Neither mode authenticates the agent service or grants technical acceptance.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import stat
import sys
import tempfile


IMPLEMENTATION = "e1420fd550f716df33a2556057b7086a03032cbe"
INITIAL_SHA256 = "81de6faa4f785fb60a58e92c2216aaaf071eee3101d6a618bff5fb6d21f22784"
WAVES = (
    ("runtime_audit", "provenance_audit", "model_audit", "package_audit", "contract_review", "qualification_audit"),
    ("native_owners", "native_loader", "python_api", "packaging", "bundle_producer", "fault_runtime"),
    ("context_lease_review", "python_api_tests", "qualification_runner", "installed_matrix", "ci_workflow", "launcher_bundle_tests"),
    ("native_fault_tests", "producer_tests", "runner_process_review", "qualification_tests", "binding_docs", "packaging_tests"),
    ("native_r3_review", "loader_r3_review", "api_r3_review", "pipeline_r3_review", "governance_integration", "contract_review"),
    ("native_final_regressions", "final_package_build", "publication_readiness", "numerical_auditor", "dispatch_auditor", "provenance_auditor"),
    ("numerical_adversarial_review", "dispatch_adversarial_review", "provenance_adversarial_review", "dispatch_auditor_repairs", "host_ci_history_review", "archive_distribution_review"),
    ("fp16_numerical_qualification", "fp16_dispatch_qualification", "fp16_provenance_qualification", "bf16_numerical_qualification", "bf16_dispatch_qualification", "bf16_provenance_qualification"),
    ("full_matrix_evidence_review", "binding_acceptance_review", "project_handoff_update", "relocated_replay_review", "source_boundary_review", "compatibility_documentation"),
    ("final_acceptance_scope_review", "final_api_documentation_review", "final_auditor_review", "final_governance_review", "collaboration_ledger_review", "final_delivery_review"),
)
BEGIN = "<!-- BEGIN COMPLETION STATUS -->"
END = "<!-- END COMPLETION STATUS -->"
COMPLETE_TEXT = """The [completion ledger](agent-ledger.json) records **60 distinct completed
worker assignments across ten logical waves of six**. Follow-up turns are not
additional agents, and the coordinating root is not counted as a worker. Each
entry identifies its actual task path and retained receipt size and SHA-256.
The ledger was emitted only after the final coordinator observation listed all
sixty tasks with receipts present, all original receipts matched their retained
copies, and the first thirty historical receipt identities remained unchanged."""


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(body):
    return hashlib.sha256(body).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def unique(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "duplicate JSON key")
        result[key] = value
    return result


def decode(body):
    return json.loads(body.decode("utf-8"), object_pairs_hook=unique,
                      parse_constant=lambda value: (_ for _ in ()).throw(ValueError("nonfinite JSON value")))


def directory(path):
    require(path.is_absolute() and path.resolve(strict=True) == path and path.is_dir(),
            "directory must be canonical and free of symlinks: " + str(path))


def read(path):
    require(path.is_absolute() and path.resolve(strict=True) == path
            and stat.S_ISREG(path.stat().st_mode) and path.stat().st_size <= 1024 * 1024,
            "input must be a bounded regular file without symlinks: " + str(path))
    with path.open("rb") as stream:
        body = stream.read(1024 * 1024 + 1)
    require(len(body) <= 1024 * 1024, "input exceeds byte bound")
    return body


def expected_rows():
    return [dict(wave=wave, assignment=(wave - 1) * 6 + slot,
                 agent=f"/root/w{wave:02}_a{slot}_{name}", receipt=f"w{wave:02}_a{slot}.md",
                 receipt_present=True)
            for wave, names in enumerate(WAVES, 1) for slot, name in enumerate(names, 1)]


def validate_observation(rows):
    expected = expected_rows()
    require(type(rows) is list and len(rows) == 60, "exactly sixty observed worker assignments are required")
    for row, wanted in zip(rows, expected):
        require(type(row) is dict and set(row) == set(wanted), "spawn observation fields differ")
        require(type(row["wave"]) is int and type(row["assignment"]) is int,
                "wave and assignment must be integers")
        require(row["receipt_present"] is True, "completion remains pending: " + wanted["receipt"])
        require(row == wanted, "spawn observation order, task identity or membership differs")
    require(len({row["agent"] for row in rows}) == 60, "worker identities are not distinct")
    return rows


def receipt_inventory(root, names):
    directory(root)
    observed = {path.name for path in root.glob("w*_a*.md")}
    require(observed == set(names), "missing or extra worker receipts in " + str(root))
    result = {}
    for name in names:
        body = read(root / name)
        require(body.strip() and b"\0" not in body, "empty or invalid worker receipt: " + name)
        body.decode("utf-8")
        result[name] = dict(sha256=sha(body), size_bytes=len(body), line_count=len(body.splitlines()))
    return result


def assemble(rows, development, originals=None):
    validate_observation(rows)
    names = [row["receipt"] for row in rows]
    copies = receipt_inventory(development, names)
    if originals is not None:
        require(receipt_inventory(originals, names) == copies, "original and retained worker receipts differ")
    manifest_body = read(development / "initial-receipts.json")
    require(sha(manifest_body) == INITIAL_SHA256, "initial thirty-receipt manifest changed")
    manifest = decode(manifest_body)
    require(manifest["requested_total"] == 60 and manifest["completed_at_checkpoint"] == 30
            and len(manifest["receipts"]) == 30, "initial checkpoint membership differs")
    for initial, row in zip(manifest["receipts"], rows[:30]):
        require(initial["wave"] == row["wave"] and initial["assignment"] == row["assignment"]
                and initial["receipt"] == row["receipt"], "initial checkpoint ordering differs")
        actual = copies[row["receipt"]]
        require(initial["sha256"] == actual["sha256"] and initial["size_bytes"] == actual["size_bytes"],
                "initial historical receipt changed: " + row["receipt"])
    entries = [dict(wave=row["wave"], assignment=row["assignment"], agent=row["agent"],
                    receipt=row["receipt"], status="completed", **copies[row["receipt"]]) for row in rows]
    require(len({entry["sha256"] for entry in entries}) == 60, "duplicate worker receipt bodies")
    return {
        "schema_version": 1, "record_id": "p05-sixty-worker-completion-v1", "state": "complete",
        "scope": "Completed development assignments and retained receipts; no technical gate or publication acceptance",
        "qualified_implementation_revision": IMPLEMENTATION,
        "requested_workers": 60, "completed_workers": 60, "wave_count": 10, "workers_per_wave": 6,
        "followup_turns_counted_as_workers": False, "coordinator_counted_as_worker": False,
        "original_receipts_compared_at_finalization": True,
        "coordinator_observation": {"canonical_sha256": sha(canonical(rows)), "entries": rows},
        "initial_checkpoint": {"receipt": "initial-receipts.json", "sha256": INITIAL_SHA256,
                               "size_bytes": len(manifest_body), "completed_workers": 30,
                               "published_revision": IMPLEMENTATION},
        "builder": {"path": "build_agent_ledger.py", "sha256": sha(read(Path(__file__).resolve()))},
        "waves": [dict(wave=wave, completed_workers=6,
                       assignments=list(range((wave - 1) * 6 + 1, wave * 6 + 1))) for wave in range(1, 11)],
        "assignments": entries, "receipt_inventory_sha256": sha(canonical(entries)),
        "limitations": [
            "Coordinator spawn observations and final worker receipts identify the actual assignments; this utility does not query or authenticate agent-service history.",
            "An assignment count is not a test count, qualification result, maintainer waiver or completed phase.",
            "Each receipt retains its original execution scope, failures and limitations; follow-up verification does not create a new worker.",
            "Portable verification checks retained receipt identities; the finalization command additionally compares the original scratch receipts.",
        ],
    }


def completed_index(body):
    text = body.decode("utf-8")
    require(text.count(BEGIN) == text.count(END) == 1 and text.index(BEGIN) < text.index(END),
            "development index completion markers are missing or duplicated")
    left = text.index(BEGIN) + len(BEGIN)
    right = text.index(END)
    return (text[:left] + "\n\n" + COMPLETE_TEXT + "\n\n" + text[right:]).encode("utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("build", "verify"))
    parser.add_argument("--development", type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument("--spawn-record", type=Path)
    parser.add_argument("--original-receipts", type=Path)
    args = parser.parse_args()
    try:
        directory(args.development)
        output = args.development / "agent-ledger.json"
        if args.mode == "build":
            require(args.spawn_record is not None and args.original_receipts is not None,
                    "build requires --spawn-record and --original-receipts")
            require(not os.path.lexists(output), "completed ledger already exists; use verify")
            observation_body = read(args.spawn_record)
            rows = decode(observation_body)
            ledger = assemble(rows, args.development, args.original_receipts)
            index_path = args.development / "README.md"
            index_before = read(index_path)
            index_after = completed_index(index_before)
            require(read(args.spawn_record) == observation_body, "coordinator observation changed during finalization")
            require(assemble(rows, args.development, args.original_receipts) == ledger,
                    "receipt inventory changed during finalization")
            require(read(index_path) == index_before, "development index changed during finalization")
            with output.open("x", encoding="utf-8") as stream:
                json.dump(ledger, stream, indent=2, sort_keys=True, allow_nan=False)
                stream.write("\n")
            with tempfile.NamedTemporaryFile(dir=args.development, prefix="agent-ledger-index-", delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(index_after)
            try:
                os.chmod(temporary, stat.S_IMODE(index_path.stat().st_mode))
                os.replace(temporary, index_path)
            finally:
                if temporary.exists():
                    temporary.unlink()
        else:
            require(args.spawn_record is None and args.original_receipts is None,
                    "verify uses only retained ledger and receipt files")
            ledger = decode(read(output))
            rows = ledger["coordinator_observation"]["entries"]
            require(canonical(assemble(rows, args.development)) == canonical(ledger),
                    "retained ledger content or receipt identities differ")
            require(read(args.development / "README.md") == completed_index(read(args.development / "README.md")),
                    "development index does not contain the completed ledger statement")
        print(json.dumps({"outcome": "pass", "mode": args.mode, "completed_workers": 60,
                          "wave_count": 10, "ledger_sha256": sha(read(output))}, sort_keys=True))
        return 0
    except (ValueError, OSError, KeyError, TypeError, UnicodeError) as error:
        print(json.dumps({"outcome": "fail", "reason": str(error)}, sort_keys=True))
        return 2


if __name__ == "__main__":
    sys.exit(main())

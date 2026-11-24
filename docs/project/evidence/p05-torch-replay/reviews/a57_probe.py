#!/usr/bin/env python3
"""Read retained evidence and Git blobs; do not import/run project code or archives."""
import ast
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import subprocess

BASE = Path(__file__).resolve().parents[1]
REPO = BASE / "AI-GPU"
D8 = "d8abc24d2fd5dab5ceddbae3627e3d3eb9750358"
C0 = "c0b44ce64665fe11895f869eea8c38c9b820d6f7"
inputs = {}


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def read(path):
    raw = (BASE / path).read_bytes()
    inputs[path] = {"sha256": sha(raw), "size_bytes": len(raw)}
    return raw


def data(path):
    return json.loads(read(path))


def git(*args, optional=False):
    result = subprocess.run(["git", *args], cwd=REPO, capture_output=True, check=False)
    if optional and result.returncode:
        return None
    assert result.returncode == 0, result.stderr.decode()
    return result.stdout


def parse_blocks(text):
    """Independent block parser; result rows and failed subtests stay distinct."""
    lines = text.splitlines()
    cutoff = next((i for i, line in enumerate(lines) if line == "=" * 70), len(lines))
    pattern = re.compile(r"^(test_\w+|setUpClass) \(([^)]+)\)(?: \.\.\.(.*))?$")
    starts = [(i, match) for i, line in enumerate(lines[:cutoff])
              if (match := pattern.fullmatch(line))]
    rows = []
    for n, (i, match) in enumerate(starts):
        stop = starts[n + 1][0] if n + 1 < len(starts) else cutoff
        parts = [(i + 1, (match[3] or "").strip())]
        parts += [(k + 1, lines[k]) for k in range(i + 1, stop)]
        subtests = []
        terminals = []
        for number, line in parts:
            sub = re.fullmatch(r"  test_\w+ \(([^)]+)\)(.*?) \.\.\. (FAIL|ERROR)", line)
            if sub:
                assert sub[1] == match[2]
                subtests.append({"line": number, "parameters": sub[2].strip(), "result": sub[3]})
                continue
            tail = line.rsplit(" ... ", 1)[-1]
            if re.fullmatch(r"ok|FAIL|ERROR|skipped .+|expected failure|unexpected success", tail):
                terminals.append((number, tail))
        if subtests:
            assert not terminals
            outcome = "failed_subtests"
        else:
            assert len(terminals) == 1, (match[2], terminals)
            outcome = terminals[0][1]
        rows.append({"id": match[2], "kind": "class_setup" if match[1] == "setUpClass" else "method",
                     "line": i + 1, "result": outcome, "subtests": subtests})
    assert len(rows) == len({(row["kind"], row["id"]) for row in rows})
    return rows, lines


def static_class_ids(raw, module, class_name=None):
    result = []
    for node in ast.parse(raw).body:
        if isinstance(node, ast.ClassDef) and (class_name is None or node.name == class_name):
            result += [f"{module}.{node.name}.{child.name}" for child in node.body
                       if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
                       and child.name.startswith("test_")]
    return sorted(result)


local_result = data("validation/governance-result.json")
selected = data("validation/governance-test-ids.json")
before = data("validation/governance-before.json")
a43 = data("agent-notes/a43-reconciliation.json")
hosted_result = data("validation/d8-hosted-governance-results.json")
local_raw = read("validation/governance.log").decode()
step_raw = read("validation/d8-hosted-governance-test-step.log").decode()
decoded_raw = read("validation/d8-hosted-governance-decoded.log")
read("validation/reconcile_hosted_governance.py")
read("validation/run_governance.py")
local_rows, local_lines = parse_blocks(local_raw)
hosted_rows, step_lines = parse_blocks(step_raw)
decoded_lines = [re.sub(r"^\d{4}-\d\d-\d\dT\S+Z\s?", "", line)
                 for line in decoded_raw.decode().splitlines()]
offset = decoded_lines.index(step_lines[0])
assert decoded_lines[offset:offset + len(step_lines)] == step_lines
assert sha(decoded_raw) == hosted_result["decoded_log_sha256"]
assert len(decoded_raw) == hosted_result["decoded_log_size_bytes"]
assert hosted_result["source_revision"] == D8
assert hosted_result["source_identity_lines"] == [f"Source: {D8} (tracked changes: False)"]
assert all(line in decoded_lines for line in hosted_result["source_identity_lines"])
assert hosted_result["summary_lines"] == ["Ran 4610 tests in 2311.819s", "OK (skipped=23)"]
assert step_lines[-1] == "OK (skipped=23)"
assert hosted_result["summary_lines"][0] in step_lines
assert len(hosted_rows) == len(hosted_result["rows"])
for row, stored in zip(hosted_rows, hosted_result["rows"]):
    assert (row["id"], row["kind"], row["result"], row["line"] + offset) == (
        stored["id"], stored["kind"], stored["result"], stored["log_line"])

local_methods = {row["id"]: row for row in local_rows if row["kind"] == "method"}
hosted_methods = {row["id"]: row for row in hosted_rows if row["kind"] == "method"}
local_setups = [row for row in local_rows if row["kind"] == "class_setup"]
hosted_setups = [row for row in hosted_rows if row["kind"] == "class_setup"]
failed = {name: row for name, row in local_methods.items() if row["result"] == "failed_subtests"}
errored_classes = {row["id"]: row for row in local_setups if row["result"] == "ERROR"}
blocked = {name: errored_classes[name.rsplit(".", 1)[0]] for name in selected
           if name.rsplit(".", 1)[0] in errored_classes}
local_skipped = {name for name, row in local_methods.items() if row["result"].startswith("skipped ")}
hosted_skipped = {name for name, row in hosted_methods.items() if row["result"].startswith("skipped ")}
local_skipped_classes = {row["id"] for row in local_setups if row["result"].startswith("skipped ")}
hosted_skipped_classes = {row["id"] for row in hosted_setups if row["result"].startswith("skipped ")}
assert local_skipped == hosted_skipped and local_skipped_classes == hosted_skipped_classes
class_skipped_ids = {name for name in selected if name.rsplit(".", 1)[0] in local_skipped_classes}
assert set(selected) - set(local_methods) == set(blocked) | class_skipped_ids
assert len(selected) == len(set(selected)) == 4633
assert len(local_methods) == local_result["tests_run"] == 4595
assert len(failed) == 8 and len(blocked) == 23 and len(errored_classes) == 2
assert sum(len(row["subtests"]) for row in failed.values()) == local_result["failures"] == 55
assert len(local_skipped) == 21 and len(class_skipped_ids) == 15
assert local_result["success"] is False and local_result["errors"] == 2 and local_result["skips"] == 23
assert "Ran 4595 tests in 2974.160s" in local_lines
assert local_lines[-1] == "FAILED (failures=55, errors=2, skipped=23)"
assert len(hosted_methods) == hosted_result["method_results"] == 4610
assert sum(row["result"] == "ok" for row in hosted_methods.values()) == 4589
assert len(hosted_setups) == 2
assert set(a43["governance"]["nonpassing_ids"]["F"]) == set(failed)
assert set(a43["governance"]["nonpassing_ids"]["E"]) == set(blocked)
assert all(row["result"] in ("ok", "failed_subtests") or row["result"].startswith("skipped ")
           for row in local_methods.values())

for class_id in local_skipped_classes | set(errored_classes):
    module, cls = class_id.split(".", 1)
    blob = git("show", f"{D8}:ci/project/{module}.py")
    assert set(static_class_ids(blob, module, cls)) == {
        name for name in selected if name.rsplit(".", 1)[0] == class_id}

mapping = []
for name in sorted(set(failed) | set(blocked)):
    hosted = hosted_methods[name]
    assert hosted["result"] == "ok"
    literal = step_lines[hosted["line"] - 1]
    assert literal == f"{name.rsplit('.', 1)[1]} ({name}) ... ok"
    if name in failed:
        local = failed[name]
        record = {"id": name, "local_outcome": "failed_parent", "local_line": local["line"],
                  "failed_subtest_events": len(local["subtests"]),
                  "local_subtest_lines": [event["line"] for event in local["subtests"]]}
    else:
        local = blocked[name]
        record = {"id": name, "local_outcome": "class_error_blocked_body",
                  "local_class": local["id"], "local_setup_line": local["line"]}
    record.update(hosted_result="ok", hosted_step_line=hosted["line"],
                  hosted_decoded_line=hosted["line"] + offset)
    mapping.append(record)

receipts = [ast.literal_eval(line.split(" : ", 1)[1]) for line in local_lines
            if line.startswith("AssertionError: None not found in (0, 1, 2) : ")]
assert len(receipts) == 55
for receipt in receipts:
    assert receipt["outcome"] == "blocked" and receipt["reason"] == "disk_reserve"
    assert receipt["process_started"] is False and receipt["exit_code"] is None
    assert receipt["duration_seconds"] == 0 and receipt["log_sha256"] is None
assert local_raw.count("AssertionError: Host command failed: disk_reserve (exit None)") == 2

hosted_reconstructed_selection = set(hosted_methods) | class_skipped_ids
local_only = sorted(set(selected) - hosted_reconstructed_selection)
assert hosted_reconstructed_selection <= set(selected)
assert len(hosted_reconstructed_selection) == 4625 and len(local_only) == 8
assert Counter(name.split(".")[0] for name in local_only) == {
    "test_p05_replay_lineage": 3, "test_p05_replay_nested_archives": 5}
assert all(local_methods[name]["result"] == "ok" for name in local_only)
assert {name for name in hosted_methods if name.startswith("test_p05_")} == set(
    data("validation/reader-core-suite-test-ids.json"))

source_paths = [
    "ci/project/baseline_process.py", "ci/project/p06_dependency_build.py", "ci/project/tensor_host_tools.py",
    "ci/project/test_p06_dependency_build.py", "ci/project/test_p06_dependency_option_controls.py",
    "ci/project/test_p06_dependency_receipt.py", "ci/project/test_p06_workspace_caller.py",
    "ci/project/test_p06_workspace_edges.py", "ci/project/test_p06_workspace_model_guard.py",
    "ci/project/p05_replay_installation.py", "ci/project/p05_replay_native.py",
    "ci/project/p05_torch_replay.py", "ci/project/test_p05_replay_effective_headers.py",
    "ci/project/test_p05_replay_lineage.py", "ci/project/test_p05_replay_nested_archives.py",
    "docs/project/evidence/p05-torch/reviews/archive_reader.py"]
before_hashes = {row["path"]: row["sha256"] for row in before["files"]}
source_identity = []
for path in source_paths:
    current = read("AI-GPU/" + path)
    published = git("show", f"{D8}:{path}", optional=True)
    historical = git("show", f"{C0}:{path}", optional=True)
    row = {"path": path, "current_sha256": sha(current), "broad_run_sha256": before_hashes.get(path),
           "d8_blob_sha256": sha(published) if published is not None else None,
           "c0_blob_sha256": sha(historical) if historical is not None else None}
    source_identity.append(row)
    if path in source_paths[:9]:
        assert row["current_sha256"] == row["broad_run_sha256"] == row["d8_blob_sha256"] == row["c0_blob_sha256"]
header_ids = static_class_ids((REPO / "ci/project/test_p05_replay_effective_headers.py").read_bytes(),
                              "test_p05_replay_effective_headers")
assert len(header_ids) == 5 and not set(header_ids) & (set(selected) | hosted_reconstructed_selection)
header_receipt = data("agent-notes/a47-fix-validation.json")
assert header_receipt["tests_run"] == 5 and header_receipt["exit_code"] == 0
assert header_receipt["source_stable"] is True and header_receipt["public_replay_executed"] is False
for path, digest in header_receipt["source_after"].items():
    assert sha((REPO / path).read_bytes()) == digest

replays = []
for name in ["fp16-replay", "bf16-replay", "c6-fp16-replay", "c6-bf16-replay"]:
    path = f"validation/{name}.json"
    replay = data(path)
    flags = {key: replay[key] for key in ["acceptance_claimed", "phase_acceptance", "native_execution",
                                        "retained_code_executed", "host_fault_semantics_revalidated"]}
    assert flags == {"acceptance_claimed": False, "phase_acceptance": False, "native_execution": "not_run",
                     "retained_code_executed": False, "host_fault_semantics_revalidated": False}
    replays.append({"path": path, "execution_revision": replay["execution_revision"],
                    "format": replay["format"], "outcome": replay["outcome"],
                    "archive_identity_from_receipt_only": replay["archive_read"]["archive"], "flags": flags,
                    "origin_authenticated_by_replay": replay["provider_record"]["origin_authenticated_by_replay"],
                    "reader_sources": [row for row in replay["reader_sources"]
                                       if row["path"] in source_paths[9:12] + source_paths[-1:]]})
assert all(sha((REPO / row["path"]).read_bytes()) == row["current_sha256"] for row in source_identity)
assert before["git_head_at_start"] == D8 and local_result["source_changed"] == []
assert len(before["files"]) == 480

report = {
    "schema_version": 1, "agent": "a57", "scope": "independent retained-log and local-Git evidence reconciliation",
    "project_tests_executed_by_probe": 0, "archives_opened_by_probe": 0, "network_calls": 0,
    "native_execution": "not_run", "acceptance_claimed": False,
    "probe_sha256": sha(Path(__file__).read_bytes()), "inputs": inputs,
    "hosted": {"revision": D8, "run_id": hosted_result["run_id"], "job_id": hosted_result["job_id"],
               "run_attempt": hosted_result["run_attempt"], "provider_conclusion_from_retained_metadata": "success",
               "raw_summary": hosted_result["summary_lines"], "method_rows": 4610, "passed_methods": 4589,
               "method_skip_events": 21, "class_skip_events": 2, "class_skip_suppressed_bodies": 15,
               "reconstructed_selected_ids": 4625, "full_zero_skip_invocation": False,
               "test_step_to_decoded_line_offset": offset,
               "raw_rows_match_existing_parser_json": True,
               "source_identity_line": hosted_result["source_identity_lines"][0]},
    "local": {"git_head_at_start": D8, "selected_ids": 4633, "method_rows": 4595,
              "passed_methods": 4566, "failed_parent_methods": 8, "failed_subtest_events": 55,
              "class_error_events": 2, "class_error_blocked_bodies": 23,
              "method_skip_events": 21, "class_skip_events": 2, "class_skip_suppressed_bodies": 15,
              "result": "FAILED", "raw_summary": local_lines[-1], "a43_exact_nonpassing_id_sets_match": True,
              "monitored_paths": 480, "recorded_monitored_source_changes": [],
              "whole_checkout_frozen_or_clean": False},
    "exact_hosted_pass_mapping": mapping,
    "selection_reconciliation": {"local_only_p05_ids": local_only,
                                 "same_skipped_method_ids": sorted(local_skipped),
                                 "same_class_skipped_body_ids": sorted(class_skipped_ids),
                                 "later_effective_header_ids_not_in_either_broad_run": header_ids,
                                 "hosted_p05_passed": 534, "local_p05_passed": 542,
                                 "no_additive_or_final_source_coverage_claim": True},
    "source_identity": source_identity,
    "representative_replay_receipts": replays,
    "limits": {
        "local_failed_run_not_reclassified": True,
        "hosted_ok_rows_are_parent_method_results_not_55_enumerated_subtest_results": True,
        "two_class_errors_have_no_retained_full_process_receipt": True,
        "55_failure_receipts_all_disk_reserve_process_not_started": True,
        "root_reported_free_space": "approximately 2.5 GiB before; 658 MiB after; no per-failure sample",
        "disk_growth_causation_or_precise_shortfall_not_established": True,
        "host_fixture_reserve_bytes": 1073741824, "native_p06_reserve_bytes_unchanged": 16106127360,
        "hosted_revision_excludes_later_installation_and_header_fixes": True,
        "local_broad_includes_installation_fix_but_precedes_header_fix": True,
        "five_header_tests_are_separate_focused_source_bound_evidence": True,
        "older_original_replay_receipts_do_not_validate_current_reader_bytes": True,
        "fresh_final_source_validation_remains_root_owned": True,
        "no_current_source_native_execution_or_phase_acceptance_inferred": True,
    },
    "findings": [
        {"severity": "F0", "confidence": "high", "finding": "All eight locally failed parents and all 23 class-error-blocked IDs have exact hosted D8 ok method rows; affected P06 source files match."},
        {"severity": "F2", "confidence": "high", "scope": "existing governance evidence gap",
         "finding": "Neither run supplies a complete zero-skip invocation; D8 success does not erase the failed local run or validate later reader fixes."},
    ],
}
output = BASE / "agent-notes/a57-reconciliation.json"
output.write_text(json.dumps(report, indent=2) + "\n")
print(json.dumps({"output": str(output), "sha256": sha(output.read_bytes()),
                  "exact_hosted_pass_mappings": len(mapping), "failed_parents": len(failed),
                  "class_error_blocked_bodies": len(blocked), "local_only_ids": len(local_only),
                  "later_header_ids": len(header_ids), "project_tests_executed": 0}))

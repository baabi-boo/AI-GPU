#!/usr/bin/env python3
"""Reconcile retained unittest evidence as data; never import or run project tests."""
import argparse
import ast
from collections import Counter, defaultdict
import gzip
import hashlib
import json
from pathlib import Path
import re
import subprocess


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def ids_sha(ids):
    return sha(json.dumps(list(ids), separators=(",", ":")).encode())


def pairs(rows):
    result = {}
    for key, value in rows:
        if key in result:
            raise ValueError("duplicate JSON key: " + key)
        result[key] = value
    return result


def decode(raw):
    return json.loads(raw, object_pairs_hook=pairs,
                      parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))


def need(condition, message):
    if not condition:
        raise ValueError(message)


def parse_verbose(text, timestamped=False):
    """Preserve method outcomes separately from setup and failed subtest events."""
    lines = text.splitlines()
    if timestamped:
        lines = [re.sub(r"^\ufeff?\d{4}-\d\d-\d\dT\S+Z ", "", line) for line in lines]
    rows, setups, subtests, pending = [], [], [], None

    def finish():
        nonlocal pending
        if pending is None:
            return
        if pending.get("status") is None and pending["failed_subtests"]:
            pending["status"] = "failed_subtests"
        need(pending.get("status") is not None, "method without outcome: " + pending["id"])
        rows.append(pending)
        pending = None

    for number, line in enumerate(lines, 1):
        if line == "=" * 70:
            break
        header = re.fullmatch(r"test_\w+ \((test_[\w.]+)\)(?: \.\.\. (.*))?", line)
        setup = re.fullmatch(r"(setUpClass|tearDownClass|setUpModule|tearDownModule) \(([^)]+)\) \.\.\. (.+)", line)
        subtest = re.fullmatch(r"  test_\w+ \((test_[\w.]+)\)(.*?) \.\.\. (FAIL|ERROR|skipped .+)", line)
        status = None
        if header:
            finish()
            pending = {"id": header[1], "start_line": number, "failed_subtests": []}
            status = header[2]
        elif setup:
            finish()
            setups.append({"event": setup[1], "class": setup[2], "status_text": setup[3], "log_line": number})
        elif subtest:
            need(pending is not None and pending["id"] == subtest[1], "subtest without matching parent")
            event = {"id": subtest[1], "parameters": subtest[2].strip(), "status": subtest[3], "log_line": number}
            subtests.append(event)
            pending["failed_subtests"].append(event)
        elif pending is not None and not line.startswith("  test_"):
            tail = re.search(r" \.\.\. (ok|skipped .+|FAIL|ERROR|expected failure|unexpected success)$", line)
            status = tail[1] if tail else (line if line in ("ok", "FAIL", "ERROR", "expected failure", "unexpected success") else None)
        if pending is not None and status:
            if status == "ok" or status.startswith("skipped ") or status in ("FAIL", "ERROR", "expected failure", "unexpected success"):
                need(pending.get("status") is None, "duplicate method outcome")
                pending["status"] = status
                pending["result_line"] = number
    finish()
    need(len(rows) == len({r["id"] for r in rows}), "duplicate method ID")
    return rows, setups, subtests, lines


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[1] / "AI-GPU")
    parser.add_argument("--validation", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    repo = args.repo.resolve()
    validation = (args.validation or repo.parent / "validation").resolve()
    output = (args.output or Path(__file__).with_name("a43-reconciliation.json")).resolve()
    baseline = repo / "docs/project/evidence/p06-qualified-warm/validation"
    inputs = {}

    def data(path, compressed=False):
        path = Path(path)
        raw = path.read_bytes()
        decoded = gzip.decompress(raw) if compressed else raw
        label = str(path.relative_to(repo)) if path.is_relative_to(repo) else "../" + str(path.relative_to(repo.parent))
        inputs[label] = {"sha256": sha(raw), "size_bytes": len(raw)}
        if compressed:
            inputs[label].update(decoded_sha256=sha(decoded), decoded_size_bytes=len(decoded))
        return decoded

    def read(path, compressed=False):
        return decode(data(path, compressed))

    before = read(validation / "governance-before.json")
    result = read(validation / "governance-result.json")
    selected = read(validation / "governance-test-ids.json")
    log = data(validation / "governance.log").decode()
    runner = data(validation / "run_governance.py")
    need(sha(runner) == before["runner_sha256"], "governance runner pin")
    need(len(selected) == len(set(selected)) == result["unique_test_ids"] == 4633, "selected ID inventory")
    need(len(before["modules"]) == len(set(before["modules"])) == 282, "selected module inventory")
    need(set(before["modules"]) == {x.split(".")[0] for x in selected}, "selected modules equal IDs")
    rows, setups, subtests, lines = parse_verbose(log)
    by_id = {r["id"]: r for r in rows}
    need(len(rows) == result["tests_run"] == 4595, "actual method row count")
    need(set(by_id) <= set(selected), "unexpected executed IDs")
    need(all(s["event"] == "setUpClass" for s in setups), "unexpected fixture event")
    need(all(s["status_text"] == "ERROR" or s["status_text"].startswith("skipped ") for s in setups), "unexpected fixture status")
    missing = set(selected) - set(by_id)
    setup_ids = set()
    for event in setups:
        ids = [x for x in selected if x.rsplit(".", 1)[0] == event["class"]]
        need(ids and not set(ids) & set(by_id), "class fixture body unexpectedly ran")
        event["suppressed_ids"] = ids
        event["suppressed_count"] = len(ids)
        setup_ids.update(ids)
    need(missing == setup_ids, "unexplained missing ID")
    need([r["id"] for r in rows] == [x for x in selected if x not in setup_ids], "actual method order differs from selection")

    details = []
    pattern = r"^={70}\n((?:FAIL|ERROR): .+)\n-{70}\n"
    matches = list(re.finditer(pattern, log, re.M))
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else log.index("\n" + "-" * 70 + "\nRan ", match.end())
        body = log[match.end():end].rstrip()
        head = match[1]
        record = {"header": head, "detail_line": log.count("\n", 0, match.start()) + 2,
                  "traceback_sha256": sha(body.encode()), "confidence": "high"}
        if head.startswith("FAIL:"):
            failed = re.fullmatch(r"FAIL: test_\w+ \((test_[\w.]+)\)(.*)", head)
            need(failed is not None, "unrecognized failure header")
            receipt_line = next(l for l in body.splitlines() if l.startswith("AssertionError: None not found in (0, 1, 2) : "))
            receipt = ast.literal_eval(receipt_line.split(" : ", 1)[1])
            need(receipt["outcome"] == "blocked" and receipt["reason"] == "disk_reserve"
                 and receipt["process_started"] is False and receipt["exit_code"] is None
                 and receipt["duration_seconds"] == 0 and receipt["log_sha256"] is None,
                 "failure is not an explicit prelaunch disk-reserve block")
            record.update(id=failed[1], parameters=failed[2].strip(), classification="resource_admission_block_before_child_launch",
                          reason=receipt["reason"], process_started=False, exit_code=None)
        else:
            failed = re.fullmatch(r"ERROR: setUpClass \((test_[\w.]+)\)", head)
            need(failed is not None and "AssertionError: Host command failed: disk_reserve (exit None)" in body,
                 "unclassified setup error")
            record.update(class_name=failed[1], classification="resource_disk_reserve_class_setup_error",
                          reason="disk_reserve", exit_code=None,
                          process_started="not retained; no launch is strongly supported by helper/monitor source and exit None")
        details.append(record)
    failure_details = [r for r in details if r["header"].startswith("FAIL:")]
    error_details = [r for r in details if r["header"].startswith("ERROR:")]
    need(len(failure_details) == len(subtests) == result["failures"] == 55, "failure/subtest counts")
    need(len(error_details) == result["errors"] == 2, "class error count")
    need([(r["id"], r["parameters"]) for r in failure_details]
         == [(r["id"], r["parameters"]) for r in subtests], "failure detail/subtest identity join")
    need(all(r["status"] == "FAIL" for r in subtests), "nonfailure subtest")
    passed = {r["id"] for r in rows if r["status"] == "ok"}
    skipped = {r["id"] for r in rows if r["status"].startswith("skipped ")}
    failed_parents = {r["id"] for r in rows if r["status"] == "failed_subtests"}
    need(passed | skipped | failed_parents == set(by_id), "unknown method status")
    class_skipped = {x for s in setups if s["status_text"].startswith("skipped ") for x in s["suppressed_ids"]}
    class_error = {x for s in setups if s["status_text"] == "ERROR" for x in s["suppressed_ids"]}
    need(len(skipped) + sum(s["status_text"].startswith("skipped ") for s in setups) == result["skips"] == 23,
         "skip event count")
    need((len(passed), len(skipped), len(failed_parents), len(class_skipped), len(class_error))
         == (4566, 21, 8, 15, 23), "method/body outcome accounting")
    need([l for l in lines if re.fullmatch(r"Ran \d+ tests in [\d.]+s", l)] == ["Ran 4595 tests in 2974.160s"], "finished run line")
    need([l for l in lines if re.match(r"^(OK|FAILED)(?: \(.*\))?$", l)] == ["FAILED (failures=55, errors=2, skipped=23)"], "finished outcome line")
    need(result["elapsed_seconds"] == 2974.16 and result["success"] is False
         and result["source_changed"] == [] and result["native_execution"] == "not_run", "result summary identity")

    discovery = read(baseline / "w05_a05-current-discovery.json.gz", True)
    old_ids = discovery["ids"]
    historical = read(baseline / "coverage/final-reconciliation.json")
    coverage_raw = data(baseline / "coverage/final-id-coverage.json.gz", True)
    coverage = decode(coverage_raw)
    need(len(old_ids) == len(set(old_ids)) == 4527 and ids_sha(old_ids) == discovery["canonical_ids_sha256"]
         == historical["canonical_ids_sha256"], "historical selected IDs")
    need(sha(coverage_raw) == historical["coverage_decoded_sha256"]
         and sha((baseline / "coverage/final-id-coverage.json.gz").read_bytes()) == historical["coverage_gzip_sha256"],
         "historical coverage retained hashes")
    need([r["id"] for r in coverage] == old_ids and all(r["hosted_passed"] or r["supplement_passed"] for r in coverage),
         "historical complete passing union")
    hosted_raw = data(baseline / "hosted-c0b44ce6/w09_a03-job.log.gz", True)
    need(sha(hosted_raw) == historical["hosted_log_utf8_sha256"], "historical hosted log pin")
    hosted_rows, hosted_setups, hosted_subtests, _ = parse_verbose(hosted_raw.decode(), True)
    hosted_passed = {r["id"] for r in hosted_rows if r["status"] == "ok"}
    need(not hosted_subtests and len(hosted_passed) == 4491
         and len(hosted_rows) == 4512 and len(hosted_setups) == 2, "historical raw hosted outcomes")
    supplement_root = baseline / "coverage/supplement-result"
    supplement = read(supplement_root / "execution.json")
    need(sha((supplement_root / "execution.json").read_bytes()) == historical["supplemental_execution_sha256"], "historical supplement pin")
    need(supplement["state"] == "finished" and supplement["outcome"] == "pass"
         and not supplement["failures"] and not supplement["not_run"], "historical supplement finished")
    supplement_passed = set()
    for command in supplement["commands"]:
        raw = data(supplement_root / "output" / (command["log"] + ".gz"), True)
        need(sha(raw) == command["log_sha256"] and len(raw) == command["log_size_bytes"], "historical supplemental raw log")
        sr, sc, ss, _ = parse_verbose(raw.decode())
        need(not sc and not ss and all(r["status"] == "ok" for r in sr), "historical supplement adverse outcome")
        need([r["id"] for r in sr] == command["expected_ids"], "historical supplemental exact IDs")
        supplement_passed.update(r["id"] for r in sr)
    need(len(supplement_passed) == 59 and len(supplement_passed & hosted_passed) == 23
         and supplement_passed | hosted_passed == set(old_ids), "historical 4491 plus 59 minus 23 union")
    need(all(r["hosted_passed"] == (r["id"] in hosted_passed)
             and r["supplement_passed"] == (r["id"] in supplement_passed) for r in coverage),
         "historical raw logs equal retained coverage map")
    need(historical["source_revision"] == discovery["revision"] == supplement["source_revision"]
         == "c0b44ce64665fe11895f869eea8c38c9b820d6f7", "historical source revision")
    need(set(old_ids) <= set(selected), "historical selection omitted IDs")
    additions = set(selected) - set(old_ids)
    need(len(additions) == 106 and all(x.startswith("test_p05_") for x in additions), "106 P05 additions only")

    initial_before = read(validation / "p05-suite-source-before.json")
    initial_after = read(validation / "p05-suite-source-after.json")
    initial_result = read(validation / "p05-suite-result.json")
    initial_log = data(validation / "p05-suite.log")
    core_before = read(validation / "reader-core-suite-before.json")
    core_result = read(validation / "reader-core-suite-result.json")
    core_ids = read(validation / "reader-core-suite-test-ids.json")
    core_log = data(validation / "reader-core-suite.log")
    need(initial_before == initial_after and sha(initial_log) == initial_result["log_sha256"], "initial log and stable source pins")
    need(initial_result["tests_run"] == 520 and initial_result["outcome"] == "pass"
         and all(initial_result[k] == 0 for k in ("failures", "errors", "skips")), "initial result")
    need(core_result["tests_run"] == core_result["unique_test_ids"] == len(core_ids) == len(set(core_ids)) == 534
         and core_result["success"] is True and not core_result["source_changed"]
         and all(core_result[k] == 0 for k in ("failures", "errors", "skips")), "core result")
    need(b"Ran 520 tests in 127.900s\n\nOK\n" in initial_log
         and b"Ran 534 tests in 121.040s\n\nOK\n" in core_log, "focused suite summary logs")
    initial_map = {r["path"]: r["sha256"] for r in initial_before}
    core_map = {r["path"]: r["sha256"] for r in core_before["files"]}
    before_map = {r["path"]: r["sha256"] for r in before["files"]}
    initial_test_paths = sorted(p for p in initial_map if Path(p).name.startswith("test_"))
    initial_modules = {Path(p).stem for p in initial_test_paths}
    need(len(initial_modules) == 23 and all(initial_map[p] == core_map[p] == before_map[p] for p in initial_test_paths),
         "unchanged initial 23 test module hashes")
    initial_ids = [x for x in core_ids if x.split(".")[0] in initial_modules]
    need(len(initial_ids) == 520 and set(initial_ids) <= set(core_ids) <= set(selected), "focused selections nested")
    p05_ids = [x for x in selected if x.startswith("test_p05_")]
    need(len(p05_ids) == 542 and set(p05_ids) <= passed, "all broad P05 IDs passed")
    need(set(p05_ids) - set(core_ids) == {x for x in selected if x.startswith(("test_p05_replay_lineage.", "test_p05_replay_nested_archives."))},
         "core to broad eight added P05 IDs")

    source_paths = {
        "ci/project/baseline_process.py", "ci/project/tensor_host_tools.py", "ci/project/p06_dependency_build.py",
        "ci/project/test_p06_workspace_caller.py", "ci/project/test_p06_workspace_edges.py",
        "ci/project/test_p06_workspace_model_guard.py", "ci/project/test_p06_dependency_build.py",
        "ci/project/test_p06_dependency_option_controls.py", "ci/project/test_p06_dependency_receipt.py",
        "ci/project/p05_execution_records.py", "ci/project/p05_installed_check.py",
        "ci/project/p05_torch_records.py", "ci/project/p05_replay_installation.py", "ci/project/p05_replay_native.py",
        "ci/project/p05_torch_replay.py",
    }
    source_paths |= {"ci/project/" + x.split(".")[0] + ".py" for x in p05_ids}
    source_rows = []
    for path in sorted(source_paths):
        raw = data(repo / path)
        need(sha(raw) == before_map[path], "reviewed source differs from governance snapshot: " + path)
        source_rows.append({"path": path, "sha256": sha(raw)})
    shared_reader_path = "docs/project/evidence/p05-torch/reviews/archive_reader.py"
    shared_reader_raw = data(repo / shared_reader_path)
    need(sha(shared_reader_raw) == "4144becd4fe3c829380f7e66cdb66f7cf073b5e189c2620cd60c62940b9317d3", "shared immutable archive reader pin")
    p06_unmodified = []
    for path in sorted(source_paths):
        if path.startswith("ci/project/test_p06_") or path in ("ci/project/baseline_process.py", "ci/project/tensor_host_tools.py", "ci/project/p06_dependency_build.py"):
            historical_source = subprocess.check_output(["git", "--no-optional-locks", "show", discovery["revision"] + ":" + path], cwd=repo)
            need(sha(historical_source) == before_map[path], "failed/skipped/helper source changed from historical baseline")
            p06_unmodified.append(path)
    diff = subprocess.check_output(["git", "--no-optional-locks", "diff", "f01c9d03147343d274ee0a45b71b34f004709c0e", "--", "ci/project"], cwd=repo)
    current_modules = {p.stem for p in (repo / "ci/project").glob("test_*.py")}
    status_groups = {"P": passed, "S": skipped, "F": failed_parents, "K": class_skipped, "E": class_error}
    status_code = {identifier: key for key, ids in status_groups.items() for identifier in ids}
    need(set(status_code) == set(selected), "one status for every selected ID")
    module_counts = []
    for module in before["modules"]:
        ids = [x for x in selected if x.split(".")[0] == module]
        counts = Counter(status_code[x] for x in ids)
        module_counts.append({"module": module, "selected": len(ids), **dict(sorted(counts.items()))})
    p05_direct_modules = {"test_p05_execution_records", "test_p05_installed_check", "test_p05_torch_records"}
    directly_changed = additions | {x for x in selected if x.split(".")[0] in p05_direct_modules}
    need(len(directly_changed) == 174 and directly_changed <= passed, "174 direct changed-module test outcomes")

    report = {
        "schema_version": 1,
        "agent": "a43",
        "scope": "read-only retained host unittest evidence reconciliation; no test or native execution",
        "probe_sha256": sha(Path(__file__).read_bytes()),
        "project_tests_run_by_probe": 0,
        "native_execution": "not_run",
        "acceptance_claimed": False,
        "governance": {
            "selected_ids": 4633, "selected_modules": 282, "actual_method_rows": 4595,
            "passed_method_ids": 4566, "failed_parent_method_ids": 8, "failed_subtest_events": 55,
            "method_skip_events": 21, "class_skip_events": 2, "class_skip_suppressed_bodies": 15,
            "class_error_events": 2, "class_error_suppressed_bodies": 23,
            "all_nonpassing_selected_ids": 67, "missing_method_rows": 38,
            "elapsed_seconds": 2974.16, "outcome": "FAILED", "result_receipt": result,
            "unexplained_missing_ids": [], "unexpected_ids": [], "duplicate_ids": [],
            "selected_order_sha256": ids_sha(selected),
            "passed_order_sha256": ids_sha(x for x in selected if x in passed),
            "run_order_sha256": ids_sha(r["id"] for r in rows),
            "status_code_order": "one character per ID in governance-test-ids.json; input hash retained below",
            "status_codes": {"P": "passed method", "S": "skipped method", "F": "failed parent with failed subtests",
                             "K": "body omitted by skipped class setup", "E": "body omitted by errored class setup"},
            "status_by_selected_index": "".join(status_code[x] for x in selected),
            "nonpassing_ids": {key: sorted(ids) for key, ids in status_groups.items() if key != "P"},
            "setup_events": setups,
            "method_skip_events_detail": [{"id": r["id"], "reason": r["status"], "log_line": r["result_line"]}
                                          for r in rows if r["id"] in skipped],
            "failed_methods": [{"id": r["id"], "start_line": r["start_line"],
                                "failed_subtests": r["failed_subtests"]} for r in rows if r["id"] in failed_parents],
            "failure_error_details": details,
        },
        "failure_classification": {
            "confidence": "high for explicit resource admission outcomes; no claim of untested code correctness",
            "55_subtest_failures": "Every retained receipt says blocked/disk_reserve, process_started=false, exit_code=null, duration=0, log_sha256=null.",
            "2_class_setup_errors": "Both tracebacks report Host command failed: disk_reserve (exit None); child bodies were never scheduled. Full process receipts were not retained for these two events.",
            "host_fixture_reserve_bytes": 1073741824,
            "p06_native_reserve_unchanged_bytes": 16106127360,
            "cmake_skips": "36 bodies are skipped or suppressed because fixture CMake is missing from its sanitized tool inventory; no claim that ambient CMake is absent.",
            "new_code_failure_demonstrated": False,
            "root_cause_of_disk_consumption_established": False,
            "per_failure_free_byte_measurements_retained": False,
            "exact_physical_capacity_shortfall_or_timing_established": False,
            "untested_failed_and_suppressed_bodies_are_not_passes": True,
            "p06_failure_skip_and_helper_source_equal_historical_revision": p06_unmodified,
        },
        "historical_4527_comparison": {
            "source_revision": discovery["revision"], "source_tree": discovery["tree"],
            "canonical_ids": 4527, "raw_hosted_passed": 4491, "raw_supplement_passed": 59,
            "raw_passing_overlap": 23, "raw_unique_pass_union": 4527,
            "baseline_ids_omitted_from_current_selection": [],
            "current_passed_baseline_ids": len(passed & set(old_ids)),
            "current_nonpassing_baseline_ids": len(set(old_ids) - passed),
            "new_current_ids": 106, "all_additions_are_p05": True,
            "additions_by_module": dict(sorted(Counter(x.split(".")[0] for x in additions).items())),
            "current_skipped_body_ids_equal_historical_hosted_gaps": skipped | class_skipped == set(old_ids) - hosted_passed,
            "historical_pass_is_separate_revision_evidence": True,
            "current_broad_failure_not_overridden_by_historical_passes": True,
            "single_full_zero_skip_invocation_proven": False,
        },
        "p05_overlap_and_outcomes": {
            "initial": {"count": 520, "seconds": 127.9, "passed": True, "explicit_selected_id_file_retained": False,
                        "id_reconstruction": "Filter later explicit 534-ID inventory by the 23 test modules in the initial manifest; all 23 test-file SHA256 values match initial/core/broad manifests.",
                        "reconstructed_ids_sha256": ids_sha(initial_ids)},
            "core": {"count": 534, "seconds": 121.04, "passed": True, "explicit_selected_id_file_retained": True,
                     "selected_ids_sha256": ids_sha(core_ids)},
            "broad": {"count": 542, "passed": 542, "failures": 0, "errors": 0, "skips": 0,
                      "selected_ids_sha256": ids_sha(p05_ids)},
            "initial_core_overlap": 520, "core_broad_overlap": 534, "three_selection_union": 542,
            "broad_additions_to_core": sorted(set(p05_ids) - set(core_ids)),
            "initial_to_core_source_changes": [{"path": p, "before": initial_map[p], "after": core_map[p]}
                                               for p in sorted(initial_map.keys() & core_map.keys()) if initial_map[p] != core_map[p]],
            "core_to_broad_source_changes": [{"path": p, "before": core_map[p], "after": before_map[p]}
                                             for p in sorted(core_map) if core_map[p] != before_map[p]],
            "direct_changed_module_methods": 174, "direct_changed_module_methods_passed": 174,
            "direct_changed_module_scope": "106 new replay IDs plus 23 execution-record, 28 installed-check and 17 torch-record methods; all are included in the 542 total.",
            "module_outcomes": [r for r in module_counts if r["module"].startswith("test_p05_")],
            "no_additive_unique_test_claim": True,
        },
        "source_scope": {
            "git_head_at_governance_start": before["git_head_at_start"],
            "monitored_path_count": len(before["files"]),
            "recorded_before_after_differences": result["source_changed"],
            "monitor_patterns": ["ci/project/*.py", "python/**/*.py", "profiles/*.json", "docs/project/*.json"],
            "whole_checkout_frozen_or_clean_claimed": False,
            "without_concurrent_work_proven": False,
            "concurrency_limitation": "Markdown documentation and separately owned later work occurred concurrently; root owns final-source and documentation checks.",
            "current_unselected_test_module_names_at_probe": sorted(current_modules - set(before["modules"])),
            "current_test_module_check_is_not_final_source_freeze": True,
            "reviewed_source_hashes": source_rows,
            "separately_pinned_shared_reader": {"path": shared_reader_path, "sha256": sha(shared_reader_raw),
                                                "in_governance_monitor": shared_reader_path in before_map},
            "task_python_diff_against_f01_sha256_at_probe": sha(diff),
        },
        "findings": [
            {"severity": "F2", "scope": "execution capacity / governance evidence", "confidence": "high",
             "finding": "The broad run is failed and non-zero-skip; it cannot close the stricter P06 uninterrupted, no-concurrent-work invocation requirement."},
            {"severity": "F0", "scope": "P05 host regression evidence", "confidence": "high",
             "finding": "All 542 selected P05 IDs passed; no prior canonical ID was omitted and 106 additions are P05 only."},
            {"severity": "F0", "scope": "evidence limits", "confidence": "high",
             "finding": "Initial 520 IDs are reconstructible rather than separately retained; successful subtests are not enumerated by this verbose log; counts never add overlapping selections."},
        ],
        "inputs": inputs,
    }
    for path, receipt in inputs.items():
        absolute = repo / path
        need(sha(absolute.read_bytes()) == receipt["sha256"], "input changed while reconciling: " + path)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    compact = {
        "agent": "a43",
        "scope": report["scope"],
        "project_tests_run_by_probe": 0,
        "detail_file": output.name,
        "detail_sha256": sha(output.read_bytes()),
        "probe_sha256": report["probe_sha256"],
        "governance": {key: report["governance"][key] for key in (
            "selected_ids", "selected_modules", "actual_method_rows", "passed_method_ids",
            "failed_parent_method_ids", "failed_subtest_events", "method_skip_events", "class_skip_events",
            "class_skip_suppressed_bodies", "class_error_events", "class_error_suppressed_bodies",
            "all_nonpassing_selected_ids", "missing_method_rows", "elapsed_seconds", "outcome",
            "unexplained_missing_ids", "unexpected_ids", "duplicate_ids")},
        "failure_classification": {key: value for key, value in report["failure_classification"].items()
                                   if key != "p06_failure_skip_and_helper_source_equal_historical_revision"},
        "historical_4527_comparison": report["historical_4527_comparison"],
        "p05": {"initial_passed": 520, "initial_ids_reconstructed_from_unchanged_test_manifests": True,
                "core_passed": 534, "broad_passed": 542, "initial_core_overlap": 520,
                "core_broad_overlap": 534, "unique_union": 542,
                "direct_changed_module_passed": 174,
                "direct_changed_module_scope": report["p05_overlap_and_outcomes"]["direct_changed_module_scope"],
                "broad_additional_tests": {"test_p05_replay_lineage": 3, "test_p05_replay_nested_archives": 5}},
        "source_scope": {key: report["source_scope"][key] for key in (
            "git_head_at_governance_start", "monitored_path_count", "monitor_patterns",
            "recorded_before_after_differences", "whole_checkout_frozen_or_clean_claimed",
            "without_concurrent_work_proven", "concurrency_limitation",
            "current_unselected_test_module_names_at_probe", "current_test_module_check_is_not_final_source_freeze")},
        "p06_single_full_zero_skip_invocation_proven": False,
        "findings": report["findings"],
    }
    compact_path = output.with_name("a43-summary.json")
    compact_path.write_text(json.dumps(compact, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"output": str(output), "sha256": sha(output.read_bytes()),
                      "summary": str(compact_path), "summary_sha256": sha(compact_path.read_bytes()),
                      "governance": "FAILED", "selected": 4633, "ran": 4595, "passed": 4566,
                      "failed_parent_methods": 8, "failed_subtests": 55, "class_errors": 2,
                      "method_skips": 21, "class_skips": 2, "omitted_bodies": 38,
                      "p05_passed": 542, "baseline_selection_omissions": 0,
                      "project_tests_run_by_probe": 0}, sort_keys=True))


if __name__ == "__main__":
    main()

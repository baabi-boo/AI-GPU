#!/usr/bin/env python3
"""A36 evidence collector: focused execution or canonical enumeration only."""

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import time
import traceback
import unittest


NEW_MODULES = [
    "test_p06_qualified_warm_replay_cli",
    "test_p06_qualified_warm_writer_receipts",
    "test_p06_qualified_warm_retention",
    "test_p06_qualified_warm_restore",
    "test_p06_qualified_warm_retention_integration",
    "test_p06_qualified_warm_cleanup",
]
EXISTING_MODULES = [
    "test_p06_qualified_warm_replay",
    "test_p06_qualified_warm_hosted",
    "test_p06_qualified_warm_complete_replay",
]
EXPECTED_FINAL_HASHES = {
    "ci/project/p06_qualified_warm_retention.py": "4645e2a4aac840c87b467b08cb2d338818739d6fbdbbd3ec95a1103dfa11bcbe",
    "ci/project/p06_qualified_warm_restore.py": "21bc047ef9b76232aa79ce5199b82fca48cb6611aab4b61018f8ff9f08bbbf1d",
    "ci/project/test_p06_qualified_warm_cleanup.py": "465be3759f5450809202f4a5be548ea8880cb8e737e1881fba72457d63da75de",
}


def utc():
    return datetime.now(timezone.utc).isoformat()


def digest(body):
    return hashlib.sha256(body).hexdigest()


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def code_inventory(root):
    files = {}
    for path in sorted((root / "ci/project").rglob("*")):
        if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc":
            raw = path.read_bytes()
            files[path.relative_to(root).as_posix()] = {
                "sha256": digest(raw), "size_bytes": len(raw),
                "mode": oct(path.stat().st_mode & 0o777),
            }
    canonical = json.dumps(files, sort_keys=True, separators=(",", ":")).encode()
    return {"scope": "ci/project regular code, tests, fixtures and contract inputs; docs excluded",
            "file_count": len(files), "sha256": digest(canonical), "files": files}


def command():
    env = [f"{key}={value}" for key, value in sorted(os.environ.items())]
    return shlex.join(["/usr/bin/env", "-i", *env, sys.executable, *sys.argv])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("focused", "enumerate"))
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--revision", required=True)
    args = parser.parse_args()
    root = args.source.resolve()
    output = args.output.resolve()
    output.mkdir()
    os.chdir(root)
    sys.path.insert(0, str(root / "ci/project"))
    started_at = utc()
    started = time.monotonic()
    before = code_inventory(root)
    write_json(output / "code-before.json", before)
    launch = {
        "mode": args.mode, "source_root": str(root), "reference_revision": args.revision,
        "started_at": started_at, "command": command(), "environment": dict(os.environ),
        "interpreter": {"requested": sys.executable,
                        "resolved": str(Path(sys.executable).resolve()),
                        "sha256": digest(Path(sys.executable).read_bytes()),
                        "version": sys.version},
        "collector_sha256": digest(Path(__file__).read_bytes()),
        "code_before_sha256": before["sha256"],
        "full_governance_qualification": False,
    }
    write_json(output / "launch.json", launch)
    (output / "command.txt").write_text(launch["command"] + "\n")
    print(json.dumps({"status": "started", "mode": args.mode, "started_at": started_at}), flush=True)
    import governance_run
    loader = unittest.TestLoader()
    if args.mode == "enumerate":
        suite = loader.discover("ci/project", pattern="test_*.py")
    else:
        for name, expected in EXPECTED_FINAL_HASHES.items():
            observed = before["files"].get(name, {}).get("sha256")
            if observed != expected:
                raise RuntimeError(f"Final source mismatch before execution: {name}")
        suite = loader.loadTestsFromNames(NEW_MODULES + EXISTING_MODULES)
    ids = governance_run.collect_test_ids(suite)
    duplicate_ids = sorted(identity for identity, count in Counter(ids).items() if count != 1)
    loader_errors = list(loader.errors)
    loader_errors += [identity for identity in ids if identity.startswith("unittest.loader._FailedTest.")]
    ids_sha = digest("".join(identity + "\n" for identity in ids).encode())
    inventory = {
        "mode": args.mode, "test_count": len(ids), "test_ids_sha256": ids_sha,
        "test_ids": ids, "duplicate_ids": duplicate_ids, "loader_errors": loader_errors,
        "counts_by_module": dict(sorted(Counter(i.split(".")[0] for i in ids).items())),
        "new_module_test_count": sum(i.split(".")[0] in NEW_MODULES for i in ids),
        "existing_module_test_count": sum(i.split(".")[0] in EXISTING_MODULES for i in ids),
        "discovery": {"start_directory": "ci/project", "pattern": "test_*.py"} if args.mode == "enumerate"
                     else {"modules": NEW_MODULES + EXISTING_MODULES},
        "enumeration_is_execution": False,
    }
    write_json(output / "test-ids.json", inventory)
    (output / "test-ids.txt").write_text("".join(i + "\n" for i in ids))
    print(json.dumps({"status": "discovered", "mode": args.mode,
                      "test_count": len(ids), "new_module_test_count": inventory["new_module_test_count"],
                      "loader_error_count": len(loader_errors)}), flush=True)
    result = None
    abort = None
    if args.mode == "focused" and ids and not duplicate_ids and not loader_errors:
        with (output / "events.jsonl").open("w") as events:
            def event_sink(event):
                events.write(json.dumps(event, sort_keys=True) + "\n")
                events.flush()

            def result_factory(*items, **kwargs):
                nonlocal result
                result = governance_run.StrictResult(*items, test_ids=ids,
                    event_sink=event_sink, loader_errors=loader_errors, **kwargs)
                return result

            runner = unittest.TextTestRunner(stream=sys.stderr, verbosity=2,
                resultclass=result_factory, failfast=True)
            try:
                runner.run(suite)
                result.execution_completed = True
            except BaseException as exc:
                abort = {"type": type(exc).__name__, "message": str(exc)}
                if result is not None:
                    result.abort = abort
                traceback.print_exc()
            if result is not None:
                result.finalize()
    after = code_inventory(root)
    write_json(output / "code-after.json", after)
    changed = sorted(name for name in set(before["files"]) | set(after["files"])
                     if before["files"].get(name) != after["files"].get(name))
    accounting = result.summary if result is not None else None
    summary = {
        "scope": "focused development validation" if args.mode == "focused" else "canonical discovery only",
        "mode": args.mode, "source_root": str(root), "reference_revision": args.revision,
        "started_at": started_at, "finished_at": utc(),
        "duration_seconds": round(time.monotonic() - started, 6),
        "command": launch["command"], "test_count": len(ids), "test_ids_sha256": ids_sha,
        "counts_by_module": inventory["counts_by_module"],
        "new_module_test_count": inventory["new_module_test_count"],
        "existing_module_test_count": inventory["existing_module_test_count"],
        "loader_errors": loader_errors, "duplicate_ids": duplicate_ids,
        "execution": accounting, "abort": abort,
        "tests_executed": result.testsRun if result is not None else 0,
        "success_count": sum(count for (_, outcome), count in result.outcomes.items() if outcome == "success")
                         if result is not None else 0,
        "failures": result.failures if result is not None else [],
        "errors": result.errors if result is not None else [],
        "skips": result.skipped if result is not None else [],
        "expected_failures": result.expectedFailures if result is not None else [],
        "unexpected_successes": result.unexpectedSuccesses if result is not None else [],
        "code_scope": before["scope"], "code_file_count": before["file_count"],
        "code_before_sha256": before["sha256"], "code_after_sha256": after["sha256"],
        "code_stable": not changed, "code_changed_paths": changed,
        "full_suite_executed": False, "full_governance_qualification": False,
        "native_execution": "not_run", "retry_count": 0,
    }
    success = not loader_errors and not duplicate_ids and bool(ids) and not changed and abort is None
    if args.mode == "focused":
        success = success and result is not None and result.strict_success
    summary["status"] = ("focused_pass" if args.mode == "focused" else "enumeration_complete") if success else "failed"
    write_json(output / "summary.json", summary)
    print(json.dumps({"status": summary["status"], "tests_executed": summary["tests_executed"],
                      "success_count": summary["success_count"], "duration_seconds": summary["duration_seconds"],
                      "code_stable": summary["code_stable"]}), flush=True)
    return 0 if success else 1


if __name__ == "__main__":
    raise SystemExit(main())

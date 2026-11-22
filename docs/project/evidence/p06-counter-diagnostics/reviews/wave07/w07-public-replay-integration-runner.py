"""Focused test accounting; no discovery, native execution, or evidence writes."""

import argparse
from datetime import datetime, timezone
import hashlib
import importlib
import io
import json
from pathlib import Path
import sys
import time
import unittest


class AccountedResult(unittest.TextTestResult):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.started_methods = []
        self.passed_methods = []
        self.subtests = []

    def startTest(self, test):
        self.started_methods.append(test.id())
        super().startTest(test)

    def addSuccess(self, test):
        self.passed_methods.append(test.id())
        super().addSuccess(test)

    def addSubTest(self, test, subtest, error):
        self.subtests.append({"method": test.id(), "case": str(subtest),
                              "outcome": "pass" if error is None else "fail"})
        super().addSubTest(test, subtest, error)


def method_ids(suite):
    if isinstance(suite, unittest.TestSuite):
        return [name for child in suite for name in method_ids(child)]
    return [suite.id()]


def run_accounted(suite, label, *, log_path, result_path, source_paths=()):
    declared = method_ids(suite)
    started = datetime.now(timezone.utc).isoformat()
    before = {str(path): hashlib.sha256(Path(path).read_bytes()).hexdigest() for path in source_paths}
    stream = io.StringIO()
    clock = time.monotonic()
    result = unittest.TextTestRunner(stream=stream, verbosity=2, resultclass=AccountedResult).run(suite)
    seconds = time.monotonic() - clock
    after = {str(path): hashlib.sha256(Path(path).read_bytes()).hexdigest() for path in source_paths}
    record = {"label": label, "started_at": started, "duration_seconds": seconds,
              "declared_method_count": len(declared), "declared_methods": declared,
              "executed_method_count": result.testsRun, "executed_methods": result.started_methods,
              "passed_method_count": len(result.passed_methods), "passed_methods": result.passed_methods,
              "unexecuted_method_count": len(set(declared) - set(result.started_methods)),
              "unexecuted_methods": sorted(set(declared) - set(result.started_methods)),
              "skip_events": [{"test": str(test), "reason": reason} for test, reason in result.skipped],
              "subtest_count": len(result.subtests), "subtests": result.subtests,
              "failure_count": len(result.failures), "error_count": len(result.errors),
              "sources_before": before, "sources_after": after,
              "sources_unchanged": before == after, "successful": result.wasSuccessful(),
              "native_execution": "not_run"}
    Path(result_path).write_text(json.dumps(record, indent=2) + "\n")
    output = stream.getvalue()
    with Path(log_path).open("a") as log:
        log.write("\n=== " + label + " @ " + started + " ===\n")
        log.write(output)
        log.write("ACCOUNTING " + json.dumps({key: value for key, value in record.items()
                  if key.endswith("_count") or key in ("successful", "sources_unchanged", "native_execution")}) + "\n")
        for row in result.subtests:
            log.write("SUBTEST " + json.dumps(row, sort_keys=True) + "\n")
    print(output, end="")
    print("ACCOUNTING", json.dumps({key: value for key, value in record.items()
          if key.endswith("_count") or key in ("successful", "sources_unchanged", "native_execution")}))
    return result.wasSuccessful() and before == after


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("module")
    parser.add_argument("--label", required=True)
    parser.add_argument("--log", required=True)
    parser.add_argument("--result", required=True)
    args = parser.parse_args()
    module = importlib.import_module(args.module)
    suite = unittest.defaultTestLoader.loadTestsFromModule(module)
    root = Path.cwd()
    tracked = [root / "ci/project/test_p06_counter_public_replay.py",
               root / "ci/project/p06_counter_public_replay.py",
               root / "ci/project/p06_counter_diagnostics_replay.py",
               root / "ci/project/p06_counter_public_records.py",
               root / "ci/project/test_p06_counter_public_records.py",
               root / "ci/project/p06_counter_source_inventory.py"]
    sys.exit(0 if run_accounted(suite, args.label, log_path=args.log, result_path=args.result,
                               source_paths=tracked) else 1)

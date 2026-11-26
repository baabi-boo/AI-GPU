import hashlib
import importlib
import json
import os
from pathlib import Path
import subprocess
import sys
import types
import unittest

repo = Path.cwd()
output = Path(os.environ["TMPDIR"])
sys.path.insert(0, str(repo / "ci/project"))
paths = ["ci/project/governance_replay_archive.py", "ci/project/test_governance_archive_input_ownership.py"]
def hashes():
    return {path: hashlib.sha256((repo / path).read_bytes()).hexdigest() for path in paths}

before = hashes()
head = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
status = subprocess.check_output(["git", "status", "--short"], text=True)
module = importlib.import_module("test_governance_archive_input_ownership")
current = module.reader
baseline_source = subprocess.check_output(["git", "show", "81d7a35c641f3a969c23c8e604f7468a4d88644a:ci/project/governance_replay_archive.py"])
baseline = types.ModuleType("a009_baseline_archive")
exec(compile(baseline_source, "git-show:81d7a35c:governance_replay_archive.py", "exec"), baseline.__dict__)
summary = {"head": head, "git_status": status, "before_sha256": before,
           "baseline_revision": "81d7a35c641f3a969c23c8e604f7468a4d88644a",
           "baseline_sha256": hashlib.sha256(baseline_source).hexdigest(), "runs": {}}
for label, reader in (("candidate", current), ("baseline", baseline)):
    module.reader = reader
    suite = unittest.defaultTestLoader.loadTestsFromModule(module)
    with (output / (label + ".log")).open("w") as stream:
        result = unittest.TextTestRunner(stream=stream, verbosity=2).run(suite)
    summary["runs"][label] = {"tests": result.testsRun, "failures": len(result.failures),
                              "errors": len(result.errors), "skips": len(result.skipped),
                              "failed_ids": [test.id() for test, _ in result.failures],
                              "error_ids": [test.id() for test, _ in result.errors]}
summary["after_sha256"] = hashes()
summary["source_stable"] = summary["before_sha256"] == summary["after_sha256"]
summary["final_head"] = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
(output / "results.json").write_text(json.dumps(summary, indent=2) + "\n")
print(json.dumps(summary, indent=2))
assert summary["source_stable"], "source changed during test execution"
assert summary["runs"]["candidate"] == {"tests": 9, "failures": 0, "errors": 0, "skips": 0, "failed_ids": [], "error_ids": []}
assert summary["runs"]["baseline"]["failures"] + summary["runs"]["baseline"]["errors"] >= 3

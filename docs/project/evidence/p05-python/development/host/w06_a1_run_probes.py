"""Use only W06 A1's freshly built FP16 fake; do not compile or modify its pin."""

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

NOTES = Path(__file__).resolve().parent
REPO = NOTES.parent / "AI-GPU"
sys.path.insert(0, str(REPO / "ci/project"))
from p05_test_runtime import TestRuntime


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


work = NOTES / "w06_a1-probes"
work.mkdir()
runtime_root = NOTES / "w06_a1-native/fp16"
extension, = (runtime_root / "python/vortex_ai").glob("_native*.so")
runtime = TestRuntime(runtime_root, runtime_root / "bundle", runtime_root / "python",
                      extension, runtime_root / "generated/p05_build_config.h", "fp16", ())
manifest = json.loads((runtime.bundle / "manifest.json").read_text())
assert all(sha(REPO / row["path"]) == row["sha256"] for row in manifest["binding_sources"])
original_hashes = {str(p.relative_to(runtime_root)): sha(p) for p in runtime_root.rglob("*")
                   if p.is_file()}
child = NOTES / "w06_a1_probe_child.py"
report = {"scope": "host-only-fault-injection", "extension_sha256": sha(extension),
          "manifest_sha256": sha(runtime.bundle / "manifest.json"),
          "source_sha256": manifest["source_sha256"],
          "probe_child_sha256": sha(child), "probe_runner_sha256": sha(__file__),
          "original_artifact_sha256": original_hashes, "results": []}
cases = [
    ("absolute_colon", "left:right", False, "separators or expansion tokens"),
    ("absolute_semicolon", "left;right", False, "separators or expansion tokens"),
    ("absolute_dollar", "left$ORIGINright", False, "separators or expansion tokens"),
    ("absolute_linefeed", "left\nright", False, "without control characters"),
    ("absolute_delete", "left\x7fright", False, "without control characters"),
    ("relative_cwd_dollar", "cwd$ORIGIN", True, "separators or expansion tokens"),
]


def execute(name, mode, bundle, cwd, expected=None):
    target = work / "children" / name
    target.mkdir(parents=True)
    env = runtime.environment({"P05_TEST_BUNDLE": str(bundle)})
    if expected:
        env["P05_EXPECT_PATH_ERROR"] = expected
    command = [sys.executable, "-B", str(child), mode]
    row = {"name": name, "mode": mode, "command": command, "cwd": str(cwd),
           "bundle_argument": str(bundle), "timeout_seconds": 20,
           "pythonpath": env["PYTHONPATH"], "expected_error": expected}
    (target / "command.json").write_text(json.dumps(row, indent=2, sort_keys=True) + "\n")
    began = time.monotonic()
    try:
        result = subprocess.run(command, cwd=cwd, env=env, capture_output=True,
                                text=True, timeout=20, check=False)
        row.update(returncode=result.returncode, stdout=result.stdout, stderr=result.stderr,
                   passed=result.returncode == 0 and not result.stderr)
    except subprocess.TimeoutExpired as error:
        row.update(returncode=None, stdout=str(error.stdout or ""), stderr=str(error.stderr or ""),
                   passed=False, failure="child exceeded 20-second deadline")
    row["seconds"] = round(time.monotonic() - began, 3)
    (target / "stdout.log").write_text(row["stdout"])
    (target / "stderr.log").write_text(row["stderr"])
    if row["passed"]:
        row["observations"] = json.loads(row["stdout"])
    report["results"].append(row)
    (work / "results.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps({key: row[key] for key in ("name", "returncode", "passed", "seconds")}), flush=True)


for name, dirname, relative, expected in cases:
    copied = work / "copies" / name / dirname / "bundle"
    shutil.copytree(runtime.bundle, copied)
    assert sha(copied / "manifest.json") == report["manifest_sha256"]
    assert all(sha(copied / row["path"]) == row["sha256"] for row in manifest["artifacts"])
    execute(name, "path_reject", "bundle" if relative else copied,
            copied.parent if relative else work, expected)
safe = work / "copies/safe/bundle"
shutil.copytree(runtime.bundle, safe)
execute("safe_copy_positive_control", "path_accept", safe, work)
for name in ("pending_close", "lazy_submit", "lazy_memory_info", "empty_owners"):
    execute(name, name, runtime.bundle, work)
report["original_artifacts_unchanged"] = all(sha(runtime_root / name) == digest
                                             for name, digest in original_hashes.items())
report["source_unchanged"] = all(sha(REPO / row["path"]) == row["sha256"]
                                  for row in manifest["binding_sources"])
report["completed"] = len(report["results"])
report["passed"] = sum(row["passed"] for row in report["results"])
(work / "results.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
assert report["original_artifacts_unchanged"] and report["source_unchanged"]
sys.exit(0 if report["completed"] == report["passed"] else 1)

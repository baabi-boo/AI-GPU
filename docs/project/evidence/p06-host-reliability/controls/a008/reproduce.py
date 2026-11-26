import hashlib
import json
from pathlib import Path
import subprocess
import sys

source = Path(sys.argv[1]).resolve()
output = Path(__file__).resolve().parent
base_revision = "30b2e8ca69fba47646392c0cf6650cbb75155843"
sys.path.insert(0, str(source / "ci/project"))
from test_p05_ci_workflow import children, script, steps, workflow

base = subprocess.run(
    ["git", "show", base_revision + ":.github/workflows/ci.yml"],
    cwd=source, capture_output=True, check=True,
).stdout
current = (source / ".github/workflows/ci.yml").read_bytes()
snapshots = {"base": base, "current": current}
scripts = {}
for label, body in snapshots.items():
    path = output / (label + "-ci.yml")
    path.write_bytes(body)
    job = children(children(workflow(path), "jobs", 2), "complete", 4)
    gate, = [step for step in steps(job) if step.get("name", (None,))[0] == "Gate"]
    scripts[label] = script(gate)

names = ("PLAN_RESULT", "PLAN_RUN", "SETUP_RESULT", "BUILD_RESULT", "TESTS_RESULT")
cases = {
    "plan_cancelled": ("cancelled", "", "skipped", "skipped", "skipped"),
    "setup_cancelled": ("success", "true", "cancelled", "skipped", "skipped"),
    "build_cancelled": ("success", "true", "success", "cancelled", "skipped"),
    "tests_cancelled": ("success", "true", "success", "success", "cancelled"),
}
records = []
for name, values in cases.items():
    environment = dict(zip(names, values))
    runs = {}
    for label, body in scripts.items():
        if label == "base":
            failure = any(environment[key] == "failure" for key in names if key != "PLAN_RUN")
            body = body.replace("${{ contains(needs.*.result, 'failure') }}", str(failure).lower())
            body = body.replace("${{ needs.tests.result }}", environment["TESTS_RESULT"])
        result = subprocess.run(
            ["/bin/bash", "--noprofile", "--norc", "-c", body],
            env={"PATH": "/usr/bin:/bin", "LC_ALL": "C", **environment},
            text=True, capture_output=True, timeout=5,
        )
        runs[label] = {"returncode": result.returncode, "stdout": result.stdout, "stderr": result.stderr}
    assert runs["base"]["returncode"] == 0, runs
    assert runs["current"]["returncode"] != 0, runs
    records.append({"case": name, "environment": environment, "expected_success": False, "runs": runs})

report = {
    "base_revision": base_revision,
    "workflow_sha256": {label: hashlib.sha256(body).hexdigest() for label, body in snapshots.items()},
    "cases": records,
    "limitation": "Local shell reproduction; only the base gate's two GitHub expressions are substituted. No hosted scheduling or GPU execution.",
}
(output / "results.json").write_text(json.dumps(report, indent=2) + "\n")
print(json.dumps({"base_revision": base_revision, "cases": len(records), "base_false_green": len(records), "current_rejects": len(records)}))

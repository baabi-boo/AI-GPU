import itertools
import os
from pathlib import Path
import subprocess

script = Path(__file__).with_name("gate.sh")
fields = ("PLAN_RESULT", "PLAN_RUN", "SETUP_RESULT", "BUILD_RESULT", "TESTS_RESULT")
statuses = ("success", "failure", "cancelled", "skipped")
runs = ("true", "false", "", "TRUE", "0", "false ")
accepted = {
    ("success", "true", "success", "success", "success"),
    ("success", "false", "skipped", "skipped", "skipped"),
}
checked = old_passes = new_passes = 0
for result_tuple in itertools.product(statuses, repeat=4):
    for run in runs:
        row = (result_tuple[0], run, *result_tuple[1:])
        env = {**os.environ, **dict(zip(fields, row))}
        actual = subprocess.run(["bash", str(script)], env=env, capture_output=True)
        expected = row in accepted
        assert (actual.returncode == 0) == expected, (row, actual.returncode, actual.stdout)
        checked += 1
        old_passes += "failure" not in result_tuple
        new_passes += actual.returncode == 0
for field in fields:
    env = {**os.environ, **dict(zip(fields, ("success", "true", "success", "success", "success")))}
    del env[field]
    assert subprocess.run(["bash", str(script)], env=env, capture_output=True).returncode != 0
print(f"PASS: {checked} truth-table rows; new passes={new_passes}; original passes={old_passes}; 5 unset-field negatives.")
for row in (("success", "true", "cancelled", "skipped", "skipped"),
            ("cancelled", "", "skipped", "skipped", "skipped"),
            ("success", "true", "success", "success", "skipped")):
    assert "failure" not in (row[0], *row[2:])
    assert row not in accepted
    print("False-green reproduction (original accepts, proposed rejects):", ":".join(row))

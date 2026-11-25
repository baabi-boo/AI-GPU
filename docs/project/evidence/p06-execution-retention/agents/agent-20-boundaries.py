"""Read-only capacity audit; injected commands produce no native execution."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import p06_qualified_warm_capacity as capacity
import p06_qualified_warm_hosted as hosted
import p06_qualified_warm_inputs as inputs
import p06_qualified_warm_run as runner
from test_p06_qualified_warm_capacity import Fixture
from test_p06_qualified_warm_hosted import HostedCompositionTests
from test_p06_qualified_warm_inputs import QualifiedWarmInputAcquisitionTests
from test_p06_qualified_warm_run import QualifiedWarmRunTests

GIB = 1024**3
rows = []


def checked(name, **details):
    rows.append({"check": name, "passed": True, **details})


def gate(observation, free=15 * GIB):
    with mock.patch.object(hosted.capacity, "observe_capacity", return_value=observation), \
            mock.patch.object(hosted.shutil, "disk_usage", return_value=SimpleNamespace(free=free)):
        return hosted.capacity_gate(Path("/source"), Path("/attempt"))


observation = Fixture().observe()
for key in capacity.FALSE_CLAIMS:
    assert observation[key] is False
assert observation["effective_capacity_status"] == "unknown"
assert observation["ancestry_complete"] is None
assert gate(observation)["effective_capacity_established"] is False
checked("complete-visible-all-max-does-not-establish-effective-capacity")

fixture = Fixture()
del fixture.files[fixture.directories[1] + "/memory.current"]
incomplete = fixture.observe()
assert incomplete["observation_complete"] is False
assert incomplete["effective_capacity_status"] == "unknown"
assert gate(incomplete)["gate_satisfied"] is False
checked("missing-ancestor-sample-blocks-hosted-capacity-screen")

for disk_delta in (-1, 0, 1):
    for memory_delta in (-1, 0, 1):
        observed = dict(observation, host_available_bytes=4 * GIB + memory_delta)
        outcome = gate(observed, 15 * GIB + disk_delta)
        assert outcome["gate_satisfied"] is (disk_delta >= 0 and memory_delta >= 0)
        assert outcome["effective_capacity_established"] is False
        checked("hosted-exact-byte-thresholds", disk_delta=disk_delta, memory_delta=memory_delta)

for key, value in (("known_memory_shortfall", None), ("known_memory_shortfall", 0),
                   ("observation_complete", None), ("observation_complete", 1),
                   ("effective_capacity_status", "unlimited"),
                   ("effective_capacity_status", "sufficient"),
                   ("host_available_bytes", None), ("host_available_bytes", True)):
    assert gate(dict(observation, **{key: value}))["gate_satisfied"] is False
    checked("hosted-rejects-unknown-or-nonauthoritative-field", field=key, value=value)

for index in (0, 1):
    free = [15 * GIB, 15 * GIB]
    free[index] -= 1
    with mock.patch.object(hosted.capacity, "observe_capacity", return_value=observation), \
            mock.patch.object(hosted.shutil, "disk_usage", side_effect=[SimpleNamespace(free=v) for v in free]):
        assert hosted.capacity_gate(Path("/source"), Path("/attempt"))["gate_satisfied"] is False
    checked("each-hosted-volume-must-meet-native-reserve", volume_index=index)

QualifiedWarmInputAcquisitionTests.setUpClass()
try:
    for when in ("before", "after"):
        case = QualifiedWarmInputAcquisitionTests()
        case.setUp()
        try:
            high = {"free_disk_bytes": {"source": 15 * GIB}, "available_memory_bytes": 4 * GIB}
            fault = OSError("injected resource inventory failure")
            effect = fault if when == "before" else [high, fault]
            with mock.patch.object(inputs, "_resources", side_effect=effect):
                report = case.acquire()
            assert report["outcome"] == ("blocked" if when == "before" else "fail")
            assert report["native_execution"] == "not_run"
            assert report["input_identity_sha256"] is None
            assert bool(report["commands"]) is (when == "after")
            assert report["failures"]
            checked("input-resource-error-retains-scope", when=when, outcome=report["outcome"],
                    commands=len(report["commands"]), retained_parts=len(report["parts"]))
        finally:
            case.doCleanups()
finally:
    QualifiedWarmInputAcquisitionTests.doClassCleanups()

for when in ("inventory", "native-prelaunch"):
    case = QualifiedWarmRunTests()
    case.setUp()
    try:
        if when == "inventory":
            with mock.patch.object(runner.shutil, "disk_usage", side_effect=OSError("injected inventory failure")):
                report = case.run_route()
            assert report["outcome"] == "blocked"
            assert not report["stages"]
        else:
            def bounded(argv, cwd, environment, log, **limits):
                assert limits["min_free_bytes"] == 15 * GIB
                assert limits["max_rss_bytes"] == 4 * GIB
                if log.stem == "qualified-warm":
                    return {"outcome": "blocked", "reason": "resource_inventory_unavailable",
                            "process_started": False, "cleanup_complete": True, "exit_code": None}
                return case.child(argv, cwd, environment, log, **limits)
            report = case.run_route(bounded)
            assert report["outcome"] == "fail"
            assert report["stages"][-1]["process_started"] is False
            assert report["stages"][-1]["cleanup_complete"] is True
        assert report["native_execution"] == "not_run"
        assert report["orchestration_passed"] is False
        assert report["completed_counts"] is None
        checked("runner-resource-error-retains-scope", when=when, outcome=report["outcome"])
    finally:
        case.doCleanups()

case = HostedCompositionTests()
case.setUp()
try:
    with mock.patch.object(hosted, "capacity_gate", side_effect=OSError("injected inventory failure")):
        report = case.execute()
    assert report["outcome"] == "fail"
    assert report["native_execution"] == "not_run"
    assert report["orchestration_passed"] is False
    assert report["packaging_passed"] is True and report["encryption_passed"] is True
    assert all(call["module"] not in ("p06_qualified_warm_inputs", "p06_qualified_warm_run") for call in case.calls)
    checked("hosted-capacity-error-remains-failed-after-synthetic-retention-closeout")
finally:
    case.doCleanups()

source = Path.cwd()
local = hosted.capacity_gate(source, source.parent)
observed = local["observation"]
local_summary = {key: observed[key] for key in (
    "status", "observation_complete", "known_memory_shortfall", "host_available_bytes",
    "visible_headroom_bytes", "effective_capacity_status", "ancestry_complete",
    "native_launch_authorized", "native_execution", "errors")}
local_summary.update(local_gate_satisfied=local["gate_satisfied"],
                     effective_capacity_established=local["effective_capacity_established"],
                     free_disk_bytes=local["free_disk_bytes"])
assert local["gate_satisfied"] is False
assert observed["native_launch_authorized"] is False
checked("local-observation-cannot-admit-this-runner")

files = ["ci/project/" + name for name in (
    "p06_qualified_warm_capacity.py", "p06_qualified_warm_hosted.py",
    "p06_qualified_warm_inputs.py", "p06_qualified_warm_run.py",
    "p06_qualified_warm_encrypt.py", "p06_dependency_contract.py",
    "baseline_process.py", "preflight.py", "test_p06_qualified_warm_capacity.py",
    "test_p06_qualified_warm_hosted.py", "test_p06_qualified_warm_inputs.py",
    "test_p06_qualified_warm_run.py", "test_p06_qualified_warm_encrypt.py")]
output = {"recorded_at": datetime.now(timezone.utc).isoformat(), "checks": rows,
          "passed_checks": len(rows), "local_observation": local_summary,
          "source_sha256": {name: hashlib.sha256((source / name).read_bytes()).hexdigest() for name in files},
          "native_execution": "not_run", "toolchain_execution": "not_run"}
target = source.parent / "validation/agent-20-boundaries.json"
target.write_text(json.dumps(output, indent=2, sort_keys=True) + "\n")
print(json.dumps({"passed_checks": len(rows), "local_observation": local_summary}, sort_keys=True))

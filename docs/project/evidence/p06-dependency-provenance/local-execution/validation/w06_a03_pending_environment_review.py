"""Independent scratch reproduction of the local pending PATH mismatch."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path, PurePosixPath
import time
import unittest

import p06_dependency_control_replay as control
import test_p06_pending_probe as output_tests
from test_p06_dependency_control_replay import SyntheticControls, SyntheticNativeWithControlTools

START = time.monotonic()
SOURCE = Path(control.ROOT)
HOST = "/workspace/p06-local-host-02/bin"
RESULT = {"scope": "synthetic fixture plus static producer/reader review; no native execution",
          "source": str(SOURCE), "expected_revision": "ac2f2ae761c3644103278f7a41cc6ae7db734a86",
          "source_sha256": {name: hashlib.sha256((SOURCE / name).read_bytes()).hexdigest() for name in (
              "ci/project/p06_pending_probe.py", "ci/project/p06_dependency_control_replay.py",
              "ci/project/p06_dependency_local_execute.py", "tests/unittest/pending_reads/main.cpp")}}

original = SyntheticNativeWithControlTools()
native = original.reader()
native_result = native.run()
packet = SyntheticControls(original, native)
baseline = packet.probe_check()
assert baseline["outcome"] == "pass" and baseline["managed_population_included"] is False
old_path = packet.probe_report["environment"]["PATH"]
native.paths["host_bin"] = PurePosixPath(HOST)
producer_path = ":".join(dict.fromkeys([HOST, str(PurePosixPath(native.tools["executing_python"]["path"]).parent), "/usr/bin", "/bin"]))
packet.probe_report["environment"]["PATH"] = producer_path
try:
    packet.probe_check()
except ValueError as error:
    rejection = str(error)
    assert rejection == "pending environment.PATH: value differs", rejection
else:
    raise AssertionError("the frozen pending environment mismatch was not reproduced")
RESULT.update(baseline_synthetic_probe_passed=True, declared_host_bin=HOST,
              producer_path=producer_path, frozen_reader_path=old_path,
              rejection=rejection, finding_severity="F2", confidence="high",
              evidence_type="static-proof plus targeted executable reproduction",
              fixture_limitation="The dependency semantic boundary is mocked; after the valid synthetic native check, host_bin and the probe PATH are changed to reproduce this isolated join. This is not a forged or actual native original.",
              native_execution="not_run", retained_code_executed=False)
suite = unittest.defaultTestLoader.loadTestsFromTestCase(output_tests.PendingOutputTests)
run = unittest.TextTestRunner(verbosity=2).run(suite)
assert run.wasSuccessful()
RESULT.update(output_tests=run.testsRun, output_tests_passed=True,
              duration_seconds=time.monotonic()-START)
Path("/workspace/scratch/279b6658611e/validation/w06_a03-pending-review.json").write_text(json.dumps(RESULT, indent=2)+"\n")
print(json.dumps(RESULT, indent=2))

"""Bounded host-only test-quality witness; no optional original artifacts."""
import copy
import hashlib
import json
from pathlib import Path
import traceback
import unittest
from unittest.mock import patch

import p05_replay_installation as installation
from p06_replay import _archive_api
import test_p05_replay_installation_identity as identity_tests
import test_p05_replay_nested_archives as nested_tests
from test_p05_replay_installation import SyntheticInstallation, source_archive

ROOT = Path(__file__).resolve().parent.parent / "AI-GPU"
PATHS = ["ci/project/" + name for name in (
    "test_p05_replay_installation_identity.py", "test_p05_replay_nested_archives.py",
    "test_p05_replay_installation.py", "p05_replay_installation.py", "p05_torch_replay.py")]
PATHS.append("docs/project/evidence/p05-torch/reviews/archive_reader.py")

def hashes():
    return {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in PATHS}

def flatten(suite):
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from flatten(item)
        else:
            yield item.id()

before = hashes()
ids = sorted(test_id for module in (identity_tests, nested_tests)
             for test_id in flatten(unittest.defaultTestLoader.loadTestsFromModule(module)))
assert len(ids) == len(set(ids)) == 13
checks = []
fixture = SyntheticInstallation()
summary = fixture.run()["summary"]
assert summary["scope"] == "retained-installation-consistency"
assert summary["native_execution"] == "not_run"
assert len(summary["limitations"]) == 7
assert all(summary[key] is False for key in (
    "third_party_bytes_rehashed", "interpreter_bytes_rehashed", "retained_code_executed",
    "acceptance_claimed", "phase_acceptance"))
checks.append({"case": "valid_synthetic_installation", "outcome": "pass"})

original_interpreter = copy.deepcopy(fixture.tr["provisioning_interpreter"])
row = {key: original_interpreter[key] for key in ("path", "sha256", "size_bytes")}
row["sha256"] = "0" * 64
identity_tests.package_files(fixture, {"setuptools": [row]})
assert fixture.tr["provisioning_interpreter"] == original_interpreter
assert fixture.snapshot_value("python", fixture.pr, "tools_before")["python3"] == original_interpreter
try:
    fixture.run()
except installation.InstallationError as error:
    assert "recorded file identity" in str(error)
    frames = traceback.extract_tb(error.__traceback__)
    assert "_join_identity" in [frame.name for frame in frames]
    checks.append({"case": "independent_identity_collision", "outcome": "expected_rejection", "reason": str(error)})
else:
    raise AssertionError("identity collision was accepted")

fixture = SyntheticInstallation()
trusted_installed = fixture.files["torch/snapshots/installed-before.json"]
identity_tests.transfer_files(fixture, "vortex_ai", "torch", {installation.SITE + "vortex_ai/torch_ops.py"})
assert fixture.files["torch/snapshots/installed-before.json"] == trusted_installed
try:
    fixture.run()
except installation.InstallationError as error:
    assert "first-party distribution membership" in str(error)
    frames = traceback.extract_tb(error.__traceback__)
    assert "_environments" in [frame.name for frame in frames]
    checks.append({"case": "independent_ownership_exchange", "outcome": "expected_rejection", "reason": str(error)})
else:
    raise AssertionError("ownership exchange was accepted")

api = _archive_api()
for later, boundary in ((False, "tarfile.open"), (True, "next(entries)")):
    try:
        installation._sdist_members(nested_tests.truncated_sparse_archive(later=later), api)
    except installation.InstallationError as error:
        assert str(error) == "malformed source archive header"
        assert isinstance(error.__cause__, IndexError)
        frames = traceback.extract_tb(error.__cause__.__traceback__)
        entry = next(frame for frame in frames if frame.name == "_sdist_members")
        assert boundary in entry.line
        checks.append({"case": "sparse_later_" + str(later).lower(), "outcome": "expected_rejection",
                       "boundary": boundary, "cause": type(error.__cause__).__name__, "line": entry.lineno})
    else:
        raise AssertionError("truncated sparse archive was accepted")

with patch.object(api, "relative_name", side_effect=IndexError("validation bug")):
    try:
        installation._sdist_members(source_archive({"setup.py": b"inert"}), api)
    except IndexError as error:
        assert str(error) == "validation bug"
        checks.append({"case": "unrelated_validation_index_error", "outcome": "propagated_unmodified"})
    else:
        raise AssertionError("implementation IndexError was hidden")

after = hashes()
assert after == before
result = {"scope": "bounded_synthetic_test_quality_witness", "discovered_test_ids": ids,
          "test_id_sha256": hashlib.sha256(("\n".join(ids) + "\n").encode()).hexdigest(),
          "discovered_count": len(ids), "unittest_cases_executed": 0, "witness_checks": checks,
          "source_sha256_before": before, "source_sha256_after": after,
          "source_changes": [], "original_archives_opened": 0,
          "native_execution": "not_run", "retained_code_executed": False,
          "acceptance_claimed": False, "phase_acceptance": False}
out = Path(__file__).with_name("a40-evidence.json")
out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
print(json.dumps({"discovered": len(ids), "unique": len(set(ids)), "witness_checks": len(checks),
                  "outcome": "pass", "source_changes": [], "evidence": str(out)}, sort_keys=True))

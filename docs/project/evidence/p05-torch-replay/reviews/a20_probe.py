"""Bounded inert installation/native-binding join probe; no native execution."""

import copy
import hashlib
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1] / "AI-GPU"
sys.path.insert(0, str(ROOT / "ci/project"))

import p05_replay_installation as replay
from p06_replay import _archive_api
from test_p05_replay_installation import SyntheticInstallation, REVISION, encoded
from test_p05_replay_native import MemoryView


SOURCES = (
    "ci/project/p05_replay_installation.py",
    "ci/project/p05_replay_native.py",
    "ci/project/p05_torch_replay.py",
    "ci/project/test_p05_replay_installation.py",
    "ci/project/test_p05_replay_native.py",
    "docs/project/evidence/p05-torch/reviews/archive_reader.py",
)


def hashes():
    return {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in SOURCES}


def positive():
    fixture = SyntheticInstallation()
    fixture.put("python", "report.json", encoded(fixture.pr))
    fixture.tr["python_report"] = fixture.put("torch", "python/report.json", encoded(fixture.pr))
    fixture.put("torch", "report.json", encoded(fixture.tr))
    result = replay.verify_installations(MemoryView(fixture.files), fixture.tr, fixture.native,
                                        expected_revision=REVISION, expected_format="fp16")
    summary = result["summary"]
    assert summary["native_execution"] == "not_run"
    assert summary["retained_code_executed"] is False
    assert summary["acceptance_claimed"] is False
    assert summary["phase_acceptance"] is False
    return {"case": "complete_synthetic_installation", "outcome": "pass",
            "bound_wheel_members": summary["bound_wheel_members"],
            "retained_plain_installed_files": summary["retained_plain_installed_files"]}


def swapped(role, rewrite_local_binding):
    fixture = SyntheticInstallation()
    independent = copy.deepcopy(fixture.native)
    frozen_native = encoded(independent["model_binding"])
    manifest = copy.deepcopy(fixture.manifest)
    frozen_sources = encoded(manifest["binding_sources"])
    source_pin = manifest["binding_source_sha256"]
    relative, native_name = replay.ROLES[role]
    raw = b"Changed synthetic inert library bytes: " + role.encode()
    digest = hashlib.sha256(raw).hexdigest()
    next(row for row in manifest["artifacts"] if row["role"] == role).update(sha256=digest, size=len(raw))
    if rewrite_local_binding:
        binding = manifest["native_binding"]
        next(row for row in binding["artifacts"] + binding["dependencies"]
             if row["path"] == native_name).update(sha256=digest, size_bytes=len(raw))
        manifest["qualification_id"] = hashlib.sha256(encoded(binding)).hexdigest()
        fixture.pr["native_qualification_id"] = manifest["qualification_id"]
    manifest_raw = encoded(manifest) + b"\n"
    for packet, report in (("python", fixture.pr), ("torch", fixture.tr)):
        fixture.put(packet, "artifacts/bundle/" + relative, raw)
        report["bundle_manifest"] = fixture.put(packet, "artifacts/bundle/manifest.json", manifest_raw)
        report["bundle_artifacts"] = fixture.tree(packet, "artifacts/bundle")
        view = MemoryView(fixture.files).subview(packet)
        assert view.verified(report["bundle_manifest"]) == manifest_raw
        assert view.subview("artifacts/bundle").inventory() == report["bundle_artifacts"]
    assert manifest["binding_source_sha256"] == source_pin
    assert encoded(manifest["binding_sources"]) == frozen_sources
    assert encoded(independent["model_binding"]) == frozen_native
    expected = ("bundle/native model binding differs" if rewrite_local_binding
                else "bundle/native artifact " + role + " differs")
    view = MemoryView(fixture.files)
    try:
        replay._manifest(view.subview("python"), view.subview("torch"), fixture.pr, fixture.tr,
                         independent, _archive_api(), REVISION, "fp16")
    except replay.InstallationError as error:
        assert str(error) == expected, (expected, str(error))
        return {"case": role + ("_local_binding_rewritten" if rewrite_local_binding else "_local_artifact_rewritten"),
                "outcome": "rejected", "reason": str(error), "source_pins_unchanged": True,
                "local_bundle_descriptors_match_bytes": True, "independent_native_unchanged": True}
    raise AssertionError("changed bundle escaped independent native binding")


if __name__ == "__main__":
    before = hashes()
    results = [positive()]
    results.extend(swapped(role, rewritten) for role in ("runtime", "ramulator") for rewritten in (False, True))
    assert hashes() == before, "reviewed source changed during probe"
    print(json.dumps({"scope": "synthetic host-only; no accelerator execution",
                      "results": results, "source_sha256": before}, indent=2, sort_keys=True))

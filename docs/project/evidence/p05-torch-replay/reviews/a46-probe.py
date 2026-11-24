#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Bounded synthetic identity-join audit; never accelerator execution evidence."""

from __future__ import annotations

import copy
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[1] / "AI-GPU"
sys.path.insert(0, str(ROOT / "ci/project"))

import p05_execution_records as base_records
import p05_replay_installation as installation
import p05_replay_native as native_replay
import p05_torch_records as torch_records
import p05_torch_replay as driver
import test_p05_replay_installation as installation_fixture
from p05_torch_qualification_test_fixture import raw_log, synthetic
from test_p05_replay_native import (MemoryView, encoded, matmul_output,
                                    model_output, synthetic_results)
from test_p05_retained_observation_records import denied_live_access, retained_identity

C0 = "c0b44ce64665fe11895f869eea8c38c9b820d6f7"
C6 = "c6fb039e706e812b6b3f4d2a5db1828076fe50df"
REVISIONS = (C0, C6)
FORMATS = ("fp16", "bf16")
API = driver._archive_api()
ROWS = []
ARCHIVES = []


def digest(value):
    return hashlib.sha256(encoded(value)).hexdigest()


def check(name, function, *, rejects=None, details=None):
    row = {"id": name, "scope": "synthetic-host-only-helper-probe",
           "expected": "reject" if rejects else "pass", **(details or {})}
    try:
        result = function()
    except ValueError as error:
        if rejects is None or rejects not in str(error):
            raise AssertionError((name, "unexpected rejection", str(error))) from error
        row.update(actual="reject", reason=str(error))
    else:
        if rejects is not None:
            raise AssertionError((name, "substitution accepted"))
        row["actual"] = "pass"
        if result is not None:
            row["result"] = result
    ROWS.append(row)


def qualification(revision, fmt, kind):
    # These are explicit synthetic labels, never real original qualification IDs.
    return digest({"scope": "synthetic-only", "revision": revision, "format": fmt, "kind": kind})


def native_sample(fmt, revision):
    sample = copy.deepcopy(synthetic_results(fmt))
    files, native, python, _, _ = sample
    mid, qid = qualification(revision, fmt, "model"), qualification(revision, fmt, "matmul")
    for case in native["variants"][0]["cases"]:
        for row in case["observations"]:
            row.update(source_revision=revision, qualification_id=mid)
            for stage in row["trace"]["native"]:
                stage["dispatch"]["qualification_id"] = mid
        files["native/logs/simx-" + fmt + "-" + case["id"] + ".log"] = model_output(case["observations"]).encode()
    for case in python["native_matmuls"]:
        for row in case["observations"]:
            row["qualification_id"] = qid
        files["python/logs/native-" + case["id"] + ".log"] = matmul_output(case["observations"]).encode()
    return sample


def native_numbers(sample):
    return digest({"matmuls": [row["actual_bits"] for case in sample[2]["native_matmuls"]
                                for row in case["observations"]],
                   "models": [{key: row["trace"][key] for key in ("hidden_words", "bridge_words", "output_words")}
                              for case in sample[1]["variants"][0]["cases"] for row in case["observations"]]})


def check_native(sample, fmt, revision, *, model_id=None, matmul_id=None):
    files, native, python, matmuls, models = sample
    view = MemoryView(files)
    with denied_live_access():
        return native_replay._results(view.subview("native"), view.subview("python"), native, python,
            matmuls, models, model_id or qualification(revision, fmt, "model"),
            matmul_id or qualification(revision, fmt, "matmul"), revision, fmt)[2]


def make_installation(revision):
    # Patch the trusted test fixture's construction constant, never a validator.
    with patch.object(installation_fixture, "REVISION", revision):
        return installation_fixture.SyntheticInstallation()


def check_installation(fixture, revision, fmt="fp16"):
    fixture.put("python", "report.json", encoded(fixture.pr))
    fixture.tr["python_report"] = fixture.put("torch", "python/report.json", encoded(fixture.pr))
    fixture.put("torch", "report.json", encoded(fixture.tr))
    with tempfile.TemporaryDirectory(prefix="a46-inert-installation-") as temporary:
        path = Path(temporary) / "synthetic.zip"
        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for name, raw in sorted(fixture.files.items()):
                archive.writestr(name, raw)
        sha256 = hashlib.sha256(path.read_bytes()).hexdigest()
        ARCHIVES.append({"sha256": sha256, "size_bytes": path.stat().st_size,
                         "expected_revision": revision, "expected_format": fmt})
        with API.ArchiveReader(path, sha256) as archive:
            result = installation.verify_installations(archive.view(), fixture.tr, fixture.native,
                        expected_revision=revision, expected_format=fmt)
        assert hashlib.sha256(path.read_bytes()).hexdigest() == sha256
        return result["summary"]


def replace_requests(fixture, key, value, *, python_too):
    # Rewrite request + observations + report descriptors together. The
    # installation fixture contains no numerical execution and makes no such claim.
    if python_too:
        request = fixture.snapshot_value("python", fixture.pr, "installed_request")
        request["binding"][key] = value
        fixture.snapshot("python", fixture.pr, "installed_request", request)
        fixture.native["python_request"] = copy.deepcopy(request)
        observations = copy.deepcopy(fixture.native["python_observations"])
        observations["binding"][key] = value
        fixture.pr["observations"] = fixture.put("python", "artifacts/installed-observations.json", encoded(observations))
        fixture.native["python_observations"] = copy.deepcopy(observations)
    request = fixture.snapshot_value("torch", fixture.tr, "installed_request")
    request["base_request"]["binding"][key] = value
    fixture.snapshot("torch", fixture.tr, "installed_request", request)
    observations = json.loads(fixture.files["torch/artifacts/installed-observations.json"])
    observations["base_observations"]["binding"][key] = value
    fixture.tr["observations"] = fixture.put("torch", "artifacts/installed-observations.json", encoded(observations))
    assert request["base_request"]["binding"] == observations["base_observations"]["binding"]
    if python_too:
        assert fixture.native["python_request"]["binding"] == fixture.native["python_observations"]["binding"]


def reseal_manifest(fixture):
    fixture.manifest["qualification_id"] = digest(fixture.manifest["native_binding"])
    fixture.pr["native_qualification_id"] = fixture.manifest["qualification_id"]
    raw = encoded(fixture.manifest) + b"\n"
    for packet, report in (("python", fixture.pr), ("torch", fixture.tr)):
        report["bundle_manifest"] = fixture.put(packet, "artifacts/bundle/manifest.json", raw)
        report["bundle_artifacts"] = fixture.tree(packet, "artifacts/bundle")


def manifest_fixture(revision, fmt):
    fixture = make_installation(revision)
    fixture.manifest["format"] = fmt
    fixture.manifest["native_binding"]["format"] = fmt
    fixture.native["model_binding"] = copy.deepcopy(fixture.manifest["native_binding"])
    reseal_manifest(fixture)
    return fixture


def check_manifest(fixture, revision, fmt):
    view = MemoryView(fixture.files)
    with denied_live_access():
        manifest, raw = installation._manifest(view.subview("python"), view.subview("torch"),
            fixture.pr, fixture.tr, fixture.native, API, revision, fmt)
    return {"qualification_id": manifest["qualification_id"], "bundle_sha256": hashlib.sha256(raw).hexdigest()}


def main():
    sources_before = driver._reader_sources()
    fixture_paths = ("test_p05_replay_installation.py", "test_p05_replay_native.py",
                     "test_p05_retained_observation_records.py", "p05_torch_qualification_test_fixture.py",
                     "p05_qualification_test_fixture.py", "test_p03_execution_records.py", "test_p04_execution_records.py")
    fixture_hashes = {name: hashlib.sha256((ROOT / "ci/project" / name).read_bytes()).hexdigest()
                      for name in fixture_paths}
    numerics = {}
    for fmt in FORMATS:
        samples = {revision: native_sample(fmt, revision) for revision in REVISIONS}
        assert native_numbers(samples[C0]) == native_numbers(samples[C6])
        numerics[fmt] = {"native_results_equal_across_revision_labels": True,
                         "native_output_words_sha256": native_numbers(samples[C0])}
        for revision in REVISIONS:
            check("native-valid-" + fmt + "-" + revision[:8],
                  lambda s=samples[revision], r=revision: check_native(s, fmt, r))
        check("native-wrong-source-pin-" + fmt,
              lambda: check_native(samples[C6], fmt, C0,
                  model_id=qualification(C6, fmt, "model"), matmul_id=qualification(C6, fmt, "matmul")),
              rejects="source_revision", details={"record_revision": C6, "expected_revision": C0,
                                                  "numeric_bytes_unchanged": True})
        check("native-wrong-model-qualification-" + fmt,
              lambda: check_native(samples[C6], fmt, C6, model_id=qualification(C0, fmt, "model")),
              rejects="qualification", details={"numeric_bytes_unchanged": True})
        check("native-wrong-matmul-qualification-" + fmt,
              lambda: check_native(samples[C6], fmt, C6, matmul_id=qualification(C0, fmt, "matmul")),
              rejects="result identity differs", details={"numeric_bytes_unchanged": True})

        with tempfile.TemporaryDirectory(prefix="a46-mock-observations-") as temporary:
            original_value, original_request, native = synthetic(Path(temporary), fmt)
            identity = retained_identity(original_value, original_request)
            adapter = Path(original_value["framework"]["adapter_file"]).read_bytes()
            summaries, identities, values, requests = {}, {}, {}, {}
            for revision in REVISIONS:
                value, request = copy.deepcopy(original_value), copy.deepcopy(original_request)
                request["base_request"]["binding"]["source_revision"] = revision
                value["base_observations"]["binding"]["source_revision"] = revision
                for row in value["base_observations"]["models"]:
                    row["record"]["source_revision"] = revision
                joined = replace(identity, request_sha256=digest(request["base_request"]))
                def verify(value=value, request=request, joined=joined):
                    with denied_live_access():
                        return torch_records.verify_retained_observations(value, request,
                            retained_identity=joined, adapter_bytes=adapter, **native, raw_log=raw_log(value))
                summaries[revision] = verify()
                identities[revision], values[revision], requests[revision] = joined, value, request
                check("locally-coherent-observation-" + fmt + "-" + revision[:8], verify,
                      details={"not_a_public_archive_verdict": True})
            assert summaries[C0] == summaries[C6]
            assert [row["result"] for row in values[C0]["framework_matmuls"] + values[C0]["framework_models"]] == [
                   row["result"] for row in values[C6]["framework_matmuls"] + values[C6]["framework_models"]]
            numerics[fmt]["framework_summaries_equal_across_revision_labels"] = True
            numerics[fmt]["framework_numeric_results_equal_across_revision_labels"] = True
            def wrong_identity():
                with denied_live_access():
                    return torch_records.verify_retained_observations(values[C6], requests[C6],
                        retained_identity=identities[C0], adapter_bytes=adapter, **native, raw_log=raw_log(values[C6]))
            check("observations-c6-with-c0-request-identity-" + fmt, wrong_identity,
                  rejects="retained installed request identity differs")

    for revision in REVISIONS:
        other = C6 if revision == C0 else C0
        fixture = make_installation(revision)
        check("complete-installation-valid-fp16-" + revision[:8], lambda: check_installation(fixture, revision))
        donor_qualification = make_installation(other).manifest["qualification_id"]
        for python_too in (False, True):
            for key, value in (("source_revision", other), ("format", "bf16"),
                               ("qualification_id", donor_qualification)):
                fixture = make_installation(revision)
                replace_requests(fixture, key, value, python_too=python_too)
                check("coherent-" + ("python-and-torch-" if python_too else "torch-only-") + key + "-" + revision[:8],
                      lambda: check_installation(fixture, revision),
                      rejects="Python request binding differs" if python_too else "framework installed request differs",
                      details={"expected_revision": revision, "expected_format": "fp16",
                               "replacement": value, "request_observation_descriptors_recomputed": True})

    for revision in REVISIONS:
        for fmt in FORMATS:
            fixture = manifest_fixture(revision, fmt)
            check("manifest-valid-" + fmt + "-" + revision[:8], lambda: check_manifest(fixture, revision, fmt))
            for axis in ("format", "source"):
                fixture = manifest_fixture(revision, fmt)
                donor_revision = (C6 if revision == C0 else C0) if axis == "source" else revision
                donor_fmt = ("bf16" if fmt == "fp16" else "fp16") if axis == "format" else fmt
                fixture.native["model_binding"] = copy.deepcopy(manifest_fixture(donor_revision, donor_fmt).native["model_binding"])
                check("coherent-python-torch-bundle-vs-foreign-native-" + axis + "-" + fmt + "-" + revision[:8],
                      lambda: check_manifest(fixture, revision, fmt), rejects="bundle/native model binding differs",
                      details={"expected_revision": revision, "expected_format": fmt,
                               "native_binding_revision": donor_revision, "native_binding_format": donor_fmt,
                               "both_bundle_copies_and_report_qualification_coherent": True})

    fixture = manifest_fixture(C0, "fp16")
    check("manifest-explicit-wrong-source-pin", lambda: check_manifest(fixture, C6, "fp16"),
          rejects="bundle contract differs", details={"expected_revision": C6, "bundle_revision": C0})
    fixture = manifest_fixture(C0, "fp16")
    fixture.manifest["native_binding"] = copy.deepcopy(fixture.manifest["native_binding"])
    fixture.manifest["native_binding"]["source"]["revision"] = C6
    fixture.native["model_binding"] = copy.deepcopy(fixture.manifest["native_binding"])
    reseal_manifest(fixture)
    # Keep the independent Python source snapshot at c0; the forged native
    # binding, qualification hash and both manifests agree with one another.
    fixture.native["python_source"]["checkout"]["revision"] = C0
    check("coherent-native-binding-and-bundles-vs-independent-python-source",
          lambda: check_manifest(fixture, C0, "fp16"), rejects="bundle native/Python source differs",
          details={"expected_revision": C0, "native_binding_revision": C6,
                   "qualification_hash_recomputed": True, "both_bundle_descriptors_recomputed": True})

    sources_after = driver._reader_sources()
    assert sources_after == sources_before
    assert fixture_hashes == {name: hashlib.sha256((ROOT / "ci/project" / name).read_bytes()).hexdigest()
                             for name in fixture_paths}
    receipt = {"schema_version": 1, "scope": "a46-bounded-synthetic-cross-layer-identity-joins",
        "outcome": "pass", "native_execution": "not_run", "retained_code_executed": False,
        "acceptance_claimed": False, "phase_acceptance": False,
        "complete_public_archive_replay_performed": False, "originals_opened": [],
        "reader_revision": "d8abc24d2fd5dab5ceddbae3627e3d3eb9750358 plus recorded installation repair",
        "source_before": sources_before, "source_after": sources_after, "fixture_sha256": fixture_hashes,
        "probe_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "positive_controls": sum(row["expected"] == "pass" for row in ROWS),
        "rejection_controls": sum(row["expected"] == "reject" for row in ROWS),
        "cases": ROWS, "numeric_equivalence": numerics, "synthetic_archive_inputs": ARCHIVES,
        "aggregation_boundary": {"builtin_multiarchive_aggregator": False,
            "combined_counts_are_manual_review_claim": True, "required_separate_formats": ["fp16", "bf16"],
            "required_same_independently_selected_execution_revision": True,
            "combined_framework_calls_if_both_originals_validated": 32,
            "combined_distinct_launches_if_both_originals_validated": 216},
        "limitations": ["Synthetic source labels are not original execution or source authenticity evidence.",
            "Numeric parsers, installation verifier and manifest join are exercised separately; no complete synthetic public replay is claimed.",
            "Locally coherent observation helpers trust independently supplied RetainedIdentity and native result inputs; their success alone is not an archive verdict.",
            "No native build, retained import/execution/extraction, actual producer-path access, original archive rerun, full suite, acceptance or guard change occurred."]}
    path = Path(__file__).with_name("a46-evidence.json")
    path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"outcome": receipt["outcome"], "positive_controls": receipt["positive_controls"],
                      "rejection_controls": receipt["rejection_controls"], "source_hashes_stable": len(sources_before),
                      "evidence": str(path)}, sort_keys=True))


if __name__ == "__main__":
    main()

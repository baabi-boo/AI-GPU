#!/usr/bin/env python3
"""Agent 23 host-only accounting audit; retained payloads are never executed."""
import copy
import hashlib
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1] / "AI-GPU"
sys.path.insert(0, str(ROOT / "ci/project"))
import p05_execution_records as base
import p05_replay_native as native
import p05_torch_records as torch
import p05_torch_replay as driver
import test_p05_replay_native as nf
import test_p05_torch_replay_driver as df
from p05_qualification_test_fixture import raw_log as base_log
from p05_torch_qualification_test_fixture import synthetic, raw_log
from test_p05_retained_observation_records import denied_live_access, retained_identity

EVIDENCE = []
REVIEWED = (
    "ci/project/p05_replay_native.py", "ci/project/p05_execution_records.py",
    "ci/project/p05_torch_records.py", "ci/project/p05_torch_replay.py",
    "ci/project/p04_execution_records.py", "ci/project/p03_execution_records.py",
    "ci/project/test_p05_replay_native.py", "ci/project/test_p05_torch_replay_driver.py",
    "ci/project/test_p05_retained_observation_records.py",
    "ci/project/p05_qualification_test_fixture.py", "ci/project/p05_torch_qualification_test_fixture.py",
    "docs/project/evidence/p05-torch/reviews/archive_reader.py",
)


def hashes():
    return {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in REVIEWED}


def parse_native(sample, fmt):
    files, report, python, matmuls, models = sample
    view = nf.MemoryView(files)
    return native._results(view.subview("native"), view.subview("python"), report,
                           python, matmuls, models, nf.MODEL_ID, nf.MATMUL_ID, nf.REVISION, fmt)


class AccountingAudit(unittest.TestCase):
    def test_both_formats_derive_counts_from_real_record_validators(self):
        for fmt in ("fp16", "bf16"):
            with self.subTest(format=fmt), tempfile.TemporaryDirectory() as root:
                sample = nf.synthetic_results(fmt)
                producer = Path(root) / "producer"
                value, request, comparisons = synthetic(producer, fmt)
                identity = retained_identity(value, request)
                adapter = Path(value["framework"]["adapter_file"]).read_bytes()
                plain_raw, framework_raw = base_log(value["base_observations"]), raw_log(value)
                shutil.rmtree(producer)
                with denied_live_access():
                    _, _, native_counts = parse_native(sample, fmt)
                    python = base.verify_retained_observations(value["base_observations"],
                        request["base_request"], retained_identity=identity,
                        **comparisons, raw_log=plain_raw)
                    framework = torch.verify_retained_observations(value, request,
                        retained_identity=identity, adapter_bytes=adapter,
                        **comparisons, raw_log=framework_raw)
                counts = [native_counts["total_launches"], python["counts"]["total_launches"],
                          framework["counts"]["total_launches"]]
                self.assertEqual(counts, [36, 36, 36])
                self.assertEqual(framework["operator_calls"], 16)
                self.assertEqual(framework["event_profile_pairs"], 180)
                EVIDENCE.append({"control": fmt, "derived_routes": counts,
                                 "framework_calls": 16, "framework_profile_pairs": 180,
                                 "producer_removed_and_live_access_denied": True})

    def test_duplicate_records_and_consistent_doubled_summaries_reject(self):
        for fmt in ("fp16", "bf16"):
            sample = nf.synthetic_results(fmt)
            files, report, python, _, _ = sample
            # All repeated raw rows, saved observations, and numerical summaries agree.
            for saved in report["variants"][0]["cases"]:
                saved["observations"] += copy.deepcopy(saved["observations"])
                files["native/logs/simx-" + fmt + "-" + saved["id"] + ".log"] = (
                    nf.model_output(saved["observations"]).encode())
            for saved in python["native_matmuls"]:
                saved["observations"] += copy.deepcopy(saved["observations"])
                files["python/logs/native-" + saved["id"] + ".log"] = (
                    nf.matmul_output(saved["observations"]).encode())
            for key in ("completed_model_runs", "completed_launches", "tensor_h2d_bytes", "tensor_d2h_bytes"):
                report[key] *= 2
            report["comparison_counts"] = {key: 2 * n for key, n in report["comparison_counts"].items()}
            python["native_counts"] = {key: 2 * n for key, n in python["native_counts"].items()}
            python["completed_native_and_python_launches"] *= 2
            with self.subTest(format=fmt), self.assertRaises(ValueError) as caught:
                parse_native(sample, fmt)
            EVIDENCE.append({"attack": "coherent duplicated native records", "format": fmt,
                             "rejection": str(caught.exception)})

    def test_public_driver_coherent_count_forgery_and_valid_control(self):
        helper = df.OrchestrationTests()
        with tempfile.TemporaryDirectory() as root:
            path = helper.archive(root)
            with helper.driver(path) as run:
                result = run()
                self.assertEqual(result["counts"]["distinct_total_launches"], 108)
                self.assertEqual(result["counts"]["copied_packet_additional_launches"], 0)
            with helper.driver(path) as run:
                nr = driver.verify_native.return_value
                pr = driver.python_records.verify_retained_observations.return_value
                fr = driver.torch_records.verify_retained_observations.return_value
                report = driver._report.return_value[0]
                for population in (nr, pr, fr):
                    population["counts"]["total_launches"] = 72
                fr.update(operator_calls=32, event_profile_pairs=360)
                report["execution_counts"].update(distinct_total_launches=216,
                    native_comparison_launches=72, plain_python_launches=72,
                    framework_launches=72, framework_operator_calls=32,
                    framework_event_profile_pairs=360)
                self.assertEqual(report["comparison"], fr)
                self.assertEqual(nr["python_report"]["comparison"], pr)
                self.assertEqual(sum(p["counts"]["total_launches"] for p in (nr, pr, fr)), 216)
                with self.assertRaisesRegex(ValueError, "derived one-format execution population") as caught:
                    run()
                EVIDENCE.append({"attack": "all orchestration summaries coherently doubled",
                                 "rejection": str(caught.exception), "orchestration_stubs": True,
                                 "control_total": 108, "control_copied_additional": 0})

    def test_complete_extra_python_packet_copy_rejects(self):
        outer, report, nr = df.packet_fixture()
        native._copies(outer.subview("python"), outer.subview("torch/python"), "control copies")
        driver._packet_members(outer, report, nr, df.API)
        originals = {name: outer.subview("python").read(name) for name in outer.subview("python").files()}
        for name, body in originals.items():
            outer.add("python-copy/" + name, body)
        native._copies(outer.subview("python"), outer.subview("python-copy"), "extra complete copy")
        with self.assertRaisesRegex(ValueError, "complete outer archive member inventory") as caught:
            driver._packet_members(outer, report, nr, df.API)
        EVIDENCE.append({"attack": "additional complete byte-identical Python packet",
                         "copied_members": len(originals), "rejection": str(caught.exception)})


if __name__ == "__main__":
    before = hashes()
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(AccountingAudit))
    stable = hashes() == before
    print(json.dumps({"scope": "synthetic host-only; no original archive or accelerator execution",
                      "tests_run": result.testsRun, "source_stable": stable,
                      "reviewed_sha256": before, "evidence": EVIDENCE}, sort_keys=True, indent=2))
    sys.exit(0 if result.wasSuccessful() and stable else 1)

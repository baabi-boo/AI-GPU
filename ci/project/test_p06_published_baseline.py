# SPDX-License-Identifier: Apache-2.0
"""Reanalyze the retained original P06 matrix without native execution."""

import hashlib
import json
from pathlib import Path
import unittest
import zipfile

import p06_analyze as analyze


ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = ROOT / "docs/project/evidence/p06-baseline"
REVISION = "84b6ca0ca75fba248ba330642bbf8764db3d459c"
FORMATS = ("fp16", "bf16")
INVENTORY = {
    "workloads": 8, "warmup_processes": 8, "measured_processes": 40,
    "total_processes": 48, "warmup_launches": 12,
    "measured_launches": 60, "total_launches": 72,
}


class PublishedBaselineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.index = json.loads((EVIDENCE / "archive-index.json").read_text())
        cls.saved = json.loads((EVIDENCE / "reviews/analysis.json").read_text())
        cls.indexed_archives = {row["format"]: row for row in cls.index["archives"]}
        cls.archives = {fmt: EVIDENCE / "archives" / ("simx-" + fmt + ".zip")
                        for fmt in FORMATS}
        cls.result = analyze.analyze_archives(
            cls.archives["fp16"], cls.indexed_archives["fp16"]["sha256"],
            cls.archives["bf16"], cls.indexed_archives["bf16"]["sha256"],
            expected_revision=REVISION,
        )

    def test_original_archives_match_the_independent_index(self):
        self.assertEqual(self.index["schema_version"], 1)
        self.assertEqual(self.index["source_revision"], REVISION)
        self.assertCountEqual([row["format"] for row in self.index["archives"]], FORMATS)
        self.assertEqual(self.result["source_revision"], REVISION)
        self.assertEqual([row["format"] for row in self.result["inputs"]], list(FORMATS))
        for row in self.result["inputs"]:
            fmt = row["format"]
            indexed = self.indexed_archives[fmt]
            path = self.archives[fmt]
            with self.subTest(format=fmt):
                self.assertEqual(indexed["path"], path.relative_to(ROOT).as_posix())
                self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), indexed["sha256"])
                self.assertEqual(path.stat().st_size, indexed["size_bytes"])
                self.assertEqual(row["archive"], {
                    "path": str(path), "sha256": indexed["sha256"],
                    "size_bytes": indexed["size_bytes"],
                })

    def test_retained_source_and_hosted_workflow_agree_with_the_index(self):
        self.assertEqual(self.index["workflow_url"],
                         "https://github.com/" + self.index["repository"]
                         + "/actions/runs/" + str(self.index["workflow_run_id"]))
        for row in self.result["inputs"]:
            fmt = row["format"]
            with self.subTest(format=fmt), zipfile.ZipFile(self.archives[fmt]) as archive:
                source = json.loads(archive.read("baseline/snapshots/source-before.json"))
                workflow = archive.read("baseline/artifacts/source/.github/workflows/p06-baseline.yml")
                job = row["hosted_job_identity"]
                self.assertEqual(source["checkout"]["revision"], self.index["source_revision"])
                self.assertEqual(source["checkout"]["tree"], self.index["source_tree"])
                self.assertIs(source["checkout"]["dirty"], False)
                expected = {
                    "GITHUB_SHA": self.index["source_revision"],
                    "GITHUB_REPOSITORY": self.index["repository"],
                    "GITHUB_RUN_ID": str(self.index["workflow_run_id"]),
                    "GITHUB_RUN_ATTEMPT": str(self.index["run_attempt"]),
                    "GITHUB_EVENT_NAME": "push", "GITHUB_REF": "refs/heads/master",
                    "GITHUB_JOB": "baseline", "P06_BACKEND": "simx", "P06_FORMAT": fmt,
                    "workflow_sha256": hashlib.sha256(workflow).hexdigest(),
                }
                self.assertEqual({name: job[name] for name in expected}, expected)
                self.assertEqual(archive.read("workflow.yml"), workflow)
                self.assertEqual(json.loads(archive.read("job.json")), job)

    def test_complete_matrix_retains_each_warmup_and_measured_sample(self):
        summary = self.result["summary"]
        self.assertIs(summary["full_matrix"], True)
        self.assertEqual(summary["formats"], list(FORMATS))
        self.assertEqual(summary["inventory"], INVENTORY)
        self.assertEqual(len(summary["workloads"]), INVENTORY["workloads"])
        diagnostics = {row["workload_id"]: row for row in self.result["diagnostics"]}
        self.assertEqual(len(diagnostics), INVENTORY["workloads"])
        self.assertEqual(len(self.result["diagnostics"]), len(diagnostics))
        process_counts = {"warmup": 0, "measurement": 0}
        launch_counts = {"warmup": 0, "measurement": 0}
        sample_ids = []
        for workload in summary["workloads"]:
            with self.subTest(workload=workload["workload_id"]):
                diagnostic = diagnostics[workload["workload_id"]]
                self.assertEqual(diagnostic["format"], workload["format"])
                self.assertEqual(diagnostic["kind"], workload["kind"])
                self.assertEqual(len(diagnostic["samples"]), 6)
                for phase, field, repetitions in (
                        ("warmup", "warmup_sample_ids", [0]),
                        ("measurement", "measured_sample_ids", list(range(5)))):
                    samples = [row for row in diagnostic["samples"] if row["phase"] == phase]
                    self.assertEqual([row["repetition"] for row in samples], repetitions)
                    ids = [row["sample_id"] for row in samples]
                    self.assertEqual(ids, workload[field])
                    sample_ids.extend(ids)
                    process_counts[phase] += len(samples)
                    launch_counts[phase] += len(samples) * len(diagnostic["native_shapes"])
        self.assertEqual(process_counts, {"warmup": 8, "measurement": 40})
        self.assertEqual(launch_counts, {"warmup": 12, "measurement": 60})
        self.assertEqual(len(sample_ids), INVENTORY["total_processes"])
        self.assertEqual(len(set(sample_ids)), len(sample_ids))
        self.assertEqual(sum(launch_counts.values()), INVENTORY["total_launches"])

    def test_saved_summary_diagnostics_and_metric_definitions_are_unchanged(self):
        for section in ("summary", "diagnostics", "metric_definitions", "counter_null_policy"):
            with self.subTest(section=section):
                self.assertEqual(self.result[section], self.saved[section])

    def test_saved_data_identities_are_unchanged_after_relocation(self):
        self.assertEqual(self.result["compatibility"], self.saved["compatibility"])
        self.assertEqual(len(self.result["inputs"]), len(self.saved["inputs"]))
        for actual, saved in zip(self.result["inputs"], self.saved["inputs"]):
            with self.subTest(format=actual["format"]):
                # Only the local ZIP pathname changes with the review checkout.
                actual_identity = {**actual, "archive": {
                    name: value for name, value in actual["archive"].items() if name != "path"}}
                saved_identity = {**saved, "archive": {
                    name: value for name, value in saved["archive"].items() if name != "path"}}
                self.assertEqual(actual_identity, saved_identity)
                self.assertEqual(actual["commands_checked"], 45)
                self.assertEqual(actual["inventory"], {name: value // 2
                                                       for name, value in INVENTORY.items()})
        self.assertNotEqual(self.result["inputs"][0]["binding_id"],
                            self.result["inputs"][1]["binding_id"])

    def test_unavailable_counters_are_preserved_as_null(self):
        for workload in self.result["summary"]["workloads"]:
            with self.subTest(workload=workload["workload_id"]):
                counters = workload["counter_statistics"]
                self.assertEqual(len(counters), 45)
                self.assertEqual(sum(row["available"] for row in counters), 33)
                unavailable = [row for row in counters if not row["available"]]
                self.assertEqual(len(unavailable), 12)
                for counter in unavailable:
                    self.assertIsNone(counter["statistics"])
                diagnostic = next(row for row in self.result["diagnostics"]
                                  if row["workload_id"] == workload["workload_id"])
                for sample in diagnostic["samples"]:
                    for counter in unavailable:
                        self.assertIsNone(sample["counter_values"][counter["name"]])

    def test_analysis_makes_no_execution_acceptance_or_optimization_claim(self):
        self.assertEqual(self.result["schema_version"], 1)
        self.assertEqual(self.result["scope"], "p06-full-matrix-retained-data-analysis")
        self.assertEqual(self.result["outcome"], "pass")
        self.assertEqual(self.result["native_execution"], "not_run")
        for claim in ("acceptance_claimed", "phase_complete", "optimization_claimed"):
            self.assertIs(self.result[claim], False)
        self.assertIs(self.result["summary"]["acceptance_claimed"], False)
        for row in self.result["inputs"]:
            with self.subTest(format=row["format"]):
                self.assertEqual(row["hosted_job_identity"]["native_execution"], "not_run")
                self.assertIs(row["hosted_job_identity"]["acceptance_claimed"], False)


if __name__ == "__main__":
    unittest.main()

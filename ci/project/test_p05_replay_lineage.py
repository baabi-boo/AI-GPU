# SPDX-License-Identifier: Apache-2.0
"""Linked synthetic model substitutions; no archive or accelerator execution."""

import copy
from pathlib import Path
import tempfile
import unittest

import p05_replay_native as replay
import p05_torch_records as torch_records
from test_p05_replay_native import (MATMUL_ID, MODEL_ID, REVISION, MemoryView,
                                    encoded, model_output, synthetic_results)
from test_p05_retained_observation_records import denied_live_access, retained_identity
from p05_torch_qualification_test_fixture import packed, raw_log, synthetic


def verify_results(sample, fmt):
    files, native, python, matmuls, models = sample
    view = MemoryView(files)
    return replay._results(view.subview("native"), view.subview("python"), native, python,
                           matmuls, models, MODEL_ID, MATMUL_ID, REVISION, fmt)


def substitute_intermediates(trace, donor):
    """Keep case, inputs, weights, poisons and lifecycle; transplant actual data."""
    for key in ("hidden_words", "bridge_words", "bridge_bytes", "output_words"):
        trace[key] = copy.deepcopy(donor[key])
    for index, stage in enumerate(trace["native"]):
        stage["output_words"] = list(donor["native"][index]["output_words"])
        if index:
            stage["a_bytes"] = donor["native"][index]["a_bytes"]


class ReplayModelLineageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.samples = {fmt: synthetic_results(fmt) for fmt in ("fp16", "bf16")}

    def assert_linked(self, trace):
        self.assertEqual(trace["native"][0]["output_words"], trace["hidden_words"])
        self.assertEqual(trace["bridge_bytes"], packed(trace["bridge_words"]).hex())
        self.assertEqual(trace["native"][1]["a_bytes"], trace["bridge_bytes"][:256])
        self.assertEqual(trace["native"][2]["a_bytes"], trace["bridge_bytes"][256:])
        self.assertEqual(trace["output_words"],
                         trace["native"][1]["output_words"] + trace["native"][2]["output_words"])

    def test_cross_case_intermediates_cannot_replace_frozen_model_in_either_poison(self):
        for fmt in self.samples:
            for iterations in ((0,), (1,), (0, 1)):
                with self.subTest(format=fmt, iterations=iterations):
                    sample = copy.deepcopy(self.samples[fmt])
                    frozen = encoded(sample[3:])
                    target, donor = sample[1]["variants"][0]["cases"][:2]
                    # Both frozen cases use the same weights, so the donor's
                    # bridge conversion and complete second stage stay valid.
                    for key in ("w1_words", "w2_words"):
                        self.assertEqual(sample[4][0][key], sample[4][1][key])
                    for iteration in iterations:
                        trace = target["observations"][iteration]["trace"]
                        original_input = trace["native"][0]["a_bytes"]
                        substitute_intermediates(trace, donor["observations"][iteration]["trace"])
                        self.assert_linked(trace)
                        self.assertEqual(trace["native"][0]["a_bytes"], original_input)
                    sample[0]["native/logs/simx-" + fmt + "-" + target["id"] + ".log"] = \
                        model_output(target["observations"]).encode()
                    with denied_live_access(), self.assertRaisesRegex(
                            ValueError, "actual hidden_words differ from frozen reference"):
                        verify_results(sample, fmt)
                    self.assertEqual(encoded(sample[3:]), frozen)

    def test_consistent_native_python_and_framework_substitution_still_uses_frozen_reference(self):
        for fmt in self.samples:
            sample = copy.deepcopy(self.samples[fmt])
            native_matmuls, native_models, _ = verify_results(sample, fmt)
            native = {"native_matmuls": native_matmuls, "native_models": native_models,
                      "model_cases": sample[4]}
            frozen = encoded(native["model_cases"])
            with tempfile.TemporaryDirectory(prefix="p05-lineage-host-only-") as directory:
                value, request, _ = synthetic(Path(directory), fmt)
                request["base_request"]["binding"]["source_revision"] = REVISION
                value["base_observations"]["binding"]["source_revision"] = REVISION
                for row in value["base_observations"]["models"]:
                    row["record"]["source_revision"] = REVISION
                identity = retained_identity(value, request)
                adapter = Path(value["framework"]["adapter_file"]).read_bytes()

                def verify(observations, comparators):
                    with denied_live_access():
                        return torch_records.verify_retained_observations(observations, request,
                            retained_identity=identity, adapter_bytes=adapter, **comparators,
                            raw_log=raw_log(observations))

                self.assertEqual(verify(value, native)["operator_calls"], 16)
                case_id, donor_id = request["base_request"]["model_cases"][:2]
                for iterations in ((0,), (1,), (0, 1)):
                    with self.subTest(format=fmt, iterations=iterations):
                        changed, comparisons = copy.deepcopy(value), copy.deepcopy(native)
                        for iteration in iterations:
                            trace = changed["base_observations"]["models"][iteration]["record"]["trace"]
                            donor = native_models[donor_id][iteration]["trace"]
                            substitute_intermediates(trace, donor)
                            substitute_intermediates(comparisons["native_models"][case_id][iteration]["trace"], donor)
                            changed["framework_models"][iteration]["result"]["bytes"] = \
                                packed(trace["output_words"]).hex()
                            self.assert_linked(trace)
                        # JSON/raw records and all three routes agree with one
                        # another; the immutable case must still reject them.
                        with self.assertRaisesRegex(ValueError, "actual hidden_words differ from frozen reference"):
                            verify(changed, comparisons)
                        self.assertEqual(encoded(comparisons["model_cases"]), frozen)

    def test_parsed_intermediates_do_not_alias_references_or_saved_observations(self):
        for fmt in self.samples:
            with self.subTest(format=fmt):
                sample = copy.deepcopy(self.samples[fmt])
                before = encoded(sample[1:])
                _, models, _ = verify_results(sample, fmt)
                pristine = copy.deepcopy(models)
                for case, saved in zip(sample[4], sample[1]["variants"][0]["cases"]):
                    for iteration, row in enumerate(models[case["id"]]):
                        trace = row["trace"]
                        for key in ("hidden_words", "bridge_words", "output_words"):
                            self.assertIsNot(trace[key], case[key])
                            self.assertIsNot(trace[key], saved["observations"][iteration]["trace"][key])
                            trace[key][0] = "ffffffff"
                        for stage in trace["native"]:
                            stage["output_words"][0] = "ffffffff"
                self.assertEqual(encoded(sample[1:]), before)
                self.assertEqual(verify_results(sample, fmt)[1], pristine)


if __name__ == "__main__":
    unittest.main()

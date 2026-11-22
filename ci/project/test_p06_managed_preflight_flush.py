# SPDX-License-Identifier: Apache-2.0
"""Cache-flush accounting controls; synthetic host records only."""

from copy import deepcopy
import itertools
import unittest

import p06_managed_preflight_contract as manifest
import p06_managed_preflight_records as records
from p06_managed_preflight_test_fixture import (
    BINDING, EXPECTED_LIBRARIES, raw_records, render_log,
)


class ManagedPreflightFlushTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contract = manifest.load_contract()
        cls.examples = {(fmt, policy): raw_records(fmt, policy, contract=cls.contract)
                        for fmt, policy in itertools.product(("fp16", "bf16"),
                            ("per_operation", "reusable_single_tile"))}

    def raw(self, fmt="fp16", policy="per_operation"):
        return deepcopy(self.examples[fmt, policy])

    def verify(self, raw, fmt="fp16", policy="per_operation"):
        case, operations, summary, witness = raw
        return records.verify_output(render_log(operations, summary, witness),
            contract=self.contract, case=case, fmt=fmt, policy=policy,
            binding_id=BINDING, sample_id=f"warm-simx-{fmt}-pair0-{policy}",
            process_id=f"preflight-simx-{fmt}-{policy}", expected_libraries=EXPECTED_LIBRARIES)

    def reject(self, mutate, *, full=False):
        raw = self.raw()
        mutate(raw[3])
        with self.assertRaises(ValueError):
            if full:
                self.verify(raw)
            else:
                records._cache_flushes(raw[3])

    def test_four_cells_account_for_33_flushes_and_297_total_dcr_reads(self):
        flushes = total = 0
        for (fmt, policy), example in self.examples.items():
            with self.subTest(fmt=fmt, policy=policy):
                result = self.verify(example, fmt, policy)
                witness = result["witness"]
                self.assertEqual(len(witness["reads"]), 264)
                self.assertEqual(len(witness["cache_flush_reads"]), 33)
                self.assertEqual(witness["observation"]["dcr_read_entries"], 297)
                self.assertEqual(witness["observation"]["dcr_read_completed"], 297)
                self.assertEqual(witness["observation"]["cache_flush_count"], 33)
                for name in manifest.FALSE_CLAIMS:
                    self.assertIs(witness[name], False)
                flushes += len(witness["cache_flush_reads"])
                total += witness["observation"]["dcr_read_completed"]
        self.assertEqual((flushes, total), (132, 1188))
        self.assertEqual(manifest.COMPLETE_COUNTS["cache_flush_reads"], flushes)
        self.assertEqual(manifest.COMPLETE_COUNTS["dcr_reads"], total)

    def test_global_sequence_has_flushes_between_the_original_mpm_groups(self):
        witness = self.raw()[3]
        expected_mpm = [*range(1, 67), *range(68, 134), *range(166, 232), *range(232, 298)]
        expected_flush = [67, *range(134, 166)]
        self.assertEqual([row["sequence"] for row in witness["reads"]], expected_mpm)
        self.assertEqual([row["sequence"] for row in witness["cache_flush_reads"]], expected_flush)
        self.assertEqual(sorted(expected_mpm + expected_flush), list(range(1, 298)))
        self.assertEqual([row["completed_runs"] for row in witness["cache_flush_reads"]],
                         list(range(1, 34)))
        self.assertEqual([row["cache_flush_count"] for row in witness["snapshots"]], [0, 1, 33, 33])

    def test_real_flush_clock_advance_is_allowed_but_mpm_sampling_is_quiescent(self):
        raw = self.raw()
        for index, row in enumerate(raw[3]["cache_flush_reads"]):
            row["ticks_before"] = 100 + index
            row["ticks_after"] = 140 + 2 * index
        result = self.verify(raw)
        self.assertTrue(all(row["ticks_after"] > row["ticks_before"]
                            for row in result["witness"]["cache_flush_reads"]))
        self.assertTrue(all(row["ticks_after"] == row["ticks_before"]
                            for row in result["witness"]["reads"]))
        raw[3]["reads"][132]["ticks_after"] += 1
        with self.assertRaises(ValueError):
            self.verify(raw)

    def test_flush_without_additional_ticks_is_also_a_valid_observation(self):
        raw = self.raw()
        for row in raw[3]["cache_flush_reads"]:
            row["ticks_after"] = row["ticks_before"]
        self.verify(raw)

    def test_every_flush_route_reply_and_sequence_is_checked(self):
        for index in range(33):
            for name in ("addr", "tag", "value", "sequence", "completed_runs", "generation"):
                with self.subTest(index=index, field=name):
                    self.reject(lambda w, i=index, n=name:
                        w["cache_flush_reads"][i].__setitem__(n, w["cache_flush_reads"][i][n] + 1))

    def test_every_flush_completion_and_error_state_is_checked(self):
        changes = {"status": -1, "completed": False, "overflow": True,
                   "idle_before": False, "idle_after": False,
                   "any_running_before": True, "any_running_after": True}
        for index in range(33):
            for name, value in changes.items():
                with self.subTest(index=index, field=name):
                    self.reject(lambda w, i=index, n=name, v=value:
                                w["cache_flush_reads"][i].__setitem__(n, v))

    def test_every_flush_preserves_class_and_reset_and_never_rewinds_ticks(self):
        for index in range(33):
            for name in ("class_after", "reset_after"):
                with self.subTest(index=index, field=name):
                    self.reject(lambda w, i=index, n=name:
                        w["cache_flush_reads"][i].__setitem__(n, w["cache_flush_reads"][i][n] + 1))
            with self.subTest(index=index, field="ticks_after"):
                self.reject(lambda w, i=index: w["cache_flush_reads"][i].__setitem__(
                    "ticks_after", w["cache_flush_reads"][i]["ticks_before"] - 1))

    def test_public_verifier_rejects_flush_route_status_and_lifetime_mutations(self):
        changes = {"addr": 1, "tag": 1, "value": 1, "status": 1, "completed": False,
                   "overflow": True, "sequence": 68, "completed_runs": 2,
                   "idle_before": False, "idle_after": False,
                   "any_running_before": True, "any_running_after": True,
                   "class_after": 1, "reset_after": 3, "ticks_after": 99}
        for name, value in changes.items():
            with self.subTest(field=name):
                self.reject(lambda w, n=name, v=value:
                            w["cache_flush_reads"][0].__setitem__(n, v), full=True)

    def test_missing_extra_null_and_wrong_container_flush_inventory_reject(self):
        raw = self.raw()
        rows = raw[3]["cache_flush_reads"]
        for value in (None, {}, [], rows[:-1], rows + [deepcopy(rows[-1])]):
            with self.subTest(kind=type(value).__name__, length=len(value) if value is not None else None):
                self.reject(lambda w, v=value: w.__setitem__("cache_flush_reads", v), full=True)
        self.reject(lambda w: w.pop("cache_flush_reads"), full=True)

    def test_each_flush_is_individually_required(self):
        for index in range(33):
            with self.subTest(index=index):
                self.reject(lambda w, i=index: w["cache_flush_reads"].pop(i))

    def test_duplicate_and_reordered_flushes_reject(self):
        self.reject(lambda w: w["cache_flush_reads"].__setitem__(17,
                                                             deepcopy(w["cache_flush_reads"][16])))
        def reorder(witness):
            rows = witness["cache_flush_reads"]
            rows[0], rows[1] = rows[1], rows[0]
        self.reject(reorder, full=True)

    def test_surplus_unknown_dcr_route_cannot_be_hidden_by_changed_totals(self):
        def surplus(witness):
            extra = deepcopy(witness["cache_flush_reads"][-1])
            extra.update(addr=0x123, sequence=298, completed_runs=33)
            witness["cache_flush_reads"].append(extra)
            witness["observation"].update(dcr_read_entries=298, dcr_read_completed=298,
                                           cache_flush_count=34)
        self.reject(surplus, full=True)

    def test_flush_reply_cannot_be_substituted_for_an_mpm_half(self):
        self.reject(lambda w: w["reads"].__setitem__(66, deepcopy(w["cache_flush_reads"][0])), full=True)

    def test_mpm_half_cannot_be_substituted_for_a_flush_reply(self):
        self.reject(lambda w: w["cache_flush_reads"].__setitem__(0, deepcopy(w["reads"][66])), full=True)

    def test_historical_264_total_read_assumption_is_rejected(self):
        for name in ("dcr_read_entries", "dcr_read_completed"):
            with self.subTest(field=name):
                self.reject(lambda w, n=name: w["observation"].__setitem__(n, 264), full=True)
        self.reject(lambda w: w["observation"].update(dcr_read_entries=264, dcr_read_completed=264),
                    full=True)

    def test_flush_and_half_count_observations_are_not_interchangeable(self):
        for name, value in (("read_count", 297), ("cache_flush_count", 0),
                            ("cache_flush_count", 32), ("cache_flush_count", 34)):
            with self.subTest(field=name, value=value):
                self.reject(lambda w, n=name, v=value: w["observation"].__setitem__(n, v), full=True)

    def test_snapshot_flush_counts_bind_all_four_operation_boundaries(self):
        for index in range(4):
            with self.subTest(snapshot=index):
                self.reject(lambda w, i=index: w["snapshots"][i].__setitem__(
                    "cache_flush_count", w["snapshots"][i]["cache_flush_count"] + 1), full=True)

    def test_mpm_completed_runs_bind_each_quiescent_snapshot(self):
        for index in (0, 65, 66, 131, 132, 197, 198, 263):
            with self.subTest(half=index):
                self.reject(lambda w, i=index: w["reads"][i].__setitem__(
                    "completed_runs", w["reads"][i]["completed_runs"] + 1), full=True)

    def test_prime_and_final_flush_reset_generations_bind_snapshots(self):
        def set_reset(witness, index, value):
            witness["cache_flush_reads"][index].update(reset_before=value, reset_after=value)
        self.reject(lambda w: set_reset(w, 0, 1), full=True)
        self.reject(lambda w: set_reset(w, -1, 33), full=True)

    def test_intermediate_flush_reset_generation_stays_within_lifetime_and_order(self):
        for index, value in ((1, 0), (15, 15), (20, 35)):
            with self.subTest(index=index, generation=value):
                self.reject(lambda w, i=index, v=value:
                            w["cache_flush_reads"][i].update(reset_before=v, reset_after=v))

    def test_complete_global_sequence_cannot_be_replaced_by_per_trace_ordinals(self):
        def renumber(witness):
            for index, row in enumerate(witness["cache_flush_reads"]):
                row["sequence"] = index + 1
            for index, row in enumerate(witness["reads"]):
                row["sequence"] = index + 1
        self.reject(renumber, full=True)

    def test_missing_and_extra_flush_fields_reject(self):
        for field in manifest.READ_FIELDS:
            with self.subTest(field=field):
                self.reject(lambda w, n=field: w["cache_flush_reads"][0].pop(n))
        self.reject(lambda w: w["cache_flush_reads"][0].__setitem__("unknown", 0), full=True)
        self.reject(lambda w: w["cache_flush_reads"].__setitem__(0, None))

    def test_flush_integers_are_unsigned_bounded_and_not_booleans(self):
        widths = {name: 64 for name in ("sequence", "generation", "completed_runs", "ticks_before",
                                       "ticks_after", "reset_before", "reset_after")}
        widths.update({name: 32 for name in ("addr", "tag", "value", "class_before", "class_after")})
        for name, bits in widths.items():
            for value in (False, -1, 1 << bits, "0", None):
                with self.subTest(field=name, value=value):
                    self.reject(lambda w, n=name, v=value: w["cache_flush_reads"][0].__setitem__(n, v))

    def test_flush_boolean_and_status_types_cannot_alias_integer_values(self):
        for name in ("completed", "overflow", "idle_before", "idle_after",
                     "any_running_before", "any_running_after"):
            with self.subTest(field=name):
                self.reject(lambda w, n=name: w["cache_flush_reads"][0].__setitem__(
                    n, int(w["cache_flush_reads"][0][n])))
        self.reject(lambda w: w["cache_flush_reads"][0].__setitem__("status", False))


if __name__ == "__main__":
    unittest.main()

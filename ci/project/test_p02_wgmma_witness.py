# SPDX-License-Identifier: Apache-2.0
"""Independent synthetic controls for the passive metadata-witness contract.

The event schedules below are deliberately interleaved and reuse one-bit UUIDs.
They test the log validator, not RTL execution or observed processor coverage.
"""

from copy import deepcopy
import json
from pathlib import Path
import unittest
from unittest import mock

import p02_wgmma_records as arithmetic
import p02_wgmma_witness as witness


ROOT = Path(__file__).resolve().parents[2]
CASE = next(case for case in json.loads((ROOT / "ci/project/fixtures/p02_wgmma_v1.json").read_text())["cases"]
            if case["id"] == "fp16-sparse-signatures-a")
VARIANT = {"mode": "ss", "a_layout": "row-major-compressed"}
EVENT_ORDER = {"reserve": 0, "wait": 1, "release": 2, "issue": 3}


def trace(*, reset=False, wait_launches=(True, True), delayed_issue=False):
    rows = []
    for iteration in range(2):
        identity = dict(case_id=CASE["id"], format="fp16", sparse=True,
                        mode="ss", a_layout="row-major-compressed", iteration=iteration)
        rows.append(("BEGIN", dict(identity, m=64, n=8, k=16, words=512)))
        events = []
        for tile in range(2):
            for warp in range(8):
                slot, local_warp = warp % 4, warp // 4
                start = 20 + tile * 40 + slot * 2 + local_warp
                if not reset:
                    start += iteration * 200
                base = dict(instance=f"core0.issue{slot}.scoreboard", wis=local_warp,
                            epoch=iteration + 1 if reset else 1,
                            sequence=tile + 1 if reset else iteration * 2 + tile + 1,
                            load_pc="0x100", load_uuid="0x0", load_cta=local_warp,
                            wid=warp, pc="0x100", uuid="0x0", cta=local_warp,
                            wait_cycles=0)
                events.append(dict(base, event="reserve", cycle=start))
                waited = wait_launches[iteration]
                if waited:
                    events.append(dict(base, event="wait", cycle=start + 3,
                                       pc="0x110", wait_cycles=1))
                events.append(dict(base, event="release", cycle=start + 8,
                                   wait_cycles=5 if waited else 0))
                events.append(dict(base, event="issue", cycle=start + 8 + (3 if delayed_issue else 0),
                                   pc="0x110", wait_cycles=5 if waited else 0))
        events.sort(key=lambda item: (item["cycle"], EVENT_ORDER[item["event"]], item["wid"]))
        rows.extend(("META", event) for event in events)
        rows.append(("RESULT", dict(identity, checked=512, mismatches=0,
                                    actual_bits=list(CASE["expected"]), expected_bits=list(CASE["expected"]))))
        rows.append(("PERF", f"PERF: instrs={100 * (iteration + 1)}, cycles={1000 * (iteration + 1)}, IPC=0.100"))
    rows.append(("PASS", dict(case_id=CASE["id"], iterations=2, checked=1024)))
    return rows


def render(rows):
    return "\n".join(payload if kind == "PERF" else "P02_WGMMA_" + kind + " " + json.dumps(payload)
                     for kind, payload in rows) + "\n"


def position(rows, event, *, warp=0, sequence=1):
    return next(index for index, (kind, record) in enumerate(rows)
                if kind == "META" and record["event"] == event
                and record["wid"] == warp and record["sequence"] == sequence)


def add_first_launch_transaction(rows, *, warp=0, sequence=3):
    extra = []
    for kind, record in rows:
        if kind == "META" and record["epoch"] == 1 and record["wid"] == warp and record["sequence"] == 2:
            record = deepcopy(record)
            record["sequence"] = sequence
            record["cycle"] += 40 * (sequence - 2)
            extra.append((kind, record))
    if len(extra) != 4:
        raise AssertionError("the independent schedule needs a complete source transaction")
    index = next(index for index, (kind, _) in enumerate(rows) if kind == "RESULT")
    rows[index:index] = extra


class WgmmaWitnessTest(unittest.TestCase):
    def reject(self, rows, message=None):
        with self.assertRaisesRegex(ValueError, message or "WGMMA witness"):
            witness.verify_witness(render(rows))

    def test_interleaved_warps_reused_uuid_and_same_cycle_release(self):
        rows = trace()
        result = witness.verify_witness(render(rows))
        self.assertEqual(result["launch_count"], 2)
        self.assertEqual(result["event_count"], 128)
        self.assertEqual(result["transaction_count"], 32)
        self.assertEqual(result["waited_transaction_count"], 32)
        self.assertEqual(result["wait_cycles"], 160)
        self.assertEqual(result["coverage_requirement"], "nonzero_wait_each_launch")
        for launch in result["launches"]:
            self.assertEqual(launch["transaction_count"], 16)
            self.assertEqual(launch["wait_cycles"], 80)
            self.assertEqual({slot["wid"] for slot in launch["per_slot"]}, set(range(8)))
            self.assertTrue(all(slot["transaction_count"] == 2 for slot in launch["per_slot"]))
        exact = arithmetic.verify_output(render(rows), CASE, VARIANT, witness=True)
        self.assertEqual(exact["checked_output_words"], 1024)
        self.assertEqual(exact["metadata_records"], 128)

    def test_reset_epochs_and_delayed_acceptance_are_legal(self):
        result = witness.verify_witness(render(trace(reset=True, delayed_issue=True)))
        for iteration, launch in enumerate(result["launches"]):
            self.assertEqual({slot["epoch"] for slot in launch["per_slot"]}, {iteration + 1})
        self.assertEqual(result["wait_cycles"], 160)

    def test_cta_numbers_can_change_between_complete_launches(self):
        rows = trace(reset=True, delayed_issue=True)
        ctas = {1: (2, 6), 2: (3, 7)}
        for kind, record in rows:
            if kind == "META":
                record["cta"] = record["load_cta"] = ctas[record["epoch"]][record["wid"] // 4]
        result = witness.verify_witness(render(rows))
        for iteration, launch in enumerate(result["launches"]):
            self.assertEqual({slot["cta"] for slot in launch["per_slot"]}, set(ctas[iteration + 1]))
            self.assertEqual([len(group["warps"]) for group in launch["cta_groups"]], [4, 4])

    def test_complete_inventory_does_not_require_every_warp_to_wait(self):
        rows = []
        for kind, record in trace():
            if kind == "META" and not (record["wid"] == 0 and record["sequence"] % 2 == 1):
                if record["event"] == "wait":
                    continue
                record["wait_cycles"] = 0
            rows.append((kind, record))
        result = witness.verify_witness(render(rows))
        self.assertEqual(result["transaction_count"], 32)
        self.assertEqual(result["waited_transaction_count"], 2)
        self.assertTrue(all(launch["waited_transaction_count"] == 1 for launch in result["launches"]))

    def test_missing_complete_slot_or_warp_stream_cannot_qualify(self):
        for epoch in (1, 2):
            for removed in ({0, 4}, {3, 7}, {0}, {7}):
                with self.subTest(epoch=epoch, removed=removed):
                    rows = [(kind, record) for kind, record in trace(reset=True)
                            if kind != "META" or record["epoch"] != epoch or record["wid"] not in removed]
                    self.assertEqual(arithmetic.verify_output(render(rows), CASE, VARIANT,
                                                              witness=True)["checked_output_words"], 1024)
                    self.reject(rows, "exactly 16")

    def test_total_and_per_warp_transaction_counts_are_independent(self):
        missing = [(kind, record) for kind, record in trace(reset=True)
                   if not (kind == "META" and record["epoch"] == 1
                           and record["wid"] == 1 and record["sequence"] == 2)]
        self.reject(missing, "exactly 16")
        extra = trace(reset=True)
        add_first_launch_transaction(extra)
        self.reject(extra, "exactly 16")
        unbalanced = deepcopy(missing)
        add_first_launch_transaction(unbalanced)
        self.reject(unbalanced, "exactly two transactions per warp")
        missing_warp = [(kind, record) for kind, record in trace(reset=True)
                        if not (kind == "META" and record["epoch"] == 1 and record["wid"] == 0)]
        add_first_launch_transaction(missing_warp, warp=4, sequence=3)
        add_first_launch_transaction(missing_warp, warp=4, sequence=4)
        self.reject(missing_warp, "all eight physical warps")

    def test_each_warp_keeps_its_cta_across_both_metadata_loads(self):
        rows = trace(reset=True)
        for kind, record in rows:
            if kind == "META" and record["epoch"] == 1 and record["wid"] == 0 and record["sequence"] == 2:
                record["cta"] = record["load_cta"] = 2
        self.reject(rows, "warp changed CTA within a launch")

    def test_cta_inventory_requires_two_groups_of_four_warps(self):
        for grouping in ("one_cta", "three_ctas", "five_and_three"):
            with self.subTest(grouping=grouping):
                rows = trace()
                for kind, record in rows:
                    if kind != "META":
                        continue
                    if grouping == "one_cta":
                        record["cta"] = record["load_cta"] = 0
                    elif grouping == "three_ctas" and record["wid"] == 0:
                        record["cta"] = record["load_cta"] = 2
                    elif grouping == "five_and_three" and record["wid"] == 4:
                        record["cta"] = record["load_cta"] = 0
                self.reject(rows, "two CTAs with four warps each")

    def test_diagnostic_wait_switch_cannot_waive_inventory(self):
        rows = [(kind, record) for kind, record in trace(wait_launches=(False, False))
                if kind != "META" or record["wid"] not in {3, 7}]
        with self.assertRaisesRegex(ValueError, "exactly 16"):
            witness.verify_witness(render(rows), require_wait=False)

    def test_wait_is_required_in_each_launch_and_diagnostic_is_labeled(self):
        for waited in ((False, True), (True, False), (False, False)):
            with self.subTest(waited=waited):
                rows = trace(wait_launches=waited)
                self.reject(rows, "zero actual metadata waits")
                result = witness.verify_witness(render(rows), require_wait=False)
                self.assertEqual(result["coverage_requirement"], "observation_only")
                self.assertEqual(result["waited_transaction_count"], 16 * sum(waited))

    def test_missing_and_duplicate_transitions_cannot_close_transactions(self):
        for event in EVENT_ORDER:
            for mutation in ("remove", "duplicate"):
                with self.subTest(event=event, mutation=mutation):
                    rows = trace()
                    index = position(rows, event)
                    if mutation == "remove":
                        del rows[index]
                    else:
                        rows.insert(index + 1, deepcopy(rows[index]))
                    self.reject(rows)

    def test_release_and_issue_ordering(self):
        for first, second in (("wait", "reserve"), ("release", "wait"), ("issue", "release")):
            with self.subTest(first=first, second=second):
                rows = trace()
                left, right = position(rows, first), position(rows, second)
                rows[left], rows[right] = rows[right], rows[left]
                self.reject(rows)

    def test_waiter_and_metadata_identity_cannot_alias_one_bit_uuid(self):
        mutations = (("release", "pc", "0x104"), ("release", "uuid", "0x1"),
                     ("issue", "pc", "0x114"), ("issue", "uuid", "0x1"),
                     ("wait", "load_pc", "0x104"), ("issue", "load_uuid", "0x1"),
                     ("release", "load_cta", 1), ("issue", "cta", 1),
                     ("wait", "wid", 1), ("release", "wis", 1))
        for event, field, value in mutations:
            with self.subTest(event=event, field=field):
                rows = trace()
                rows[position(rows, event)][1][field] = value
                self.reject(rows)

    def test_busy_interval_count_is_exact(self):
        for event, field, value in (("wait", "wait_cycles", 2),
                                    ("release", "wait_cycles", 4),
                                    ("issue", "wait_cycles", 6),
                                    ("release", "cycle", 23),
                                    ("issue", "cycle", 27)):
            with self.subTest(event=event, field=field, value=value):
                rows = trace()
                rows[position(rows, event)][1][field] = value
                self.reject(rows)

    def test_sequences_continue_and_only_reset_with_epochs(self):
        for value in (0, 2, 1025):
            with self.subTest(sequence=value):
                rows = trace()
                rows[position(rows, "reserve")][1]["sequence"] = value
                self.reject(rows)
        rows = trace()
        for kind, record in rows:
            if kind == "META" and record["sequence"] >= 3:
                record["sequence"] -= 2
        self.reject(rows, "sequence")

    def test_epoch_regression_or_reset_inside_launch_fails(self):
        rows = trace()
        rows[position(rows, "release")][1]["epoch"] = 2
        self.reject(rows, "reset occurred inside a launch")
        rows = trace(reset=True)
        for kind, record in rows:
            if kind == "META" and record["epoch"] == 2:
                record["epoch"] = 1
        self.reject(rows)

    def test_instance_to_slot_assignment_cannot_change_or_duplicate(self):
        for new_instance in ("new.scoreboard", "core0.issue1.scoreboard"):
            with self.subTest(instance=new_instance):
                rows = trace()
                rows[position(rows, "reserve", sequence=2)][1]["instance"] = new_instance
                self.reject(rows)

    def test_invalid_numeric_types_ranges_and_pc_encodings(self):
        mutations = {"wis": (False, -1, 2), "wid": (True, -1, 8),
                     "epoch": (True, 0, 2**32), "sequence": (True, 1.0, 1025),
                     "cycle": (True, -1, 2**64), "wait_cycles": (True, -1, 1048576),
                     "load_cta": (True, -1, 8), "cta": (True, -1, 8),
                     "load_pc": (12, "0X100", "0xg", "0x" + "1" * 17),
                     "uuid": (None, "0X0", "1"), "instance": (0, "", "bad\ninstance"),
                     "event": (None, "complete")}
        for field, values in mutations.items():
            for value in values:
                with self.subTest(field=field, value=value):
                    rows = trace()
                    rows[position(rows, "reserve")][1][field] = value
                    self.reject(rows)

    def test_metadata_schema_requires_exact_keys(self):
        for mutation in ("missing", "extra"):
            rows = trace()
            record = rows[position(rows, "reserve")][1]
            if mutation == "missing":
                del record["load_pc"]
            else:
                record["unobserved"] = True
            self.reject(rows, "fields")

    def test_json_duplicates_nonfinite_values_and_bad_markers_fail(self):
        text = render(trace())
        for mutated in (text.replace('"epoch": 1', '"epoch": 1, "epoch": 1', 1),
                        text.replace('"epoch": 1', '"epoch": NaN', 1),
                        text.replace("P02_WGMMA_META", "prefix:P02_WGMMA_META", 1),
                        text.replace("P02_WGMMA_META", "P02_WGMMA_UNKNOWN", 1),
                        text.replace("P02_WGMMA_META {", "P02_WGMMA_META [", 1)):
            with self.subTest(prefix=mutated[:80]):
                with self.assertRaises(ValueError):
                    witness.verify_witness(mutated)

    def test_launch_boundaries_and_complete_two_launch_inventory(self):
        for mutation in ("missing_begin", "missing_result", "missing_pass", "duplicate_begin",
                         "outside", "after_pass", "no_monitor", "unfinished"):
            with self.subTest(mutation=mutation):
                rows = trace()
                if mutation.startswith("missing_"):
                    kind = mutation[len("missing_"):].upper()
                    del rows[next(i for i, row in enumerate(rows) if row[0] == kind)]
                elif mutation == "duplicate_begin":
                    rows.insert(1, deepcopy(rows[0]))
                elif mutation in ("outside", "after_pass"):
                    event = deepcopy(rows[position(rows, "reserve")])
                    rows.insert(0 if mutation == "outside" else len(rows), event)
                elif mutation == "no_monitor":
                    rows = [row for row in rows if row[0] != "META"]
                else:
                    del rows[position(rows, "issue", warp=7, sequence=2)]
                self.reject(rows)

    def test_host_identity_and_shape_are_fixed(self):
        for kind, field, value in (("BEGIN", "format", "bf16"), ("BEGIN", "sparse", False),
                                   ("BEGIN", "mode", "rs"), ("BEGIN", "m", 32),
                                   ("BEGIN", "iteration", True), ("RESULT", "case_id", "different"),
                                   ("RESULT", "checked", 511), ("RESULT", "mismatches", 1),
                                   ("PASS", "iterations", 1), ("PASS", "checked", 512)):
            with self.subTest(kind=kind, field=field):
                rows = trace()
                next(record for label, record in rows if label == kind)[field] = value
                self.reject(rows)

    def test_observation_and_arithmetic_are_separate_required_checks(self):
        rows = trace()
        next(record for kind, record in rows if kind == "RESULT")["actual_bits"][0] = "7fc00001"
        self.assertEqual(witness.verify_witness(render(rows))["transaction_count"], 32)
        with self.assertRaisesRegex(ValueError, "actual_bits"):
            arithmetic.verify_output(render(rows), CASE, VARIANT, witness=True)
        with self.assertRaisesRegex(ValueError, "metadata witness record"):
            arithmetic.verify_output(render(trace()), CASE, VARIANT, witness=False)

    def test_failure_diagnostics_and_control_bytes_fail(self):
        text = render(trace())
        for prefix in ("fatal: stopped\n", "runtime error: bad value\n", "Assertion x failed\n",
                       "Segmentation fault\n", "bad\x00control\n"):
            with self.subTest(prefix=prefix):
                with self.assertRaises(ValueError):
                    witness.verify_witness(prefix + text)

    def test_log_budget_is_inclusive_and_diagnostic_switch_is_boolean(self):
        text = render(trace())
        size = len(text.encode("utf-8"))
        with mock.patch.object(witness, "MAX_LOG_BYTES", size):
            self.assertEqual(witness.verify_witness(text)["transaction_count"], 32)
        with mock.patch.object(witness, "MAX_LOG_BYTES", size - 1):
            with self.assertRaisesRegex(ValueError, "budget"):
                witness.verify_witness(text)
        for value in (None, 0, 1, "false"):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, "boolean"):
                    witness.verify_witness(text, require_wait=value)


if __name__ == "__main__":
    unittest.main()

# SPDX-License-Identifier: Apache-2.0
"""Adversarial synthetic lifetime records; no native or performance evidence."""

from copy import deepcopy
import itertools
import unittest

import p06_managed_preflight_contract as preflight
import p06_managed_preflight_records as parent_records
import p06_managed_preflight_test_fixture as parent_fixture
import p06_native_lifetime_contract as manifest
import p06_native_lifetime_records as records
from p06_native_lifetime_test_fixture import (
    BINDING, EXPECTED_LIBRARIES, raw_records, render_log,
)


class NativeLifetimeRecordTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contract = preflight.load_contract()
        cls.examples = {
            (fmt, policy): raw_records(fmt, policy, contract=cls.contract)
            for fmt, policy in itertools.product(
                ("fp16", "bf16"), ("per_operation", "reusable_single_tile"))
        }

    def raw(self, fmt="fp16", policy="per_operation"):
        return deepcopy(self.examples[fmt, policy])

    def arguments(self, raw, fmt="fp16", policy="per_operation"):
        return {
            "contract": self.contract, "case": raw[0], "fmt": fmt, "policy": policy,
            "binding_id": BINDING, "sample_id": f"warm-simx-{fmt}-pair0-{policy}",
            "process_id": f"preflight-simx-{fmt}-{policy}",
            "expected_libraries": EXPECTED_LIBRARIES,
        }

    def verify(self, raw, fmt="fp16", policy="per_operation", *, text=None):
        return records.verify_output(render_log(*raw[1:]) if text is None else text,
                                     **self.arguments(raw, fmt, policy))

    def verify_parent(self, raw, fmt="fp16", policy="per_operation"):
        return parent_records.verify_output(parent_fixture.render_log(*raw[1:4]),
                                            **self.arguments(raw, fmt, policy))

    @staticmethod
    def at(value, path):
        for part in path:
            value = value[part]
        return value

    def reject_value(self, path, value, pattern=None):
        raw = self.raw()
        self.at(raw[4], path[:-1])[path[-1]] = value
        with self.assertRaisesRegex(ValueError, pattern or ".*"):
            self.verify(raw)

    @staticmethod
    def models(value):
        if isinstance(value, dict):
            if "exitcode" in value:
                yield value
            for child in value.values():
                yield from NativeLifetimeRecordTests.models(child)
        elif isinstance(value, (list, tuple)):
            for child in value:
                yield from NativeLifetimeRecordTests.models(child)

    def test_four_cells_preserve_the_original_prefix_and_result(self):
        totals = dict(processes=0, launches=0, checked_words=0, runs=0,
                      snapshots=0, mpm_pending_sides=0, flush_pending_sides=0)
        for (fmt, policy), raw in self.examples.items():
            with self.subTest(fmt=fmt, policy=policy):
                text = render_log(*raw[1:])
                original = parent_fixture.render_log(*raw[1:4])
                prefix, sidecar = records._split_output(text)
                self.assertEqual(prefix.encode(), original.encode())
                self.assertEqual(sidecar, raw[4])
                result = self.verify(raw, fmt, policy)
                parent = self.verify_parent(raw, fmt, policy)
                self.assertEqual({name: result[name] for name in parent}, parent)
                self.assertEqual(result["lifetime"], raw[4])
                totals["processes"] += 1
                totals["launches"] += result["warm"]["accounting"]["launches"]
                totals["checked_words"] += result["warm"]["accounting"]["checked_words"]
                totals["runs"] += len(sidecar["runs"])
                totals["snapshots"] += len(sidecar["snapshots"])
                totals["mpm_pending_sides"] += 2 * len(sidecar["reads"])
                totals["flush_pending_sides"] += 2 * len(sidecar["cache_flush_reads"])
                self.assertEqual(sidecar["unresolved_obligations"],
                                 list(manifest.UNRESOLVED_OBLIGATIONS))
                for name in manifest.FALSE_CLAIMS:
                    self.assertIs(sidecar[name], False)
        self.assertEqual(totals, dict(processes=4, launches=132, checked_words=4224,
                                     runs=132, snapshots=16, mpm_pending_sides=2112,
                                     flush_pending_sides=264))

    def test_version_selection_never_reconstructs_missing_observations(self):
        raw = self.raw()
        prefix = parent_fixture.render_log(*raw[1:4])
        self.verify_parent(raw)
        with self.assertRaisesRegex(ValueError, "exactly one lifetime witness"):
            self.verify(raw, text=prefix)
        with self.assertRaisesRegex(ValueError, "final witness line"):
            parent_records.verify_output(render_log(*raw[1:]), **self.arguments(raw))

    def test_successful_signed_legacy_gp_values_are_not_error_status(self):
        for gp in (-1, 7, -(1 << 31), (1 << 31) - 1):
            with self.subTest(gp=gp):
                raw = self.raw()
                for value in self.models(raw[3:]):
                    value["exitcode"] = gp
                result = self.verify(raw)
                self.assertEqual(result["lifetime"]["runs"][-1]["after"]["exitcode"], gp)
                self.assertTrue(all(run["completed"] and not run["exception"]
                                    for run in result["lifetime"]["runs"]))

    def test_every_run_side_requires_an_observed_zero_pending_balance(self):
        raw = self.raw()
        lifetime, witness = raw[4], raw[3]
        baseline = lifetime["constructed_state"]["reset_generation"]
        checked = 0
        for index, run in enumerate(lifetime["runs"]):
            for side in ("before", "after"):
                with self.subTest(run=index, side=side):
                    run[side]["pending_reads"] = 1
                    with self.assertRaisesRegex(ValueError, "pending_reads"):
                        records._runs(lifetime, witness, baseline)
                    run[side]["pending_reads"] = 0
                    checked += 1
        self.assertEqual(checked, 66)
        for index, side in itertools.product((0, 16, 32), ("before", "after")):
            self.reject_value(("runs", index, side, "pending_reads"), 1, "pending_reads")

    def test_every_mpm_and_flush_side_requires_observed_zero_pending(self):
        raw = self.raw()
        checked = 0
        for name, expected in (("reads", 264), ("cache_flush_reads", 33)):
            values, originals = raw[4][name], raw[3][name]
            self.assertEqual(len(values), expected)
            for index, row in enumerate(values):
                for side in ("pending_before", "pending_after"):
                    with self.subTest(kind=name, index=index, side=side):
                        row[side] = 1
                        with self.assertRaisesRegex(ValueError, side):
                            records._pending_reads(values, originals, name)
                        row[side] = 0
                        checked += 1
            for index, side in itertools.product((0, expected // 2, expected - 1),
                                                 ("pending_before", "pending_after")):
                self.reject_value((name, index, side), 1, side)
        self.assertEqual(checked, 594)

    def test_construction_snapshots_and_destructor_cannot_hide_pending_reads(self):
        paths = [("constructed_state", "pending_reads"),
                 ("destruction", "before", "pending_reads")]
        paths.extend(("snapshots", index, side, "pending_reads")
                     for index, side in itertools.product(range(4), ("before", "after")))
        for path in paths:
            with self.subTest(path=path):
                self.reject_value(path, 1, "pending_reads")

    def test_missing_extra_duplicate_and_reordered_run_records_fail(self):
        runs = self.raw()[4]["runs"]
        for value in (None, {}, [], runs[:-1], runs + [deepcopy(runs[-1])]):
            with self.subTest(kind=type(value).__name__):
                self.reject_value(("runs",), value, "run inventory")
        for first, second in ((0, 1), (15, 16), (31, 32)):
            for repair_ordinal in (False, True):
                with self.subTest(first=first, second=second, repair_ordinal=repair_ordinal):
                    raw = self.raw()
                    changed = raw[4]["runs"]
                    changed[first], changed[second] = changed[second], changed[first]
                    if repair_ordinal:
                        changed[first]["ordinal"], changed[second]["ordinal"] = first + 1, second + 1
                    self.assertEqual(raw[3]["observation"]["run_completed"], 33)
                    with self.assertRaises(ValueError):
                        self.verify(raw)
        duplicate = deepcopy(runs)
        duplicate[16] = deepcopy(duplicate[15])
        duplicate[16]["ordinal"] = 17
        self.reject_value(("runs",), duplicate)

    def test_exact_reset_delta_is_checked_at_every_run_boundary(self):
        raw = self.raw()
        lifetime, witness = raw[4], raw[3]
        baseline = lifetime["constructed_state"]["reset_generation"]
        for index, run in enumerate(lifetime["runs"]):
            for side, delta in itertools.product(("before", "after"), (-1, 1)):
                with self.subTest(run=index, side=side, delta=delta):
                    original = run[side]["reset_generation"]
                    run[side]["reset_generation"] += delta
                    with self.assertRaisesRegex(ValueError, "reset_generation"):
                        records._runs(lifetime, witness, baseline)
                    run[side]["reset_generation"] = original
        for index, side in itertools.product((0, 16, 32), ("before", "after")):
            value = raw[4]["runs"][index][side]["reset_generation"] + 1
            self.reject_value(("runs", index, side, "reset_generation"), value)

    def test_v1_accepts_collapsed_intermediate_resets_but_lifetime_rejects_them(self):
        raw = self.raw()
        for row in raw[3]["cache_flush_reads"][1:-1]:
            row["reset_before"] = row["reset_after"] = 2
        self.verify_parent(raw)
        self.assertEqual(raw[3]["observation"]["run_completed"], 33)
        with self.assertRaisesRegex(ValueError, "flush reset"):
            self.verify(raw)

    def test_snapshot_reset_progression_is_exact_even_with_repaired_v1_records(self):
        raw = self.raw()
        index = 1
        for side in ("before", "after"):
            raw[3]["snapshots"][index][side]["reset_generation"] += 1
            raw[4]["snapshots"][index][side]["reset_generation"] += 1
        for row in raw[3]["reads"][66:132]:
            row["reset_before"] += 1
            row["reset_after"] += 1
        raw[3]["cache_flush_reads"][0]["reset_before"] += 1
        raw[3]["cache_flush_reads"][0]["reset_after"] += 1
        self.verify_parent(raw)
        with self.assertRaisesRegex(ValueError, "snapshot.*reset_generation"):
            self.verify(raw)

    def test_run_outcomes_and_dcr_order_cannot_be_replaced_by_aggregate_counts(self):
        for index in (0, 1, 16, 32):
            for name, value in (("real_call_entered", False), ("completed", False),
                                ("exception", True)):
                with self.subTest(run=index, field=name):
                    self.reject_value(("runs", index, name), value, name)
            for name in ("dcr_reads_before", "dcr_reads_after", "cache_flushes_before",
                         "cache_flushes_after", "ordinal"):
                with self.subTest(run=index, field=name):
                    value = self.examples["fp16", "per_operation"][4]["runs"][index][name] + 1
                    self.reject_value(("runs", index, name), value, name)
        self.reject_value(("trace_overflow",), True, "trace_overflow")

    def test_clocks_reset_between_runs_and_only_flushes_may_advance_between_them(self):
        raw = self.raw()
        runs = raw[4]["runs"]
        self.assertGreater(runs[1]["before"]["ticks"], runs[1]["after"]["ticks"])
        self.verify(raw)
        for index, side in itertools.product((0, 16, 32), ("before", "after")):
            with self.subTest(run=index, side=side):
                self.reject_value(("runs", index, side, "ticks"), runs[index][side]["ticks"] + 1)
        for index in (0, 16, 32):
            changed = self.raw()
            changed[3]["cache_flush_reads"][index]["ticks_after"] += 1
            self.verify_parent(changed)
            with self.subTest(flush=index), self.assertRaises(ValueError):
                self.verify(changed)

    def test_hidden_cleanup_tick_rejects_even_if_terminal_and_disposal_are_repaired(self):
        raw = self.raw()
        for side in ("before", "after"):
            raw[3]["snapshots"][3][side]["ticks"] += 1
            raw[4]["snapshots"][3][side]["ticks"] += 1
        for row in raw[3]["reads"][198:]:
            row["ticks_before"] += 1
            row["ticks_after"] += 1
        raw[3]["observation"]["destruction"]["before"]["ticks"] += 1
        raw[4]["destruction"]["before"]["ticks"] += 1
        self.verify_parent(raw)
        with self.assertRaisesRegex(ValueError, "final cleanup boundary"):
            self.verify(raw)

    def test_post_terminal_change_and_unfinished_disposal_reject(self):
        raw = self.raw()
        terminal = raw[4]["destruction"]["before"]
        for name in ("ticks", "reset_generation", "core_cycles", "core_instructions", "generation"):
            with self.subTest(field=name):
                self.reject_value(("destruction", "before", name), terminal[name] + 1)
        for name, value in (("completed", False), ("idle_after", False),
                            ("ticks_after", 1), ("reset_after", terminal["reset_generation"] + 1)):
            with self.subTest(field=name):
                self.reject_value(("destruction", name), value)

    def test_core_counters_cannot_decrease_during_a_run(self):
        raw = self.raw()
        for name in ("core_cycles", "core_instructions"):
            value = raw[4]["runs"][16]["before"][name] - 1
            self.reject_value(("runs", 16, "after", name), value, "decreased")

    def test_every_pending_record_is_sequence_bound_and_cannot_be_omitted(self):
        for name in ("reads", "cache_flush_reads"):
            rows = self.raw()[4][name]
            for value in (None, {}, [], rows[:-1], rows + [deepcopy(rows[-1])]):
                with self.subTest(kind=name, value_type=type(value).__name__):
                    self.reject_value((name,), value, "inventory length")
            for index in (0, len(rows) // 2, len(rows) - 1):
                self.reject_value((name, index, "sequence"), rows[index]["sequence"] + 1, "sequence")
            changed = deepcopy(rows)
            changed[0], changed[1] = changed[1], changed[0]
            self.reject_value((name,), changed, "sequence")

    def test_unknown_missing_fields_and_boolean_integer_substitutions_reject(self):
        for path in ((), ("runs", 0), ("runs", 0, "before"), ("reads", 0),
                     ("snapshots", 0), ("destruction",)):
            for add in (False, True):
                raw = self.raw()
                target = self.at(raw[4], path)
                if add:
                    target["invented"] = 0
                else:
                    target.pop(next(iter(target)))
                with self.subTest(path=path, add=add), self.assertRaisesRegex(ValueError, "fields"):
                    self.verify(raw)
        for path, value in (
            (("schema_version",), True), (("simulation_workers",), True),
            (("trace_overflow",), 0), (("runs", 0, "ordinal"), True),
            (("runs", 0, "completed"), 1), (("runs", 0, "exception"), 0),
            (("runs", 0, "before", "pending_reads"), False),
            (("reads", 0, "pending_before"), False),
            (("runs", 0, "after", "exitcode"), True),
            (("runs", 0, "after", "exitcode"), 1 << 31),
            (("runs", 0, "after", "exitcode"), -(1 << 31) - 1),
            (("runs", 0, "after", "ticks"), -1),
            (("runs", 0, "after", "ticks"), 1 << 64),
        ):
            with self.subTest(path=path, value=value):
                self.reject_value(path, value)

    def test_identity_route_and_false_claims_are_bound(self):
        for name, value in (
            ("schema_version", 2), ("contract_id", preflight.CONTRACT_ID),
            ("process_id", "other-process"), ("sample_id", "other-sample"),
            ("execution_binding_sha256", "b" * 64), ("format", "bf16"),
            ("policy", "reusable_single_tile"), ("backend", "rtlsim"),
            ("xlen", 32), ("checked_counter_bits", 32), ("simulation_workers", 2),
            ("seeded", True), ("unresolved_obligations", []),
            *((name, True) for name in manifest.FALSE_CLAIMS),
        ):
            with self.subTest(field=name):
                self.reject_value((name,), value)

    def test_record_framing_duplicates_and_invalid_json_are_rejected(self):
        raw = self.raw()
        text = render_log(*raw[1:])
        prefix, _ = records._split_output(text)
        suffix = text[len(prefix):]
        invalid = (
            text.rstrip("\n"), text + "\n", text + suffix, suffix + prefix,
            text + "ignored trailing text\n", text.replace("\n", "\r\n"),
            prefix + manifest.WITNESS_PREFIX + "null\n",
            prefix + manifest.WITNESS_PREFIX + '{"schema_version":1,"schema_version":1}\n',
            prefix + manifest.WITNESS_PREFIX + '{"pending_reads":0.0}\n',
            prefix + manifest.WITNESS_PREFIX + '{"pending_reads":NaN}\n',
            prefix + manifest.WITNESS_PREFIX + "[" * 18 + "0" + "]" * 18 + "\n",
            prefix + manifest.WITNESS_PREFIX + " " * (manifest.MAX_RECORD_BYTES + 1) + "\n",
            text.replace(manifest.WITNESS_PREFIX, manifest.WITNESS_MARKER + "\t"),
        )
        for index, value in enumerate(invalid):
            with self.subTest(case=index), self.assertRaises(ValueError):
                self.verify(raw, text=value)

    def test_a_valid_lifetime_record_cannot_override_failed_original_evidence(self):
        for kind in ("numerics", "raw_counter", "async_error", "owner"):
            raw = self.raw()
            if kind == "numerics":
                bits = raw[1][0]["actual_bits"][0]
                raw[1][0]["actual_bits"][0] = f"{int(bits, 16) ^ 1:08x}"
            elif kind == "raw_counter":
                raw[3]["reads"][0]["value"] ^= 1
            elif kind == "async_error":
                raw[3]["observation"]["run_errors"] = 1
            else:
                raw[3]["snapshots"][3]["device_refs"] = 2
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                self.verify(raw)


if __name__ == "__main__":
    unittest.main()

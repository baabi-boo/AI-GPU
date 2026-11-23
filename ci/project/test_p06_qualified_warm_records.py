# SPDX-License-Identifier: Apache-2.0
"""Synthetic route and adversarial lifetime checks; no native execution evidence."""

from copy import deepcopy
import itertools
import unittest
from unittest import mock

import p06_managed_preflight_contract as preflight
import p06_managed_preflight_records as old_managed
import p06_native_lifetime_records as old_lifetime
import p06_native_lifetime_test_fixture as fixture
import p06_qualified_warm_records as records


BINDING = fixture.BINDING
EXPECTED_LIBRARIES = fixture.EXPECTED_LIBRARIES
render_log = fixture.render_log


def raw_records(fmt="fp16", policy="per_operation", *, pair_index=1,
                binding_id=BINDING, contract=None, **kwargs):
    """Invent warm identities around the coherent synthetic lifetime observations."""
    raw = fixture.raw_records(fmt, policy, binding_id=binding_id, contract=contract, **kwargs)
    _, operations, summary, witness, lifetime = raw
    sample_id = f"warm-simx-{fmt}-pair{pair_index}-{policy}"
    phase = "warmup" if pair_index == 0 else "measured"
    for row in [*operations, summary]:
        row.update(sample_id=sample_id, pair_index=pair_index, phase=phase)
    for snapshot in summary["snapshots"].values():
        snapshot["sample_id"] = sample_id
    summary["device_release"]["sample_id"] = sample_id
    witness.update(contract_id="p06-qualified-warm-counter-witness-v1",
                   process_id=sample_id, sample_id=sample_id)
    lifetime.update(contract_id="p06-qualified-warm-lifetime-witness-v1",
                    process_id=sample_id, sample_id=sample_id)
    return raw


class QualifiedWarmRecordTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contract = preflight.load_contract()
        cls.examples = {(fmt, policy): raw_records(fmt, policy, contract=cls.contract)
                        for fmt, policy in itertools.product(preflight.FORMATS, preflight.POLICIES)}

    def raw(self, fmt="fp16", policy="per_operation", pair_index=1):
        if pair_index == 1:
            return deepcopy(self.examples[fmt, policy])
        return raw_records(fmt, policy, pair_index=pair_index, contract=self.contract)

    def arguments(self, raw):
        summary = raw[2]
        return {"contract": self.contract, "case": raw[0], "fmt": summary["format"],
                "policy": summary["policy"], "binding_id": BINDING,
                "sample_id": summary["sample_id"], "process_id": summary["sample_id"],
                "pair_index": summary["pair_index"], "phase": summary["phase"],
                "expected_libraries": EXPECTED_LIBRARIES}

    def verify(self, raw, *, text=None, **changes):
        arguments = self.arguments(raw)
        arguments.update(changes)
        return records.verify_output(render_log(*raw[1:]) if text is None else text, **arguments)

    def test_all_24_frozen_cells_validate_complete_original_records(self):
        counts = {"processes": 0, "launches": 0, "checked_words": 0}
        identities = set()
        for fmt, policy, pair in itertools.product(preflight.FORMATS, preflight.POLICIES, range(6)):
            with self.subTest(fmt=fmt, policy=policy, pair=pair):
                raw = self.raw(fmt, policy, pair)
                result = self.verify(raw)
                self.assertEqual(result["warm"]["operations"], raw[1])
                self.assertEqual(result["warm"]["summary"], raw[2])
                self.assertEqual(result["witness"], raw[3])
                self.assertEqual(result["lifetime"], raw[4])
                self.assertGreater(raw[2]["snapshots"]["after_prime"]["counters"][0]["value"], 2**32)
                identities.add(result["witness"]["process_id"])
                counts["processes"] += 1
                counts["launches"] += result["warm"]["accounting"]["launches"]
                counts["checked_words"] += result["warm"]["accounting"]["checked_words"]
        self.assertEqual(len(identities), 24)
        self.assertEqual(counts, {"processes": 24, "launches": 792, "checked_words": 25344})

    def test_identity_rejects_noncanonical_pair_phase_format_policy_and_digest(self):
        valid = ("fp16", "per_operation", BINDING, 1, "measured")
        for index, values in ((0, (None, "fp32")), (1, (None, "resident")),
                              (2, (None, "a" * 63, "A" * 64)),
                              (3, (True, False, -1, 6, "1", 1.0)),
                              (4, (None, True, "warmup", "Measured"))):
            for value in values:
                args = list(valid)
                args[index] = value
                with self.subTest(index=index, value=value), self.assertRaises(ValueError):
                    records.process_identity(*args)

    def test_caller_cannot_select_a_different_pair_phase_sample_or_process(self):
        raw = self.raw()
        for change in ({"pair_index": 0}, {"pair_index": 2}, {"phase": "warmup"},
                       {"sample_id": "warm-simx-fp16-pair2-per_operation"},
                       {"process_id": "preflight-simx-fp16-per_operation"},
                       {"binding_id": "c" * 64}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.verify(raw, **change)

    def test_each_witness_binds_its_actual_contract_sample_process_and_execution(self):
        for index, field, value in itertools.product((3, 4),
                ("contract_id", "process_id", "sample_id", "execution_binding_sha256", "format", "policy"),
                ("wrong", None)):
            raw = self.raw()
            raw[index][field] = value
            with self.subTest(index=index, field=field, value=value), self.assertRaises(ValueError):
                self.verify(raw)

    def test_every_warm_operation_and_summary_keep_the_selected_pair_and_phase(self):
        for index in (0, 1, 16, 32, 33):
            for field, value in (("pair_index", 2), ("phase", "warmup"),
                                 ("sample_id", "warm-simx-fp16-pair2-per_operation"),
                                 ("qualification_id", "e" * 64)):
                raw = self.raw()
                row = raw[2] if index == 33 else raw[1][index]
                row[field] = value
                with self.subTest(index=index, field=field), self.assertRaises(ValueError):
                    self.verify(raw, pair_index=1, phase="measured",
                                sample_id="warm-simx-fp16-pair1-per_operation")

    def test_historical_transcript_cannot_be_upgraded_by_caller_route_selection(self):
        raw = fixture.raw_records(contract=self.contract)
        with self.assertRaisesRegex(ValueError, "counter witness.contract_id"):
            self.verify(raw)

    def test_historical_readers_reject_new_witnesses_even_for_pair_zero(self):
        raw = self.raw(pair_index=0)
        text = render_log(*raw[1:])
        args = self.arguments(raw)
        args.pop("pair_index")
        args.pop("phase")
        args["process_id"] = "preflight-simx-fp16-per_operation"
        with self.assertRaisesRegex(ValueError, "contract_id"):
            old_lifetime.verify_output(text, **args)
        with self.assertRaisesRegex(ValueError, "contract_id"):
            old_managed.verify_output(fixture.parent_fixture.render_log(*raw[1:4]), **args)

    def test_new_route_does_not_invoke_historical_identity_verifiers(self):
        with mock.patch.object(old_lifetime, "verify_output", side_effect=AssertionError("old lifetime route")), \
             mock.patch.object(old_managed, "verify_output", side_effect=AssertionError("old managed route")):
            self.verify(self.raw())

    def test_missing_extra_reordered_or_duplicate_witnesses_fail(self):
        raw = self.raw()
        text = render_log(*raw[1:])
        lines = text.splitlines(keepends=True)
        for changed in ("".join(lines[:-1]), "".join(lines[:-2]),
                        text + lines[-1], "".join(lines[:-2] + [lines[-1], lines[-2]]),
                        text.rstrip("\n"), text + "unexpected\n"):
            with self.subTest(tail=changed[-30:]), self.assertRaises(ValueError):
                self.verify(raw, text=changed)
        for index in (3, 4):
            for field, remove in (("phase", False), ("sample_id", True)):
                changed = self.raw()
                if remove:
                    del changed[index][field]
                else:
                    changed[index][field] = "measured"
                with self.subTest(index=index, field=field), self.assertRaises(ValueError):
                    self.verify(changed)

    def test_prime_numerics_and_cleanup_remain_required_when_excluded_from_timing(self):
        for change in ("bits", "close", "role", "missing"):
            raw = self.raw()
            if change == "bits":
                bits = raw[1][0]["actual_bits"][0]
                raw[1][0]["actual_bits"][0] = f"{int(bits, 16) ^ 1:08x}"
            elif change == "close":
                raw[1][0]["results"]["close"]["complete"] = False
            elif change == "role":
                raw[1][0]["role"] = "sample"
            else:
                raw[1].pop(0)
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.verify(raw)

    def test_terminal_half_reply_and_counter_coverage_are_required(self):
        for change in ("missing_high_half", "corrupt_high_half", "missing_selector"):
            raw = self.raw()
            if change == "missing_high_half":
                raw[3]["reads"].pop()
            elif change == "corrupt_high_half":
                raw[3]["reads"][-1]["value"] ^= 1
            else:
                raw[2]["snapshots"]["before_release"]["counters"].pop()
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.verify(raw)

    def test_interior_pending_reset_or_exception_cannot_hide_in_valid_aggregate_counts(self):
        for field, value in (("pending_reads", 1), ("reset_generation", 100), ("ticks", 0)):
            raw = self.raw()
            raw[4]["runs"][16]["after"][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.verify(raw)
        raw = self.raw()
        raw[4]["runs"][16]["exception"] = True
        with self.assertRaises(ValueError):
            self.verify(raw)

    def test_pending_queries_flushes_and_complete_destruction_are_required(self):
        for kind in ("reads", "cache_flush_reads", "destruction", "trace_overflow"):
            raw = self.raw()
            if kind in ("reads", "cache_flush_reads"):
                raw[4][kind][16]["pending_after"] = 1
            elif kind == "destruction":
                raw[4][kind]["completed"] = False
            else:
                raw[4][kind] = True
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                self.verify(raw)

    def test_expected_loaded_library_paths_are_independent_and_exact(self):
        raw = self.raw()
        for name in EXPECTED_LIBRARIES:
            changed = dict(EXPECTED_LIBRARIES)
            changed[name] += ".substitute"
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, "library"):
                self.verify(raw, expected_libraries=changed)

    def test_all_historical_claims_stay_false_in_each_new_witness(self):
        for index, name, value in itertools.product((3, 4), preflight.FALSE_CLAIMS, (True, 0)):
            raw = self.raw()
            raw[index][name] = value
            with self.subTest(index=index, name=name, value=value), self.assertRaises(ValueError):
                self.verify(raw)


if __name__ == "__main__":
    unittest.main()

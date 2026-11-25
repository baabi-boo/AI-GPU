# SPDX-License-Identifier: Apache-2.0
"""Successful producer compatibility and adversarial inert event reconciliation."""

from copy import deepcopy
import hashlib
import io
import json
import unittest
from unittest import mock

import governance_replay_events as replay
import governance_run as producer


def _case(identity, body=None):
    class Case(unittest.TestCase):
        def id(self):
            return identity

        def runTest(self):
            if body is not None:
                body(self)

    return Case()


def _encode(records):
    return b"".join((json.dumps(record, sort_keys=True) + "\n").encode("utf-8")
                    for record in records)


def _digest(identities):
    return hashlib.sha256("".join(identity + "\n" for identity in identities).encode("utf-8")).hexdigest()


class GovernanceReplayEventsTests(unittest.TestCase):
    def setUp(self):
        self.discovered, self.records, self.execution = self.produce()

    @staticmethod
    def produce(body=None, identities=None):
        identities = identities or ["test_fixture.Case.test_first", "test_fixture.Case.test_second"]
        records = []
        result = producer.run_suite(
            unittest.TestSuite(_case(identity, body) for identity in identities),
            stream=io.StringIO(), event_sink=records.append)
        discovered = {
            "schema_version": 1, "scope": producer.SCOPE, "discovery": dict(producer.DISCOVERY),
            "test_ids": identities, "count": len(identities), "sha256": _digest(identities),
        }
        return discovered, records, result.summary

    def run_replay(self, *, discovered=None, records=None, raw=None, execution=None):
        if raw is None:
            raw = _encode(self.records if records is None else records)
        return replay.reconcile(
            self.discovered if discovered is None else discovered, raw,
            self.execution if execution is None else execution)

    def reject(self, *, message=None, **options):
        with self.assertRaisesRegex(replay.ReplayEventsError, message or "."):
            self.run_replay(**options)

    @staticmethod
    def resequence(records):
        for index, record in enumerate(records, 1):
            record["sequence"] = index
            record["elapsed_seconds"] = 0
        return records

    def test_real_producer_success_derives_every_execution_field(self):
        self.assertEqual(self.run_replay(), self.execution)
        for name in ("MAX_TESTS", "MAX_ID_BYTES", "MAX_RECORD_BYTES", "MAX_EVENTS", "SCOPE", "DISCOVERY"):
            self.assertEqual(getattr(replay, name), getattr(producer, name))

    def test_replay_does_not_mutate_or_alias_the_retained_summary(self):
        before = deepcopy((self.discovered, self.records, self.execution))
        derived = self.run_replay()
        derived["outcome_counts"]["success"] = 0
        derived["missing_started_ids"].append("injected")
        self.assertEqual((self.discovered, self.records, self.execution), before)

    def test_replay_neither_discovers_nor_executes_tests(self):
        with mock.patch.object(producer, "run_suite", side_effect=AssertionError("execution")), \
                mock.patch.object(unittest.TestLoader, "discover", side_effect=AssertionError("discovery")):
            self.assertEqual(self.run_replay()["tests_run"], 2)

    def test_repeated_nested_unicode_subtests_are_valid(self):
        def body(case):
            for label in ("é", "é"):
                with case.subTest(label=label):
                    with case.subTest(inner="λ"):
                        pass

        discovered, records, execution = self.produce(body)
        self.assertEqual(replay.reconcile(discovered, _encode(records), execution), execution)
        self.assertEqual(execution["subtest_counts"], {"success": 8})

    def test_full_hash_bound_long_subtest_labels_and_duplicates_are_valid(self):
        def body(case):
            for label in ("é" * 4096, "é" * 4096, "z" * 4097):
                with case.subTest(label=label):
                    pass

        discovered, records, execution = self.produce(body)
        hashes = [record for record in records if record["event"] == "subtest_outcome"]
        self.assertTrue(all(record["subtest_id_encoding"] == "sha256" for record in hashes))
        self.assertEqual(hashes[0]["subtest_id"], hashes[1]["subtest_id"])
        self.assertEqual(replay.reconcile(discovered, _encode(records), execution), execution)

    def test_maximum_parent_and_subtest_utf8_boundaries_match_the_producer(self):
        def body(case):
            with case.subTest(label="é"):
                pass

        discovered, records, execution = self.produce(body, ["x" * producer.MAX_ID_BYTES])
        self.assertEqual(replay.reconcile(discovered, _encode(records), execution), execution)
        identity = "test_fixture.Case.test_boundary"
        available = producer.MAX_ID_BYTES - len((identity + " (label='')").encode("utf-8"))
        label = "é" * (available // 2) + "x" * (available % 2)

        def boundary(case):
            for value in (label, label + "é"):
                with case.subTest(label=value):
                    pass

        discovered, records, execution = self.produce(boundary, [identity])
        self.assertNotIn("subtest_id_encoding", records[1])
        self.assertIn("subtest_id_encoding", records[2])
        self.assertEqual(replay.reconcile(discovered, _encode(records), execution), execution)

    def test_empty_duplicate_and_failed_loader_discovery_cannot_qualify(self):
        for identities in ([], [self.discovered["test_ids"][0]] * 2,
                           ["unittest.loader._FailedTest.test_bad"]):
            with self.subTest(identities=identities):
                discovered = deepcopy(self.discovered)
                discovered.update(test_ids=identities, count=len(identities), sha256=_digest(identities))
                self.reject(discovered=discovered)

    def test_identity_types_encoding_and_byte_limits_are_checked(self):
        for identity in (None, True, 7, [], {}, "", "\ud800", "é" * 2049):
            with self.subTest(identity_type=type(identity).__name__):
                discovered = deepcopy(self.discovered)
                discovered["test_ids"][0] = identity
                self.reject(discovered=discovered)
        for identities in (None, {}, tuple(self.discovered["test_ids"]), "test_fixture.Case.test_first"):
            with self.subTest(container=type(identities).__name__):
                discovered = deepcopy(self.discovered)
                discovered["test_ids"] = identities
                self.reject(discovered=discovered)

    def test_discovery_schema_and_digest_cannot_be_substituted(self):
        mutations = {
            "schema_version": (True, 2, "1"), "scope": ("native", None),
            "count": (True, 2.0, 1, 3), "sha256": ("0" * 64, None),
            "discovery": ({"start_directory": "ci/project", "pattern": "test_one.py"},
                          {"start_directory": "elsewhere", "pattern": "test_*.py"}),
        }
        for field, values in mutations.items():
            for value in values:
                with self.subTest(field=field, value=value):
                    discovered = deepcopy(self.discovered)
                    discovered[field] = value
                    self.reject(discovered=discovered)
        for field in self.discovered:
            with self.subTest(missing=field):
                discovered = deepcopy(self.discovered)
                del discovered[field]
                self.reject(discovered=discovered)
        self.reject(discovered={**self.discovered, "extra": True})

    def test_reordered_discovery_is_rejected_even_with_a_recomputed_digest(self):
        discovered = deepcopy(self.discovered)
        discovered["test_ids"].reverse()
        discovered["sha256"] = _digest(discovered["test_ids"])
        execution = deepcopy(self.execution)
        execution["discovered_sha256"] = discovered["sha256"]
        self.reject(discovered=discovered, execution=execution, message="discovered test order")

    def test_evidence_test_and_event_limits_are_inclusive(self):
        raw = _encode(self.records)
        with mock.patch.object(replay, "MAX_RECORD_BYTES", len(raw)):
            self.assertEqual(self.run_replay(raw=raw), self.execution)
        with mock.patch.object(replay, "MAX_RECORD_BYTES", len(raw) - 1):
            self.reject(raw=raw, message="byte limit")
        with mock.patch.object(replay, "MAX_TESTS", 1):
            self.reject(message="bounded list")
        with mock.patch.object(replay, "MAX_EVENTS", len(self.records) - 1):
            self.reject(message="event count limit")
        max_line = max(map(len, raw.splitlines(keepends=True)))
        with mock.patch.object(replay, "MAX_EVENT_LINE_BYTES", max_line):
            self.assertEqual(self.run_replay(raw=raw), self.execution)
        with mock.patch.object(replay, "MAX_EVENT_LINE_BYTES", max_line - 1):
            self.reject(raw=raw, message="line byte limit")

    def test_nonbyte_empty_truncated_and_malformed_lines_are_rejected(self):
        raw = _encode(self.records)
        variants = ("", bytearray(raw), None, b"", raw[:-1], raw[:-5] + b"\n",
                    b"\n" + raw, raw + b"\n", b"\xff\n", b"\xef\xbb\xbf" + raw,
                    b"[]\n", b"null\n", b"true\n", b"{} {}\n",
                    b'{"a": {"nested": 1, "nested": 2}}\n',
                    b'{"sequence": 1, "sequence": 1}\n',
                    b'{"sequence": 1, "sequ\\u0065nce": 1}\n',
                    b'[' * 2000 + b'0' + b']' * 2000 + b'\n')
        for index, value in enumerate(variants):
            with self.subTest(variant=index), self.assertRaises(replay.ReplayEventsError):
                replay.reconcile(self.discovered, value, self.execution)

    def test_sequence_must_be_a_contiguous_integer_not_a_boolean(self):
        for index, value in ((0, True), (0, 1.0), (0, 0), (0, -1), (0, "1"),
                             (1, 1), (1, 3), (1, None)):
            with self.subTest(index=index, value=value):
                records = deepcopy(self.records)
                records[index]["sequence"] = value
                self.reject(records=records, message="sequence")

    def test_event_clocks_are_finite_nonnegative_and_nondecreasing(self):
        for value in (True, False, "0", None, -1, float("nan"), float("inf"), float("-inf"), 10**400):
            with self.subTest(value=str(value)):
                records = deepcopy(self.records)
                records[0]["elapsed_seconds"] = value
                self.reject(records=records)
        records = deepcopy(self.records)
        records[0]["elapsed_seconds"], records[1]["elapsed_seconds"] = 2, 1
        self.reject(records=records, message="decreasing")
        raw = _encode(self.records)
        start = raw.index(b'"elapsed_seconds": ') + len(b'"elapsed_seconds": ')
        end = raw.index(b",", start)
        self.reject(raw=raw[:start] + b"1e9999" + raw[end:], message="finite")

    def test_equal_rounded_clocks_are_allowed(self):
        records = self.resequence(deepcopy(self.records))
        execution = {**self.execution, "duration_seconds": 0}
        self.assertEqual(self.run_replay(records=records, execution=execution), execution)

    def test_final_duration_cannot_be_nonfinite_negative_boolean_or_before_events(self):
        for value in (True, False, None, "1", -1, float("nan"), float("inf"), float("-inf"), 10**400):
            with self.subTest(value=str(value)):
                self.reject(execution={**self.execution, "duration_seconds": value})
        self.reject(execution={**self.execution, "duration_seconds": 0}, message="final event clock")

    def test_overlapping_duplicate_reordered_and_unexpected_starts_are_rejected(self):
        variants = [
            [self.records[0], self.records[3], *self.records[1:]],
            [*self.records[:3], *self.records[:3], *self.records[3:]],
            [*self.records[3:], *self.records[:3]],
        ]
        unexpected = deepcopy(self.records)
        unexpected[0]["test_id"] = "test_fixture.Case.test_unknown"
        variants.append(unexpected)
        for index, records in enumerate(variants):
            with self.subTest(variant=index):
                self.reject(records=self.resequence(deepcopy(records)))

    def test_missing_duplicate_or_misplaced_outcomes_and_stops_are_rejected(self):
        variants = [
            [self.records[0], *self.records[2:]],
            [*self.records[:2], self.records[1], *self.records[2:]],
            self.records[:-1], self.records[:3], self.records[1:],
            [*self.records[:3], self.records[2], *self.records[3:]],
            [self.records[0], self.records[2], self.records[1], *self.records[3:]],
        ]
        for index, records in enumerate(variants):
            with self.subTest(variant=index):
                self.reject(records=self.resequence(deepcopy(records)))
        for index in (1, 2):
            records = deepcopy(self.records)
            records[index]["test_id"] = self.discovered["test_ids"][1]
            self.reject(records=records, message="active test")

    def test_every_nonsuccessful_outcome_is_rejected_despite_success_claims(self):
        for outcome in ("failure", "error", "skip", "expected_failure", "unexpected_success", "", None, True):
            with self.subTest(outcome=outcome):
                records = deepcopy(self.records)
                records[1]["outcome"] = outcome
                self.reject(records=records, message="outcome")
                subtest = {**records[1], "event": "subtest_outcome",
                           "subtest_id": self.discovered["test_ids"][0] + " (part='bad')"}
                records = [self.records[0], subtest, *self.records[1:]]
                self.reject(records=self.resequence(deepcopy(records)), message="outcome")

    def test_fixture_outcomes_and_unknown_event_kinds_never_qualify(self):
        for kind in ("fixture_outcome", "test_retry", "", None, True, []):
            with self.subTest(kind=kind):
                record = {"sequence": 1, "elapsed_seconds": 0, "event": kind,
                          "fixture_id": "tearDownClass (test_fixture.Case)", "outcome": "success"}
                self.reject(records=self.resequence([record, *deepcopy(self.records)]))

    def subtest_fixture(self, hashed=False):
        def body(case):
            with case.subTest(label="x" * 4097 if hashed else "good"):
                pass

        return self.produce(body, [self.discovered["test_ids"][0]])

    def test_subtests_must_be_inside_the_named_parents_body(self):
        discovered, original, execution = self.subtest_fixture()
        for records in ([original[1], original[0], *original[2:]],
                        [original[0], original[2], original[1], original[3]],
                        [original[0], *original[2:], original[1]]):
            self.reject(discovered=discovered, records=self.resequence(deepcopy(records)), execution=execution)
        records = deepcopy(original)
        records[1]["test_id"] = self.discovered["test_ids"][1]
        self.reject(discovered=discovered, records=records, execution=execution, message="active test")

    def test_short_subtest_identity_and_parent_binding_are_checked(self):
        discovered, original, execution = self.subtest_fixture()
        for value in (None, True, "", "other.Case.test_parent (label='good')",
                      discovered["test_ids"][0] + " ", "x" * 4097, "\ud800"):
            with self.subTest(identity_type=type(value).__name__):
                records = deepcopy(original)
                records[1]["subtest_id"] = value
                self.reject(discovered=discovered, records=records, execution=execution)

    def test_hash_bound_subtest_metadata_must_be_complete_and_well_typed(self):
        discovered, original, execution = self.subtest_fixture(hashed=True)
        mutations = {
            "subtest_id": ("sha256:" + "A" * 64, "sha256:" + "0" * 63, "x" * 71),
            "subtest_id_encoding": ("base64", None),
            "subtest_id_original_encoding": ("ascii", None),
            "subtest_id_original_bytes": (True, 4096, 0, -1, 4097.0, "4097", None),
        }
        for field, values in mutations.items():
            for value in values:
                with self.subTest(field=field, value=value):
                    records = deepcopy(original)
                    records[1][field] = value
                    self.reject(discovered=discovered, records=records, execution=execution)
            records = deepcopy(original)
            del records[1][field]
            self.reject(discovered=discovered, records=records, execution=execution)
        records = deepcopy(original)
        for field in tuple(records[1]):
            if field.startswith("subtest_id_"):
                del records[1][field]
        self.reject(discovered=discovered, records=records, execution=execution)

    def test_event_schema_rejects_missing_and_unknown_fields(self):
        for index in range(len(self.records)):
            for field in self.records[index]:
                with self.subTest(index=index, missing=field):
                    records = deepcopy(self.records)
                    del records[index][field]
                    self.reject(records=records)
            records = deepcopy(self.records)
            records[index]["extra"] = "ignored success claim"
            self.reject(records=records)
        discovered, original, execution = self.subtest_fixture()
        records = deepcopy(original)
        records[1]["subtest_id_encoding"] = "sha256"
        self.reject(discovered=discovered, records=records, execution=execution)

    def test_execution_flags_are_checked_but_cannot_replace_replayed_evidence(self):
        for field in ("strict_success", "execution_completed", "coverage_complete", "order_matches", "counts_match"):
            for value in (False, 1, "true", None):
                with self.subTest(field=field, value=value):
                    self.reject(execution={**self.execution, field: value}, message=field)

    def test_all_execution_statistics_and_empty_arrays_must_match(self):
        for field, original in self.execution.items():
            if field == "duration_seconds":
                continue
            values = ([original + 1, float(original), True] if type(original) is int else
                      [{"success": 0}, {"success": True}, {"success": 2.0}] if type(original) is dict else
                      [["unreconciled"], {}] if type(original) is list else
                      [False, ""] if original is None else
                      [original + "x"] if type(original) is str else [])
            for value in values:
                with self.subTest(field=field, value=value):
                    self.reject(execution={**self.execution, field: value}, message=field)
        for field in self.execution:
            with self.subTest(missing=field):
                execution = deepcopy(self.execution)
                del execution[field]
                self.reject(execution=execution)
        self.reject(execution={**self.execution, "extra": True})
        self.reject(execution={**self.execution, "fixture_counts": {"error": 0}})
        self.reject(execution={**self.execution, "subtest_counts": {"success": 0}})

    def test_subtest_counts_are_derived_including_repeated_labels(self):
        discovered, records, execution = self.subtest_fixture()
        for counts in ({}, {"success": 0}, {"success": 2}, {"success": True}, {"success": 1.0},
                       {"success": 1, "skip": 0}):
            with self.subTest(counts=counts):
                self.reject(discovered=discovered, records=records,
                            execution={**execution, "subtest_counts": counts})


if __name__ == "__main__":
    unittest.main()

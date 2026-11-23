# SPDX-License-Identifier: Apache-2.0
"""Regress the observed native-report intake overflow without running native code."""

from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import baseline_packet_io as packet
import p06_dependency_contract as contract
import p06_dependency_local_execute as execute
import p06_pending_probe as probe
import test_p06_dependency_local_execute as execution_fixture


class ManagedReportJSONReviewTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="p06-managed-json-review-")
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name) / "managed.json"
        self.large = {"rows": ["v"] * 125000}
        self.body = json.dumps(self.large, separators=(",", ":")).encode()

    def test_generic_default_is_unchanged_and_explicit_bound_admits_larger_object(self):
        self.assertEqual(packet.MAX_JSON_TOKENS, 250000)
        self.assertEqual(contract.MANAGED_REPORT_MAX_JSON_TOKENS, 500000)
        with self.assertRaisesRegex(ValueError, "structure exceeds"):
            packet.load_json_bytes(self.body)
        self.assertEqual(packet.load_json_bytes(self.body,
            max_tokens=contract.MANAGED_REPORT_MAX_JSON_TOKENS), self.large)
        with self.assertRaisesRegex(ValueError, "structure exceeds"):
            packet.load_json_bytes(self.body)

    def test_explicit_budget_is_bounded_and_enforced_at_its_edge(self):
        for value in (True, -1, 500001, 500000.0, "500000", None):
            with self.subTest(value=value), self.assertRaises(ValueError):
                packet.load_json_bytes(b"{}", max_tokens=value)
        self.assertEqual(packet.load_json_bytes(b'{"a":1}', max_tokens=3), {"a": 1})
        with self.assertRaisesRegex(ValueError, "structure exceeds"):
            packet.load_json_bytes(b'{"a":1}', max_tokens=2)
        body = b'{"rows":[' + b'"v",' * 249998 + b'"v"]}'
        with self.assertRaisesRegex(ValueError, "structure exceeds"):
            packet.load_json_bytes(body, max_tokens=contract.MANAGED_REPORT_MAX_JSON_TOKENS)

    def test_expanded_bound_preserves_structural_numeric_and_utf8_guards(self):
        invalid = [b'[]', b'{"a":1,"a":2}', b'{"a":NaN}', b'{"a":Infinity}',
            b'{"a":1e999}', b'{"a":' + b'1' * 1025 + b'}',
            b'{"a":' + b'[' * 64 + b'0' + b']' * 64 + b'}',
            b'{"a":"\xff"}', b'{"a":1} trailing']
        for body in invalid:
            with self.subTest(body=body[:50]), self.assertRaises(ValueError):
                packet.load_json_bytes(body, max_tokens=contract.MANAGED_REPORT_MAX_JSON_TOKENS)

    def test_only_explicit_pinned_control_intake_uses_expanded_budget(self):
        self.path.write_bytes(self.body)
        with self.assertRaisesRegex(ValueError, "structure exceeds"):
            probe.managed_json(self.path)
        self.assertEqual(probe.managed_json(self.path,
            dependency_receipt_sha256="a" * 64), self.large)
        with self.assertRaisesRegex(ValueError, "structure exceeds"):
            probe.bounded_json(self.path)

    def test_malformed_pin_is_rejected_before_control_file_read(self):
        with mock.patch.object(probe, "bounded_json", side_effect=AssertionError("unexpected read")):
            for pin in ("", "a" * 63, "A" * 64, True, 17):
                with self.subTest(pin=pin), self.assertRaisesRegex(ValueError, "exact SHA256"):
                    probe.managed_json(self.path, dependency_receipt_sha256=pin)

    def test_control_intake_keeps_byte_and_container_bounds(self):
        self.path.write_bytes(b"[]")
        with self.assertRaisesRegex(ValueError, "container type"):
            probe.managed_json(self.path, dependency_receipt_sha256="a" * 64)
        self.path.write_bytes(self.body)
        with mock.patch.object(probe, "MAX_JSON_BYTES", len(self.body) - 1):
            with self.assertRaisesRegex(ValueError, "byte bound"):
                probe.managed_json(self.path, dependency_receipt_sha256="a" * 64)

    def route(self, name, mutate=None):
        fixture = execution_fixture.LocalExecutionTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)

        def change(stage, document, argv):
            if stage == name:
                document["review_structure"] = deepcopy(self.large["rows"])
                if mutate is not None:
                    mutate(document)
            return 0

        fixture.change = change
        return fixture.run_route(), fixture.observed

    def test_large_native_report_proceeds_through_both_separate_control_stages(self):
        result, observed = self.route("native-lifetime")
        self.assertEqual(result["outcome"], "pass")
        self.assertEqual([row["id"] for row in observed], list(execute.STAGE_NAMES))
        self.assertEqual(result["native_execution"], "run")

    def test_other_local_child_reports_keep_generic_budget(self):
        result, observed = self.route("dependency-build")
        self.assertEqual(result["outcome"], "fail")
        self.assertIn("structure exceeds", result["reason"])
        self.assertEqual([row["id"] for row in observed], ["preparation", "dependency-build"])

    def test_large_native_wrong_contract_is_still_rejected(self):
        result, observed = self.route("native-lifetime",
            lambda document: document.update(contract_id="unreviewed-managed-contract"))
        self.assertEqual(result["outcome"], "fail")
        self.assertIn("matching non-acceptance report", result["reason"])
        self.assertEqual(len(observed), 3)

    def test_large_native_wrong_population_is_still_rejected(self):
        result, observed = self.route("native-lifetime",
            lambda document: document["completed_counts"].update(launches=131))
        self.assertEqual(result["outcome"], "fail")
        self.assertIn("fixed four-process", result["reason"])
        self.assertEqual(len(observed), 3)


if __name__ == "__main__":
    unittest.main()

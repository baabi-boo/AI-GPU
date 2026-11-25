# SPDX-License-Identifier: Apache-2.0
"""Whole-packet joins and fail-closed CLI checks using a genuine miniature run."""

from copy import deepcopy
import hashlib
import io
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest import mock
import zipfile

import governance_replay as replay
import governance_run as producer
from test_governance_replay_records import REVISION, records_fixture


def _encode(value):
    return (json.dumps(value, sort_keys=True, indent=2) + "\n").encode("utf-8")


def packet_fixture():
    """Produce actual serial events and a unittest trailer, without external tools."""
    started, summary, environment = records_fixture()
    identities = ["test_fixture.Case.test_first", "test_fixture.Case.test_second"]

    def case(identity):
        class Case(unittest.TestCase):
            def id(self):
                return identity

            def runTest(self):
                with self.subTest(value="fixture"):
                    pass
        return Case()

    events, log = [], io.StringIO()
    result = producer.run_suite(unittest.TestSuite(case(identity) for identity in identities),
                                stream=log, event_sink=events.append)
    summary["execution"] = result.summary
    raw_events = b"".join((json.dumps(value, sort_keys=True) + "\n").encode() for value in events)
    raw_log = log.getvalue().encode()
    summary["log"]["bytes"] = len(raw_log)
    summary["event_bytes"] = len(raw_events)
    discovered = {"schema_version": 1, "scope": producer.SCOPE, "discovery": dict(producer.DISCOVERY),
                  "test_ids": identities, "count": len(identities),
                  "sha256": hashlib.sha256("".join(value + "\n" for value in identities).encode()).hexdigest()}
    ending = ("Strict governance PASSED: " + summary["command"][3] + "/summary.json\n").encode()
    members = {
        "logs/cmake-install.log": b"Installing collected packages: cmake\nSuccessfully installed cmake-3.22.6\n",
        "logs/cmake-requirements.txt": replay.CMAKE_REQUIREMENT,
        "logs/cmake-version.log": b"cmake version 3.22.6\n",
        "logs/environment.log": _encode({"interpreter": environment["interpreter"],
                                        "environment_receipt": environment["output_dir"] + "/environment.json"}),
        "logs/governance.log": raw_log + ending,
        "logs/source-revision.txt": (REVISION + "\n").encode(),
        "environment/environment.json": _encode(environment),
        "run/discovered.json": _encode(discovered), "run/events.jsonl": raw_events,
        "run/started.json": _encode(started), "run/summary.json": _encode(summary),
        "run/unittest.log": raw_log,
    }
    source = summary["source_before"]
    binding = {"head": REVISION, "tree": source["tree"], "object_format": "sha1",
               "tracked_sha256": source["tracked_sha256"], "tracked_count": source["tracked_count"],
               "tracked_bytes": source["tracked_bytes"],
               "gitlinks": [{"path": row["path"], "oid": row["pinned_oid"]} for row in source["gitlinks"]]}
    return members, binding, identities


class GovernanceReplayTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="governance-replay-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.archive = self.root / "packet.zip"
        self.source = self.root / "trusted"
        self.source.mkdir()
        self.members, self.binding, self.identities = packet_fixture()
        self.original = deepcopy(self.members)
        self.source_mock = self.enterContext(mock.patch.object(
            replay, "_source_binding", side_effect=lambda *_: deepcopy(self.binding)))
        self.collect_mock = self.enterContext(mock.patch.object(replay, "_collect", return_value=self.identities))

    def save(self):
        with zipfile.ZipFile(self.archive, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for name, raw in self.members.items():
                archive.writestr(name, raw)
        return hashlib.sha256(self.archive.read_bytes()).hexdigest()

    def verify(self, **kwargs):
        options = {"revision": REVISION, "source_dir": self.source, "expected_sha256": self.save(), **kwargs}
        return replay.verify_archive(self.archive, **options)

    def change_json(self, member, change):
        record = json.loads(self.members[member])
        change(record)
        self.members[member] = _encode(record)

    def reject(self):
        with self.assertRaises(ValueError):
            self.verify()

    def cli(self, *extra, args=None):
        argv = args if args is not None else ["--archive", str(self.archive), "--expected-revision", REVISION,
                "--source-dir", str(self.source), "--expected-sha256", self.save(), *extra]
        stdout, stderr = io.StringIO(), io.StringIO()
        with mock.patch.object(replay.sys, "stdout", stdout), mock.patch.object(replay.sys, "stderr", stderr):
            code = replay.main(argv)
        return code, stdout.getvalue(), stderr.getvalue()

    def test_genuine_miniature_packet_is_fully_reconciled(self):
        receipt = self.verify()
        self.assertTrue(receipt["independent_packet_replay"])
        self.assertEqual((receipt["canonical_tests"], receipt["successful_subtests"], receipt["events"]), (2, 2, 8))
        self.assertEqual(receipt["archive"]["sha256"], hashlib.sha256(self.archive.read_bytes()).hexdigest())
        self.assertEqual(receipt["source_tree"], self.binding["tree"])
        self.assertEqual(self.source_mock.call_count, 3)
        self.collect_mock.assert_called_once_with(self.source, REVISION)
        for field in ("provider_authenticated", "retained_code_executed", "tests_executed_by_replay",
                      "native_acceptance", "phase_acceptance", "performance_acceptance"):
            self.assertIs(receipt[field], False)
        serialized = json.dumps(receipt)
        self.assertNotIn("/recorded/", serialized)
        self.assertNotIn(str(self.root), serialized)
        self.assertLess(len(serialized), 8192)

    def test_missing_and_additional_members_cannot_be_ignored(self):
        for name in self.original:
            with self.subTest(missing=name):
                self.members = deepcopy(self.original)
                del self.members[name]
                self.reject()
        self.members = {**self.original, "extra.py": b"raise AssertionError('retained code')\n"}
        self.reject()
        self.collect_mock.assert_not_called()

    def test_every_member_has_its_specific_byte_bound(self):
        for name, raw in self.original.items():
            with self.subTest(member=name):
                with mock.patch.dict(replay.MEMBER_LIMITS, {name: len(raw) - 1}):
                    self.reject()
        self.source_mock.assert_not_called()

    def test_empty_members_cannot_form_a_complete_packet(self):
        for name in self.original:
            with self.subTest(member=name):
                self.members = {**self.original, name: b""}
                self.reject()

    def test_expected_digest_and_full_revision_are_mandatory(self):
        for value in (None, "", "A" * 64, "a" * 63, True):
            with self.subTest(digest=value):
                with self.assertRaises(ValueError):
                    self.verify(expected_sha256=value)
        with self.assertRaises(ValueError):
            self.verify(expected_sha256="0" * 64)
        for value in (None, "a" * 8, "A" * 40, True, "a" * 41):
            with self.subTest(revision=value):
                with self.assertRaises(ValueError):
                    self.verify(revision=value)
        self.source_mock.assert_not_called()

    def test_source_revision_text_must_be_exact(self):
        for raw in ((REVISION + " ").encode(), (REVISION + "\n\n").encode(), ("b" * 40 + "\n").encode()):
            with self.subTest(raw=raw):
                self.members["logs/source-revision.txt"] = raw
                self.reject()

    def test_json_ambiguity_nonfinite_overflow_and_invalid_types_are_rejected(self):
        json_names = [name for name in self.original if name.endswith(".json")] + ["logs/environment.log"]
        for name in json_names:
            for raw in (b'{"x":1,"x":1}\n', b'{"x":NaN}\n', b'{"x":Infinity}\n',
                        b'{"x":1e99999}\n', b'[]\n', b'null\n', b'\xff', b'{"x":'):
                with self.subTest(member=name, raw=raw):
                    self.members = {**self.original, name: raw}
                    self.reject()
        self.collect_mock.assert_not_called()

    def test_boolean_counts_and_false_completion_are_rejected(self):
        mutations = [("run/discovered.json", lambda record: record.update(count=True)),
                     ("run/summary.json", lambda record: record["log"].update(bytes=True)),
                     ("run/summary.json", lambda record: record["execution"].update(tests_run=True)),
                     ("run/summary.json", lambda record: record.update(governance_passed=False)),
                     ("run/summary.json", lambda record: record["execution"].update(strict_success=False))]
        for member, change in mutations:
            with self.subTest(member=member, change=change):
                self.members = deepcopy(self.original)
                self.change_json(member, change)
                self.reject()
        self.collect_mock.assert_not_called()

    def test_all_semantic_source_identities_must_match(self):
        original = deepcopy(self.binding)
        for key, value in (("head", "d" * 40), ("tree", "d" * 40), ("object_format", "sha256"),
                           ("tracked_sha256", "d" * 64), ("tracked_count", True), ("tracked_bytes", 99),
                           ("gitlinks", [])):
            with self.subTest(field=key):
                self.binding = {**original, key: value}
                self.reject()
        self.collect_mock.assert_not_called()

    def test_host_paths_and_submodule_initialized_state_are_not_local_identities(self):
        for member in ("run/started.json", "run/summary.json"):
            def initialize(record):
                for key in ("source_before", "source_after"):
                    if key in record:
                        record[key]["gitlinks"][0]["status"] = " "
                        record[key]["submodules"] = " " + "d" * 40 + " third_party/example (heads/main)\n"
            self.change_json(member, initialize)
        self.assertTrue(self.verify()["independent_packet_replay"])
        self.assertNotEqual(str(self.source), json.loads(self.members["run/summary.json"])["source_root"])

    def test_collection_is_exact_and_ordered(self):
        for identities in (self.identities[:1], self.identities[::-1], self.identities * 2,
                           ["different.Case.test"] * 2, tuple(self.identities)):
            with self.subTest(identities=identities):
                self.collect_mock.return_value = identities
                self.reject()

    def test_source_is_rechecked_after_collection_and_replay(self):
        changed = {**self.binding, "tree": "e" * 40}
        for observations in ([self.binding, changed], [self.binding, self.binding, changed]):
            with self.subTest(observations=len(observations)):
                self.source_mock.side_effect = deepcopy(observations)
                self.reject()

    def test_source_or_collector_failure_cannot_emit_a_receipt(self):
        for helper in (self.source_mock, self.collect_mock):
            with self.subTest(helper=helper):
                original = helper.side_effect
                helper.side_effect = ValueError("secret retained URL and path")
                code, stdout, stderr = self.cli()
                self.assertEqual(code, 1)
                self.assertEqual(stdout, "")
                self.assertNotIn("secret", stderr)
                helper.side_effect = original

    def test_event_bytes_and_complete_event_population_are_joined(self):
        mutations = [("run/summary.json", lambda record: record.update(event_bytes=1)),
                     ("run/summary.json", lambda record: record["execution"].update(event_count=1))]
        for name, change in mutations:
            with self.subTest(name=name, change=change):
                self.members = deepcopy(self.original)
                self.change_json(name, change)
                self.reject()
        self.members = deepcopy(self.original)
        self.members["run/events.jsonl"] = b"\n".join(self.members["run/events.jsonl"].splitlines()[:-1]) + b"\n"
        self.reject()

    def test_inner_log_byte_count_and_truncation_are_bound(self):
        for change in (lambda record: record["log"].update(bytes=1),
                       lambda record: record["log"].update(truncated=True)):
            self.members = deepcopy(self.original)
            self.change_json("run/summary.json", change)
            self.reject()

    def test_ok_text_cannot_replace_successful_unittest_completion(self):
        for raw in (b"OK\n", b"\n" + b"-" * 70 + b"\nRan 1 test in 0.000s\n\nOK\n",
                    self.original["run/unittest.log"][:-1],
                    self.original["run/unittest.log"].replace(b"\nOK\n", b"\nOK (skipped=1)\n")):
            with self.subTest(raw=raw[-100:]):
                self.members = deepcopy(self.original)
                self.members["run/unittest.log"] = raw
                ending = self.original["logs/governance.log"][len(self.original["run/unittest.log"]):]
                self.members["logs/governance.log"] = raw + ending
                self.change_json("run/summary.json", lambda record: record["log"].update(bytes=len(raw)))
                self.reject()

    def test_outer_log_requires_exact_success_tail_and_internal_byte_order(self):
        outer = self.original["logs/governance.log"]
        first_line = outer.index(b"\n") + 1
        variants = [outer[:-1], outer + b"later output\n", outer.replace(b"PASSED:", b"FAILED:"),
                    outer.replace(b"/run/summary.json", b"/wrong/summary.json"),
                    b"z" * first_line + outer[first_line:]]
        for raw in variants:
            with self.subTest(tail=raw[-100:]):
                self.members = {**self.original, "logs/governance.log": raw}
                self.reject()

    def test_outer_native_diagnostics_may_interrupt_python_log_lines(self):
        self.members["logs/governance.log"] = self.members["logs/governance.log"].replace(
            b" ... ok\n", b" ... expected compiler error: invalid syntax\nchild diagnostic\nok\n", 1)
        self.assertTrue(self.verify()["independent_packet_replay"])

    def test_preparation_logs_and_pinned_requirement_are_joined(self):
        variants = {"logs/cmake-requirements.txt": replay.CMAKE_REQUIREMENT.replace(b"a235", b"b235"),
                    "logs/cmake-version.log": b"cmake version 3.25.0\n",
                    "logs/cmake-install.log": b"install started\n",
                    "logs/environment.log": _encode({"environment_receipt": "/wrong/environment.json",
                                                       "interpreter": "/wrong/python"})}
        for name, raw in variants.items():
            with self.subTest(member=name):
                self.members = {**self.original, name: raw}
                self.reject()

    def test_retained_text_is_not_executed_and_recorded_paths_are_not_opened(self):
        self.members["logs/cmake-install.log"] = b"__import__('subprocess').Popen(['untrusted'])\n" + self.members["logs/cmake-install.log"]
        with mock.patch("subprocess.Popen", side_effect=AssertionError("retained code execution")):
            self.assertTrue(self.verify()["independent_packet_replay"])
        self.collect_mock.assert_called_once_with(self.source, REVISION)

    def test_cli_requires_all_trust_arguments_and_has_no_bypass_flags(self):
        for args in ([], ["--archive", str(self.archive)], ["--skip-source-binding"], ["--expected-sha", "a" * 64]):
            with self.subTest(args=args):
                code, stdout, stderr = self.cli(args=args)
                self.assertEqual((code, stdout), (1, ""))
                self.assertEqual(stderr, "governance replay failed\n")

    def test_cli_emits_only_bounded_scoped_json(self):
        code, stdout, stderr = self.cli()
        self.assertEqual((code, stderr), (0, ""))
        self.assertTrue(json.loads(stdout)["independent_packet_replay"])
        self.assertNotIn("/recorded/", stdout)
        self.assertLess(len(stdout), 8192)

    def test_cli_output_is_fresh_private_and_complete(self):
        output = self.root / "receipt.json"
        code, stdout, stderr = self.cli("--output", str(output))
        self.assertEqual((code, stderr), (0, ""))
        self.assertEqual(output.read_text(), stdout)
        self.assertEqual(stat.S_IMODE(output.stat().st_mode), 0o600)
        before = output.read_bytes()
        code, stdout, stderr = self.cli("--output", str(output))
        self.assertEqual((code, stdout), (1, ""))
        self.assertEqual(output.read_bytes(), before)

    def test_cli_output_refuses_symlinks_aliases_and_trusted_source(self):
        sentinel = self.root / "sentinel"
        sentinel.write_bytes(b"unchanged")
        leaf = self.root / "link"
        leaf.symlink_to(sentinel)
        alias = self.root / "alias"
        alias.symlink_to(self.root, target_is_directory=True)
        hard = self.root / "hard"
        os.link(sentinel, hard)
        outputs = [str(leaf), str(hard), str(alias / "receipt.json"), str(self.source / "receipt.json"),
                   str(self.root) + "/./receipt.json", str(self.root) + "//receipt.json", "relative.json"]
        for output in outputs:
            with self.subTest(output=output):
                code, stdout, stderr = self.cli("--output", output)
                self.assertEqual((code, stdout), (1, ""))
                self.assertNotIn(str(self.root), stderr)
        self.assertEqual(sentinel.read_bytes(), b"unchanged")
        self.assertFalse((self.root / "receipt.json").exists())

    def test_failed_write_removes_partial_output_without_success_json(self):
        output = self.root / "receipt.json"
        write = os.write
        calls = 0

        def fail_after_prefix(descriptor, data):
            nonlocal calls
            calls += 1
            if calls == 1:
                return write(descriptor, data[:3])
            raise OSError("sensitive filesystem failure")

        with mock.patch.object(replay.os, "write", side_effect=fail_after_prefix):
            code, stdout, stderr = self.cli("--output", str(output))
        self.assertEqual((code, stdout), (1, ""))
        self.assertFalse(output.exists())
        self.assertNotIn("sensitive", stderr)


if __name__ == "__main__":
    unittest.main()

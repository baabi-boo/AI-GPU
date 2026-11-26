# SPDX-License-Identifier: Apache-2.0
"""Real acquisition checkpoint faults with synthetic commands and no network work."""

from contextlib import contextmanager
from copy import deepcopy
import json
import unittest
from unittest import mock

import p06_qualified_warm_hosted as hosted
import p06_qualified_warm_inputs as inputs
import test_p06_qualified_warm_inputs as fixtures


@contextmanager
def _synthetic_acquisition():
    case = fixtures.QualifiedWarmInputAcquisitionTests()
    try:
        case.setUp()
        case.args.output_dir = case.root / "acquisition"
        yield case
    finally:
        case.doCleanups()


class CheckpointInputRecoveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixtures.QualifiedWarmInputAcquisitionTests.setUpClass()
        cls.addClassCleanup(fixtures.QualifiedWarmInputAcquisitionTests.doClassCleanups)

    def check_recovery(self, case, error_type, command=None):
        target = case.args.output_dir / inputs.RECEIPT_NAME
        temporary = target.with_name(target.name + ".tmp")
        stages = [{"id": "input-acquisition", "process_started": True, "cleanup_complete": True}]
        write_json, real_fsync = inputs.base._write_json, inputs.base.os.fsync
        fault = error_type("one-shot acquisition checkpoint fsync failure")
        injected, failures, following_writes, logs = [], [], [], {}

        def fail_fsync(descriptor):
            if not injected and temporary.exists():
                opened, pending = inputs.base.os.fstat(descriptor), temporary.lstat()
                if (opened.st_dev, opened.st_ino) == (pending.st_dev, pending.st_ino):
                    document = json.loads(temporary.read_bytes())
                    commands = document["commands"]
                    selected = (not commands and document["source_before"] is None
                        if command is None else commands and commands[-1]["id"] == command
                        and commands[-1]["process_started"] is None)
                    if document["state"] == "running" and selected:
                        injected.append(document)
                        for row in commands:
                            if row.get("process_started") is True:
                                path = case.args.output_dir / row["log"]
                                logs[path] = path.read_bytes()
                        raise fault
            return real_fsync(descriptor)

        def observe_write(path, document):
            self.assertEqual(path, target)
            before = path.read_bytes() if path.exists() else None
            if injected:
                following_writes.append(deepcopy(document))
            try:
                return write_json(path, document)
            except (OSError, KeyboardInterrupt) as error:
                failures.append((error, before, path.read_bytes() if path.exists() else None,
                                 temporary.exists()))
                raise

        with mock.patch.object(inputs.base, "_write_json", side_effect=observe_write), \
                mock.patch.object(inputs.base.os, "fsync", side_effect=fail_fsync):
            result = case.acquire()

        self.assertEqual(len(injected), 1)
        self.assertEqual(len(failures), 1)
        error, before, after, temporary_remains = failures[0]
        self.assertIs(error, fault)
        self.assertEqual(after, before)
        self.assertFalse(temporary_remains)
        self.assertEqual(following_writes, [result])
        self.assertFalse(temporary.exists())
        self.assertEqual(result["reason"], str(fault))
        self.assertEqual(result["failures"], [{"stage": "input-acquisition", "reason": str(fault)}])
        self.assertTrue(hosted.writers_finished(case.root, stages))
        self.assertIsNone(result["input_identity_sha256"])
        self.assertIsNone(result["source_after"])
        self.assertIsNone(result["resources_after"])
        self.assertFalse(any("--url" in argv for argv, *_ in case.observed))
        self.assertFalse(any(path.is_file() for path in case.args.archive_root.rglob("*")))
        self.assertEqual(result["network_acquisition"],
                         any("fetch" in argv for argv, *_ in case.observed))
        for field, value in result.items():
            if type(value) is bool and field != "network_acquisition":
                self.assertIs(value, False, field)
        for path, body in logs.items():
            self.assertEqual(path.read_bytes(), body)

        if command is None:
            self.assertIsNone(before)
            self.assertEqual(result["outcome"], "blocked")
            self.assertEqual(result["commands"], [])
            self.assertEqual(result["parts"], [])
            self.assertEqual(result["repositories"], {})
            self.assertIsNone(result["plan"])
            self.assertIsNone(result["source_before"])
            for observer in (case.run_mock, case.source_mock, case.plan_mock,
                             case.disk_mock, case.memory_mock):
                observer.assert_not_called()
            self.assertFalse(case.args.archive_root.exists())
            self.assertFalse(case.args.dependency_repositories.exists())
            return

        self.assertEqual(json.loads(before)["state"], "running")
        self.assertEqual(result["outcome"], "fail")
        expected = [name + suffix for name in inputs.FETCHED_NAMES for suffix in ("-init", "-fetch")]
        expected.append("toolchain-part-01")
        expected = expected[:expected.index(command) + 1]
        self.assertEqual([row["id"] for row in result["commands"]], expected)
        self.assertEqual(result["commands"][:-1], injected[0]["commands"][:-1])
        self.assertEqual([row["argv"] for row in result["commands"][:-1]],
                         [argv for argv, *_ in case.observed])
        self.assertEqual(case.run_mock.call_count, len(expected) - 1)
        active = result["commands"][-1]
        self.assertIs(active["process_started"], False)
        self.assertIs(active["cleanup_complete"], True)
        self.assertEqual(active["outcome"], "blocked")
        self.assertIsNone(active["exit_code"])
        self.assertEqual(active["reason"], str(fault))
        self.assertFalse((case.args.output_dir / active["log"]).exists())
        self.assertEqual(result["parts"], injected[0]["parts"])
        self.assertEqual(result["repositories"], injected[0]["repositories"])

    def test_initial_fsync_failure_finishes_known_nonstart(self):
        for error_type in (OSError, KeyboardInterrupt):
            with self.subTest(error=error_type.__name__), _synthetic_acquisition() as case:
                self.check_recovery(case, error_type)

    def test_prelaunch_fsync_failure_preserves_commands_without_download_or_retry(self):
        for command in (inputs.FETCHED_NAMES[0] + "-fetch", "toolchain-part-01"):
            for error_type in (OSError, KeyboardInterrupt):
                with self.subTest(command=command, error=error_type.__name__), \
                        _synthetic_acquisition() as case:
                    self.check_recovery(case, error_type, command)


if __name__ == "__main__":
    unittest.main()

# SPDX-License-Identifier: Apache-2.0
"""Initial supervisor receipt faults retain a finished, never-started attempt."""

from copy import deepcopy
import json
import unittest
from unittest import mock

import p06_qualified_warm_hosted as hosted
import p06_qualified_warm_run as runner
import test_p06_qualified_warm_run as fixtures


class InitialCheckpointCloseoutTests(unittest.TestCase):
    def setUp(self):
        self.case = fixtures.QualifiedWarmRunTests()
        self.addCleanup(self.case.doCleanups)
        self.case.setUp()
        self.case.workspace = self.case.root / "workspace"
        self.case.args.workspace_dir = self.case.workspace
        self.case.paths["workspace"] = str(self.case.workspace)

    def assert_initial_checkpoint_closeout(self, error, reason):
        target = self.case.workspace / "evidence" / runner.RECEIPT_PATH
        supervisor = [{"id": "native-supervisor", "process_started": True, "cleanup_complete": True}]
        write_json = runner.base._write_json
        writes = []

        def fail_first_write(path, document):
            writes.append((path, deepcopy(document)))
            if len(writes) == 1:
                raise error
            return write_json(path, document)

        with mock.patch.object(runner.base, "_write_json", side_effect=fail_first_write), \
                mock.patch.object(runner, "run_bounded") as launch:
            try:
                result = runner.execute(self.case.args)
            except (OSError, KeyboardInterrupt) as escaped:
                self.fail(f"{type(escaped).__name__} escaped initial checkpoint; "
                    f"receipt_exists={target.exists()}; "
                    f"writers_finished={hosted.writers_finished(self.case.root, supervisor)}; "
                    f"native_execution={hosted.observed_native_execution(self.case.root, self.case.revision)}")

        launch.assert_not_called()
        self.assertEqual([path for path, _ in writes], [target, target])
        self.assertEqual([document["state"] for _, document in writes], ["running", "finished"])
        self.assertTrue(target.is_file())
        self.assertEqual(json.loads(target.read_text()), result)
        self.assertEqual(writes[-1][1], result)
        self.assertEqual(result["state"], "finished")
        self.assertIsNotNone(result["finished_at"])
        self.assertEqual(result["outcome"], "blocked")
        self.assertEqual(result["reason"], reason)
        self.assertEqual([(row["stage"], row["reason"]) for row in result["failures"]],
                         [("orchestration", reason)])
        self.assertEqual(result["native_execution"], "not_run")
        self.assertEqual(result["stages"], [])
        self.assertEqual(result["reports"], {})
        self.assertIsNone(result["completed_counts"])
        self.assertIsNone(result["dependency_receipt_sha256"])
        self.assertIsNone(result["qualified_warm_report_sha256"])
        self.assertIsNone(result["source_before"])
        self.assertEqual(result["source_after"], self.case.checkout)
        self.assertFalse(result["orchestration_passed"])
        for field in runner.qualification.FALSE_CLAIMS:
            self.assertIs(result[field], False, field)
        self.assertEqual(result["expected_counts"], runner.COMPLETE_COUNTS)
        self.assertEqual(result["budget"], runner.BUDGET)
        self.assertTrue(hosted.writers_finished(self.case.root, supervisor))
        self.assertEqual(hosted.observed_native_execution(self.case.root, self.case.revision), "not_run")

    def test_initial_oserror_retains_known_nonstart(self):
        self.assert_initial_checkpoint_closeout(OSError("initial receipt unavailable"),
                                               "initial receipt unavailable")

    def test_initial_interrupt_retains_known_nonstart(self):
        self.assert_initial_checkpoint_closeout(KeyboardInterrupt(), "interrupted")


if __name__ == "__main__":
    unittest.main()

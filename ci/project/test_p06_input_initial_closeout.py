# SPDX-License-Identifier: Apache-2.0
"""Initial acquisition receipt faults retain a finished, never-started attempt."""

from copy import deepcopy
import unittest
from unittest import mock

import p06_qualified_warm_hosted as hosted
import p06_qualified_warm_inputs as inputs
import test_p06_qualified_warm_inputs as fixtures


class InputInitialCloseoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixtures.QualifiedWarmInputAcquisitionTests.setUpClass()
        cls.addClassCleanup(fixtures.QualifiedWarmInputAcquisitionTests.doClassCleanups)

    def setUp(self):
        self.case = fixtures.QualifiedWarmInputAcquisitionTests()
        self.addCleanup(self.case.doCleanups)
        self.case.setUp()
        self.case.args.output_dir = self.case.root / "acquisition"

    def assert_initial_checkpoint_closeout(self, error, reason):
        target = self.case.args.output_dir / inputs.RECEIPT_NAME
        stages = [{"id": "input-acquisition", "process_started": True, "cleanup_complete": True}]
        write_json = inputs.base._write_json
        writes = []

        def fail_first_write(path, document):
            writes.append((path, deepcopy(document)))
            if len(writes) == 1:
                raise error
            return write_json(path, document)

        with mock.patch.object(inputs.base, "_write_json", side_effect=fail_first_write):
            try:
                result = self.case.acquire()
            except (OSError, KeyboardInterrupt) as escaped:
                self.fail(f"{type(escaped).__name__} escaped initial checkpoint; "
                    f"receipt_exists={target.exists()}; "
                    f"monitor_calls={self.case.run_mock.call_count}; "
                    f"writers_finished={hosted.writers_finished(self.case.root, stages)}")

        self.assertEqual([path for path, _ in writes], [target, target])
        self.assertEqual([document["state"] for _, document in writes], ["running", "finished"])
        self.assertEqual(writes[-1][1], result)
        self.assertEqual(result["state"], "finished")
        self.assertEqual(result["outcome"], "blocked")
        self.assertEqual(result["reason"], reason)
        self.assertEqual(result["failures"], [{"stage": "input-acquisition", "reason": reason}])
        self.assertEqual(result["commands"], [])
        self.assertEqual(result["parts"], [])
        self.assertEqual(result["repositories"], {})
        self.assertEqual(result["native_execution"], "not_run")
        self.assertIs(result["network_acquisition"], False)
        for field, value in result.items():
            if type(value) is bool:
                self.assertIs(value, False, field)
        for field in ("plan", "source_before", "source_after", "source_manifest",
                      "resources_before", "resources_after", "input_identity_sha256"):
            self.assertIsNone(result[field], field)
        self.case.run_mock.assert_not_called()
        self.case.source_mock.assert_not_called()
        self.case.plan_mock.assert_not_called()
        self.case.disk_mock.assert_not_called()
        self.case.memory_mock.assert_not_called()
        self.assertFalse(self.case.args.archive_root.exists())
        self.assertFalse(self.case.args.dependency_repositories.exists())
        self.assertTrue(hosted.writers_finished(self.case.root, stages))

    def test_initial_oserror_retains_known_nonstart(self):
        self.assert_initial_checkpoint_closeout(OSError("initial receipt unavailable"),
                                               "initial receipt unavailable")

    def test_initial_interrupt_retains_known_nonstart(self):
        self.assert_initial_checkpoint_closeout(KeyboardInterrupt(), "interrupted")


if __name__ == "__main__":
    unittest.main()

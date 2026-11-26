# SPDX-License-Identifier: Apache-2.0
"""Initial builder receipt faults retain a finished, never-started dependency build."""

from copy import deepcopy
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

import p06_dependency_build as build
import p06_dependency_contract as contract
import p06_qualified_warm_hosted as hosted
import p06_qualified_warm_run as runner


class BuilderInitialCloseoutTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="p06-builder-initial-")
        self.addCleanup(temporary.cleanup)
        self.attempt = Path(temporary.name)
        self.workspace = self.attempt / "workspace"
        evidence = self.workspace / "evidence"
        evidence.mkdir(parents=True)
        self.revision = "1" * 40
        self.args = SimpleNamespace(source_dir=build.ROOT, workspace_dir=self.workspace,
            output_dir=evidence / "dependency-build", expected_revision=self.revision,
            preparation=evidence / "dependency-preparation.json")
        self.target = self.args.output_dir / "report.json"
        self.supervisor = [{"id": "native-supervisor", "process_started": True,
                            "cleanup_complete": True}]
        build.base._write_json(evidence / runner.RECEIPT_PATH, {
            "contract_id": runner.CONTRACT_ID, "expected_revision": self.revision,
            "state": "finished", "native_execution": "not_run", "stages": [{
                "id": "dependency-build", "report_path": "dependency-build/report.json",
                "process_started": True, "cleanup_complete": True}]})

    def assert_nonstart(self, report, reason):
        self.assertEqual(report["state"], "finished")
        self.assertEqual(report["outcome"], "blocked")
        self.assertEqual(report["reason"], reason)
        self.assertEqual(report["failures"], [{"stage": "execution", "reason": reason}])
        for name in ("commands", "records", "retained_files", "helper_sources", "source_plan",
                     "generated_inputs", "generated_sources", "archives", "external_archives",
                     "maps", "staged_files"):
            self.assertEqual(report[name], [], name)
        for name in ("preparation", "source_manifest", "tool_config", "compile_database",
                     "source_checkout_before", "source_checkout_after"):
            self.assertIsNone(report[name], name)
        for name in ("tools", "products", "cmake_configuration"):
            self.assertEqual(report[name], {}, name)
        for name in ("fresh_dependency_build_passed", *contract.FALSE_CLAIMS):
            self.assertIs(report[name], False, name)
        self.assertEqual(report["budget"], contract.BUDGET)
        self.assertEqual(report["stability_checks"], [{
            "label": "final", "staged_sha256": contract.digest([])}])
        self.assertFalse((self.workspace / "dependency-build").exists())
        self.assertFalse((self.workspace / "dependency-sources").exists())
        for name in ("logs", "records", "payloads", "helpers", "build-inputs", "launchers"):
            self.assertEqual(list((self.args.output_dir / name).iterdir()), [], name)

    def assert_initial_checkpoint_closeout(self, error, *, published):
        write_json = build.base._write_json
        writes = []

        def fail_first_write(path, report):
            writes.append((path, deepcopy(report)))
            if len(writes) == 1:
                if published:
                    write_json(path, report)
                raise error
            return write_json(path, report)

        self.assertFalse(hosted.writers_finished(self.attempt, self.supervisor))
        with mock.patch.object(build.base, "_write_json", side_effect=fail_first_write), \
                mock.patch.object(build, "collect_source") as checkout, \
                mock.patch.object(build, "tool_inventory") as tools, \
                mock.patch.object(build.sources, "materialize_sources") as sources, \
                mock.patch.object(build, "run_bounded") as launch:
            try:
                report = build.build(self.args)
            except (OSError, KeyboardInterrupt) as escaped:
                self.fail(f"{type(escaped).__name__} escaped initial checkpoint; "
                          f"receipt_exists={self.target.exists()}; "
                          f"writers_finished={hosted.writers_finished(self.attempt, self.supervisor)}")

        for operation in (checkout, tools, sources, launch):
            operation.assert_not_called()
        self.assertEqual([path for path, _ in writes], [self.target, self.target])
        self.assertEqual([value["state"] for _, value in writes], ["running", "finished"])
        self.assertEqual(writes[-1][1], report)
        self.assertEqual(json.loads(self.target.read_text()), report)
        self.assert_nonstart(report, str(error) or "interrupted")
        self.assertTrue(hosted.writers_finished(self.attempt, self.supervisor))
        self.assertEqual(hosted.observed_native_execution(self.attempt, self.revision), "not_run")

    def test_initial_oserror_retains_known_nonstart(self):
        self.assert_initial_checkpoint_closeout(OSError("initial receipt unavailable"), published=False)

    def test_initial_interrupt_retains_known_nonstart(self):
        self.assert_initial_checkpoint_closeout(KeyboardInterrupt(), published=False)

    def test_published_initial_receipt_is_finished_after_oserror(self):
        self.assert_initial_checkpoint_closeout(OSError("initial receipt completion unavailable"), published=True)

    def test_published_initial_receipt_is_finished_after_interrupt(self):
        self.assert_initial_checkpoint_closeout(KeyboardInterrupt(), published=True)

    def test_terminal_receipt_failure_is_not_retried(self):
        initial = OSError("initial receipt unavailable")
        terminal = OSError("terminal receipt unavailable")
        writes = []

        def unavailable(path, report):
            writes.append((path, deepcopy(report)))
            raise initial if len(writes) == 1 else terminal

        with mock.patch.object(build.base, "_write_json", side_effect=unavailable), \
                mock.patch.object(build, "collect_source") as checkout, \
                mock.patch.object(build, "tool_inventory") as tools, \
                mock.patch.object(build.sources, "materialize_sources") as sources, \
                mock.patch.object(build, "run_bounded") as launch:
            with self.assertRaises(OSError) as raised:
                build.build(self.args)

        self.assertIs(raised.exception, terminal)
        for operation in (checkout, tools, sources, launch):
            operation.assert_not_called()
        self.assertEqual([path for path, _ in writes], [self.target, self.target])
        self.assertEqual([value["state"] for _, value in writes], ["running", "finished"])
        self.assert_nonstart(writes[-1][1], str(initial))
        self.assertFalse(self.target.exists())
        self.assertFalse(hosted.writers_finished(self.attempt, self.supervisor))


if __name__ == "__main__":
    unittest.main()

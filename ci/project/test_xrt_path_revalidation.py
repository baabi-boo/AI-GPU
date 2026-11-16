# Licensed under the Apache License, Version 2.0.
"""Reject changed path boundaries using only inert, temporary runner fixtures."""

import copy
from pathlib import Path
import unittest
from unittest import mock

import xrt_baseline
from test_xrt_baseline import RunnerFixture, STAGES
from xrt_test_support import write_file


class PathRevalidationTests(RunnerFixture):
    def tree_snapshot(self, root):
        result = {}
        for path in root.rglob("*"):
            if path.is_symlink():
                value = ("symlink", str(path.readlink()))
            elif path.is_dir():
                value = ("directory",)
            else:
                value = ("file", path.read_bytes())
            result[str(path.relative_to(root))] = value
        return result

    def protected_tree(self, name="unrelated"):
        root = self.base / name
        write_file(root / ".config.stamp", "KEEP EXISTING CONFIGURATION\n")
        write_file(root / "existing.txt", "KEEP UNRELATED BYTES\n")
        return root, self.tree_snapshot(root)

    def redirect_directory(self, path, target):
        self.assertTrue(path.is_relative_to(self.base))
        self.assertTrue(target.is_relative_to(self.base))
        original = path.with_name(path.name + "-before-retarget")
        path.rename(original)
        path.symlink_to(target, target_is_directory=True)
        return original

    def after_checkpoint(self, stage, mutate):
        checkpoint = xrt_baseline._checkpoint
        events = []

        def checkpoint_then_mutate(output, report, paths, data):
            result = checkpoint(output, report, paths, data)
            if report.get("active_command") == stage and not events:
                mutate()
                events.append(stage)
            return result

        self.stack.enter_context(mock.patch.object(
            xrt_baseline, "_checkpoint", side_effect=checkpoint_then_mutate))
        return events

    def before_retention(self, destination, mutate):
        retain = xrt_baseline._retain
        events = []

        def mutate_then_retain(path, target, *args, **kwargs):
            if target == destination and not events:
                mutate()
                events.append(target)
            return retain(path, target, *args, **kwargs)

        self.stack.enter_context(mock.patch.object(
            xrt_baseline, "_retain", side_effect=mutate_then_retain))
        return events

    def assertStopped(self, report, launched=(), pending=None, reason="symlinks"):
        self.assertEqual(report["outcome"], "fail", report.get("reason"))
        self.assertIn(reason, report["reason"])
        self.assertEqual([call["id"] for call in self.calls], list(launched))
        self.assertEqual(self.runner.call_count, len(launched))
        expected = list(launched) + ([pending] if pending is not None else [])
        self.assertEqual([entry["id"] for entry in report["commands"]], expected)
        if pending is not None:
            self.assertEqual(report["commands"][-1]["outcome"], "not_run")
            self.assertIsNone(report["commands"][-1]["exit_code"])
        smoke_ran = "smoke" in launched
        self.assertEqual(report["integration"]["outcome"], "fail" if smoke_ran else "not_run")
        self.assertEqual(report["integration"]["exit_code"], 0 if smoke_ran else None)
        stored = self.assertFinished(report)
        self.assertEqual(stored["integration"], report["integration"])
        self.assertEqual(len(stored["commands"]), len(report["commands"]))
        for current, checkpoint in zip(report["commands"], stored["commands"]):
            for key in ("id", "outcome", "exit_code"):
                self.assertEqual(checkpoint[key], current[key])
        self.assertFalse((self.fixture.output / "report.json.tmp").exists())
        return stored

    def output_under_parent(self):
        parent = self.base / "output-parent"
        parent.mkdir()
        self.fixture.output = parent / "packet"
        return parent

    def assertCachedOutputRejected(self, blocked=False):
        parent = self.output_under_parent()
        if blocked:
            Path(self.fixture.files["vpp"]["path"]).unlink()
        args, paths, report = self.plan()
        self.assertEqual(report["outcome"], "blocked" if blocked else "pass", report)
        before = self.tree_snapshot(self.fixture.source)
        original = self.redirect_directory(parent, self.fixture.source)

        with self.assertRaisesRegex(ValueError, "symlinks"):
            xrt_baseline.execute_run(args, report, paths)

        self.assertEqual(self.tree_snapshot(self.fixture.source), before)
        self.assertFalse((self.fixture.source / "packet").exists())
        self.assertEqual(list(original.iterdir()), [])
        self.assertEqual(self.calls, [])
        self.runner.assert_not_called()
        self.host_observation.assert_not_called()
        self.assertEqual(list(self.fixture.build.iterdir()), [])

    def test_cached_output_ancestor_cannot_redirect_passing_plan_into_source(self):
        self.assertCachedOutputRejected()

    def test_cached_output_ancestor_cannot_redirect_blocked_checkpoint_into_source(self):
        self.assertCachedOutputRejected(blocked=True)

    def test_cli_reports_blocked_when_output_ancestor_changes_after_planning(self):
        parent = self.output_under_parent()
        before = self.tree_snapshot(self.fixture.source)
        plan = xrt_baseline.plan_run
        originals = []

        def plan_then_redirect(*args, **kwargs):
            report = plan(*args, **kwargs)
            self.assertEqual(report["outcome"], "pass", report["blockers"])
            originals.append(self.redirect_directory(parent, self.fixture.source))
            return report

        with mock.patch.object(xrt_baseline, "plan_run", side_effect=plan_then_redirect):
            code, report = self.invoke()

        self.assertEqual(code, 1)
        self.assertEqual(report["outcome"], "blocked")
        self.assertTrue(any("symlinks" in blocker for blocker in report["blockers"]))
        self.assertNotAccepted(report)
        self.assertEqual(self.tree_snapshot(self.fixture.source), before)
        self.assertFalse((self.fixture.source / "packet").exists())
        self.assertEqual(len(originals), 1)
        self.assertEqual(list(originals[0].iterdir()), [])
        self.runner.assert_not_called()
        self.host_observation.assert_not_called()

    def test_cached_build_ancestor_cannot_configure_an_unrelated_nonempty_tree(self):
        parent = self.base / "build-parent"
        self.fixture.build = parent / "build64"
        self.fixture.build.mkdir(parents=True)
        args, paths, report = self.plan()
        self.assertEqual(report["outcome"], "pass", report["blockers"])
        target, before = self.protected_tree("unrelated-parent/build64")
        original = self.redirect_directory(parent, target.parent)

        with self.assertRaisesRegex(ValueError, "symlinks"):
            xrt_baseline.execute_run(args, report, paths)

        self.assertEqual(self.tree_snapshot(target), before)
        self.assertEqual(list((original / "build64").iterdir()), [])
        self.assertFalse(self.fixture.output.exists())
        self.assertEqual(self.calls, [])
        self.runner.assert_not_called()
        self.host_observation.assert_not_called()

    def test_nonempty_build_arriving_after_plan_is_preserved_before_output_creation(self):
        args, paths, report = self.plan()
        self.assertEqual(report["outcome"], "pass", report["blockers"])
        write_file(self.fixture.build / ".config.stamp", "NEW UNRELATED CONFIGURATION\n")
        before = self.tree_snapshot(self.fixture.build)

        with self.assertRaisesRegex(ValueError, "fresh or empty"):
            xrt_baseline.execute_run(args, report, paths)

        self.assertEqual(self.tree_snapshot(self.fixture.build), before)
        self.assertFalse(self.fixture.output.exists())
        self.runner.assert_not_called()
        self.host_observation.assert_not_called()

    def test_nonempty_build_arriving_during_host_probe_is_preserved(self):
        snapshots = []

        def probe_then_populate(*_):
            write_file(self.fixture.build / ".config.stamp", "ARRIVED DURING HOST PROBE\n")
            snapshots.append(self.tree_snapshot(self.fixture.build))
            return copy.deepcopy(self.host_record)

        self.host_observation.side_effect = probe_then_populate
        report = self.run_fixture()

        self.assertStopped(report, reason="fresh or empty")
        self.assertEqual(len(snapshots), 1)
        self.assertEqual(self.tree_snapshot(self.fixture.build), snapshots[0])

    def test_nonempty_build_after_active_checkpoint_is_not_overwritten_by_configure(self):
        events = self.after_checkpoint("configure", lambda: write_file(
            self.fixture.build / ".config.stamp", "ARRIVED BEFORE CONFIGURE\n"))

        report = self.run_fixture()

        self.assertStopped(report, pending="configure", reason="fresh or empty")
        self.assertEqual(events, ["configure"])
        self.assertEqual(self.tree_snapshot(self.fixture.build), {
            ".config.stamp": ("file", b"ARRIVED BEFORE CONFIGURE\n")})

    def test_output_root_retargeted_after_configure_receives_no_checkpoint(self):
        before = self.tree_snapshot(self.fixture.source)
        originals = []

        def redirect_after_configure(stage):
            if stage == "configure":
                originals.append(self.redirect_directory(self.fixture.output, self.fixture.source))

        self.after_stage = redirect_after_configure
        with self.assertRaisesRegex(ValueError, "symlinks"):
            self.run_fixture()

        self.assertEqual([call["id"] for call in self.calls], ["configure"])
        self.assertEqual(self.tree_snapshot(self.fixture.source), before)
        self.assertEqual(len(originals), 1)
        self.assertTrue((originals[0] / "report.json").is_file())
        self.assertFalse((self.fixture.source / "report.json").exists())
        self.assertFalse((self.fixture.source / "report.json.tmp").exists())

    def assertOutputChildRejected(self, child, after_stage="configure"):
        target, before = self.protected_tree()
        self.after_stage = lambda stage: self.redirect_directory(
            self.fixture.output / child, target) if stage == after_stage else None

        report = self.run_fixture()

        self.assertStopped(report, launched=STAGES[:STAGES.index(after_stage) + 1])
        self.assertEqual(self.tree_snapshot(target), before)

    def test_logs_directory_retargeted_between_stages_receives_no_next_log(self):
        self.assertOutputChildRejected("logs")

    def test_tmp_directory_retargeted_between_stages_prevents_next_command(self):
        self.assertOutputChildRejected("tmp")

    def test_artifact_directory_retargeted_after_smoke_receives_no_configuration_copies(self):
        self.assertOutputChildRejected("artifacts", after_stage="smoke")

    def test_log_leaf_symlink_after_active_checkpoint_cannot_overwrite_its_target(self):
        target, before = self.protected_tree()
        log = self.fixture.output / "logs/configure.log"
        events = self.after_checkpoint("configure", lambda: log.symlink_to(target / "existing.txt"))

        report = self.run_fixture()

        self.assertStopped(report, pending="configure")
        self.assertEqual(events, ["configure"])
        self.assertTrue(log.is_symlink())
        self.assertEqual(self.tree_snapshot(target), before)

    def test_artifact_parent_retargeted_during_host_probe_receives_no_tooling_directory(self):
        target, before = self.protected_tree()
        events = []

        def probe_then_redirect(*_):
            events.append(self.redirect_directory(self.fixture.output / "artifacts", target))
            return copy.deepcopy(self.host_record)

        self.host_observation.side_effect = probe_then_redirect
        report = self.run_fixture()

        self.assertStopped(report)
        self.assertEqual(len(events), 1)
        self.assertEqual(self.tree_snapshot(target), before)
        self.assertFalse((target / "tooling").exists())

    def test_tooling_ancestor_retargeted_before_retention_receives_no_helper_copy(self):
        target, before = self.protected_tree()
        tooling = self.fixture.output / "artifacts/tooling"
        destination = tooling / "xrt_baseline.py"
        events = self.before_retention(destination, lambda: self.redirect_directory(tooling, target))

        report = self.run_fixture()

        self.assertStopped(report)
        self.assertEqual(events, [destination])
        self.assertEqual(self.tree_snapshot(target), before)
        self.assertTrue((self.fixture.output / "artifacts/manifest.json").is_file())

    def test_retained_artifact_leaf_symlink_cannot_overwrite_its_target(self):
        target, before = self.protected_tree()
        destination = self.fixture.output / "artifacts/build_receipt"
        events = self.before_retention(destination, lambda: destination.symlink_to(target / "existing.txt"))

        report = self.run_fixture()

        self.assertStopped(report)
        self.assertEqual(events, [destination])
        self.assertTrue(destination.is_symlink())
        self.assertEqual(self.tree_snapshot(target), before)

    def assertMakeDirectoryRejected(self, relative, previous_stage, pending):
        target, before = self.protected_tree()
        self.after_stage = lambda stage: self.redirect_directory(
            self.fixture.build / relative, target) if stage == previous_stage else None

        report = self.run_fixture()

        self.assertStopped(report, launched=STAGES[:STAGES.index(previous_stage) + 1], pending=pending)
        self.assertEqual(self.tree_snapshot(target), before)

    def test_kernel_make_directory_symlink_prevents_kernel_command(self):
        self.assertMakeDirectoryRejected("sw/kernel", "configure", "kernel-library")

    def test_runtime_stub_make_directory_symlink_prevents_stub_command(self):
        self.assertMakeDirectoryRejected("sw/runtime/stub", "kernel-library", "runtime-stub")

    def test_application_make_directory_symlink_prevents_application_command(self):
        self.assertMakeDirectoryRejected("tests/regression/demo", "runtime-stub", "application")

    def test_make_directory_retargeted_after_active_checkpoint_prevents_launch(self):
        target, before = self.protected_tree()
        events = self.after_checkpoint("kernel-library", lambda: self.redirect_directory(
            self.fixture.build / "sw/kernel", target))

        report = self.run_fixture()

        self.assertStopped(report, launched=("configure",), pending="kernel-library")
        self.assertEqual(events, ["kernel-library"])
        self.assertEqual(self.tree_snapshot(target), before)

    def test_smoke_cwd_retargeted_after_active_checkpoint_prevents_launch(self):
        target, before = self.protected_tree()
        events = self.after_checkpoint("smoke", lambda: self.redirect_directory(
            self.fixture.build / "tests/regression/demo", target))

        report = self.run_fixture()

        self.assertStopped(report, launched=STAGES[:-1], pending="smoke")
        self.assertEqual(events, ["smoke"])
        self.assertEqual(self.tree_snapshot(target), before)

    def assertManifestCheckpointPreserved(self, mutate):
        args, paths, report = self.plan()
        self.assertEqual(report["outcome"], "pass", report["blockers"])
        mutate()

        report = xrt_baseline.execute_run(args, report, paths)

        stored = self.assertStopped(report, reason="manifest became invalid after planning")
        self.assertIn("manifest became invalid after planning", stored["reason"])
        self.runner.assert_not_called()
        self.host_observation.assert_not_called()
        self.assertEqual(list(self.fixture.build.iterdir()), [])

    def test_malformed_manifest_still_retains_a_safe_failure_checkpoint(self):
        self.assertManifestCheckpointPreserved(
            lambda: self.fixture.manifest_path.write_bytes(b"{broken-json"))

    def test_deleted_manifest_still_retains_a_safe_failure_checkpoint(self):
        self.assertManifestCheckpointPreserved(self.fixture.manifest_path.unlink)


if __name__ == "__main__":
    unittest.main()

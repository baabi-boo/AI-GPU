# SPDX-License-Identifier: Apache-2.0
"""Real checkpoint faults with synthetic children; no native execution evidence."""

from contextlib import contextmanager
from copy import deepcopy
import json
import unittest
from unittest import mock

import p06_qualified_warm_hosted as hosted
import p06_qualified_warm_run as runner
import test_p06_qualified_warm_run as fixtures


@contextmanager
def _synthetic_runner():
    case = fixtures.QualifiedWarmRunTests()
    try:
        case.setUp()
        case.workspace = case.root / "workspace"
        case.args.workspace_dir = case.workspace
        case.paths["workspace"] = str(case.workspace)

        def complete_command_inventory(name, document, argv):
            if name == "dependency-build":
                document["commands"] = []
            return 0

        case.change = complete_command_inventory
        yield case
    finally:
        case.doCleanups()


class CheckpointRunRecoveryTests(unittest.TestCase):
    def assert_checkpoint_recovery(self, stage=None, *, completed=False):
        for error_type in (OSError, KeyboardInterrupt):
            with self.subTest(error=error_type.__name__), _synthetic_runner() as case:
                self.check_checkpoint_recovery(case, stage, completed, error_type)

    def check_checkpoint_recovery(self, case, stage, completed, error_type):
        evidence = case.workspace / "evidence"
        target = evidence / runner.RECEIPT_PATH
        temporary = target.with_name(target.name + ".tmp")
        supervisor = [{"id": "native-supervisor", "process_started": True, "cleanup_complete": True}]
        write_json, real_fsync = runner.base._write_json, runner.base.os.fsync
        fault = error_type("one-shot checkpoint fsync failure")
        injected, failures, subsequent_writes, originals = [], [], [], {}

        def selected(document):
            if document["state"] != "running":
                return False
            if stage is None:
                return document["source_before"] is None and not document["stages"]
            if not document["stages"] or document["stages"][-1]["id"] != stage:
                return False
            active = document["stages"][-1]
            if completed:
                return active.get("process_started") is True and active["finished_at"] is not None
            return active["process_started"] is None and active["finished_at"] is None

        def fail_fsync(descriptor):
            if not injected and temporary.exists():
                opened, pending = runner.base.os.fstat(descriptor), temporary.lstat()
                if (opened.st_dev, opened.st_ino) == (pending.st_dev, pending.st_ino):
                    document = json.loads(temporary.read_bytes())
                    if selected(document):
                        injected.append(document)
                        for row in document["stages"]:
                            if row.get("process_started") is True:
                                for field in ("report_path", "log"):
                                    path = evidence / row[field]
                                    originals[path] = path.read_bytes()
                        raise fault
            return real_fsync(descriptor)

        def observe_write(path, document):
            self.assertEqual(path, target)
            before = path.read_bytes() if path.exists() else None
            if injected:
                subsequent_writes.append(deepcopy(document))
            try:
                return write_json(path, document)
            except (OSError, KeyboardInterrupt) as error:
                failures.append({"error": error, "before": before,
                    "after": path.read_bytes() if path.exists() else None,
                    "temporary_remains": temporary.exists(),
                    "writers_finished": hosted.writers_finished(case.root, supervisor),
                    "native_execution": hosted.observed_native_execution(case.root, case.revision)})
                raise

        with mock.patch.object(runner, "run_bounded", side_effect=case.child), \
                mock.patch.object(runner.base, "_write_json", side_effect=observe_write), \
                mock.patch.object(runner.base.os, "fsync", side_effect=fail_fsync):
            result = runner.execute(case.args)

        self.assertEqual(len(injected), 1)
        self.assertEqual(len(failures), 1)
        failed, pending = failures[0], injected[0]
        self.assertIs(failed["error"], fault)
        self.assertEqual(failed["after"], failed["before"])
        self.assertFalse(failed["temporary_remains"])
        self.assertFalse(failed["writers_finished"])
        self.assertEqual(failed["native_execution"], "unknown")
        self.assertEqual(subsequent_writes, [result])
        self.assertEqual(json.loads(target.read_bytes()), result)
        self.assertFalse(temporary.exists())
        self.assertEqual(result["state"], "finished")
        self.assertIsNotNone(result["finished_at"])
        self.assertEqual(result["reason"], str(fault))
        self.assertEqual([(row["stage"], row["reason"]) for row in result["failures"]],
                         [(stage or "orchestration", str(fault))])
        self.assertFalse(result["orchestration_passed"])
        for claim in runner.qualification.FALSE_CLAIMS:
            self.assertIs(result[claim], False, claim)
        self.assertEqual(result["expected_counts"], runner.COMPLETE_COUNTS)
        self.assertEqual(result["budget"], runner.BUDGET)
        self.assertIsNone(result["completed_counts"])
        self.assertIsNone(result["qualified_warm_report_sha256"])
        self.assertEqual(result["source_after"], case.checkout)

        children = list(runner.STAGE_NAMES) if completed else (
            list(runner.STAGE_NAMES[:runner.STAGE_NAMES.index(stage)]) if stage else [])
        stages = children if completed or stage is None else [*children, stage]
        self.assertEqual([row["id"] for row in case.observed], children)
        self.assertEqual([row["id"] for row in result["stages"]], stages)
        self.assertEqual(result["outcome"], "fail" if children else "blocked")
        for row in result["stages"][:len(children)]:
            self.assertIs(row["process_started"], True)
            self.assertIs(row["cleanup_complete"], True)
            self.assertEqual(row["outcome"], "pass")
            self.assertEqual(row["exit_code"], 0)
        if stage is not None and not completed:
            active = result["stages"][-1]
            self.assertIs(active["process_started"], False)
            self.assertIs(active["cleanup_complete"], True)
            self.assertEqual(active["outcome"], "blocked")
            self.assertEqual(active["reason"], str(fault))
            self.assertIsNotNone(active["finished_at"])
            self.assertFalse((evidence / active["log"]).exists())
            self.assertFalse((evidence / active["report_path"]).exists())
        for path, body in originals.items():
            self.assertEqual(path.read_bytes(), body, path.name)
        self.assertEqual(result["reports"], pending["reports"])

        native = "run" if completed else "not_run"
        self.assertEqual(result["native_execution"], native)
        self.assertTrue(hosted.writers_finished(case.root, supervisor))
        self.assertEqual(hosted.observed_native_execution(case.root, case.revision), native)
        if stage is None:
            self.assertIsNone(failed["before"])
            self.assertEqual(pending["native_execution"], "not_run")
            self.assertIsNone(result["source_before"])
        else:
            previous = json.loads(failed["before"])
            self.assertEqual(previous["state"], "running")
            self.assertEqual(previous["native_execution"], "unknown" if completed else "not_run")
            self.assertEqual(pending["native_execution"],
                             "run" if completed else "unknown" if stage == "qualified-warm" else "not_run")
        if completed:
            self.assertEqual(result["stages"], pending["stages"])
            self.assertEqual(set(result["reports"]),
                             {*runner.STAGE_NAMES, "native-source-before", "native-source-after"})
            child = json.loads((evidence / "qualified-warm/report.json").read_bytes())
            self.assertEqual(child["state"], "finished")
            self.assertEqual(child["completed_counts"], runner.COMPLETE_COUNTS)

    def test_initial_fsync_failure_finishes_known_nonstart(self):
        self.assert_checkpoint_recovery()

    def test_preparation_prelaunch_fsync_failure_keeps_child_unstarted(self):
        self.assert_checkpoint_recovery("preparation")

    def test_native_prelaunch_fsync_failure_preserves_prior_children(self):
        self.assert_checkpoint_recovery("qualified-warm")

    def test_post_child_fsync_failure_preserves_observed_execution(self):
        self.assert_checkpoint_recovery("qualified-warm", completed=True)


if __name__ == "__main__":
    unittest.main()

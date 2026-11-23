# SPDX-License-Identifier: Apache-2.0
"""Preserve observed child starts when later process monitoring fails."""

import os
import subprocess
import sys
import time
import unittest
from unittest import mock

import p06_dependency_record as recorder
import test_p06_dependency_record as recorder_fixture


class ProcessStartReviewTests(unittest.TestCase):
    def setUp(self):
        self.fixture = recorder_fixture.DependencyRecorderTests(methodName="runTest")
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.processes = []
        self.addCleanup(self.reap_children)
        self.ready = self.fixture.roots["build"] / "child-ready.txt"
        tool = self.fixture.root / "waiting-archiver"
        tool.write_text("#!" + sys.executable + "\n"
            "import time\nfrom pathlib import Path\n"
            "Path(" + repr(str(self.ready)) + ").write_text('ready')\n"
            "time.sleep(30)\n")
        tool.chmod(0o755)
        self.tool = tool
        self.fixture.config["tools"]["ar"] = recorder.file_identity(tool)
        self.fixture.write_config()
        source = self.fixture.roots["build"] / "input.o"
        source.write_bytes(b"synthetic archive input; process-state control only")
        self.output = self.fixture.roots["build"] / "libinput.a"
        self.arguments = ["crs", str(self.output), str(source)]
        self.original_popen = subprocess.Popen

    def reap_children(self):
        for process, original_wait in self.processes:
            if process.poll() is None:
                process.kill()
            original_wait(timeout=3)

    def launch(self, *args, **kwargs):
        process = self.original_popen(*args, **kwargs)
        original_wait = process.wait
        self.processes.append((process, original_wait))
        limit = time.monotonic() + 3
        while not self.ready.exists() and time.monotonic() < limit:
            time.sleep(0.005)
        self.assertTrue(self.ready.exists(), "selected child did not reach its ready state")
        return process

    def run_tool(self):
        return self.fixture.run_tool("ar", "archive", self.arguments)

    def assert_failed_observed_child(self, result, reason, *, group_known):
        self.assertEqual(result["state"], "finished")
        self.assertEqual(result["outcome"], "fail")
        self.assertEqual(result["reason"], reason)
        self.assertEqual(result["failures"][0]["reason"], reason)
        self.assertEqual(len(self.processes), 1)
        process, _ = self.processes[0]
        self.assertEqual(len(result["children"]), 1)
        child = result["children"][0]
        observed = {"record_started": result["process_started"],
                    "child_started": child["process_started"], "recorded_pid": child["pid"],
                    "actual_pid": process.pid, "group": child["process_group"],
                    "finished_ns": child["finished_ns"], "actual_exit": process.poll()}
        self.assertIs(result["process_started"], True, observed)
        self.assertIs(child["process_started"], True, observed)
        self.assertEqual(child["pid"], process.pid)
        if group_known:
            self.assertEqual(child["process_group"], os.getpgrp())
        else:
            self.assertIsNone(child["process_group"])
        self.assertIsInstance(child["finished_ns"], int)
        self.assertIsNotNone(process.poll(), "recorder returned with a live selected child")
        self.assertEqual(child["exit_code"], process.returncode)
        self.assertEqual(result["exit_code"], child["exit_code"])
        self.assertLess(child["exit_code"], 0)
        self.assertIsNone(result["output"])
        self.assertFalse(self.output.exists())

    def test_group_observation_failure_retains_started_child_and_reaps_it(self):
        reason = "process-group observation failed"
        with mock.patch.object(recorder.subprocess, "Popen", side_effect=self.launch), \
                mock.patch.object(recorder.os, "getpgid", side_effect=OSError(reason)):
            result = self.run_tool()
        self.assert_failed_observed_child(result, reason, group_known=False)

    def test_wait_observation_failure_retains_started_child_and_reaps_it(self):
        reason = "wait observation failed"

        def launch(*args, **kwargs):
            process = self.launch(*args, **kwargs)
            original_wait = process.wait
            first = True

            def wait(*wait_args, **wait_kwargs):
                nonlocal first
                if first:
                    first = False
                    raise OSError(reason)
                return original_wait(*wait_args, **wait_kwargs)

            process.wait = wait
            return process

        with mock.patch.object(recorder.subprocess, "Popen", side_effect=launch):
            result = self.run_tool()
        self.assert_failed_observed_child(result, reason, group_known=True)

    def test_failed_process_creation_remains_a_known_nonstart(self):
        observed_errors = []

        def launch(*args, **kwargs):
            self.tool.chmod(0o600)
            try:
                return self.original_popen(*args, **kwargs)
            except OSError as error:
                observed_errors.append(error)
                raise

        with mock.patch.object(recorder.subprocess, "Popen", side_effect=launch):
            result = self.run_tool()
        self.assertEqual(len(observed_errors), 1)
        self.assertIsInstance(observed_errors[0], PermissionError)
        reason = str(observed_errors[0])
        self.assertEqual(result["state"], "finished")
        self.assertEqual(result["outcome"], "fail")
        self.assertEqual(result["reason"], reason)
        self.assertEqual(result["failures"][0]["reason"], reason)
        self.assertIs(result["process_started"], False)
        self.assertEqual(self.processes, [])
        self.assertEqual(len(result["children"]), 1)
        child = result["children"][0]
        self.assertIs(child["process_started"], False)
        self.assertIsNone(child["pid"])
        self.assertIsNone(child["process_group"])
        self.assertIsNone(child["exit_code"])
        self.assertIsNone(result["exit_code"])
        self.assertIsNone(result["output"])
        self.assertFalse(self.ready.exists())


if __name__ == "__main__":
    unittest.main()

# SPDX-License-Identifier: Apache-2.0
"""Independent controls for interrupted recorder children and cleanup errors."""

import os
import subprocess
import sys
import time
import unittest
from unittest import mock

import p06_dependency_record as recorder
import test_p06_dependency_record as recorder_fixture


class InterruptedChildReviewTests(unittest.TestCase):
    def test_interruption_survives_cleanup_failure_and_child_is_reaped(self):
        for failure in ("timeout", "terminate-error"):
            with self.subTest(failure=failure):
                self.check_interrupted_child(failure)

    def check_interrupted_child(self, failure):
        fixture = recorder_fixture.DependencyRecorderTests(methodName="runTest")
        fixture.setUp()
        processes = []
        original_popen = subprocess.Popen
        try:
            ready = fixture.roots["build"] / "ready.txt"
            tool = fixture.root / "waiting-archiver"
            tool.write_text("#!" + sys.executable + "\n"
                "import signal,time\nfrom pathlib import Path\n"
                "signal.signal(signal.SIGTERM,signal.SIG_IGN)\n"
                "Path(" + repr(str(ready)) + ").write_text('ready')\n"
                "time.sleep(30)\n")
            tool.chmod(0o755)
            fixture.config["tools"]["ar"] = recorder.file_identity(tool)
            fixture.write_config()
            source = fixture.roots["build"] / "input.o"
            source.write_bytes(b"synthetic archive input; interruption control only")
            output = fixture.roots["build"] / "libinput.a"

            def launch(*args, **kwargs):
                process = original_popen(*args, **kwargs)
                original_wait = process.wait
                processes.append((process, original_wait))
                first = True

                def wait(*wait_args, **wait_kwargs):
                    nonlocal first
                    if first:
                        first = False
                        limit = time.monotonic() + 3
                        while not ready.exists() and time.monotonic() < limit:
                            time.sleep(0.005)
                        if not ready.exists():
                            raise RuntimeError("child did not reach its ready state")
                        raise KeyboardInterrupt("review interruption")
                    return original_wait(*wait_args, **wait_kwargs)

                process.wait = wait
                if failure == "terminate-error":
                    def terminate():
                        raise OSError("termination monitor failed")
                    process.terminate = terminate
                return process

            with mock.patch.object(recorder.subprocess, "Popen", side_effect=launch):
                result = fixture.run_tool("ar", "archive", ["crs", str(output), str(source)])

            self.assertEqual(result["reason"], "review interruption")
            self.assertEqual(result["failures"][0]["reason"], "review interruption")
            expected = "timed out after" if failure == "timeout" else "termination monitor failed"
            self.assertTrue(any(expected in row["reason"] for row in result["failures"][1:]),
                            result["failures"])
            self.assertEqual(result["outcome"], "fail")
            self.assertEqual(result["state"], "finished")
            self.assertIs(result["process_started"], True)
            self.assertEqual(len(result["children"]), 1)
            child = result["children"][0]
            self.assertIs(child["process_started"], True)
            self.assertEqual(child["process_group"], os.getpgrp())
            self.assertIsNotNone(processes[0][0].poll(), "recorder returned with a live selected child")
            self.assertEqual(child["exit_code"], processes[0][0].returncode)
            self.assertEqual(result["exit_code"], child["exit_code"])
            self.assertLess(child["exit_code"], 0)
            self.assertIsNone(result["output"])
        finally:
            for process, original_wait in processes:
                if process.poll() is None:
                    process.kill()
                original_wait(timeout=3)
            fixture.doCleanups()


if __name__ == "__main__":
    unittest.main()

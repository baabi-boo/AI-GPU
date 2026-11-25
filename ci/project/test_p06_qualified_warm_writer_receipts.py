# SPDX-License-Identifier: Apache-2.0
"""Exercise the hosted writer guard with inert retained child receipts."""

from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

import p06_qualified_warm_hosted as hosted


CHILD_PATHS = {"preparation": "dependency-preparation.json",
               "dependency-build": "dependency-build/report.json",
               "qualified-warm": "qualified-warm/report.json"}
COMMAND_STAGES = ("dependency-build", "qualified-warm")


class HostedWriterReceiptTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.attempt = Path(self.directory.name)
        self.evidence = self.attempt / "workspace/evidence"
        self.outer = [{"id": "native-supervisor", "process_started": True, "cleanup_complete": True}]
        self.stages = [{"id": name, "report_path": path, "process_started": True,
                        "cleanup_complete": True} for name, path in CHILD_PATHS.items()]
        self.children = {"preparation": {"contract_id": hosted.preparation.CONTRACT_ID,
            "execution_origin": "local", "outcome": "pass", "native_execution": "not_run"}}
        for name in COMMAND_STAGES:
            self.children[name] = {"state": "finished", "commands": [
                {"id": "completed-command", "process_started": True, "cleanup_complete": True}]}
        self.write_supervisor(self.stages)
        for name, document in self.children.items():
            self.write_child(name, document)

    def write(self, path, document):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(document), encoding="utf-8")

    def write_supervisor(self, stages):
        self.write(self.evidence / "qualified-warm-run.json", {"state": "finished", "stages": stages})

    def write_child(self, name, document):
        self.write(self.evidence / CHILD_PATHS[name], document)

    def assert_child_finished(self, name, document, expected):
        self.write_child(name, document)
        try:
            self.assertIs(hosted.writers_finished(self.attempt, self.outer), expected)
        finally:
            self.write_child(name, self.children[name])

    def test_started_dependency_build_requires_explicit_commands(self):
        self.assert_child_finished("dependency-build", {"state": "finished"}, False)

    def test_started_qualified_warm_requires_explicit_commands(self):
        self.assert_child_finished("qualified-warm", {"state": "finished"}, False)

    def test_null_commands_are_rejected_for_every_started_child(self):
        for name in CHILD_PATHS:
            with self.subTest(stage=name):
                document = dict(self.children[name], commands=None)
                self.assert_child_finished(name, document, False)

    def test_nonlist_commands_are_rejected_for_every_started_child(self):
        for name in CHILD_PATHS:
            for commands in ({}, "", "commands", 0, False):
                with self.subTest(stage=name, commands=commands):
                    self.assert_child_finished(name, dict(self.children[name], commands=commands), False)

    def test_preparation_legitimately_omits_state_and_commands(self):
        self.assertNotIn("state", self.children["preparation"])
        self.assertNotIn("commands", self.children["preparation"])
        self.assertTrue(hosted.writers_finished(self.attempt, self.outer))

    def test_explicit_empty_command_lists_allow_finished_closeout(self):
        for name in CHILD_PATHS:
            with self.subTest(stage=name):
                self.assert_child_finished(name, dict(self.children[name], commands=[]), True)

    def test_completed_and_confirmed_prelaunch_commands_allow_closeout(self):
        for name in COMMAND_STAGES:
            with self.subTest(stage=name):
                document = deepcopy(self.children[name])
                document["commands"].append({"id": "blocked-command", "process_started": False,
                    "cleanup_complete": True, "outcome": "blocked", "reason": "disk_reserve"})
                self.assert_child_finished(name, document, True)

    def test_malformed_or_unresolved_command_receipts_fail_closed(self):
        for name in COMMAND_STAGES:
            for command in (None, "malformed", {}, {"process_started": None, "cleanup_complete": True},
                            {"process_started": True}, {"process_started": True, "cleanup_complete": False}):
                with self.subTest(stage=name, command=command):
                    self.assert_child_finished(name, dict(self.children[name], commands=[command]), False)

    def test_command_child_must_have_finished_state(self):
        for name in COMMAND_STAGES:
            for state in (None, "running"):
                with self.subTest(stage=name, state=state):
                    document = dict(self.children[name])
                    if state is None:
                        document.pop("state")
                    else:
                        document["state"] = state
                    self.assert_child_finished(name, document, False)

    def test_started_child_requires_retained_report(self):
        for name in CHILD_PATHS:
            with self.subTest(stage=name):
                (self.evidence / CHILD_PATHS[name]).unlink()
                self.assertFalse(hosted.writers_finished(self.attempt, self.outer))
            self.write_child(name, self.children[name])

    def test_confirmed_prelaunch_child_needs_no_retained_report(self):
        for name in CHILD_PATHS:
            with self.subTest(stage=name):
                stages = deepcopy(self.stages)
                row = next(row for row in stages if row["id"] == name)
                row.update(process_started=False, cleanup_complete=True, outcome="blocked", reason="disk_reserve")
                self.write_supervisor(stages)
                (self.evidence / CHILD_PATHS[name]).unlink()
                self.assertTrue(hosted.writers_finished(self.attempt, self.outer))
            self.write_child(name, self.children[name])

    def test_confirmed_prelaunch_outer_stage_requires_completed_cleanup(self):
        (self.evidence / "qualified-warm-run.json").unlink()
        for name in ("input-acquisition", "native-supervisor"):
            for cleanup in (True, False, None):
                with self.subTest(stage=name, cleanup=cleanup):
                    stages = [{"id": name, "process_started": False, "cleanup_complete": cleanup}]
                    self.assertIs(hosted.writers_finished(self.attempt, stages), cleanup is True)

    def test_unresolved_child_observation_cannot_authorize_closeout(self):
        for name in CHILD_PATHS:
            for started, cleanup in ((None, True), (True, None), (True, False)):
                with self.subTest(stage=name, started=started, cleanup=cleanup):
                    stages = deepcopy(self.stages)
                    row = next(row for row in stages if row["id"] == name)
                    row.update(process_started=started, cleanup_complete=cleanup)
                    self.write_supervisor(stages)
                    self.assertFalse(hosted.writers_finished(self.attempt, self.outer))


if __name__ == "__main__":
    unittest.main()

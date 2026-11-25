# SPDX-License-Identifier: Apache-2.0
"""Independent controls for contradictory recorded identities and paths."""

from pathlib import PurePosixPath
import unittest

import governance_replay_records as records
from test_governance_replay_records import REVISION, _bind_environment, records_fixture


class GovernanceReplayRecordControlsTests(unittest.TestCase):
    def test_requested_path_cannot_conflict_with_another_tools_resolved_path(self):
        started, summary, environment = records_fixture()
        raw = _bind_environment(started, summary, environment)
        records.validate_records(started, summary, environment,
                                 revision=REVISION, environment_bytes=raw)

        environment["cmake_selection"]["requested"]["path"] = environment["tools"]["gcc"]["resolved_path"]
        raw = _bind_environment(started, summary, environment)
        with self.assertRaisesRegex(ValueError, "requested/resolved tool identity"):
            records.validate_records(started, summary, environment,
                                     revision=REVISION, environment_bytes=raw)

    def test_run_output_cannot_overlap_known_prepared_inputs(self):
        for role in ("environment", "environment_parent", "venv", "environment.json", "gcc", "gcc_child"):
            with self.subTest(role=role):
                started, summary, environment = records_fixture()
                output = PurePosixPath(environment["output_dir"])
                if role == "environment":
                    selected = output
                elif role == "environment_parent":
                    selected = output.parent
                elif role == "gcc":
                    selected = PurePosixPath(environment["tools"]["gcc"]["path"])
                elif role == "gcc_child":
                    selected = PurePosixPath(environment["tools"]["gcc"]["resolved_path"]) / "child"
                else:
                    selected = output / role
                started["command"][3] = summary["command"][3] = str(selected)
                raw = _bind_environment(started, summary, environment)
                with self.assertRaisesRegex(ValueError, "run output overlaps a prepared input"):
                    records.validate_records(started, summary, environment,
                                             revision=REVISION, environment_bytes=raw)

    def test_fresh_run_output_below_prepared_directories_is_supported(self):
        for relative in ("new-run", "home/new-run", "probe-source/new-run", "probe-build", "probe32.so"):
            with self.subTest(relative=relative):
                started, summary, environment = records_fixture()
                started["command"][3] = summary["command"][3] = environment["output_dir"] + "/" + relative
                raw = _bind_environment(started, summary, environment)
                records.validate_records(started, summary, environment,
                                         revision=REVISION, environment_bytes=raw)


if __name__ == "__main__":
    unittest.main()

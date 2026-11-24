# SPDX-License-Identifier: Apache-2.0
"""Host-only receipt identity controls using inert synthetic installations."""

import copy
import json
import unittest

import p05_replay_installation as replay
from test_p05_replay_installation import SyntheticInstallation, encoded, record


def package_files(fixture, replacements):
    value = fixture.snapshot_value("python", fixture.pr, "package_tools_before")
    for name, rows in replacements.items():
        value["distributions"][name]["files"] = copy.deepcopy(rows)
    for when in ("before", "after"):
        fixture.snapshot("python", fixture.pr, "package_tools_" + when, value)
        fixture.put("python", "logs/package-tools-" + when + ".log", b"P05_PACKAGE_TOOLS " + encoded(value) + b"\n")


def tool_receipts(fixture, additions):
    value = fixture.snapshot_value("python", fixture.pr, "tools_before")
    value.update(additions)
    for when in ("before", "after"):
        fixture.snapshot("python", fixture.pr, "tools_" + when, value)


def transfer_files(fixture, source, destination, paths):
    value = fixture.snapshot_value("torch", fixture.tr, "framework_before")
    original = value["distributions"][source]["files"]
    selected = [row for row in original if row["path"] in paths]
    assert len(selected) == len(paths)
    value["distributions"][source]["files"] = [row for row in original if row["path"] not in paths]
    value["distributions"][destination]["files"] += selected
    raw = json.loads(fixture.files["torch/logs/framework-environment-before.log"].split(b" ", 1)[1])
    for name, distribution in value["distributions"].items():
        distribution["files"].sort(key=lambda row: row["path"].removeprefix(replay.SITE)
                                   if row["path"].startswith(replay.SITE) else "../../../" + row["path"])
        raw["distributions"][name]["files"] = [row["path"].removeprefix(replay.SITE)
            if row["path"].startswith(replay.SITE) else "../../../" + row["path"] for row in distribution["files"]]
    for when in ("before", "after"):
        fixture.snapshot("torch", fixture.tr, "framework_" + when, value)
        fixture.put("torch", "logs/framework-environment-" + when + ".log", b"P05_TORCH_ENVIRONMENT " + encoded(raw) + b"\n")


class InstallationIdentityTests(unittest.TestCase):
    def test_complete_positive_preserves_missing_byte_limits(self):
        summary = SyntheticInstallation().run()["summary"]
        self.assertEqual(summary["scope"], "retained-installation-consistency")
        self.assertEqual(summary["native_execution"], "not_run")
        for field in ("third_party_bytes_rehashed", "interpreter_bytes_rehashed", "retained_code_executed",
                      "acceptance_claimed", "phase_acceptance"):
            self.assertIs(summary[field], False)
        self.assertEqual(len(summary["limitations"]), 7)

    def test_package_file_cannot_contradict_interpreter_or_copied_path(self):
        for receipt in ("provisioning", "python_venv", "torch_venv"):
            for key in ("path", "resolved_path"):
                for field, replacement in (("sha256", "0" * 64), ("size_bytes", 1)):
                    with self.subTest(receipt=receipt, key=key, field=field):
                        fixture = SyntheticInstallation()
                        identity = {"provisioning": fixture.tr["provisioning_interpreter"],
                                    "python_venv": fixture.pr["venv_interpreter"],
                                    "torch_venv": fixture.tr["venv_interpreter"]}[receipt]
                        row = {"path": identity[key], "sha256": identity["sha256"], "size_bytes": identity["size_bytes"]}
                        row[field] = replacement
                        package_files(fixture, {"setuptools": [row]})
                        with self.assertRaisesRegex(ValueError, "recorded file identity"):
                            fixture.run()

    def test_package_file_cannot_contradict_other_tool_alias(self):
        for key in ("path", "resolved_path"):
            with self.subTest(key=key):
                fixture = SyntheticInstallation()
                tool = {**record("/producer/bin/make", b"Absent make"), "resolved_path": "/producer/tools/make"}
                tool_receipts(fixture, {"make": tool})
                package_files(fixture, {"wheel": [{"path": tool[key], "sha256": "0" * 64, "size_bytes": tool["size_bytes"]}]})
                with self.assertRaisesRegex(ValueError, "recorded file identity"):
                    fixture.run()

    def test_executable_aliases_cannot_contradict_each_other(self):
        for key in ("path", "resolved_path"):
            for target in ("path", "resolved_path"):
                with self.subTest(key=key, target=target):
                    fixture = SyntheticInstallation()
                    tool = {**record("/producer/bin/make", b"Absent make"), "resolved_path": "/producer/tools/make"}
                    tool[key] = fixture.tr["provisioning_interpreter"][target]
                    tool_receipts(fixture, {"make": tool})
                    with self.assertRaisesRegex(ValueError, "recorded file identity"):
                        fixture.run()

    def test_package_distributions_cannot_disagree_on_shared_path(self):
        for field, replacement in (("sha256", "0" * 64), ("size_bytes", 1)):
            with self.subTest(field=field):
                fixture = SyntheticInstallation()
                row = record("/producer/shared/prerequisite", b"Absent shared prerequisite")
                package_files(fixture, {"wheel": [row], "setuptools": [{**row, field: replacement}]})
                with self.assertRaisesRegex(ValueError, "recorded file identity"):
                    fixture.run()

    def test_consistent_shared_paths_and_resolved_aliases_remain_valid(self):
        fixture = SyntheticInstallation()
        identity = fixture.tr["provisioning_interpreter"]
        tool_receipts(fixture, {"make": {**identity, "path": "/producer/bin/identical-tool"}})
        rows = [{"path": identity[key], "sha256": identity["sha256"], "size_bytes": identity["size_bytes"]}
                for key in ("path", "resolved_path")]
        package_files(fixture, {name: rows for name in ("setuptools", "wheel", "packaging")})
        self.assertEqual(fixture.run()["summary"]["scope"], "retained-installation-consistency")

    def test_first_party_membership_cannot_move_to_torch(self):
        for leaf in ("vortex_ai/torch_ops.py", replay.DIST + "METADATA", replay.DIST + "RECORD",
                     replay.DIST + "direct_url.json", "all_but_one"):
            with self.subTest(leaf=leaf):
                fixture = SyntheticInstallation()
                value = fixture.snapshot_value("torch", fixture.tr, "framework_before")
                paths = ({row["path"] for row in value["distributions"]["vortex_ai"]["files"][1:]}
                         if leaf == "all_but_one" else {replay.SITE + leaf})
                transfer_files(fixture, "vortex_ai", "torch", paths)
                with self.assertRaisesRegex(ValueError, "first-party distribution membership"):
                    fixture.run()

    def test_first_party_membership_cannot_absorb_third_party_or_seed(self):
        for source, path in (("torch", replay.SITE + "torch/lib/libtorch_cpu.so"), ("pip", "bin/pip")):
            with self.subTest(source=source):
                fixture = SyntheticInstallation()
                transfer_files(fixture, source, "vortex_ai", {path})
                with self.assertRaisesRegex(ValueError, "first-party distribution membership"):
                    fixture.run()


if __name__ == "__main__":
    unittest.main()

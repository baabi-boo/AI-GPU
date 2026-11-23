# SPDX-License-Identifier: Apache-2.0
"""Independent same-record shell-boundary checks for application replay."""

from copy import deepcopy
import unittest

from p06_managed_preflight_application_build import RECIPE_SHA256, validate_application_build
from p06_managed_preflight_replay_test_support import Packet, PREFIX


class ApplicationShellBoundaryReviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with Packet() as packet:
            report = packet.report
            variant = report["variants"][0]
            command = next(row for row in report["commands"]
                           if row["id"] == variant["application_build_command"])
            cls.original = packet[PREFIX + command["log"]].decode("utf-8")
            cls.recipes = {name: packet[PREFIX + "artifacts/source/" + name]
                           for name in RECIPE_SHA256}
            cls.arguments = {
                "stamp": packet[PREFIX + "artifacts/" + variant["id"]
                    + "/frozen/tests/regression/ai_counter_preflight/config.stamp"].decode("utf-8"),
                "source": report["paths"]["source"], "build": variant["build_dir"],
                "tools_root": report["paths"]["tools"],
                "tools": packet.json(report["tools_before"]["path"]),
                "fmt": variant["format"], "compiler_records": variant["compiler_records"],
            }

    def check_mutation(self, index, transform):
        lines = self.original.splitlines()
        lines[index] = transform(lines[index])
        text = "\n".join(lines) + "\n"
        self.assertEqual(len([line for line in text.splitlines() if line.strip()]), 30)
        with self.assertRaisesRegex(ValueError, "unsupported or altered command at record " + str(index + 1)):
            validate_application_build(text, source_body=self.recipes.__getitem__, **self.arguments)

    def test_shell_operators_cannot_hide_in_same_record_spacing(self):
        suffixes = (
            "\t;\t/usr/bin/true", " \t&&\t/usr/bin/true", " \t||\t/usr/bin/true",
            " \t|\t/usr/bin/true", "\t&\t/usr/bin/true", "\t# unrecorded annotation",
        )
        for index in (0, 1, 3, 17, 19, 21, 24, 26, 27, 28, 29):
            for suffix in suffixes:
                with self.subTest(record=index + 1, suffix=suffix):
                    self.check_mutation(index, lambda line: line.rstrip(";") + suffix)

    def test_hidden_prefix_execution_cannot_preserve_thirty_records(self):
        prefixes = (
            "/usr/bin/true;\t", ":;\t", "LD_PRELOAD=/tmp/foreign.so\t",
            "$(/usr/bin/true)\t", chr(96) + "/usr/bin/true" + chr(96) + "\t",
        )
        for index in (1, 24, 28):
            for prefix in prefixes:
                with self.subTest(record=index + 1, prefix=prefix):
                    self.check_mutation(index, lambda line: prefix + line)
        before = deepcopy(self.arguments)
        receipt = validate_application_build(self.original,
            source_body=self.recipes.__getitem__, **self.arguments)
        self.assertEqual(receipt["command_count"], 30)
        self.assertEqual(self.arguments, before)


if __name__ == "__main__":
    unittest.main()

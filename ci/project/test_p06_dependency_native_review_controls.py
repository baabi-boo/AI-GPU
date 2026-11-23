# SPDX-License-Identifier: Apache-2.0
"""Host controls for lexical linker paths; synthetic receipt admission only."""

import posixpath
import unittest

import p06_dependency_admission as admission
import test_p06_dependency_admission as admission_tests


class ModelMapPathAliasControls(unittest.TestCase):
    def setUp(self):
        self.fixture = admission_tests.AdmissionLiveChecks("test_exact_model_member_object_and_product_join")
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.setUp()
        self.checked = self.fixture.inputs.admit()
        self.work = self.fixture.source.parent / "work"
        self.build = self.work / "simx-fp16"
        self.build.mkdir(parents=True)
        self.records = self.fixture.inputs.model(self.build)
        self.path = self.build / admission.MODEL_MAP
        self.original = self.path.read_text()
        self.cwd = str(self.build / "sim/simx")
        self.checked.validate_model(self.build, self.records)

    def relative(self, path):
        return posixpath.relpath(str(path), self.cwd)

    def test_selected_loads_can_use_equivalent_relative_spellings(self):
        lines = self.original.splitlines()
        for index, line in enumerate(lines):
            if line.startswith("LOAD "):
                lines[index] = "LOAD ./" + self.relative(line[5:])
        self.path.write_text("\n".join(lines) + "\n")
        result = self.checked.validate_model(self.build, self.records)
        self.assertTrue(result["source_to_model_link_verified"])
        self.assertEqual(len(result["objects"]), 43)

    def test_relative_source_and_other_format_inputs_cannot_evade_the_load_gate(self):
        for path in (self.work / "simx-bf16/sw/runtime/unplanned.o",
                     self.fixture.source / "third_party/unplanned.so"):
            for spelling in (self.relative(path), "./" + self.relative(path),
                             self.relative(path).replace("/", "//")):
                with self.subTest(spelling=spelling):
                    self.path.write_text(self.original + "LOAD " + spelling + "\n")
                    with self.assertRaisesRegex(ValueError, "unplanned source/work input"):
                        self.checked.validate_model(self.build, self.records)

    def test_relative_alias_cannot_hide_a_duplicate_selected_object(self):
        self.path.write_text(self.original + "LOAD ./" + self.relative(
            self.records["object_paths"][0]) + "\n")
        with self.assertRaisesRegex(ValueError, "lacks an exact production object load"):
            self.checked.validate_model(self.build, self.records)


if __name__ == "__main__":
    unittest.main()

# SPDX-License-Identifier: Apache-2.0
"""Exercise repeated GCC prerequisites with actual children and inert receipts."""

from copy import deepcopy
import hashlib
import os
from pathlib import Path
import unittest
from unittest import mock

import p06_dependency_build as builder
import p06_dependency_receipt as receipt
import p06_dependency_record as recorder
import test_p06_dependency_record as record_tests


GCC_DEPENDENCIES = rb"""/workspace/p06-host-diagnostic-5527-03/dependency-sources/softfloat/build/Linux-x86_64-GCC/s_shortShiftLeft128.o: \
 ../../source/s_shortShiftLeft128.c /usr/include/stdc-predef.h \
 /usr/lib/gcc/x86_64-linux-gnu/14/include/stdint.h /usr/include/stdint.h \
 /usr/include/x86_64-linux-gnu/bits/libc-header-start.h \
 /usr/include/features.h /usr/include/features-time64.h \
 /usr/include/x86_64-linux-gnu/bits/wordsize.h \
 /usr/include/x86_64-linux-gnu/bits/timesize.h \
 /usr/include/x86_64-linux-gnu/sys/cdefs.h \
 /usr/include/x86_64-linux-gnu/bits/long-double.h \
 /usr/include/x86_64-linux-gnu/gnu/stubs.h \
 /usr/include/x86_64-linux-gnu/gnu/stubs-64.h \
 /usr/include/x86_64-linux-gnu/bits/types.h \
 /usr/include/x86_64-linux-gnu/bits/typesizes.h \
 /usr/include/x86_64-linux-gnu/bits/time64.h \
 /usr/include/x86_64-linux-gnu/bits/wchar.h \
 /usr/include/x86_64-linux-gnu/bits/stdint-intn.h \
 /usr/include/x86_64-linux-gnu/bits/stdint-uintn.h \
 /usr/include/x86_64-linux-gnu/bits/stdint-least.h platform.h \
 ../../source/include/opts-GCC.h ../../source/include/primitiveTypes.h \
 ../../source/include/primitiveTypes.h
"""


def prerequisites(body):
    return body.decode("utf-8").replace("\\\n", " ").split(":", 1)[1].split()


def populate(fixture):
    includes = fixture.roots["sources"] / "include"
    includes.mkdir()
    selected = includes / "selected.h"
    selected.write_text("#define SELECTED_VALUE 37\n")
    (includes / "bridge.h").write_text('#include "selected.h"\n')
    (includes / "extra.h").write_text("#define EXTRA_VALUE 1\n")
    fixture.source.write_text('#include "bridge.h"\n#include "selected.h"\n'
                              'int sample(void) { return SELECTED_VALUE; }\n')
    arguments = ["-fPIC", "-I", str(includes), "-c", str(fixture.source), "-o", str(fixture.output)]
    return selected, arguments


class RepeatedPrerequisiteParserTests(unittest.TestCase):
    def test_retained_gcc_prerequisites_replay_without_recorded_files(self):
        self.assertEqual(hashlib.sha256(GCC_DEPENDENCIES).hexdigest(),
                         "db6caaf93bafa268d5c32322b87e005f8094957f10033bcb69ecdd5060bae7e8")
        target = Path(GCC_DEPENDENCIES.decode().split(":", 1)[0])
        with mock.patch.object(Path, "open", side_effect=AssertionError("recorded file access forbidden")), \
                mock.patch.object(Path, "resolve", side_effect=AssertionError("recorded resolution forbidden")):
            selected = recorder.dependency_paths(GCC_DEPENDENCIES, target=target, cwd=target.parent)
        self.assertEqual(len(prerequisites(GCC_DEPENDENCIES)), 24)
        self.assertEqual(len(selected), 23)
        self.assertEqual(sum(path.name == "primitiveTypes.h" for path in selected), 1)
        self.assertEqual(selected[0], target.parent.parent.parent / "source/s_shortShiftLeft128.c")

    def test_raw_prerequisite_count_remains_bounded_before_deduplication(self):
        target, cwd = Path("/fixture/sample.o"), Path("/fixture")
        body = b"sample.o: " + b"header.h " * recorder.MAX_INPUTS
        self.assertEqual(recorder.dependency_paths(body, target=target, cwd=cwd), [cwd / "header.h"])
        for changed in (body + b"header.h", b"sample.o:\n"):
            with self.subTest(size=len(changed)), self.assertRaisesRegex(recorder.RecorderError, "empty or oversized"):
                recorder.dependency_paths(changed, target=target, cwd=cwd)


class ActualRepeatedPrerequisiteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixture = record_tests.DependencyRecorderTests()
        fixture.setUp()
        cls.addClassCleanup(fixture.doCleanups)
        cls.header, arguments = populate(fixture)
        with mock.patch.dict(os.environ, builder.clean_environment(fixture.roots["build"]), clear=True):
            cls.record = fixture.compile(arguments)
        if cls.record["outcome"] != "pass":
            raise AssertionError(cls.record["reason"])
        cls.config, cls.config_sha256 = deepcopy(fixture.config), fixture.config_sha256
        cls.payloads = {"payloads/" + path.name: path.read_bytes()
                        for path in fixture.roots["payloads"].glob("*.bin")}
        cls.recorder_identity = recorder.file_identity(recorder.__file__)
        cls.producer_root = fixture.root
        cls.raw_dependencies = {field: Path(cls.record[field]["path"]).read_bytes()
                                for field in ("dependency_prepass_file", "dependency_file")}
        fixture.doCleanups()

    def verify(self, record, payloads=None):
        return receipt._validate_record(record, self.config, self.config_sha256,
            (self.payloads if payloads is None else payloads).__getitem__, self.recorder_identity)

    def test_real_compiler_retains_repeated_raw_headers_and_unique_stable_inputs(self):
        self.assertFalse(self.producer_root.exists())
        record = self.record
        self.assertTrue(all(child["process_started"] and child["exit_code"] == 0
                            for child in record["children"]))
        self.assertEqual([child["stage"] for child in record["children"]], ["dependencies", "tool"])
        self.assertEqual(record["inputs_before"], record["inputs_after"])
        paths = [item["path"] for item in record["inputs_before"]]
        self.assertEqual(paths.count(str(self.header)), 1)
        self.assertEqual(len(paths), len(set(paths)))
        for field, raw in self.raw_dependencies.items():
            descriptor = record[field]
            self.assertEqual(prerequisites(raw).count(str(self.header)), 2)
            self.assertEqual(raw, self.payloads["payloads/" + descriptor["payload"]])
            self.assertEqual(hashlib.sha256(raw).hexdigest(), descriptor["sha256"])
            self.assertEqual(len(raw), descriptor["size_bytes"])
        with mock.patch("subprocess.Popen", side_effect=AssertionError("retained execution forbidden")), \
                mock.patch.object(Path, "open", side_effect=AssertionError("producer file access forbidden")), \
                mock.patch.object(Path, "resolve", side_effect=AssertionError("producer resolution forbidden")):
            self.assertEqual(self.verify(record), record)

    def test_rehashed_added_removed_and_reordered_depfile_inputs_reject(self):
        for field in self.raw_dependencies:
            original = prerequisites(self.raw_dependencies[field])
            cases = {"added": [*original, str(self.header.parent / "extra.h")],
                     "removed": [name for name in original if name != str(self.header)],
                     "reordered": [original[1], original[0], *original[2:]]}
            for mode, names in cases.items():
                value, payloads = deepcopy(self.record), dict(self.payloads)
                body = (value["output_path"] + ": " + " ".join(names) + "\n").encode()
                digest = hashlib.sha256(body).hexdigest()
                payloads["payloads/" + digest + ".bin"] = body
                value[field].update(sha256=digest, size_bytes=len(body), payload=digest + ".bin")
                with self.subTest(field=field, mode=mode), self.assertRaisesRegex(ValueError, "included-input closure"):
                    self.verify(value, payloads)

    def test_duplicate_receipt_input_rows_still_reject(self):
        value = deepcopy(self.record)
        for key in ("inputs_before", "inputs_after"):
            value[key].append(deepcopy(value[key][-1]))
        with self.assertRaisesRegex(ValueError, "input inventory contains duplicates"):
            self.verify(value)

    def test_actual_compile_input_changes_after_prepass_remain_failures(self):
        function = 'int sample(void) { return SELECTED_VALUE; }\n'
        cases = {"added": '#include "bridge.h"\n#include "selected.h"\n#include "extra.h"\n',
                 "removed": '#include "selected.h"\n',
                 "reordered": '#include "selected.h"\n#include "bridge.h"\n'}
        for mode, includes in cases.items():
            with self.subTest(mode=mode):
                fixture = record_tests.DependencyRecorderTests()
                fixture.setUp()
                try:
                    _, arguments = populate(fixture)
                    actual_popen = recorder.subprocess.Popen

                    def launch(argv, *args, **kwargs):
                        if "-c" in argv and "-M" not in argv:
                            fixture.source.write_text(includes + function)
                        return actual_popen(argv, *args, **kwargs)

                    with mock.patch.object(recorder.subprocess, "Popen", side_effect=launch):
                        result = fixture.compile(arguments)
                    self.assertEqual(result["outcome"], "fail")
                    self.assertEqual(result["reason"], "included-input set changed during compilation")
                    self.assertIs(result["process_started"], True)
                    self.assertIsNotNone(result["output"])
                    self.assertTrue(all(child["exit_code"] == 0 for child in result["children"]))
                finally:
                    fixture.doCleanups()


if __name__ == "__main__":
    unittest.main()

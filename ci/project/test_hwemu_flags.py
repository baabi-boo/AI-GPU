# SPDX-License-Identifier: Apache-2.0
"""Adversarial effective-flag checks using synthetic generated build inputs."""

from contextlib import contextmanager
import unittest

from hwemu_build import check_build
from hwemu_fixture import HwemuFixture
from hwemu_io import Inputs


REQUIRED = (
    "-DVX_CFG_NUM_CLUSTERS=1", "-DVX_CFG_NUM_CORES=1",
    "-DVX_CFG_NUM_WARPS=4", "-DVX_CFG_NUM_THREADS=4",
    "-DVX_CFG_ISSUE_WIDTH=1", "-DVX_CFG_FPU_TYPE_STD",
    "-DVX_CFG_XLEN=64", "-DVX_CFG_XLEN_64",
)


class EffectiveHwemuFlagTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = HwemuFixture()
        cls.addClassCleanup(cls.fixture.close)

    def compile_records(self):
        return (
            (self.fixture.build / "sw/runtime/xrt_config.stamp", 0),
            (self.fixture.build / "tests/regression/demo/config.stamp", 0),
            (self.fixture.build / "tests/regression/demo/config.stamp", 1),
        )

    @contextmanager
    def changed_record(self, path, index, transform):
        original = path.read_bytes()
        lines = original.decode("utf-8").splitlines()
        lines[index] = transform(lines[index])
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        try:
            yield
        finally:
            path.write_bytes(original)

    def check(self):
        with Inputs() as inputs:
            result = check_build(inputs, self.fixture.manifest)
            inputs.recheck()
            return result

    def reject_record(self, path, index, transform):
        with self.changed_record(path, index, transform), self.assertRaises(ValueError):
            self.check()

    def reject_compile_suffixes(self, suffixes):
        for path, index in self.compile_records():
            for suffix in suffixes:
                with self.subTest(stamp=str(path.relative_to(self.fixture.build)),
                                  record=index, suffix=suffix):
                    self.reject_record(path, index, lambda line: line + " " + suffix)

    def test_every_required_macro_must_be_effective_in_each_compiler_record(self):
        for path, index in self.compile_records():
            for macro in REQUIRED:
                for prefix in ("-I ", "-Wp,-MD,", "-Xpreprocessor -MQ -Xpreprocessor "):
                    with self.subTest(stamp=str(path.relative_to(self.fixture.build)),
                                      record=index, macro=macro, prefix=prefix):
                        self.reject_record(path, index, lambda line: line.replace(
                            macro, prefix + macro))

    def test_comments_cannot_supply_any_compiler_configuration(self):
        for path, index in self.compile_records():
            for prefix in ("# ", "-O2 # "):
                with self.subTest(stamp=str(path.relative_to(self.fixture.build)),
                                  record=index, prefix=prefix):
                    self.reject_record(path, index, lambda line: prefix + line)

    def test_required_values_cannot_be_zero_or_empty(self):
        for path, index in self.compile_records():
            for macro in REQUIRED:
                for value in ("0", ""):
                    replacement = macro.partition("=")[0] + "=" + value
                    with self.subTest(stamp=str(path.relative_to(self.fixture.build)),
                                      record=index, macro=macro, value=value):
                        self.reject_record(path, index, lambda line: line.replace(
                            macro, replacement))

    def test_forwarded_macros_cannot_override_or_undefine_frozen_fields(self):
        flags = (
            "-DVX_CFG_NUM_THREADS=8", "-DVX_CFG_XLEN=32", "-DVX_CFG_XLEN_32=0",
            "-DVX_CFG_FPU_TYPE_DPI=0", "-DVX_CFG_FPU_TYPE=DPI",
            "-DVX_CFG_TCU_TYPE_DPI=0", "-DVX_CFG_TCU_TYPE=DPI",
            "-UVX_CFG_NUM_CORES", "-UVX_CFG_XLEN_64",
        )
        self.reject_compile_suffixes(tuple(
            forwarded for flag in flags for forwarded in (
                "-Wp," + flag[:2] + "," + flag[2:],
                "-Xpreprocessor " + flag[:2] + " -Xpreprocessor " + flag[2:],
            )
        ))

    def test_compiler_records_reject_opaque_option_sources_and_unknown_transports(self):
        self.reject_compile_suffixes((
            "-include unretained.h", "-imacros unretained.h",
            "-specs=unretained.specs", "--config=unretained.cfg",
            "-Wp,@unretained.rsp", "-Xpreprocessor @unretained.rsp",
            "-Wp,-include,unretained.h",
            "-Xpreprocessor -imacros -Xpreprocessor unretained.h",
            "-Wp,--unrecognized-option,-DVX_CFG_NUM_THREADS=4",
            "-Xpreprocessor --unrecognized-option",
            "-Xlinker @unretained.rsp",
        ))

    def test_genuine_split_quoted_and_forwarded_configuration_remains_valid(self):
        forms = (
            lambda macro: "-D " + macro[2:],
            lambda macro: "'" + macro + "'",
            lambda macro: "-Wp,-D," + macro[2:],
            lambda macro: "-Xpreprocessor -D -Xpreprocessor " + macro[2:],
        )
        harmless = (
            " -I -DVX_CFG_XLEN_32=0 -MF -UVX_CFG_XLEN_64"
            " -Wp,-I,-DVX_CFG_FPU_TYPE_DPI=0"
            " -Xpreprocessor -MQ -Xpreprocessor -DVX_CFG_NUM_THREADS=8"
            " -D VX_CFG_XLEN=64 -D VX_CFG_FPU_TYPE_STD=1"
        )
        for path, index in self.compile_records():
            for form_index, form in enumerate(forms):
                with self.subTest(stamp=str(path.relative_to(self.fixture.build)),
                                  record=index, form=form_index):
                    def transform(line):
                        return " ".join(form(word) if word in REQUIRED else word
                                        for word in line.split()) + harmless
                    with self.changed_record(path, index, transform):
                        self.assertIsNone(self.check())

    def test_linker_rejects_shell_normalized_shim_names(self):
        path = self.fixture.build / "tests/regression/demo/config.stamp"
        for suffix in (
            r"-l xrt\sim", '-l xrt""sim',
            r"-Xlinker -lxrt\sim", '-Xlinker -lxrt""sim',
            r"-Xlinker -l -Xlinker xrt\sim",
            '-Xlinker --library=xrt""sim',
            r"/unretained/libxrt\sim.so", '/unretained/libxrt""sim.so',
        ):
            with self.subTest(suffix=suffix):
                self.reject_record(path, 2, lambda line: line + " " + suffix)

    def test_linker_rejects_opaque_and_forwarded_options(self):
        path = self.fixture.build / "tests/regression/demo/config.stamp"
        for suffix in (
            "-T unretained.ld", "-Xlinker --script=unretained.ld",
            "-Xlinker -T -Xlinker unretained.ld",
            "-Xlinker --default-script=unretained.ld",
            "-Xlinker --plugin=unretained.so", "-Xlinker --unrecognized-option",
            "-Xlinker @unretained.rsp", "-Wl,@unretained.rsp",
            "-Xlinker --as-needed", "-Xlinker -z -Xlinker now",
            "-LDFLAGS '-T unretained.ld'", "-Wl,-T,unretained.ld",
        ):
            with self.subTest(suffix=suffix):
                self.reject_record(path, 2, lambda line: line + " " + suffix)

    def test_linker_requires_exact_bound_runtime_search_and_vortex_library(self):
        path = self.fixture.build / "tests/regression/demo/config.stamp"
        search = "-L" + str(self.fixture.build / "sw/runtime")
        for replacement in (
            "-lvortex", search, search + " -lother",
            "-L/foreign/runtime -lvortex", "-L/foreign/runtime " + search + " -lvortex",
            search + " -lvortex -lvortex", search + " -lvortex unrelated.o",
            "# " + search + " -lvortex",
        ):
            with self.subTest(replacement=replacement):
                self.reject_record(path, 2, lambda _line: replacement)

    def test_canonical_linker_words_allow_shell_equivalent_quoting(self):
        path = self.fixture.build / "tests/regression/demo/config.stamp"
        search = "-L" + str(self.fixture.build / "sw/runtime")
        for replacement in (
            "'" + search + "' '-lvortex'",
            '"' + search + '" -lvort""ex',
            search + r" -lvor\tex",
        ):
            with self.subTest(replacement=replacement):
                with self.changed_record(path, 2, lambda _line: replacement):
                    self.assertIsNone(self.check())


if __name__ == "__main__":
    unittest.main()

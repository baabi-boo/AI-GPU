# SPDX-License-Identifier: Apache-2.0
"""Independently reject inconsistent generated vendor-emulation inputs."""

from contextlib import contextmanager
from copy import deepcopy
import hashlib
import unittest
from unittest import mock

from hwemu_build import check_build
from hwemu_fixture import HwemuFixture
from hwemu_io import Inputs


COPIED_PATHS = (
    "config.mk", "ci/blackbox.sh", "ci/gen_config.py", "sw/kernel/Makefile",
    "sw/runtime/stub/Makefile", "sw/runtime/common.mk", "sw/runtime/xrt/Makefile",
    "sw/runtime/xrt/xrt.ini", "tests/regression/demo/Makefile",
    "tests/regression/common.mk", "hw/syn/xilinx/xrt/Makefile",
    "hw/syn/xilinx/common.mk", "hw/syn/xilinx/platform.mk",
)
HEADER_PATHS = (
    "sw/VX_config.h", "sw/VX_types.h", "hw/VX_config.vh", "hw/VX_types.vh",
)


class GeneratedBuildContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = HwemuFixture()
        cls.addClassCleanup(cls.fixture.close)

    @contextmanager
    def changed(self, path, content):
        original = path.read_bytes()
        path.write_bytes(content.encode("utf-8") if isinstance(content, str) else content)
        try:
            yield
        finally:
            path.write_bytes(original)

    def check(self, manifest=None):
        with Inputs() as inputs:
            result = check_build(inputs, self.fixture.manifest if manifest is None else manifest)
            inputs.recheck()
            return result

    def assert_rejected(self, path, content):
        with self.changed(path, content), self.assertRaises(ValueError):
            self.check()

    def compile_records(self):
        return (
            (self.fixture.build / "sw/runtime/xrt_config.stamp", 0),
            (self.fixture.build / "tests/regression/demo/config.stamp", 0),
            (self.fixture.build / "tests/regression/demo/config.stamp", 1),
        )

    def replace_record(self, path, index, transform):
        lines = path.read_text(encoding="utf-8").splitlines()
        lines[index] = transform(lines[index])
        return "\n".join(lines) + "\n"

    def test_fresh_build_passes_without_mutating_manifest_or_inputs(self):
        manifest = deepcopy(self.fixture.manifest)
        paths = [self.fixture.build / item for item in (*COPIED_PATHS, *HEADER_PATHS)]
        paths.extend((self.fixture.source / "VERSION", self.fixture.build / ".config.stamp"))
        before = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}
        with mock.patch("subprocess.Popen", side_effect=AssertionError("must remain inert")):
            self.assertIsNone(self.check())
        self.assertEqual(self.fixture.manifest, manifest)
        self.assertEqual(before, {
            str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths
        })

    def test_every_generated_recipe_is_compared_to_its_source(self):
        for relative in COPIED_PATHS:
            path = self.fixture.build / relative
            with self.subTest(path=relative):
                self.assert_rejected(path, path.read_bytes() + b"\n# stale copy\n")

    def test_configure_bindings_cannot_point_to_different_inputs(self):
        path = self.fixture.build / ".config.stamp"
        original = path.read_text(encoding="utf-8")
        values = dict(token.split("=", 1) for token in original.split())
        replacements = {
            "XLEN": "32", "PROFILE": "ai-dev", "OSVERSION": "ubuntu/other",
            "TOOLDIR": "/different/tools", "SOURCE_DIR": "/different/source",
            "BUILDDIR": "/different/build", "PREFIX": "/different/install",
            "VORTEX_VERSION": "99.0", "TOOLCHAIN_REV": "different",
            "GEM5_REV": "different", "FIRESIM_REV": "different",
        }
        for key, value in replacements.items():
            with self.subTest(field=key):
                changed = dict(values, **{key: value})
                self.assert_rejected(path, " ".join(k + "=" + v for k, v in changed.items()))

    def test_configure_stamp_rejects_missing_duplicate_unknown_and_nul_fields(self):
        path = self.fixture.build / ".config.stamp"
        original = path.read_text(encoding="utf-8")
        for text in (" ".join(original.split()[1:]), original + " XLEN=64",
                     original + " UNKNOWN=value", original + "\0"):
            with self.subTest(text=text[-25:]):
                self.assert_rejected(path, text)

    def test_source_pin_inventory_rejects_ambiguous_or_unsupported_fields(self):
        path = self.fixture.source / "VERSION"
        original = path.read_text(encoding="utf-8")
        pins = [line for line in original.splitlines() if line and not line.startswith("#")]
        for text in (original + "\n" + pins[0], original + "\nUNKNOWN=1\n",
                     "\n".join(pins[1:]), original.replace("v3.0.2", "$(unsafe)")):
            with self.subTest(text=text[-30:]):
                self.assertNotEqual(original, text)
                self.assert_rejected(path, text)

    def test_generated_ini_is_screened_even_when_source_template_matches(self):
        source = self.fixture.source / "sw/runtime/xrt/xrt.ini.in"
        generated = self.fixture.build / "sw/runtime/xrt/xrt.ini"
        template = source.read_text(encoding="utf-8")
        mutations = (
            template.replace("/sw/runtime/xrt/xsim.tcl", "/runtime/xrt/xsim.tcl"),
            "\n".join(line for line in template.splitlines()
                      if not line.startswith("user_pre_sim_script=")),
            template.replace("debug_mode=off", "debug_mode=batch"),
            template.replace("profile=false", "profile=true"),
            template.replace("timeline_trace=false", "timeline_trace=true"),
            template.replace("data_transfer_trace=off", "data_transfer_trace=fine"),
            template + "\n[DEFAULT]\nprofile=false\n",
            template + "\n[Unsupported]\nmode=1\n",
            template + "\n[Debug]\nprofile=false\n",
        )
        for index, changed in enumerate(mutations):
            with self.subTest(case=index):
                self.assertNotEqual(changed, template)
                generated_text = changed.replace("@VORTEX_HOME@", str(self.fixture.source))
                with self.changed(source, changed), self.changed(generated, generated_text):
                    with self.assertRaises(ValueError):
                        self.check()

    def test_template_must_not_leave_unknown_substitutions(self):
        source = self.fixture.source / "config.mk.in"
        generated = self.fixture.build / "config.mk"
        with self.changed(source, source.read_bytes() + b"\n# @UNKNOWN_PIN@\n"), \
                self.changed(generated, generated.read_bytes() + b"\n# @UNKNOWN_PIN@\n"):
            with self.assertRaises(ValueError):
                self.check()

    def test_generated_headers_accept_external_xlen_but_reject_local_overrides(self):
        self.assertIsNone(self.check())
        for relative in HEADER_PATHS:
            path = self.fixture.build / relative
            original = path.read_bytes()
            marker = b"#" if relative.endswith(".h") else b"`"
            for directive in (b"define VX_CFG_XLEN 32", b"define VX_CFG_XLEN_32 1",
                              b"undef VX_CFG_XLEN_64"):
                with self.subTest(path=relative, directive=directive):
                    self.assert_rejected(path, original + b"\n" + marker + directive + b"\n")

    def test_generated_headers_reject_empty_or_nul_content(self):
        for relative in HEADER_PATHS:
            path = self.fixture.build / relative
            for content in (b"", b" \n", b"content\0"):
                with self.subTest(path=relative, content=content):
                    self.assert_rejected(path, content)

    def test_each_compilation_record_requires_every_frozen_macro(self):
        required = (
            "-DVX_CFG_NUM_CLUSTERS=1", "-DVX_CFG_NUM_CORES=1",
            "-DVX_CFG_NUM_WARPS=4", "-DVX_CFG_NUM_THREADS=4",
            "-DVX_CFG_ISSUE_WIDTH=1", "-DVX_CFG_FPU_TYPE_STD",
            "-DVX_CFG_XLEN=64", "-DVX_CFG_XLEN_64",
        )
        for path, index in self.compile_records():
            for macro in required:
                with self.subTest(path=path.name, record=index, macro=macro):
                    text = self.replace_record(path, index, lambda line: " ".join(
                        token for token in line.split() if token != macro))
                    self.assert_rejected(path, text)

    def test_each_compilation_record_rejects_shim_and_conflicting_selectors(self):
        invalid = (
            "-DXRTSIM", "-DXRTSIM=0", "-DVX_CFG_XLEN_32=0",
            "-DVX_CFG_XLEN=32", "-DVX_CFG_FPU_TYPE_DPI=0",
            "-DVX_CFG_FPU_TYPE=DPI", "-DVX_CFG_TCU_TYPE_DPI=0",
            "-DVX_CFG_TCU_TYPE=DPI", "-UVX_CFG_XLEN", "@hidden-options",
            "-unknown-option -DVX_CFG_XLEN=64", "\0",
        )
        for path, index in self.compile_records():
            for flag in invalid:
                with self.subTest(path=path.name, record=index, flag=flag):
                    text = self.replace_record(path, index, lambda line: line + " " + flag)
                    self.assert_rejected(path, text)

    def test_each_compilation_record_rejects_shell_normalized_shim_macros(self):
        for path, index in self.compile_records():
            for flag in (r"-DXRTS\IM", '-DXRTS""IM', r"-DXRTS\IM=0",
                         '-DXRTS""IM=0'):
                with self.subTest(path=path.name, record=index, flag=flag):
                    text = self.replace_record(path, index, lambda line: line + " " + flag)
                    self.assert_rejected(path, text)

    def test_runtime_and_demo_record_counts_are_not_interchangeable(self):
        for relative in ("sw/runtime/xrt_config.stamp", "tests/regression/demo/config.stamp"):
            path = self.fixture.build / relative
            lines = path.read_text(encoding="utf-8").splitlines()
            for altered in ([], lines[:-1], lines + [lines[0]]):
                with self.subTest(path=relative, count=len(altered)):
                    self.assert_rejected(path, "\n".join(altered))

    def test_demo_linker_record_rejects_shim_opaque_flags_and_invalid_bytes(self):
        path = self.fixture.build / "tests/regression/demo/config.stamp"
        for suffix in (" -lxrtsim", " @options", " -unknown-flag", "\0"):
            with self.subTest(suffix=suffix):
                self.assert_rejected(path, self.replace_record(
                    path, 2, lambda line: line + suffix))

    def test_hook_declaration_must_name_the_checked_source_hook(self):
        manifest = deepcopy(self.fixture.manifest)
        manifest["files"]["xsim_hook"]["path"] = str(self.fixture.source / "different.tcl")
        with self.assertRaises(ValueError):
            self.check(manifest)

    def test_emconfig_only_accepts_bounded_nonempty_unambiguous_json_objects(self):
        path = self.fixture.artifacts / "emconfig.json"
        for content in (b"", b"{}", b"[]", b"{", b'{"x":1,"x":2}',
                        b'{"x":NaN}', b'{"x":Infinity}', b'"text"', b"\xff"):
            with self.subTest(content=content):
                self.assert_rejected(path, content)
        with self.changed(path, '{"synthetic":"no schema or execution claim"}'):
            self.assertIsNone(self.check())


if __name__ == "__main__":
    unittest.main()

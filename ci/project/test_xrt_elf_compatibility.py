# Licensed under the Apache License, Version 2.0.
"""CPU-only ELF compatibility regressions; no vendor code or GPU is used."""

from pathlib import Path
import platform
import struct
import subprocess
import sys
import unittest
from unittest import mock

import test_xrt_runtime as fixtures
import xrt_runtime
from xrt_test_support import identity, write_file


def minimal_elf(elf_class, data, machine, *, needed=(), soname=None):
    """Build a readable ELF dynamic object without executable fixture code."""
    endian = "<" if data == 1 else ">"
    word = 8 if elf_class == 2 else 4
    ehfmt = endian + ("16sHHIQQQIHHHHHH" if elf_class == 2 else "16sHHIIIIIHHHHHH")
    phfmt = endian + ("IIQQQQQQ" if elf_class == 2 else "IIIIIIII")
    shfmt = endian + ("IIQQQQIIQQ" if elf_class == 2 else "IIIIIIIIII")
    dynfmt = endian + ("qQ" if elf_class == 2 else "iI")
    ehsize, phsize, shsize, dynsize = map(struct.calcsize, (ehfmt, phfmt, shfmt, dynfmt))
    strings = bytearray(b"\0")
    entries = []
    for tag, name in [(1, item) for item in needed] + ([(14, soname)] if soname else []):
        entries.append((tag, len(strings)))
        strings.extend(name.encode("ascii") + b"\0")
    stroff = ehsize + 2 * phsize
    dynoff = (stroff + len(strings) + word - 1) // word * word
    base = 0x10000
    entries = [(5, base + stroff), (10, len(strings)), *entries, (0, 0)]
    dynamic = b"".join(struct.pack(dynfmt, *entry) for entry in entries)
    names = b"\0.dynamic\0.dynstr\0.shstrtab\0"
    namesoff = dynoff + len(dynamic)
    shoff = (namesoff + len(names) + word - 1) // word * word
    size = shoff + 4 * shsize
    result = bytearray(size)
    magic = b"\x7fELF" + bytes((elf_class, data, 1, 0, 0)) + bytes(7)
    struct.pack_into(ehfmt, result, 0, magic, 3, machine, 1, 0, ehsize, shoff, 0,
                     ehsize, phsize, 2, shsize, 4, 3)
    programs = [
        (1, 4, 0, base, base, size, size, 0x1000),
        (2, 6, dynoff, base + dynoff, base + dynoff, len(dynamic), len(dynamic), word),
    ]
    for index, program in enumerate(programs):
        if elf_class == 1:
            kind, flags, offset, virtual, physical, filesz, memsz, align = program
            program = (kind, offset, virtual, physical, filesz, memsz, flags, align)
        struct.pack_into(phfmt, result, ehsize + index * phsize, *program)
    result[stroff:stroff + len(strings)] = strings
    result[dynoff:dynoff + len(dynamic)] = dynamic
    result[namesoff:namesoff + len(names)] = names
    sections = [
        (0,) * 10,
        (1, 6, 3, base + dynoff, dynoff, len(dynamic), 2, 0, word, dynsize),
        (10, 3, 2, base + stroff, stroff, len(strings), 0, 0, 1, 0),
        (18, 3, 0, 0, namesoff, len(names), 0, 0, 1, 0),
    ]
    for index, section in enumerate(sections):
        struct.pack_into(shfmt, result, shoff + index * shsize, *section)
    return bytes(result)


@unittest.skipUnless(sys.platform.startswith("linux") and fixtures.COMPILER and fixtures.READELF,
                     "host ELF fixtures require Linux, a C compiler and readelf")
class ElfCompatibilityTests(unittest.TestCase):
    def setUp(self):
        self.case = fixtures.RuntimeBindingTests()
        self.addCleanup(self.case.doCleanups)
        self.case.setUp()
        self.paths = {
            "demo": self.case.demo,
            "libvortex": self.case.runtime / "libvortex.so",
            "libvortex_xrt": self.case.runtime / "libvortex-xrt.so",
            "xrt_coreutil": self.case.core,
        }
        contents = self.case.demo.read_bytes()
        self.assertEqual(contents[:4], b"\x7fELF")
        self.abi = {"class": contents[4], "data": contents[5],
                    "machine": int.from_bytes(contents[18:20],
                                              "little" if contents[5] == 1 else "big")}

    def inspect_without_loading(self):
        real_popen = subprocess.Popen
        calls = []

        def host_readelf_only(argv, *args, **kwargs):
            self.assertEqual(argv[0], str(Path(fixtures.READELF).resolve()))
            self.assertIn("-d", argv)
            self.assertIn("--wide", argv)
            self.assertIn(Path(argv[-1]), self.paths.values())
            self.assertEqual(set(kwargs["env"]), {"PATH", "LANG", "LC_ALL"})
            calls.append(Path(argv[-1]))
            return real_popen(argv, *args, **kwargs)

        with mock.patch.object(subprocess, "Popen", side_effect=host_readelf_only):
            report = self.case.inspect()
        return report, calls

    def assertBlocked(self, report, reason):
        self.assertEqual(report["outcome"], "blocked", report["blockers"])
        self.assertTrue(any(reason in item for item in report["blockers"]), report["blockers"])

    def object_bytes(self, role, abi):
        dynamic = {
            "demo": {"needed": ("libvortex.so",)},
            "libvortex": {"soname": "libvortex.so"},
            "libvortex_xrt": {"needed": ("libxrt_coreutil.so.2",)},
            "xrt_coreutil": {"soname": "libxrt_coreutil.so.2"},
        }
        return minimal_elf(abi["class"], abi["data"], abi["machine"], **dynamic[role])

    def replace_object(self, role, contents):
        self.paths[role].write_bytes(contents)
        if role == "xrt_coreutil":
            self.case.fixture.manifest["vendor"]["files"][role] = identity(self.paths[role])

    def assert_field_mismatch_blocked(self, field, value):
        changed = dict(self.abi, **{field: value})
        for role, path in self.paths.items():
            original = path.read_bytes()
            with self.subTest(role=role):
                try:
                    self.replace_object(role, self.object_bytes(role, changed))
                    report, _ = self.inspect_without_loading()
                    self.assertBlocked(report, "ELF " + field + " is incompatible with demo")
                    self.assertNotIn("xrt_coreutil", report["bindings"])
                finally:
                    self.replace_object(role, original)

    def test_matching_abi_passes_with_four_probes_and_stable_observations(self):
        before, calls = self.inspect_without_loading()
        self.assertEqual(before["outcome"], "pass", before["blockers"])
        self.assertEqual(self.case.run_fixture(), "11")
        after, _ = self.inspect_without_loading()
        self.assertEqual(after["outcome"], "pass", after["blockers"])
        self.assertEqual(before, after)
        self.assertCountEqual(calls, self.paths.values())
        observed = before["bindings"]["elf"]
        self.assertEqual(set(observed), set(self.paths))
        for role in self.paths:
            for field in ("class", "data", "machine"):
                self.assertEqual(observed[role]["header"][field], observed["demo"]["header"][field])

    def test_minimal_matching_elf_controls_pass_for_every_selected_role(self):
        for role, path in self.paths.items():
            original = path.read_bytes()
            with self.subTest(role=role):
                try:
                    self.replace_object(role, self.object_bytes(role, self.abi))
                    report, _ = self.inspect_without_loading()
                    self.assertEqual(report["outcome"], "pass", report["blockers"])
                finally:
                    self.replace_object(role, original)

    def test_real_loader_skips_elf32_coreutil_for_backend_runpath_then_inspector_blocks(self):
        if (platform.machine().lower() not in ("x86_64", "amd64")
                or platform.libc_ver()[0] != "glibc" or self.abi["class"] != 2):
            self.skipTest("ELF32 fallback reproduction requires a 64-bit x86 Linux/glibc loader")
        alternate = self.case.root / "alternate"
        alternate.mkdir()
        fallback = alternate / "libxrt_coreutil.so.2"
        self.case.compile("int core_value(void) { return 55; }", fallback,
                          "-shared", "-nostdlib", "-Wl,-soname,libxrt_coreutil.so.2")
        self.case.build_backend("-Wl,--enable-new-dtags,-rpath," + str(alternate))
        self.assertEqual(self.case.run_fixture(), "11")
        try:
            self.case.compile("int core_value(void) { return 1; }", self.case.core,
                              "-shared", "-m32", "-nostdlib", "-Wl,-soname,libxrt_coreutil.so.2")
        except subprocess.CalledProcessError as error:
            self.skipTest("ELF32 fixture needs compiler/linker -m32 -nostdlib support; "
                          "32-bit libc is not required: " + error.stderr.strip())
        self.case.fixture.manifest["vendor"]["files"]["xrt_coreutil"] = identity(self.case.core)
        self.assertEqual(self.case.core.read_bytes()[4], 1)
        self.assertEqual(self.paths["libvortex_xrt"].read_bytes()[4], 2)
        self.assertEqual((self.case.vendor / "libxrt_coreutil.so.2").resolve(), self.case.core)
        identities = {role: identity(path) for role, path in self.paths.items()}
        self.assertEqual(self.case.run_fixture(), "65")
        before, _ = self.inspect_without_loading()
        self.assertEqual(self.case.run_fixture(), "65")
        after, _ = self.inspect_without_loading()
        self.assertEqual(identities, {role: identity(path) for role, path in self.paths.items()})
        self.assertEqual(before, after)
        self.assertEqual(before["outcome"], "blocked",
                         "loader selected fallback value 65; stable before/after reports must not pass")
        self.assertBlocked(before, "ELF class is incompatible with demo: xrt_coreutil")
        self.assertBlocked(after, "ELF class is incompatible with demo: xrt_coreutil")

    def test_class_mismatch_blocks_each_selected_object_without_loading(self):
        self.assert_field_mismatch_blocked("class", 1 if self.abi["class"] == 2 else 2)

    def test_data_mismatch_blocks_each_selected_object_without_loading(self):
        self.assert_field_mismatch_blocked("data", 2 if self.abi["data"] == 1 else 1)

    def test_machine_mismatch_blocks_each_selected_object_without_loading(self):
        self.assert_field_mismatch_blocked("machine", 183 if self.abi["machine"] != 183 else 62)

    def test_non_elf_coreutil_is_blocked_without_executing_it(self):
        sentinel = self.case.root / "executed-coreutil"
        write_file(self.case.core, "#!/bin/sh\ntouch " + str(sentinel) + "\n", executable=True)
        self.case.fixture.manifest["vendor"]["files"]["xrt_coreutil"] = identity(self.case.core)
        report, _ = self.inspect_without_loading()
        self.assertBlocked(report, "readelf could not inspect xrt_coreutil")
        self.assertFalse(sentinel.exists())

    def test_coreutil_mutation_during_header_probe_is_blocked(self):
        real_probe = xrt_runtime._probe

        def mutate_coreutil(argv, **kwargs):
            result = real_probe(argv, **kwargs)
            if Path(argv[-1]) == self.case.core:
                with self.case.core.open("ab") as stream:
                    stream.write(b"changed")
            return result

        with mock.patch.object(xrt_runtime, "_probe", side_effect=mutate_coreutil):
            report, _ = self.inspect_without_loading()
        self.assertBlocked(report, "changed during inspection: xrt_coreutil")


if __name__ == "__main__":
    unittest.main()

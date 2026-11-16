# Licensed under the Apache License, Version 2.0.
"""CPU-only ELF lookup fixtures; no vendor installation or GPU is exercised."""

import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

import xrt_runtime
from xrt_test_support import VendorFixture, identity, write_file


COMPILER = shutil.which("gcc") or shutil.which("cc")
READELF = shutil.which("readelf")
STUB_SOURCE = """
#include <dlfcn.h>
int selected_value(void) {
    void *handle = dlopen("libvortex-xrt.so", RTLD_NOW);
    if (!handle) return -99;
    int (*value)(void) = (int (*)(void))dlsym(handle, "backend_value");
    return value ? value() : -98;
}
"""
DEMO_SOURCE = """
#include <stdio.h>
extern int selected_value(void);
int main(void) { printf("%d\\n", selected_value()); return 0; }
"""
BACKEND_SOURCE = "extern int core_value(void); int backend_value(void) { return core_value() + 10; }"


@unittest.skipUnless(COMPILER and READELF, "small host ELF fixtures require a C compiler and readelf")
class RuntimeBindingTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.fixture = VendorFixture(self.root / "fixture")
        self.build = self.fixture.build
        self.runtime = self.build / "sw/runtime"
        self.vendor = self.fixture.xrt / "lib"
        self.runtime.mkdir(parents=True)
        self.demo = self.build / "tests/regression/demo/demo"
        self.demo.parent.mkdir(parents=True)
        self.core = self.vendor / "pinned-core.so"
        self.compile("int core_value(void) { return 1; }", self.core,
                     "-shared", "-Wl,-soname,libxrt_coreutil.so.2")
        (self.vendor / "libxrt_coreutil.so").unlink()
        for name in ("libxrt_coreutil.so", "libxrt_coreutil.so.2"):
            (self.vendor / name).symlink_to(self.core.name)
        self.fixture.manifest["vendor"]["files"]["xrt_coreutil"] = identity(self.core)
        self.build_stub()
        self.build_backend()
        self.build_demo()
        self.environment = {
            "PATH": os.defpath,
            "LD_LIBRARY_PATH": str(self.runtime) + ":" + str(self.vendor),
            "VORTEX_DRIVER": "xrt", "XCL_EMULATION_MODE": "hw_emu",
        }

    def compile(self, source, output, *flags):
        subprocess.run([COMPILER, "-fPIC", "-x", "c", "-", "-x", "none", "-o", str(output), *flags],
                       input=source, text=True, capture_output=True, check=True,
                       timeout=10, env={"PATH": os.defpath, "LANG": "C", "LC_ALL": "C"})

    def build_stub(self, *flags):
        self.compile(STUB_SOURCE, self.runtime / "libvortex.so", "-shared",
                     "-Wl,-soname,libvortex.so", "-Wl,-rpath,$ORIGIN", "-ldl", *flags)

    def build_backend(self, *flags):
        self.compile(BACKEND_SOURCE, self.runtime / "libvortex-xrt.so", "-shared",
                     "-L" + str(self.vendor), "-lxrt_coreutil", *flags)

    def build_demo(self, *flags):
        self.compile(DEMO_SOURCE, self.demo, "-L" + str(self.runtime), "-lvortex", *flags)

    def inspect(self, environment=None):
        return xrt_runtime.inspect_runtime(self.fixture.manifest, self.build,
                                           self.environment if environment is None else environment)

    def run_fixture(self, environment=None):
        result = subprocess.run([str(self.demo)], cwd=self.demo.parent,
                                env=self.environment if environment is None else environment,
                                text=True, capture_output=True, check=True, timeout=5)
        return result.stdout.strip()

    def assertBlocked(self, report, reason):
        self.assertEqual(report["outcome"], "blocked", report)
        self.assertTrue(any(reason in blocker for blocker in report["blockers"]), report)

    def test_real_elf_observations_are_stable_and_bind_selected_files(self):
        report = self.inspect()
        self.assertEqual(report["outcome"], "pass", report)
        self.assertEqual(report, self.inspect())
        self.assertEqual(set(report), {"outcome", "blockers", "identities", "bindings", "limitations"})
        self.assertEqual(report["bindings"]["xrt_coreutil"]["name"], "libxrt_coreutil.so.2")
        self.assertEqual(report["bindings"]["xrt_coreutil"]["resolved"], str(self.core))
        self.assertEqual(report["bindings"]["libvortex_xrt"]["kind"], "dlopen")
        self.assertEqual(report["bindings"]["elf"]["libvortex"]["runpath"], "$ORIGIN")
        self.assertEqual(report["identities"]["libvortex"], identity(self.runtime / "libvortex.so"))
        self.assertTrue(any("not a complete" in limitation for limitation in report["limitations"]))

    def test_vendor_stub_and_backend_shadows_cannot_replace_generated_objects(self):
        self.compile("int backend_value(void) { return 101; }",
                     self.vendor / "libvortex-xrt.so", "-shared")
        reversed_environment = dict(self.environment, LD_LIBRARY_PATH=str(self.vendor) + ":" + str(self.runtime))
        self.assertEqual(self.run_fixture(reversed_environment), "101")
        self.assertBlocked(self.inspect(reversed_environment), "LD_LIBRARY_PATH")
        self.assertEqual(self.run_fixture(), "11")
        self.assertEqual(self.inspect()["outcome"], "pass")
        self.compile("int selected_value(void) { return 999; }",
                     self.vendor / "libvortex.so", "-shared", "-Wl,-soname,libvortex.so")
        self.assertEqual(self.run_fixture(reversed_environment), "999")
        report = self.inspect()
        self.assertEqual(report["outcome"], "pass", report)
        self.assertEqual(self.run_fixture(), "11")
        for role, name in (("libvortex", "libvortex.so"), ("libvortex_xrt", "libvortex-xrt.so")):
            self.assertEqual(report["bindings"][role]["resolved"], str(self.runtime / name))

    def test_versioned_coreutil_alias_must_select_the_manifest_file(self):
        unpinned = self.vendor / "unpinned-core.so"
        self.compile("int core_value(void) { return 2; }", unpinned,
                     "-shared", "-Wl,-soname,libxrt_coreutil.so.2")
        alias = self.vendor / "libxrt_coreutil.so.2"
        alias.unlink()
        alias.symlink_to(unpinned.name)
        self.assertEqual((self.vendor / "libxrt_coreutil.so").resolve(), self.core)
        self.assertEqual(self.run_fixture(), "12")
        self.assertBlocked(self.inspect(), "does not select the pinned file")

    def test_identical_coreutil_bytes_at_an_alternate_path_are_rejected(self):
        other = self.vendor / "other-core.so"
        shutil.copyfile(self.core, other)
        alias = self.vendor / "libxrt_coreutil.so.2"
        alias.unlink()
        alias.symlink_to(other.name)
        self.assertBlocked(self.inspect(), "does not select the pinned file")

    def test_coreutil_alias_retargeting_during_identity_read_is_rejected(self):
        other = self.vendor / "other-core.so"
        shutil.copyfile(self.core, other)
        real_identity = xrt_runtime._identity
        observations = 0

        def retarget(path, **kwargs):
            nonlocal observations
            result = real_identity(path, **kwargs)
            if Path(path) == self.core:
                observations += 1
                if observations == 2:
                    alias = self.vendor / "libxrt_coreutil.so.2"
                    alias.unlink()
                    alias.symlink_to(other.name)
            return result

        with mock.patch.object(xrt_runtime, "_identity", side_effect=retarget):
            self.assertBlocked(self.inspect(), "does not select the pinned file")

    def test_generated_directory_coreutil_shadow_is_rejected(self):
        shutil.copyfile(self.core, self.runtime / "libxrt_coreutil.so.2")
        self.assertBlocked(self.inspect(), "does not select the pinned file")

    def test_unversioned_actual_needed_name_is_supported(self):
        self.compile("int core_value(void) { return 1; }", self.core, "-shared")
        self.fixture.manifest["vendor"]["files"]["xrt_coreutil"] = identity(self.core)
        self.build_backend()
        report = self.inspect()
        self.assertEqual(report["outcome"], "pass", report)
        self.assertEqual(report["bindings"]["xrt_coreutil"]["name"], "libxrt_coreutil.so")

    def test_missing_actual_coreutil_alias_cannot_fall_back_to_system_search(self):
        (self.vendor / "libxrt_coreutil.so.2").unlink()
        self.assertBlocked(self.inspect(), "absent from the explicit lookup")

    def test_backend_without_a_coreutil_dependency_is_rejected(self):
        self.compile("int backend_value(void) { return 11; }", self.runtime / "libvortex-xrt.so", "-shared")
        self.assertBlocked(self.inspect(), "exactly one libxrt_coreutil")

    def test_multiple_coreutil_needed_versions_are_rejected(self):
        extra = self.vendor / "libxrt_coreutil.so.3"
        self.compile("int extra_value(void) { return 3; }", extra,
                     "-shared", "-Wl,-soname,libxrt_coreutil.so.3")
        self.build_backend("-Wl,--no-as-needed", str(extra))
        self.assertBlocked(self.inspect(), "exactly one libxrt_coreutil")

    def test_xrtsim_dependency_is_rejected(self):
        simulation = self.runtime / "libxrtsim.so"
        self.compile("int core_value(void) { return 1; }", simulation,
                     "-shared", "-Wl,-soname,libxrtsim.so")
        self.compile(BACKEND_SOURCE, self.runtime / "libvortex-xrt.so", "-shared",
                     "-L" + str(self.runtime), "-lxrtsim")
        self.assertBlocked(self.inspect(), "XRTSIM")

    def test_legacy_rpath_that_preempts_library_path_is_rejected(self):
        self.compile("int selected_value(void) { return 999; }", self.vendor / "libvortex.so",
                     "-shared", "-Wl,-soname,libvortex.so")
        self.build_demo("-Wl,--disable-new-dtags,-rpath," + str(self.vendor))
        self.assertEqual(self.run_fixture(), "999")
        self.assertBlocked(self.inspect(), "DT_RPATH")

    def test_stub_and_backend_legacy_rpath_are_rejected(self):
        for name, builder in (("libvortex.so", self.build_stub), ("libvortex-xrt.so", self.build_backend)):
            with self.subTest(name=name):
                contents = (self.runtime / name).read_bytes()
                builder("-Wl,--disable-new-dtags,-rpath," + str(self.vendor))
                self.assertBlocked(self.inspect(), "DT_RPATH")
                (self.runtime / name).write_bytes(contents)

    def test_runpath_cannot_preempt_the_explicit_library_path(self):
        self.compile("int selected_value(void) { return 999; }", self.vendor / "libvortex.so",
                     "-shared", "-Wl,-soname,libvortex.so")
        self.build_demo("-Wl,-rpath," + str(self.vendor))
        self.assertEqual(self.run_fixture(), "11")
        self.assertEqual(self.inspect()["outcome"], "pass")

    def test_needed_absolute_path_is_rejected(self):
        self.compile("int core_value(void) { return 1; }", self.core, "-shared")
        self.fixture.manifest["vendor"]["files"]["xrt_coreutil"] = identity(self.core)
        self.compile(BACKEND_SOURCE, self.runtime / "libvortex-xrt.so", "-shared", str(self.core))
        self.assertBlocked(self.inspect(), "plain basenames")

    def test_noncanonical_generated_object_is_rejected(self):
        path = self.runtime / "libvortex-xrt.so"
        replacement = self.runtime / "replacement.so"
        path.rename(replacement)
        path.symlink_to(replacement.name)
        self.assertBlocked(self.inspect(), "symlink")

    def test_manifest_coreutil_byte_drift_is_rejected(self):
        with self.core.open("ab") as output:
            output.write(b"changed")
        self.assertBlocked(self.inspect(), "differs from the manifest")

    def test_generated_object_mutation_during_probe_is_rejected(self):
        real_probe = xrt_runtime._probe

        def mutate(argv, **kwargs):
            result = real_probe(argv, **kwargs)
            with Path(argv[-1]).open("ab") as stream:
                stream.write(b"changed")
            return result

        with mock.patch.object(xrt_runtime, "_probe", side_effect=mutate):
            self.assertBlocked(self.inspect(), "changed during inspection")

    def test_readelf_identity_is_checked_after_the_probe(self):
        real_identity = xrt_runtime._identity
        selected = Path(READELF).resolve()
        observations = 0

        def changed(path, **kwargs):
            nonlocal observations
            value = real_identity(path, **kwargs)
            if Path(path) == selected:
                observations += 1
                if observations > 1:
                    value["sha256"] = "0" * 64
            return value

        with mock.patch.object(xrt_runtime, "_identity", side_effect=changed):
            self.assertBlocked(self.inspect(), "readelf changed")

    def test_readelf_alias_retargeting_is_rejected_even_for_identical_bytes(self):
        hostbin = self.root / "hostbin"
        hostbin.mkdir()
        alias = hostbin / "readelf"
        alias.symlink_to(Path(READELF).resolve())
        alternative = hostbin / "other-readelf"
        shutil.copyfile(Path(READELF).resolve(), alternative)
        alternative.chmod(0o700)
        real_probe = xrt_runtime._probe

        def retarget(argv, **kwargs):
            result = real_probe(argv, **kwargs)
            alias.unlink()
            alias.symlink_to(alternative.name)
            return result

        environment = dict(self.environment, PATH=str(hostbin) + ":" + os.defpath)
        with mock.patch.object(xrt_runtime, "_probe", side_effect=retarget):
            self.assertBlocked(self.inspect(environment), "readelf changed")

    def test_only_host_readelf_is_probed_without_vendor_loader_variables(self):
        real_probe = xrt_runtime._probe
        calls = []

        def inspect_probe(argv, **kwargs):
            calls.append(argv)
            self.assertEqual(argv[:4], [str(Path(READELF).resolve()), "-h", "-d", "--wide"])
            self.assertEqual(kwargs["timeout"], 5)
            self.assertEqual(set(kwargs["environment"]), {"PATH", "LANG", "LC_ALL"})
            return real_probe(argv, **kwargs)

        with mock.patch.object(xrt_runtime, "_probe", side_effect=inspect_probe):
            self.assertEqual(self.inspect()["outcome"], "pass")
        self.assertEqual(len(calls), 4)

    def test_inspected_executable_script_is_never_run(self):
        sentinel = self.root / "executed"
        write_file(self.demo, "#!/bin/sh\ntouch " + str(sentinel) + "\n", executable=True)
        self.assertBlocked(self.inspect(), "readelf could not inspect")
        self.assertFalse(sentinel.exists())

    def test_incorrect_launch_environment_is_rejected_without_probing(self):
        variants = []
        for key in ("LD_LIBRARY_PATH", "VORTEX_DRIVER", "XCL_EMULATION_MODE"):
            current = dict(self.environment)
            current.pop(key)
            variants.append(current)
        for key, value in (("LD_PRELOAD", ""), ("LD_AUDIT", "/tmp/audit.so"),
                           ("GLIBC_TUNABLES", ""), ("VORTEX_DRIVER", "simx"),
                           ("XCL_EMULATION_MODE", "sw_emu"), ("PATH", ":/usr/bin"),
                           ("PATH", "relative:/usr/bin"),
                           ("LD_LIBRARY_PATH", self.environment["LD_LIBRARY_PATH"] + ":")):
            variants.append(dict(self.environment, **{key: value}))
        with mock.patch.object(xrt_runtime, "_probe", side_effect=AssertionError("invalid launch probed")):
            for environment in variants:
                with self.subTest(environment=environment):
                    self.assertEqual(self.inspect(environment)["outcome"], "blocked")

    def test_absent_readelf_is_a_blocker(self):
        self.assertBlocked(self.inspect(dict(self.environment, PATH=str(self.root / "absent"))), "readelf is unavailable")

    def test_probe_errors_and_non_dynamic_output_are_blockers(self):
        for result in ((1, b""), (0, b"There is no dynamic section in this file.\n"), (0, b"\xff")):
            with self.subTest(result=result), mock.patch.object(xrt_runtime, "_probe", return_value=result):
                self.assertEqual(self.inspect()["outcome"], "blocked")
        for reason in ("identity probe timed out", "identity probe output exceeded its limit"):
            with self.subTest(reason=reason), mock.patch.object(xrt_runtime, "_probe", side_effect=ValueError(reason)):
                self.assertBlocked(self.inspect(), reason)

    def test_hardware_capability_shadow_is_rejected(self):
        capability = self.runtime / "glibc-hwcaps/x86-64-v3"
        capability.mkdir(parents=True)
        shutil.copyfile(self.runtime / "libvortex.so", capability / "libvortex.so")
        self.assertBlocked(self.inspect(), "hardware-capability")

    def test_system_preload_with_objects_is_rejected(self):
        preload = self.root / "ld.so.preload"
        write_file(preload, "# fixture loader settings\n/tmp/unpinned.so\n")
        with mock.patch.object(xrt_runtime, "PRELOAD_FILE", preload):
            self.assertBlocked(self.inspect(), "system ld.so.preload")

    def test_comment_only_system_preload_is_identified(self):
        preload = self.root / "ld.so.preload"
        write_file(preload, "# no preloaded objects\n")
        with mock.patch.object(xrt_runtime, "PRELOAD_FILE", preload):
            report = self.inspect()
        self.assertEqual(report["outcome"], "pass", report)
        self.assertEqual(report["identities"]["system_preload"], identity(preload))

    def test_system_preload_created_during_inspection_is_rejected(self):
        preload = self.root / "ld.so.preload"
        real_probe = xrt_runtime._probe

        def create_preload(argv, **kwargs):
            result = real_probe(argv, **kwargs)
            write_file(preload, "# new configuration\n")
            return result

        with mock.patch.object(xrt_runtime, "PRELOAD_FILE", preload), \
                mock.patch.object(xrt_runtime, "_probe", side_effect=create_preload):
            self.assertBlocked(self.inspect(), "preload configuration changed")


class DynamicObservationTests(unittest.TestCase):
    def output(self, entries):
        lines = ["Dynamic section at offset 0x100 contains 8 entries:"]
        lines.extend(" 0x0000000000000001 (" + tag + ") " + value for tag, value in entries)
        lines.append(" 0x0000000000000000 (NULL) 0x0")
        return "\n".join(lines).encode("utf-8")

    def test_inert_dynamic_redirection_tags_are_rejected(self):
        for tag in ("AUDIT", "DEPAUDIT", "FILTER", "AUXILIARY"):
            with self.subTest(tag=tag), self.assertRaisesRegex(ValueError, "redirection"):
                xrt_runtime._dynamic(self.output([(tag, "[libredirect.so]")]))

    def test_duplicate_needed_and_malformed_strings_are_rejected(self):
        for entries in ([('NEEDED', 'Shared library: [libsame.so]')] * 2,
                        [('NEEDED', 'Shared library: [${ORIGIN}/libsame.so]')],
                        [('NEEDED', 'Shared library: libsame.so')],
                        [('SONAME', '[first.so]'), ('SONAME', '[second.so]')]):
            with self.subTest(entries=entries), self.assertRaises(ValueError):
                xrt_runtime._dynamic(self.output(entries))


if __name__ == "__main__":
    unittest.main()

# Licensed under the Apache License, Version 2.0.
"""Reject changed generated inputs even when their timestamps look current."""

import hashlib
import json
import os
from pathlib import Path
import time
import unittest

import baseline_inventory as inventory
import test_baseline_inventory as fixtures


class GeneratedInputTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.BuildTests("test_matching_build_records_fresh_generated_hashes")
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.source = self.fixture.source
        self.build = self.fixture.build

    def collect(self):
        return inventory.collect_build(self.build, self.source)

    def assert_blocked(self):
        report = self.collect()
        self.assertEqual(report["outcome"], "blocked", report)
        self.assertFalse(report["identity_matches"])

    def test_real_generated_headers_and_copied_recipes_pass_without_mutation(self):
        paths = [self.build / name for name in inventory.GENERATED_PATHS]
        paths.extend(self.build / name for name in inventory.COPIED_BUILD_INPUTS)
        before = {str(path): (hashlib.sha256(path.read_bytes()).hexdigest(),
                             path.stat().st_mtime_ns) for path in paths}
        report = self.collect()
        self.assertEqual(report["outcome"], "pass", report)
        self.assertTrue(report["identity_matches"])
        self.assertEqual({item["path"] for item in report["build_inputs"]},
                         set(inventory.COPIED_BUILD_INPUTS))
        after = {str(path): (hashlib.sha256(path.read_bytes()).hexdigest(),
                            path.stat().st_mtime_ns) for path in paths}
        self.assertEqual(before, after)
        self.assertNotIn(str(self.fixture.base), json.dumps(report))

    def test_newer_conflicting_config_header_is_rejected(self):
        for relative in ("sw/VX_config.h", "hw/VX_config.vh"):
            target = self.build / relative
            original = target.read_bytes()
            with self.subTest(header=relative):
                target.write_bytes(original + b"\n#define VX_CFG_DCACHE_ENABLE 0\n")
                os.utime(target, (time.time() + 30, time.time() + 30))
                self.assert_blocked()
            target.write_bytes(original)

    def test_resolved_type_header_uses_rv64_not_an_unrelated_generation(self):
        for relative in ("sw/VX_types.h", "hw/VX_types.vh"):
            target = self.build / relative
            original = target.read_bytes()
            with self.subTest(header=relative):
                target.write_bytes(original.replace(b"80000000", b"90000000", 1))
                if target.read_bytes() == original:
                    target.write_bytes(original + b"\n/* foreign generated constants */\n")
                os.utime(target, (time.time() + 30, time.time() + 30))
                self.assert_blocked()
            target.write_bytes(original)

    def test_newer_application_recipe_cannot_replace_the_reference_check(self):
        for app in ("sgemm_tcu", "flash_attn_tcu_wg"):
            target = self.build / "tests/regression" / app / "Makefile"
            original = target.read_bytes()
            with self.subTest(app=app):
                target.write_bytes(original + b"\nrun-simx:\n\t@echo PASSED!\n")
                os.utime(target, (time.time() + 30, time.time() + 30))
                self.assert_blocked()
            target.write_bytes(original)

    def test_native_backend_and_shared_build_fragments_are_verified(self):
        for relative in ("sw/kernel/Makefile", "sw/runtime/common.mk", "sim/common.mk",
                         "sw/runtime/stub/Makefile", "sw/runtime/simx/Makefile",
                         "sw/runtime/rtlsim/Makefile", "sim/simx/Makefile",
                         "sim/rtlsim/Makefile", "tests/regression/common.mk"):
            target = self.build / relative
            original = target.read_bytes()
            with self.subTest(recipe=relative):
                target.write_bytes(original + b"\noverride CONFIGS := -DVX_CFG_TCU_TYPE_DPI\n")
                self.assert_blocked()
            target.write_bytes(original)

    def test_copied_config_generator_cannot_differ_from_the_source(self):
        target = self.build / "ci/gen_config.py"
        target.write_text("print('-DVX_CFG_TCU_TYPE_DPI')\n")
        self.assert_blocked()

    def test_verilator_template_must_match_the_instantiated_source(self):
        target = self.build / "sim/rtlsim/verilator.vlt"
        with target.open("a") as stream:
            stream.write("\n`verilator_config\ncoverage_off -file \"*\"\n")
        self.assert_blocked()

    def test_source_template_change_requires_an_updated_copy(self):
        source = self.source / "sim/rtlsim/verilator.vlt.in"
        with source.open("a") as stream:
            stream.write("\n// additional source directive\n")
        self.assert_blocked()

    def test_missing_copied_recipe_is_not_an_optional_inventory_item(self):
        (self.build / "sim/rtlsim/Makefile").unlink()
        self.assert_blocked()

    def test_escaped_and_nonregular_recipes_are_rejected_before_read(self):
        target = self.build / "tests/regression/sgemm_tcu/Makefile"
        target.unlink()
        os.mkfifo(target)
        start = time.monotonic()
        self.assert_blocked()
        self.assertLess(time.monotonic() - start, 2)
        target.unlink()
        outside = self.fixture.base / "foreign-Makefile"
        outside.write_text("run-simx:\n\t@echo PASSED!\n")
        target.symlink_to(outside)
        self.assert_blocked()


if __name__ == "__main__":
    unittest.main()

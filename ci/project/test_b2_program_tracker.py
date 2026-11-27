#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Unit tests for ci/project/b2_program_tracker.py."""

import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest

HERE = str(Path(__file__).resolve().parent)
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import b2_program_tracker as tracker


class TestB2ProgramTracker(unittest.TestCase):
    def test_committed_ledger_valid(self):
        ledger = json.loads(tracker.LEDGER_PATH.read_text(encoding="utf-8"))
        self.assertEqual(tracker.validate_ledger(ledger), [])
        total_planned = sum(w["target_prod_loc"] for w in ledger["waves"])
        self.assertGreaterEqual(total_planned, 500000)

    def test_ledger_rejects_foundry_signoff_or_silicon_claim(self):
        ledger = json.loads(tracker.LEDGER_PATH.read_text(encoding="utf-8"))
        bad = copy.deepcopy(ledger)
        bad["evidence_boundary"]["foundry_signoff"] = True
        bad["evidence_boundary"]["allowed_levels"].append("silicon_measured")
        errs = tracker.validate_ledger(bad)
        self.assertTrue(any("foundry_signoff" in e for e in errs))
        self.assertTrue(any("silicon_measured" in e for e in errs))

    def test_classify_path_separates_production_tests_and_docs(self):
        self.assertEqual(tracker.classify_path("hw/rtl/tcu/v2/VX_tcu_v2.sv"), "rtl_silicon")
        self.assertEqual(tracker.classify_path("sim/simx/b2/tmem.cpp"), "simx")
        self.assertEqual(tracker.classify_path("compiler/aigpu_cc/ir/ssa.cpp"), "compiler")
        self.assertEqual(tracker.classify_path("python/aigpu_triton/jit.py"), "compiler")
        self.assertEqual(tracker.classify_path("sw/libs/aigpu_blas/gemm_fp4.cpp"), "kernels")
        self.assertEqual(tracker.classify_path("sw/driver/aigpu_drm/drm_drv.c"), "driver_runtime")
        self.assertEqual(tracker.classify_path("sw/ccl/allreduce.cpp"), "driver_runtime")
        self.assertEqual(tracker.classify_path("python/aigpu_serve/engine.py"), "frameworks_tools")
        self.assertEqual(tracker.classify_path("hw/dv/tcu_v2/tb_tcu.cpp"), "verification_test")
        self.assertEqual(tracker.classify_path("tests/libs/aigpu_blas/test_gemm.cpp"), "verification_test")
        self.assertEqual(tracker.classify_path("ci/project/test_b2_program_tracker.py"), "verification_test")
        self.assertEqual(tracker.classify_path("docs/project/b2-commercial-master-plan.md"), "excluded")
        self.assertEqual(tracker.classify_path("third_party/foo/bar.cpp"), "excluded")

    def test_substantive_line_filters_comments_and_blanks(self):
        self.assertFalse(tracker.is_substantive_line("   ", ".cpp"))
        self.assertFalse(tracker.is_substantive_line("  // comment", ".sv"))
        self.assertFalse(tracker.is_substantive_line("  # py comment", ".py"))
        self.assertTrue(tracker.is_substantive_line("  assign y = a + b;", ".sv"))
        self.assertTrue(tracker.is_substantive_line("  return x * 2", ".py"))

    def test_anti_bloat_flags_repetitive_padding(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad_file = Path(tmp) / "padded.py"
            bad_file.write_text("x = x + 1\n" * 300, encoding="utf-8")
            warnings = tracker.check_file_anti_bloat(bad_file)
            self.assertTrue(warnings)

            good_file = Path(tmp) / "real.py"
            good_file.write_text(
                "\n".join(f"def fn_{i}(a, b): return a * {i} + b" for i in range(300)) + "\n",
                encoding="utf-8",
            )
            self.assertEqual(tracker.check_file_anti_bloat(good_file), [])


if __name__ == "__main__":
    unittest.main()

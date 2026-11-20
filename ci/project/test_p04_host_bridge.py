# SPDX-License-Identifier: Apache-2.0
"""Exercise the actual host bridge; these checks perform no GPU dispatch."""

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import struct
import tempfile
import unittest

from tensor_host_tools import run_host_command


ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / "sw/runtime/ai"
HARNESS = ROOT / "ci/project/fixtures/p04_host_bridge_test.cpp"
FIXTURE = ROOT / "ci/project/fixtures/p04_tiny_mlp_v1.json"


class TinyMlpHostBridgeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler = shutil.which("c++") or shutil.which("g++") or shutil.which("clang++")
        if compiler is None:
            raise AssertionError("Tiny-MLP host bridge tests require C++17 and UBSan")
        cls.temporary = tempfile.TemporaryDirectory(prefix="p04-bridge-", dir=ROOT.parent)
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.build = Path(cls.temporary.name)
        cls.binary = cls.build / "bridge-test"
        cls.packet = cls.build / "frozen-cases.bin"
        cls.environment = {
            "PATH": os.environ.get("PATH", os.defpath), "LC_ALL": "C",
            "TMPDIR": str(cls.build), "UBSAN_OPTIONS": "halt_on_error=1:print_stacktrace=1",
        }
        sources = [HARNESS, FIXTURE, ROOT / "sw/common/ai_matmul_args.h",
                   *(RUNTIME / name for name in ("mlp_host.h", "mlp_host.cpp", "contract.h"))]
        cls.identities = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in sources}
        run_host_command([
            compiler, "-std=c++17", "-O1", "-g0", "-Wall", "-Wextra", "-Werror", "-pedantic",
            "-fsanitize=undefined", "-fno-sanitize-recover=undefined",
            "-I", str(RUNTIME), str(HARNESS), str(RUNTIME / "mlp_host.cpp"),
            "-o", str(cls.binary),
        ], cwd=cls.build, env=cls.environment, timeout=30)
        fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
        packet = bytearray(b"MLP1" + struct.pack("<I", len(fixture["cases"])))
        for case in fixture["cases"]:
            packet.extend(struct.pack("<I", {"fp16": 1, "bf16": 2}[case["format"]]))
            for name, count in (("hidden_words", 128), ("bridge_words", 64)):
                if len(case[name]) != count:
                    raise AssertionError("Frozen bridge fixture has an unexpected word count")
                packet.extend(struct.pack("<" + "I" * count,
                                          *(int(word, 16) for word in case[name])))
        if len(packet) != 7728:
            raise AssertionError("Frozen bridge packet exceeds its exact case inventory")
        cls.packet.write_bytes(packet)

    def group(self, name, *arguments):
        output = run_host_command([str(self.binary), name, *map(str, arguments)],
                                  cwd=self.build, env=self.environment, timeout=10)
        self.assertRegex(output, r"\APASS " + re.escape(name) + r" checks=[1-9][0-9]*\n\Z")
        for path, expected in self.identities.items():
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), expected,
                             "Input changed during host bridge tests: " + str(path))
        self.assertLess(sum(path.stat().st_size for path in self.build.rglob("*") if path.is_file()),
                        64 * 1024 * 1024)

    def test_all_129_legal_integers_at_every_position_in_both_formats(self):
        self.group("legal_domain")

    def test_adjacent_fractional_words_reject_before_relu_and_return_no_prefix(self):
        self.group("adjacent_fractional_words")

    def test_nonfinite_subnormal_and_out_of_range_values_of_both_signs_reject(self):
        self.group("exceptional_words")

    def test_null_input_wrong_extent_and_unsupported_dtype_reject_atomically(self):
        self.group("invalid_structure")

    def test_signed_zero_and_literal_little_endian_row_boundary_encodings(self):
        self.group("zero_and_row_order")

    def test_all_frozen_cases_use_actual_input_words_and_match_stored_bridge_bytes(self):
        self.group("frozen_cases", self.packet)

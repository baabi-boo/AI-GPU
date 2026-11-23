# SPDX-License-Identifier: Apache-2.0
"""Original-data checks for trusted generation and inert input boundaries."""

from copy import deepcopy
import hashlib
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

import p06_managed_preflight_generated as generated
from p06_managed_preflight_replay_test_support import Packet, PREFIX, replay
from p06_replay import ReplayError


class ManagedPreflightGeneratedTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with Packet() as packet:
            cls.sources = {name: packet[PREFIX + "artifacts/source/" + name]
                           for name in generated.INPUT_SHA256}
            cls.headers = {fmt: {stage: {name: packet[
                PREFIX + "artifacts/simx-" + fmt + "/" + stage + "/" + name]
                for name in generated.HEADERS} for stage in ("configured", "backend", "frozen")}
                for fmt in ("fp16", "bf16")}
            cls.flags = {fmt: packet[PREFIX + "logs/simx-" + fmt + "-expected-flags.log"].decode()
                         for fmt in ("fp16", "bf16")}

    def headers_receipt(self, headers=None, sources=None):
        return generated.validate_generated_headers(
            source_body=(self.sources if sources is None else sources).__getitem__,
            build_body=(self.headers["fp16"]["frozen"] if headers is None else headers).__getitem__)

    def test_original_four_headers_reproduce_in_all_stages_and_formats(self):
        for fmt, stages in self.headers.items():
            for stage, headers in stages.items():
                with self.subTest(format=fmt, stage=stage):
                    result = self.headers_receipt(headers)
                    self.assertEqual({row["path"] for row in result["headers"]}, set(generated.HEADERS))
                    self.assertEqual(result["xlen"], 64)
                    self.assertEqual(result["profile"], "p02-tfr")
                    for row in result["headers"]:
                        self.assertEqual(row["sha256"], hashlib.sha256(headers[row["path"]]).hexdigest())
                        self.assertEqual(row["size_bytes"], len(headers[row["path"]]))

    def test_semantic_change_to_every_retained_header_rejects(self):
        for name in generated.HEADERS:
            with self.subTest(header=name):
                headers = deepcopy(self.headers["fp16"]["frozen"])
                old = b"VX_DCR_DATA_BITS 32" if "types" in name else b"VX_CFG_NUM_WARPS 4"
                new = b"VX_DCR_DATA_BITS 64" if "types" in name else b"VX_CFG_NUM_WARPS 8"
                self.assertIn(old, headers[name])
                headers[name] = headers[name].replace(old, new)
                with self.assertRaisesRegex(ReplayError, "reproduced generated header " + name):
                    self.headers_receipt(headers)

    def test_cpp_and_verilog_outputs_cannot_be_substituted(self):
        for name, other in (("sw/VX_config.h", "hw/VX_config.vh"), ("hw/VX_types.vh", "sw/VX_types.h")):
            headers = deepcopy(self.headers["fp16"]["frozen"])
            headers[name] = headers[other]
            with self.subTest(header=name), self.assertRaisesRegex(ReplayError, "reproduced generated header " + name):
                self.headers_receipt(headers)

    def test_rv32_address_content_cannot_replace_rv64(self):
        headers = deepcopy(self.headers["fp16"]["frozen"])
        self.assertIn(b"8589672448", headers["sw/VX_types.h"])
        headers["sw/VX_types.h"] = headers["sw/VX_types.h"].replace(b"8589672448", b"2147418112")
        with self.assertRaisesRegex(ReplayError, "reproduced generated header sw/VX_types.h"):
            self.headers_receipt(headers)

    def test_truncated_or_appended_header_content_rejects(self):
        for body in (b"", self.headers["fp16"]["frozen"]["sw/VX_types.h"][:-1],
                     self.headers["fp16"]["frozen"]["sw/VX_types.h"] + b"\n#define VX_DCR_DATA_BITS 64\n"):
            headers = deepcopy(self.headers["fp16"]["frozen"])
            headers["sw/VX_types.h"] = body
            with self.subTest(size=len(body)), self.assertRaisesRegex(ReplayError, "reproduced generated header sw/VX_types.h"):
                self.headers_receipt(headers)

    def test_header_body_types_are_exact(self):
        for body in ("text", None, bytearray(self.headers["fp16"]["frozen"]["sw/VX_types.h"])):
            headers = deepcopy(self.headers["fp16"]["frozen"])
            headers["sw/VX_types.h"] = body
            with self.subTest(type=type(body)), self.assertRaisesRegex(ReplayError, "value type differs"):
                self.headers_receipt(headers)

    def test_retained_generator_is_never_loaded(self):
        sources = dict(self.sources, **{"ci/gen_config.py": b"raise AssertionError('retained code executed')\n"})
        with mock.patch.object(generated, "_render_headers", side_effect=AssertionError("rendered bad inputs")):
            with self.assertRaisesRegex(ReplayError, "retained configuration source ci/gen_config.py"):
                self.headers_receipt(sources=sources)

    def test_changed_toml_and_profile_reject_before_rendering(self):
        for name in ("VX_config.toml", "VX_types.toml", "profiles/p02-tfr.json"):
            sources = dict(self.sources)
            sources[name] += b"\nINJECTED = \"expr: __import__('os').system('false')\"\n"
            with self.subTest(source=name), mock.patch.object(
                    generated, "_render_headers", side_effect=AssertionError("rendered changed inputs")):
                with self.assertRaisesRegex(ReplayError, "retained configuration source " + name):
                    self.headers_receipt(sources=sources)

    def test_changed_trusted_input_fails_its_fixed_digest(self):
        real = generated.PacketReader.read_bytes

        def substituted(reader, name, *args, **kwargs):
            body = real(reader, name, *args, **kwargs)
            return body + b"\n" if name == "VX_types.toml" else body

        with mock.patch.object(generated.PacketReader, "read_bytes", substituted):
            with self.assertRaisesRegex(ReplayError, "trusted generated input VX_types.toml"):
                generated.trusted_generator_identity()

    def test_trusted_generator_module_and_origin_are_checked(self):
        for target, field in ((generated.TRUSTED_GENERATOR_MODULE, "__file__"),
                              (generated.TRUSTED_GENERATOR_MODULE.__spec__, "origin")):
            with self.subTest(field=field), mock.patch.object(target, field, "/recorded/producer/gen_config.py"):
                with self.assertRaisesRegex(ReplayError, "trusted configuration renderer module"):
                    self.headers_receipt()

    def test_private_renderer_rejects_unapproved_paths_and_writes(self):
        for name, mode in (("/recorded/producer/VX_types.toml", "r"),
                           (str(generated.ROOT / "VX_types.toml"), "w"),
                           (str(generated.ROOT / "VX_types.toml"), "rb")):
            with self.subTest(name=name, mode=mode):
                with self.assertRaisesRegex(ReplayError, "unapproved input"):
                    generated.TRUSTED_GENERATOR_MODULE.open(name, mode, encoding="utf-8")

    def test_rendering_does_not_use_ambient_environment_or_argv(self):
        expected = self.headers_receipt()
        with mock.patch.dict(os.environ, {"XLEN": "32", "__FILE__": "hostile", "__LINE__": "123456"}), \
                mock.patch.object(sys, "argv", ["untrusted-name.py", "--xlen=32"]):
            self.assertEqual(self.headers_receipt(), expected)
            self.assertEqual(os.environ["XLEN"], "32")
            self.assertEqual(sys.argv[0], "untrusted-name.py")

    def test_rendering_starts_no_subprocess_and_executes_no_generator_main(self):
        with mock.patch("subprocess.Popen", side_effect=AssertionError("process started")), \
                mock.patch("os.system", side_effect=AssertionError("shell started")), \
                mock.patch.object(generated.TRUSTED_GENERATOR_MODULE, "main", side_effect=AssertionError("main called")):
            self.headers_receipt()

    def test_original_full_generated_flags_reproduce_for_both_formats(self):
        for fmt, text in self.flags.items():
            with self.subTest(format=fmt):
                result = generated.validate_generated_flags(text, source_body=self.sources.__getitem__, fmt=fmt)
                self.assertEqual(result["format"], fmt)
                self.assertEqual(result["flags_count"], 273)
                self.assertEqual(result["flags_sha256"], hashlib.sha256(text.encode()).hexdigest())

    def test_changed_generated_flag_is_not_accepted_as_new_expectation(self):
        original = self.flags["fp16"]
        self.assertIn("-DVX_CFG_XLEN=64", original)
        for text in (original.replace("-DVX_CFG_XLEN=64", "-DVX_CFG_XLEN=32"),
                     original.replace("-DVX_CFG_NUM_WARPS=4", "-DVX_CFG_NUM_WARPS=8"),
                     original.rstrip() + " -DVX_INJECTED=1\n", original[:-1]):
            self.assertNotEqual(text, original)
            with self.subTest(digest=hashlib.sha256(text.encode()).hexdigest()):
                with self.assertRaisesRegex(ReplayError, "reproduced generated flags fp16"):
                    generated.validate_generated_flags(text, source_body=self.sources.__getitem__, fmt="fp16")

    def test_generated_flags_reject_changed_source_before_resolving(self):
        sources = dict(self.sources, **{"VX_config.toml": b"arbitrary expression"})
        with mock.patch.object(generated, "_resolve", side_effect=AssertionError("resolved changed source")):
            with self.assertRaisesRegex(ReplayError, "retained configuration source VX_config.toml"):
                generated.validate_generated_flags(self.flags["fp16"], source_body=sources.__getitem__, fmt="fp16")

    def test_generated_flags_use_private_environment(self):
        with mock.patch.dict(os.environ, {"XLEN": "32", "__FILE__": "bad", "__LINE__": "-8"}):
            for fmt in ("fp16", "bf16"):
                generated.validate_generated_flags(self.flags[fmt], source_body=self.sources.__getitem__, fmt=fmt)

    def test_generated_flags_format_is_closed(self):
        for fmt in ("fp32", "FP16", "", True, None, ["fp16"]):
            with self.subTest(format=fmt), self.assertRaisesRegex(ReplayError, "unsupported generated flags format"):
                generated.validate_generated_flags(self.flags["fp16"], source_body=self.sources.__getitem__, fmt=fmt)

    def test_receipt_states_retained_coverage_and_execution_limits(self):
        result = self.headers_receipt()
        self.assertFalse(result["retained_code_executed"])
        self.assertEqual(result["native_execution"], "not_run")
        self.assertEqual(result["generator"], generated.TRUSTED_GENERATOR_SOURCE)
        self.assertEqual({row["path"] for row in result["inputs"]}, set(generated.INPUT_SHA256))
        self.assertTrue(any("vortex_opae" in value and "not retained" in value for value in result["limitations"]))
        self.assertEqual(len(result["headers"]), 4)

    def test_coherently_rehashed_generated_header_mutation_rejects(self):
        with Packet() as packet, tempfile.TemporaryDirectory(prefix="p06-generated-control-") as directory:
            for fmt in ("fp16", "bf16"):
                for stage in ("configured", "backend", "frozen"):
                    name = "artifacts/simx-" + fmt + "/" + stage + "/sw/VX_types.h"
                    original = packet[PREFIX + name]
                    altered = original.replace(b"#define VX_DCR_DATA_BITS 32\n", b"#define VX_DCR_DATA_BITS 64\n")
                    self.assertNotEqual(original, altered)
                    packet.replace_retained(name, altered, aliases=("sw/VX_types.h",))
            packet.rehash_bindings()
            target = Path(directory) / "header-control.zip"
            digest = packet.write(target)
            with self.assertRaisesRegex(ReplayError, "reproduced generated header sw/VX_types.h"):
                replay(target, digest)


if __name__ == "__main__":
    unittest.main()

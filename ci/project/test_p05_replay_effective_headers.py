# SPDX-License-Identifier: Apache-2.0
"""Host-only effective-header joins; no compiler or retained code executes."""

import copy
from pathlib import Path
import unittest
from unittest.mock import patch

import p05_replay_native as replay
from test_p02_matrix import BUILD, SOURCE, STAMP_SAMPLES, sample
from test_p05_replay_native import MemoryView, descriptor


def compiler_fixture(fmt):
    app = "tests/regression/ai_mlp"
    prefix = "artifacts/simx-" + fmt
    application = sample("application", fmt=fmt).splitlines()
    application[2] = "-L" + str(BUILD / "sw/runtime") + " -lvortex"
    stamps = {
        "sw/runtime/simx_rt_config.stamp": sample("simx_rt", fmt=fmt).encode(),
        "sw/runtime/simx_config.stamp": sample("simx_backend", fmt=fmt).encode(),
        app + "/config.stamp": ("\n".join(application) + "\n").encode(),
    }
    view = MemoryView({prefix + "/" + name: body for name, body in stamps.items()})
    artifacts = {name: descriptor(name, body) for name, body in stamps.items()}
    return replay._build_records(view, prefix, artifacts, source=str(SOURCE), build=str(BUILD),
                                 jobs=2, fmt=fmt, app=app)


def effective_header(fmt):
    return STAMP_SAMPLES["header"] + "#define ITYPE " + fmt + "\n#define OTYPE fp32\n#define KUNROLL 1\n"


class EffectiveHeaderTests(unittest.TestCase):
    def test_both_formats_join_parsed_kernel_records_without_io_and_keep_summary_shape(self):
        for fmt in ("fp16", "bf16"):
            with self.subTest(format=fmt), \
                    patch.object(Path, "open", side_effect=AssertionError("filesystem read")), \
                    patch.object(Path, "resolve", side_effect=AssertionError("producer resolution")), \
                    patch("subprocess.Popen", side_effect=AssertionError("compiler launch")):
                records = compiler_fixture(fmt)
                self.assertEqual([record["role"] for record in records], ["runtime", "backend_cpp", "kernel", "host"])
                before = copy.deepcopy(records)
                text = effective_header(fmt)
                parsed = replay._effective_header_macros(text, records[2])
                self.assertEqual(parsed, replay.validate_header_macros(text))
                self.assertTrue(all(name.startswith("VX_CFG_") for name in parsed))
                self.assertEqual(records, before)

    def test_format_output_type_and_unroll_disagreement_cannot_hide_in_unchanged_summary(self):
        for fmt in ("fp16", "bf16"):
            kernel = compiler_fixture(fmt)[2]
            original = effective_header(fmt)
            summary = replay.validate_header_macros(original)
            for name, old, new in (("ITYPE", fmt, "bf16" if fmt == "fp16" else "fp16"),
                                   ("OTYPE", "fp32", "fp16"), ("KUNROLL", "1", "2")):
                text = original.replace("#define " + name + " " + old + "\n",
                                        "#define " + name + " " + new + "\n")
                with self.subTest(format=fmt, macro=name):
                    self.assertNotEqual(text, original)
                    self.assertEqual(replay.validate_header_macros(text), summary)
                    with self.assertRaisesRegex(ValueError, "effective header " + name + " differs"):
                        replay._effective_header_macros(text, kernel)

    def test_each_selected_macro_is_required_once_with_an_object_value(self):
        kernel = compiler_fixture("fp16")[2]
        original = effective_header("fp16")
        for name, value in (("ITYPE", "fp16"), ("OTYPE", "fp32"), ("KUNROLL", "1")):
            line = "#define " + name + " " + value + "\n"
            for mutation, text in (
                ("missing", original.replace(line, "")),
                ("empty", original.replace(line, "#define " + name + "\n")),
                ("duplicate", original + line),
                ("function", original.replace(line, "#define " + name + "(x) x\n")),
                ("second_function", original + "#define " + name + "(x) x\n"),
            ):
                with self.subTest(macro=name, mutation=mutation), self.assertRaises(ValueError):
                    replay._effective_header_macros(text, kernel)

    def test_base_header_and_shared_profile_validation_keep_their_contracts(self):
        kernel = compiler_fixture("fp16")[2]
        base = STAMP_SAMPLES["header"]
        self.assertEqual(replay.validate_header_macros(base)["VX_CFG_XLEN"], "64")
        with self.assertRaisesRegex(ValueError, "effective header must define ITYPE exactly once"):
            replay._effective_header_macros(base, kernel)
        changed = effective_header("fp16").replace("#define VX_CFG_XLEN 64\n", "#define VX_CFG_XLEN 32\n")
        self.assertNotEqual(changed, effective_header("fp16"))
        with self.assertRaisesRegex(ValueError, "generated header has missing/conflicting VX_CFG_XLEN"):
            replay._effective_header_macros(changed, kernel)

    def test_effective_header_requires_the_independent_kernel_role(self):
        records = compiler_fixture("fp16")
        for index in (0, 1, 3):
            with self.subTest(role=records[index]["role"]), \
                    self.assertRaisesRegex(ValueError, "effective-header compiler role differs"):
                replay._effective_header_macros(effective_header("fp16"), records[index])


if __name__ == "__main__":
    unittest.main()

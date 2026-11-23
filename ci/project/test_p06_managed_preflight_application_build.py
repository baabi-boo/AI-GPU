# SPDX-License-Identifier: Apache-2.0
"""Original-archive and adversarial application-build replay checks."""

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import unittest
from unittest import mock
import zipfile

from p06_managed_preflight_application_build import (
    CONTRACT_ID, MAX_LOG_BYTES, RECIPE_SHA256, validate_application_build,
)
from p06_managed_preflight_execute import validate_host_build


ARCHIVE = Path(__file__).resolve().parents[2] / (
    "docs/project/evidence/p06-managed-preflight/native/run-45085300171-attempt1.zip")
ARCHIVE_SHA256 = "cee5be4dba875494f6eafb83484933ab7693428e4773b932a26d5b91bd17969d"


class ApplicationBuildTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if hashlib.sha256(ARCHIVE.read_bytes()).hexdigest() != ARCHIVE_SHA256:
            raise AssertionError("application replay original archive identity changed")
        with zipfile.ZipFile(ARCHIVE) as archive:
            read = lambda name: archive.read("managed-preflight/" + name)
            report = json.loads(read("report.json"))
            tools = json.loads(read(report["tools_before"]["path"]))
            cls.recipes = {name: read("artifacts/source/" + name) for name in RECIPE_SHA256}
            cls.inputs = {}
            for variant in report["variants"]:
                command = next(row for row in report["commands"] if row["id"] == variant["application_build_command"])
                cls.inputs[variant["format"]] = {
                    "text": read(command["log"]).decode("utf-8"),
                    "stamp": read("artifacts/" + variant["id"] + "/frozen/tests/regression/ai_counter_preflight/config.stamp").decode("utf-8"),
                    "source": report["paths"]["source"], "build": variant["build_dir"],
                    "tools_root": report["paths"]["tools"], "tools": tools,
                    "fmt": variant["format"], "compiler_records": variant["compiler_records"],
                }

    def replay(self, fmt="fp16", **changes):
        args = dict(self.inputs[fmt], source_body=self.recipes.__getitem__)
        args.update(changes)
        return validate_application_build(**args)

    def changed(self, index, old, new, fmt="fp16"):
        lines = self.inputs[fmt]["text"].splitlines()
        self.assertIn(old, lines[index])
        lines[index] = lines[index].replace(old, new, 1)
        return "\n".join(lines) + "\n"

    def test_both_original_formats(self):
        expected_hashes = {
            "fp16": "3f9d5b9398697b24e9656429454a7f312d258d61521afd10f1c12c93d745c25b",
            "bf16": "0909ae2d2633310faf482f0e07ba691cb776a914bc967aaad93033c89ea694be",
        }
        for fmt, digest in expected_hashes.items():
            with self.subTest(fmt=fmt):
                receipt = self.replay(fmt)
                self.assertEqual(receipt["contract_id"], CONTRACT_ID)
                self.assertEqual(receipt["format"], fmt)
                self.assertEqual(receipt["command_count"], 30)
                self.assertEqual(receipt["command_counts"], {
                    "host_dependency": 1, "recursive_make": 2, "riscv_compile": 14,
                    "kernel_archive": 2, "archive_dump": 2, "kernel_clang": 5,
                    "kernel_conversion": 1, "kernel_dump": 1,
                    "stub_compile_link": 1, "host_compile_link": 1,
                })
                self.assertEqual(receipt["normalized_commands_sha256"], digest)
                self.assertEqual(receipt["recipe_sha256"], RECIPE_SHA256)

    def test_final_host_line_alone_no_longer_establishes_application_build(self):
        for fmt, original in self.inputs.items():
            with self.subTest(fmt=fmt):
                final = original["text"].splitlines()[-1] + "\n"
                host = validate_host_build(final, original["stamp"],
                    source=Path(original["source"]), build=Path(original["build"]),
                    compiler=original["tools"]["g++"]["path"])
                self.assertEqual(host["output"], "tests/regression/ai_counter_preflight/ai_counter_preflight")
                with self.assertRaisesRegex(ValueError, "missing or extra"):
                    self.replay(fmt, text=final)

    def test_every_command_is_required_in_both_formats(self):
        for fmt, original in self.inputs.items():
            lines = original["text"].splitlines()
            for index in range(30):
                with self.subTest(fmt=fmt, record=index + 1):
                    with self.assertRaisesRegex(ValueError, "missing or extra"):
                        self.replay(fmt, text="\n".join(lines[:index] + lines[index + 1:]))

    def test_extra_duplicate_or_unrelated_shell_commands_fail(self):
        original = self.inputs["fp16"]["text"]
        for extra in (original.splitlines()[3], original.splitlines()[-1], "echo unrelated", "/usr/bin/true"):
            with self.subTest(extra=extra[:30]):
                with self.assertRaisesRegex(ValueError, "missing or extra"):
                    self.replay(text=original + extra + "\n")
        lines = original.splitlines()
        for replacement in (lines[3], "echo unrelated"):
            with self.subTest(replacement=replacement[:30]):
                with self.assertRaises(ValueError):
                    self.replay(text="\n".join(lines[:4] + [replacement] + lines[5:]))

    def test_compiler_identity_in_each_command_family(self):
        for index in (0, 3, 21, 28, 29):
            command = self.inputs["fp16"]["text"].splitlines()[index]
            with self.subTest(record=index + 1):
                with self.assertRaisesRegex(ValueError, "altered command"):
                    self.replay(text=self.changed(index, command.split()[0], "/different/compiler"))

    def test_abi_optimization_and_configuration_are_exact(self):
        controls = (
            (3, "-march=rv64imafd", "-march=rv32imaf"),
            (3, "-mabi=lp64d", "-mabi=lp64"),
            (3, "-O3", "-O0"),
            (3, "-fdata-sections", "-ffast-math"),
            (10, "-DKMU_ENABLE", "-DKMU_DISABLE"),
            (21, "--target=riscv64-unknown-elf", "--target=riscv32-unknown-elf"),
            (21, "-DITYPE=fp16", "-DITYPE=bf16"),
            (21, "-DSIMX_CHECKED_COUNTERS=1", "-DSIMX_CHECKED_COUNTERS=0"),
            (21, "-O3", "-O2"),
            (28, "-O2", "-O0"),
            (28, "-fPIC", "-fPIE"),
            (28, "-DNDEBUG", "-DDEBUG"),
            (29, "-O2", "-O3"),
            (1, "PERF=1", "PERF=0"),
        )
        for index, old, new in controls:
            with self.subTest(record=index + 1, flag=old):
                with self.assertRaisesRegex(ValueError, "altered command"):
                    self.replay(text=self.changed(index, old, new))

    def test_source_output_and_link_inputs_are_exact(self):
        controls = (
            (0, "> .depend;", "> wrong.depend;"),
            (3, "/sw/kernel/src/vx_start.S", "/sw/kernel/src/vx_print.S"),
            (3, "-o vx_start.S.o", "-o vx_print.S.o"),
            (21, "/sw/kernel/ai/matmul.cpp", "/sw/kernel/ai/other.cpp"),
            (23, "vx_start.o matmul.o", "vx_start.o foreign.o"),
            (23, "STARTUP_ADDR=0x180000000", "STARTUP_ADDR=0x80000000"),
            (25, "/sw/kernel/libvortex2.a", "/sw/kernel/libvortex.a"),
            (25, "-lm -lc", "-lc -lm"),
            (25, "-o kernel.elf", "-o other.elf"),
            (28, "/sw/runtime/common/queue.cpp", "/sw/runtime/common/other.cpp"),
            (28, "-shared -pthread -ldl", "-shared -ldl"),
            (28, "-Wl,-soname,libvortex.so", "-Wl,-soname,foreign.so"),
            (29, "/ai_warm_workspace/observer.cpp", "/ai_warm_workspace/main.cpp"),
            (29, "-lvortex-simx", "-lvortex-rtlsim"),
        )
        for index, old, new in controls:
            with self.subTest(record=index + 1, value=old):
                with self.assertRaisesRegex(ValueError, "altered command"):
                    self.replay(text=self.changed(index, old, new))

    def test_archive_members_and_order_are_exact(self):
        for index, first, second in ((17, "vx_start.S.o", "vx_syscalls.c.o"),
                                     (18, "vx_start.S.2.o", "vx_syscalls.c.2.o")):
            for old, new in ((first, second), (first + " ", ""),
                             (first + " " + second, second + " " + first)):
                with self.subTest(record=index + 1, replacement=new):
                    with self.assertRaisesRegex(ValueError, "altered command"):
                        self.replay(text=self.changed(index, old, new))

    def test_startup_substitution_is_exact_inert_grammar(self):
        source = self.inputs["fp16"]["source"]
        original = self.inputs["fp16"]["text"].splitlines()[24]
        substitution = original[original.index("$("):original.index("vx_start.o.elf)") + len("vx_start.o.elf)")]
        for old, new in (
            ("/scripts/kernel_startup.sh", "/scripts/other.sh"),
            ("vx_start.o.elf)", "other.elf)"),
            ("&& rm -f vx_start.o.elf", "; rm -f vx_start.o.elf"),
            (substitution, "'" + substitution + "'"),
            (substitution, "`" + substitution[2:-1] + "`"),
            ("$(" + source, "$(echo injected; " + source),
        ):
            with self.subTest(replacement=new[:60]):
                with self.assertRaisesRegex(ValueError, "altered command"):
                    self.replay(text=self.changed(24, old, new))

    def test_stub_origin_quote_semantics_are_preserved(self):
        for replacement in ("$ORIGIN", '"$ORIGIN"', "'$OTHER'", "'$(echo injected)'"):
            with self.subTest(replacement=replacement):
                with self.assertRaisesRegex(ValueError, "altered command"):
                    self.replay(text=self.changed(28, "'$ORIGIN'", replacement))

    def test_vxbin_and_dump_commands_are_exact(self):
        for index, old, new in (
            (26, "/bin/llvm-objcopy", "/bin/llvm-objdump"),
            (26, "/scripts/vxbin.py", "/scripts/other.py"),
            (26, "kernel.elf kernel.vxbin", "foreign.elf kernel.vxbin"),
            (26, "kernel.vxbin", "other.vxbin"),
            (27, "> kernel.dump", "> other.dump"),
            (19, "-D libvortex.a", "-D libvortex2.a"),
        ):
            with self.subTest(record=index + 1, value=old):
                with self.assertRaisesRegex(ValueError, "altered command"):
                    self.replay(text=self.changed(index, old, new))

    def test_compiler_records_and_stamps_must_agree(self):
        stamp = self.inputs["fp16"]["stamp"].replace("-O3", "-O0", 1)
        with self.assertRaisesRegex(ValueError, "independent kernel record"):
            self.replay(stamp=stamp)
        records = deepcopy(self.inputs["fp16"]["compiler_records"])
        records[2]["original_record"] = stamp.splitlines()[0]
        with self.assertRaisesRegex(ValueError, "unexpected compiler option"):
            self.replay(stamp=stamp, compiler_records=records)

    def test_unreviewed_recipe_body_fails_closed(self):
        for name in self.recipes:
            changed = dict(self.recipes, **{name: self.recipes[name] + b"\n"})
            with self.subTest(recipe=name):
                with self.assertRaisesRegex(ValueError, "unsupported retained application recipe"):
                    self.replay(source_body=changed.__getitem__)

    def test_selected_tools_cannot_be_replaced_internally(self):
        for name in ("riscv-gcc", "riscv-gcc-ar", "clang++", "llvm-objcopy", "g++", "make"):
            tools = deepcopy(self.inputs["fp16"]["tools"])
            tools[name]["path"] = "/different/selected-tool"
            with self.subTest(tool=name):
                with self.assertRaises(ValueError):
                    self.replay(tools=tools)

    def test_prerequisites_precede_consumers(self):
        for earlier, later in ((3, 17), (21, 23), (23, 24), (25, 26), (28, 29)):
            lines = self.inputs["fp16"]["text"].splitlines()
            lines[earlier], lines[later] = lines[later], lines[earlier]
            with self.subTest(earlier=earlier + 1, later=later + 1):
                with self.assertRaisesRegex(ValueError, "precedes its prerequisites"):
                    self.replay(text="\n".join(lines))

    def test_independent_parallel_work_can_reorder(self):
        lines = self.inputs["fp16"]["text"].splitlines()
        reordered = lines[:3] + lines[28:] + [lines[4], lines[3]] + lines[5:28]
        receipt = self.replay(text="\n".join(reordered))
        self.assertEqual(receipt["command_count"], 30)
        self.assertEqual(receipt["command_order"][3:5], ["stub-link", "host-link"])

    def test_ascii_spacing_blank_lines_and_final_newline(self):
        original = self.inputs["fp16"]["text"]
        varied = "\n\t\n" + "\n\n".join("\t" + line.replace(" ", " \t ") + "\t"
                                            for line in original.splitlines())
        expected = self.replay()["normalized_commands_sha256"]
        self.assertEqual(self.replay(text=varied)["normalized_commands_sha256"], expected)
        self.assertEqual(self.replay(text=original.rstrip("\n"))["normalized_commands_sha256"], expected)

    def test_control_characters_and_new_command_boundaries_fail(self):
        for control in ("\x00", "\r", "\v", "\x85", "\u2028", "\u00a0"):
            with self.subTest(control=repr(control)):
                with self.assertRaisesRegex(ValueError, "control characters or record separators"):
                    self.replay(text=self.inputs["fp16"]["text"] + control)
        for replacement in ("\n-O3", "\\\n-O3"):
            with self.subTest(replacement=repr(replacement)):
                with self.assertRaisesRegex(ValueError, "missing or extra"):
                    self.replay(text=self.changed(3, "-O3", replacement))

    def test_relocated_producer_paths_and_substitutions_are_never_opened_or_run(self):
        args = deepcopy(self.inputs["fp16"])
        replacements = {args["source"]: "/unmounted/recorded-source",
                        args["build"]: "/unmounted/recorded-build",
                        args["tools_root"]: "/unmounted/recorded-tools"}
        encoded = json.dumps(args)
        for old, new in replacements.items():
            encoded = encoded.replace(old, new)
        args = json.loads(encoded)
        args["source_body"] = self.recipes.__getitem__
        with mock.patch("builtins.open", side_effect=AssertionError("filesystem read")), \
             mock.patch("pathlib.Path.read_bytes", side_effect=AssertionError("path read")), \
             mock.patch("subprocess.run", side_effect=AssertionError("process execution")), \
             mock.patch("subprocess.Popen", side_effect=AssertionError("process execution")), \
             mock.patch("os.system", side_effect=AssertionError("shell execution")):
            self.assertEqual(validate_application_build(**args)["command_count"], 30)

    def test_inputs_are_not_mutated(self):
        before = deepcopy(self.inputs)
        self.replay()
        self.assertEqual(self.inputs, before)

    def test_log_bounds(self):
        for text in (None, b"not text", "x" * (MAX_LOG_BYTES + 1)):
            with self.subTest(kind=type(text).__name__):
                with self.assertRaisesRegex(ValueError, "bounded text"):
                    self.replay(text=text)


if __name__ == "__main__":
    unittest.main()

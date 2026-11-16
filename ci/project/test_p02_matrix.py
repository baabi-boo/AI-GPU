# SPDX-License-Identifier: Apache-2.0
"""Independent, Python-only contract tests for the P02 matrix runner.

Run from the checkout root with its ci/project directory on PYTHONPATH. The
runner's process boundary is mocked; none of these tests compiles or launches
GPU code. Generated compiler records below are retained probe samples, with
only source/build/tool path prefixes normalized. They are not reconstructed
from the validator's implementation. Their original SHA-256 identities are
recorded alongside the samples.
"""

from contextlib import ExitStack, redirect_stderr, redirect_stdout
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import struct
import tempfile
import unittest
from unittest import mock

import p02_matrix as matrix
import p02_matrix_records as records
import p02_wmma_fixtures as fixtures


ROOT = matrix.ROOT
APP = "tests/regression/sgemm_tcu"
SOURCE = Path("/p02-fixture/source")
BUILD = Path("/p02-fixture/build")
TOOLS = Path("/p02-fixture/tools")

# This record fixture checks the transport, including signed zero and NaN bits;
# it is not an arithmetic oracle or an assertion that this arbitrary matrix ran.
OUTPUT_CASE = {
    "id": "transport-bits", "format": "bf16", "m": 8, "n": 4, "k": 8,
    "expected": ["00000000", "80000000", "7f800000", "ff800000",
                 "7fc00000", "3f800000", "bf800000", "00000001"] * 4,
}


def result_record(case=OUTPUT_CASE, iteration=0):
    return {"case_id": case["id"], "format": case["format"],
            "m": case["m"], "n": case["n"], "k": case["k"],
            "iteration": iteration, "checked": case["m"] * case["n"],
            "mismatches": 0, "actual_bits": list(case["expected"])}


def output_text(case=OUTPUT_CASE, iterations=2, *, values=None):
    if values is None:
        values = [result_record(case, index) for index in range(iterations)]
    return "Launching fixture\n" + "".join(
        "P02_RESULT " + json.dumps(value, separators=(",", ":")) + "\n"
        for value in values) + "PASSED!\n"


def sample(name, *, source=SOURCE, build=BUILD, tools=TOOLS, fmt="bf16"):
    text = STAMP_SAMPLES[name]
    for marker, value in (("@SOURCE@", source), ("@BUILD@", build), ("@TOOLS@", tools)):
        text = text.replace(marker, str(value))
    # The actual retained stamps are BF16. The simulated workflow may exercise
    # the same command-record shape with the one declared application selector.
    if fmt != "bf16":
        text = text.replace("-DITYPE=bf16", "-DITYPE=" + fmt)
    return text


def parse_args(*extra):
    return matrix.argument_parser().parse_args([
        "run", "--tools-dir", str(TOOLS), "--work-dir", "/p02-fixture/work",
        "--output", "/p02-fixture/output", *extra])


class SelectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cases = fixtures.load_cases(ROOT)

    def test_defaults_request_exactly_88_cases_and_all_four_variants(self):
        before = copy.deepcopy(self.cases)
        selected, variants, full = matrix.select_cases(self.cases, parse_args())
        self.assertEqual(len(selected), 88)
        self.assertEqual(variants, [("simx", "fp16"), ("simx", "bf16"),
                                    ("rtlsim", "fp16"), ("rtlsim", "bf16")])
        self.assertTrue(full)
        self.assertEqual(sum(sum(case["format"] == fmt for case in selected)
                             for _, fmt in variants), 176)
        self.assertEqual(self.cases, before)

    def test_development_selection_preserves_corpus_order(self):
        chosen = [case for case in self.cases if case["format"] == "bf16"][:2]
        args = parse_args("--development", "--backend", "rtlsim", "--format", "bf16",
                          "--case", chosen[1]["id"], "--case", chosen[0]["id"],
                          "--iterations", "1")
        selected, variants, full = matrix.select_cases(self.cases, args)
        self.assertEqual(selected, chosen)
        self.assertEqual(variants, [("rtlsim", "bf16")])
        self.assertFalse(full)

    def test_partial_or_single_iteration_formal_requests_are_rejected(self):
        for options in (("--backend", "simx"), ("--format", "fp16"),
                        ("--case", self.cases[0]["id"]), ("--iterations", "1")):
            with self.subTest(options=options), self.assertRaisesRegex(ValueError, "development"):
                matrix.select_cases(self.cases, parse_args(*options))

    def test_duplicate_backend_format_and_case_requests_are_rejected(self):
        for flag, value in (("--backend", "simx"), ("--format", "bf16"),
                            ("--case", self.cases[0]["id"])):
            args = parse_args("--development", flag, value, flag, value)
            with self.subTest(flag=flag), self.assertRaisesRegex(ValueError, "duplicate"):
                matrix.select_cases(self.cases, args)

    def test_unknown_empty_and_conflicting_case_selections_are_rejected(self):
        wrong_format = "bf16" if self.cases[0]["format"] == "fp16" else "fp16"
        candidates = [parse_args("--development", "--case", "does-not-exist"),
                      parse_args("--development", "--format", wrong_format,
                                 "--case", self.cases[0]["id"])]
        empty = parse_args("--development")
        empty.case = []
        candidates.append(empty)
        for args in candidates:
            with self.subTest(args=args), self.assertRaises(ValueError):
                matrix.select_cases(self.cases, args)

    def test_corrupt_inventory_is_rejected_before_selection(self):
        mutations = [lambda data: data.pop(),
                     lambda data: data.__setitem__(-1, copy.deepcopy(data[0])),
                     lambda data: data[0].__setitem__("id", "../escape"),
                     lambda data: data[0].__setitem__("id", "a;touch_bad"),
                     lambda data: data[0].__setitem__("format", "tf32")]
        for key, value in (("m", True), ("m", 8.0), ("m", 0), ("m", 7),
                           ("n", 3), ("k", 4), ("k", 8192)):
            mutations.append(lambda data, key=key, value=value: data[0].__setitem__(key, value))
        for key in ("a_words", "b_words", "expected"):
            mutations.append(lambda data, key=key: data[0][key].pop())
            mutations.append(lambda data, key=key: data[0][key].__setitem__(0, "FFFFFFFF"))
            mutations.append(lambda data, key=key: data[0][key].__setitem__(0, 0))
        for index, mutate in enumerate(mutations):
            candidate = copy.deepcopy(self.cases)
            mutate(candidate)
            with self.subTest(mutation=index), self.assertRaises(ValueError):
                matrix.select_cases(candidate, parse_args("--development"))

    def test_parser_limits_and_unknown_options_fail_closed(self):
        options = [("--backend", "xrt"), ("--format", "fp8"), ("--iterations", "0"),
                   ("--iterations", "3"), ("--iterations", "true"), ("--jobs", "3"),
                   ("--jobs", "0"), ("--timeout-seconds", "0"),
                   ("--timeout-seconds", "1801"), ("--run-timeout-seconds", "1.5"),
                   ("--accept",), ("--waive",)]
        for extra in options:
            with self.subTest(extra=extra), redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
                parse_args(*extra)
            self.assertEqual(error.exception.code, 2)
        args = parse_args("--timeout-seconds", "1", "--run-timeout-seconds", "1800")
        self.assertEqual((args.timeout_seconds, args.run_timeout_seconds), (1, 1800))
        self.assertEqual((args.jobs, args.iterations, args.development), (2, 2, False))


class PathTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="p02-path-")
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name).resolve()
        self.source, self.tools = self.base / "source", self.base / "tools"
        self.source.mkdir()
        self.tools.mkdir()
        patcher = mock.patch.object(matrix, "ROOT", self.source)
        patcher.start()
        self.addCleanup(patcher.stop)

    def arguments(self, **changes):
        args = parse_args()
        args.source_dir, args.tools_dir = self.source, self.tools
        args.work_dir, args.output = self.base / "work", self.base / "output"
        for key, value in changes.items():
            setattr(args, key, value)
        return args

    def test_fresh_disjoint_paths_are_returned_without_creation(self):
        paths = matrix.resolve_paths(self.arguments())
        self.assertEqual(paths["source"], self.source)
        self.assertFalse(paths["work"].exists())
        self.assertFalse(paths["output"].exists())

    def test_shell_metacharacters_whitespace_and_controls_are_rejected(self):
        for name in ("bad name", "bad;name", "bad$name", "bad`name", "bad'name",
                     "bad\nname", "bad\tname", "bad(name)", "bad\\name", "bad*name"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                matrix.resolve_paths(self.arguments(work_dir=self.base / name))

    def test_symlink_ancestors_and_dangling_destinations_are_rejected(self):
        link = self.base / "linked"
        link.symlink_to(self.tools, target_is_directory=True)
        dangling = self.base / "dangling"
        dangling.symlink_to(self.base / "absent")
        for changes in ({"tools_dir": link}, {"work_dir": link / "new"},
                        {"output": dangling}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                matrix.resolve_paths(self.arguments(**changes))

    def test_existing_destinations_and_missing_parents_are_rejected(self):
        existing_dir, existing_file = self.base / "existing-dir", self.base / "existing-file"
        existing_dir.mkdir()
        existing_file.write_text("preserve me")
        for value in (existing_dir, existing_file, self.base / "missing-parent/new"):
            for field in ("work_dir", "output"):
                with self.subTest(value=value, field=field), self.assertRaises(ValueError):
                    matrix.resolve_paths(self.arguments(**{field: value}))
        self.assertEqual(existing_file.read_text(), "preserve me")

    def test_equal_nested_and_input_overlapping_roots_are_rejected(self):
        candidates = [dict(output=self.base / "work"),
                      dict(output=self.base / "work/nested"),
                      dict(work_dir=self.source / "new-build"),
                      dict(output=self.tools / "new-output"),
                      dict(output=self.source.parent)]
        for changes in candidates:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                matrix.resolve_paths(self.arguments(**changes))
        self.assertTrue(matrix._overlap(self.base / "a", self.base / "a/b"))
        self.assertFalse(matrix._overlap(self.base / "a", self.base / "ab"))

    def test_runner_must_belong_to_selected_checkout(self):
        other = self.base / "other-source"
        other.mkdir()
        with self.assertRaisesRegex(ValueError, "selected source checkout"):
            matrix.resolve_paths(self.arguments(source_dir=other))

    def test_host_directory_and_verilator_entrypoint_are_checked(self):
        tool = self.tools / "verilator/bin/verilator"
        tool.parent.mkdir(parents=True)
        tool.write_text("fixture")
        paths = matrix.resolve_paths(self.arguments(verilator=tool))
        self.assertEqual(paths["verilator"], self.tools / "verilator")
        with self.assertRaisesRegex(ValueError, "host-bin must be a directory"):
            matrix.resolve_paths(self.arguments(host_bin=tool))

    def test_environment_does_not_inherit_configuration_or_loader_overrides(self):
        paths = matrix.resolve_paths(self.arguments())
        with mock.patch.dict(os.environ, {"CONFIGS": "-Ofast", "LD_PRELOAD": "bad.so",
                                         "MAKEFLAGS": "-j99", "PYTHONPATH": "/bad"}):
            env = matrix.clean_environment(paths, 2)
        for key in ("CONFIGS", "LD_PRELOAD", "PYTHONPATH"):
            self.assertNotIn(key, env)
        self.assertEqual(env["MAKEFLAGS"], "-j2")
        self.assertEqual(env["TMPDIR"], str(paths["work"] / "tmp"))
        self.assertEqual(env["HOME"], str(paths["work"] / "home"))
        self.assertEqual(env["CCACHE_DISABLE"], "1")


class OutputRecordTests(unittest.TestCase):
    def reject(self, text, *, iterations=2):
        with self.assertRaises(ValueError):
            records.verify_output(text, OUTPUT_CASE, iterations)

    def test_exact_records_accept_only_declared_repeats_and_little_endian_digest(self):
        for count in (1, 2):
            observations = records.verify_output(output_text(iterations=count), OUTPUT_CASE, count)
            expected_digest = hashlib.sha256(struct.pack("<32I", *[
                int(value, 16) for value in OUTPUT_CASE["expected"]])).hexdigest()
            self.assertEqual(observations, [
                {"iteration": index, "checked": 32, "mismatches": 0,
                 "actual_bits_sha256": expected_digest} for index in range(count)])

    def test_malformed_json_duplicate_fields_and_non_object_records_are_rejected(self):
        valid = json.dumps(result_record())
        payloads = ["{", "[]", "null", "42", '"string"', valid + "garbage",
                    valid[:-1] + ', "m":8}', valid[:-1] + ', "iteration":0}',
                    valid.replace('"m": 8', '"m": NaN'),
                    valid.replace('"m": 8', '"m": Infinity')]
        for payload in payloads:
            with self.subTest(payload=payload[:70]):
                self.reject("P02_RESULT " + payload + "\nPASSED!\n", iterations=1)

    def test_missing_and_extra_fields_are_rejected(self):
        baseline = result_record()
        for key in baseline:
            candidate = copy.deepcopy(baseline)
            del candidate[key]
            with self.subTest(missing=key):
                self.reject(output_text(iterations=1, values=[candidate]), iterations=1)
        candidate = dict(baseline, accepted=True)
        self.reject(output_text(iterations=1, values=[candidate]), iterations=1)

    def test_deeply_nested_json_is_rejected(self):
        # 20 KB is far below the command log budget. The decoder may reject
        # nesting with RecursionError; the separate workflow regression verifies
        # that this RuntimeError subclass becomes a finished failure report.
        malformed = "P02_RESULT " + "[" * 10000 + "0" + "]" * 10000 + "\nPASSED!\n"
        with self.assertRaises((ValueError, RecursionError)):
            records.verify_output(malformed, OUTPUT_CASE, 1)

    def test_boolean_float_string_and_null_integer_fields_are_rejected(self):
        for key in ("m", "n", "k", "iteration", "checked", "mismatches"):
            for value in (True, False, float(result_record()[key]), str(result_record()[key]), None):
                candidate = result_record()
                candidate[key] = value
                with self.subTest(field=key, value=value):
                    self.reject(output_text(iterations=1, values=[candidate]), iterations=1)

    def test_wrong_identity_dimensions_checked_count_and_mismatches_are_rejected(self):
        for key, value in (("case_id", "another"), ("format", "fp16"),
                           ("m", 16), ("n", 8), ("k", 16),
                           ("checked", 31), ("checked", 33), ("mismatches", 1),
                           ("mismatches", -1)):
            candidate = result_record()
            candidate[key] = value
            with self.subTest(field=key, value=value):
                self.reject(output_text(iterations=1, values=[candidate]), iterations=1)

    def test_every_raw_word_and_its_representation_is_checked(self):
        for index, value in ((0, "80000000"), (1, "00000000"), (4, "7fc00001"),
                             (31, "00000000"), (0, "0000000"), (0, "0x00000000"),
                             (4, "7FC00000"), (0, 0), (0, False)):
            candidate = result_record()
            candidate["actual_bits"][index] = value
            with self.subTest(index=index, value=value):
                self.reject(output_text(iterations=1, values=[candidate]), iterations=1)
        for bits in ([], OUTPUT_CASE["expected"][:-1], OUTPUT_CASE["expected"] + ["00000000"],
                     "00000000", None, {"0": "00000000"}):
            candidate = dict(result_record(), actual_bits=bits)
            with self.subTest(bits_type=type(bits).__name__, length=len(bits) if bits is not None else None):
                self.reject(output_text(iterations=1, values=[candidate]), iterations=1)

    def test_missing_extra_duplicate_and_reordered_iterations_are_rejected(self):
        for indices in ([], [0], [1], [0, 0], [1, 0], [0, 2], [0, 1, 2]):
            with self.subTest(indices=indices):
                self.reject(output_text(values=[result_record(iteration=i) for i in indices]))
        self.reject(output_text(), iterations=1)
        for iterations in (0, 3, -1):
            self.reject(output_text(), iterations=iterations)

    def test_missing_repeated_prefixed_and_reordered_markers_are_rejected(self):
        good = output_text()
        cases = [good.replace("PASSED!\n", ""), good + "PASSED!\n",
                 good.replace("PASSED!", "PASSED"), "PASSED!\n" + good.replace("PASSED!\n", ""),
                 good.replace("P02_RESULT ", " P02_RESULT ", 1),
                 good.replace("P02_RESULT ", "P02_RESULT=", 1),
                 good.replace("P02_RESULT ", "prefix P02_RESULT ", 1),
                 "PASSED earlier\n" + good, good + "unexpected trailer\n"]
        for index, candidate in enumerate(cases):
            with self.subTest(candidate=index):
                self.reject(candidate)

    def test_failure_markers_and_control_bytes_are_rejected(self):
        for marker in ("FAILED", "FAIL", "ERROR", "FATAL", "ABORTED", "MISMATCH",
                       "Assertion x failed", "Segmentation fault", "core dumped", "runtime error:",
                       "\x00", "\x1b[32m"):
            with self.subTest(marker=marker):
                self.reject(marker + "\n" + output_text())

    def test_only_make_directory_trailer_and_whitespace_follow_success(self):
        good = output_text() + "\nmake[1]: Leaving directory '/fixture'\n\n"
        self.assertEqual(len(records.verify_output(good, OUTPUT_CASE, 2)), 2)
        self.reject(output_text() + "make[1]: Entering directory '/fixture'\n")


class CompilerRecordTests(unittest.TestCase):
    def stamps(self, driver="simx"):
        return [sample(driver + "_rt"), sample(driver + "_backend"), sample("application")]

    def validate(self, values, driver="simx"):
        return records.validate_records(*values, driver=driver, fmt="bf16", source=SOURCE,
                                        build=BUILD, jobs=2)

    def test_real_generated_bf16_records_validate_independently_for_both_backends(self):
        for driver, roles in (("simx", ["runtime", "backend_cpp", "kernel", "host"]),
                              ("rtlsim", ["runtime", "verilator", "backend_cpp", "kernel", "host"])):
            with self.subTest(driver=driver):
                values = self.stamps(driver)
                result = self.validate(values, driver)
                self.assertEqual([item["role"] for item in result], roles)
                self.assertTrue(all(item["configuration"]["ITYPE"] == "bf16" for item in result))

    def test_missing_extra_and_reordered_independent_records_are_rejected(self):
        for driver in ("simx", "rtlsim"):
            for index in range(3):
                for mutation in ("missing", "duplicate"):
                    values = self.stamps(driver)
                    lines = values[index].splitlines()
                    values[index] = "\n".join(lines[1:] if mutation == "missing" else lines + [lines[0]])
                    with self.subTest(driver=driver, stamp=index, mutation=mutation), self.assertRaises(ValueError):
                        self.validate(values, driver)
            values = self.stamps(driver)
            lines = values[2].splitlines()
            values[2] = "\n".join([lines[1], lines[0], lines[2]])
            with self.subTest(driver=driver, mutation="reordered"), self.assertRaises(ValueError):
                self.validate(values, driver)

    def test_configuration_cannot_be_pooled_across_records(self):
        for driver in ("simx", "rtlsim"):
            values = self.stamps(driver)
            for stamp_index, text in enumerate(values):
                lines = text.splitlines()
                for line_index in range(len(lines) - (1 if stamp_index == 2 else 0)):
                    candidate = list(values)
                    changed = list(lines)
                    self.assertIn("-DVX_CFG_NUM_THREADS=4", changed[line_index])
                    changed[line_index] = changed[line_index].replace("-DVX_CFG_NUM_THREADS=4", "")
                    candidate[stamp_index] = "\n".join(changed)
                    with self.subTest(driver=driver, stamp=stamp_index, record=line_index), self.assertRaises(ValueError):
                        self.validate(candidate, driver)

    def test_arithmetic_record_requires_resolved_native_selectors(self):
        for driver in ("simx", "rtlsim"):
            for selector in ("VX_CFG_TCU_TYPE_TFR", "VX_CFG_FPU_TYPE_STD"):
                values = self.stamps(driver)
                lines = values[1].splitlines()
                self.assertIn("-D" + selector, lines[0])
                lines[0] = lines[0].replace("-D" + selector, "")
                values[1] = "\n".join(lines)
                with self.subTest(driver=driver, selector=selector), self.assertRaisesRegex(
                        ValueError, "resolved native arithmetic selector"):
                    self.validate(values, driver)

    def test_actual_pre_fix_simx_record_is_rejected(self):
        values = self.stamps()
        values[1] = sample("simx_backend_missing_selectors")
        with self.assertRaisesRegex(ValueError, "resolved native arithmetic selector"):
            self.validate(values)

    def test_forwarded_fast_math_is_rejected_in_every_cpp_record(self):
        for stamp_index, line_indices in ((0, (0,)), (1, (0,)), (2, (0, 1))):
            for line_index in line_indices:
                for flag in ("-Wp,-Ofast", "-Xpreprocessor -Ofast",
                             "-D__FAST_MATH__=1", "-D__FINITE_MATH_ONLY__=1"):
                    values = self.stamps()
                    lines = values[stamp_index].splitlines()
                    lines[line_index] = lines[line_index].replace(" -O2 ", " ") + " " + flag
                    values[stamp_index] = "\n".join(lines)
                    with self.subTest(stamp=stamp_index, line=line_index, flag=flag), self.assertRaisesRegex(
                            ValueError, "fast math"):
                        self.validate(values)

    def test_arithmetic_macro_probe_keeps_raw_and_resolved_flags(self):
        for driver in ("simx", "rtlsim"):
            result = self.validate(self.stamps(driver), driver)
            flags = result[1]["macro_flags"]
            for flag in ("-DVX_CFG_TCU_TYPE=TFR", "-DVX_CFG_TCU_TYPE_TFR",
                         "-DVX_CFG_FPU_TYPE=STD", "-DVX_CFG_FPU_TYPE_STD",
                         "-DVX_CFG_TCU_FP8_DISABLE"):
                with self.subTest(driver=driver, flag=flag):
                    self.assertIn(flag, flags)

    def test_conflicting_native_format_disable_and_fast_math_flags_are_rejected(self):
        replacements = [("-DVX_CFG_TCU_TYPE=TFR", "-DVX_CFG_TCU_TYPE=DPI"),
                        ("-DITYPE=bf16", "-DITYPE=fp16"), ("-DOTYPE=fp32", "-DOTYPE=fp16"),
                        ("-DKUNROLL=1", "-DKUNROLL=2"),
                        ("-DVX_CFG_TCU_FP8_DISABLE", "-DVX_CFG_TCU_FP8_ENABLE=0")]
        for old, new in replacements:
            for stamp_index in range(3):
                values = self.stamps()
                self.assertIn(old, values[stamp_index])
                values[stamp_index] = values[stamp_index].replace(old, new)
                with self.subTest(stamp=stamp_index, replacement=new), self.assertRaises(ValueError):
                    self.validate(values)
        for flag in ("-ffast-math", "-Ofast", "-UVX_CFG_NUM_THREADS", "@response.txt",
                     ";touch bad", "$(touch bad)"):
            values = self.stamps()
            values[0] = values[0].rstrip() + " " + flag + "\n"
            with self.subTest(flag=flag), self.assertRaises(ValueError):
                self.validate(values)

    def test_rtl_jobs_packages_and_linker_binding_cannot_drift(self):
        original = self.stamps("rtlsim")
        for old, new in (("-j 2", "-j 3"), ("--top-module rtlsim_shim", "--top-module other"),
                         (str(SOURCE / "hw/rtl/VX_gpu_pkg.sv"), str(SOURCE / "hw/rtl/other.sv"))):
            values = list(original)
            self.assertIn(old, values[1])
            values[1] = values[1].replace(old, new)
            with self.subTest(replacement=new), self.assertRaises(ValueError):
                self.validate(values, "rtlsim")
        values = self.stamps()
        values[2] = values[2].replace("-L" + str(BUILD / "sw/runtime"), "-L/another/runtime")
        with self.assertRaisesRegex(ValueError, "binding"):
            self.validate(values)

    def test_real_generated_header_and_conflicting_macros(self):
        header = STAMP_SAMPLES["header"]
        observed = records.validate_header_macros(header)
        self.assertEqual(observed["VX_CFG_XLEN"], "64")
        self.assertEqual(observed["VX_CFG_TCU_TYPE_TFR"], "1")
        for extra in ("#define VX_CFG_NUM_THREADS 4\n", "#define VX_CFG_TCU_FP8_ENABLE 0\n",
                      "#define VX_CFG_TCU_TYPE_DPI 1\n", "#define DEBUG 1\n",
                      "#define __FAST_MATH__ 1\n"):
            with self.subTest(extra=extra), self.assertRaises(ValueError):
                records.validate_header_macros(header + extra)


class RunWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cases = fixtures.load_cases(ROOT)

    def scenario(self, *, full=False, source_drift_at=None, tool_drift_at=None,
                 dependency_drift=False, helper_drift=False, command_result=None,
                 command_raises=None, fail_at_case=1, bad_output=False,
                 artifact_drift=False, reproduce_drift=False, resource_change=None):
        """Mock external execution; keep real selection, output checks and hashes."""
        temporary = tempfile.TemporaryDirectory(prefix="p02-workflow-")
        self.addCleanup(temporary.cleanup)
        base = Path(temporary.name).resolve()
        paths = {"source": ROOT, "tools": base / "tools", "work": base / "work",
                 "output": base / "output", "host_bin": None, "verilator": base / "verilator"}
        paths["tools"].mkdir()
        selected = [case for case in self.cases if case["format"] == "bf16"][:2]
        extra = [] if full else ["--development", "--backend", "simx", "--format", "bf16",
                                "--case", selected[0]["id"], "--case", selected[1]["id"]]
        args = parse_args(*extra)
        checkout = {"dirty": False, "blockers": [], "revision": "a" * 40,
                    "changed_paths": [], "untracked_paths": []}
        source_identity = {"checkout": checkout, "files": [{"path": "observed.cpp", "sha256": "b" * 64}]}
        inventory = {name: {"path": "/fake-tools/" + name, "sha256": "c" * 64}
                     for name in ("g++", "make", "clang", "riscv-gcc", "python3", "verilator")}
        calls = {"source": 0, "tools": 0, "dependency": 0, "case": 0}
        resource = {"available_memory_bytes": 64 * matrix.GIB,
                    "free_disk_bytes": {key: 64 * matrix.GIB for key in ("source", "tools", "work", "output")}}
        if resource_change:
            resource_change(resource)
        real_hash = matrix.hash_artifacts

        def observe_source(_source):
            calls["source"] += 1
            value = copy.deepcopy(source_identity)
            if source_drift_at is not None and calls["source"] >= source_drift_at:
                value["files"][0]["sha256"] = "d" * 64
            return value

        def observe_tools(*_args):
            calls["tools"] += 1
            value = copy.deepcopy(inventory)
            if tool_drift_at is not None and calls["tools"] >= tool_drift_at:
                value["make"]["sha256"] = "e" * 64
            return value

        def observe_artifacts(root, names):
            names = tuple(names)
            if Path(root) == ROOT and names == matrix.DEPENDENCIES:
                calls["dependency"] += 1
                digest = "f" * 64 if dependency_drift and calls["dependency"] >= 2 else "0" * 64
                return [{"path": name, "sha256": digest, "size_bytes": 1} for name in names]
            observed = real_hash(root, names)
            if helper_drift and Path(root) == ROOT and names == tuple(item["path"] for item in matrix.LOADED_HELPERS):
                observed[0]["sha256"] = "1" * 64
            return observed

        def run_command(argv, cwd, env, log_path, **_budget):
            name = log_path.stem
            cwd = Path(cwd)
            result = {"outcome": "pass", "exit_code": 0, "process_started": True,
                      "cleanup_complete": True, "reason": None}
            if command_raises is not None and name.startswith("version-"):
                raise command_raises
            log_path.write_text("mock external command\n")
            if name.endswith("-configure"):
                for relative, body in (("sw/VX_config.h", "cpp fixture header\n"),
                                       ("hw/VX_config.vh", "verilog fixture header\n")):
                    path = cwd / relative
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(body)
                (cwd / APP).mkdir(parents=True)
            elif name.endswith("-header"):
                log_path.write_text(STAMP_SAMPLES["header"])
            elif name.endswith("-header-reproduce"):
                destination = Path(next(value.removeprefix("--output=") for value in argv if value.startswith("--output=")))
                body = "cpp fixture header\n" if destination.suffix == ".h" else "verilog fixture header\n"
                destination.write_text(body + ("changed\n" if reproduce_drift else ""))
            elif name.endswith("-application-build"):
                build = cwd.parents[2]
                driver, fmt = name.split("-", 2)[:2]
                (build / "binding.bin").write_bytes(b"unchanged executable fixture")
                for relative, kind in (("sw/runtime/" + driver + "_rt_config.stamp", driver + "_rt"),
                                       ("sw/runtime/" + driver + "_config.stamp", driver + "_backend"),
                                       (APP + "/config.stamp", "application")):
                    path = build / relative
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(sample(kind, source=ROOT, build=build, tools=paths["tools"], fmt=fmt))
            elif any(value.startswith("OPTS=-f ") for value in argv):
                calls["case"] += 1
                options = next(value for value in argv if value.startswith("OPTS=-f ")).split()
                case = next(case for case in self.cases if case["id"] == options[1])
                log_path.write_text(output_text(case, args.iterations))
                if calls["case"] == fail_at_case:
                    if bad_output:
                        malformed = "P02_RESULT " + "[" * 10000 + "0" + "]" * 10000 + "\nPASSED!\n"
                        log_path.write_text(malformed if bad_output == "nested" else output_text(case, 1))
                    if artifact_drift:
                        (cwd.parents[2] / "binding.bin").write_bytes(b"unexpected rebuild")
                    if command_result is not None:
                        result = copy.deepcopy(command_result)
            return result

        with ExitStack() as stack:
            for name, replacement in (("_resources", mock.Mock(return_value=resource)),
                                      ("source_snapshot", observe_source), ("tool_inventory", observe_tools),
                                      ("hash_artifacts", observe_artifacts), ("run_bounded", run_command),
                                      ("_generated_identity", mock.Mock(return_value=[])),
                                      ("_build_artifacts", mock.Mock(return_value=("binding.bin",)))):
                stack.enter_context(mock.patch.object(matrix, name, replacement))
            report = matrix.execute_run(args, paths)
        saved = json.loads((paths["output"] / "report.json").read_text())
        self.assertEqual(saved, report)
        self.assertEqual(report["state"], "finished")
        for field in ("acceptance_claimed", "qualifies_P02_A02", "qualifies_P02_A03", "phase_complete"):
            self.assertIs(report[field], False)
        return report, calls

    def test_full_passing_workflow_never_claims_acceptance(self):
        report, calls = self.scenario(full=True)
        self.assertEqual(report["outcome"], "pass", report["reason"])
        self.assertTrue(report["full_matrix_requested"])
        self.assertEqual(report["selected_case_count"], 88)
        self.assertEqual(report["expected_case_executions"], 176)
        self.assertEqual(report["completed_case_executions"], 176)
        self.assertEqual(calls["case"], 176)
        self.assertEqual(sum(len(case["observations"]) for variant in report["variants"]
                             for case in variant["cases"]), 352)
        self.assertEqual({variant["outcome"] for variant in report["variants"]}, {"pass"})

    def test_development_pass_has_explicitly_partial_scope(self):
        report, calls = self.scenario()
        self.assertEqual(report["outcome"], "pass", report["reason"])
        self.assertFalse(report["full_matrix_requested"])
        self.assertTrue(report["development"])
        self.assertEqual((report["completed_case_executions"], calls["case"]), (2, 2))

    def test_failing_or_incomplete_command_results_stop_the_matrix(self):
        valid = {"outcome": "pass", "exit_code": 0, "process_started": True,
                 "cleanup_complete": True, "reason": None}
        candidates = [dict(valid, outcome="fail"), dict(valid, exit_code=7),
                      dict(valid, process_started=False), dict(valid, cleanup_complete=False)]
        for key in ("exit_code", "process_started", "cleanup_complete"):
            candidate = dict(valid)
            del candidate[key]
            candidates.append(candidate)
        for candidate in candidates:
            with self.subTest(result=candidate):
                report, calls = self.scenario(command_result=candidate)
                self.assertEqual(report["outcome"], "fail")
                self.assertEqual(calls["case"], 1)
                self.assertEqual(report["variants"][0]["outcome"], "fail")
                self.assertEqual(report["variants"][0]["cases"][0]["outcome"], "fail")
                self.assertNotIn("completed_case_executions", report)

    def test_failed_second_case_preserves_first_success_and_does_not_complete(self):
        report, calls = self.scenario(fail_at_case=2, command_result={
            "outcome": "fail", "exit_code": 9, "process_started": True,
            "cleanup_complete": True, "reason": "injected failure"})
        self.assertEqual(report["outcome"], "fail")
        self.assertEqual(calls["case"], 2)
        self.assertEqual([case["outcome"] for case in report["variants"][0]["cases"]], ["pass", "fail"])

    def test_successful_exit_with_incomplete_output_still_fails(self):
        report, calls = self.scenario(bad_output=True)
        self.assertEqual(report["outcome"], "fail")
        self.assertIn("wrong number", report["reason"])
        self.assertEqual(calls["case"], 1)

    def test_deeply_nested_output_finishes_with_a_failed_checkpoint(self):
        report, calls = self.scenario(bad_output="nested")
        self.assertEqual(report["outcome"], "fail")
        self.assertEqual(calls["case"], 1)
        self.assertEqual(report["variants"][0]["cases"][0]["outcome"], "fail")

    def test_changed_loaded_helpers_block_before_any_command(self):
        report, calls = self.scenario(helper_drift=True)
        self.assertEqual(report["outcome"], "blocked")
        self.assertIn("changed after import", report["reason"])
        self.assertEqual(report["commands"], [])
        self.assertEqual(calls["case"], 0)

    def test_source_drift_before_variant_and_at_final_check_never_passes(self):
        for when in (2, 5):
            with self.subTest(observation=when):
                report, calls = self.scenario(source_drift_at=when)
                self.assertEqual(report["outcome"], "fail")
                self.assertIn("source changed", report["reason"])
                self.assertFalse(report["source_stable"])
                self.assertEqual(calls["case"], 0 if when == 2 else 2)

    def test_tool_drift_before_variant_and_at_final_check_never_passes(self):
        for when in (2, 5):
            with self.subTest(observation=when):
                report, calls = self.scenario(tool_drift_at=when)
                self.assertEqual(report["outcome"], "fail")
                self.assertIn("changed during execution", report["reason"])
                self.assertEqual(calls["case"], 0 if when == 2 else 2)

    def test_dependency_or_build_artifact_drift_never_passes(self):
        for options, reason in (({"dependency_drift": True}, "dependencies changed"),
                                ({"artifact_drift": True}, "build artifacts changed")):
            with self.subTest(options=options):
                report, _ = self.scenario(**options)
                self.assertEqual(report["outcome"], "fail")
                self.assertIn(reason, report["reason"])

    def test_nonreproducing_configuration_header_fails_before_build(self):
        report, calls = self.scenario(reproduce_drift=True)
        self.assertEqual(report["outcome"], "fail")
        self.assertIn("header did not reproduce", report["reason"])
        self.assertEqual(calls["case"], 0)

    def test_launch_error_and_interrupt_leave_finished_failure_checkpoints(self):
        for error in (OSError("injected launch failure"), KeyboardInterrupt()):
            with self.subTest(error=type(error).__name__):
                report, calls = self.scenario(command_raises=error)
                self.assertEqual(report["outcome"], "fail")
                self.assertEqual(calls["case"], 0)
                self.assertEqual(len(report["commands"]), 1)

    def test_insufficient_memory_or_disk_blocks_without_commands(self):
        for change in (lambda resource: resource.__setitem__("available_memory_bytes", None),
                       lambda resource: resource.__setitem__("available_memory_bytes", 6 * matrix.GIB - 1),
                       lambda resource: resource["free_disk_bytes"].__setitem__("output", 15 * matrix.GIB - 1)):
            report, calls = self.scenario(resource_change=change)
            self.assertEqual(report["outcome"], "blocked")
            self.assertEqual(report["commands"], [])
            self.assertEqual(calls["case"], 0)

    def test_formal_source_rejects_dirty_and_development_does_not_ignore_other_blockers(self):
        dirty_reason = "source contains tracked changes or nonignored untracked inputs"
        snapshot = {"checkout": {"dirty": True, "blockers": [dirty_reason]}}
        with self.assertRaises(ValueError):
            matrix._source_ok(snapshot, False)
        matrix._source_ok(snapshot, True)
        snapshot["checkout"]["blockers"].append("submodule identity missing")
        with self.assertRaisesRegex(ValueError, "submodule"):
            matrix._source_ok(snapshot, True)

    def test_main_prints_failure_and_no_acceptance_for_path_rejection(self):
        output = io.StringIO()
        with mock.patch.object(matrix, "resolve_paths", side_effect=ValueError("unsafe fixture path")), redirect_stdout(output):
            result = matrix.main(["run", "--tools-dir", str(TOOLS), "--work-dir", "/work", "--output", "/output"])
        self.assertEqual(result, 1)
        self.assertEqual(json.loads(output.getvalue()), {
            "outcome": "blocked", "reason": "unsafe fixture path", "acceptance_claimed": False})


class GeneratedInputTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="p02-generated-")
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()
        self.build, self.tools = self.base / "build", self.base / "tools"
        self.build.mkdir()
        self.tools.mkdir()
        self.config = ("XLEN ?= 64\nPROFILE ?= p02-tfr\nVORTEX_HOME ?= " + str(ROOT)
                       + "\nTOOLDIR ?= " + str(self.tools) + "\nOSVERSION ?= ubuntu/focal\n")
        self.stamp = ("XLEN=64 PROFILE=p02-tfr SOURCE_DIR=" + str(ROOT)
                      + " BUILDDIR=" + str(self.build) + " TOOLDIR=" + str(self.tools) + "\n")
        for relative in matrix.GENERATED + matrix.COPIED:
            path = self.build / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes((ROOT / relative).read_bytes() if relative in matrix.COPIED else b"generated fixture\n")
        (self.build / "config.mk").write_text(self.config)
        (self.build / ".config.stamp").write_text(self.stamp)
        (self.build / "sim/rtlsim/verilator.vlt").write_text(
            (ROOT / "sim/rtlsim/verilator.vlt.in").read_text().replace("@VORTEX_HOME@", str(ROOT)))

    def test_copied_inputs_are_bound_to_source_and_all_artifacts_are_hashed(self):
        observed = matrix._generated_identity(self.build, ROOT, self.tools)
        self.assertEqual({item["path"] for item in observed}, set(matrix.GENERATED + matrix.COPIED))
        for relative in matrix.COPIED:
            path = self.build / relative
            original = path.read_bytes()
            path.write_bytes(original + b"\n# stale generated copy\n")
            with self.subTest(relative=relative), self.assertRaisesRegex(ValueError, "differs from source"):
                matrix._generated_identity(self.build, ROOT, self.tools)
            path.write_bytes(original)

    def test_wrong_or_duplicate_config_selection_is_rejected(self):
        for name, value in (("XLEN", "32"), ("PROFILE", "other"), ("VORTEX_HOME", "/wrong/source"),
                            ("TOOLDIR", "/wrong/tools"), ("OSVERSION", "other/bundle")):
            lines = [name + " ?= " + value if line.startswith(name + " ") else line
                     for line in self.config.splitlines()]
            (self.build / "config.mk").write_text("\n".join(lines) + "\n")
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, "incorrect " + name):
                matrix._generated_identity(self.build, ROOT, self.tools)
        (self.build / "config.mk").write_text(self.config + "XLEN ?= 64\n")
        with self.assertRaises(ValueError):
            matrix._generated_identity(self.build, ROOT, self.tools)

    def test_configure_stamp_and_verilator_config_cannot_be_stale(self):
        for stamp in (self.stamp.replace("XLEN=64", "XLEN=32"), self.stamp + "PROFILE=p02-tfr\n",
                      self.stamp.replace(str(self.build), "/other/build")):
            (self.build / ".config.stamp").write_text(stamp)
            with self.subTest(stamp=stamp), self.assertRaises(ValueError):
                matrix._generated_identity(self.build, ROOT, self.tools)
        (self.build / ".config.stamp").write_text(self.stamp)
        (self.build / "sim/rtlsim/verilator.vlt").write_text("stale configuration\n")
        with self.assertRaisesRegex(ValueError, "Verilator configuration differs"):
            matrix._generated_identity(self.build, ROOT, self.tools)

    def test_tool_identity_binds_resolved_bytes_as_well_as_invoked_path(self):
        tool, link = self.tools / "actual", self.tools / "alias"
        tool.write_bytes(b"first identity")
        link.symlink_to(tool)
        before = matrix._file_identity(link)
        self.assertEqual(before["path"], str(link))
        self.assertEqual(before["resolved_path"], str(tool))
        tool.write_bytes(b"second identity")
        self.assertNotEqual(matrix._file_identity(link)["sha256"], before["sha256"])


# Retained generated samples are appended below by the proposal preparation step.

STAMP_SAMPLE_ORIGINS = {'simx_rt': {'source': 'build/sw/runtime/simx_rt_config.stamp',
             'sha256': '9eee428c65265cf4c51e1f1062cd814e592cdd9e214c7b832ba4b85c0be0e032'},
 'simx_backend': {'source': 'w03-simx-selector-evidence/bf16-simx_config.stamp',
                  'sha256': '64d48b9530ba30e70f000e798be10ca19fa116b7798900af42ea8f08634e677c'},
 'rtlsim_rt': {'source': 'build/sw/runtime/rtlsim_rt_config.stamp',
               'sha256': '58210a6b6394b92f26af619f9b75167c871319a12e095743a93369f5fefce771'},
 'rtlsim_backend': {'source': 'build/sw/runtime/rtlsim_config.stamp',
                    'sha256': '971a73e7aac91913b205d2aba9840212cb6c6ffe729d6dc575b785e02412162e'},
 'application': {'source': 'build/tests/regression/sgemm_tcu/config.stamp',
                 'sha256': '85eb73f31e0c6128fadf4065aa6d0da11d658fd1bbb11ecfa7448f88cd42c414'},
 'header': {'source': 'logs/header-rv64.log',
            'sha256': '77688cde5e748b535c20c6955a51ef3b1cd2998eeb3398cec08957b9d4a0144a'},
 'simx_backend_missing_selectors': {'source': 'build/sw/runtime/simx_config.stamp',
                                    'sha256': 'fd8499204c6b265f1145ad4998ff612cc4064080190d7b29273be0bcc3bf844d'}}

STAMP_SAMPLES = {'simx_rt': '-DVX_CFG_XLEN=64 -DVX_CFG_XLEN_64 -DVX_CFG_FLEN=64 -DVX_CFG_FLEN_64 '
            '-DVX_CFG_FPU_TYPE=STD -DVX_CFG_FPU_TYPE_STD -DVX_CFG_TCU_TYPE=TFR '
            '-DVX_CFG_TCU_TYPE_TFR -DVX_CFG_PLATFORM_MEMORY_TYPE=HBM2 '
            '-DVX_CFG_PLATFORM_MEMORY_TYPE_HBM2 -DVX_CFG_NUM_CLUSTERS=1 -DVX_CFG_NUM_CORES=1 '
            '-DVX_CFG_SOCKET_SIZE=1 -DVX_CFG_RESET_DELAY=8 -DVX_CFG_ICACHE_ENABLE '
            '-DVX_CFG_ICACHE_ENABLED=1 -DVX_CFG_DCACHE_ENABLE -DVX_CFG_DCACHE_ENABLED=1 '
            '-DVX_CFG_LMEM_ENABLE -DVX_CFG_LMEM_ENABLED=1 -DVX_CFG_L2_ENABLED=0 '
            '-DVX_CFG_L3_ENABLED=0 -DVX_CFG_VM_ENABLED=0 -DVX_CFG_EXT_D_ENABLE '
            '-DVX_CFG_EXT_D_ENABLED=1 -DVX_CFG_FLEN=64 -DVX_CFG_EXT_M_ENABLE '
            '-DVX_CFG_EXT_M_ENABLED=1 -DVX_CFG_EXT_F_ENABLE -DVX_CFG_EXT_F_ENABLED=1 '
            '-DVX_CFG_EXT_C_ENABLED=0 -DVX_CFG_EXT_A_ENABLED=0 -DVX_CFG_EXT_ZACAS_ENABLED=0 '
            '-DVX_CFG_EXT_ZICOND_ENABLE -DVX_CFG_EXT_ZICOND_ENABLED=1 '
            '-DVX_CFG_EXT_ZFHMIN_ENABLED=0 -DVX_CFG_EXT_TCU_ENABLE -DVX_CFG_EXT_TCU_ENABLED=1 '
            '-DVX_CFG_EXT_DMA_ENABLED=0 -DVX_CFG_EXT_DXA_ENABLED=0 -DVX_CFG_EXT_TEX_ENABLED=0 '
            '-DVX_CFG_EXT_RASTER_ENABLED=0 -DVX_CFG_EXT_OM_ENABLED=0 -DVX_CFG_EXT_RTU_ENABLED=0 '
            '-DVX_CFG_EXT_MUFU_ENABLED=0 -DVX_CFG_EXT_LDST_WIDE_ENABLED=0 '
            '-DVX_CFG_EXT_LDST_MATRIX_ENABLED=0 -DVX_CFG_VLEN=256 -DVX_CFG_NUM_WARPS=4 '
            '-DVX_CFG_NUM_THREADS=4 -DVX_CFG_NUM_BARRIERS=8 -DVX_CFG_MAX_BAR_EVENTS=32 '
            '-DVX_CFG_IBUF_SIZE=4 -DVX_CFG_DISPATCH_QUEUE_SIZE=4 -DVX_CFG_ISSUE_WIDTH=1 '
            '-DVX_CFG_FETCH_WIDTH=1 -DVX_CFG_SIMD_WIDTH=4 -DVX_CFG_NUM_OPCS=1 '
            '-DVX_CFG_NUM_GPR_BANKS=4 -DVX_CFG_NUM_VGPR_BANKS=2 -DVX_CFG_MEM_BLOCK_SIZE=64 '
            '-DVX_CFG_MEM_ADDR_WIDTH=48 -DVX_CFG_L1_LINE_SIZE=64 -DVX_CFG_L2_LINE_SIZE=64 '
            '-DVX_CFG_L2_SECTOR_SIZE=64 -DVX_CFG_L3_LINE_SIZE=64 -DVX_CFG_L3_SECTOR_SIZE=64 '
            '-DVX_CFG_PLATFORM_MEMORY_NUM_BANKS=2 -DVX_CFG_PLATFORM_MEMORY_ADDR_WIDTH=48 '
            '-DVX_CFG_PLATFORM_MEMORY_DATA_SIZE=64 -DVX_CFG_PLATFORM_MEMORY_INTERLEAVE=1 '
            '-DVX_CFG_PLATFORM_MEMORY_PEAK_BW=460000 -DVX_CFG_PLATFORM_CLOCK_RATE=400 '
            '-DVX_CFG_PLATFORM_MEMORY_TYPE=HBM2 -DVX_CFG_PLATFORM_MEMORY_DATA_RATE=800 '
            '-DVX_CFG_PLATFORM_MEMORY_LATENCY=0 -DVX_CFG_PLATFORM_MEMORY_QUEUE_SIZE=0 '
            '-DVX_CFG_NUM_ALU_LANES=4 -DVX_CFG_NUM_ALU_BLOCKS=1 -DVX_CFG_NUM_SFU_LANES=4 '
            '-DVX_CFG_NUM_SFU_BLOCKS=1 -DVX_CFG_NUM_LSU_LANES=4 -DVX_CFG_NUM_LSU_BLOCKS=1 '
            '-DVX_CFG_LSU_STACK_INTERLEAVE_ENABLE -DVX_CFG_LSU_STACK_INTERLEAVE_ENABLED=1 '
            '-DVX_CFG_LSU_LINE_SIZE=32 -DVX_CFG_LSU_QUEUE_IN_SIZE=4 -DVX_CFG_LSU_PENDING_SIZE=8 '
            '-DVX_CFG_LSU_PENDING_LIMIT=32 -DVX_CFG_FPU_TYPE=STD -DVX_CFG_NUM_FPU_LANES=4 '
            '-DVX_CFG_NUM_FPU_BLOCKS=1 -DVX_CFG_FPU_QUEUE_SIZE=2 -DVX_CFG_FPU_USE_DSP=0 '
            '-DVX_CFG_FMA_LATENCY=12 -DVX_CFG_FDIV_LATENCY=32 -DVX_CFG_FSQRT_LATENCY=32 '
            '-DVX_CFG_FNCP_LATENCY=2 -DVX_CFG_FCVT_LATENCY=5 -DVX_CFG_FMA_PE_RATIO=1 '
            '-DVX_CFG_FMA64_PE_RATIO=1 -DVX_CFG_FDIV_PE_RATIO=1 -DVX_CFG_FSQRT_PE_RATIO=1 '
            '-DVX_CFG_FCVT_PE_RATIO=1 -DVX_CFG_FNCP_PE_RATIO=1 -DVX_CFG_NUM_MUFU_LANES=1 '
            '-DVX_CFG_AMO_RS_SIZE=4 -DVX_CFG_NUM_VPU_LANES=4 -DVX_CFG_NUM_VPU_BLOCKS=1 '
            '-DVX_CFG_TLB_SIZE=32 -DVX_CFG_DTLB_SIZE=16 -DVX_CFG_ITLB_SIZE=8 '
            '-DVX_CFG_L1_TLB_MSHR_SIZE=4 -DVX_CFG_UTLB_SIZE=8 -DVX_CFG_CTLB_SIZE=8 '
            '-DVX_CFG_L2_TLB_SIZE=512 -DVX_CFG_L2_TLB_NUM_WAYS=4 -DVX_CFG_L2_TLB_MEGA_SIZE=8 '
            '-DVX_CFG_L2_TLB_MSHR_SIZE=8 -DVX_CFG_L2_TLB_LATENCY=4 -DVX_CFG_PTW_NUM_WALKERS=2 '
            '-DVX_CFG_PTW_WALK_CACHE_SIZE=16 -DVX_CFG_VM_PINNED_REGION_SIZE=0x10000000 '
            '-DVX_CFG_CP_LLC_CLIENT=1 -DVX_CFG_CP_ON_LLC=0 -DVX_CFG_ICACHE_SIZE=16384 '
            '-DVX_CFG_ICACHE_NUM_WAYS=4 -DVX_CFG_ICACHE_REPL_POLICY=1 -DVX_CFG_ICACHE_MSHR_SIZE=16 '
            '-DVX_CFG_ICACHE_MRSQ_SIZE=0 -DVX_CFG_ICACHE_MREQ_SIZE=0 -DVX_CFG_ICACHE_CRSQ_SIZE=0 '
            '-DVX_CFG_ICACHE_MEM_PORTS=1 -DVX_CFG_ICACHE_NUM_BANKS=1 -DVX_CFG_ICACHE_READ_MERGE=1 '
            '-DVX_CFG_ICACHE_LATENCY=2 -DVX_CFG_DCACHE_SIZE=16384 -DVX_CFG_DCACHE_NUM_WAYS=4 '
            '-DVX_CFG_DCACHE_WORD_SIZE=16 -DVX_CFG_DCACHE_WRITEBACK=1 -DVX_CFG_DCACHE_DIRTYBYTES=1 '
            '-DVX_CFG_DCACHE_LAZY_FETCH=1 -DVX_CFG_DCACHE_REPL_POLICY=1 '
            '-DVX_CFG_DCACHE_MSHR_SIZE=16 -DVX_CFG_DCACHE_LINE_SIZE=64 '
            '-DVX_CFG_DCACHE_SECTOR_SIZE=64 -DVX_CFG_DCACHE_LATENCY=2 -DVX_CFG_L1_LINK_LATENCY=0 '
            '-DVX_CFG_DCACHE_MRSQ_SIZE=4 -DVX_CFG_DCACHE_MREQ_SIZE=0 -DVX_CFG_DCACHE_CRSQ_SIZE=0 '
            '-DVX_CFG_NUM_ICACHES=1 -DVX_CFG_NUM_DCACHES=1 -DVX_CFG_DCACHE_NUM_BANKS=1 '
            '-DVX_CFG_DCACHE_BANK_HASH=0 -DVX_CFG_DCACHE_SET_HASH=1 -DVX_CFG_DCACHE_READ_MERGE=1 '
            '-DVX_CFG_L1_MEM_PORTS=1 -DVX_CFG_L2_SIZE=1048576 -DVX_CFG_L2_NUM_WAYS=8 '
            '-DVX_CFG_L2_WRITEBACK=0 -DVX_CFG_L2_DIRTYBYTES=0 -DVX_CFG_L2_LAZY_FETCH=0 '
            '-DVX_CFG_L2_REPL_POLICY=1 -DVX_CFG_L2_MSHR_SIZE=16 -DVX_CFG_L2_LATENCY=4 '
            '-DVX_CFG_L2_LINK_LATENCY=0 -DVX_CFG_L2_MRSQ_SIZE=4 -DVX_CFG_L2_MREQ_SIZE=0 '
            '-DVX_CFG_L2_CRSQ_SIZE=0 -DVX_CFG_L2_NUM_BANKS=1 -DVX_CFG_L2_BANK_HASH=1 '
            '-DVX_CFG_L2_MEM_PORTS=0 -DVX_CFG_L3_SIZE=2097152 -DVX_CFG_L3_NUM_WAYS=8 '
            '-DVX_CFG_L3_WRITEBACK=0 -DVX_CFG_L3_DIRTYBYTES=0 -DVX_CFG_L3_LAZY_FETCH=0 '
            '-DVX_CFG_L3_REPL_POLICY=1 -DVX_CFG_L3_MSHR_SIZE=16 -DVX_CFG_L3_LATENCY=4 '
            '-DVX_CFG_L3_MRSQ_SIZE=4 -DVX_CFG_L3_MREQ_SIZE=0 -DVX_CFG_L3_CRSQ_SIZE=0 '
            '-DVX_CFG_L3_NUM_BANKS=1 -DVX_CFG_L3_MEM_PORTS=0 -DVX_CFG_LMEM_NUM_BANKS=4 '
            '-DVX_CFG_LMEM_LOG_SIZE=14 -DVX_CFG_LMEM_SIZE=16384 -DVX_CFG_TCU_TYPE=TFR '
            '-DVX_CFG_NUM_TCU_LANES=4 -DVX_CFG_NUM_TCU_BLOCKS=1 -DVX_CFG_TCU_USE_DSP=0 '
            '-DVX_CFG_TCU_LATENCY=4 -DVX_CFG_TCU_PE_RATIO=1 -DVX_CFG_TCU_TF32_ENABLED=0 '
            '-DVX_CFG_TCU_FP16_ENABLE -DVX_CFG_TCU_FP16_ENABLED=1 -DVX_CFG_TCU_FP8_ENABLED=0 '
            '-DVX_CFG_TCU_FP4_ENABLED=0 -DVX_CFG_TCU_INT8_ENABLED=0 -DVX_CFG_TCU_INT4_ENABLED=0 '
            '-DVX_CFG_TCU_MX_ENABLED=0 -DVX_CFG_TCU_MXFP4_ENABLED=0 -DVX_CFG_TCU_NVFP4_ENABLED=0 '
            '-DVX_CFG_TCU_SPARSE_ENABLED=0 -DVX_CFG_TCU_DSM_ENABLED=0 -DVX_CFG_TCU_WGMMA_ENABLED=0 '
            '-DVX_CFG_NUM_DXA_CORES=1 -DVX_CFG_DXA_MEM_PORTS=1 -DVX_CFG_DXA_QUEUE_SIZE=16 '
            '-DVX_CFG_DXA_MAX_INFLIGHT=8 -DVX_CFG_NUM_RTU_CORES=1 -DVX_CFG_RTU_BVH_WIDTH=4 '
            '-DVX_CFG_RTU_TLAS_ENABLED=0 -DVX_CFG_RTU_STACK_DEPTH=16 -DVX_CFG_RTU_RECIP_DSP_SEED=0 '
            '-DVX_CFG_RTU_USE_DSP=0 -DVX_CFG_RTU_FDIV_LATENCY=17 -DVX_CFG_RTU_NUM_SLOTS=1 '
            '-DVX_CFG_RTU_NUM_CTX=4 -DVX_CFG_RTU_MERGE_DEPTH=0 -DVX_CFG_NUM_RTU_BLOCKS=2 '
            '-DVX_CFG_NUM_TEX_CORES=1 -DVX_CFG_TEX_REQ_QUEUE_SIZE=8 -DVX_CFG_TEX_MEM_QUEUE_SIZE=8 '
            '-DVX_CFG_NUM_RASTER_CORES=1 -DVX_CFG_RASTER_NUM_SLICES=1 '
            '-DVX_CFG_RASTER_TILE_LOG_SIZE=5 -DVX_CFG_RASTER_BIN_LOG_SIZE=7 '
            '-DVX_CFG_RASTER_BLOCK_LOG_SIZE=2 -DVX_CFG_RASTER_MEM_FIFO_DEPTH=8 '
            '-DVX_CFG_RASTER_QUAD_FIFO_DEPTH=32 -DVX_CFG_RASTER_MEM_QUEUE_SIZE=4 '
            '-DVX_CFG_RASTER_EARLYZ_ENABLED=0 -DVX_CFG_NUM_OM_CORES=1 -DVX_CFG_OM_MEM_QUEUE_SIZE=4 '
            '-DVX_CFG_TCACHE_SIZE=8192 -DVX_CFG_TCACHE_NUM_BANKS=1 -DVX_CFG_TCACHE_NUM_WAYS=2 '
            '-DVX_CFG_TCACHE_CRSQ_SIZE=0 -DVX_CFG_TCACHE_MSHR_SIZE=16 -DVX_CFG_TCACHE_MRSQ_SIZE=0 '
            '-DVX_CFG_TCACHE_MREQ_SIZE=0 -DVX_CFG_NUM_TCACHES=1 -DVX_CFG_RCACHE_SIZE=4096 '
            '-DVX_CFG_RCACHE_NUM_BANKS=1 -DVX_CFG_RCACHE_NUM_WAYS=2 -DVX_CFG_RCACHE_CRSQ_SIZE=0 '
            '-DVX_CFG_RCACHE_MSHR_SIZE=16 -DVX_CFG_RCACHE_MRSQ_SIZE=0 -DVX_CFG_RCACHE_MREQ_SIZE=0 '
            '-DVX_CFG_NUM_RCACHES=1 -DVX_CFG_RTCACHE_SIZE=8192 -DVX_CFG_RTCACHE_NUM_BANKS=1 '
            '-DVX_CFG_RTCACHE_NUM_WAYS=2 -DVX_CFG_RTCACHE_CRSQ_SIZE=2 '
            '-DVX_CFG_RTCACHE_MSHR_SIZE=16 -DVX_CFG_RTCACHE_MREQ_SIZE=4 '
            '-DVX_CFG_RTCACHE_MRSQ_SIZE=0 -DVX_CFG_NUM_RTCACHES=1 -DVX_CFG_OCACHE_SIZE=16384 '
            '-DVX_CFG_OCACHE_NUM_BANKS=1 -DVX_CFG_OCACHE_NUM_WAYS=2 -DVX_CFG_OCACHE_CRSQ_SIZE=0 '
            '-DVX_CFG_OCACHE_MSHR_SIZE=16 -DVX_CFG_OCACHE_MRSQ_SIZE=0 -DVX_CFG_OCACHE_MREQ_SIZE=0 '
            '-DVX_CFG_NUM_OCACHES=1 -DVX_CFG_MISA_STD=9441576 -DVX_CFG_MISA_EXT=563 '
            '-DVX_DBG_STALL_TIMEOUT=100000 -DVX_DBG_DEBUG_LEVEL=3 -std=c++17 -Wall -Wextra '
            '-Wfatal-errors -Werror -fPIC -I@SOURCE@/sw/runtime/include -I../common -I@BUILD@/sw '
            '-I@BUILD@/hw -I@SOURCE@/sim/simx -I@SOURCE@/sim/common -I@SOURCE@/sw/common '
            '-I@SOURCE@/sw/runtime/common -DVX_CFG_XLEN=64 -DVX_CFG_XLEN_64 -DVX_PROFILE=p02-tfr '
            '-DVX_CFG_EXT_LDST_MATRIX_DISABLE -DVX_CFG_EXT_TCU_ENABLE -DVX_CFG_FPU_TYPE=STD '
            '-DVX_CFG_ISSUE_WIDTH=1 -DVX_CFG_LMEM_ENABLE -DVX_CFG_NUM_ALU_BLOCKS=1 '
            '-DVX_CFG_NUM_CLUSTERS=1 -DVX_CFG_NUM_CORES=1 -DVX_CFG_NUM_FPU_BLOCKS=1 '
            '-DVX_CFG_NUM_LSU_BLOCKS=1 -DVX_CFG_NUM_THREADS=4 -DVX_CFG_NUM_WARPS=4 '
            '-DVX_CFG_TCU_DSM_DISABLE -DVX_CFG_TCU_FP16_ENABLE -DVX_CFG_TCU_FP4_DISABLE '
            '-DVX_CFG_TCU_FP8_DISABLE -DVX_CFG_TCU_INT4_DISABLE -DVX_CFG_TCU_INT8_DISABLE '
            '-DVX_CFG_TCU_LATENCY=4 -DVX_CFG_TCU_MXFP4_DISABLE -DVX_CFG_TCU_MX_DISABLE '
            '-DVX_CFG_TCU_NVFP4_DISABLE -DVX_CFG_TCU_PE_RATIO=1 -DVX_CFG_TCU_SPARSE_DISABLE '
            '-DVX_CFG_TCU_TF32_DISABLE -DVX_CFG_TCU_TYPE=TFR -DVX_CFG_TCU_USE_DSP=0 '
            '-DVX_CFG_TCU_WGMMA_DISABLE -DITYPE=bf16 -DOTYPE=fp32 -DKUNROLL=1 -O2 -DNDEBUG\n',
 'simx_backend': '-std=c++17 -Wall -Wextra -Wfatal-errors -Werror -fPIC -I@SOURCE@/sim/simx '
                 '-I@SOURCE@/sim/simx/dxa -I@SOURCE@/sim/simx/tex -I@SOURCE@/sim/simx/om '
                 '-I@SOURCE@/sim/simx/raster -I@SOURCE@/sim/simx/rtu -I@SOURCE@/sim/simx/kmu '
                 '-I@SOURCE@/sim/simx/mem -I@SOURCE@/sim/simx/dtm -I@SOURCE@/sw/common '
                 '-I@SOURCE@/sim/common -I@BUILD@/sw -I@BUILD@/hw -I@SOURCE@/third_party '
                 '-I@SOURCE@/third_party/softfloat/source/include '
                 '-I@SOURCE@/third_party/ramulator/ext/spdlog/include '
                 '-I@SOURCE@/third_party/ramulator/ext/yaml-cpp/include '
                 '-I@SOURCE@/third_party/ramulator/src -DVX_CFG_XLEN=64 -DVX_CFG_XLEN_64 '
                 '-DVX_PROFILE=p02-tfr -DVX_CFG_EXT_LDST_MATRIX_DISABLE -DVX_CFG_EXT_TCU_ENABLE '
                 '-DVX_CFG_FPU_TYPE=STD -DVX_CFG_ISSUE_WIDTH=1 -DVX_CFG_LMEM_ENABLE '
                 '-DVX_CFG_NUM_ALU_BLOCKS=1 -DVX_CFG_NUM_CLUSTERS=1 -DVX_CFG_NUM_CORES=1 '
                 '-DVX_CFG_NUM_FPU_BLOCKS=1 -DVX_CFG_NUM_LSU_BLOCKS=1 -DVX_CFG_NUM_THREADS=4 '
                 '-DVX_CFG_NUM_WARPS=4 -DVX_CFG_TCU_DSM_DISABLE -DVX_CFG_TCU_FP16_ENABLE '
                 '-DVX_CFG_TCU_FP4_DISABLE -DVX_CFG_TCU_FP8_DISABLE -DVX_CFG_TCU_INT4_DISABLE '
                 '-DVX_CFG_TCU_INT8_DISABLE -DVX_CFG_TCU_LATENCY=4 -DVX_CFG_TCU_MXFP4_DISABLE '
                 '-DVX_CFG_TCU_MX_DISABLE -DVX_CFG_TCU_NVFP4_DISABLE -DVX_CFG_TCU_PE_RATIO=1 '
                 '-DVX_CFG_TCU_SPARSE_DISABLE -DVX_CFG_TCU_TF32_DISABLE -DVX_CFG_TCU_TYPE=TFR '
                 '-DVX_CFG_TCU_USE_DSP=0 -DVX_CFG_TCU_WGMMA_DISABLE -DITYPE=bf16 -DOTYPE=fp32 '
                 '-DKUNROLL=1 -DVX_CFG_FPU_TYPE_STD -DVX_CFG_TCU_TYPE_TFR -I@SOURCE@/sim/simx/tcu '
                 '-O2 -DNDEBUG -MMD -MP -MF @BUILD@/sw/runtime/simx_config.stamp\n',
 'rtlsim_rt': '-DVX_CFG_XLEN=64 -DVX_CFG_XLEN_64 -DVX_CFG_FLEN=64 -DVX_CFG_FLEN_64 '
              '-DVX_CFG_FPU_TYPE=STD -DVX_CFG_FPU_TYPE_STD -DVX_CFG_TCU_TYPE=TFR '
              '-DVX_CFG_TCU_TYPE_TFR -DVX_CFG_PLATFORM_MEMORY_TYPE=HBM2 '
              '-DVX_CFG_PLATFORM_MEMORY_TYPE_HBM2 -DVX_CFG_NUM_CLUSTERS=1 -DVX_CFG_NUM_CORES=1 '
              '-DVX_CFG_SOCKET_SIZE=1 -DVX_CFG_RESET_DELAY=8 -DVX_CFG_ICACHE_ENABLE '
              '-DVX_CFG_ICACHE_ENABLED=1 -DVX_CFG_DCACHE_ENABLE -DVX_CFG_DCACHE_ENABLED=1 '
              '-DVX_CFG_LMEM_ENABLE -DVX_CFG_LMEM_ENABLED=1 -DVX_CFG_L2_ENABLED=0 '
              '-DVX_CFG_L3_ENABLED=0 -DVX_CFG_VM_ENABLED=0 -DVX_CFG_EXT_D_ENABLE '
              '-DVX_CFG_EXT_D_ENABLED=1 -DVX_CFG_FLEN=64 -DVX_CFG_EXT_M_ENABLE '
              '-DVX_CFG_EXT_M_ENABLED=1 -DVX_CFG_EXT_F_ENABLE -DVX_CFG_EXT_F_ENABLED=1 '
              '-DVX_CFG_EXT_C_ENABLED=0 -DVX_CFG_EXT_A_ENABLED=0 -DVX_CFG_EXT_ZACAS_ENABLED=0 '
              '-DVX_CFG_EXT_ZICOND_ENABLE -DVX_CFG_EXT_ZICOND_ENABLED=1 '
              '-DVX_CFG_EXT_ZFHMIN_ENABLED=0 -DVX_CFG_EXT_TCU_ENABLE -DVX_CFG_EXT_TCU_ENABLED=1 '
              '-DVX_CFG_EXT_DMA_ENABLED=0 -DVX_CFG_EXT_DXA_ENABLED=0 -DVX_CFG_EXT_TEX_ENABLED=0 '
              '-DVX_CFG_EXT_RASTER_ENABLED=0 -DVX_CFG_EXT_OM_ENABLED=0 -DVX_CFG_EXT_RTU_ENABLED=0 '
              '-DVX_CFG_EXT_MUFU_ENABLED=0 -DVX_CFG_EXT_LDST_WIDE_ENABLED=0 '
              '-DVX_CFG_EXT_LDST_MATRIX_ENABLED=0 -DVX_CFG_VLEN=256 -DVX_CFG_NUM_WARPS=4 '
              '-DVX_CFG_NUM_THREADS=4 -DVX_CFG_NUM_BARRIERS=8 -DVX_CFG_MAX_BAR_EVENTS=32 '
              '-DVX_CFG_IBUF_SIZE=4 -DVX_CFG_DISPATCH_QUEUE_SIZE=4 -DVX_CFG_ISSUE_WIDTH=1 '
              '-DVX_CFG_FETCH_WIDTH=1 -DVX_CFG_SIMD_WIDTH=4 -DVX_CFG_NUM_OPCS=1 '
              '-DVX_CFG_NUM_GPR_BANKS=4 -DVX_CFG_NUM_VGPR_BANKS=2 -DVX_CFG_MEM_BLOCK_SIZE=64 '
              '-DVX_CFG_MEM_ADDR_WIDTH=48 -DVX_CFG_L1_LINE_SIZE=64 -DVX_CFG_L2_LINE_SIZE=64 '
              '-DVX_CFG_L2_SECTOR_SIZE=64 -DVX_CFG_L3_LINE_SIZE=64 -DVX_CFG_L3_SECTOR_SIZE=64 '
              '-DVX_CFG_PLATFORM_MEMORY_NUM_BANKS=2 -DVX_CFG_PLATFORM_MEMORY_ADDR_WIDTH=48 '
              '-DVX_CFG_PLATFORM_MEMORY_DATA_SIZE=64 -DVX_CFG_PLATFORM_MEMORY_INTERLEAVE=1 '
              '-DVX_CFG_PLATFORM_MEMORY_PEAK_BW=460000 -DVX_CFG_PLATFORM_CLOCK_RATE=400 '
              '-DVX_CFG_PLATFORM_MEMORY_TYPE=HBM2 -DVX_CFG_PLATFORM_MEMORY_DATA_RATE=800 '
              '-DVX_CFG_PLATFORM_MEMORY_LATENCY=0 -DVX_CFG_PLATFORM_MEMORY_QUEUE_SIZE=0 '
              '-DVX_CFG_NUM_ALU_LANES=4 -DVX_CFG_NUM_ALU_BLOCKS=1 -DVX_CFG_NUM_SFU_LANES=4 '
              '-DVX_CFG_NUM_SFU_BLOCKS=1 -DVX_CFG_NUM_LSU_LANES=4 -DVX_CFG_NUM_LSU_BLOCKS=1 '
              '-DVX_CFG_LSU_STACK_INTERLEAVE_ENABLE -DVX_CFG_LSU_STACK_INTERLEAVE_ENABLED=1 '
              '-DVX_CFG_LSU_LINE_SIZE=32 -DVX_CFG_LSU_QUEUE_IN_SIZE=4 -DVX_CFG_LSU_PENDING_SIZE=8 '
              '-DVX_CFG_LSU_PENDING_LIMIT=32 -DVX_CFG_FPU_TYPE=STD -DVX_CFG_NUM_FPU_LANES=4 '
              '-DVX_CFG_NUM_FPU_BLOCKS=1 -DVX_CFG_FPU_QUEUE_SIZE=2 -DVX_CFG_FPU_USE_DSP=0 '
              '-DVX_CFG_FMA_LATENCY=12 -DVX_CFG_FDIV_LATENCY=32 -DVX_CFG_FSQRT_LATENCY=32 '
              '-DVX_CFG_FNCP_LATENCY=2 -DVX_CFG_FCVT_LATENCY=5 -DVX_CFG_FMA_PE_RATIO=1 '
              '-DVX_CFG_FMA64_PE_RATIO=1 -DVX_CFG_FDIV_PE_RATIO=1 -DVX_CFG_FSQRT_PE_RATIO=1 '
              '-DVX_CFG_FCVT_PE_RATIO=1 -DVX_CFG_FNCP_PE_RATIO=1 -DVX_CFG_NUM_MUFU_LANES=1 '
              '-DVX_CFG_AMO_RS_SIZE=4 -DVX_CFG_NUM_VPU_LANES=4 -DVX_CFG_NUM_VPU_BLOCKS=1 '
              '-DVX_CFG_TLB_SIZE=32 -DVX_CFG_DTLB_SIZE=16 -DVX_CFG_ITLB_SIZE=8 '
              '-DVX_CFG_L1_TLB_MSHR_SIZE=4 -DVX_CFG_UTLB_SIZE=8 -DVX_CFG_CTLB_SIZE=8 '
              '-DVX_CFG_L2_TLB_SIZE=512 -DVX_CFG_L2_TLB_NUM_WAYS=4 -DVX_CFG_L2_TLB_MEGA_SIZE=8 '
              '-DVX_CFG_L2_TLB_MSHR_SIZE=8 -DVX_CFG_L2_TLB_LATENCY=4 -DVX_CFG_PTW_NUM_WALKERS=2 '
              '-DVX_CFG_PTW_WALK_CACHE_SIZE=16 -DVX_CFG_VM_PINNED_REGION_SIZE=0x10000000 '
              '-DVX_CFG_CP_LLC_CLIENT=1 -DVX_CFG_CP_ON_LLC=0 -DVX_CFG_ICACHE_SIZE=16384 '
              '-DVX_CFG_ICACHE_NUM_WAYS=4 -DVX_CFG_ICACHE_REPL_POLICY=1 '
              '-DVX_CFG_ICACHE_MSHR_SIZE=16 -DVX_CFG_ICACHE_MRSQ_SIZE=0 '
              '-DVX_CFG_ICACHE_MREQ_SIZE=0 -DVX_CFG_ICACHE_CRSQ_SIZE=0 -DVX_CFG_ICACHE_MEM_PORTS=1 '
              '-DVX_CFG_ICACHE_NUM_BANKS=1 -DVX_CFG_ICACHE_READ_MERGE=1 -DVX_CFG_ICACHE_LATENCY=2 '
              '-DVX_CFG_DCACHE_SIZE=16384 -DVX_CFG_DCACHE_NUM_WAYS=4 -DVX_CFG_DCACHE_WORD_SIZE=16 '
              '-DVX_CFG_DCACHE_WRITEBACK=1 -DVX_CFG_DCACHE_DIRTYBYTES=1 '
              '-DVX_CFG_DCACHE_LAZY_FETCH=1 -DVX_CFG_DCACHE_REPL_POLICY=1 '
              '-DVX_CFG_DCACHE_MSHR_SIZE=16 -DVX_CFG_DCACHE_LINE_SIZE=64 '
              '-DVX_CFG_DCACHE_SECTOR_SIZE=64 -DVX_CFG_DCACHE_LATENCY=2 -DVX_CFG_L1_LINK_LATENCY=0 '
              '-DVX_CFG_DCACHE_MRSQ_SIZE=4 -DVX_CFG_DCACHE_MREQ_SIZE=0 -DVX_CFG_DCACHE_CRSQ_SIZE=0 '
              '-DVX_CFG_NUM_ICACHES=1 -DVX_CFG_NUM_DCACHES=1 -DVX_CFG_DCACHE_NUM_BANKS=1 '
              '-DVX_CFG_DCACHE_BANK_HASH=0 -DVX_CFG_DCACHE_SET_HASH=1 -DVX_CFG_DCACHE_READ_MERGE=1 '
              '-DVX_CFG_L1_MEM_PORTS=1 -DVX_CFG_L2_SIZE=1048576 -DVX_CFG_L2_NUM_WAYS=8 '
              '-DVX_CFG_L2_WRITEBACK=0 -DVX_CFG_L2_DIRTYBYTES=0 -DVX_CFG_L2_LAZY_FETCH=0 '
              '-DVX_CFG_L2_REPL_POLICY=1 -DVX_CFG_L2_MSHR_SIZE=16 -DVX_CFG_L2_LATENCY=4 '
              '-DVX_CFG_L2_LINK_LATENCY=0 -DVX_CFG_L2_MRSQ_SIZE=4 -DVX_CFG_L2_MREQ_SIZE=0 '
              '-DVX_CFG_L2_CRSQ_SIZE=0 -DVX_CFG_L2_NUM_BANKS=1 -DVX_CFG_L2_BANK_HASH=1 '
              '-DVX_CFG_L2_MEM_PORTS=0 -DVX_CFG_L3_SIZE=2097152 -DVX_CFG_L3_NUM_WAYS=8 '
              '-DVX_CFG_L3_WRITEBACK=0 -DVX_CFG_L3_DIRTYBYTES=0 -DVX_CFG_L3_LAZY_FETCH=0 '
              '-DVX_CFG_L3_REPL_POLICY=1 -DVX_CFG_L3_MSHR_SIZE=16 -DVX_CFG_L3_LATENCY=4 '
              '-DVX_CFG_L3_MRSQ_SIZE=4 -DVX_CFG_L3_MREQ_SIZE=0 -DVX_CFG_L3_CRSQ_SIZE=0 '
              '-DVX_CFG_L3_NUM_BANKS=1 -DVX_CFG_L3_MEM_PORTS=0 -DVX_CFG_LMEM_NUM_BANKS=4 '
              '-DVX_CFG_LMEM_LOG_SIZE=14 -DVX_CFG_LMEM_SIZE=16384 -DVX_CFG_TCU_TYPE=TFR '
              '-DVX_CFG_NUM_TCU_LANES=4 -DVX_CFG_NUM_TCU_BLOCKS=1 -DVX_CFG_TCU_USE_DSP=0 '
              '-DVX_CFG_TCU_LATENCY=4 -DVX_CFG_TCU_PE_RATIO=1 -DVX_CFG_TCU_TF32_ENABLED=0 '
              '-DVX_CFG_TCU_FP16_ENABLE -DVX_CFG_TCU_FP16_ENABLED=1 -DVX_CFG_TCU_FP8_ENABLED=0 '
              '-DVX_CFG_TCU_FP4_ENABLED=0 -DVX_CFG_TCU_INT8_ENABLED=0 -DVX_CFG_TCU_INT4_ENABLED=0 '
              '-DVX_CFG_TCU_MX_ENABLED=0 -DVX_CFG_TCU_MXFP4_ENABLED=0 -DVX_CFG_TCU_NVFP4_ENABLED=0 '
              '-DVX_CFG_TCU_SPARSE_ENABLED=0 -DVX_CFG_TCU_DSM_ENABLED=0 '
              '-DVX_CFG_TCU_WGMMA_ENABLED=0 -DVX_CFG_NUM_DXA_CORES=1 -DVX_CFG_DXA_MEM_PORTS=1 '
              '-DVX_CFG_DXA_QUEUE_SIZE=16 -DVX_CFG_DXA_MAX_INFLIGHT=8 -DVX_CFG_NUM_RTU_CORES=1 '
              '-DVX_CFG_RTU_BVH_WIDTH=4 -DVX_CFG_RTU_TLAS_ENABLED=0 -DVX_CFG_RTU_STACK_DEPTH=16 '
              '-DVX_CFG_RTU_RECIP_DSP_SEED=0 -DVX_CFG_RTU_USE_DSP=0 -DVX_CFG_RTU_FDIV_LATENCY=17 '
              '-DVX_CFG_RTU_NUM_SLOTS=1 -DVX_CFG_RTU_NUM_CTX=4 -DVX_CFG_RTU_MERGE_DEPTH=0 '
              '-DVX_CFG_NUM_RTU_BLOCKS=2 -DVX_CFG_NUM_TEX_CORES=1 -DVX_CFG_TEX_REQ_QUEUE_SIZE=8 '
              '-DVX_CFG_TEX_MEM_QUEUE_SIZE=8 -DVX_CFG_NUM_RASTER_CORES=1 '
              '-DVX_CFG_RASTER_NUM_SLICES=1 -DVX_CFG_RASTER_TILE_LOG_SIZE=5 '
              '-DVX_CFG_RASTER_BIN_LOG_SIZE=7 -DVX_CFG_RASTER_BLOCK_LOG_SIZE=2 '
              '-DVX_CFG_RASTER_MEM_FIFO_DEPTH=8 -DVX_CFG_RASTER_QUAD_FIFO_DEPTH=32 '
              '-DVX_CFG_RASTER_MEM_QUEUE_SIZE=4 -DVX_CFG_RASTER_EARLYZ_ENABLED=0 '
              '-DVX_CFG_NUM_OM_CORES=1 -DVX_CFG_OM_MEM_QUEUE_SIZE=4 -DVX_CFG_TCACHE_SIZE=8192 '
              '-DVX_CFG_TCACHE_NUM_BANKS=1 -DVX_CFG_TCACHE_NUM_WAYS=2 -DVX_CFG_TCACHE_CRSQ_SIZE=0 '
              '-DVX_CFG_TCACHE_MSHR_SIZE=16 -DVX_CFG_TCACHE_MRSQ_SIZE=0 '
              '-DVX_CFG_TCACHE_MREQ_SIZE=0 -DVX_CFG_NUM_TCACHES=1 -DVX_CFG_RCACHE_SIZE=4096 '
              '-DVX_CFG_RCACHE_NUM_BANKS=1 -DVX_CFG_RCACHE_NUM_WAYS=2 -DVX_CFG_RCACHE_CRSQ_SIZE=0 '
              '-DVX_CFG_RCACHE_MSHR_SIZE=16 -DVX_CFG_RCACHE_MRSQ_SIZE=0 '
              '-DVX_CFG_RCACHE_MREQ_SIZE=0 -DVX_CFG_NUM_RCACHES=1 -DVX_CFG_RTCACHE_SIZE=8192 '
              '-DVX_CFG_RTCACHE_NUM_BANKS=1 -DVX_CFG_RTCACHE_NUM_WAYS=2 '
              '-DVX_CFG_RTCACHE_CRSQ_SIZE=2 -DVX_CFG_RTCACHE_MSHR_SIZE=16 '
              '-DVX_CFG_RTCACHE_MREQ_SIZE=4 -DVX_CFG_RTCACHE_MRSQ_SIZE=0 -DVX_CFG_NUM_RTCACHES=1 '
              '-DVX_CFG_OCACHE_SIZE=16384 -DVX_CFG_OCACHE_NUM_BANKS=1 -DVX_CFG_OCACHE_NUM_WAYS=2 '
              '-DVX_CFG_OCACHE_CRSQ_SIZE=0 -DVX_CFG_OCACHE_MSHR_SIZE=16 '
              '-DVX_CFG_OCACHE_MRSQ_SIZE=0 -DVX_CFG_OCACHE_MREQ_SIZE=0 -DVX_CFG_NUM_OCACHES=1 '
              '-DVX_CFG_MISA_STD=9441576 -DVX_CFG_MISA_EXT=563 -DVX_DBG_STALL_TIMEOUT=100000 '
              '-DVX_DBG_DEBUG_LEVEL=3 -std=c++17 -Wall -Wextra -pedantic -Wfatal-errors -Werror '
              '-I@SOURCE@/sw/runtime/include -I@BUILD@/sw -I@BUILD@/hw -I@SOURCE@/sim/rtlsim '
              '-I@SOURCE@/sim/common -I@SOURCE@/sw/common -I@SOURCE@/sw/runtime/common '
              '-DVX_CFG_XLEN=64 -DVX_CFG_XLEN_64 -fPIC -DVX_PROFILE=p02-tfr '
              '-DVX_CFG_EXT_LDST_MATRIX_DISABLE -DVX_CFG_EXT_TCU_ENABLE -DVX_CFG_FPU_TYPE=STD '
              '-DVX_CFG_ISSUE_WIDTH=1 -DVX_CFG_LMEM_ENABLE -DVX_CFG_NUM_ALU_BLOCKS=1 '
              '-DVX_CFG_NUM_CLUSTERS=1 -DVX_CFG_NUM_CORES=1 -DVX_CFG_NUM_FPU_BLOCKS=1 '
              '-DVX_CFG_NUM_LSU_BLOCKS=1 -DVX_CFG_NUM_THREADS=4 -DVX_CFG_NUM_WARPS=4 '
              '-DVX_CFG_TCU_DSM_DISABLE -DVX_CFG_TCU_FP16_ENABLE -DVX_CFG_TCU_FP4_DISABLE '
              '-DVX_CFG_TCU_FP8_DISABLE -DVX_CFG_TCU_INT4_DISABLE -DVX_CFG_TCU_INT8_DISABLE '
              '-DVX_CFG_TCU_LATENCY=4 -DVX_CFG_TCU_MXFP4_DISABLE -DVX_CFG_TCU_MX_DISABLE '
              '-DVX_CFG_TCU_NVFP4_DISABLE -DVX_CFG_TCU_PE_RATIO=1 -DVX_CFG_TCU_SPARSE_DISABLE '
              '-DVX_CFG_TCU_TF32_DISABLE -DVX_CFG_TCU_TYPE=TFR -DVX_CFG_TCU_USE_DSP=0 '
              '-DVX_CFG_TCU_WGMMA_DISABLE -DITYPE=bf16 -DOTYPE=fp32 -DKUNROLL=1 -O2 -DNDEBUG\n',
 'rtlsim_backend': '--exe --language 1800-2012 --assert -Wall -Wpedantic -Wno-DECLFILENAME '
                   '-Wno-REDEFMACRO --replication-limit 65536 --x-initial unique --x-assign unique '
                   'verilator.vlt -DVX_CFG_XLEN=64 -DVX_CFG_XLEN_64 -DVX_PROFILE=p02-tfr '
                   '-DVX_CFG_EXT_LDST_MATRIX_DISABLE -DVX_CFG_EXT_TCU_ENABLE -DVX_CFG_FPU_TYPE=STD '
                   '-DVX_CFG_ISSUE_WIDTH=1 -DVX_CFG_LMEM_ENABLE -DVX_CFG_NUM_ALU_BLOCKS=1 '
                   '-DVX_CFG_NUM_CLUSTERS=1 -DVX_CFG_NUM_CORES=1 -DVX_CFG_NUM_FPU_BLOCKS=1 '
                   '-DVX_CFG_NUM_LSU_BLOCKS=1 -DVX_CFG_NUM_THREADS=4 -DVX_CFG_NUM_WARPS=4 '
                   '-DVX_CFG_TCU_DSM_DISABLE -DVX_CFG_TCU_FP16_ENABLE -DVX_CFG_TCU_FP4_DISABLE '
                   '-DVX_CFG_TCU_FP8_DISABLE -DVX_CFG_TCU_INT4_DISABLE -DVX_CFG_TCU_INT8_DISABLE '
                   '-DVX_CFG_TCU_LATENCY=4 -DVX_CFG_TCU_MXFP4_DISABLE -DVX_CFG_TCU_MX_DISABLE '
                   '-DVX_CFG_TCU_NVFP4_DISABLE -DVX_CFG_TCU_PE_RATIO=1 -DVX_CFG_TCU_SPARSE_DISABLE '
                   '-DVX_CFG_TCU_TF32_DISABLE -DVX_CFG_TCU_TYPE=TFR -DVX_CFG_TCU_USE_DSP=0 '
                   '-DVX_CFG_TCU_WGMMA_DISABLE -DITYPE=bf16 -DOTYPE=fp32 -DKUNROLL=1 -DSIMULATION '
                   '-DSV_DPI -DVX_CFG_FPU_TYPE_STD -DVX_CFG_TCU_TYPE_TFR -I@BUILD@/sw -I@BUILD@/hw '
                   '-I@SOURCE@/sim/rtlsim -I@SOURCE@/hw/rtl -I@SOURCE@/hw/dpi '
                   '-I@SOURCE@/hw/rtl/libs -I@SOURCE@/hw/rtl/interfaces -I@SOURCE@/hw/rtl/core '
                   '-I@SOURCE@/hw/rtl/mem -I@SOURCE@/hw/rtl/vm -I@SOURCE@/hw/rtl/cache '
                   '-I@SOURCE@/hw/rtl/fpu -I@SOURCE@/hw/rtl/tcu -I@SOURCE@/hw/rtl/tcu/tfr '
                   '@SOURCE@/hw/rtl/VX_gpu_pkg.sv @SOURCE@/hw/rtl/fpu/VX_fpu_pkg.sv '
                   '@SOURCE@/hw/rtl/tcu/VX_tcu_pkg.sv @SOURCE@/hw/rtl/VX_trace_pkg.sv  --cc '
                   'rtlsim_shim --top-module rtlsim_shim -j 2 -DNDEBUG -MAKEFLAGS OPT_FAST=-O2 '
                   '-MAKEFLAGS OPT_GLOBAL=-O2\n'
                   '-std=c++17 -Wall -Wextra -Wfatal-errors -Werror -fPIC '
                   '-fno-tree-loop-distribute-patterns -I@BUILD@/sw -I@BUILD@/hw '
                   '-I@SOURCE@/sim/common -I@SOURCE@/sw/common '
                   '-I@SOURCE@/third_party/softfloat/source/include '
                   '-I@SOURCE@/third_party/ramulator/ext/spdlog/include '
                   '-I@SOURCE@/third_party/ramulator/ext/yaml-cpp/include '
                   '-I@SOURCE@/third_party/ramulator/src -DVX_CFG_XLEN=64 -DVX_CFG_XLEN_64 '
                   '-DVX_PROFILE=p02-tfr -DVX_CFG_EXT_LDST_MATRIX_DISABLE -DVX_CFG_EXT_TCU_ENABLE '
                   '-DVX_CFG_FPU_TYPE=STD -DVX_CFG_ISSUE_WIDTH=1 -DVX_CFG_LMEM_ENABLE '
                   '-DVX_CFG_NUM_ALU_BLOCKS=1 -DVX_CFG_NUM_CLUSTERS=1 -DVX_CFG_NUM_CORES=1 '
                   '-DVX_CFG_NUM_FPU_BLOCKS=1 -DVX_CFG_NUM_LSU_BLOCKS=1 -DVX_CFG_NUM_THREADS=4 '
                   '-DVX_CFG_NUM_WARPS=4 -DVX_CFG_TCU_DSM_DISABLE -DVX_CFG_TCU_FP16_ENABLE '
                   '-DVX_CFG_TCU_FP4_DISABLE -DVX_CFG_TCU_FP8_DISABLE -DVX_CFG_TCU_INT4_DISABLE '
                   '-DVX_CFG_TCU_INT8_DISABLE -DVX_CFG_TCU_LATENCY=4 -DVX_CFG_TCU_MXFP4_DISABLE '
                   '-DVX_CFG_TCU_MX_DISABLE -DVX_CFG_TCU_NVFP4_DISABLE -DVX_CFG_TCU_PE_RATIO=1 '
                   '-DVX_CFG_TCU_SPARSE_DISABLE -DVX_CFG_TCU_TF32_DISABLE -DVX_CFG_TCU_TYPE=TFR '
                   '-DVX_CFG_TCU_USE_DSP=0 -DVX_CFG_TCU_WGMMA_DISABLE -DITYPE=bf16 -DOTYPE=fp32 '
                   '-DKUNROLL=1 -DSIMULATION -DSV_DPI -DNDEBUG\n',
 'application': '-march=rv64imafd -mabi=lp64d -Wall -Wextra -Wfatal-errors -Werror '
                '-Wno-unused-command-line-argument -O3 -mcmodel=medany -fno-rtti -fno-exceptions '
                '-nostartfiles -nostdlib -fdata-sections -ffunction-sections '
                '-I@SOURCE@/sw/kernel/include -I@BUILD@/sw -I@BUILD@/hw -I@SOURCE@/sw/common '
                '-DNDEBUG -D__VORTEX__ -DVX_PROFILE=p02-tfr -DVX_CFG_EXT_LDST_MATRIX_DISABLE '
                '-DVX_CFG_EXT_TCU_ENABLE -DVX_CFG_FPU_TYPE=STD -DVX_CFG_ISSUE_WIDTH=1 '
                '-DVX_CFG_LMEM_ENABLE -DVX_CFG_NUM_ALU_BLOCKS=1 -DVX_CFG_NUM_CLUSTERS=1 '
                '-DVX_CFG_NUM_CORES=1 -DVX_CFG_NUM_FPU_BLOCKS=1 -DVX_CFG_NUM_LSU_BLOCKS=1 '
                '-DVX_CFG_NUM_THREADS=4 -DVX_CFG_NUM_WARPS=4 -DVX_CFG_TCU_DSM_DISABLE '
                '-DVX_CFG_TCU_FP16_ENABLE -DVX_CFG_TCU_FP4_DISABLE -DVX_CFG_TCU_FP8_DISABLE '
                '-DVX_CFG_TCU_INT4_DISABLE -DVX_CFG_TCU_INT8_DISABLE -DVX_CFG_TCU_LATENCY=4 '
                '-DVX_CFG_TCU_MXFP4_DISABLE -DVX_CFG_TCU_MX_DISABLE -DVX_CFG_TCU_NVFP4_DISABLE '
                '-DVX_CFG_TCU_PE_RATIO=1 -DVX_CFG_TCU_SPARSE_DISABLE -DVX_CFG_TCU_TF32_DISABLE '
                '-DVX_CFG_TCU_TYPE=TFR -DVX_CFG_TCU_USE_DSP=0 -DVX_CFG_TCU_WGMMA_DISABLE '
                '-DITYPE=bf16 -DOTYPE=fp32 -DKUNROLL=1 -DVX_CFG_XLEN=64 -DVX_CFG_XLEN_64 '
                '-DVX_CFG_FLEN=64 -DVX_CFG_FLEN_64 -DVX_CFG_FPU_TYPE=STD -DVX_CFG_FPU_TYPE_STD '
                '-DVX_CFG_TCU_TYPE=TFR -DVX_CFG_TCU_TYPE_TFR -DVX_CFG_PLATFORM_MEMORY_TYPE=HBM2 '
                '-DVX_CFG_PLATFORM_MEMORY_TYPE_HBM2 -DVX_CFG_NUM_CLUSTERS=1 -DVX_CFG_NUM_CORES=1 '
                '-DVX_CFG_SOCKET_SIZE=1 -DVX_CFG_RESET_DELAY=8 -DVX_CFG_ICACHE_ENABLE '
                '-DVX_CFG_ICACHE_ENABLED=1 -DVX_CFG_DCACHE_ENABLE -DVX_CFG_DCACHE_ENABLED=1 '
                '-DVX_CFG_LMEM_ENABLE -DVX_CFG_LMEM_ENABLED=1 -DVX_CFG_L2_ENABLED=0 '
                '-DVX_CFG_L3_ENABLED=0 -DVX_CFG_VM_ENABLED=0 -DVX_CFG_EXT_D_ENABLE '
                '-DVX_CFG_EXT_D_ENABLED=1 -DVX_CFG_FLEN=64 -DVX_CFG_EXT_M_ENABLE '
                '-DVX_CFG_EXT_M_ENABLED=1 -DVX_CFG_EXT_F_ENABLE -DVX_CFG_EXT_F_ENABLED=1 '
                '-DVX_CFG_EXT_C_ENABLED=0 -DVX_CFG_EXT_A_ENABLED=0 -DVX_CFG_EXT_ZACAS_ENABLED=0 '
                '-DVX_CFG_EXT_ZICOND_ENABLE -DVX_CFG_EXT_ZICOND_ENABLED=1 '
                '-DVX_CFG_EXT_ZFHMIN_ENABLED=0 -DVX_CFG_EXT_TCU_ENABLE -DVX_CFG_EXT_TCU_ENABLED=1 '
                '-DVX_CFG_EXT_DMA_ENABLED=0 -DVX_CFG_EXT_DXA_ENABLED=0 -DVX_CFG_EXT_TEX_ENABLED=0 '
                '-DVX_CFG_EXT_RASTER_ENABLED=0 -DVX_CFG_EXT_OM_ENABLED=0 '
                '-DVX_CFG_EXT_RTU_ENABLED=0 -DVX_CFG_EXT_MUFU_ENABLED=0 '
                '-DVX_CFG_EXT_LDST_WIDE_ENABLED=0 -DVX_CFG_EXT_LDST_MATRIX_ENABLED=0 '
                '-DVX_CFG_VLEN=256 -DVX_CFG_NUM_WARPS=4 -DVX_CFG_NUM_THREADS=4 '
                '-DVX_CFG_NUM_BARRIERS=8 -DVX_CFG_MAX_BAR_EVENTS=32 -DVX_CFG_IBUF_SIZE=4 '
                '-DVX_CFG_DISPATCH_QUEUE_SIZE=4 -DVX_CFG_ISSUE_WIDTH=1 -DVX_CFG_FETCH_WIDTH=1 '
                '-DVX_CFG_SIMD_WIDTH=4 -DVX_CFG_NUM_OPCS=1 -DVX_CFG_NUM_GPR_BANKS=4 '
                '-DVX_CFG_NUM_VGPR_BANKS=2 -DVX_CFG_MEM_BLOCK_SIZE=64 -DVX_CFG_MEM_ADDR_WIDTH=48 '
                '-DVX_CFG_L1_LINE_SIZE=64 -DVX_CFG_L2_LINE_SIZE=64 -DVX_CFG_L2_SECTOR_SIZE=64 '
                '-DVX_CFG_L3_LINE_SIZE=64 -DVX_CFG_L3_SECTOR_SIZE=64 '
                '-DVX_CFG_PLATFORM_MEMORY_NUM_BANKS=2 -DVX_CFG_PLATFORM_MEMORY_ADDR_WIDTH=48 '
                '-DVX_CFG_PLATFORM_MEMORY_DATA_SIZE=64 -DVX_CFG_PLATFORM_MEMORY_INTERLEAVE=1 '
                '-DVX_CFG_PLATFORM_MEMORY_PEAK_BW=460000 -DVX_CFG_PLATFORM_CLOCK_RATE=400 '
                '-DVX_CFG_PLATFORM_MEMORY_TYPE=HBM2 -DVX_CFG_PLATFORM_MEMORY_DATA_RATE=800 '
                '-DVX_CFG_PLATFORM_MEMORY_LATENCY=0 -DVX_CFG_PLATFORM_MEMORY_QUEUE_SIZE=0 '
                '-DVX_CFG_NUM_ALU_LANES=4 -DVX_CFG_NUM_ALU_BLOCKS=1 -DVX_CFG_NUM_SFU_LANES=4 '
                '-DVX_CFG_NUM_SFU_BLOCKS=1 -DVX_CFG_NUM_LSU_LANES=4 -DVX_CFG_NUM_LSU_BLOCKS=1 '
                '-DVX_CFG_LSU_STACK_INTERLEAVE_ENABLE -DVX_CFG_LSU_STACK_INTERLEAVE_ENABLED=1 '
                '-DVX_CFG_LSU_LINE_SIZE=32 -DVX_CFG_LSU_QUEUE_IN_SIZE=4 '
                '-DVX_CFG_LSU_PENDING_SIZE=8 -DVX_CFG_LSU_PENDING_LIMIT=32 -DVX_CFG_FPU_TYPE=STD '
                '-DVX_CFG_NUM_FPU_LANES=4 -DVX_CFG_NUM_FPU_BLOCKS=1 -DVX_CFG_FPU_QUEUE_SIZE=2 '
                '-DVX_CFG_FPU_USE_DSP=0 -DVX_CFG_FMA_LATENCY=12 -DVX_CFG_FDIV_LATENCY=32 '
                '-DVX_CFG_FSQRT_LATENCY=32 -DVX_CFG_FNCP_LATENCY=2 -DVX_CFG_FCVT_LATENCY=5 '
                '-DVX_CFG_FMA_PE_RATIO=1 -DVX_CFG_FMA64_PE_RATIO=1 -DVX_CFG_FDIV_PE_RATIO=1 '
                '-DVX_CFG_FSQRT_PE_RATIO=1 -DVX_CFG_FCVT_PE_RATIO=1 -DVX_CFG_FNCP_PE_RATIO=1 '
                '-DVX_CFG_NUM_MUFU_LANES=1 -DVX_CFG_AMO_RS_SIZE=4 -DVX_CFG_NUM_VPU_LANES=4 '
                '-DVX_CFG_NUM_VPU_BLOCKS=1 -DVX_CFG_TLB_SIZE=32 -DVX_CFG_DTLB_SIZE=16 '
                '-DVX_CFG_ITLB_SIZE=8 -DVX_CFG_L1_TLB_MSHR_SIZE=4 -DVX_CFG_UTLB_SIZE=8 '
                '-DVX_CFG_CTLB_SIZE=8 -DVX_CFG_L2_TLB_SIZE=512 -DVX_CFG_L2_TLB_NUM_WAYS=4 '
                '-DVX_CFG_L2_TLB_MEGA_SIZE=8 -DVX_CFG_L2_TLB_MSHR_SIZE=8 -DVX_CFG_L2_TLB_LATENCY=4 '
                '-DVX_CFG_PTW_NUM_WALKERS=2 -DVX_CFG_PTW_WALK_CACHE_SIZE=16 '
                '-DVX_CFG_VM_PINNED_REGION_SIZE=0x10000000 -DVX_CFG_CP_LLC_CLIENT=1 '
                '-DVX_CFG_CP_ON_LLC=0 -DVX_CFG_ICACHE_SIZE=16384 -DVX_CFG_ICACHE_NUM_WAYS=4 '
                '-DVX_CFG_ICACHE_REPL_POLICY=1 -DVX_CFG_ICACHE_MSHR_SIZE=16 '
                '-DVX_CFG_ICACHE_MRSQ_SIZE=0 -DVX_CFG_ICACHE_MREQ_SIZE=0 '
                '-DVX_CFG_ICACHE_CRSQ_SIZE=0 -DVX_CFG_ICACHE_MEM_PORTS=1 '
                '-DVX_CFG_ICACHE_NUM_BANKS=1 -DVX_CFG_ICACHE_READ_MERGE=1 '
                '-DVX_CFG_ICACHE_LATENCY=2 -DVX_CFG_DCACHE_SIZE=16384 -DVX_CFG_DCACHE_NUM_WAYS=4 '
                '-DVX_CFG_DCACHE_WORD_SIZE=16 -DVX_CFG_DCACHE_WRITEBACK=1 '
                '-DVX_CFG_DCACHE_DIRTYBYTES=1 -DVX_CFG_DCACHE_LAZY_FETCH=1 '
                '-DVX_CFG_DCACHE_REPL_POLICY=1 -DVX_CFG_DCACHE_MSHR_SIZE=16 '
                '-DVX_CFG_DCACHE_LINE_SIZE=64 -DVX_CFG_DCACHE_SECTOR_SIZE=64 '
                '-DVX_CFG_DCACHE_LATENCY=2 -DVX_CFG_L1_LINK_LATENCY=0 -DVX_CFG_DCACHE_MRSQ_SIZE=4 '
                '-DVX_CFG_DCACHE_MREQ_SIZE=0 -DVX_CFG_DCACHE_CRSQ_SIZE=0 -DVX_CFG_NUM_ICACHES=1 '
                '-DVX_CFG_NUM_DCACHES=1 -DVX_CFG_DCACHE_NUM_BANKS=1 -DVX_CFG_DCACHE_BANK_HASH=0 '
                '-DVX_CFG_DCACHE_SET_HASH=1 -DVX_CFG_DCACHE_READ_MERGE=1 -DVX_CFG_L1_MEM_PORTS=1 '
                '-DVX_CFG_L2_SIZE=1048576 -DVX_CFG_L2_NUM_WAYS=8 -DVX_CFG_L2_WRITEBACK=0 '
                '-DVX_CFG_L2_DIRTYBYTES=0 -DVX_CFG_L2_LAZY_FETCH=0 -DVX_CFG_L2_REPL_POLICY=1 '
                '-DVX_CFG_L2_MSHR_SIZE=16 -DVX_CFG_L2_LATENCY=4 -DVX_CFG_L2_LINK_LATENCY=0 '
                '-DVX_CFG_L2_MRSQ_SIZE=4 -DVX_CFG_L2_MREQ_SIZE=0 -DVX_CFG_L2_CRSQ_SIZE=0 '
                '-DVX_CFG_L2_NUM_BANKS=1 -DVX_CFG_L2_BANK_HASH=1 -DVX_CFG_L2_MEM_PORTS=0 '
                '-DVX_CFG_L3_SIZE=2097152 -DVX_CFG_L3_NUM_WAYS=8 -DVX_CFG_L3_WRITEBACK=0 '
                '-DVX_CFG_L3_DIRTYBYTES=0 -DVX_CFG_L3_LAZY_FETCH=0 -DVX_CFG_L3_REPL_POLICY=1 '
                '-DVX_CFG_L3_MSHR_SIZE=16 -DVX_CFG_L3_LATENCY=4 -DVX_CFG_L3_MRSQ_SIZE=4 '
                '-DVX_CFG_L3_MREQ_SIZE=0 -DVX_CFG_L3_CRSQ_SIZE=0 -DVX_CFG_L3_NUM_BANKS=1 '
                '-DVX_CFG_L3_MEM_PORTS=0 -DVX_CFG_LMEM_NUM_BANKS=4 -DVX_CFG_LMEM_LOG_SIZE=14 '
                '-DVX_CFG_LMEM_SIZE=16384 -DVX_CFG_TCU_TYPE=TFR -DVX_CFG_NUM_TCU_LANES=4 '
                '-DVX_CFG_NUM_TCU_BLOCKS=1 -DVX_CFG_TCU_USE_DSP=0 -DVX_CFG_TCU_LATENCY=4 '
                '-DVX_CFG_TCU_PE_RATIO=1 -DVX_CFG_TCU_TF32_ENABLED=0 -DVX_CFG_TCU_FP16_ENABLE '
                '-DVX_CFG_TCU_FP16_ENABLED=1 -DVX_CFG_TCU_FP8_ENABLED=0 -DVX_CFG_TCU_FP4_ENABLED=0 '
                '-DVX_CFG_TCU_INT8_ENABLED=0 -DVX_CFG_TCU_INT4_ENABLED=0 -DVX_CFG_TCU_MX_ENABLED=0 '
                '-DVX_CFG_TCU_MXFP4_ENABLED=0 -DVX_CFG_TCU_NVFP4_ENABLED=0 '
                '-DVX_CFG_TCU_SPARSE_ENABLED=0 -DVX_CFG_TCU_DSM_ENABLED=0 '
                '-DVX_CFG_TCU_WGMMA_ENABLED=0 -DVX_CFG_NUM_DXA_CORES=1 -DVX_CFG_DXA_MEM_PORTS=1 '
                '-DVX_CFG_DXA_QUEUE_SIZE=16 -DVX_CFG_DXA_MAX_INFLIGHT=8 -DVX_CFG_NUM_RTU_CORES=1 '
                '-DVX_CFG_RTU_BVH_WIDTH=4 -DVX_CFG_RTU_TLAS_ENABLED=0 -DVX_CFG_RTU_STACK_DEPTH=16 '
                '-DVX_CFG_RTU_RECIP_DSP_SEED=0 -DVX_CFG_RTU_USE_DSP=0 -DVX_CFG_RTU_FDIV_LATENCY=17 '
                '-DVX_CFG_RTU_NUM_SLOTS=1 -DVX_CFG_RTU_NUM_CTX=4 -DVX_CFG_RTU_MERGE_DEPTH=0 '
                '-DVX_CFG_NUM_RTU_BLOCKS=2 -DVX_CFG_NUM_TEX_CORES=1 -DVX_CFG_TEX_REQ_QUEUE_SIZE=8 '
                '-DVX_CFG_TEX_MEM_QUEUE_SIZE=8 -DVX_CFG_NUM_RASTER_CORES=1 '
                '-DVX_CFG_RASTER_NUM_SLICES=1 -DVX_CFG_RASTER_TILE_LOG_SIZE=5 '
                '-DVX_CFG_RASTER_BIN_LOG_SIZE=7 -DVX_CFG_RASTER_BLOCK_LOG_SIZE=2 '
                '-DVX_CFG_RASTER_MEM_FIFO_DEPTH=8 -DVX_CFG_RASTER_QUAD_FIFO_DEPTH=32 '
                '-DVX_CFG_RASTER_MEM_QUEUE_SIZE=4 -DVX_CFG_RASTER_EARLYZ_ENABLED=0 '
                '-DVX_CFG_NUM_OM_CORES=1 -DVX_CFG_OM_MEM_QUEUE_SIZE=4 -DVX_CFG_TCACHE_SIZE=8192 '
                '-DVX_CFG_TCACHE_NUM_BANKS=1 -DVX_CFG_TCACHE_NUM_WAYS=2 '
                '-DVX_CFG_TCACHE_CRSQ_SIZE=0 -DVX_CFG_TCACHE_MSHR_SIZE=16 '
                '-DVX_CFG_TCACHE_MRSQ_SIZE=0 -DVX_CFG_TCACHE_MREQ_SIZE=0 -DVX_CFG_NUM_TCACHES=1 '
                '-DVX_CFG_RCACHE_SIZE=4096 -DVX_CFG_RCACHE_NUM_BANKS=1 -DVX_CFG_RCACHE_NUM_WAYS=2 '
                '-DVX_CFG_RCACHE_CRSQ_SIZE=0 -DVX_CFG_RCACHE_MSHR_SIZE=16 '
                '-DVX_CFG_RCACHE_MRSQ_SIZE=0 -DVX_CFG_RCACHE_MREQ_SIZE=0 -DVX_CFG_NUM_RCACHES=1 '
                '-DVX_CFG_RTCACHE_SIZE=8192 -DVX_CFG_RTCACHE_NUM_BANKS=1 '
                '-DVX_CFG_RTCACHE_NUM_WAYS=2 -DVX_CFG_RTCACHE_CRSQ_SIZE=2 '
                '-DVX_CFG_RTCACHE_MSHR_SIZE=16 -DVX_CFG_RTCACHE_MREQ_SIZE=4 '
                '-DVX_CFG_RTCACHE_MRSQ_SIZE=0 -DVX_CFG_NUM_RTCACHES=1 -DVX_CFG_OCACHE_SIZE=16384 '
                '-DVX_CFG_OCACHE_NUM_BANKS=1 -DVX_CFG_OCACHE_NUM_WAYS=2 '
                '-DVX_CFG_OCACHE_CRSQ_SIZE=0 -DVX_CFG_OCACHE_MSHR_SIZE=16 '
                '-DVX_CFG_OCACHE_MRSQ_SIZE=0 -DVX_CFG_OCACHE_MREQ_SIZE=0 -DVX_CFG_NUM_OCACHES=1 '
                '-DVX_CFG_MISA_STD=9441576 -DVX_CFG_MISA_EXT=563 -DVX_DBG_STALL_TIMEOUT=100000 '
                '-DVX_DBG_DEBUG_LEVEL=3\n'
                '-I@SOURCE@/third_party/softfloat/source/include -std=c++17 -Wall -Wextra '
                '-pedantic -Wfatal-errors -Werror -DOMPI_SKIP_MPICXX -DMPICH_SKIP_MPICXX '
                '-I@SOURCE@/sw/runtime/include -I@SOURCE@/sw/kernel/include -I@BUILD@/sw '
                '-I@BUILD@/hw -I@SOURCE@/sw/common -DVX_PROFILE=p02-tfr '
                '-DVX_CFG_EXT_LDST_MATRIX_DISABLE -DVX_CFG_EXT_TCU_ENABLE -DVX_CFG_FPU_TYPE=STD '
                '-DVX_CFG_ISSUE_WIDTH=1 -DVX_CFG_LMEM_ENABLE -DVX_CFG_NUM_ALU_BLOCKS=1 '
                '-DVX_CFG_NUM_CLUSTERS=1 -DVX_CFG_NUM_CORES=1 -DVX_CFG_NUM_FPU_BLOCKS=1 '
                '-DVX_CFG_NUM_LSU_BLOCKS=1 -DVX_CFG_NUM_THREADS=4 -DVX_CFG_NUM_WARPS=4 '
                '-DVX_CFG_TCU_DSM_DISABLE -DVX_CFG_TCU_FP16_ENABLE -DVX_CFG_TCU_FP4_DISABLE '
                '-DVX_CFG_TCU_FP8_DISABLE -DVX_CFG_TCU_INT4_DISABLE -DVX_CFG_TCU_INT8_DISABLE '
                '-DVX_CFG_TCU_LATENCY=4 -DVX_CFG_TCU_MXFP4_DISABLE -DVX_CFG_TCU_MX_DISABLE '
                '-DVX_CFG_TCU_NVFP4_DISABLE -DVX_CFG_TCU_PE_RATIO=1 -DVX_CFG_TCU_SPARSE_DISABLE '
                '-DVX_CFG_TCU_TF32_DISABLE -DVX_CFG_TCU_TYPE=TFR -DVX_CFG_TCU_USE_DSP=0 '
                '-DVX_CFG_TCU_WGMMA_DISABLE -DITYPE=bf16 -DOTYPE=fp32 -DKUNROLL=1 -DVX_CFG_XLEN=64 '
                '-DVX_CFG_XLEN_64 -DVX_CFG_FLEN=64 -DVX_CFG_FLEN_64 -DVX_CFG_FPU_TYPE=STD '
                '-DVX_CFG_FPU_TYPE_STD -DVX_CFG_TCU_TYPE=TFR -DVX_CFG_TCU_TYPE_TFR '
                '-DVX_CFG_PLATFORM_MEMORY_TYPE=HBM2 -DVX_CFG_PLATFORM_MEMORY_TYPE_HBM2 '
                '-DVX_CFG_NUM_CLUSTERS=1 -DVX_CFG_NUM_CORES=1 -DVX_CFG_SOCKET_SIZE=1 '
                '-DVX_CFG_RESET_DELAY=8 -DVX_CFG_ICACHE_ENABLE -DVX_CFG_ICACHE_ENABLED=1 '
                '-DVX_CFG_DCACHE_ENABLE -DVX_CFG_DCACHE_ENABLED=1 -DVX_CFG_LMEM_ENABLE '
                '-DVX_CFG_LMEM_ENABLED=1 -DVX_CFG_L2_ENABLED=0 -DVX_CFG_L3_ENABLED=0 '
                '-DVX_CFG_VM_ENABLED=0 -DVX_CFG_EXT_D_ENABLE -DVX_CFG_EXT_D_ENABLED=1 '
                '-DVX_CFG_FLEN=64 -DVX_CFG_EXT_M_ENABLE -DVX_CFG_EXT_M_ENABLED=1 '
                '-DVX_CFG_EXT_F_ENABLE -DVX_CFG_EXT_F_ENABLED=1 -DVX_CFG_EXT_C_ENABLED=0 '
                '-DVX_CFG_EXT_A_ENABLED=0 -DVX_CFG_EXT_ZACAS_ENABLED=0 -DVX_CFG_EXT_ZICOND_ENABLE '
                '-DVX_CFG_EXT_ZICOND_ENABLED=1 -DVX_CFG_EXT_ZFHMIN_ENABLED=0 '
                '-DVX_CFG_EXT_TCU_ENABLE -DVX_CFG_EXT_TCU_ENABLED=1 -DVX_CFG_EXT_DMA_ENABLED=0 '
                '-DVX_CFG_EXT_DXA_ENABLED=0 -DVX_CFG_EXT_TEX_ENABLED=0 '
                '-DVX_CFG_EXT_RASTER_ENABLED=0 -DVX_CFG_EXT_OM_ENABLED=0 '
                '-DVX_CFG_EXT_RTU_ENABLED=0 -DVX_CFG_EXT_MUFU_ENABLED=0 '
                '-DVX_CFG_EXT_LDST_WIDE_ENABLED=0 -DVX_CFG_EXT_LDST_MATRIX_ENABLED=0 '
                '-DVX_CFG_VLEN=256 -DVX_CFG_NUM_WARPS=4 -DVX_CFG_NUM_THREADS=4 '
                '-DVX_CFG_NUM_BARRIERS=8 -DVX_CFG_MAX_BAR_EVENTS=32 -DVX_CFG_IBUF_SIZE=4 '
                '-DVX_CFG_DISPATCH_QUEUE_SIZE=4 -DVX_CFG_ISSUE_WIDTH=1 -DVX_CFG_FETCH_WIDTH=1 '
                '-DVX_CFG_SIMD_WIDTH=4 -DVX_CFG_NUM_OPCS=1 -DVX_CFG_NUM_GPR_BANKS=4 '
                '-DVX_CFG_NUM_VGPR_BANKS=2 -DVX_CFG_MEM_BLOCK_SIZE=64 -DVX_CFG_MEM_ADDR_WIDTH=48 '
                '-DVX_CFG_L1_LINE_SIZE=64 -DVX_CFG_L2_LINE_SIZE=64 -DVX_CFG_L2_SECTOR_SIZE=64 '
                '-DVX_CFG_L3_LINE_SIZE=64 -DVX_CFG_L3_SECTOR_SIZE=64 '
                '-DVX_CFG_PLATFORM_MEMORY_NUM_BANKS=2 -DVX_CFG_PLATFORM_MEMORY_ADDR_WIDTH=48 '
                '-DVX_CFG_PLATFORM_MEMORY_DATA_SIZE=64 -DVX_CFG_PLATFORM_MEMORY_INTERLEAVE=1 '
                '-DVX_CFG_PLATFORM_MEMORY_PEAK_BW=460000 -DVX_CFG_PLATFORM_CLOCK_RATE=400 '
                '-DVX_CFG_PLATFORM_MEMORY_TYPE=HBM2 -DVX_CFG_PLATFORM_MEMORY_DATA_RATE=800 '
                '-DVX_CFG_PLATFORM_MEMORY_LATENCY=0 -DVX_CFG_PLATFORM_MEMORY_QUEUE_SIZE=0 '
                '-DVX_CFG_NUM_ALU_LANES=4 -DVX_CFG_NUM_ALU_BLOCKS=1 -DVX_CFG_NUM_SFU_LANES=4 '
                '-DVX_CFG_NUM_SFU_BLOCKS=1 -DVX_CFG_NUM_LSU_LANES=4 -DVX_CFG_NUM_LSU_BLOCKS=1 '
                '-DVX_CFG_LSU_STACK_INTERLEAVE_ENABLE -DVX_CFG_LSU_STACK_INTERLEAVE_ENABLED=1 '
                '-DVX_CFG_LSU_LINE_SIZE=32 -DVX_CFG_LSU_QUEUE_IN_SIZE=4 '
                '-DVX_CFG_LSU_PENDING_SIZE=8 -DVX_CFG_LSU_PENDING_LIMIT=32 -DVX_CFG_FPU_TYPE=STD '
                '-DVX_CFG_NUM_FPU_LANES=4 -DVX_CFG_NUM_FPU_BLOCKS=1 -DVX_CFG_FPU_QUEUE_SIZE=2 '
                '-DVX_CFG_FPU_USE_DSP=0 -DVX_CFG_FMA_LATENCY=12 -DVX_CFG_FDIV_LATENCY=32 '
                '-DVX_CFG_FSQRT_LATENCY=32 -DVX_CFG_FNCP_LATENCY=2 -DVX_CFG_FCVT_LATENCY=5 '
                '-DVX_CFG_FMA_PE_RATIO=1 -DVX_CFG_FMA64_PE_RATIO=1 -DVX_CFG_FDIV_PE_RATIO=1 '
                '-DVX_CFG_FSQRT_PE_RATIO=1 -DVX_CFG_FCVT_PE_RATIO=1 -DVX_CFG_FNCP_PE_RATIO=1 '
                '-DVX_CFG_NUM_MUFU_LANES=1 -DVX_CFG_AMO_RS_SIZE=4 -DVX_CFG_NUM_VPU_LANES=4 '
                '-DVX_CFG_NUM_VPU_BLOCKS=1 -DVX_CFG_TLB_SIZE=32 -DVX_CFG_DTLB_SIZE=16 '
                '-DVX_CFG_ITLB_SIZE=8 -DVX_CFG_L1_TLB_MSHR_SIZE=4 -DVX_CFG_UTLB_SIZE=8 '
                '-DVX_CFG_CTLB_SIZE=8 -DVX_CFG_L2_TLB_SIZE=512 -DVX_CFG_L2_TLB_NUM_WAYS=4 '
                '-DVX_CFG_L2_TLB_MEGA_SIZE=8 -DVX_CFG_L2_TLB_MSHR_SIZE=8 -DVX_CFG_L2_TLB_LATENCY=4 '
                '-DVX_CFG_PTW_NUM_WALKERS=2 -DVX_CFG_PTW_WALK_CACHE_SIZE=16 '
                '-DVX_CFG_VM_PINNED_REGION_SIZE=0x10000000 -DVX_CFG_CP_LLC_CLIENT=1 '
                '-DVX_CFG_CP_ON_LLC=0 -DVX_CFG_ICACHE_SIZE=16384 -DVX_CFG_ICACHE_NUM_WAYS=4 '
                '-DVX_CFG_ICACHE_REPL_POLICY=1 -DVX_CFG_ICACHE_MSHR_SIZE=16 '
                '-DVX_CFG_ICACHE_MRSQ_SIZE=0 -DVX_CFG_ICACHE_MREQ_SIZE=0 '
                '-DVX_CFG_ICACHE_CRSQ_SIZE=0 -DVX_CFG_ICACHE_MEM_PORTS=1 '
                '-DVX_CFG_ICACHE_NUM_BANKS=1 -DVX_CFG_ICACHE_READ_MERGE=1 '
                '-DVX_CFG_ICACHE_LATENCY=2 -DVX_CFG_DCACHE_SIZE=16384 -DVX_CFG_DCACHE_NUM_WAYS=4 '
                '-DVX_CFG_DCACHE_WORD_SIZE=16 -DVX_CFG_DCACHE_WRITEBACK=1 '
                '-DVX_CFG_DCACHE_DIRTYBYTES=1 -DVX_CFG_DCACHE_LAZY_FETCH=1 '
                '-DVX_CFG_DCACHE_REPL_POLICY=1 -DVX_CFG_DCACHE_MSHR_SIZE=16 '
                '-DVX_CFG_DCACHE_LINE_SIZE=64 -DVX_CFG_DCACHE_SECTOR_SIZE=64 '
                '-DVX_CFG_DCACHE_LATENCY=2 -DVX_CFG_L1_LINK_LATENCY=0 -DVX_CFG_DCACHE_MRSQ_SIZE=4 '
                '-DVX_CFG_DCACHE_MREQ_SIZE=0 -DVX_CFG_DCACHE_CRSQ_SIZE=0 -DVX_CFG_NUM_ICACHES=1 '
                '-DVX_CFG_NUM_DCACHES=1 -DVX_CFG_DCACHE_NUM_BANKS=1 -DVX_CFG_DCACHE_BANK_HASH=0 '
                '-DVX_CFG_DCACHE_SET_HASH=1 -DVX_CFG_DCACHE_READ_MERGE=1 -DVX_CFG_L1_MEM_PORTS=1 '
                '-DVX_CFG_L2_SIZE=1048576 -DVX_CFG_L2_NUM_WAYS=8 -DVX_CFG_L2_WRITEBACK=0 '
                '-DVX_CFG_L2_DIRTYBYTES=0 -DVX_CFG_L2_LAZY_FETCH=0 -DVX_CFG_L2_REPL_POLICY=1 '
                '-DVX_CFG_L2_MSHR_SIZE=16 -DVX_CFG_L2_LATENCY=4 -DVX_CFG_L2_LINK_LATENCY=0 '
                '-DVX_CFG_L2_MRSQ_SIZE=4 -DVX_CFG_L2_MREQ_SIZE=0 -DVX_CFG_L2_CRSQ_SIZE=0 '
                '-DVX_CFG_L2_NUM_BANKS=1 -DVX_CFG_L2_BANK_HASH=1 -DVX_CFG_L2_MEM_PORTS=0 '
                '-DVX_CFG_L3_SIZE=2097152 -DVX_CFG_L3_NUM_WAYS=8 -DVX_CFG_L3_WRITEBACK=0 '
                '-DVX_CFG_L3_DIRTYBYTES=0 -DVX_CFG_L3_LAZY_FETCH=0 -DVX_CFG_L3_REPL_POLICY=1 '
                '-DVX_CFG_L3_MSHR_SIZE=16 -DVX_CFG_L3_LATENCY=4 -DVX_CFG_L3_MRSQ_SIZE=4 '
                '-DVX_CFG_L3_MREQ_SIZE=0 -DVX_CFG_L3_CRSQ_SIZE=0 -DVX_CFG_L3_NUM_BANKS=1 '
                '-DVX_CFG_L3_MEM_PORTS=0 -DVX_CFG_LMEM_NUM_BANKS=4 -DVX_CFG_LMEM_LOG_SIZE=14 '
                '-DVX_CFG_LMEM_SIZE=16384 -DVX_CFG_TCU_TYPE=TFR -DVX_CFG_NUM_TCU_LANES=4 '
                '-DVX_CFG_NUM_TCU_BLOCKS=1 -DVX_CFG_TCU_USE_DSP=0 -DVX_CFG_TCU_LATENCY=4 '
                '-DVX_CFG_TCU_PE_RATIO=1 -DVX_CFG_TCU_TF32_ENABLED=0 -DVX_CFG_TCU_FP16_ENABLE '
                '-DVX_CFG_TCU_FP16_ENABLED=1 -DVX_CFG_TCU_FP8_ENABLED=0 -DVX_CFG_TCU_FP4_ENABLED=0 '
                '-DVX_CFG_TCU_INT8_ENABLED=0 -DVX_CFG_TCU_INT4_ENABLED=0 -DVX_CFG_TCU_MX_ENABLED=0 '
                '-DVX_CFG_TCU_MXFP4_ENABLED=0 -DVX_CFG_TCU_NVFP4_ENABLED=0 '
                '-DVX_CFG_TCU_SPARSE_ENABLED=0 -DVX_CFG_TCU_DSM_ENABLED=0 '
                '-DVX_CFG_TCU_WGMMA_ENABLED=0 -DVX_CFG_NUM_DXA_CORES=1 -DVX_CFG_DXA_MEM_PORTS=1 '
                '-DVX_CFG_DXA_QUEUE_SIZE=16 -DVX_CFG_DXA_MAX_INFLIGHT=8 -DVX_CFG_NUM_RTU_CORES=1 '
                '-DVX_CFG_RTU_BVH_WIDTH=4 -DVX_CFG_RTU_TLAS_ENABLED=0 -DVX_CFG_RTU_STACK_DEPTH=16 '
                '-DVX_CFG_RTU_RECIP_DSP_SEED=0 -DVX_CFG_RTU_USE_DSP=0 -DVX_CFG_RTU_FDIV_LATENCY=17 '
                '-DVX_CFG_RTU_NUM_SLOTS=1 -DVX_CFG_RTU_NUM_CTX=4 -DVX_CFG_RTU_MERGE_DEPTH=0 '
                '-DVX_CFG_NUM_RTU_BLOCKS=2 -DVX_CFG_NUM_TEX_CORES=1 -DVX_CFG_TEX_REQ_QUEUE_SIZE=8 '
                '-DVX_CFG_TEX_MEM_QUEUE_SIZE=8 -DVX_CFG_NUM_RASTER_CORES=1 '
                '-DVX_CFG_RASTER_NUM_SLICES=1 -DVX_CFG_RASTER_TILE_LOG_SIZE=5 '
                '-DVX_CFG_RASTER_BIN_LOG_SIZE=7 -DVX_CFG_RASTER_BLOCK_LOG_SIZE=2 '
                '-DVX_CFG_RASTER_MEM_FIFO_DEPTH=8 -DVX_CFG_RASTER_QUAD_FIFO_DEPTH=32 '
                '-DVX_CFG_RASTER_MEM_QUEUE_SIZE=4 -DVX_CFG_RASTER_EARLYZ_ENABLED=0 '
                '-DVX_CFG_NUM_OM_CORES=1 -DVX_CFG_OM_MEM_QUEUE_SIZE=4 -DVX_CFG_TCACHE_SIZE=8192 '
                '-DVX_CFG_TCACHE_NUM_BANKS=1 -DVX_CFG_TCACHE_NUM_WAYS=2 '
                '-DVX_CFG_TCACHE_CRSQ_SIZE=0 -DVX_CFG_TCACHE_MSHR_SIZE=16 '
                '-DVX_CFG_TCACHE_MRSQ_SIZE=0 -DVX_CFG_TCACHE_MREQ_SIZE=0 -DVX_CFG_NUM_TCACHES=1 '
                '-DVX_CFG_RCACHE_SIZE=4096 -DVX_CFG_RCACHE_NUM_BANKS=1 -DVX_CFG_RCACHE_NUM_WAYS=2 '
                '-DVX_CFG_RCACHE_CRSQ_SIZE=0 -DVX_CFG_RCACHE_MSHR_SIZE=16 '
                '-DVX_CFG_RCACHE_MRSQ_SIZE=0 -DVX_CFG_RCACHE_MREQ_SIZE=0 -DVX_CFG_NUM_RCACHES=1 '
                '-DVX_CFG_RTCACHE_SIZE=8192 -DVX_CFG_RTCACHE_NUM_BANKS=1 '
                '-DVX_CFG_RTCACHE_NUM_WAYS=2 -DVX_CFG_RTCACHE_CRSQ_SIZE=2 '
                '-DVX_CFG_RTCACHE_MSHR_SIZE=16 -DVX_CFG_RTCACHE_MREQ_SIZE=4 '
                '-DVX_CFG_RTCACHE_MRSQ_SIZE=0 -DVX_CFG_NUM_RTCACHES=1 -DVX_CFG_OCACHE_SIZE=16384 '
                '-DVX_CFG_OCACHE_NUM_BANKS=1 -DVX_CFG_OCACHE_NUM_WAYS=2 '
                '-DVX_CFG_OCACHE_CRSQ_SIZE=0 -DVX_CFG_OCACHE_MSHR_SIZE=16 '
                '-DVX_CFG_OCACHE_MRSQ_SIZE=0 -DVX_CFG_OCACHE_MREQ_SIZE=0 -DVX_CFG_NUM_OCACHES=1 '
                '-DVX_CFG_MISA_STD=9441576 -DVX_CFG_MISA_EXT=563 -DVX_DBG_STALL_TIMEOUT=100000 '
                '-DVX_DBG_DEBUG_LEVEL=3 -O2 -DNDEBUG\n'
                '@SOURCE@/third_party/softfloat/build/Linux-x86_64-GCC/softfloat.a '
                '-L@BUILD@/sw/runtime -lvortex\n',
 'header': '#define VX_CFG_L2_MSHR_SIZE 16\n'
           '#define VX_CFG_NUM_LSU_BLOCKS 1\n'
           '#define VX_CFG_SOCKET_SIZE 1\n'
           '#define VX_CFG_EXT_M_ENABLE \n'
           '#define VX_CFG_ISSUE_WIDTH 1\n'
           '#define VX_CFG_PLATFORM_MEMORY_TYPE HBM2\n'
           '#define VX_CFG_FPU_TYPE STD\n'
           '#define VX_CFG_DCACHE_READ_MERGE 1\n'
           '#define VX_CFG_EXT_ZICOND_ENABLED 1\n'
           '#define VX_CFG_L2_ENABLED 0\n'
           '#define VX_CFG_TCU_MX_ENABLED 0\n'
           '#define VX_CFG_FLEN_64 \n'
           '#define VX_CFG_L2_CRSQ_SIZE 0\n'
           '#define VX_CFG_RASTER_NUM_SLICES 1\n'
           '#define VX_CFG_L2_DIRTYBYTES VX_CFG_L2_LAZY_FETCH\n'
           '#define VX_CFG_UTLB_SIZE 8\n'
           '#define VX_CFG_L1_LINE_SIZE VX_CFG_MEM_BLOCK_SIZE\n'
           '#define VX_CFG_PLATFORM_MEMORY_PEAK_BW 460000\n'
           '#define VX_CFG_MEM_BLOCK_SIZE 64\n'
           '#define VX_CFG_MAX_BAR_EVENTS 32\n'
           '#define VX_CFG_XLEN 64\n'
           '#define VX_CFG_DCACHE_WORD_SIZE __MIN(VX_CFG_L1_LINE_SIZE, '
           '__MIN(VX_CFG_MEM_BLOCK_SIZE, ((((VX_CFG_XLEN) / (8))) * (__POW(2, '
           '((((__CLOG2(VX_CFG_NUM_LSU_LANES)) + (1))) / (2)))))))\n'
           '#define VX_CFG_NUM_RASTER_CORES __MAX(1, __UP(((VX_CFG_NUM_CORES) / (16))))\n'
           '#define VX_CFG_RTU_BVH_WIDTH 4\n'
           '#define VX_CFG_RASTER_BIN_LOG_SIZE 7\n'
           '#define VX_CFG_RTCACHE_SIZE 8192\n'
           '#define VX_CFG_L3_MREQ_SIZE 0\n'
           '#define VX_CFG_PLATFORM_MEMORY_TYPE_HBM2 \n'
           '#define VX_CFG_RCACHE_NUM_WAYS 2\n'
           '#define VX_CFG_RCACHE_MREQ_SIZE 0\n'
           '#define VX_CFG_L2_NUM_BANKS __POW(2, __CLOG2(__MIN(VX_CFG_L2_NUM_REQS, 16)))\n'
           '#define VX_CFG_TEX_MEM_QUEUE_SIZE VX_CFG_TEX_REQ_QUEUE_SIZE\n'
           '#define VX_CFG_LMEM_NUM_BANKS VX_CFG_NUM_LSU_LANES\n'
           '#define VX_CFG_NUM_TCACHES __MAX(1, __UP(((VX_CFG_NUM_TEX_CORES) / (4))))\n'
           '#define VX_CFG_ITLB_SIZE 8\n'
           '#define VX_CFG_FNCP_LATENCY 2\n'
           '#define VX_CFG_LSU_QUEUE_IN_SIZE __MAX(4, ((2) * (((VX_CFG_SIMD_WIDTH) / '
           '(VX_CFG_NUM_LSU_LANES)))))\n'
           '#define VX_CFG_FDIV_PE_RATIO 1\n'
           '#define VX_CFG_DISPATCH_QUEUE_SIZE 4\n'
           '#define VX_CFG_LSU_STACK_INTERLEAVE_ENABLED 1\n'
           '#define VX_CFG_L3_LATENCY ((4) + (__MAX(0, ((__CLOG2(VX_CFG_L3_SIZE)) - '
           '(__CLOG2(2097152))))))\n'
           '#define VX_CFG_FSQRT_PE_RATIO 1\n'
           '#define VX_CFG_PLATFORM_MEMORY_ADDR_WIDTH 48\n'
           '#define VX_CFG_LSU_LINE_SIZE __MIN(((VX_CFG_NUM_LSU_LANES) * (((VX_CFG_XLEN) / (8)))), '
           'VX_CFG_L1_LINE_SIZE)\n'
           '#define VX_CFG_DCACHE_MRSQ_SIZE 4\n'
           '#define VX_CFG_L2_TLB_LATENCY 4\n'
           '#define VX_CFG_EXT_ZACAS_ENABLED 0\n'
           '#define VX_CFG_RTU_TLAS_ENABLED 0\n'
           '#define VX_CFG_TCU_FP8_ENABLED 0\n'
           '#define VX_CFG_OCACHE_NUM_WAYS 2\n'
           '#define VX_CFG_RASTER_EARLYZ_ENABLED 0\n'
           '#define VX_CFG_EXT_M_ENABLED 1\n'
           '#define VX_CFG_NUM_RCACHES __MAX(1, __UP(((VX_CFG_NUM_RASTER_CORES) / (4))))\n'
           '#define VX_CFG_OCACHE_CRSQ_SIZE 0\n'
           '#define VX_CFG_TCU_FP4_ENABLED 0\n'
           '#define VX_CFG_IBUF_SIZE 4\n'
           '#define VX_CFG_TCACHE_MRSQ_SIZE 0\n'
           '#define VX_CFG_L2_SECTOR_SIZE VX_CFG_L1_LINE_SIZE\n'
           '#define VX_CFG_ICACHE_MEM_PORTS 1\n'
           '#define VX_CFG_TCACHE_MREQ_SIZE 0\n'
           '#define VX_CFG_NUM_THREADS 4\n'
           '#define VX_CFG_OCACHE_MREQ_SIZE 0\n'
           '#define VX_CFG_EXT_ZFHMIN_ENABLED 0\n'
           '#define VX_CFG_L2_BANK_HASH 1\n'
           '#define VX_CFG_NUM_OM_CORES __MAX(1, __UP(((VX_CFG_NUM_CORES) / (8))))\n'
           '#define VX_CFG_PTW_WALK_CACHE_SIZE 16\n'
           '#define VX_CFG_VLEN ((VX_CFG_XLEN) * (4))\n'
           '#define VX_CFG_OCACHE_MRSQ_SIZE 0\n'
           '#define VX_CFG_CP_ON_LLC (((((VX_CFG_CP_LLC_CLIENT) != (0))) && '
           '(((((((((VX_CFG_L2_ENABLED) == (1))) && (((VX_CFG_L3_ENABLED) == (0))))) && '
           '(((VX_CFG_NUM_CLUSTERS) == (1))))) || (((VX_CFG_L3_ENABLED) == (1)))))))\n'
           '#define VX_CFG_TCU_TYPE TFR\n'
           '#define VX_CFG_ICACHE_ENABLE \n'
           '#define VX_CFG_NUM_CLUSTERS 1\n'
           '#define VX_CFG_L2_TLB_SIZE 512\n'
           '#define VX_CFG_RASTER_MEM_FIFO_DEPTH 8\n'
           '#define VX_CFG_EXT_A_ENABLED 0\n'
           '#define VX_CFG_EXT_OM_ENABLED 0\n'
           '#define VX_CFG_ICACHE_READ_MERGE 1\n'
           '#define VX_CFG_TCACHE_NUM_WAYS 2\n'
           '#define VX_CFG_FETCH_WIDTH ((VX_CFG_ISSUE_WIDTH) & ((-(VX_CFG_ISSUE_WIDTH))))\n'
           '#define VX_CFG_EXT_F_ENABLE \n'
           '#define VX_CFG_L1_TLB_MSHR_SIZE 4\n'
           '#define VX_CFG_PLATFORM_MEMORY_DATA_SIZE 64\n'
           '#define VX_CFG_RTCACHE_MSHR_SIZE 16\n'
           '#define VX_CFG_ICACHE_MRSQ_SIZE 0\n'
           '#define VX_CFG_TCU_LATENCY 4\n'
           '#define VX_CFG_TCU_MXFP4_ENABLED 0\n'
           '#define VX_CFG_L2_LATENCY ((4) + (__MAX(0, ((__CLOG2(VX_CFG_L2_SIZE)) - '
           '(__CLOG2(1048576))))))\n'
           '#define VX_CFG_TCU_FP16_ENABLE \n'
           '#define VX_CFG_NUM_ALU_BLOCKS 1\n'
           '#define VX_CFG_PLATFORM_CLOCK_RATE 400\n'
           '#define VX_CFG_RTCACHE_CRSQ_SIZE 2\n'
           '#define VX_CFG_PTW_NUM_WALKERS 2\n'
           '#define VX_CFG_NUM_DCACHES __UP(((VX_CFG_SOCKET_SIZE) / (4)))\n'
           '#define VX_CFG_DXA_MEM_PORTS __MIN(VX_CFG_NUM_DXA_CORES, ((__UP(((VX_CFG_NUM_CORES) / '
           '(VX_CFG_SOCKET_SIZE)))) * (VX_CFG_L1_MEM_PORTS)))\n'
           '#define VX_CFG_NUM_SFU_BLOCKS 1\n'
           '#define VX_CFG_DCACHE_REPL_POLICY 1\n'
           '#define VX_CFG_EXT_RASTER_ENABLED 0\n'
           '#define VX_CFG_TCU_NVFP4_ENABLED 0\n'
           '#define VX_CFG_NUM_TCU_LANES VX_CFG_NUM_THREADS\n'
           '#define VX_CFG_ICACHE_ENABLED 1\n'
           '#define VX_CFG_TCACHE_SIZE 8192\n'
           '#define VX_CFG_L2_MEM_PORTS __MIN(VX_CFG_L2_NUM_REQS, '
           'VX_CFG_PLATFORM_MEMORY_NUM_BANKS)\n'
           '#define VX_CFG_RTU_FDIV_LATENCY 17\n'
           '#define VX_CFG_L2_WRITEBACK (((((((VX_CFG_L2_ENABLED) == (1))) && '
           '(((VX_CFG_L3_ENABLED) == (0))))) && (((VX_CFG_NUM_CLUSTERS) == (1)))))\n'
           '#define VX_CFG_NUM_VPU_BLOCKS 1\n'
           '#define VX_CFG_FCVT_PE_RATIO 1\n'
           '#define VX_CFG_RTCACHE_NUM_BANKS 1\n'
           '#define VX_CFG_DTLB_SIZE 16\n'
           '#define VX_CFG_ICACHE_REPL_POLICY 1\n'
           '#define VX_CFG_NUM_SFU_LANES VX_CFG_SIMD_WIDTH\n'
           '#define VX_CFG_EXT_DXA_ENABLED 0\n'
           '#define VX_CFG_EXT_C_ENABLED 0\n'
           '#define VX_CFG_L1_LINK_LATENCY 0\n'
           '#define VX_CFG_FMA_LATENCY 12\n'
           '#define VX_CFG_ICACHE_MREQ_SIZE 0\n'
           '#define VX_CFG_LMEM_LOG_SIZE __CLOG2(__MAX(16384, ((VX_CFG_LMEM_NUM_BANKS) * '
           '(2048))))\n'
           '#define VX_CFG_RTCACHE_NUM_WAYS 2\n'
           '#define VX_CFG_DCACHE_MREQ_SIZE 0\n'
           '#define VX_CFG_DCACHE_LINE_SIZE VX_CFG_L1_LINE_SIZE\n'
           '#define VX_CFG_DCACHE_ENABLED 1\n'
           '#define VX_CFG_L2_LINK_LATENCY 0\n'
           '#define VX_CFG_L2_SIZE 1048576\n'
           '#define VX_CFG_PLATFORM_MEMORY_LATENCY 0\n'
           '#define VX_CFG_LMEM_ENABLE \n'
           '#define VX_CFG_NUM_RTU_BLOCKS 2\n'
           '#define VX_CFG_L3_LINE_SIZE VX_CFG_L2_SECTOR_SIZE\n'
           '#define VX_CFG_EXT_D_ENABLED 1\n'
           '#define VX_CFG_RASTER_TILE_LOG_SIZE 5\n'
           '#define VX_CFG_PLATFORM_MEMORY_INTERLEAVE 1\n'
           '#define VX_CFG_RCACHE_CRSQ_SIZE 0\n'
           '#define VX_CFG_L2_TLB_MSHR_SIZE 8\n'
           '#define VX_CFG_FSQRT_LATENCY 32\n'
           '#define VX_CFG_NUM_RTCACHES __MAX(1, __UP(((VX_CFG_NUM_RTU_CORES) / (4))))\n'
           '#define VX_CFG_L3_NUM_WAYS 8\n'
           '#define VX_CFG_L3_MRSQ_SIZE 4\n'
           '#define VX_CFG_FLEN 64\n'
           '#define VX_CFG_RTU_MERGE_DEPTH 0\n'
           '#define VX_CFG_FCVT_LATENCY 5\n'
           '#define VX_CFG_DCACHE_LATENCY ((2) + (__MAX(0, ((__CLOG2(VX_CFG_DCACHE_SIZE)) - '
           '(__CLOG2(16384))))))\n'
           '#define VX_CFG_NUM_WARPS 4\n'
           '#define VX_CFG_L2_MRSQ_SIZE 4\n'
           '#define VX_CFG_L3_REPL_POLICY 1\n'
           '#define VX_CFG_NUM_TEX_CORES __MAX(1, __UP(((VX_CFG_NUM_CORES) / (8))))\n'
           '#define VX_CFG_VM_PINNED_REGION_SIZE 0x10000000\n'
           '#define VX_CFG_RCACHE_MSHR_SIZE 16\n'
           '#define VX_CFG_L3_SIZE 2097152\n'
           '#define VX_CFG_FPU_QUEUE_SIZE ((2) * (((VX_CFG_SIMD_WIDTH) / '
           '(VX_CFG_NUM_FPU_LANES))))\n'
           '#define VX_CFG_PLATFORM_MEMORY_NUM_BANKS 2\n'
           '#define VX_CFG_RCACHE_NUM_BANKS 1\n'
           '#define VX_CFG_L3_WRITEBACK (((VX_CFG_L3_ENABLED) == (1)))\n'
           '#define VX_CFG_L2_TLB_NUM_WAYS 4\n'
           '#define VX_CFG_DXA_QUEUE_SIZE 16\n'
           '#define VX_CFG_NUM_FPU_BLOCKS 1\n'
           '#define VX_CFG_MISA_STD '
           '((((((((((((((((((((((((((((((((((((((((((((((((((((VX_CFG_EXT_A_ENABLED) << (0))) | '
           '(((0) << (1))))) | (((VX_CFG_EXT_C_ENABLED) << (2))))) | (((VX_CFG_EXT_D_ENABLED) << '
           '(3))))) | (((0) << (4))))) | (((VX_CFG_EXT_F_ENABLED) << (5))))) | (((0) << (6))))) | '
           '(((0) << (7))))) | (((1) << (8))))) | (((0) << (9))))) | (((0) << (10))))) | (((0) << '
           '(11))))) | (((VX_CFG_EXT_M_ENABLED) << (12))))) | (((0) << (13))))) | (((0) << '
           '(14))))) | (((0) << (15))))) | (((0) << (16))))) | (((0) << (17))))) | (((0) << '
           '(18))))) | (((0) << (19))))) | (((1) << (20))))) | (((0) << (21))))) | (((0) << '
           '(22))))) | (((1) << (23))))) | (((0) << (24))))) | (((0) << (25))))\n'
           '#define VX_CFG_L3_NUM_BANKS __POW(2, __CLOG2(__MIN(VX_CFG_L3_NUM_REQS, 16)))\n'
           '#define VX_CFG_RTU_NUM_SLOTS ((VX_CFG_SOCKET_SIZE) / (VX_CFG_NUM_RTU_CORES))\n'
           '#define VX_CFG_L2_MREQ_SIZE 0\n'
           '#define VX_CFG_CP_LLC_CLIENT 1\n'
           '#define VX_CFG_DCACHE_LAZY_FETCH (((VX_CFG_DCACHE_WRITEBACK) && '
           '(((((VX_CFG_L2_ENABLED) == (0))) && (((VX_CFG_L3_ENABLED) == (0)))))))\n'
           '#define VX_CFG_TEX_REQ_QUEUE_SIZE __MAX(8, ((2) * (__UP(((VX_CFG_NUM_THREADS) / '
           '(VX_CFG_NUM_SFU_LANES))))))\n'
           '#define VX_CFG_RESET_DELAY 8\n'
           '#define VX_CFG_EXT_TEX_ENABLED 0\n'
           '#define VX_CFG_CTLB_SIZE 8\n'
           '#define VX_CFG_EXT_D_ENABLE \n'
           '#define VX_CFG_L2_NUM_WAYS 8\n'
           '#define VX_CFG_TCU_USE_DSP 0\n'
           '#define VX_CFG_L3_ENABLED 0\n'
           '#define VX_CFG_L1_MEM_PORTS __MIN(VX_CFG_DCACHE_NUM_BANKS, '
           'VX_CFG_PLATFORM_MEMORY_NUM_BANKS)\n'
           '#define VX_CFG_L2_LAZY_FETCH (((VX_CFG_L2_WRITEBACK) && (((((VX_CFG_L2_ENABLED) == '
           '(1))) && (((VX_CFG_L3_ENABLED) == (0)))))))\n'
           '#define VX_CFG_SIMD_WIDTH VX_CFG_NUM_THREADS\n'
           '#define VX_CFG_LSU_PENDING_LIMIT __CLAMP(__POW(2, '
           '__CLOG2(((((((((((VX_CFG_PLATFORM_MEMORY_PEAK_BW) / (VX_CFG_PLATFORM_CLOCK_RATE))) * '
           '(((((VX_CFG_PLATFORM_MEMORY_LATENCY) + (((2) * (VX_CFG_L2_LINK_LATENCY))))) + (((2) * '
           '(VX_CFG_L1_LINK_LATENCY))))))) + (((((((VX_CFG_NUM_CLUSTERS) * (VX_CFG_NUM_CORES))) * '
           '(VX_CFG_NUM_LSU_BLOCKS))) * (VX_CFG_LSU_LINE_SIZE))))) - (1))) / '
           '(((((((VX_CFG_NUM_CLUSTERS) * (VX_CFG_NUM_CORES))) * (VX_CFG_NUM_LSU_BLOCKS))) * '
           '(VX_CFG_LSU_LINE_SIZE)))))), 32, 256)\n'
           '#define VX_CFG_OCACHE_MSHR_SIZE 16\n'
           '#define VX_CFG_OCACHE_NUM_BANKS 1\n'
           '#define VX_CFG_DCACHE_MSHR_SIZE __CLAMP(__POW(2, '
           '__CLOG2(((((((((((VX_CFG_PLATFORM_MEMORY_PEAK_BW) / (VX_CFG_PLATFORM_CLOCK_RATE))) * '
           '(((VX_CFG_PLATFORM_MEMORY_LATENCY) + (((2) * (VX_CFG_L2_LINK_LATENCY))))))) + '
           '(((((((((VX_CFG_NUM_CLUSTERS) * (__UP(((VX_CFG_NUM_CORES) / (VX_CFG_SOCKET_SIZE)))))) '
           '* (__UP(VX_CFG_NUM_DCACHES)))) * (VX_CFG_DCACHE_NUM_BANKS))) * '
           '(VX_CFG_DCACHE_SECTOR_SIZE))))) - (1))) / (((((((((VX_CFG_NUM_CLUSTERS) * '
           '(__UP(((VX_CFG_NUM_CORES) / (VX_CFG_SOCKET_SIZE)))))) * (__UP(VX_CFG_NUM_DCACHES)))) * '
           '(VX_CFG_DCACHE_NUM_BANKS))) * (VX_CFG_DCACHE_SECTOR_SIZE)))))), 16, 64)\n'
           '#define VX_CFG_EXT_TCU_ENABLED 1\n'
           '#define VX_CFG_TCU_FP16_ENABLED 1\n'
           '#define VX_CFG_TCU_TYPE_TFR \n'
           '#define VX_CFG_LMEM_SIZE __POW(2, VX_CFG_LMEM_LOG_SIZE)\n'
           '#define VX_CFG_RASTER_MEM_QUEUE_SIZE 4\n'
           '#define VX_CFG_NUM_BARRIERS 8\n'
           '#define VX_CFG_DCACHE_CRSQ_SIZE 0\n'
           '#define VX_CFG_PLATFORM_MEMORY_DATA_RATE ((2) * (VX_CFG_PLATFORM_CLOCK_RATE))\n'
           '#define VX_CFG_ICACHE_NUM_WAYS 4\n'
           '#define VX_CFG_DCACHE_SECTOR_SIZE VX_CFG_L1_LINE_SIZE\n'
           '#define VX_CFG_L3_MSHR_SIZE 16\n'
           '#define VX_CFG_EXT_LDST_MATRIX_ENABLED 0\n'
           '#define VX_CFG_VM_ENABLED 0\n'
           '#define VX_CFG_NUM_OCACHES __MAX(1, __UP(((VX_CFG_NUM_OM_CORES) / (4))))\n'
           '#define VX_CFG_TCACHE_MSHR_SIZE 16\n'
           '#define VX_CFG_TCACHE_NUM_BANKS 1\n'
           '#define VX_CFG_DCACHE_WRITEBACK (((((((VX_CFG_L2_ENABLED) == (0))) && '
           '(((VX_CFG_L3_ENABLED) == (0))))) && (((((VX_CFG_NUM_CORES) == (1))) && '
           '(((VX_CFG_NUM_CLUSTERS) == (1)))))))\n'
           '#define VX_CFG_DCACHE_ENABLE \n'
           '#define VX_CFG_PLATFORM_MEMORY_QUEUE_SIZE 0\n'
           '#define VX_CFG_L3_CRSQ_SIZE 0\n'
           '#define VX_CFG_DCACHE_DIRTYBYTES VX_CFG_DCACHE_LAZY_FETCH\n'
           '#define VX_CFG_FPU_USE_DSP 0\n'
           '#define VX_CFG_TCACHE_CRSQ_SIZE 0\n'
           '#define VX_CFG_L2_LINE_SIZE VX_CFG_L1_LINE_SIZE\n'
           '#define VX_CFG_RTU_NUM_CTX ((VX_CFG_RTU_NUM_SLOTS) * (VX_CFG_NUM_THREADS))\n'
           '#define VX_CFG_TCU_TF32_ENABLED 0\n'
           '#define VX_CFG_ICACHE_LATENCY ((2) + (__MAX(0, ((__CLOG2(VX_CFG_ICACHE_SIZE)) - '
           '(__CLOG2(16384))))))\n'
           '#define VX_CFG_OCACHE_SIZE 16384\n'
           '#define VX_CFG_LSU_PENDING_SIZE __MIN(VX_CFG_LSU_PENDING_LIMIT, __MAX(8, ((((2) * '
           '(VX_CFG_NUM_WARPS))) * (((VX_CFG_SIMD_WIDTH) / (VX_CFG_NUM_LSU_LANES))))))\n'
           '#define VX_CFG_DCACHE_NUM_BANKS __POW(2, __CLOG2(__MIN(VX_CFG_DCACHE_NUM_REQS, 16)))\n'
           '#define VX_CFG_OM_MEM_QUEUE_SIZE 4\n'
           '#define VX_CFG_DCACHE_NUM_WAYS 4\n'
           '#define VX_CFG_MISA_EXT ((((((((((((((((((((((((((((((((VX_CFG_ICACHE_ENABLED) << '
           '(0))) | (((VX_CFG_DCACHE_ENABLED) << (1))))) | (((VX_CFG_L2_ENABLED) << (2))))) | '
           '(((VX_CFG_L3_ENABLED) << (3))))) | (((VX_CFG_LMEM_ENABLED) << (4))))) | '
           '(((VX_CFG_EXT_ZICOND_ENABLED) << (5))))) | (((VX_CFG_EXT_TCU_ENABLED) << (9))))) | '
           '(((VX_CFG_EXT_DXA_ENABLED) << (10))))) | (((VX_CFG_EXT_TEX_ENABLED) << (6))))) | '
           '(((VX_CFG_EXT_RASTER_ENABLED) << (7))))) | (((VX_CFG_EXT_OM_ENABLED) << (8))))) | '
           '(((VX_CFG_EXT_RTU_ENABLED) << (11))))) | (((VX_CFG_EXT_MUFU_ENABLED) << (12))))) | '
           '(((VX_CFG_EXT_ZFHMIN_ENABLED) << (13))))) | (((VX_CFG_EXT_LDST_WIDE_ENABLED) << '
           '(14))))) | (((VX_CFG_EXT_LDST_MATRIX_ENABLED) << (15))))\n'
           '#define VX_CFG_NUM_ICACHES __UP(((VX_CFG_SOCKET_SIZE) / (4)))\n'
           '#define VX_CFG_NUM_VGPR_BANKS 2\n'
           '#define VX_CFG_RTU_STACK_DEPTH 16\n'
           '#define VX_CFG_RASTER_BLOCK_LOG_SIZE 2\n'
           '#define VX_CFG_NUM_VPU_LANES VX_CFG_SIMD_WIDTH\n'
           '#define VX_CFG_EXT_TCU_ENABLE \n'
           '#define VX_CFG_NUM_LSU_LANES VX_CFG_SIMD_WIDTH\n'
           '#define VX_CFG_TCU_SPARSE_ENABLED 0\n'
           '#define VX_CFG_EXT_DMA_ENABLED 0\n'
           '#define VX_CFG_ICACHE_MSHR_SIZE 16\n'
           '#define VX_CFG_L3_MEM_PORTS __MIN(VX_CFG_L3_NUM_REQS, '
           'VX_CFG_PLATFORM_MEMORY_NUM_BANKS)\n'
           '#define VX_CFG_EXT_LDST_WIDE_ENABLED 0\n'
           '#define VX_CFG_DXA_MAX_INFLIGHT 8\n'
           '#define VX_CFG_RCACHE_SIZE 4096\n'
           '#define VX_CFG_DCACHE_SIZE 16384\n'
           '#define VX_CFG_AMO_RS_SIZE __MAX(VX_CFG_NUM_WARPS, __UP(((((VX_CFG_NUM_CORES) * '
           '(VX_CFG_NUM_WARPS))) / (VX_CFG_L2_NUM_BANKS))))\n'
           '#define VX_CFG_L2_REPL_POLICY 1\n'
           '#define VX_CFG_NUM_RTU_CORES __UP(((VX_CFG_SOCKET_SIZE) / (4)))\n'
           '#define VX_CFG_XLEN_64 1\n'
           '#define VX_CFG_ICACHE_CRSQ_SIZE 0\n'
           '#define VX_CFG_EXT_MUFU_ENABLED 0\n'
           '#define VX_CFG_RTU_USE_DSP 0\n'
           '#define VX_CFG_FNCP_PE_RATIO 1\n'
           '#define VX_CFG_TCU_INT8_ENABLED 0\n'
           '#define VX_CFG_LSU_STACK_INTERLEAVE_ENABLE \n'
           '#define VX_CFG_RTCACHE_MRSQ_SIZE 0\n'
           '#define VX_CFG_EXT_ZICOND_ENABLE \n'
           '#define VX_CFG_NUM_FPU_LANES VX_CFG_SIMD_WIDTH\n'
           '#define VX_CFG_EXT_RTU_ENABLED 0\n'
           '#define VX_CFG_TCU_INT4_ENABLED 0\n'
           '#define VX_CFG_LMEM_ENABLED 1\n'
           '#define VX_CFG_NUM_DXA_CORES __MAX(1, __UP(((VX_CFG_NUM_CORES) / (8))))\n'
           '#define VX_CFG_NUM_ALU_LANES VX_CFG_SIMD_WIDTH\n'
           '#define VX_CFG_DCACHE_BANK_HASH (((VX_CFG_DCACHE_NUM_BANKS) >= (4)))\n'
           '#define VX_CFG_FPU_TYPE_STD \n'
           '#define VX_CFG_L3_SECTOR_SIZE VX_CFG_L2_SECTOR_SIZE\n'
           '#define VX_CFG_RTCACHE_MREQ_SIZE 4\n'
           '#define VX_CFG_ICACHE_NUM_BANKS __POW(2, __CLOG2(VX_CFG_FETCH_WIDTH))\n'
           '#define VX_CFG_NUM_OPCS __UP(((VX_CFG_NUM_WARPS) / (((4) * (VX_CFG_ISSUE_WIDTH)))))\n'
           '#define VX_CFG_TCU_PE_RATIO 1\n'
           '#define VX_CFG_NUM_GPR_BANKS 4\n'
           '#define VX_CFG_L2_TLB_MEGA_SIZE 8\n'
           '#define VX_CFG_RASTER_QUAD_FIFO_DEPTH 32\n'
           '#define VX_CFG_L3_DIRTYBYTES VX_CFG_L3_LAZY_FETCH\n'
           '#define VX_CFG_NUM_MUFU_LANES 1\n'
           '#define VX_CFG_TCU_DSM_ENABLED 0\n'
           '#define VX_CFG_RCACHE_MRSQ_SIZE 0\n'
           '#define VX_CFG_TLB_SIZE 32\n'
           '#define VX_CFG_NUM_CORES 1\n'
           '#define VX_CFG_TCU_WGMMA_ENABLED 0\n'
           '#define VX_CFG_RTU_RECIP_DSP_SEED 0\n'
           '#define VX_CFG_DCACHE_SET_HASH 1\n'
           '#define VX_CFG_FMA_PE_RATIO 1\n'
           '#define VX_CFG_EXT_F_ENABLED 1\n'
           '#define VX_CFG_FDIV_LATENCY 32\n'
           '#define VX_CFG_NUM_TCU_BLOCKS VX_CFG_ISSUE_WIDTH\n'
           '#define VX_CFG_MEM_ADDR_WIDTH 48\n'
           '#define VX_CFG_ICACHE_SIZE 16384\n'
           '#define VX_CFG_FMA64_PE_RATIO 1\n'
           '#define VX_CFG_L3_LAZY_FETCH (((VX_CFG_L3_WRITEBACK) && (((VX_CFG_L3_ENABLED) == '
           '(1)))))\n',
 'simx_backend_missing_selectors': '-std=c++17 -Wall -Wextra -Wfatal-errors -Werror -fPIC '
                                   '-I@SOURCE@/sim/simx -I@SOURCE@/sim/simx/dxa '
                                   '-I@SOURCE@/sim/simx/tex -I@SOURCE@/sim/simx/om '
                                   '-I@SOURCE@/sim/simx/raster -I@SOURCE@/sim/simx/rtu '
                                   '-I@SOURCE@/sim/simx/kmu -I@SOURCE@/sim/simx/mem '
                                   '-I@SOURCE@/sim/simx/dtm -I@SOURCE@/sw/common '
                                   '-I@SOURCE@/sim/common -I@BUILD@/sw -I@BUILD@/hw '
                                   '-I@SOURCE@/third_party '
                                   '-I@SOURCE@/third_party/softfloat/source/include '
                                   '-I@SOURCE@/third_party/ramulator/ext/spdlog/include '
                                   '-I@SOURCE@/third_party/ramulator/ext/yaml-cpp/include '
                                   '-I@SOURCE@/third_party/ramulator/src -DVX_CFG_XLEN=64 '
                                   '-DVX_CFG_XLEN_64 -DVX_PROFILE=p02-tfr '
                                   '-DVX_CFG_EXT_LDST_MATRIX_DISABLE -DVX_CFG_EXT_TCU_ENABLE '
                                   '-DVX_CFG_FPU_TYPE=STD -DVX_CFG_ISSUE_WIDTH=1 '
                                   '-DVX_CFG_LMEM_ENABLE -DVX_CFG_NUM_ALU_BLOCKS=1 '
                                   '-DVX_CFG_NUM_CLUSTERS=1 -DVX_CFG_NUM_CORES=1 '
                                   '-DVX_CFG_NUM_FPU_BLOCKS=1 -DVX_CFG_NUM_LSU_BLOCKS=1 '
                                   '-DVX_CFG_NUM_THREADS=4 -DVX_CFG_NUM_WARPS=4 '
                                   '-DVX_CFG_TCU_DSM_DISABLE -DVX_CFG_TCU_FP16_ENABLE '
                                   '-DVX_CFG_TCU_FP4_DISABLE -DVX_CFG_TCU_FP8_DISABLE '
                                   '-DVX_CFG_TCU_INT4_DISABLE -DVX_CFG_TCU_INT8_DISABLE '
                                   '-DVX_CFG_TCU_LATENCY=4 -DVX_CFG_TCU_MXFP4_DISABLE '
                                   '-DVX_CFG_TCU_MX_DISABLE -DVX_CFG_TCU_NVFP4_DISABLE '
                                   '-DVX_CFG_TCU_PE_RATIO=1 -DVX_CFG_TCU_SPARSE_DISABLE '
                                   '-DVX_CFG_TCU_TF32_DISABLE -DVX_CFG_TCU_TYPE=TFR '
                                   '-DVX_CFG_TCU_USE_DSP=0 -DVX_CFG_TCU_WGMMA_DISABLE -DITYPE=bf16 '
                                   '-DOTYPE=fp32 -DKUNROLL=1 -I@SOURCE@/sim/simx/tcu -O2 -DNDEBUG '
                                   '-MMD -MP -MF @BUILD@/sw/runtime/simx_config.stamp\n'}


if __name__ == "__main__":
    unittest.main()

# SPDX-License-Identifier: Apache-2.0
"""Independent negative controls for the bounded WGMMA processor runner.

Processor execution boundaries are mocked. Compiler records below are synthetic
grammar fixtures constructed from the frozen manifest, not retained execution
evidence. These tests never build or launch a processor model.
"""

from contextlib import ExitStack, redirect_stderr
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

import p02_wgmma_matrix as matrix
import p02_wgmma_records as records


ROOT = Path(__file__).resolve().parents[2]
MANIFEST = json.loads((ROOT / "ci/project/p02_wgmma_matrix.json").read_text())
CASES = {case["id"]: case for case in json.loads(
    (ROOT / "ci/project/fixtures/p02_wgmma_v1.json").read_text())["cases"]}
SOURCE = Path("/wgmma-test/source")
BUILD = Path("/wgmma-test/build")
VARIANT = MANIFEST["variants"][0]
CASE = CASES[VARIANT["cases"][0]]


def arguments(*extra):
    return matrix.argument_parser().parse_args([
        "run", "--tools-dir", "/wgmma-test/tools", "--work-dir", "/wgmma-test/work",
        "--output", "/wgmma-test/output", *extra])


def output_rows(case=CASE, variant=VARIANT, *, cycles=(1000, 2011), instructions=(100, 203)):
    rows = []
    for iteration in range(2):
        identity = {"case_id": case["id"], "format": case["format"], "sparse": case["sparse"],
                    "mode": variant["mode"], "a_layout": variant["a_layout"], "iteration": iteration}
        rows.append(("P02_WGMMA_BEGIN", dict(identity, m=64, n=8, k=16, words=512)))
        rows.append(("P02_WGMMA_RESULT", dict(identity, checked=512, mismatches=0,
                    actual_bits=list(case["expected"]), expected_bits=list(case["expected"]))))
        rows.append(("PERF", f"PERF: instrs={instructions[iteration]}, cycles={cycles[iteration]}, IPC=0.100"))
    rows.append(("P02_WGMMA_PASS", {"case_id": case["id"], "iterations": 2, "checked": 1024}))
    return rows


def render(rows):
    return "\n".join(value if label == "PERF" else label + " " + json.dumps(value)
                     for label, value in rows) + "\n"


def compiler_fixture(driver="simx", variant=VARIANT, *, source=SOURCE, build=BUILD, witness=False):
    # These are transport fixtures. Actual compiler records must still be
    # retained and validated by an independently executed native run.
    flags = MANIFEST["configs"] + variant["configs"] + [
        "-DVX_CFG_TCU_TYPE_TFR=1", "-DVX_CFG_FPU_TYPE_STD=1", "-DNDEBUG=1"]
    if witness:
        flags.append("-DP02_WGMMA_WITNESS=1")
    common = "-O2 -Wall -Wextra -std=c++17 " + " ".join(flags)
    kernel = common + " -march=rv64imafd -mabi=lp64d"
    linker = "-L" + str(build / "sw/runtime") + " -lvortex"
    application = "\n".join((kernel, common, linker))
    backend = common
    if driver == "rtlsim":
        rtl = ["--language 1800-2012", "--replication-limit 65536", "--x-initial unique",
               "--x-assign unique", "--cc rtlsim_shim", "--top-module rtlsim_shim", "-j 2",
               "--exe --assert -Wall -Wpedantic -Wno-DECLFILENAME -Wno-REDEFMACRO", "verilator.vlt"]
        rtl.extend(str(source / "hw/rtl" / name) for name in (
            "VX_gpu_pkg.sv", "fpu/VX_fpu_pkg.sv", "tcu/VX_tcu_pkg.sv", "VX_trace_pkg.sv"))
        rtl.extend(flags)
        if witness:
            rtl.append(str(source / "sim/rtlsim/p02_wgmma_scoreboard_monitor.sv"))
        backend = " ".join(rtl) + "\n" + common
    return [common, backend, application]


def check_compiler(stamps, driver="simx", variant=VARIANT, *, source=SOURCE, build=BUILD, witness=False):
    return records.validate_records(*stamps, driver=driver, variant=variant, source=source,
                                    build=build, jobs=2, witness=witness)


def header_for(variant, witness=False):
    words = compiler_fixture(variant=variant, witness=witness)[0].split()
    return "\n".join("#define " + word[2:].replace("=", " ", 1)
                     for word in words if word.startswith("-D")) + (
        "\n#define VX_CFG_LMEM_SIZE __POW(2, VX_CFG_LMEM_LOG_SIZE)\n"
        "#define __POW(x,y) __vx_cfg_pow((x), (y))\n")


class SelectionAndBudgetTests(unittest.TestCase):
    def test_manifest_reproduces_and_full_inventory_is_exact(self):
        manifest, cases = matrix.load_inputs(ROOT)
        self.assertEqual(manifest, MANIFEST)
        self.assertEqual(cases, CASES)
        selected, full = matrix.select_variants(manifest, cases, arguments())
        self.assertTrue(full)
        self.assertEqual(len(selected), 12)
        self.assertEqual(sum(len(names) for _, _, names in selected), 24)
        self.assertEqual(sum(len(names) * 1024 for _, _, names in selected), 24576)
        self.assertEqual({driver for driver, _, _ in selected}, {"simx", "rtlsim"})

    def test_partial_formal_requests_reject_and_development_is_explicit(self):
        for options in (("--backend", "simx"), ("--variant", VARIANT["id"]), ("--case", CASE["id"])):
            with self.subTest(options=options), self.assertRaisesRegex(ValueError, "development"):
                matrix.select_variants(MANIFEST, CASES, arguments(*options))
            chosen, full = matrix.select_variants(MANIFEST, CASES, arguments("--development", *options))
            self.assertTrue(chosen)
            self.assertFalse(full)

    def test_duplicates_unknown_and_incompatible_selections_reject(self):
        selections = [(flag, value, flag, value) for flag, value in (
            ("--backend", "simx"), ("--variant", VARIANT["id"]), ("--case", CASE["id"]))]
        selections += [("--case", "unknown"), ("--variant", "sparse-fp16-ss", "--case", CASE["id"])]
        for options in selections:
            with self.subTest(options=options), self.assertRaises(ValueError):
                matrix.select_variants(MANIFEST, CASES, arguments("--development", *options))

    def test_witness_requires_sparse_rtl_and_selection_preserves_contract_order(self):
        with self.assertRaisesRegex(ValueError, "sparse RTL"):
            matrix.select_variants(MANIFEST, CASES, arguments("--development", "--backend", "simx", "--witness"))
        chosen, full = matrix.select_variants(MANIFEST, CASES, arguments(
            "--development", "--backend", "rtlsim", "--variant", "sparse-fp16-ss", "--witness",
            "--case", "fp16-sparse-signatures-b", "--case", "fp16-sparse-signatures-a"))
        self.assertFalse(full)
        self.assertEqual(chosen[0][2], ["fp16-sparse-signatures-a", "fp16-sparse-signatures-b"])

    def test_cli_enforces_resource_caps_and_retains_builds_by_default(self):
        for options in (("--jobs", "3"), ("--jobs", "0"), ("--timeout-seconds", "1801"),
                        ("--run-timeout-seconds", "0"), ("--iterations", "1"),
                        ("--iterations", "3"), ("--waive",), ("--backend", "xrt")):
            with self.subTest(options=options), redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                arguments(*options)
        args = arguments()
        self.assertEqual((args.jobs, args.timeout_seconds, args.run_timeout_seconds), (2, 1800, 1800))
        self.assertFalse(args.discard_builds)
        self.assertEqual(matrix.BUDGET, {"min_free_bytes": 15 * 1024 ** 3,
            "max_rss_bytes": 6 * 1024 ** 3, "max_log_bytes": 16 * 1024 ** 2})

    def test_formal_dirty_rejects_and_development_only_relaxes_dirty_blocker(self):
        value = {"checkout": {"dirty": True, "blockers": [
            "source contains tracked changes or nonignored untracked inputs"]}}
        with self.assertRaises(ValueError):
            matrix._source_ok(value, False)
        matrix._source_ok(value, True)
        value["checkout"]["blockers"].append("uninitialized submodule")
        with self.assertRaisesRegex(ValueError, "submodule"):
            matrix._source_ok(value, True)

    def test_environment_excludes_inherited_injection_and_unbounded_jobs(self):
        paths = {"work": Path("/wgmma-test/work"), "host_bin": None}
        with mock.patch.dict(os.environ, {"CONFIGS": "-Ofast", "LD_PRELOAD": "bad.so", "MAKEFLAGS": "-j99",
                                           "PYTHONPATH": "/bad", "CXXFLAGS": "-ffast-math"}):
            env = matrix.clean_environment(paths, 2)
        for name in ("CONFIGS", "LD_PRELOAD", "PYTHONPATH", "CXXFLAGS"):
            self.assertNotIn(name, env)
        self.assertEqual((env["MAKEFLAGS"], env["THREADS"], env["CMAKE_BUILD_PARALLEL_LEVEL"]), ("-j2", "2", "2"))
        self.assertEqual(env["CCACHE_DISABLE"], "1")


class OutputTests(unittest.TestCase):
    def reject(self, rows):
        with self.assertRaises((ValueError, RuntimeError)):
            records.verify_output(render(rows) if isinstance(rows, list) else rows, CASE, VARIANT)

    def test_exact_bits_digest_and_cumulative_deltas_are_independent(self):
        result = records.verify_output(render(output_rows()), CASE, VARIANT)
        self.assertEqual((result["launch_count"], result["checked_output_words"]), (2, 1024))
        self.assertEqual(result["launches"][1]["performance"], {
            "instructions": 103, "cycles": 1011, "derivation": "cumulative_delta"})
        raw = b"".join(struct.pack("<I", int(word, 16)) for word in CASE["expected"])
        self.assertEqual(result["launches"][0]["actual_bits_sha256"], hashlib.sha256(raw).hexdigest())

    def test_both_actual_and_printed_expected_bits_must_match_independent_corpus(self):
        for fields in (("actual_bits",), ("expected_bits",), ("actual_bits", "expected_bits")):
            rows = output_rows()
            for field in fields:
                rows[1][1][field][317] = "00000000"
            with self.subTest(fields=fields):
                self.reject(rows)

    def test_every_begin_result_perf_and_final_record_is_required_once(self):
        for index in range(7):
            rows = output_rows()
            del rows[index]
            with self.subTest(missing=index):
                self.reject(rows)
            if index != 5:  # One exact final cleanup performance duplicate is allowed.
                rows = output_rows()
                rows.insert(index, copy.deepcopy(rows[index]))
                with self.subTest(duplicate=index):
                    self.reject(rows)

    def test_reordering_and_mixed_fixture_or_variant_identities_reject(self):
        for pair in ((0, 1), (1, 2), (2, 3), (3, 4), (5, 6)):
            rows = output_rows()
            rows[pair[0]], rows[pair[1]] = rows[pair[1]], rows[pair[0]]
            with self.subTest(pair=pair):
                self.reject(rows)
        for key, value in (("case_id", "other"), ("format", "bf16"), ("sparse", True),
                           ("mode", "rs"), ("a_layout", "row-major"), ("iteration", 1)):
            rows = output_rows()
            rows[1][1][key] = value
            with self.subTest(key=key):
                self.reject(rows)

    def test_strict_types_dimensions_counts_and_word_encodings(self):
        mutations = [(0, "iteration", False), (0, "m", 64.0), (0, "n", 9), (0, "words", 511),
                     (1, "sparse", 0), (1, "checked", 512.0), (1, "mismatches", False),
                     (1, "mismatches", 1), (6, "checked", 1024.0), (6, "iterations", True)]
        for index, key, value in mutations:
            rows = output_rows()
            rows[index][1][key] = value
            with self.subTest(index=index, key=key, value=value):
                self.reject(rows)
        for bad in ("0000000", "FFFFFFFF", "100000000", 0, None):
            rows = output_rows()
            rows[1][1]["actual_bits"][0] = bad
            with self.subTest(word=bad):
                self.reject(rows)
        rows = output_rows()
        rows[1][1]["actual_bits"].pop()
        self.reject(rows)

    def test_duplicate_json_keys_constants_unknown_keys_and_malformed_markers(self):
        good = render(output_rows())
        candidates = [good.replace('"iteration": 0', '"iteration": 0, "iteration": 0', 1),
                      good.replace('"iteration": 0', '"iteration": NaN', 1),
                      good.replace('"iteration": 0', '"iteration": Infinity', 1),
                      good.replace('"iteration": 0', '"iteration": 0, "extra": 1', 1),
                      good.replace("P02_WGMMA_BEGIN ", "P02_WGMMA_OTHER ", 1),
                      good.replace("P02_WGMMA_BEGIN ", "prefix P02_WGMMA_BEGIN ", 1),
                      good.replace("P02_WGMMA_BEGIN ", "P02_WGMMA_BEGIN", 1),
                      good + "unexpected trailing success\n", good + "\x00"]
        for text in candidates:
            with self.subTest(prefix=text[:120]):
                self.reject(text)

    def test_cumulative_counters_must_increase_and_cannot_wrap_or_reset(self):
        for cycles, instructions in (((1000, 1000), (100, 203)), ((1000, 999), (100, 203)),
                                    ((1000, 2011), (100, 100)), ((1000, 2011), (100, 99)),
                                    ((0, 2011), (100, 203)), ((1000, 2011), (0, 203))):
            with self.subTest(cycles=cycles, instructions=instructions):
                self.reject(output_rows(cycles=cycles, instructions=instructions))

    def test_cleanup_duplicate_is_identical_final_and_at_most_one(self):
        rows = output_rows()
        rows.insert(-1, rows[-2])
        self.assertEqual(records.verify_output(render(rows), CASE, VARIANT)["cleanup_perf_duplicates"], 1)
        rows.insert(-1, rows[-2])
        self.reject(rows)
        rows = output_rows()
        rows.insert(-1, ("PERF", "PERF: instrs=203, cycles=2012, IPC=0.100"))
        self.reject(rows)
        rows = output_rows()
        rows.append(rows[-2])
        self.reject(rows)

    def test_error_diagnostics_override_complete_success_and_truncated_json_rejects(self):
        good = render(output_rows())
        for diagnostic in ("error: bad output", "FATAL: stopped", "Assertion x failed", "Segmentation fault",
                           "core dumped", "runtime error: bad", "WGMMA verification failed"):
            with self.subTest(diagnostic=diagnostic):
                self.reject(diagnostic + "\n" + good)
        self.reject(good[:good.index("P02_WGMMA_RESULT") + 80])
        self.reject(good.replace('"checked": 512', '"checked": ' + '[' * 1500 + '0' + ']' * 1500, 1))

    def test_witness_records_are_only_inside_selected_launches(self):
        rows = output_rows()
        rows.insert(1, ("P02_WGMMA_META", {"synthetic": True}))
        self.reject(rows)
        accepted = records.verify_output(render(rows), CASE, VARIANT, witness=True)
        self.assertEqual(accepted["metadata_records"], 1)
        for index in (0, 3, 7):
            rows = output_rows()
            rows.insert(index, ("P02_WGMMA_META", {"synthetic": True}))
            with self.subTest(index=index), self.assertRaises(ValueError):
                records.verify_output(render(rows), CASE, VARIANT, witness=True)

    def test_parity_exact_five_percent_uses_rtl_denominator_and_instructions_are_exact(self):
        rtl = records.verify_output(render(output_rows(cycles=(1000, 2000), instructions=(100, 200))), CASE, VARIANT)["launches"]
        for cycles, expected in ((950, "pass"), (1050, "pass"), (949, "fail"), (1051, "fail")):
            simx = records.verify_output(render(output_rows(cycles=(cycles, 2 * cycles), instructions=(100, 200))), CASE, VARIANT)["launches"]
            result = records.compare_pair(simx, rtl)
            with self.subTest(cycles=cycles):
                self.assertEqual(result["outcome"], expected)
                self.assertEqual(result["launches"][0]["cycle_relative_denominator"], "rtlsim_cycles")
        simx = copy.deepcopy(rtl)
        simx[1]["performance"]["instructions"] += 1
        self.assertEqual(records.compare_pair(simx, rtl)["outcome"], "fail")
        with self.assertRaises(ValueError):
            records.compare_pair(rtl, rtl[::-1])


class CompilerContextTests(unittest.TestCase):
    def test_resolved_boolean_flags_select_native_makefile_sources(self):
        for variant in MANIFEST["variants"]:
            flags = MANIFEST["configs"] + variant["configs"]
            resolved = subprocess.check_output([
                sys.executable, str(ROOT / "ci/gen_config.py"),
                "--config=" + str(ROOT / "VX_config.toml"),
                "--cflags=" + " ".join(flags)], text=True).split()
            required = ["-DVX_CFG_EXT_TCU_ENABLE", "-DVX_CFG_LMEM_ENABLE",
                        "-DVX_CFG_TCU_WGMMA_ENABLE", "-DVX_CFG_TCU_FP16_ENABLE",
                        "-DVX_CFG_TCU_TYPE_TFR", "-DVX_CFG_FPU_TYPE_STD"]
            if variant["sparse"]:
                required.append("-DVX_CFG_TCU_SPARSE_ENABLE")
            with self.subTest(variant=variant["id"]):
                for flag in required:
                    self.assertIn(flag, resolved)

    def test_all_six_variants_and_both_backend_record_shapes_accept(self):
        for variant in MANIFEST["variants"]:
            for driver in ("simx", "rtlsim"):
                with self.subTest(variant=variant["id"], driver=driver):
                    observed = check_compiler(compiler_fixture(driver, variant), driver, variant)
                    self.assertEqual([row["role"] for row in observed], ["runtime"] +
                        (["verilator", "backend_cpp"] if driver == "rtlsim" else ["backend_cpp"]) + ["kernel", "host"])
                    records.validate_header_macros(header_for(variant), variant)

    def test_each_context_independently_requires_frozen_geometry_arithmetic_and_mode(self):
        for driver in ("simx", "rtlsim"):
            original = compiler_fixture(driver)
            for section, line_index in ((0, 0), (1, 0), (2, 0), (2, 1)) + (((1, 1),) if driver == "rtlsim" else ()):
                for flag in ("-DVX_CFG_NUM_THREADS=8", "-DVX_CFG_TCU_TYPE=TFR", "-DITYPE=fp16",
                             "-DWGMMA_SS=1", "-DVX_CFG_TCU_SPARSE_DISABLE", "-DNDEBUG=1"):
                    stamps = original.copy()
                    lines = stamps[section].splitlines()
                    self.assertIn(flag, lines[line_index])
                    lines[line_index] = lines[line_index].replace(flag, "")
                    stamps[section] = "\n".join(lines)
                    with self.subTest(driver=driver, section=section, line=line_index, flag=flag), self.assertRaises(ValueError):
                        check_compiler(stamps, driver)

    def test_record_pooling_additional_records_and_host_runtime_rebinding_reject(self):
        original = compiler_fixture()
        variants = [[original[0] + "\n" + original[1], "", original[2]],
                    [original[0], original[1] + "\n" + original[1], original[2]],
                    [original[0], original[1], original[2].replace(str(BUILD), "/other-build")]]
        for stamps in variants:
            with self.subTest(stamps=[len(x) for x in stamps]), self.assertRaises(ValueError):
                check_compiler(stamps)
        stamps = original.copy()
        lines = stamps[2].splitlines()
        lines[0] = lines[0].replace("-mabi=lp64d", "")
        lines[1] += " -mabi=lp64d"
        stamps[2] = "\n".join(lines)
        with self.assertRaises(ValueError):
            check_compiler(stamps)

    def test_disabled_bank_zero_enable_nonnative_selectors_and_fast_math_reject(self):
        extras = ("-DVX_CFG_TCU_SPARSE_ENABLE=0", "-DVX_CFG_TCU_TYPE_DPI=0", "-DVX_CFG_FPU_TYPE_DPI=1",
                  "-DVX_CFG_TCU_FEDP2K=0", "-DWGMMA_RS=0", "-DDEBUG=0", "-DVCD_OUTPUT=0",
                  "-D__FAST_MATH__=0", "-D__FINITE_MATH_ONLY__=1", "-Ofast", "-Wp,-Ofast",
                  "-UVX_CFG_NUM_THREADS", "-Xpreprocessor -UVX_CFG_NUM_THREADS")
        for extra in extras:
            stamps = compiler_fixture()
            stamps[0] += " " + extra
            with self.subTest(extra=extra), self.assertRaises(ValueError):
                check_compiler(stamps)

    def test_shell_expansion_source_operands_and_hidden_redefinitions_reject(self):
        for extra in ("; true", "$(echo unsafe)", "`id`", "@flags.rsp", "/tmp/other.cpp",
                      "-DVX_CFG_NUM_THREADS=4", "-Wp,-DVX_CFG_NUM_THREADS=4"):
            stamps = compiler_fixture()
            stamps[0] += " " + extra
            with self.subTest(extra=extra), self.assertRaises(ValueError):
                check_compiler(stamps)

    def test_witness_source_and_all_compiler_contexts_must_agree(self):
        sparse = MANIFEST["variants"][-1]
        original = compiler_fixture("rtlsim", sparse, witness=True)
        check_compiler(original, "rtlsim", sparse, witness=True)
        monitor = str(SOURCE / "sim/rtlsim/p02_wgmma_scoreboard_monitor.sv")
        for replacement in ("", monitor + " " + monitor, "/different/monitor.sv"):
            stamps = original.copy()
            stamps[1] = stamps[1].replace(monitor, replacement)
            with self.subTest(replacement=replacement), self.assertRaises(ValueError):
                check_compiler(stamps, "rtlsim", sparse, witness=True)
        for section in range(3):
            stamps = original.copy()
            stamps[section] = stamps[section].replace("-DP02_WGMMA_WITNESS=1", "")
            with self.subTest(section=section), self.assertRaises(ValueError):
                check_compiler(stamps, "rtlsim", sparse, witness=True)
        with self.assertRaises(ValueError):
            check_compiler(original, "rtlsim", sparse, witness=False)

    def test_generated_header_duplicates_conflicts_and_wrong_variant_reject(self):
        good = header_for(VARIANT)
        for bad in (good + "#define ITYPE fp16\n", good.replace("VX_CFG_NUM_THREADS 8", "VX_CFG_NUM_THREADS 4"),
                    good.replace("ITYPE fp16", "ITYPE bf16"), good + "#define VX_CFG_TCU_FP8_ENABLE 0\n"):
            with self.subTest(ending=bad[-100:]), self.assertRaises(ValueError):
                records.validate_header_macros(bad, VARIANT)


class WorkflowTests(unittest.TestCase):
    def scenario(self, *, full=False, drift=None, drift_at=2, resource=None, result=None,
                 failed_case=1, bad_output=False, artifact_drift=False, witness=False,
                 witness_failure=False, parity_failure=False, discard=False, dirty=False,
                 copy_disk_usage=None, dependency_header_inventory=None):
        """Mock processes and platform identities; retain real parser/hash gates."""
        temporary = tempfile.TemporaryDirectory(prefix="wgmma-workflow-")
        self.addCleanup(temporary.cleanup)
        base = Path(temporary.name).resolve()
        paths = {"source": ROOT, "tools": base / "tools", "work": base / "work", "output": base / "output",
                 "host_bin": None, "verilator": base / "verilator"}
        paths["tools"].mkdir()
        variant_name = "sparse-fp16-ss" if witness else "dense-fp16-ss"
        extra = [] if full else ["--development", "--backend", "rtlsim" if witness else "simx", "--variant", variant_name]
        if witness:
            extra += ["--witness"]
        if discard:
            extra += ["--discard-builds"]
        args = arguments(*extra)
        saved_sources = set(matrix.TOOLING + matrix.CORPUS + matrix.COPIED + matrix.CONFIG_INPUTS)
        for directory in (matrix.APP, "tests/regression/sgemm_tcu_wg", "tests/regression/sgemm_tcu_wg_sp"):
            saved_sources.update(path.relative_to(ROOT).as_posix() for path in (ROOT / directory).iterdir()
                                 if path.is_file() and (path.suffix in matrix.SOURCE_SUFFIXES or path.name == "Makefile"))
        if witness:
            saved_sources.add(MANIFEST["witness"]["source"])
        source_identity = {"checkout": {"dirty": dirty, "blockers": [], "revision": "a" * 40,
            "changed_paths": [], "untracked_paths": []}, "files": matrix.hash_artifacts(ROOT, sorted(saved_sources))}
        inventory = {name: {"path": "/fake-tools/" + name, "sha256": "c" * 64} for name in
                     ("g++", "make", "clang", "riscv-gcc", "python3", "verilator", "llvm-objdump")}
        resources = {"available_memory_bytes": 8 * matrix.GIB,
                     "free_disk_bytes": {key: 20 * matrix.GIB for key in ("source", "tools", "work", "output")}}
        if resource:
            resource(resources)
        calls = {"source": 0, "tools": 0, "dependency": 0, "headers": 0, "case": 0, "budgets": []}
        real_hash = matrix.hash_artifacts

        def observe_source(_):
            calls["source"] += 1
            value = copy.deepcopy(source_identity)
            if drift == "source" and calls["source"] >= drift_at:
                value["files"][0]["sha256"] = "d" * 64
            return value

        def observe_tools(*_):
            calls["tools"] += 1
            value = copy.deepcopy(inventory)
            if drift == "tools" and calls["tools"] >= drift_at:
                value["make"]["sha256"] = "e" * 64
            return value

        def observe_headers(root):
            calls["headers"] += 1
            if dependency_header_inventory is not None:
                return dependency_header_inventory(root)
            return [{"path": "third_party/ramulator/ext/" + name + "/include/test.h",
                     "sha256": "0" * 64, "size_bytes": 1} for name in ("spdlog", "yaml-cpp")]

        def observe_hashes(root, names):
            names = tuple(names)
            if Path(root) == ROOT and names == matrix.DEPENDENCIES:
                calls["dependency"] += 1
                digest = "f" * 64 if drift == "dependency" and calls["dependency"] >= drift_at else "0" * 64
                return [{"path": name, "sha256": digest, "size_bytes": 1} for name in names]
            found = real_hash(root, names)
            if drift == "helpers" and Path(root) == ROOT and names == tuple(row["path"] for row in matrix.LOADED_HELPERS):
                found[0]["sha256"] = "1" * 64
            return found

        def execute(argv, cwd, env, log, **budget):
            calls["budgets"].append(budget)
            cwd = Path(cwd)
            name = log.stem
            log.write_text("synthetic external-command boundary\n")
            outcome = {"outcome": "pass", "exit_code": 0, "process_started": True, "cleanup_complete": True, "reason": None}
            if name.endswith("-configure"):
                for relative, contents in (("sw/VX_config.h", "cpp header\n"), ("hw/VX_config.vh", "verilog header\n")):
                    path = cwd / relative
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(contents)
                (cwd / matrix.APP).mkdir(parents=True)
            elif name.endswith("-header-reproduce"):
                path = Path(next(item.split("=", 1)[1] for item in argv if item.startswith("--output=")))
                path.write_text("cpp header\n" if path.suffix == ".h" else "verilog header\n")
            elif name.endswith("-application-build"):
                build = cwd.parents[2]
                driver = build.name.split("-", 1)[0]
                variant = next(item for item in MANIFEST["variants"] if driver + "-" + item["id"] == build.name)
                stamps = compiler_fixture(driver, variant, source=ROOT, build=build,
                                          witness=witness and driver == "rtlsim" and variant["sparse"])
                for relative, stamp in zip(("sw/runtime/" + driver + "_rt_config.stamp",
                    "sw/runtime/" + driver + "_config.stamp", matrix.APP + "/config.stamp"), stamps):
                    path = build / relative
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(stamp)
                (build / "binding.bin").write_bytes(b"stable synthetic build artifact")
            elif name.endswith("-effective-header"):
                variant = next(item for item in MANIFEST["variants"] if cwd.name.endswith("-" + item["id"]))
                log.write_text(header_for(variant, witness=witness and variant["sparse"]))
            elif any(item.startswith("OPTS=--case=") for item in argv):
                self.assertIn("--silent", argv)
                calls["case"] += 1
                case_id = next(item.split("=", 2)[2].split()[0] for item in argv if item.startswith("OPTS=--case="))
                variant = next(item for item in MANIFEST["variants"] if cwd.parents[2].name.endswith("-" + item["id"]))
                cycle = 1051 if parity_failure and cwd.parents[2].name.startswith("simx-") else 1000
                rows = output_rows(CASES[case_id], variant, cycles=(cycle, 2 * cycle), instructions=(100, 200))
                if calls["case"] == failed_case:
                    if bad_output:
                        rows[1][1]["actual_bits"][0] = "00000000"
                    if artifact_drift:
                        (cwd.parents[2] / "binding.bin").write_bytes(b"changed after execution")
                    if result is not None:
                        outcome = result
                log.write_text(render(rows))
            return outcome

        with ExitStack() as stack:
            for name, replacement in (("source_snapshot", observe_source), ("tool_inventory", observe_tools),
                                      ("dependency_headers", observe_headers),
                                      ("hash_artifacts", observe_hashes), ("_resources", lambda _: resources),
                                      ("run_bounded", execute), ("generated_identity", lambda *_: []),
                                      ("build_artifacts", lambda *_: ("sw/VX_config.h", "hw/VX_config.vh", "binding.bin"))):
                stack.enter_context(mock.patch.object(matrix, name, replacement))
            stack.enter_context(mock.patch.object(matrix.shutil, "disk_usage", side_effect=copy_disk_usage or
                (lambda _: SimpleNamespace(free=resources["free_disk_bytes"]["output"]))))
            if witness:
                stack.enter_context(mock.patch("p02_wgmma_witness.verify_witness",
                    side_effect=ValueError("synthetic missing observed wait") if witness_failure else None,
                    return_value={"outcome": "pass"}))
            report = matrix.execute_run(args, paths)
        self.assertEqual(json.loads((paths["output"] / "report.json").read_text()), report)
        self.assertEqual(report["state"], "finished")
        for key in ("acceptance_claimed", "qualifies_P02_A03", "phase_complete"):
            self.assertIs(report[key], False)
        return report, calls, paths

    def test_full_mock_workflow_exact_counts_and_enforced_command_budgets(self):
        report, calls, paths = self.scenario(full=True)
        self.assertEqual(report["outcome"], "pass", report["reason"])
        self.assertEqual((len(report["variants"]), calls["case"], report["verified_launches"],
                          report["checked_output_words"]), (12, 24, 48, 24576))
        self.assertEqual(len(report["paired_performance"]["pairs"]), 12)
        for budget in calls["budgets"]:
            self.assertLessEqual(budget["timeout_seconds"], 1800)
            for key, value in matrix.BUDGET.items():
                self.assertEqual(budget[key], value)
            self.assertEqual(set(budget["resource_paths"]), {paths[key] for key in ("source", "tools", "work", "output")})
        self.assertTrue(all(Path(item["build_dir"]).exists() for item in report["variants"]))

    def test_partial_development_is_labeled_and_has_no_implicit_parity(self):
        report, calls, _ = self.scenario()
        self.assertEqual(report["outcome"], "pass", report["reason"])
        self.assertTrue(report["development"])
        self.assertFalse(report["full_matrix_requested"])
        self.assertEqual(report["parity_outcome"], "not_run")
        self.assertEqual((calls["case"], report["verified_launches"]), (2, 4))

    def test_source_tools_dependency_drift_before_execution_or_at_final_check_fails(self):
        for kind in ("source", "tools", "dependency"):
            for when in (2, 5):
                with self.subTest(kind=kind, when=when):
                    report, calls, _ = self.scenario(drift=kind, drift_at=when)
                    self.assertEqual(report["outcome"], "fail")
                    self.assertIn("changed", report["reason"])
                    self.assertEqual(calls["case"], 0 if when == 2 else 2)

    def test_changed_loaded_helpers_or_dirty_formal_source_block_before_commands(self):
        for kwargs in ({"drift": "helpers"}, {"full": True, "dirty": True}):
            with self.subTest(kwargs=kwargs):
                report, calls, _ = self.scenario(**kwargs)
                self.assertEqual(report["outcome"], "blocked")
                self.assertEqual(report["commands"], [])
                self.assertEqual(calls["case"], 0)

    def test_low_disk_or_unavailable_memory_blocks_before_any_process(self):
        changes = [lambda r: r.__setitem__("available_memory_bytes", None),
                   lambda r: r.__setitem__("available_memory_bytes", 6 * matrix.GIB - 1)]
        changes += [lambda r, key=key: r["free_disk_bytes"].__setitem__(key, 15 * matrix.GIB - 1)
                    for key in ("source", "tools", "work", "output")]
        for change in changes:
            report, calls, _ = self.scenario(resource=change)
            self.assertEqual(report["outcome"], "blocked")
            self.assertEqual(report["commands"], [])
            self.assertEqual(calls["case"], 0)

    def test_command_failure_exit_cleanup_and_incomplete_results_fail(self):
        passing = {"outcome": "pass", "exit_code": 0, "process_started": True, "cleanup_complete": True, "reason": None}
        candidates = [dict(passing, **{key: value}) for key, value in (
            ("outcome", "fail"), ("exit_code", 4), ("process_started", False), ("cleanup_complete", False))]
        for key in ("exit_code", "process_started", "cleanup_complete"):
            value = passing.copy()
            del value[key]
            candidates.append(value)
        for value in candidates:
            with self.subTest(value=value):
                report, calls, _ = self.scenario(result=value)
                self.assertEqual(report["outcome"], "fail")
                self.assertEqual(calls["case"], 1)
                self.assertEqual(report["verified_case_executions"], 0)

    def test_second_case_failure_preserves_first_exact_observation(self):
        report, calls, _ = self.scenario(bad_output=True, failed_case=2)
        self.assertEqual(report["outcome"], "fail")
        self.assertEqual(report["arithmetic_outcome"], "fail")
        self.assertEqual((calls["case"], report["verified_case_executions"], report["checked_output_words"]), (2, 1, 1024))

    def test_artifact_drift_rejects_execution_even_with_complete_passing_log(self):
        report, calls, _ = self.scenario(artifact_drift=True)
        self.assertEqual(report["outcome"], "fail")
        self.assertIn("artifacts changed", report["reason"])
        self.assertEqual(report["verified_case_executions"], 0)

    def test_witness_failure_preserves_arithmetic_and_continues_bounded_matrix(self):
        report, calls, _ = self.scenario(witness=True, witness_failure=True)
        self.assertEqual((report["outcome"], report["arithmetic_outcome"], report["witness_outcome"]), ("fail", "pass", "fail"))
        self.assertEqual((calls["case"], report["verified_launches"], report["checked_output_words"]), (2, 4, 2048))

    def test_parity_failure_preserves_arithmetic_without_widening_tolerance(self):
        report, _, _ = self.scenario(full=True, parity_failure=True)
        self.assertEqual((report["outcome"], report["arithmetic_outcome"], report["parity_outcome"]), ("fail", "pass", "fail"))
        self.assertEqual(report["paired_performance"]["cycle_tolerance_percent"], 5)
        self.assertFalse(report["paired_performance"]["automatic_waiver"])
        self.assertEqual(report["verified_launches"], 48)

    def test_build_deletion_is_explicit_and_failed_trees_remain(self):
        report, _, _ = self.scenario(discard=True)
        self.assertEqual(report["outcome"], "pass", report["reason"])
        self.assertTrue(report["variants"][0]["build_tree_removed"])
        self.assertFalse(Path(report["variants"][0]["build_dir"]).exists())
        report, _, _ = self.scenario(discard=True, bad_output=True)
        self.assertEqual(report["outcome"], "fail")
        self.assertTrue(Path(report["variants"][0]["build_dir"]).exists())


if __name__ == "__main__":
    unittest.main()

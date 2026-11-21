# SPDX-License-Identifier: Apache-2.0
"""Real caller/observer/reader integration over fixture-copying fake C APIs.

No GPU kernel, simulator or arithmetic model runs here. The fake backend checks
the complete input/poison/argument bytes and returns the existing independent
fixture words, solely to exercise transport, ownership and result validation.
"""

import hashlib
import itertools
import json
import os
from pathlib import Path
import shlex
import shutil
import sys
import tempfile
import unittest

from baseline_process import GIB, MIB, run_bounded
from p02_wmma_fixtures import load_cases, render_header
import p06_workspace_records as records
from tensor_host_tools import run_host_command


ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "tests/regression/ai_workspace"
RUNTIME = ROOT / "sw/runtime/ai"
BACKEND = ROOT / "ci/project/fixtures/p06_workspace_caller_backend.cpp"
BINDING = "0123456789abcdef" * 4
FORMATS = ("fp16", "bf16")
POLICIES = ("per_operation", "reusable_single_tile")
SEQUENCE = ("single-dense_boundaries", "numerical-zero", "single-k03",
            "single-dense_boundaries")
WRAPPERS = ("-Wl,--wrap=vx_buffer_create", "-Wl,--wrap=vx_buffer_release",
            "-Wl,--wrap=vx_device_open", "-Wl,--wrap=vx_device_release")


class WorkspaceCallerIntegrationTests(unittest.TestCase):
    child_commands = 0

    @classmethod
    def setUpClass(cls):
        cls.compiler = shutil.which("c++") or shutil.which("g++") or shutil.which("clang++")
        cls.make = shutil.which("make")
        if not cls.compiler or not cls.make:
            raise AssertionError("Workspace caller tests require make, C++17 and UBSan")
        cls.temporary = tempfile.TemporaryDirectory(prefix="p06-workspace-caller-", dir=ROOT.parent)
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.directory = Path(cls.temporary.name)
        cls.marker = cls.directory / "forbidden-compiler-used"
        guard = cls.directory / "forbidden-compiler"
        guard.write_text('#!/bin/sh\nprintf "%s\\n" "$0" >> "$P06_CALLER_COMPILER_SENTINEL"\nexit 97\n')
        guard.chmod(0o700)
        cls.environment = {
            "PATH": str(Path(sys.executable).parent) + os.pathsep + os.environ.get("PATH", os.defpath),
            "LANG": "C", "LC_ALL": "C", "TMPDIR": str(cls.directory),
            "PYTHONDONTWRITEBYTECODE": "1", "UBSAN_OPTIONS": "halt_on_error=1:print_stacktrace=1",
            "MAKEFLAGS": "-j1", "THREADS": "1", "CCACHE_DISABLE": "1", "OBJCACHE": "",
            "P06_CALLER_COMPILER_SENTINEL": str(cls.marker),
        }
        sources = [
            Path(__file__).resolve(), BACKEND,
            ROOT / "ci/project/fixtures/p03_managed_runtime_test.cpp",
            *(APP / name for name in ("Makefile", "main.cpp", "observer.cpp", "observer.h")),
            *(RUNTIME / name for name in ("runtime.cpp", "runtime.h", "contract.cpp", "contract.h")),
            *(ROOT / "sw/common" / name for name in ("ai_matmul_args.h", "ai_matmul_profile.h")),
            ROOT / "sw/runtime/include/vortex2.h", ROOT / "tests/regression/sgemm_tcu/p02_fixtures.h",
            *(ROOT / name for name in (
                "configure", "Makefile.in", "config.mk.in", "VERSION", "VX_config.toml", "VX_types.toml",
                "profiles/p02-tfr.json", "ci/gen_config.py", "sw/runtime/common.mk",
                "sw/runtime/simx/Makefile", "sim/common.mk", "sim/simx/Makefile",
                "tests/regression/common.mk", "ci/project/tensor_host_tools.py",
                "ci/project/baseline_process.py", "ci/project/p06_workspace_records.py",
                "ci/project/p06_workspace_compiler_records.py", "ci/project/p06_workspace_contract.json",
                "ci/project/p02_wmma_fixtures.py", "ci/project/p02_fixture_oracle.py",
                "ci/project/p02_layout_fixture_oracle.py", "ci/project/p02_wmma_numerical_fixture_oracle.py",
                "ci/project/fixtures/p02_layout_v1.json",
                "ci/project/fixtures/p02_wmma_numerical_v1.json")),
        ]
        cls.identities = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in sources}
        cls.contract = records.load_contract(ROOT)
        all_cases = load_cases(ROOT)
        if (ROOT / "tests/regression/sgemm_tcu/p02_fixtures.h").read_bytes() != render_header(all_cases):
            raise AssertionError("Independent P02 fixture header did not reproduce")
        inventory = {case["id"]: case for case in all_cases}
        cls.cases = {fmt: [inventory[fmt + "-" + suffix] for suffix in SEQUENCE] for fmt in FORMATS}
        cls.generated = {}
        guard_options = [name + "=" + str(guard) for name in ("CC", "CXX", "VX_CC", "VX_CXX")]
        for fmt in FORMATS:
            build = cls.directory / fmt
            build.mkdir()
            cls.host([str(ROOT / "configure"), "--xlen=64", "--profile=p02-tfr",
                      "--osversion=ubuntu/focal", "--tooldir=" + str(cls.directory / "unused-tools")], build)
            current = dict(cls.environment, CONFIGS=f"-DITYPE={fmt} -DOTYPE=fp32 -DKUNROLL=1")
            native_runtime = build / "sw/runtime"
            for relative, target in (("sw/runtime/simx", "simx_rt_config.stamp"),
                                     ("sim/simx", "simx_config.stamp")):
                cls.host([cls.make, "--no-print-directory", "-s", "-j1", "-C", relative,
                          *guard_options, "DESTDIR=" + str(native_runtime), str(native_runtime / target)],
                         build, current)
            cls.host([cls.make, "--no-print-directory", "-s", "-j1", "--old-file=.depend",
                      "-C", "tests/regression/ai_workspace", *guard_options, "config.stamp"], build, current)
            stamp = (build / "tests/regression/ai_workspace/config.stamp").read_text()
            original = ((native_runtime / "simx_rt_config.stamp").read_text(),
                        (native_runtime / "simx_config.stamp").read_text(), stamp)
            validated = records.validate_records(*original, driver="simx", fmt=fmt,
                                                 source=ROOT, build=build, jobs=1)
            if [row["role"] for row in validated] != ["runtime", "backend_cpp", "kernel", "host"]:
                raise AssertionError("Generated workspace compiler roles differ")
            host_flags = shlex.split(stamp.splitlines()[1])
            linker_flags = shlex.split(stamp.splitlines()[2])
            if linker_flags != [*WRAPPERS, "-L" + str(native_runtime), "-lvortex"]:
                raise AssertionError("Original application wrapper/linker order changed")
            if cls.marker.exists():
                raise AssertionError("Generating compiler records invoked a forbidden compiler")
            binary = build / "caller-host-test"
            # The actual host flags come from the generated application. Only
            # host-test diagnostics/optimization are appended. Fake C APIs replace
            # -lvortex; no kernel target or simulator is compiled or executed.
            cls.host([
                cls.compiler, *host_flags, "-O1", "-g0", "-fsanitize=undefined",
                "-fno-sanitize-recover=undefined", "-pthread", "-I", str(APP),
                str(APP / "main.cpp"), str(APP / "observer.cpp"), str(RUNTIME / "runtime.cpp"),
                str(RUNTIME / "contract.cpp"), str(BACKEND), *WRAPPERS, "-o", str(binary),
            ], build, timeout=45)
            cls.generated[fmt] = {"build": build, "binary": binary, "stamps": original,
                                  "validated": validated}
        cls.modules = cls.directory / "modules"
        cls.modules.mkdir()
        for size in (0, 15, 16, 64, 16 * MIB, 16 * MIB + 1):
            with (cls.modules / str(size)).open("wb") as stream:
                stream.truncate(size)
                if size:
                    stream.write(b"\x5a")
                    stream.seek(size - 1)
                    stream.write(b"\xa5")
        cls.counter = 0
        cls.child_commands = 0

    @classmethod
    def host(cls, argv, cwd, env=None, timeout=30):
        return run_host_command(argv, cwd=cwd, env=env or cls.environment, timeout=timeout)

    def stable(self):
        for path, expected in self.identities.items():
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), expected,
                             "Caller-test source changed: " + str(path))
        self.assertFalse(self.marker.exists(), "Record generation invoked a compiler")

    def tearDown(self):
        self.stable()
        self.assertLess(sum(path.stat().st_size for path in self.directory.rglob("*") if path.is_file()),
                        64 * MIB)

    def run_caller(self, fmt, policy, *, fault="none", arguments=None, module_size=64):
        self.stable()
        type(self).counter += 1
        type(self).child_commands += 1
        number = type(self).counter
        build = self.generated[fmt]["build"]
        audit_path = build / ("caller-audit-" + str(number) + ".json")
        log_path = build / ("caller-output-" + str(number) + ".log")
        environment = dict(self.environment, P06_CALLER_TEST_FAULT=fault,
                           P06_CALLER_TEST_AUDIT=str(audit_path))
        argv = [str(self.generated[fmt]["binary"]), *(arguments if arguments is not None else (
            "--policy", policy, "--module", str(self.modules / str(module_size)),
            "--qualification-id", BINDING))]
        if any(argument == "" for argument in argv):
            # The shared bounded-process API intentionally rejects empty argv
            # elements. This fixed launcher preserves the empty CLI argument
            # for the application test without altering that runner contract.
            argv = [sys.executable, "-I", "-c",
                    "import json, os, sys; argv=json.loads(sys.argv[1]); os.execv(argv[0], argv)",
                    json.dumps(argv)]
        receipt = run_bounded(argv, build, environment, log_path,
                              timeout_seconds=10, min_free_bytes=GIB, max_log_bytes=MIB,
                              max_rss_bytes=GIB, resource_paths=(build,))
        self.assertTrue(receipt["cleanup_complete"], receipt)
        self.assertIn(receipt["exit_code"], (0, 1, 2), receipt)
        text = log_path.read_text(encoding="utf-8")
        self.assertNotIn("runtime error:", text)
        self.assertTrue(audit_path.is_file(), text[-2048:])
        audit = json.loads(audit_path.read_text())
        self.assertEqual(audit["scope"], "host-fixture-transport-only")
        for name in ("devices", "modules", "kernels", "queues", "events", "buffers", "premature"):
            self.assertEqual(audit[name], 0, (name, audit, text[-1024:]))
        self.stable()
        return receipt, text, audit

    def verified(self, text, fmt, policy):
        return records.verify_output(text, cases=self.cases[fmt], fmt=fmt, policy=policy,
                                     binding_id=BINDING, contract=self.contract)

    def assert_success(self, fmt, policy, *, fault="none", module_size=64, arguments=None):
        receipt, text, audit = self.run_caller(fmt, policy, fault=fault,
                                              module_size=module_size, arguments=arguments)
        self.assertEqual(receipt["exit_code"], 0, text[-4096:])
        self.assertEqual(receipt["outcome"], "pass", receipt)
        rows = self.verified(text, fmt, policy)
        self.assertEqual(len(rows["operations"]), 4)
        self.assertEqual(audit["cases"], [fmt + "-" + suffix for suffix in SEQUENCE])
        self.assertEqual(audit["native_opens"], 1)
        self.assertEqual(audit["native_releases"], 1)
        self.assertEqual(audit["launches"], 4)
        self.assertEqual(audit["input_checks"], 8)
        self.assertEqual(audit["poison_checks"], 4)
        self.assertEqual(audit["writes"], 12)
        expected = 3 if policy == "reusable_single_tile" else 12
        self.assertEqual(audit["buffer_creates"], expected)
        self.assertEqual(audit["buffer_releases"], expected)
        self.assertEqual(rows["summary"]["counts"]["peak_requested_payload_bytes"], 320)
        first, last = rows["operations"][0], rows["operations"][-1]
        self.assertEqual(first["actual_bits"], last["actual_bits"])
        self.assertNotEqual(first["poison"], last["poison"])
        for record in rows["operations"]:
            self.assertEqual(len(bytes.fromhex(record["dispatch"]["argument_bytes"])), 56)
        return rows

    def assert_fault(self, fmt, policy, name):
        receipt, text, audit = self.run_caller(fmt, policy, fault=name)
        self.assertEqual(receipt["exit_code"], 1, (name, text[-4096:]))
        self.assertNotIn("PASSED!", text)
        self.assertEqual(text.splitlines()[-1], "FAILED workspace correctness, exit=1",
                         "Failure diagnostics must follow the fully flushed JSON records")
        with self.assertRaises(ValueError):
            self.verified(text, fmt, policy)
        # Ignore the observed exit/FAILED marker and forge only the claimed
        # success booleans. The original failed observations must still reject.
        claimed = []
        for line in text.splitlines():
            if line.startswith(("P06_WORKSPACE_RESULT ", "P06_WORKSPACE_SUMMARY ")):
                prefix, encoded = line.split(" ", 1)
                value = json.loads(encoded)
                value["passed"] = True
                claimed.append(prefix + " " + json.dumps(value))
        self.assertTrue(claimed, text)
        with self.assertRaises(ValueError):
            self.verified("\n".join([*claimed, "PASSED!", ""]), fmt, policy)
        return text, audit

    def test_generated_flags_and_real_caller_observer_reader_cover_both_formats_and_policies(self):
        for fmt, policy in itertools.product(FORMATS, POLICIES):
            with self.subTest(fmt=fmt, policy=policy):
                self.assert_success(fmt, policy)

    def test_requested_payload_is_distinct_from_reconciled_rounded_allocator_cost(self):
        for fmt, policy in itertools.product(FORMATS, POLICIES):
            with self.subTest(fmt=fmt, policy=policy):
                rows = self.assert_success(fmt, policy, fault="rounded")
                for buffer in rows["summary"]["buffers"]:
                    self.assertEqual(buffer["create_after"]["used_bytes"]
                                     - buffer["create_before"]["used_bytes"], 256)
                    self.assertEqual(buffer["release_before"]["used_bytes"]
                                     - buffer["release_after"]["used_bytes"], 256)

    def test_recycled_default_addresses_remain_distinct_closed_allocation_lifetimes(self):
        for fmt in FORMATS:
            with self.subTest(fmt=fmt):
                rows = self.assert_success(fmt, "per_operation", fault="reuse_addresses")
                addresses = [[row["dispatch"][name] for name in ("a_address", "b_address", "d_address")]
                             for row in rows["operations"]]
                self.assertEqual(addresses, [addresses[0]] * 4)
                self.assertEqual(len(rows["summary"]["buffers"]), 12)

    def test_live_memory_undercharging_lingering_charge_and_capacity_drift_cannot_pass(self):
        for fmt, policy, name in itertools.product(FORMATS, POLICIES,
                ("allocation_charge", "lingering_charge", "capacity_drift", "memory_failure")):
            with self.subTest(fmt=fmt, policy=policy, fault=name):
                self.assert_fault(fmt, policy, name)

    def test_reported_release_failure_remains_failed_after_actual_host_cleanup(self):
        for fmt, policy in itertools.product(FORMATS, POLICIES):
            with self.subTest(fmt=fmt, policy=policy):
                text, _ = self.assert_fault(fmt, policy, "failed_release")
                self.assertIn('"cleanup":3', text)  # VX_ERR_INVALID_VALUE from the fake release.

    def test_surplus_native_device_open_and_premature_buffer_release_are_observed(self):
        for fmt, policy, name in itertools.product(FORMATS, POLICIES,
                                                  ("second_open", "premature_release")):
            with self.subTest(fmt=fmt, policy=policy, fault=name):
                text, audit = self.assert_fault(fmt, policy, name)
                if name == "second_open":
                    self.assertEqual(audit["native_opens"], 2)
                    self.assertEqual(audit["native_releases"], 2)
                else:
                    self.assertIn('"premature_releases":1', text)

    def test_changed_word_and_stale_prior_output_cannot_pass_independent_fixture_comparison(self):
        for fmt, policy, name in itertools.product(FORMATS, POLICIES,
                                                  ("altered_output", "stale_output")):
            with self.subTest(fmt=fmt, policy=policy, fault=name):
                _, audit = self.assert_fault(fmt, policy, name)
                self.assertEqual(audit["launches"], 1 if name == "altered_output" else 2)

    def test_setup_address_and_partial_submission_failures_do_not_emit_success(self):
        for fmt, policy, name in itertools.product(FORMATS, POLICIES,
                                                  ("module_failure", "bad_address", "partial_enqueue")):
            with self.subTest(fmt=fmt, policy=policy, fault=name):
                self.assert_fault(fmt, policy, name)

    def test_module_minimum_and_maximum_sizes_are_read_with_exact_cli_order_independence(self):
        for fmt, policy, size in itertools.product(FORMATS, POLICIES, (16, 16 * MIB)):
            with self.subTest(fmt=fmt, policy=policy, size=size):
                self.assert_success(fmt, policy, arguments=[
                    "--qualification-id", BINDING, "--module", str(self.modules / str(size)),
                    "--policy", policy])

    def test_invalid_cli_is_rejected_before_any_native_open(self):
        original = ["--policy", POLICIES[0], "--module", str(self.modules / "64"),
                    "--qualification-id", BINDING]
        variants = [[], original[:-1], original + ["extra"],
                    ["--policy", "unknown", *original[2:]],
                    ["--policy", "", *original[2:]],
                    ["--format", "fp16", *original[2:]],
                    [*original[:2], "--policy", "per_operation", *original[4:]],
                    [*original[:4], "--qualification-id", "a" * 63],
                    [*original[:4], "--qualification-id", "a" * 65],
                    [*original[:4], "--qualification-id", "g" * 64],
                    [*original[:4], "--qualification-id", 'a' * 63 + '"']]
        for fmt, arguments in itertools.product(FORMATS, variants):
            with self.subTest(fmt=fmt, arguments=arguments):
                receipt, text, audit = self.run_caller(fmt, POLICIES[0], arguments=arguments)
                self.assertEqual(receipt["exit_code"], 2)
                self.assertNotIn("PASSED!", text)
                self.assertEqual(audit["native_opens"], 0)
                self.assertEqual(audit["buffer_creates"], 0)

    def test_missing_short_directory_and_oversized_module_inputs_reject_before_native_open(self):
        for fmt, module in itertools.product(FORMATS, (
                self.modules / "missing", self.modules, self.modules / "0",
                self.modules / "15", self.modules / str(16 * MIB + 1))):
            with self.subTest(fmt=fmt, module=module):
                receipt, text, audit = self.run_caller(fmt, POLICIES[0], arguments=[
                    "--policy", POLICIES[0], "--module", str(module), "--qualification-id", BINDING])
                self.assertEqual(receipt["exit_code"], 2)
                self.assertNotIn("PASSED!", text)
                self.assertEqual(audit["native_opens"], 0)
                self.assertEqual(audit["buffer_creates"], 0)

# SPDX-License-Identifier: Apache-2.0
"""Warm caller/observer/reader integration over fixture-copying fake C APIs.

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
import p06_warm_contract as manifest
import p06_warm_records as records
from p06_warm_compiler_records import validate_records
from tensor_host_tools import run_host_command


ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "tests/regression/ai_warm_workspace"
RUNTIME = ROOT / "sw/runtime/ai"
BACKEND = ROOT / "ci/project/fixtures/p06_warm_caller_backend.cpp"
BINDING = "0123456789abcdef" * 4
FORMATS = ("fp16", "bf16")
POLICIES = ("per_operation", "reusable_single_tile")
WRAPPERS = ("-Wl,--wrap=vx_buffer_create", "-Wl,--wrap=vx_buffer_release",
            "-Wl,--wrap=vx_device_open", "-Wl,--wrap=vx_device_release")


class WarmCallerIntegrationTests(unittest.TestCase):
    child_commands = 0

    @classmethod
    def setUpClass(cls):
        cls.compiler = shutil.which("c++") or shutil.which("g++") or shutil.which("clang++")
        cls.make = shutil.which("make")
        if not cls.compiler or not cls.make:
            raise AssertionError("Warm caller tests require make, C++17 and UBSan")
        cls.temporary = tempfile.TemporaryDirectory(prefix="p06-warm-caller-", dir=ROOT.parent)
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.directory = Path(cls.temporary.name)
        cls.marker = cls.directory / "forbidden-compiler-used"
        guard = cls.directory / "forbidden-compiler"
        guard.write_text('#!/bin/sh\nprintf "%s\\n" "$0" >> "$P06_WARM_CALLER_COMPILER_SENTINEL"\nexit 97\n')
        guard.chmod(0o700)
        cls.environment = {
            "PATH": str(Path(sys.executable).parent) + os.pathsep + os.environ.get("PATH", os.defpath),
            "LANG": "C", "LC_ALL": "C", "TMPDIR": str(cls.directory),
            "PYTHONDONTWRITEBYTECODE": "1", "UBSAN_OPTIONS": "halt_on_error=1:print_stacktrace=1",
            "MAKEFLAGS": "-j1", "THREADS": "1", "CCACHE_DISABLE": "1", "OBJCACHE": "",
            "P06_WARM_CALLER_COMPILER_SENTINEL": str(cls.marker),
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
                "ci/project/baseline_process.py", "ci/project/p06_workspace_records.py", "ci/project/p06_records.py",
                "ci/project/p06_warm_records.py", "ci/project/p06_warm_contract.py",
                "ci/project/p06_warm_contract.json", "ci/project/p06_warm_compiler_records.py",
                "tests/regression/ai_bench_common/counters.h",
                "ci/project/p06_workspace_compiler_records.py", "ci/project/p06_workspace_contract.json",
                "ci/project/p02_wmma_fixtures.py", "ci/project/p02_fixture_oracle.py",
                "ci/project/p02_layout_fixture_oracle.py", "ci/project/p02_wmma_numerical_fixture_oracle.py",
                "ci/project/fixtures/p02_layout_v1.json",
                "ci/project/fixtures/p02_wmma_numerical_v1.json")),
        ]
        cls.identities = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in sources}
        cls.contract = manifest.load_contract(ROOT)
        all_cases = load_cases(ROOT)
        if (ROOT / "tests/regression/sgemm_tcu/p02_fixtures.h").read_bytes() != render_header(all_cases):
            raise AssertionError("Independent P02 fixture header did not reproduce")
        inventory = {case["id"]: case for case in all_cases}
        cls.cases = {fmt: inventory[fmt + "-single-dense_boundaries"] for fmt in FORMATS}
        cls.generated = {}
        guard_options = [name + "=" + str(guard) for name in ("CC", "CXX", "VX_CC", "VX_CXX")]
        for fmt in FORMATS:
            build = cls.directory / fmt
            build.mkdir()
            cls.host([str(ROOT / "configure"), "--xlen=64", "--profile=p02-tfr",
                      "--osversion=ubuntu/focal", "--tooldir=" + str(cls.directory / "unused-tools")], build)
            current = dict(cls.environment, CONFIGS=f"-DITYPE={fmt} -DOTYPE=fp32 -DKUNROLL=1",
                           PERF="1")
            native_runtime = build / "sw/runtime"
            for relative, target in (("sw/runtime/simx", "simx_rt_config.stamp"),
                                     ("sim/simx", "simx_config.stamp")):
                cls.host([cls.make, "--no-print-directory", "-s", "-j1", "-C", relative,
                          *guard_options, "DESTDIR=" + str(native_runtime), str(native_runtime / target)],
                         build, current)
            cls.host([cls.make, "--no-print-directory", "-s", "-j1", "--old-file=.depend",
                      "-C", "tests/regression/ai_warm_workspace", *guard_options, "config.stamp"], build, current)
            stamp = (build / "tests/regression/ai_warm_workspace/config.stamp").read_text()
            original = ((native_runtime / "simx_rt_config.stamp").read_text(),
                        (native_runtime / "simx_config.stamp").read_text(), stamp)
            validated = validate_records(*original, driver="simx", fmt=fmt,
                                         source=ROOT, build=build, jobs=1)
            if [row["role"] for row in validated] != ["runtime", "backend_cpp", "kernel", "host"]:
                raise AssertionError("Generated warm compiler roles differ")
            if "-DPERF_ENABLE" not in original[1]:
                raise AssertionError("Generated backend does not enable performance counters")
            if any("-DPERF_ENABLE" in text for text in (original[0], original[2])):
                raise AssertionError("Performance counters leaked into runtime/kernel/host flags")
            host_flags = shlex.split(stamp.splitlines()[1])
            if "-std=c++17" not in host_flags:
                raise AssertionError("Generated host flags do not select C++17")
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
                cls.compiler, *host_flags, "-Werror", "-O1", "-g0", "-fsanitize=undefined",
                "-fno-sanitize-recover=undefined", "-pthread", "-I", str(APP),
                str(APP / "main.cpp"), str(APP / "observer.cpp"), str(RUNTIME / "runtime.cpp"),
                str(RUNTIME / "contract.cpp"), str(BACKEND), *WRAPPERS, "-o", str(binary),
            ], build, timeout=60)
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
                             "Warm caller-test source changed: " + str(path))
        self.assertFalse(self.marker.exists(), "Record generation invoked a compiler")

    def tearDown(self):
        self.stable()
        self.assertLess(sum(path.stat().st_size for path in self.directory.rglob("*") if path.is_file()),
                        64 * MIB)

    def arguments(self, fmt, policy, *, pair_index=1, module_size=64):
        return ["--policy", policy, "--module", str(self.modules / str(module_size)),
                "--qualification-id", BINDING,
                "--sample-id", f"warm-simx-{fmt}-pair{pair_index}-{policy}",
                "--pair-index", str(pair_index),
                "--phase", "warmup" if pair_index == 0 else "measured"]

    def run_caller(self, fmt, policy, *, fault="none", arguments=None, pair_index=1, module_size=64):
        self.stable()
        type(self).counter += 1
        type(self).child_commands += 1
        number = type(self).counter
        build = self.generated[fmt]["build"]
        audit_path = build / ("caller-audit-" + str(number) + ".json")
        log_path = build / ("caller-output-" + str(number) + ".log")
        environment = dict(self.environment, P06_WARM_CALLER_TEST_FAULT=fault,
                           P06_WARM_CALLER_TEST_AUDIT=str(audit_path))
        selected = arguments if arguments is not None else self.arguments(
            fmt, policy, pair_index=pair_index, module_size=module_size)
        argv = [str(self.generated[fmt]["binary"]), *selected]
        if any(argument == "" for argument in argv):
            # Preserve empty application arguments without changing the bounded
            # process runner's prohibition on empty argv elements.
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

    def verified(self, text, fmt, policy, pair_index=1):
        return records.verify_output(text, case=self.cases[fmt], fmt=fmt, policy=policy,
                                     binding_id=BINDING,
                                     sample_id=f"warm-simx-{fmt}-pair{pair_index}-{policy}",
                                     pair_index=pair_index,
                                     phase="warmup" if pair_index == 0 else "measured",
                                     contract=self.contract)

    def assert_success(self, fmt, policy, *, fault="none", pair_index=1,
                       module_size=64, arguments=None):
        receipt, text, audit = self.run_caller(fmt, policy, fault=fault, pair_index=pair_index,
                                              module_size=module_size, arguments=arguments)
        self.assertEqual(receipt["exit_code"], 0, text[-4096:])
        self.assertEqual(receipt["outcome"], "pass", receipt)
        rows = self.verified(text, fmt, policy, pair_index)
        self.assertEqual(len(rows["operations"]), 33)
        self.assertEqual(len(rows["timed_operation_durations_ns"]), 32)
        self.assertEqual(audit["cases"], [fmt + "-single-dense_boundaries"] * 33)
        self.assertEqual(audit["native_opens"], 1)
        self.assertEqual(audit["native_releases"], 1)
        self.assertEqual(audit["launches"], 33)
        self.assertEqual(audit["input_checks"], 66)
        self.assertEqual(audit["poison_checks"], 33)
        self.assertEqual(audit["writes"], 99)
        self.assertEqual(audit["counter_queries"], 4 * 33)
        self.assertEqual(audit["memory_queries"], 5)
        expected = 3 if policy == "reusable_single_tile" else 99
        self.assertEqual(audit["buffer_creates"], expected)
        self.assertEqual(audit["buffer_releases"], expected)
        self.assertEqual(rows["summary"]["checked"], 1056)
        self.assertEqual(rows["summary"]["counts"]["peak_requested_payload_bytes"], 320)
        for index, record in enumerate(rows["operations"]):
            self.assertEqual(record["poison"], manifest.poison_for(index))
            self.assertEqual(record["actual_bits"], self.cases[fmt]["expected"])
            self.assertEqual(len(bytes.fromhex(record["dispatch"]["argument_bytes"])), 56)
        for snapshot in rows["summary"]["snapshots"].values():
            unavailable = [item for item in snapshot["counters"] if not item["enabled"]]
            self.assertEqual(len(unavailable), 12)
            self.assertTrue(all(item["status"] is None and item["value"] is None
                                for item in unavailable))
        deltas = {row["name"]: row["value"] for row in rows["counter_deltas"]}
        self.assertEqual(deltas["cycles"], 320)
        self.assertEqual(deltas["instructions"], 640)
        self.assertFalse(rows["performance_acceptance"])
        self.assertFalse(rows["phase_acceptance"])
        return rows

    def assert_fault(self, fmt, policy, name):
        receipt, text, audit = self.run_caller(fmt, policy, fault=name)
        self.assertEqual(receipt["exit_code"], 1, (name, text[-4096:]))
        self.assertNotIn("PASSED!", text)
        self.assertIn("P06_WARM_FAILURE ", text)
        with self.assertRaises(ValueError):
            self.verified(text, fmt, policy)
        return text, audit

    def test_generated_perf_flags_and_real_caller_observer_reader_cover_complete_identity_plan(self):
        for row in manifest.process_plan(self.contract):
            with self.subTest(fmt=row["format"], policy=row["policy"], pair=row["pair_index"]):
                self.assert_success(row["format"], row["policy"], pair_index=row["pair_index"])

    def test_rounded_native_memory_cost_is_distinct_from_requested_payload(self):
        for fmt, policy in itertools.product(FORMATS, POLICIES):
            with self.subTest(fmt=fmt, policy=policy):
                rows = self.assert_success(fmt, policy, fault="rounded")
                memory = rows["summary"]["memory"]
                expected = 640 + (768 if policy == "reusable_single_tile" else 0)
                self.assertEqual(memory["after_create"]["used_bytes"], expected)
                self.assertEqual(memory["before_release"]["used_bytes"], 0)

    def test_recycled_default_addresses_preserve_33_distinct_closed_lifetimes(self):
        for fmt in FORMATS:
            with self.subTest(fmt=fmt):
                rows = self.assert_success(fmt, "per_operation", fault="reuse_addresses")
                addresses = [[row["dispatch"][key] for key in ("a_address", "b_address", "d_address")]
                             for row in rows["operations"]]
                self.assertEqual(addresses, [addresses[0]] * 33)

    def test_first_last_and_unwritten_poison_output_cannot_pass_exact_comparison(self):
        for fmt, policy, name in itertools.product(FORMATS, POLICIES,
                                                   ("altered_prime", "altered_last", "left_poison")):
            with self.subTest(fmt=fmt, policy=policy, fault=name):
                text, audit = self.assert_fault(fmt, policy, name)
                expected = {"altered_prime": 1, "altered_last": 33, "left_poison": 2}[name]
                self.assertEqual(audit["launches"], expected)
                self.assertIn('"mismatches":' + ("32" if name == "left_poison" else "1"), text)

    def test_timeout_partial_enqueue_and_asynchronous_failure_clean_up_without_success(self):
        for fmt, policy, name in itertools.product(FORMATS, POLICIES,
                                                   ("timeout", "partial_enqueue", "async_failure")):
            with self.subTest(fmt=fmt, policy=policy, fault=name):
                text, audit = self.assert_fault(fmt, policy, name)
                self.assertEqual(audit["launches"], 1 if name == "timeout" else 0)
                if name == "timeout":
                    self.assertIn('"timed_out_waits":1', text)

    def test_setup_address_and_reported_cleanup_failures_remain_failed_after_host_cleanup(self):
        for fmt, policy, name in itertools.product(FORMATS, POLICIES,
                ("module_failure", "bad_address", "failed_release", "device_release_failure")):
            with self.subTest(fmt=fmt, policy=policy, fault=name):
                self.assert_fault(fmt, policy, name)

    def test_failed_empty_and_decreasing_counter_observations_cannot_pass(self):
        for fmt, policy, name in itertools.product(FORMATS, POLICIES,
                ("capability_failure", "counter_failure", "zero_cycles", "counter_decrease")):
            with self.subTest(fmt=fmt, policy=policy, fault=name):
                self.assert_fault(fmt, policy, name)

    def test_failed_memory_queries_capacity_drift_and_lingering_charge_cannot_pass(self):
        for fmt, policy, name in itertools.product(FORMATS, POLICIES,
                ("memory_failure", "capacity_drift", "lingering_charge")):
            with self.subTest(fmt=fmt, policy=policy, fault=name):
                self.assert_fault(fmt, policy, name)

    def test_module_size_boundaries_and_cli_option_order_are_supported(self):
        for fmt, policy, size in itertools.product(FORMATS, POLICIES, (16, 16 * MIB)):
            with self.subTest(fmt=fmt, policy=policy, size=size):
                original = self.arguments(fmt, policy, module_size=size)
                pairs = [original[index:index + 2] for index in range(0, len(original), 2)]
                self.assert_success(fmt, policy, arguments=[part for pair in reversed(pairs) for part in pair])

    def test_invalid_cli_and_cross_bound_identities_reject_before_native_open(self):
        for fmt in FORMATS:
            original = self.arguments(fmt, POLICIES[0])
            variants = [[], original[:-1], original + ["extra"],
                        [*original[:2], "--policy", POLICIES[0], *original[4:]]]
            changes = {
                "--policy": ("unknown", ""),
                "--qualification-id": ("a" * 63, "a" * 65, "g" * 64, "A" * 64, 'a' * 63 + '"'),
                "--sample-id": ("warm-simx-fp16-pair0-per_operation", "wrong",
                                 f"warm-rtlsim-{fmt}-pair1-per_operation",
                                 f"warm-simx-{fmt}-pair1-reusable_single_tile"),
                "--pair-index": ("6", "-1", "01", "1.0", "0", ""),
                "--phase": ("warmup", "other", ""),
            }
            for key, values in changes.items():
                for value in values:
                    variant = list(original)
                    variant[variant.index(key) + 1] = value
                    variants.append(variant)
            unknown = list(original)
            unknown[0] = "--format"
            variants.append(unknown)
            for arguments in variants:
                with self.subTest(fmt=fmt, arguments=arguments):
                    receipt, text, audit = self.run_caller(fmt, POLICIES[0], arguments=arguments)
                    self.assertEqual(receipt["exit_code"], 2)
                    self.assertNotIn("PASSED!", text)
                    self.assertEqual(audit["native_opens"], 0)
                    self.assertEqual(audit["buffer_creates"], 0)

    def test_missing_short_directory_and_oversized_modules_reject_before_native_open(self):
        for fmt, module in itertools.product(FORMATS, (
                self.modules / "missing", self.modules, self.modules / "0",
                self.modules / "15", self.modules / str(16 * MIB + 1))):
            with self.subTest(fmt=fmt, module=module):
                arguments = self.arguments(fmt, POLICIES[0])
                arguments[3] = str(module)
                receipt, text, audit = self.run_caller(fmt, POLICIES[0], arguments=arguments)
                self.assertEqual(receipt["exit_code"], 2)
                self.assertNotIn("PASSED!", text)
                self.assertEqual(audit["native_opens"], 0)
                self.assertEqual(audit["buffer_creates"], 0)

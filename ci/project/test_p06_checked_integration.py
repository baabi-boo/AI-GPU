# SPDX-License-Identifier: Apache-2.0
"""Bounded host checks of production SimX counter storage and aggregation.

These tests compile real model headers using freshly configured p02-tfr build
trees. They do not link or run a processor, execute a kernel, exercise model
launch resets, or establish warm-counter qualification.
"""

import os
from pathlib import Path
import shlex
import shutil
import tempfile
import unittest

from tensor_host_tools import run_host_command


ROOT = Path(__file__).resolve().parents[2]
NATIVE_FIXTURE = ROOT / "tests/unittest/checked_counters/main.cpp"

# Explicit member lists make a reversion to a scalar source counter a compile
# error. Expected behavior is exercised through the production operator+=,
# rather than a second implementation of that operator in the fixture.
STATS = {
    "core": ("Core", (
        "cycles", "instrs", "sched_idle", "active_warps", "stalled_warps",
        "issued_warps", "issued_threads", "fetch_stalls", "ibuf_stalls",
        "scrb_stalls", "opds_stalls", "alu_stalls", "fpu_stalls", "lsu_stalls",
        "sfu_stalls", "tcu_stalls", "branches", "divergence", "alu_instrs",
        "fpu_instrs", "lsu_instrs", "sfu_instrs", "tcu_instrs", "ifetches",
        "loads", "stores", "ifetch_latency", "load_latency",
    )),
    "cache": ("Cache", (
        "reads", "writes", "read_misses", "write_misses", "evictions",
        "bank_stalls", "mshr_stalls", "mem_latency",
    )),
    "local": ("LocalMem", ("reads", "writes", "bank_stalls")),
    "coalescer": ("MemCoalescer", ("misses",)),
    "memory": ("Memory", ("bank_stalls",)),
    "tensor": ("TcuUnit", ("latency", "tbuf_stalls", "tbuf_cache_hits", "lmem_reads")),
    "processor": ("ProcessorImpl", ("mem_reads", "mem_writes", "mem_latency")),
}
AGGREGATES = ("cache", "local", "coalescer", "memory", "tensor")


def fixture_source():
    declarations = []
    layout = []
    boundaries = []
    overflow = []
    for name, (model, members) in STATS.items():
        stats = "vortex::" + model + "::PerfStats"
        declarations.append(
            "constexpr std::array<PerfCounter " + stats + "::*, " + str(len(members))
            + "> " + name + "_fields = {{\n"
            + "".join("  &" + stats + "::" + member + ",\n" for member in members)
            + "}};\nstatic_assert(std::is_standard_layout_v<" + stats + ">);\n"
        )
        # Processor snapshots also contain cache/memory substructures and may
        # include VM stats, so compare their full layout between modes below.
        if name != "processor":
            declarations.append(
                "static_assert(sizeof(" + stats + ") == " + str(len(members))
                + " * sizeof(uint64_t));\n"
                + "static_assert(alignof(" + stats + ") == alignof(uint64_t));\n"
            )
        layout.append(
            'std::printf("' + name + ' %zu %zu", sizeof(' + stats + "), alignof("
            + stats + "));\n"
            + "".join('std::printf(" %zu", offsetof(' + stats + ", " + member
                      + "));\n" for member in members)
            + 'std::puts("");\n'
        )
        boundaries.append("check_storage(" + name + "_fields);\n")
        operation = "aggregate_overflow" if name in AGGREGATES else "storage_overflow"
        overflow.append(
            'if (std::strcmp(argv[2], "' + name + '") == 0) {\n'
            + "  return " + operation + "(" + name + "_fields, index);\n}\n"
        )
    boundaries.extend("check_aggregation(" + name + "_fields);\n" for name in AGGREGATES)
    return r'''
#include <array>
#include <cstddef>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <limits>
#include <type_traits>
#include "core.h"
#include "processor_impl.h"
#include "cache.h"
#include "local_mem.h"
#include "mem_coalescer.h"
#include "memory.h"
#include "tcu_unit.h"

#if !defined(PERF_ENABLE) || !defined(VX_CFG_XLEN_64) || !defined(VX_CFG_EXT_TCU_ENABLE)
#error "The host integration fixture requires RV64, PERF and TCU"
#endif
#if defined(SIMX_FUNCTIONAL) || SIMX_MT > 1
#error "The host integration fixture requires serial timing configuration"
#endif
#if !defined(VX_CFG_FPU_TYPE_STD) || !defined(VX_CFG_TCU_TYPE_TFR)
#error "The host integration fixture requires STD scalar and TFR tensor arithmetic"
#endif
static_assert(VX_CFG_XLEN == 64);
static_assert(VX_CFG_NUM_CLUSTERS == 1 && VX_CFG_NUM_CORES == 1);
static_assert(VX_CFG_NUM_WARPS == 4 && VX_CFG_NUM_THREADS == 4);
static_assert(VX_CFG_ISSUE_WIDTH == 1 && VX_CFG_NUM_LSU_BLOCKS == 1);

using vortex::PerfCounter;
#ifdef SIMX_CHECKED_COUNTERS
static_assert(!std::is_same_v<PerfCounter, uint64_t>);
#else
static_assert(std::is_same_v<PerfCounter, uint64_t>);
#endif
static_assert(sizeof(PerfCounter) == sizeof(uint64_t));
static_assert(alignof(PerfCounter) == alignof(uint64_t));

constexpr uint64_t kLowMax = 0xffffffffull;
constexpr uint64_t kCarry = 0x100000000ull;
constexpr uint64_t kMax = std::numeric_limits<uint64_t>::max();

void require(bool condition) {
  if (!condition) {
    std::fputs("FAIL: production counter integration\n", stderr);
    std::exit(2);
  }
}

#ifdef SIMX_CHECKED_COUNTERS
template <typename Operation>
void require_overflow(Operation operation) {
  bool caught = false;
  try {
    operation();
  } catch (const vortex::PerfCounterError& error) {
    caught = true;
    require(error.reason() == vortex::PerfCounterError::Reason::Overflow);
    require(std::strcmp(error.what(), "SIMX_CHECKED_COUNTER_FAILURE: overflow") == 0);
  } catch (...) {
    require(false);
  }
  require(caught);
}
#endif

template <typename Stats, std::size_t N>
void check_storage(const std::array<PerfCounter Stats::*, N>& fields) {
  Stats stats{};
  for (const auto member : fields) {
    require(uint64_t(stats.*member) == 0);
    stats.*member = kLowMax;
    ++(stats.*member);
    require(uint64_t(stats.*member) == kCarry);
  }
  const Stats snapshot = stats;
  stats = {};
  for (const auto member : fields) {
    require(uint64_t(stats.*member) == 0);
    require(uint64_t(snapshot.*member) == kCarry);
  }
}

template <typename Stats, std::size_t N>
void check_aggregation(const std::array<PerfCounter Stats::*, N>& fields) {
  Stats first{}, second{}, total{};
  for (std::size_t i = 0; i < N; ++i) {
    first.*fields[i] = kLowMax - i;
    second.*fields[i] = 2 * i + 1;
  }
  require(&(total += first) == &total);
  require(&(total += second) == &total);
  for (std::size_t i = 0; i < N; ++i) {
    require(uint64_t(total.*fields[i]) == kCarry + i);
    require(uint64_t(first.*fields[i]) == kLowMax - i);
    require(uint64_t(second.*fields[i]) == 2 * i + 1);
    first.*fields[i] = kMax - i;
    second.*fields[i] = i;
  }
  first += second;
  total = {};
  total += first;
  for (std::size_t i = 0; i < N; ++i) {
    require(uint64_t(first.*fields[i]) == kMax);
    require(uint64_t(total.*fields[i]) == kMax);
    require(uint64_t(second.*fields[i]) == i);
  }
}

template <typename Stats, std::size_t N>
int aggregate_overflow(const std::array<PerfCounter Stats::*, N>& fields,
                       std::size_t index) {
  require(index < N);
  Stats first{}, second{};
  first.*fields[index] = kMax;
  second.*fields[index] = 1;
#ifdef SIMX_CHECKED_COUNTERS
  const Stats source = second;
  require_overflow([&] { first += second; });
  require(uint64_t(first.*fields[index]) == kMax);
  for (const auto member : fields) {
    require(uint64_t(second.*member) == uint64_t(source.*member));
  }
  std::puts("PASSED: checked model aggregation rejects overflow unchanged");
#else
  first += second;
  require(uint64_t(first.*fields[index]) == 0);
  require(uint64_t(second.*fields[index]) == 1);
  std::puts("PASSED: ordinary model aggregation wraps");
#endif
  return 0;
}

template <typename Stats, std::size_t N>
int storage_overflow(const std::array<PerfCounter Stats::*, N>& fields,
                     std::size_t index) {
  require(index < N);
  Stats stats{};
  stats.*fields[index] = kMax;
#ifdef SIMX_CHECKED_COUNTERS
  const Stats snapshot = stats;
  require_overflow([&] { ++(stats.*fields[index]); });
  for (const auto member : fields) {
    require(uint64_t(stats.*member) == uint64_t(snapshot.*member));
  }
  std::puts("PASSED: checked model storage rejects overflow unchanged");
#else
  ++(stats.*fields[index]);
  require(uint64_t(stats.*fields[index]) == 0);
  std::puts("PASSED: ordinary model storage wraps");
#endif
  return 0;
}
''' + "\n".join(declarations) + r'''
int main(int argc, char** argv) {
  if (argc == 2 && std::strcmp(argv[1], "boundaries") == 0) {
''' + "".join(boundaries) + r'''
    std::puts("PASSED: production counter storage and aggregation");
    return 0;
  }
  if (argc == 2 && std::strcmp(argv[1], "layout") == 0) {
''' + "".join(layout) + r'''
    return 0;
  }
  if (argc == 4 && std::strcmp(argv[1], "overflow") == 0) {
    char* end = nullptr;
    const auto index = std::strtoul(argv[3], &end, 10);
    require(end != argv[3] && *end == '\0');
''' + "".join(overflow) + r'''
  }
  return 3;
}
'''


class CheckedCounterModelIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.compiler = shutil.which("c++") or shutil.which("g++") or shutil.which("clang++")
        cls.make = shutil.which("make")
        if cls.compiler is None or cls.make is None:
            raise AssertionError("Model-header tests require make and a C++17 compiler with UBSan")
        cls.temporary = tempfile.TemporaryDirectory(prefix="p06-counter-integration-")
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.build = Path(cls.temporary.name).resolve()
        cls.environment = {
            "PATH": os.environ.get("PATH", os.defpath), "LC_ALL": "C",
            "TMPDIR": str(cls.build), "UBSAN_OPTIONS": "halt_on_error=1:print_stacktrace=1",
            "PYTHONDONTWRITEBYTECODE": "1",
        }
        source = cls.build / "model_stats.cpp"
        source.write_text(fixture_source(), encoding="utf-8")
        flags_makefile = cls.build / "host_flags.mk"
        flags_makefile.write_text(
            ".PHONY: p06-host-flags\np06-host-flags:\n"
            "\t@$(info P06_HOST_CXXFLAGS=$(CXXFLAGS)) true\n", encoding="utf-8",
        )
        cls.binaries = {}
        cls.flags = {}
        cls.trees = {}
        cls.configuration_bodies = {}
        for mode in ("ordinary", "checked"):
            tree = cls.build / mode
            tree.mkdir()
            # This OS selector only permits host configuration generation on
            # distributions outside configure's supported toolchain platforms.
            # No toolchain is installed or selected as execution evidence.
            run_host_command([
                str(ROOT / "configure"), "--xlen=64", "--profile=p02-tfr",
                "--osversion=ubuntu/focal", "--tooldir=" + str(cls.build / "unused-tools"),
            ], cwd=tree, env=cls.environment, timeout=60)
            configs = "-DSIMX_CHECKED_COUNTERS=1" if mode == "checked" else ""
            output = run_host_command([
                cls.make, "--no-print-directory", "-s", "-f", "Makefile",
                "-f", str(flags_makefile), "p06-host-flags", "PERF=1",
                "CXX=" + cls.compiler, "CONFIGS=" + configs,
            ], cwd=tree / "sim/simx", env=cls.environment, timeout=30)
            prefix = "P06_HOST_CXXFLAGS="
            records = [line[len(prefix):] for line in output.splitlines() if line.startswith(prefix)]
            if len(records) != 1:
                raise AssertionError("Expected one resolved production CXXFLAGS record: " + output)
            flags = shlex.split(records[0])
            required = {"-O2", "-DNDEBUG", "-DPERF_ENABLE", "-DVX_CFG_XLEN=64", "-DVX_CFG_XLEN_64"}
            if not required.issubset(flags):
                raise AssertionError("Missing release/profile flags: " + repr(flags))
            if ("-DSIMX_CHECKED_COUNTERS=1" in flags) != (mode == "checked"):
                raise AssertionError("Wrong counter mode in production flags")
            flags += ["-g0", "-fsanitize=undefined", "-fno-sanitize-recover=undefined"]
            binary = tree / "model-stats"
            run_host_command([
                cls.compiler, *flags, str(source), "-o", str(binary),
            ], cwd=tree, env=cls.environment, timeout=45)
            cls.binaries[mode] = binary
            cls.flags[mode] = flags
            cls.trees[mode] = tree
            for header in (tree / "sw").glob("*.h"):
                cls.configuration_bodies[header] = header.read_bytes()

    def setUp(self):
        self.assertEqual(
            {path: path.read_bytes() for path in self.configuration_bodies},
            self.configuration_bodies, "Generated configuration changed after compilation",
        )

    def run_fixture(self, mode, *arguments):
        return run_host_command([
            str(self.binaries[mode]), *map(str, arguments),
        ], cwd=self.trees[mode], env=self.environment, timeout=10)

    def assert_model_overflow_rejected(self, name, index):
        operation = "aggregation" if name in AGGREGATES else "storage"
        self.assertEqual(
            self.run_fixture("checked", "overflow", name, index),
            "PASSED: checked model " + operation + " rejects overflow unchanged\n",
        )

    def test_real_model_storage_copy_zeroing_and_aggregate_carries(self):
        for mode in self.binaries:
            with self.subTest(mode=mode):
                self.assertEqual(
                    self.run_fixture(mode, "boundaries"),
                    "PASSED: production counter storage and aggregation\n",
                )

    def test_ordinary_and_checked_stats_have_identical_member_layout(self):
        ordinary = self.run_fixture("ordinary", "layout")
        self.assertEqual(len(ordinary.splitlines()), len(STATS))
        self.assertEqual(ordinary, self.run_fixture("checked", "layout"))

    def test_each_production_aggregate_member_rejects_overflow(self):
        for name in AGGREGATES:
            for index, member in enumerate(STATS[name][1]):
                with self.subTest(model=name, member=member):
                    self.assert_model_overflow_rejected(name, index)

    def test_core_and_processor_storage_reject_overflow(self):
        for name, member in (("core", "cycles"), ("processor", "mem_latency")):
            with self.subTest(model=name, member=member):
                self.assert_model_overflow_rejected(name, STATS[name][1].index(member))

    def test_ordinary_production_aggregation_retains_uint64_behavior(self):
        for name in AGGREGATES:
            for index, member in enumerate(STATS[name][1]):
                with self.subTest(model=name, member=member):
                    self.assertEqual(
                        self.run_fixture("ordinary", "overflow", name, index),
                        "PASSED: ordinary model aggregation wraps\n",
                    )

    def test_native_linked_harness_compiles_against_both_model_modes(self):
        # Syntax validation catches real-header/API integration errors without
        # pretending to link the missing SoftFloat/Ramulator dependencies.
        for mode in self.binaries:
            with self.subTest(mode=mode):
                run_host_command([
                    self.compiler, *self.flags[mode], "-fsyntax-only", str(NATIVE_FIXTURE),
                ], cwd=self.trees[mode], env=self.environment, timeout=45)


if __name__ == "__main__":
    unittest.main()

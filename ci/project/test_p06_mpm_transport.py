# SPDX-License-Identifier: Apache-2.0
"""Host adapter regression; extracted production code is not a full SimX run."""

import os
from pathlib import Path
import re
import shutil
import tempfile
import unittest

from tensor_host_tools import run_host_command


ROOT = Path(__file__).resolve().parents[2]
CORE = ROOT / "sim/simx/core.cpp"
CSR = ROOT / "sim/simx/csr_unit.cpp"
PERF = ROOT / "sw/runtime/common/perf.cpp"
HARNESS = ROOT / "ci/project/fixtures/p06_mpm_transport_host.cpp"


def extract_definition(source, signature):
    """Copy one complete definition verbatim, including any nested lambdas."""
    if source.count(signature) != 1:
        raise AssertionError("Expected one production definition: " + signature)
    start = source.index(signature)
    masked = re.sub(
        r'//[^\n]*|/\*.*?\*/|"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'',
        lambda match: " " * len(match.group()), source, flags=re.DOTALL,
    )
    opening = masked.index("{", start)
    depth = 0
    for offset in range(opening, len(masked)):
        if masked[offset] == "{":
            depth += 1
        elif masked[offset] == "}":
            depth -= 1
            if depth == 0:
                return source[start:offset + 1]
    raise AssertionError("Unterminated production definition: " + signature)


def production_fragments(core_source=None):
    csr_source = CSR.read_text(encoding="utf-8")
    macros = re.findall(
        r"^#ifdef VX_CFG_XLEN_64\s*\n(?=[ \t]*#define CSR_READ_64\().*?^#endif[^\n]*",
        csr_source, flags=re.MULTILINE | re.DOTALL,
    )
    if len(macros) != 1:
        raise AssertionError("Expected one XLEN-dependent production CSR_READ_64 macro")
    constants = []
    types = (ROOT / "VX_types.toml").read_text(encoding="utf-8")
    for name in (
        "VX_CSR_MPM_BASE", "VX_CSR_MPM_BASE_H", "VX_CSR_MCYCLE", "VX_CSR_MINSTRET",
        "VX_DCR_BASE_CACHE_FLUSH", "VX_DCR_BASE_MPM_VALUE",
    ):
        values = re.findall(r"^" + name + r"\s*=\s*(0x[0-9a-fA-F]+|[0-9]+)\s*(?:#.*)?$",
                            types, flags=re.MULTILINE)
        if len(values) != 1:
            raise AssertionError("Expected one literal transport constant: " + name)
        constants.append("#define " + name + " " + values[0])
    return {
        "production_constants.inc": "\n".join(constants),
        "production_csr_read.inc": macros[0],
        "production_dcr_read.inc": extract_definition(
            CORE.read_text(encoding="utf-8") if core_source is None else core_source,
            "  int dcr_read("),
        "production_mpm_query.inc": extract_definition(
            PERF.read_text(encoding="utf-8"), 'extern "C" vx_result_t vx_device_mpm_query('),
    }


class MpmTransportHostTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler = shutil.which("c++") or shutil.which("g++") or shutil.which("clang++")
        if compiler is None:
            raise AssertionError("MPM host adapter tests require a C++17 compiler with UBSan")
        cls.temporary = tempfile.TemporaryDirectory(prefix="p06-mpm-host-", dir=ROOT.parent)
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.build = Path(cls.temporary.name)
        cls.environment = {
            "PATH": os.environ.get("PATH", os.defpath), "LC_ALL": "C",
            "TMPDIR": str(cls.build), "UBSAN_OPTIONS": "halt_on_error=1:print_stacktrace=1",
        }
        cls.fragments = production_fragments()
        for name, source in cls.fragments.items():
            (cls.build / name).write_text(source + "\n", encoding="utf-8")
        cls.binaries = {}
        for xlen in (32, 64):
            binary = cls.build / ("host-adapter-rv" + str(xlen))
            run_host_command([
                compiler, "-std=c++17", "-O1", "-g0", "-Wall", "-Wextra", "-Werror",
                "-fsanitize=undefined", "-fno-sanitize-recover=undefined",
                *(["-DVX_CFG_XLEN_64"] if xlen == 64 else []),
                "-I", str(cls.build), "-I", str(ROOT / "sw/runtime/include"),
                str(HARNESS), "-o", str(binary),
            ], cwd=cls.build, env=cls.environment, timeout=45)
            cls.binaries[xlen] = binary

    def run_group(self, group):
        self.assertEqual(production_fragments(), self.fragments,
                         "Extracted production code changed after compilation")
        for xlen, binary in self.binaries.items():
            with self.subTest(xlen=xlen):
                output = run_host_command([str(binary), group], cwd=self.build,
                                          env=self.environment, timeout=10)
                self.assertRegex(output, r"\APASS host-adapter " + group
                                 + r" checks=[1-9][0-9]*\n\Z")

    def test_core_adapter_exact_halves_class_restore_and_csr_addresses(self):
        self.run_group("core_vectors")

    def test_public_query_reconstructs_exact_uint64_values_and_core_sum(self):
        self.run_group("public_query")

    def test_public_query_rejects_invalid_inputs_and_propagates_each_failure(self):
        self.run_group("public_errors")

    def test_production_device_csr_macro_preserves_xlen_semantics(self):
        self.run_group("device_width")
        source = extract_definition(CSR.read_text(encoding="utf-8"), "Word CsrUnit::get_csr(")
        for name, field in (("VX_CSR_MCYCLE", "cycles"), ("VX_CSR_MINSTRET", "instrs")):
            self.assertRegex(source, r"CSR_READ_64\(\s*" + name
                             + r"\s*,\s*core_perf\." + field + r"\s*\)")

    def test_architectural_rtl_counter_aliases_and_width_remain_distinct(self):
        # Narrow semantic source guard, not a whole-file identity requirement.
        source = (ROOT / "hw/rtl/core/VX_csr_data.sv").read_text(encoding="utf-8")
        source = re.sub(r"//[^\n]*|/\*.*?\*/", "", source, flags=re.DOTALL)
        aliases = re.search(r"`ifndef VX_CFG_XLEN_64\s+(.*?)`endif", source, re.DOTALL)
        self.assertIsNotNone(aliases)
        for name, slot in (("MCYCLE", "CYCLE"), ("MINSTRET", "INSTRET")):
            high_alias = r"`VX_CSR_" + name + r"\s*\+\s*12'h80"
            self.assertRegex(aliases.group(1), high_alias
                             + r"\s*:\s*live_sel_w\[LIVE_" + slot + r"_H\]\s*=\s*1")
            self.assertEqual(len(re.findall(high_alias, source)), 1,
                             "High alias must occur only in the RV32 branch")
            self.assertNotRegex(source, r"`VX_CSR_" + name + r"_H\b")
        width = re.search(r"`ifdef VX_CFG_XLEN_64\s+(assign live_src\[LIVE_CYCLE\].*?)`else",
                          source, re.DOTALL)
        self.assertIsNotNone(width)
        for slot, field in (("CYCLE", "cycles"), ("INSTRET", "instret")):
            self.assertRegex(width.group(1), r"live_src\[LIVE_" + slot
                             + r"\]\s*=\s*`VX_CFG_XLEN'\(sched_csr_if\." + field + r"\)")
            self.assertRegex(width.group(1), r"live_src\[LIVE_" + slot + r"_H\]\s*=\s*'0")


if __name__ == "__main__":
    unittest.main()

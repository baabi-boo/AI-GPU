# SPDX-License-Identifier: Apache-2.0
"""Original compiler and linker checks for the counter-enabled warm caller."""

from pathlib import Path

from baseline_packet_contract import _stamp_defines, _stamp_words
from compiler_records import _syntax
from p02_matrix_records import require
import p06_compiler_records as timed
import p06_workspace_compiler_records as workspace


WRAP_FLAGS = workspace.WRAP_FLAGS
ROLES = ("runtime", "backend_cpp", "kernel", "host")


def _configuration(text, *, role, fmt):
    expanded = role != "backend_cpp"
    expected = dict(workspace._EXPANDED_CONFIGURATION if expanded
                    else workspace._RAW_CONFIGURATION)
    if not expanded:
        expected.update(workspace._ARITHMETIC_SELECTORS, PERF_ENABLE="1")
    expected.update(VX_PROFILE="p02-tfr", ITYPE=fmt, OTYPE="fp32", KUNROLL="1", NDEBUG="1")
    if expanded:
        expected.update(VX_DBG_STALL_TIMEOUT="100000", VX_DBG_DEBUG_LEVEL="3")
    if role == "kernel":
        expected["__VORTEX__"] = "1"
    if role == "host":
        expected.update(OMPI_SKIP_MPICXX="1", MPICH_SKIP_MPICXX="1")
    actual = _stamp_defines(text, "warm " + role + " stamp")
    require(actual == expected, "warm " + role + " macro inventory differs from the frozen profile")


def validate_records(runtime, backend, application, *, driver="simx", fmt, source, build, jobs):
    require(type(driver) is str and driver == "simx", "warm benchmark requires SimX")
    require(type(fmt) is str and fmt in ("fp16", "bf16"), "unsupported warm format")
    require(type(jobs) is int and jobs in (1, 2), "unsupported warm build-job budget")
    source, build = Path(source), Path(build)
    require(source.is_absolute() and build.is_absolute()
            and ".." not in source.parts and ".." not in build.parts,
            "warm compiler bindings require absolute paths")
    runtime_lines = workspace._bounded_records(runtime, "warm runtime stamp")
    backend_lines = workspace._bounded_records(backend, "warm backend stamp")
    app_lines = workspace._bounded_records(application, "warm application stamp")
    require(len(runtime_lines) == len(backend_lines) == 1 and len(app_lines) == 3,
            "warm caller requires original runtime/backend/kernel/host/linker records")
    result = []
    for text, role in zip((*runtime_lines, *backend_lines, *app_lines[:2]), ROLES):
        row = timed._record(text, "warm " + role + " stamp", fmt,
                            role=role, source=source, build=build)
        _configuration(text, role=role, fmt=fmt)
        result.append(row)
    _syntax(app_lines[2], "warm linker stamp")
    require(_stamp_words(app_lines[2], "warm linker stamp")
            == [*WRAP_FLAGS, "-L" + str(build / "sw/runtime"), "-lvortex"],
            "warm linker differs from the four-observer runtime binding")
    return result


def validate_effective_header(text, expected, *, driver="simx", role):
    require(driver == "simx" and role in ROLES, "unsupported warm effective-header role")
    macros = timed.validate_header_macros(text, performance=role == "backend_cpp")
    require(type(expected) is dict and macros == expected,
            "warm " + role + " effective configuration differs from the generated profile")
    return macros

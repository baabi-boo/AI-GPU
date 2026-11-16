# SPDX-License-Identifier: Apache-2.0
"""Check declared generated build inputs without interpreting or executing them."""

import configparser
import re

from compiler_records import validate_records
from hwemu_contract import CONFIGS, safe_path


PIN_NAMES = ("VORTEX_VERSION", "TOOLCHAIN_REV", "GEM5_REV", "FIRESIM_REV")
STAMP_KEYS = ("XLEN", "TOOLDIR", "OSVERSION", "PREFIX", "PROFILE",
              "SOURCE_DIR", "BUILDDIR", *PIN_NAMES)
COPIED_INPUTS = {
    "config.mk": "config.mk.in",
    "ci/blackbox.sh": "ci/blackbox.sh",
    "ci/gen_config.py": "ci/gen_config.py",
    "sw/kernel/Makefile": "sw/kernel/Makefile",
    "sw/runtime/stub/Makefile": "sw/runtime/stub/Makefile",
    "sw/runtime/common.mk": "sw/runtime/common.mk",
    "sw/runtime/xrt/Makefile": "sw/runtime/xrt/Makefile",
    "sw/runtime/xrt/xrt.ini": "sw/runtime/xrt/xrt.ini.in",
    "tests/regression/demo/Makefile": "tests/regression/demo/Makefile",
    "tests/regression/common.mk": "tests/regression/common.mk",
    "hw/syn/xilinx/xrt/Makefile": "hw/syn/xilinx/xrt/Makefile",
    "hw/syn/xilinx/common.mk": "hw/syn/xilinx/common.mk",
    "hw/syn/xilinx/platform.mk": "hw/syn/xilinx/platform.mk",
}
HEADERS = ("sw/VX_config.h", "sw/VX_types.h", "hw/VX_config.vh", "hw/VX_types.vh")
LIMITATIONS = (
    "Generated headers are identity-pinned and screened for XLEN overrides; "
    "they are not regenerated or numerically qualified by this offline check.",
    "A nonempty emconfig JSON object is checked for bounded parseability only; "
    "the vendor-specific schema and platform compatibility remain unverified.",
    "Matching source copies and compiler stamps do not prove which inputs "
    "produced an existing binary or that a vendor build completed successfully.",
)


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _stamp(text, manifest, pins):
    _require("\0" not in text, "configure stamp contains a NUL byte")
    values = {}
    for word in text.split():
        key, separator, value = word.partition("=")
        _require(separator and key in STAMP_KEYS and key not in values,
                 "configure stamp has unknown, missing, or duplicate fields")
        values[key] = value
    _require(set(values) == set(STAMP_KEYS), "configure stamp has incomplete fields")
    expected = {
        "XLEN": "64", "PROFILE": "", "OSVERSION": "ubuntu/focal",
        "TOOLDIR": manifest["build"]["tool_dir"],
        "SOURCE_DIR": manifest["source"]["root"],
        "BUILDDIR": manifest["build"]["root"],
        "PREFIX": manifest["build"]["root"] + "/install", **pins,
    }
    _require(values == expected, "configure stamp differs from the frozen build bindings")
    return values


def _pins(text):
    values = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, separator, value = line.partition("=")
        _require(separator and key in PIN_NAMES and key not in values
                 and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._+\-]*", value),
                 "source VERSION has unsupported or duplicate fields")
        values[key] = value
    _require(set(values) == set(PIN_NAMES), "source VERSION is incomplete")
    return values


def _substitute(text, values):
    replacements = {
        **values, "VORTEX_HOME": values["SOURCE_DIR"],
        "INSTALLDIR": values["PREFIX"],
    }
    for key, value in replacements.items():
        text = text.replace("@" + key + "@", value)
    _require(re.search(r"@[A-Z_][A-Z0-9_]*@", text) is None,
             "generated template contains an unresolved substitution")
    return text


def _ini(text, source):
    parser = configparser.ConfigParser(interpolation=None, delimiters=("=",),
                                       strict=True)
    parser.optionxform = str
    try:
        parser.read_string(text)
    except configparser.Error as error:
        raise ValueError("generated XRT INI is malformed") from error
    expected = {
        "Runtime": {"runtime_log": "console"},
        "Emulation": {"debug_mode": "off", "user_pre_sim_script":
                      source + "/sw/runtime/xrt/xsim.tcl"},
        "Debug": {"profile": "false", "timeline_trace": "false",
                  "data_transfer_trace": "off"},
    }
    _require(not parser.defaults() and set(parser.sections()) == set(expected),
             "generated XRT INI has unsupported sections or defaults")
    _require(all(dict(parser.items(section, raw=True)) == values
                 for section, values in expected.items()),
             "generated XRT INI does not use the source hook and lean trace defaults")


def check_build(inputs, manifest):
    """Reject inconsistent generated inputs; grant no vendor qualification."""
    source = safe_path(manifest["source"]["root"], "source root")
    build = safe_path(manifest["build"]["root"], "build root")
    pins = _pins(inputs.read_text(source + "/VERSION", limit=16384))
    values = _stamp(inputs.read_text(build + "/.config.stamp", limit=16384),
                    manifest, pins)
    for destination, origin in COPIED_INPUTS.items():
        expected = inputs.read_text(source + "/" + origin)
        if origin.endswith(".in"):
            expected = _substitute(expected, values)
        _require(inputs.read_text(build + "/" + destination) == expected,
                 "generated input differs from its source: " + destination)
    for relative in HEADERS:
        text = inputs.read_text(build + "/" + relative)
        _require(bool(text.strip()) and "\0" not in text,
                 "generated header is empty or malformed: " + relative)
        # XLEN is an extern supplied by compilation, not a generated definition.
        _require(re.search(r"(?m)^\s*[#`](?:define|undef)\s+VX_CFG_XLEN(?:\b|_)",
                           text) is None,
                 "generated header overrides the external XLEN selection: " + relative)
    validate_records(
        inputs.read_text(build + "/sw/runtime/xrt_config.stamp", limit=65536),
        inputs.read_text(build + "/tests/regression/demo/config.stamp", limit=65536),
        build, CONFIGS,
    )
    _ini(inputs.read_text(build + "/sw/runtime/xrt/xrt.ini", limit=16384), source)
    _require(manifest["files"]["xsim_hook"]["path"] ==
             source + "/sw/runtime/xrt/xsim.tcl", "XRT hook declaration is inconsistent")
    _require(bool(inputs.read_json(manifest["files"]["emconfig"]["path"])),
             "emconfig must contain a nonempty JSON object")

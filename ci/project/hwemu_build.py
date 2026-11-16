# SPDX-License-Identifier: Apache-2.0
"""Check declared generated build inputs without interpreting or executing them."""

import configparser
import re

from baseline_packet_contract import _stamp_defines, _stamp_flags, _stamp_words
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


def _kernel_architecture(words, label):
    expected = {"-march": "rv64imafd", "-mabi": "lp64d"}
    selected = {}
    operand_options = {
        "-I", "-isystem", "-isystem-after", "-iquote", "-idirafter", "-iprefix",
        "-iwithprefix", "-iwithprefixbefore", "-isysroot", "-imultilib", "-imultiarch",
        "-MF", "-MT", "-MQ", "--include-directory", "--include-directory-after",
        "--include-prefix", "--include-with-prefix", "--include-with-prefix-after",
        "--include-with-prefix-before", "--sysroot",
    }
    joined_operands = (
        "-I", "-isystem", "-iquote", "-idirafter", "-iprefix", "-iwithprefixbefore",
        "-iwithprefix", "-isysroot", "-imultilib", "-imultiarch", "-MF", "-MT", "-MQ",
    )
    standalone = {
        "-Wall", "-Wextra", "-Werror", "-Wfatal-errors", "-Wpedantic", "-pedantic",
        "-fPIC", "-fdata-sections", "-ffunction-sections", "-fno-exceptions", "-fno-rtti",
        "-fno-tree-loop-distribute-patterns", "-nostartfiles", "-nostdlib", "-nostdinc",
        "-nostdinc++", "-M", "-MM", "-MD", "-MMD", "-MP", "-MG", "-c", "-E", "-S",
        "-P", "-C", "-CC", "-H", "-pipe",
    }

    def scan(arguments, *, preprocessor=False):
        pending = iter(arguments)
        forwarded = []

        def operand():
            value = next(pending, None)
            _require(value is not None, label + " has a compiler option without an operand")
            return value

        for word in pending:
            option, separator, value = word.partition("=")
            if word.startswith(("-D", "-U")):
                if len(word) == 2:
                    operand()
                continue
            if option in ("--define-macro", "--undefine-macro"):
                if not separator:
                    operand()
                continue
            if not preprocessor and word.startswith("-Wp,"):
                forwarded.extend(word[4:].split(","))
                continue
            if not preprocessor and word == "-Xpreprocessor":
                forwarded.append(operand())
                continue
            if option in expected:
                _require(not preprocessor and separator and value == expected[option]
                         and option not in selected,
                         label + " has a missing, repeated, or conflicting kernel ISA/ABI selection")
                selected[option] = value
                continue
            if word in operand_options or (preprocessor and word in ("-MD", "-MMD")):
                operand()
                continue
            if separator and option.startswith("--") and option in operand_options:
                continue
            if any(word.startswith(prefix) and len(word) > len(prefix)
                   and not word[len(prefix):].startswith("-") for prefix in joined_operands):
                continue
            if word == "-I-" or word in standalone or re.fullmatch(
                    r"-O(?:[0-3sgz]|fast)|-g[0-3]?|-W(?:no-|error[=-])[A-Za-z0-9_-]+"
                    r"|-(?:std|mcmodel)=[A-Za-z0-9+._-]+", word):
                continue
            raise ValueError(label + " contains unsupported kernel flags or source operands")

        # Preprocessor operands form a separate stream; they cannot establish
        # driver ISA/ABI selections or consume a following driver argument.
        if forwarded:
            scan(forwarded, preprocessor=True)

    scan(words)
    _require(selected == expected, label + " does not establish the frozen kernel ISA/ABI")


def _compile_flags(text, label, *, kernel=False):
    _require("\0" not in text, label + " contains a NUL byte")
    _require(re.search(r"[;&|<>$`]", text) is None,
             label + " contains unsupported shell expansion or operator syntax")
    words = _stamp_words(text, label)
    _require(not any("xrtsim" in word.lower() for word in words),
             label + " selects the vendor-free shim")
    defines = _stamp_defines(text, label)
    _require("XRTSIM" not in defines, label + " selects the vendor-free shim")
    expected = _stamp_defines(" ".join(CONFIGS), "frozen configuration")
    expected.update(VX_CFG_XLEN="64", VX_CFG_XLEN_64="1")
    _require(all(defines.get(key) == value for key, value in expected.items()),
             label + " does not establish the frozen native RV64 configuration")
    _require(not any(key.startswith("VX_CFG_XLEN_") and key != "VX_CFG_XLEN_64"
                     for key in defines), label + " contains a conflicting XLEN selector")
    _require(not any(key.startswith("VX_CFG_FPU_TYPE_")
                     and key != "VX_CFG_FPU_TYPE_STD" for key in defines),
             label + " contains a nonnative scalar selector")
    _require(defines.get("VX_CFG_FPU_TYPE", "STD") == "STD",
             label + " contradicts native STD scalar arithmetic")
    _require(not any(key.startswith("VX_CFG_TCU_TYPE_")
                     and key != "VX_CFG_TCU_TYPE_TFR" for key in defines)
             and defines.get("VX_CFG_TCU_TYPE", "TFR") == "TFR",
             label + " contains a nonnative tensor selector")
    if kernel:
        _kernel_architecture(words, label)


def _configuration_flags(runtime, demo, build):
    runtime_lines = [line for line in runtime.splitlines() if line.strip()]
    demo_lines = [line for line in demo.splitlines() if line.strip()]
    _require(len(runtime_lines) == 1, "XRT runtime stamp must contain one compiler record")
    _require(len(demo_lines) == 3, "demo stamp must contain kernel, host, and linker records")
    _compile_flags(runtime_lines[0], "XRT runtime stamp")
    _compile_flags(demo_lines[0], "demo kernel stamp", kernel=True)
    _compile_flags(demo_lines[1], "demo host stamp")
    _require("\0" not in demo_lines[2] and not any(
                 "xrtsim" in word.lower()
                 for word in _stamp_words(demo_lines[2], "demo linker stamp")),
             "demo linker stamp contains the vendor-free shim or invalid bytes")
    _stamp_flags(demo_lines[2], "demo linker stamp")
    _require(_stamp_words(demo_lines[2], "demo linker stamp") ==
             ["-L" + build + "/sw/runtime", "-lvortex"],
             "demo linker stamp differs from the frozen runtime binding")


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
    _configuration_flags(
        inputs.read_text(build + "/sw/runtime/xrt_config.stamp", limit=65536),
        inputs.read_text(build + "/tests/regression/demo/config.stamp", limit=65536),
        build,
    )
    _ini(inputs.read_text(build + "/sw/runtime/xrt/xrt.ini", limit=16384), source)
    _require(manifest["files"]["xsim_hook"]["path"] ==
             source + "/sw/runtime/xrt/xsim.tcl", "XRT hook declaration is inconsistent")
    _require(bool(inputs.read_json(manifest["files"]["emconfig"]["path"])),
             "emconfig must contain a nonempty JSON object")

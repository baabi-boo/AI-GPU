# SPDX-License-Identifier: Apache-2.0
"""Strict compiler-record checks shared by vendor preparation and execution."""

import re

from baseline_packet_contract import _stamp_defines, _stamp_flags, _stamp_words


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _records(text, label):
    _require(type(text) is str, label + " must contain text")
    _require(not any((ord(char) < 32 and char not in "\t\n")
                     or 127 <= ord(char) <= 159
                     or (char.isspace() and char not in " \t\n")
                     for char in text),
             label + " contains unsupported control characters or record separators")
    return [line for line in text.split("\n") if line.strip()]


def _syntax(text, label):
    _require(re.search(r"[;&|<>$`*?\[\]{}()~]", text) is None,
             label + " contains unsupported shell expansion or operator syntax")


def _compiler_arguments(words, label, *, kernel=False):
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
        "-P", "-C", "-CC", "-H", "-pipe", "-pthread",
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
                _require(kernel and not preprocessor and separator and value == expected[option]
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
            raise ValueError(label + " contains unsupported compiler flags or source operands")

        # Preprocessor operands form a separate stream; they cannot establish
        # driver ISA/ABI selections or consume a following driver argument.
        if forwarded:
            scan(forwarded, preprocessor=True)

    scan(words)
    if kernel:
        _require(selected == expected, label + " does not establish the frozen kernel ISA/ABI")


def _compile_flags(text, label, configs, *, kernel=False):
    _syntax(text, label)
    words = _stamp_words(text, label)
    _require(not any("xrtsim" in word.lower() for word in words),
             label + " selects the vendor-free shim")
    _compiler_arguments(words, label, kernel=kernel)
    defines = _stamp_defines(text, label)
    _require("XRTSIM" not in defines, label + " selects the vendor-free shim")
    expected = _stamp_defines(" ".join(configs), "frozen configuration")
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


def validate_records(runtime, demo, build, configs):
    """Check each frozen compiler invocation and its exact runtime link binding."""
    runtime_lines = _records(runtime, "XRT runtime stamp")
    demo_lines = _records(demo, "demo stamp")
    _require(len(runtime_lines) == 1, "XRT runtime stamp must contain one compiler record")
    _require(len(demo_lines) == 3, "demo stamp must contain kernel, host, and linker records")
    _compile_flags(runtime_lines[0], "XRT runtime stamp", configs)
    _compile_flags(demo_lines[0], "demo kernel stamp", configs, kernel=True)
    _compile_flags(demo_lines[1], "demo host stamp", configs)
    _syntax(demo_lines[2], "demo linker stamp")
    _require(not any(
                 "xrtsim" in word.lower()
                 for word in _stamp_words(demo_lines[2], "demo linker stamp")),
             "demo linker stamp contains the vendor-free shim or invalid bytes")
    _stamp_flags(demo_lines[2], "demo linker stamp")
    _require(_stamp_words(demo_lines[2], "demo linker stamp") ==
             ["-L" + build + "/sw/runtime", "-lvortex"],
             "demo linker stamp differs from the frozen runtime binding")

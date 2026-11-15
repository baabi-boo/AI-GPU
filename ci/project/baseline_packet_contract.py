# SPDX-License-Identifier: Apache-2.0
"""Offline checks for stopped, retained native-baseline execution evidence."""

from datetime import datetime
import hashlib
import json
import math
import re
import shlex

from baseline_matrix import command_for, config_for, validate_matrix
from baseline_packet_io import PacketError


MIB = 1024 * 1024
MAX_INTEGER = 2**63 - 1
# The second snapshot corrects only the attention operand descriptions from RS to SS.
MATRIX_SEMANTIC_SHA256S = {
    "8c89315b2c5cb42903166f07c0c7ea96cbf95b1d3f63c708c879dbc27a8c18d5",
    "20af3af4e074ddc02020cf55a94053c93b750b802aa31cf6ebd775bf5345acea",
}
BUNDLE_SEMANTIC_SHA256 = "f7638b92912ee8b61640d32431814e676950124b9455649f16400cb54b2a4eb3"
TOOLCHAIN_COMMIT = "e3db4bcdf819a17f618ad9fc2472f8f7dea3192b"
HELPERS = ("baseline.py", "baseline_inventory.py", "baseline_matrix.py",
           "baseline_process.py", "baseline_host.py", "preflight.py")
SOURCE_INPUTS = ("VERSION", ".gitmodules", "configure", "config.mk.in",
                 "VX_config.toml", "VX_types.toml", "ci/gen_config.py", "ci/blackbox.sh")
GENERATED = (".config.stamp", "config.mk", "sw/VX_config.h", "sw/VX_types.h",
             "hw/VX_config.vh", "hw/VX_types.vh", "ci/blackbox.sh")
BUILD_INPUTS = ("ci/gen_config.py", "sw/kernel/Makefile", "sw/runtime/common.mk",
                "sw/runtime/stub/Makefile", "sw/runtime/simx/Makefile",
                "sw/runtime/rtlsim/Makefile", "sim/common.mk", "sim/simx/Makefile",
                "sim/rtlsim/Makefile", "sim/rtlsim/verilator.vlt",
                "tests/regression/common.mk", "tests/regression/sgemm_tcu/Makefile",
                "tests/regression/flash_attn_tcu_wg/Makefile")
SOURCE_BUILD_INPUTS = tuple(name + ".in" if name.endswith("verilator.vlt") else name
                            for name in BUILD_INPUTS)
DEPENDENCIES = ("third_party/softfloat/build/Linux-x86_64-GCC/softfloat.a",
                "third_party/ramulator/libramulator.so",
                "third_party/ramulator_ext/libramulator-vortex.so")
SUBMODULES = {"third_party/" + name for name in
              ("cocogfx", "cvfpu", "hardfloat", "ramulator", "softfloat")}
RECURSIVE_SUBMODULES = SUBMODULES | {
    "third_party/cvfpu/src/common_cells",
    "third_party/cvfpu/src/fpu_div_sqrt_mvp",
    "third_party/cvfpu/tb/flexfloat",
}
TOOLS = {
    "riscv_gcc": "riscv64-gnu-toolchain/bin/riscv64-unknown-elf-gcc",
    "llvm_clang": "llvm-vortex/bin/clang", "verilator": "verilator/bin/verilator",
    "verilator_binary": "verilator/bin/verilator_bin",
}
LIBRARIES = ("libc64/lib/libc.a", "libc64/lib/libm.a",
             "libcrt64/lib/baremetal/libclang_rt.builtins-riscv64.a")
HOST_TOOLS = {"gcc", "g++", "make", "ld", "as", "python3", "cc1plus"}
CONFIGURE = ["$SOURCE/configure", "--xlen=64", "--osversion=ubuntu/focal",
             "--tooldir=$TOOLS"]
SOURCE_FIELDS = {"revision", "tree", "dirty", "changed_paths", "untracked_paths",
                 "submodules", "pins", "blockers", "outcome"}
BUILD_FIELDS = {"xlen", "profile", "os_bundle", "identity_matches", "generated",
                "source_inputs", "build_inputs", "source_build_inputs", "blockers",
                "limitations", "outcome"}
CASE_FIELDS = {"id", "app", "driver", "configs", "args", "reference", "arithmetic",
               "outcome", "reason", "artifacts"}
CASE_STAGES = ("dependencies_before", "tooling_before", "source_before", "build_before",
               "dependencies_at_launch", "dependencies_after", "tooling_after",
               "source_after", "build_after")
CASE_OPTIONAL = set(CASE_STAGES) | {"reference_marker_verified", "configuration_artifacts",
                                   "binary_identities", "native_flags_verified"}
LIMITATIONS = [
    "Integrity checks bind recorded assertions and retained bytes; they do not prove honest execution or independently establish numerical correctness.",
    "The unsigned manifest covers referenced evidence read by the verifier; unrelated directory contents are outside its scope.",
    "The original matrix input hash is provenance metadata; the retained matrix is separately checked against the frozen semantic contract.",
    "Source, generated-build, binary, dependency and installed-tool identities are inventory assertions; original files are not required or reconstructed.",
    "Build identity observations do not establish an independent clean-room rebuild; a previously configured build is permitted.",
    "Retained helper sources are hashed as inert evidence and are never imported or executed; their checkout revision is independent of GPU source.",
    "SimX is software simulation; processor rtlsim is not full-AFU vendor XRT hw_emu, physical FPGA or silicon evidence.",
    "Native matrix success does not accept P01; independent review, phase governance and the blocked P01-A03 integration gate remain external obligations.",
    "Resource observations are sampled budgets and do not certify a container/cgroup memory limit or every escaped descendant.",
]


def _require(condition, message):
    if not condition:
        raise PacketError(message)


def _fields(value, required, label, optional=()):
    _require(type(value) is dict, label + " must be an object")
    _require(set(required) <= set(value) <= set(required) | set(optional),
             label + " has missing or unknown fields")


def _text(value, label, *, maximum=4096, empty=False):
    _require(type(value) is str and len(value) <= maximum
             and (empty or bool(value.strip()))
             and not any(ord(character) < 32 or ord(character) == 127 for character in value),
             label + " must be bounded text")
    return value


def _integer(value, label, minimum=0, maximum=MAX_INTEGER):
    _require(type(value) is int and minimum <= value <= maximum,
             label + " must be a bounded integer")
    return value


def _number(value, label, minimum=0, maximum=MAX_INTEGER):
    _require(type(value) in (int, float), label + " must be a finite bounded number")
    try:
        valid = math.isfinite(value) and minimum <= value <= maximum
    except OverflowError:
        valid = False
    _require(valid, label + " must be a finite bounded number")
    return value


def _strings(value, label, maximum=256):
    _require(type(value) is list and len(value) <= maximum, label + " must be a bounded list")
    for item in value:
        _text(item, label)
    return value


def _path(value, label):
    _text(value, label, maximum=1024)
    _require(not value.startswith("/") and "\\" not in value
             and all(part not in ("", ".", "..") for part in value.split("/")),
             label + " must be a canonical relative POSIX path")
    return value


def _hex(value, digits, label):
    _require(type(value) is str and re.fullmatch("[0-9a-f]{" + str(digits) + "}", value),
             label + " is not a valid hexadecimal identity")


def _canonical(value):
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeError, RecursionError) as error:
        raise PacketError("evidence contains a malformed JSON value") from error


def _same(left, right):
    return _canonical(left) == _canonical(right)


def _identity(value, label, expected=None, *, extra=(), maximum=MAX_INTEGER):
    _fields(value, {"path", "sha256", "size_bytes"} | set(extra), label)
    _path(value["path"], label + ".path")
    _hex(value["sha256"], 64, label + ".sha256")
    _integer(value["size_bytes"], label + ".size_bytes", 1, maximum)
    if expected is not None:
        _require(value["path"] == expected, label + " has the wrong path")
    return (value["sha256"], value["size_bytes"])


def _identities(value, paths, label, *, complete=True, maximum=MAX_INTEGER):
    _require(type(value) is list and len(value) <= len(paths), label + " has the wrong inventory size")
    result = {}
    for item in value:
        identity = _identity(item, label, maximum=maximum)
        path = item["path"]
        _require(path in paths and path not in result, label + " has an unexpected or duplicate path")
        result[path] = identity
    if complete:
        _require(set(result) == set(paths), label + " is incomplete")
    return result


def _observation(value, label, *, required=False):
    _require(value["outcome"] in ("pass", "blocked"), label + " has an invalid observation outcome")
    _strings(value["blockers"], label + ".blockers")
    passed = value["outcome"] == "pass"
    _require(passed == (not value["blockers"]), label + " contradicts its blockers")
    if "limitations" in value:
        _strings(value["limitations"], label + ".limitations")
    _require(not required or passed, label + " must be a passing observation")
    return passed


def _source(value, label, *, required=False):
    _fields(value, SOURCE_FIELDS, label, {"inputs"})
    passed = _observation(value, label, required=required)
    for name in ("revision", "tree"):
        if value[name] is not None:
            _hex(value[name], 40, label + "." + name)
        _require(not passed or value[name] is not None, label + " lacks a source revision/tree")
    _require(type(value["dirty"]) is bool or value["dirty"] is None, label + ".dirty is malformed")
    for name in ("changed_paths", "untracked_paths"):
        entries = _strings(value[name], label + "." + name)
        _require(len(entries) == len(set(entries)), label + " has duplicate changed paths")
        for path in entries:
            _path(path, label + "." + name)
    _require(not passed or (value["dirty"] is False and not value["changed_paths"]
                            and not value["untracked_paths"]), label + " claims a clean source with changes")
    pins = value["pins"]
    pin_names = {"VORTEX_VERSION", "TOOLCHAIN_REV", "GEM5_REV", "FIRESIM_REV"}
    _fields(pins, pin_names if passed else (), label + ".pins", pin_names)
    for pin in pins.values():
        _require(type(pin) is str and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._+-]{0,255}", pin),
                 label + " has a malformed version pin")
    if passed:
        _require(pins["TOOLCHAIN_REV"] == "v3.0.2", label + " has the wrong toolchain pin")
    modules = value["submodules"]
    _require(type(modules) is dict, label + ".submodules must be an object")
    if modules or passed:
        _fields(modules, {"declared_count", "entries", "errors"}, label + ".submodules")
        _integer(modules["declared_count"], label + ".submodules.declared_count", 0, 256)
        _strings(modules["errors"], label + ".submodules.errors")
        _require(type(modules["entries"]) is list and len(modules["entries"]) <= 256,
                 label + " has an excessive submodule inventory")
        observed = set()
        for entry in modules["entries"]:
            _fields(entry, {"path", "revision", "status"}, label + ".submodule")
            path = _path(entry["path"], label + ".submodule.path")
            _require(path not in observed, label + " has duplicate submodules")
            observed.add(path)
            _hex(entry["revision"], 40, label + ".submodule.revision")
            _require(entry["status"] in ("initialized", "not_initialized", "revision_mismatch", "conflict"),
                     label + " has an invalid submodule status")
            _require(not passed or entry["status"] == "initialized", label + " has an uninitialized submodule")
        if passed:
            _require(not modules["errors"] and modules["declared_count"] == len(SUBMODULES)
                     and RECURSIVE_SUBMODULES <= observed, label + " lacks the declared recursive submodule inventory")
    _require(not passed or "inputs" in value, label + " lacks source input identities")
    if "inputs" in value:
        _identities(value["inputs"], SOURCE_INPUTS, label + ".inputs", complete=passed)
    return passed


def _build(value, label, source, *, fresh=False):
    if fresh and type(value) is dict and value.get("outcome") == "not_run":
        _fields(value, {"outcome", "reason"}, label)
        _text(value["reason"], label + ".reason")
        return False
    _fields(value, BUILD_FIELDS, label)
    passed = _observation(value, label)
    _require(type(value["identity_matches"]) is bool, label + ".identity_matches must be boolean")
    _require(not passed or value["identity_matches"] is True, label + " lacks matching build provenance")
    if value["xlen"] is not None:
        _integer(value["xlen"], label + ".xlen", 1, 256)
    for name in ("profile", "os_bundle"):
        if value[name] is not None:
            _text(value[name], label + "." + name, empty=name == "profile")
    _require(not passed or (value["xlen"] == 64 and value["profile"] == ""
                            and value["os_bundle"] == "ubuntu/focal"), label + " is not the frozen RV64 build")
    maps = {}
    for name, paths in (("generated", GENERATED), ("source_inputs", SOURCE_INPUTS),
                        ("build_inputs", BUILD_INPUTS), ("source_build_inputs", SOURCE_BUILD_INPUTS)):
        maps[name] = _identities(value[name], paths, label + "." + name, complete=passed)
    if passed:
        source_inputs = _identities(source["inputs"], SOURCE_INPUTS, label + ".source")
        _require(maps["source_inputs"] == source_inputs, label + " has different source inputs")
        _require(maps["generated"]["ci/blackbox.sh"] == source_inputs["ci/blackbox.sh"],
                 label + " has a different generated blackbox script")
        _require(maps["source_build_inputs"]["ci/gen_config.py"] == source_inputs["ci/gen_config.py"],
                 label + " has a different build generator")
        for destination, origin in zip(BUILD_INPUTS, SOURCE_BUILD_INPUTS):
            if destination == origin:
                _require(maps["build_inputs"][destination] == maps["source_build_inputs"][origin],
                         label + " has a copied build recipe mismatch")
    return passed


def _dependencies(value, label, *, required=False):
    _fields(value, {"artifacts", "blockers", "outcome"}, label)
    passed = _observation(value, label, required=required)
    _identities(value["artifacts"], DEPENDENCIES, label + ".artifacts", complete=passed)
    return passed


def _tooling(value, label, *, required=False):
    _fields(value, {"files", "checkout", "blockers", "limitations", "outcome"}, label)
    passed = _observation(value, label, required=required)
    _identities(value["files"], HELPERS, label + ".files", complete=passed, maximum=MIB)
    checkout = value["checkout"]
    _fields(checkout, {"revision", "tree", "dirty"}, label + ".checkout")
    for name in ("revision", "tree"):
        if checkout[name] is not None:
            _hex(checkout[name], 40, label + ".checkout." + name)
    _require(type(checkout["dirty"]) is bool or checkout["dirty"] is None,
             label + ".checkout.dirty must be boolean or null")
    return passed


def _tools(value, label, *, required=False):
    _fields(value, {"toolchain_commit", "toolchain_tag", "os_bundle", "bundle_manifest",
                    "tools", "libraries", "blockers", "limitations", "outcome"}, label)
    passed = _observation(value, label, required=required)
    _require(value["toolchain_commit"] == TOOLCHAIN_COMMIT and value["toolchain_tag"] == "v3.0.2"
             and value["os_bundle"] == "ubuntu/focal", label + " has the wrong frozen toolchain")
    bundle = value["bundle_manifest"]
    if bundle is not None:
        _fields(bundle, {"repository", "tag", "revision", "os_bundle", "parts", "sha256", "size_bytes"},
                label + ".bundle_manifest")
        _hex(bundle["sha256"], 64, label + ".bundle_manifest.sha256")
        _integer(bundle["size_bytes"], label + ".bundle_manifest.size_bytes", 1, MIB)
        _require(type(bundle["parts"]) is list and len(bundle["parts"]) == 18,
                 label + " has an incomplete bundle inventory")
        paths = set()
        for part in bundle["parts"]:
            _identity(part, label + ".bundle_part", extra={"git_blob_sha"})
            _hex(part["git_blob_sha"], 40, label + ".bundle_part.git_blob_sha")
            _require(part["path"] not in paths, label + " has duplicate bundle parts")
            paths.add(part["path"])
        canonical = {name: bundle[name] for name in ("repository", "tag", "revision", "os_bundle")}
        canonical["parts"] = sorted(bundle["parts"], key=lambda item: item["path"])
        _require(hashlib.sha256(_canonical(canonical)).hexdigest() == BUNDLE_SEMANTIC_SHA256,
                 label + " differs from the reviewed immutable toolchain lock")
    _require(not passed or bundle is not None, label + " lacks the immutable bundle inventory")
    _fields(value["tools"], set(TOOLS) if passed else (), label + ".tools", TOOLS)
    for name, tool in value["tools"].items():
        _identity(tool, label + "." + name, TOOLS[name], extra={"version"})
        _text(tool["version"], label + ".version", maximum=512)
    _identities(value["libraries"], LIBRARIES, label + ".libraries", complete=passed)
    return passed


def _host(value, label, *, required=False):
    _fields(value, {"host", "tools", "blockers", "limitations", "outcome"}, label)
    passed = _observation(value, label, required=required)
    platform = value["host"]
    if platform is not None:
        _fields(platform, {"system", "machine", "libc"}, label + ".host")
        _fields(platform["libc"], {"name", "version"}, label + ".host.libc")
        for text in (platform["system"], platform["machine"], *platform["libc"].values()):
            _require(type(text) is str and re.fullmatch(r"[A-Za-z0-9_.+-]{1,256}", text),
                     label + " has a malformed host platform")
    _require(not passed or platform is not None, label + " lacks a host platform")
    _fields(value["tools"], HOST_TOOLS if passed else (), label + ".tools", HOST_TOOLS | {"cmake"})
    for name, tool in value["tools"].items():
        extra = "reported_by" if name == "cc1plus" else "version"
        _fields(tool, {"command", "resolved_name", "sha256", "size_bytes", extra}, label + "." + name)
        _require(tool["command"] == name, label + " has a mismatched host command")
        _path(tool["resolved_name"], label + ".resolved_name")
        _require("/" not in tool["resolved_name"], label + ".resolved_name must be a basename")
        _hex(tool["sha256"], 64, label + ".sha256")
        _integer(tool["size_bytes"], label + ".size_bytes", 1)
        if name == "cc1plus":
            _require(tool[extra] == "g++ -print-prog-name=cc1plus", label + " has an invalid C++ frontend source")
        else:
            _text(tool[extra], label + ".version", maximum=512)
            _require(re.search(r"\d+\.\d+", tool[extra]) is not None, label + " has an invalid host version")
    return passed


def _stable(value, initial, kind):
    if value["outcome"] != "pass":
        return False
    if kind == "tooling":
        return _same(value["files"], initial["files"])
    if kind == "dependencies":
        return _same(value["artifacts"], initial)
    if kind == "source":
        return all(_same(value[key], initial[key]) for key in
                   ("revision", "tree", "pins", "submodules", "inputs"))
    return _same(value, initial)


def _retained(reader, identity, label, limit):
    contents = reader.read_bytes(identity["path"], limit=limit)
    _require(len(contents) == identity["size_bytes"]
             and hashlib.sha256(contents).hexdigest() == identity["sha256"],
             label + " differs from its retained bytes")
    return contents


def _stamp_words(text, label):
    # A stamp is flag records, not a shell program. Permit whole-line comments
    # used by synthetic fixtures; never treat an inline '#' in a macro as a
    # comment, perform expansion, or execute retained text.
    words = []
    for line in text.split("\n"):
        if line.lstrip().startswith("#"):
            continue
        _require("#" not in line, label + " contains unsupported inline comment syntax")
        try:
            words.extend(shlex.split(line, comments=False, posix=True))
        except ValueError as error:
            raise PacketError(label + " contains malformed flag quoting") from error
    return words


def _stamp_flags(text, label):
    """Consume option operands before interpreting supported macro transports."""
    operand_options = {
        "-I", "-isystem", "-isystem-after", "-iquote", "-idirafter", "-iprefix",
        "-iwithprefix", "-iwithprefixbefore", "-isysroot", "-imultilib", "-imultiarch",
        "-MF", "-MT", "-MQ", "-o", "-L", "-l", "-x", "-u", "-T",
        "-Xassembler", "-Xlinker", "-aux-info", "-dumpbase", "-dumpbase-ext", "-dumpdir",
        "--include-directory", "--include-directory-after", "--include-prefix",
        "--include-with-prefix", "--include-with-prefix-after", "--include-with-prefix-before",
        "--sysroot", "--output", "--library-directory",
    }
    joined_operands = (
        "-I", "-isystem", "-iquote", "-idirafter", "-iprefix", "-iwithprefixbefore",
        "-iwithprefix", "-isysroot", "-imultilib", "-imultiarch", "-MF", "-MT", "-MQ", "-L",
    )
    standalone = {
        "-Wall", "-Wextra", "-Werror", "-Wfatal-errors", "-Wpedantic", "-pedantic",
        "-fPIC", "-fdata-sections", "-ffunction-sections", "-fno-exceptions", "-fno-rtti",
        "-fno-tree-loop-distribute-patterns", "-nostartfiles", "-nostdlib", "-nostdinc",
        "-nostdinc++", "-M", "-MM", "-MD", "-MMD", "-MP", "-MG", "-c", "-E", "-S",
        "-P", "-C", "-CC", "-H", "-pipe", "-pthread", "-shared", "-static", "-lvortex",
    }
    verilator_operands = {
        "--language", "--replication-limit", "--top-module", "--x-assign", "--x-initial", "--j",
    }
    verilator_standalone = {"--assert", "--cc", "--exe"}
    flags = []

    def checked(word):
        _require(not re.search(r"\$(?!(?:SOURCE|BUILD|TOOLS|OUTPUT)(?:/|$))|`", word),
                 label + " contains unresolved flag expansion")
        _require(not word.startswith("@"), label + " contains an opaque response file")
        return word

    def scan(words, context):
        pending = iter(words)
        preprocessor, compiler = [], []

        def operand():
            value = next(pending, None)
            _require(value is not None, label + " has a compiler option without an operand")
            return checked(value)

        for word in pending:
            checked(word)
            option, separator, value = word.partition("=")
            if word.startswith(("-D", "-U")):
                argument = word[2:] if len(word) > 2 else operand()
                _require(bool(argument), label + " contains a malformed macro operand")
                flags.append(word[:2] + argument)
                continue
            if option in ("--define-macro", "--undefine-macro"):
                argument = value if separator else operand()
                _require(bool(argument), label + " contains a malformed macro operand")
                flags.append(("-D" if option == "--define-macro" else "-U") + argument)
                continue
            if context != "preprocessor" and word.startswith("-Wp,"):
                forwarded = word[4:].split(",")
                _require(all(forwarded), label + " has an empty preprocessor flag operand")
                preprocessor.extend(forwarded)
                continue
            if context != "preprocessor" and word == "-Xpreprocessor":
                preprocessor.append(operand())
                continue
            if context == "driver" and option in ("-CFLAGS", "--CFLAGS"):
                forwarded = _stamp_words(value if separator else operand(), label)
                _require(bool(forwarded), label + " has an empty flag transport")
                compiler.extend(forwarded)
                continue
            if context == "driver" and option in ("-MAKEFLAGS", "--MAKEFLAGS"):
                # Other make assignments can inject flags or replace the compiler.
                value = value if separator else operand()
                _require(re.fullmatch(r"OPT_(?:FAST|SLOW|GLOBAL)=-O[0-3sg]", value),
                         label + " contains opaque make flags")
                continue
            if word in operand_options or (context == "preprocessor" and word in ("-MD", "-MMD")):
                operand()
                continue
            if separator and option.startswith("--") and option in operand_options:
                continue
            verilator_option = ("-" + option
                                if option.startswith("-") and not option.startswith("--") else option)
            if context == "driver" and verilator_option in verilator_operands:
                if not separator:
                    operand()
                continue
            if context == "driver" and (word in verilator_standalone
                    or "-" + word in verilator_standalone or re.fullmatch(r"-j[0-9]+", word)):
                continue
            if word.startswith("-LDFLAGS"):
                raise PacketError(label + " contains opaque linker flag transport")
            if any(word.startswith(prefix) and len(word) > len(prefix)
                   and not word[len(prefix):].startswith("-") for prefix in joined_operands):
                continue
            if word == "-I-" or word in standalone or re.fullmatch(
                    r"-O(?:[0-3sgz]|fast)|-g[0-3]?|-W(?:no-|error[=-])[A-Za-z0-9_-]+"
                    r"|-(?:std|mabi|march|mcmodel)=[A-Za-z0-9+._-]+", word):
                continue
            # Unknown options may consume the following word. Offline verification
            # cannot infer their arity or inspect option files and wrappers.
            _require(not word.startswith(("-", "+")),
                     label + " contains opaque or unsupported compiler flags")

        # Forwarded options have their own argument stream: consuming a raw
        # -Xpreprocessor marker as an include path would expose its -D operand.
        if preprocessor:
            scan(preprocessor, "preprocessor")
        if compiler:
            scan(compiler, "compiler")

    scan(_stamp_words(text, label), "driver")
    return flags


def _stamp_defines(text, label):
    defines = {}
    flags = iter(_stamp_flags(text, label))
    for flag in flags:
        if not flag.startswith(("-D", "-U")):
            continue
        operation, argument = flag[:2], flag[2:]
        if not argument:
            argument = next(flags, "")
        name, separator, value = argument.partition("=")
        _require(re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name),
                 label + " contains a malformed macro operand")
        if operation == "-U":
            _require(not separator, label + " contains a malformed undefinition")
            _require(not name.startswith(("VX_CFG_", "WGMMA_")) and name not in ("ITYPE", "OTYPE"),
                     label + " undefines a required configuration macro")
            continue
        # A bare -DNAME means NAME=1; -DNAME= is an explicitly empty value.
        value = value if separator else "1"
        _require(name not in defines or defines[name] == value, label + " contains conflicting defines")
        defines[name] = value
    return defines


def _stamp(contents, case, label):
    try:
        text = contents.decode("utf-8")
    except UnicodeError as error:
        raise PacketError(label + " must be UTF-8 text") from error
    _require("\x00" not in text, label + " contains a NUL byte")
    defines = _stamp_defines(text, label)
    expected = _stamp_defines(config_for(case), label)
    expected["VX_CFG_XLEN"] = "64"
    expected["VX_CFG_XLEN_64"] = "1"
    _require(all(defines.get(name) == value for name, value in expected.items()),
             label + " does not contain the frozen configuration and RV64")
    _require(not any(name.startswith("VX_CFG_XLEN_") and name != "VX_CFG_XLEN_64"
                     for name in defines), label + " contains a conflicting XLEN selector")
    _require(not any((name.startswith("VX_CFG_TCU_TYPE_") and name != "VX_CFG_TCU_TYPE_TFR")
                     or (name.startswith("VX_CFG_FPU_TYPE_") and name != "VX_CFG_FPU_TYPE_STD")
                     for name in defines), label + " selects non-native arithmetic")
    _require(defines.get("VX_CFG_TCU_TYPE", "TFR") == "TFR"
             and defines.get("VX_CFG_FPU_TYPE", "STD") == "STD", label + " contradicts native arithmetic")


def _case_artifacts(reader, result, case):
    label = "case " + case["id"]
    paths = ["tests/regression/" + case["app"] + "/config.stamp",
             "sw/runtime/" + case["driver"] + "_config.stamp",
             "sw/runtime/" + case["driver"] + "_rt_config.stamp"]
    artifacts = result["configuration_artifacts"]
    _require(type(artifacts) is list and len(artifacts) == 3, label + " must retain exactly three configuration stamps")
    seen = set()
    for artifact in artifacts:
        _identity(artifact, label + ".stamp", extra={"source", "redaction"}, maximum=MIB)
        original = artifact["source"]
        _identity(original, label + ".stamp.source", maximum=MIB)
        _require(original["path"] in paths and original["path"] not in seen,
                 label + " has an unexpected or duplicate source stamp")
        seen.add(original["path"])
        expected = "artifacts/" + case["id"] + "-" + original["path"].replace("/", "_")
        _require(artifact["path"] == expected, label + " has the wrong retained stamp path")
        _require(artifact["redaction"] == "source/build/tool/output roots replaced by symbolic labels",
                 label + " has an unknown stamp redaction")
        _stamp(_retained(reader, artifact, label + ".stamp", MIB), case, label + ".stamp")
    binaries = ["tests/regression/" + case["app"] + "/" + case["app"],
                "tests/regression/" + case["app"] + "/kernel.vxbin",
                "sw/runtime/libvortex-" + case["driver"] + ".so",
                "sw/runtime/lib" + case["driver"] + ".so"]
    _identities(result["binary_identities"], binaries, label + ".binary_identities")
    _require(result["native_flags_verified"] is True, label + " lacks its native flag assertion")


def _reference(contents):
    text = contents.decode("utf-8", errors="replace")
    return (len(re.findall(r"^PASSED![ \t\r]*$", text, re.MULTILINE)) == 1
            and re.search(r"^(?:FAILED!|Found [1-9][0-9]* errors!)[ \t\r]*$", text, re.MULTILINE) is None)


def _command(reader, entry, expected, budget, log_resolver=None):
    label = "command " + expected[0]
    _fields(entry, {"id", "argv", "cwd", "environment", "log", "outcome", "exit_code",
                    "reason", "duration_seconds", "log_sha256", "log_size_bytes",
                    "peak_rss_bytes", "cleanup_complete", "limitations"}, label)
    identifier, argv, configs = expected
    environment = {"MAKEFLAGS": "-j" + str(budget["jobs"]), "THREADS": str(budget["jobs"]),
                   "CCACHE_DISABLE": "1", "OBJCACHE": ""}
    if configs is not None:
        environment["CONFIGS"] = configs
    _require(entry["id"] == identifier and _same(entry["argv"], argv) and entry["cwd"] == "$BUILD"
             and _same(entry["environment"], environment), label + " differs from its frozen invocation")
    _require(entry["log"] == "logs/" + identifier + ".log", label + " has the wrong log path")
    _require(entry["outcome"] in ("pass", "fail", "blocked"), label + " is incomplete")
    _strings(entry["limitations"], label + ".limitations")
    _number(entry["duration_seconds"], label + ".duration_seconds", maximum=min(MAX_INTEGER, budget["timeout_seconds"] + 10))
    _integer(entry["peak_rss_bytes"], label + ".peak_rss_bytes")
    _integer(entry["log_size_bytes"], label + ".log_size_bytes", maximum=budget["max_log_bytes"])
    _require(type(entry["cleanup_complete"]) is bool, label + ".cleanup_complete must be boolean")
    if entry["exit_code"] is not None:
        _integer(entry["exit_code"], label + ".exit_code", -2**31, 2**31 - 1)
    if entry["outcome"] == "pass":
        _require(type(entry["exit_code"]) is int and entry["exit_code"] == 0
                 and entry["reason"] is None and entry["cleanup_complete"] is True,
                 label + " has contradictory success metadata")
        _require(entry["peak_rss_bytes"] <= budget["max_rss_bytes"], label + " exceeded its memory budget")
    else:
        _text(entry["reason"], label + ".reason")
        if entry["outcome"] == "blocked":
            _require(entry["exit_code"] is None, label + " reports an exit for an unlaunched blocked command")
        if entry["reason"] == "nonzero_exit":
            _require(type(entry["exit_code"]) is int and entry["exit_code"] != 0,
                     label + " claims a nonzero exit without one")
    if entry["log_sha256"] is None:
        _require(entry["outcome"] == "blocked" and entry["exit_code"] is None
                 and entry["reason"] in ("disk_reserve", "resource_inventory_unavailable", "log_open_failed")
                 and entry["log_size_bytes"] == 0 and entry["peak_rss_bytes"] == 0
                 and entry["cleanup_complete"] is True, label + " is missing its completed log identity")
        return None
    _hex(entry["log_sha256"], 64, label + ".log_sha256")
    identity = {"path": entry["log"], "sha256": entry["log_sha256"],
                "size_bytes": entry["log_size_bytes"]}
    limit = min(16 * MIB, budget["max_log_bytes"])
    if log_resolver is None:
        return _retained(reader, identity, label + ".log", limit)
    contents = log_resolver(identity, limit)
    _require(type(contents) is bytes and len(contents) <= limit,
             label + " resolver returned invalid or oversized log bytes")
    return contents


def _timestamp(value, label):
    _text(value, label, maximum=40)
    _require(re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})", value),
             label + " must contain a timezone")
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise PacketError(label + " is not a valid timestamp") from error


def verify_contract(reader, report, matrix, *, log_resolver=None):
    """Validate retained assertions without opening original paths or executing code."""
    _require(log_resolver is None or callable(log_resolver), "log resolver must be callable")
    _require(type(report) is dict, "report must be an object")
    _require(report.get("mode") == "run" and report.get("state") == "finished",
             "report is not a stopped finished run; planned, running and prerequisite-blocked reports are not verifiable")
    required = {"schema_version", "mode", "state", "outcome", "phase_complete", "scope",
                "started_at", "finished_at", "matrix", "budget", "resources", "source_before",
                "tools_before", "host_before", "tooling_before", "dependencies", "dependencies_planned",
                "build_before", "commands", "blockers", "coverage", "cases", "integration", "limitations"}
    launch_stages = ("dependencies_before_execution", "tooling_before_execution", "host_before_execution", "tooling_snapshots")
    final_stages = ("tools_after", "host_after", "dependencies_after", "tooling_after")
    _fields(report, required, "report", {"reason", "build_configured", *launch_stages, *final_stages})
    _require(type(report["schema_version"]) is int and report["schema_version"] == 1, "unsupported report schema")
    _require(report["mode"] == "run" and report["state"] == "finished", "report is not a stopped finished run")
    _require(report["phase_complete"] is False, "a packet cannot claim phase completion")
    _require(report["outcome"] in ("pass", "fail", "blocked"), "finished report has an invalid outcome")
    _text(report["scope"], "report.scope")
    _strings(report["limitations"], "report.limitations")
    _strings(report["blockers"], "report.blockers")
    _require(not report["blockers"], "a prerequisite-blocked report cannot be a finished execution")
    if "reason" in report:
        _text(report["reason"], "report.reason")
    _require(report["outcome"] != "pass" or "reason" not in report, "successful report contains a failure reason")
    start = _timestamp(report["started_at"], "report.started_at")
    finish = _timestamp(report["finished_at"], "report.finished_at")
    _require(finish >= start, "report finishes before it starts")
    try:
        validate_matrix(matrix)
    except (TypeError, ValueError, KeyError) as error:
        raise PacketError("retained matrix violates the frozen matrix contract") from error
    _require(hashlib.sha256(_canonical(matrix)).hexdigest() in MATRIX_SEMANTIC_SHA256S,
             "retained matrix differs from the frozen semantic snapshot")
    _fields(report["matrix"], {"id", "sha256", "size_bytes"}, "report.matrix")
    _require(report["matrix"]["id"] == matrix["id"], "report matrix ID differs from the retained matrix")
    _hex(report["matrix"]["sha256"], 64, "report.matrix.sha256")
    _integer(report["matrix"]["size_bytes"], "report.matrix.size_bytes", 1, 256 * 1024)
    budget = report["budget"]
    _fields(budget, {"jobs", "timeout_seconds", "min_free_bytes", "max_log_bytes", "max_rss_bytes"}, "budget")
    _integer(budget["jobs"], "budget.jobs", 1, 2)
    _number(budget["timeout_seconds"], "budget.timeout_seconds", 1)
    for name in ("min_free_bytes", "max_log_bytes", "max_rss_bytes"):
        _integer(budget[name], "budget." + name, 1)
    resources = report["resources"]
    disks = {name + "_free_disk_bytes" for name in ("source", "build", "tools", "output")}
    _fields(resources, disks | {"host_available_ram_bytes", "effective_cgroup_limit_bytes"}, "resources")
    for name in disks:
        _integer(resources[name], "resources." + name, budget["min_free_bytes"])
    if resources["host_available_ram_bytes"] is not None:
        _integer(resources["host_available_ram_bytes"], "resources.host_available_ram_bytes")
    _require(resources["effective_cgroup_limit_bytes"] is None, "runner does not certify an effective cgroup memory limit")
    integration = report["integration"]
    _fields(integration, {"gate", "driver", "target", "outcome", "exit_code", "reason"}, "integration")
    _require(all(integration[name] == value for name, value in
                 (("gate", "P01-A03"), ("driver", "xrt"), ("target", "hw_emu"), ("outcome", "blocked")))
             and integration["exit_code"] is None, "vendor XRT integration must remain blocked")
    _text(integration["reason"], "integration.reason")
    _source(report["source_before"], "source_before", required=True)
    _tools(report["tools_before"], "tools_before", required=True)
    _host(report["host_before"], "host_before", required=True)
    _tooling(report["tooling_before"], "tooling_before", required=True)
    _dependencies(report["dependencies_planned"], "dependencies_planned", required=True)
    _identities(report["dependencies"], DEPENDENCIES, "dependencies")
    _require(_same(report["dependencies"], report["dependencies_planned"]["artifacts"]), "planned dependency identities disagree")
    initial_build = _build(report["build_before"], "build_before", report["source_before"], fresh=True)
    _require(initial_build or report["build_before"]["outcome"] == "not_run", "initial build provenance did not pass")
    coverage = report["coverage"]
    _fields(coverage, {"selected_ids", "required_ids", "full_matrix_selected", "full_native_matrix_passed"}, "coverage")
    ids = [case["id"] for case in matrix["cases"]]
    selected = _strings(coverage["selected_ids"], "coverage.selected_ids", 6)
    _require(selected and len(selected) == len(set(selected))
             and selected == [identifier for identifier in ids if identifier in selected], "selected cases are not a nonempty ordered frozen subset")
    _require(_same(coverage["required_ids"], ids), "required case coverage differs from the frozen matrix")
    _require(coverage["full_matrix_selected"] is (selected == ids), "full-matrix selection claim is incorrect")
    _require(type(report["cases"]) is list and len(report["cases"]) == len(selected), "case records do not match selected coverage")
    cases = [case for case in matrix["cases"] if case["id"] in selected]
    expected = [("configure", CONFIGURE, None),
                ("kernel-library", ["make", "-j" + str(budget["jobs"]), "-C", "sw/kernel"], None),
                ("runtime-stub", ["make", "-j" + str(budget["jobs"]), "-C", "sw/runtime/stub"], None)]
    for case in cases:
        expected.extend(((case["id"] + "-configure", CONFIGURE, None),
                         (case["id"], command_for(case), config_for(case))))
    commands = report["commands"]
    _require(type(commands) is list and len(commands) <= len(expected), "command list exceeds the frozen execution sequence")
    logs = {}
    for index, entry in enumerate(commands):
        contents = _command(reader, entry, expected[index], budget, log_resolver)
        logs[entry["id"]] = contents
        _require(entry["outcome"] == "pass" or index == len(commands) - 1,
                 "commands continued after a failed or blocked command")
    command_map = {entry["id"]: entry for entry in commands}
    _require(sum(entry["duration_seconds"] for entry in commands) <= (finish - start).total_seconds() + 2,
             "command durations exceed the reported execution interval")
    # Validate object shape before provenance dispatch accesses conditional fields.
    for result, case in zip(report["cases"], cases):
        _fields(result, CASE_FIELDS, "case " + case["id"], CASE_OPTIONAL)
    _verify_observations(reader, report, cases, command_map)
    interrupted_run = report["outcome"] == "fail" and report.get("reason") == "execution interrupted"
    capture_fields = {"configuration_artifacts", "binary_identities", "native_flags_verified"}
    passed, interrupted, not_run = [], [], []
    terminal = False
    for result, case in zip(report["cases"], cases):
        for name in ("id", "app", "driver", "configs", "args", "reference", "arithmetic"):
            _require(_same(result[name], case[name]), "case " + case["id"] + " differs from its frozen " + name)
        _require(result["artifacts"] == [], "legacy case artifacts must be empty")
        outcome = result["outcome"]
        _require(outcome in ("pass", "fail", "blocked", "not_run"), "case has an invalid outcome")
        _require(not terminal or outcome == "not_run", "case execution continued after a terminal result")
        prepared = command_map.get(case["id"] + "-configure")
        workload = command_map.get(case["id"])
        if outcome == "not_run":
            _text(result["reason"], "not-run case reason")
            started = (bool(set(result) & CASE_OPTIONAL) or prepared is not None
                       or workload is not None or result["reason"] == "execution in progress")
            if started:
                _require(interrupted_run and not terminal and result["reason"] == "execution in progress",
                         "not-run case contains execution evidence outside a terminal interruption")
                _require(not (set(result) & (CASE_OPTIONAL - set(CASE_STAGES[:5]))),
                         "not-run case contains post-workload evidence")
                interrupted.append(case["id"])
            else:
                not_run.append(case["id"])
            terminal = True
            continue
        if outcome != "pass":
            terminal = True
            _text(result["reason"], "failed case reason")
            _require(report["outcome"] != "pass", "successful run contains a failed case")
        else:
            _require(result["reason"] is None and prepared is not None and workload is not None
                     and prepared["outcome"] == workload["outcome"] == "pass",
                     "passed case lacks successful configure/workload commands")
            complete = (set(CASE_STAGES) <= set(result)
                        and result.get("reference_marker_verified") is True
                        and capture_fields <= set(result))
            # The runner copies process success before checking and capturing the case.
            if not complete:
                _require(interrupted_run, "passed case lacks completed provenance, reference or capture evidence")
                interrupted.append(case["id"])
                terminal = True
            else:
                passed.append(case["id"])
        if "reference_marker_verified" in result:
            _require(set(CASE_STAGES) <= set(result), "reference assertion precedes boundary provenance")
            _require(type(result["reference_marker_verified"]) is bool and workload is not None
                     and workload["outcome"] == "pass", "reference assertion lacks a successful workload")
            _require(result["reference_marker_verified"] is _reference(logs[case["id"]]),
                     "recorded CPU-reference result contradicts the retained workload log")
        if set(result) & capture_fields:
            _require(capture_fields <= set(result)
                     and result.get("reference_marker_verified") is True, "case has incomplete capture evidence")
            _case_artifacts(reader, result, case)
        if outcome == "blocked":
            _require((workload or prepared) is not None and (workload or prepared)["outcome"] == "blocked",
                     "blocked case lacks a blocked command")
    if any(name in report for name in final_stages):
        _require(passed == selected, "final provenance was recorded before all selected cases passed")
    if report["outcome"] == "pass":
        _require(passed == selected and len(commands) == len(expected)
                 and all(entry["outcome"] == "pass" for entry in commands), "successful run lacks complete selected-case execution")
        _require(all(name in report for name in final_stages), "successful run lacks final provenance")
    else:
        _require("reason" in report or any(result["outcome"] in ("fail", "blocked") for result in report["cases"])
                 or any(entry["outcome"] != "pass" for entry in commands), "failed run lacks a retained failure explanation")
        if report["outcome"] == "blocked":
            _require(commands and commands[-1]["outcome"] == "blocked",
                     "blocked run lacks a terminal blocked command")
            for result in report["cases"]:
                if commands[-1]["id"] in (result["id"], result["id"] + "-configure"):
                    _require(result["outcome"] == "blocked", "blocked run has a non-blocked terminal case")
    native_passed = report["outcome"] == "pass" and passed == ids
    _require(coverage["full_native_matrix_passed"] is native_passed, "native-matrix coverage claim is incorrect")
    return {"native_matrix_passed": native_passed, "run_outcome": report["outcome"],
            "selected_ids": list(selected), "passed_ids": passed,
            "failed_ids": [result["id"] for result in report["cases"] if result["outcome"] in ("fail", "blocked")],
            "not_run_ids": not_run, "interrupted_ids": interrupted,
            "source_revision": report["source_before"]["revision"], "source_tree": report["source_before"]["tree"],
            "instrumentation_revision": report["tooling_before"]["checkout"]["revision"],
            "integration_outcome": "blocked", "phase_complete": False, "limitations": list(LIMITATIONS)}


def _verify_observations(reader, report, cases, commands):
    launch = ("dependencies_before_execution", "tooling_before_execution", "host_before_execution", "tooling_snapshots")
    final = ("tools_after", "host_after", "dependencies_after", "tooling_after")
    validators = {"dependencies": _dependencies, "tooling": _tooling, "host": _host, "tools": _tools}
    for stages in (launch, final):
        present = [name for name in stages if name in report]
        _require(present == list(stages[:len(present)]), "run provenance observations are out of sequence")
    for name in launch[:-1] + final:
        if name not in report:
            continue
        kind = name.split("_", 1)[0]
        validators[kind](report[name], name)
        initial = report["dependencies"] if kind == "dependencies" else report[kind + "_before"]
        stable = _stable(report[name], initial, kind)
        stages = launch if name in launch else final
        subsequent = any(stage in report for stage in stages[stages.index(name) + 1:])
        _require(stable or (report["outcome"] != "pass" and not subsequent
                            and (name not in launch or not commands)), name + " drift overlaps continued or passing execution")
    if commands:
        _require(set(launch) <= set(report), "executed commands lack launch provenance and helper snapshots")
    if "tooling_snapshots" in report:
        snapshots = report["tooling_snapshots"]
        expected = {"artifacts/tooling/" + name for name in HELPERS}
        _identities(snapshots, expected, "tooling_snapshots", maximum=MIB)
        original = {item["path"]: item for item in report["tooling_before"]["files"]}
        for identity in snapshots:
            source = original[identity["path"].rsplit("/", 1)[-1]]
            _require((identity["sha256"], identity["size_bytes"]) == (source["sha256"], source["size_bytes"]),
                     "helper snapshot does not match the executing instrumentation")
            _retained(reader, identity, "helper snapshot", MIB)
    configured = report.get("build_configured")
    if configured is not None:
        _require("configure" in commands and commands["configure"]["outcome"] == "pass",
                 "configured build lacks a successful configure command")
        okay = _build(configured, "build_configured", report["source_before"])
        if report["build_before"]["outcome"] == "pass":
            okay = okay and _stable(configured, report["build_before"], "build")
        _require(okay or (report["outcome"] == "fail" and len(commands) == 1), "configured build drift overlaps continued execution")
    if len(commands) > 1:
        _require(configured is not None, "execution lacks configured-build provenance")
    for index, (case, result) in enumerate(zip(cases, report["cases"])):
        present = [name for name in CASE_STAGES if name in result]
        _require(present == list(CASE_STAGES[:len(present)]), "case provenance observations are out of sequence")
        prepared = commands.get(case["id"] + "-configure")
        workload = commands.get(case["id"])
        if result["outcome"] != "not_run" or present or result["reason"] == "execution in progress":
            _require(all(name in commands and commands[name]["outcome"] == "pass"
                         for name in ("configure", "kernel-library", "runtime-stub")),
                     "case observation precedes successful prerequisite commands")
        if prepared is not None:
            _require(set(CASE_STAGES[:3]) <= set(result), "case configure lacks source/dependency/helper provenance")
        if workload is not None:
            _require(set(CASE_STAGES[:5]) <= set(result), "workload lacks build and launch provenance")
        if "build_before" in result:
            _require(prepared is not None and prepared["outcome"] == "pass",
                     "case build observation lacks a successful reconfiguration")
        for stage in present:
            label = case["id"] + "." + stage
            kind = stage.split("_", 1)[0]
            if kind == "source":
                _source(result[stage], label)
                stable = _stable(result[stage], report["source_before"], kind)
            elif kind == "build":
                source = result.get("source_after" if stage == "build_after" else "source_before", report["source_before"])
                # A blocked source inventory can legitimately stop a failed observation.
                if source.get("outcome") != "pass":
                    source = report["source_before"]
                okay = _build(result[stage], label, source)
                stable = okay and configured is not None and _stable(result[stage], configured, kind)
            else:
                validators[kind](result[stage], label)
                initial = report["dependencies"] if kind == "dependencies" else report[kind + "_before"]
                stable = _stable(result[stage], initial, kind)
            if stable:
                continue
            later = CASE_STAGES[CASE_STAGES.index(stage) + 1:]
            continued = any(name in result for name in later)
            if stage == "source_after":
                # The runner observes both source and build before comparing source.
                continued = any(name in result for name in later if name != "build_after")
            if stage in CASE_STAGES[:3]:
                continued = continued or prepared is not None
            elif stage in ("build_before", "dependencies_at_launch"):
                continued = continued or workload is not None
            continued = continued or any(item.get("outcome") != "not_run" for item in report["cases"][index + 1:])
            _require(result.get("outcome") == "fail" and report["outcome"] == "fail" and not continued,
                     label + " drift overlaps continued or passing execution")
        if workload is None:
            _require(not (set(CASE_STAGES[5:]) & set(result)), "post-workload provenance lacks a workload command")

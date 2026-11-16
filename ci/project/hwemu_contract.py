# SPDX-License-Identifier: Apache-2.0
"""Strict declarations for an offline vendor-emulation launch plan."""

from copy import deepcopy
from pathlib import PurePosixPath
import re


GIB = 1024 ** 3
MIB = 1024 ** 2
MAX_INPUT_BYTES = 512 * MIB
MAX_MANIFEST_BYTES = 256 * 1024
SHA256_RE = re.compile(r"[0-9a-f]{64}")
REVISION_RE = re.compile(r"[0-9a-f]{40}")
CONFIGS = (
    "-DVX_CFG_NUM_CLUSTERS=1",
    "-DVX_CFG_NUM_CORES=1",
    "-DVX_CFG_NUM_WARPS=4",
    "-DVX_CFG_NUM_THREADS=4",
    "-DVX_CFG_ISSUE_WIDTH=1",
    "-DVX_CFG_FPU_TYPE_STD",
)
FILE_ROLES = (
    "vpp", "vivado", "emconfigutil", "platforminfo", "xrt_header",
    "xrt_library", "platform", "xclbin", "emconfig", "build_receipt",
    "xsim_hook",
)
GENERATED_PATHS = (
    ".config.stamp", "config.mk", "sw/VX_config.h", "sw/VX_types.h",
    "hw/VX_config.vh", "hw/VX_types.vh", "ci/blackbox.sh", "ci/gen_config.py",
    "sw/kernel/Makefile", "sw/runtime/stub/Makefile", "sw/runtime/common.mk",
    "sw/runtime/xrt/Makefile", "sw/runtime/xrt/xrt.ini",
    "sw/runtime/xrt_config.stamp", "tests/regression/demo/Makefile",
    "tests/regression/demo/config.stamp", "tests/regression/common.mk",
    "hw/syn/xilinx/xrt/Makefile", "hw/syn/xilinx/common.mk",
    "hw/syn/xilinx/platform.mk",
)
MANIFEST_KEYS = (
    "schema_version", "target", "source", "build", "vendor", "platform",
    "files", "generated", "budget",
)
RECEIPT_KEYS = tuple(key for key in MANIFEST_KEYS if key != "budget")


def _object(value, keys, label):
    if type(value) is not dict or set(value) != set(keys):
        raise ValueError(label + " must contain exactly the required fields")
    return value


def _integer(value, minimum, maximum, label):
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError(label + " must be an integer within its supported bounds")
    return value


def _match(value, pattern, label):
    if type(value) is not str or pattern.fullmatch(value) is None:
        raise ValueError(label + " has an unsupported value")
    return value


def safe_path(value, label="path"):
    """Accept canonical absolute paths safe for the existing Make recipes."""
    if (type(value) is not str or len(value) > 4096
            or re.fullmatch(r"/[A-Za-z0-9_./+\-]+", value) is None
            or any(part in ("", ".", "..") for part in value.split("/")[1:])):
        raise ValueError(label + " must be a canonical absolute path without shell syntax")
    return value


def _inside(path, root):
    return path.startswith(root + "/")


def _identity(value, label, *, path):
    keys = ("path", "size_bytes", "sha256") if path else ("size_bytes", "sha256")
    _object(value, keys, label)
    if path:
        safe_path(value["path"], label + ".path")
    _integer(value["size_bytes"], 1, MAX_INPUT_BYTES, label + ".size_bytes")
    _match(value["sha256"], SHA256_RE, label + ".sha256")


def _bindings(data, *, receipt=False):
    _integer(data["schema_version"], 1, 1, "schema_version")
    if type(data["target"]) is not str or data["target"] != "hw_emu":
        raise ValueError("target must be hw_emu")
    source = _object(data["source"], ("root", "revision", "tree"), "source")
    safe_path(source["root"], "source.root")
    _match(source["revision"], REVISION_RE, "source.revision")
    _match(source["tree"], REVISION_RE, "source.tree")
    build = _object(data["build"], ("root", "tool_dir", "xlen", "profile", "configs"), "build")
    safe_path(build["root"], "build.root")
    safe_path(build["tool_dir"], "build.tool_dir")
    _integer(build["xlen"], 64, 64, "build.xlen")
    if type(build["profile"]) is not str or build["profile"] != "":
        raise ValueError("build.profile must be empty")
    if type(build["configs"]) is not list or build["configs"] != list(CONFIGS):
        raise ValueError("build.configs must equal the frozen integer smoke configuration")
    if source["root"] == build["root"] or _inside(source["root"], build["root"]):
        raise ValueError("build.root must be separate from the source inputs")
    if _inside(build["root"], source["root"]):
        relative = build["root"][len(source["root"]) + 1:]
        if "/" in relative or not relative.startswith("build"):
            raise ValueError("an in-checkout build must be a direct build-prefixed directory")
    if (build["tool_dir"] in (build["root"], source["root"])
            or _inside(build["tool_dir"], build["root"])
            or _inside(build["root"], build["tool_dir"])
            or _inside(build["tool_dir"], source["root"])
            or _inside(source["root"], build["tool_dir"])):
        raise ValueError("tool_dir and build/source directories must remain separate")

    vendor = _object(data["vendor"], ("vitis", "vivado", "xrt"), "vendor")
    for name in vendor:
        value = _object(vendor[name], ("root", "release"), "vendor." + name)
        safe_path(value["root"], "vendor." + name + ".root")
        _match(value["release"], re.compile(r"[A-Za-z0-9][A-Za-z0-9_.+\-]{0,79}"),
               "vendor." + name + ".release")
    platform = _object(data["platform"], ("name",), "platform")
    _match(platform["name"], re.compile(r"[A-Za-z0-9][A-Za-z0-9_.+\-]{0,159}"),
           "platform.name")

    roles = tuple(role for role in FILE_ROLES if not receipt or role != "build_receipt")
    files = _object(data["files"], roles, "files")
    for role, value in files.items():
        _identity(value, "files." + role, path=True)
    paths = [value["path"] for value in files.values()]
    if len(set(paths)) != len(paths):
        raise ValueError("file roles must identify distinct paths")
    required = {
        "vpp": vendor["vitis"]["root"] + "/bin/v++",
        "vivado": vendor["vivado"]["root"] + "/bin/vivado",
        "emconfigutil": vendor["vitis"]["root"] + "/bin/emconfigutil",
        "platforminfo": vendor["vitis"]["root"] + "/bin/platforminfo",
        "xsim_hook": source["root"] + "/sw/runtime/xrt/xsim.tcl",
    }
    for role, path in required.items():
        if files[role]["path"] != path:
            raise ValueError("files." + role + ".path does not match its declared root")
    if not _inside(files["xrt_header"]["path"], vendor["xrt"]["root"] + "/include"):
        raise ValueError("xrt_header must be inside the declared XRT include directory")
    library = PurePosixPath(files["xrt_library"]["path"])
    if (str(library.parent) != vendor["xrt"]["root"] + "/lib"
            or re.fullmatch(r"libxrt_coreutil\.so(?:\.[0-9]+)*", library.name) is None):
        raise ValueError("xrt_library must name the XRT coreutil library within its declared root")
    if PurePosixPath(files["platform"]["path"]).name != platform["name"] + ".xpfm":
        raise ValueError("platform descriptor filename must match platform.name")
    xclbin = PurePosixPath(files["xclbin"]["path"])
    emconfig = PurePosixPath(files["emconfig"]["path"])
    if (xclbin.name != "vortex_afu.xclbin" or emconfig.name != "emconfig.json"
            or xclbin.parent != emconfig.parent):
        raise ValueError("xclbin and emconfig must be paired canonical artifact filenames")
    generated = _object(data["generated"], GENERATED_PATHS, "generated")
    for path, value in generated.items():
        _identity(value, "generated." + path, path=False)
    generated_paths = {build["root"] + "/" + path for path in generated}
    if generated_paths.intersection(paths):
        raise ValueError("file roles must not alias generated inputs")
    return sum(value["size_bytes"] for value in files.values()) + sum(
        value["size_bytes"] for value in generated.values())


def validate_manifest(data):
    """Validate declarations only; matching identities cannot qualify hardware."""
    _object(data, MANIFEST_KEYS, "manifest")
    size = _bindings(data)
    budget = _object(data["budget"], (
        "jobs", "timeout_seconds", "min_free_bytes", "max_rss_bytes",
        "max_log_bytes", "max_input_bytes",
    ), "budget")
    bounds = {
        "jobs": (1, 2), "timeout_seconds": (1, 7200),
        "min_free_bytes": (15 * GIB, 1024 * GIB),
        "max_rss_bytes": (1, 6 * GIB), "max_log_bytes": (1, 16 * MIB),
        "max_input_bytes": (1, MAX_INPUT_BYTES),
    }
    for key, (minimum, maximum) in bounds.items():
        _integer(budget[key], minimum, maximum, "budget." + key)
    if size > budget["max_input_bytes"]:
        raise ValueError("declared input sizes exceed budget.max_input_bytes")
    if data["files"]["build_receipt"]["size_bytes"] > MAX_MANIFEST_BYTES:
        raise ValueError("build receipt exceeds its JSON byte limit")
    return deepcopy(data)


def validate_receipt(data, manifest):
    """Check an asserted build receipt against the independent manifest."""
    manifest = validate_manifest(manifest)
    _object(data, RECEIPT_KEYS, "build receipt")
    _bindings(data, receipt=True)
    expected = {key: value for key, value in manifest.items() if key != "budget"}
    expected["files"] = {
        role: value for role, value in manifest["files"].items() if role != "build_receipt"
    }
    if data != expected:
        raise ValueError("build receipt declarations differ from the manifest")
    return deepcopy(data)

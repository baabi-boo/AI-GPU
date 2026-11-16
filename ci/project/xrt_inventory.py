# Licensed under the Apache License, Version 2.0.
"""Read-only identities and prerequisites for the bounded vendor XRT smoke."""

import configparser
import os
from pathlib import Path
import shutil

from baseline_inventory import collect_build
from compiler_records import validate_records
from xrt_contract import (CONFIGS, decode_json, file_identity, read_verified,
                          safe_path, validate_manifest, validate_receipt)
from xrt_source import collect_source


MIB = 1024 * 1024
EXECUTABLE_ROLES = ("vpp", "vivado", "emconfigutil", "platforminfo")
ROLE_PATHS = {
    "vpp": ("vitis_root", "bin/v++"),
    "vivado": ("vivado_root", "bin/vivado"),
    "emconfigutil": ("vitis_root", "bin/emconfigutil"),
    "platforminfo": ("vitis_root", "bin/platforminfo"),
    "xrt_header": ("xrt_root", "include/experimental/xrt_device.h"),
    "xrt_coreutil": ("xrt_root", "lib/libxrt_coreutil.so"),
}
XRT_HEADERS = ("xrt_bo.h", "xrt_device.h", "xrt_error.h", "xrt_ip.h",
               "xrt_kernel.h", "xrt_xclbin.h")
BUILD_COPIES = (
    "sw/runtime/xrt/Makefile", "tests/regression/demo/Makefile",
    "sw/runtime/common.mk", "tests/regression/common.mk",
)
SOURCE_FILES = (
    "sw/runtime/xrt/vortex.cpp", "sw/runtime/xrt/xsim.tcl",
    "tests/regression/demo/main.cpp", "tests/regression/demo/kernel.cpp",
    "tests/regression/demo/common.h",
)
STAMP_FILES = ("tests/regression/demo/config.stamp", "sw/runtime/xrt_config.stamp")
BINARY_FILES = (
    "tests/regression/demo/demo", "tests/regression/demo/kernel.vxbin",
    "sw/runtime/libvortex.so", "sw/runtime/libvortex-xrt.so",
)
LIMITATIONS = (
    "File identities and receipt bindings do not establish that build logs or reviewer claims are truthful.",
    "Vendor compatibility, license entitlement and artifact provenance require independent review; this inventory does not grant acceptance.",
    "Wrapper, header, library and platform-descriptor hashes do not inventory complete vendor installations or referenced platform files.",
    "No vendor program, FPGA build or GPU workload is executed by manifest inspection.",
)


def _finish(report):
    report["outcome"] = "blocked" if report["blockers"] else "pass"
    return report


def _record(report, role, expected, *, max_bytes=None):
    observed = file_identity(expected["path"], max_bytes=max_bytes)
    if observed != {key: expected[key] for key in ("sha256", "size_bytes")}:
        raise ValueError("file identity differs from the manifest")
    report["identities"][role] = {"path": expected["path"], **observed}


def _alias(root, relative, expected=None):
    root = safe_path(str(root))
    if root.resolve(strict=True) != root or not root.is_dir():
        raise ValueError("vendor root is not a canonical directory")
    selected = (root / relative).resolve(strict=True)
    if not selected.is_relative_to(root):
        raise ValueError("vendor lookup escapes its declared root")
    if expected is not None and str(selected) != expected["path"]:
        raise ValueError("vendor lookup does not select the pinned file")
    return selected


def inspect_manifest(data, source):
    """Bind declared vendor files and inert build evidence to a clean source tree."""
    validate_manifest(data)
    report = {"outcome": "blocked", "phase_complete": False,
              "acceptance": "not_evaluated", "blockers": [], "identities": {},
              "lookup_bindings": {}, "limitations": list(LIMITATIONS)}
    source_report = collect_source(source)
    report["source"] = source_report
    report["blockers"].extend(source_report["blockers"])
    if any(source_report.get(key) != value for key, value in data["source"].items()):
        report["blockers"].append("source commit/tree differs from the artifact manifest")

    for role, (root_key, relative) in ROLE_PATHS.items():
        expected = data["vendor"]["files"][role]
        try:
            selected = _alias(data["vendor"][root_key], relative, expected)
            if role in EXECUTABLE_ROLES and not os.access(selected, os.X_OK):
                raise ValueError("required vendor program is not executable")
            _record(report, "vendor." + role, expected)
            report["lookup_bindings"][role] = {
                "lookup": str(Path(data["vendor"][root_key]) / relative),
                "resolved": str(selected),
            }
        except (OSError, ValueError, RuntimeError) as error:
            report["blockers"].append("vendor " + role + ": " + str(error))

    extra = [("vivado_root", "bin/xsim")]
    extra.extend(("xrt_root", "include/experimental/" + name) for name in XRT_HEADERS)
    for root_key, relative in extra:
        role = root_key + ":" + relative
        try:
            selected = _alias(data["vendor"][root_key], relative)
            if relative == "bin/xsim" and not os.access(selected, os.X_OK):
                raise ValueError("vendor simulator is not executable")
            report["identities"][role] = {"path": str(selected), **file_identity(selected)}
            report["lookup_bindings"][role] = {
                "lookup": str(Path(data["vendor"][root_key]) / relative),
                "resolved": str(selected),
            }
        except (OSError, ValueError, RuntimeError) as error:
            report["blockers"].append("vendor prerequisite " + role + ": " + str(error))

    records = [("platform", data["platform"]["file"], None),
               ("xclbin", data["artifacts"]["xclbin"], None),
               ("emconfig", data["artifacts"]["emconfig"], MIB),
               ("build_receipt", data["build_receipt"], MIB),
               ("qualification_review", data["qualification_review"], MIB)]
    for role, expected, limit in records:
        try:
            _record(report, role, expected, max_bytes=limit)
        except (OSError, ValueError, RuntimeError) as error:
            report["blockers"].append(role + ": " + str(error))

    try:
        receipt = decode_json(read_verified(data["build_receipt"], max_bytes=MIB))
        validate_receipt(receipt, data)
        report["receipt_commands"] = receipt["commands"]
        for index, command in enumerate(receipt["commands"]):
            _record(report, "build_log_" + str(index), command["log"], max_bytes=16 * MIB)
        report["receipt_bound"] = True
    except (OSError, ValueError, RuntimeError, UnicodeError) as error:
        report["receipt_bound"] = False
        report["blockers"].append("build receipt binding: " + str(error))
    try:
        emconfig = decode_json(read_verified(data["artifacts"]["emconfig"], max_bytes=MIB))
        if not isinstance(emconfig, dict) or not emconfig:
            raise ValueError("emconfig must be a nonempty JSON object")
    except (OSError, ValueError, RuntimeError, UnicodeError) as error:
        report["blockers"].append("emulation configuration: " + str(error))
    try:
        review = read_verified(data["qualification_review"], max_bytes=MIB).decode("utf-8")
        if not review.strip() or "\x00" in review:
            raise ValueError("qualification review must contain nonempty UTF-8 text")
    except (OSError, ValueError, RuntimeError, UnicodeError) as error:
        report["blockers"].append("qualification review: " + str(error))
    return _finish(report)


def probe_environment(environ=None):
    """Report installed names without executing tools or asserting qualification."""
    environment = os.environ if environ is None else environ
    report = {"outcome": "blocked", "phase_complete": False,
              "acceptance": "not_evaluated", "tools": {}, "roots": {},
              "blockers": [], "limitations": list(LIMITATIONS)}
    for name in ("v++", "vivado", "emconfigutil", "platforminfo", "xsim"):
        present = shutil.which(name, path=environment.get("PATH", os.defpath)) is not None
        report["tools"][name] = {"available_on_path": present}
        if not present:
            report["blockers"].append("required vendor executable is absent from PATH: " + name)
    for name in ("XILINX_VITIS", "XILINX_VIVADO", "XILINX_XRT"):
        value = environment.get(name)
        exists = bool(value and Path(value).is_dir())
        report["roots"][name] = {"set": bool(value), "directory_exists": exists}
        if not exists:
            report["blockers"].append("required vendor root is unset or unavailable: " + name)
    report["blockers"].append("a pinned platform/artifact manifest and independently reviewed build receipt are required")
    return report


def _read(path, limit=MIB):
    identity = file_identity(path, max_bytes=limit)
    return read_verified({"path": str(path), **identity}, max_bytes=limit), identity


def inspect_build(build, source):
    """Check generated XRT inputs after configure, including native header checks."""
    build, source = safe_path(str(build)), safe_path(str(source))
    base = collect_build(build, source)
    report = {"base": base, "blockers": list(base["blockers"]),
              "identities": {}, "limitations": [
                  "Header comparison invokes the source's Python configuration generator, but no vendor, Make or GPU program."]}
    for relative in BUILD_COPIES:
        try:
            generated, identity = _read(build / relative)
            original, source_identity = _read(source / relative)
            if generated != original:
                raise ValueError("generated input differs from the current source")
            report["identities"][relative] = identity
            report["identities"]["source:" + relative] = source_identity
        except (OSError, ValueError, RuntimeError) as error:
            report["blockers"].append(relative + ": " + str(error))
    try:
        generated, identity = _read(build / "sw/runtime/xrt/xrt.ini")
        template, template_identity = _read(source / "sw/runtime/xrt/xrt.ini.in")
        expected = template.replace(b"@VORTEX_HOME@", str(source).encode())
        if generated != expected:
            raise ValueError("generated XRT INI differs from its source template")
        parser = configparser.ConfigParser(interpolation=None, strict=True)
        parser.read_string(generated.decode("utf-8"))
        if parser.get("Emulation", "user_pre_sim_script") != str(source / "sw/runtime/xrt/xsim.tcl"):
            raise ValueError("XRT pre-simulation script does not select the tracked Tcl source")
        report["identities"]["sw/runtime/xrt/xrt.ini"] = identity
        report["identities"]["source:sw/runtime/xrt/xrt.ini.in"] = template_identity
    except (OSError, ValueError, RuntimeError, UnicodeError, configparser.Error) as error:
        report["blockers"].append("generated XRT configuration: " + str(error))
    for relative in SOURCE_FILES:
        try:
            report["identities"]["source:" + relative] = file_identity(source / relative, max_bytes=MIB)
        except (OSError, ValueError, RuntimeError) as error:
            report["blockers"].append(relative + ": " + str(error))
    return _finish(report)


def inspect_effective(build):
    """Validate each compiler record and retain stamp and produced binary identities."""
    build = safe_path(str(build))
    report = {"blockers": [], "identities": {}, "native_flags_verified": False}
    stamps = {}
    for relative in STAMP_FILES:
        try:
            contents, identity = _read(build / relative)
            report["identities"][relative] = identity
            stamps[relative] = contents.decode("utf-8")
        except (OSError, ValueError, RuntimeError, UnicodeError) as error:
            report["blockers"].append(relative + ": " + str(error))
    if not report["blockers"]:
        try:
            validate_records(stamps["sw/runtime/xrt_config.stamp"],
                             stamps["tests/regression/demo/config.stamp"], str(build), CONFIGS)
        except ValueError as error:
            report["blockers"].append("effective compiler records: " + str(error))
    for relative in BINARY_FILES:
        try:
            report["identities"][relative] = file_identity(build / relative)
            if relative.endswith("/demo") and not os.access(build / relative, os.X_OK):
                raise ValueError("built demo is not executable")
        except (OSError, ValueError, RuntimeError) as error:
            report["blockers"].append(relative + ": " + str(error))
    report["native_flags_verified"] = not report["blockers"]
    return _finish(report)

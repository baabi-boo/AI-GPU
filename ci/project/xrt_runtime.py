# Licensed under the Apache License, Version 2.0.
"""Inspect the selected ELF loader bindings without executing a vendor object."""

import os
from pathlib import Path
import re
import shutil
import stat

from baseline_inventory import _probe
from xrt_contract import file_identity, read_verified, safe_path, validate_manifest


MAX_ELF_BYTES = 512 * 1024 * 1024
GENERATED = {
    "demo": "tests/regression/demo/demo",
    "libvortex": "sw/runtime/libvortex.so",
    "libvortex_xrt": "sw/runtime/libvortex-xrt.so",
}
COREUTIL = re.compile(r"libxrt_coreutil\.so(?:\.[0-9]+)*\Z")
LIBRARY_NAME = re.compile(r"[A-Za-z0-9_+.-]{1,255}\Z")
PRELOAD_FILE = Path("/etc/ld.so.preload")
LIMITATIONS = (
    "Only the demo, libvortex.so, libvortex-xrt.so and its direct coreutil lookup are bound; this is not a complete vendor or system dependency closure.",
    "ELF headers, dynamic tags and file identities predict the selected lookups; this inspection does not observe loaded process maps or establish symbol-level provenance.",
    "Matching ELF class, machine and data encoding is required; complete ELF loadability, ABI and transitive dependency compatibility remain unverified.",
    "Legacy DT_RPATH and hardware-capability lookup directories are unsupported because they can precede the fixed library directories.",
    "The host readelf program is executed read-only; no inspected executable, shared object, vendor tool or GPU workload is executed.",
)


def _finish(report):
    report["outcome"] = "blocked" if report["blockers"] else "pass"
    return report


def _directory(path):
    path = safe_path(path)
    if path.resolve(strict=True) != path or not path.is_dir():
        raise ValueError("loader directory is not canonical")
    return path


def _identity(path, executable=False):
    path = safe_path(path)
    identity = {"path": str(path), **file_identity(path, max_bytes=MAX_ELF_BYTES)}
    if executable and not os.access(path, os.X_OK):
        raise ValueError("required host ELF is not executable")
    if path.stat().st_mode & (stat.S_ISUID | stat.S_ISGID):
        raise ValueError("set-ID objects cannot use the inspected loader environment")
    if executable and hasattr(os, "listxattr") and "security.capability" in os.listxattr(path):
        raise ValueError("file capabilities can disable the explicit loader environment")
    return identity


def _header(output, size_bytes):
    lines = output.decode("utf-8").splitlines()
    headers = [index for index, line in enumerate(lines) if line == "ELF Header:"]
    if len(headers) != 1:
        raise ValueError("readelf did not identify one ELF header")
    fields = {}
    for line in lines[headers[0] + 1:]:
        if not line:
            break
        match = re.fullmatch(r" +([^:]+): +(.+?) *", line)
        if match is None:
            raise ValueError("readelf returned a malformed ELF header")
        key, value = match.groups()
        fields.setdefault(key, []).append(value)
    required = ("Magic", "Class", "Data", "Type", "Machine", "Size of this header",
                "Start of program headers", "Size of program headers", "Number of program headers")
    if (any(len(fields.get(key, [])) != 1 for key in required)
            or any(len(values) != 1 for key, values in fields.items() if key != "Version")
            or fields.get("Version") != ["1 (current)", "0x1"]):
        raise ValueError("readelf returned an incomplete or ambiguous ELF header")
    fields = {key: values[0] for key, values in fields.items() if key != "Version"}
    if not re.fullmatch(r"[0-9a-fA-F]{2}(?: +[0-9a-fA-F]{2}){15}", fields["Magic"]):
        raise ValueError("readelf returned malformed ELF identification bytes")
    magic = bytes.fromhex(fields["Magic"])
    classes = {1: "ELF32", 2: "ELF64"}
    encodings = {1: "2's complement, little endian", 2: "2's complement, big endian"}
    if (magic[:4] != b"\x7fELF" or magic[4] not in classes or magic[5] not in encodings
            or magic[6] != 1 or fields["Class"] != classes[magic[4]]
            or fields["Data"] != encodings[magic[5]]):
        raise ValueError("readelf returned invalid ELF class, data encoding or version")
    kind = re.fullmatch(r"(EXEC|DYN) \([^()]+\)", fields["Type"])
    if kind is None:
        raise ValueError("ELF type must be an executable or shared object")
    machine = fields["Machine"]
    if (machine in ("None", "none", "Unknown")
            or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_ .,+/():-]{0,127}", machine)):
        raise ValueError("readelf returned an unsupported ELF machine")
    layout = {}
    for key, suffix in (("Size of this header", " (bytes)"),
                        ("Start of program headers", " (bytes into file)"),
                        ("Size of program headers", " (bytes)"),
                        ("Number of program headers", "")):
        match = re.fullmatch(r"([0-9]+)" + re.escape(suffix), fields[key])
        if match is None:
            raise ValueError("readelf returned an unsupported ELF header layout")
        layout[key] = int(match.group(1))
    header_size, entry_size = (52, 32) if magic[4] == 1 else (64, 56)
    offset = layout["Start of program headers"]
    count = layout["Number of program headers"]
    if (layout["Size of this header"] != header_size
            or layout["Size of program headers"] != entry_size or not 0 < count < 65535
            or offset < header_size or offset + count * entry_size > size_bytes):
        raise ValueError("readelf returned an invalid ELF header or program table layout")
    return {"class": fields["Class"], "data": fields["Data"],
            "machine": machine, "type": kind.group(1)}


def _dynamic(output):
    text = output.decode("utf-8")
    if len(re.findall(r"^Dynamic section at offset ", text, re.MULTILINE)) != 1:
        raise ValueError("readelf did not identify one ELF dynamic section")
    result = {"needed": [], "soname": None, "rpath": None, "runpath": None}
    terminated = False
    for line in text.splitlines():
        match = re.match(r"\s*0x[0-9a-fA-F]+\s+\(([^)]+)\)\s*(.*)\Z", line)
        if match is None:
            continue
        tag, value = match.groups()
        if tag == "NULL":
            terminated = True
        if tag in ("FILTER", "AUXILIARY", "AUDIT", "DEPAUDIT"):
            raise ValueError("ELF loader redirection tag is unsupported: " + tag)
        if tag not in ("NEEDED", "SONAME", "RPATH", "RUNPATH"):
            continue
        value = re.fullmatch(r"[^\[\]]*\[([^\[\]\n]*)\]", value)
        if value is None:
            raise ValueError("readelf returned a malformed dynamic string")
        value = value.group(1)
        key = tag.lower()
        if tag in ("NEEDED", "SONAME"):
            if not LIBRARY_NAME.fullmatch(value):
                raise ValueError("ELF library names must be plain basenames")
            if "xrtsim" in value.lower():
                raise ValueError("ELF references an XRTSIM library")
        if tag == "NEEDED":
            if value in result[key]:
                raise ValueError("ELF has duplicate DT_NEEDED entries")
            result[key].append(value)
        elif result[key] is not None:
            raise ValueError("ELF has duplicate " + tag + " entries")
        else:
            result[key] = value
    if not terminated:
        raise ValueError("readelf dynamic section is incomplete")
    if result["rpath"] is not None:
        raise ValueError("DT_RPATH can preempt the fixed library lookup")
    return result


def _no_capability_directories(directory):
    # Reject rather than approximate CPU-dependent and legacy loader priority.
    for name in ("glibc-hwcaps", "tls", "haswell", "xeon_phi", "x86_64",
                 "i686", "i586", "i486", "sse2", "powerpc64", "s390x"):
        if os.path.lexists(directory / name):
            raise ValueError("hardware-capability lookup directory is unsupported: "
                             + str(directory / name))


def _resolve(name, directories, expected):
    for directory in directories:
        _no_capability_directories(directory)
        lookup = directory / name
        if not os.path.lexists(lookup):
            continue
        selected = lookup.resolve(strict=True)
        if str(selected) != expected["path"]:
            raise ValueError("runtime lookup does not select the pinned file: " + str(lookup))
        if _identity(selected) != expected:
            raise ValueError("runtime lookup identity differs from the pinned file")
        return {"lookup": str(lookup), "resolved": str(selected)}
    raise ValueError("runtime library is absent from the explicit lookup: " + name)


def _environment(environment, directories):
    if (type(environment) is not dict or any(
            type(key) is not str or not key or "=" in key or "\0" in key
            or type(value) is not str or "\0" in value
            for key, value in environment.items())):
        raise ValueError("runtime environment must contain valid strings")
    expected = ":".join(str(path) for path in directories)
    if environment.get("LD_LIBRARY_PATH") != expected:
        raise ValueError("LD_LIBRARY_PATH must be exactly generated runtime then vendor XRT/lib")
    for name, value in (("VORTEX_DRIVER", "xrt"), ("XCL_EMULATION_MODE", "hw_emu")):
        if environment.get(name) != value:
            raise ValueError(name + " must be explicitly " + value)
    if any(name.startswith("LD_") and name != "LD_LIBRARY_PATH" for name in environment):
        raise ValueError("additional LD_* loader controls are unsupported")
    if "GLIBC_TUNABLES" in environment:
        raise ValueError("GLIBC_TUNABLES loader controls are unsupported")
    path = environment.get("PATH", os.defpath)
    if any(not item or not Path(item).is_absolute() for item in path.split(os.pathsep)):
        raise ValueError("host PATH entries must be nonempty absolute directories")
    return {"PATH": path, "LANG": "C", "LC_ALL": "C"}


def _preload(report):
    if not os.path.lexists(PRELOAD_FILE):
        return
    identity = {"path": str(PRELOAD_FILE), **file_identity(PRELOAD_FILE, max_bytes=65536)}
    report["identities"]["system_preload"] = identity
    if identity["size_bytes"]:
        contents = read_verified(identity, max_bytes=65536).decode("utf-8")
        if any(line.split("#", 1)[0].strip() for line in contents.splitlines()):
            raise ValueError("system ld.so.preload can preempt the inspected bindings")


def inspect_runtime(data, build, environment):
    """Bind the built ELF loader names to generated files and pinned coreutil."""
    report = {"outcome": "blocked", "blockers": [], "identities": {},
              "bindings": {}, "limitations": list(LIMITATIONS)}
    try:
        validate_manifest(data)
        build = _directory(build)
        vendor = _directory(data["vendor"]["xrt_root"])
        directories = (_directory(build / "sw/runtime"), _directory(vendor / "lib"))
        probe_environment = _environment(environment, directories)
        report["bindings"]["environment"] = {
            key: environment[key] for key in ("LD_LIBRARY_PATH", "VORTEX_DRIVER", "XCL_EMULATION_MODE")}
        _preload(report)
        for role, relative in GENERATED.items():
            report["identities"][role] = _identity(build / relative, executable=role == "demo")
        expected = data["vendor"]["files"]["xrt_coreutil"]
        pinned = safe_path(expected["path"])
        if not pinned.is_relative_to(vendor) or any("xrtsim" in part.lower() for part in pinned.parts):
            raise ValueError("pinned coreutil is not a contained vendor runtime")
        if _identity(pinned) != expected:
            raise ValueError("pinned coreutil identity differs from the manifest")
        report["identities"]["xrt_coreutil"] = dict(expected)

        located = shutil.which("readelf", path=probe_environment["PATH"])
        if located is None:
            raise ValueError("required host readelf is unavailable")
        tool = Path(located).resolve(strict=True)
        if any(tool.is_relative_to(Path(data["vendor"][key]))
               for key in ("vitis_root", "vivado_root", "xrt_root")) or tool.is_relative_to(build):
            raise ValueError("readelf must be a host tool outside the vendor and build roots")
        report["identities"]["readelf"] = _identity(tool, executable=True)
        observations = {}
        for role in (*GENERATED, "xrt_coreutil"):
            target = report["identities"][role]
            code, output = _probe([str(tool), "-h", "-d", "--wide", target["path"]],
                                  environment=probe_environment, timeout=5)
            if (Path(located).resolve(strict=True) != tool
                    or _identity(tool, executable=True) != report["identities"]["readelf"]):
                raise ValueError("host readelf changed during ELF inspection")
            if code != 0:
                raise ValueError("readelf could not inspect " + role)
            if _identity(target["path"], executable=role == "demo") != target:
                raise ValueError("selected ELF changed during inspection: " + role)
            observations[role] = {"header": _header(output, target["size_bytes"]),
                                  **_dynamic(output)}
        report["bindings"]["elf"] = observations

        reference = observations["demo"]["header"]
        for role, observation in observations.items():
            header = observation["header"]
            if role != "demo" and header["type"] != "DYN":
                raise ValueError("runtime library must be an ELF shared object: " + role)
            for field in ("class", "machine", "data"):
                if header[field] != reference[field]:
                    raise ValueError("ELF " + field + " is incompatible with demo: " + role)

        if observations["demo"]["needed"].count("libvortex.so") != 1:
            raise ValueError("demo must directly need libvortex.so")
        if observations["libvortex"]["soname"] != "libvortex.so":
            raise ValueError("generated stub SONAME must be libvortex.so")
        if observations["libvortex_xrt"]["soname"] not in (None, "libvortex-xrt.so"):
            raise ValueError("generated backend SONAME is not libvortex-xrt.so")
        for role, observation in observations.items():
            for name in observation["needed"]:
                if name.startswith("libvortex") and not (role == "demo" and name == "libvortex.so"):
                    raise ValueError("unexpected Vortex library dependency in " + role)
                if "xrt_coreutil" in name and not (role == "libvortex_xrt" and COREUTIL.fullmatch(name)):
                    raise ValueError("unexpected coreutil dependency in " + role)
        needed = [name for name in observations["libvortex_xrt"]["needed"] if COREUTIL.fullmatch(name)]
        if len(needed) != 1:
            raise ValueError("vendor backend must need exactly one libxrt_coreutil.so version")

        checks = (
            ("libvortex", "libvortex.so", "demo", "DT_NEEDED"),
            ("libvortex_xrt", "libvortex-xrt.so", "libvortex", "dlopen"),
            ("xrt_coreutil", needed[0], "libvortex_xrt", "DT_NEEDED"),
        )
        for role, name, requester, kind in checks:
            report["bindings"][role] = {
                "requester": report["identities"][requester]["path"],
                "kind": kind, "name": name,
                **_resolve(name, directories, report["identities"][role]),
            }
        for role, name, _, _ in checks:
            observed = _resolve(name, directories, report["identities"][role])
            if any(report["bindings"][role][key] != value for key, value in observed.items()):
                raise ValueError("runtime lookup changed during inspection: " + role)
        preload = {"identities": {}}
        _preload(preload)
        if preload["identities"].get("system_preload") != report["identities"].get("system_preload"):
            raise ValueError("system preload configuration changed during inspection")
        for role, identity in report["identities"].items():
            if role == "system_preload":
                observed = {"path": identity["path"], **file_identity(identity["path"], max_bytes=65536)}
            else:
                observed = _identity(identity["path"], executable=role in ("demo", "readelf"))
            if observed != identity:
                raise ValueError("runtime identity changed during inspection: " + role)
    except (OSError, ValueError, RuntimeError, UnicodeError, TypeError, KeyError) as error:
        report["blockers"].append("runtime loader binding: " + str(error))
    return _finish(report)

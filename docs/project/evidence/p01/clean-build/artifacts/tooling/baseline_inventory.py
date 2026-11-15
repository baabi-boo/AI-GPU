# Licensed under the Apache License, Version 2.0.
"""Read-only identities for a native baseline execution packet."""

import hashlib
import json
import os
from pathlib import Path
import re
import selectors
import signal
import stat
import subprocess
import sys
import tempfile
import time

import preflight


TOOLCHAIN_COMMIT = "e3db4bcdf819a17f618ad9fc2472f8f7dea3192b"
TOOLCHAIN_TAG = "v3.0.2"
TOOLCHAIN_REPOSITORY = "vortexgpgpu/vortex-toolchain-prebuilt"
# Bind caller-supplied archive identities to the reviewed lock, not just its revision label.
TOOLCHAIN_MANIFEST_SHA256 = "f7638b92912ee8b61640d32431814e676950124b9455649f16400cb54b2a4eb3"
OS_BUNDLE = "ubuntu/focal"
MAX_PROBE_BYTES = 65536
GENERATED_PATHS = (
    ".config.stamp", "config.mk", "sw/VX_config.h", "sw/VX_types.h",
    "hw/VX_config.vh", "hw/VX_types.vh", "ci/blackbox.sh",
)
SOURCE_INPUTS = (
    "VERSION", ".gitmodules", "configure", "config.mk.in", "VX_config.toml",
    "VX_types.toml", "ci/gen_config.py", "ci/blackbox.sh",
)
COPIED_BUILD_INPUTS = {
    "ci/gen_config.py": "ci/gen_config.py",
    "sw/kernel/Makefile": "sw/kernel/Makefile",
    "sw/runtime/common.mk": "sw/runtime/common.mk",
    "sw/runtime/stub/Makefile": "sw/runtime/stub/Makefile",
    "sw/runtime/simx/Makefile": "sw/runtime/simx/Makefile",
    "sw/runtime/rtlsim/Makefile": "sw/runtime/rtlsim/Makefile",
    "sim/common.mk": "sim/common.mk",
    "sim/simx/Makefile": "sim/simx/Makefile",
    "sim/rtlsim/Makefile": "sim/rtlsim/Makefile",
    "sim/rtlsim/verilator.vlt": "sim/rtlsim/verilator.vlt.in",
    "tests/regression/common.mk": "tests/regression/common.mk",
    "tests/regression/sgemm_tcu/Makefile": "tests/regression/sgemm_tcu/Makefile",
    "tests/regression/flash_attn_tcu_wg/Makefile": "tests/regression/flash_attn_tcu_wg/Makefile",
}
GENERATED_HEADERS = (
    "sw/VX_config.h", "hw/VX_config.vh", "sw/VX_types.h", "hw/VX_types.vh",
)
TOOL_BINARIES = {
    "riscv_gcc": "riscv64-gnu-toolchain/bin/riscv64-unknown-elf-gcc",
    "llvm_clang": "llvm-vortex/bin/clang",
    "verilator": "verilator/bin/verilator",
    "verilator_binary": "verilator/bin/verilator_bin",
}
LIBRARIES = (
    "libc64/lib/libc.a", "libc64/lib/libm.a",
    "libcrt64/lib/baremetal/libclang_rt.builtins-riscv64.a",
)


def _probe(argv, cwd=None, environment=None, timeout=10):
    """Read a bounded subprocess output without retaining stderr or descendants."""
    process = None
    try:
        process = subprocess.Popen(
            argv, cwd=cwd, env=environment, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, start_new_session=True,
        )
        output = bytearray()
        deadline = time.monotonic() + timeout
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ)
            while selector.get_map():
                if time.monotonic() >= deadline:
                    raise ValueError("identity probe timed out")
                for key, _ in selector.select(min(0.1, max(0, deadline - time.monotonic()))):
                    chunk = os.read(key.fileobj.fileno(), 8192)
                    if not chunk:
                        selector.unregister(key.fileobj)
                        continue
                    output.extend(chunk)
                    if len(output) > MAX_PROBE_BYTES:
                        raise ValueError("identity probe output exceeded its limit")
            process.wait(timeout=max(0.001, deadline - time.monotonic()))
        return process.returncode, bytes(output)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise ValueError("identity probe unavailable") from error
    finally:
        if process is not None:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait()
            if process.stdout is not None:
                process.stdout.close()


def _git(root, *arguments):
    environment = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    environment["GIT_OPTIONAL_LOCKS"] = "0"
    code, output = _probe(
        ["git", "--no-optional-locks", "-c", "core.fsmonitor=false", "-c",
         "core.untrackedCache=false", "-C", str(root), *arguments],
        environment=environment,
    )
    if code != 0:
        raise ValueError("Git identity observation failed")
    return output


def _digest(path):
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        before = os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode):
            raise ValueError("identity is not a regular file")
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
            size += len(chunk)
        after = os.fstat(stream.fileno())
        if (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (
                after.st_size, after.st_mtime_ns, after.st_ctime_ns) or size != after.st_size:
            raise ValueError("identity changed while it was being read")
    return digest.hexdigest(), size


def hash_artifacts(root, relative_paths):
    root = Path(root).resolve(strict=True)
    if not root.is_dir():
        raise ValueError("artifact root is not a directory")
    artifacts = []
    seen = set()
    for name in relative_paths:
        if (not isinstance(name, str) or not name or "\\" in name
                or Path(name).is_absolute() or ".." in Path(name).parts
                or name in seen or any(ord(c) < 32 for c in name)):
            raise ValueError("invalid or duplicate artifact path")
        seen.add(name)
        try:
            path = (root / name).resolve(strict=True)
            if not path.is_relative_to(root) or not stat.S_ISREG(path.stat().st_mode):
                raise ValueError("artifact is not a contained regular file")
            digest, size = _digest(path)
        except (OSError, RuntimeError) as error:
            raise ValueError("artifact is missing or unreadable") from error
        artifacts.append({"path": name, "sha256": digest, "size_bytes": size})
    return artifacts


def _finish(report):
    report["outcome"] = "blocked" if report["blockers"] else "pass"
    return report


def collect_source(root):
    report = {"revision": None, "tree": None, "dirty": None,
              "changed_paths": [], "untracked_paths": [], "submodules": {},
              "pins": {}, "blockers": []}
    try:
        root = Path(root).resolve(strict=True)
        toplevel = _git(root, "rev-parse", "--show-toplevel").decode().strip()
        if Path(toplevel).resolve() != root:
            raise ValueError("source root is not the Git checkout root")
        for key, ref in (("revision", "HEAD"), ("tree", "HEAD^{tree}")):
            value = _git(root, "rev-parse", "--verify", ref).decode("ascii").strip()
            if not re.fullmatch(r"[0-9a-f]{40}", value):
                raise ValueError("source identity is malformed")
            report[key] = value
        status = _git(root, "status", "--porcelain=v1", "-z", "--untracked-files=all",
                      "--ignore-submodules=none")
        entries = status.split(b"\0")
        index = 0
        while index < len(entries):
            entry = entries[index]
            index += 1
            if not entry:
                continue
            if len(entry) < 4 or entry[2:3] != b" ":
                raise ValueError("unrecognized source status")
            flags = entry[:2].decode("ascii")
            name = entry[3:].decode("utf-8")
            if Path(name).is_absolute() or ".." in Path(name).parts or any(ord(c) < 32 for c in name):
                raise ValueError("unsafe filename in source status")
            report["untracked_paths" if flags == "??" else "changed_paths"].append(name)
            if "R" in flags or "C" in flags:
                index += 1
        report["dirty"] = bool(report["changed_paths"] or report["untracked_paths"])
        if report["dirty"]:
            report["blockers"].append("source contains tracked changes or nonignored untracked inputs")
        report["pins"], pin_errors = preflight.read_pins(root)
        report["blockers"].extend(pin_errors)
        report["submodules"] = preflight.submodule_inventory(root)
        report["blockers"].extend(report["submodules"]["errors"])
        for entry in report["submodules"]["entries"]:
            if entry["status"] != "initialized":
                report["blockers"].append("submodule is not at its recorded revision: " + entry["path"])
        report["inputs"] = hash_artifacts(root, list(SOURCE_INPUTS))
    except (ValueError, OSError, RuntimeError, UnicodeError):
        report["blockers"].append("source identity could not be completely verified")
    return _finish(report)


def _expected_bundle_paths():
    expected = set()
    for component, letters in (("riscv64-gnu-toolchain", "abcdefghij"),
                               ("llvm-vortex", "abc"), ("verilator", "abc")):
        expected.update(f"{component}/{OS_BUNDLE}/{component}.tar.bz2.parta{x}" for x in letters)
    expected.update(("libc64/libc64.tar.bz2", "libcrt64/libcrt64.tar.bz2"))
    return expected


def manifest_digest(manifest):
    canonical = dict(manifest, parts=sorted(manifest["parts"], key=lambda item: item["path"]))
    return hashlib.sha256(json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _unique_fields(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON field")
        result[key] = value
    return result


def _bundle_identity(path):
    path = Path(path)
    if not path.is_file() or path.stat().st_size > 1024 * 1024:
        raise ValueError("bundle manifest is missing or oversized")
    data = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_unique_fields)
    if (not isinstance(data, dict) or data.get("repository") != TOOLCHAIN_REPOSITORY
            or data.get("tag") != TOOLCHAIN_TAG or data.get("revision") != TOOLCHAIN_COMMIT
            or data.get("os_bundle") != OS_BUNDLE or not isinstance(data.get("parts"), list)):
        raise ValueError("bundle manifest has the wrong immutable pin")
    paths = []
    for item in data["parts"]:
        if (not isinstance(item, dict) or not isinstance(item.get("path"), str)
                or type(item.get("size_bytes")) is not int or item["size_bytes"] <= 0
                or not re.fullmatch(r"[0-9a-f]{40}", str(item.get("git_blob_sha", "")))
                or not re.fullmatch(r"[0-9a-f]{64}", str(item.get("sha256", "")))):
            raise ValueError("bundle manifest contains a malformed part")
        paths.append(item["path"])
    if len(paths) != len(set(paths)) or set(paths) != _expected_bundle_paths():
        raise ValueError("bundle manifest does not identify every required archive part")
    if manifest_digest(data) != TOOLCHAIN_MANIFEST_SHA256:
        raise ValueError("bundle manifest differs from the reviewed immutable lock")
    digest, size = _digest(path)
    return {"sha256": digest, "size_bytes": size, "repository": TOOLCHAIN_REPOSITORY,
            "revision": TOOLCHAIN_COMMIT, "tag": TOOLCHAIN_TAG, "os_bundle": OS_BUNDLE,
            "parts": data["parts"]}


def collect_tools(tool_dir, bundle_manifest=None):
    report = {"toolchain_commit": TOOLCHAIN_COMMIT, "toolchain_tag": TOOLCHAIN_TAG,
              "os_bundle": OS_BUNDLE, "bundle_manifest": None, "tools": {},
              "libraries": [], "blockers": [], "limitations": [
                  "Installed file hashes and archive identities are observations; this inventory does not re-extract archives to prove their relationship."]}
    try:
        root = Path(tool_dir).resolve(strict=True)
        if not root.is_dir():
            raise ValueError("tool directory is not a directory")
    except (OSError, ValueError, RuntimeError):
        report["blockers"].append("tool directory is unavailable")
        return _finish(report)
    if bundle_manifest is None:
        report["blockers"].append("immutable bundle manifest was not supplied")
    else:
        try:
            report["bundle_manifest"] = _bundle_identity(bundle_manifest)
        except (OSError, ValueError, RuntimeError, UnicodeError):
            report["blockers"].append("immutable bundle manifest could not be verified")
    for name, relative in TOOL_BINARIES.items():
        try:
            identity = hash_artifacts(root, [relative])[0]
            executable = (root / relative).resolve(strict=True)
            if not os.access(executable, os.X_OK):
                raise ValueError("tool is not executable")
            code, output = _probe([str(executable), "--version"])
            if code != 0:
                raise ValueError("tool version probe failed")
            lines = output.decode("utf-8").splitlines()
            if not lines or not lines[0].strip():
                raise ValueError("tool version is empty")
            version = re.sub(r"(?:[A-Za-z]:)?/[^\s]+", "<path>", lines[0].strip())[:512]
            identity["version"] = version
            report["tools"][name] = identity
        except (OSError, ValueError, RuntimeError, UnicodeError):
            report["blockers"].append("required tool identity unavailable: " + name)
    for relative in LIBRARIES:
        try:
            report["libraries"].extend(hash_artifacts(root, [relative]))
        except (OSError, ValueError, RuntimeError):
            report["blockers"].append("required library identity unavailable: " + relative)
    return _finish(report)


def _instantiate(contents, replacements):
    for name, value in replacements.items():
        contents = contents.replace("@" + name + "@", value)
    return contents


def _verify_build_copies(build, source, replacements):
    generated = hash_artifacts(build, list(COPIED_BUILD_INPUTS))
    inputs = hash_artifacts(source, list(COPIED_BUILD_INPUTS.values()))
    for destination, origin in COPIED_BUILD_INPUTS.items():
        expected = (source / origin).read_bytes()
        if origin.endswith(".in"):
            expected = _instantiate(expected.decode("utf-8"), replacements).encode("utf-8")
        if (build / destination).read_bytes() != expected:
            raise ValueError("copied build input differs from its source: " + destination)
    return generated, inputs


def _verify_generated_headers(build, source, xlen):
    environment = {"PATH": os.defpath, "XLEN": str(xlen), "LANG": "C",
                   "LC_ALL": "C", "PYTHONUTF8": "1"}
    with tempfile.TemporaryDirectory(prefix="ai-gpu-baseline-headers-") as temporary:
        for relative in GENERATED_HEADERS:
            name = Path(relative).name
            stem = Path(relative).stem
            output = Path(temporary) / name
            arguments = [sys.executable, "-I", "-S", "-B", str(source / "ci/gen_config.py"),
                         "--config", str(source / (stem + ".toml")),
                         "--output", str(output), "--format",
                         "cpp" if relative.startswith("sw/") else "verilog"]
            if stem == "VX_types":
                arguments.append("--resolved")
            code, _ = _probe(arguments, cwd=temporary, environment=environment)
            if code != 0:
                raise ValueError("reference header generation failed")
            identity = hash_artifacts(temporary, [name])[0]
            if identity["size_bytes"] > 1024 * 1024:
                raise ValueError("reference generated header exceeds its limit")
            if output.read_bytes() != (build / relative).read_bytes():
                raise ValueError("generated header differs from its source: " + relative)


def collect_build(build_dir, source_root):
    report = {"xlen": None, "profile": None, "os_bundle": None,
              "identity_matches": False, "generated": [], "source_inputs": [],
              "build_inputs": [], "source_build_inputs": [],
              "blockers": [], "limitations": [
                  "Generated headers and the native baseline build recipes are compared with source; successful compilation and execution require separate command results."]}
    try:
        build = Path(build_dir).resolve(strict=True)
        source = Path(source_root).resolve(strict=True)
        if (not build.is_dir() or not source.is_dir() or build == source
                or source.is_relative_to(build)):
            raise ValueError("build must be separate from the source directory")
        if build.is_relative_to(source):
            relative = build.relative_to(source)
            if len(relative.parts) != 1 or not relative.name.startswith("build"):
                raise ValueError("build directory overlaps source inputs")
        stamp_path = build / ".config.stamp"
        config_path = build / "config.mk"
        report["generated"] = hash_artifacts(build, list(GENERATED_PATHS))
        report["source_inputs"] = hash_artifacts(source, list(SOURCE_INPUTS))
        if stamp_path.stat().st_size > 16384 or config_path.stat().st_size > 1024 * 1024:
            raise ValueError("generated configuration is oversized")
        stamp = {}
        for token in stamp_path.read_text(encoding="utf-8").strip().split():
            key, sep, value = token.partition("=")
            if not sep or key in stamp:
                raise ValueError("generated configuration stamp is malformed")
            stamp[key] = value
        replacements = {
            "VORTEX_HOME": stamp["SOURCE_DIR"], "XLEN": stamp["XLEN"],
            "TOOLDIR": stamp["TOOLDIR"], "OSVERSION": stamp["OSVERSION"],
            "INSTALLDIR": stamp["PREFIX"], "BUILDDIR": stamp["BUILDDIR"],
            "TOOLCHAIN_REV": stamp["TOOLCHAIN_REV"],
            "VORTEX_VERSION": stamp["VORTEX_VERSION"],
            "GEM5_REV": stamp["GEM5_REV"], "PROFILE": stamp["PROFILE"],
            "FIRESIM_REV": stamp["FIRESIM_REV"],
        }
        expected = _instantiate((source / "config.mk.in").read_text(encoding="utf-8"), replacements)
        if config_path.read_text(encoding="utf-8") != expected:
            raise ValueError("generated configuration differs from its source template")
        config = dict(re.findall(r"^([A-Z_]+)[ \t]*\?=[ \t]*(.*?)[ \t]*$",
                                 config_path.read_text(encoding="utf-8"), re.MULTILINE))
        if (Path(stamp.get("SOURCE_DIR", "")).resolve() != source
                or Path(stamp.get("BUILDDIR", "")).resolve() != build
                or Path(config.get("VORTEX_HOME", "")).resolve() != source
                or stamp.get("TOOLDIR") != config.get("TOOLDIR")
                or stamp.get("XLEN") != config.get("XLEN")
                or stamp.get("PROFILE") != config.get("PROFILE")
                or stamp.get("OSVERSION") != config.get("OSVERSION")):
            raise ValueError("generated configuration points to a different source or build")
        report["xlen"] = int(stamp["XLEN"])
        report["profile"] = stamp["PROFILE"]
        report["os_bundle"] = stamp["OSVERSION"]
        if report["xlen"] != 64 or report["profile"] or report["os_bundle"] != OS_BUNDLE:
            raise ValueError("generated configuration does not match the native RV64 baseline")
        pins, errors = preflight.read_pins(source)
        if errors or any(stamp.get(key) != value for key, value in pins.items()):
            raise ValueError("generated configuration has stale version pins")
        if (build / "ci/blackbox.sh").read_bytes() != (source / "ci/blackbox.sh").read_bytes():
            raise ValueError("generated runner is stale")
        for relative in GENERATED_HEADERS:
            stem = Path(relative).stem
            inputs = [source / (stem + ".toml"), source / "ci/gen_config.py", stamp_path]
            if any(item.stat().st_mtime_ns > (build / relative).stat().st_mtime_ns for item in inputs):
                raise ValueError("generated headers are older than their inputs")
        report["build_inputs"], report["source_build_inputs"] = _verify_build_copies(
            build, source, replacements)
        _verify_generated_headers(build, source, report["xlen"])
        report["identity_matches"] = True
    except (OSError, ValueError, RuntimeError, UnicodeError, KeyError):
        report["blockers"].append("build provenance is missing, stale, incompatible or points outside its source")
    return _finish(report)

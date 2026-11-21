# SPDX-License-Identifier: Apache-2.0
"""Build a HOST-ONLY fault runtime and an independently pinned test extension.

No result from this module establishes accelerator numerics or qualification.
The fake DSO returns synthetic words or immutable P04 fixture responses after
checking actual transferred stage inputs. Production setup.py rejects its
deliberately different manifest contract. No production code receives a test
hook, environment bypass, verification callback, or reference array.

Example in a host unittest (run each bundle/format in a fresh subprocess)::

    with tempfile.TemporaryDirectory() as work:
        runtime = build_test_runtime(Path(work) / "fp16")
        runtime.run_python('''
from p05_test_runtime import FaultControls
from vortex_ai import Session, Tensor
import os
bundle = os.environ["P05_TEST_BUNDLE"]
controls = FaultControls.activate(bundle)  # load through verifier, then ctypes
session = Session.open(bundle)
controls.fail("buffer_create", occurrence=2)
operation = session.submit(
    Tensor(bytes(128), dtype="fp16", shape=(8, 8), layout="row_major"),
    Tensor(bytes(64), dtype="fp16", shape=(8, 4), layout="column_major"))
assert operation.close().complete
assert session.close().ok
controls.assert_no_resources()
''')

``select_case(name)`` applies to the NEXT native device opened, before calling
``session.model(name)``. Existing owners retain their own response selection.
Fault occurrences are relative to subsequent calls; separate named faults may
be armed together. Cleanup errors release the actual fake resource and then
report failure, matching the P03 host test's semantics.

The production loader intentionally rejects preloaded project DSOs, including
this fake. ``activate`` opens/closes one session before obtaining control
symbols. To test the FIRST open, run a fresh child with the fake-only variable
``P05_TEST_INITIAL_FAILURE=device_open:1:6`` and load ``FaultControls`` after
the failing Session.open attempt. Never preload libvortex.so for those tests.
"""

from __future__ import annotations

import argparse
import ctypes
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import sysconfig
import tempfile


ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "ci/project/fixtures/p05_python_runtime.cpp"
SCOPE = "host-only-fault-injection"
RESOURCE_NAMES = ("devices", "modules", "kernels", "queues", "buffers", "events", "bytes")
ARTIFACTS = (
    ("ramulator", "lib/libramulator.so"),
    ("ramulator_extension", "lib/libramulator-vortex.so"),
    ("runtime", "lib/libvortex.so"),
    ("simulator", "lib/libsimx.so"),
    ("backend", "lib/libvortex-simx.so"),
    ("module", "kernel.vxbin"),
)
VX_FUNCTIONS = frozenset((
    "vx_device_open", "vx_device_release", "vx_device_query", "vx_device_memory_info",
    "vx_module_load_bytes", "vx_module_release", "vx_module_get_kernel", "vx_kernel_release",
    "vx_queue_create", "vx_queue_release", "vx_buffer_create", "vx_buffer_address",
    "vx_buffer_release", "vx_enqueue_write", "vx_enqueue_launch", "vx_enqueue_read",
    "vx_event_wait_value", "vx_event_get_value", "vx_event_get_profiling", "vx_event_release",
))
EXTENSION_SOURCES = (
    "python/native/module.cpp", "python/native/runtime_loader.cpp",
    "sw/runtime/ai/contract.cpp", "sw/runtime/ai/runtime.cpp",
    "sw/runtime/ai/mlp_host.cpp", "sw/runtime/ai/mlp_runtime.cpp",
)
INCLUDE_DIRS = (
    "python/native", "sw/runtime/ai", "sw/runtime/include", "sw/common", "tests/regression/ai_mlp",
)


def _digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _canonical(value):
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()


def _run(command, *, cwd, env=None, timeout=90):
    result = subprocess.run(command, cwd=cwd, env=env, capture_output=True, text=True,
                            timeout=timeout, check=False)
    if result.returncode:
        raise AssertionError(
            f"Host-only command failed ({result.returncode}): {command!r}\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}")
    return result


@dataclass(frozen=True)
class TestRuntime:
    """Paths from a direct test build; this is not a production wheel or bundle."""

    root: Path
    bundle: Path
    package_root: Path
    extension: Path
    build_config: Path
    dtype: str
    commands: tuple[tuple[str, ...], ...]

    @property
    def runtime(self):
        return self.bundle / "lib/libvortex.so"

    def environment(self, overrides=None):
        env = os.environ.copy()
        # Start the verifier in its ordinary supported environment. These are
        # loader settings, not a replacement for verification or a test bypass.
        for key in ("LD_PRELOAD", "LD_AUDIT", "LD_LIBRARY_PATH", "VORTEX_DRIVER",
                    "VORTEX_AI_BUNDLE", "P05_TEST_INITIAL_FAILURE"):
            env.pop(key, None)
        env.update({
            "PYTHONPATH": os.pathsep.join((str(self.package_root), str(ROOT / "ci/project"))),
            "PYTHONDONTWRITEBYTECODE": "1",
            "P05_TEST_BUNDLE": str(self.bundle),
            "P05_TEST_DTYPE": self.dtype,
            "UBSAN_OPTIONS": "halt_on_error=1:print_stacktrace=1",
        })
        if overrides:
            env.update(overrides)
        return env

    def run_python(self, source, *, env=None, timeout=30, check=True):
        result = subprocess.run([sys.executable, "-c", source], cwd=self.root,
                                env=self.environment(env), capture_output=True,
                                text=True, timeout=timeout, check=False)
        if check and result.returncode:
            raise AssertionError(
                f"Host-only child failed ({result.returncode})\n"
                f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}")
        return result


def build_test_runtime(directory, *, dtype="fp16", compiler=None, sanitize=True):
    """Compile the five-DSO fake bundle and real native extension in an empty dir.

    The generated pin binds exact manifest bytes and six artifact sizes/hashes.
    Its manifest's schema/contract explicitly excludes production qualification.
    Builds are sequential, bounded host C++17 compilations; no GPU build or
    toolchain installation is performed. ``sanitize`` enables UBSan by default.
    """
    if dtype not in ("fp16", "bf16"):
        raise ValueError("test format must be fp16 or bf16")
    compiler = compiler or shutil.which("c++") or shutil.which("g++") or shutil.which("clang++")
    if not compiler:
        raise AssertionError("P05 native boundary tests require a C++17 compiler")
    directory = Path(directory).absolute()
    directory.mkdir(parents=True, exist_ok=True)
    if any(directory.iterdir()):
        raise ValueError("host-only build directory must be empty")
    bundle = directory / "bundle"
    library = bundle / "lib"
    package_root = directory / "python"
    package = package_root / "vortex_ai"
    generated = directory / "generated"
    library.mkdir(parents=True)
    package.mkdir(parents=True)
    generated.mkdir()
    commands = []

    def run(command):
        command = [str(item) for item in command]
        commands.append(tuple(command))
        result = _run(command, cwd=directory)
        with (directory / "build.log").open("a", encoding="utf-8") as output:
            output.write(json.dumps(command) + "\n" + result.stdout + result.stderr)
        return result

    flags = ["-std=c++17", "-shared", "-fPIC", "-O1", "-g0", "-fvisibility=hidden", "-pthread"]
    if sanitize:
        flags += ["-fsanitize=undefined", "-fno-sanitize-recover=undefined"]
    includes = [item for relative in INCLUDE_DIRS for item in ("-I", str(ROOT / relative))]
    exports = generated / "fake.exports"
    exports.write_text("{ global: vx_*; p05_test_*; local: *; };\n", encoding="utf-8")
    run([compiler, *flags, "-Wall", "-Wextra", "-Werror", *includes, FIXTURE,
         "-Wl,-z,defs", "-Wl,-soname,libvortex.so", f"-Wl,--version-script={exports}",
         "-o", library / "libvortex.so"])
    dummy = generated / "dummy.cpp"
    dummy.write_text(
        "// HOST-ONLY loader identity fixture; no simulator or backend execution.\n"
        '#if defined(P05_TEST_BACKEND)\nextern "C" __attribute__((visibility("default"))) '
        "void vx_dev_init() {}\n#endif\n", encoding="utf-8")
    for role, relative in ARTIFACTS:
        if role in ("runtime", "module"):
            continue
        path = bundle / relative
        backend = ["-DP05_TEST_BACKEND=1"] if role == "backend" else []
        run([compiler, *flags, *backend, dummy, f"-Wl,-soname,{path.name}", "-o", path])
    (bundle / "kernel.vxbin").write_bytes(b"P05-HOST-ONLY-FAKE-MODULE\x00" + bytes(range(40)))
    artifact_rows = [dict(role=role, path=relative, sha256=_digest(bundle / relative),
                          size=(bundle / relative).stat().st_size) for role, relative in ARTIFACTS]
    # Include transitive native/header and Python files, plus this actual fake.
    sources = {ROOT / relative for relative in EXTENSION_SOURCES}
    for relative in INCLUDE_DIRS:
        sources.update((ROOT / relative).glob("*.h"))
    sources.update((ROOT / "python/vortex_ai").glob("*.py"))
    sources.update((FIXTURE, Path(__file__).resolve()))
    inventory = [dict(path=str(path.relative_to(ROOT)), sha256=_digest(path), size=path.stat().st_size)
                 for path in sorted(sources) if path.name != "p05_build_config.h"]
    source_digest = hashlib.sha256(_canonical(inventory)).hexdigest()
    revision = _run(["git", "rev-parse", "HEAD"], cwd=ROOT).stdout.strip()
    qualification_id = hashlib.sha256(b"HOST-ONLY: NOT NATIVE QUALIFICATION").hexdigest()
    manifest = {
        "schema_version": 0, "contract_id": "p05-host-only-fault-bundle-v1",
        "scope": SCOPE, "arithmetic": "synthetic-pattern-or-immutable-fixture-response",
        "backend": "simx", "format": dtype, "source_revision": revision,
        "source_sha256": source_digest, "qualification_id": qualification_id,
        "binding_sources": inventory, "artifacts": artifact_rows,
    }
    manifest_bytes = _canonical(manifest)
    (bundle / "manifest.json").write_bytes(manifest_bytes)
    values = {
        "bundle_sha256": hashlib.sha256(manifest_bytes).hexdigest(), "source_sha256": source_digest,
        "backend": "simx", "format": dtype, "qualification_id": qualification_id,
        "source_revision": revision,
    }
    header = [
        "// HOST-ONLY generated test pin; production setup rejects this receipt.",
        "#pragma once", "#include <array>", "#include <cstdint>",
        "namespace vortex_ai_python::build {",
        "struct Artifact { const char* role; const char* path; const char* sha256; std::uint64_t size; };",
    ]
    header.extend(f"inline constexpr char {name}[] = {json.dumps(value)};" for name, value in values.items())
    header.append("inline constexpr std::array<Artifact, 6> artifacts{{")
    for row in artifact_rows:
        fields = [json.dumps(row[key]) for key in ("role", "path", "sha256")]
        header.append("  {" + ", ".join((*fields, str(row["size"]) + "ULL")) + "},")
    header.extend(("}};", "}", ""))
    build_config = generated / "p05_build_config.h"
    build_config.write_text("\n".join(header), encoding="utf-8")
    for source in (ROOT / "python/vortex_ai").glob("*.py"):
        shutil.copyfile(source, package / source.name)
    extension = package / ("_native" + sysconfig.get_config_var("EXT_SUFFIX"))
    run([compiler, *flags, "-I", generated, "-I", sysconfig.get_paths()["include"],
         *includes, *(ROOT / source for source in EXTENSION_SOURCES), "-ldl", "-o", extension])
    # Record exact exports and assert the required 20-symbol runtime boundary.
    symbols = run(["nm", "-D", "--defined-only", library / "libvortex.so"]).stdout
    vx_symbols = {line.split()[-1] for line in symbols.splitlines() if line.split()[-1].startswith("vx_")}
    if vx_symbols != VX_FUNCTIONS:
        raise AssertionError(f"Wrong fake vx_* export surface: {sorted(vx_symbols ^ VX_FUNCTIONS)}")
    if sorted(path.name for path in library.iterdir()) != sorted(Path(relative).name for _, relative in ARTIFACTS[:-1]):
        raise AssertionError("Test lib directory must contain exactly five pinned DSOs")
    for row in inventory:
        if _digest(ROOT / row["path"]) != row["sha256"]:
            raise AssertionError("Test source changed during host compilation: " + row["path"])
    (directory / "build_commands.json").write_bytes(_canonical({"scope": SCOPE, "commands": commands}))
    return TestRuntime(directory, bundle, package_root, extension, build_config, dtype, tuple(commands))


class FaultControls:
    """ctypes controls exported ONLY by the host fake libvortex DSO.

    Construct after a native Session.open attempt has loaded the verified bundle.
    ``activate`` performs that bootstrap and resets its completed counters.
    """

    def __init__(self, bundle):
        self.bundle = Path(bundle).absolute()
        # RTLD_NOLOAD is crucial: this must not silently preload a DSO and change
        # the production loader's before-first-open identity behavior.
        mode = os.RTLD_NOW | os.RTLD_LOCAL | os.RTLD_NOLOAD
        self.library = ctypes.CDLL(str(self.bundle / "lib/libvortex.so"), mode=mode)
        signatures = {
            "reset": ([], ctypes.c_int),
            "fail": ([ctypes.c_char_p, ctypes.c_uint64, ctypes.c_int], ctypes.c_int),
            "clear_failures": ([], ctypes.c_int),
            "timeout": ([ctypes.c_uint64], ctypes.c_int),
            "async_failure": ([ctypes.c_uint, ctypes.c_int], ctypes.c_int),
            "select_case": ([ctypes.c_char_p], ctypes.c_int),
            "bad_address": ([ctypes.c_uint], ctypes.c_int),
            "threads": ([ctypes.c_uint], ctypes.c_int),
            "corrupt_response": ([ctypes.c_int, ctypes.c_uint64, ctypes.c_uint32], ctypes.c_int),
            "counter": ([ctypes.c_char_p], ctypes.c_int64),
            "owner_counter": ([ctypes.c_uint64, ctypes.c_char_p], ctypes.c_int64),
            "counters_json": ([], ctypes.c_char_p),
            "captures_json": ([], ctypes.c_char_p),
        }
        for name, (arguments, result) in signatures.items():
            function = getattr(self.library, "p05_test_" + name)
            function.argtypes = arguments
            function.restype = result

    @classmethod
    def activate(cls, bundle):
        from vortex_ai import Session
        session = Session.open(str(bundle))
        status = session.close()
        if not status.ok:
            raise AssertionError(f"Host-only control bootstrap failed to close: {status}")
        controls = cls(bundle)
        controls.reset()
        return controls

    def _set(self, name, *args):
        code = getattr(self.library, "p05_test_" + name)(*args)
        if code:
            raise AssertionError(f"Host-only control {name}{args!r} failed with code {code}")

    def reset(self):
        self._set("reset")

    def fail(self, name, occurrence=1, code=-1):
        self._set("fail", name.encode("ascii"), occurrence, code)

    def clear_failures(self):
        self._set("clear_failures")

    def timeout(self, budget=1):
        self._set("timeout", budget)

    def async_failure(self, ordinal, code=6):
        self._set("async_failure", ordinal, code)

    def select_case(self, case_id):
        self._set("select_case", case_id.encode("ascii"))

    def bad_address(self, mode):
        self._set("bad_address", mode)

    def threads(self, count):
        self._set("threads", count)

    def corrupt_response(self, stage, word=0, xor_bits=1):
        self._set("corrupt_response", stage, word, xor_bits)

    def counter(self, name, *, owner=None):
        if owner is None:
            value = self.library.p05_test_counter(name.encode("ascii"))
        else:
            value = self.library.p05_test_owner_counter(owner, name.encode("ascii"))
        if value < 0:
            raise KeyError((owner, name))
        return value

    @property
    def counters(self):
        return json.loads(self.library.p05_test_counters_json())

    @property
    def captures(self):
        return json.loads(self.library.p05_test_captures_json())

    def assert_no_resources(self):
        actual = self.counters
        if any(actual["resources"].values()) or actual["premature"] or actual["contract_errors"]:
            raise AssertionError(f"Host-only runtime did not cleanly release resources: {actual}")


def _main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build-dir", type=Path)
    parser.add_argument("--format", choices=("fp16", "bf16"), default="fp16")
    parser.add_argument("--no-sanitize", action="store_true")
    args = parser.parse_args()
    directory = args.build_dir
    if directory is None:
        directory = Path(tempfile.mkdtemp(prefix="p05-host-only-"))
    result = build_test_runtime(directory, dtype=args.format, sanitize=not args.no_sanitize)
    print(json.dumps({"scope": SCOPE, "bundle": str(result.bundle),
                      "pythonpath": str(result.package_root), "extension": str(result.extension),
                      "build_commands": str(result.root / "build_commands.json")}, sort_keys=True))


if __name__ == "__main__":
    _main()

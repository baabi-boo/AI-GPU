# SPDX-License-Identifier: Apache-2.0
"""Synthetic host-only P06 packets for replay tests, never GPU evidence.

The real runner writes the packet around the existing mocked process harness.
Source bodies come from an explicit input inventory copied into a temporary
tree. Source, build, output, and tool trees are deleted before this function
returns. No compiler, simulator, archived code, or downloaded tool is executed.
"""

import hashlib
import json
from pathlib import Path
import re
import sys
import unittest
from unittest import mock
import zipfile

import baseline_inventory
from baseline_process import LIMITATIONS as PROCESS_LIMITATIONS
import p04_model_contract
import test_p06_runner as harness_module
from p06_test_samples import REVISION


runner = harness_module.runner
ROOT = runner.ROOT
# Observed in a fresh import of the native entry point, without any test module.
# This is deliberately independent of p06_replay.RUNNER_HELPERS.
NATIVE_HELPERS = tuple(sorted("ci/project/" + name + ".py" for name in (
    "baseline_inventory", "baseline_matrix", "baseline_packet_contract",
    "baseline_packet_io", "baseline_process", "compiler_records",
    "p02_fixture_oracle", "p02_layout_fixture_oracle", "p02_matrix",
    "p02_matrix_records", "p02_wmma_fixtures", "p02_wmma_numerical_fixture_oracle",
    "p03_execute", "p03_execution_records", "p04_execute", "p04_execution_records",
    "p04_fixture_adapter", "p04_model_contract", "p04_reference",
    "p06_compiler_records", "p06_contract", "p06_execute", "p06_records", "preflight",
)))
HOST_TOOLS = ("make", "g++", "gcc", "ar", "as", "ld", "python3", "bash", "perl")
TOOL_PATHS = {
    **{name: "llvm-vortex/bin/" + name
       for name in ("clang", "clang++", "llvm-objcopy", "llvm-objdump")},
    **{"riscv-" + name: "riscv64-gnu-toolchain/bin/riscv64-unknown-elf-" + name
       for name in ("gcc", "gcc-ar", "objdump", "objcopy")},
    **{name: name for name in ("libc64/lib/libc.a", "libc64/lib/libm.a",
                             "libcrt64/lib/baremetal/libclang_rt.builtins-riscv64.a")},
}


def encoded(value):
    return (json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n").encode("utf-8")


def descriptor(name, body):
    return {"path": name, "sha256": hashlib.sha256(body).hexdigest(), "size_bytes": len(body)}


class PacketHarness(harness_module.RunnerHarness):
    """Supply declared synthetic provenance, retaining the original validators."""

    def __init__(self, test, fmt):
        super().__init__(test, "--format", fmt)
        source = self.paths["tools"].parent / "source"
        names = set(NATIVE_HELPERS + runner.SOURCE_FILES + runner.base.COPIED
                    + runner.base.CORPUS + baseline_inventory.SOURCE_INPUTS
                    + runner.model_run.SOURCE_FILES + runner.model_run.operator_run.SOURCE_FILES
                    + p04_model_contract.ARTIFACT_PATHS)
        names.update(row["path"] for row in harness_module.CONTRACT["source_inputs"])
        names.update(("sim/rtlsim/verilator.vlt.in", "sw/runtime/include/vortex2.h"))
        for name in sorted(names):
            target = source / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes((ROOT / name).read_bytes())
        self.paths["source"] = source
        self.stack.enter_context(mock.patch.object(harness_module, "ROOT", source))
        loaded = harness_module.ORIGINAL_HASH(source, NATIVE_HELPERS)
        self.stack.enter_context(mock.patch.object(runner, "LOADED_HELPERS", loaded))
        pins = dict(line.split("=", 1) for line in (source / "VERSION").read_text().splitlines()
                    if line and not line.startswith("#"))
        submodules = re.findall(r"^\s*path\s*=\s*(\S+)\s*$",
                                (source / ".gitmodules").read_text(), re.MULTILINE)
        self.snapshot = {
            "checkout": {
                "revision": REVISION, "tree": "f" * 40, "dirty": False,
                "changed_paths": [], "untracked_paths": [], "blockers": [], "outcome": "pass",
                "pins": pins,
                "submodules": {"errors": [], "entries": [
                    {"path": name, "revision": "e" * 40, "status": "initialized"}
                    for name in submodules]},
                "inputs": harness_module.ORIGINAL_HASH(source, baseline_inventory.SOURCE_INPUTS),
            },
            "files": harness_module.ORIGINAL_HASH(source, sorted(names)),
        }

    def tool_inventory(self, *_):
        paths = {name: str(Path("/usr/bin") / name) for name in HOST_TOOLS}
        paths["python3"] = sys.executable
        paths.update({name: str(self.paths["tools"] / suffix) for name, suffix in TOOL_PATHS.items()})
        return {name: {"path": path, "resolved_path": path, "sha256": "a" * 64, "size_bytes": 1}
                for name, path in paths.items()}

    def process(self, *args, **kwargs):
        return dict(super().process(*args, **kwargs), limitations=list(PROCESS_LIMITATIONS))


def synthetic_packet(fmt="fp16"):
    """Return member bytes only, after every recorded temporary root is deleted."""
    cleanup = unittest.TestCase()
    try:
        with PacketHarness(cleanup, fmt) as harness:
            report = harness.execute()
            if report["outcome"] != "pass":
                raise AssertionError("synthetic packet producer failed: " + str(report.get("reason")))
            output = harness.paths["output"]
            members = {"baseline/" + path.relative_to(output).as_posix(): path.read_bytes()
                       for path in output.rglob("*") if path.is_file()}
            removed_roots = [path for name, path in harness.paths.items()
                             if name != "host_bin" and path is not None]
    finally:
        cleanup.doCleanups()
    if any(path.exists() for path in removed_roots):
        raise AssertionError("synthetic source/build/tool roots were not removed")
    members["SYNTHETIC-HOST-ONLY.txt"] = (
        b"SYNTHETIC HOST TEST ONLY. No compiler, simulator, GPU, or native process ran.\n"
        b"All checkout, tool, dependency, build, process, and counter observations are synthetic.\n"
    )
    return members


def write_archive(path, members):
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, body in sorted(members.items()):
            archive.writestr(name, body)
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

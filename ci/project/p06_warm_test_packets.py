# SPDX-License-Identifier: Apache-2.0
"""Synthetic warm packets from the real runner; never native execution evidence."""

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
import test_p06_warm_runner as harness_module


runner = harness_module.runner
ROOT = runner.ROOT
REVISION = "1" * 40
PREFIX = "warm-workspace/"
REPORT = PREFIX + "report.json"
# This inventory was observed in a fresh native-entry-point import, outside
# unittest discovery; the replay reader is deliberately not its producer.
NATIVE_HELPERS = tuple(sorted("ci/project/" + name + ".py" for name in (
    "baseline_inventory", "baseline_matrix", "baseline_packet_contract", "baseline_packet_io",
    "baseline_process", "compiler_records", "p02_fixture_oracle", "p02_layout_fixture_oracle",
    "p02_matrix", "p02_matrix_records", "p02_wmma_fixtures", "p02_wmma_numerical_fixture_oracle",
    "p03_execute", "p03_execution_records", "p04_execution_records", "p04_fixture_adapter",
    "p04_model_contract", "p04_reference", "p06_compiler_records", "p06_contract", "p06_records",
    "p06_warm_compiler_records", "p06_warm_contract", "p06_warm_execute", "p06_warm_records",
    "p06_workspace_compiler_records", "p06_workspace_records", "preflight",
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
PREPARATION_SOURCES = ("ci/project/p04_ci_prepare.py", ".github/workflows/p04-model.yml",
                       "ci/toolchain_rev.sh", "ci/install_dependencies.sh")
NOTICE = (b"SYNTHETIC HOST TEST ONLY. No compiler, simulator, GPU, or native process ran.\n"
          b"Checkout, tool, dependency, binary, process, timing and counter observations are synthetic.\n")


def encoded(value):
    return (json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n").encode("utf-8")


def descriptor(name, body):
    return {"path": name, "sha256": hashlib.sha256(body).hexdigest(), "size_bytes": len(body)}


class PacketHarness(harness_module.WarmHarness):
    """Supply synthetic external provenance without bypassing actual validators."""

    def __init__(self, test):
        super().__init__(test)
        source = self.paths["tools"].parent / "source"
        names = set(NATIVE_HELPERS + runner.SOURCE_FILES + runner.base.COPIED
                    + runner.base.CORPUS + baseline_inventory.SOURCE_INPUTS
                    + runner.operator_run.SOURCE_FILES)
        names.update(row["path"] for row in harness_module.CONTRACT["source_inputs"])
        names.update(("sim/rtlsim/verilator.vlt.in", "sw/runtime/include/vortex2.h"))
        for name in sorted(names):
            target = source / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes((ROOT / name).read_bytes())
        self.paths["source"] = source
        self.args.source_dir = source
        loaded = harness_module.ORIGINAL_HASH(source, NATIVE_HELPERS)
        self.stack.enter_context(mock.patch.object(runner, "LOADED_HELPERS", loaded))
        pins = dict(line.split("=", 1) for line in (source / "VERSION").read_text().splitlines()
                    if line and not line.startswith("#"))
        modules = re.findall(r"^\s*path\s*=\s*(\S+)\s*$",
                             (source / ".gitmodules").read_text(), re.MULTILINE)
        self.snapshot = {
            "checkout": {
                "revision": REVISION, "tree": "f" * 40, "dirty": False,
                "changed_paths": [], "untracked_paths": [], "blockers": [], "outcome": "pass",
                "pins": pins,
                "submodules": {"declared_count": len(modules), "errors": [], "entries": [
                    {"path": name, "revision": "e" * 40, "status": "initialized"}
                    for name in modules]},
                "inputs": harness_module.ORIGINAL_HASH(source, baseline_inventory.SOURCE_INPUTS),
            },
            "files": harness_module.ORIGINAL_HASH(source, sorted(names)),
        }

    def tool_inventory(self, *_):
        paths = {name: str(Path("/usr/bin") / name) for name in HOST_TOOLS}
        paths["python3"] = str(Path(sys.executable).parent / "python3")
        paths.update({name: str(self.paths["tools"] / suffix) for name, suffix in TOOL_PATHS.items()})
        return {name: {"path": path, "resolved_path": path, "sha256": "a" * 64, "size_bytes": 1}
                for name, path in paths.items()}

    def process(self, *args, **kwargs):
        return dict(super().process(*args, **kwargs), limitations=list(PROCESS_LIMITATIONS))


def synthetic_packet():
    """Return only member bytes after deleting every recorded temporary root."""
    cleanup = unittest.TestCase()
    try:
        with PacketHarness(cleanup) as harness:
            report = harness.execute()
            if report["outcome"] != "pass":
                raise AssertionError("synthetic warm producer failed: " + str(report.get("reason")))
            output = harness.paths["output"]
            members = {PREFIX + path.relative_to(output).as_posix(): path.read_bytes()
                       for path in output.rglob("*") if path.is_file()}
            removed_roots = [path for name, path in harness.paths.items()
                             if name != "host_bin" and path is not None]
    finally:
        cleanup.doCleanups()
    if any(path.exists() for path in removed_roots):
        raise AssertionError("synthetic source/build/tool roots were not removed")
    members["SYNTHETIC-HOST-ONLY.txt"] = NOTICE
    return members


def hosted(members, *, relocated=False):
    """Add invented workflow observations; these do not authenticate GitHub."""
    members = dict(members)
    members.pop("SYNTHETIC-HOST-ONLY.txt", None)
    members["host-dependencies.log"] = NOTICE
    report = json.loads(members[REPORT])
    source = json.loads(members[PREFIX + report["source_before"]["path"]])
    tools = json.loads(members[PREFIX + report["tools_before"]["path"]])
    dependencies = json.loads(members[PREFIX + report["dependencies_before"]["path"]])
    source_bodies = {name[len(PREFIX + "artifacts/source/"):]: body for name, body in members.items()
                     if name.startswith(PREFIX + "artifacts/source/")}
    workflow = source_bodies[".github/workflows/p06-warm-workspace.yml"]
    members["workflow.yml"] = workflow
    members["job.json"] = encoded({
        "GITHUB_SHA": REVISION, "GITHUB_EVENT_NAME": "push", "GITHUB_RUN_ID": "123456789",
        "GITHUB_RUN_ATTEMPT": "1", "GITHUB_JOB": "experiment", "GITHUB_REPOSITORY": "baabi-boo/AI-GPU",
        "GITHUB_REF": "refs/heads/master", "P06_WARM_BACKEND": "simx", "P06_WARM_FORMAT": "both",
        "scope": "matched-warm-context-workspace-experiment", "record_stage": "job-initialization",
        "native_execution": "not_run", "acceptance_claimed": False,
        "workflow_sha256": hashlib.sha256(workflow).hexdigest(),
    })
    members["python-provision.json"] = encoded({
        "python_version": [3, 12, 14], "implementation": "CPython", "platform": "linux",
        "executable": tools["python3"]["resolved_path"], "python3_on_path": tools["python3"]["path"],
    })
    toolchain = source["checkout"]["pins"]["TOOLCHAIN_REV"] + "-" + "e" * 40
    cache_digest = hashlib.sha256(b"".join(hashlib.sha256(source_bodies[name]).digest()
        for name in ("third_party/Makefile", ".gitmodules"))).hexdigest()
    quarantine = {"submodule": "third_party/cocogfx", "state": "not_needed", "files": [],
                  "expected_revision": "e" * 40, "revision_before": "e" * 40,
                  "revision_after": "e" * 40, "status_before": [], "status_after": []}
    if relocated:
        destination = Path(report["paths"]["tools"]).parent / "cache-quarantine/cocogfx"
        product = descriptor("third_party/cocogfx/.depend", b"synthetic cache product\n")
        quarantine.update(state="relocated", destination=str(destination), status_before=["?? .depend"],
            files=[dict(product, moved=True, destination=str(destination / ".depend"),
                        after_sha256=product["sha256"], after_size_bytes=product["size_bytes"])])
    members["preparation.json"] = encoded({
        "schema_version": 1, "contract_id": "p04-hosted-preparation-v1", "outcome": "pass", "reason": None,
        "native_execution": "not_run", "acceptance_claimed": False, "expected_revision": REVISION,
        "backend": "simx", "formats": ["fp16", "bf16"], "toolchain_id": toolchain,
        "toolchain_cache_key": "Linux-toolchain-" + toolchain + "-lite",
        "third_party_cache_key": "Linux-thirdparty-" + cache_digest,
        "budget": {"min_free_bytes": 15 * 1024**3, "max_rss_bytes": 4 * 1024**3,
                   "max_log_bytes": 16 * 1024**2, "jobs": 2},
        "tools_relocated": True, "limitations": [NOTICE.decode("ascii").strip()],
        "resources": {"available_memory_bytes": 4 * 1024**3,
                      "free_disk_bytes": {"source": 15 * 1024**3, "workspace": 15 * 1024**3}},
        "tools_dir": report["paths"]["tools"], "cache_quarantine": quarantine,
        "source": source["checkout"], "tool_identities": tools, "dependency_identities": dependencies,
        "preparation_sources": [descriptor(name, source_bodies[name]) for name in PREPARATION_SOURCES],
    })
    members["preparation.log"] = encoded({"outcome": "pass", "reason": None, "native_execution": "not_run"})
    members["execution.log"] = encoded({"outcome": "pass", "reason": None,
        "report": str(Path(report["paths"]["output"]) / "report.json"),
        "completed_processes": 24, "completed_launches": 792, "checked_words": 25344,
        "full_matrix_completed": True, "acceptance_claimed": False, "performance_acceptance": False,
        "hypothesis_evaluation": "not_evaluated"})
    return members


def write_archive(path, members):
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, body in sorted(members.items()):
            archive.writestr(name, body)
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

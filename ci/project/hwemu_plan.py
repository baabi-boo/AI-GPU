# SPDX-License-Identifier: Apache-2.0
"""Observe declared emulation inputs and describe a candidate without running it."""

from contextlib import ExitStack
import os
from pathlib import PurePosixPath

from baseline_packet_io import _DirectoryChain
from hwemu_build import LIMITATIONS as BUILD_LIMITATIONS, check_build
from hwemu_contract import CONFIGS, FILE_ROLES, GENERATED_PATHS
from hwemu_contract import validate_manifest, validate_receipt
from hwemu_inventory import observe_source
from hwemu_io import Inputs
import preflight


LIMITATIONS = (
    "A planned result verifies declared input consistency, not launch readiness.",
    "File identities and matching receipts do not authenticate vendor releases, "
    "platform compatibility, licensing, build origin, or execution.",
    "Complete platform dependencies, native toolchain qualification, and "
    "site-specific vendor setup require independent review.",
    "No vendor binary, setup script, license server, network, build, or workload is invoked.",
    "Execution budgets are declarations; this planner does not enforce process "
    "time, RSS, log size, or disk quotas. A separate bounded supervisor is required.",
    "MemAvailable describes the host; the effective container/cgroup limit is unknown.",
    "Input and directory rechecks cannot prevent a writer changing them after inspection.",
    *BUILD_LIMITATIONS,
)


def _report():
    return {
        "schema_version": 1,
        "target": "hw_emu",
        "outcome": "blocked",
        "input_consistency_verified": False,
        "execution_performed": False,
        "phase_complete": False,
        "launch_ready": False,
        "vendor_qualification": "unverified",
        "vendor_qualification_verified": False,
        "acceptance_id": "P01-A03",
        "acceptance_outcome": "blocked",
        "candidate": None,
        "source": None,
        "resources": {},
        "checked_input_count": 0,
        "checked_input_bytes": 0,
        "blockers": [],
        "limitations": list(LIMITATIONS),
    }


def _resource_paths(manifest):
    paths = {
        "source": manifest["source"]["root"],
        "build": manifest["build"]["root"],
        "native_tools": manifest["build"]["tool_dir"],
    }
    paths.update({"vendor_" + name: item["root"]
                  for name, item in manifest["vendor"].items()})
    paths.update({"files_" + role: str(PurePosixPath(item["path"]).parent)
                  for role, item in manifest["files"].items()})
    return paths


def _open_directories(manifest, stack):
    by_path = {}
    result = {}
    for label, path in _resource_paths(manifest).items():
        if path not in by_path:
            chain = _DirectoryChain(path)
            stack.callback(chain.close)
            by_path[path] = chain
        result[label] = by_path[path]
    return result


def _sample_resources(directories):
    free = {}
    for label, chain in directories.items():
        chain.check()
        observed = os.fstatvfs(chain.fd)
        count = observed.f_bavail * observed.f_frsize
        free[label] = count if type(count) is int and count >= 0 else None
    memory = preflight.available_memory_bytes()
    if type(memory) is not int or memory < 0:
        memory = None
    return {
        "free_disk_bytes": free,
        "available_memory_bytes": memory,
        "cgroup_limit_bytes": None,
    }


def _resource_blockers(resources, budget):
    blockers = []
    for label, available in resources["free_disk_bytes"].items():
        if available is None or available < budget["min_free_bytes"]:
            blockers.append("disk reserve is unavailable or insufficient for " + label)
    memory = resources["available_memory_bytes"]
    if memory is None or memory < budget["max_rss_bytes"]:
        blockers.append("available host memory is unknown or below the declared RSS budget")
    return blockers


def _check_source(observed, manifest):
    expected = manifest["source"]
    if (observed.get("outcome") != "pass" or observed.get("blockers")
            or observed.get("dirty") is not False or observed.get("clean") is not True
            or observed.get("revision") != expected["revision"]
            or observed.get("tree") != expected["tree"]
            or observed.get("submodules", {}).get("at_recorded_revisions") is not True
            or observed.get("submodules", {}).get("errors")):
        raise ValueError("source identity or cleanliness differs from the declaration")


def _candidate(manifest):
    vendor = manifest["vendor"]
    jobs = str(manifest["budget"]["jobs"])
    environment = {
        "PATH": ":".join((vendor["vitis"]["root"] + "/bin",
                          vendor["vivado"]["root"] + "/bin", "/usr/bin", "/bin")),
        "LANG": "C",
        "LC_ALL": "C",
        "CONFIGS": " ".join(CONFIGS),
        "PROFILE": "",
        "XILINX_VITIS": vendor["vitis"]["root"],
        "XILINX_VIVADO": vendor["vivado"]["root"],
        "XILINX_XRT": vendor["xrt"]["root"],
        "PLATFORM": manifest["files"]["platform"]["path"],
        "FPGA_BIN_DIR": str(PurePosixPath(manifest["files"]["xclbin"]["path"]).parent),
        "MAKEFLAGS": "-j" + jobs,
        "JOBS": jobs,
        "MAX_JOBS": jobs,
        "THREADS": jobs,
        "CCACHE_DISABLE": "1",
        "OBJCACHE": "",
        "VORTEX_XRT_WAVEFORM": "0",
        "XRT_DEVICE_INDEX": "0",
    }
    return {
        "cwd": manifest["build"]["root"],
        "argv": ["./ci/blackbox.sh", "--driver=xrt", "--target=hw_emu",
                 "--app=demo", "--args=-n1"],
        "environment": environment,
        "inherit_environment": False,
        "supervision_required": True,
        "budget": dict(manifest["budget"]),
    }


def create_plan(manifest):
    """Verify declared inputs and emit a nonexecuting, unqualified candidate."""
    report = _report()
    stage = "manifest does not satisfy the frozen emulation contract"
    try:
        manifest = validate_manifest(manifest)
        with ExitStack() as stack:
            stage = "a required directory is missing, unsafe, changed, or unreadable"
            directories = _open_directories(manifest, stack)
            stage = "resource observations are unavailable"
            report["resources"]["initial"] = _sample_resources(directories)
            report["blockers"].extend(_resource_blockers(
                report["resources"]["initial"], manifest["budget"]))
            if report["blockers"]:
                return report

            stage = "source identity, cleanliness, or submodule provenance is inconsistent"
            initial_source = observe_source(manifest["source"]["root"])
            report["source"] = initial_source
            _check_source(initial_source, manifest)
            inputs = stack.enter_context(Inputs(
                max_total_bytes=manifest["budget"]["max_input_bytes"], max_files=64))
            for role in FILE_ROLES:
                stage = "declared " + role + " input is missing, unsafe, changed, or mismatched"
                inputs.check_file(manifest["files"][role], label=role)
            for relative in GENERATED_PATHS:
                stage = "generated " + relative + " identity is missing, unsafe, changed, or mismatched"
                identity = dict(manifest["generated"][relative],
                                path=manifest["build"]["root"] + "/" + relative)
                inputs.check_file(identity, label="generated input")

            stage = "build receipt is malformed or differs from the declared inputs"
            receipt = inputs.read_json(manifest["files"]["build_receipt"]["path"])
            validate_receipt(receipt, manifest)
            stage = "generated build content does not satisfy the frozen source and runtime contract"
            check_build(inputs, manifest)
            stage = "source identity or submodule state changed during inspection"
            final_source = observe_source(manifest["source"]["root"])
            _check_source(final_source, manifest)
            if final_source != initial_source:
                raise ValueError("source observation changed")
            stage = "retained inputs or directories changed during inspection"
            inputs.recheck()
            for chain in directories.values():
                chain.check()
            stage = "final resource observations are unavailable"
            report["resources"]["final"] = _sample_resources(directories)
            report["blockers"].extend(_resource_blockers(
                report["resources"]["final"], manifest["budget"]))
            if report["blockers"]:
                return report
            inventory = inputs.inventory()
            report["checked_input_count"] = len(inventory)
            report["checked_input_bytes"] = sum(item["size_bytes"] for item in inventory)
            report["candidate"] = _candidate(manifest)
            report["input_consistency_verified"] = True
            report["outcome"] = "planned"
    except (ValueError, OSError, TypeError, KeyError, AttributeError):
        report["candidate"] = None
        report["input_consistency_verified"] = False
        report["outcome"] = "blocked"
        report["blockers"].append(stage)
    return report

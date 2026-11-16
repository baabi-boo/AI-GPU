# SPDX-License-Identifier: Apache-2.0
"""Read-only prerequisite observations, without vendor execution or qualification."""

import os
from pathlib import Path
import re
import shutil

import hwemu_source
import preflight


GIB = 1024 ** 3
MIB = 1024 ** 2
DEFAULT_BUDGET = {
    "jobs": 2,
    "timeout_seconds": 7200,
    "min_free_bytes": 15 * GIB,
    "max_rss_bytes": 6 * GIB,
    "max_log_bytes": 16 * MIB,
    "max_input_bytes": 512 * MIB,
}
VENDOR_TOOLS = {
    "vpp": ("v++",),
    "vivado": ("vivado",),
    "platforminfo": ("platforminfo",),
    "emconfigutil": ("emconfigutil",),
    "xrt_inventory": ("xbutil", "xrt-smi"),
}
VENDOR_ROOT_VARIABLES = ("XILINX_VITIS", "XILINX_VIVADO", "XILINX_XRT")
LIMITATIONS = (
    "PATH presence does not establish a vendor release, working tool, or compatibility.",
    "Vendor-root booleans report nonempty environment variables, not validated directories.",
    "No vendor executable, setup script, license server, network, build, or workload is invoked.",
    "Source cleanliness requires exact tracked bytes and executable/link modes; checkout conversions are not applied.",
    "Source observations reject executable filters, hidden index entries, and deferred Git object retrieval.",
    "Source reads are bounded to 1 MiB per identity input, 8 MiB of identity inputs, "
    "512 MiB of tracked bytes, 32768 tracked files, and 32 recursive submodules.",
    "MemAvailable is a host observation; the effective container/cgroup memory limit is unknown.",
    "The resource budget is a proposed limit, not enforced by this read-only inventory.",
    "Native toolchain, generated build, platform package, and emulation artifacts need separate inspection.",
)


def _revision(value):
    if type(value) is str and re.fullmatch(r"[0-9a-f]{40}", value):
        return value
    return None


def observe_source(root):
    """Return local source identity without exposing filenames, roots, or errors."""
    try:
        observed = hwemu_source.collect_source(root)
    except (OSError, ValueError, TypeError, RuntimeError):
        observed = {}
    revision = _revision(observed.get("revision"))
    tree = _revision(observed.get("tree"))
    dirty = observed.get("dirty")
    dirty = dirty if type(dirty) is bool else None
    modules = observed.get("submodules", {})
    entries = modules.get("entries", [])
    declared = modules.get("declared_count")
    declared = declared if type(declared) is int and declared >= 0 else None
    valid_entries = all(type(entry) is dict and _revision(entry.get("revision"))
                        and entry.get("status") == "initialized" for entry in entries)
    module_errors = []
    if modules.get("errors") or declared is None:
        module_errors.append("submodule inventory is incomplete or invalid")
    if not valid_entries or declared is not None and len(entries) < declared:
        module_errors.append("submodules are not all at their recorded revisions")
    blockers = []
    if revision is None or tree is None:
        blockers.append("exact source revision and tree are unavailable")
    if dirty is not False:
        blockers.append("source is dirty or its working-tree state is unavailable")
    blockers.extend(module_errors)
    if observed.get("outcome") != "pass" or observed.get("blockers"):
        blockers.append("source provenance is not completely verified")
    return {
        "revision": revision,
        "tree": tree,
        "dirty": dirty,
        "clean": dirty is False,
        "outcome": "blocked" if blockers else "pass",
        "submodules": {
            "declared_count": declared,
            "observed_count": len(entries),
            "initialized_count": sum(type(entry) is dict and
                                     entry.get("status") == "initialized" for entry in entries),
            "at_recorded_revisions": not module_errors,
            "errors": module_errors,
        },
        "blockers": blockers,
    }


def _bytes(value):
    return value if type(value) is int and value >= 0 else None


def inventory(root):
    """Report missing prerequisites; file or tool presence can never qualify a run."""
    source = observe_source(root)
    tools = {
        name: {"candidates": list(candidates),
               "available": any(shutil.which(candidate) is not None for candidate in candidates)}
        for name, candidates in VENDOR_TOOLS.items()
    }
    try:
        free_disk = _bytes(shutil.disk_usage(Path(root)).free)
    except (OSError, ValueError, TypeError):
        free_disk = None
    available_memory = _bytes(preflight.available_memory_bytes())
    blockers = list(source["blockers"])
    blockers.extend("vendor PATH tool missing: " + name for name, tool in tools.items()
                    if not tool["available"])
    if free_disk is None or free_disk < DEFAULT_BUDGET["min_free_bytes"]:
        blockers.append("free disk is unknown or below the proposed reserve")
    if available_memory is None or available_memory < DEFAULT_BUDGET["max_rss_bytes"]:
        blockers.append("available host memory is unknown or below the proposed RSS budget")
    blockers.extend((
        "qualified vendor releases and license/access entitlement remain unverified",
        "supported platform identity and compatibility remain unverified",
        "matching hw_emu artifacts, build receipt, and generated configuration remain unverified",
    ))
    return {
        "schema_version": 1,
        "target": "hw_emu",
        "outcome": "blocked",
        "execution_performed": False,
        "phase_complete": False,
        "vendor_qualification_verified": False,
        "source": source,
        "vendor_tools": tools,
        "vendor_roots_present": {name: bool(os.environ.get(name))
                                 for name in VENDOR_ROOT_VARIABLES},
        "resources": {
            "free_disk_bytes": free_disk,
            "available_memory_bytes": available_memory,
            "cgroup_limit_bytes": None,
        },
        "default_budget": dict(DEFAULT_BUDGET),
        "blockers": blockers,
        "limitations": list(LIMITATIONS),
    }

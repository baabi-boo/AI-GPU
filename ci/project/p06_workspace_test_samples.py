# SPDX-License-Identifier: Apache-2.0
"""Independent synthetic transport samples; no native execution or arithmetic."""

from copy import deepcopy
from functools import lru_cache
import json
from pathlib import Path
import struct

from test_p02_matrix import BUILD, SOURCE, sample


ROOT = Path(__file__).resolve().parents[2]
BINDING = "0123456789abcdef" * 4
POLICIES = ("per_operation", "reusable_single_tile")
FORMATS = ("fp16", "bf16")
SEQUENCE = ("single-dense_boundaries", "numerical-zero", "single-k03",
            "single-dense_boundaries")
POISONS = (0xDEADBEEF, 0x7FC0DEAD, 0xDEADBEEF, 0x7FC0DEAD)
PROBES = ("context_before_wait", "operation_before_wait", "owner_close_before_wait",
          "context_after_wait", "operation_after_wait", "owner_close_after_wait")
RESOURCES = ("before_submit", "after_submit", "after_wait", "after_close")
WRAPPERS = ("-Wl,--wrap=vx_buffer_create", "-Wl,--wrap=vx_buffer_release",
            "-Wl,--wrap=vx_device_open", "-Wl,--wrap=vx_device_release")
COMPILER_ROLES = {
    "simx": ((0, 0, "runtime"), (1, 0, "backend_cpp"),
             (2, 0, "kernel"), (2, 1, "host")),
    "rtlsim": ((0, 0, "runtime"), (1, 0, "verilator"), (1, 1, "backend_cpp"),
               (2, 0, "kernel"), (2, 1, "host")),
}


@lru_cache(maxsize=1)
def _source_cases():
    inventory = {}
    for name in ("p02_layout_v1.json", "p02_wmma_numerical_v1.json"):
        document = json.loads((ROOT / "ci/project/fixtures" / name).read_text())
        for case in document["cases"]:
            inventory[case["id"]] = {**case, **case["dimensions"]}
    return inventory


def cases(fmt="bf16"):
    return [deepcopy(_source_cases()[fmt + "-" + suffix]) for suffix in SEQUENCE]


def contract():
    return json.loads((ROOT / "ci/project/p06_workspace_contract.json").read_text())


def memory(used):
    return {"status": 0, "free_bytes": 0x1000000 - used, "used_bytes": used}


def counts(creates, releases, live, peak=320, device_releases=0):
    return {
        "device_open_calls": 1, "device_release_calls": device_releases,
        "buffer_create_calls": creates, "buffer_release_calls": releases,
        "live_buffers": 3 if live else 0, "live_requested_bytes": 320 if live else 0,
        "peak_requested_payload_bytes": peak, "premature_releases": 0, "errors": 0,
    }


def result(*, validation=0, primary=0, cleanup=0, complete=True):
    return {"validation": validation, "primary": primary,
            "cleanup": cleanup, "complete": complete}


def argument_hex(fmt, addresses):
    return struct.pack("<8I3Q", 1, 56, 1 if fmt == "fp16" else 2,
                       0, 8, 4, 8, 0, *addresses).hex()


def _buffer_group(group, resident):
    addresses = (0x10000 + 0x1000 * group, 0x10100 + 0x1000 * group,
                 0x10200 + 0x1000 * group)
    # A, B, D allocate in that order and release D, B, A. These fixed readings
    # include 512 context bytes and separately measured 128/64/128 tensor bytes.
    boundaries = (512, 640, 704, 832)
    rows = []
    for slot, (address, size, flags) in enumerate(zip(addresses, (128, 64, 128), (1, 1, 2))):
        rows.append({
            "buffer_id": group * 3 + slot + 1, "device_id": 1,
            "requested_bytes": size, "flags": flags, "address": address,
            "address_status": 0, "create_status": 0,
            "create_phase": "context_create" if resident else "submit",
            "create_sequence": -1 if resident else group,
            "create_before": memory(boundaries[slot]),
            "create_after": memory(boundaries[slot + 1]),
            "release_status": 0,
            "release_phase": "owner_close" if resident else "operation_close",
            "release_sequence": -1 if resident else group, "release_device_live": True,
            "release_before": memory(boundaries[slot + 1]),
            "release_after": memory(boundaries[slot]),
        })
    return rows


def process_records(fmt="bf16", policy="reusable_single_tile"):
    """Construct fixed observations without using either validator's builders."""
    resident = policy == "reusable_single_tile"
    identity = {"schema_version": 1,
                "contract_id": "p06-serial-workspace-correctness-v1",
                "qualification_id": BINDING, "policy": policy, "format": fmt}
    buffers = [row for group in range(1 if resident else 4)
               for row in _buffer_group(group, resident)]
    operations = []
    for index, case in enumerate(cases(fmt)):
        before_creates = 3 if resident else index * 3
        after_creates = 3 if resident else (index + 1) * 3
        before_releases = 0 if resident else index * 3
        after_releases = 0 if resident else (index + 1) * 3
        idle = counts(before_creates, before_releases, resident,
                      peak=320 if resident or index else 0)
        active = counts(after_creates, before_releases, True)
        closed = counts(after_creates, after_releases, resident)
        group = buffers[:3] if resident else buffers[index * 3:index * 3 + 3]
        addresses = [row["address"] for row in group]
        row = {
            **identity, "sequence_index": index, "case_id": case["id"],
            "m": 8, "n": 4, "k": 8, "poison": POISONS[index],
            "checked": 32, "mismatches": 0, "actual_bits": list(case["expected"]),
            "passed": True,
            "dispatch": {
                "a_address": addresses[0], "b_address": addresses[1],
                "d_address": addresses[2], "a_bytes": 128, "b_bytes": 64, "d_bytes": 128,
                "writes": 3, "launches": 1, "reads": 1, "waits": 1, "timed_out_waits": 0,
                "argument_bytes": argument_hex(fmt, addresses), "event_results": [0, 0, 0, 0, 0],
                "profiling_enabled": False,
            },
            "results": {"submit": result(complete=False), "wait": result(), "close": result()},
            "probes": {
                name: {"result": result(primary=7, complete=not name.startswith("owner_close")),
                       "returned_object": False, "before": deepcopy(active),
                       "after": deepcopy(active)} for name in PROBES
            },
            "resources": {
                name: {"memory": memory(832 if resident or name in ("after_submit", "after_wait") else 512),
                       "counts": deepcopy(value)}
                for name, value in zip(RESOURCES, (idle, active, active, closed))
            },
        }
        operations.append(row)
    setup_counts = counts(3 if resident else 0, 0, resident, peak=320 if resident else 0)
    count = 3 if resident else 12
    summary = {
        **identity, "operations": 4, "checked": 128, "mismatches": 0, "passed": True,
        "counts": counts(count, count, False, device_releases=1),
        "results": {"setup": result(), "teardown": result(), "teardown_repeat": result()},
        "unsupported_shape": {
            "result": result(validation=5), "returned_object": False,
            "before": deepcopy(setup_counts), "after": deepcopy(setup_counts),
            "m": 8 if resident else 7, "n": 4, "k": 16 if resident else 8,
        },
        "devices": [{"device_id": 1, "index": 0, "open_status": 0,
                     "after_open": memory(256), "release_status": 0,
                     "before_release": memory(256)}],
        "buffers": buffers,
    }
    return {"operations": operations, "summary": summary}


def render_log(raw):
    lines = ["synthetic parser sample; no native execution"]
    lines.extend("P06_WORKSPACE_RESULT " + json.dumps(row, separators=(",", ":"))
                 for row in raw["operations"])
    lines.append("P06_WORKSPACE_SUMMARY " + json.dumps(raw["summary"], separators=(",", ":")))
    return "\n".join((*lines, "PASSED!", ""))


def compiler_stamps(driver="simx", fmt="bf16", jobs=2):
    """Adapt retained P02 probe stamps only at the workspace caller boundary."""
    runtime = sample(driver + "_rt", fmt=fmt)
    backend = sample(driver + "_backend", fmt=fmt)
    if driver == "rtlsim":
        backend = backend.replace("-j 2", "-j " + str(jobs))
    application = sample("application", fmt=fmt).splitlines()
    application[1] = application[1].replace(
        "-I" + str(SOURCE / "third_party/softfloat/source/include"),
        "-I" + str(SOURCE / "sw/runtime/ai"))
    application[2] = " ".join((*WRAPPERS, "-L" + str(BUILD / "sw/runtime"), "-lvortex"))
    return [runtime, backend, "\n".join(application) + "\n"]


def change_role(stamps, outer, inner, transform):
    changed = list(stamps)
    lines = changed[outer].splitlines()
    lines[inner] = transform(lines[inner])
    changed[outer] = "\n".join(lines) + "\n"
    return changed

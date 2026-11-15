# SPDX-License-Identifier: Apache-2.0
"""Synthetic stopped-run packets for offline verifier tests, never GPU evidence.

The records below independently model the fields written by ``baseline.py``.
No runner or verifier implementation is imported, and no command, binary, or
retained helper is executed. Only the committed matrix and archive lock are
read as contract data; observed identities and results are entirely synthetic.
"""

from copy import deepcopy
import hashlib
import json
from pathlib import Path


HERE = Path(__file__).resolve().parent
SYNTHETIC = "SYNTHETIC TEST FIXTURE: no workload or compiler was executed"
CASE_IDS = (
    "gemm-fp16-simx", "gemm-fp16-rtlsim",
    "gemm-bf16-simx", "gemm-bf16-rtlsim",
    "attention-tf32-simx", "attention-tf32-rtlsim",
)
SOURCE_INPUTS = (
    "VERSION", ".gitmodules", "configure", "config.mk.in", "VX_config.toml",
    "VX_types.toml", "ci/gen_config.py", "ci/blackbox.sh",
)
GENERATED_PATHS = (
    ".config.stamp", "config.mk", "sw/VX_config.h", "sw/VX_types.h",
    "hw/VX_config.vh", "hw/VX_types.vh", "ci/blackbox.sh",
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
    "tests/regression/flash_attn_tcu_wg/Makefile":
        "tests/regression/flash_attn_tcu_wg/Makefile",
}
DEPENDENCY_PATHS = (
    "third_party/softfloat/build/Linux-x86_64-GCC/softfloat.a",
    "third_party/ramulator/libramulator.so",
    "third_party/ramulator_ext/libramulator-vortex.so",
)
HELPER_NAMES = (
    "baseline.py", "baseline_inventory.py", "baseline_matrix.py",
    "baseline_process.py", "baseline_host.py", "preflight.py",
)
TOOL_PATHS = {
    "riscv_gcc": "riscv64-gnu-toolchain/bin/riscv64-unknown-elf-gcc",
    "llvm_clang": "llvm-vortex/bin/clang",
    "verilator": "verilator/bin/verilator",
    "verilator_binary": "verilator/bin/verilator_bin",
}
LIBRARY_PATHS = (
    "libc64/lib/libc.a", "libc64/lib/libm.a",
    "libcrt64/lib/baremetal/libclang_rt.builtins-riscv64.a",
)
CONFIGURE_ARGV = [
    "$SOURCE/configure", "--xlen=64", "--osversion=ubuntu/focal",
    "--tooldir=$TOOLS",
]
COMMAND_ENVIRONMENT = {
    "MAKEFLAGS": "-j2", "THREADS": "2", "CCACHE_DISABLE": "1", "OBJCACHE": "",
}


def _bytes(label):
    return (SYNTHETIC + "\n" + label + "\n").encode("utf-8")


def _identity(path, contents=None):
    contents = _bytes("metadata identity for " + path) if contents is None else contents
    return {"path": path, "sha256": hashlib.sha256(contents).hexdigest(),
            "size_bytes": len(contents)}


def _revision(label):
    # Format-correct, deliberately invented Git identities, unrelated to HEAD.
    return hashlib.sha256(_bytes(label)).hexdigest()[:40]


def _source():
    submodules = ["third_party/" + name for name in (
        "softfloat", "ramulator", "cvfpu", "hardfloat", "cocogfx")]
    submodules.extend(("third_party/cvfpu/src/common_cells",
                       "third_party/cvfpu/src/fpu_div_sqrt_mvp",
                       "third_party/cvfpu/tb/flexfloat"))
    return {
        "revision": _revision("synthetic GPU source commit"),
        "tree": _revision("synthetic GPU source tree"),
        "dirty": False, "changed_paths": [], "untracked_paths": [],
        "pins": {"VORTEX_VERSION": "3.0", "TOOLCHAIN_REV": "v3.0.2",
                 "GEM5_REV": "v25.0.0.1",
                 "FIRESIM_REV": "57bb93f1e23daf46198659ddd93608f70121fee0"},
        "submodules": {
            "declared_count": 5, "errors": [],
            "entries": [{"path": path, "revision": _revision(path),
                         "status": "initialized"} for path in submodules],
        },
        "inputs": [_identity(path) for path in SOURCE_INPUTS],
        "blockers": [], "outcome": "pass",
    }


def _tools():
    # The archive lock identifies the required contract, not observed execution.
    raw_lock = (HERE / "p01_toolchain.lock.json").read_bytes()
    lock = json.loads(raw_lock)
    versions = {
        "riscv_gcc": "riscv64-unknown-elf-gcc 12.2.0 (synthetic fixture)",
        "llvm_clang": "clang version 18.0.0 (synthetic fixture)",
        "verilator": "Verilator 5.028 (synthetic fixture)",
        "verilator_binary": "Verilator 5.028 (synthetic fixture)",
    }
    return {
        "toolchain_commit": lock["revision"], "toolchain_tag": lock["tag"],
        "os_bundle": lock["os_bundle"],
        "bundle_manifest": {
            "sha256": hashlib.sha256(raw_lock).hexdigest(),
            "size_bytes": len(raw_lock), **lock,
        },
        "tools": {name: {**_identity(path), "version": versions[name]}
                  for name, path in TOOL_PATHS.items()},
        "libraries": [_identity(path) for path in LIBRARY_PATHS],
        "blockers": [], "outcome": "pass", "limitations": [SYNTHETIC],
    }


def _host():
    versions = {
        "gcc": "gcc (synthetic fixture) 11.3.0",
        "g++": "g++ (synthetic fixture) 11.3.0",
        "make": "GNU Make 4.3 (synthetic fixture)",
        "ld": "GNU ld 2.34 (synthetic fixture)",
        "as": "GNU assembler 2.34 (synthetic fixture)",
        "python3": "Python 3.12.0 (synthetic fixture)",
        "cmake": "cmake version 3.16.3 (synthetic fixture)",
    }
    tools = {}
    for name in (*versions, "cc1plus"):
        identity = _identity(name)
        tools[name] = {
            "command": name, "resolved_name": "synthetic-" + name,
            "sha256": identity["sha256"], "size_bytes": identity["size_bytes"],
        }
        if name == "cc1plus":
            tools[name]["reported_by"] = "g++ -print-prog-name=cc1plus"
        else:
            tools[name]["version"] = versions[name]
    return {
        "host": {"system": "Linux", "machine": "x86_64",
                 "libc": {"name": "glibc", "version": "2.31"}},
        "tools": tools, "blockers": [], "outcome": "pass",
        "limitations": [SYNTHETIC],
    }


def _build():
    # Uninstantiated build copies and blackbox have their source hashes. The one
    # .in template has a distinct generated identity, as a real build would.
    return {
        "xlen": 64, "profile": "", "os_bundle": "ubuntu/focal",
        "identity_matches": True,
        "generated": [_identity(path) for path in GENERATED_PATHS],
        "source_inputs": [_identity(path) for path in SOURCE_INPUTS],
        "build_inputs": [_identity(path) for path in COPIED_BUILD_INPUTS],
        "source_build_inputs": [_identity(path) for path in COPIED_BUILD_INPUTS.values()],
        "blockers": [], "outcome": "pass", "limitations": [SYNTHETIC],
    }


def _tooling(root):
    files, snapshots = [], []
    for name in HELPER_NAMES:
        contents = (
            "# SPDX-License-Identifier: Apache-2.0\n# " + SYNTHETIC + "\n"
            "# Inert stand-in for " + name + "; retained solely for hash checks.\n"
            "raise RuntimeError('Synthetic retained helper must never execute')\n"
        ).encode("utf-8")
        relative = "artifacts/tooling/" + name
        (root / relative).write_bytes(contents)
        files.append(_identity(name, contents))
        snapshots.append(_identity(relative, contents))
    return {
        "files": files,
        "checkout": {"revision": _revision("synthetic instrumentation commit"),
                     "tree": _revision("synthetic instrumentation tree"), "dirty": False},
        "blockers": [], "outcome": "pass", "limitations": [SYNTHETIC],
    }, snapshots


def refresh_log(root, command, contents=None):
    """Optionally replace a fixture log, then refresh its recorded hash and size.

    Mutates ``command`` only; call ``save_report`` after editing the report.
    This helper intentionally does not change outcome or reference claims.
    """
    path = Path(root) / command["log"]
    if contents is not None:
        path.write_bytes(contents.encode("utf-8") if isinstance(contents, str) else contents)
    observed = _identity(command["log"], path.read_bytes())
    command["log_sha256"] = observed["sha256"]
    command["log_size_bytes"] = observed["size_bytes"]
    return command


def refresh_stamp(root, artifact, contents=None):
    """Refresh a retained stamp identity without inventing a new source identity."""
    path = Path(root) / artifact["path"]
    if contents is not None:
        path.write_bytes(contents.encode("utf-8") if isinstance(contents, str) else contents)
    artifact.update(_identity(artifact["path"], path.read_bytes()))
    return artifact


def _command(root, name, argv, *, configs=None, failed=False, numerical=False):
    command = {
        "id": name, "argv": list(argv), "cwd": "$BUILD",
        "environment": dict(COMMAND_ENVIRONMENT), "log": "logs/" + name + ".log",
        "outcome": "fail" if failed else "pass", "exit_code": 2 if failed else 0,
        "reason": "nonzero_exit" if failed else None, "duration_seconds": 0.125,
        "peak_rss_bytes": 65536, "cleanup_complete": True,
        "limitations": [SYNTHETIC, "Resource limits are polled budgets, not hard quotas."],
    }
    if configs is not None:
        command["environment"]["CONFIGS"] = " ".join(configs)
    contents = SYNTHETIC + "\nsynthetic command: " + name + "\n"
    contents += "FAILED!\n" if failed else ("PASSED!\n" if numerical else "synthetic prerequisite complete\n")
    return refresh_log(root, command, contents)


def _case_artifacts(root, case):
    stamps = ["tests/regression/" + case["app"] + "/config.stamp",
              "sw/runtime/" + case["driver"] + "_config.stamp",
              "sw/runtime/" + case["driver"] + "_rt_config.stamp"]
    artifacts = []
    for source_path in stamps:
        raw = (
            "# " + SYNTHETIC + "\n"
            "# synthetic stamp role: " + source_path + "\n"
            "SOURCE=/synthetic-p01/source BUILD=/synthetic-p01/build "
            "TOOLS=/synthetic-p01/tools OUTPUT=/synthetic-p01/output\n"
            "CONFIGS: " + " ".join(case["configs"]) + "\n"
            "CXXFLAGS: -DVX_CFG_XLEN=64 -DVX_CFG_XLEN_64 -DVX_CFG_TCU_TYPE=TFR "
            "-DVX_CFG_FPU_TYPE=STD -DSYNTHETIC_PACKET_FIXTURE=1\n"
        )
        redacted = raw
        for label in ("source", "build", "tools", "output"):
            redacted = redacted.replace("/synthetic-p01/" + label, "$" + label.upper())
        relative = "artifacts/" + case["id"] + "-" + source_path.replace("/", "_")
        (root / relative).write_bytes(redacted.encode("utf-8"))
        artifacts.append({
            **_identity(relative, redacted.encode("utf-8")),
            "source": _identity(source_path, raw.encode("utf-8")),
            "redaction": "source/build/tool/output roots replaced by symbolic labels",
        })
    binary_paths = ["tests/regression/" + case["app"] + "/" + case["app"],
                    "tests/regression/" + case["app"] + "/kernel.vxbin",
                    "sw/runtime/libvortex-" + case["driver"] + ".so",
                    "sw/runtime/lib" + case["driver"] + ".so"]
    return {
        "configuration_artifacts": artifacts,
        "binary_identities": [_identity(path, _bytes(case["id"] + " binary " + path))
                              for path in binary_paths],
        "native_flags_verified": True,
    }


def save_report(root, report):
    """Write the current synthetic report and return its path."""
    path = Path(root) / "report.json"
    path.write_text(json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n",
                    encoding="utf-8")
    return path


def make_packet(root, selected_ids=None, failed_case=None):
    """Create an independent synthetic stopped packet and return its report.

    ``root`` must be absent or an empty directory. Selection follows canonical
    matrix order. ``failed_case`` is an optional selected workload ID: it models
    a nonzero process exit, keeps earlier successes and leaves the tail not run.
    All snapshots are independent objects so a mutation affects one stage only.
    """
    raw_matrix = (HERE / "p01_baseline.json").read_bytes()
    matrix = json.loads(raw_matrix)
    if tuple(case["id"] for case in matrix["cases"]) != CASE_IDS:
        raise AssertionError("synthetic fixture requires the frozen six-case matrix")
    if selected_ids is None:
        selected_ids = list(CASE_IDS)
    if (type(selected_ids) not in (list, tuple) or not selected_ids
            or any(type(item) is not str for item in selected_ids)
            or len(set(selected_ids)) != len(selected_ids)
            or not set(selected_ids) <= set(CASE_IDS)):
        raise ValueError("fixture selection must contain unique frozen case IDs")
    selected = [case for case in matrix["cases"] if case["id"] in selected_ids]
    if failed_case is not None and failed_case not in selected_ids:
        raise ValueError("failed_case must be one of the selected workload IDs")
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    if any(root.iterdir()):
        raise ValueError("synthetic packet root must be empty")
    (root / "logs").mkdir()
    (root / "artifacts" / "tooling").mkdir(parents=True)
    (root / "matrix.json").write_text(json.dumps(matrix, indent=2) + "\n", encoding="utf-8")

    source, tools, host, build = _source(), _tools(), _host(), _build()
    tooling, snapshots = _tooling(root)
    dependencies = {"artifacts": [_identity(path) for path in DEPENDENCY_PATHS],
                    "blockers": [], "outcome": "pass"}
    full = len(selected) == len(CASE_IDS)
    report = {
        "schema_version": 1, "mode": "run", "state": "finished",
        "started_at": "2000-01-01T00:00:00+00:00", "finished_at": "2000-01-01T00:01:00+00:00",
        "scope": SYNTHETIC + "; frozen P01 native packet parser exercise",
        "outcome": "pass" if failed_case is None else "fail", "phase_complete": False,
        "matrix": {"id": matrix["id"], "sha256": hashlib.sha256(raw_matrix).hexdigest(),
                   "size_bytes": len(raw_matrix)},
        "budget": {"jobs": 2, "timeout_seconds": 60, "min_free_bytes": 15 * 1024**3,
                   "max_log_bytes": 16 * 1024**2, "max_rss_bytes": 6 * 1024**3},
        "resources": {"source_free_disk_bytes": 100 * 1024**3,
                      "build_free_disk_bytes": 100 * 1024**3,
                      "tools_free_disk_bytes": 100 * 1024**3,
                      "output_free_disk_bytes": 100 * 1024**3,
                      "host_available_ram_bytes": 8 * 1024**3,
                      "effective_cgroup_limit_bytes": None},
        "source_before": deepcopy(source), "tools_before": deepcopy(tools),
        "host_before": deepcopy(host), "host_before_execution": deepcopy(host),
        "tooling_before": deepcopy(tooling), "tooling_before_execution": deepcopy(tooling),
        "tooling_snapshots": snapshots,
        "dependencies": deepcopy(dependencies["artifacts"]),
        "dependencies_planned": deepcopy(dependencies),
        "dependencies_before_execution": deepcopy(dependencies),
        "build_before": {"outcome": "not_run", "reason": "fresh build will be configured"},
        "build_configured": deepcopy(build),
        "commands": [], "cases": [], "blockers": [],
        "coverage": {"selected_ids": [case["id"] for case in selected],
                     "required_ids": list(CASE_IDS), "full_matrix_selected": full,
                     "full_native_matrix_passed": full and failed_case is None},
        "integration": {
            "gate": "P01-A03", "driver": "xrt", "target": "hw_emu",
            "outcome": "blocked", "exit_code": None,
            "reason": "A separately qualified vendor tool/platform environment and full AFU run are required; this runner does not execute them.",
        },
        "limitations": [SYNTHETIC, "Synthetic records are not P01 acceptance or GPU evidence.",
                        "Independent review and full XRT hw_emu remain required.",
                        "No container/cgroup allocation is certified by this fixture."],
    }
    for name, argv in (
        ("configure", CONFIGURE_ARGV),
        ("kernel-library", ["make", "-j2", "-C", "sw/kernel"]),
        ("runtime-stub", ["make", "-j2", "-C", "sw/runtime/stub"]),
    ):
        report["commands"].append(_command(root, name, argv))

    stopped = False
    for case in selected:
        result = {key: deepcopy(case[key]) for key in (
            "id", "app", "driver", "configs", "args", "reference", "arithmetic")}
        result.update({"outcome": "not_run", "reason": "execution has not started", "artifacts": []})
        report["cases"].append(result)
        if stopped:
            continue
        for key in ("dependencies_before", "dependencies_at_launch", "dependencies_after"):
            result[key] = deepcopy(dependencies)
        for key in ("tooling_before", "tooling_after"):
            result[key] = deepcopy(tooling)
        for key in ("source_before", "source_after"):
            result[key] = deepcopy(source)
        for key in ("build_before", "build_after"):
            result[key] = deepcopy(build)
        report["commands"].append(_command(root, case["id"] + "-configure", CONFIGURE_ARGV))
        failed = case["id"] == failed_case
        argv = ["./ci/blackbox.sh", "--driver=" + case["driver"],
                "--app=" + case["app"], "--args=" + " ".join(case["args"])]
        report["commands"].append(_command(root, case["id"], argv,
                                           configs=case["configs"], failed=failed, numerical=True))
        result["outcome"] = "fail" if failed else "pass"
        result["reason"] = "nonzero_exit" if failed else None
        if failed:
            stopped = True
        else:
            result["reference_marker_verified"] = True
            result.update(_case_artifacts(root, case))

    if not stopped:
        report["tools_after"] = deepcopy(tools)
        report["host_after"] = deepcopy(host)
        report["dependencies_after"] = deepcopy(dependencies)
        report["tooling_after"] = deepcopy(tooling)
    save_report(root, report)
    return report

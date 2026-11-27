#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Live VM toolchain, EDA, Docker, Python, disk, and RAM verifier.

Probes:
  1. Vortex prebuilt toolchain binaries (`verilator`, `yosys`, `yosys-smtbmc`,
     `sta`, `circt-verilog`, `riscv64-unknown-elf-gcc`, `clang`), running
     version probes and `ldd` shared-library checks (catching `not found` .so
     issues such as `libtinfo.so.5`).
  2. Additional EDA / infrastructure tools: `z3`, Docker daemon +
     `openroad/orfs:latest` image digest + container OpenROAD/KLayout health,
     `git submodule status`, and `ccache` size/limit.
  3. Active Python interpreter packages (`torch`, `numpy`, `onnx`, `scipy`,
     `pytest`, `yaml`, `pybind11`) and verification that `pytest` is not trapped
     in an isolated `pipx` venv missing `torch`/`numpy`.
  4. VM free disk space (`df` / `shutil.disk_usage`) and RAM/swap (`free`,
     `/proc/meminfo`, cgroup memory limit) against configurable thresholds.

Honesty contract:
  Every emitted report enforces `foundry_signoff=False`, `fpga_measured=False`,
  `silicon_measured=False`. Verifying local toolchain installation establishes
  environment readiness only and never certifies silicon or FPGA execution.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from typing import Any


SCHEMA_VERSION = 1
REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_TOOLDIR = Path.home() / "tools"
DEFAULT_BUILD_DIR = Path.home() / "vortex_builds/build64_b2"
DEFAULT_DOCKER_IMAGE = "openroad/orfs:latest"
DEFAULT_WARN_DISK_GIB = 20.0
DEFAULT_MIN_DISK_GIB = 10.0
DEFAULT_MIN_RAM_GIB = 4.0
SUBPROCESS_TIMEOUT_SEC = 15

# Relative candidate paths inside $TOOLDIR for Vortex prebuilt components.
VORTEX_TOOL_CANDIDATES: dict[str, tuple[str, ...]] = {
    "verilator": ("verilator/bin/verilator",),
    "yosys": ("yosys/bin/yosys",),
    "yosys-smtbmc": ("yosys/bin/yosys-smtbmc",),
    "sta": ("sta/bin/sta", "sta/sta"),
    "circt-verilog": ("circt/bin/circt-verilog",),
    "riscv64-unknown-elf-gcc": ("riscv64-gnu-toolchain/bin/riscv64-unknown-elf-gcc",),
    "clang": ("llvm-vortex/bin/clang",),
}

VERSION_FLAGS: dict[str, tuple[str, ...]] = {
    "verilator": ("--version",),
    "yosys": ("-V",),
    "yosys-smtbmc": ("--help",),
    "sta": ("-version",),
    "circt-verilog": ("--version",),
    "riscv64-unknown-elf-gcc": ("--version",),
    "clang": ("--version",),
    "z3": ("--version",),
}

REQUIRED_PYTHON_PACKAGES = (
    ("torch", "torch"),
    ("numpy", "numpy"),
    ("onnx", "onnx"),
    ("scipy", "scipy"),
    ("pytest", "pytest"),
    ("yaml", "yaml"),
    ("pybind11", "pybind11"),
)

LDD_NOT_FOUND_RE = re.compile(r"^\s*([^\s=>]+)\s*=>\s*not found\s*$", re.MULTILINE)


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str
    stderr: str
    timed_out: bool = False
    error: str = ""


def _run_cmd(
    argv: list[str],
    *,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
    timeout: int = SUBPROCESS_TIMEOUT_SEC,
) -> CommandResult:
    try:
        proc = subprocess.run(
            argv,
            cwd=cwd,
            env=env,
            capture_output=True,
            text=True,
            errors="replace",
            timeout=timeout,
            check=False,
        )
        return CommandResult(
            returncode=proc.returncode,
            stdout=proc.stdout,
            stderr=proc.stderr,
        )
    except subprocess.TimeoutExpired as exc:
        return CommandResult(
            returncode=124,
            stdout=exc.stdout.decode("utf-8", errors="replace") if isinstance(exc.stdout, bytes) else (exc.stdout or ""),
            stderr=exc.stderr.decode("utf-8", errors="replace") if isinstance(exc.stderr, bytes) else (exc.stderr or ""),
            timed_out=True,
            error=f"timed out after {timeout}s",
        )
    except OSError as exc:
        return CommandResult(
            returncode=127,
            stdout="",
            stderr="",
            error=str(exc),
        )


def parse_ldd_output(output: str) -> dict[str, Any]:
    """Parse `ldd` stdout/stderr and detect missing `.so` dependencies (`not found`)."""
    missing: list[str] = []
    resolved: list[dict[str, str]] = []
    not_dynamic = False

    if "not a dynamic executable" in output or "statically linked" in output:
        not_dynamic = True

    for line in output.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        m = LDD_NOT_FOUND_RE.match(line)
        if m:
            missing.append(m.group(1))
            continue
        if "=>" in stripped:
            left, right = stripped.split("=>", 1)
            lib_name = left.strip()
            target = right.strip()
            if target.startswith("not found"):
                missing.append(lib_name)
            else:
                resolved.append({"library": lib_name, "target": target})

    return {
        "ok": len(missing) == 0,
        "not_dynamic": not_dynamic,
        "missing_libs": sorted(set(missing)),
        "resolved_count": len(resolved),
    }


def parse_tool_version(tool_name: str, output: str) -> str:
    """Extract a clean single-line version string from a tool's `--version`/`-V` output."""
    lines = [ln.strip() for ln in output.splitlines() if ln.strip()]
    if not lines:
        return ""
    if tool_name == "verilator":
        for ln in lines:
            m = re.search(r"Verilator\s+([0-9]+\.[0-9]+[^\s]*)", ln, re.IGNORECASE)
            if m:
                return f"Verilator {m.group(1)}"
    elif tool_name == "yosys":
        for ln in lines:
            m = re.search(r"Yosys\s+([0-9]+\.[0-9]+[^\s]*)", ln, re.IGNORECASE)
            if m:
                return f"Yosys {m.group(1)}"
    elif tool_name == "yosys-smtbmc":
        return "yosys-smtbmc (present)"
    elif tool_name == "z3":
        for ln in lines:
            m = re.search(r"Z3\s+version\s+([0-9]+\.[0-9]+\.[0-9]+)", ln, re.IGNORECASE)
            if m:
                return f"Z3 {m.group(1)}"
    elif tool_name == "circt-verilog":
        for ln in lines:
            if "version" in ln.lower() or "circt" in ln.lower():
                return ln[:120]
    elif tool_name in ("riscv64-unknown-elf-gcc", "clang", "sta"):
        return lines[0][:120]
    return lines[0][:120]


def resolve_tool_binary(tool_name: str, tooldir: Path) -> Path | None:
    """Locate a tool binary in $TOOLDIR first, falling back to PATH."""
    for rel in VORTEX_TOOL_CANDIDATES.get(tool_name, ()):
        candidate = tooldir / rel
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return candidate
    which_path = shutil.which(tool_name)
    if which_path:
        return Path(which_path)
    return None


def probe_binary_tool(
    tool_name: str,
    tooldir: Path,
    *,
    runner: Any | None = None,
) -> dict[str, Any]:
    """Probe existence, `ldd` shared-library closure, and version output for a binary."""
    runner = runner or _run_cmd
    binary = resolve_tool_binary(tool_name, tooldir)
    if binary is None:
        return {
            "tool": tool_name,
            "found": False,
            "ok": False,
            "path": None,
            "version": "",
            "ldd": {"ok": False, "missing_libs": [], "not_dynamic": False, "resolved_count": 0},
            "error": f"{tool_name} not found in {tooldir} or PATH",
        }

    # Run ldd only on ELF binaries (skip Python scripts like yosys-smtbmc if shebang text).
    is_elf = False
    try:
        with binary.open("rb") as fh:
            is_elf = fh.read(4) == b"\x7fELF"
    except OSError:
        is_elf = False

    if is_elf and shutil.which("ldd"):
        ldd_res = runner(["ldd", str(binary)])
        ldd_info = parse_ldd_output(ldd_res.stdout + "\n" + ldd_res.stderr)
    else:
        ldd_info = {"ok": True, "missing_libs": [], "not_dynamic": True, "resolved_count": 0}

    flags = VERSION_FLAGS.get(tool_name, ("--version",))
    env = dict(os.environ)
    if (tooldir / "yosys/lib").is_dir():
        ld_prev = env.get("LD_LIBRARY_PATH", "")
        env["LD_LIBRARY_PATH"] = f"{tooldir / 'yosys/lib'}:{ld_prev}" if ld_prev else str(tooldir / "yosys/lib")
    ver_res = runner([str(binary), *flags], env=env)
    combined = (ver_res.stdout + "\n" + ver_res.stderr).strip()
    version = parse_tool_version(tool_name, combined)

    # Note: yosys-smtbmc --help exits 0 or 2 depending on version; sta -version exits 0.
    version_ok = ver_res.returncode == 0 or (tool_name == "yosys-smtbmc" and bool(combined))
    if not ldd_info["ok"]:
        err = f"Missing shared libraries: {', '.join(ldd_info['missing_libs'])}"
    elif not version_ok:
        err = ver_res.error or f"version command exited {ver_res.returncode}: {combined[:160]}"
    else:
        err = ""

    return {
        "tool": tool_name,
        "found": True,
        "ok": bool(ldd_info["ok"] and version_ok),
        "path": str(binary),
        "source": "tooldir" if str(binary).startswith(str(tooldir)) else "path",
        "version": version,
        "ldd": ldd_info,
        "error": err,
    }


def probe_z3(runner: Any | None = None) -> dict[str, Any]:
    """Probe Z3 SMT solver binary and/or z3-solver Python binding."""
    runner = runner or _run_cmd
    z3_bin = shutil.which("z3")
    bin_ok = False
    version = ""
    err = ""
    if z3_bin:
        res = runner([z3_bin, "--version"])
        version = parse_tool_version("z3", res.stdout + "\n" + res.stderr)
        bin_ok = res.returncode == 0
        if not bin_ok:
            err = res.error or f"z3 exited {res.returncode}"
    py_z3_spec = importlib.util.find_spec("z3") is not None
    if not z3_bin and not py_z3_spec:
        err = "neither z3 binary nor python z3 package found"
    return {
        "tool": "z3",
        "found": bool(z3_bin or py_z3_spec),
        "ok": bin_ok,
        "path": z3_bin,
        "python_z3_available": py_z3_spec,
        "version": version,
        "error": err,
    }


def parse_docker_image_digest(inspect_stdout: str) -> str:
    """Parse `docker image inspect` RepoDigests or Id output."""
    text = inspect_stdout.strip()
    if not text:
        return ""
    try:
        parsed = json.loads(text)
        if isinstance(parsed, list) and parsed:
            item = parsed[0]
            digests = item.get("RepoDigests") or []
            if digests:
                return str(digests[0])
            return str(item.get("Id", ""))
    except json.JSONDecodeError:
        pass
    return text.splitlines()[0].strip()


def probe_docker_orfs(
    docker_image: str = DEFAULT_DOCKER_IMAGE,
    *,
    skip_docker: bool = False,
    runner: Any | None = None,
) -> dict[str, Any]:
    """Probe Docker daemon health, ORFS image digest, and OpenROAD/KLayout container health."""
    runner = runner or _run_cmd
    if skip_docker:
        return {
            "skipped": True,
            "ok": True,
            "daemon_ok": False,
            "image": docker_image,
            "image_present": False,
            "image_digest": "",
            "openroad_version": "",
            "klayout_version": "",
            "error": "",
        }

    docker_bin = shutil.which("docker")
    if not docker_bin:
        return {
            "skipped": False,
            "ok": False,
            "daemon_ok": False,
            "image": docker_image,
            "image_present": False,
            "image_digest": "",
            "openroad_version": "",
            "klayout_version": "",
            "error": "docker CLI not found on PATH",
        }

    info_res = runner([docker_bin, "info", "--format", "{{.ServerVersion}}"])
    daemon_ok = info_res.returncode == 0
    if not daemon_ok:
        return {
            "skipped": False,
            "ok": False,
            "daemon_ok": False,
            "image": docker_image,
            "image_present": False,
            "image_digest": "",
            "openroad_version": "",
            "klayout_version": "",
            "error": f"Docker daemon unreachable: {(info_res.stderr or info_res.error).strip()[:160]}",
        }

    insp_res = runner([docker_bin, "image", "inspect", docker_image])
    image_present = insp_res.returncode == 0
    image_digest = parse_docker_image_digest(insp_res.stdout) if image_present else ""
    if not image_present:
        return {
            "skipped": False,
            "ok": False,
            "daemon_ok": True,
            "image": docker_image,
            "image_present": False,
            "image_digest": "",
            "openroad_version": "",
            "klayout_version": "",
            "error": f"Docker image {docker_image!r} not pulled locally",
        }

    or_cmd = (
        "if [ -f /OpenROAD-flow-scripts/env.sh ]; then "
        "source /OpenROAD-flow-scripts/env.sh >/dev/null 2>&1; fi; "
        "openroad -version; "
        '(klayout -v 2>/dev/null || python3 -c "import klayout.db, importlib.metadata as m; print(\\"klayout\\", m.version(\\"klayout\\"))")'
    )
    or_res = runner([
        docker_bin, "run", "--rm", docker_image,
        "bash", "-lc", or_cmd,
    ], timeout=30)
    combined = (or_res.stdout + "\n" + or_res.stderr).strip()
    or_ver = ""
    kl_ver = ""
    for line in combined.splitlines():
        s = line.strip()
        if not s:
            continue
        low = s.lower()
        if "command not found" in low or "no module named" in low:
            continue
        if "klayout" in low and not kl_ver:
            kl_ver = s[:120]
        elif not or_ver and (
            "openroad" in low
            or low == "unknown"
            or re.match(r"^(?:[0-9a-f]{7,}|v?[0-9]+(?:Q[1-4]|\.[0-9]+))", s)
        ):
            or_ver = s[:120]

    ok = or_res.returncode == 0 and bool(or_ver) and bool(kl_ver)
    return {
        "skipped": False,
        "ok": ok,
        "daemon_ok": True,
        "daemon_version": info_res.stdout.strip(),
        "image": docker_image,
        "image_present": True,
        "image_digest": image_digest,
        "openroad_version": or_ver,
        "klayout_version": kl_ver,
        "error": "" if ok else f"ORFS container probe failed: {combined[:160]}",
    }


def probe_python_environment(
    python_exe: str | None = None,
    *,
    runner: Any | None = None,
) -> dict[str, Any]:
    """Probe active Python packages and verify pytest is not trapped in an isolated pipx venv."""
    runner = runner or _run_cmd
    exe = python_exe or sys.executable
    pkg_script = (
        "import importlib, json\n"
        "out = {}\n"
        "for name in ['torch', 'numpy', 'onnx', 'scipy', 'pytest', 'yaml', 'pybind11']:\n"
        "    try:\n"
        "        m = importlib.import_module(name)\n"
        "        out[name] = {'installed': True, 'version': str(getattr(m, '__version__', 'installed')), 'file': str(getattr(m, '__file__', ''))}\n"
        "    except Exception as e:\n"
        "        out[name] = {'installed': False, 'version': '', 'error': str(e)}\n"
        "print(json.dumps(out))\n"
    )
    res = runner([exe, "-c", pkg_script])
    packages: dict[str, Any] = {}
    if res.returncode == 0 and res.stdout.strip():
        try:
            packages = json.loads(res.stdout.strip().splitlines()[-1])
        except json.JSONDecodeError:
            packages = {}

    missing_packages = [
        name for name, _ in REQUIRED_PYTHON_PACKAGES
        if not packages.get(name, {}).get("installed", False)
    ]

    pytest_bin = shutil.which("pytest")
    pytest_in_pipx = bool(pytest_bin and "/pipx/" in os.path.realpath(pytest_bin))
    pytest_isolated_missing_deps = False
    pytest_probe_detail = ""

    if pytest_bin:
        p_res = runner([pytest_bin, "--version"])
        pytest_probe_detail = (p_res.stdout + " " + p_res.stderr).strip().splitlines()[0] if (p_res.stdout or p_res.stderr).strip() else ""
        # Check if the `pytest` CLI's interpreter can import torch and numpy.
        try:
            first_line = Path(pytest_bin).read_text(encoding="utf-8", errors="replace").splitlines()[0]
            if first_line.startswith("#!"):
                pytest_py = first_line[2:].strip().split()[0]
                chk = runner([pytest_py, "-c", "import torch, numpy"])
                if chk.returncode != 0:
                    pytest_isolated_missing_deps = True
        except OSError:
            pass

    module_pytest_ok = packages.get("pytest", {}).get("installed", False)
    pipx_trap = pytest_in_pipx and pytest_isolated_missing_deps

    return {
        "ok": len(missing_packages) == 0 and not pipx_trap and module_pytest_ok,
        "python_executable": exe,
        "python_version": sys.version.split()[0],
        "packages": packages,
        "missing_packages": missing_packages,
        "pytest_cli_path": pytest_bin,
        "pytest_cli_resolved": os.path.realpath(pytest_bin) if pytest_bin else None,
        "pytest_in_pipx": pytest_in_pipx,
        "pytest_isolated_missing_torch_numpy": pytest_isolated_missing_deps,
        "pytest_cli_banner": pytest_probe_detail,
        "pipx_trap_detected": pipx_trap,
        "recommendation": (
            f"Run tests via '{exe} -m pytest' or install pytest into {exe} instead of isolated pipx pytest"
            if pipx_trap else ""
        ),
    }


def probe_git_submodules(repo_root: Path, *, runner: Any | None = None) -> dict[str, Any]:
    """Check `git submodule status` across repo submodules."""
    runner = runner or _run_cmd
    res = runner(["git", "submodule", "status"], cwd=repo_root)
    if res.returncode != 0:
        return {
            "ok": False,
            "total": 0,
            "uninitialized": [],
            "modified": [],
            "conflicts": [],
            "entries": [],
            "error": (res.stderr or res.error).strip()[:160],
        }
    entries: list[dict[str, str]] = []
    uninit: list[str] = []
    modified: list[str] = []
    conflicts: list[str] = []
    for line in res.stdout.splitlines():
        if not line:
            continue
        flag = line[0]
        rest = line[1:].strip().split()
        if len(rest) < 2:
            continue
        commit, path = rest[0], rest[1]
        state = {
            " ": "clean",
            "-": "uninitialized",
            "+": "modified",
            "U": "conflict",
        }.get(flag, "unknown")
        entries.append({"path": path, "commit": commit, "state": state})
        if state == "uninitialized":
            uninit.append(path)
        elif state == "modified":
            modified.append(path)
        elif state == "conflict":
            conflicts.append(path)
    return {
        "ok": len(conflicts) == 0,
        "total": len(entries),
        "uninitialized": uninit,
        "modified": modified,
        "conflicts": conflicts,
        "entries": entries,
        "error": "",
    }


def parse_ccache_stats(output: str) -> dict[str, Any]:
    """Parse `ccache -s` / `ccache --print-config` output for cache size and limit."""
    cache_size = ""
    max_size = ""
    hits = ""
    misses = ""
    for line in output.splitlines():
        low = line.lower()
        if "cache size" in low or "primary storage" in low:
            if ":" in line:
                cache_size = line.split(":", 1)[1].strip()
        elif "max cache size" in low or "max_size" in low:
            if ":" in line:
                max_size = line.split(":", 1)[1].strip()
            elif "=" in line:
                max_size = line.split("=", 1)[1].strip()
        elif "hits" in low and ":" in line and not hits:
            hits = line.split(":", 1)[1].strip()
        elif "misses" in low and ":" in line and not misses:
            misses = line.split(":", 1)[1].strip()
    return {
        "cache_size": cache_size,
        "max_size": max_size,
        "hits": hits,
        "misses": misses,
    }


def probe_ccache(runner: Any | None = None) -> dict[str, Any]:
    """Probe `ccache` installation, cache size, and configured max size."""
    runner = runner or _run_cmd
    ccache_bin = shutil.which("ccache")
    if not ccache_bin:
        return {"found": False, "ok": False, "path": None, "stats": {}, "error": "ccache not found"}
    stat_res = runner([ccache_bin, "-s"])
    cfg_res = runner([ccache_bin, "-p"])
    parsed = parse_ccache_stats(stat_res.stdout + "\n" + cfg_res.stdout)
    return {
        "found": True,
        "ok": stat_res.returncode == 0,
        "path": ccache_bin,
        "stats": parsed,
        "error": "" if stat_res.returncode == 0 else (stat_res.stderr or stat_res.error).strip()[:160],
    }


def parse_proc_meminfo(text: str) -> dict[str, int]:
    """Parse `/proc/meminfo` fields into KiB integers."""
    values: dict[str, int] = {}
    for line in text.splitlines():
        if ":" not in line:
            continue
        key, rest = line.split(":", 1)
        m = re.search(r"([0-9]+)", rest)
        if m:
            values[key.strip()] = int(m.group(1))
    return values


def _read_cgroup_memory_limit_bytes() -> int | None:
    for path_str in (
        "/sys/fs/cgroup/memory.max",
        "/sys/fs/cgroup/memory/memory.limit_in_bytes",
    ):
        p = Path(path_str)
        if p.is_file():
            raw = p.read_text(encoding="utf-8", errors="replace").strip()
            if raw == "max":
                return None
            if raw.isdigit():
                val = int(raw)
                # Ignore sentinel huge values (> 1 PiB).
                if 0 < val < (1 << 50):
                    return val
    return None


def probe_disk_and_ram(
    target_path: Path,
    *,
    warn_disk_gib: float = DEFAULT_WARN_DISK_GIB,
    min_disk_gib: float = DEFAULT_MIN_DISK_GIB,
    min_ram_gib: float = DEFAULT_MIN_RAM_GIB,
    meminfo_path: Path = Path("/proc/meminfo"),
    disk_usage_fn: Any = shutil.disk_usage,
) -> dict[str, Any]:
    """Check free disk space and RAM/swap/cgroup limits against safety thresholds."""
    usage_path = target_path if target_path.exists() else target_path.parent
    if not usage_path.exists():
        usage_path = Path("/")
    total_b, used_b, free_b = disk_usage_fn(usage_path)
    gib = float(1024 ** 3)
    free_disk_gib = round(free_b / gib, 2)
    total_disk_gib = round(total_b / gib, 2)
    used_disk_gib = round(used_b / gib, 2)

    meminfo: dict[str, int] = {}
    if meminfo_path.is_file():
        meminfo = parse_proc_meminfo(meminfo_path.read_text(encoding="utf-8", errors="replace"))

    mem_total_gib = round(meminfo.get("MemTotal", 0) * 1024 / gib, 2)
    mem_avail_gib = round(meminfo.get("MemAvailable", meminfo.get("MemFree", 0)) * 1024 / gib, 2)
    swap_total_gib = round(meminfo.get("SwapTotal", 0) * 1024 / gib, 2)
    swap_free_gib = round(meminfo.get("SwapFree", 0) * 1024 / gib, 2)
    cgroup_limit_b = _read_cgroup_memory_limit_bytes()
    cgroup_limit_gib = round(cgroup_limit_b / gib, 2) if cgroup_limit_b is not None else None

    effective_ram_gib = mem_total_gib
    if cgroup_limit_gib is not None and cgroup_limit_gib < effective_ram_gib:
        effective_ram_gib = cgroup_limit_gib

    warnings: list[str] = []
    errors: list[str] = []

    if free_disk_gib < min_disk_gib:
        errors.append(f"Free disk {free_disk_gib:.2f} GiB < hard minimum {min_disk_gib:.2f} GiB")
    elif free_disk_gib < warn_disk_gib:
        warnings.append(f"Free disk {free_disk_gib:.2f} GiB < warning threshold {warn_disk_gib:.2f} GiB")

    if mem_total_gib > 0 and effective_ram_gib < min_ram_gib:
        errors.append(f"Effective RAM {effective_ram_gib:.2f} GiB < minimum {min_ram_gib:.2f} GiB")

    return {
        "ok": len(errors) == 0,
        "disk": {
            "path": str(usage_path),
            "total_gib": total_disk_gib,
            "used_gib": used_disk_gib,
            "free_gib": free_disk_gib,
            "warn_threshold_gib": warn_disk_gib,
            "min_threshold_gib": min_disk_gib,
        },
        "memory": {
            "mem_total_gib": mem_total_gib,
            "mem_available_gib": mem_avail_gib,
            "swap_total_gib": swap_total_gib,
            "swap_free_gib": swap_free_gib,
            "cgroup_limit_gib": cgroup_limit_gib,
            "effective_ram_gib": effective_ram_gib,
            "min_ram_gib": min_ram_gib,
        },
        "warnings": warnings,
        "errors": errors,
    }


def probe_build_dir(build_dir: Path) -> dict[str, Any]:
    """Inspect whether an out-of-tree Vortex build directory is configured and built."""
    exists = build_dir.is_dir()
    vx_config_h = (build_dir / "sw/VX_config.h").is_file() or (build_dir / "hw/VX_config.vh").is_file()
    simx_candidates = (
        build_dir / "sw/runtime/libvortex-simx.so",
        build_dir / "sw/runtime/libsimx.so",
        build_dir / "sim/simx/simx",
        build_dir / "runtime/libvortex-simx.so",
        build_dir / "runtime/libsimx.so",
    )
    rtlsim_candidates = (
        build_dir / "sw/runtime/libvortex-rtlsim.so",
        build_dir / "sw/runtime/librtlsim.so",
        build_dir / "runtime/libvortex-rtlsim.so",
        build_dir / "runtime/librtlsim.so",
    )
    simx_bin = any(p.is_file() for p in simx_candidates)
    rtlsim_lib = any(p.is_file() for p in rtlsim_candidates)
    return {
        "path": str(build_dir),
        "exists": exists,
        "configured": vx_config_h,
        "simx_built": simx_bin,
        "rtlsim_built": rtlsim_lib,
    }


def run_verification(
    *,
    repo_root: Path = REPO_ROOT,
    tooldir: Path = DEFAULT_TOOLDIR,
    build_dir: Path = DEFAULT_BUILD_DIR,
    docker_image: str = DEFAULT_DOCKER_IMAGE,
    skip_docker: bool = False,
    warn_disk_gib: float = DEFAULT_WARN_DISK_GIB,
    min_disk_gib: float = DEFAULT_MIN_DISK_GIB,
    min_ram_gib: float = DEFAULT_MIN_RAM_GIB,
    runner: Any | None = None,
) -> dict[str, Any]:
    """Execute complete VM toolchain, EDA, Docker, Python, disk, and RAM verification."""
    runner = runner or _run_cmd
    tools: dict[str, Any] = {}
    for tool_name in VORTEX_TOOL_CANDIDATES:
        tools[tool_name] = probe_binary_tool(tool_name, tooldir, runner=runner)
    tools["z3"] = probe_z3(runner=runner)

    docker_status = probe_docker_orfs(
        docker_image=docker_image,
        skip_docker=skip_docker,
        runner=runner,
    )
    python_status = probe_python_environment(runner=runner)
    submodules = probe_git_submodules(repo_root, runner=runner)
    ccache = probe_ccache(runner=runner)
    resources = probe_disk_and_ram(
        repo_root,
        warn_disk_gib=warn_disk_gib,
        min_disk_gib=min_disk_gib,
        min_ram_gib=min_ram_gib,
    )
    build_status = probe_build_dir(build_dir)

    tools_ok = all(t["ok"] for t in tools.values())
    overall_ok = (
        tools_ok
        and docker_status["ok"]
        and python_status["ok"]
        and submodules["ok"]
        and resources["ok"]
    )

    failing_checks: list[str] = []
    for name, info in tools.items():
        if not info["ok"]:
            failing_checks.append(f"tool:{name}: {info.get('error', 'failed')}")
    if not docker_status["ok"]:
        failing_checks.append(f"docker: {docker_status.get('error', 'failed')}")
    if not python_status["ok"]:
        failing_checks.append(
            f"python: missing={python_status['missing_packages']} pipx_trap={python_status['pipx_trap_detected']}"
        )
    if not submodules["ok"]:
        failing_checks.append(f"git_submodules: {submodules.get('error', 'conflict')}")
    for err in resources["errors"]:
        failing_checks.append(f"resources: {err}")

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "evidence_level": "source_present",
        "foundry_signoff": False,
        "fpga_measured": False,
        "silicon_measured": False,
        "physical_gates_unwaived": True,
        "ok": overall_ok,
        "tooldir": str(tooldir),
        "build_dir": build_status,
        "tools": tools,
        "docker_orfs": docker_status,
        "python": python_status,
        "git_submodules": submodules,
        "ccache": ccache,
        "resources": resources,
        "failing_checks": failing_checks,
    }


def render_markdown_report(report: dict[str, Any]) -> str:
    """Format verification report as clean Markdown table for runbooks and handoffs."""
    res = report["resources"]
    disk = res["disk"]
    mem = res["memory"]
    docker = report["docker_orfs"]
    py = report["python"]

    lines = [
        "## ADR-007 VM Toolchain & Environment Verification Report",
        "",
        f"- **Overall Status:** `{'PASS' if report['ok'] else 'FAIL'}`",
        f"- **TOOLDIR:** `{report['tooldir']}`",
        f"- **Disk Free:** `{disk['free_gib']:.2f} GiB` / `{disk['total_gib']:.2f} GiB` (warn `<{disk['warn_threshold_gib']} GiB`, fail `<{disk['min_threshold_gib']} GiB`)",
        f"- **RAM / Swap:** `{mem['mem_total_gib']:.2f} GiB` total (`{mem['mem_available_gib']:.2f} GiB` avail) | Swap `{mem['swap_total_gib']:.2f} GiB`",
        f"- **Honesty Boundary:** `foundry_signoff=false`, `fpga_measured=false`, `silicon_measured=false`",
        "",
        "### Prebuilt & EDA Binaries",
        "",
        "| Tool | Status | Path | Version | Missing Shared Libs |",
        "|---|---|---|---|---|",
    ]
    for name, info in report["tools"].items():
        status = "PASS" if info["ok"] else "FAIL"
        path = info.get("path") or "—"
        ver = info.get("version") or info.get("error", "—")
        missing_so = ", ".join(info.get("ldd", {}).get("missing_libs", [])) or "none"
        lines.append(f"| `{name}` | `{status}` | `{path}` | {ver} | `{missing_so}` |")

    lines.extend([
        "",
        "### Docker ORFS, Python & Cache",
        "",
        f"- **Docker `{docker['image']}`:** `{'SKIPPED' if docker.get('skipped') else ('PASS' if docker['ok'] else 'FAIL')}`"
        + (f" (OpenROAD: `{docker['openroad_version']}`, KLayout: `{docker['klayout_version']}`)" if docker.get("openroad_version") else ""),
        f"- **Python (`{py['python_executable']}`):** `{'PASS' if py['ok'] else 'FAIL'}` | Missing: `{py['missing_packages']}` | `pipx_trap={py['pipx_trap_detected']}`",
        f"- **ccache:** `{'PASS' if report['ccache']['ok'] else 'MISSING'}` | Size: `{report['ccache']['stats'].get('cache_size', 'n/a')}` | Max: `{report['ccache']['stats'].get('max_size', 'n/a')}`",
        f"- **Git Submodules:** `{report['git_submodules']['total']}` total (`{len(report['git_submodules']['uninitialized'])}` uninitialized)",
    ])
    if report["failing_checks"]:
        lines.extend(["", "### Failing Checks", ""])
        for item in report["failing_checks"]:
            lines.append(f"- `{item}`")
    return "\n".join(lines) + "\n"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Verify live VM toolchain, EDA, Docker ORFS, Python, disk, and RAM readiness."
    )
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--tooldir", type=Path, default=DEFAULT_TOOLDIR)
    parser.add_argument("--build-dir", type=Path, default=DEFAULT_BUILD_DIR)
    parser.add_argument("--docker-image", default=DEFAULT_DOCKER_IMAGE)
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument("--check-all", action="store_true", help="Run all readiness checks (default).")
    mode_group.add_argument("--skip-docker", action="store_true", help="Skip Docker ORFS container probe.")
    parser.add_argument("--min-disk-gib", type=float, default=DEFAULT_MIN_DISK_GIB)
    parser.add_argument("--warn-disk-gib", type=float, default=DEFAULT_WARN_DISK_GIB)
    parser.add_argument("--min-ram-gib", type=float, default=DEFAULT_MIN_RAM_GIB)
    output_group = parser.add_mutually_exclusive_group()
    output_group.add_argument("--json", action="store_true", help="Emit structured JSON output.")
    output_group.add_argument("--markdown", action="store_true", help="Emit Markdown readiness report.")
    parser.add_argument("--output", type=Path, default=None, help="Optional file path to write output.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    report = run_verification(
        repo_root=args.repo_root.resolve(),
        tooldir=args.tooldir,
        build_dir=args.build_dir,
        docker_image=args.docker_image,
        skip_docker=args.skip_docker,
        warn_disk_gib=args.warn_disk_gib,
        min_disk_gib=args.min_disk_gib,
        min_ram_gib=args.min_ram_gib,
    )

    if args.json:
        rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
    elif args.markdown:
        rendered = render_markdown_report(report)
    else:
        status = "PASS" if report["ok"] else "FAIL"
        tools_ok = sum(1 for t in report["tools"].values() if t["ok"])
        rendered = (
            f"B2 Toolchain Verify {status}: "
            f"tools={tools_ok}/{len(report['tools'])} | "
            f"docker={'SKIP' if report['docker_orfs'].get('skipped') else ('PASS' if report['docker_orfs']['ok'] else 'FAIL')} | "
            f"python={'PASS' if report['python']['ok'] else 'FAIL'} | "
            f"disk_free={report['resources']['disk']['free_gib']:.2f}GiB | "
            f"ram={report['resources']['memory']['mem_total_gib']:.2f}GiB | "
            f"foundry_signoff=false silicon_measured=false\n"
        )
        if report["failing_checks"]:
            rendered += "\n".join(f"  - {c}" for c in report["failing_checks"]) + "\n"

    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")

    sys.stdout.write(rendered)
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

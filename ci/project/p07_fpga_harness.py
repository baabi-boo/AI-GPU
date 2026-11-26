#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""P07 physical FPGA preflight, execution planner, and soak telemetry analyzer.

This tool enforces strict evidence-level separation: emulation targets
(hw_emu, xrtsim) and simulator targets (simx, rtlsim) are unconditionally
rejected for `fpga_measured` claims. Offline execution of this CLI never
certifies physical FPGA hardware.
"""

from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from typing import Any


SCHEMA_VERSION = 1
MIN_SOAK_SECONDS = 3600.0
DEFAULT_MAX_TEMP_C = 95.0
DEFAULT_MAX_POWER_W = 225.0

NON_PHYSICAL_TARGETS = ("hw_emu", "xrtsim", "avedsim", "simx", "rtlsim", "sw_emu", "sim", "emu")
PHYSICAL_DRIVERS = frozenset({"xrt", "aved"})
NON_PHYSICAL_DRIVERS = frozenset({"simx", "rtlsim", "xrtsim", "avedsim", "foldsim", "firesim", "opaesim", "stub", "null", "emulation"})
SUPPORTED_BOARDS = {
    "u55c": {
        "board": "u55c",
        "part": "xcu55c-fsvh2892-2L-e",
        "driver": "xrt",
        "flow": "xrt",
        "memory_type": "HBM2",
        "memory_banks": 32,
        "bank_size_bytes": 512 * 1024 * 1024,
        "total_memory_bytes": 16 * 1024 * 1024 * 1024,
        "default_platform": "xilinx_u55c_gen3x16_xdma_3_202210_1",
        "bitstream_ext": ".xclbin",
        "capacity": {
            "lut": 1_303_680,
            "ff": 2_607_360,
            "bram": 2_016,
            "uram": 960,
            "dsp": 9_024,
        },
    },
    "v80": {
        "board": "v80",
        "part": "xcv80-lsva4737-2MHP-e-S",
        "driver": "aved",
        "flow": "aved",
        "memory_type": "HBM2e",
        "memory_banks": 1,
        "bank_size_bytes": 32 * 1024 * 1024 * 1024,
        "total_memory_bytes": 32 * 1024 * 1024 * 1024,
        "default_platform": "xcv80-lsva4737-2MHP-e-S",
        "bitstream_ext": ".vbin",
        "capacity": {
            "lut": None,
            "ff": None,
            "bram": None,
            "uram": None,
            "dsp": None,
        },
    },
}

BDF_PATTERN = re.compile(r"^[0-9a-fA-F]{4}:[0-9a-fA-F]{2}:[0-9a-fA-F]{2}\.[0-9a-fA-F]$")
PLATFORM_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:+-]{0,127}$")
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


def _is_finite_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _is_nonneg_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _is_ready_false(value: Any) -> bool:
    if value is False:
        return True
    if isinstance(value, str) and value.strip().lower() == "false":
        return True
    return False


def _normalize_bdf(bdf: str | None) -> str | None:
    if not isinstance(bdf, str):
        return None
    text = bdf.strip().lower()
    if re.fullmatch(r"[0-9a-f]{2}:[0-9a-f]{2}\.[0-9a-f]", text):
        text = "0000:" + text
    if not BDF_PATTERN.fullmatch(text):
        return None
    return text


def _sha256_file(path: Path, *, label: str = "bitstream") -> tuple[str | None, int | None, str | None]:
    try:
        resolved = path.resolve(strict=True)
        if not resolved.is_file():
            return None, None, f"{label} path is not a regular file: {path}"
        digest = hashlib.sha256()
        size = 0
        with resolved.open("rb") as handle:
            while True:
                chunk = handle.read(1024 * 1024)
                if not chunk:
                    break
                digest.update(chunk)
                size += len(chunk)
        if size == 0:
            return None, 0, f"{label} file is empty: {path}"
        return digest.hexdigest(), size, None
    except OSError as exc:
        return None, None, f"cannot read {label} file ({type(exc).__name__}): {path}"


def _run_xbutil_examine(xbutil_path: str, bdf: str, timeout_s: float = 15.0) -> tuple[dict[str, Any] | None, str | None]:
    try:
        proc = subprocess.run(
            [xbutil_path, "examine", "-d", bdf, "--format", "json"],
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout_s,
        )
    except (OSError, subprocess.TimeoutExpired, UnicodeError) as exc:
        return None, f"xbutil examine invocation failed ({type(exc).__name__})"
    if proc.returncode != 0:
        return None, f"xbutil examine exited with code {proc.returncode}"
    try:
        payload = json.loads(proc.stdout)
    except ValueError:
        return None, "xbutil examine output is not valid JSON"
    if not isinstance(payload, dict):
        return None, "xbutil examine JSON root must be an object"
    return payload, None


def _run_v80_smi_list(v80_smi_path: str, bdf: str, timeout_s: float = 20.0) -> tuple[dict[str, Any] | None, str | None]:
    try:
        proc = subprocess.run(
            [v80_smi_path, "list"],
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout_s,
        )
    except (OSError, subprocess.TimeoutExpired, UnicodeError) as exc:
        return None, f"v80-smi list invocation failed ({type(exc).__name__})"
    if proc.returncode != 0:
        return None, f"v80-smi list exited with code {proc.returncode}"

    output = proc.stdout or ""
    lowered = output.lower()
    for token in ("hw_emu", "sw_emu", "xrtsim", "avedsim", "emulation", "simulator"):
        if token in lowered:
            return None, f"device identity indicates non-physical target ({token})"

    short_bdf = bdf[5:] if bdf.startswith("0000:") else bdf
    bus_dev = short_bdf.rsplit(".", 1)[0]
    bdf_pattern = re.compile(
        rf"(?:0000:)?{re.escape(bus_dev)}(?:\.{re.escape(short_bdf.rsplit('.', 1)[1])})?(?![0-9a-fA-F.:])",
        re.IGNORECASE,
    )
    matching_lines = [line.strip() for line in output.splitlines() if bdf_pattern.search(line)]
    if not matching_lines:
        return None, f"target physical BDF {bdf} not found in v80-smi list output"

    line = matching_lines[0]
    line_lower = line.lower()
    is_ready = (
        "not ready" not in line_lower
        and "no_amc" not in line_lower
        and "pf0: ok" in line_lower
        and "vrtd: ok" in line_lower
    )
    return {
        "bdf": bdf,
        "vbnv": SUPPORTED_BOARDS["v80"]["part"],
        "is_ready": is_ready,
        "raw_line": line,
    }, None


def _extract_xbutil_device(payload: dict[str, Any], expected_bdf: str) -> tuple[dict[str, Any] | None, str | None]:
    """Extract matching physical device identity from xbutil examine JSON."""
    devices: list[dict[str, Any]] = []
    system = payload.get("system")
    if isinstance(system, dict) and isinstance(system.get("host"), dict):
        host_devs = system["host"].get("devices")
        if isinstance(host_devs, list):
            devices.extend(d for d in host_devs if isinstance(d, dict))
    if not devices and isinstance(payload.get("devices"), list):
        devices.extend(d for d in payload["devices"] if isinstance(d, dict))

    if not devices:
        return None, "xbutil examine reported zero devices"

    for dev in devices:
        raw_bdf = dev.get("bdf") or dev.get("vbnv_bdf")
        norm = _normalize_bdf(raw_bdf)
        if norm == expected_bdf:
            return dev, None

    return None, f"target physical BDF {expected_bdf} not found in xbutil examine output"


def _device_looks_emulated(device: dict[str, Any]) -> str | None:
    text_blobs = []
    for key in ("vbnv", "platform", "name", "interface_uuid", "is_ready", "class"):
        val = device.get(key)
        if val is not None:
            text_blobs.append(str(val).lower())
    platforms = device.get("platforms")
    if isinstance(platforms, list):
        for entry in platforms:
            if isinstance(entry, dict):
                sp = entry.get("static_region") or {}
                if isinstance(sp, dict):
                    text_blobs.append(str(sp.get("vbnv", "")).lower())
                    text_blobs.append(str(sp.get("name", "")).lower())
    joined = " ".join(text_blobs)
    for token in ("hw_emu", "sw_emu", "xrtsim", "avedsim", "emulation", "simulator"):
        if token in joined:
            return f"device identity indicates non-physical target ({token})"
    return None


def _extract_platform_vbnv(device: dict[str, Any]) -> str | None:
    for key in ("vbnv", "platform", "name"):
        val = device.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    platforms = device.get("platforms")
    if isinstance(platforms, list):
        for entry in platforms:
            if isinstance(entry, dict):
                static = entry.get("static_region")
                if isinstance(static, dict) and isinstance(static.get("vbnv"), str) and static["vbnv"].strip():
                    return static["vbnv"].strip()
    return None


def run_preflight(
    *,
    board: str = "u55c",
    target: str,
    requested_evidence: str,
    bdf: str | None,
    platform: str | None,
    xclbin: Path | None,
    expected_sha256: str | None = None,
    probe_device: bool = True,
    environ: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Validate prerequisites for physical FPGA execution without claiming pass lightly."""
    env = os.environ if environ is None else environ
    blockers: list[str] = []
    warnings: list[str] = []

    board_key = (board or "").strip().lower()
    if board_key not in SUPPORTED_BOARDS:
        blockers.append(
            f"unsupported board {board!r}; expected one of {sorted(SUPPORTED_BOARDS)}"
        )
        spec = SUPPORTED_BOARDS["u55c"]
    else:
        spec = SUPPORTED_BOARDS[board_key]

    driver = spec["driver"]
    norm_target = (target or "").strip().lower()
    if norm_target != "hw":
        blockers.append(
            f"target {target!r} is non-physical; `fpga_measured` strictly requires --target hw "
            f"(hw_emu/xrtsim/avedsim/simx/rtlsim are rejected)"
        )

    if requested_evidence not in ("fpga_measured", "source_present"):
        blockers.append(f"unsupported evidence level request: {requested_evidence!r}")

    if requested_evidence == "fpga_measured" and norm_target != "hw":
        blockers.append("cannot claim `fpga_measured` without --target hw")

    emu_env = env.get("XCL_EMULATION_MODE", "").strip()
    if emu_env:
        blockers.append(
            f"XCL_EMULATION_MODE={emu_env!r} is set; physical `hw` execution requires it unset"
        )

    norm_bdf = _normalize_bdf(bdf)
    if norm_bdf is None:
        blockers.append(
            "physical PCIe BDF is missing or malformed (expected e.g. 0000:3d:00.1)"
        )

    xrt_root = env.get("XILINX_XRT", "").strip()
    fpga_bin_dir = env.get("FPGA_BIN_DIR", "").strip()
    vrt_device_bdf = env.get("VRT_DEVICE_BDF", "").strip()
    xbutil_path: str | None = None
    v80_smi_path: str | None = None
    v80_preflight_script: str | None = None

    if board_key == "u55c":
        if not xrt_root:
            blockers.append("XILINX_XRT environment variable is not set")
        elif not Path(xrt_root).is_dir():
            blockers.append(f"XILINX_XRT does not point to an existing directory: {xrt_root}")
        xbutil_path = shutil.which("xbutil", path=env.get("PATH"))
        if xbutil_path is None:
            blockers.append("`xbutil` executable not found on PATH")
        if fpga_bin_dir and not Path(fpga_bin_dir).is_dir():
            blockers.append(f"FPGA_BIN_DIR does not point to an existing directory: {fpga_bin_dir}")
    elif board_key == "v80":
        v80_smi_path = shutil.which("v80-smi", path=env.get("PATH"))
        if v80_smi_path is None:
            blockers.append("`v80-smi` executable not found on PATH")
        preflight_candidate = Path(__file__).resolve().parents[1] / "v80_preflight.sh"
        if preflight_candidate.is_file():
            v80_preflight_script = str(preflight_candidate)
        else:
            warnings.append("ci/v80_preflight.sh not found in repository tree")
        if vrt_device_bdf:
            norm_env_bdf = _normalize_bdf(vrt_device_bdf)
            if norm_env_bdf is None:
                blockers.append(f"VRT_DEVICE_BDF is malformed: {vrt_device_bdf!r}")
            elif norm_bdf is not None and norm_env_bdf != norm_bdf:
                blockers.append(
                    f"VRT_DEVICE_BDF ({norm_env_bdf}) does not match requested --bdf ({norm_bdf})"
                )
        elif norm_bdf is not None:
            warnings.append(
                f"VRT_DEVICE_BDF is unset; set VRT_DEVICE_BDF={norm_bdf} before running ci/v80_preflight.sh or AVED hw"
            )

    if not platform or not PLATFORM_PATTERN.fullmatch(platform.strip()):
        blockers.append("target platform VBNV/name is missing or malformed")
    else:
        for token in NON_PHYSICAL_TARGETS:
            if token in platform.lower():
                blockers.append(
                    f"platform string {platform!r} contains non-physical marker {token!r}"
                )
                break

    xclbin_sha256: str | None = None
    xclbin_size: int | None = None
    expected_ext = spec["bitstream_ext"]
    bitstream_label = "xclbin" if board_key == "u55c" else "vbin"
    if xclbin is None:
        blockers.append(f"bitstream {expected_ext} path is required")
    else:
        if xclbin.suffix != expected_ext:
            warnings.append(f"bitstream path does not end with {expected_ext}: {xclbin.name}")
        xclbin_sha256, xclbin_size, err = _sha256_file(xclbin, label=bitstream_label)
        if err is not None:
            blockers.append(err)
        elif expected_sha256 is not None:
            exp = expected_sha256.strip().lower()
            if not SHA256_PATTERN.fullmatch(exp):
                blockers.append("expected --xclbin-sha256 is not a valid 64-hex digest")
            elif xclbin_sha256 != exp:
                blockers.append(
                    f"bitstream SHA-256 mismatch: expected {exp}, observed {xclbin_sha256}"
                )

    device_identity: dict[str, Any] | None = None
    if probe_device and norm_bdf is not None and norm_target == "hw":
        if board_key == "u55c" and xbutil_path is not None:
            payload, xbutil_err = _run_xbutil_examine(xbutil_path, norm_bdf)
            if xbutil_err is not None:
                blockers.append(xbutil_err)
            else:
                assert payload is not None
                dev, dev_err = _extract_xbutil_device(payload, norm_bdf)
                if dev_err is not None:
                    blockers.append(dev_err)
                else:
                    assert dev is not None
                    emu_err = _device_looks_emulated(dev)
                    if emu_err is not None:
                        blockers.append(emu_err)
                    observed_vbnv = _extract_platform_vbnv(dev)
                    if platform and observed_vbnv and platform.strip() != observed_vbnv:
                        blockers.append(
                            f"platform mismatch: requested {platform.strip()!r}, device reports {observed_vbnv!r}"
                        )
                    if _is_ready_false(dev.get("is_ready")):
                        blockers.append(f"physical device {norm_bdf} reports is_ready=false")
                    device_identity = {
                        "bdf": norm_bdf,
                        "vbnv": observed_vbnv,
                        "is_ready": dev.get("is_ready"),
                    }
        elif board_key == "v80" and v80_smi_path is not None:
            v80_dev, v80_err = _run_v80_smi_list(v80_smi_path, norm_bdf)
            if v80_err is not None:
                blockers.append(v80_err)
            else:
                assert v80_dev is not None
                if platform and v80_dev.get("vbnv") and platform.strip() != v80_dev["vbnv"]:
                    blockers.append(
                        f"platform mismatch: requested {platform.strip()!r}, device expects {v80_dev['vbnv']!r}"
                    )
                if _is_ready_false(v80_dev.get("is_ready")):
                    blockers.append(f"physical device {norm_bdf} reports not ready in v80-smi list")
                device_identity = v80_dev
    elif requested_evidence == "fpga_measured" and not probe_device:
        blockers.append(
            "physical device probe was skipped (--no-probe); cannot assert `fpga_measured` "
            "without observed physical device identity"
        )

    eligible_for_fpga_measured = (
        not blockers
        and norm_target == "hw"
        and device_identity is not None
        and xclbin_sha256 is not None
    )

    return {
        "schema_version": SCHEMA_VERSION,
        "mode": "preflight",
        "outcome": "pass" if not blockers else "blocked",
        "board": board_key,
        "driver": driver,
        "requested_evidence_level": requested_evidence,
        "eligible_for_fpga_measured": eligible_for_fpga_measured,
        "target": norm_target or None,
        "bdf": norm_bdf,
        "platform": platform.strip() if isinstance(platform, str) and platform.strip() else None,
        "xilinx_xrt": (xrt_root or None) if board_key == "u55c" else None,
        "fpga_bin_dir": fpga_bin_dir or None,
        "vrt_device_bdf": (vrt_device_bdf or None) if board_key == "v80" else None,
        "xbutil_path": xbutil_path,
        "v80_smi_path": v80_smi_path,
        "v80_preflight_script": v80_preflight_script,
        "xclbin": {
            "path": str(xclbin) if xclbin is not None else None,
            "sha256": xclbin_sha256,
            "size_bytes": xclbin_size,
        },
        "device_identity": device_identity,
        "blockers": blockers,
        "warnings": warnings,
    }


def build_execution_plan(
    *,
    board: str,
    bdf: str,
    platform: str | None,
    build_dir: str,
    fpga_bin_dir: str,
    soak_seconds: int = int(MIN_SOAK_SECONDS),
) -> dict[str, Any]:
    """Emit deterministic P07-A02 + P07-A03 physical FPGA execution plan JSON."""
    board_key = board.strip().lower()
    if board_key not in SUPPORTED_BOARDS:
        raise ValueError(f"unsupported board {board!r}; expected one of {sorted(SUPPORTED_BOARDS)}")
    spec = SUPPORTED_BOARDS[board_key]

    norm_bdf = _normalize_bdf(bdf)
    if norm_bdf is None:
        raise ValueError(f"invalid PCIe BDF {bdf!r}; expected format DDDD:BB:DD.F")

    resolved_platform = (platform or spec["default_platform"]).strip()
    if not PLATFORM_PATTERN.fullmatch(resolved_platform):
        raise ValueError(f"invalid platform name: {resolved_platform!r}")
    for token in NON_PHYSICAL_TARGETS:
        if token in resolved_platform.lower():
            raise ValueError(f"platform {resolved_platform!r} contains non-physical token {token!r}")

    if soak_seconds < int(MIN_SOAK_SECONDS):
        raise ValueError(f"soak_seconds must be >= {int(MIN_SOAK_SECONDS)} for P07-A03")

    if not build_dir.strip() or not fpga_bin_dir.strip():
        raise ValueError("build_dir and fpga_bin_dir must be nonempty")

    driver = spec["driver"]
    target = "hw"
    if board_key == "u55c":
        env_prefix: dict[str, Any] = {
            "FPGA_BIN_DIR": fpga_bin_dir,
            "XILINX_XRT": "/opt/xilinx/xrt",
            "XRT_DEVICE_INDEX": "0",
            "XRT_TARGET_BDF": norm_bdf,
            "XCL_EMULATION_MODE_MUST_BE_UNSET": True,
        }
        base_step_env = {"FPGA_BIN_DIR": fpga_bin_dir}
        examine_step = {
            "id": "host-device-examine",
            "category": "enumeration",
            "gate": "P07-A01",
            "cwd": build_dir,
            "env": {},
            "argv": ["xbutil", "examine", "-d", norm_bdf, "--format", "json"],
            "target": target,
            "driver": driver,
            "notes": "Verify U55C physical device enumeration, shell VBNV, and sensor readiness via xbutil.",
        }
        telemetry_cmd = ["xbutil", "examine", "-d", norm_bdf, "--format", "json"]
        soak_telemetry_note = "xbutil examine"
    else:
        env_prefix = {
            "VRT_DEVICE_BDF": norm_bdf,
            "VRT_VBIN_PATH": f"{fpga_bin_dir.rstrip('/')}/vortex_afu.vbin",
            "FPGA_BIN_DIR": fpga_bin_dir,
            "XCL_EMULATION_MODE_MUST_BE_UNSET": True,
        }
        base_step_env = {
            "FPGA_BIN_DIR": fpga_bin_dir,
            "VRT_DEVICE_BDF": norm_bdf,
        }
        examine_step = {
            "id": "host-device-examine",
            "category": "enumeration",
            "gate": "P07-A01",
            "cwd": build_dir,
            "env": {"VRT_DEVICE_BDF": norm_bdf},
            "argv": ["bash", "-c", "v80-smi list && ./ci/v80_preflight.sh"],
            "target": target,
            "driver": driver,
            "notes": "Verify V80 PF0/PF1/PF2, vrtd health, and cooldown readiness via v80-smi and ci/v80_preflight.sh.",
        }
        telemetry_cmd = ["v80-smi", "list"]
        soak_telemetry_note = "v80-smi list"

    def bb_step(
        step_id: str,
        category: str,
        gate: str,
        app: str,
        args: str = "",
        configs: str = "",
        profile: str = "",
        notes: str = "",
    ) -> dict[str, Any]:
        argv = ["./ci/blackbox.sh", f"--driver={driver}", f"--target={target}"]
        if profile:
            argv.append(f"--profile={profile}")
        argv.append(f"--app={app}")
        if args:
            argv.append(f"--args={args}")
        step_env = dict(base_step_env)
        if configs:
            step_env["CONFIGS"] = configs
        return {
            "id": step_id,
            "category": category,
            "gate": gate,
            "cwd": build_dir,
            "env": step_env,
            "argv": argv,
            "target": target,
            "driver": driver,
            "notes": notes,
        }

    steps: list[dict[str, Any]] = [
        examine_step,
        bb_step(
            "smoke-demo",
            "enumeration",
            "P07-A02",
            "demo",
            args="-n16",
            notes="Basic host-device open, buffer transfer, kernel launch, and cleanup on physical hw.",
        ),
        bb_step(
            "device-reopen-reset",
            "enumeration",
            "P07-A02",
            "reopen",
            args="-n1 -i4",
            notes="Repeated open/launch/close cycle verifying clean reset and handle release.",
        ),
        bb_step(
            "dma-roundtrip-vecadd",
            "dma",
            "P07-A02",
            "vecadd",
            args="-n4096",
            notes="Host-to-device and device-to-host DMA round-trip and exact reference check.",
        ),
        bb_step(
            "dma-io-addr",
            "dma",
            "P07-A02",
            "io_addr",
            notes="DMA addressing, alignment, and indirect pointer transfer check.",
        ),
        bb_step(
            "hbm-bank-boundary-mstress",
            "hbm_bank_boundary",
            "P07-A02",
            "mstress",
            args="-n4096",
            notes=(
                f"Exercises {spec['memory_banks']} {spec['memory_type']} banks "
                f"(total {spec['total_memory_bytes'] // (1024 ** 3)} GiB) and allocation/free boundaries."
            ),
        ),
        bb_step(
            "memory-coherence-fence",
            "hbm_bank_boundary",
            "P07-A02",
            "fence",
            notes="Compute/DMA visibility and memory fence ordering check.",
        ),
        bb_step(
            "gemm-fp16-tfr",
            "gemm_fp16",
            "P07-A02",
            "sgemm_tcu",
            args="-n64",
            configs="-DVX_CFG_EXT_TCU_ENABLE -DVX_CFG_TCU_TYPE_TFR -DITYPE=fp16 -DOTYPE=fp32",
            notes="Native TFR FP16-to-FP32 matrix multiply against frozen CPU reference.",
        ),
        bb_step(
            "gemm-bf16-tfr",
            "gemm_bf16",
            "P07-A02",
            "sgemm_tcu",
            args="-n64",
            configs="-DVX_CFG_EXT_TCU_ENABLE -DVX_CFG_TCU_TYPE_TFR -DITYPE=bf16 -DOTYPE=fp32",
            notes="Native TFR BF16-to-FP32 matrix multiply against frozen CPU reference.",
        ),
        bb_step(
            "attention-native",
            "attention",
            "P07-A02",
            "flash_attn_tcu_wg",
            args="-N 32 -D 16 -c 8 -t 8",
            configs="-DVX_CFG_EXT_TCU_ENABLE -DVX_CFG_TCU_TYPE_TFR -DVX_CFG_TCU_WGMMA_ENABLE -DITYPE=fp16 -DOTYPE=fp32",
            notes="Physical attention execution with explicit FP16-to-FP32 flags matching target bitstream against frozen CPU reference.",
        ),
        bb_step(
            "tiny-mlp-p04-fp16",
            "tiny_mlp",
            "P07-A02",
            "ai_mlp_fused",
            args="-c fp16-seeded_dense -n 1",
            configs="-DITYPE=fp16 -DOTYPE=fp32 -DKUNROLL=1",
            profile="p02-tfr",
            notes=(
                "P04 tiny-MLP FP16 physical execution via ai_mlp_fused (standard vortex2.h, compatible with XRT/AVED); "
                "note that ai_mlp v1 currently restricts --backend to simx|rtlsim."
            ),
        ),
        bb_step(
            "tiny-mlp-p04-bf16",
            "tiny_mlp",
            "P07-A02",
            "ai_mlp_fused",
            args="-c bf16-seeded_dense -n 1",
            configs="-DITYPE=bf16 -DOTYPE=fp32 -DKUNROLL=1",
            profile="p02-tfr",
            notes=(
                "P04 tiny-MLP BF16 physical execution via ai_mlp_fused (standard vortex2.h, compatible with XRT/AVED); "
                "note that ai_mlp v1 currently restricts --backend to simx|rtlsim."
            ),
        ),
        {
            "id": "physical-soak-3600s",
            "category": "soak",
            "gate": "P07-A03",
            "cwd": build_dir,
            "duration_seconds": soak_seconds,
            "telemetry_poll_interval_seconds": 10,
            "env": {
                **base_step_env,
                "P07_SOAK_DURATION_S": str(soak_seconds),
                "P07_SOAK_BDF": norm_bdf,
            },
            "argv": [
                "./ci/blackbox.sh",
                f"--driver={driver}",
                f"--target={target}",
                "--app=sgemm_tcu",
                "--args=-n64",
            ],
            "telemetry_cmd": telemetry_cmd,
            "target": target,
            "driver": driver,
            "notes": (
                f"Run continuous workload loop for >= {soak_seconds}s with periodic {soak_telemetry_note} "
                "telemetry logging into JSONL for `soak-analyze`."
            ),
        },
    ]

    return {
        "schema_version": SCHEMA_VERSION,
        "mode": "plan",
        "outcome": "planned",
        "execution_performed": False,
        "evidence_level": "source_present",
        "board": spec,
        "bdf": norm_bdf,
        "platform": resolved_platform,
        "driver": driver,
        "target": target,
        "build_dir": build_dir,
        "fpga_bin_dir": fpga_bin_dir,
        "environment_contract": env_prefix,
        "soak_duration_seconds": soak_seconds,
        "steps": steps,
    }


def _parse_timestamp(raw: Any) -> float | None:
    if _is_finite_number(raw):
        return float(raw)
    if isinstance(raw, str) and raw.strip():
        text = raw.strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            return datetime.fromisoformat(text).timestamp()
        except ValueError:
            return None
    return None


def analyze_soak_jsonl(
    lines: list[str],
    *,
    expected_bdf: str | None = None,
    min_duration_seconds: float = MIN_SOAK_SECONDS,
    max_temp_c: float = DEFAULT_MAX_TEMP_C,
    max_power_w: float = DEFAULT_MAX_POWER_W,
) -> dict[str, Any]:
    """Strictly analyze timestamped P07-A03 soak iteration and telemetry JSONL."""
    failures: list[str] = []
    warnings: list[str] = []

    norm_expected_bdf = _normalize_bdf(expected_bdf) if expected_bdf is not None else None
    if expected_bdf is not None and norm_expected_bdf is None:
        failures.append(f"expected BDF is malformed: {expected_bdf!r}")

    timestamps: list[float] = []
    observed_bdfs: set[str] = set()
    observed_targets: set[str] = set()
    observed_drivers: set[str] = set()
    temps_c: list[float] = []
    powers_w: list[float] = []
    throughputs: list[float] = []

    iteration_records = 0
    telemetry_records = 0
    passed_iterations = 0
    failed_iterations = 0
    total_numerical_mismatches = 0
    total_dma_errors = 0
    total_reset_errors = 0
    total_ecc_errors = 0

    for line_no, raw_line in enumerate(lines, start=1):
        stripped = raw_line.strip()
        if not stripped:
            continue
        try:
            rec = json.loads(stripped)
        except ValueError as exc:
            failures.append(f"line {line_no}: malformed JSON ({exc})")
            continue
        if not isinstance(rec, dict):
            failures.append(f"line {line_no}: JSONL entry must be an object")
            continue

        ts = _parse_timestamp(rec.get("timestamp"))
        if ts is None:
            failures.append(f"line {line_no}: missing or invalid timestamp")
        else:
            if timestamps and ts < timestamps[-1]:
                failures.append(f"line {line_no}: timestamp regressed ({ts} < {timestamps[-1]})")
            timestamps.append(ts)

        target = rec.get("target")
        if target is not None:
            if not isinstance(target, str) or not target.strip():
                failures.append(f"line {line_no}: target must be a nonempty string")
            else:
                target_str = target.strip().lower()
                observed_targets.add(target_str)
                if target_str != "hw":
                    failures.append(
                        f"line {line_no}: non-physical target {target!r} is disallowed for P07-A03"
                    )

        driver = rec.get("driver")
        if driver is not None:
            if not isinstance(driver, str) or not driver.strip():
                failures.append(f"line {line_no}: driver must be a nonempty string")
            else:
                driver_str = driver.strip().lower()
                observed_drivers.add(driver_str)
                if driver_str not in PHYSICAL_DRIVERS:
                    failures.append(
                        f"line {line_no}: non-physical driver {driver!r} is disallowed for P07-A03 "
                        f"(expected one of {sorted(PHYSICAL_DRIVERS)})"
                    )

        rec_bdf = rec.get("bdf")
        if rec_bdf is not None:
            norm_rec_bdf = _normalize_bdf(str(rec_bdf))
            if norm_rec_bdf is None:
                failures.append(f"line {line_no}: malformed device BDF {rec_bdf!r}")
            else:
                observed_bdfs.add(norm_rec_bdf)
                if norm_expected_bdf is not None and norm_rec_bdf != norm_expected_bdf:
                    failures.append(
                        f"line {line_no}: BDF mismatch ({norm_rec_bdf} != {norm_expected_bdf})"
                    )

        kind = rec.get("kind", "iteration")
        if kind == "iteration":
            iteration_records += 1
            if "target" not in rec or rec.get("target") is None:
                failures.append(f"line {line_no}: iteration record missing `target` field")
            if "driver" not in rec or rec.get("driver") is None:
                failures.append(f"line {line_no}: iteration record missing `driver` field")
            status = rec.get("status")
            if status == "pass":
                passed_iterations += 1
            elif status == "fail":
                failed_iterations += 1
                failures.append(
                    f"line {line_no}: iteration failed (app={rec.get('app')!r}, "
                    f"reason={rec.get('error', 'unspecified')!r})"
                )
            else:
                failures.append(f"line {line_no}: invalid iteration status {status!r}")

            mismatches = rec.get("numerical_mismatches", 0)
            if not _is_nonneg_int(mismatches):
                failures.append(f"line {line_no}: numerical_mismatches must be a non-negative integer")
            else:
                total_numerical_mismatches += mismatches
                if mismatches > 0:
                    failures.append(f"line {line_no}: {mismatches} numerical mismatch(es) recorded")

            dma_errs = rec.get("dma_errors", 0)
            if not _is_nonneg_int(dma_errs):
                failures.append(f"line {line_no}: dma_errors must be a non-negative integer")
            else:
                total_dma_errors += dma_errs
                if dma_errs > 0:
                    failures.append(f"line {line_no}: {dma_errs} DMA error(s) recorded")

            reset_errs = rec.get("reset_errors", 0)
            if not _is_nonneg_int(reset_errs):
                failures.append(f"line {line_no}: reset_errors must be a non-negative integer")
            else:
                total_reset_errors += reset_errs
                if reset_errs > 0:
                    failures.append(f"line {line_no}: {reset_errs} reset error(s) recorded")

            if "throughput_gflops" in rec and rec["throughput_gflops"] is not None:
                tp = rec["throughput_gflops"]
                if not _is_finite_number(tp) or tp < 0:
                    failures.append(f"line {line_no}: invalid throughput_gflops {tp!r}")
                else:
                    throughputs.append(float(tp))

        elif kind == "telemetry":
            telemetry_records += 1
        else:
            failures.append(f"line {line_no}: unsupported record kind {kind!r}")

        if "temp_c" in rec:
            temp = rec["temp_c"]
            if temp is not None:
                if not _is_finite_number(temp) or temp < -40.0 or temp > 150.0:
                    failures.append(f"line {line_no}: invalid temp_c reading {temp!r}")
                else:
                    temps_c.append(float(temp))
                    if float(temp) > max_temp_c:
                        failures.append(
                            f"line {line_no}: temperature {temp} C exceeds threshold {max_temp_c} C"
                        )

        if "power_w" in rec:
            power = rec["power_w"]
            if power is not None:
                if not _is_finite_number(power) or power < 0.0:
                    failures.append(f"line {line_no}: invalid power_w reading {power!r}")
                else:
                    powers_w.append(float(power))
                    if float(power) > max_power_w:
                        failures.append(
                            f"line {line_no}: power {power} W exceeds threshold {max_power_w} W"
                        )

        if "ecc_errors" in rec and rec["ecc_errors"] is not None:
            ecc = rec["ecc_errors"]
            if not _is_nonneg_int(ecc):
                failures.append(f"line {line_no}: ecc_errors must be a non-negative integer")
            else:
                total_ecc_errors += ecc
                if ecc > 0:
                    failures.append(f"line {line_no}: {ecc} ECC/memory error(s) recorded")

    if iteration_records == 0:
        failures.append("soak log contains zero workload iteration records")
    if telemetry_records == 0:
        warnings.append("no dedicated telemetry poll records present")
    if not temps_c:
        warnings.append("temperature telemetry unavailable across run")
    if not powers_w:
        warnings.append("power telemetry unavailable across run")
    if not observed_bdfs:
        failures.append("soak log does not identify any physical device BDF")
    elif len(observed_bdfs) > 1:
        failures.append(f"soak log spans multiple BDFs unexpectedly: {sorted(observed_bdfs)}")
    if not observed_drivers:
        failures.append("soak log does not identify any physical driver")

    duration_seconds = (timestamps[-1] - timestamps[0]) if len(timestamps) >= 2 else 0.0
    if duration_seconds < min_duration_seconds:
        failures.append(
            f"soak duration {duration_seconds:.1f}s is below required minimum {min_duration_seconds:.1f}s"
        )

    verdict = "pass" if not failures else "fail"
    return {
        "schema_version": SCHEMA_VERSION,
        "mode": "soak-analyze",
        "verdict": verdict,
        "evidence_level": "fpga_measured" if verdict == "pass" else "unqualified",
        "duration_seconds": round(duration_seconds, 3),
        "min_required_seconds": min_duration_seconds,
        "observed_bdfs": sorted(observed_bdfs),
        "observed_targets": sorted(observed_targets),
        "observed_drivers": sorted(observed_drivers),
        "counts": {
            "iterations_total": iteration_records,
            "iterations_passed": passed_iterations,
            "iterations_failed": failed_iterations,
            "telemetry_samples": telemetry_records,
            "numerical_mismatches": total_numerical_mismatches,
            "dma_errors": total_dma_errors,
            "reset_errors": total_reset_errors,
            "ecc_errors": total_ecc_errors,
        },
        "telemetry": {
            "temp_c_min": min(temps_c) if temps_c else None,
            "temp_c_max": max(temps_c) if temps_c else None,
            "temp_c_status": "measured" if temps_c else "unavailable",
            "power_w_avg": round(sum(powers_w) / len(powers_w), 3) if powers_w else None,
            "power_w_max": max(powers_w) if powers_w else None,
            "power_w_status": "measured" if powers_w else "unavailable",
            "throughput_gflops_avg": (
                round(sum(throughputs) / len(throughputs), 3) if throughputs else None
            ),
        },
        "failures": failures,
        "warnings": warnings,
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="p07_fpga_harness.py",
        description="P07 Physical FPGA preflight, execution planner, and soak analyzer.",
    )
    sub = parser.add_subparsers(dest="subcommand", required=True)

    p_pre = sub.add_parser("preflight", help="Validate physical FPGA prerequisites.")
    p_pre.add_argument("--board", default="u55c", choices=sorted(SUPPORTED_BOARDS))
    p_pre.add_argument("--target", required=True, help="Execution target (must be `hw`).")
    p_pre.add_argument(
        "--requested-evidence",
        default="fpga_measured",
        choices=("fpga_measured", "source_present"),
        help="Evidence level being qualified.",
    )
    p_pre.add_argument("--bdf", help="Physical PCIe BDF (e.g. 0000:3d:00.1).")
    p_pre.add_argument("--platform", help="Expected XRT platform VBNV or V80 part string.")
    p_pre.add_argument("--xclbin", type=Path, help="Path to TARGET=hw bitstream (.xclbin or .vbin).")
    p_pre.add_argument("--xclbin-sha256", help="Expected 64-hex SHA-256 of bitstream.")
    p_pre.add_argument(
        "--no-probe",
        action="store_true",
        help="Skip invoking xbutil/v80-smi probe (prevents fpga_measured eligibility).",
    )

    p_plan = sub.add_parser("plan", help="Emit deterministic P07-A02/A03 execution plan JSON.")
    p_plan.add_argument("--board", default="u55c", choices=sorted(SUPPORTED_BOARDS))
    p_plan.add_argument("--bdf", required=True, help="Physical PCIe BDF (e.g. 0000:3d:00.1).")
    p_plan.add_argument("--platform", help="Override default platform VBNV.")
    p_plan.add_argument("--build-dir", required=True, help="Configured RV64 build directory.")
    p_plan.add_argument("--fpga-bin-dir", required=True, help="Directory holding TARGET=hw bitstream.")
    p_plan.add_argument(
        "--soak-seconds",
        type=int,
        default=int(MIN_SOAK_SECONDS),
        help="Soak duration in seconds (must be >= 3600).",
    )

    p_soak = sub.add_parser("soak-analyze", help="Analyze timestamped P07-A03 soak telemetry JSONL.")
    p_soak.add_argument("--input", type=Path, required=True, help="Path to soak JSONL log.")
    p_soak.add_argument("--bdf", help="Expected physical PCIe BDF.")
    p_soak.add_argument("--min-duration-seconds", type=float, default=MIN_SOAK_SECONDS)
    p_soak.add_argument("--max-temp-c", type=float, default=DEFAULT_MAX_TEMP_C)
    p_soak.add_argument("--max-power-w", type=float, default=DEFAULT_MAX_POWER_W)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.subcommand == "preflight":
        report = run_preflight(
            board=args.board,
            target=args.target,
            requested_evidence=args.requested_evidence,
            bdf=args.bdf,
            platform=args.platform,
            xclbin=args.xclbin,
            expected_sha256=args.xclbin_sha256,
            probe_device=not args.no_probe,
        )
        print(json.dumps(report, indent=2, sort_keys=True, allow_nan=False))
        return 0 if report["outcome"] == "pass" else 1

    if args.subcommand == "plan":
        try:
            plan = build_execution_plan(
                board=args.board,
                bdf=args.bdf,
                platform=args.platform,
                build_dir=args.build_dir,
                fpga_bin_dir=args.fpga_bin_dir,
                soak_seconds=args.soak_seconds,
            )
        except ValueError as exc:
            error_obj = {
                "schema_version": SCHEMA_VERSION,
                "mode": "plan",
                "outcome": "blocked",
                "error": str(exc),
            }
            print(json.dumps(error_obj, indent=2, sort_keys=True, allow_nan=False))
            return 1
        print(json.dumps(plan, indent=2, sort_keys=True, allow_nan=False))
        return 0

    if args.subcommand == "soak-analyze":
        try:
            raw_lines = args.input.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeError) as exc:
            error_obj = {
                "schema_version": SCHEMA_VERSION,
                "mode": "soak-analyze",
                "verdict": "fail",
                "failures": [f"cannot read soak log ({type(exc).__name__}): {args.input}"],
            }
            print(json.dumps(error_obj, indent=2, sort_keys=True, allow_nan=False))
            return 1
        report = analyze_soak_jsonl(
            raw_lines,
            expected_bdf=args.bdf,
            min_duration_seconds=args.min_duration_seconds,
            max_temp_c=args.max_temp_c,
            max_power_w=args.max_power_w,
        )
        print(json.dumps(report, indent=2, sort_keys=True, allow_nan=False))
        return 0 if report["verdict"] == "pass" else 1

    return 2


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""
Open-Source RTL-to-GDSII Physical Design Flow Driver.

Runs Yosys synthesis + OpenSTA static timing/power analysis across ASAP7
(7nm RVT NLDM) and Nangate45 (45nm typical) on:
  - VX_asic_dft_top    (IEEE-1149.1 JTAG/DFT/MBIST controller)
  - VX_asic_soc_top    (Dual-clock CDC-clean AXI4 SoC shell + SRAM macro / behav)
  - VX_tcu_fedp_tfr    (TFR FP16/BF16 Tensor-Core FEDP datapath macro)
  - VX_tcu_tfr_mul_f16 (TFR FP16/BF16/TF32 Booth-Wallace product-stage macro)

Additionally runs OpenROAD Place-and-Route (floorplan, tapcell/PDN, IO pin
placement, global/detailed placement, CTS, setup/hold repair, GRT, DRT, OpenRCX
SPEF parasitic extraction, post-route STA) and KLayout GDSII streamout via
`openroad/orfs:latest` into the specified output directory (default
`/home/antigravity/vortex_builds/phys_out/` outside git), recording exact
SHA-256 digests, areas, instance counts, wirelengths, DRC counts, and post-route
WNS/TNS/Fmax/power into `hw/asic/phys/phys_results.json`.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


REPO_ROOT = Path(__file__).resolve().parents[3]
PHYS_DIR = Path(__file__).resolve().parent
DEFAULT_OUT_ROOT = Path("/home/antigravity/vortex_builds/phys_out")

DEFAULT_YOSYS_BIN = Path("/home/antigravity/tools/yosys/bin/yosys")
DEFAULT_OPENSTA_BIN = Path("/home/antigravity/tools/sta/bin/sta")
DEFAULT_ASAP7_HOST_LIB = Path(
    "/home/antigravity/vortex_builds/build32_asic_gate/hw/syn/libs/asap7/lib/asap7_rvt_tt.lib"
)
NANGATE45_HOST_LIB = REPO_ROOT / "hw/syn/libs/NangateOpenCellLibrary_typical.lib"
AIGPU_SDC = REPO_ROOT / "hw/asic/constraints/aigpu_b1.sdc"

ORFS_IMAGE = "openroad/orfs:latest"
ORFS_FLOW = "/OpenROAD-flow-scripts/flow"

ORFS_ASAP7_TT_GROUPS: Tuple[Tuple[str, str], ...] = (
    ("INVBUF", "lib/NLDM/asap7sc7p5t_INVBUF_RVT_TT_nldm_220122.lib.gz"),
    ("SIMPLE", "lib/NLDM/asap7sc7p5t_SIMPLE_RVT_TT_nldm_211120.lib.gz"),
    ("AO", "lib/NLDM/asap7sc7p5t_AO_RVT_TT_nldm_211120.lib.gz"),
    ("OA", "lib/NLDM/asap7sc7p5t_OA_RVT_TT_nldm_211120.lib.gz"),
    ("SEQ", "lib/NLDM/asap7sc7p5t_SEQ_RVT_TT_nldm_220123.lib"),
)

TFR_SRC_FILES = [
    "hw/rtl/VX_gpu_pkg.sv",
    "hw/rtl/tcu/VX_tcu_pkg.sv",
    "hw/rtl/tcu/tfr/VX_tcu_fedp_tfr.sv",
    "hw/rtl/tcu/tfr/VX_tcu_tfr_mul_f16.sv",
    "hw/rtl/tcu/tfr/VX_tcu_tfr_mul_f8.sv",
    "hw/rtl/tcu/tfr/VX_tcu_tfr_mul_f4.sv",
    "hw/rtl/tcu/tfr/VX_tcu_tfr_mul_i8.sv",
    "hw/rtl/tcu/tfr/VX_tcu_tfr_mul_i4.sv",
    "hw/rtl/tcu/tfr/VX_tcu_tfr_shared_mul.sv",
    "hw/rtl/tcu/tfr/VX_tcu_tfr_mul_join.sv",
    "hw/rtl/tcu/tfr/VX_tcu_tfr_align.sv",
    "hw/rtl/tcu/tfr/VX_tcu_tfr_acc.sv",
    "hw/rtl/tcu/tfr/VX_tcu_tfr_norm_round.sv",
    "hw/rtl/tcu/tfr/VX_tcu_tfr_wmul.sv",
    "hw/rtl/tcu/tfr/VX_tcu_tfr_classifier.sv",
    "hw/rtl/tcu/tfr/VX_tcu_tfr_pipe_register.sv",
    "hw/rtl/tcu/tfr/VX_tcu_tfr_exc_reduce.sv",
    "hw/rtl/tcu/tfr/VX_tcu_tfr_lane_mask.sv",
    "hw/rtl/tcu/tfr/VX_tcu_tfr_max_exp.sv",
    "hw/rtl/libs/VX_pipe_register.sv",
    "hw/rtl/libs/VX_wallace_mul.sv",
    "hw/rtl/libs/VX_ks_adder.sv",
    "hw/rtl/libs/VX_lzc.sv",
    "hw/rtl/libs/VX_onehot_mux.sv",
    "hw/rtl/libs/VX_popcount.sv",
    "hw/rtl/libs/VX_csa_tree.sv",
    "hw/rtl/libs/VX_csa_32.sv",
    "hw/rtl/libs/VX_csa_42.sv",
    "hw/rtl/libs/VX_find_first.sv",
    "hw/rtl/libs/VX_priority_encoder.sv",
    "hw/rtl/libs/VX_reduce_tree.sv",
    "hw/rtl/libs/VX_mux.sv",
]

FAKERAM7_256X32_WRAPPER_SV = """\
(* blackbox, keep_hierarchy = "yes" *)
module fakeram7_256x32 (
    output wire [31:0] rd_out,
    input  wire [7:0]  addr_in,
    input  wire        we_in,
    input  wire [31:0] wd_in,
    input  wire        clk,
    input  wire        ce_in
);
endmodule

module VX_sram_1rw_macro #(
    parameter int DEPTH  = 256,
    parameter int DATAW  = 32,
    parameter int WRENW  = 4,
    parameter int BYTE_W = 8,
    parameter int ADDRW  = 8
) (
    input  wire                 CLK,
    input  wire                 CEB,
    input  wire                 WEB,
    input  wire [DATAW-1:0]     BWEB,
    input  wire [ADDRW-1:0]     A,
    input  wire [DATAW-1:0]     D,
    output wire [DATAW-1:0]     Q,
    input  wire                 SLP,
    input  wire                 SD,
    input  wire                 RET
);
    wire unused_ctl = SLP ^ SD ^ RET ^ (^BWEB);
    fakeram7_256x32 u_fakeram (
        .rd_out  (Q),
        .addr_in (A),
        .we_in   (~WEB),
        .wd_in   (D),
        .clk     (CLK),
        .ce_in   (~CEB)
    );
endmodule
"""


def run_cmd(
    cmd: List[str],
    *,
    cwd: Path = REPO_ROOT,
    env: Optional[Dict[str, str]] = None,
    log_path: Optional[Path] = None,
    timeout: Optional[int] = None,
) -> Tuple[int, str, float]:
    full_env = os.environ.copy()
    if env:
        full_env.update(env)
    t0 = time.monotonic()
    if log_path is not None:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("w", encoding="utf-8") as lf:
            proc = subprocess.run(
                cmd,
                cwd=str(cwd),
                env=full_env,
                stdout=lf,
                stderr=subprocess.STDOUT,
                text=True,
                timeout=timeout,
            )
        elapsed = time.monotonic() - t0
        out = log_path.read_text(encoding="utf-8", errors="replace")
        return proc.returncode, out, elapsed
    proc = subprocess.run(
        cmd,
        cwd=str(cwd),
        env=full_env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        timeout=timeout,
    )
    elapsed = time.monotonic() - t0
    return proc.returncode, proc.stdout, elapsed


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            chunk = f.read(1024 * 1024)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def resolve_binary(cli_val: Optional[Path], env_name: str, default_path: Path, cmd_name: str) -> Path:
    candidates: List[Path] = []
    if cli_val is not None:
        candidates.append(cli_val.expanduser())
    env_val = os.environ.get(env_name, "").strip()
    if env_val:
        candidates.append(Path(env_val).expanduser())
    candidates.append(default_path)
    which_hit = shutil.which(cmd_name)
    if which_hit:
        candidates.append(Path(which_hit))
    for cand in candidates:
        if cand.is_file():
            return cand.resolve()
    searched = ", ".join(str(c) for c in candidates)
    raise FileNotFoundError(f"Could not locate '{cmd_name}' binary (searched: {searched})")


def _extract_liberty_body(text: str, source_name: str) -> str:
    match = re.search(r"\blibrary\s*\([^)]*\)\s*\{", text)
    if not match:
        raise ValueError(f"{source_name}: library declaration not found")
    start = match.end() - 1
    depth = 0
    in_string = False
    escaped = False
    line_comment = False
    block_comment = False
    end = None
    index = start
    n = len(text)
    while index < n:
        ch = text[index]
        nxt = text[index + 1] if index + 1 < n else ""
        if line_comment:
            line_comment = ch != "\n"
        elif block_comment:
            if ch == "*" and nxt == "/":
                block_comment = False
                index += 1
        elif in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
        elif ch == "/" and nxt == "/":
            line_comment = True
            index += 1
        elif ch == "/" and nxt == "*":
            block_comment = True
            index += 1
        elif ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                end = index
                break
        index += 1
    if end is None:
        raise ValueError(f"{source_name}: unbalanced library braces")
    return text[start + 1 : end].strip()


def resolve_asap7_host_lib(cli_val: Optional[Path], out_root: Path) -> Path:
    candidates: List[Path] = []
    if cli_val is not None:
        candidates.append(cli_val.expanduser())
    env_val = os.environ.get("ASAP7_HOST_LIB", "").strip()
    if env_val:
        candidates.append(Path(env_val).expanduser())
    candidates.append(DEFAULT_ASAP7_HOST_LIB)
    for base in (REPO_ROOT, REPO_ROOT.parent, Path("/home/antigravity/vortex_builds")):
        if base.is_dir():
            for hit in sorted(base.glob("build*/hw/syn/libs/asap7/lib/asap7_rvt_tt.lib")):
                candidates.append(hit)
    for cand in candidates:
        if cand.is_file():
            return cand.resolve()

    # Fallback: extract and merge the ORFS ASAP7 RVT TT split libraries from docker
    cached = out_root / "libs/asap7_rvt_tt.lib"
    if cached.is_file():
        return cached.resolve()

    print(f"[INFO] ASAP7_HOST_LIB not found on host; extracting ASAP7 RVT TT Liberty from {ORFS_IMAGE}...")
    cached.parent.mkdir(parents=True, exist_ok=True)
    bodies: List[str] = []
    for group, rel_path in ORFS_ASAP7_TT_GROUPS:
        container_path = f"{ORFS_FLOW}/platforms/asap7/{rel_path}"
        raw_dest = out_root / "libs" / Path(rel_path).name
        extract_orfs_file_bytes(container_path, raw_dest)
        if raw_dest.suffix == ".gz":
            with gzip.open(raw_dest, "rt", encoding="utf-8") as gf:
                txt = gf.read()
        else:
            txt = raw_dest.read_text(encoding="utf-8")
        bodies.append(f"/* {group} */\n{_extract_liberty_body(txt, str(raw_dest))}")
    cached.write_text("library (asap7_rvt_tt) {\n" + "\n".join(bodies) + "\n}\n", encoding="utf-8")
    return cached.resolve()


def ensure_generated_hw_cfg(gen_dir: Path) -> Path:
    """Generate VX_config.vh and VX_types.vh in gen_dir via ci/gen_config.py."""
    gen_dir.mkdir(parents=True, exist_ok=True)
    gen_script = REPO_ROOT / "ci/gen_config.py"
    cflags_str = " ".join([
        "-DVX_CFG_XLEN=64",
        "-DVX_CFG_XLEN_64",
        "-DVX_CFG_NUM_THREADS=4",
        "-DVX_CFG_NUM_WARPS=4",
        "-DVX_CFG_EXT_TCU_ENABLE",
        "-DVX_CFG_TCU_TYPE=TFR",
        "-DVX_CFG_TCU_TYPE_TFR",
        "-DVX_CFG_TCU_FP16_ENABLE",
    ])
    for cfg_name, out_name, use_cflags in [
        ("VX_config.toml", "VX_config.vh", True),
        ("VX_types.toml", "VX_types.vh", False),
    ]:
        out_path = gen_dir / out_name
        cmd = [
            sys.executable,
            str(gen_script),
            "--config",
            str(REPO_ROOT / cfg_name),
            "--output",
            str(out_path),
            "--format",
            "verilog",
            "--xlen",
            "64",
        ]
        if use_cflags:
            cmd.extend(["--cflags", cflags_str])
        else:
            cmd.append("--resolved")
        rc, out, _ = run_cmd(cmd, env={"XLEN": "64"})
        if rc != 0:
            raise RuntimeError(f"gen_config.py failed for {cfg_name}:\n{out}")
    return gen_dir


def extract_orfs_file_bytes(container_path: str, dest_path: Path) -> Path:
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(
        ["docker", "run", "--rm", ORFS_IMAGE, "cat", container_path],
        cwd=str(REPO_ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if proc.returncode != 0:
        err = proc.stderr.decode("utf-8", errors="replace")
        raise RuntimeError(f"Failed to extract {container_path} from {ORFS_IMAGE}: {err}")
    dest_path.write_bytes(proc.stdout)
    return dest_path


def extract_orfs_file(container_path: str, dest_path: Path) -> Path:
    return extract_orfs_file_bytes(container_path, dest_path)


def parse_yosys_stat(log_text: str, module_name: str) -> Dict[str, Any]:
    lines = log_text.splitlines()
    target_hdr = f"=== {module_name} ==="
    start_idx = None
    for i, ln in enumerate(lines):
        if ln.strip() == target_hdr:
            start_idx = i
    if start_idx is None:
        raise ValueError(f"Could not find stat header '{target_hdr}' in Yosys log")

    total_cells = None
    total_area_um2 = None
    seq_area_um2 = None
    seq_pct = None
    ff_count = 0
    macro_cells: Dict[str, int] = {}
    cell_breakdown: Dict[str, Dict[str, Any]] = {}

    in_cells = False
    for ln in lines[start_idx + 1 :]:
        s = ln.strip()
        if s.startswith("Chip area for module"):
            m = re.search(r":\s*([0-9]+(?:\.[0-9]+)?)", s)
            if m:
                total_area_um2 = float(m.group(1))
            in_cells = False
            continue
        if s.startswith("of which used for sequential elements"):
            m = re.search(r":\s*([0-9]+(?:\.[0-9]+)?)\s*\(([0-9]+(?:\.[0-9]+)?)%\)", s)
            if m:
                seq_area_um2 = float(m.group(1))
                seq_pct = float(m.group(2))
            break
        m_total = re.match(r"^\s*(\d+)\s+([0-9.eE+-]+|-)\s+cells\s*$", ln)
        if m_total:
            total_cells = int(m_total.group(1))
            if total_area_um2 is None and m_total.group(2) != "-":
                total_area_um2 = float(m_total.group(2))
            in_cells = True
            continue
        if in_cells:
            m_cell = re.match(r"^\s*(\d+)\s+([0-9.eE+-]+|-)\s+(\S+)\s*$", ln)
            if m_cell:
                cnt = int(m_cell.group(1))
                area_s = m_cell.group(2)
                cname = m_cell.group(3)
                area_val = float(area_s) if area_s != "-" else None
                cell_breakdown[cname] = {"count": cnt, "area_um2": area_val}
                if "DFF" in cname or cname.startswith("SDFF") or "DLH" in cname:
                    ff_count += cnt
                if cname.startswith("fakeram"):
                    macro_cells[cname] = cnt

    return {
        "cell_count": total_cells,
        "flip_flop_count": ff_count,
        "standard_cell_area_um2": round(
            total_area_um2
            - sum(
                v["area_um2"]
                for k, v in cell_breakdown.items()
                if k in macro_cells and v["area_um2"] is not None
            ),
            6,
        )
        if total_area_um2 is not None
        else None,
        "total_chip_area_um2": total_area_um2,
        "sequential_area_um2": seq_area_um2,
        "sequential_area_pct": seq_pct,
        "macro_instances": macro_cells,
        "unique_cell_types": len(cell_breakdown),
    }


def parse_sta_or_openroad_timing(log_text: str) -> Dict[str, Any]:
    res: Dict[str, Any] = {}
    wns_m = re.findall(r"^wns\s+max\s+([-0-9.eE+infINF]+)", log_text, re.M)
    tns_m = re.findall(r"^tns\s+max\s+([-0-9.eE+infINF]+)", log_text, re.M)
    max_s = re.findall(r"^worst slack max\s+([-0-9.eE+infINF]+)", log_text, re.M)
    min_s = re.findall(r"^worst slack min\s+([-0-9.eE+infINF]+)", log_text, re.M)

    if wns_m:
        res["wns_setup_ns"] = float(wns_m[-1])
    if tns_m:
        res["tns_setup_ns"] = float(tns_m[-1])
    if max_s:
        res["worst_setup_slack_ns"] = float(max_s[-1])
    if min_s:
        res["worst_hold_slack_ns"] = float(min_s[-1])

    clocks: Dict[str, Dict[str, Optional[float]]] = {}
    for m in re.finditer(
        r"^(\S+)\s+period_min\s*=\s*([0-9.infINF+-]+)\s+fmax\s*=\s*([0-9.infINF+-]+)",
        log_text,
        re.M,
    ):
        cname = m.group(1)
        p_str = m.group(2)
        f_str = m.group(3)
        p_val = None if "inf" in p_str.lower() else float(p_str)
        f_val = None if "inf" in f_str.lower() else float(f_str)
        clocks[cname] = {"period_min_ns": p_val, "fmax_mhz": f_val}
    res["clocks_min_period"] = clocks

    power_m = re.findall(
        r"^Total\s+([0-9.eE+-]+)\s+([0-9.eE+-]+)\s+([0-9.eE+-]+)\s+([0-9.eE+-]+)\s+100\.0%",
        log_text,
        re.M,
    )
    if power_m:
        i_w, s_w, l_w, t_w = [float(x) for x in power_m[-1]]
        res["power_mw"] = {
            "internal": round(i_w * 1e3, 6),
            "switching": round(s_w * 1e3, 6),
            "leakage": round(l_w * 1e3, 6),
            "total": round(t_w * 1e3, 6),
            "unit": "mW",
            "assumption": "default_input_activity_0.1_duty_0.5_typical_corner",
        }

    group_paths: Dict[str, Dict[str, Any]] = {}
    current_group = None
    lines = log_text.splitlines()
    for i, ln in enumerate(lines):
        mg = re.match(r"^---\s+(?:POST_ROUTE\s+)?CLOCK GROUP:\s+(\S+)\s+---", ln.strip())
        if mg:
            current_group = mg.group(1)
            continue
        if current_group and "Path Type: max" in ln:
            sp = ep = None
            arr = req = slk = None
            for b in range(max(0, i - 6), i):
                if lines[b].startswith("Startpoint:"):
                    sp = lines[b].split("Startpoint:", 1)[1].strip()
                elif lines[b].startswith("Endpoint:"):
                    ep = lines[b].split("Endpoint:", 1)[1].strip()
            for f_idx in range(i + 1, min(len(lines), i + 120)):
                fln = lines[f_idx]
                if "data arrival time" in fln and arr is None:
                    parts = fln.strip().split()
                    try:
                        arr = float(parts[0])
                    except ValueError:
                        pass
                if "data required time" in fln:
                    parts = fln.strip().split()
                    try:
                        req = float(parts[0])
                    except ValueError:
                        pass
                ms = re.match(r"^\s*([-0-9.]+)\s+slack\s+\((MET|VIOLATED)\)", fln)
                if ms:
                    slk = float(ms.group(1))
                    status = ms.group(2)
                    if current_group not in group_paths:
                        group_paths[current_group] = {
                            "startpoint": sp,
                            "endpoint": ep,
                            "data_arrival_ns": arr,
                            "data_required_ns": req,
                            "slack_ns": slk,
                            "status": status,
                        }
                    break
    if group_paths:
        res["critical_paths_by_clock"] = group_paths

    m_da = re.findall(r"^Design area\s+([0-9.]+)\s+um\^2\s+([0-9.]+)%\s+utilization\.", log_text, re.M)
    if m_da:
        res["design_area_um2"] = float(m_da[-1][0])
        res["utilization_pct"] = float(m_da[-1][1])

    return res


def parse_def_physical_stats(def_path: Path) -> Dict[str, Any]:
    """Extract instance counts, core area, and routed SPECIALNETS segments from DEF."""
    text = def_path.read_text(encoding="utf-8")
    stats: Dict[str, Any] = {}

    dbu = 1000.0
    m_dbu = re.search(r"UNITS\s+DISTANCE\s+MICRONS\s+(\d+)", text)
    if m_dbu:
        dbu = float(m_dbu.group(1))

    # Derive core bounding box from standard-cell ROW extents if present, else DIEAREA
    row_boxes: List[Tuple[float, float, float, float]] = []
    for rm in re.finditer(
        r"^ROW\s+\S+\s+\S+\s+(-?\d+)\s+(-?\d+)\s+\S+\s+DO\s+(\d+)\s+BY\s+(\d+)\s+STEP\s+(\d+)\s+(\d+)",
        text,
        re.M,
    ):
        ox, oy, nx, ny, sx, sy = [int(v) for v in rm.groups()]
        # ASAP7 / Nangate45 row step is site width; for single-row height use site height or spacing
        if nx > 0 and sx > 0:
            row_boxes.append((ox, oy, ox + nx * sx, oy))
    if row_boxes:
        min_x = min(r[0] for r in row_boxes)
        max_x = max(r[2] for r in row_boxes)
        ys = sorted({r[1] for r in row_boxes})
        row_h = (ys[1] - ys[0]) if len(ys) > 1 else 0
        min_y = ys[0]
        max_y = ys[-1] + row_h
        stats["core_area_um2"] = round(((max_x - min_x) / dbu) * ((max_y - min_y) / dbu), 2)

    m_comp = re.search(r"COMPONENTS\s+\d+\s*;(.*?)END\s+COMPONENTS", text, re.S)
    if m_comp:
        comp_block = m_comp.group(1)
        insts = re.findall(r"^\s*-\s+\S+\s+(\S+)", comp_block, re.M)
        tap_cnt = 0
        fill_cnt = 0
        std_macro_cnt = 0
        for master in insts:
            if master.startswith(("FILLER", "DECAP", "FILLCELL")):
                fill_cnt += 1
            elif master.startswith("TAPCELL"):
                tap_cnt += 1
            else:
                std_macro_cnt += 1
        stats["post_route_stdcell_plus_macro_instances"] = std_macro_cnt
        stats["post_route_tapcell_instances"] = tap_cnt
        stats["post_route_filler_decap_instances"] = fill_cnt

    m_snet = re.search(r"SPECIALNETS\s+\d+\s*;(.*?)END\s+SPECIALNETS", text, re.S)
    snet_block = m_snet.group(1) if m_snet else ""
    routed_nets = len(re.findall(r"\+\s+ROUTED\b", snet_block))
    new_segs = len(re.findall(r"\bNEW\b", snet_block))
    stats["pdn_specialnets_routed_nets"] = routed_nets
    stats["pdn_specialnets_routed_segments"] = routed_nets + new_segs
    return stats


def parse_pnr_metrics(log_text: str, drt_drc_path: Path, def_path: Path) -> Dict[str, Any]:
    out = parse_sta_or_openroad_timing(log_text)

    wl_matches = re.findall(r"^Total wire length\s*=\s*(\d+)\s*um\.", log_text, re.M)
    via_matches = re.findall(r"^Total number of vias\s*=\s*(\d+)\.", log_text, re.M)
    if wl_matches:
        out["total_wirelength_um"] = int(wl_matches[-1])
    if via_matches:
        out["total_vias"] = int(via_matches[-1])

    layer_wl: Dict[str, int] = {}
    last_wl_idx = log_text.rfind("Total wire length =")
    if last_wl_idx != -1:
        tail = log_text[last_wl_idx : last_wl_idx + 1200]
        for lm in re.finditer(r"Total wire length on LAYER (\S+)\s*=\s*(\d+)\s*um\.", tail):
            wl_val = int(lm.group(2))
            if wl_val > 0:
                layer_wl[lm.group(1)] = wl_val
    out["wirelength_by_layer_um"] = layer_wl

    viol_matches = re.findall(r"Number of violations\s*=\s*(\d+)\.", log_text)
    drc_text = drt_drc_path.read_text(encoding="utf-8") if drt_drc_path.exists() else ""
    drc_lines = [ln for ln in drc_text.splitlines() if ln.strip()]
    out["drt_drc_violation_count"] = len(drc_lines)
    if viol_matches:
        out["drt_last_reported_violations"] = int(viol_matches[-1])

    dpl_core = re.findall(r"\[INFO DPL-0006\] Core area:\s*([0-9.]+)\s*um\^2", log_text)
    dpl_mov = re.findall(r"\[INFO DPL-0007\] Movable instances area:\s*([0-9.]+)\s*um\^2", log_text)
    dpl_fix = re.findall(r"\[INFO DPL-0008\] Fixed instances area within core:\s*([0-9.]+)\s*um\^2", log_text)
    dpl_util = re.findall(r"\[INFO DPL-0009\] Utilization:\s*([0-9.]+)%", log_text)
    if dpl_core:
        out["core_area_um2"] = float(dpl_core[-1])
    if dpl_mov:
        out["movable_area_um2"] = float(dpl_mov[-1])
    if dpl_fix:
        out["fixed_area_um2"] = float(dpl_fix[-1])
    if dpl_util:
        out["dpl_utilization_pct"] = float(dpl_util[-1])

    # Programmatic instance & PDN counts from OpenROAD log and DEF
    m_inst = re.search(
        r"^POST_ROUTE_INST_COUNTS\s+core_area_um2=([0-9.]+)\s+std_cells=(\d+)\s+"
        r"macros=(\d+)\s+tapcells=(\d+)\s+filler_decap=(\d+)\s+total_insts=(\d+)",
        log_text,
        re.M,
    )
    def_stats = parse_def_physical_stats(def_path) if def_path.is_file() else {}
    if m_inst:
        out["core_area_um2"] = float(m_inst.group(1))
        out["post_route_stdcell_plus_macro_instances"] = int(m_inst.group(2)) + int(m_inst.group(3))
        out["post_route_tapcell_instances"] = int(m_inst.group(4))
        out["post_route_filler_decap_instances"] = int(m_inst.group(5))
    elif def_stats:
        for k in (
            "core_area_um2",
            "post_route_stdcell_plus_macro_instances",
            "post_route_tapcell_instances",
            "post_route_filler_decap_instances",
        ):
            if k in def_stats and (k != "core_area_um2" or "core_area_um2" not in out):
                out[k] = def_stats[k]

    if def_stats:
        out["pdn_specialnets_routed_nets"] = def_stats["pdn_specialnets_routed_nets"]
        out["pdn_specialnets_routed_segments"] = def_stats["pdn_specialnets_routed_segments"]

    out["placement_check_passed"] = "[ERROR DPL-" not in log_text and "Placement check failed" not in log_text
    return out


def strip_signed_in_netlist(netlist_path: Path) -> None:
    txt = netlist_path.read_text(encoding="utf-8")
    txt = re.sub(
        r"^([ \t]*(?:wire|reg|input|output|inout))[ \t]+signed[ \t]+",
        r"\1 ",
        txt,
        flags=re.M,
    )
    netlist_path.write_text(txt, encoding="utf-8")


def run_yosys_synth(
    *,
    yosys_bin: Path,
    name: str,
    top: str,
    pdk: str,
    liberty_files: List[Path],
    slang_args: List[str],
    target_period_ps: int,
    work_dir: Path,
) -> Tuple[Path, Path, Dict[str, Any]]:
    work_dir.mkdir(parents=True, exist_ok=True)
    netlist_path = work_dir / f"{top}_{pdk}.v"
    ys_path = work_dir / "synth.ys"
    log_path = work_dir / "yosys.log"
    abc_script = work_dir / "abc.script"
    abc_constr = work_dir / "abc.constr"

    abc_script.write_text(
        "strash\n&get -n\n&nf {D}\n&put\nbuffer -N 32\nupsize {D}\ndnsize {D}\nstime -p\n",
        encoding="utf-8",
    )

    if pdk == "asap7":
        abc_constr.write_text(
            "set_driving_cell BUFx4_ASAP7_75t_R\nset_load 5.0\n",
            encoding="utf-8",
        )
        dff_cmd = (
            f"dfflibmap -dont_use *DFFHQx4* -dont_use *DFFLQx4* "
            f"-liberty {liberty_files[0]}"
        )
        abc_cmd = (
            f"abc -markgroups -D {target_period_ps} -liberty {liberty_files[0]} "
            f"-constr {abc_constr} -script {abc_script}"
        )
        hilo_cmd = "hilomap -singleton -hicell TIEHIx1_ASAP7_75t_R H -locell TIELOx1_ASAP7_75t_R L"
        buf_cmd = "insbuf -buf BUFx2_ASAP7_75t_R A Y"
    elif pdk == "nangate45":
        abc_constr.write_text(
            "set_driving_cell BUF_X4\nset_load 4.0\n",
            encoding="utf-8",
        )
        dff_cmd = f"dfflibmap -liberty {liberty_files[0]}"
        abc_cmd = (
            f"abc -markgroups -D {target_period_ps} -liberty {liberty_files[0]} "
            f"-constr {abc_constr} -script {abc_script}"
        )
        hilo_cmd = "hilomap -singleton -hicell LOGIC1_X1 Z -locell LOGIC0_X1 Z"
        buf_cmd = "insbuf -buf BUF_X1 A Z"
    else:
        raise ValueError(f"Unsupported pdk {pdk}")

    lib_reads = "\n".join(f"read_liberty -lib {lf}" for lf in liberty_files)
    stat_libs = " ".join(f"-liberty {lf}" for lf in liberty_files)
    slang_line = "read_slang " + " ".join(shlex.quote(a) for a in slang_args)

    ys_text = "\n".join([
        lib_reads,
        slang_line,
        f"hierarchy -check -top {top}",
        "proc; opt; fsm; opt; memory; opt; alumacc; wreduce; opt; share; opt; flatten; opt; techmap; opt",
        dff_cmd,
        "setundef -zero",
        abc_cmd,
        "splitnets",
        "opt_clean -purge",
        hilo_cmd,
        buf_cmd,
        "opt_clean -purge",
        f"stat {stat_libs} -top {top}",
        f"write_verilog -noattr -noexpr -nohex -nodec {netlist_path}",
    ]) + "\n"
    ys_path.write_text(ys_text, encoding="utf-8")

    rc, out, elapsed = run_cmd(
        [str(yosys_bin), "-s", str(ys_path)],
        log_path=log_path,
    )
    if rc != 0:
        raise RuntimeError(f"Yosys failed for {name} (rc={rc}):\n{out[-2000:]}")

    strip_signed_in_netlist(netlist_path)
    stats = parse_yosys_stat(out, top)
    stats["yosys_runtime_s"] = round(elapsed, 2)
    stats["target_abc_period_ps"] = target_period_ps
    return netlist_path, log_path, stats


def run_opensta(
    *,
    opensta_bin: Path,
    name: str,
    top: str,
    netlist_path: Path,
    liberty_files: List[Path],
    work_dir: Path,
    sdc_file: Optional[Path] = None,
    clock_port: str = "clk",
    target_period_ns: Optional[str] = None,
    io_delay_ns: str = "0.050",
    clk_uncert_ns: str = "0.050",
    clk_hold_unc_ns: str = "0.020",
    core_period_ns: Optional[str] = None,
    axi_period_ns: Optional[str] = None,
    extra_sdc: Optional[Path] = None,
) -> Tuple[Path, Dict[str, Any]]:
    log_path = work_dir / "sta.log"
    env = {
        "TOP": top,
        "NETLIST": str(netlist_path),
        "LIB_FILES": ":".join(str(p) for p in liberty_files),
        "SDC_FILE": str(sdc_file) if sdc_file else "",
        "CLOCK_PORT": clock_port,
        "TARGET_PERIOD_NS": str(target_period_ns or "1.000"),
        "IO_DELAY_NS": io_delay_ns,
        "CLK_UNCERT_NS": clk_uncert_ns,
        "CLK_HOLD_UNC_NS": clk_hold_unc_ns,
    }
    if core_period_ns:
        env["CORE_PERIOD"] = core_period_ns
    if axi_period_ns:
        env["AXI_PERIOD"] = axi_period_ns
    if extra_sdc:
        env["EXTRA_SDC"] = str(extra_sdc)

    sta_tcl = PHYS_DIR / "asap7_synth_sta.tcl"
    rc, out, elapsed = run_cmd(
        [str(opensta_bin), "-no_splash", "-exit", str(sta_tcl)],
        env=env,
        log_path=log_path,
    )
    if rc != 0:
        raise RuntimeError(f"OpenSTA failed for {name} (rc={rc}):\n{out[-2000:]}")

    metrics = parse_sta_or_openroad_timing(out)
    metrics["opensta_runtime_s"] = round(elapsed, 2)
    return log_path, metrics


def collect_pnr_metrics_from_artifacts(
    *,
    name: str,
    top: str,
    pnr_dir: Path,
    gds_out_path: Path,
    elapsed_s: float,
) -> Dict[str, Any]:
    pnr_log = pnr_dir / "pnr.log"
    def_path = pnr_dir / f"{top}.def"
    spef_path = pnr_dir / f"{top}.spef"
    pnr_v_path = pnr_dir / f"{top}_pnr.v"
    grt_rpt = pnr_dir / "grt_congestion.rpt"
    drt_rpt = pnr_dir / "drt_drc.rpt"

    for req_path in (pnr_log, def_path, spef_path, pnr_v_path, drt_rpt, gds_out_path):
        if not req_path.is_file():
            raise RuntimeError(f"Missing PnR/GDS artifact for {name}: {req_path}")

    out = pnr_log.read_text(encoding="utf-8", errors="replace")
    if "KLAYOUT_VERIFY " not in out or "=== POST_ROUTE REPORTS END ===" not in out:
        raise RuntimeError(f"Incomplete PnR/GDS log for {name}: {pnr_log}")

    metrics = parse_pnr_metrics(out, drt_rpt, def_path)
    metrics["pnr_runtime_s"] = round(elapsed_s, 2)

    m_kl = re.search(
        r"KLAYOUT_VERIFY top=(\S+) cells=(\d+) layers=(\d+) bbox=\(([^)]+)\)",
        out,
    )
    klayout_info: Dict[str, Any] = {}
    if m_kl:
        coords = [float(x) for x in m_kl.group(4).split(",")]
        die_w = round(coords[2] - coords[0], 4)
        die_h = round(coords[3] - coords[1], 4)
        klayout_info = {
            "top_cell": m_kl.group(1),
            "gds_cell_count": int(m_kl.group(2)),
            "gds_layer_count": int(m_kl.group(3)),
            "die_width_um": die_w,
            "die_height_um": die_h,
            "die_area_um2": round(die_w * die_h, 4),
        }

    metrics["artifacts"] = {
        "def_path": str(def_path),
        "def_bytes": def_path.stat().st_size,
        "def_sha256": sha256_file(def_path),
        "spef_path": str(spef_path),
        "spef_bytes": spef_path.stat().st_size,
        "pnr_netlist_path": str(pnr_v_path),
        "grt_congestion_report": str(grt_rpt),
        "drt_drc_report": str(drt_rpt),
        "gds_path": str(gds_out_path),
        "gds_bytes": gds_out_path.stat().st_size,
        "gds_sha256": sha256_file(gds_out_path),
        "klayout": klayout_info,
        "log_path": str(pnr_log),
    }

    if metrics.get("drt_drc_violation_count", 0) != 0:
        raise RuntimeError(
            f"DRT DRC violation count for {name} is {metrics['drt_drc_violation_count']} (expected 0)"
        )
    if metrics.get("pdn_specialnets_routed_segments", 0) <= 0:
        raise RuntimeError(f"PDN SPECIALNETS has no routed power segments in {def_path}")
    if not metrics.get("placement_check_passed", False):
        raise RuntimeError(f"OpenROAD placement check failed for {name}")
    return metrics


def run_openroad_pnr_and_gds(
    *,
    out_root: Path,
    name: str,
    top: str,
    pdk: str,
    netlist_path: Path,
    pnr_dir: Path,
    gds_out_path: Path,
    sdc_container_path: Optional[str] = None,
    use_sram_macro: bool = False,
    target_period_ns: str = "1.000",
    utilization: str = "40",
    place_density: str = "0.55",
    die_area: Optional[str] = None,
    core_area: Optional[str] = None,
    sram_loc: str = "8.0 16.0",
    hold_margin_ns: str = "0.025",
    drt_end_iter: str = "20",
    core_period_ns: Optional[str] = None,
    axi_period_ns: Optional[str] = None,
    timeout_s: int = 1800,
) -> Dict[str, Any]:
    pnr_dir.mkdir(parents=True, exist_ok=True)
    gds_out_path.parent.mkdir(parents=True, exist_ok=True)

    rel_work = netlist_path.relative_to(out_root).as_posix()
    rel_pnr = pnr_dir.relative_to(out_root).as_posix()
    rel_gds = gds_out_path.relative_to(out_root).as_posix()

    if pdk == "asap7":
        in_gds_files = [f"{ORFS_FLOW}/platforms/asap7/gds/asap7sc7p5t_28_R_220121a.gds"]
        tech_file = f"{ORFS_FLOW}/platforms/asap7/KLayout/asap7.lyt"
    elif pdk == "nangate45":
        in_gds_files = [f"{ORFS_FLOW}/platforms/nangate45/gds/NangateOpenCellLibrary.gds"]
        tech_file = f"{ORFS_FLOW}/platforms/nangate45/FreePDK45.lyt"
    else:
        raise ValueError(f"Unsupported pdk {pdk}")

    docker_env = {
        "PDK": pdk,
        "TOP": top,
        "NETLIST": f"/work/{rel_work}",
        "OUT_DIR": f"/work/{rel_pnr}",
        "SDC_FILE": sdc_container_path or "",
        "USE_SRAM_MACRO": "1" if use_sram_macro else "0",
        "CLOCK_PORT": "clk",
        "TARGET_PERIOD_NS": target_period_ns,
        "UTILIZATION": utilization,
        "PLACE_DENSITY": place_density,
        "DIE_AREA": die_area or "",
        "CORE_AREA": core_area or "",
        "SRAM_LOC": sram_loc,
        "HOLD_MARGIN_NS": hold_margin_ns,
        "DRT_END_ITER": drt_end_iter,
        "GDS_ALLOW_EMPTY": "fakeram.*" if use_sram_macro else "",
    }
    if core_period_ns:
        docker_env["CORE_PERIOD"] = core_period_ns
    if axi_period_ns:
        docker_env["AXI_PERIOD"] = axi_period_ns

    env_flags: List[str] = []
    for k, v in docker_env.items():
        env_flags.extend(["-e", f"{k}={v}"])

    in_files_arg = " ".join(in_gds_files)
    container_cmd = (
        "source /OpenROAD-flow-scripts/env.sh >/dev/null 2>&1 && "
        "openroad -threads 2 -exit /repo/hw/asic/phys/openroad_pnr.tcl && "
        f"python3 {ORFS_FLOW}/util/def2stream.py "
        f"--design-name {shlex.quote(top)} "
        f"--in-def /work/{rel_pnr}/{top}.def "
        f"--in-files {shlex.quote(in_files_arg)} "
        f"--out-file /work/{rel_gds} "
        f"--tech-file {shlex.quote(tech_file)} && "
        "python3 -c "
        + shlex.quote(
            f"import klayout.db as db; ly = db.Layout(); ly.read('/work/{rel_gds}'); "
            f"tc = ly.top_cell(); bb = tc.dbbox(); "
            f"print(f'KLAYOUT_VERIFY top={{tc.name}} cells={{len(list(ly.each_cell()))}} "
            f"layers={{len(ly.layer_indices())}} bbox=({{bb.left:.4f}},{{bb.bottom:.4f}},{{bb.right:.4f}},{{bb.top:.4f}})')"
        )
    )

    uid_gid = f"{os.getuid()}:{os.getgid()}"
    pnr_log = pnr_dir / "pnr.log"
    rc, out, elapsed = run_cmd(
        [
            "docker",
            "run",
            "--rm",
            "--init",
            "--user",
            uid_gid,
            "-v",
            f"{REPO_ROOT}:/repo:ro",
            "-v",
            f"{out_root}:/work",
            *env_flags,
            ORFS_IMAGE,
            "bash",
            "-c",
            container_cmd,
        ],
        log_path=pnr_log,
        timeout=timeout_s,
    )
    if rc != 0:
        raise RuntimeError(f"OpenROAD PnR/GDS failed for {name} (rc={rc}):\n{out[-2500:]}")

    return collect_pnr_metrics_from_artifacts(
        name=name,
        top=top,
        pnr_dir=pnr_dir,
        gds_out_path=gds_out_path,
        elapsed_s=elapsed,
    )


def get_tool_provenance(yosys_bin: Path, opensta_bin: Path) -> Dict[str, Any]:
    _, yv, _ = run_cmd([str(yosys_bin), "-V"])
    _, sv, _ = run_cmd([str(opensta_bin), "-version"])
    _, or_ver_out, _ = run_cmd(
        [
            "docker",
            "image",
            "inspect",
            ORFS_IMAGE,
            "--format",
            "{{.Id}}",
        ]
    )
    _, kl_ver, _ = run_cmd(
        [
            "docker",
            "run",
            "--rm",
            ORFS_IMAGE,
            "bash",
            "-c",
            "source /OpenROAD-flow-scripts/env.sh >/dev/null 2>&1 && "
            "python3 -c 'import klayout; print(klayout.__version__)' && "
            "which openroad",
        ]
    )
    _, git_head, _ = run_cmd(["git", "rev-parse", "HEAD"])
    return {
        "git_head": git_head.strip(),
        "yosys": {
            "path": str(yosys_bin),
            "version": yv.strip(),
            "frontend": "read_slang",
        },
        "opensta": {
            "path": str(opensta_bin),
            "version": sv.strip(),
        },
        "openroad_orfs": {
            "docker_image": ORFS_IMAGE,
            "image_id": or_ver_out.strip(),
            "klayout_python_version": kl_ver.splitlines()[0].strip() if kl_ver.strip() else "unknown",
            "openroad_binary": kl_ver.splitlines()[1].strip() if len(kl_ver.splitlines()) > 1 else "unknown",
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=DEFAULT_OUT_ROOT,
        help="External output root for netlists, DEF, SPEF, logs, and binary GDS",
    )
    parser.add_argument(
        "--yosys-bin",
        type=Path,
        default=None,
        help="Path to Yosys binary (overrides YOSYS_BIN env var)",
    )
    parser.add_argument(
        "--opensta-bin",
        type=Path,
        default=None,
        help="Path to OpenSTA binary (overrides OPENSTA_BIN env var)",
    )
    parser.add_argument(
        "--asap7-lib",
        type=Path,
        default=None,
        help="Path to merged ASAP7 RVT TT Liberty file (overrides ASAP7_HOST_LIB env var)",
    )
    parser.add_argument(
        "--skip-soc-pnr",
        action="store_true",
        help="Skip full PnR for VX_asic_soc_top (runs DFT and TFR macro PnR only)",
    )
    parser.add_argument(
        "--only-synth",
        action="store_true",
        help="Run Stage 1 (Yosys synthesis + OpenSTA) only and write phys_results.json",
    )
    parser.add_argument(
        "--only-macro-pnr",
        action="store_true",
        help="Run Stage 2 PnR for the 3 macro/DFT targets using existing synthesized netlists and merge into phys_results.json",
    )
    parser.add_argument(
        "--only-soc-pnr",
        action="store_true",
        help="Run only VX_asic_soc_top PnR using the existing synthesized netlist in --out-dir and merge into phys_results.json",
    )
    parser.add_argument(
        "--only-pnr-id",
        type=str,
        default=None,
        help="Run a single PnR target by ID using existing synthesized netlist in --out-dir and merge into phys_results.json",
    )
    parser.add_argument(
        "--collect-soc-pnr",
        action="store_true",
        help="Collect and verify already-completed VX_asic_soc_top PnR/GDS artifacts in --out-dir and merge into phys_results.json",
    )
    parser.add_argument(
        "--clean",
        action="store_true",
        help="Remove previous output directory contents before executing",
    )
    args = parser.parse_args()

    mode_flags = [
        args.skip_soc_pnr,
        args.only_synth,
        args.only_macro_pnr,
        args.only_soc_pnr,
        args.only_pnr_id is not None,
        args.collect_soc_pnr,
    ]
    if sum(1 for f in mode_flags if f) > 1:
        parser.error(
            "At most one of --skip-soc-pnr, --only-synth, --only-macro-pnr, --only-soc-pnr, --only-pnr-id, --collect-soc-pnr may be specified"
        )
    if args.clean and args.skip_soc_pnr:
        parser.error("--clean cannot be combined with --skip-soc-pnr")
    if args.clean and (args.only_macro_pnr or args.only_soc_pnr or args.only_pnr_id is not None or args.collect_soc_pnr):
        parser.error("--clean cannot be combined with staged PnR flags")

    out_root = args.out_dir.expanduser().resolve()
    yosys_bin = resolve_binary(args.yosys_bin, "YOSYS_BIN", DEFAULT_YOSYS_BIN, "yosys")
    opensta_bin = resolve_binary(args.opensta_bin, "OPENSTA_BIN", DEFAULT_OPENSTA_BIN, "sta")

    if args.clean and out_root.exists():
        shutil.rmtree(out_root)
    out_root.mkdir(parents=True, exist_ok=True)
    for sub in ("gen_cfg", "libs", "wrappers", "synth", "sta", "pnr", "gds"):
        (out_root / sub).mkdir(parents=True, exist_ok=True)

    asap7_host_lib = resolve_asap7_host_lib(args.asap7_lib, out_root)
    provenance = get_tool_provenance(yosys_bin, opensta_bin)
    out_json = PHYS_DIR / "phys_results.json"

    print(f"[INFO] Running physical design flow at commit {provenance['git_head'][:12]} (out_dir={out_root})...")

    macro_pnr_cases: List[Dict[str, Any]] = [
        {
            "id": "vx_asic_dft_top_asap7",
            "synth_id": "vx_asic_dft_top_asap7",
            "module": "VX_asic_dft_top",
            "pdk": "asap7",
            "sdc_container_path": "/repo/hw/asic/constraints/aigpu_b1.sdc",
            "utilization": "40",
            "place_density": "0.55",
            "hold_margin_ns": "0.025",
            "drt_end_iter": "20",
            "gds_name": "VX_asic_dft_top_asap7.gds",
            "netlist_rel": "synth/vx_asic_dft_top_asap7/VX_asic_dft_top_asap7.v",
            "timeout_s": 600,
        },
        {
            "id": "vx_asic_dft_top_nangate45",
            "synth_id": "vx_asic_dft_top_nangate45",
            "module": "VX_asic_dft_top",
            "pdk": "nangate45",
            "sdc_container_path": "/repo/hw/asic/constraints/aigpu_b1.sdc",
            "utilization": "40",
            "place_density": "0.55",
            "hold_margin_ns": "0.025",
            "drt_end_iter": "20",
            "gds_name": "VX_asic_dft_top_nangate45.gds",
            "netlist_rel": "synth/vx_asic_dft_top_nangate45/VX_asic_dft_top_nangate45.v",
            "timeout_s": 600,
        },
        {
            "id": "vx_tcu_tfr_mul_f16_asap7",
            "synth_id": "vx_tcu_tfr_mul_f16_asap7",
            "module": "VX_tcu_tfr_mul_f16",
            "pdk": "asap7",
            "target_period_ns": "1.000",
            "utilization": "40",
            "place_density": "0.55",
            "hold_margin_ns": "0.025",
            "drt_end_iter": "12",
            "gds_name": "VX_tcu_tfr_mul_f16_asap7.gds",
            "netlist_rel": "synth/vx_tcu_tfr_mul_f16_asap7/VX_tcu_tfr_mul_f16_asap7.v",
            "timeout_s": 900,
        },
    ]

    soc_pnr_case: Dict[str, Any] = {
        "id": "vx_asic_soc_top_asap7_fakeram7",
        "synth_id": "vx_asic_soc_top_asap7_fakeram7",
        "module": "VX_asic_soc_top",
        "pdk": "asap7",
        "sdc_container_path": "/repo/hw/asic/constraints/aigpu_b1.sdc",
        "use_sram_macro": True,
        "die_area": "0 0 80 80",
        "core_area": "2.0 2.0 78.0 78.0",
        "sram_loc": "8.0 18.0",
        "place_density": "0.50",
        "hold_margin_ns": "0.025",
        "drt_end_iter": "10",
        "core_period_ns": "0.500",
        "axi_period_ns": "1.000",
        "gds_name": "VX_asic_soc_top_asap7.gds",
        "netlist_rel": "synth/vx_asic_soc_top_asap7_fakeram7/VX_asic_soc_top_asap7.v",
        "timeout_s": 1800,
    }

    def run_pnr_case_list(
        cases_to_run: List[Dict[str, Any]],
        netlist_map: Dict[str, Path],
        pnr_results: Dict[str, Any],
    ) -> bool:
        failed = False
        for pcase in cases_to_run:
            pid = pcase["id"]
            print(f"[OPENROAD PNR->GDS] {pid} ({pcase['module']} @ {pcase['pdk']}) ...")
            pdir = out_root / "pnr" / pid
            gds_path = out_root / "gds" / pcase["gds_name"]
            try:
                net_path = netlist_map.get(pcase["synth_id"])
                if net_path is None or not net_path.is_file():
                    raise RuntimeError(f"Synthesis netlist missing for {pcase['synth_id']}")
                pmetrics = run_openroad_pnr_and_gds(
                    out_root=out_root,
                    name=pid,
                    top=pcase["module"],
                    pdk=pcase["pdk"],
                    netlist_path=net_path,
                    pnr_dir=pdir,
                    gds_out_path=gds_path,
                    sdc_container_path=pcase.get("sdc_container_path"),
                    use_sram_macro=pcase.get("use_sram_macro", False),
                    target_period_ns=pcase.get("target_period_ns", "1.000"),
                    utilization=pcase.get("utilization", "40"),
                    place_density=pcase.get("place_density", "0.55"),
                    die_area=pcase.get("die_area"),
                    core_area=pcase.get("core_area"),
                    sram_loc=pcase.get("sram_loc", "8.0 16.0"),
                    hold_margin_ns=pcase.get("hold_margin_ns", "0.025"),
                    drt_end_iter=pcase.get("drt_end_iter", "20"),
                    core_period_ns=pcase.get("core_period_ns"),
                    axi_period_ns=pcase.get("axi_period_ns"),
                    timeout_s=pcase.get("timeout_s", 1200),
                )
                pmetrics["status"] = "complete"
                pnr_results[pid] = pmetrics
                print(
                    f"  -> GDS={pmetrics['artifacts']['gds_bytes']}B "
                    f"area={pmetrics.get('design_area_um2')}um^2 ({pmetrics.get('utilization_pct')}%) "
                    f"WL={pmetrics.get('total_wirelength_um')}um vias={pmetrics.get('total_vias')} "
                    f"DRC={pmetrics.get('drt_drc_violation_count')} "
                    f"PDN_segs={pmetrics.get('pdn_specialnets_routed_segments')} "
                    f"setup_wns={pmetrics.get('wns_setup_ns')}ns hold_min={pmetrics.get('worst_hold_slack_ns')}ns "
                    f"({pmetrics['pnr_runtime_s']}s)"
                )
            except Exception as exc:
                failed = True
                print(f"  -> [ERROR] {pid} did not complete: {exc}", file=sys.stderr)
                pnr_results[pid] = {
                    "status": "failed_or_timed_out",
                    "error": str(exc)[:1000],
                }
        return failed

    if args.only_macro_pnr or args.only_soc_pnr or args.only_pnr_id is not None or args.collect_soc_pnr:
        if not out_json.is_file():
            raise RuntimeError(f"Staged PnR requires existing {out_json}")
        existing_payload = json.loads(out_json.read_text(encoding="utf-8"))
        if existing_payload.get("tools", {}).get("git_head") != provenance["git_head"]:
            raise RuntimeError(
                "Existing phys_results.json git_head differs from current HEAD; run full synthesis first."
            )
        synth_results = existing_payload.get("synthesis_and_sta", {})
        pnr_results = existing_payload.get("openroad_pnr_and_gds", {})
        if args.collect_soc_pnr:
            pid = soc_pnr_case["id"]
            pdir = out_root / "pnr" / pid
            gds_path = out_root / "gds" / soc_pnr_case["gds_name"]
            pnr_log = pdir / "pnr.log"
            grt_rpt = pdir / "grt_congestion.rpt"
            if grt_rpt.is_file() and pnr_log.is_file():
                # GRT runs ~45s after launch; estimate full container runtime from log/file mtimes,
                # floored cleanly by OpenROAD DRT+other step runtime sum if grt_rpt is close.
                elapsed_est = max(0.0, pnr_log.stat().st_mtime - grt_rpt.stat().st_mtime + 45.0)
            else:
                elapsed_est = 0.0
            pmetrics = collect_pnr_metrics_from_artifacts(
                name=pid,
                top=soc_pnr_case["module"],
                pnr_dir=pdir,
                gds_out_path=gds_path,
                elapsed_s=elapsed_est,
            )
            pmetrics["status"] = "complete"
            pnr_results[pid] = pmetrics
            failed = False
            print(
                f"  -> GDS={pmetrics['artifacts']['gds_bytes']}B "
                f"area={pmetrics.get('design_area_um2')}um^2 ({pmetrics.get('utilization_pct')}%) "
                f"WL={pmetrics.get('total_wirelength_um')}um vias={pmetrics.get('total_vias')} "
                f"DRC={pmetrics.get('drt_drc_violation_count')} "
                f"PDN_segs={pmetrics.get('pdn_specialnets_routed_segments')} "
                f"setup_wns={pmetrics.get('wns_setup_ns')}ns hold_min={pmetrics.get('worst_hold_slack_ns')}ns "
                f"({pmetrics['pnr_runtime_s']}s)"
            )
        else:
            all_pnr_cases = macro_pnr_cases + [soc_pnr_case]
            if args.only_pnr_id is not None:
                cases_to_run = [c for c in all_pnr_cases if c["id"] == args.only_pnr_id]
                if not cases_to_run:
                    valid_ids = ", ".join(c["id"] for c in all_pnr_cases)
                    parser.error(f"Unknown --only-pnr-id '{args.only_pnr_id}' (valid: {valid_ids})")
            elif args.only_macro_pnr:
                cases_to_run = macro_pnr_cases
            else:
                cases_to_run = [soc_pnr_case]
            netlist_map = {c["synth_id"]: out_root / c["netlist_rel"] for c in cases_to_run}
            failed = run_pnr_case_list(cases_to_run, netlist_map, pnr_results)
        existing_payload["generated_utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        existing_payload["external_build_root"] = str(out_root)
        existing_payload["tools"] = provenance
        existing_payload["synthesis_and_sta"] = synth_results
        existing_payload["openroad_pnr_and_gds"] = pnr_results
        out_json.write_text(json.dumps(existing_payload, indent=2) + "\n", encoding="utf-8")
        print(f"[DONE] Updated {out_json}")
        return 1 if failed else 0

    # Generate VX_config.vh and VX_types.vh deterministically from repo TOML
    gen_cfg_dir = ensure_generated_hw_cfg(out_root / "gen_cfg")

    # Extract ORFS fakeram7_256x32.lib for host OpenSTA matching ORFS PnR SRAM macro
    fakeram7_lib = extract_orfs_file(
        f"{ORFS_FLOW}/platforms/asap7/lib/NLDM/fakeram7_256x32.lib",
        out_root / "libs/fakeram7_256x32.lib",
    )
    fakeram7_sv = out_root / "wrappers/VX_sram_1rw_fakeram7.sv"
    fakeram7_sv.write_text(FAKERAM7_256X32_WRAPPER_SV, encoding="utf-8")

    # Isolate synchronous datapath timing by false-pathing unbuffered pre-CTS reset synchronizer trees
    soc_datapath_only_extra_sdc = out_root / "wrappers/soc_datapath_excl_reset_sync.sdc"
    soc_datapath_only_extra_sdc.write_text(
        "set rst_nets [get_nets -quiet -hierarchical {rst_axi_sync1_q rst_core_sync1_q}]\n"
        "if {[llength $rst_nets] > 0} {\n"
        "  set_false_path -through $rst_nets\n"
        "}\n",
        encoding="utf-8",
    )

    # =========================================================================
    # Stage 1: Yosys + OpenSTA Synthesis & STA Matrix
    # =========================================================================
    synth_cases: List[Dict[str, Any]] = [
        {
            "id": "vx_asic_dft_top_asap7",
            "module": "VX_asic_dft_top",
            "description": "IEEE-1149.1 JTAG TAP, scan chain & MBIST controller",
            "pdk": "asap7",
            "liberty": [asap7_host_lib],
            "target_period_ps": 1000,
            "slang_args": [
                "--top", "VX_asic_dft_top",
                "--ignore-assertions",
                "-I", "hw/asic/dft",
                "-D", "SYNTHESIS",
                "-D", "ASIC",
                "-D", "YOSYS",
                "hw/asic/dft/VX_asic_dft_top.sv",
            ],
            "sta": {
                "sdc_file": AIGPU_SDC,
                "core_period_ns": "0.500",
                "axi_period_ns": "1.000",
            },
        },
        {
            "id": "vx_asic_dft_top_nangate45",
            "module": "VX_asic_dft_top",
            "description": "IEEE-1149.1 JTAG TAP, scan chain & MBIST controller (Nangate45 reference)",
            "pdk": "nangate45",
            "liberty": [NANGATE45_HOST_LIB],
            "target_period_ps": 2000,
            "slang_args": [
                "--top", "VX_asic_dft_top",
                "--ignore-assertions",
                "-I", "hw/asic/dft",
                "-D", "SYNTHESIS",
                "-D", "ASIC",
                "-D", "YOSYS",
                "hw/asic/dft/VX_asic_dft_top.sv",
            ],
            "sta": {
                "sdc_file": AIGPU_SDC,
                "core_period_ns": "0.500",
                "axi_period_ns": "1.000",
            },
        },
        {
            "id": "vx_asic_soc_top_asap7_fakeram7",
            "module": "VX_asic_soc_top",
            "description": "Dual-clock CDC AXI4 SoC shell with hard fakeram7_256x32 boot SRAM macro",
            "pdk": "asap7",
            "liberty": [asap7_host_lib, fakeram7_lib],
            "target_period_ps": 500,
            "slang_args": [
                "--top", "VX_asic_soc_top",
                "--ignore-assertions",
                "-I", "hw/asic/dft",
                "-I", "hw/asic/sram",
                "-I", "hw/asic/soc",
                "-D", "SYNTHESIS",
                "-D", "ASIC",
                "-D", "ASIC_SRAM_MACROS",
                "-D", "YOSYS",
                "hw/asic/dft/VX_asic_dft_top.sv",
                str(fakeram7_sv),
                "hw/asic/sram/VX_sram_1rw.sv",
                "hw/asic/soc/VX_asic_soc_top.sv",
            ],
            "sta": {
                "sdc_file": AIGPU_SDC,
                "core_period_ns": "0.500",
                "axi_period_ns": "1.000",
            },
            "sta_datapath_check": {
                "extra_sdc": soc_datapath_only_extra_sdc,
            },
        },
        {
            "id": "vx_asic_soc_top_asap7_behav_sram",
            "module": "VX_asic_soc_top",
            "description": "Dual-clock CDC AXI4 SoC shell (all-flip-flop behavioral 1 KiB boot SRAM baseline)",
            "pdk": "asap7",
            "liberty": [asap7_host_lib],
            "target_period_ps": 500,
            "slang_args": [
                "--top", "VX_asic_soc_top",
                "--ignore-assertions",
                "-I", "hw/asic/dft",
                "-I", "hw/asic/sram",
                "-I", "hw/asic/soc",
                "-D", "SYNTHESIS",
                "-D", "ASIC",
                "-D", "YOSYS",
                "hw/asic/dft/VX_asic_dft_top.sv",
                "hw/asic/sram/VX_sram_1rw.sv",
                "hw/asic/soc/VX_asic_soc_top.sv",
            ],
            "sta": {
                "sdc_file": AIGPU_SDC,
                "core_period_ns": "0.500",
                "axi_period_ns": "1.000",
            },
        },
        {
            "id": "vx_tcu_fedp_tfr_asap7_lat4",
            "module": "VX_tcu_fedp_tfr",
            "description": "TFR FP16/BF16 Tensor-Core FEDP macro (N=2, NT=4, default LATENCY=4)",
            "pdk": "asap7",
            "liberty": [asap7_host_lib],
            "target_period_ps": 800,
            "slang_args": [
                "--top", "VX_tcu_fedp_tfr",
                "--ignore-assertions",
                "-I", str(gen_cfg_dir),
                "-I", "hw/rtl",
                "-I", "hw/rtl/libs",
                "-I", "hw/rtl/tcu",
                "-I", "hw/rtl/tcu/tfr",
                "-I", "hw/rtl/interfaces",
                "-D", "SYNTHESIS",
                "-D", "ASIC",
                "-D", "YOSYS",
                "-D", "VX_CFG_XLEN=64",
                "-D", "VX_CFG_XLEN_64",
                "-D", "VX_CFG_NUM_THREADS=4",
                "-D", "VX_CFG_NUM_WARPS=4",
                "-D", "VX_CFG_EXT_TCU_ENABLE",
                "-D", "VX_CFG_TCU_TYPE=TFR",
                "-D", "VX_CFG_TCU_TYPE_TFR",
                "-D", "VX_CFG_TCU_FP16_ENABLE",
                *TFR_SRC_FILES,
            ],
            "sta": {
                "clock_port": "clk",
                "target_period_ns": "1.000",
                "io_delay_ns": "0.040",
                "clk_uncert_ns": "0.048",
                "clk_hold_unc_ns": "0.020",
            },
        },
        {
            "id": "vx_tcu_fedp_tfr_asap7_lat5",
            "module": "VX_tcu_fedp_tfr",
            "description": "TFR FP16/BF16 Tensor-Core FEDP macro (N=2, NT=4, LATENCY=5 pipelined)",
            "pdk": "asap7",
            "liberty": [asap7_host_lib],
            "target_period_ps": 800,
            "slang_args": [
                "--top", "VX_tcu_fedp_tfr",
                "--ignore-assertions",
                "-I", str(gen_cfg_dir),
                "-I", "hw/rtl",
                "-I", "hw/rtl/libs",
                "-I", "hw/rtl/tcu",
                "-I", "hw/rtl/tcu/tfr",
                "-I", "hw/rtl/interfaces",
                "-D", "SYNTHESIS",
                "-D", "ASIC",
                "-D", "YOSYS",
                "-D", "VX_CFG_XLEN=64",
                "-D", "VX_CFG_XLEN_64",
                "-D", "VX_CFG_NUM_THREADS=4",
                "-D", "VX_CFG_NUM_WARPS=4",
                "-D", "VX_CFG_EXT_TCU_ENABLE",
                "-D", "VX_CFG_TCU_TYPE=TFR",
                "-D", "VX_CFG_TCU_TYPE_TFR",
                "-D", "VX_CFG_TCU_FP16_ENABLE",
                "-D", "VX_CFG_TCU_LATENCY=5",
                *TFR_SRC_FILES,
            ],
            "sta": {
                "clock_port": "clk",
                "target_period_ns": "1.000",
                "io_delay_ns": "0.040",
                "clk_uncert_ns": "0.048",
                "clk_hold_unc_ns": "0.020",
            },
        },
        {
            "id": "vx_tcu_fedp_tfr_nangate45_lat4",
            "module": "VX_tcu_fedp_tfr",
            "description": "TFR FP16/BF16 Tensor-Core FEDP macro (Nangate45 reference, LATENCY=4)",
            "pdk": "nangate45",
            "liberty": [NANGATE45_HOST_LIB],
            "target_period_ps": 2000,
            "slang_args": [
                "--top", "VX_tcu_fedp_tfr",
                "--ignore-assertions",
                "-I", str(gen_cfg_dir),
                "-I", "hw/rtl",
                "-I", "hw/rtl/libs",
                "-I", "hw/rtl/tcu",
                "-I", "hw/rtl/tcu/tfr",
                "-I", "hw/rtl/interfaces",
                "-D", "SYNTHESIS",
                "-D", "ASIC",
                "-D", "YOSYS",
                "-D", "VX_CFG_XLEN=64",
                "-D", "VX_CFG_XLEN_64",
                "-D", "VX_CFG_NUM_THREADS=4",
                "-D", "VX_CFG_NUM_WARPS=4",
                "-D", "VX_CFG_EXT_TCU_ENABLE",
                "-D", "VX_CFG_TCU_TYPE=TFR",
                "-D", "VX_CFG_TCU_TYPE_TFR",
                "-D", "VX_CFG_TCU_FP16_ENABLE",
                *TFR_SRC_FILES,
            ],
            "sta": {
                "clock_port": "clk",
                "target_period_ns": "2.000",
                "io_delay_ns": "0.050",
                "clk_uncert_ns": "0.050",
                "clk_hold_unc_ns": "0.020",
            },
        },
        {
            "id": "vx_tcu_tfr_mul_f16_asap7",
            "module": "VX_tcu_tfr_mul_f16",
            "description": "TFR FP16/BF16/TF32 Booth-Wallace product macro (PROD_REG=1, TCK=4)",
            "pdk": "asap7",
            "liberty": [asap7_host_lib],
            "target_period_ps": 800,
            "slang_args": [
                "--top", "VX_tcu_tfr_mul_f16",
                "--ignore-assertions",
                "-I", str(gen_cfg_dir),
                "-I", "hw/rtl",
                "-I", "hw/rtl/libs",
                "-I", "hw/rtl/tcu",
                "-I", "hw/rtl/tcu/tfr",
                "-I", "hw/rtl/interfaces",
                "-D", "SYNTHESIS",
                "-D", "ASIC",
                "-D", "YOSYS",
                "-D", "VX_CFG_XLEN=64",
                "-D", "VX_CFG_XLEN_64",
                "-D", "VX_CFG_NUM_THREADS=4",
                "-D", "VX_CFG_NUM_WARPS=4",
                "-D", "VX_CFG_EXT_TCU_ENABLE",
                "-D", "VX_CFG_TCU_TYPE=TFR",
                "-D", "VX_CFG_TCU_TYPE_TFR",
                "-D", "VX_CFG_TCU_FP16_ENABLE",
                "-G", "PROD_REG=1",
                "hw/rtl/VX_gpu_pkg.sv",
                "hw/rtl/tcu/VX_tcu_pkg.sv",
                "hw/rtl/tcu/tfr/VX_tcu_tfr_mul_f16.sv",
                "hw/rtl/tcu/tfr/VX_tcu_tfr_classifier.sv",
                "hw/rtl/tcu/tfr/VX_tcu_tfr_wmul.sv",
                "hw/rtl/libs/VX_pipe_register.sv",
                "hw/rtl/libs/VX_wallace_mul.sv",
                "hw/rtl/libs/VX_ks_adder.sv",
                "hw/rtl/libs/VX_csa_tree.sv",
                "hw/rtl/libs/VX_csa_32.sv",
                "hw/rtl/libs/VX_csa_42.sv",
            ],
            "sta": {
                "clock_port": "clk",
                "target_period_ns": "1.000",
                "io_delay_ns": "0.030",
                "clk_uncert_ns": "0.030",
                "clk_hold_unc_ns": "0.020",
            },
        },
    ]

    synth_results: Dict[str, Any] = {}
    netlists: Dict[str, Path] = {}
    had_failure = False

    for case in synth_cases:
        cid = case["id"]
        print(f"[SYNTH+STA] {cid} ({case['module']} @ {case['pdk']}) ...")
        s_dir = out_root / "synth" / cid
        sta_dir = out_root / "sta" / cid
        sta_dir.mkdir(parents=True, exist_ok=True)

        try:
            netlist_path, ylog_path, ystats = run_yosys_synth(
                yosys_bin=yosys_bin,
                name=cid,
                top=case["module"],
                pdk=case["pdk"],
                liberty_files=case["liberty"],
                slang_args=case["slang_args"],
                target_period_ps=case["target_period_ps"],
                work_dir=s_dir,
            )
            netlists[cid] = netlist_path

            sta_cfg = case["sta"]
            slog_path, sta_metrics = run_opensta(
                opensta_bin=opensta_bin,
                name=cid,
                top=case["module"],
                netlist_path=netlist_path,
                liberty_files=case["liberty"],
                work_dir=sta_dir,
                sdc_file=sta_cfg.get("sdc_file"),
                clock_port=sta_cfg.get("clock_port", "clk"),
                target_period_ns=sta_cfg.get("target_period_ns"),
                io_delay_ns=sta_cfg.get("io_delay_ns", "0.050"),
                clk_uncert_ns=sta_cfg.get("clk_uncert_ns", "0.050"),
                clk_hold_unc_ns=sta_cfg.get("clk_hold_unc_ns", "0.020"),
                core_period_ns=sta_cfg.get("core_period_ns"),
                axi_period_ns=sta_cfg.get("axi_period_ns"),
            )

            achieved_fmax = None
            clks = sta_metrics.get("clocks_min_period", {})
            if sta_cfg.get("sdc_file") is None and "clk" in clks:
                achieved_fmax = clks["clk"]["fmax_mhz"]
            elif "tck" in clks:
                achieved_fmax = clks["tck"]["fmax_mhz"]

            entry: Dict[str, Any] = {
                "id": cid,
                "module": case["module"],
                "description": case["description"],
                "pdk": case["pdk"],
                "liberty_files": [str(p) for p in case["liberty"]],
                "yosys": ystats,
                "opensta_post_synth": sta_metrics,
                "achieved_fmax_mhz": achieved_fmax,
                "netlist_path": str(netlist_path),
                "netlist_sha256": sha256_file(netlist_path),
                "yosys_log_path": str(ylog_path),
                "opensta_log_path": str(slog_path),
            }

            if "sta_datapath_check" in case:
                dp_dir = sta_dir / "datapath_excl_reset_sync"
                dp_dir.mkdir(parents=True, exist_ok=True)
                dp_log, dp_metrics = run_opensta(
                    opensta_bin=opensta_bin,
                    name=f"{cid}_datapath",
                    top=case["module"],
                    netlist_path=netlist_path,
                    liberty_files=case["liberty"],
                    work_dir=dp_dir,
                    sdc_file=sta_cfg.get("sdc_file"),
                    core_period_ns=sta_cfg.get("core_period_ns"),
                    axi_period_ns=sta_cfg.get("axi_period_ns"),
                    extra_sdc=case["sta_datapath_check"]["extra_sdc"],
                )
                dp_metrics["opensta_log_path"] = str(dp_log)
                entry["opensta_post_synth_datapath_excl_async_reset_tree"] = dp_metrics

            synth_results[cid] = entry
            print(
                f"  -> cells={ystats['cell_count']} ff={ystats['flip_flop_count']} "
                f"stdcell_area={ystats['standard_cell_area_um2']} um^2 "
                f"wns={sta_metrics.get('wns_setup_ns')}ns fmax={achieved_fmax}MHz"
            )
        except Exception as exc:
            had_failure = True
            print(f"  -> [ERROR] {cid} synthesis/STA failed: {exc}", file=sys.stderr)
            synth_results[cid] = {
                "id": cid,
                "module": case["module"],
                "pdk": case["pdk"],
                "status": "failed",
                "error": str(exc)[:1000],
            }

    # =========================================================================
    # Stage 2: OpenROAD Place-and-Route -> RCX -> Post-Route STA -> GDSII
    # =========================================================================
    pnr_results: Dict[str, Any] = {}
    if not args.only_synth:
        pnr_cases: List[Dict[str, Any]] = list(macro_pnr_cases)
        if not args.skip_soc_pnr:
            pnr_cases.append(soc_pnr_case)
        if run_pnr_case_list(pnr_cases, netlists, pnr_results):
            had_failure = True

    payload = {
        "schema_version": 1,
        "artifact_id": "aigpu_phys_proof",
        "evidence_level": "open_source_synth_pnr_gds",
        "foundry_signoff": False,
        "non_signoff_notice": (
            "All synthesis, STA, placement, CTS, detailed routing, OpenRCX parasitic extraction, "
            "and GDSII streamout metrics in this record were produced by real open-source EDA runs "
            "(Yosys, OpenSTA, OpenROAD ORFS, KLayout) targeting academic/open PDKs "
            "(ASAP7 7nm RVT NLDM and Nangate45 45nm typical, with FakeRAM7_256x32 blackbox SRAM macro). "
            "Commercial foundry PDK/SRAM-compiler sign-off (DRC, LVS, multi-corner EM/IR, foundry tape-out) "
            "is NOT established by this packet (foundry_signoff=false)."
        ),
        "generated_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "external_build_root": str(out_root),
        "tools": provenance,
        "synthesis_and_sta": synth_results,
        "openroad_pnr_and_gds": pnr_results,
    }

    out_json.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"[DONE] Wrote {out_json}")
    return 1 if had_failure else 0


if __name__ == "__main__":
    sys.exit(main())

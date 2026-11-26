#!/usr/bin/env python3
# Copyright (c) 2018-2026 Georgia Tech Vortex & AI-GPU Project
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Open-source formal verification runner using Yosys + yosys-smtbmc + Z3."""

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time


DEFAULT_YOSYS = "/home/antigravity/tools/yosys/bin/yosys"
DEFAULT_SMTBMC = "/home/antigravity/tools/yosys/bin/yosys-smtbmc"
DEFAULT_BUILD_DIR = "/home/antigravity/vortex_builds/dv_formal"


def run_cmd(cmd, cwd, timeout=180):
    t0 = time.monotonic()
    proc = subprocess.run(
        cmd,
        cwd=cwd,
        text=True,
        capture_output=True,
        timeout=timeout,
    )
    elapsed = round(time.monotonic() - t0, 3)
    return {
        "command": " ".join(cmd),
        "returncode": proc.returncode,
        "elapsed_sec": elapsed,
        "stdout": proc.stdout,
        "stderr": proc.stderr,
    }


def extract_status(output):
    if "Status: PASSED" in output:
        return "PASS"
    if "Status: FAILED" in output:
        return "FAIL"
    return "UNKNOWN"


def main():
    repo_root = Path(__file__).resolve().parents[3]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--yosys", default=DEFAULT_YOSYS)
    parser.add_argument("--smtbmc", default=DEFAULT_SMTBMC)
    parser.add_argument("--solver", default="z3")
    parser.add_argument("--build-dir", type=Path, default=Path(DEFAULT_BUILD_DIR))
    parser.add_argument("--dft-bmc-depth", type=int, default=20)
    parser.add_argument("--cdc-bmc-depth", type=int, default=12)
    parser.add_argument("--induct-depth", type=int, default=4)
    parser.add_argument("--out-json", type=Path, default=None)
    args = parser.parse_args()

    args.build_dir.mkdir(parents=True, exist_ok=True)

    # Tool version provenance
    yosys_ver = subprocess.check_output([args.yosys, "-V"], text=True).strip()
    z3_ver = subprocess.check_output([args.solver, "--version"], text=True).strip()

    proofs = []

    specs = [
        {
            "id": "dft_tap_k_induction",
            "module": "VX_asic_dft_formal",
            "mode": "k-induction",
            "depth": args.induct_depth,
            "defines": ["-DFORMAL_INDUCT_ONLY"],
            "sources": [
                "hw/asic/dft/VX_asic_dft_top.sv",
                "hw/dv/formal/VX_asic_dft_formal.sv",
            ],
            "chparams": [],
            "smt2": args.build_dir / "dft_induct.smt2",
            "smtbmc_flags": ["-i", "-t", str(args.induct_depth), "--unroll", "--noprogress"],
            "properties": [
                "Exhaustive 16-state IEEE-1149.1 TAP 5-cycle TMS=1 return to TEST_LOGIC_RESET",
                "TEST_LOGIC_RESET self-loop invariance under TMS=1",
                "Reset-safe functional outputs (dft_scan_enable=0, dft_test_mode=0, mbist_run=0, pwr_clust_en=4'hF)",
            ],
        },
        {
            "id": "dft_tap_bmc",
            "module": "VX_asic_dft_formal",
            "mode": "BMC",
            "depth": args.dft_bmc_depth,
            "defines": [],
            "sources": [
                "hw/asic/dft/VX_asic_dft_top.sv",
                "hw/dv/formal/VX_asic_dft_formal.sv",
            ],
            "chparams": [],
            "smt2": args.build_dir / "dft_bmc.smt2",
            "smtbmc_flags": ["-t", str(args.dft_bmc_depth), "--unroll", "--noprogress"],
            "properties": [
                "Reachable 16-state JTAG TAP returns to TEST_LOGIC_RESET within 5 TMS=1 TCK cycles",
                "IDCODE immutability and exact bit-serial TDO shift match 32'h1A16_B101",
                "dft_scan_enable=0, dft_test_mode=0, mbist_run=0, pwr_clust_en=4'hF in TEST_LOGIC_RESET",
                "TDO output-enable active strictly in SHIFT_DR / SHIFT_IR",
            ],
        },
        {
            "id": "cdc_fifo_k_induction",
            "module": "VX_cdc_fifo_formal",
            "mode": "k-induction",
            "depth": args.induct_depth,
            "defines": ["-DFORMAL_INDUCT_ONLY"],
            "sources": [
                "hw/dv/sva/VX_cdc_fifo_sva.sv",
                "hw/dv/formal/VX_cdc_fifo_formal.sv",
            ],
            "chparams": [("ADDRW", "3"), ("DATAW", "8")],
            "smt2": args.build_dir / "cdc_induct.smt2",
            "smtbmc_flags": ["-i", "-t", str(args.induct_depth), "--unroll", "--noprogress"],
            "properties": [
                "Exhaustive bijection gray2bin(bin2gray(x)) == x and bin2gray(gray2bin(x)) == x for all x",
                "Consecutive Gray-code pointers differ by exactly 1 bit (Hamming distance == 1)",
                "Gray full/empty flag equivalence to binary occupancy and mutual exclusion",
            ],
        },
        {
            "id": "cdc_fifo_bmc",
            "module": "VX_cdc_fifo_formal",
            "mode": "BMC",
            "depth": args.cdc_bmc_depth,
            "defines": [],
            "sources": [
                "hw/dv/sva/VX_cdc_fifo_sva.sv",
                "hw/dv/formal/VX_cdc_fifo_formal.sv",
            ],
            "chparams": [("ADDRW", "3"), ("DATAW", "8")],
            "smt2": args.build_dir / "cdc_bmc.smt2",
            "smtbmc_flags": ["-t", str(args.cdc_bmc_depth), "--unroll", "--noprogress"],
            "properties": [
                "Dual-clock async Gray-code CDC FIFO under arbitrary wclk/rclk phase/ratio",
                "VX_cdc_fifo_sva zero violations (no write-when-full, no read-when-empty, 1-bit Gray steps)",
                "Exact push/pop occupancy conservation and bit-exact head data integrity",
            ],
        },
        {
            "id": "axi4_sva_compile_formal",
            "module": "VX_axi4_sva",
            "mode": "formal-smt2",
            "depth": args.induct_depth,
            "defines": [],
            "sources": [
                "hw/dv/sva/VX_axi4_sva.sv",
            ],
            "chparams": [],
            "smt2": args.build_dir / "axi4_sva_formal.smt2",
            "smtbmc_flags": None,
            "properties": [
                "Formal elaboration and SMT-LIBv2 extraction of VX_axi4_sva protocol monitors",
            ],
        },
        {
            "id": "tcu_handshake_sva_compile_formal",
            "module": "VX_tcu_handshake_sva",
            "mode": "formal-smt2",
            "depth": args.induct_depth,
            "defines": [],
            "sources": [
                "hw/dv/sva/VX_tcu_handshake_sva.sv",
            ],
            "chparams": [],
            "smt2": args.build_dir / "tcu_handshake_sva_formal.smt2",
            "smtbmc_flags": None,
            "properties": [
                "Formal elaboration and SMT-LIBv2 extraction of VX_tcu_handshake_sva monitors",
            ],
        },
    ]

    overall_pass = True
    for spec in specs:
        chparam_cmds = " ".join(
            f"chparam -set {k} {v} {spec['module']};" for k, v in spec["chparams"]
        )
        define_str = " ".join(spec["defines"])
        yosys_script = (
            f"read_verilog -sv -formal {define_str} {' '.join(spec['sources'])}; "
            f"{chparam_cmds} "
            f"prep -top {spec['module']}; "
            f"flatten; memory_map; opt; clk2fflogic; opt_clean; "
            f"write_smt2 -wires {spec['smt2']}"
        )
        y_res = run_cmd([args.yosys, "-q", "-p", yosys_script], cwd=repo_root)
        entry = {
            "id": spec["id"],
            "module": spec["module"],
            "mode": spec["mode"],
            "depth": spec["depth"],
            "properties": spec["properties"],
            "yosys_command": y_res["command"],
            "yosys_returncode": y_res["returncode"],
            "yosys_elapsed_sec": y_res["elapsed_sec"],
        }
        if y_res["returncode"] != 0:
            entry["verdict"] = "FAIL"
            entry["yosys_stderr"] = y_res["stderr"]
            overall_pass = False
            proofs.append(entry)
            continue

        if spec["smtbmc_flags"] is None:
            entry["smtbmc_command"] = None
            entry["smtbmc_returncode"] = 0
            entry["smtbmc_elapsed_sec"] = 0.0
            entry["verdict"] = "PASS_ELAB_SMT2"
            proofs.append(entry)
            continue

        smt_cmd = [args.smtbmc, "-s", args.solver] + spec["smtbmc_flags"] + [str(spec["smt2"])]
        s_res = run_cmd(smt_cmd, cwd=repo_root, timeout=300)
        verdict = extract_status(s_res["stdout"])
        if s_res["returncode"] != 0 or verdict != "PASS":
            overall_pass = False
        steps_checked = len(re.findall(r"(Checking assertions|Trying induction) in step", s_res["stdout"]))
        entry.update({
            "smtbmc_command": s_res["command"],
            "smtbmc_returncode": s_res["returncode"],
            "smtbmc_elapsed_sec": s_res["elapsed_sec"],
            "steps_checked": steps_checked,
            "verdict": verdict,
            "log_tail": s_res["stdout"].strip().splitlines()[-8:],
        })
        proofs.append(entry)
        print(f"[{entry['verdict']}] {spec['id']} ({spec['mode']} depth={spec['depth']}, {s_res['elapsed_sec']}s)")

    report = {
        "yosys_version": yosys_ver,
        "solver": args.solver,
        "solver_version": z3_ver,
        "overall_verdict": "PASS" if overall_pass else "FAIL",
        "proofs": proofs,
    }
    if args.out_json is not None:
        args.out_json.parent.mkdir(parents=True, exist_ok=True)
        args.out_json.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    return 0 if overall_pass else 1


if __name__ == "__main__":
    sys.exit(main())

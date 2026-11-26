#!/usr/bin/env bash
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

# Compiles VX_asic_soc_top + VX_asic_dft_top + VX_sram_1rw + SVA protocol
# monitors with Verilator --assert --coverage-line --coverage-toggle into an
# out-of-tree build directory, runs tb_asic_soc, and extracts real line/toggle
# coverage percentages via verilator_coverage.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"
VERILATOR="${VERILATOR:-/home/antigravity/tools/verilator/bin/verilator}"
VERILATOR_COV="${VERILATOR_COV:-/home/antigravity/tools/verilator/bin/verilator_coverage}"
BUILD_DIR="${BUILD_DIR:-/home/antigravity/vortex_builds/dv_cov}"
SEED="${SEED:-0x5A172026}"
OPS_PER_RATIO="${OPS_PER_RATIO:-350}"

mkdir -p "${BUILD_DIR}/obj_dir" "${BUILD_DIR}/annotate" "${BUILD_DIR}/annotate_dut"

WRAP_SV="${BUILD_DIR}/tb_soc_wrap.sv"
COV_DAT="${BUILD_DIR}/coverage.dat"
SIM_JSON="${BUILD_DIR}/sim_summary.json"
COV_FULL_LOG="${BUILD_DIR}/cov_full.log"
COV_DUT_LOG="${BUILD_DIR}/cov_dut.log"
SUMMARY_JSON="${BUILD_DIR}/coverage_report.json"

cat > "${WRAP_SV}" << 'EOF'
// Out-of-tree verification wrapper binding VX_axi4_sva, VX_cdc_fifo_sva,
// and VX_tcu_handshake_sva onto VX_asic_soc_top under --assert --coverage.
module tb_soc_wrap #(
    parameter int NUM_CLUSTERS    = 4,
    parameter int SCAN_CHAINS     = 8,
    parameter int CDC_ADDRW       = 3,
    parameter int AXIL_ADDRW      = 12,
    parameter int AXIL_DATAW      = 32,
    parameter int AXI_ADDRW       = 48,
    parameter int AXI_DATAW       = 64,
    parameter int AXI_IDW         = 4,
    parameter int BOOT_SRAM_DEPTH = 256
) (
    input  wire                        clk_core,
    input  wire                        clk_axi,
    input  wire                        rst_n,

    input  wire                        tck,
    input  wire                        trst_n,
    input  wire                        tms,
    input  wire                        tdi,
    output wire                        tdo,
    output wire                        tdo_oe_n,
    input  wire                        por_n,
    input  wire                        test_mode_pin,
    input  wire                        scan_enable_pin,
    input  wire [SCAN_CHAINS-1:0]      scan_in,
    output wire [SCAN_CHAINS-1:0]      scan_out,
    output wire [NUM_CLUSTERS-1:0]     pwr_clust_en,
    output wire [NUM_CLUSTERS-1:0]     pwr_clust_iso_en,
    output wire [NUM_CLUSTERS-1:0]     pwr_clust_ret_en,
    output wire                        dft_scan_enable,
    output wire                        dft_test_mode,
    output wire                        dft_cg_override,
    output wire                        irq,

    input  wire                        s_axil_awvalid,
    output wire                        s_axil_awready,
    input  wire [AXIL_ADDRW-1:0]       s_axil_awaddr,
    input  wire [2:0]                  s_axil_awprot,
    input  wire                        s_axil_wvalid,
    output wire                        s_axil_wready,
    input  wire [AXIL_DATAW-1:0]       s_axil_wdata,
    input  wire [(AXIL_DATAW/8)-1:0]   s_axil_wstrb,
    output wire                        s_axil_bvalid,
    input  wire                        s_axil_bready,
    output wire [1:0]                  s_axil_bresp,
    input  wire                        s_axil_arvalid,
    output wire                        s_axil_arready,
    input  wire [AXIL_ADDRW-1:0]       s_axil_araddr,
    input  wire [2:0]                  s_axil_arprot,
    output wire                        s_axil_rvalid,
    input  wire                        s_axil_rready,
    output wire [AXIL_DATAW-1:0]       s_axil_rdata,
    output wire [1:0]                  s_axil_rresp,

    output wire                        m_axi_awvalid,
    input  wire                        m_axi_awready,
    output wire [AXI_IDW-1:0]          m_axi_awid,
    output wire [AXI_ADDRW-1:0]        m_axi_awaddr,
    output wire [7:0]                  m_axi_awlen,
    output wire [2:0]                  m_axi_awsize,
    output wire [1:0]                  m_axi_awburst,
    output wire                        m_axi_awlock,
    output wire [3:0]                  m_axi_awcache,
    output wire [2:0]                  m_axi_awprot,
    output wire [3:0]                  m_axi_awqos,
    output wire                        m_axi_wvalid,
    input  wire                        m_axi_wready,
    output wire [AXI_DATAW-1:0]        m_axi_wdata,
    output wire [(AXI_DATAW/8)-1:0]    m_axi_wstrb,
    output wire                        m_axi_wlast,
    input  wire                        m_axi_bvalid,
    output wire                        m_axi_bready,
    input  wire [AXI_IDW-1:0]          m_axi_bid,
    input  wire [1:0]                  m_axi_bresp,
    output wire                        m_axi_arvalid,
    input  wire                        m_axi_arready,
    output wire [AXI_IDW-1:0]          m_axi_arid,
    output wire [AXI_ADDRW-1:0]        m_axi_araddr,
    output wire [7:0]                  m_axi_arlen,
    output wire [2:0]                  m_axi_arsize,
    output wire [1:0]                  m_axi_arburst,
    output wire                        m_axi_arlock,
    output wire [3:0]                  m_axi_arcache,
    output wire [2:0]                  m_axi_arprot,
    output wire [3:0]                  m_axi_arqos,
    input  wire                        m_axi_rvalid,
    output wire                        m_axi_rready,
    input  wire [AXI_IDW-1:0]          m_axi_rid,
    input  wire [AXI_DATAW-1:0]        m_axi_rdata,
    input  wire [1:0]                  m_axi_rresp,
    input  wire                        m_axi_rlast,

    // TCU handshake monitor exercise ports
    input  wire                        tcu_req_valid,
    input  wire                        tcu_req_ready,
    input  wire [43:0]                 tcu_req_tag,
    input  wire                        tcu_req_wb,
    input  wire                        tcu_rsp_valid,
    input  wire                        tcu_rsp_ready,
    input  wire [43:0]                 tcu_rsp_tag,
    input  wire                        tcu_rsp_wb
);

    VX_asic_soc_top #(
        .NUM_CLUSTERS    (NUM_CLUSTERS),
        .SCAN_CHAINS     (SCAN_CHAINS),
        .CDC_ADDRW       (CDC_ADDRW),
        .AXIL_ADDRW      (AXIL_ADDRW),
        .AXIL_DATAW      (AXIL_DATAW),
        .AXI_ADDRW       (AXI_ADDRW),
        .AXI_DATAW       (AXI_DATAW),
        .AXI_IDW         (AXI_IDW),
        .BOOT_SRAM_DEPTH (BOOT_SRAM_DEPTH)
    ) u_dut (
        .clk_core         (clk_core),
        .clk_axi          (clk_axi),
        .rst_n            (rst_n),
        .tck              (tck),
        .trst_n           (trst_n),
        .tms              (tms),
        .tdi              (tdi),
        .tdo              (tdo),
        .tdo_oe_n         (tdo_oe_n),
        .por_n            (por_n),
        .test_mode_pin    (test_mode_pin),
        .scan_enable_pin  (scan_enable_pin),
        .scan_in          (scan_in),
        .scan_out         (scan_out),
        .pwr_clust_en     (pwr_clust_en),
        .pwr_clust_iso_en (pwr_clust_iso_en),
        .pwr_clust_ret_en (pwr_clust_ret_en),
        .dft_scan_enable  (dft_scan_enable),
        .dft_test_mode    (dft_test_mode),
        .dft_cg_override  (dft_cg_override),
        .irq              (irq),
        .s_axil_awvalid   (s_axil_awvalid),
        .s_axil_awready   (s_axil_awready),
        .s_axil_awaddr    (s_axil_awaddr),
        .s_axil_awprot    (s_axil_awprot),
        .s_axil_wvalid    (s_axil_wvalid),
        .s_axil_wready    (s_axil_wready),
        .s_axil_wdata     (s_axil_wdata),
        .s_axil_wstrb     (s_axil_wstrb),
        .s_axil_bvalid    (s_axil_bvalid),
        .s_axil_bready    (s_axil_bready),
        .s_axil_bresp     (s_axil_bresp),
        .s_axil_arvalid   (s_axil_arvalid),
        .s_axil_arready   (s_axil_arready),
        .s_axil_araddr    (s_axil_araddr),
        .s_axil_arprot    (s_axil_arprot),
        .s_axil_rvalid    (s_axil_rvalid),
        .s_axil_rready    (s_axil_rready),
        .s_axil_rdata     (s_axil_rdata),
        .s_axil_rresp     (s_axil_rresp),
        .m_axi_awvalid    (m_axi_awvalid),
        .m_axi_awready    (m_axi_awready),
        .m_axi_awid       (m_axi_awid),
        .m_axi_awaddr     (m_axi_awaddr),
        .m_axi_awlen      (m_axi_awlen),
        .m_axi_awsize     (m_axi_awsize),
        .m_axi_awburst    (m_axi_awburst),
        .m_axi_awlock     (m_axi_awlock),
        .m_axi_awcache    (m_axi_awcache),
        .m_axi_awprot     (m_axi_awprot),
        .m_axi_awqos      (m_axi_awqos),
        .m_axi_wvalid     (m_axi_wvalid),
        .m_axi_wready     (m_axi_wready),
        .m_axi_wdata      (m_axi_wdata),
        .m_axi_wstrb      (m_axi_wstrb),
        .m_axi_wlast      (m_axi_wlast),
        .m_axi_bvalid     (m_axi_bvalid),
        .m_axi_bready     (m_axi_bready),
        .m_axi_bid        (m_axi_bid),
        .m_axi_bresp      (m_axi_bresp),
        .m_axi_arvalid    (m_axi_arvalid),
        .m_axi_arready    (m_axi_arready),
        .m_axi_arid       (m_axi_arid),
        .m_axi_araddr     (m_axi_araddr),
        .m_axi_arlen      (m_axi_arlen),
        .m_axi_arsize     (m_axi_arsize),
        .m_axi_arburst    (m_axi_arburst),
        .m_axi_arlock     (m_axi_arlock),
        .m_axi_arcache    (m_axi_arcache),
        .m_axi_arprot     (m_axi_arprot),
        .m_axi_arqos      (m_axi_arqos),
        .m_axi_rvalid     (m_axi_rvalid),
        .m_axi_rready     (m_axi_rready),
        .m_axi_rid        (m_axi_rid),
        .m_axi_rdata      (m_axi_rdata),
        .m_axi_rresp      (m_axi_rresp),
        .m_axi_rlast      (m_axi_rlast)
    );

    VX_axi4_sva #(
        .ADDRW   (AXIL_ADDRW),
        .DATAW   (AXIL_DATAW),
        .IDW     (1),
        .IS_FULL (0)
    ) u_axil_sva (
        .clk     (clk_axi),
        .rst_n   (u_dut.rst_axi_n),
        .awvalid (s_axil_awvalid),
        .awready (s_axil_awready),
        .awid    (1'b0),
        .awaddr  (s_axil_awaddr),
        .awlen   (8'd0),
        .awsize  (3'd2),
        .awburst (2'b01),
        .awprot  (s_axil_awprot),
        .wvalid  (s_axil_wvalid),
        .wready  (s_axil_wready),
        .wdata   (s_axil_wdata),
        .wstrb   (s_axil_wstrb),
        .wlast   (1'b1),
        .bvalid  (s_axil_bvalid),
        .bready  (s_axil_bready),
        .bid     (1'b0),
        .bresp   (s_axil_bresp),
        .arvalid (s_axil_arvalid),
        .arready (s_axil_arready),
        .arid    (1'b0),
        .araddr  (s_axil_araddr),
        .arlen   (8'd0),
        .arsize  (3'd2),
        .arburst (2'b01),
        .arprot  (s_axil_arprot),
        .rvalid  (s_axil_rvalid),
        .rready  (s_axil_rready),
        .rid     (1'b0),
        .rdata   (s_axil_rdata),
        .rresp   (s_axil_rresp),
        .rlast   (1'b1)
    );

    VX_axi4_sva #(
        .ADDRW   (AXI_ADDRW),
        .DATAW   (AXI_DATAW),
        .IDW     (AXI_IDW),
        .IS_FULL (1)
    ) u_axi_m_sva (
        .clk     (clk_axi),
        .rst_n   (u_dut.rst_axi_n),
        .awvalid (m_axi_awvalid),
        .awready (m_axi_awready),
        .awid    (m_axi_awid),
        .awaddr  (m_axi_awaddr),
        .awlen   (m_axi_awlen),
        .awsize  (m_axi_awsize),
        .awburst (m_axi_awburst),
        .awprot  (m_axi_awprot),
        .wvalid  (m_axi_wvalid),
        .wready  (m_axi_wready),
        .wdata   (m_axi_wdata),
        .wstrb   (m_axi_wstrb),
        .wlast   (m_axi_wlast),
        .bvalid  (m_axi_bvalid),
        .bready  (m_axi_bready),
        .bid     (m_axi_bid),
        .bresp   (m_axi_bresp),
        .arvalid (m_axi_arvalid),
        .arready (m_axi_arready),
        .arid    (m_axi_arid),
        .araddr  (m_axi_araddr),
        .arlen   (m_axi_arlen),
        .arsize  (m_axi_arsize),
        .arburst (m_axi_arburst),
        .arprot  (m_axi_arprot),
        .rvalid  (m_axi_rvalid),
        .rready  (m_axi_rready),
        .rid     (m_axi_rid),
        .rdata   (m_axi_rdata),
        .rresp   (m_axi_rresp),
        .rlast   (m_axi_rlast)
    );

    wire cmd_push_fire = u_dut.wr_commit &&
                         (u_dut.wr_addr[11:10] == 2'b00) &&
                         (u_dut.wr_addr[9:0] == 10'h01C) &&
                         !u_dut.cmd_fifo_full;
    wire cmd_pop_fire  = !u_dut.soft_rst_core_sync2_q &&
                         (u_dut.core_state_q == u_dut.CORE_IDLE) &&
                         !u_dut.cmd_fifo_empty;

    VX_cdc_fifo_sva #(
        .ADDRW (CDC_ADDRW)
    ) u_cmd_cdc_sva (
        .wclk            (clk_axi),
        .wrst_n          (u_dut.rst_axi_n),
        .w_en            (cmd_push_fire),
        .w_full          (u_dut.cmd_fifo_full),
        .wptr_bin        (u_dut.cmd_wptr_bin_q),
        .wptr_gray       (u_dut.cmd_wptr_gray_q),
        .rptr_gray_wsync (u_dut.cmd_rptr_gray_sync2_q),
        .rclk            (clk_core),
        .rrst_n          (u_dut.rst_core_n),
        .r_en            (cmd_pop_fire),
        .r_empty         (u_dut.cmd_fifo_empty),
        .rptr_bin        (u_dut.cmd_rptr_bin_q),
        .rptr_gray       (u_dut.cmd_rptr_gray_q),
        .wptr_gray_rsync (u_dut.cmd_wptr_gray_sync2_q)
    );

    wire rsp_push_fire = !u_dut.soft_rst_core_sync2_q &&
                         (u_dut.core_state_q == u_dut.CORE_FINISH) &&
                         !u_dut.rsp_fifo_full;

    VX_cdc_fifo_sva #(
        .ADDRW (CDC_ADDRW)
    ) u_rsp_cdc_sva (
        .wclk            (clk_core),
        .wrst_n          (u_dut.rst_core_n),
        .w_en            (rsp_push_fire),
        .w_full          (u_dut.rsp_fifo_full),
        .wptr_bin        (u_dut.rsp_wptr_bin_q),
        .wptr_gray       (u_dut.rsp_wptr_gray_q),
        .rptr_gray_wsync (u_dut.rsp_rptr_gray_sync2_q),
        .rclk            (clk_axi),
        .rrst_n          (u_dut.rst_axi_n),
        .r_en            (u_dut.rsp_pop_en),
        .r_empty         (u_dut.rsp_fifo_empty),
        .rptr_bin        (u_dut.rsp_rptr_bin_q),
        .rptr_gray       (u_dut.rsp_rptr_gray_q),
        .wptr_gray_rsync (u_dut.rsp_wptr_gray_sync2_q)
    );

    VX_tcu_handshake_sva #(
        .TAG_W      (44),
        .FIFO_DEPTH (32)
    ) u_tcu_sva (
        .clk       (clk_core),
        .reset     (~u_dut.rst_core_n),
        .req_valid (tcu_req_valid),
        .req_ready (tcu_req_ready),
        .req_tag   (tcu_req_tag),
        .req_wb    (tcu_req_wb),
        .rsp_valid (tcu_rsp_valid),
        .rsp_ready (tcu_rsp_ready),
        .rsp_tag   (tcu_rsp_tag),
        .rsp_wb    (tcu_rsp_wb)
    );

endmodule
EOF

rm -f "${COV_DAT}"

"${VERILATOR}" \
    --cc --exe --build -j 4 \
    --assert --coverage-line --coverage-toggle \
    -Wall -Wpedantic --language 1800-2012 -Wno-SYNCASYNCNET \
    --Mdir "${BUILD_DIR}/obj_dir" \
    -CFLAGS "-std=c++17 -O2 -Wall -Wextra -Werror" \
    --top-module tb_soc_wrap \
    "${REPO_ROOT}/hw/asic/sram/VX_sram_1rw.sv" \
    "${REPO_ROOT}/hw/asic/dft/VX_asic_dft_top.sv" \
    "${REPO_ROOT}/hw/asic/soc/VX_asic_soc_top.sv" \
    "${REPO_ROOT}/hw/dv/sva/VX_axi4_sva.sv" \
    "${REPO_ROOT}/hw/dv/sva/VX_cdc_fifo_sva.sv" \
    "${REPO_ROOT}/hw/dv/sva/VX_tcu_handshake_sva.sv" \
    "${WRAP_SV}" \
    "${REPO_ROOT}/hw/dv/coverage/tb_asic_soc.cpp"

"${BUILD_DIR}/obj_dir/Vtb_soc_wrap" \
    --seed="${SEED}" \
    --ops="${OPS_PER_RATIO}" \
    --cov="${COV_DAT}" > "${SIM_JSON}"

"${VERILATOR_COV}" \
    --annotate "${BUILD_DIR}/annotate" \
    --annotate-all \
    "${COV_DAT}" > "${COV_FULL_LOG}" 2>&1

# Extract RTL-only .dat (VX_asic_soc_top + VX_asic_dft_top + VX_sram_1rw) and run verilator_coverage on it!
DUT_COV_DAT="${BUILD_DIR}/coverage_dut_only.dat"
python3 - "${COV_DAT}" "${DUT_COV_DAT}" << 'PYEOF'
import sys
from pathlib import Path
src, dst = Path(sys.argv[1]), Path(sys.argv[2])
dut_names = ("VX_asic_soc_top.sv", "VX_asic_dft_top.sv", "VX_sram_1rw.sv")
lines = []
for ln in src.read_text(encoding="utf-8").splitlines():
    if ln.startswith("C "):
        if any(name in ln for name in dut_names):
            lines.append(ln)
    else:
        lines.append(ln)
dst.write_text("\n".join(lines) + "\n", encoding="utf-8")
PYEOF

"${VERILATOR_COV}" \
    --annotate "${BUILD_DIR}/annotate_dut" \
    --annotate-all \
    "${DUT_COV_DAT}" > "${COV_DUT_LOG}" 2>&1

python3 - "${SIM_JSON}" "${COV_FULL_LOG}" "${COV_DUT_LOG}" "${COV_DAT}" "${BUILD_DIR}/annotate_dut" "${SUMMARY_JSON}" << 'PYEOF'
from collections import defaultdict
import json
import re
import sys
from pathlib import Path

sim_json, cov_log, cov_dut_log, cov_dat, annotate_dut_dir, out_json = sys.argv[1:7]
sim = json.loads(Path(sim_json).read_text(encoding="utf-8"))

def parse_cov_summary(text):
    res = {}
    for line in text.splitlines():
        m = re.match(r"^\s*(line|toggle|branch)\s*:\s*([0-9.]+)%\s*\(\s*(\d+)\s*/\s*(\d+)\s*\)", line)
        if m:
            kind = m.group(1)
            res[kind] = {
                "pct": float(m.group(2)),
                "covered": int(m.group(3)),
                "total": int(m.group(4)),
            }
    return res

overall = parse_cov_summary(Path(cov_log).read_text(encoding="utf-8"))
dut_only = parse_cov_summary(Path(cov_dut_log).read_text(encoding="utf-8"))

# Compute exact per-file breakdown directly from Verilator coverage.dat records
per_file_raw = defaultdict(lambda: defaultdict(lambda: [0, 0]))
for line in Path(cov_dat).read_text(encoding="utf-8").splitlines():
    if not line.startswith("C "):
        continue
    idx = line.rfind("'")
    if idx < 0:
        continue
    meta = line[3:idx]
    cnt = int(line[idx + 1 :].strip())
    fields = {}
    for part in meta.split("\x01"):
        if "\x02" in part:
            k, v = part.split("\x02", 1)
            fields[k] = v
    fname = Path(fields.get("f", "")).name
    ctype = fields.get("t", "unknown")
    per_file_raw[fname][ctype][1] += 1
    if cnt >= 1:
        per_file_raw[fname][ctype][0] += 1

per_file = {}
for fname, metrics in sorted(per_file_raw.items()):
    entry = {}
    for ctype, (c, t) in sorted(metrics.items()):
        entry[ctype] = {
            "covered": c,
            "total": t,
            "pct": round(100.0 * c / t, 2) if t else 0.0,
        }
    ann_p = Path(annotate_dut_dir) / fname
    if ann_p.exists():
        entry["annotated_file"] = str(ann_p)
    per_file[fname] = entry

report = {
    "simulation": sim,
    "dut_rtl_verilator_coverage": dut_only,
    "full_harness_verilator_coverage": overall,
    "per_file_coverage": per_file,
    "annotate_dir": annotate_dut_dir,
    "coverage_dut_log": cov_dut_log,
    "coverage_full_log": cov_log,
}
Path(out_json).write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
print(json.dumps(report, indent=2))
PYEOF

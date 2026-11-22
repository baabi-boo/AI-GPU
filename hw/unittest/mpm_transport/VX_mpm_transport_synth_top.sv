// Copyright © 2019-2023
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
// http://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS IS" BASIS,
// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
// See the License for the specific language governing permissions and
// limitations under the License.

`include "VX_define.vh"

// Register live requests and independent counter inputs for out-of-context
// timing. VX_dcr_data supplies the registered response boundary; only the
// production DCR response is observable outside this wrapper.
module VX_mpm_transport_synth_top import VX_gpu_pkg::*; (
    input  wire                         clk,
    input  wire                         reset,
    input  wire [CORE_ID_WIDTH-1:0]      core_id,

    input  wire                         dcr_req_valid,
    input  wire                         dcr_req_rw,
    input  wire [VX_DCR_ADDR_WIDTH-1:0] dcr_req_addr,
    input  wire [VX_DCR_DATA_WIDTH-1:0] dcr_req_data,
    output wire                         dcr_rsp_valid,
    output wire [VX_DCR_DATA_WIDTH-1:0] dcr_rsp_data,

`ifdef PERF_ENABLE
    input  wire [PERF_CTR_BITS-1:0]     core_sched_idle,
    input  wire [PERF_CTR_BITS-1:0]     core_active_warps,
    input  wire [PERF_CTR_BITS-1:0]     core_loads,
    input  wire [PERF_CTR_BITS-1:0]     core_stores,
`endif
    input  wire [PERF_CTR_BITS-1:0]     cycles,
    input  wire [PERF_CTR_BITS-1:0]     instret
);
    reg [CORE_ID_WIDTH-1:0]      core_id_r;
    reg                         dcr_req_valid_r;
    reg                         dcr_req_rw_r;
    reg [VX_DCR_ADDR_WIDTH-1:0] dcr_req_addr_r;
    reg [VX_DCR_DATA_WIDTH-1:0] dcr_req_data_r;
    reg [PERF_CTR_BITS-1:0]     cycles_r;
    reg [PERF_CTR_BITS-1:0]     instret_r;

`ifdef PERF_ENABLE
    reg [PERF_CTR_BITS-1:0]     core_sched_idle_r;
    reg [PERF_CTR_BITS-1:0]     core_active_warps_r;
    reg [PERF_CTR_BITS-1:0]     core_loads_r;
    reg [PERF_CTR_BITS-1:0]     core_stores_r;
`endif

    always @(posedge clk) begin
        if (reset) begin
            dcr_req_valid_r <= 1'b0;
        end else begin
            dcr_req_valid_r <= dcr_req_valid;
        end
        core_id_r      <= core_id;
        dcr_req_rw_r   <= dcr_req_rw;
        dcr_req_addr_r <= dcr_req_addr;
        dcr_req_data_r <= dcr_req_data;
        cycles_r      <= cycles;
        instret_r     <= instret;
    `ifdef PERF_ENABLE
        core_sched_idle_r   <= core_sched_idle;
        core_active_warps_r <= core_active_warps;
        core_loads_r        <= core_loads;
        core_stores_r       <= core_stores;
    `endif
    end

    VX_dcr_bus_if dcr_bus_if ();
    VX_dcr_csr_if dcr_csr_if ();
    VX_dcr_flush_if dcr_flush_if ();

    assign dcr_bus_if.req_valid = dcr_req_valid_r;
    assign dcr_bus_if.req_data.rw = dcr_req_rw_r;
    assign dcr_bus_if.req_data.addr = dcr_req_addr_r;
    assign dcr_bus_if.req_data.data = dcr_req_data_r;
    assign dcr_rsp_valid = dcr_bus_if.rsp_valid;
    assign dcr_rsp_data = dcr_bus_if.rsp_data.data;

    // This leaf measures MPM reads, without a cache flush completion source.
    assign dcr_flush_if.done = 1'b0;
    `UNUSED_VAR (dcr_flush_if.req)

`ifdef PERF_ENABLE
    pipeline_perf_t pipeline_perf;
    sysmem_perf_t sysmem_perf;

    // Keep the native base/CORE matrix live; other classes are outside this
    // synthesis slice and retain zero-valued performance inputs.
    always @(*) begin
        pipeline_perf = '0;
        pipeline_perf.sched.idles = core_sched_idle_r;
        pipeline_perf.sched.active_warps = core_active_warps_r;
        pipeline_perf.loads = core_loads_r;
        pipeline_perf.stores = core_stores_r;
        sysmem_perf = '0;
    end
`endif

    VX_dcr_data #(
        .INSTANCE_ID ("mpm_transport_synth")
    ) dcr_data (
        .clk          (clk),
        .reset        (reset),
        .core_id      (core_id_r),
        .dcr_bus_if   (dcr_bus_if),
        .dcr_csr_if   (dcr_csr_if),
        .dcr_flush_if (dcr_flush_if),
        `UNUSED_PIN (flush_l1_only)
    );

    VX_csr_mpm #(
        .INSTANCE_ID ("mpm_transport_synth")
    ) csr_mpm (
    `ifdef PERF_ENABLE
        .sysmem_perf   (sysmem_perf),
        .pipeline_perf (pipeline_perf),
    `endif
        .cycles        (cycles_r),
        .instret       (instret_r),
        .dcr_csr_if    (dcr_csr_if)
    );
endmodule

// Copyright © 2019-2023
// Licensed under the Apache License, Version 2.0.

`include "VX_define.vh"

// Expose the production host read path and independent counter inputs.
module VX_mpm_transport_top import VX_gpu_pkg::*; (
    input  wire                         clk,
    input  wire                         reset,
    input  wire [CORE_ID_WIDTH-1:0]      core_id,

    input  wire                         dcr_req_valid,
    input  wire                         dcr_req_rw,
    input  wire [VX_DCR_ADDR_WIDTH-1:0] dcr_req_addr,
    input  wire [VX_DCR_DATA_WIDTH-1:0] dcr_req_data,
    output wire                         dcr_rsp_valid,
    output wire [VX_DCR_DATA_WIDTH-1:0] dcr_rsp_data,

    output wire                         csr_valid,
    output wire                         csr_ready,
    output wire [`VX_CSR_ADDR_BITS-1:0] csr_addr,
    output wire [7:0]                   csr_class,

`ifdef PERF_ENABLE
    input  wire [PERF_CTR_BITS-1:0]     core_sched_idle,
    input  wire [PERF_CTR_BITS-1:0]     core_active_warps,
    input  wire [PERF_CTR_BITS-1:0]     core_loads,
    input  wire [PERF_CTR_BITS-1:0]     core_stores,
    input  wire [PERF_CTR_BITS-1:0]     icache_reads,
    input  wire [PERF_CTR_BITS-1:0]     icache_read_misses,
    input  wire [PERF_CTR_BITS-1:0]     icache_mshr_stalls,
    input  wire [PERF_CTR_BITS-1:0]     dcache_reads,
    input  wire [PERF_CTR_BITS-1:0]     dcache_writes,
    input  wire [PERF_CTR_BITS-1:0]     dcache_mshr_stalls,
    input  wire [PERF_CTR_BITS-1:0]     l2cache_reads,
    input  wire [PERF_CTR_BITS-1:0]     l2cache_writes,
    input  wire [PERF_CTR_BITS-1:0]     l2cache_mshr_stalls,
    input  wire [PERF_CTR_BITS-1:0]     l3cache_reads,
    input  wire [PERF_CTR_BITS-1:0]     l3cache_writes,
    input  wire [PERF_CTR_BITS-1:0]     l3cache_mshr_stalls,
    input  wire [PERF_CTR_BITS-1:0]     mem_reads,
    input  wire [PERF_CTR_BITS-1:0]     mem_writes,
    input  wire [PERF_CTR_BITS-1:0]     mem_latency,
    input  wire [PERF_CTR_BITS-1:0]     lmem_reads,
    input  wire [PERF_CTR_BITS-1:0]     lmem_writes,
    input  wire [PERF_CTR_BITS-1:0]     lmem_bank_stalls,
    input  wire [PERF_CTR_BITS-1:0]     coalescer_misses,
`ifdef VX_CFG_EXT_TCU_ENABLE
    input  wire [PERF_CTR_BITS-1:0]     tcu_tbuf_stalls,
    input  wire [PERF_CTR_BITS-1:0]     tcu_tbuf_cache_hits,
    input  wire [PERF_CTR_BITS-1:0]     tcu_lmem_reads,
`endif
`endif
    input  wire [PERF_CTR_BITS-1:0]     cycles,
    input  wire [PERF_CTR_BITS-1:0]     instret
);
    VX_dcr_bus_if dcr_bus_if ();
    VX_dcr_csr_if dcr_csr_if ();
    VX_dcr_flush_if dcr_flush_if ();

    assign dcr_bus_if.req_valid = dcr_req_valid;
    assign dcr_bus_if.req_data.rw = dcr_req_rw;
    assign dcr_bus_if.req_data.addr = dcr_req_addr;
    assign dcr_bus_if.req_data.data = dcr_req_data;
    assign dcr_rsp_valid = dcr_bus_if.rsp_valid;
    assign dcr_rsp_data = dcr_bus_if.rsp_data.data;

    assign csr_valid = dcr_csr_if.valid;
    assign csr_ready = dcr_csr_if.ready;
    assign csr_addr = dcr_csr_if.addr;
    assign csr_class = dcr_csr_if.mpm_class;

    assign dcr_flush_if.done = 1'b0;
    `UNUSED_VAR (dcr_flush_if.req)

`ifdef PERF_ENABLE
    pipeline_perf_t pipeline_perf;
    sysmem_perf_t sysmem_perf;

    always @(*) begin
        pipeline_perf = '0;
        pipeline_perf.sched.idles = core_sched_idle;
        pipeline_perf.sched.active_warps = core_active_warps;
        pipeline_perf.loads = core_loads;
        pipeline_perf.stores = core_stores;
    `ifdef VX_CFG_EXT_TCU_ENABLE
        pipeline_perf.tcu.tbuf_stalls = tcu_tbuf_stalls;
        pipeline_perf.tcu.tbuf_cache_hits = tcu_tbuf_cache_hits;
        pipeline_perf.tcu.lmem_reads = tcu_lmem_reads;
    `endif

        sysmem_perf = '0;
        sysmem_perf.icache.reads = icache_reads;
        sysmem_perf.icache.read_misses = icache_read_misses;
        sysmem_perf.icache.mshr_stalls = icache_mshr_stalls;
        sysmem_perf.dcache.reads = dcache_reads;
        sysmem_perf.dcache.writes = dcache_writes;
        sysmem_perf.dcache.mshr_stalls = dcache_mshr_stalls;
        sysmem_perf.l2cache.reads = l2cache_reads;
        sysmem_perf.l2cache.writes = l2cache_writes;
        sysmem_perf.l2cache.mshr_stalls = l2cache_mshr_stalls;
        sysmem_perf.l3cache.reads = l3cache_reads;
        sysmem_perf.l3cache.writes = l3cache_writes;
        sysmem_perf.l3cache.mshr_stalls = l3cache_mshr_stalls;
        sysmem_perf.mem.reads = mem_reads;
        sysmem_perf.mem.writes = mem_writes;
        sysmem_perf.mem.latency = mem_latency;
        sysmem_perf.lmem.reads = lmem_reads;
        sysmem_perf.lmem.writes = lmem_writes;
        sysmem_perf.lmem.bank_stalls = lmem_bank_stalls;
        sysmem_perf.coalescer.misses = coalescer_misses;
    end
`endif

    VX_dcr_data #(
        .INSTANCE_ID ("mpm_transport")
    ) dcr_data (
        .clk          (clk),
        .reset        (reset),
        .core_id      (core_id),
        .dcr_bus_if   (dcr_bus_if),
        .dcr_csr_if   (dcr_csr_if),
        .dcr_flush_if (dcr_flush_if),
        `UNUSED_PIN (flush_l1_only)
    );

    VX_csr_mpm #(
        .INSTANCE_ID ("mpm_transport")
    ) csr_mpm (
    `ifdef PERF_ENABLE
        .sysmem_perf   (sysmem_perf),
        .pipeline_perf (pipeline_perf),
    `endif
        .cycles        (cycles),
        .instret       (instret),
        .dcr_csr_if    (dcr_csr_if)
    );
endmodule

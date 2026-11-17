// SPDX-License-Identifier: Apache-2.0
`include "VX_define.vh"

module VX_tcu_wgmma_top import VX_gpu_pkg::*, VX_tcu_pkg::*; (
    input  wire                           clk,
    input  wire                           reset,
    input  wire [3:0]                     dispatch_valid,
    output wire [3:0]                     dispatch_ready,
    input  wire [63:0]                    dispatch_uuid [4],
    input  wire [ISSUE_WIS_W-1:0]         dispatch_wis [4],
    input  wire [NCTA_WIDTH-1:0]          dispatch_cta [4],
    input  wire [SIMD_IDX_W-1:0]          dispatch_sid [4],
    input  wire [7:0]                     dispatch_tmask [4],
    input  wire [63:0]                    dispatch_pc [4],
    input  wire [3:0]                     dispatch_wb,
    input  wire [NUM_XREGS-1:0]           dispatch_wr_xregs [4],
    input  wire [NUM_REGS_BITS-1:0]       dispatch_rd [4],
    input  wire [BYTESEL_BITS-1:0]        dispatch_bytesel [4],
    input  wire [INST_OP_BITS-1:0]        dispatch_op [4],
    input  wire [4:0]                     dispatch_fmt_s [4],
    input  wire [4:0]                     dispatch_fmt_d [4],
    input  wire [3:0]                     dispatch_m [4],
    input  wire [3:0]                     dispatch_n [4],
    input  wire [3:0]                     dispatch_k [4],
    input  wire [1:0]                     dispatch_cd_nregs [4],
    input  wire [3:0]                     dispatch_a_smem,
    input  wire [3:0]                     dispatch_first,
    input  wire [3:0]                     dispatch_last,
    input  wire [63:0]                    dispatch_rs1 [4][8],
    input  wire [63:0]                    dispatch_rs2 [4][8],
    input  wire [63:0]                    dispatch_rs3 [4][8],
    input  wire [3:0]                     dispatch_sop,
    input  wire [3:0]                     dispatch_eop,
    output wire [3:0]                     commit_valid,
    input  wire [3:0]                     commit_ready,
    output wire [63:0]                    commit_uuid [4],
    output wire [NW_WIDTH-1:0]            commit_wid [4],
    output wire [NCTA_WIDTH-1:0]          commit_cta [4],
    output wire [SIMD_IDX_W-1:0]          commit_sid [4],
    output wire [7:0]                     commit_tmask [4],
    output wire [63:0]                    commit_pc [4],
    output wire [3:0]                     commit_wb,
    output wire [NUM_XREGS-1:0]           commit_wr_xregs [4],
    output wire [NUM_REGS_BITS-1:0]       commit_rd [4],
    output wire [BYTESEL_BITS-1:0]        commit_bytesel [4],
    output wire [63:0]                    commit_data [4][8],
    output wire [3:0]                     commit_sop,
    output wire [3:0]                     commit_eop,
    output wire                           lmem_req_valid,
    input  wire                           lmem_req_ready,
    output wire [LMEM_DMA_ADDR_WIDTH-1:0] lmem_req_addr,
    output wire [63:0]                    lmem_req_tag,
    output wire [LMEM_DMA_ATTR_W-1:0]     lmem_req_attr,
    output wire                           lmem_req_rw,
    input  wire                           lmem_rsp_valid,
    output wire                           lmem_rsp_ready,
    input  wire [63:0]                    lmem_rsp_data [8],
    input  wire [63:0]                    lmem_rsp_tag,
    output wire                           meta_req_valid,
    input  wire                           meta_req_ready,
    output wire                           meta_req_rw,
    output wire [7:0]                     meta_req_mask,
    output wire [7:0]                     meta_req_byteen [8],
    output wire [63:0]                    meta_req_addr [8],
    output wire [MEM_ATTR_WIDTH-1:0]      meta_req_attr [8],
    output wire [31:0]                    meta_req_tag [8],
    input  wire                           meta_rsp_valid,
    output wire                           meta_rsp_ready,
    input  wire [7:0]                     meta_rsp_mask,
    input  wire [63:0]                    meta_rsp_data [8],
    input  wire [31:0]                    meta_rsp_tag [8],
    input  wire                           meta_rsp_sop,
    input  wire                           meta_rsp_eop,
    output wire [3:0]                     observe_exec_valid,
    output wire [3:0]                     observe_exec_ready,
    output wire [3:0]                     observe_tbuf_ready,
    output wire [3:0]                     observe_result_valid,
    output wire [3:0]                     observe_result_ready,
    output wire [3:0]                     observe_result_wb,
    output wire [3:0]                     observe_admission_blocked,
    output wire [3:0]                     observe_first,
    output wire [3:0]                     observe_last,
    output wire [NCTA_WIDTH-1:0]          observe_cta [4],
    output wire [3:0]                     observe_conflict,
    output wire [3:0]                     observe_resident,
    output wire [NCTA_WIDTH-1:0]          observe_owner [4],
    output wire [3:0]                     observe_meta_write,
    output wire [NW_WIDTH-1:0]            observe_meta_wid [4],
    output wire [4:0]                     observe_meta_idx [4],
    output wire [7:0]                     observe_meta_mask [4],
    output wire [31:0]                    observe_meta_data [4][8]
);
    `STATIC_ASSERT (`VX_CFG_XLEN == 64 && `VX_CFG_NUM_THREADS == 8 && `VX_CFG_NUM_WARPS == 8,
                    ("tcu_wgmma requires RV64/T8/W8"))
    `STATIC_ASSERT (`VX_CFG_ISSUE_WIDTH == 4 && `VX_CFG_NUM_TCU_BLOCKS == 4 && `VX_CFG_NUM_LSU_BLOCKS == 1,
                    ("tcu_wgmma requires four TCU slots and one metadata LSU client"))
    `STATIC_ASSERT (`VX_CFG_NUM_LSU_LANES == 8 && `VX_CFG_LMEM_NUM_BANKS == 8 && TCU_BLOCK_CAP == 8,
                    ("tcu_wgmma requires eight lanes and banks"))
    `STATIC_ASSERT (TCU_LMEM_TAG_W <= 64 && LSU_CLIENT_TAG_WIDTH <= 256,
                    ("test tag transport must preserve every bit"))

    VX_dispatch_if dispatch_if[4]();
    VX_commit_if commit_if[4]();
    VX_lsu_sched_if tcu_mem_if[1]();
    VX_mem_bus_if #(
        .DATA_SIZE  (LMEM_DMA_DATA_SIZE),
        .ADDR_WIDTH (LMEM_DMA_ADDR_WIDTH),
        .TAG_WIDTH  (TCU_LMEM_TAG_W),
        .ATTR_WIDTH (LMEM_DMA_ATTR_W)
    ) tcu_lmem_if();

    assign lmem_req_valid = tcu_lmem_if.req_valid;
    assign tcu_lmem_if.req_ready = lmem_req_ready;
    assign lmem_req_addr = tcu_lmem_if.req_data.addr;
    assign lmem_req_tag = 64'(tcu_lmem_if.req_data.tag);
    assign lmem_req_attr = tcu_lmem_if.req_data.attr;
    assign lmem_req_rw = tcu_lmem_if.req_data.rw;
    assign tcu_lmem_if.rsp_valid = lmem_rsp_valid;
    assign lmem_rsp_ready = tcu_lmem_if.rsp_ready;
    assign tcu_lmem_if.rsp_data.tag = TCU_LMEM_TAG_W'(lmem_rsp_tag);
    `UNUSED_VAR (tcu_lmem_if.req_data.byteen)
    `UNUSED_VAR (tcu_lmem_if.req_data.data)
    `UNUSED_VAR (lmem_rsp_tag[63:TCU_LMEM_TAG_W])

    wire [255:0] meta_req_tag_padded = 256'(tcu_mem_if[0].req_data.tag);
    wire [255:0] meta_rsp_tag_padded;
    assign meta_req_valid = tcu_mem_if[0].req_valid;
    assign tcu_mem_if[0].req_ready = meta_req_ready;
    assign meta_req_rw = tcu_mem_if[0].req_data.rw;
    assign meta_req_mask = tcu_mem_if[0].req_data.mask;
    assign tcu_mem_if[0].rsp_valid = meta_rsp_valid;
    assign meta_rsp_ready = tcu_mem_if[0].rsp_ready;
    assign tcu_mem_if[0].rsp_data.mask = meta_rsp_mask;
    assign tcu_mem_if[0].rsp_data.tag = LSU_CLIENT_TAG_WIDTH'(meta_rsp_tag_padded);
    assign tcu_mem_if[0].rsp_data.sop = meta_rsp_sop;
    assign tcu_mem_if[0].rsp_data.eop = meta_rsp_eop;
    `UNUSED_VAR (tcu_mem_if[0].req_data.data)
    `UNUSED_VAR (meta_rsp_tag_padded[255:LSU_CLIENT_TAG_WIDTH])
    for (genvar i = 0; i < 8; ++i) begin : g_memory_lanes
        assign tcu_lmem_if.rsp_data.data[64*i +: 64] = lmem_rsp_data[i];
        assign meta_req_byteen[i] = tcu_mem_if[0].req_data.byteen[i];
        assign meta_req_addr[i] = 64'(tcu_mem_if[0].req_data.addr[i]);
        assign meta_req_attr[i] = tcu_mem_if[0].req_data.attr[i];
        assign meta_req_tag[i] = meta_req_tag_padded[32*i +: 32];
        assign meta_rsp_tag_padded[32*i +: 32] = meta_rsp_tag[i];
        assign tcu_mem_if[0].rsp_data.data[i] = meta_rsp_data[i];
    end

    wire [3:0] exec_valid, exec_ready, tbuf_ready;
    tcu_execute_t exec_data[4];
    wire [3:0][TCU_WG_A_DATA_SIZE-1:0][63:0] tbuf_rs1_data;
    wire [3:0][TCU_WG_RS2_WIDTH-1:0][63:0] tbuf_rs2_data;
    for (genvar b = 0; b < 4; ++b) begin : g_slots
        assign dispatch_if[b].valid = dispatch_valid[b];
        assign dispatch_ready[b] = dispatch_if[b].ready;
        always_comb begin
            dispatch_if[b].data = '0;
            dispatch_if[b].data.uuid = UUID_WIDTH'(dispatch_uuid[b]);
            dispatch_if[b].data.wis = dispatch_wis[b];
            dispatch_if[b].data.cta_id = dispatch_cta[b];
            dispatch_if[b].data.sid = dispatch_sid[b];
            dispatch_if[b].data.tmask = dispatch_tmask[b];
            dispatch_if[b].data.PC = PC_BITS'(dispatch_pc[b]);
            dispatch_if[b].data.wb = dispatch_wb[b];
            dispatch_if[b].data.wr_xregs = dispatch_wr_xregs[b];
            dispatch_if[b].data.rd = dispatch_rd[b];
            dispatch_if[b].data.bytesel = dispatch_bytesel[b];
            dispatch_if[b].data.op_type = dispatch_op[b];
            dispatch_if[b].data.op_args.tcu.fmt_s = dispatch_fmt_s[b];
            dispatch_if[b].data.op_args.tcu.fmt_d = dispatch_fmt_d[b];
            dispatch_if[b].data.op_args.tcu.step_m = dispatch_m[b];
            dispatch_if[b].data.op_args.tcu.step_n = dispatch_n[b];
            dispatch_if[b].data.op_args.tcu.step_k = dispatch_k[b];
            dispatch_if[b].data.op_args.tcu.a_from_smem = dispatch_a_smem[b];
            dispatch_if[b].data.op_args.tcu.cd_nregs = dispatch_cd_nregs[b];
            dispatch_if[b].data.op_args.tcu.is_first_uop = dispatch_first[b];
            dispatch_if[b].data.op_args.tcu.is_last_uop = dispatch_last[b];
            for (int i = 0; i < 8; ++i) begin
                dispatch_if[b].data.rs1_data[i] = dispatch_rs1[b][i];
                dispatch_if[b].data.rs2_data[i] = dispatch_rs2[b][i];
                dispatch_if[b].data.rs3_data[i] = dispatch_rs3[b][i];
            end
            dispatch_if[b].data.sop = dispatch_sop[b];
            dispatch_if[b].data.eop = dispatch_eop[b];
        end
        `UNUSED_VAR (dispatch_uuid[b][63:UUID_WIDTH])
        if (PC_BITS < 64) begin : g_pc_unused
            `UNUSED_VAR (dispatch_pc[b][63:PC_BITS])
        end
        assign commit_valid[b] = commit_if[b].valid;
        assign commit_if[b].ready = commit_ready[b];
        assign commit_uuid[b] = 64'(commit_if[b].data.uuid);
        assign commit_wid[b] = commit_if[b].data.wid;
        assign commit_cta[b] = commit_if[b].data.cta_id;
        assign commit_sid[b] = commit_if[b].data.sid;
        assign commit_tmask[b] = commit_if[b].data.tmask;
        assign commit_pc[b] = 64'(commit_if[b].data.PC);
        assign commit_wb[b] = commit_if[b].data.wb;
        assign commit_wr_xregs[b] = commit_if[b].data.wr_xregs;
        assign commit_rd[b] = commit_if[b].data.rd;
        assign commit_bytesel[b] = commit_if[b].data.bytesel;
        assign commit_sop[b] = commit_if[b].data.sop;
        assign commit_eop[b] = commit_if[b].data.eop;
        for (genvar i = 0; i < 8; ++i) begin : g_commit_lanes
            assign commit_data[b][i] = commit_if[b].data.data[i];
            assign observe_meta_data[b][i] = tcu_unit.g_blocks[b].tcu_block.meta_wr_data[i];
        end
        assign observe_first[b] = exec_data[b].op_args.tcu.is_first_uop;
        assign observe_last[b] = exec_data[b].op_args.tcu.is_last_uop;
        assign observe_cta[b] = exec_data[b].header.cta_id;
        assign observe_owner[b] = tcu_shared.wgmma.lockstep.cta_owner_r[b];
        assign observe_meta_write[b] = tcu_unit.g_blocks[b].tcu_block.meta_wr_en;
        assign observe_meta_wid[b] = tcu_unit.g_blocks[b].tcu_block.meta_wr_wid;
        assign observe_meta_idx[b] = tcu_unit.g_blocks[b].tcu_block.meta_wr_idx;
        assign observe_meta_mask[b] = tcu_unit.g_blocks[b].tcu_block.meta_wr_mask;
        assign observe_result_valid[b] = tcu_unit.g_blocks[b].tcu_block.core_result_if.valid;
        assign observe_result_ready[b] = tcu_unit.g_blocks[b].tcu_block.core_result_if.ready;
        assign observe_result_wb[b] = tcu_unit.g_blocks[b].tcu_block.core_result_if.data.header.wb;
        assign observe_admission_blocked[b] = tcu_unit.g_blocks[b].tcu_block.tcu_core.mdata_queue_full
            || tcu_unit.g_blocks[b].tcu_block.tcu_core.landq_credits_full
            || (tcu_unit.g_blocks[b].tcu_block.tcu_core.fedp_done
                && !tcu_unit.g_blocks[b].tcu_block.core_result_if.ready);
    end
    assign observe_exec_valid = exec_valid;
    assign observe_exec_ready = exec_ready;
    assign observe_tbuf_ready = tbuf_ready;
    assign observe_conflict = tcu_shared.wgmma.cta_conflict;
    assign observe_resident = tcu_shared.wgmma.lockstep.in_expansion_r;

    VX_tcu_unit #(
        .INSTANCE_ID ("tcu_wgmma")
    ) tcu_unit (
        `SCOPE_IO_BIND (0)
        .clk           (clk),
        .reset         (reset),
        .exec_valid    (exec_valid),
        .exec_ready    (exec_ready),
        .exec_data     (exec_data),
        .tbuf_rs1_data (tbuf_rs1_data),
        .tbuf_rs2_data (tbuf_rs2_data),
        .tbuf_ready    (tbuf_ready),
        .tcu_mem_if    (tcu_mem_if),
        .dispatch_if   (dispatch_if),
        .commit_if     (commit_if)
    );
    VX_tcu_shared #(
        .INSTANCE_ID ("tcu_wgmma"),
        .BLOCK_SIZE  (4)
    ) tcu_shared (
        .clk            (clk),
        .reset          (reset),
        .exec_valid     (exec_valid),
        .exec_ready     (exec_ready),
        .exec_data      (exec_data),
        .tbuf_rs1_data  (tbuf_rs1_data),
        .tbuf_rs2_data  (tbuf_rs2_data),
        .tbuf_ready_eff (tbuf_ready),
        .tcu_lmem_if    (tcu_lmem_if)
    );
endmodule

// Copyright © 2026
// SPDX-License-Identifier: Apache-2.0

`include "VX_define.vh"

`ifdef P02_WGMMA_WITNESS

// This test-only bind has no outputs and observes the unmodified issue path.
module VX_p02_wgmma_scoreboard_monitor import VX_gpu_pkg::*; #(
    parameter `STRING INSTANCE_ID = ""
) (
    input  wire                             clk,
    input  wire                             reset,
    input  wire [1:0]                       staging_valid,
    input  wire [1:0]                       staging_ready,
    input  wire [1:0][$bits(ibuffer_t)-1:0] staging_data,
    input  wire [1:0][NUM_XREGS-1:0]        inuse_xregs,
    input  wire [1:0][NUM_XREGS-1:0]        wb_inuse_xregs,
    input  wire                             writeback_valid,
    input  wire [$bits(writeback_t)-1:0]    writeback_data
);
    `UNUSED_VAR ({inuse_xregs, wb_inuse_xregs})
    `STATIC_ASSERT(PER_ISSUE_WARPS == 2, ("P02 witness requires two local warps per issue slot"))
    `STATIC_ASSERT(`VX_CFG_XLEN == 64 && `VX_CFG_NUM_THREADS == 8
        && `VX_CFG_NUM_WARPS == 8 && `VX_CFG_ISSUE_WIDTH == 4,
        ("P02 witness requires the frozen RV64/T8/W8/IW4 profile"))

`ifdef VX_CFG_EXT_TCU_ENABLE
`ifdef VX_CFG_TCU_WGMMA_ENABLE
`ifdef VX_CFG_TCU_SPARSE_ENABLE
    localparam MAX_TRANSACTIONS = 1024;
    localparam logic [63:0] MAX_TRANSACTION_CYCLES = 64'd1048576;

    wire writeback_t writeback = writeback_t'(writeback_data);
    `UNUSED_VAR (writeback)

    reg [63:0] cycle;
    reg [31:0] epoch;
    reg reset_seen;
    initial begin
        epoch = '0;
        reset_seen = 1'b0;
    end
    always @(posedge clk) begin
        reset_seen <= reset;
        if (reset) begin
            cycle <= '0;
            if (!reset_seen) begin
                epoch <= epoch + 32'd1;
            end
        end else begin
            cycle <= cycle + 64'd1;
        end
    end

    for (genvar w = 0; w < 2; ++w) begin : g_warp
        wire ibuffer_t staged = ibuffer_t'(staging_data[w]);
        `UNUSED_VAR (staged)
        wire staging_fire = staging_valid[w] && staging_ready[w];
        wire metadata_reserve = staging_fire && staged.ex_type == EX_TCU
            && staged.op_type == INST_TCU_LD && staged.wr_xregs[XREG_0];
        wire sparse_present = staging_valid[w] && staged.ex_type == EX_TCU
            && staged.op_type == INST_TCU_WGMMA_SP && staged.rd_xregs[XREG_0];
        wire first_sparse = sparse_present && staged.op_args.tcu.is_first_uop;
        wire xreg_release = writeback_valid && writeback.eop_wis[w]
            && writeback.wr_xregs[XREG_0];

        reg token_valid;
        reg load_pending;
        reg wait_seen;
        reg [31:0] load_sequence;
        reg [63:0] load_cycle;
        reg [63:0] wait_cycles;
        reg [PC_BITS-1:0] load_pc;
        reg [UUID_WIDTH-1:0] load_uuid;
        reg [NCTA_WIDTH-1:0] load_cta;
        reg [NW_WIDTH-1:0] load_wid;
        reg [PC_BITS-1:0] dependent_pc;
        reg [UUID_WIDTH-1:0] dependent_uuid;
        reg [NCTA_WIDTH-1:0] dependent_cta;

        // Emit transitions as they occur; finalization is not required.
        task automatic emit_record(
            input string kind,
            input logic [31:0] seq,
            input logic [PC_BITS-1:0] meta_pc,
            input logic [UUID_WIDTH-1:0] meta_uuid,
            input logic [NCTA_WIDTH-1:0] meta_cta,
            input logic [NW_WIDTH-1:0] wid,
            input logic [PC_BITS-1:0] pc,
            input logic [UUID_WIDTH-1:0] uuid,
            input logic [NCTA_WIDTH-1:0] cta,
            input logic [63:0] waits
        );
            $display("P02_WGMMA_META {\"event\":\"%s\",\"instance\":\"%s\",\"wis\":%0d,\"epoch\":%0d,\"sequence\":%0d,\"cycle\":%0d,\"load_pc\":\"0x%0h\",\"load_uuid\":\"0x%0h\",\"load_cta\":%0d,\"wid\":%0d,\"pc\":\"0x%0h\",\"uuid\":\"0x%0h\",\"cta\":%0d,\"wait_cycles\":%0d}",
                kind, INSTANCE_ID, w, epoch, seq, cycle, to_fullPC(meta_pc), meta_uuid,
                meta_cta, wid, to_fullPC(pc), uuid, cta, waits);
        endtask

        always @(posedge clk) begin
            if (reset) begin
                token_valid <= 1'b0;
                load_pending <= 1'b0;
                wait_seen <= 1'b0;
                load_sequence <= '0;
                load_cycle <= '0;
                wait_cycles <= '0;
                load_pc <= '0;
                load_uuid <= '0;
                load_cta <= '0;
                load_wid <= '0;
                dependent_pc <= '0;
                dependent_uuid <= '0;
                dependent_cta <= '0;
            end else begin
                // A same-cycle metadata completion clears wb_inuse_xregs and
                // may legally permit issue while the registered bit is set.
                if (sparse_present && staging_fire) begin
                    assert (!wb_inuse_xregs[w][XREG_0]) else begin
                        $fatal(1, "P02 WGMMA issued with metadata busy: %s wis=%0d", INSTANCE_ID, w);
                    end
                end

                if (token_valid) begin
                    assert ((cycle - load_cycle) < MAX_TRANSACTION_CYCLES) else begin
                        $fatal(1, "P02 metadata transaction timed out: %s wis=%0d", INSTANCE_ID, w);
                    end
                end

                if (wait_seen && token_valid) begin
                    assert (first_sparse && staged.PC == dependent_pc
                        && staged.uuid == dependent_uuid && staged.cta_id == dependent_cta
                        && staged.wid == load_wid) else begin
                        $fatal(1, "P02 waiting instruction changed: %s wis=%0d", INSTANCE_ID, w);
                    end
                end

                if (metadata_reserve) begin
                    assert (!token_valid && !wb_inuse_xregs[w][XREG_0]) else begin
                        $fatal(1, "P02 metadata reservation overlaps a transaction: %s wis=%0d", INSTANCE_ID, w);
                    end
                    assert (load_sequence < MAX_TRANSACTIONS) else begin
                        $fatal(1, "P02 metadata witness record budget exceeded: %s wis=%0d", INSTANCE_ID, w);
                    end
                    token_valid <= 1'b1;
                    load_pending <= 1'b1;
                    wait_seen <= 1'b0;
                    load_sequence <= load_sequence + 32'd1;
                    load_cycle <= cycle;
                    wait_cycles <= '0;
                    load_pc <= staged.PC;
                    load_uuid <= staged.uuid;
                    load_cta <= staged.cta_id;
                    load_wid <= staged.wid;
                    emit_record("reserve", load_sequence + 32'd1, staged.PC,
                        staged.uuid, staged.cta_id, staged.wid, staged.PC,
                        staged.uuid, staged.cta_id, 64'd0);
                end

                if (first_sparse && wb_inuse_xregs[w][XREG_0] && load_pending) begin
                    assert (token_valid && staged.cta_id == load_cta && staged.wid == load_wid) else begin
                        $fatal(1, "P02 metadata waiter has different ownership: %s wis=%0d", INSTANCE_ID, w);
                    end
                    assert (!staging_ready[w] && inuse_xregs[w][XREG_0]) else begin
                        $fatal(1, "P02 metadata wait did not block issue: %s wis=%0d", INSTANCE_ID, w);
                    end
                    wait_cycles <= wait_cycles + 64'd1;
                    if (!wait_seen) begin
                        wait_seen <= 1'b1;
                        dependent_pc <= staged.PC;
                        dependent_uuid <= staged.uuid;
                        dependent_cta <= staged.cta_id;
                        emit_record("wait", load_sequence, load_pc, load_uuid,
                            load_cta, load_wid, staged.PC, staged.uuid, staged.cta_id, 64'd1);
                    end
                end

                if (xreg_release && load_pending) begin
                    assert (token_valid && inuse_xregs[w][XREG_0]
                        && writeback.PC == load_pc && writeback.uuid == load_uuid
                        && writeback.cta_id == load_cta) else begin
                        $fatal(1, "P02 metadata completion identity mismatch: %s wis=%0d", INSTANCE_ID, w);
                    end
                    load_pending <= 1'b0;
                    emit_record("release", load_sequence, load_pc, load_uuid,
                        load_cta, load_wid, writeback.PC, writeback.uuid,
                        writeback.cta_id, wait_cycles);
                end

                if (first_sparse && staging_fire) begin
                    assert (token_valid && (!load_pending || xreg_release)
                        && staged.cta_id == load_cta && staged.wid == load_wid) else begin
                        $fatal(1, "P02 sparse WGMMA lacks a completed metadata load: %s wis=%0d", INSTANCE_ID, w);
                    end
                    token_valid <= 1'b0;
                    emit_record("issue", load_sequence, load_pc, load_uuid,
                        load_cta, load_wid, staged.PC, staged.uuid, staged.cta_id, wait_cycles);
                end
            end
        end
    end
`else
    initial $fatal(1, "P02 witness requires sparse tensor support");
`endif
`else
    initial $fatal(1, "P02 witness requires WGMMA support");
`endif
`else
    initial $fatal(1, "P02 witness requires tensor support");
`endif
endmodule

bind VX_scoreboard VX_p02_wgmma_scoreboard_monitor #(
    .INSTANCE_ID (INSTANCE_ID)
) p02_wgmma_monitor (
    .clk             (clk),
    .reset           (reset),
    .staging_valid   ({staging_if[1].valid, staging_if[0].valid}),
    .staging_ready   ({staging_if[1].ready, staging_if[0].ready}),
    .staging_data    ({staging_if[1].data, staging_if[0].data}),
    .inuse_xregs     ({g_scoreboard[1].inuse_xregs, g_scoreboard[0].inuse_xregs}),
    .wb_inuse_xregs  ({g_scoreboard[1].wb_inuse_xregs, g_scoreboard[0].wb_inuse_xregs}),
    .writeback_valid (writeback_if.valid),
    .writeback_data  (writeback_if.data)
);

`endif

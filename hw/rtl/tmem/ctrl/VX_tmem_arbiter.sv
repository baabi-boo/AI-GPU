// SPDX-License-Identifier: Apache-2.0
`include "VX_platform.vh"

module VX_tmem_arbiter
    import VX_tmem_pkg::*;
#(
    parameter int LANES            = 8,
    parameter int NUM_BANKS        = TMEM_NUM_BANKS,
    parameter int AGE_THRESHOLD    = 8,
    parameter int DEFICIT_MAX      = 16
) (
    input  logic                                    clk,
    input  logic                                    reset,
    // Configuration inputs (QoS weights, priority mode, anti-starvation threshold)
    input  logic [3:0]                              weight_ld,
    input  logic [3:0]                              weight_st,
    input  logic [3:0]                              weight_mma,
    input  logic                                    strict_mma_prio,
    input  logic [4:0]                              starve_limit,
    // Client 0: Load Engine (read port A requests)
    input  logic [LANES-1:0]                        ld_req_valid,
    output logic [LANES-1:0]                        ld_req_ready,
    input  logic [LANES-1:0][TMEM_ROW_W-1:0]        ld_req_row,
    input  logic [LANES-1:0][TMEM_COL_W-1:0]        ld_req_col,
    input  tmem_swizzle_e                           ld_req_swizzle,
    // Client 1: Store Engine (write port requests)
    input  logic [LANES-1:0]                        st_req_valid,
    output logic [LANES-1:0]                        st_req_ready,
    input  logic [LANES-1:0][TMEM_ROW_W-1:0]        st_req_row,
    input  logic [LANES-1:0][TMEM_COL_W-1:0]        st_req_col,
    input  tmem_swizzle_e                           st_req_swizzle,
    input  logic [LANES-1:0][63:0]                  st_req_data,
    input  logic [LANES-1:0][7:0]                   st_req_be,
    // Client 2: MMA Feeder (read A, read B/C, write D requests)
    input  logic [LANES-1:0]                        mma_rda_valid,
    output logic [LANES-1:0]                        mma_rda_ready,
    input  logic [LANES-1:0][TMEM_ROW_W-1:0]        mma_rda_row,
    input  logic [LANES-1:0][TMEM_COL_W-1:0]        mma_rda_col,
    input  tmem_swizzle_e                           mma_rda_swizzle,
    input  logic [LANES-1:0]                        mma_rdb_valid,
    output logic [LANES-1:0]                        mma_rdb_ready,
    input  logic [LANES-1:0][TMEM_ROW_W-1:0]        mma_rdb_row,
    input  logic [LANES-1:0][TMEM_COL_W-1:0]        mma_rdb_col,
    input  tmem_swizzle_e                           mma_rdb_swizzle,
    input  logic [LANES-1:0]                        mma_wr_valid,
    output logic [LANES-1:0]                        mma_wr_ready,
    input  logic [LANES-1:0][TMEM_ROW_W-1:0]        mma_wr_row,
    input  logic [LANES-1:0][TMEM_COL_W-1:0]        mma_wr_col,
    input  tmem_swizzle_e                           mma_wr_swizzle,
    input  logic [LANES-1:0][63:0]                  mma_wr_data,
    input  logic [LANES-1:0][7:0]                   mma_wr_be,
    // Downstream Bank Array Read Port A (shared between LD and MMA Read A)
    output logic [LANES-1:0]                        bank_rda_valid,
    input  logic [LANES-1:0]                        bank_rda_ready,
    output logic [LANES-1:0][TMEM_ROW_W-1:0]        bank_rda_row,
    output logic [LANES-1:0][TMEM_COL_W-1:0]        bank_rda_col,
    output tmem_swizzle_e                           bank_rda_swizzle,
    // Downstream Bank Array Read Port B (dedicated to MMA Read B/C)
    output logic [LANES-1:0]                        bank_rdb_valid,
    input  logic [LANES-1:0]                        bank_rdb_ready,
    output logic [LANES-1:0][TMEM_ROW_W-1:0]        bank_rdb_row,
    output logic [LANES-1:0][TMEM_COL_W-1:0]        bank_rdb_col,
    output tmem_swizzle_e                           bank_rdb_swizzle,
    // Downstream Bank Array Write Port (shared between ST and MMA Write D)
    output logic [LANES-1:0]                        bank_wr_valid,
    input  logic [LANES-1:0]                        bank_wr_ready,
    output logic [LANES-1:0][TMEM_ROW_W-1:0]        bank_wr_row,
    output logic [LANES-1:0][TMEM_COL_W-1:0]        bank_wr_col,
    output tmem_swizzle_e                           bank_wr_swizzle,
    output logic [LANES-1:0][63:0]                  bank_wr_data,
    output logic [LANES-1:0][7:0]                   bank_wr_be,
    // Registered grant telemetry & anti-starvation diagnostics
    output logic                                    grant_rda_is_mma_out,
    output logic                                    grant_wr_is_mma_out,
    output logic [31:0]                             ld_grants_out,
    output logic [31:0]                             st_grants_out,
    output logic [31:0]                             mma_rda_grants_out,
    output logic [31:0]                             mma_rdb_grants_out,
    output logic [31:0]                             mma_wr_grants_out,
    output logic [31:0]                             escalations_out,
    output logic [31:0]                             conflict_stall_cycles_out
);

    localparam int BANK_W = $clog2(NUM_BANKS);

    // Deficit counters and starvation age counters for DRR + anti-starvation
    logic [4:0]  deficit_ld_q, deficit_ld_d;
    logic [4:0]  deficit_st_q, deficit_st_d;
    logic [4:0]  deficit_mma_rd_q, deficit_mma_rd_d;
    logic [4:0]  deficit_mma_wr_q, deficit_mma_wr_d;

    logic [4:0]  age_ld_q, age_ld_d;
    logic [4:0]  age_st_q, age_st_d;
    logic [4:0]  age_mma_rd_q, age_mma_rd_d;
    logic [4:0]  age_mma_wr_q, age_mma_wr_d;

    logic        rr_rda_q, rr_rda_d;
    logic        rr_wr_q, rr_wr_d;

    // Registered output buffers (owned outputs)
    logic [LANES-1:0]                 bank_rda_valid_q, bank_rda_valid_d;
    logic [LANES-1:0][TMEM_ROW_W-1:0] bank_rda_row_q, bank_rda_row_d;
    logic [LANES-1:0][TMEM_COL_W-1:0] bank_rda_col_q, bank_rda_col_d;
    tmem_swizzle_e                    bank_rda_swizzle_q, bank_rda_swizzle_d;

    logic [LANES-1:0]                 bank_rdb_valid_q, bank_rdb_valid_d;
    logic [LANES-1:0][TMEM_ROW_W-1:0] bank_rdb_row_q, bank_rdb_row_d;
    logic [LANES-1:0][TMEM_COL_W-1:0] bank_rdb_col_q, bank_rdb_col_d;
    tmem_swizzle_e                    bank_rdb_swizzle_q, bank_rdb_swizzle_d;

    logic [LANES-1:0]                 bank_wr_valid_q, bank_wr_valid_d;
    logic [LANES-1:0][TMEM_ROW_W-1:0] bank_wr_row_q, bank_wr_row_d;
    logic [LANES-1:0][TMEM_COL_W-1:0] bank_wr_col_q, bank_wr_col_d;
    tmem_swizzle_e                    bank_wr_swizzle_q, bank_wr_swizzle_d;
    logic [LANES-1:0][63:0]           bank_wr_data_q, bank_wr_data_d;
    logic [LANES-1:0][7:0]            bank_wr_be_q, bank_wr_be_d;

    // Registered ready outputs and telemetry
    logic        grant_rda_is_mma_q, grant_rda_is_mma_d;
    logic        grant_wr_is_mma_q, grant_wr_is_mma_d;
    logic [31:0] ld_grants_q, ld_grants_d;
    logic [31:0] st_grants_q, st_grants_d;
    logic [31:0] mma_rda_grants_q, mma_rda_grants_d;
    logic [31:0] mma_rdb_grants_q, mma_rdb_grants_d;
    logic [31:0] mma_wr_grants_q, mma_wr_grants_d;
    logic [31:0] escalations_q, escalations_d;
    logic [31:0] conflict_stall_cycles_q, conflict_stall_cycles_d;

    // Combinational arbitration signals
    logic        ld_any_req;
    logic        st_any_req;
    logic        mma_rda_any_req;
    logic        mma_rdb_any_req;
    logic        mma_wr_any_req;

    logic        rda_slot_free;
    logic        rdb_slot_free;
    logic        wr_slot_free;

    logic        ld_bank_conflict;
    logic        st_bank_conflict;
    logic        mma_rda_conflict;
    logic        mma_wr_conflict;
    logic        any_conflict;

    logic [4:0]  eff_age_limit;
    logic [4:0]  eff_w_ld;
    logic [4:0]  eff_w_st;
    logic [4:0]  eff_w_mma;

    logic        pick_mma_rda;
    logic        pick_ld_rda;
    logic        pick_mma_wr;
    logic        pick_st_wr;
    logic        esc_event_rda;
    logic        esc_event_wr;

    logic [NUM_BANKS-1:0] ld_bank_seen;
    logic [NUM_BANKS-1:0] st_bank_seen;
    logic [NUM_BANKS-1:0] mma_rda_bank_seen;
    logic [NUM_BANKS-1:0] mma_wr_bank_seen;

    `UNUSED_PARAM (BANK_W)

    // Helper: clamp deficit increment to DEFICIT_MAX
    function automatic logic [4:0] sat_add_deficit(
        input logic [4:0] cur,
        input logic [4:0] quantum
    );
        logic [5:0] sum;
        sum = {1'b0, cur} + {1'b0, quantum};
        if (sum > 6'(DEFICIT_MAX)) begin
            return 5'(DEFICIT_MAX);
        end else begin
            return sum[4:0];
        end
    endfunction

    // Detect per-client internal bank collisions across the 8 request lanes
    always_comb begin
        ld_any_req      = |ld_req_valid;
        st_any_req      = |st_req_valid;
        mma_rda_any_req = |mma_rda_valid;
        mma_rdb_any_req = |mma_rdb_valid;
        mma_wr_any_req  = |mma_wr_valid;

        ld_bank_seen      = '0;
        st_bank_seen      = '0;
        mma_rda_bank_seen = '0;
        mma_wr_bank_seen  = '0;
        ld_bank_conflict  = 1'b0;
        st_bank_conflict  = 1'b0;
        mma_rda_conflict  = 1'b0;
        mma_wr_conflict   = 1'b0;

        for (int l = 0; l < LANES; ++l) begin
            logic [TMEM_BANK_ID_W-1:0] b_ld;
            logic [TMEM_BANK_ID_W-1:0] b_st;
            logic [TMEM_BANK_ID_W-1:0] b_ma;
            logic [TMEM_BANK_ID_W-1:0] b_mw;

            b_ld = tmem_swizzled_bank(ld_req_row[l], ld_req_col[l], ld_req_swizzle);
            b_st = tmem_swizzled_bank(st_req_row[l], st_req_col[l], st_req_swizzle);
            b_ma = tmem_swizzled_bank(mma_rda_row[l], mma_rda_col[l], mma_rda_swizzle);
            b_mw = tmem_swizzled_bank(mma_wr_row[l], mma_wr_col[l], mma_wr_swizzle);

            if (ld_req_valid[l]) begin
                if (ld_bank_seen[b_ld]) begin
                    ld_bank_conflict = 1'b1;
                end
                ld_bank_seen[b_ld] = 1'b1;
            end
            if (st_req_valid[l]) begin
                if (st_bank_seen[b_st]) begin
                    st_bank_conflict = 1'b1;
                end
                st_bank_seen[b_st] = 1'b1;
            end
            if (mma_rda_valid[l]) begin
                if (mma_rda_bank_seen[b_ma]) begin
                    mma_rda_conflict = 1'b1;
                end
                mma_rda_bank_seen[b_ma] = 1'b1;
            end
            if (mma_wr_valid[l]) begin
                if (mma_wr_bank_seen[b_mw]) begin
                    mma_wr_conflict = 1'b1;
                end
                mma_wr_bank_seen[b_mw] = 1'b1;
            end
        end

        any_conflict = ld_bank_conflict | st_bank_conflict | mma_rda_conflict | mma_wr_conflict;
    end

    // Port readiness: output register can accept new beat if empty or all active lanes consumed
    always_comb begin
        rda_slot_free = (~|bank_rda_valid_q) || (&(bank_rda_ready | ~bank_rda_valid_q));
        rdb_slot_free = (~|bank_rdb_valid_q) || (&(bank_rdb_ready | ~bank_rdb_valid_q));
        wr_slot_free  = (~|bank_wr_valid_q)  || (&(bank_wr_ready  | ~bank_wr_valid_q));

        eff_age_limit = (starve_limit == 5'd0) ? 5'(AGE_THRESHOLD) : starve_limit;
        eff_w_ld      = (weight_ld == 4'd0) ? 5'd1 : {1'b0, weight_ld};
        eff_w_st      = (weight_st == 4'd0) ? 5'd1 : {1'b0, weight_st};
        eff_w_mma     = (weight_mma == 4'd0) ? 5'd2 : {1'b0, weight_mma};
    end

    // Arbitration decisions for Read Port A (LD vs MMA_RD_A) and Write Port (ST vs MMA_WR_D)
    always_comb begin
        pick_mma_rda  = 1'b0;
        pick_ld_rda   = 1'b0;
        esc_event_rda = 1'b0;

        if (rda_slot_free) begin
            if (ld_any_req && !mma_rda_any_req) begin
                pick_ld_rda = 1'b1;
            end else if (!ld_any_req && mma_rda_any_req) begin
                pick_mma_rda = 1'b1;
            end else if (ld_any_req && mma_rda_any_req) begin
                if (age_ld_q >= eff_age_limit) begin
                    pick_ld_rda   = 1'b1;
                    esc_event_rda = 1'b1;
                end else if (age_mma_rd_q >= eff_age_limit) begin
                    pick_mma_rda  = 1'b1;
                    esc_event_rda = 1'b1;
                end else if (strict_mma_prio) begin
                    pick_mma_rda = 1'b1;
                end else if ((deficit_ld_q > 5'd0) && (deficit_mma_rd_q == 5'd0)) begin
                    pick_ld_rda = 1'b1;
                end else if ((deficit_mma_rd_q > 5'd0) && (deficit_ld_q == 5'd0)) begin
                    pick_mma_rda = 1'b1;
                end else if (rr_rda_q == 1'b0) begin
                    pick_mma_rda = 1'b1;
                end else begin
                    pick_ld_rda = 1'b1;
                end
            end
        end

        pick_mma_wr  = 1'b0;
        pick_st_wr   = 1'b0;
        esc_event_wr = 1'b0;

        if (wr_slot_free) begin
            if (st_any_req && !mma_wr_any_req) begin
                pick_st_wr = 1'b1;
            end else if (!st_any_req && mma_wr_any_req) begin
                pick_mma_wr = 1'b1;
            end else if (st_any_req && mma_wr_any_req) begin
                if (age_st_q >= eff_age_limit) begin
                    pick_st_wr   = 1'b1;
                    esc_event_wr = 1'b1;
                end else if (age_mma_wr_q >= eff_age_limit) begin
                    pick_mma_wr  = 1'b1;
                    esc_event_wr = 1'b1;
                end else if (strict_mma_prio) begin
                    pick_mma_wr = 1'b1;
                end else if ((deficit_st_q > 5'd0) && (deficit_mma_wr_q == 5'd0)) begin
                    pick_st_wr = 1'b1;
                end else if ((deficit_mma_wr_q > 5'd0) && (deficit_st_q == 5'd0)) begin
                    pick_mma_wr = 1'b1;
                end else if (rr_wr_q == 1'b0) begin
                    pick_mma_wr = 1'b1;
                end else begin
                    pick_st_wr = 1'b1;
                end
            end
        end
    end

    // Ready backpressure signals to clients
    always_comb begin
        ld_req_ready  = {LANES{pick_ld_rda}};
        mma_rda_ready = {LANES{pick_mma_rda}};
        mma_rdb_ready = {LANES{rdb_slot_free & mma_rdb_any_req}};
        st_req_ready  = {LANES{pick_st_wr}};
        mma_wr_ready  = {LANES{pick_mma_wr}};
    end

    // Next-state datapath registers, DRR credits, age counters, and telemetry
    always_comb begin
        bank_rda_valid_d   = bank_rda_valid_q;
        bank_rda_row_d     = bank_rda_row_q;
        bank_rda_col_d     = bank_rda_col_q;
        bank_rda_swizzle_d = bank_rda_swizzle_q;

        bank_rdb_valid_d   = bank_rdb_valid_q;
        bank_rdb_row_d     = bank_rdb_row_q;
        bank_rdb_col_d     = bank_rdb_col_q;
        bank_rdb_swizzle_d = bank_rdb_swizzle_q;

        bank_wr_valid_d    = bank_wr_valid_q;
        bank_wr_row_d      = bank_wr_row_q;
        bank_wr_col_d      = bank_wr_col_q;
        bank_wr_swizzle_d  = bank_wr_swizzle_q;
        bank_wr_data_d     = bank_wr_data_q;
        bank_wr_be_d       = bank_wr_be_q;

        deficit_ld_d     = deficit_ld_q;
        deficit_st_d     = deficit_st_q;
        deficit_mma_rd_d = deficit_mma_rd_q;
        deficit_mma_wr_d = deficit_mma_wr_q;

        age_ld_d         = age_ld_q;
        age_st_d         = age_st_q;
        age_mma_rd_d     = age_mma_rd_q;
        age_mma_wr_d     = age_mma_wr_q;

        rr_rda_d         = rr_rda_q;
        rr_wr_d          = rr_wr_q;

        grant_rda_is_mma_d      = grant_rda_is_mma_q;
        grant_wr_is_mma_d       = grant_wr_is_mma_q;
        ld_grants_d             = ld_grants_q;
        st_grants_d             = st_grants_q;
        mma_rda_grants_d        = mma_rda_grants_q;
        mma_rdb_grants_d        = mma_rdb_grants_q;
        mma_wr_grants_d         = mma_wr_grants_q;
        escalations_d           = escalations_q;
        conflict_stall_cycles_d = conflict_stall_cycles_q;

        // Clear consumed lanes on bank_rda
        for (int l = 0; l < LANES; ++l) begin
            if (bank_rda_valid_q[l] && bank_rda_ready[l]) begin
                bank_rda_valid_d[l] = 1'b0;
            end
            if (bank_rdb_valid_q[l] && bank_rdb_ready[l]) begin
                bank_rdb_valid_d[l] = 1'b0;
            end
            if (bank_wr_valid_q[l] && bank_wr_ready[l]) begin
                bank_wr_valid_d[l] = 1'b0;
            end
        end

        // Read Port A winner capture & DRR accounting
        if (pick_mma_rda) begin
            bank_rda_valid_d   = mma_rda_valid;
            bank_rda_row_d     = mma_rda_row;
            bank_rda_col_d     = mma_rda_col;
            bank_rda_swizzle_d = mma_rda_swizzle;
            grant_rda_is_mma_d = 1'b1;
            mma_rda_grants_d   = mma_rda_grants_q + 32'd1;
            age_mma_rd_d       = 5'd0;
            rr_rda_d           = 1'b1;

            if (deficit_mma_rd_q > 5'd0) begin
                deficit_mma_rd_d = deficit_mma_rd_q - 5'd1;
            end else begin
                deficit_mma_rd_d = sat_add_deficit(5'd0, eff_w_mma - 5'd1);
            end

            if (ld_any_req) begin
                age_ld_d     = (age_ld_q == 5'h1F) ? 5'h1F : (age_ld_q + 5'd1);
                deficit_ld_d = sat_add_deficit(deficit_ld_q, eff_w_ld);
            end else begin
                age_ld_d = 5'd0;
            end
        end else if (pick_ld_rda) begin
            bank_rda_valid_d   = ld_req_valid;
            bank_rda_row_d     = ld_req_row;
            bank_rda_col_d     = ld_req_col;
            bank_rda_swizzle_d = ld_req_swizzle;
            grant_rda_is_mma_d = 1'b0;
            ld_grants_d        = ld_grants_q + 32'd1;
            age_ld_d           = 5'd0;
            rr_rda_d           = 1'b0;

            if (deficit_ld_q > 5'd0) begin
                deficit_ld_d = deficit_ld_q - 5'd1;
            end else begin
                deficit_ld_d = sat_add_deficit(5'd0, eff_w_ld - 5'd1);
            end

            if (mma_rda_any_req) begin
                age_mma_rd_d     = (age_mma_rd_q == 5'h1F) ? 5'h1F : (age_mma_rd_q + 5'd1);
                deficit_mma_rd_d = sat_add_deficit(deficit_mma_rd_q, eff_w_mma);
            end else begin
                age_mma_rd_d = 5'd0;
            end
        end else begin
            if (!ld_any_req) begin
                age_ld_d = 5'd0;
            end else if (!rda_slot_free) begin
                age_ld_d = (age_ld_q == 5'h1F) ? 5'h1F : (age_ld_q + 5'd1);
            end
            if (!mma_rda_any_req) begin
                age_mma_rd_d = 5'd0;
            end else if (!rda_slot_free) begin
                age_mma_rd_d = (age_mma_rd_q == 5'h1F) ? 5'h1F : (age_mma_rd_q + 5'd1);
            end
        end

        // Read Port B dedicated to MMA B/C
        if (rdb_slot_free && mma_rdb_any_req) begin
            bank_rdb_valid_d   = mma_rdb_valid;
            bank_rdb_row_d     = mma_rdb_row;
            bank_rdb_col_d     = mma_rdb_col;
            bank_rdb_swizzle_d = mma_rdb_swizzle;
            mma_rdb_grants_d   = mma_rdb_grants_q + 32'd1;
        end

        // Write Port winner capture & DRR accounting
        if (pick_mma_wr) begin
            bank_wr_valid_d   = mma_wr_valid;
            bank_wr_row_d     = mma_wr_row;
            bank_wr_col_d     = mma_wr_col;
            bank_wr_swizzle_d = mma_wr_swizzle;
            bank_wr_data_d    = mma_wr_data;
            bank_wr_be_d      = mma_wr_be;
            grant_wr_is_mma_d = 1'b1;
            mma_wr_grants_d   = mma_wr_grants_q + 32'd1;
            age_mma_wr_d      = 5'd0;
            rr_wr_d           = 1'b1;

            if (deficit_mma_wr_q > 5'd0) begin
                deficit_mma_wr_d = deficit_mma_wr_q - 5'd1;
            end else begin
                deficit_mma_wr_d = sat_add_deficit(5'd0, eff_w_mma - 5'd1);
            end

            if (st_any_req) begin
                age_st_d     = (age_st_q == 5'h1F) ? 5'h1F : (age_st_q + 5'd1);
                deficit_st_d = sat_add_deficit(deficit_st_q, eff_w_st);
            end else begin
                age_st_d = 5'd0;
            end
        end else if (pick_st_wr) begin
            bank_wr_valid_d   = st_req_valid;
            bank_wr_row_d     = st_req_row;
            bank_wr_col_d     = st_req_col;
            bank_wr_swizzle_d = st_req_swizzle;
            bank_wr_data_d    = st_req_data;
            bank_wr_be_d      = st_req_be;
            grant_wr_is_mma_d = 1'b0;
            st_grants_d       = st_grants_q + 32'd1;
            age_st_d          = 5'd0;
            rr_wr_d           = 1'b0;

            if (deficit_st_q > 5'd0) begin
                deficit_st_d = deficit_st_q - 5'd1;
            end else begin
                deficit_st_d = sat_add_deficit(5'd0, eff_w_st - 5'd1);
            end

            if (mma_wr_any_req) begin
                age_mma_wr_d     = (age_mma_wr_q == 5'h1F) ? 5'h1F : (age_mma_wr_q + 5'd1);
                deficit_mma_wr_d = sat_add_deficit(deficit_mma_wr_q, eff_w_mma);
            end else begin
                age_mma_wr_d = 5'd0;
            end
        end else begin
            if (!st_any_req) begin
                age_st_d = 5'd0;
            end else if (!wr_slot_free) begin
                age_st_d = (age_st_q == 5'h1F) ? 5'h1F : (age_st_q + 5'd1);
            end
            if (!mma_wr_any_req) begin
                age_mma_wr_d = 5'd0;
            end else if (!wr_slot_free) begin
                age_mma_wr_d = (age_mma_wr_q == 5'h1F) ? 5'h1F : (age_mma_wr_q + 5'd1);
            end
        end

        if (esc_event_rda || esc_event_wr) begin
            escalations_d = escalations_q + 32'd1;
        end

        if (any_conflict || (|(bank_rda_valid_q & ~bank_rda_ready)) ||
            (|(bank_rdb_valid_q & ~bank_rdb_ready)) ||
            (|(bank_wr_valid_q  & ~bank_wr_ready))) begin
            conflict_stall_cycles_d = conflict_stall_cycles_q + 32'd1;
        end
    end

    always_ff @(posedge clk) begin
        if (reset) begin
            bank_rda_valid_q   <= '0;
            bank_rda_row_q     <= '0;
            bank_rda_col_q     <= '0;
            bank_rda_swizzle_q <= TMEM_SWIZZLE_NONE;

            bank_rdb_valid_q   <= '0;
            bank_rdb_row_q     <= '0;
            bank_rdb_col_q     <= '0;
            bank_rdb_swizzle_q <= TMEM_SWIZZLE_NONE;

            bank_wr_valid_q    <= '0;
            bank_wr_row_q      <= '0;
            bank_wr_col_q      <= '0;
            bank_wr_swizzle_q  <= TMEM_SWIZZLE_NONE;
            bank_wr_data_q     <= '0;
            bank_wr_be_q       <= '0;

            deficit_ld_q       <= 5'd0;
            deficit_st_q       <= 5'd0;
            deficit_mma_rd_q   <= 5'd0;
            deficit_mma_wr_q   <= 5'd0;

            age_ld_q           <= 5'd0;
            age_st_q           <= 5'd0;
            age_mma_rd_q       <= 5'd0;
            age_mma_wr_q       <= 5'd0;

            rr_rda_q           <= 1'b0;
            rr_wr_q            <= 1'b0;

            grant_rda_is_mma_q      <= 1'b0;
            grant_wr_is_mma_q       <= 1'b0;
            ld_grants_q             <= 32'd0;
            st_grants_q             <= 32'd0;
            mma_rda_grants_q        <= 32'd0;
            mma_rdb_grants_q        <= 32'd0;
            mma_wr_grants_q         <= 32'd0;
            escalations_q           <= 32'd0;
            conflict_stall_cycles_q <= 32'd0;
        end else begin
            bank_rda_valid_q   <= bank_rda_valid_d;
            bank_rda_row_q     <= bank_rda_row_d;
            bank_rda_col_q     <= bank_rda_col_d;
            bank_rda_swizzle_q <= bank_rda_swizzle_d;

            bank_rdb_valid_q   <= bank_rdb_valid_d;
            bank_rdb_row_q     <= bank_rdb_row_d;
            bank_rdb_col_q     <= bank_rdb_col_d;
            bank_rdb_swizzle_q <= bank_rdb_swizzle_d;

            bank_wr_valid_q    <= bank_wr_valid_d;
            bank_wr_row_q      <= bank_wr_row_d;
            bank_wr_col_q      <= bank_wr_col_d;
            bank_wr_swizzle_q  <= bank_wr_swizzle_d;
            bank_wr_data_q     <= bank_wr_data_d;
            bank_wr_be_q       <= bank_wr_be_d;

            deficit_ld_q       <= deficit_ld_d;
            deficit_st_q       <= deficit_st_d;
            deficit_mma_rd_q   <= deficit_mma_rd_d;
            deficit_mma_wr_q   <= deficit_mma_wr_d;

            age_ld_q           <= age_ld_d;
            age_st_q           <= age_st_d;
            age_mma_rd_q       <= age_mma_rd_d;
            age_mma_wr_q       <= age_mma_wr_d;

            rr_rda_q           <= rr_rda_d;
            rr_wr_q            <= rr_wr_d;

            grant_rda_is_mma_q      <= grant_rda_is_mma_d;
            grant_wr_is_mma_q       <= grant_wr_is_mma_d;
            ld_grants_q             <= ld_grants_d;
            st_grants_q             <= st_grants_d;
            mma_rda_grants_q        <= mma_rda_grants_d;
            mma_rdb_grants_q        <= mma_rdb_grants_d;
            mma_wr_grants_q         <= mma_wr_grants_d;
            escalations_q           <= escalations_d;
            conflict_stall_cycles_q <= conflict_stall_cycles_d;
        end
    end

    assign bank_rda_valid            = bank_rda_valid_q;
    assign bank_rda_row              = bank_rda_row_q;
    assign bank_rda_col              = bank_rda_col_q;
    assign bank_rda_swizzle          = bank_rda_swizzle_q;

    assign bank_rdb_valid            = bank_rdb_valid_q;
    assign bank_rdb_row              = bank_rdb_row_q;
    assign bank_rdb_col              = bank_rdb_col_q;
    assign bank_rdb_swizzle          = bank_rdb_swizzle_q;

    assign bank_wr_valid             = bank_wr_valid_q;
    assign bank_wr_row               = bank_wr_row_q;
    assign bank_wr_col               = bank_wr_col_q;
    assign bank_wr_swizzle           = bank_wr_swizzle_q;
    assign bank_wr_data              = bank_wr_data_q;
    assign bank_wr_be                = bank_wr_be_q;

    assign grant_rda_is_mma_out      = grant_rda_is_mma_q;
    assign grant_wr_is_mma_out       = grant_wr_is_mma_q;
    assign ld_grants_out             = ld_grants_q;
    assign st_grants_out             = st_grants_q;
    assign mma_rda_grants_out        = mma_rda_grants_q;
    assign mma_rdb_grants_out        = mma_rdb_grants_q;
    assign mma_wr_grants_out         = mma_wr_grants_q;
    assign escalations_out           = escalations_q;
    assign conflict_stall_cycles_out = conflict_stall_cycles_q;

endmodule

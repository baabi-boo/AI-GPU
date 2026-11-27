// SPDX-License-Identifier: Apache-2.0
`ifndef VX_TMEM_PKG_SV
`define VX_TMEM_PKG_SV

package VX_tmem_pkg;

    // -------------------------------------------------------------------------
    // Dedicated Tensor Memory (TMEM) Geometry & ECC Constants
    // -------------------------------------------------------------------------
    localparam int TMEM_CAPACITY_BYTES     = 262144; // 256 KiB per core
    localparam int TMEM_LANES_ROWS         = 128;
    localparam int TMEM_COLUMNS            = 512;
    localparam int TMEM_CELL_BYTES         = 4;
    localparam int TMEM_CELL_BITS          = 32;
    localparam int TMEM_NUM_BANKS          = 32;
    localparam int TMEM_BANK_WIDTH_BITS    = 64;
    localparam int TMEM_BANK_WIDTH_BYTES   = 8;
    localparam int TMEM_BANK_DEPTH_WORDS   = 1024;   // 32 * 1024 * 8 B = 256 KiB
    localparam int TMEM_ALLOC_GRANULE_COLS = 32;
    localparam int TMEM_MIN_ALLOC_COLS     = 32;
    localparam int TMEM_NUM_ALLOC_UNITS    = 16;     // 512 / 32 = 16 column granules
    localparam int TMEM_MAX_REGIONS        = 16;

    localparam int TMEM_ECC_DATA_W         = 64;
    localparam int TMEM_ECC_PARITY_W       = 8;
    localparam int TMEM_ECC_CODE_W         = 72;     // SECDED Hsiao(72,64)
    localparam int TMEM_READ_PORTS         = 2;
    localparam int TMEM_WRITE_PORTS        = 1;

    localparam int TMEM_ROW_W              = 7;      // log2(128)
    localparam int TMEM_COL_W              = 9;      // log2(512)
    localparam int TMEM_BANK_ID_W          = 5;      // log2(32)
    localparam int TMEM_BANK_ADDR_W        = 10;     // log2(1024)
    localparam int TMEM_REGION_ID_W        = 4;      // log2(16)
    localparam int TMEM_TAG_W              = 8;
    localparam int TMEM_BARRIER_ID_W       = 4;

    // Hsiao(72,64) parity check matrix rows [7:0] over 64-bit data words.
    // Packed descending order: element [7] is parity bit 7, element [0] is parity bit 0.
    // Every data column has odd Hamming weight (3 or 5) and all 72 H-columns are unique.
    localparam logic [7:0][63:0] TMEM_HSIAO_P_MATRIX = '{
        64'h48ED_348D_221A_4420,
        64'hA4DA_AA4A_9115_2210,
        64'h92B6_5926_488C_9108,
        64'h7171_C711_C443_8884,
        64'h0F0F_C0F0_3C20_7842,
        64'hFF00_3FF0_03E0_07C1,
        64'hFF00_000F_FFE0_003F,
        64'hFF00_0000_001F_FFFF
    };

    // -------------------------------------------------------------------------
    // Swizzle, Opcode, Allocation, and Status Enumerations
    // -------------------------------------------------------------------------
    typedef enum logic [1:0] {
        TMEM_SWIZZLE_NONE = 2'd0,
        TMEM_SWIZZLE_32B  = 2'd1,
        TMEM_SWIZZLE_64B  = 2'd2,
        TMEM_SWIZZLE_128B = 2'd3
    } tmem_swizzle_e;

    typedef enum logic [3:0] {
        TMEM_OP_NOP      = 4'd0,
        TMEM_OP_LD       = 4'd1,
        TMEM_OP_ST       = 4'd2,
        TMEM_OP_MMA_RD_A = 4'd3,
        TMEM_OP_MMA_RD_B = 4'd4,
        TMEM_OP_MMA_RD_C = 4'd5,
        TMEM_OP_MMA_WR_D = 4'd6,
        TMEM_OP_ALLOC    = 4'd7,
        TMEM_OP_DEALLOC  = 4'd8,
        TMEM_OP_WAIT     = 4'd9,
        TMEM_OP_FENCE    = 4'd10
    } tmem_op_e;

    typedef enum logic [2:0] {
        TMEM_STATUS_OK          = 3'd0,
        TMEM_STATUS_BAD_ALIGN   = 3'd1,
        TMEM_STATUS_BAD_SIZE    = 3'd2,
        TMEM_STATUS_OUT_OF_COLS = 3'd3,
        TMEM_STATUS_OVERLAP     = 3'd4,
        TMEM_STATUS_NOT_ALLOCED = 3'd5,
        TMEM_STATUS_ECC_UE      = 3'd6,
        TMEM_STATUS_FULL        = 3'd7
    } tmem_status_e;

    // -------------------------------------------------------------------------
    // Packed Request, Response, Allocation, Region, ECC, and Perf Structs
    // -------------------------------------------------------------------------
    typedef struct packed {
        tmem_op_e                         op;
        logic [TMEM_TAG_W-1:0]            tag;
        logic [TMEM_REGION_ID_W-1:0]      region_id;
        logic [TMEM_ROW_W-1:0]            row;
        logic [TMEM_COL_W-1:0]            col;
        tmem_swizzle_e                    swizzle;
        logic [TMEM_BANK_WIDTH_BITS-1:0]  wr_data;
        logic [TMEM_BANK_WIDTH_BYTES-1:0] wr_be;
        logic                             cell_mode32;
        logic [TMEM_BARRIER_ID_W-1:0]     barrier_id;
        logic                             barrier_phase;
    } tmem_req_t;

    typedef struct packed {
        logic                            valid;
        tmem_op_e                        op;
        logic [TMEM_TAG_W-1:0]           tag;
        tmem_status_e                    status;
        logic [TMEM_BANK_WIDTH_BITS-1:0] rd_data;
        logic                            ecc_ce;
        logic                            ecc_ue;
        logic [TMEM_BANK_ID_W-1:0]       bank_id;
    } tmem_rsp_t;

    typedef struct packed {
        logic                        is_dealloc;
        logic [TMEM_REGION_ID_W-1:0] region_id;
        logic [TMEM_COL_W-1:0]       col_offset;
        logic [9:0]                  num_columns;
        logic [7:0]                  num_rows;
        tmem_swizzle_e               swizzle;
        logic                        double_buf_en;
        logic [4:0]                  owner_warp;
    } tmem_alloc_req_t;

    typedef struct packed {
        logic                        valid;
        tmem_status_e                status;
        logic [TMEM_REGION_ID_W-1:0] region_id;
        logic [TMEM_COL_W-1:0]       col_offset;
        logic [9:0]                  num_columns;
        logic [TMEM_COL_W-1:0]       buf_b_col_offset;
    } tmem_alloc_rsp_t;

    typedef struct packed {
        logic                            allocated;
        logic                            active_buf;
        logic                            double_buf_en;
        logic [TMEM_REGION_ID_W-1:0]     region_id;
        logic [TMEM_COL_W-1:0]           col_offset;
        logic [9:0]                      num_columns;
        logic [7:0]                      num_rows;
        tmem_swizzle_e                   swizzle;
        logic [4:0]                      owner_warp;
        logic [TMEM_NUM_ALLOC_UNITS-1:0] granule_mask;
    } tmem_region_entry_t;

    typedef struct packed {
        logic                         ce_detected;
        logic                         ue_detected;
        logic [TMEM_BANK_ID_W-1:0]    last_bank_id;
        logic [TMEM_BANK_ADDR_W-1:0]  last_word_addr;
        logic [TMEM_ECC_PARITY_W-1:0] last_syndrome;
        logic [31:0]                  ce_total;
        logic [31:0]                  ue_total;
    } tmem_ecc_status_t;

    typedef struct packed {
        logic [31:0] rd_a_ops;
        logic [31:0] rd_b_ops;
        logic [31:0] wr_ops;
        logic [31:0] conflict_cycles;
        logic [31:0] fence_wait_cycles;
        logic [31:0] alloc_ops;
        logic [31:0] dealloc_ops;
        logic [31:0] scrub_ops;
    } tmem_perf_cnt_t;

    // -------------------------------------------------------------------------
    // Swizzle and Bijective Physical Bank/Word/Half-Cell Mapping Functions
    // -------------------------------------------------------------------------
    // Bijection proof across all 128 * 512 = 65,536 4-byte cells (262,144 B):
    //   bank_id   = tmem_swizzled_bank(row, col, mode)  (5 bits -> 32 banks)
    //   word_addr = {row[6:0], col[8:6]}                (10 bits -> 1024 words/bank)
    //   half_sel  = col[5]                              (1 bit -> low/high 32-bit half of 64-bit word)
    // Because XOR with a function of row is an involution on col[4:0], every
    // logical (row[6:0], col[8:0]) maps 1-to-1 to (bank_id[4:0], word_addr[9:0], half_sel).
    function automatic logic [TMEM_BANK_ID_W-1:0] tmem_swizzled_bank(
        input logic [TMEM_ROW_W-1:0] row,
        input logic [TMEM_COL_W-1:0] col,
        input tmem_swizzle_e         mode
    );
        logic [4:0] base_bank;
        logic       unused_zero;
        base_bank   = col[4:0];
        unused_zero = &{1'b0, row[6:5], col[8:5]};
        if (unused_zero) begin
            return base_bank;
        end
        case (mode)
            TMEM_SWIZZLE_NONE: return base_bank;
            TMEM_SWIZZLE_32B:  return base_bank ^ {2'b00, row[2:0]};
            TMEM_SWIZZLE_64B:  return base_bank ^ {1'b0, row[3:0]};
            TMEM_SWIZZLE_128B: return base_bank ^ row[4:0];
            default:           return base_bank;
        endcase
    endfunction

    function automatic logic [4:0] tmem_inv_swizzle_col_low(
        input logic [TMEM_ROW_W-1:0]     row,
        input logic [TMEM_BANK_ID_W-1:0] bank_id,
        input tmem_swizzle_e             mode
    );
        logic unused_zero;
        unused_zero = &{1'b0, row[6:5]};
        if (unused_zero) begin
            return bank_id;
        end
        case (mode)
            TMEM_SWIZZLE_NONE: return bank_id;
            TMEM_SWIZZLE_32B:  return bank_id ^ {2'b00, row[2:0]};
            TMEM_SWIZZLE_64B:  return bank_id ^ {1'b0, row[3:0]};
            TMEM_SWIZZLE_128B: return bank_id ^ row[4:0];
            default:           return bank_id;
        endcase
    endfunction

    function automatic logic [TMEM_BANK_ADDR_W-1:0] tmem_bank_word_addr(
        input logic [TMEM_ROW_W-1:0] row,
        input logic [TMEM_COL_W-1:0] col
    );
        logic unused_zero;
        unused_zero = &{1'b0, col[5:0]};
        return unused_zero ? '0 : {row[6:0], col[8:6]};
    endfunction

    function automatic logic tmem_cell_half_sel(
        input logic [TMEM_COL_W-1:0] col
    );
        logic unused_zero;
        unused_zero = &{1'b0, col[8:6], col[4:0]};
        return unused_zero ? 1'b0 : col[5];
    endfunction

    function automatic logic [TMEM_ROW_W-1:0] tmem_row_from_word_addr(
        input logic [TMEM_BANK_ADDR_W-1:0] word_addr
    );
        logic unused_zero;
        unused_zero = &{1'b0, word_addr[2:0]};
        return unused_zero ? '0 : word_addr[9:3];
    endfunction

    function automatic logic [TMEM_COL_W-1:0] tmem_col_from_phys(
        input logic [TMEM_BANK_ADDR_W-1:0] word_addr,
        input logic [TMEM_BANK_ID_W-1:0]   bank_id,
        input logic                        half_sel,
        input tmem_swizzle_e               mode
    );
        logic [TMEM_ROW_W-1:0] row;
        logic [4:0]            col_low;
        row     = tmem_row_from_word_addr(word_addr);
        col_low = tmem_inv_swizzle_col_low(row, bank_id, mode);
        return {word_addr[2:0], half_sel, col_low};
    endfunction

    // -------------------------------------------------------------------------
    // Allocation Alignment, Power-of-Two, and Overlap Validation Helpers
    // -------------------------------------------------------------------------
    function automatic logic tmem_is_pow2_cols(
        input logic [9:0] num_columns
    );
        return (num_columns != 10'd0) && ((num_columns & (num_columns - 10'd1)) == 10'd0);
    endfunction

    function automatic logic tmem_rows_legal(
        input logic [7:0] num_rows
    );
        return (num_rows == 8'd32) || (num_rows == 8'd64) || (num_rows == 8'd128);
    endfunction

    function automatic logic tmem_alloc_legal(
        input logic [TMEM_COL_W-1:0] col_offset,
        input logic [9:0]            num_columns,
        input logic [7:0]            num_rows
    );
        logic align_ok;
        logic size_ok;
        logic bounds_ok;
        logic rows_ok;
        logic [10:0] end_col;
        align_ok  = (col_offset[4:0] == 5'd0);
        size_ok   = (num_columns >= 10'(TMEM_MIN_ALLOC_COLS)) &&
                    (num_columns <= 10'(TMEM_COLUMNS)) &&
                    tmem_is_pow2_cols(num_columns);
        end_col   = {2'b00, col_offset} + {1'b0, num_columns};
        bounds_ok = (end_col <= 11'(TMEM_COLUMNS));
        rows_ok   = tmem_rows_legal(num_rows);
        return align_ok && size_ok && bounds_ok && rows_ok;
    endfunction

    function automatic logic [TMEM_NUM_ALLOC_UNITS-1:0] tmem_alloc_granule_mask(
        input logic [TMEM_COL_W-1:0] col_offset,
        input logic [9:0]            num_columns
    );
        logic [TMEM_NUM_ALLOC_UNITS-1:0] mask;
        logic [4:0] start_unit;
        logic [4:0] unit_count;
        logic       unused_zero;
        unused_zero = &{1'b0, col_offset[4:0], num_columns[4:0]};
        start_unit  = {1'b0, col_offset[8:5]};
        unit_count  = num_columns[9:5];
        mask = '0;
        for (int i = 0; i < TMEM_NUM_ALLOC_UNITS; ++i) begin
            if (!unused_zero && (5'(i) >= start_unit) && (5'(i) < (start_unit + unit_count))) begin
                mask[i] = 1'b1;
            end
        end
        return mask;
    endfunction

    function automatic logic tmem_region_overlaps(
        input logic [TMEM_COL_W-1:0] a_offset,
        input logic [9:0]            a_cols,
        input logic [TMEM_COL_W-1:0] b_offset,
        input logic [9:0]            b_cols
    );
        logic [10:0] a_start;
        logic [10:0] a_end;
        logic [10:0] b_start;
        logic [10:0] b_end;
        a_start = {2'b00, a_offset};
        a_end   = a_start + {1'b0, a_cols};
        b_start = {2'b00, b_offset};
        b_end   = b_start + {1'b0, b_cols};
        return (a_start < b_end) && (b_start < a_end);
    endfunction

    function automatic logic tmem_coord_in_region(
        input tmem_region_entry_t    region,
        input logic [TMEM_ROW_W-1:0] row,
        input logic [TMEM_COL_W-1:0] col
    );
        logic [10:0] col_ext;
        logic [10:0] reg_start;
        logic [10:0] reg_cols_eff;
        logic [10:0] reg_end;
        logic        unused_zero;
        col_ext      = {2'b00, col};
        reg_start    = {2'b00, region.col_offset};
        reg_cols_eff = region.double_buf_en
                       ? ({1'b0, region.num_columns} << 1)
                       : {1'b0, region.num_columns};
        reg_end      = reg_start + reg_cols_eff;
        unused_zero  = &{1'b0, region};
        return !unused_zero &&
               region.allocated &&
               ({1'b0, row} < region.num_rows) &&
               (col_ext >= reg_start) &&
               (col_ext < reg_end);
    endfunction

    // -------------------------------------------------------------------------
    // SECDED Hsiao(72,64) Encode & Syndrome Helpers
    // -------------------------------------------------------------------------
    function automatic logic [TMEM_ECC_PARITY_W-1:0] tmem_ecc_parity(
        input logic [TMEM_ECC_DATA_W-1:0] data
    );
        logic [TMEM_ECC_PARITY_W-1:0] parity;
        for (int p = 0; p < TMEM_ECC_PARITY_W; ++p) begin
            parity[p] = ^(data & TMEM_HSIAO_P_MATRIX[p]);
        end
        return parity;
    endfunction

    function automatic logic [TMEM_ECC_CODE_W-1:0] tmem_ecc_encode(
        input logic [TMEM_ECC_DATA_W-1:0] data
    );
        logic [TMEM_ECC_PARITY_W-1:0] parity;
        parity = tmem_ecc_parity(data);
        return {parity, data};
    endfunction

    function automatic logic [TMEM_ECC_PARITY_W-1:0] tmem_ecc_syndrome(
        input logic [TMEM_ECC_CODE_W-1:0] codeword
    );
        logic [TMEM_ECC_DATA_W-1:0]   data;
        logic [TMEM_ECC_PARITY_W-1:0] stored_parity;
        data          = codeword[TMEM_ECC_DATA_W-1:0];
        stored_parity = codeword[TMEM_ECC_CODE_W-1:TMEM_ECC_DATA_W];
        return stored_parity ^ tmem_ecc_parity(data);
    endfunction

    function automatic logic tmem_syndrome_is_odd_weight(
        input logic [TMEM_ECC_PARITY_W-1:0] syndrome
    );
        return ^syndrome;
    endfunction

    function automatic logic tmem_geometry_consistent();
        return (TMEM_CAPACITY_BYTES == (TMEM_LANES_ROWS * TMEM_COLUMNS * TMEM_CELL_BYTES)) &&
               (TMEM_CAPACITY_BYTES == (TMEM_NUM_BANKS * TMEM_BANK_DEPTH_WORDS * TMEM_BANK_WIDTH_BYTES)) &&
               (TMEM_CELL_BITS == (TMEM_CELL_BYTES * 8)) &&
               (TMEM_COLUMNS == (TMEM_NUM_ALLOC_UNITS * TMEM_ALLOC_GRANULE_COLS)) &&
               (TMEM_MAX_REGIONS == TMEM_NUM_ALLOC_UNITS) &&
               (TMEM_READ_PORTS == 2) &&
               (TMEM_WRITE_PORTS == 1);
    endfunction

endpackage

`endif // VX_TMEM_PKG_SV

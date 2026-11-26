// Copyright (c) 2018-2026 Georgia Tech Vortex & AI-GPU Project
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

// Formal verification harness for the Gray-code CDC FIFO logic used in VX_asic_soc_top.
// Supports two formal proof modes via `ifdef FORMAL_INDUCT_ONLY:
//   - Undefined (Dual-clock async BMC): instantiates full CDC FIFO + VX_cdc_fifo_sva
//     and proves zero SVA violations, exact pointer/occupancy conservation, no write-full
//     overflow, no read-empty underflow, and bit-exact data integrity under arbitrary
//     asynchronous wclk/rclk schedules and arbitrary push/pop sequences.
//   - Defined (Unbounded k-induction): proves universally over ALL (ADDRW+1)-bit
//     symbolic pointers x that gray2bin(bin2gray(x)) == x, bin2gray(gray2bin(x)) == x,
//     consecutive Gray pointers differ in exactly 1 bit, and Gray full/empty encoding
//     never aliases.
module VX_cdc_fifo_formal #(
    parameter int ADDRW = 3,
    parameter int DATAW = 8
) (
    input  wire             wclk,
    input  wire             rclk,
    input  wire             rst_n,
    input  wire             push_req,
    input  wire [DATAW-1:0] push_data,
    input  wire             pop_req,
    input  wire [ADDRW:0]   arb_x,
    input  wire [ADDRW:0]   arb_y,

    output wire             fifo_full,
    output wire             fifo_empty,
    output wire [DATAW-1:0] pop_data,
    output wire [ADDRW:0]   wptr_gray_out,
    output wire [ADDRW:0]   rptr_gray_out
);

    localparam int DEPTH = (1 << ADDRW);
    localparam int PTR_W = ADDRW + 1;

    function automatic [PTR_W-1:0] bin2gray(input [PTR_W-1:0] b);
        bin2gray = b ^ (b >> 1);
    endfunction

    function automatic [PTR_W-1:0] gray2bin(input [PTR_W-1:0] g);
        integer i;
        reg [PTR_W-1:0] b;
        begin
            b[PTR_W-1] = g[PTR_W-1];
            for (i = PTR_W - 2; i >= 0; i = i - 1) begin
                b[i] = b[i + 1] ^ g[i];
            end
            gray2bin = b;
        end
    endfunction

    // ------------------------------------------------------------------------
    // CDC FIFO RTL (mirrors VX_asic_soc_top Gray-code async FIFO logic)
    // ------------------------------------------------------------------------
    reg [DATAW-1:0] mem [0:DEPTH-1];

    // Write clock domain
    reg [PTR_W-1:0] wptr_bin_q;
    reg [PTR_W-1:0] wptr_gray_q;
    reg [PTR_W-1:0] rptr_gray_sync1_q;
    reg [PTR_W-1:0] rptr_gray_sync2_q;

    // Read clock domain
    reg [PTR_W-1:0] rptr_bin_q;
    reg [PTR_W-1:0] rptr_gray_q;
    reg [PTR_W-1:0] wptr_gray_sync1_q;
    reg [PTR_W-1:0] wptr_gray_sync2_q;

    wire [PTR_W-1:0] wptr_bin_next  = wptr_bin_q + {{ADDRW{1'b0}}, 1'b1};
    wire [PTR_W-1:0] wptr_gray_next = wptr_bin_next ^ (wptr_bin_next >> 1);
    assign fifo_full = (wptr_gray_q == {~rptr_gray_sync2_q[ADDRW:ADDRW-1],
                                         rptr_gray_sync2_q[ADDRW-2:0]});

    wire [PTR_W-1:0] rptr_bin_next  = rptr_bin_q + {{ADDRW{1'b0}}, 1'b1};
    wire [PTR_W-1:0] rptr_gray_next = rptr_bin_next ^ (rptr_bin_next >> 1);
    assign fifo_empty = (rptr_gray_q == wptr_gray_sync2_q);

    wire w_en = push_req && !fifo_full;
    wire r_en = pop_req  && !fifo_empty;

    always @(posedge wclk or negedge rst_n) begin
        if (!rst_n) begin
            wptr_bin_q        <= {PTR_W{1'b0}};
            wptr_gray_q       <= {PTR_W{1'b0}};
            rptr_gray_sync1_q <= {PTR_W{1'b0}};
            rptr_gray_sync2_q <= {PTR_W{1'b0}};
        end else begin
            rptr_gray_sync1_q <= rptr_gray_q;
            rptr_gray_sync2_q <= rptr_gray_sync1_q;
            if (w_en) begin
                mem[wptr_bin_q[ADDRW-1:0]] <= push_data;
                wptr_bin_q                 <= wptr_bin_next;
                wptr_gray_q                <= wptr_gray_next;
            end
        end
    end

    always @(posedge rclk or negedge rst_n) begin
        if (!rst_n) begin
            rptr_bin_q        <= {PTR_W{1'b0}};
            rptr_gray_q       <= {PTR_W{1'b0}};
            wptr_gray_sync1_q <= {PTR_W{1'b0}};
            wptr_gray_sync2_q <= {PTR_W{1'b0}};
        end else begin
            wptr_gray_sync1_q <= wptr_gray_q;
            wptr_gray_sync2_q <= wptr_gray_sync1_q;
            if (r_en) begin
                rptr_bin_q  <= rptr_bin_next;
                rptr_gray_q <= rptr_gray_next;
            end
        end
    end

    assign pop_data      = mem[rptr_bin_q[ADDRW-1:0]];
    assign wptr_gray_out = wptr_gray_q;
    assign rptr_gray_out = rptr_gray_q;

`ifdef FORMAL
`ifdef FORMAL_INDUCT_ONLY
    // Unbounded k-induction proof of Gray-code bijection, 1-bit transition,
    // and full/empty encoding uniqueness over ALL 2^(ADDRW+1) pointer pairs.
    wire [PTR_W-1:0] gx0 = bin2gray(arb_x);
    wire [PTR_W-1:0] gx1 = bin2gray(arb_x + {{ADDRW{1'b0}}, 1'b1});
    wire [PTR_W-1:0] gy  = bin2gray(arb_y);
    wire [PTR_W-1:0] gdiff = gx0 ^ gx1;
    wire [PTR_W-1:0] full_gray_pattern = {~gy[ADDRW:ADDRW-1], gy[ADDRW-2:0]};

    always @(posedge wclk) begin
        // 1. Universal bijection for ALL values
        assert (gray2bin(gx0) == arb_x);
        assert (bin2gray(gray2bin(arb_x)) == arb_x);

        // 2. Consecutive Gray pointers differ in exactly 1 bit
        assert (gdiff != {PTR_W{1'b0}});
        assert ((gdiff & (gdiff - PTR_W'(1))) == {PTR_W{1'b0}});

        // 3. Gray full/empty condition equivalence to binary occupancy == DEPTH / == 0
        assert ((gx0 == gy) == (arb_x == arb_y));
        assert ((gx0 == full_gray_pattern) == ((arb_x - arb_y) == PTR_W'(DEPTH)));
        assert (!((gx0 == gy) && (gx0 == full_gray_pattern)));
    end
`else
    // Bind protocol assertion checker in full dual-clock BMC
    VX_cdc_fifo_sva #(
        .ADDRW (ADDRW)
    ) u_cdc_sva (
        .wclk            (wclk),
        .wrst_n          (rst_n),
        .w_en            (w_en),
        .w_full          (fifo_full),
        .wptr_bin        (wptr_bin_q),
        .wptr_gray       (wptr_gray_q),
        .rptr_gray_wsync (rptr_gray_sync2_q),
        .rclk            (rclk),
        .rrst_n          (rst_n),
        .r_en            (r_en),
        .r_empty         (fifo_empty),
        .rptr_bin        (rptr_bin_q),
        .rptr_gray       (rptr_gray_q),
        .wptr_gray_rsync (wptr_gray_sync2_q)
    );

    reg       f_init_done_q;
    reg [7:0] f_push_count_q;
    reg [7:0] f_pop_count_q;

    reg [DATAW-1:0] f_ref_mem [0:DEPTH-1];
    reg [PTR_W-1:0] f_ref_wptr_q;
    reg [PTR_W-1:0] f_ref_rptr_q;

    initial begin
        f_init_done_q  = 1'b0;
        f_push_count_q = 8'd0;
        f_pop_count_q  = 8'd0;
        f_ref_wptr_q   = {PTR_W{1'b0}};
        f_ref_rptr_q   = {PTR_W{1'b0}};
    end

    always @(posedge wclk or negedge rst_n) begin
        if (!rst_n) begin
            f_ref_wptr_q   <= {PTR_W{1'b0}};
            f_push_count_q <= 8'd0;
        end else if (w_en) begin
            f_ref_mem[f_ref_wptr_q[ADDRW-1:0]] <= push_data;
            f_ref_wptr_q   <= f_ref_wptr_q + PTR_W'(1);
            f_push_count_q <= f_push_count_q + 8'd1;
        end
    end

    always @(posedge rclk or negedge rst_n) begin
        if (!rst_n) begin
            f_ref_rptr_q  <= {PTR_W{1'b0}};
            f_pop_count_q <= 8'd0;
        end else if (r_en) begin
            f_ref_rptr_q  <= f_ref_rptr_q + PTR_W'(1);
            f_pop_count_q <= f_pop_count_q + 8'd1;
        end
    end

    always @($global_clock) begin
        if (!f_init_done_q) begin
            assume (!rst_n);
            assume (!wclk);
            assume (!rclk);
            f_init_done_q <= 1'b1;
        end else begin
            assume (rst_n);
        end

        // Algebraic Gray properties
        assert (gray2bin(bin2gray(arb_x)) == arb_x);
        assert (bin2gray(gray2bin(arb_x)) == arb_x);

        if (f_init_done_q && rst_n) begin
            // Exact pointer and occupancy conservation
            assert (wptr_bin_q == f_ref_wptr_q);
            assert (rptr_bin_q == f_ref_rptr_q);
            assert ((wptr_bin_q - rptr_bin_q) <= PTR_W'(DEPTH));
            assert ((f_push_count_q - f_pop_count_q) == (8'(wptr_bin_q - rptr_bin_q)));

            // Full/empty safety
            if ((wptr_bin_q - rptr_bin_q) == PTR_W'(DEPTH)) begin
                assert (fifo_full);
            end
            if (wptr_bin_q == rptr_bin_q) begin
                assert (fifo_empty);
            end
            assert (!(fifo_full && fifo_empty));

            // Data integrity
            if (wptr_bin_q != rptr_bin_q) begin
                assert (pop_data == f_ref_mem[f_ref_rptr_q[ADDRW-1:0]]);
            end
        end
    end
`endif
`endif

endmodule

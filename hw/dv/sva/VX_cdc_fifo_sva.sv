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

// Dual-flow (Verilator + Yosys) protocol checker for dual-clock Gray-code
// asynchronous CDC FIFOs: verifies Gray 1-bit transition invariant, no write-when-full
// overflow/corruption, no read-when-empty underflow, binary/Gray consistency,
// and global push/pop FIFO occupancy conservation across domains.
module VX_cdc_fifo_sva #(
    parameter int ADDRW = 3
) (
    // Write clock domain
    input  wire             wclk,
    input  wire             wrst_n,
    input  wire             w_en,
    input  wire             w_full,
    input  wire [ADDRW:0]   wptr_bin,
    input  wire [ADDRW:0]   wptr_gray,
    input  wire [ADDRW:0]   rptr_gray_wsync,

    // Read clock domain
    input  wire             rclk,
    input  wire             rrst_n,
    input  wire             r_en,
    input  wire             r_empty,
    input  wire [ADDRW:0]   rptr_bin,
    input  wire [ADDRW:0]   rptr_gray,
    input  wire [ADDRW:0]   wptr_gray_rsync
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
    // Write-domain monitor (wclk)
    // ------------------------------------------------------------------------
    reg             w_prev_valid_q;
    reg             w_prev_rst_n_q;
    reg [PTR_W-1:0] w_prev_bin_q;
    reg [PTR_W-1:0] w_prev_gray_q;
    reg             w_prev_en_q;
    reg             w_prev_full_q;

    wire [PTR_W-1:0] w_gray_diff = wptr_gray ^ w_prev_gray_q;
    wire             w_gray_one_bit = ((w_gray_diff & (w_gray_diff - PTR_W'(1))) == {PTR_W{1'b0}});
    wire             w_bin_gray_eq  = (wptr_gray == bin2gray(wptr_bin));
    wire             w_gray_bin_eq  = (gray2bin(wptr_gray) == wptr_bin);
    wire             w_full_expected = (wptr_gray == {~rptr_gray_wsync[ADDRW:ADDRW-1],
                                                      rptr_gray_wsync[ADDRW-2:0]});

    wire w_check_en = wrst_n && w_prev_valid_q && w_prev_rst_n_q;

`ifdef FORMAL
    initial w_prev_valid_q = 1'b0;
`endif

    always @(posedge wclk) begin
        if (!wrst_n) begin
            w_prev_valid_q <= 1'b0;
            w_prev_rst_n_q <= 1'b0;
            w_prev_bin_q   <= {PTR_W{1'b0}};
            w_prev_gray_q  <= {PTR_W{1'b0}};
            w_prev_en_q    <= 1'b0;
            w_prev_full_q  <= 1'b0;
        end else begin
            w_prev_valid_q <= 1'b1;
            w_prev_rst_n_q <= wrst_n;
            w_prev_bin_q   <= wptr_bin;
            w_prev_gray_q  <= wptr_gray;
            w_prev_en_q    <= w_en;
            w_prev_full_q  <= w_full;
        end
    end

    // ------------------------------------------------------------------------
    // Read-domain monitor (rclk)
    // ------------------------------------------------------------------------
    reg             r_prev_valid_q;
    reg             r_prev_rst_n_q;
    reg [PTR_W-1:0] r_prev_bin_q;
    reg [PTR_W-1:0] r_prev_gray_q;
    reg             r_prev_en_q;
    reg             r_prev_empty_q;

    wire [PTR_W-1:0] r_gray_diff = rptr_gray ^ r_prev_gray_q;
    wire             r_gray_one_bit = ((r_gray_diff & (r_gray_diff - PTR_W'(1))) == {PTR_W{1'b0}});
    wire             r_bin_gray_eq  = (rptr_gray == bin2gray(rptr_bin));
    wire             r_gray_bin_eq  = (gray2bin(rptr_gray) == rptr_bin);
    wire             r_empty_expected = (rptr_gray == wptr_gray_rsync);

    wire r_check_en = rrst_n && r_prev_valid_q && r_prev_rst_n_q;

`ifdef FORMAL
    initial r_prev_valid_q = 1'b0;
`endif

    always @(posedge rclk) begin
        if (!rrst_n) begin
            r_prev_valid_q <= 1'b0;
            r_prev_rst_n_q <= 1'b0;
            r_prev_bin_q   <= {PTR_W{1'b0}};
            r_prev_gray_q  <= {PTR_W{1'b0}};
            r_prev_en_q    <= 1'b0;
            r_prev_empty_q <= 1'b1;
        end else begin
            r_prev_valid_q <= 1'b1;
            r_prev_rst_n_q <= rrst_n;
            r_prev_bin_q   <= rptr_bin;
            r_prev_gray_q  <= rptr_gray;
            r_prev_en_q    <= r_en;
            r_prev_empty_q <= r_empty;
        end
    end

    // ------------------------------------------------------------------------
    // Global FIFO occupancy conservation (exact true pointer difference)
    // ------------------------------------------------------------------------
    wire [PTR_W-1:0] true_occupancy = wptr_bin - rptr_bin;
    wire             occ_in_range   = (true_occupancy <= PTR_W'(DEPTH));
    wire             w_sync_in_range = ((wptr_bin - gray2bin(rptr_gray_wsync)) <= PTR_W'(DEPTH));
    wire             r_sync_in_range = ((gray2bin(wptr_gray_rsync) - rptr_bin) <= PTR_W'(DEPTH));

`ifndef SYNTHESIS
`ifdef FORMAL
    always @(posedge wclk) begin
        if (w_check_en) begin
            assert (w_bin_gray_eq);
            assert (w_gray_bin_eq);
            assert (w_gray_one_bit);
            assert (w_full == w_full_expected);
            assert (!(w_en && w_full));
            assert (!w_prev_en_q || !w_prev_full_q);
            if (w_prev_en_q && !w_prev_full_q) begin
                assert (wptr_bin == (w_prev_bin_q + PTR_W'(1)));
            end else if (!w_prev_en_q) begin
                assert (wptr_bin == w_prev_bin_q);
            end
            assert (occ_in_range);
        end
    end

    always @(posedge rclk) begin
        if (r_check_en) begin
            assert (r_bin_gray_eq);
            assert (r_gray_bin_eq);
            assert (r_gray_one_bit);
            assert (r_empty == r_empty_expected);
            assert (!(r_en && r_empty));
            assert (!r_prev_en_q || !r_prev_empty_q);
            if (r_prev_en_q && !r_prev_empty_q) begin
                assert (rptr_bin == (r_prev_bin_q + PTR_W'(1)));
            end else if (!r_prev_en_q) begin
                assert (rptr_bin == r_prev_bin_q);
            end
            assert (occ_in_range);
        end
    end
`else
    // Write-domain concurrent SVA properties
    property p_w_known;
        @(posedge wclk) disable iff (!wrst_n)
        (!$isunknown({w_en, w_full, wptr_bin, wptr_gray, rptr_gray_wsync}));
    endproperty
    a_w_known: assert property (p_w_known)
        else $error("VX_cdc_fifo_sva: X/Z on write-domain CDC signals");

    property p_w_gray_encoding;
        @(posedge wclk) disable iff (!wrst_n)
        (w_bin_gray_eq && w_gray_bin_eq);
    endproperty
    a_w_gray_encoding: assert property (p_w_gray_encoding)
        else $error("VX_cdc_fifo_sva: write Gray/binary pointer mismatch bin=0x%0h gray=0x%0h", wptr_bin, wptr_gray);

    property p_w_gray_1bit;
        @(posedge wclk) disable iff (!wrst_n)
        w_check_en |-> w_gray_one_bit;
    endproperty
    a_w_gray_1bit: assert property (p_w_gray_1bit)
        else $error("VX_cdc_fifo_sva: write Gray pointer changed >1 bit: 0x%0h -> 0x%0h", w_prev_gray_q, wptr_gray);

    property p_w_no_write_when_full;
        @(posedge wclk) disable iff (!wrst_n)
        !(w_en && w_full);
    endproperty
    a_w_no_write_when_full: assert property (p_w_no_write_when_full)
        else $error("VX_cdc_fifo_sva: write attempted while CDC FIFO full (wptr=0x%0h)", wptr_gray);

    property p_w_full_flag_exact;
        @(posedge wclk) disable iff (!wrst_n)
        (w_full == w_full_expected);
    endproperty
    a_w_full_flag_exact: assert property (p_w_full_flag_exact)
        else $error("VX_cdc_fifo_sva: w_full mismatch got=%b exp=%b", w_full, w_full_expected);

    property p_w_occ_conservation;
        @(posedge wclk) disable iff (!wrst_n)
        (occ_in_range && w_sync_in_range);
    endproperty
    a_w_occ_conservation: assert property (p_w_occ_conservation)
        else $error("VX_cdc_fifo_sva: write-side FIFO occupancy out of bounds (%0d > %0d)", true_occupancy, DEPTH);

    // Read-domain concurrent SVA properties
    property p_r_known;
        @(posedge rclk) disable iff (!rrst_n)
        (!$isunknown({r_en, r_empty, rptr_bin, rptr_gray, wptr_gray_rsync}));
    endproperty
    a_r_known: assert property (p_r_known)
        else $error("VX_cdc_fifo_sva: X/Z on read-domain CDC signals");

    property p_r_gray_encoding;
        @(posedge rclk) disable iff (!rrst_n)
        (r_bin_gray_eq && r_gray_bin_eq);
    endproperty
    a_r_gray_encoding: assert property (p_r_gray_encoding)
        else $error("VX_cdc_fifo_sva: read Gray/binary pointer mismatch bin=0x%0h gray=0x%0h", rptr_bin, rptr_gray);

    property p_r_gray_1bit;
        @(posedge rclk) disable iff (!rrst_n)
        r_check_en |-> r_gray_one_bit;
    endproperty
    a_r_gray_1bit: assert property (p_r_gray_1bit)
        else $error("VX_cdc_fifo_sva: read Gray pointer changed >1 bit: 0x%0h -> 0x%0h", r_prev_gray_q, rptr_gray);

    property p_r_no_read_when_empty;
        @(posedge rclk) disable iff (!rrst_n)
        !(r_en && r_empty);
    endproperty
    a_r_no_read_when_empty: assert property (p_r_no_read_when_empty)
        else $error("VX_cdc_fifo_sva: read attempted while CDC FIFO empty (rptr=0x%0h)", rptr_gray);

    property p_r_empty_flag_exact;
        @(posedge rclk) disable iff (!rrst_n)
        (r_empty == r_empty_expected);
    endproperty
    a_r_empty_flag_exact: assert property (p_r_empty_flag_exact)
        else $error("VX_cdc_fifo_sva: r_empty mismatch got=%b exp=%b", r_empty, r_empty_expected);

    property p_r_occ_conservation;
        @(posedge rclk) disable iff (!rrst_n)
        (occ_in_range && r_sync_in_range);
    endproperty
    a_r_occ_conservation: assert property (p_r_occ_conservation)
        else $error("VX_cdc_fifo_sva: read-side FIFO occupancy out of bounds (%0d > %0d)", true_occupancy, DEPTH);
`endif
`endif

    wire _unused_ok = &{1'b0,
                        w_check_en,
                        r_check_en,
                        w_gray_one_bit,
                        r_gray_one_bit,
                        w_bin_gray_eq,
                        w_gray_bin_eq,
                        r_bin_gray_eq,
                        r_gray_bin_eq,
                        w_full_expected,
                        r_empty_expected,
                        occ_in_range,
                        w_sync_in_range,
                        r_sync_in_range,
                        w_prev_bin_q,
                        w_prev_en_q,
                        w_prev_full_q,
                        r_prev_bin_q,
                        r_prev_en_q,
                        r_prev_empty_q};

endmodule

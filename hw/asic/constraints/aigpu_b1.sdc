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

# =============================================================================
# AI-GPU B1 Multi-Clock ASIC SDC Timing Constraints
# =============================================================================
# Synopsys PrimeTime / Design Compiler & OpenSTA 3.1.0 compliant constraint deck.
#
# Clock domains:
#   1. clk_core : 2.000 GHz (0.500 ns) - Compute cores, TCU, local SRAM, caches
#   2. clk_axi  : 1.000 GHz (1.000 ns) - AXI4-Full HBM/NoC & AXI4-Lite CSR/SRAM
#   3. clk_pcie : 500.0 MHz (2.000 ns) - PCIe Gen5 x16 endpoint / DXA DMA shell
#   4. tck      : 50.00 MHz (20.00 ns) - IEEE-1149.1 JTAG TAP & MBIST/DFT
#
# Target technology assumptions: TSMC N4P / N3E pre-PDK synthesis & STA budget.
# Parameterizable primary core period via CORE_PERIOD prior to sourcing.

# Units match target technology library (Synopsys DC/PT default ns/pF; OpenSTA uses read_liberty units)
if {![info exists SKIP_SET_UNITS]} {
    # Set only if liberty uses matching scale; default Nangate uses fF while foundry PDK uses pF
}

# -----------------------------------------------------------------------------
# 1. Clock Definitions (override CORE_PERIOD / AXI_PERIOD externally if needed)
# -----------------------------------------------------------------------------
if {![info exists CORE_PERIOD]} { set CORE_PERIOD 0.500 }
if {![info exists AXI_PERIOD]}  { set AXI_PERIOD  1.000 }
if {![info exists PCIE_PERIOD]} { set PCIE_PERIOD 2.000 }
if {![info exists TCK_PERIOD]}  { set TCK_PERIOD  20.000 }

# Core compute clock (real port)
set core_clk_ports [get_ports -quiet clk_core]
if {[llength $core_clk_ports] > 0} {
    create_clock -name clk_core -period $CORE_PERIOD \
        -waveform [list 0.0 [expr {$CORE_PERIOD * 0.5}]] $core_clk_ports
} else {
    create_clock -name clk_core -period $CORE_PERIOD
}

# HBM / AXI interconnect & always-on CSR clock (real port)
set axi_clk_ports [get_ports -quiet clk_axi]
if {[llength $axi_clk_ports] > 0} {
    create_clock -name clk_axi -period $AXI_PERIOD \
        -waveform [list 0.0 [expr {$AXI_PERIOD * 0.5}]] $axi_clk_ports
} else {
    create_clock -name clk_axi -period $AXI_PERIOD
}

# PCIe / DXA host-interface clock (physical port on full chip, virtual on SoC shell)
set pcie_clk_ports [get_ports -quiet clk_pcie]
if {[llength $pcie_clk_ports] > 0} {
    create_clock -name clk_pcie -period $PCIE_PERIOD \
        -waveform [list 0.0 [expr {$PCIE_PERIOD * 0.5}]] $pcie_clk_ports
} else {
    create_clock -name clk_pcie -period $PCIE_PERIOD
}

# IEEE-1149.1 JTAG test clock (real port)
set jtag_clk_ports [get_ports -quiet tck]
if {[llength $jtag_clk_ports] > 0} {
    create_clock -name tck -period $TCK_PERIOD \
        -waveform [list 0.0 [expr {$TCK_PERIOD * 0.5}]] $jtag_clk_ports
} else {
    create_clock -name tck -period $TCK_PERIOD
}

# Clock uncertainty (pre-CTS setup jitter + skew margin, hold margin) and transition
if {[llength $core_clk_ports] > 0} { set_clock_transition 0.040 [get_clocks clk_core] }
set_clock_uncertainty -setup [expr {0.06 * $CORE_PERIOD}] [get_clocks clk_core]
set_clock_uncertainty -hold  0.020                       [get_clocks clk_core]

if {[llength $axi_clk_ports] > 0}  { set_clock_transition 0.060 [get_clocks clk_axi] }
set_clock_uncertainty -setup [expr {0.05 * $AXI_PERIOD}]  [get_clocks clk_axi]
set_clock_uncertainty -hold  0.025                       [get_clocks clk_axi]

if {[llength $pcie_clk_ports] > 0} { set_clock_transition 0.080 [get_clocks clk_pcie] }
set_clock_uncertainty -setup [expr {0.05 * $PCIE_PERIOD}] [get_clocks clk_pcie]
set_clock_uncertainty -hold  0.030                       [get_clocks clk_pcie]

if {[llength $jtag_clk_ports] > 0} { set_clock_transition 0.200 [get_clocks tck] }
set_clock_uncertainty -setup 0.500                       [get_clocks tck]
set_clock_uncertainty -hold  0.100                       [get_clocks tck]

# -----------------------------------------------------------------------------
# 2. Asynchronous Clock Domain Groupings
# -----------------------------------------------------------------------------
set_clock_groups -asynchronous \
    -group [get_clocks clk_core] \
    -group [get_clocks clk_axi] \
    -group [get_clocks clk_pcie] \
    -group [get_clocks tck]

# -----------------------------------------------------------------------------
# 3. Asynchronous Reset False Paths & Static DFT/Power Control Exceptions
# -----------------------------------------------------------------------------
foreach rst_name {rst_n trst_n por_n} {
    set rst_p [get_ports -quiet $rst_name]
    if {[llength $rst_p] > 0} {
        set_input_delay -clock [get_clocks tck] -max 2.000 $rst_p
        set_input_delay -clock [get_clocks tck] -min 0.000 $rst_p
        set_false_path -from $rst_p
    }
}

# Static test-mode & JTAG-to-functional control configurations
foreach dft_port {test_mode_pin scan_enable_pin scan_in*} {
    set dp [get_ports -quiet $dft_port]
    if {[llength $dp] > 0} {
        set_input_delay -clock [get_clocks tck] -max 2.000 $dp
        set_input_delay -clock [get_clocks tck] -min 0.000 $dp
        set_false_path -from $dp
    }
}

# Helper: resolve leaf sequential driver cells anchored on kept RTL net names so
# constraints continue to match after synthesis renames or flattens flop cells.
# Accepts one or more net patterns and an optional hierarchical pin fallback
# for aliased output-port / submodule-boundary nets.
proc _aigpu_reg_cells_by_net {net_pats {hier_pin_pat ""}} {
    set nets [get_nets -quiet -hierarchical $net_pats]
    if {[llength $nets] > 0} {
        set drv_pins [get_pins -quiet -of_objects $nets -filter "direction == output"]
        if {[llength $drv_pins] > 0} {
            set leaf_cells [get_cells -quiet -of_objects $drv_pins -filter "is_hierarchical == false"]
            if {[llength $leaf_cells] > 0} {
                return $leaf_cells
            }
        }
    }
    if {$hier_pin_pat ne ""} {
        set hpins [get_pins -quiet $hier_pin_pat]
        if {[llength $hpins] > 0} {
            return [get_fanin -to $hpins -flat -only_cells -startpoints_only]
        }
    }
    return {}
}

proc _aigpu_set_cdc_max_delay {delay_val src_net_pats dst_net_pats {src_hier_pin ""} {dst_hier_pin ""}} {
    set s_cells [_aigpu_reg_cells_by_net $src_net_pats $src_hier_pin]
    set d_cells [_aigpu_reg_cells_by_net $dst_net_pats $dst_hier_pin]
    if {[llength $s_cells] > 0 && [llength $d_cells] > 0} {
        if {[catch {set_max_delay -datapath_only $delay_val -from $s_cells -to $d_cells}]} {
            set_max_delay -ignore_clock_latency $delay_val -from $s_cells -to $d_cells
        }
        return [list [llength $s_cells] [llength $d_cells]]
    }
    return {0 0}
}

set u_dft_scan [_aigpu_reg_cells_by_net *scan_ctrl_q* u_dft/dft_*]
if {[llength $u_dft_scan] > 0} {
    set static_dft_outs [get_ports -quiet {dft_scan_enable dft_test_mode dft_cg_override}]
    if {[llength $static_dft_outs] > 0} {
        set_false_path -from $u_dft_scan -to $static_dft_outs
    }
}
set u_dft_pwr [_aigpu_reg_cells_by_net {*pwr_ctrl_q*} u_dft/pwr_clust_*]
if {[llength $u_dft_pwr] > 0} {
    set static_pwr_outs [get_ports -quiet {pwr_clust_*}]
    if {[llength $static_pwr_outs] > 0} {
        set_false_path -from $u_dft_pwr -to $static_pwr_outs
    }
}

# Reset-synchronizer first-stage recovery is governed by async false path above;
# inter-stage flop Q->D remains synchronously timed within each clock domain.

# -----------------------------------------------------------------------------
# 4. CDC Gray-Code Pointer & Synchronizer Max-Delay Skew Constraints
# -----------------------------------------------------------------------------
# Bound datapath skew across Gray-code pointer registers to <= 1 destination
# clock period (min(CORE_PERIOD, AXI_PERIOD) = CORE_PERIOD) so multi-bit Gray
# vectors cannot experience >1-bit skew across asynchronous clock edges.

set cdc_skew_budget $CORE_PERIOD

# Command FIFO: clk_axi write pointer -> clk_core sync stage 1
_aigpu_set_cdc_max_delay $cdc_skew_budget *cmd_wptr_gray_q* *cmd_wptr_gray_sync1_q*

# Command FIFO: clk_core read pointer -> clk_axi sync stage 1
_aigpu_set_cdc_max_delay $cdc_skew_budget *cmd_rptr_gray_q* *cmd_rptr_gray_sync1_q*

# Telemetry/HBM Response FIFO: clk_core write pointer -> clk_axi sync stage 1
_aigpu_set_cdc_max_delay $cdc_skew_budget *rsp_wptr_gray_q* *rsp_wptr_gray_sync1_q*

# Telemetry/HBM Response FIFO: clk_axi read pointer -> clk_core sync stage 1
_aigpu_set_cdc_max_delay $cdc_skew_budget *rsp_rptr_gray_q* *rsp_rptr_gray_sync1_q*

# Quasi-static FIFO payload & toggle-handshake snapshot registers: bound datapath skew
_aigpu_set_cdc_max_delay $AXI_PERIOD *cmd_fifo_mem* *active_cmd_q*
_aigpu_set_cdc_max_delay $AXI_PERIOD *cmd_fifo_mem* *core_rem_cycles_q*
_aigpu_set_cdc_max_delay $AXI_PERIOD *rsp_fifo_mem* {*axi_req_* *m_axi_araddr* *m_axi_wdata*}
_aigpu_set_cdc_max_delay $AXI_PERIOD *rsp_fifo_mem* *completed_cnt_q*
_aigpu_set_cdc_max_delay $AXI_PERIOD *cycle_snap_*  *cycle_cnt_axi_q*

# Single-bit and 2-FF control/telemetry/JTAG synchronizer 1st stages (bound flight time)
_aigpu_set_cdc_max_delay $AXI_PERIOD *core_busy_q*           *core_busy_sync1_q*
_aigpu_set_cdc_max_delay $AXI_PERIOD *soft_reset_q*          *soft_rst_core_sync1_q*
_aigpu_set_cdc_max_delay $AXI_PERIOD *thermal_throttle_en_q* *throttle_core_sync1_q*
_aigpu_set_cdc_max_delay $AXI_PERIOD *cycle_req_axi_q*       *cycle_req_core_sync1_q*
_aigpu_set_cdc_max_delay $AXI_PERIOD *cycle_ack_core_q*      *cycle_ack_axi_sync1_q*
_aigpu_set_cdc_max_delay $AXI_PERIOD *mbist_ctrl_q*          *mbist_run_sync1_q*    u_dft/mbist_run
_aigpu_set_cdc_max_delay $AXI_PERIOD *mbist_ctrl_q*          *mbist_ret_sync1_q*    u_dft/mbist_retention_mode
_aigpu_set_cdc_max_delay $AXI_PERIOD *mbist_done_q*          *mbist_done_tck_sync1_q*
_aigpu_set_cdc_max_delay $AXI_PERIOD *mbist_fail_q*          *mbist_fail_tck_sync1_q*
_aigpu_set_cdc_max_delay $AXI_PERIOD *scan_ctrl_q*           *dft_test_mode_sync1_q* u_dft/dft_test_mode
_aigpu_set_cdc_max_delay $AXI_PERIOD *pwr_ctrl_q*            *dft_pwr_en_sync1_q*    u_dft/pwr_clust_en*
_aigpu_set_cdc_max_delay $AXI_PERIOD *pwr_ctrl_q*            *dft_pwr_iso_sync1_q*   u_dft/pwr_clust_iso_en*
_aigpu_set_cdc_max_delay $AXI_PERIOD *pwr_ctrl_q*            *dft_pwr_ret_sync1_q*   u_dft/pwr_clust_ret_en*

# -----------------------------------------------------------------------------
# 5. Interface I/O Timing Budgets & Design Rule Limits
# -----------------------------------------------------------------------------
# AXI4-Lite CSR & AXI4-Full HBM I/O interfaces synchronous to clk_axi
set axi_io_in_max  [expr {0.35 * $AXI_PERIOD}]
set axi_io_in_min  [expr {0.05 * $AXI_PERIOD}]
set axi_io_out_max [expr {0.35 * $AXI_PERIOD}]
set axi_io_out_min [expr {-0.05 * $AXI_PERIOD}]

set axi_in_ports [get_ports -quiet {s_axil_awvalid s_axil_awaddr* s_axil_awprot* s_axil_wvalid s_axil_wdata* s_axil_wstrb* s_axil_bready s_axil_arvalid s_axil_araddr* s_axil_arprot* s_axil_rready m_axi_awready m_axi_wready m_axi_bvalid m_axi_bid* m_axi_bresp* m_axi_arready m_axi_rvalid m_axi_rid* m_axi_rdata* m_axi_rresp* m_axi_rlast}]
if {[llength $axi_in_ports] > 0} {
    set_input_delay  -clock [get_clocks clk_axi] -max $axi_io_in_max  $axi_in_ports
    set_input_delay  -clock [get_clocks clk_axi] -min $axi_io_in_min  $axi_in_ports
}

set axi_out_ports [get_ports -quiet {s_axil_awready s_axil_wready s_axil_bvalid s_axil_bresp* s_axil_arready s_axil_rvalid s_axil_rdata* s_axil_rresp* m_axi_awvalid m_axi_awid* m_axi_awaddr* m_axi_awlen* m_axi_awsize* m_axi_awburst* m_axi_awlock m_axi_awcache* m_axi_awprot* m_axi_awqos* m_axi_wvalid m_axi_wdata* m_axi_wstrb* m_axi_wlast m_axi_bready m_axi_arvalid m_axi_arid* m_axi_araddr* m_axi_arlen* m_axi_arsize* m_axi_arburst* m_axi_arlock m_axi_arcache* m_axi_arprot* m_axi_arqos* m_axi_rready irq}]
if {[llength $axi_out_ports] > 0} {
    set_output_delay -clock [get_clocks clk_axi] -max $axi_io_out_max $axi_out_ports
    set_output_delay -clock [get_clocks clk_axi] -min $axi_io_out_min $axi_out_ports
}

# JTAG IEEE-1149.1 I/O delays relative to tck (TMS/TDI sampled on posedge, TDO updated on negedge)
set jtag_in_ports [get_ports -quiet {tms tdi}]
if {[llength $jtag_in_ports] > 0} {
    set_input_delay  -clock [get_clocks tck] -max [expr {0.25 * $TCK_PERIOD}] $jtag_in_ports
    set_input_delay  -clock [get_clocks tck] -min 0.200                      $jtag_in_ports
}
set jtag_out_ports [get_ports -quiet {tdo tdo_oe_n scan_out*}]
if {[llength $jtag_out_ports] > 0} {
    set_output_delay -clock [get_clocks tck] -clock_fall -max [expr {0.25 * $TCK_PERIOD}] $jtag_out_ports
    set_output_delay -clock [get_clocks tck] -clock_fall -min -0.100                      $jtag_out_ports
}

# Power-domain / DFT control outputs (quasi-static / asynchronous interface)
set ctrl_out_ports [get_ports -quiet {pwr_clust_* dft_*}]
if {[llength $ctrl_out_ports] > 0} {
    set_output_delay -clock [get_clocks tck] -max 2.000 $ctrl_out_ports
    set_output_delay -clock [get_clocks tck] -min 0.000 $ctrl_out_ports
}

# Global design rule budgets (DRC / capacitive load / slew)
set_max_transition 0.120 [current_design]
set_max_fanout     32    [current_design]
set_input_transition 0.050 [all_inputs]
set_load             0.025 [all_outputs]

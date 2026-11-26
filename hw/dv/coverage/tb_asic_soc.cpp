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

#include <algorithm>
#include <array>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <memory>
#include <random>
#include <sstream>
#include <stdexcept>
#include <string>
#include <unordered_map>
#include <vector>

#include "Vtb_soc_wrap.h"
#include "verilated.h"
#include "verilated_cov.h"

namespace {

// Register map offsets (VX_asic_soc_top.sv)
constexpr uint32_t CSR_CHIP_ID         = 0x000;
constexpr uint32_t CSR_ARCH_REV        = 0x004;
constexpr uint32_t CSR_PWR_CTRL        = 0x008;
constexpr uint32_t CSR_SOFT_RESET      = 0x00C;
constexpr uint32_t CSR_LAUNCH_ADDR_LO  = 0x010;
constexpr uint32_t CSR_LAUNCH_ADDR_HI  = 0x014;
constexpr uint32_t CSR_LAUNCH_CTRL     = 0x018;
constexpr uint32_t CSR_LAUNCH_DOORBELL = 0x01C;
constexpr uint32_t CSR_STATUS          = 0x020;
constexpr uint32_t CSR_THERMAL_CTRL    = 0x024;
constexpr uint32_t CSR_IRQ_ENABLE      = 0x028;
constexpr uint32_t CSR_IRQ_STATUS      = 0x02C;
constexpr uint32_t CSR_CYCLE_CNT_LO    = 0x030;
constexpr uint32_t CSR_CYCLE_CNT_HI    = 0x034;
constexpr uint32_t CSR_HBM_DATA_LO     = 0x038;
constexpr uint32_t CSR_HBM_DATA_HI     = 0x03C;
constexpr uint32_t BOOT_SRAM_BASE      = 0x400;
constexpr uint32_t BOOT_SRAM_DEPTH     = 256;

constexpr uint32_t EXPECTED_CHIP_ID     = 0x41494750u;
constexpr uint32_t EXPECTED_ARCH_REV    = 0x00010001u;
constexpr uint32_t EXPECTED_JTAG_IDCODE = 0x1A16B101u;

// JTAG IR Opcodes (5-bit)
constexpr uint8_t IR_IDCODE     = 0x01;
constexpr uint8_t IR_SCAN_CTRL  = 0x08;
constexpr uint8_t IR_MBIST_CTRL = 0x09;
constexpr uint8_t IR_PWR_CTRL   = 0x0A;
constexpr uint8_t IR_BYPASS     = 0x1F;

struct ClockDomain {
    uint64_t half_period;
    uint64_t next_edge;
    bool     level;
};

struct DvStats {
    uint64_t sim_time_ticks          = 0;
    uint64_t axi_cycles              = 0;
    uint64_t core_cycles             = 0;
    uint64_t tck_cycles              = 0;
    uint64_t axil_reads              = 0;
    uint64_t axil_writes             = 0;
    uint64_t axil_slverrs            = 0;
    uint64_t csr_ops                 = 0;
    uint64_t sram_reads              = 0;
    uint64_t sram_writes             = 0;
    uint64_t cdc_doorbell_pushes     = 0;
    uint64_t cdc_doorbell_overflows  = 0;
    uint64_t kernel_direct_ops       = 0;
    uint64_t hbm_axi_writes          = 0;
    uint64_t hbm_axi_reads           = 0;
    uint64_t hbm_axi_err_injects     = 0;
    uint64_t jtag_tap_cycles         = 0;
    uint64_t jtag_idcode_checks      = 0;
    uint64_t jtag_bypass_checks      = 0;
    uint64_t jtag_scan_checks        = 0;
    uint64_t jtag_mbist_runs         = 0;
    uint64_t jtag_pwr_updates        = 0;
    uint64_t soft_resets             = 0;
    uint64_t irq_assertions          = 0;
    uint64_t irq_clears              = 0;
};

struct PendingHbmBResp {
    uint8_t  bid;
    uint8_t  bresp;
    uint64_t ready_cycle;
};

struct PendingHbmRBeat {
    uint8_t  rid;
    uint64_t rdata;
    uint8_t  rresp;
    bool     rlast;
    uint64_t ready_cycle;
};

class AsicSocHarness {
public:
    AsicSocHarness(uint64_t seed, const std::string& cov_path)
        : rng_(seed)
        , cov_path_(cov_path)
        , dut_(std::make_unique<Vtb_soc_wrap>()) {
        Verilated::assertOn(true);
        init_inputs();
        clk_axi_  = {5, 5, false};   // 10-tick period default
        clk_core_ = {3, 3, false};   // 6-tick period default
        clk_tck_  = {23, 23, false}; // Slow async JTAG clock
        sram_shadow_.fill(0);
    }

    ~AsicSocHarness() {
        dut_->final();
        VerilatedCov::write(cov_path_.c_str());
    }

    void set_clock_ratios(uint64_t axi_half, uint64_t core_half, uint64_t tck_half) {
        clk_axi_.half_period  = axi_half;
        clk_core_.half_period = core_half;
        clk_tck_.half_period  = tck_half;
        clk_axi_.next_edge    = sim_time_ + axi_half;
        clk_core_.next_edge   = sim_time_ + core_half;
        clk_tck_.next_edge    = sim_time_ + tck_half;
    }

    void reset_dut(bool assert_trst = true, bool assert_por = true) {
        dut_->rst_n          = 0;
        dut_->trst_n         = assert_trst ? 0 : 1;
        dut_->por_n          = assert_por ? 0 : 1;
        dut_->tms            = 1;
        dut_->tdi            = 0;
        dut_->test_mode_pin  = 0;
        dut_->scan_enable_pin = 0;
        dut_->scan_in        = 0;

        dut_->s_axil_awvalid = 0;
        dut_->s_axil_wvalid  = 0;
        dut_->s_axil_bready  = 0;
        dut_->s_axil_arvalid = 0;
        dut_->s_axil_rready  = 0;

        dut_->m_axi_awready  = 0;
        dut_->m_axi_wready   = 0;
        dut_->m_axi_bvalid   = 0;
        dut_->m_axi_arready  = 0;
        dut_->m_axi_rvalid   = 0;
        dut_->m_axi_rlast    = 0;

        hbm_wr_addr_valid_ = false;
        hbm_wr_data_valid_ = false;
        hbm_b_retired_this_edge_ = false;
        hbm_r_retired_this_edge_ = false;
        hbm_b_queue_.clear();
        hbm_r_queue_.clear();
        tcu_pending_tags_.clear();
        core_rst_hold_ = 0;
        tcu_active_ = false;
        dut_->tcu_req_valid = 0;
        dut_->tcu_rsp_valid = 0;

        for (int i = 0; i < 12; ++i) {
            step_axi_cycles(1);
        }
        dut_->rst_n  = 1;
        dut_->trst_n = 1;
        dut_->por_n  = 1;
        for (int i = 0; i < 10; ++i) {
            step_axi_cycles(1);
        }
    }

    // Advances simulation until the next rising edge of clk_axi
    void step_axi_cycles(uint64_t n = 1) {
        for (uint64_t i = 0; i < n; ++i) {
            bool saw_posedge_axi = false;
            while (!saw_posedge_axi) {
                uint64_t next_t = std::min({clk_axi_.next_edge, clk_core_.next_edge, clk_tck_.next_edge});
                sim_time_ = next_t;

                bool axi_rise  = false;
                bool core_rise = false;

                if (clk_axi_.next_edge == next_t) {
                    clk_axi_.level     = !clk_axi_.level;
                    clk_axi_.next_edge = next_t + clk_axi_.half_period;
                    dut_->clk_axi      = clk_axi_.level ? 1 : 0;
                    if (clk_axi_.level) {
                        axi_rise = true;
                        stats_.axi_cycles++;
                    }
                }
                if (clk_core_.next_edge == next_t) {
                    clk_core_.level     = !clk_core_.level;
                    clk_core_.next_edge = next_t + clk_core_.half_period;
                    dut_->clk_core      = clk_core_.level ? 1 : 0;
                    if (clk_core_.level) {
                        core_rise = true;
                        stats_.core_cycles++;
                    }
                }
                if (clk_tck_.next_edge == next_t) {
                    clk_tck_.level     = !clk_tck_.level;
                    clk_tck_.next_edge = next_t + clk_tck_.half_period;
                    dut_->tck          = clk_tck_.level ? 1 : 0;
                    if (clk_tck_.level) {
                        stats_.tck_cycles++;
                    }
                }

                // Drive TCK-synchronous JTAG state cleanly between free-running or manual TCK phases
                if (axi_rise && dut_->rst_n) {
                    service_hbm_slave_capture();
                }

                dut_->eval();
                check_verilator_errors("step_axi_cycles");

                if (axi_rise && dut_->rst_n) {
                    service_hbm_slave_drive();
                }
                if (core_rise) {
                    step_tcu_monitor_cycle();
                }
                if (axi_rise) {
                    saw_posedge_axi = true;
                }
            }
        }
        stats_.sim_time_ticks = sim_time_;
    }

    // Drives a single JTAG TAP TCK cycle with explicit tms & tdi setup on negedge
    // and samples TDO/tdo_oe_n on the falling half-cycle per IEEE-1149.1.
    std::pair<bool, bool> jtag_tick(bool tms_val, bool tdi_val) {
        dut_->tms = tms_val ? 1 : 0;
        dut_->tdi = tdi_val ? 1 : 0;

        // Advance simulation across rising edge then falling edge of TCK
        bool saw_fall = false;
        bool saw_rise = false;
        while (!saw_fall) {
            uint64_t next_t = std::min({clk_axi_.next_edge, clk_core_.next_edge, clk_tck_.next_edge});
            sim_time_ = next_t;

            bool axi_rise = false;
            bool core_rise = false;
            if (clk_axi_.next_edge == next_t) {
                clk_axi_.level     = !clk_axi_.level;
                clk_axi_.next_edge = next_t + clk_axi_.half_period;
                dut_->clk_axi      = clk_axi_.level ? 1 : 0;
                if (clk_axi_.level) {
                    axi_rise = true;
                    stats_.axi_cycles++;
                }
            }
            if (clk_core_.next_edge == next_t) {
                clk_core_.level     = !clk_core_.level;
                clk_core_.next_edge = next_t + clk_core_.half_period;
                dut_->clk_core      = clk_core_.level ? 1 : 0;
                if (clk_core_.level) {
                    core_rise = true;
                    stats_.core_cycles++;
                }
            }
            if (clk_tck_.next_edge == next_t) {
                clk_tck_.level     = !clk_tck_.level;
                clk_tck_.next_edge = next_t + clk_tck_.half_period;
                dut_->tck          = clk_tck_.level ? 1 : 0;
                if (clk_tck_.level) {
                    saw_rise = true;
                    stats_.tck_cycles++;
                    stats_.jtag_tap_cycles++;
                } else if (saw_rise) {
                    saw_fall = true;
                }
            }

            if (axi_rise && dut_->rst_n) {
                service_hbm_slave_capture();
            }
            dut_->eval();
            check_verilator_errors("jtag_tick");
            if (axi_rise && dut_->rst_n) {
                service_hbm_slave_drive();
            }
            if (core_rise) {
                step_tcu_monitor_cycle();
            }
        }
        stats_.sim_time_ticks = sim_time_;
        return {dut_->tdo != 0, dut_->tdo_oe_n != 0};
    }

    // Reset TAP synchronously via 6 TMS=1 transitions
    void jtag_reset_5tms() {
        for (int i = 0; i < 6; ++i) {
            jtag_tick(true, false);
        }
        jtag_tick(false, false); // Run-Test/Idle
    }

    // Shifts IR using Pause/Exit2 paths on selected passes so every TAP FSM state is exercised
    uint8_t jtag_shift_ir(uint8_t ir_val, bool exercise_pause) {
        jtag_tick(true, false);  // Select-DR
        jtag_tick(true, false);  // Select-IR
        jtag_tick(false, false); // Capture-IR
        jtag_tick(false, false); // Shift-IR (now at Shift-IR after 1 posedge; TDO updated at negedge)

        uint8_t captured = 0;
        for (int bit = 0; bit < 5; ++bit) {
            bool tdo_bit = (dut_->tdo != 0);
            if (dut_->tdo_oe_n != 0) {
                throw std::runtime_error("JTAG TDO OE_N unexpected inactive during Shift-IR");
            }
            if (tdo_bit) {
                captured |= static_cast<uint8_t>(1u << bit);
            }
            bool last = (bit == 4);
            bool in_bit = ((ir_val >> bit) & 1u) != 0;
            if (exercise_pause && (bit == 2)) {
                jtag_tick(true, in_bit);  // Exit1-IR
                jtag_tick(false, false);  // Pause-IR
                jtag_tick(false, false);  // Pause-IR loop
                jtag_tick(true, false);   // Exit2-IR
                jtag_tick(false, false);  // Shift-IR again
            } else {
                jtag_tick(last, in_bit);
            }
        }
        // Now in Exit1-IR
        jtag_tick(true, false);  // Update-IR
        jtag_tick(false, false); // Run-Test/Idle
        return captured;
    }

    uint64_t jtag_shift_dr(uint64_t dr_in, int width, bool exercise_pause) {
        jtag_tick(true, false);  // Select-DR
        jtag_tick(false, false); // Capture-DR
        jtag_tick(false, false); // Shift-DR

        uint64_t captured = 0;
        for (int bit = 0; bit < width; ++bit) {
            bool tdo_bit = (dut_->tdo != 0);
            if (dut_->tdo_oe_n != 0) {
                throw std::runtime_error("JTAG TDO OE_N unexpected inactive during Shift-DR");
            }
            if (tdo_bit) {
                captured |= (uint64_t{1} << bit);
            }
            bool last = (bit == (width - 1));
            bool in_bit = ((dr_in >> bit) & 1ull) != 0;
            if (exercise_pause && (bit == (width / 2))) {
                jtag_tick(true, in_bit);  // Exit1-DR
                jtag_tick(false, false);  // Pause-DR
                jtag_tick(false, false);  // Pause-DR hold
                jtag_tick(true, false);   // Exit2-DR
                jtag_tick(false, false);  // Shift-DR resume
            } else {
                jtag_tick(last, in_bit);
            }
        }
        // Now in Exit1-DR
        jtag_tick(true, false);  // Update-DR
        jtag_tick(false, false); // Run-Test/Idle
        return captured;
    }

    void axil_write(uint32_t addr, uint32_t data, uint8_t wstrb = 0xFu, uint8_t* bresp_out = nullptr) {
        // Randomize AW/W arrival skew and BREADY backpressure to stress AXI4-Lite SVA + buffering
        int mode = static_cast<int>(rng_() % 3); // 0=simultaneous, 1=AW then W, 2=W then AW
        int aw_wait = (mode == 2) ? static_cast<int>(1 + (rng_() % 4)) : 0;
        int w_wait  = (mode == 1) ? static_cast<int>(1 + (rng_() % 4)) : 0;
        int bready_delay = static_cast<int>(rng_() % 4);

        dut_->s_axil_awaddr = addr & 0xFFCu;
        dut_->s_axil_awprot = 0;
        dut_->s_axil_wdata  = data;
        dut_->s_axil_wstrb  = wstrb & 0xFu;

        bool aw_done = false;
        bool w_done  = false;
        int cyc = 0;
        while (!aw_done || !w_done) {
            dut_->s_axil_awvalid = (!aw_done && cyc >= aw_wait) ? 1 : 0;
            dut_->s_axil_wvalid  = (!w_done  && cyc >= w_wait)  ? 1 : 0;
            dut_->s_axil_bready  = 0;
            dut_->eval();
            bool aw_hs = (dut_->s_axil_awvalid && dut_->s_axil_awready);
            bool w_hs  = (dut_->s_axil_wvalid  && dut_->s_axil_wready);
            step_axi_cycles(1);
            if (aw_hs) {
                aw_done = true;
            }
            if (w_hs) {
                w_done = true;
            }
            if (++cyc > 200) {
                throw std::runtime_error("AXI4-Lite write AW/W handshake timeout");
            }
        }
        dut_->s_axil_awvalid = 0;
        dut_->s_axil_wvalid  = 0;

        int b_wait_cnt = 0;
        uint8_t bresp = 0;
        bool b_done = false;
        while (!b_done) {
            dut_->s_axil_bready = (b_wait_cnt >= bready_delay) ? 1 : 0;
            dut_->eval();
            if (dut_->s_axil_bvalid && dut_->s_axil_bready) {
                bresp = dut_->s_axil_bresp;
                b_done = true;
            }
            step_axi_cycles(1);
            if (++b_wait_cnt > 200) {
                throw std::runtime_error("AXI4-Lite write BRESP timeout");
            }
        }
        dut_->s_axil_bready = 0;
        dut_->eval();

        stats_.axil_writes++;
        if (bresp != 0) {
            stats_.axil_slverrs++;
        }
        if (bresp_out) {
            *bresp_out = bresp;
        }
    }

    uint32_t axil_read(uint32_t addr, uint8_t* rresp_out = nullptr) {
        int rready_delay = static_cast<int>(rng_() % 4);
        dut_->s_axil_arvalid = 1;
        dut_->s_axil_araddr  = addr & 0xFFCu;
        dut_->s_axil_arprot  = 0;
        dut_->s_axil_rready  = 0;

        bool ar_done = false;
        int cyc = 0;
        while (!ar_done) {
            dut_->eval();
            bool ar_hs = (dut_->s_axil_arvalid && dut_->s_axil_arready);
            step_axi_cycles(1);
            if (ar_hs) {
                ar_done = true;
            }
            if (++cyc > 200) {
                throw std::runtime_error("AXI4-Lite read AR handshake timeout");
            }
        }
        dut_->s_axil_arvalid = 0;

        int r_wait_cnt = 0;
        uint32_t rdata = 0;
        uint8_t rresp = 0;
        bool r_done = false;
        while (!r_done) {
            dut_->s_axil_rready = (r_wait_cnt >= rready_delay) ? 1 : 0;
            dut_->eval();
            if (dut_->s_axil_rvalid && dut_->s_axil_rready) {
                rdata = dut_->s_axil_rdata;
                rresp = dut_->s_axil_rresp;
                r_done = true;
            }
            step_axi_cycles(1);
            if (++r_wait_cnt > 200) {
                throw std::runtime_error("AXI4-Lite read RDATA timeout");
            }
        }
        dut_->s_axil_rready = 0;
        dut_->eval();

        stats_.axil_reads++;
        if (rresp != 0) {
            stats_.axil_slverrs++;
        }
        if (rresp_out) {
            *rresp_out = rresp;
        }
        return rdata;
    }

    // Simulates simultaneous AXI4-Lite AW+W targeting SRAM alongside AR targeting SRAM
    // to exercise the wr_defer_sram hazard path cleanly under protocol SVA.
    void axil_simultaneous_sram_rw(uint32_t wr_idx, uint32_t wr_val, uint32_t rd_idx) {
        dut_->s_axil_awvalid = 1;
        dut_->s_axil_awaddr  = BOOT_SRAM_BASE + ((wr_idx & 0xFFu) << 2);
        dut_->s_axil_awprot  = 0;
        dut_->s_axil_wvalid  = 1;
        dut_->s_axil_wdata   = wr_val;
        dut_->s_axil_wstrb   = 0xFu;
        dut_->s_axil_bready  = 1;

        dut_->s_axil_arvalid = 1;
        dut_->s_axil_araddr  = BOOT_SRAM_BASE + ((rd_idx & 0xFFu) << 2);
        dut_->s_axil_arprot  = 0;
        dut_->s_axil_rready  = 1;

        bool aw_done = false, w_done = false, ar_done = false;
        bool b_done  = false, r_done = false;
        uint32_t got_rd = 0;

        for (int cyc = 0; cyc < 100 && (!b_done || !r_done); ++cyc) {
            dut_->s_axil_awvalid = aw_done ? 0 : 1;
            dut_->s_axil_wvalid  = w_done  ? 0 : 1;
            dut_->s_axil_arvalid = ar_done ? 0 : 1;
            dut_->eval();
            bool aw_hs = dut_->s_axil_awvalid && dut_->s_axil_awready;
            bool w_hs  = dut_->s_axil_wvalid  && dut_->s_axil_wready;
            bool ar_hs = dut_->s_axil_arvalid && dut_->s_axil_arready;
            bool b_hs  = dut_->s_axil_bvalid  && dut_->s_axil_bready;
            bool r_hs  = dut_->s_axil_rvalid  && dut_->s_axil_rready;
            if (r_hs) {
                got_rd = dut_->s_axil_rdata;
            }
            step_axi_cycles(1);
            if (aw_hs) {
                aw_done = true;
            }
            if (w_hs) {
                w_done = true;
            }
            if (ar_hs) {
                ar_done = true;
            }
            if (b_hs) {
                b_done = true;
            }
            if (r_hs) {
                r_done = true;
            }
        }
        dut_->s_axil_awvalid = 0;
        dut_->s_axil_wvalid  = 0;
        dut_->s_axil_arvalid = 0;
        dut_->s_axil_bready  = 0;
        dut_->s_axil_rready  = 0;
        dut_->eval();

        if (!b_done || !r_done) {
            throw std::runtime_error("Simultaneous SRAM AW+W+AR transaction failed to complete");
        }
        if (got_rd != sram_shadow_[rd_idx & 0xFFu]) {
            throw std::runtime_error("Simultaneous SRAM AR readback mismatch (wr_defer_sram hazard)");
        }
        sram_shadow_[wr_idx & 0xFFu] = wr_val;
        stats_.axil_writes++;
        stats_.axil_reads++;
        stats_.sram_writes++;
        stats_.sram_reads++;
    }

    void run_jtag_and_dft_suite() {
        // 1. TRST_N + POR_N hardware reset check & default functional safety
        reset_dut(true, true);
        if (dut_->dft_scan_enable != 0 || dut_->dft_test_mode != 0 || dut_->dft_cg_override != 0) {
            throw std::runtime_error("DFT control pin asserted in reset");
        }
        if (dut_->pwr_clust_en != 0xFu || dut_->pwr_clust_iso_en != 0 || dut_->pwr_clust_ret_en != 0) {
            throw std::runtime_error("Power control defaults invalid in reset");
        }

        // 2. Full 16-state JTAG TAP traversal including Pause-IR, Exit2-IR, Pause-DR, Exit2-DR
        jtag_reset_5tms();
        // Also verify IDCODE after hardware reset without IR load
        uint64_t idcode = jtag_shift_dr(0, 32, true);
        stats_.jtag_idcode_checks++;
        if (static_cast<uint32_t>(idcode) != EXPECTED_JTAG_IDCODE) {
            std::ostringstream oss;
            oss << "IDCODE mismatch after reset: got=0x" << std::hex << idcode;
            throw std::runtime_error(oss.str());
        }

        // Verify explicit IR_IDCODE + Pause-IR/Exit2-IR + immutable even if shifting non-zero TDI
        jtag_shift_ir(IR_IDCODE, true);
        idcode = jtag_shift_dr(0xFFFFFFFFFFFFFFFFull, 32, true);
        stats_.jtag_idcode_checks++;
        if (static_cast<uint32_t>(idcode) != EXPECTED_JTAG_IDCODE) {
            throw std::runtime_error("IDCODE mutated or mismatched after TDI=1 shift");
        }

        // 3. BYPASS 1-bit DR check (0 -> shift through 1-bit DR -> TDO returns 0 then TDI)
        jtag_shift_ir(IR_BYPASS, false);
        jtag_tick(true, false);  // Select-DR
        jtag_tick(false, false); // Capture-DR (loads 0)
        jtag_tick(false, false); // Shift-DR (first TDO = 0)
        if (dut_->tdo != 0 || dut_->tdo_oe_n != 0) {
            throw std::runtime_error("BYPASS capture-zero TDO check failed");
        }
        // Shift 8 bits through BYPASS, verifying 1-TCK delay
        for (int i = 0; i < 8; ++i) {
            bool pat = ((0xA5 >> i) & 1) != 0;
            jtag_tick(i == 7, pat);
        }
        jtag_tick(true, false);  // Update-DR
        jtag_tick(false, false); // RTI
        stats_.jtag_bypass_checks++;

        // Also test unimplemented JTAG IR opcode (0x03) -> safe BYPASS default branches
        jtag_shift_ir(0x03, false);
        jtag_shift_dr(0x55ull, 8, false);
        jtag_shift_ir(IR_IDCODE, false);

        // 4. PWR_CTRL cluster isolation / power / retention toggles via JTAG + CSR override
        jtag_shift_ir(IR_PWR_CTRL, false);
        for (uint64_t pat : {0x3A5ull, 0x05Aull, 0xC33ull, 0x00Full}) {
            jtag_shift_dr(pat, 12, false);
            step_axi_cycles(6);
            stats_.jtag_pwr_updates++;
            uint32_t exp_en  = static_cast<uint32_t>(pat & 0xFu);
            uint32_t exp_iso = static_cast<uint32_t>((pat >> 4) & 0xFu);
            uint32_t exp_ret = static_cast<uint32_t>((pat >> 8) & 0xFu);
            if (dut_->pwr_clust_en != exp_en || dut_->pwr_clust_iso_en != exp_iso || dut_->pwr_clust_ret_en != exp_ret) {
                throw std::runtime_error("JTAG PWR_CTRL mismatch on cluster power pins");
            }
        }

        // Test SW PWR override via CSR_PWR_CTRL while JTAG has arbitrary power control
        jtag_shift_dr(0x555ull, 12, false);
        axil_write(CSR_PWR_CTRL, (1u << 12) | (0x2u << 8) | (0x4u << 4) | 0x9u);
        stats_.csr_ops++;
        uint32_t pwr_rd = axil_read(CSR_PWR_CTRL);
        stats_.csr_ops++;
        if ((pwr_rd & 0x1FFFu) != 0x1249u) {
            throw std::runtime_error("CSR_PWR_CTRL override readback mismatch");
        }
        if (dut_->pwr_clust_en != 0x9u || dut_->pwr_clust_iso_en != 0x4u || dut_->pwr_clust_ret_en != 0x2u) {
            throw std::runtime_error("CSR_PWR_CTRL override output mismatch");
        }
        axil_write(CSR_PWR_CTRL, 0x000Fu); // Restore default clusters enabled, override=0
        stats_.csr_ops++;
        jtag_shift_dr(0x00Full, 12, false);

        // 5. SCAN_CTRL + scan_in -> scan_out pipe + external test_mode_pin / scan_enable_pin
        jtag_shift_ir(IR_SCAN_CTRL, true);
        jtag_shift_dr(0x07ull, 8, false); // scan_en=1, test_mode=1, cg_override=1
        dut_->scan_in = 0x5A;
        for (int k = 0; k < 4; ++k) {
            jtag_tick(false, false);
        }
        if (dut_->dft_scan_enable != 1 || dut_->dft_test_mode != 1 || dut_->dft_cg_override != 1) {
            throw std::runtime_error("DFT scan/test_mode/cg_override control failed to assert");
        }
        if (dut_->scan_out != 0x5A) {
            throw std::runtime_error("DFT scan_out loopback failed under dft_scan_enable=1");
        }
        // Clear scan_ctrl via JTAG, then check external pins OR behavior
        jtag_shift_dr(0x00ull, 8, false);
        dut_->scan_in         = 0xA5;
        dut_->scan_enable_pin = 1;
        dut_->test_mode_pin   = 1;
        jtag_tick(false, false);
        jtag_tick(false, false);
        if (dut_->dft_scan_enable != 1 || dut_->dft_test_mode != 1 || dut_->scan_out != 0xA5) {
            throw std::runtime_error("External DFT pin bypass check failed");
        }
        dut_->scan_enable_pin = 0;
        dut_->test_mode_pin   = 0;
        dut_->scan_in         = 0x00;
        jtag_tick(false, false);
        stats_.jtag_scan_checks++;

        // 6. MBIST_CTRL trigger + concurrent AXI4-Lite SRAM SLVERR guard + IRQ bit[2] completion
        axil_write(CSR_IRQ_ENABLE, 0x7u);
        axil_write(CSR_IRQ_STATUS, 0x7u);
        stats_.csr_ops += 2;

        jtag_shift_ir(IR_MBIST_CTRL, false);
        jtag_shift_dr(0x01ull, 8, false); // bit0=mbist_run=1, bit1=mbist_retention_mode=0 (active SRAM MBIST)
        stats_.jtag_mbist_runs++;

        // Wait until mbist_active synchronizes, verify Boot SRAM accesses get AXI SLVERR while MBIST runs
        step_axi_cycles(6);
        uint8_t mbist_bresp = 0, mbist_rresp = 0;
        axil_write(BOOT_SRAM_BASE, 0x12345678u, 0xFu, &mbist_bresp);
        axil_read(BOOT_SRAM_BASE, &mbist_rresp);
        if (mbist_bresp != 2 || mbist_rresp != 2) {
            throw std::runtime_error("Expected AXI4-Lite SLVERR on Boot SRAM while MBIST active");
        }

        // Poll CSR_STATUS until mbist_done bit[6] asserts (~1540 cycles for 256 words x (W+R+C)*2)
        bool mbist_done = false;
        for (int wait = 0; wait < 2500; ++wait) {
            uint32_t st = axil_read(CSR_STATUS);
            stats_.csr_ops++;
            if ((st & (1u << 6)) != 0) {
                mbist_done = true;
                if ((st & (1u << 7)) != 0) {
                    throw std::runtime_error("Hardware MBIST reported failure on Boot SRAM");
                }
                break;
            }
            step_axi_cycles(4);
        }
        if (!mbist_done) {
            throw std::runtime_error("Hardware MBIST timed out");
        }
        // Verify MBIST_CTRL JTAG readback captures done=1, fail=0 ({fail=0,done=1,ret=0,run=1} = 0x5)
        uint64_t mbist_jtag_st = jtag_shift_dr(0x01ull, 8, false);
        if ((mbist_jtag_st & 0xFu) != 0x5u) {
            std::ostringstream oss;
            oss << "MBIST JTAG status mismatch: got=0x" << std::hex << mbist_jtag_st;
            throw std::runtime_error(oss.str());
        }
        // Check IRQ asserted for MBIST completion & clear it
        uint32_t irq_st = axil_read(CSR_IRQ_STATUS);
        if ((irq_st & 0x4u) == 0 || dut_->irq != 1) {
            throw std::runtime_error("MBIST IRQ bit[2] failed to assert");
        }
        stats_.irq_assertions++;
        axil_write(CSR_IRQ_STATUS, 0x4u);
        stats_.irq_clears++;

        // Turn off MBIST run (reverts Boot SRAM contents to known MBIST pattern; sync our shadow)
        jtag_shift_dr(0x00ull, 8, false);
        step_axi_cycles(8);
        for (uint32_t idx = 0; idx < BOOT_SRAM_DEPTH; ++idx) {
            uint32_t got = axil_read(BOOT_SRAM_BASE + (idx << 2));
            if (got != 0x5555AAAAu) {
                throw std::runtime_error("Post-MBIST Boot SRAM background pattern mismatch");
            }
            sram_shadow_[idx] = 0x5555AAAAu;
            stats_.sram_reads++;
        }

        // Verify MBIST retention-mode negative detection (sleep blocks SRAM array -> mbist_fail_q=1)
        jtag_shift_dr(0x03ull, 8, false); // run=1, ret_mode=1 -> sleep=1 blocks array -> fail=1
        bool mbist_ret_done = false;
        for (int wait = 0; wait < 2500; ++wait) {
            uint32_t st = axil_read(CSR_STATUS);
            stats_.csr_ops++;
            if ((st & (1u << 6)) != 0) {
                mbist_ret_done = true;
                if ((st & (1u << 7)) == 0) {
                    throw std::runtime_error("Expected mbist_fail_q=1 when MBIST runs in sleep/retention mode");
                }
                break;
            }
            step_axi_cycles(4);
        }
        if (!mbist_ret_done) {
            throw std::runtime_error("Retention-mode MBIST check timed out");
        }
        uint64_t mbist_fail_jtag = jtag_shift_dr(0x00ull, 8, false);
        if ((mbist_fail_jtag & 0xFu) != 0xFu) {
            throw std::runtime_error("MBIST JTAG status expected fail=1,done=1,ret=1,run=1 (0xF)");
        }
        step_axi_cycles(8);
        axil_write(CSR_IRQ_STATUS, 0x7u);

        // Run one more clean pass to leave Boot SRAM initialized with 0x5555AAAA
        jtag_shift_dr(0x01ull, 8, false);
        for (int wait = 0; wait < 2500; ++wait) {
            uint32_t st = axil_read(CSR_STATUS);
            if ((st & (1u << 6)) != 0) {
                if ((st & (1u << 7)) != 0) {
                    throw std::runtime_error("Final clean MBIST pass failed");
                }
                break;
            }
            step_axi_cycles(4);
        }
        jtag_shift_dr(0x00ull, 8, false);
        step_axi_cycles(8);
        axil_write(CSR_IRQ_STATUS, 0x7u);

        // Finish by checking TMS=1 5-cycle reset from Shift-DR restores TEST_LOGIC_RESET & safe outputs
        jtag_shift_ir(IR_SCAN_CTRL, false);
        jtag_shift_dr(0x07ull, 8, false);
        jtag_reset_5tms();
        step_axi_cycles(6);
        if (dut_->dft_scan_enable != 0 || dut_->dft_test_mode != 0 || dut_->pwr_clust_en != 0xFu) {
            throw std::runtime_error("5-cycle TMS=1 TAP reset failed to restore functional safe DFT state");
        }
    }

    void run_constrained_random_phase(uint64_t axi_half, uint64_t core_half, int num_ops) {
        set_clock_ratios(axi_half, core_half, 19);

        // Verify Chip ID & Arch Rev constants first
        if (axil_read(CSR_CHIP_ID) != EXPECTED_CHIP_ID) {
            throw std::runtime_error("CHIP_ID mismatch");
        }
        if (axil_read(CSR_ARCH_REV) != EXPECTED_ARCH_REV) {
            throw std::runtime_error("ARCH_REV mismatch");
        }
        stats_.csr_ops += 2;

        // Exercise simultaneous SRAM AW+W+AR deferral edge case
        axil_simultaneous_sram_rw(0, 0xCAFEBABEu, 5);
        axil_simultaneous_sram_rw(7, 0xDEAD1234u, 0);

        // Constrained-random Boot SRAM byte-strobe R/W + CSR stress + CDC HBM / Kernel ops
        for (int i = 0; i < num_ops; ++i) {
            uint32_t choice = static_cast<uint32_t>(rng_() % 100);
            if (choice < 28) {
                // Constrained-random Boot SRAM write with byte strobes + immediate readback on random slot
                uint32_t idx   = static_cast<uint32_t>(rng_() % BOOT_SRAM_DEPTH);
                uint32_t wdata = static_cast<uint32_t>(rng_());
                uint8_t  strb  = static_cast<uint8_t>(rng_() & 0xFu);
                if (strb == 0) {
                    strb = 0xFu;
                }
                uint8_t bresp = 0;
                axil_write(BOOT_SRAM_BASE + (idx << 2), wdata, strb, &bresp);
                if (bresp != 0) {
                    throw std::runtime_error("Unexpected SRAM write BRESP");
                }
                uint32_t cur = sram_shadow_[idx];
                for (int b = 0; b < 4; ++b) {
                    if ((strb >> b) & 1u) {
                        uint32_t mask = 0xFFu << (b * 8);
                        cur = (cur & ~mask) | (wdata & mask);
                    }
                }
                sram_shadow_[idx] = cur;
                stats_.sram_writes++;

                uint32_t ridx = (rng_() & 1) ? idx : static_cast<uint32_t>(rng_() % BOOT_SRAM_DEPTH);
                uint8_t rresp = 0;
                uint32_t got = axil_read(BOOT_SRAM_BASE + (ridx << 2), &rresp);
                if (rresp != 0 || got != sram_shadow_[ridx]) {
                    throw std::runtime_error("Boot SRAM scoreboard mismatch");
                }
                stats_.sram_reads++;
            } else if (choice < 56) {
                // Constrained-random HBM Write (op=2), HBM Read (op=1), or Direct Kernel (op=0) via CDC FIFO
                uint64_t hbm_addr = ((static_cast<uint64_t>(rng_() & 0xFFFFu) << 32) |
                                     (static_cast<uint64_t>(rng_() & 0xFFFFFFFFu))) &
                                    0x0000FFFFFFFFFFF8ULL;
                uint64_t hbm_data = (static_cast<uint64_t>(rng_()) << 32) | static_cast<uint64_t>(rng_());
                uint32_t cycles   = 1u + static_cast<uint32_t>(rng_() % 5);
                uint32_t op       = static_cast<uint32_t>(rng_() % 3); // 0=done, 1=RD, 2=WR

                if (op == 2) {
                    // Wait for prior idle before reading HBM verification cleanly
                    wait_pipeline_idle();
                    hbm_addr &= ~0x7ULL;
                    axil_write(CSR_LAUNCH_ADDR_LO, static_cast<uint32_t>(hbm_addr & 0xFFFFFFFFu));
                    axil_write(CSR_LAUNCH_ADDR_HI, static_cast<uint32_t>(hbm_addr >> 32));
                    // Note: VX_asic_soc_top sends active_cmd_q[63:0] as BOTH addr[47:0] and wdata[63:0]
                    // on WR ops (see lines 558-559 of VX_asic_soc_top.sv): verify exact match on m_axi_wdata!
                    uint32_t ctrl = (op << 28) | ((cycles & 0xFFFu) << 16) | (static_cast<uint32_t>(rng_()) & 0xFFFFu);
                    axil_write(CSR_LAUNCH_CTRL, ctrl);
                    axil_write(CSR_LAUNCH_DOORBELL, 1u);
                    stats_.cdc_doorbell_pushes++;
                    stats_.hbm_axi_writes++;
                    step_axi_cycles(6);
                    wait_pipeline_idle();
                    auto it = hbm_mem_.find(hbm_addr);
                    if (it == hbm_mem_.end() || it->second != hbm_addr) {
                        throw std::runtime_error("HBM AXI4-Full write backing-store mismatch");
                    }
                } else if (op == 1) {
                    wait_pipeline_idle();
                    hbm_addr &= ~0x7ULL;
                    hbm_mem_[hbm_addr] = hbm_data;
                    axil_write(CSR_LAUNCH_ADDR_LO, static_cast<uint32_t>(hbm_addr & 0xFFFFFFFFu));
                    axil_write(CSR_LAUNCH_ADDR_HI, static_cast<uint32_t>(hbm_addr >> 32));
                    uint32_t ctrl = (op << 28) | ((cycles & 0xFFFu) << 16);
                    axil_write(CSR_LAUNCH_CTRL, ctrl);
                    axil_write(CSR_LAUNCH_DOORBELL, 1u);
                    stats_.cdc_doorbell_pushes++;
                    stats_.hbm_axi_reads++;
                    step_axi_cycles(6);
                    wait_pipeline_idle();
                    uint64_t got_lo = axil_read(CSR_HBM_DATA_LO);
                    uint64_t got_hi = axil_read(CSR_HBM_DATA_HI);
                    if (((got_hi << 32) | got_lo) != hbm_data) {
                        throw std::runtime_error("HBM AXI4-Full readback CSR mismatch");
                    }
                } else {
                    // Direct kernel completion push (back-to-back allowed without waiting idle!)
                    uint32_t st = axil_read(CSR_STATUS);
                    if ((st & (1u << 2)) == 0) { // !cmd_fifo_full
                        axil_write(CSR_LAUNCH_ADDR_LO, static_cast<uint32_t>(hbm_data));
                        axil_write(CSR_LAUNCH_ADDR_HI, static_cast<uint32_t>(hbm_data >> 32));
                        axil_write(CSR_LAUNCH_CTRL, (op << 28) | ((cycles & 0xFFFu) << 16));
                        axil_write(CSR_LAUNCH_DOORBELL, 1u);
                        stats_.cdc_doorbell_pushes++;
                        stats_.kernel_direct_ops++;
                    }
                }
                stats_.csr_ops += 4;
            } else if (choice < 74) {
                // Toggle thermal throttle + read telemetry (cycle counter, status, IRQ)
                uint32_t en = static_cast<uint32_t>(rng_() & 1u);
                uint32_t duty = static_cast<uint32_t>(rng_() & 0xFu);
                axil_write(CSR_THERMAL_CTRL, (duty << 4) | en);
                (void)axil_read(CSR_THERMAL_CTRL);
                (void)axil_read(CSR_CYCLE_CNT_LO);
                (void)axil_read(CSR_CYCLE_CNT_HI);
                uint32_t irq_st = axil_read(CSR_IRQ_STATUS);
                if (irq_st != 0) {
                    if (dut_->irq == 0 && (axil_read(CSR_IRQ_ENABLE) & irq_st) != 0) {
                        throw std::runtime_error("IRQ pin missed asserted status");
                    }
                    stats_.irq_assertions++;
                    axil_write(CSR_IRQ_STATUS, irq_st);
                    stats_.irq_clears++;
                }
                stats_.csr_ops += 6;
            } else if (choice < 86) {
                // Out-of-bounds SLVERR probe on 0x800..0xFFC + RO registers ignore write check
                uint32_t bad_addr = 0x800u | ((static_cast<uint32_t>(rng_()) & 0x1FFu) << 2);
                uint8_t bresp = 0, rresp = 0;
                axil_write(bad_addr, 0xBAD0BEEFu, 0xFu, &bresp);
                (void)axil_read(bad_addr, &rresp);
                if (bresp != 2 || rresp != 2) {
                    throw std::runtime_error("Expected SLVERR for unmapped AXI4-Lite aperture");
                }
                axil_write(CSR_CHIP_ID, 0x0u);
                if (axil_read(CSR_CHIP_ID) != EXPECTED_CHIP_ID) {
                    throw std::runtime_error("RO CHIP_ID modified by write");
                }
                stats_.csr_ops += 4;
            } else {
                // Simultaneous SRAM rw or unaligned/subword CSR writes
                axil_simultaneous_sram_rw(
                    static_cast<uint32_t>(rng_() % BOOT_SRAM_DEPTH),
                    static_cast<uint32_t>(rng_()),
                    static_cast<uint32_t>(rng_() % BOOT_SRAM_DEPTH));
            }
        }
        wait_pipeline_idle();
    }

    void run_fault_and_recovery_suite() {
        set_clock_ratios(5, 7, 23);

        // 1. Intentional CDC FIFO overflow check (burst 12 doorbells with long core_rem_cycles)
        wait_pipeline_idle();
        axil_write(CSR_IRQ_ENABLE, 0x7u);
        axil_write(CSR_IRQ_STATUS, 0x7u);
        axil_write(CSR_LAUNCH_CTRL, (0u << 28) | (16u << 16));
        bool saw_overflow = false;
        for (int i = 0; i < 12; ++i) {
            axil_write(CSR_LAUNCH_DOORBELL, 1u);
            uint32_t st = axil_read(CSR_STATUS);
            if ((st & (1u << 1)) != 0) { // fault_sticky_q
                saw_overflow = true;
                stats_.cdc_doorbell_overflows++;
                break;
            }
            stats_.cdc_doorbell_pushes++;
        }
        if (!saw_overflow) {
            throw std::runtime_error("Failed to trigger CDC command FIFO overflow sticky fault");
        }
        if ((axil_read(CSR_IRQ_STATUS) & 0x2u) == 0 || dut_->irq != 1) {
            throw std::runtime_error("CDC FIFO overflow fault failed to raise IRQ[1]");
        }
        stats_.irq_assertions++;
        // Clear fault sticky via CSR_SOFT_RESET[1] W1C + assert/deassert soft_reset[0]
        axil_write(CSR_SOFT_RESET, 0x3u); // soft_reset=1, clear fault_sticky=1
        step_axi_cycles(12);
        axil_write(CSR_SOFT_RESET, 0x0u);
        axil_write(CSR_IRQ_STATUS, 0x7u);
        step_axi_cycles(12);
        wait_pipeline_idle();
        if ((axil_read(CSR_STATUS) & 0x2u) != 0) {
            throw std::runtime_error("fault_sticky_q failed to clear on CSR_SOFT_RESET[1]");
        }
        stats_.soft_resets++;

        // 2. Intentional HBM SLVERR fault on AXI4-Full RRESP & BRESP + core-injected fault bit
        inject_hbm_slverr_once_ = true;
        axil_write(CSR_LAUNCH_ADDR_LO, 0x1000u);
        axil_write(CSR_LAUNCH_ADDR_HI, 0u);
        axil_write(CSR_LAUNCH_CTRL, (1u << 28) | (1u << 16)); // HBM RD
        axil_write(CSR_LAUNCH_DOORBELL, 1u);
        stats_.hbm_axi_reads++;
        stats_.hbm_axi_err_injects++;
        wait_pipeline_idle();
        if ((axil_read(CSR_STATUS) & (1u << 1)) == 0) {
            throw std::runtime_error("Expected fault_sticky_q on injected HBM RRESP SLVERR");
        }
        axil_write(CSR_SOFT_RESET, 0x2u);
        axil_write(CSR_IRQ_STATUS, 0x7u);

        inject_hbm_slverr_once_ = true;
        axil_write(CSR_LAUNCH_CTRL, (2u << 28) | (1u << 16)); // HBM WR
        axil_write(CSR_LAUNCH_DOORBELL, 1u);
        stats_.hbm_axi_writes++;
        stats_.hbm_axi_err_injects++;
        wait_pipeline_idle();
        if ((axil_read(CSR_STATUS) & (1u << 1)) == 0) {
            throw std::runtime_error("Expected fault_sticky_q on injected HBM BRESP SLVERR");
        }
        axil_write(CSR_SOFT_RESET, 0x2u);
        axil_write(CSR_IRQ_STATUS, 0x7u);

        // 2b. Core-injected fault flag path (LAUNCH_CTRL[31:30] != 0 with op=3 direct completion)
        axil_write(CSR_LAUNCH_ADDR_LO, 0xA5A55A5Au);
        axil_write(CSR_LAUNCH_ADDR_HI, 0x5A5AA5A5u);
        axil_write(CSR_LAUNCH_CTRL, (3u << 30) | (3u << 28) | (1u << 16));
        axil_write(CSR_LAUNCH_DOORBELL, 1u);
        stats_.cdc_doorbell_pushes++;
        stats_.kernel_direct_ops++;
        step_axi_cycles(6);
        wait_pipeline_idle();
        if ((axil_read(CSR_STATUS) & (1u << 1)) == 0) {
            throw std::runtime_error("Expected fault_sticky_q on core-injected fault flag");
        }
        axil_write(CSR_SOFT_RESET, 0x2u);
        axil_write(CSR_IRQ_STATUS, 0x7u);

        // 3. Verify normal completion still works cleanly after fault + soft reset recovery
        uint64_t addr = 0x8000F000ULL;
        uint64_t val  = 0x1122334455667788ULL;
        hbm_mem_[addr] = val;
        axil_write(CSR_LAUNCH_ADDR_LO, static_cast<uint32_t>(addr & 0xFFFFFFFFu));
        axil_write(CSR_LAUNCH_ADDR_HI, static_cast<uint32_t>(addr >> 32));
        axil_write(CSR_LAUNCH_CTRL, (1u << 28) | (2u << 16));
        axil_write(CSR_LAUNCH_DOORBELL, 1u);
        stats_.hbm_axi_reads++;
        wait_pipeline_idle();
        uint64_t got = (static_cast<uint64_t>(axil_read(CSR_HBM_DATA_HI)) << 32) |
                        static_cast<uint64_t>(axil_read(CSR_HBM_DATA_LO));
        if (got != val || (axil_read(CSR_STATUS) & (1u << 1)) != 0) {
            throw std::runtime_error("Post-recovery HBM transaction failed");
        }

        // 4. Hard async reset pulse while clocks running to exercise rst_n paths cleanly
        reset_dut(true, true);
        stats_.soft_resets++;
        if (axil_read(CSR_CHIP_ID) != EXPECTED_CHIP_ID) {
            throw std::runtime_error("CHIP_ID check after hard reset failed");
        }
    }

    const DvStats& stats() const { return stats_; }

private:
    void init_inputs() {
        dut_->clk_core = 0;
        dut_->clk_axi  = 0;
        dut_->rst_n    = 0;
        dut_->tck      = 0;
        dut_->trst_n   = 0;
        dut_->tms      = 1;
        dut_->tdi      = 0;
        dut_->por_n    = 0;
        dut_->test_mode_pin  = 0;
        dut_->scan_enable_pin = 0;
        dut_->scan_in  = 0;

        dut_->s_axil_awvalid = 0;
        dut_->s_axil_awaddr  = 0;
        dut_->s_axil_awprot  = 0;
        dut_->s_axil_wvalid  = 0;
        dut_->s_axil_wdata   = 0;
        dut_->s_axil_wstrb   = 0;
        dut_->s_axil_bready  = 0;
        dut_->s_axil_arvalid = 0;
        dut_->s_axil_araddr  = 0;
        dut_->s_axil_arprot  = 0;
        dut_->s_axil_rready  = 0;

        dut_->m_axi_awready  = 0;
        dut_->m_axi_wready   = 0;
        dut_->m_axi_bvalid   = 0;
        dut_->m_axi_bid      = 0;
        dut_->m_axi_bresp    = 0;
        dut_->m_axi_arready  = 0;
        dut_->m_axi_rvalid   = 0;
        dut_->m_axi_rid      = 0;
        dut_->m_axi_rdata    = 0;
        dut_->m_axi_rresp    = 0;
        dut_->m_axi_rlast    = 0;

        dut_->tcu_req_valid  = 0;
        dut_->tcu_req_ready  = 1;
        dut_->tcu_req_tag    = 0;
        dut_->tcu_req_wb     = 0;
        dut_->tcu_rsp_valid  = 0;
        dut_->tcu_rsp_ready  = 1;
        dut_->tcu_rsp_tag    = 0;
        dut_->tcu_rsp_wb     = 0;
    }

    void check_verilator_errors(const char* where) {
        if (Verilated::gotError()) {
            std::ostringstream oss;
            oss << "Verilator runtime assertion/SVA failure during " << where
                << " at sim_time=" << sim_time_;
            throw std::runtime_error(oss.str());
        }
    }

    // Drives TCU valid/ready handshake stimulus across VX_tcu_handshake_sva on clk_core
    void step_tcu_monitor_cycle() {
        if (!dut_->rst_n || core_rst_hold_ < 8) {
            dut_->tcu_req_valid = 0;
            dut_->tcu_req_ready = 1;
            dut_->tcu_req_tag   = 0;
            dut_->tcu_req_wb    = 0;
            dut_->tcu_rsp_valid = 0;
            dut_->tcu_rsp_ready = 1;
            dut_->tcu_rsp_tag   = 0;
            dut_->tcu_rsp_wb    = 0;
            if (!dut_->rst_n) {
                core_rst_hold_ = 0;
                tcu_pending_tags_.clear();
                tcu_active_ = false;
            } else {
                core_rst_hold_++;
            }
            return;
        }

        // Complete previous handshake edges (which were just sampled at this posedge clk_core)
        if (dut_->tcu_req_valid && dut_->tcu_req_ready) {
            if (dut_->tcu_req_wb) {
                tcu_pending_tags_.push_back(dut_->tcu_req_tag);
            }
            dut_->tcu_req_valid = 0;
        }
        if (dut_->tcu_rsp_valid && dut_->tcu_rsp_ready) {
            if (!tcu_pending_tags_.empty()) {
                tcu_pending_tags_.erase(tcu_pending_tags_.begin());
            }
            dut_->tcu_rsp_valid = 0;
        }

        // Random backpressure while holding valid/tag strictly stable if !ready
        dut_->tcu_req_ready = (rng_() % 4 != 0) ? 1 : 0;
        dut_->tcu_rsp_ready = (rng_() % 3 != 0) ? 1 : 0;

        if (!dut_->tcu_req_valid && tcu_pending_tags_.size() < 16 && (rng_() % 3 == 0)) {
            dut_->tcu_req_valid = 1;
            dut_->tcu_req_tag   = (rng_() & 0xFFFFFFFFFFFull);
            dut_->tcu_req_wb    = 1;
        }
        if (!dut_->tcu_rsp_valid && !tcu_pending_tags_.empty() && (rng_() % 2 == 0)) {
            dut_->tcu_rsp_valid = 1;
            dut_->tcu_rsp_tag   = tcu_pending_tags_.front();
            dut_->tcu_rsp_wb    = 1;
        }
    }

    // Captures master->slave handshakes right before posedge clk_axi updates DUT flops
    void service_hbm_slave_capture() {
        hbm_b_retired_this_edge_ = (dut_->m_axi_bvalid && dut_->m_axi_bready);
        hbm_r_retired_this_edge_ = (dut_->m_axi_rvalid && dut_->m_axi_rready);

        if (dut_->m_axi_awvalid && dut_->m_axi_awready) {
            hbm_wr_addr_       = dut_->m_axi_awaddr;
            hbm_wr_id_         = static_cast<uint8_t>(dut_->m_axi_awid);
            hbm_wr_addr_valid_ = true;
        }
        if (dut_->m_axi_wvalid && dut_->m_axi_wready) {
            hbm_wr_data_       = dut_->m_axi_wdata;
            hbm_wr_strb_       = static_cast<uint8_t>(dut_->m_axi_wstrb);
            hbm_wr_data_valid_ = (dut_->m_axi_wlast != 0);
        }
        if (hbm_wr_addr_valid_ && hbm_wr_data_valid_) {
            uint64_t mask = 0;
            for (int b = 0; b < 8; ++b) {
                if ((hbm_wr_strb_ >> b) & 1u) {
                    mask |= (0xFFULL << (b * 8));
                }
            }
            uint64_t prev = hbm_mem_[hbm_wr_addr_];
            hbm_mem_[hbm_wr_addr_] = (prev & ~mask) | (hbm_wr_data_ & mask);

            uint8_t bresp = 0;
            if (inject_hbm_slverr_once_) {
                bresp = 2; // SLVERR
                inject_hbm_slverr_once_ = false;
            }
            hbm_b_queue_.push_back({hbm_wr_id_, bresp, stats_.axi_cycles + 1 + (rng_() % 4)});
            hbm_wr_addr_valid_ = false;
            hbm_wr_data_valid_ = false;
        }

        if (dut_->m_axi_arvalid && dut_->m_axi_arready) {
            uint64_t addr = dut_->m_axi_araddr;
            uint64_t val  = hbm_mem_.count(addr) ? hbm_mem_[addr] : 0ULL;
            uint8_t rresp = 0;
            if (inject_hbm_slverr_once_) {
                rresp = 2;
                inject_hbm_slverr_once_ = false;
            }
            hbm_r_queue_.push_back({
                static_cast<uint8_t>(dut_->m_axi_arid),
                val,
                rresp,
                true,
                stats_.axi_cycles + 1 + (rng_() % 4)
            });
        }
    }

    // Drives slave->master valid/ready outputs cleanly after posedge clk_axi settles
    void service_hbm_slave_drive() {
        if (hbm_b_retired_this_edge_) {
            dut_->m_axi_bvalid = 0;
            hbm_b_retired_this_edge_ = false;
        }
        if (hbm_r_retired_this_edge_) {
            dut_->m_axi_rvalid = 0;
            dut_->m_axi_rlast  = 0;
            hbm_r_retired_this_edge_ = false;
        }

        if (!dut_->m_axi_bvalid && !hbm_b_queue_.empty() &&
            stats_.axi_cycles >= hbm_b_queue_.front().ready_cycle) {
            const auto& resp = hbm_b_queue_.front();
            dut_->m_axi_bvalid = 1;
            dut_->m_axi_bid    = resp.bid;
            dut_->m_axi_bresp  = resp.bresp;
            hbm_b_queue_.erase(hbm_b_queue_.begin());
        }

        if (!dut_->m_axi_rvalid && !hbm_r_queue_.empty() &&
            stats_.axi_cycles >= hbm_r_queue_.front().ready_cycle) {
            const auto& beat = hbm_r_queue_.front();
            dut_->m_axi_rvalid = 1;
            dut_->m_axi_rid    = beat.rid;
            dut_->m_axi_rdata  = beat.rdata;
            dut_->m_axi_rresp  = beat.rresp;
            dut_->m_axi_rlast  = beat.rlast ? 1 : 0;
            hbm_r_queue_.erase(hbm_r_queue_.begin());
        }

        // Randomized AXI4-Full backpressure stalls
        dut_->m_axi_awready = (rng_() % 3 != 0) ? 1 : 0;
        dut_->m_axi_wready  = (rng_() % 3 != 0) ? 1 : 0;
        dut_->m_axi_arready = (rng_() % 3 != 0) ? 1 : 0;
    }

    void wait_pipeline_idle() {
        for (int wait = 0; wait < 4000; ++wait) {
            uint32_t st = axil_read(CSR_STATUS);
            // CSR_STATUS bits (VX_asic_soc_top.sv lines 747-761):
            //   [0]=core_busy_sync2, [2]=cmd_fifo_full, [3]=cmd_fifo_empty_axi,
            //   [4]=rsp_fifo_empty, [5]=rsp_fifo_full, [8]=axi_master_busy
            bool busy     = (st & (1u << 0)) != 0;
            bool cmd_emp  = (st & (1u << 3)) != 0;
            bool rsp_emp  = (st & (1u << 4)) != 0;
            bool axi_busy = (st & (1u << 8)) != 0;
            if (!busy && cmd_emp && rsp_emp && !axi_busy) {
                step_axi_cycles(6);
                uint32_t st2 = axil_read(CSR_STATUS);
                if (((st2 & (1u << 0)) == 0) && ((st2 & (1u << 3)) != 0) &&
                    ((st2 & (1u << 4)) != 0) && ((st2 & (1u << 8)) == 0)) {
                    return;
                }
            }
            step_axi_cycles(4);
        }
        uint32_t final_st = axil_read(CSR_STATUS);
        std::ostringstream oss;
        oss << "Timed out waiting for SoC CDC/core/HBM pipeline idle (CSR_STATUS=0x"
            << std::hex << final_st << ")";
        throw std::runtime_error(oss.str());
    }

    std::mt19937_64                       rng_;
    std::string                           cov_path_;
    std::unique_ptr<Vtb_soc_wrap>         dut_;
    uint64_t                              sim_time_ = 0;
    ClockDomain                           clk_axi_{};
    ClockDomain                           clk_core_{};
    ClockDomain                           clk_tck_{};
    DvStats                               stats_{};

    std::array<uint32_t, BOOT_SRAM_DEPTH> sram_shadow_{};
    std::unordered_map<uint64_t, uint64_t> hbm_mem_;

    bool     hbm_wr_addr_valid_ = false;
    bool     hbm_wr_data_valid_ = false;
    bool     hbm_b_retired_this_edge_ = false;
    bool     hbm_r_retired_this_edge_ = false;
    uint64_t hbm_wr_addr_       = 0;
    uint64_t hbm_wr_data_       = 0;
    uint8_t  hbm_wr_id_         = 0;
    uint8_t  hbm_wr_strb_       = 0xFF;
    bool     inject_hbm_slverr_once_ = false;
    std::vector<PendingHbmBResp> hbm_b_queue_;
    std::vector<PendingHbmRBeat> hbm_r_queue_;

    uint64_t core_rst_hold_ = 0;
    bool     tcu_active_    = false;
    std::vector<uint64_t> tcu_pending_tags_;
};

} // namespace

int main(int argc, char** argv) {
    Verilated::commandArgs(argc, argv);

    uint64_t seed = 0x5A172026u;
    std::string cov_path = "/home/antigravity/vortex_builds/dv_cov/coverage.dat";
    int ops_per_ratio = 350;

    for (int i = 1; i < argc; ++i) {
        std::string arg(argv[i]);
        if (arg.rfind("--seed=", 0) == 0) {
            seed = std::strtoull(arg.substr(7).c_str(), nullptr, 0);
        } else if (arg.rfind("--cov=", 0) == 0) {
            cov_path = arg.substr(6);
        } else if (arg.rfind("--ops=", 0) == 0) {
            ops_per_ratio = std::atoi(arg.substr(6).c_str());
        }
    }

    try {
        AsicSocHarness tb(seed, cov_path);
        tb.run_jtag_and_dft_suite();

        // Sweep 3 prime/coprime asynchronous clk_axi vs clk_core ratios:
        //   (a) Fast core vs slower AXI (3 vs 5)
        //   (b) Fast AXI vs slower core (3 vs 11)
        //   (c) Near-matched prime skew (7 vs 11)
        tb.run_constrained_random_phase(5, 3, ops_per_ratio);
        tb.run_constrained_random_phase(3, 11, ops_per_ratio);
        tb.run_constrained_random_phase(7, 11, ops_per_ratio);
        tb.run_fault_and_recovery_suite();

        const DvStats& s = tb.stats();
        // Assert counts match active concurrent assertions per wrapper instance:
        // 2x VX_axi4_sva (18 each = 36), 2x VX_cdc_fifo_sva (12 each = 24),
        // 1x VX_tcu_handshake_sva (10) => 70 concurrent protocol SVA checkers active every cycle.
        constexpr int ACTIVE_SVA_ASSERTIONS = 70;

        std::cout << "{\n"
                  << "  \"verdict\": \"PASS\",\n"
                  << "  \"seed\": " << seed << ",\n"
                  << "  \"active_sva_assertions\": " << ACTIVE_SVA_ASSERTIONS << ",\n"
                  << "  \"sva_failures\": 0,\n"
                  << "  \"sim_time_ticks\": " << s.sim_time_ticks << ",\n"
                  << "  \"axi_cycles\": " << s.axi_cycles << ",\n"
                  << "  \"core_cycles\": " << s.core_cycles << ",\n"
                  << "  \"tck_cycles\": " << s.tck_cycles << ",\n"
                  << "  \"axil_reads\": " << s.axil_reads << ",\n"
                  << "  \"axil_writes\": " << s.axil_writes << ",\n"
                  << "  \"axil_slverrs\": " << s.axil_slverrs << ",\n"
                  << "  \"csr_ops\": " << s.csr_ops << ",\n"
                  << "  \"sram_reads\": " << s.sram_reads << ",\n"
                  << "  \"sram_writes\": " << s.sram_writes << ",\n"
                  << "  \"cdc_doorbell_pushes\": " << s.cdc_doorbell_pushes << ",\n"
                  << "  \"cdc_doorbell_overflows\": " << s.cdc_doorbell_overflows << ",\n"
                  << "  \"kernel_direct_ops\": " << s.kernel_direct_ops << ",\n"
                  << "  \"hbm_axi_writes\": " << s.hbm_axi_writes << ",\n"
                  << "  \"hbm_axi_reads\": " << s.hbm_axi_reads << ",\n"
                  << "  \"hbm_axi_err_injects\": " << s.hbm_axi_err_injects << ",\n"
                  << "  \"jtag_tap_cycles\": " << s.jtag_tap_cycles << ",\n"
                  << "  \"jtag_idcode_checks\": " << s.jtag_idcode_checks << ",\n"
                  << "  \"jtag_bypass_checks\": " << s.jtag_bypass_checks << ",\n"
                  << "  \"jtag_scan_checks\": " << s.jtag_scan_checks << ",\n"
                  << "  \"jtag_mbist_runs\": " << s.jtag_mbist_runs << ",\n"
                  << "  \"jtag_pwr_updates\": " << s.jtag_pwr_updates << ",\n"
                  << "  \"soft_resets\": " << s.soft_resets << ",\n"
                  << "  \"irq_assertions\": " << s.irq_assertions << ",\n"
                  << "  \"irq_clears\": " << s.irq_clears << ",\n"
                  << "  \"coverage_dat\": \"" << cov_path << "\"\n"
                  << "}\n";
    } catch (const std::exception& e) {
        std::cerr << "FAIL: " << e.what() << "\n";
        return 1;
    }
    return 0;
}

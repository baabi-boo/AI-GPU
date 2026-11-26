# OpenROAD Place-and-Route -> RCX -> Post-Route STA -> DEF/Verilog Script
# Supports both ASAP7 (with optional fakeram7_256x32 SRAM macro) and Nangate45.
# Parameterized via environment variables for reproducible builds.

proc _env_or {name default} {
    if {[info exists ::env($name)] && $::env($name) ne ""} {
        return $::env($name)
    }
    return $default
}

set pdk             [_env_or PDK "asap7"]
set top_module      [_env_or TOP "VX_asic_dft_top"]
set netlist_file    [_env_or NETLIST ""]
set out_dir         [_env_or OUT_DIR "/work"]
set sdc_file        [_env_or SDC_FILE ""]
set use_sram_macro  [_env_or USE_SRAM_MACRO "0"]
set clock_port      [_env_or CLOCK_PORT "clk"]
set target_period   [_env_or TARGET_PERIOD_NS "1.000"]
set utilization     [_env_or UTILIZATION "40"]
set place_density   [_env_or PLACE_DENSITY "0.55"]
set die_area_str    [_env_or DIE_AREA ""]
set core_area_str   [_env_or CORE_AREA ""]
set sram_loc_str    [_env_or SRAM_LOC "8.0 16.0"]
set hold_margin_ns  [_env_or HOLD_MARGIN_NS "0.025"]
set setup_margin_ns [_env_or SETUP_MARGIN_NS "0.000"]
set drt_end_iter    [_env_or DRT_END_ITER "20"]

if {$netlist_file eq ""} {
    puts stderr "ERROR: NETLIST environment variable is required."
    exit 1
}

set orfs_flow "/OpenROAD-flow-scripts/flow"

if {$pdk eq "asap7"} {
    set pdk_dir "${orfs_flow}/platforms/asap7"
    read_lef "${pdk_dir}/lef/asap7_tech_1x_201209.lef"
    read_lef "${pdk_dir}/lef/asap7sc7p5t_28_R_1x_220121a.lef"
    if {$use_sram_macro eq "1"} {
        read_lef "${pdk_dir}/lef/fakeram7_256x32.lef"
    }

    read_liberty "${pdk_dir}/lib/NLDM/asap7sc7p5t_AO_RVT_TT_nldm_211120.lib.gz"
    read_liberty "${pdk_dir}/lib/NLDM/asap7sc7p5t_INVBUF_RVT_TT_nldm_220122.lib.gz"
    read_liberty "${pdk_dir}/lib/NLDM/asap7sc7p5t_OA_RVT_TT_nldm_211120.lib.gz"
    read_liberty "${pdk_dir}/lib/NLDM/asap7sc7p5t_SIMPLE_RVT_TT_nldm_211120.lib.gz"
    read_liberty "${pdk_dir}/lib/NLDM/asap7sc7p5t_SEQ_RVT_TT_nldm_220123.lib"
    if {$use_sram_macro eq "1"} {
        read_liberty "${pdk_dir}/lib/NLDM/fakeram7_256x32.lib"
    }

    set site_name        "asap7sc7p5t"
    set core_space       "1.0"
    set tap_dist         25
    set tap_cell         "TAPCELL_ASAP7_75t_R"
    set endcap_cell      "TAPCELL_ASAP7_75t_R"
    set tracks_tcl       "${pdk_dir}/openRoad/make_tracks.tcl"
    set gconnect_tcl     "${pdk_dir}/openRoad/pdn/global_connect.tcl"
    set pdn_tcl          "${pdk_dir}/openRoad/pdn/grid_strategy-M1-M2-M5-M6.tcl"
    set setrc_tcl        "${pdk_dir}/setRC.tcl"
    set rcx_rules        "${pdk_dir}/rcx_patterns.rules"
    set io_h_layer       "M4"
    set io_v_layer       "M5"
    set sig_layers       "M2-M7"
    set clk_layers       "M4-M7"
    set cts_root_buf     "BUFx2_ASAP7_75t_R"
    set cts_buf_list     "BUFx2_ASAP7_75t_R"
    set tiehi_pin        "TIEHIx1_ASAP7_75t_R/H"
    set tielo_pin        "TIELOx1_ASAP7_75t_R/L"
    set fill_cells       {FILLERxp5_ASAP7_75t_R FILLER_ASAP7_75t_R DECAPx1_ASAP7_75t_R DECAPx2_ASAP7_75t_R DECAPx4_ASAP7_75t_R DECAPx6_ASAP7_75t_R DECAPx10_ASAP7_75t_R}
    set dont_use_list    {*x1p*_ASAP7* *xp*_ASAP7* SDF* ICG*}
} elseif {$pdk eq "nangate45"} {
    set pdk_dir "${orfs_flow}/platforms/nangate45"
    read_lef "${pdk_dir}/lef/NangateOpenCellLibrary.tech.lef"
    read_lef "${pdk_dir}/lef/NangateOpenCellLibrary.macro.mod.lef"
    if {$use_sram_macro eq "1"} {
        read_lef "${pdk_dir}/lef/fakeram45_256x32.lef"
    }

    read_liberty "${pdk_dir}/lib/NangateOpenCellLibrary_typical.lib"
    if {$use_sram_macro eq "1"} {
        read_liberty "${pdk_dir}/lib/fakeram45_256x32.lib"
    }

    set site_name        "FreePDK45_38x28_10R_NP_162NW_34O"
    set core_space       "4.0"
    set tap_dist         120
    set tap_cell         "TAPCELL_X1"
    set endcap_cell      "TAPCELL_X1"
    set tracks_tcl       "${pdk_dir}/make_tracks.tcl"
    set gconnect_tcl     "${pdk_dir}/global_connect.tcl"
    set pdn_tcl          "${pdk_dir}/grid_strategy-M1-M4-M7.tcl"
    set setrc_tcl        "${pdk_dir}/setRC.tcl"
    set rcx_rules        "${pdk_dir}/rcx_patterns.rules"
    set io_h_layer       "metal5"
    set io_v_layer       "metal6"
    set sig_layers       "metal2-metal10"
    set clk_layers       "metal4-metal10"
    set cts_root_buf     "BUF_X4"
    set cts_buf_list     {BUF_X1 BUF_X2 BUF_X4 BUF_X8}
    set tiehi_pin        "LOGIC1_X1/Z"
    set tielo_pin        "LOGIC0_X1/Z"
    set fill_cells       {FILLCELL_X1 FILLCELL_X2 FILLCELL_X4 FILLCELL_X8 FILLCELL_X16 FILLCELL_X32}
    set dont_use_list    {TAPCELL_X1 FILLCELL_X1 AOI211_X1 OAI211_X1}
} else {
    puts stderr "ERROR: unsupported PDK '$pdk'"
    exit 1
}

set_cmd_units -time ns -capacitance fF -voltage V -current mA -resistance kOhm -power mW -distance um
read_verilog $netlist_file
link_design $top_module

if {$sdc_file ne ""} {
    foreach var_name {CORE_PERIOD AXI_PERIOD PCIE_PERIOD TCK_PERIOD} {
        if {[info exists ::env($var_name)] && $::env($var_name) ne ""} {
            set $var_name $::env($var_name)
        }
    }
    # OpenSTA inside OpenROAD rejects -datapath_only with [ERROR STA-0563] even
    # inside catch{}; map -datapath_only to -ignore_clock_latency while sourcing.
    rename set_max_delay _orig_set_max_delay
    proc set_max_delay {args} {
        set filtered {}
        foreach a $args {
            if {$a eq "-datapath_only"} {
                lappend filtered "-ignore_clock_latency"
                set ::_sdc_datapath_mapped_count [expr {[info exists ::_sdc_datapath_mapped_count] ? $::_sdc_datapath_mapped_count + 1 : 1}]
            } else {
                lappend filtered $a
            }
        }
        return [uplevel 1 [linsert $filtered 0 _orig_set_max_delay]]
    }
    set ::_sdc_datapath_mapped_count 0
    source $sdc_file
    rename set_max_delay ""
    rename _orig_set_max_delay set_max_delay
    puts "INFO: SDC sourced cleanly ($sdc_file; mapped_datapath_only=$::_sdc_datapath_mapped_count)"
} else {
    set clk_objs [get_ports -quiet $clock_port]
    if {[llength $clk_objs] > 0} {
        create_clock -name $clock_port -period $target_period $clk_objs
        set_clock_transition 0.040 [get_clocks $clock_port]
        set_clock_uncertainty -setup 0.030 [get_clocks $clock_port]
        set_clock_uncertainty -hold  0.020 [get_clocks $clock_port]
        set in_ports {}
        foreach p [all_inputs] {
            if {[get_name $p] ne $clock_port} {
                lappend in_ports $p
            }
        }
        if {[llength $in_ports] > 0} {
            set_input_delay  -clock [get_clocks $clock_port] -max 0.030 $in_ports
            set_input_delay  -clock [get_clocks $clock_port] -min 0.005 $in_ports
        }
        if {[llength [all_outputs]] > 0} {
            set_output_delay -clock [get_clocks $clock_port] -max 0.030 [all_outputs]
            set_output_delay -clock [get_clocks $clock_port] -min 0.000 [all_outputs]
        }
        set_input_transition 0.040 [all_inputs]
        if {[llength [all_outputs]] > 0} {
            set_load 2.0 [all_outputs]
        }
    }
}

set_dont_use $dont_use_list

# Match ORFS floorplan.tcl: clone singleton tie cells prior to floorplan/placement
catch {repair_tie_fanout -separation 10 -max_fanout 16 $tiehi_pin}
catch {repair_tie_fanout -separation 10 -max_fanout 16 $tielo_pin}

if {$die_area_str ne "" && $core_area_str ne ""} {
    initialize_floorplan -die_area $die_area_str -core_area $core_area_str -site $site_name
} else {
    initialize_floorplan -utilization $utilization -aspect_ratio 1.0 -core_space $core_space -site $site_name
}

source $tracks_tcl
source $gconnect_tcl

set sram_cells {}
if {$use_sram_macro eq "1"} {
    set sram_cells [get_cells -quiet -hier *u_fakeram*]
}

if {[llength $sram_cells] > 0} {
    set sram_inst [get_name [lindex $sram_cells 0]]
    puts "INFO: Placing SRAM macro instance '$sram_inst' at {$sram_loc_str}"
    place_macro -macro_name $sram_inst -location $sram_loc_str -orientation R0 -allow_overlap
    cut_rows -halo_width_x 2.0 -halo_width_y 2.0
    tapcell -distance $tap_dist -tapcell_master $tap_cell -endcap_master $endcap_cell -halo_width_x 2.0 -halo_width_y 2.0
} else {
    tapcell -distance $tap_dist -tapcell_master $tap_cell -endcap_master $endcap_cell
}

source $pdn_tcl
pdngen -skip_trim

place_pins -hor_layers $io_h_layer -ver_layers $io_v_layer

source $setrc_tcl
set_routing_layers -signal $sig_layers -clock $clk_layers
if {$pdk eq "asap7"} {
    set_global_routing_layer_adjustment M2-M7 0.25
} else {
    set_global_routing_layer_adjustment metal2-metal3 0.5
    set_global_routing_layer_adjustment metal4-metal10 0.25
}

global_placement -density $place_density -pad_left 1 -pad_right 1
detailed_placement
check_placement -verbose

if {[llength [all_clocks]] > 0} {
    clock_tree_synthesis -root_buf $cts_root_buf -buf_list $cts_buf_list -sink_clustering_enable -repair_clock_nets
}
set_placement_padding -global -left 1 -right 1
detailed_placement
estimate_parasitics -placement
repair_design
repair_timing -setup -hold -setup_margin $setup_margin_ns -hold_margin $hold_margin_ns -max_buffer_percent 80
detailed_placement

global_route -congestion_iterations 30 -congestion_report_file "${out_dir}/grt_congestion.rpt" -verbose
set_propagated_clock [all_clocks]
estimate_parasitics -global_routing
repair_timing -setup -hold -setup_margin $setup_margin_ns -hold_margin $hold_margin_ns -max_buffer_percent 80
detailed_placement

# Re-run full global route cleanly (avoids incremental marker bug in Nangate45)
global_route -congestion_iterations 30 -congestion_report_file "${out_dir}/grt_congestion.rpt"

detailed_route -output_drc "${out_dir}/drt_drc.rpt" -droute_end_iter $drt_end_iter -verbose 1

filler_placement $fill_cells
check_placement -verbose

define_process_corner -ext_model_index 0 X
set_extraction_rules_file $rcx_rules
extract_parasitics
write_spef "${out_dir}/${top_module}.spef"
read_spef  "${out_dir}/${top_module}.spef"

set block [ord::get_db_block]
set dbu [expr {double([$block getDbUnitsPerMicron])}]
set core_rect [$block getCoreArea]
set core_area [expr {([$core_rect xMax] - [$core_rect xMin]) / $dbu * ([$core_rect yMax] - [$core_rect yMin]) / $dbu}]
set std_cnt 0
set fill_cnt 0
set tap_cnt 0
set macro_cnt 0
foreach inst [$block getInsts] {
    set mname [[$inst getMaster] getName]
    if {[string match "FILLER*" $mname] || [string match "DECAP*" $mname] || [string match "FILLCELL*" $mname]} {
        incr fill_cnt
    } elseif {[string match "TAPCELL*" $mname]} {
        incr tap_cnt
    } elseif {[string match "fakeram*" $mname]} {
        incr macro_cnt
    } else {
        incr std_cnt
    }
}

puts "=== POST_ROUTE REPORTS BEGIN ==="
puts "POST_ROUTE_INST_COUNTS core_area_um2=[format %.2f $core_area] std_cells=$std_cnt macros=$macro_cnt tapcells=$tap_cnt filler_decap=$fill_cnt total_insts=[llength [$block getInsts]]"
report_design_area
report_wns -digits 4
report_tns -digits 4
report_worst_slack -max -digits 4
report_worst_slack -min -digits 4
report_clock_min_period -include_port_paths
report_checks -path_delay max -group_path_count 5 -digits 4 -format full_clock_expanded
foreach clk_obj [all_clocks] {
    set clk_name [get_name $clk_obj]
    puts "--- POST_ROUTE CLOCK GROUP: $clk_name ---"
    catch {report_checks -path_delay max -path_group $clk_name -group_path_count 2 -digits 4 -format full_clock_expanded}
}
report_checks -path_delay min -group_path_count 3 -digits 4 -format full_clock_expanded
report_power -digits 4
puts "=== POST_ROUTE REPORTS END ==="

write_def     "${out_dir}/${top_module}.def"
write_verilog "${out_dir}/${top_module}_pnr.v"
exit

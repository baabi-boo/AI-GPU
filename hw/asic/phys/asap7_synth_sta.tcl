# OpenSTA Static Timing & Power Analysis Script
# Parameterized via environment variables; reads Liberty + synthesized Verilog
# netlist, applies repo SDC or clock constraints, and emits WNS/TNS/worst_slack,
# critical path checks, clock max-frequency paths, and power breakdowns.

proc _env_or {name default} {
    if {[info exists ::env($name)] && $::env($name) ne ""} {
        return $::env($name)
    }
    return $default
}

set top_module      [_env_or TOP "VX_asic_dft_top"]
set netlist_file    [_env_or NETLIST ""]
set lib_files_str   [_env_or LIB_FILES ""]
set sdc_file        [_env_or SDC_FILE ""]
set spef_file       [_env_or SPEF_FILE ""]
set clock_port      [_env_or CLOCK_PORT "clk"]
set clock_period_ns [_env_or TARGET_PERIOD_NS "1.000"]
set io_delay_ns     [_env_or IO_DELAY_NS "0.050"]
set clk_uncert_ns   [_env_or CLK_UNCERT_NS "0.050"]
set clk_hold_unc_ns [_env_or CLK_HOLD_UNCERT_NS "0.020"]
set input_slew_ns   [_env_or INPUT_SLEW_NS "0.040"]
set output_load_ff  [_env_or OUTPUT_LOAD_FF "2.0"]
set path_count      [_env_or PATH_COUNT "5"]
set extra_sdc       [_env_or EXTRA_SDC ""]

if {$netlist_file eq "" || $lib_files_str eq ""} {
    puts stderr "ERROR: NETLIST and LIB_FILES environment variables are required."
    exit 1
}

foreach lib_f [split $lib_files_str ":"] {
    if {$lib_f ne ""} {
        puts "INFO: read_liberty $lib_f"
        read_liberty $lib_f
    }
}

set_cmd_units -time ns -capacitance fF -voltage V -current mA -resistance kOhm -power mW -distance um

puts "INFO: read_verilog $netlist_file"
read_verilog $netlist_file
puts "INFO: link_design $top_module"
link_design $top_module

if {$spef_file ne "" && [file exists $spef_file]} {
    puts "INFO: read_spef $spef_file"
    read_spef $spef_file
}

if {$sdc_file ne ""} {
    foreach var_name {CORE_PERIOD AXI_PERIOD PCIE_PERIOD TCK_PERIOD} {
        if {[info exists ::env($var_name)] && $::env($var_name) ne ""} {
            set $var_name $::env($var_name)
        }
    }
    puts "INFO: source_sdc $sdc_file"
    source $sdc_file
} else {
    set clk_objs [get_ports -quiet $clock_port]
    if {[llength $clk_objs] > 0} {
        create_clock -name $clock_port -period $clock_period_ns $clk_objs
        set_clock_uncertainty -setup $clk_uncert_ns [get_clocks $clock_port]
        set_clock_uncertainty -hold  $clk_hold_unc_ns [get_clocks $clock_port]
        set in_ports {}
        foreach p [all_inputs] {
            if {[get_name $p] ne $clock_port} {
                lappend in_ports $p
            }
        }
        if {[llength $in_ports] > 0} {
            set_input_delay  -clock [get_clocks $clock_port] -max $io_delay_ns $in_ports
            set_input_delay  -clock [get_clocks $clock_port] -min 0.000 $in_ports
        }
        if {[llength [all_outputs]] > 0} {
            set_output_delay -clock [get_clocks $clock_port] -max $io_delay_ns [all_outputs]
            set_output_delay -clock [get_clocks $clock_port] -min 0.000 [all_outputs]
        }
        set_input_transition $input_slew_ns [all_inputs]
        if {[llength [all_outputs]] > 0} {
            set_load $output_load_ff [all_outputs]
        }
    }
}

if {$extra_sdc ne "" && [file exists $extra_sdc]} {
    puts "INFO: source_extra_sdc $extra_sdc"
    source $extra_sdc
}

puts "=== STA SUMMARY BEGIN ==="
report_wns -digits 4
report_tns -digits 4
report_worst_slack -max -digits 4
report_worst_slack -min -digits 4
puts "=== STA SUMMARY END ==="

puts "=== STA CLOCKS BEGIN ==="
report_clock_min_period -include_port_paths
puts "=== STA CLOCKS END ==="

puts "=== STA SETUP PATHS BEGIN ==="
report_checks -path_delay max -group_path_count $path_count -digits 4 -format full_clock_expanded
foreach clk_obj [all_clocks] {
    set clk_name [get_name $clk_obj]
    puts "--- CLOCK GROUP: $clk_name ---"
    catch {report_checks -path_delay max -path_group $clk_name -group_path_count 2 -digits 4 -format full_clock_expanded}
}
puts "=== STA SETUP PATHS END ==="

puts "=== STA HOLD PATHS BEGIN ==="
report_checks -path_delay min -group_path_count 2 -digits 4 -format full_clock_expanded
puts "=== STA HOLD PATHS END ==="

puts "=== STA POWER BEGIN ==="
report_power -digits 4
puts "=== STA POWER END ==="

exit

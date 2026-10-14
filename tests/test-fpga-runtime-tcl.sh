#!/usr/bin/env bash
set -euo pipefail
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
fixture="$(mktemp -d /tmp/xsai-fpga-tcl.XXXXXXXX)"
trap 'rm -f "$fixture/mock.tcl" "$fixture/calls" "$fixture/bundle/design.bit" "$fixture/bundle/design.ltx" "$fixture/bundle/extra.bit"; rmdir "$fixture/bundle" "$fixture"' EXIT
mkdir "$fixture/bundle"
printf 'bit\n' > "$fixture/bundle/design.bit"
printf 'probes\n' > "$fixture/bundle/design.ltx"
cat > "$fixture/mock.tcl" <<'TCL'
proc record {name} {
  set stream [open "$::env(FIXTURE)/calls" a]
  puts $stream $name
  close $stream
}
foreach command {open_hw_manager connect_hw_server open_hw_target close_hw_target disconnect_hw_server close_hw_manager} {
  proc $command {} [list record $command]
}
proc current_hw_target {} {return target0}
proc get_hw_devices {} {
  if {$::env(TEST_CASE) eq "devices"} {return {device0 device1}}
  return {device0}
}
proc current_hw_device {args} {}
proc refresh_hw_device {args} {}
proc get_hw_vios {args} {return {vio0 vio_unrelated}}
proc refresh_hw_vio {args} {}
proc get_hw_probes {args} {
  if {$::env(TEST_CASE) eq "probes"} {return {reset_probe second_probe}}
  return {reset_probe}
}
proc set_property {key value object} {
  if {$key eq "OUTPUT_VALUE"} {
    if {$object ne "reset_probe"} {error "unrelated output mutation"}
    record "set_reset_$value"
  }
}
proc commit_hw_vio {object} {
  if {$object ne "reset_probe"} {error "unrelated VIO commit"}
  record "commit_reset"
}
proc program_hw_devices {object} {record program}
set helper [lindex $argv 0]
set argv [lrange $argv 1 end]
set argc [llength $argv]
source $helper
TCL
run() {
    FIXTURE="$fixture" TEST_CASE="$1" tclsh "$fixture/mock.tcl" "$2" "${@:3}"
}
run success "$root/scripts/fpga/reset_cpu.tcl" "$fixture/bundle/design.ltx" 1
grep -q '^commit_reset$' "$fixture/calls"
if run probes "$root/scripts/fpga/reset_cpu.tcl" "$fixture/bundle/design.ltx" 0 >/dev/null 2>&1; then exit 1; fi
if run devices "$root/scripts/fpga/reset_cpu.tcl" "$fixture/bundle/design.ltx" 0 >/dev/null 2>&1; then exit 1; fi
if run success "$root/scripts/fpga/reset_cpu.tcl" "$fixture/bundle/design.ltx" 9 >/dev/null 2>&1; then exit 1; fi
run success "$root/scripts/fpga/program_bitstream.tcl" "$fixture/bundle"
grep -q '^program$' "$fixture/calls"
if run devices "$root/scripts/fpga/program_bitstream.tcl" "$fixture/bundle" >/dev/null 2>&1; then exit 1; fi
printf 'extra\n' > "$fixture/bundle/extra.bit"
if run success "$root/scripts/fpga/program_bitstream.tcl" "$fixture/bundle" >/dev/null 2>&1; then exit 1; fi
echo "[test-fpga-runtime-tcl] unique-device/probe and programming checks passed"

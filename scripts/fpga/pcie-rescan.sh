#!/usr/bin/env bash
set -euo pipefail
bdf="${FPGA_PCIE_BDF-}"
root="${FPGA_PCIE_SYSFS_ROOT:-/sys/bus/pci}"
sudo_cmd="${FPGA_PCIE_SUDO-sudo -n}"
wait_secs="${FPGA_XDMA_WAIT_SECS:-10}"
reload="${FPGA_XDMA_RELOAD_ON_MISSING:-0}"
module="${FPGA_XDMA_MODULE:-xdma}"
required="${FPGA_XDMA_REQUIRED_DEVICES:-/dev/xdma0_c2h_0 /dev/xdma0_h2c_0 /dev/xdma0_user /dev/xdma0_bypass}"
[[ "$bdf" =~ ^[0-9a-fA-F]{4}:[0-9a-fA-F]{2}:[0-9a-fA-F]{2}\.[0-7]$ ]] || { echo "error: explicit FPGA_PCIE_BDF required" >&2; exit 2; }
[[ "$wait_secs" =~ ^[1-9][0-9]*$ && "$module" =~ ^[a-zA-Z0-9_-]+$ ]] || exit 2
[[ "$reload" == 0 || "$reload" == 1 ]] || exit 2
read -r -a devices <<< "$required"
(( ${#devices[@]} > 0 )) || { echo "error: required device list is empty" >&2; exit 2; }
for dev in "${devices[@]}"; do [[ "$dev" == /* ]] || exit 2; done
privileged() {
    if [[ -n "$sudo_cmd" ]]; then
        read -r -a sudo_args <<< "$sudo_cmd"
        "${sudo_args[@]}" "$@"
    else "$@"; fi
}
rescan() {
    if [[ -w "$root/rescan" ]]; then printf '1\n' > "$root/rescan"
    else printf '1\n' | privileged tee "$root/rescan" >/dev/null; fi
    if command -v udevadm >/dev/null; then udevadm settle --timeout=5; fi
}
ready() {
    for dev in "${devices[@]}"; do [[ -e "$dev" ]] || return 1; done
}
wait_ready() {
    local deadline=$((SECONDS + wait_secs))
    until ready; do
        (( SECONDS < deadline )) || return 1
        sleep 1
    done
}
enable_command() {
    local device="$root/devices/$bdf" value
    [[ -d "$device" && -f "$device/vendor" ]] || return 1
    read -r value < "$device/vendor"
    [[ "${value,,}" == 0x10ee ]] || return 1
    command -v setpci >/dev/null
    value="$(setpci -s "$bdf" COMMAND)"
    [[ "$value" =~ ^[0-9a-fA-F]{4}$ ]] || return 1
    if (( (16#$value & 6) != 6 )); then
        if [[ -w "$device/config" ]]; then setpci -s "$bdf" COMMAND=0006:0006
        else privileged setpci -s "$bdf" COMMAND=0006:0006; fi
    fi
    value="$(setpci -s "$bdf" COMMAND)"
    [[ "$value" =~ ^[0-9a-fA-F]{4}$ ]] && (( (16#$value & 6) == 6 ))
}
rescan
enable_command || { echo "error: selected PCI function not ready with Mem/BusMaster: $bdf" >&2; exit 1; }
if wait_ready; then echo "[fpga-pcie] selected function and required devices ready"; exit 0; fi
printf '[fpga-pcie] missing devices:' >&2
for dev in "${devices[@]}"; do [[ -e "$dev" ]] || printf ' %s' "$dev" >&2; done
printf '\n' >&2
[[ "$reload" == 1 ]] || exit 1
# Module unload affects every bound function. Refuse if any other user is bound.
shopt -s nullglob
bound=("$root/drivers/$module"/*:*.*)
for path in "${bound[@]}"; do
    [[ "$(basename "$path")" == "$bdf" ]] || {
        echo "error: refusing shared XDMA module reload while another function is bound" >&2; exit 1
    }
done
privileged modprobe -r "$module"
privileged modprobe "$module"
rescan
enable_command && wait_ready || { echo "error: XDMA still incomplete after explicit reload" >&2; exit 1; }
echo "[fpga-pcie] required devices ready after reload"

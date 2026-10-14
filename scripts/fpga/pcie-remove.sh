#!/usr/bin/env bash
# Operate only on the explicitly selected Xilinx PCI function.
set -euo pipefail
bdf="${FPGA_PCIE_BDF-}"
root="${FPGA_PCIE_SYSFS_ROOT:-/sys/bus/pci}"
sudo_cmd="${FPGA_PCIE_SUDO-sudo -n}"
[[ "$bdf" =~ ^[0-9a-fA-F]{4}:[0-9a-fA-F]{2}:[0-9a-fA-F]{2}\.[0-7]$ ]] || {
    echo "error: explicit FPGA_PCIE_BDF required" >&2; exit 2
}
device="$root/devices/$bdf"
[[ -d "$device" && -f "$device/vendor" ]] || { echo "error: missing selected PCI function: $bdf" >&2; exit 1; }
read -r vendor < "$device/vendor"
[[ "${vendor,,}" == 0x10ee ]] || { echo "error: selected device is not Xilinx: $bdf" >&2; exit 1; }
write_sysfs() {
    if [[ -w "$2" ]]; then printf '%s\n' "$1" > "$2"
    elif [[ -n "$sudo_cmd" ]]; then
        read -r -a sudo_args <<< "$sudo_cmd"
        printf '%s\n' "$1" | "${sudo_args[@]}" tee "$2" >/dev/null
    else echo "error: no write permission for $2" >&2; return 1; fi
}
if [[ -L "$device/driver" ]]; then
    driver="$(basename "$(readlink "$device/driver")")"
    [[ "$driver" =~ ^[a-zA-Z0-9_-]+$ ]] || exit 2
    write_sysfs "$bdf" "$root/drivers/$driver/unbind"
fi
write_sysfs 1 "$device/remove"
echo "[fpga-pcie] removed selected function $bdf"

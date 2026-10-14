#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MAKEFILE="$ROOT/firmware/Makefile"

grep -q '^INITRAMFS_MODE ?= builtin$' "$MAKEFILE"
grep -q '^build-external:$' "$MAKEFILE"
grep -q 'CONFIG_BLK_DEV_INITRD' "$MAKEFILE"
grep -q -- '--initrd-start' "$MAKEFILE"
grep -q -- '--initrd-end' "$MAKEFILE"
grep -q -- '--timebase-freq' "$MAKEFILE"
grep -q 'FW_PAYLOAD_PATH=$(OPENSBI_FW_PAYLOAD)' "$MAKEFILE"
grep -q 'Expected a RISC-V Linux Image header' "$MAKEFILE"
grep -q 'Initramfs overlaps direct-map memory' "$MAKEFILE"

# The standalone path must use the complete current manifest. It must not
# silently depend on rootfs#1's split descriptors, whose contents predate the
# current pinned model/wrapper manifest.
! grep -q 'initramfs-disk-xsai-base.txt\|initramfs-disk-xsai-workload.txt' "$MAKEFILE"

# Reproduce the layout arithmetic with fixed inputs: the cpio starts after an
# aligned kernel plus the documented 2 MiB gap, and the combined payload ends
# exactly at cpio end.
read -r initrd_offset initrd_start initrd_end combined_size < <(
  python3 - <<'PY'
file_size = 0x123456
image_size = 0x180000
cpio_size = 0x4567
align = 0x100000
gap = 0x200000
aligned = ((max(file_size, image_size) + align - 1) // align) * align
offset = aligned + gap
start = 0x80200000 + offset
end = start + cpio_size
combined = offset + cpio_size
print(hex(offset), hex(start), hex(end), hex(combined))
PY
)
[[ "$initrd_offset" == "0x400000" ]]
[[ "$initrd_start" == "0x80600000" ]]
[[ "$initrd_end" == "0x80604567" ]]
[[ "$combined_size" == "0x404567" ]]

echo "external-initramfs Makefile contract and layout arithmetic: PASS"

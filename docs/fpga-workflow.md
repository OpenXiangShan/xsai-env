# FPGA runtime and programming

This maintained path controls the SSH/XDMA board (`FPGA_HOST`, default `fpga`).
It is separate from the cloud VP1902/QDMA service. Cloud jobs use the
`xsai-cloud-fpga` skill's `run-payload.sh` and `watch.py`; never replace that
watcher with a hand-written polling loop.

## Safety and inputs

Reset, loading, programming and PCIe writes change board state. First verify
board ownership and the intended source, bitstream, LTX, payload and clock/
memory-map compatibility. A lack of host UART processes alone does not prove
that an existing guest workload has finished.

The SSH flow takes a cooperative per-user board lease and refuses detected
UART/XDMA/Vivado users. Manual operators and other accounts must still
coordinate board access. It never broadly kills readers. The old
`FPGA_KILL_UART_READERS=1` option now fails with a diagnostic; stop only a
reader you own.

Load paths are explicit. `FPGA_DRIVER` and `FPGA_XDMA_PROCESS` accept absolute
paths or remote `~/` paths, not implicitly expanded local home paths.
`FPGA_REMOTE_SETUP` is a trusted operator-supplied shell command used to load
Vivado. Load failures and failed reset commands propagate nonzero status.

## Reset and run

From the root, after normal environment setup:

```sh
source env.sh
make fpga-reset FPGA_HOST=fpga FPGA_LTX=/absolute/matching/probes.ltx
make run-fpga PAYLOAD=/absolute/workload.bin \
  FPGA_LTX=/absolute/matching/probes.ltx \
  FPGA_PASS_PATTERN='MY_WORKLOAD_PASS' FPGA_FAIL_PATTERN='MY_WORKLOAD_FAIL'
```

The default GCPT selection is the NEMU payload, not the QEMU payload. Explicit
`PAYLOAD` is respected. The normal `_ensure_fpga_payload` target can build a
missing default payload; inspect recursive Make recipes before dry-running an
orchestration target.

The two variants differ in `OPENSBI_EMBED_DTB`. The NEMU payload embeds the DTB;
the QEMU payload is built without one and expects the QEMU `-bios` flow to place
it at `FW_PAYLOAD_FDT_ADDR`. Nothing in the board flow does that, so passing a
QEMU payload explicitly boots the board silently — no OpenSBI banner, no console
output at all. See `docs/troubleshooting.md`.

The payload is SHA256-checked and atomically staged before reset. A matching
remote payload is reused without upload. Only the script's uniquely named
temporary helper/upload files and its own UART process group are cleaned up.
Cached payloads and existing unrelated files are retained.

CI UART starts before reset release. `FPGA_PASS_PATTERN` is a literal marker;
`FPGA_FAIL_PATTERN` is a Bash regular expression and has precedence on a line
matching both. Reset logs are kept separately from UART logs under `log/`.

Exit status:

- `0`: the configured PASS marker was observed, or explicit reset-only finished;
- `1`: configured FAIL marker or another validation failure;
- `2`: invalid inputs;
- `3`: UART ended without a PASS marker;
- `124`: the observation window expired; the guest may still be running.

SSH, loader and Vivado errors also propagate their own nonzero exit codes.
The default PASS marker is empty: no workload completion is guessed from
boot, an `after_workload` launch, EOF or a host timeout. Choose a workload-
specific marker after checking that its guest exit/data checks are meaningful.

Interactive mode creates a dedicated tmux worker:

```sh
make run-fpga PAYLOAD=/absolute/workload.bin \
  FPGA_UART_MODE=interactive FPGA_UART_TMUX_SESSION=fpga-uart
tmux attach -t fpga-uart
```

The worker retains the lease until its terminal exits. Detaching preserves
the session. A successful detached launch is not workload acceptance. An
existing session is never overwritten. Interactive mode is for live guest
input, not a retained boot-log or CI gate.

## Explicit bitstream bundle

Use a dedicated directory containing exactly one nonempty `.bit` and matching-
stem `.ltx`. There is no newest-directory or first-file selection:

```sh
make fpga-sync-bitstream FPGA_BIT_HOME=/absolute/artifacts
make fpga-program FPGA_BIT_HOME=/absolute/artifacts \
  FPGA_PCIE_BDF=0000:03:00.0
make fpga-run-bitstream FPGA_BIT_HOME=/absolute/artifacts \
  FPGA_PCIE_BDF=0000:03:00.0 PAYLOAD=/absolute/workload.bin \
  FPGA_PASS_PATTERN='MY_WORKLOAD_PASS'
```

Uploads go into a unique retained remote bundle beneath
`FPGA_REMOTE_BIT_HOME/bundles/`. Both hashes are checked before programming;
previous bundles are not deleted. The run manifest reports the actual remote
bit/LTX paths and hashes. `fpga-run-bitstream` passes the programmed bundle's
LTX to the load step instead of resetting through the old default LTX.
Individual program and load steps acquire independent leases; coordinate the
combined operation against other operators as well.

PCIe remove/rescan requires an explicit BDF and checks its Xilinx vendor ID;
it does not remove every Xilinx function. Direct writable sysfs is preferred,
otherwise `FPGA_PCIE_SUDO` is used. The rescan checks required XDMA nodes and
the Mem/BusMaster bits. Automatic module reload is disabled by default;
`FPGA_XDMA_RELOAD_ON_MISSING=1` explicitly enables recovery and refuses a
shared module with another bound function.

## Validation boundary and deferred build work

```sh
make test-smoke
make test-fpga
```

These are host/offline regression gates, including mocked transports and
PCIe fixtures. They do not certify a new bitstream, Linux boot, model accuracy
or performance. Runtime evidence must record exact source/nested pins, patches,
toolchain/ISA, effective clock/memory map, bit/LTX/payload SHA256, command, UART
result and actual exit status.

The old broad PR #32 is being separated. This runtime change does not move
XSAI/NEMU/rootfs/framework pins, alter global memory defaults, include a copied
libtinfo, or publish build outputs. Newer CHI/ZhuJiang configs, MissQueue
correctness repairs, build-directory changes spanning difftest, arbiter
optimization and design-specific ILA insertion need separate owning-component
and integration gates. Do not apply those local experiments to the older
parent XSAI pin or treat historical debug logs as current-commit acceptance.

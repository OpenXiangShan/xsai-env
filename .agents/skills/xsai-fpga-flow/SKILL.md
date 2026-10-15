---
name: xsai-fpga-flow
description: Maintain xsai-env SSH/XDMA reset, workload loading, UART capture and explicit bitstream programming; consult for run-fpga, fpga-reset, fpga-program and related scripts.
---

# XSAI FPGA flow

Read `docs/fpga-workflow.md` completely before acting. Primary owner is top-level
orchestration, not CPU RTL. Use the root Makefile and shared shell environment.

- `make test-fpga` is an offline gate; `make test-smoke` checks root wiring.
- `make fpga-reset`, `make run-fpga`, `make fpga-program` change hardware state.
  Check ownership, exact bit/LTX/payload provenance and intended board first.
- Load the embedded-DTB NEMU payload
  (`firmware/gcpt_restore/build-nemu/build/gcpt.bin`) for `run-emu`,
  `run-emu-debug`, `run-nemu` and `run-fpga`. The top-level Makefile maps the
  default `PAYLOAD=$(QEMU_PAYLOAD)` through `RUN_NEMU_PAYLOAD` for these paths;
  explicit `PAYLOAD=<path>` values remain respected. The QEMU payload is built
  with `OPENSBI_EMBED_DTB=0` and needs the QEMU `-bios` flow to supply a DTB;
  on a board it boots silently, with no OpenSBI banner and no console output.
- `FPGA_BIT_HOME` must explicitly select one nonempty same-stem bit/LTX pair.
  Do not choose an arbitrary latest build or use a stale LTX after programming.
- PCIe changes require `FPGA_PCIE_BDF`. Never remove all vendor devices.
- UART has a single consumed FIFO. Never broadly kill readers or overwrite an
  existing tmux session. Interactive mode retains its worker and lease.
- CI PASS is literal, FAIL is regex, failure wins. No configured PASS/EOF or a
  timeout is not a completed workload. Preserve logs and actual exit status.
- New RTL fixes/configs belong in their owning repository and need independent
  correctness gates. Do not hide MissQueue fixes in a board-glue patch.
- Cloud VP1902/QDMA jobs use `xsai-cloud-fpga` and its watcher exclusively.

Inspect Make recipes before dry runs involving recursive `$(MAKE)`, which can
still execute. Do not rebuild RTL or program a board just for script syntax.
No Nix workflow is required.

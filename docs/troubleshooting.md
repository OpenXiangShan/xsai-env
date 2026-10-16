# Troubleshooting

Common failures, with logs and fixes.

## Optional source repository cannot be cloned

`llvm-project-ame` and `riscv-matrix-extension-spec` (local path:
`riscv-matrix-spec`) may not yet support anonymous access while their public
release is being prepared. These source checkouts are optional, not a reason
to abandon software or simulator setup.

Use `make init-force`, which skips them by default, and follow
[Getting AME LLVM](../README.md#getting-ame-llvm) to install a prebuilt compiler.
Do not use `git clone --recursive` or a blanket recursive submodule update as
the bootstrap command: those commands bypass the optional-source handling.

If you explicitly requested sources with `INIT_OPTIONAL_SUBMODULES=1`, a skipped
source is informational. Its full Git diagnostics are in
`log/setup/llvm-project-ame.log` or `log/setup/riscv-matrix-spec.log`. After
obtaining access or fixing connectivity, rerun the same command.

This exception applies only to optional sources. A failed NEMU, QEMU, XSAI, or
firmware dependency still needs to be fixed; setup must not silently skip it.

## Rootfs artifacts from another toolchain

### Log

```text
error: patchelf is required to rewrite interpreter /old/toolchain/lib/ld-linux-riscv64-lp64d.so.1 -> /lib/ld-linux-riscv64-lp64d.so.1
make[4]: *** [firmware/riscv-rootfs/Makefile.app:24: install] Error 1
make[3]: *** [Makefile:13: apps/busybox] Error 2
make[2]: *** [Makefile:139: build-rootfs] Error 2
```

### Cause

Rootfs app binaries built with a different compiler or sysroot were reused after the environment changed.

### Recovery

Clean rootfs app artifacts, then rebuild.

```bash
source env.sh
make -C firmware/riscv-rootfs clean
make firmware
```

Optional check:

```bash
make run-qemu
```

## Kernel panic: No working init found

### Log

```text
[    0.689174] Failed to execute /init (error -2)
[    0.696213] Kernel panic - not syncing: No working init found.
```

### Cause

The initramfs contained `/init`, but `busybox` pointed to a loader path that was not present in the image.

### Recovery

Rebuild the rootfs.

```bash
make firmware
make run-qemu
```

If this happened after switching environments, clean old rootfs app artifacts first:

```bash
make -C firmware/riscv-rootfs clean
make firmware
```

## Board or emulator boots silently

### Log

The load and reset steps succeed, but the UART log never carries a single
character after them. Not even the OpenSBI banner appears:

```text
Assert reset
Load .../agent_payload.bin
Deassert reset
Start serial connection
Escape key is ctrl+\ (SIGQUIT)
```

### Cause

A QEMU GCPT payload (`firmware/gcpt_restore/build-qemu/build/gcpt.bin`) was
loaded where the board or emulator flow was expected.

`build-gcpt-qemu` produces OpenSBI with `OPENSBI_EMBED_DTB=0`: it expects a
predecessor to place the DTB at `FW_PAYLOAD_FDT_ADDR`. The QEMU `-bios` flow
provides one; the XDMA board loader does not. OpenSBI therefore finds no device
tree, and a DTB-less OpenSBI has no console — so the board looks dead even
though reset, load and PCIe all worked. The same payload rule applies to the RTL
emulator, which likewise has no predecessor to supply a DTB.

This is easy to reach by accident when invoking a low-level loader directly or
passing the QEMU payload explicitly. The top-level variable remains
`PAYLOAD ?= $(QEMU_PAYLOAD)` for QEMU/profile/checkpoint consumers, and loaders
such as the CI `load_and_run_qdma.sh` accept any `.bin` without checking for an
embedded DTB.

### Recovery

Build and load the embedded-DTB NEMU payload instead:

```bash
make -C firmware build-gcpt-nemu
make run-fpga PAYLOAD=firmware/gcpt_restore/build-nemu/build/gcpt.bin
```

`make run-emu`, `make run-emu-debug`, `make run-fpga` and `make run-nemu` map
the default `PAYLOAD` through `RUN_NEMU_PAYLOAD` and build the NEMU payload on
demand, so the usual guard is to not pass `build-qemu/build/gcpt.bin`
explicitly.

A quick sanity check before spending a board slot: an embedded-DTB payload has
an FDT magic (`d0 0d fe ed`) in its first few megabytes, a QEMU payload does
not.

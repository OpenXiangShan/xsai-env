# AI software integration

Integration work is tracked by xsai-env issue #40. Framework code belongs to
the pinned `software/{MNN,ncnn,llama.cpp}` submodules; appliance wrappers belong
to `firmware/riscv-rootfs/apps/`. The rootfs repository has issues disabled, so
this integration issue also tracks its wrapper branch and published revision.
The rootfs gitlink and `VERSIONS` select that revision, not a local experiment.
Published rootfs branch: `feat/40-ai-framework-rootfs`, commit
`c37bd8f2c530b1dc9f1ed283c42b99523e65cd10` (independent remote fetch verified).

## Setup and host gate

From the repository root:

```sh
source env.sh
make software-init
make test-smoke
make test-ai-software
```

`software-init` initializes only the three framework submodules and rootfs,
at their recorded gitlinks. It does not update to branch tips or reset dirty
worktrees. Use the normal `make init-force` workflow before heavy full-stack
builds on a fresh checkout; Nix is not needed for these software entrypoints.

The host gate checks selected revisions, missing-source diagnostics, explicit
source overrides, MNN allocator wiring without source writes, model checksum
checks, additive manifests, workload exit propagation and differential-output
validation. Local dirty sources are reported, not certified by this host gate.

NCNN links the MNN AME kernel and allocator; llama.cpp replaces its allocator
in the CMake build graph using the MNN source. Neither wrapper fetches a hidden
app-local clone or copies code into managed framework source.

## Build gates and profiles

With an AME-aware LLVM/Clang toolchain and a matching GNU RISC-V sysroot:

```sh
make -C firmware/riscv-rootfs/apps/mnn install-binaries NPROC=2
make -C firmware/riscv-rootfs/apps/ncnn install NPROC=2
make -C firmware/riscv-rootfs/apps/llama.cpp riscv NPROC=2
```

The first two commands build and install model-free test binaries. The third
builds the llama tools without model downloads. `ROOTFS_BUILD_DIR`,
`HOST_BUILD_DIR` and `TARGET_BUILD_DIR` can select isolated output directories.
Configure `RISCV`, `RISCV_SYSROOT` and `LLVM_HOME` through the shared environment
or explicit overrides, not a private path embedded in a wrapper.

The default image stays llama-based. MNN and NCNN are opt-in apps with additive
initramfs descriptors; see `firmware/riscv-rootfs/apps/AI-INTEGRATION.md`.
MNN inference additionally requires an explicit ONNX input or fixed URL plus
SHA256 and host conversion tools. SqueezeNet/BF16/NCNN external-model caches
are not implicit dependencies of the minimal installation.

Pass the exact descriptor list to rootfs `verify-manifest` before packaging.
The firmware's common base/library descriptors must be included when validating
the complete image, not just the additive MNN/NCNN descriptors.

## Validation boundary

This integration records host regression and clean fixed-source cross-build
gates. It does not assert a newly boot-tested image, end-to-end model accuracy,
performance, or FPGA compatibility. App-local `run-user*` helpers are local-only
diagnostics requiring a compatible Matrix-enabled QEMU; they are not portable
release acceptance tests. Full runtime acceptance still follows QEMU → NEMU →
checkpoint → RTL where needed.

Metadata-only `.gguf.om` / fake-like tests are not real inference. The existing
openRuyi/PyTorch and Triton evidence is separate from these appliance wrapper
gates. No simulator, ISA, RTL or FPGA bitstream changes, Nix-specific work,
large models, binaries or generated artifacts are included in this integration.

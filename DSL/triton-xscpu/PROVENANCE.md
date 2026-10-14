# Triton/xscpu integration provenance

This directory owns the integration contract only. It does not vendor Triton,
Buddy-MLIR, LLVM, generated objects, wheels, or shared-library binaries.

The validated input currently available is the fixed precompiled bundle
`triton-xscpu-riscv64-20260918.tar.gz`, whose archive SHA-256 is recorded in
`manifest.json`. The bundle contains Triton 3.4.0
`gitb758c587` wheels for CPython 3.12 and 3.13, four RISC-V compiler tools,
runtime libraries, licenses, and validation metadata. The bundle's
per-file `SHA256SUMS` is the artifact-level authority.

No readable public backend source tree or source commit was available when this
integration was prepared. Therefore `manifest.json` deliberately records
`url: null` and `commit: null`, marks the input as `precompiled`, and does not
claim source-reproducible backend builds. A release must provide the extracted
bundle through `TRITON_XSCPU_BUNDLE`; missing or incomplete bundles fail closed.

The proven board result is the existing int8-to-int32 AOT path using
ZAMES/ZMASYNC proposal-12 instructions and the existing harness. The entrypoints
do not broaden that result to BF16, floating-point hardware correctness,
`torch.compile`, generic JIT support, or a new runtime allocator. Those remain
explicitly unsupported until independently evidenced.

`compile.sh` accepts a caller-owned Python Triton driver. The driver must create
the requested object at `TRITON_XSCPU_OUTPUT`. `stage.sh` copies only the fixed
bundle and explicitly named caller artifacts into a new stage directory.
Existing outputs, cache directories, and stage directories are rejected to
prevent silent reuse of stale `.o`, `.so`, or IR.

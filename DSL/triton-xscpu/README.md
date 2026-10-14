# Triton/xscpu release integration

This is a deterministic integration wrapper for the existing RISC-V Triton
`xscpu` tool bundle. It is intentionally small: the compiler/backend sources
remain in their owning upstream/fork repository, while this directory records
the external artifact identity and the staging/compile contract.

The current release input is the precompiled
`triton-xscpu-riscv64-20260918` bundle. Its archive SHA-256 and selected tool
and wheel hashes are in [`manifest.json`](manifest.json). Obtain/extract that
bundle by an explicit release mechanism, then set:

```sh
export TRITON_XSCPU_BUNDLE=/path/to/extracted/triton-xscpu-riscv64-20260918
# Optional, when the original archive is retained:
export TRITON_XSCPU_ARCHIVE=/path/to/triton-xscpu-riscv64-20260918.tar.gz
```

The path is deliberately not guessed from a developer NFS directory. There is
no source URL or commit for the backend in the available provenance, so this
integration reports a fixed precompiled tool artifact rather than pretending to
be a source-reproducible build.

## Compile

Provide a Python driver as the source-level input. It must create the object
named by `TRITON_XSCPU_OUTPUT`:

```sh
DSL/triton-xscpu/compile.sh \
  --driver path/to/aot_driver.py \
  --output build/triton_kernel.o \
  --cache-dir build/triton-cache
```

`--bundle`, `--python`, and arguments after `--` are configurable. The wrapper
sets `PYTHONHASHSEED=0`, `LC_ALL=C`, and `TZ=UTC`, requires a new cache
directory, and rejects an existing output. The bundle setup script performs
the target ABI checks; compile therefore requires the bundle's supported
Linux riscv64 CPython runtime (or an explicitly configured compatible
emulator wrapper).

The proven AOT scope is the existing int8-to-int32 ZAMES/ZMASYNC path. This
entrypoint does not claim BF16/floating-point hardware correctness,
`torch.compile`, generic JIT support, or a new allocator/runtime.

When `TRITON_XSCPU_ARCHIVE` is set, the wrapper verifies the archive against
the corrected 64-hex SHA-256 recorded in `manifest.json`; without it, the
extracted bundle is still checked file-by-file against its bundled manifest.

## Stage

Stage only a fixed bundle plus explicitly named outputs into a new directory:

```sh
DSL/triton-xscpu/stage.sh \
  --dest build/triton-stage \
  --abi cp313 \
  --object build/triton_kernel.o:exec/triton_kernel.o
```

`stage.sh` refuses to reuse an existing stage directory and never discovers or
copies arbitrary `.o`/`.so` files. The old `local/ruyi-pytorch/triton-image`
scripts remain untouched; a parent integration may consume this stage tree.

## Tests

The host-side negative tests are fast and do not download, compile, execute a
board workload, or require the large bundle:

```sh
bash DSL/triton-xscpu/tests/test_entrypoints.sh
```

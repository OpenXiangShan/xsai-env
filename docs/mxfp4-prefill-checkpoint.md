# MXFP prefill source checkpoint — 2026-11-23

These are recovery branches, not an integration release or a pull request. The
parent gitlinks and `VERSIONS` are intentionally unchanged. Use a separate
checkout and fetch the owning revisions from the table; do not reset a live
worktree to this archive or combine alternatives by cherry-picking them together.

| Owner | Branch | Commit | Contents |
| --- | --- | --- | --- |
| `OurCompArchGroup/llama.cpp` | `archive/mxfp4-prefill-20261123` | `7ade14bf470ec7c928e8289b58edab2bae9dba34` | MXFP native backend, opt-in shared RMSNorm/pack/QKV, directed tests |
| `OurCompArchGroup/nexus-am-ame` | `archive/mxfp4-prefill-20261123` | `028052ab81e2735922c362d5403017f14f4fb4ce` | Existing AM bare-metal fixtures and their model-shape interfaces |
| `OurCompArchGroup/riscv-rootfs` | `archive/mxfp4-prefill-20261123` | `4fa51538a2a822591b06d0eb06a331ab815fb38c` | Workload flags and packaging of the existing quantizer tests |
| `OpenXiangShan/qemu` | `archive/mxfp4-prefill-20261123` | `c08ee60beed86137201a95f980d9f0ce181671a4` | Experimental MXFP functional emulation |
| `OpenXiangShan/NEMU` | `archive/mxfp4-prefill-20261123` | `a470913fa2ceab325d554f8855984cb81a68d01a` | MXFP architectural reference and directed test source |
| `OurCompArchGroup/llvm-project-ame` (requires access) | `archive/mxfp4-prefill-20261123` | `372bc8d4c9f1b58c7cdab2acb2b3f7f8eb18e140` | `mlascale`/`mlbscale` mnemonics and MC tests |
| `OurCompArchGroup/llama.cpp` | `archive/mxfp4-packed-r75-20261123` | `2d76560a2fbc7c68863d6165c79c5d024107d84b` | Frozen R75 batch8/packed source (`c72662b7e17ff857e1dafca38a6b6fe1c1f6c449`), followed by the shared-QKV source overlay |
| `OurCompArchGroup/nexus-am-ame` | `archive/mxfp4-packed-r75-20261123` | `697482dc29aaf392d38a6bc6be0e6f83ffb57e34` | Exact `tests/ame-gemm/matop.S` for that R75 build |

For example, in a separate initialized `xsai-env` checkout:

```sh
git -C software/llama.cpp fetch --no-tags origin refs/heads/archive/mxfp4-packed-r75-20261123
git -C software/llama.cpp checkout --detach 2d76560a2fbc7c68863d6165c79c5d024107d84b
git -C nexus-am fetch --no-tags origin refs/heads/archive/mxfp4-packed-r75-20261123
git -C nexus-am checkout --detach 697482dc29aaf392d38a6bc6be0e6f83ffb57e34
sha256sum nexus-am/tests/ame-gemm/matop.S
```

The expected assembly SHA-256 is
`26ee87667ec98d831cbaa8735fdeee577265d197a5386bf65dcc9b336cbf9530`.
The R75 static RV64/RVV build opts into `GGML_RV_AME` and `GGML_RV_MXFP4_PACKED`;
set `GGML_RV_MXFP4_PACKED_ASM` to the absolute path of that exact assembly.
Reuse the existing cross-toolchain configuration and CMake `test-quantize-fns`
target. This map restores source, not the original host toolchain or a
byte-identical ELF. The authorized raw receipts retain the configure args,
compile database, source hashes and diagnostic witness.

## Validation boundary

The latest bounded Stories15M real-GGUF PP256 functional witness used
`GGML_AME_RMSNORM_MXFP4=pipeline` vs `pipeline+qkv`. The latter ran one shared
pack, skipped two redundant packs, and completed Q/V/K byte-for-byte with the
K288 `256+32` tail. Natural FCSR `0x17` took the original quantizer fallback in
QEMU, so this is **not** a `PACK_MX` instruction hit. The earlier Qwen3-0.6B
bounded witness completed Q and V but timed out before K completed. Neither is
DUT timing or a prefill checkpoint. The independent short-screen experiments
are not silently enabled by these archive branches.

The budget admission, result collector and ledger tooling is in this parent
branch; see [agent workflow](agent-workflow.md#prefill-campaigns). Use only
prefill samples, keep leaf evidence out of model credit, and do not reopen the
parked AM platform link work. Raw model files, generated binaries, captured data
and internal job logs are not part of these Git branches.

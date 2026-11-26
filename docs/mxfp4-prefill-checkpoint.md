# MXFP prefill source checkpoint — 2026-11-23

## Collaboration checkout

Use `OpenXiangShan/xsai-env:feat/mxfp4-integration` to work on the MXFP source
snapshot. This branch fixes the top-level gitlinks and `VERSIONS` together; its
XSAI and CUTE gitlinks also fix the nested dependencies. It is not a validated
release. The archive refs below are unchanged.

| Path | Owning GitHub repository | Branch to fetch | Pinned commit |
| --- | --- | --- | --- |
| `XSAI` | `OpenXiangShan/XSAI` | `feat/mxfp4-collab` | `5a2ee2d2ad8cc6713c90de381747e96f0b60bbfd` |
| `XSAI/CUTE` | `OpenXiangShan/CUTE` | `feat/mxfp4-collab` | `860f37961584c09b0651e927798dc83c926ced76` |
| `XSAI/CUTE/cute-fpe` | `OpenXiangShan/CUTEFPE` | `feat/mxfp4-collab` | `7368603c559446fd6e84292121bd5a43f9e8115d` |
| `XSAI/CUTE/XSAICache` | `OpenXiangShan/XSAICache` | `feat/mxfp4-collab-cute` | `3a40ffd93aa1fdbf1f4a1994806eaecfc7790090` |
| `XSAI/XSAICache` | `OpenXiangShan/XSAICache` | `feat/mxfp4-collab-xsai` | `d2d0893ac4556ed1a25139b9024305ef2a4e6c89` |
| `XSAI/difftest` | `OpenXiangShan/difftest` | `feat/mxfp4-collab` | `051dfd3a5b663d79c5498a585bdb8f42a299493c` |
| `NEMU` | `OpenXiangShan/NEMU` | `archive/mxfp4-prefill-20261123` | `a470913fa2ceab325d554f8855984cb81a68d01a` |
| `qemu` | `OpenXiangShan/qemu` | `feat/mxfp4-collab` | `741916e23ed884feeb68e57cd4019850155e5197` |
| `nexus-am` | `OurCompArchGroup/nexus-am-ame` | `feat/mxfp4-collab` | `1c88b7f0a58b2e424dbb97516bb4ebc1b18f2739` |
| `software/llama.cpp` | `OurCompArchGroup/llama.cpp` | `feat/mxfp4-collab` | `43336c9b35999a85c097f1db00a4007debb1cdf4` |
| `firmware/riscv-rootfs` | `OurCompArchGroup/riscv-rootfs` | `archive/mxfp4-prefill-20261123` | `4fa51538a2a822591b06d0eb06a331ab815fb38c` |
| `llvm-project-ame` | `OurCompArchGroup/llvm-project-ame` | `archive/mxfp4-prefill-20261123` | `372bc8d4c9f1b58c7cdab2acb2b3f7f8eb18e140` |
| `riscv-matrix-spec` | `OurCompArchGroup/riscv-matrix-extension-spec` | `feat/mxfp4-collab` | `9499d593f122bb7a344fdfaeab7af13ab35b0f0d` |

Start in a separate checkout. Use the recorded gitlinks, not `--remote`:

```sh
git clone --single-branch --branch feat/mxfp4-integration https://github.com/OpenXiangShan/xsai-env.git
cd xsai-env
git submodule update --init -- XSAI NEMU qemu nexus-am riscv-matrix-spec firmware/riscv-rootfs software/llama.cpp
```

For RTL work, initialize XSAI using its own `make -C XSAI init-force`. For the
custom compiler, readers with GitHub access to `llvm-project-ame` can initialize
it with `git submodule update --init --checkout -- llvm-project-ame`.

The snapshot includes four scale banks per CUTE side, the matching difftest
schema and AM regressions, the QEMU scale/stride/trap fixes, and the native
GGML MXFP path with its first-load `mfence` and opt-in RMSNorm/quantize/QKV
pipeline. The two cache pins are different on purpose: XSAI and standalone
CUTE use their respective masked-store implementations.

- NEMU's gitlink is the MXFP architectural reference. It does not contain the
  source of the exact R75 `PACK_MX` handler in the retained emulator. The
  rootfs pin has opt-in workload entrypoints but does not build or install the
  separate packed binaries by itself. There is no full-stack PACK release.
- The combined AM `matop.S` contains the guarded R75 PACK section and newer
  directed tests, so its whole-file hash differs from the exact R75 archive.
  Use the archive hashes below to reconstruct that older source pair.
- The historical four-bank full-core check closed the directed scale-register
  hang; it is not byte-for-byte validation of this RTL snapshot. The assembled
  pins have not been rerun together. No end-to-end speedup, board-level memory
  ordering proof, or larger padded-output correctness is claimed.

## Recovery refs

Use the archived revisions for the historical diagnostic and build inputs.
Do not reset a live worktree to an archive or combine independent controls by
cherry-picking them together.

| Owner | Branch | Commit | Contents |
| --- | --- | --- | --- |
| `OurCompArchGroup/llama.cpp` | `archive/mxfp4-prefill-20261123` | `7ade14bf470ec7c928e8289b58edab2bae9dba34` | MXFP native backend, opt-in shared RMSNorm/pack/QKV, directed tests |
| `OurCompArchGroup/nexus-am-ame` | `archive/mxfp4-prefill-20261123` | `028052ab81e2735922c362d5403017f14f4fb4ce` | Existing AM bare-metal fixtures and their model-shape interfaces |
| `OurCompArchGroup/riscv-rootfs` | `archive/mxfp4-prefill-20261123` | `4fa51538a2a822591b06d0eb06a331ab815fb38c` | Workload flags and packaging of the existing quantizer tests |
| `OpenXiangShan/qemu` | `archive/mxfp4-prefill-20261123` | `c08ee60beed86137201a95f980d9f0ce181671a4` | Experimental MXFP functional emulation |
| `OpenXiangShan/NEMU` | `archive/mxfp4-prefill-20261123` | `a470913fa2ceab325d554f8855984cb81a68d01a` | MXFP architectural reference and directed test source |
| `OurCompArchGroup/llvm-project-ame` (requires access) | `archive/mxfp4-prefill-20261123` | `372bc8d4c9f1b58c7cdab2acb2b3f7f8eb18e140` | `mlascale`/`mlbscale` mnemonics and MC tests |
| `OurCompArchGroup/llama.cpp` | `archive/mxfp4-packed-r75-20261123` | `51712f8e19b7c1d2455561ba925c32d574651e98` | R75 batch8/packed (`c72662b7e17ff857e1dafca38a6b6fe1c1f6c449`), shared-QKV overlay (`2d76560a2fbc7c68863d6165c79c5d024107d84b`), then the opt-in startup LUT correction |
| `OurCompArchGroup/nexus-am-ame` | `archive/mxfp4-packed-r75-20261123` | `697482dc29aaf392d38a6bc6be0e6f83ffb57e34` | Exact `tests/ame-gemm/matop.S` for that R75 build |
| `OurCompArchGroup/llama.cpp` | `archive/mxfp4-model-prefill-20261123` | `8b5326a6119658d0784d62eff20dc544bc896776` | Native MXFP4 layout R3, phase-off model-control source overlays, and the separate Stories attention screen |

For example, in a separate initialized `xsai-env` checkout:

```sh
git -C software/llama.cpp fetch --no-tags origin refs/heads/archive/mxfp4-packed-r75-20261123
git -C software/llama.cpp checkout --detach 51712f8e19b7c1d2455561ba925c32d574651e98
git -C nexus-am fetch --no-tags origin refs/heads/archive/mxfp4-packed-r75-20261123
git -C nexus-am checkout --detach 697482dc29aaf392d38a6bc6be0e6f83ffb57e34
sha256sum nexus-am/tests/ame-gemm/matop.S
```

The expected assembly SHA-256 is
`26ee87667ec98d831cbaa8735fdeee577265d197a5386bf65dcc9b336cbf9530`.
The R75 static RV64/RVV build opts into `GGML_RV_AME` and `GGML_RV_MXFP4_PACKED`;
set `GGML_RV_MXFP4_PACKED_ASM` to the absolute path of that exact assembly.
For the corrected real-prefix build, pass `-DGGML_AME_FP16_LUT_INTEGER_NONFINITE=1`
to the C compiler for `ggml-cpu.c` in both arms. It avoids a startup exception
from the nonfinite FP16 LUT entries without clearing FCSR. Do not enable the
startup trace macro or assume this commit enables the masked Softmax variant.
Reuse the existing cross-toolchain configuration and CMake `test-quantize-fns`
target. This map restores source, not the original host toolchain or a
byte-identical ELF. The authorized raw receipts retain the configure args,
compile database, source hashes and diagnostic witness.

## Model prefill control and attention screen

Fetch `refs/heads/archive/mxfp4-model-prefill-20261123` in `software/llama.cpp`
to recover three separate source commits:

- `099819498336565ce1d651ed97757683a41330f0`: R3 native MXFP4 layout sources
  plus the exact `test-quantize-fns` fixture. This is the model-control
  lineage, not the shared-QKV experiment.
- `87635086191a34087874ea268cdd3cc796db87e9`: phase-off real-model control
  sources for FP16 LUT nonfinite handling and masked RVV Softmax. The recorded
  build selected `GGML_AME_FP16_LUT_INTEGER_NONFINITE=1` and
  `GGML_AME_RVV_SOFTMAX_MASKED_EXP=1`; startup diagnostics were off. The LUT
  source can be used in both fusion arms without clearing the caller's FCSR.
- `8b5326a6119658d0784d62eff20dc544bc896776`: the exact `sgemm.cpp` from the
  synthetic Stories screen. Its relink selected `GGML_XSAI_RVV_F16_STORIES_TILE23=1`
  and `GGML_XSAI_RVV_F16_STORIES_KQV_ZERO_SUFFIX=1`. Do not count it as a real-model gain.

Checkout `87635086191a34087874ea268cdd3cc796db87e9` to omit the attention
variant. These commits recover byte-verified sources, not the original
toolchain, link inputs, or production ELF.

## Validation boundary

The completed Stories15M real-GGUF PP256 fallback witness used
`GGML_AME_RMSNORM_MXFP4=pipeline` vs `pipeline+qkv`. The latter ran one shared
pack, skipped two redundant packs, and completed Q/V/K byte-for-byte with the
K288 `256+32` tail. Natural FCSR `0x17` took the original quantizer fallback in
QEMU, so this is **not** a `PACK_MX` instruction hit. The earlier Qwen3-0.6B
bounded witness completed Q and V but timed out before K completed. Neither is
DUT timing or a prefill checkpoint. The independent short-screen experiments
are not silently enabled by these archive branches.

With the LUT correction and scalar `zfh=true` in the local QEMU CPU options,
both true PP256 models entered `ggml_ame_begin_rmsnorm_qkv` and reached
`PACK_MX` (`0x0e8810fb` at ELF offset `0x2f5a80`) without forcing FCSR. The
local emulator trapped on that instruction. This proves the real dispatch
can reach the packed branch, not instruction retirement or Q/V/K completion
on that branch. The hardware timing gates remain closed.

## Real-model K-stop witness

The untimed diagnostic sources are archived separately from the production
overlays, on `archive/mxfp4-r75-kstop-20261124` in these two repositories:

| Owner | Commit | Existing entrypoint |
| --- | --- | --- |
| `OurCompArchGroup/llama.cpp` | `c9b775343b8334fafa8af319b207fe653fe8eb70` | `llama-bench` eval callback and AME native output, pack and FCSR capture; two source files match the retained witness overlays |
| `OurCompArchGroup/riscv-rootfs` | `a5e31937d41574e0d6f388c681aa13b755f81df1` | `run_llama_bench_full` readout; the function matches the staged Linux guest, not the whole rootfs tree |

Use the R75 build flags and exact PACK assembly identified above. Both arms use
the same witness with true GGUF, PP256/T1/B256/UB256/N0, no warmup, and one rep.
Set `LLAMA_BENCH_QKV_PREFIX_OUT` to a fresh writable prefix and
`GGML_AME_MXFP4_REUSE_ACTIVATION=0` in both arms. Compare
`GGML_AME_RMSNORM_MXFP4=pipeline` against `pipeline+qkv`. Enable the AME
summary (`GGML_AME_PROFILE=1`); keep per-node detail and progress off.

The staged guest images were read back, not executed. Require
`QKV_PREFIX_DONE third_projection=1`, matching lengths and SHA-256 for the six
Q/V/K dumps, matching natural FCSR and errno, and three distinct native
weight keys. Stories must include K288 `256+32`; B must report one shared
producer, three native completions and two skips. For the exact retained NEMU
(`9034d54ee09f5858db02d4fb244a0e25a6e1859ec06d16bb89e5c28c23d40a23`),
the `PACK_MX` handler return is `0x411240`. Stories has 6,912 expected return
hits in A and 2,304 in B if all rows take PACK (256 rows × 9 K32 blocks ×
three or one packs). A return count is not a cycle sample. Keep the witness
out of all timed builds and ledger credit.

The budget admission, result collector and ledger tooling is in this parent
branch; see [agent workflow](agent-workflow.md#prefill-campaigns). Use only
prefill samples, keep leaf evidence out of model credit, and do not reopen the
parked AM platform link work. Raw model files, generated binaries, captured data
and internal job logs are not part of these Git branches.

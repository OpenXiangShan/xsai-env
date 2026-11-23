# XSAI AME Diagnosis Rules

This reference specializes the Yuque article
`软硬件协同优化方法论: 从性能信息到优化点` for the GGML Q8_0/AME path.
The source article is `https://bosc.yuque.com/up3wk0/eegpen/dgpubeyv21bw4rwt`.

## Evidence Order

Diagnose in this order:

1. Static work and hardware roofs.
2. End-to-end prefill/decode timeline.
3. Operator cycle distribution.
4. AME phase distribution.
5. Isolated instruction, synchronization, or RTL counters.

The first abnormal event in a causal chain is the working root cause. For example:

```text
repeated layout copy -> AME waits for tile -> low matrix utilization
```

Low matrix utilization is the terminal symptom, not enough evidence for more RTL
compute resources.

## Metric Definitions

For the selected GEMM precision (Q8_0 or MXFP4, with its own verified peak):

```text
logical_ops       = 2 * M * N * K
operator_ops/cyc  = logical_ops / total_cycles
operator_MFU      = operator_ops/cyc / peak_ops_per_cycle
macro_ops/cyc     = logical_ops / ame_tile_call_cycles
macro_MFU         = macro_ops/cyc / peak_ops_per_cycle
edge_ratio        = edge_tiles / tiles
phase_share       = phase_cycles / total_cycles
```

Use the peak of the exact FPGA configuration and precision. The known
MinimalMatrixConfig/CUTE_2Tops INT8 configuration uses 512 MAC/cycle, or 1024
logical ops/cycle, but do not reuse that number for another configuration without
checking it.

`macro_MFU` includes the measured AME call wrapper and synchronization around each
tile. It is a useful upper-level matrix-path metric, not a claim about the internal
MAC-array occupancy.
For a fused RMS/quantization/GEMM graph, declare whether `total_cycles` includes the
whole graph while `logical_ops` counts only GEMM. Do not compare that metric with a
ready-input compute-window MFU as though the denominators were identical.
Use the conditional resource/shape model in `measurement-protocol.md`; low current
MFU is not excused by a distant optimistic roof.

## Current Phase Semantics

| Profile phase | What it measures | Common root causes | First software probes |
| --- | --- | --- | --- |
| `prepare_cache` | F32 activation quantization into Q8 AME blocks and cache maintenance | scalar reduction/rounding, cache miss or generation churn, cold allocation | RVV whole-K quantizer, prove cache identity, split cold/steady measurements |
| `pack_a` | weight tile selection or copy into AME A layout | repeated immutable-weight copy, missing packed tile cache | use prepacked `src0_tile_a`, inspect panel path and cache lifetime |
| `pack_b` | activation blocks copied into AME B tile/panel | repacking per M tile, zero fill, poor panel reuse | pack one B panel per `(j0,kb)`, reuse across M tiles |
| `zero_c` | INT32 tile clear | redundant software clear, lack of architectural zero semantics | measure skip knob only where correctness proves overwrite |
| `ame_tile_call` | matrix submit/wait and tile execution | FIFO bubbles, serialization, memory path, macro latency, low internal occupancy | isolated tile probe, async batch, sync and register-pair counters |
| `accumulator_initialization` | F32 output-tile accumulator clear | repeated large stack clear | fuse initialization with first valid contribution where semantics allow |
| `scale` | INT32-to-F32 conversion and weight/activation scale accumulation | per-K64 epilogue traffic, repeated scale loads, vector issue limits | RVV loop shape, reuse scales, whole-K INT32 accumulation when mathematically valid |
| `store` | F32 output tile transpose/store | strided load or transpose cost | change accumulator layout or vector store mapping |

`prepare_cache` is dynamic activation work. Offline weight repacking does not remove
it. Weight packing happens in the backend buffer path and must be accounted for
separately when measuring cold model initialization.

### MXFP4 Weight-Cache Attribution

Separate the outer scale-domain scan from `weight_prepare`, then split that
bucket into cache hits and misses. A hit can still re-pack and compare every
source block to detect direct writes. A hit count alone does not measure the
cost avoided, and a W0 miss does not tell how often the warm path runs. Use
the existing profile's hit/miss counts and cycles to pick the next probe.
For a warm comparison A/B, bind the real weight bytes and retain the
payload/scale mutation oracle; a cold refill or complete owner is a separate
scope. Do not remove revalidation merely to improve the hit timing.
Separate address calculation, repacking, scratch traffic and exact
comparison when choosing a follow-up. Check the linked loop for scalar,
unit-stride, strided and segmented accesses before board admission. A slower
segmented variant establishes a loss for that path and access pattern, not
for RVV generally or for any one RTL component. Reject it on the measured
path; keep exact validation and change one mechanism in the next contrast.
If linked integer address work repeats per block, test invariant addressing
separately from packing. Reuse the canonical panel-index calculation for the
initial address and prove the recurrence covers the same payload and scale
indices. An instruction removed from the loop is not a cycle saving until
both matched arms run; the measured saving remains local to that boundary.

### RMSNorm / MXFP4 Preparation Attribution

Use the producer's existing phase instrumentation to distinguish:

- RMS statistics: F32 squares, reduction, mean, square root and reciprocal;
- separately rounded RMS and gamma multiplies;
- finite/tiny-domain screening and packed-path qualification;
- vector encoding, nibble/layout conversion and final AME packing;
- unassigned preparation overhead, which must remain unassigned without evidence.

Profile ON/OFF controls on matched inputs. A percentage of instrumented preparation
is neither a whole-graph percentage nor reduction-only time. Keep uninstrumented
measurements for gain claims; quantify instrumentation overhead without simply
subtracting independently measured medians.

The existing `analyze-ame-profile.py` attaches `AME_RMS_PACKED_PHASE` only to a
matching graph sample window. For a fully packed fused sample with no fallbacks it
reports the signed `activation_quant_pack` minus the seven raw timer totals. This
is unassigned instrumented accounting, not a separately timed phase or exposed
preparation. In the RVV domain path, `rms_apply` also covers the vector amax
reduction and scratch store; `vector_pack` begins after the scale scratch refill.
The collector still owns binary identity, expected phase coverage and work gates.

For a slow adjacent MXFP4 producer without supplied RMS maxima, check whether
the canonical scale proof can use unsigned RVV maxima of the actual F32 lanes.
A packing speedup can come from bypassing scalar qualification even when all
PACK instructions stay identical. Bind the branch to the captured maxima and
raw incoming FCSR; preserve the original per-block scale, short-tail path and
sticky-NV fallback. Measure the enclosing producer, not just the new proof,
and do not generalize one captured tensor to the full model.

For an already-vectorized admission scan, inspect the linked loop for repeated
immutable tensor-extent calls and full-register spills before widening the RVV
work. An external metadata helper can survive in every K32 iteration even
when the arithmetic is vectorized. Hoist it as a separate change; verify the
same reads, rejection semantics and raw FCSR before timing.

For a hot fraction `f`, a hypothetical phase speedup `s` removes
`f*(1-1/s)` of THAT denominator's time. For example, if entire RMS statistics
is 31% of preparation, making the entire phase 4x faster ideally removes 23.25%
of preparation time. This is not an observed reduction-only or model speedup.

### Ordered Versus Unordered RMS Reduction

An unordered-sum mnemonic permits reassociation; it does not guarantee a faster
implementation. Read actual `VecDecoder.scala`, uop splitting, execution logic
and emitted code. In the audited XSAI implementation, widening ordered and
unordered sums share `vfwredosum` / `VEC_VFREDOSUM`, whereas nonwidened unordered
sum uses `VEC_VFRED`. Recheck the current source before relying on this fingerprint.
Changing only the widening opcode name, or only a decode alias without matching
uop/execution support, is not an established optimization.

Probe the canonical RMS helper/opt-in paths before adding code. Screen separately:

1. Original F32 square plus ordered F64 accumulation.
2. F32 square plus multiple partial F64 vector accumulators, then a nonwidened
   F64 unordered horizontal reduction.
3. A separately declared F32 unordered/partial-sum variant.

At first hold square precision, sqrt/reciprocal, gamma and quantization fixed.
Inspect register pressure/spills, active lanes/tails and absolute phase/graph
cycles. Do not assume a numerical tolerance or a speedup from the algorithm name.
Only variants passing the lightweight numerical/work-completion gate and showing
useful measured gains proceed to the full error/quality gates.
Changing addition order does not remove the square and two weighted multiply passes,
so it improves actual time without by itself invalidating a multiplication-only roof.

## Fingerprints And Prescriptions

### Preparation Or Packing Bound

Fingerprint:

- `prepare_cache + pack_a + pack_b` dominates total cycles;
- macro-path MFU is materially higher than operator MFU;
- `ame_tile_call` is a minority of total cycles.

Prescription order:

1. Remove repeated immutable copies.
2. Vectorize quantization and layout conversion.
3. Reuse packed panels across the outer loop that does not change their data.
4. Pipeline preparation with matrix execution only after reducing avoidable bytes.

Screening proof: the light gate passes and preparation/packing absolute cycles fall
for comparable completed work and checked outputs; final acceptance also requires
the full declared numerical contract. A falling percentage alone is insufficient.

### Scale-Epilogue Bound

Fingerprint:

- `scale` is the largest phase;
- AME produces INT32 tiles faster than software converts and accumulates them;
- the number of scale passes grows with `ceil(K/64)`.

Prescription order:

1. Hoist invariant scales and eliminate repeated loads.
2. Improve RVV traversal and accumulator layout.
3. If both weight and activation use one scale for the full K dimension, accumulate
   all K64 INT32 tiles first and apply one scale epilogue.

For whole-K INT8, prove overflow before using a single INT32 accumulator:

```text
K * max_abs(a_q) * max_abs(b_q) <= INT32_MAX
```

For values limited to `[-127, 127]` and `K=8192`, the conservative magnitude is
`8192 * 127 * 127 = 132128768`, below `INT32_MAX`. Recheck this bound for every
larger K or changed quantizer. This optimization changes quantization granularity
and accumulation order, so operator error and model-level accuracy are mandatory.

### Matrix Path Underfilled

Fingerprint:

- software phases have already been reduced or hidden;
- isolated full tiles still have low macro-path MFU;
- FIFO occupancy, issue gaps, sync waits, or matrix load/store stalls explain the
  remaining `ame_tile_call` cycles.

Prescription order:

1. Submit multiple independent tiles up to the documented FIFO depth.
2. Alternate independent accumulator/register pairs if dependencies serialize issue.
3. Double-buffer tile memory only if the bandwidth roof is not already saturated.
4. Consider RTL only when the trace identifies a specific internal queue, port,
   accumulator transfer, or load/store bottleneck.

Expected proof: `ame_tile_call` absolute cycles fall and the isolated full-tile
result improves. Do not accept a gain caused only by skipping required sync or clear.

For a pipelined kernel, compare the matrix-progress coverage and whole-ROI share in
[Same-hart overlap](measurement-protocol.md#same-hart-overlap). High coverage with
a low ROI share can mean a long RVV tail or gaps between matrix tiles. Locate the
first gap: try a shorter RVV burst or an earlier matrix submission if the PE runs
out of tiles; try unrolling independent RVV operations if vector input repeatedly
stops while the PE advances. Check accumulator dependencies, spills and the changed
scalar loop work. Change one knob and remeasure; more tiles alone may just repeat
the same short bursts. Keep the last tile's acquire and the input-panel lifetimes.

### Edge-Tile Bound

Fingerprint:

- `edge_ratio` is high;
- small M or N uses a full hardware tile for little logical work;
- the same kernel is much more efficient on aligned shapes.

Prescriptions: shape-aware kernel selection, smaller tile variant, padding/batching,
or grouping compatible small operations. Report useful logical ops, never padded ops,
in MFU.

### End-To-End Bound Outside AME

Fingerprint:

- AME operator cycles are a minority of graph or benchmark cycles;
- a large operator improvement produces a small tokens/s change.

Prescriptions: use graph profiling to identify the next operator, reduce dispatch or
boot overhead, and distinguish prefill from decode. Apply Amdahl's law before coding:

```text
speedup_total <= 1 / ((1 - hot_fraction) + hot_fraction / speedup_hot)
```

## Trade-Off Rules

- Diagnose gains against the same qualified baseline; a failed lightweight output
  or completed-work check cannot be excused by better counters.
- Larger panels reduce repeated packing but consume workspace and may reduce locality.
- More async slots hide latency but need independent buffers and architectural state.
- Whole-K quantization reduces epilogue work but can increase quantization error.
- Fusion removes traffic but can increase register pressure and make scheduling rigid.
- Higher occupancy can reduce per-operation registers and cause spills.
- Faster compute may not help a bandwidth-bound graph; increased buffering can move
  the bottleneck to on-chip capacity, ports or memory traffic.
- More pipeline stages may improve frequency while worsening short-task latency;
  fewer cycles may lose to a lower realizable clock. Compare cycles/design frequency.
- Quick-synthesis area/timing and power estimates need matched tool/constraint/PVT
  and activity context; do not infer energy from utilization alone. Final physical
  timing, congestion or power may erase the estimated benefit.
- Shortlist only meaningful gains above uncertainty with acceptable PPA and
  validation cost. Confirm them again on the fully validated implementation;
  performance measured before a later correctness fix is not final evidence.

Treat any `skip_*` knob as a diagnostic probe until the architectural overwrite and
memory-ordering contract proves it correct.

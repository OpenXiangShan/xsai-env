---
name: xsai-ame-optimization
description: Diagnose and optimize XSAI prefill operators, including RVV and GGML Q8_0/MXFP4 AME kernels. Use for extracting executed model shapes and production functions into short AM bare-metal PLDM A/Bs, parallel model screening, cumulative per-model prefill checkpoints, lightweight correctness and PPA screening, shape-aware Roofline/MFU analysis, RMSNorm/quantization fusion, packed panels, same-hart Zmasync pipelining, or CUTE utilization.
---

# XSAI AME Optimization

Use a qualified, reproducible baseline and a measurement-driven loop:

```text
qualified baseline -> lightweight correctness gate -> performance/PPA screen
                   -> beneficial candidates -> full acceptance -> same-revision remeasurement
```

Do not infer a compute bottleneck from low AME utilization alone. Data preparation,
layout copies, scale epilogues, synchronization, or edge tiles can starve the matrix
unit and produce the same symptom.

For a same-hart Zmasync kernel, try overlapping the RVV epilogue of tile `i` with
matrix work on tile `i+1`. Store `i` and register its release, submit `i+1` to a
different output buffer, then acquire the request for `i` before reading its result.
Keep input panels live until their matrix loads finish. Use `mfence` when new
scalar/vector writes must be visible to later matrix accesses. See the
[ISA example](../../../riscv-matrix-spec/spec/zmasync_appendix.adoc) and the
[stream/serial measurement](references/measurement-protocol.md#same-hart-overlap).

## Screening Is Not Acceptance

For optimization of an existing correct design, first establish that the baseline
passed full validation for the declared scope and can be reproduced. A successful
build or partial regression is not baseline qualification. New functionality or an
unqualified baseline needs correctness establishment before performance decisions.

Each candidate must pass a scope-appropriate lightweight gate: compile/elaborate,
lint, key assertions, directed tests and basic numerical comparison as applicable.
Screening workloads must check outputs, completion and actual completed work.
Early `done`, omitted reductions/tails, dropped backpressured data or unintended
fallback are not gains. A failed light gate permits diagnostic timings only, not
entry to the performance shortlist; preserve original oracles and failure evidence.

Reserve exhaustive correctness/accuracy and implementation validation for candidates
with meaningful repeatable benefit. Label them
`performance-promising / light-gate-passed / full-acceptance-pending`, not correct or
accepted. Do not serialize every eligible timing probe behind full difftest,
rounding-mode or model regressions. Full acceptance must finish with performance/PPA
remeasurement on the exact validated revision; later fixes invalidate earlier claims.

## Read The Routed Guidance

Read these references before changing code:

- `references/measurement-protocol.md` for the experiment contract, metrics, and validation ladder.
- `references/diagnosis-rules.md` for XSAI phase semantics and bottleneck fingerprints.
- `references/experiment-template.md` when creating or updating an experiment record.

Also use the existing skill that owns each execution surface:

- `xsai-llama-rootfs` for `firmware/riscv-rootfs/apps/llama.cpp/`.
- Existing `nexus-am/tests/` targets for model-shaped bare-metal probes; use
  `nexus-am/tests/ame-gemm/` for AME/MXFP4 where its kernels and checks fit.
- `pldm-workflow` for PLDM resource checks, builds, runs and file transfers.
- `xsai-fpga-flow` for FPGA loading, reset, and UART capture.
- `xsai-cute-rtl` for `XSAI/CUTE/` analysis or changes.
- `xsai-submodule-git-flow` for commits inside `firmware/riscv-rootfs` or `XSAI`.

Keep one primary write scope per experiment. Finish and measure a software change
before editing RTL for the same hypothesis.

## Model-Guided Bare-Metal Iteration

Use **short AM pairs on PLDM as the default software optimization loop** after
qualifying the model baseline. Do not run the full operator graph for each knob.
Work from the executed prefill profile:
`whole-prefill budget → existing runnable owner → short PLDM A/B → machine ledger`.
Before building or booking a new prefill pair, run `agent-workflow-guard.py admit`
against the frozen manifest and `experiments/results.jsonl`. No attributable
cycle forecast against the full prefill median, no run. Rank by weighted expected
savings divided by build, PLDM and integration cost; the default floor is 1%.
Launch through the same guard's `launch` with the existing pinned recipe. Do not
polish a phase whose whole budget cannot close the gap, or retry a mechanism after
two failures. See [commands and data contract](../../../docs/agent-workflow.md#prefill-campaigns).
Link the production
function with the executed shape, strides, input/state and tail; change one
factor at the smallest boundary that can answer the question. For slow vector
preparation, screen the real preparation path and use a ready-input AME control
to separate its cost from the matrix path. Rejoin the handoff only when it is
needed to test the hypothesis or score the complete operator. An extracted
`K=288` operator must still do `256+32` work, not time the aligned prefix alone.
Prove the optimized branch completes the same work, including the real fallback
controls.
Name the exact linked entry and its input-dependent predicate before booking
a board. A linked symbol, matching geometry, or graph-level begin/end marker
does not prove native dispatch. If only producer bytes are missing, reuse an
archived handoff or one bounded, untimed witness through the actual production
handoff. A byte match does not establish cache residency or operator timing.
When both arms rebuild an operand outside the timer with the real producer,
check its bytes, applicable FP state and canaries before the first sample.
This can qualify an operator screen with reconstructed inputs; it cannot
substitute for production entry-state or complete-owner measurements.
If production input or cache state cannot be bound quickly, keep any provable
synthetic hit as a screen only and advance the next runnable call rather than
capture a full graph.
If the owner cannot run, use only a forecast-qualified prerequisite leaf screen
or take the next runnable owner. Leaf screens never score. Keep platform work
in a separate backlog: one dependency and one bounded validation per attempt for
a named, budget-qualified call; park after two failures. Fewer symbols or a
passing provider test is not a runnable owner. Do not substitute production
allocator, locks, cache, fallback or error semantics to make it link.
Keep one extraction/build queue per model. Build, link-check and stage both
arms before a board opens; run the first eligible pair while preparing the
next. A capture, owner link or closed checkpoint in one model does not delay
the other's eligible pair. When only one model can run, keep preparing the
other model's next executable call instead of waiting at its blocked owner.
Use the short self-checking PLDM pair for correctness and timing when it can
check both; use simulation only for a named check the pair cannot cover.
If both pairs are ready, run them in parallel only after one fresh admission
check proves disjoint compatible placements and physical cores, independent
runtimes, output paths and locks, and per-job release checks. Two best-fit
answers using any of the same domains are not two lanes. Neither is a shared
run lock or a release check that rejects any live run from the same owner.
Use any compatible idle placement the allocator admits; do not pin this
workflow to board numbers.
Treat the allocator's best-fit report as a prediction, not a board assignment.
Check the actual download domains and each lane's release; if the two launches
cannot be kept disjoint, submit only one at a time.
If only one lane fits, run that pair and hand the lane to the next ready
pair after verified release and fresh admission. Do not queue a run against
a known shared lock or preempt. Reuse the sealed pair and the canonical
launch-time gates; preflight is not a reservation. A refusal before allocation
or download is a resource hold, not a DUT result. Retry only on fresh evidence.
Check the host policy before submission. Reuse documented explicit user
approval only when its host and frozen design scope match; it does not waive
live capacity, placement, identity or release checks. Without a matching
approval, park an ineligible host rather than repeat capacity probes.
On resumption, reconcile staged entries by accepted job ID, including failed
terminals. Require guest, collector and release receipts for measured pairs.
A stale staging record is not a reason to remeasure a retained or rejected
variant. Promote a synthetic screen only with new production-state evidence.
Reuse a sealed, hash-matched A image when testing a new B, but run both in
the new matched pair. Reusing the image does not qualify its historical
cycles as a control. Keep a win at its measured scope and advance the next
high-cost call; revisit it only for a named coverage or control gap.
Close repeatable losses likewise. For the next A/B, name what changes in the
linked hot loop and why that targets a measured cost; do not sweep variants
of a losing access pattern just because they use fewer source operations.

Use the cumulative savings gate only to decide when to run integrated
prefill for a model, never to admit an individual short pair. Freeze disjoint
production scopes, call weights and the baseline for that model. Remeasure the
entire frozen ledger, including unchanged scopes, on one merged phase-off
revision:
W1/R3 or better hot and at least three independent matched resets per arm
cold. At a 30% checkpoint require both `1 − sum(calls × median(B)) / sum(calls × median(A))`
and `1 − sum(calls × max(B)) / sum(calls × min(A))` to be strictly above 30%
before rounding. In both comparisons, test `10 × candidate < 7 × baseline`
on the exact totals, not sums of per-operator percentages. Missing rows leave
the gate unset. Before allocating for integration, bind each credited dispatch
and its expected optimized/fallback
counts to the production call and exact integrated ELF. Run one matched
prefill only for that qualifying model and verify the hits in the run. Rebase
only after acceptance; otherwise retain the old baseline and reduce the
failure to another short pair. Start a fresh savings batch for the accepted
model only. The other model's queue and baseline stay independent.
Report the PP configuration, measured raw DUT cycles, and missing strata;
do not run TG or turn screening/phase diagnostics into a checkpoint score.
Keep integrated DUT cycles separate from the operator totals used to admit it.
Keep screening and checkpoint qualification as separate queues. When a leaf
wins but the complete owner is not runnable, keep the win at leaf scope and
test the next real substage (for example quantize/pack/layout) or the next hot
operator. A faster activation admission scan does not make the subsequent
quantizer faster by the same amount: measure the merged owner against the
frozen baseline before crediting either change. Do not rerun the winning leaf
or rebuild the entire model to unblock ownership. Resume an admitted board
run by its job ID; never resubmit it because the local follower disconnected.
Extract only the next useful shape/function pair, not the whole graph. Reuse
`nexus-am/tests/ame-gemm` where it fits; link the production function, not a
fixture copy. Before building, bind the observed callsite and count to the
production symbol, shape/strides, entry state, timed boundary, and expected
work. For model weights, hash the exact tensor spans from the accepted GGUF;
do not substitute another conversion with the same shape or quantization.
Before allocation, prove the production input reaches the changed path and
the final AM ELF calls it. Preserve executed tails in both arms: `K=288`
is the 256-element body plus an actual 32-element tail, not a `K=256` proxy.
Start with the smallest boundary that can test the hypothesis; do not wait
for the owning operator's full link closure to screen a leaf.
Rank ready pairs by plausible saved DUT cycles per prefill using executed
call counts and measured costs, not by a leaf's percentage alone. Submit
the smallest ready pair that answers the question instead of widening the
payload. Repeat timing only for the target call and explicitly justified
performance controls; keep other siblings and directed tail/fallback checks
untimed. Stop on the existing collector's exact completion contract, then
verify the runtime terminal and resource release.
For a linked Linux AME leaf, reuse the existing AM test's platform setup;
verify hart TLS and matrix-state enablement before the first sync or matrix
CSR access. Keep setup out of both timing windows.
A link-only scout is not a runnable A/B: the fixture must call the symbol
with the production dispatch/layout and verify the work actually completed.
After reusing or relinking an AM archive, read the selected mode from the
final payload (for example `__am_mainargs`), not just the build flags or the
presence of the intended entry in the ELF.
Disassemble the full linked address range when local labels split a symbol.
An opcode also used by the control is not a branch witness; trace the
candidate-only actions (for example cache fill and reuse) at their exact PCs.
For RVV writeback, check the linked control before assuming scalar extraction:
the compiler can already lower it to a one-lane vector store. Count mode
switches and address reloads through the next tile, not just store instructions.
For an input-dependent branch, first reuse the smallest archived production
input slice that can prove its predicate (for example, a whole softmax row
and its matching mask and scale). Recreate a missing slice from the nearest
already captured producer input with the original function and transforms,
or use a capped production capture. State the witnessed call and stratum;
one hit does not qualify every call of the same shape. If the bounded check
cannot reach that call, advance another eligible pair rather than extending
the run toward a full graph.
For packed activations, check full fast-batch and partial-tail counts for
the exact captured row stride, and time the original production entry.
Exercise the original fallback with a directed sticky-NV case; an isolated
fallback sample proves coverage, not a fallback speed verdict. Keep a
repeatable producer win out of the operator ledger until its owner is measured.
Check effective aliasing in the graph allocator, not just tensor creation:
an out-of-place graph node may reuse its input storage at runtime. Match the
observed or permitted alias cases in the short fixture and recheck the exact
linked loop. When aliasing also changes the control's vectorization, do not
attribute the whole A/B delta to the removed loads.
If an archived capped trace finished the producer and timed out in its
consumer, move the cutoff to the consumer's pre-execution query at the same
cap. A timeout in an earlier operation does not qualify a later cutoff.
Prefer stopping at the real consumer before it executes, after synchronizing
its input and applying all upstream transforms (for example, gamma after
RMSNorm). Record the actual tensor edge, stride, and raw entry FCSR. A shared
Q/K/V input is not proof that the three calls share dispatch or entry state.
When replaying a producer to recreate a consumer's cache state, bind its
source strides and precision and first verify the full consumer input against
an oracle valid for the target. Use the same producer in both timed arms
unless the producer is the tested change. Run it immediately before each
consumer sample; keep logging, buffer scans and oracle checks after the timed
consumer. Bind the replay's observed handoff FCSR, not a synthetic timing
seed. An untimed match qualifies the replay input, not production cache
residency or elapsed cycles. If only the consumer's entry FCSR was captured,
do not call it the producer's entry FCSR.
If an unordered reduction yields different bits in the simulator and DUT, keep
the mismatch as diagnostic evidence. Check the allowed operation order and
derive a target-valid producer oracle and new consumer reference before timing;
do not substitute the DUT digest for a full comparison or loosen the old oracle.
Check linked dispatch and real instruction execution separately. If the local
interpreter traps on a required instruction and emits no required case records,
its exit status is not a numerical verdict. Keep the directed payload untimed
and run it on a compatible PLDM design; do not repeat the same simulator pass.
Keep fixture setup and the oracle outside the timed call; do not move any
production conversion, layout copy or synchronization there to claim a gain.
If a change removes a library call from the timed path, verify the control's
actual linked provider. AM's `memcpy` is not necessarily the production
`memcpy`. Reuse the pinned implementation at that callsite when possible;
otherwise report the result against the named AM provider, as screening only.
See [timed dependency fidelity](references/measurement-protocol.md#timed-dependency-fidelity).
Carry one testable change per pair. Before building, bind the model
and runtime callsite to `(M,N,K)` or vector width and rows, call weight, strides,
layout, cache state, production symbol, A/B branches, work counts, and the timed
boundary. Keep the real inner dimensions and tail (for example, `K=288` includes
the final 32 after 256); do not test only the aligned prefix or replace the tail
with padding. When changing matrix K tile width, carry the same accumulator
through the tail; calling a zeroing tile entry twice is not equivalent. A
ready-panel screen may exclude pack work but cannot score the whole operator.
For mixed prefix/tail widths verify operand offsets, rounding points and
synchronization for both parts. Use an independent oracle valid for the
actual replay inputs, not just for a bounded directed case.
Shrink only an outer cohort that keeps the same dispatch and changed
branch. Time the short call, with output and terminal checks outside the cycle
window. Do not boot Linux or replay an entire graph for routine iteration.

Keep unchanged strata that share the edited dispatch, especially single rows
and true tails. If a bulk win moves or slows an old route, time its enclosing
dispatch as well as the leaf. Recheck the excluded stratum on any narrowed or
merged build: selecting the original leaf does not preserve its entry cost
or code layout. Reject the tested variant if a control regresses beyond
spread; a new A/B should isolate a named cause, not try to erase the result.
For attention, bind KQ and KQV independently. Record both the tensor strides
and the leading dimensions seen by the linked kernel after casting. Keep
the mixed-type decline and conversion inside the timed operator; when changing
only one tile, keep the other call's route fixed in both arms as a control.
For a fixed shape or stride, specialize one proven invariant at a time.
Compare the exact linked hot loop and tail separately from setup and output
stores. A lower whole-symbol instruction count does not justify adding work
inside the repeated loop. If only outer address arithmetic changes, time
that narrow contrast without assuming a different compute or memory bottleneck.
When the link moves hot code or timed buffers, record those changes; equal
loop instruction counts do not isolate the cause of a cycle difference.
Before replaying a staged leaf, compare its enabled flag, dispatch and hot
loop with prior enclosing-operator results. A narrower fixture is not a
new candidate when that same specialization was already rejected.

Maintain a separate ready queue for each model, ordered by attributable
baseline cycles per prefill, not FLOPs or leaf percentage. Pick the highest-cost
eligible call, not the highest-cost blocked one. Record the exact unlock
condition for a missing capture, owner link or run cap; advance the next ready
pair rather than polling that blocker. Build and stage independently of board
admission. Launch both ready pairs when one fresh capacity check admits two
compatible disjoint placements, enough physical cores, and independent
same-design runtime, locks and per-job release. If only one fits or a runner
still needs a shared lock or owner-wide release check, launch the first
eligible pair and keep preparing the other. Do not use a blocked submission
as a queue. Match placement within each A/B, not across models. A preflight
best fit is not an allocation; use the actual downloaded domains for the
match and release checks. Use any eligible idle placement without preemption.
An isolated leaf can enter screening without waiting for ledger coverage.
Count it toward the checkpoint only after timing the complete operator in the
combined revision, including unchanged work and dispatch. Bind the leaf and
its enclosing operator to one call family so the rollup cannot count both.
Reuse that binding across candidates; revalidate any changed dispatch, input
state, work count, or timed boundary instead of re-extracting the graph.
Use a bounded path and output check to qualify the short PLDM pair. Do not
repeat a routine functional-simulator pass when the exact linked path is
already qualified and the board fixture can check work and output itself.
If tracing the repeated timing fixture is too slow, reuse its one-call check
mode and bind the executable code, symbols and branch inputs to the timing ELF.
Use the workload's real dimensions and loop trip counts even in a synthetic
fixture. Mark synthetic data or unproven cache state as screening-only unless
the timed path and state are shown to match the production call. Model weight
bytes, activation provenance, and cache state are separate checks. For paired
operands, bind immutable weights by executed tensor ID, model digest and
stored stride with the existing importer. Capture only the missing dynamic
operand at the exact consumer edge. A weight ID list for multiple calls does
not extend a single captured activation to those calls. If archived inputs
lack the bytes needed for a stronger check, advance another short pair instead
of rerunning the whole graph to collect them.
When a short prefix can recover a needed activation, reuse the production
producer and existing graph-evaluation callback. Capture exact bytes and
terminate before the next unrelated operator. Label diagnostic captures by
input window and runtime; a reproducible cold prefix is not evidence for
warm samples, later-layer activations, or cache residency.
If the needed tensor is a graph input already filled by setup, read it in the
callback's pre-execution query and stop there. Verify the exact layout and
absence of producer execution; a captured mask does not bind its logits.
If the predicate needs producer output, synchronize at that producer's
completion callback. If the bytes could be a sibling or a pre-transform
tensor, bind the synchronized tensor to the consumer's exact input pointer,
operator, strides and raw FCSR in its pre-execution query. Exit before the
consumer runs. Verify the post-transform predicate on the captured bytes
with the real parameters; keep inferred eligible work
separate from captured execution counts. Bind the exact embedded bytes and new
guest digest before counting or submitting a resealed AM pair.
A comparison of warm weight bytes screens the comparison loop, not a cache
hit. A refill into preallocated buffers screens the fill loop, not a production
cache miss. Neither can score a call on a trace that did not reach that state.
For owner credit, time the original cache path with its real lookup,
synchronization, allocation/refill, and fallback work as applicable.
Verify executed production dispatch and the exact bare-metal ELF before allocating
a board. For data-dependent changes, state what proves the candidate predicate
on the extracted fixture; matching an input mask or tensor shape alone does not
prove a predicate on post-transform values. Check the emitted hot loop for spills
and redundant work before timing a specialization. On PLDM, verify the changed
branch as well as actual completed work; a generic pack hit shared by A and B is
not proof that B's change ran. Keep branch tracing out of the timing run, and
show that deliberately ineligible controls still take the old path. Match
strides, cache state, conversions, tails, and fallbacks; keep the oracle outside
the timed window. A leaf-only probe cannot score a larger operator scope. If AM
cannot link the production owner, isolate the dependency in a bounded link
probe. Use the existing owner test for that correctness check, leave the
operator unscored, and advance the next ready pair. Adapt only the unavailable
platform service at its existing boundary; do not replace production allocation,
cache lookup, synchronization, or fallback to get an ELF to link. Prove the
adapter separately and keep it identical between arms. Distinguish buffer
identity checks from device registration, and use the AM platform marker
rather than the compiler target triple to identify a no-OS lane. A relocatable
root still retaining cache-lock calls does not prove those calls can run in
AM. Do not boot the full graph to work around a bare-metal link failure.
Include non-AME hotspots; a final-token projection executed during prefill is
not decode. For a large shape, use a smaller outer-row cohort through the same
entrypoint for a quick check. Keep the real inner width, stride and tail, and
verify it selects the same dispatch. Do not extrapolate cohort timing into the
checkpoint ledger. Before allocating a board for the full shape, size its run
cap for both the timed calls and the untimed oracle. Prefer a short self-checking
PLDM pair. If the reference computation dominates the fixture, reuse the
existing oracle to seal expected values for the exact inputs, then compare all
outputs outside the timed window. Check that a bad reference fails in the guest;
a zero host wrapper status alone does not prove success. Rebind the changed
payload, linked path and collector to each other. Once exact shape dispatch,
linked branch and the independent oracle are bound, let the short AM PLDM pair
prove on-target correctness and collect timing in the same submission. Keep
the samples provisional until both arms pass. Use functional simulation only
for a named missing check the short pair cannot supply. To diagnose slow vector
preparation, isolate arithmetic, qualification, packing, and layout movement
with matched work before proposing ISA or RTL changes. Use the isolated result
to choose the next candidate, not to fill a missing timed operator scope. Low
FLOP count or logical byte count alone does not identify the bottleneck.

For a campaign with a cumulative threshold, freeze its non-overlapping hotspot
set, workload weights and baseline per model before screening. Remeasure the
full set, including unchanged scopes, on the exact combined candidate; never
sum isolated wins or use missing rows as zero. For several retained changes
in one operator, time that complete operator against its unchanged common
baseline on the same input and cache strata. An incremental comparison against
an already optimized control is not that measurement. The current prefill campaign
covers Stories15M and Qwen3-0.6B at
`PP256/T1/B256/UB256/N0`; it does not include TG or 1B. A model gets one
matched end-to-end prefill checkpoint for its qualifying combined revision,
only when both the phase-off call-weighted median saving and its observed-spread
guard strictly exceed 30% over its entire frozen hotspot set. Use at least
W1/R3 for hot calls and at
least three separately reset, matched samples per arm for any cold stratum.
Test both unrounded savings: `1 − Σ(w × median(B))/Σ(w × median(A))` and
`1 − Σ(w × max(B))/Σ(w × min(A))`, where `w` counts executed calls in the
shape/state stratum. An isolated result or a mixed set of candidate revisions
cannot enter either total.
Check the projected cycle budget against that same denominator before doing a
merged sweep: even eliminating a set of scopes cannot recover more than their
baseline share. This bound prioritizes the next short pair, not a checkpoint.
Track screening verdicts separately from each model's checkpoint record:
baseline and merged revision, qualified calls out of frozen calls, and both
weighted savings. Until full coverage exists, report the score as unmeasured,
not as a percentage over the subset that ran. Report raw cycles; the hotspot
saving is not an end-to-end speedup. At or below the threshold, keep running
short AM pairs instead of screening changes on the full graph. One passed
checkpoint closes one batch; do not carry its savings into the next batch.
One model crossing the gate does not open the other model's checkpoint or
pause its AM queue. After a checkpoint passes, make the accepted revision
the baseline for that model and restart its batch from zero. Do not move the
other model's baseline or ledger. If the matched prefill fails its work,
path, output, or performance check, keep the old baseline and return to the
smallest affected operator.
Keep the checkpoint's production-path proof tied to the measured build. Bind
each credited optimization to its exact linked symbol, dispatch predicate and
positive hit evidence at the relevant shapes, and identify deliberate fallbacks.
An AM win does not authorize a board run of an integrated binary that still
uses the old branch or moves necessary work outside the window.
Build and stage the next short pair for each model independently. When fresh
capacity covers both Stories15M and Qwen3-0.6B, run their short pairs in parallel:
require two simultaneously reservable, disjoint compatible placements, disjoint
eligible physical cores for lanes sharing a host, and verified independent
same-design runtime state, locks, and per-job release. Two independent
best-fit probes returning the same free domains do not establish parallel fit.
Otherwise run the ready pair that fits without waiting for the other; keep its
two arms placement-matched.
Use any eligible idle placement, not fixed board numbers. A shared lock or
owner-wide release gate serializes board admission, not builds and staging.
If capacity fits but that guard serializes work, verify or scope the existing
runner's admission, stop and release checks to each job; do not bypass them or
create a parallel runner. Verify that stopping and releasing one cannot affect
the other; separate run directories or a dry run alone do not prove this.
Never cancel or displace a foreign job to make a pair fit.
Follow or recover accepted jobs instead of resubmitting. A simulator cap
without the complete guest terminal marker invalidates the pair even if the
runner exits zero. Retry a failed run only after verifying terminal state
and release. If admission stops before allocation, log the limiting gate,
retain the staged payloads and advance the next ready experiment. Reuse the
sealed pair when a release or fresh capacity evidence can reopen that gate;
do not rebuild, restage, or repeat functional simulation for unchanged arms.
See [the measurement protocol](references/measurement-protocol.md#model-hotspots-and-cumulative-checkpoints).

## Run The Optimization Loop

1. Qualify the baseline and freeze the experiment contract: validation evidence,
   revisions, bitstream/config, clock, matrix peak, binary hash, model, stage, shape,
   quantization scheme, environment knobs, warmup, repetitions, and logging settings.
2. Derive static bounds: logical operations, expected bytes, arithmetic intensity,
   edge-tile waste, and the relevant compute/bandwidth roof.
3. Use the qualified timeline's operator breakdown and phase counters to
   choose the next probe. In a model-guided prefill campaign, reuse the
   existing timeline; do not launch an end-to-end run to refresh it while the
   checkpoint gate is closed. Separate prefill from decode and cold
   preparation from steady-state execution.
4. Parse profiles with:

   ```bash
   .agents/skills/xsai-ame-optimization/scripts/analyze-ame-profile.py \
     --peak-ops-per-cycle 1024 log/<uart-log>.log
   ```

   Here 1024 is the known INT8 example, not a universal peak. Use the verified
   precision/config peak (2048 for the audited FP4 example), and check that the
   parser supports the producer's actual record format.

5. Match the earliest abnormal phase to a rule in `diagnosis-rules.md`. Treat later
   idle time or low utilization as a symptom until upstream causes are excluded.
6. Rank candidates by potential absolute benefit, screening cost and risk. State
   which counter must move and a retention threshold covering uncertainty and
   area/power/validation cost; vary one knob at a time. Declare changes in accumulation
   order, precision, quantization or approximation before applying the light gate.
7. After the light gate passes, screen on the surface in `measurement-protocol.md`:
   representative operator sizes on PLDM (AM bare metal when extracting model
   hotspots); reserve the full graph for its acceptance checkpoint. Inspect emitted operations,
   effective latency/throughput, traffic/storage pressure and relevant PPA estimates.
8. Shortlist repeatably beneficial candidates using at least three measurements after
   warmup. Apply the campaign's cumulative gate before full model checks; retain
   applicable numerical, hardware, model-quality and implemented PPA acceptance.
   Changed math is not an undeclared "equivalent" optimization.
9. Recheck performance/PPA against the baseline on the exact final validated
   source/binary/design revision. A correctness or timing fix requires remeasurement
   and any affected validation before acceptance.

## Keep Metric Boundaries Explicit

- Count one integer MAC as two logical operations.
- Compute operator MFU from `logical_ops / total_cycles / peak_ops_per_cycle`.
- Compute macro-path MFU from `logical_ops / ame_tile_call_cycles / peak_ops_per_cycle`.
- Never present macro-path MFU as whole-operator MFU.
- Report phase cycles and percentages together; percentages without absolute cycles
  hide changes in total work.
- Keep FPGA cycle measurements separate from host wall-clock simulator throughput.
- Fewer cycles need not mean lower latency: compare `cycles / design_frequency`;
  distinguish quick-synthesis estimates from implemented PPA and measured energy.
- Keep `test-backend-ops` kernel measurements separate from `llama-bench` end-to-end
  tokens/s. Preliminary results may guide screening; accepted results require the
  corresponding correctness and quality gates.
- A resource-count roof is conditional on shape, arithmetic and instantiated units.
  It is a necessary bound, not a measured gain or a sufficient recipe for 90% MFU.

## Escalate To RTL Deliberately

Enter `XSAI/CUTE/` only when an isolated measurement shows that software is supplying
ready tiles and the remaining deficit is inside `ame_tile_call`, synchronization,
accumulator transfer, load/store, or a documented matrix-core limit.
Preparation-side issue, dependency, VRF or conversion evidence belongs to the RVV
backend instead. Keep a ready-input CUTE baseline independent of the fused graph;
neither track's component result establishes the other track's whole-chain gain.

Before any RTL edit:

1. Add the proposed RTL change, causal evidence, expected counter movement, risks,
   and rollback condition to the experiment document.
2. Notify the user with `happy notify` and identify the exact RTL files or block.
3. Read the relevant local CUTE design documentation.
4. Define the candidate's lightweight gate and bounded instruction/function or PLDM
   performance/PPA screen. After editing, pass the gate before screening without
   changing defaults. Full acceptance includes applicable unit/integration,
   NEMU/difftest, numerical/model, formal, CDC/RDC and implemented PPA checks, followed
   by final same-revision performance/PPA remeasurement.

Do not change an ISA, CSR, ABI, or difftest contract as an incidental optimization.

## Preserve The Evidence

For every experiment, retain:

- hypothesis and causal chain;
- exact build/run commands and environment;
- source and binary/bitstream identities;
- baseline qualification, light-gate result, shortlist decision, remaining full
  acceptance gates and declared error tolerance;
- phase counters, operator MFU, macro-path MFU, and end-to-end throughput;
- PPA evidence/estimate scope, uncertainty and final validated-revision remeasurement;
- separate performance verdict and correctness/quality verdict;
- raw log path.

Update the active experiment record after each completed experiment, including
rejections. Update a shared Yuque record when that publishing workflow is in scope.
Feed confirmed fingerprints and reusable commands back into this skill. Experiment
numbers, successful builds and repeated status checks are not performance results.

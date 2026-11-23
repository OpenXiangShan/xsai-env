# XSAI GGML Q8_0 / MXFP4 AME Optimization Experiment Record

## Scope And Metric Contract

- Objective:
- Software revision/status:
- Execution surface (PLDM / FPGA / small emu probe) and resource availability:
- Compiled design/bitstream/config; DUT clock versus emulator execution rate:
- Matrix tile and peak logical ops/cycle:
- Workload and stage:
- Quantization semantics:
- Warmup/repetitions:
- Correctness thresholds:
- Stage: baseline qualification / lightweight gate / performance-PPA screening /
  shortlisted full acceptance / final remeasurement / accepted:
- What checks the timed workload's outputs, completion and actual completed work:

For a model-to-AM campaign, also record:

- Stable decision/mechanism key, frozen manifest, affected calls, expected
  cycles saved per full prefill, budget ceiling, relative cost and `admit` verdict:
- Existing sealed `launch` recipe and job's JSONL record key; leave derived
  percentages, spread verdicts and checkpoint status to the machine report:
- Production dispatch evidence, exact function/shape/stride/layout/tail,
  existing AM target, linked ELF path, and expected/observed AME/RVV/fallback work:
- Fixture provenance (model or synthetic), timed boundary and omitted work
  (leaf versus full operator), and evidence of matching cache setup, call
  order, distinct keys, and hit/refill:
- Changed-path evidence in the final linked ELF and on the DUT (record local
  functional traces separately), values reaching any data-dependent predicate,
  directed fallback check, and phase-off sample IDs used for timing:
- Per-prefill operator calls versus inner work such as dots, tiles and K32 blocks;
  conversion/packing cadence, body and residual work, actual terminal work and
  probe-only exclusions:
- Why this is the next short pair (attributable cycles per prefill and work
  it could remove), last required guest record, and any repeated control's
  timing purpose rather than an untimed correctness check:
- Frozen batch baseline, non-overlapping operator scopes and per-model call
  weights, separating cold and hot states:
- Reused control image (exact hash, if applicable) and new matched A/B run;
  historical A cycles are not carried into the new pair:
- Matched phase-off raw cycle samples, baseline/combined weighted medians,
  hot/cold setup, weighted saving and spread bound before rounding, strict
  checkpoint decision (or missing strata):
- Per model: screening-only wins, scored rows and total frozen rows; combined
  ELF hit evidence for the retained changes (not the separate B builds):
- Separate phase diagnostics, if any (scope, instrumentation cost and unassigned time):
- Dated capacity snapshot, eligible physical core sets per lane, reservations
  and compatible domain sets; decision to run both, only the pair that fits, or neither;
  each admitted job's exact design, independent runtime/lock, actual placement,
  expected sample IDs and guest/runtime terminals per arm, and per-job release:
- If host admission relies on explicit user approval: original approval date
  and host/design scope; live checks that still had to pass:
- If no board was allocated: dated monitor or terminal admission evidence,
  lock/capacity reason and staged payload hashes; record no cycle samples for
  the admission miss:
- Next ready short pair per model and unresolved scopes; stage independently
  of the other model and the integration decision. For each skipped scope,
  name the missing check and the evidence that would reopen it. Record
  retain/reject/screen-only for the completed pair before advancing:
- Production dependencies not present in AM, smallest existing service seam,
  adapter invariant checked on both arms, named correctness check run on the
  owner surface, and the operator scope still excluded from scoring:
- Integrated checkpoint key (model, frozen baseline, exact combined revision),
  admitted job ID, actual placement, observed production hits and prefill
  cycles; acceptance and rebase decision for this model only:

## Static Feasibility

- Logical M/N/K and hardware tile/padding:
- Useful GEMM operations and precision-specific peak:
- Preparation work, repeated passes and instantiated throughput:
- Serial versus overlap assumptions, batch count and fill/drain:
- Compute/memory bounds and what costs are omitted:
- Target cycle budget; necessary bound versus sufficient/observed result:

## Baseline

- Qualified baseline source/binary/design identities and raw logs:
- Full-validation scope, numerical contract, results and known limitations:
- Reproducibility evidence and controls; baseline qualified for this scope (yes/no):
- If not qualified, baseline-establishment work required before optimization screening:

| Metric | Value | Evidence |
| --- | ---: | --- |
| End-to-end cycles or tokens/s | | |
| AME logical ops | | |
| AME total cycles | | |
| Operator ops/cycle | | |
| Operator MFU | | |
| Macro-path ops/cycle | | |
| Macro-path MFU | | |
| AME fraction of graph | | |

### Phase Breakdown

| Phase | Cycles (M) | Share |
| --- | ---: | ---: |
| prepare_cache | | |
| pack_a | | |
| pack_b | | |
| zero_c | | |
| ame_tile_call | | |
| accumulator_initialization | | |
| scale | | |
| store | | |

## Experiment EXX: Title

- Date:
- Status: planned / running / accepted / rejected / invalid
- Hypothesis:
- Causal chain:
- Declared variable:
- Fixed controls:
- Expected counter movement:
- Correctness risk:
- Numerical changes (order / precision / approximation / none):
- Retention threshold, measurement/estimate uncertainty and area/power/validation cost:
- Exact build command:
- Exact run command:
- Binary SHA-256:
- Raw log:
- Performance-screen verdict and remaining validation:

### Lightweight Correctness Gate

- Applicable compile/elaboration, lint and key assertion results:
- Directed tests of affected data/control paths, tails/reductions and backpressure:
- Basic numerical comparison, tolerance and reference identity:
- Timed-workload output/completion checks and actual operation/tile/output counts:
- Verdict: passed / failed / pending; evidence and applicable exclusions:
- Screening eligibility (yes/no); on failure, diagnostic timings only, no shortlist:

### Performance And PPA Screen

- Representative shapes, bottleneck, warmup/repetitions and raw samples:
- Effective latency/throughput, traffic/bandwidth and workspace/on-chip pressure:
- Quick PPA context: source/design, tool/version, constraints, frequency, library/PVT,
  hierarchy coverage, implementation stage and omitted costs:
- Power/energy measurement or estimate method and activity assumptions, or unavailable:
- Gain versus declared threshold/uncertainty and PPA/validation tradeoffs:
- Shortlist decision: beneficial / no useful gain / inconclusive / ineligible:

### Same-hart async schedule (when measured)

- Stream vs serial: what moved, independent buffers, release ordinal acquired, tail:
- Same work: expected/observed tiles, normally retired arithmetic by PC, output checks:
- Build, waveform and ROI markers for each binary; common clock, ROI cycles, fill/tail:
- Matrix progress cycles, vector input/output cycles and lane-uops, largest matrix gap:
- Input and output separately: `C2`, `C2 / matrix progress`, `C2 / ROI`, `L2`; `C3`, `L3` if scalar events were traced:
- Measured serial overlap and ROI cycle difference for matched work:

### Result

| Metric | Baseline | Candidate | Delta |
| --- | ---: | ---: | ---: |
| Correctness/error | | | |
| Total cycles (M) | | | |
| Operator MFU | | | |
| Macro-path MFU | | | |
| Target phase cycles (M) | | | |
| End-to-end throughput | | | |
| Design frequency and latency (cycles/frequency) | | | |
| Memory traffic and workspace/on-chip storage | | | |
| Area/timing (estimate or implemented) | | | |
| Power/energy (evidence or unavailable) | | | |

Performance conclusion (promising after light-gate pass / no useful gain /
inconclusive / ineligible-diagnostic-only):

Correctness/quality conclusion (pending / light-gate passed, full acceptance pending /
failed / fully passed for declared scope):

Final acceptance (not yet accepted / accepted / rejected):

Follow-up:

### Full Acceptance And Final Remeasurement

- Full functional/integration, edge/exception and numerical/model-quality results:
- Applicable formal verification and relevant CDC/RDC results, or justified exclusions:
- Implemented PPA results with matched constraints/activity and any remaining limits:
- Exact final validated source/binary/design identities and validation logs:
- Correctness/timing/implementation fixes since screening and affected revalidation:
- Remeasured performance/PPA on that exact revision, baseline identities and raw logs:
- Final benefit threshold still met (yes/no); remaining gates and final verdict:

## RTL Change Gate

Complete this section and notify the user before editing RTL.

- Root cause that software cannot remove:
- Counter/trace evidence:
- Proposed block and files:
- Interface or semantic impact:
- Expected counter movement and upper-bound gain:
- Small performance discriminator and maximum screening cost:
- Qualified baseline and lightweight gate:
- Full correctness/difftest, applicable formal and CDC/RDC plan:
- Quick versus implemented PPA checks and final same-revision remeasurement:
- FPGA validation plan:
- Rollback condition:

## Decision Log

| Date | Decision | Evidence |
| --- | --- | --- |

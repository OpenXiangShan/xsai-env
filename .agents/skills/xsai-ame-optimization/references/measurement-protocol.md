# XSAI AME Measurement Protocol

## Freeze The Contract

Record these fields before a run:

| Category | Required fields |
| --- | --- |
| Source | root SHA, `firmware/riscv-rootfs` SHA/status, nested llama.cpp SHA/status |
| Bare-metal extraction | `nexus-am` SHA/status, model function/callsite, matching baseline and fixture hash, effective strides/layout/tails and expected calls per prefill |
| Hardware | PLDM compiled design or FPGA bitstream identity, XSAI config, tile M/N/K, design clock, peak ops/cycle for the actual precision |
| Binary | path, size, SHA-256, compiler flags, build timestamp |
| Workload | program, model, real/fake-like, prefill/decode, M/N/K, batch, prompt/predict lengths |
| Quantization | weight type, activation type, group/channel/K granularity |
| Runtime | every `GGML_AME_*` and `XSAI_AME_*` override, thread count |
| Sampling | warmups, measured repetitions, timeout, logging/progress settings |
| Evidence | raw UART/log path and command line |
| Baseline | exact identities, full-validation scope/results and reproducible measurement evidence |
| Experiment stage | baseline qualification, lightweight gate, performance/PPA screen, shortlisted full acceptance or final remeasurement; remaining gates |

Do not compare runs when the bitstream, clock, workload shape, binary, logging, or
quantization semantics differ unless the difference is the declared variable.

## Qualify The Baseline And Candidate

Optimization screening assumes a fully validated baseline for the declared scope.
Retain its exact source/binary/design identities, validation logs, numerical contract,
known limitations and repeatable performance controls. A successful build, a component
pass or an old result from another revision does not qualify the current baseline.
If the scope lacks such a baseline, establish its correctness first as new-function
or baseline work; do not label it performance-qualified by timing alone.

Before a candidate is eligible for performance/PPA screening, run the applicable
lightweight checks:

- compilation/elaboration and lint for the affected software/RTL;
- key assertions and directed tests of the changed dependency, data or control path;
- basic numerical comparison against the preserved reference under a declared
  contract; approximation needs explicit tolerances, not silent checker relaxation;
- output coverage, completion and actual completed-work accounting for the timed
  workload, including required reductions and tails; test backpressure when affected.

Check the intended backend, shape, operations/tiles and output count as well as the
terminal marker. A fast `done` with less work or missing output is not a valid gain.
Place numerical checking outside the timed region where the canonical harness
   supports it, with identical measurement boundaries for baseline and candidate.

Light-gate failure disqualifies a candidate from the performance shortlist. Timings
may be kept as diagnostic evidence only if their work and limitations are explicit;
they do not establish a beneficial usable candidate. Passing the light gate means
eligible for screening, not full correctness, model quality or release acceptance.
Do not run exhaustive regression/formal/physical implementation for every candidate.

## Choose The Execution Surface

Use the existing benchmark, dispatcher and build entrypoints; extend their shape
controls rather than adding a parallel workload/init/runner.

| Question | Preferred surface |
| --- | --- |
| Model hotspot iteration with a qualified profile | Existing `nexus-am` bare-metal case, short A/B on PLDM |
| Representative operator/fused-graph performance | PLDM, or the requested FPGA platform |
| Instruction or small-function timing | PLDM; small emu probe when PLDM has no free resources |
| Narrow hardware regression | PLDM when available; bounded small emu case otherwise |
| Pure software/packing correctness | Host or qemu-user, subject to ISA support |
| Software integration/custom instructions | NEMU, not a hardware performance substitute |
| Model throughput and quality | Representative real-model run on the target hardware |

Do not send a large GEMM to emu to obtain routine performance numbers. Slow whole-CPU
emulation must not become the serial prerequisite of all performance experiments.
If PLDM is busy, prepare artifacts and use a small discriminating fallback probe;
do not silently replace a representative hardware test with a tiny passing case.

For PLDM, use `pldm-workflow`, check current jobs/free domains and the compiled
design's allocation before submission, and respect the user's allocation policy.
Follow the repository monitor policy for CPU-heavy emulation. Do not restart
transport/services or cancel an existing run merely because the experiment route
changed; those actions require their own scope/ownership check.

### Model Hotspots And Cumulative Checkpoints

1. From a qualified prefill profile, record the actual operator, backend
   function, input/output shape, strides, layout, precision, tail, and call
   counts. Select the existing `nexus-am` target before adding a case; link the
   production kernel/assembly and reuse the reference oracles. Document what
   the extraction omits (for example graph scheduling and Linux), and keep data
   movement and producer/consumer handoffs that belong to the measured operator.
   For an aligned body plus a residual (for example `K=288` as `256+32`), bind
   both work counts and the final tail result to the executed call. An A/B that
   measures only the body is a leaf screen, not that operator.
   Stage only the next runnable shape/state, not an extraction of the whole
   graph. Rank ready candidates by their measured baseline cycles per prefill
   (`calls × cycles/call`), not the largest isolated speedup. Keep the executed
   call and production symbol, omitted work, and A/B payload identities in the
   experiment record. An unavailable enclosing operator leaves a missing row
   in the checkpoint ledger; it does not stop a narrower pair from running.
   A bounded producer capture can seed a short screen. Bind the capture ELF,
   runtime config, executed call, and input/output bytes at the actual
   producer-to-consumer handoff. Matching shapes, a shared object file, or
   graph-level operator logs do not prove native dispatch. Matching simulator
   replay bytes do not prove DUT input equivalence or cache residency. If
   bytes alone are missing, reuse an archived handoff or one bounded, untimed
   production witness; keep timing and cache-state evidence separate. When a
   capture differs from a qualified DUT reference, retain both identities,
   compare the candidate with the original path on the same DUT or a reference
   qualified for that input, and label the pair screening-only until production
   equivalence is proven. Charge the full
   predicate scan inside the timed boundary when it is part of the candidate.
   If the production writer can be linked as a shared, untimed setup, require
   its exact setup marker and byte/state checks before the first timing record
   in both arms. Record whether the source, object, or final linked entry
   matches production. A reconstructed operand plus the real writer still
   does not reproduce intervening graph work or cache state. Keep that pair
   as a short operator screen; do not give it complete-owner ledger credit.
   If changing compute units or reduction order, verify datatype and tile
   support for the exact compiled design, including the residual tile. Use the
   original conversion and fallback paths. Declare the output-error and FCSR
   contract and pass a directed gate before timing; an opcode in a sibling
   kernel or a successful link is not proof of support or equivalence.
   If the whole production owner is not linkable, inspect undefined symbols
   and trace both the archive extraction and the requesting symbol. A duplicate
   allocator or memory primitive can be a downstream symptom of pulling in a
   hosted runtime through logging. Verify imported archive members' relocations
   at the actual AM load address: compiling the fixture with `-mcmodel=medany`
   does not change a prebuilt library's absolute references. A link with
   unresolved symbols can fail before checking the imported relocations;
   fewer undefined symbols do not prove the provider fits. If necessary,
   rebuild just the required upstream objects with the target ABI and no-OS
   configuration. Audit which allocator, lock and growth providers the final
   image calls, then exercise reclaim, allocation failure and recovery before
   attaching the production caller. Reuse the existing AM runtime seam where
   it preserves semantics; do not suppress duplicate
   definitions or substitute no-op locking, a simplified allocator or a
   synthetic cache for timed owner work. If the owner still cannot link,
   reuse its existing test for the named
   correctness check. The AM operator stays unmeasured; proceed with another
   eligible short pair rather than turning an integration run into a link test.
   Keep an owner-closure task separate from the screening queue. Before each
   closure attempt, name the unresolved production dependency and what a
   passing check will unlock. For a link-only check, replay the exact linked
   inputs to fresh outputs and record the symbol/relocation delta; do not
   rerun an unchanged provider's functional suite. A smaller undefined list
   or a linked ELF without a witnessed call is not a runnable owner A/B.
   If undefined inputs abort the link first, audit the selected archive sections
   directly; absence of relocation diagnostics at that point is not evidence
   that the objects fit the AM load address.
   If closure is still blocked, park it at that seam and stage the next real
   call instead of extending the platform work on the screening path.
   Following a positive ready-panel screen, the original producer/pack/layout call is a
   useful next narrow boundary if it can run with the real data and strides.
   Seal the exact panel bytes and tail it emits and compare them with the
   compute input contract. Diagnose with component cycles, but do not add the
   producer and ready-panel timings to simulate the full operator: real
   cache residency, synchronization, and overlapping work can change the total.
   When layouts deliberately differ, compare each logical block's bytes and
   scale at the expected slot for that arm, not at the other arm's physical
   offset. Before enabling the mixed layout at the complete owner, bind the
   same layout to weight fill, cache identity and exact cache-match validation,
   activation pack, and compute indexing. A producer/consumer match in a leaf
   fixture cannot qualify the full dispatch or cache state.
   A scout may link a symbol only because the linker was told to retain it.
   Before admitting that leaf, bind a real call from the AM fixture, verify
   the selected ABI/layout and operand slices, and check real work and output
   at the same boundary on A and B. For a mixed-K prefix/tail split, seal both
   parts' panel offsets, scales and synchronization. Check that the mapping
   covers each packed slot exactly once across all outer panels, including
   padded M/N rows. An index that divides the K32-block count by the K64
   group width can alias a tail with the next outer panel. Check one
   accumulator lifetime, all original rounding points and a reference valid
   for the actual replay inputs, not just bounded directed data.
   A smaller debug fixture cannot stand in for the cost of the real shape.
   Keep setup and the oracle outside the timed window, but do not move a
   conversion, refill or output copy out of it if the production call pays
   that cost. If a short PLDM pair is slow to finish despite small timed
   windows, inspect the linked fixture outside `rdcycle` too. Fixed-size
   bit copies in a per-element oracle can become real klib calls. Optimize
   that fixture identically in both arms without reducing checked outputs,
   changing entry/cache state, or crediting the savings to the operator.
   When an untimed scalar oracle repeats a large operator, generate expected
   values with that same independent oracle for sealed inputs. Bind those
   bytes to both payloads and compare every required output and intermediate
   (e.g. packed RHS) outside the timed calls. Keep the original work, flags and
   canary checks. Corrupt a reference near the end of each checked buffer to
   test the full comparison range; require the guest failure/terminal even if
   the host wrapper returns zero. Recheck the exact linked branches after
   resealing, and include loading, warmup, all calls and this oracle in the
   shape-specific run cap. A truncated run or a small-cohort timing is not
   cap qualification for the full shape.
   For captured operands, prove the producing call has completed before the
   host reads it. Verify the data-dependent predicate after any original
   scale/mask/convert operations; mask bits alone may not determine it. Reuse
   the fixture's setup and independent oracle, byte-check the operands in both
   final payloads, then rebind linked hit evidence and the output digest. One
   diagnostic input window does not establish warm hardware cache state or the
   other occurrences of the shape.
   For a producer-primed consumer pair, keep the producer, buffer alignment,
   pre-producer setup and handoff order fixed across arms. Check the raw FCSR
   at the handoff, call the timed consumer on the producer's output directly,
   and do not scan/copy that output or print a marker between the calls. Check
   the replayed input and both operators' guards after the timing bracket.
   This is a separate cache-state screen until the production reuse and
   intervening work are matched or their effect is independently bounded.
   If a replay disagrees with a simulator-derived byte oracle, retain the
   failure and diagnose the smallest producer. Check whether the linked
   reduction fixes the summation order before requiring cross-runtime bits.
   A host-modeled difference is not a DUT diagnosis or permission to waive
   the check. Bind a target-valid numeric oracle and require matched inputs
   and output signatures before accepting a new timing pair.
   If the candidate removes or changes a library call, inspect
   which implementation each binary resolves (for example AM klib `memcpy`
   versus Linux libc). Compare the route for the actual size and alignment,
   including internal helpers; the same symbol in a static archive from the
   same sysroot does not prove identical code. Keep timing screening-only if
   the difference can change the cost and is not matched or bounded. A model tensor can
   establish bytes and strides, not cache
   residency. Keep the real call order and distinct tensor keys when they
   affect reuse. Match the cache owner, key, reset and hit/refill events to the
   production path before scoring a synthetic or replayed fixture. For each
   independent cold trial, restore the production cache and allocator entry
   state before timing. Repeating a fill into an already allocated destination
   does not constitute a production cache miss.
   For cache replay, bind actual weight names and call order from the executed
   profile. A hit ratio aggregated across shapes or graphs does not assign
   per-call warm state; a logical cache hit also does not prove residency in
   the hardware caches.
   When embedding weights in an AM payload, pin the GGUF loaded by the
   qualified prefill payload. A same-name local GGUF may differ even if its
   tensor shapes and types match. Verify the selected tensor slices against
   the sealed model and both linked payloads byte for byte on the host.
   An alternate-model slice is screening-only; rebind and reseal the pair
   before claiming production data. A guest checksum of the full tensor
   before the first timed call can warm a purported cold case.
   Maintain a ready list per model: executed owner and caller, shape/strides,
   weight and cache state, timing scope, A/B artifacts, changed-branch proof, and
   the intended oracle. Start with the smallest callable production boundary
   that can screen the proposed change. A ready short pair does not wait on the
   full ledger or the other model. After each pair, record retain, reject or
   screen-only, with the next short pair and any missing production boundary.
   On resumption, match staged artifacts to accepted job IDs and terminal
   collector, guest and release receipts. Resume an in-flight handle, close a
   completed binding without resubmitting it, and require a new hypothesis or
   newly matched production state before promoting an old screen. Do not use a
   stale stage marker or a synthetic run to fill an unmeasured ledger row.
   Do not start an integrated prefill to resolve a single row.
   If a complete owner pulls in a platform dependency absent in AM, inspect
   the exact link to find the first indispensable service. For allocator
   backing, preserve the owning allocator and cache: bind a reserved region
   whose identity mapping, alignment, capacity and lifetime are checked;
   exercise allocation, release, membership and the real miss/hit/fallback
   paths before timing. A link success or an always-success stub is not this
   proof. If only the production leaf is callable, screen it without scoring
   the enclosing operator; progress the other model and other ready calls.
   For an isolated bare-metal backing test, prove the region belongs to that
   exact ELF and stays outside its stack and general heap. Use guards and a
   full free-list coalescing check. Check the hosted build with the adapter
   off separately. An arena test or a relocatable link is not a cache-hit
   test and does not qualify a full operator for board admission.
   Use accountable baseline cost (`calls × cycles`) and plausible removable
   work to prioritize extraction across AME, RVV, attention and output
   projection. Compare costs from the same timing surface; label any
   diagnostic ranking separately from the phase-off ledger. If a narrow
   platform/link or input-witness check cannot make that scope runnable, write
   the exact reopen condition and move to the next ready call. Do not turn a
   blocked owner into a hosted-closure project on the iteration path.
   Keep the stage from the executed graph: a final-position
   projection can have `N=1` during prefill. Do not count its inner dot calls
   as additional operator calls. Time conversion and packing at the production
   cadence (once per input, once per panel, etc.), not once per dot unless the
   production operator actually does so.
   For grouped-query attention, match query-to-KV head reuse and the physical
   K/V cache pitch, not just `(M,N,K)` or the visible KV length. When a light
   check needs a simulator, one complete invocation per shape can prove
   work and numerics; bind it to the same linked kernel as the timed build
   and reserve W1/R3 timing for the DUT.
   Keep the extracted kernel's effective code generation aligned with the
   production kernel. In particular, verify that the bare-metal defaults do not
   turn an inlined bit copy into a per-lane `memcpy` call. Check the final ELF
   for the actual hot path and fallback, not just matching source names. A
   producer's batch of eight K32 blocks is not evidence of a supplied-amax fast
   path: verify the metadata input as well as the batch width. Likewise, a shape
   that meets a fast kernel's static constraints does not prove it was called.
   Before booking PLDM, bind the source and ELF to the dispatch evidence from
   the matching prefill profile. On the board, require nonzero expected hits and
   exact work counts; a correctly hashed payload or a completed job alone does
   not prove that it executed the optimized path.
   Record how to distinguish the candidate branch from the baseline path. If
   branch identification needs intrusive counters, verify it in an explicitly
   diagnostic run and bind the phase-off ELF to the same effective kernel and
   entry conditions; compare linked hot-path code and dispatch inputs. Do not
   charge instrumentation to only one timed arm. A simulator PC trace may
   clear a named local admission check; do not report it as a DUT hit.
   Where the exact linked paths have well-separated retirement signatures,
   readings outside both arms' cycle windows can corroborate the DUT path.
   Calibrate with linked-PC evidence, and freeze a tolerance narrow enough
   to reject partial hits and a fallback that stays on the shortened path.
   The count is not direct per-branch instrumentation or a timing metric.
   If a bounded functional trace is needed before board admission, trace the
   final linked call site and the callee containing the changed branch. Check a
   deliberately ineligible input through the real fallback when the change
   has a new guard. If directed cases run first, count the normal hit only
   after entry to the measured operator. A prefix trace can bind a conversion
   buffer and the actual inner width and stride passed to consecutive rows;
   stop once that gate is proven, and do not report full work or a terminal
   from the prefix. Keep trace and fallback-only samples out of the matched
   cycle set unless the fallback is itself a weighted production stratum.
   For a predicate on transformed data, bind the transform and the actual
   values entering the predicate, not just the upstream tensor. For example,
   a causal mask with `-Inf` entries is not itself evidence that an exponent
   reuse branch sees a whole group of `-Inf` logits and a finite row max.
   For causal KQV depth trimming, check the actual post-cast positive-zero
   suffix of every column and admit only arithmetic for which skipped FMAs
   preserve output bits and raw FCSR. A tile's last column determines the
   rounded depth, including tiles crossing a lane-group boundary; keep the
   original depth on unqualified inputs and charge the predicate scan.
   A synthetic fixture with proven branch hits is useful for screening even
   when production values or the fraction of calls taking that branch are unknown.
   If resuming a built pair, first recover the original terminal and compare
   the control to its pinned ELF. Record `linked`, `hit proven`, and `measured`
   separately; a control that is byte-identical can be reused for the same
   fixture, but changing the input or oracle requires sealing both arms again.
   For a guard-dependent fixture, include one admitting input and at least
   one deliberately ineligible input with the same shape. Bind the comparison
   to the original function on the same DUT when possible. Do not time the
   oracle or the rough hit diagnostics, but do time any scan or conversion
   required by the candidate in production.
   Skip an extra simulator pass when existing dispatch and linked-code evidence
   cover admission and the short DUT pair self-checks the remaining outputs,
   work and terminal state. Any extra functional run needs a named gap and
   a stop condition; it is not a routine prerequisite for each timing probe.
   Label synthetic inputs and their entry flags; matching shapes alone do not
   establish the production input distribution. Record fixture provenance and any
   omitted work next to the timed function. For example, a hot weight compare
   without lookup, locking, or miss/refill can screen that leaf but cannot score
   all of weight preparation.
   Real GGUF bytes establish weight provenance, not activation values or cache
   residency. Bind the matching weight's executed tensor name, model digest,
   source offset, row stride and byte digest through the existing importer.
   At the consumer edge capture or replay only the dynamic operand needed for
   that same call. A matched operand pair for one layer does not qualify other
   weight IDs, even with the same shape and stride. An address, byte span, or
   rounded debug dump does not establish the original floating-point bytes.
   If those bytes are unavailable, prove the needed path and state another
   bounded way or keep it as a screen and move to the next short pair. Do not
   launch a full graph to reconstruct the fixture.
   When moving from a dot leaf to its enclosing generic MUL_MAT, use the
   actual linked type-trait entries for conversion and dot dispatch. An
   indirect function table can retain unrelated library code after section
   pruning; trace archive extraction before changing flags or dependencies.
   An AM diagnostic I/O adapter must still emit the error and preserve its
   trap. Do not replace successful-path math, cache policy, or fallback.
   When reusing a diagnostic wrap with AM's relocatable pruning link, apply
   it at both links. Build in a fresh output directory after changing these
   flags; an old pruned object can still extract the host stdio archive and
   bring in a second allocator even if the final link lists the wrap.
   When adding an owner, prune the complete input set together with the same
   roots before extracting runtime archives. Appending a broad object after
   this step can report unrelated scheduler services as missing. If the
   dependencies are unclear, compare the same inputs with just the AM fixture
   root and with the production root added. Check removed sections and live
   relocations; a passing fixture-only link does not exercise the production
   cache lock, cleanup or fallback.
   If a hosted registry still survives pruning, test just its real provider
   as a link-only differential and compare both missing symbols and live
   relocations. Callback tables can retain the whole graph and threadpool
   even when neither executes in the fixture. If one resolved symbol pulls
   in unrelated hosted services, stop widening the link. Screen an existing
   narrower production boundary without replacing the registry or lock in
   the complete-operator test.
   For a whole native AME row in the ledger, bind the existing AM target to the
   production forward owner (or its existing linkable entry), not an AM copy of
   the dispatcher. Match admission, activation preparation, cache hit/refill,
   matrix work and committed output at the declared boundary. Check that the
   original fallback remains reachable; time it separately only if the profile
   gives it a weight. Until this path is measurable, leave the row missing;
   summing isolated activation, weight and ready-input GEMM is not a substitute.
2. Freeze a set of non-overlapping operator scopes and per-model call weights
   before screening. Use one fixed baseline for the batch and compare each
   eligible revision with the same inputs, setup, and cycle boundaries.
   Reconcile the selected calls against the executed profile and record the
   residual outside the selected set. Splitting a scope by shape or cache
   state must preserve its total call count; count the children or their
   parent, not both. Check trace filters before treating a missing field as
   a missed path. Check
   actual instruction/path hits, complete output, fallback behavior and tails
   (for example MXFP4 `K=288` must still process `256+32`). When cache state
   matters, separate cold and hot strata and use their real call weights.
   Use W1/R3 or more for hot strata and reset to the same cold state before
   each of at least three cold samples. Group calls by width only when the
   executed path, strides and work match. Keep bulk and gathered final-row
   calls separate even when they dispatch to the same vector leaf: the same
   inner width can speed up in one stratum and regress in the other.
   An activation preparer that does not
   use output width `M` may group matching calls by `K`; a weight or GEMM path
   whose work depends on `M` must retain its `(M,N,K)` strata.
   For a weight-fill change, bind both logical and padded row counts. Verify
   payload and scales for every active and padded slot; time the partial panel
   at the original boundary. A guard proven on an unpadded shape does not
   establish a hit on a padded shape, and `M` padding is not a `K` tail.
   Keep phase instrumentation in a separate diagnostic arm. Its residual is
   unassigned time, not a measured copy/traffic phase. A layout window can
   include indexing, copies, and fallback; neither its cycles nor logical bytes
   establish a memory stall. Use separate diagnostic windows to choose a candidate,
   then matched phase-off samples over the frozen scope to score it.
   If vector preparation outlasts ready-input AME work, measure both on the
   same shape and matched entry states. Use a residency-only contrast with
   unchanged instructions to test memory sensitivity, or a one-change A/B of
   the linked loop with the same bytes and work to test redundant setup or
   dependencies. Do not treat either contrast as proof of a new instruction
   requirement or of physical AME/RVV overlap.
   Rank runnable owner pairs by forecast whole-prefill savings per cost. Use the
   [machine admission and result commands](../../../../docs/agent-workflow.md#prefill-campaigns)
   before building and to launch the pinned existing recipe. Missing forecasts or
   a blocked or exhausted mechanism cannot launch. A missing capture, link or
   oracle stays in the backlog. A leaf can screen only a qualified prerequisite;
   its gain never enters the merged score.
   Retain each pair's exact callsite, function, changed branch, fixture and
   terminal work counts. For a data-dependent path, record the input witness's
   source, hash, shape/strides, and the exact predicate after the production
   transforms. Bind it to the linked branch without requiring a whole-graph
   replay. A narrow witness proves a hit in that stratum, not coverage of
   other calls or inputs. Record the pair's state (linked, staged, admitted,
   or terminal with verified release). Even a staged pair is not ready to
   submit until the production/linked evidence is in place and the existing
   collector binds both exact payloads, expected optimized and fallback
   counts, and a run cap that covers timed calls and untimed checks.
   A local entry trace is path evidence, not a DUT numeric result.
   Declare the last required guest record before admission. Give only the
   target and necessary performance controls repeated timed samples; use
   untimed directed checks for unchanged siblings when timing them cannot
   change the decision. Neither placement, output/work checks nor per-arm
   release may be shortened to reduce board time.
   Reuse a previous cap only if the work and oracle bounds still hold. For a
   dot-product call, compare K32 work, output rows, activation conversion and
   untimed directed/oracle work separately. Equal K32 counts alone do not
   qualify a different shape; a short outer cohort cannot qualify the full
   shape's cap. Keep timeouts or partial outputs out of the timing ledger.
   If a host reference can
   bind an expected digest more cheaply than an extra simulation, reuse the
   existing oracle with matched arithmetic and first reproduce a known matched
   fixture digest. The host result can qualify the collector, not the board
   cap, actual branch hits, or production activation and cache state. Screen
   the next ready pair without waiting for the other model or a completed
   ledger. While a pair runs, prepare the next eligible call; a shared board
   lock serializes launches, not extraction, building, or staging. Record wins
   as shortlist evidence, not as a cumulative pass; missing scopes still block
   the integrated checkpoint.
   Write a short outcome for each pair: retain, reject, or screening-only.
   Name the next action (another call, owner link, or missing state check).
   Count the full necessary work exactly once, including conversions, packing,
   layout copies and tails. Relocating a cost outside the measured operator is
   not a reduction unless its actual new production cadence is also scored.
   Bind the collector schema to the exact payload and timed boundary. Do not
   accept a leaf record for the enclosing operator. If a staged fixture used
   the wrong model revision, retire those payload identities. Rebind the tensor
   span hashes from the accepted artifact and recheck the linked branches,
   expected work and collector bindings for the new pair before allocation.
   Derive the expected records from the shape/state list and W/R schedule for
   each arm. Reject missing or duplicate samples and replay wrong work and
   identities against the existing collector. Require both the guest completion marker and the
   successful runtime terminal for each arm. A Tcl stop or mock replay alone
   does not prove board completion, a branch hit, or a timing result.
3. Once shortlisted changes are combined, remeasure the whole frozen set with
   the exact combined revision. Confirm actual hits for the retained changes
   in that revision; a hit on an individual B does not rule out a missed
   dispatch or fallback after merging. Use cycles per production call for each
   shape/state stratum. Share a weight only across calls shown to have the
   same relevant dispatch, layout, work and state; shape equality alone is
   not enough. Even a shared input pointer does not prove the later consumer's
   dispatch, entry FCSR, fallback eligibility, or cache state. Record the
   exact callsite and check those properties before combining weights.
   If a timed sample contains a batch of equal calls,
   retain its raw cycle delta and normalize by the verified completed call count
   before weighting; tiles, K32 blocks and oracle repetitions are not calls.
   For each arm, sum `calls * median_cycles` using per-prefill call counts.
   The per-model reduction is `1 - candidate_total / baseline_total`.
   Measure unchanged scopes too;
   do not assume their cost is unchanged in the combined revision. Record the exact
   missing scopes, if any. Missing strata, unequal work or a timed path not
   matched to the frozen profile leave the gate unset, even if a single operator
   improves. Report an unset score as unmeasured, not as zero or as a percentage
   over covered rows. Changes to the same operator may interact: measure them
   together against the checkpoint baseline rather than chaining reductions
   from separate A/Bs. Use the same witnessed input slice and cache stratum
   for that complete-owner pair; a common-baseline synthetic screen and an
   incremental real-input screen cannot be combined to fill the row. Do not
   double-count nested phases or substitute old prefill or emulation numbers.
   For a domain-guard change followed by a quantize/pack change, independently
   time each only to decide whether to retain it. The scan can change the
   cache state and dispatch seen by the packer. Score one phase-off pair
   entering the complete owner before the scan, with both changes enabled in
   B. Preserve the guard's rejection and the real fallback, and check separate
   work counts for the scan, the pack and any tail. If the pair starts before
   the guard but stops after packing, retain it as a joint producer screen;
   do not add its savings to overlapping guard-only or pack-only screens.
   Reuse a sealed arm only if its hash identifies the exact intended binary.
   Give the new pair fresh output prefixes and remeasure both arms under
   matched placement and state. Historical timing, an old passing oracle,
   or an old terminal does not qualify the new pair's samples.
   Freeze the spread rule before timing. For the current W1/R3 campaign use
   `1 - sum(calls * max(candidate)) / sum(calls * min(baseline))` as a second
   gate. It is an observed-spread guard, not a confidence interval. Record the
   raw core-cycle samples and both reductions; do not convert to wall-clock
   latency or throughput when the campaign calls for cycles only.
   At the 30% checkpoint, apply `10 × candidate_total < 7 × baseline_total`
   to each pair of totals before rounding for display. An exact 30% saving
   fails; never pool cycle savings or call counts from different models.
   If an even sample count yields half-cycle medians, double both weighted
   totals for an integer comparison instead of rounding the medians.
   Against a measured baseline, use the baseline share of the eligible,
   non-overlapping scopes as an upper bound on what optimizing only those
   scopes can save. If even that bound is at or below 30% for this campaign,
   prioritize another high-cost scope rather than starting an integration
   sweep. This is a prioritization bound, not a measured score; never infer it
   from an incomplete denominator.
   If a scope is only staged, timing is diagnostic, or its production cache
   state or real hit path is not proven, list it as missing rather than zero.
   Record coverage against the frozen call total and point to the exact missing
   strata. Screen results are a separate list; do not move any cycles from it
   into the checkpoint record until the complete owner is measured on the
   merged revision with all of its production work accounted for.
   A single-operator percentage is useful for ranking, but it cannot unlock the
   checkpoint even if that operator alone exceeds the threshold.
4. Only when the median reduction **and** the spread guard strictly exceed the
   configured threshold, run one matched end-to-end checkpoint for that model
   on the integrated candidate. Key the checkpoint to the model, frozen
   baseline and exact combined revision. Record the admitted job ID against
   that key and reattach to it rather than starting another checkpoint for
   the same bundle. Before board allocation, record for each
   credited change the production callsite, exact ELF and linked branch, its
   admitting shape/stride, the expected hit count, and the expected old-route
   or fallback count where applicable. Confirm actual hits and equal work in
   the run, not only in the AM fixture. For any guard narrowed after screening,
   remeasure both the now-admitted and now-excluded strata; taking the old
   branch alone does not prove its cycles are unchanged. If a control regresses
   with the same leaf instructions and resolved constants, compare the executed
   entry-to-leaf path and code addresses before choosing a new A/B. A bounded
   trace can establish whether extra dispatch work executes; it does not
   establish the hardware cost of that work or of a layout change.
   For the 30% campaign, test
   `10 * candidate_total < 7 * baseline_total` for each weighted total pair
   before display rounding; exactly 30% does not pass. Match the prefill fixture
   and settings; do not add decode. Reuse the matching reference when its
   contract and placement hold; otherwise obtain a matched control. Report
   hotspot cycle savings and actual prefill cycles separately. The 30% gate
   applies to the hotspot ledger, not to the integrated prefill result. Rebase
   the next batch only after work, output, path, terminal and the declared
   prefill performance checks pass. Reset only that model's accumulation to
   zero; the other model retains its baseline, ledger and ready queue. If the
   integration fails or does not confirm a useful saving, keep the baseline
   and diagnose the smallest reproducer. Qualify any revised bundle again with
   short operator measurements before another checkpoint.
5. Run both ready short pairs concurrently when the vendor allocator offers
   disjoint compatible placements, combined host capacity is sufficient, and
   independent exact compile/runtime directories, locks and logs are verified.
   Apply the same constraints to two independently eligible checkpoints;
   one model need not wait for the other to qualify.
   Evaluate the two proposed placements in one fresh capacity decision, after
   accounting for accepted jobs and existing reservations. Two separate
   best-fit answers may name the same idle domains; count that as one placement
   unless the allocator also admits a compatible, non-overlapping second slot.
   Choose from the exact image's compatible idle placements, not from preset
   board numbers. If two lanes do not fit, start the independently eligible
   pair and retain the other staged; do not submit it just to wait for a lock.
   Use per-job terminal and release evidence before allowing overlap. A shared
   runtime lock or an owner-wide stop/release predicate serializes those lanes
   even when both placements fit; do not bypass it to manufacture concurrency.
   After the first pair releases, admit the second independently against the
   current resource state. If a sealed launcher already revalidates host
   capacity, lock, hashes and placement before allocation, prefer that one
   gated submission over an extra remote preflight round trip. For an
   unlisted host, record the original explicit user approval and confirm it
   covers the exact host/design. Do not extend that exception to other hosts,
   a rebuilt design or a wider workload than the approval covers.
   Track the two models independently as `linked`, `staged`, `admitted`, and
   `terminal + release`; an artifact or a dry run cannot advance a later state.
   Keep the durable job ID with the staged A/B identities. If the local log
   follower is interrupted, reattach to that job and verify both arms and
   release there before deciding whether any new submission is needed.
   Bind untimed directed variants separately from timing payloads: seal both
   hashes and require the planned ordered case records, the guest terminal,
   the runtime terminal and each arm's release. Let a nonzero runtime terminal
   stop a wrong-mode run even if its expected guest marker never appears; it
   still fails acceptance. A cancelled job is not evidence of domain release.
   Replay acceptance and missing,
   duplicate and mismatched-record cases before admission. A simulator that
   traps on the linked target instruction and reports zero cases is unsuitable
   for that test even if it prints a generic success trap or exits zero.
   Count distinct online physical cores using a fresh sample of all their online
   SMT siblings. A quiet logical CPU on a busy core does not meet the lane's
   idle-core requirement. On a shared host, allocate disjoint eligible physical
   core sets during the nonblocking admission. For two eight-core lanes, 16
   eligible cores are necessary, not sufficient; the board and isolation gates
   still apply. If admission stops before allocation, record the first failed
   gate, observed capacity versus the requirement, and whether either payload
   reached the DUT. A capacity miss is not an A/B verdict. Keep both sealed
   arms staged and resume on fresh evidence, not by repeating the build or
   functional gate. A prior core list may be stale even when enough cores are
   now idle elsewhere. Match host affinity
   between A and B as well as PLDM placement. If changing the core list, record
   and revalidate the effective affinity in a new receipt rather than editing
   the sealed one.
   Matching top names or a count of idle boards do not prove this. Confirm the
   design identity and that neither job needs the other's mutable runtime files
   or owner-wide exclusivity. Use any compatible idle placement, not a fixed
   pair of boards. Cross-model concurrency does not relax the matching rules
   within each A/B. If only one pair is ready or fits, admit that pair without
   waiting for the other. Recheck just before submission, record the allocator's
   actual placement for each arm, and verify
   release for each job's actual domains and owner identity. If either runner,
   including an already accepted job, requires a global zero-owned check,
   serialize until both can use scoped verification. If resources would fit but
   the owner-wide check is the blocker, limit the change to the existing
   runner's job binding and prove that an unrelated active job cannot satisfy
   or invalidate the first job's stop/terminal/release checks. Never drop those
   checks to enable concurrent execution. Keep the other model's
   next short pair ready for the first compatible release. A second directory
   does not change the first job's release gate. If cloning compiled assets, do not
   share writable inodes or carry live locks or reservation files into the copy.
   A dry run verifies the command path, not live simulator isolation or release.
   Stage either model independently while the other is running. Check the exact
   free, non-reserved domains for both placements rather than the free count;
   stage-only work is not permission to bypass a held owner-wide guard. Keep
   each controlled A/B on a matching placement. If another job changes a shared
   timing resource for just one arm, label the result diagnostic and remeasure
   under matched conditions before scoring it.
   A submitted job waiting on a lock is not a board allocation. Follow or
   recover its original handle to terminal state before retrying. Record the
   last reached gate, eligible versus required physical cores, and whether a
   download or allocation occurred. A CPU gate or lock timeout before
   allocation is an admission miss, not a failed kernel or a timing sample.
   Keep both verified arms staged and advance the next short fixture or link
   check until fresh capacity evidence supports a retry; do not substitute a
   long lock waiter for admitted concurrency.

   Before submission, exercise the exact model/mode preflight without
   allocation. Derive each arm's payload path once, and use it for both the
   hash gate and the generated `+workload` argument. Keep the output prefix
   separate, so a corrective run never overwrites the original receipts.
   A sealed recipe that already passed its exact dry-run contract can repeat
   that check under the same fresh nonblocking admission that starts the pair.
   If the required fresh monitor does not list a compatible host, make no
   workload submission unless the user expressly approved that host/design.
   Apply such an exception only to its stated scope, never to live capacity,
   placement, ownership, or release checks. Otherwise leave the verified
   payloads staged and advance an already identified binding or light gate.
   A prior standalone preflight does not reserve cores or board domains.
   A synthetic UART replay tests the parser, not this path binding.
   Size the simulator cap for all cohorts, repetitions, untimed oracles,
   directed fallbacks, and the terminal marker. A cap expiry with partial
   UART is neither a validated result nor evidence of a kernel hang. If setup,
   warmup or the post-call oracle can dominate the cap, use distinct progress
   markers outside the timed windows to locate the stall without perturbing
   the operation being measured. Verify
   terminal status and actual domain release before a bounded corrective
   run. Keep both payloads, W/R and the checks fixed; justify the cap change
   and give both arms fresh output prefixes. No partial samples earn credit.

   Record the three evidence levels separately: production dispatch on that
   model shape, a linked and exercised AM candidate branch, and matched PLDM
   cycle samples. A bounded functional trace can establish the second, not the
   first or third. If inspection reveals identical hot instructions, stop that
   ablation before allocating a board. For fixed-VL or fixed-depth RVV loops,
   inspect the reduction body for compiler-introduced whole-register spills,
   `vlenb` reads, and repeated vector configuration. For a fixed-VL row
   epilogue, prove the compile-unit minimum VLEN and the guarded row width
   make every fixed chunk valid; keep other cases on the original strip loop.
   Count AVL arithmetic and the dependency on the VL result separately from
   the vector configuration instruction itself, which may remain inside the
   loop. The linked change does not establish a DUT cycle saving.
   If full unrolling defeats the reason for specializing, retain it as a
   static rejection and test a
   narrower variant rather than putting it in the board queue. If the candidate
   only changes one shape, keep the neighboring unchanged shape as a control,
   not another gain.

#### Timed Dependency Fidelity

When a candidate removes or changes a library call, resolve the timed callsite
in both final AM ELFs. The library name and equal output bytes do not show
that the control ran the same code as the production baseline. If the AM
library differs, reuse the frozen production routine or a demonstrated
equivalent. A binary relink must also preserve reachable helpers, constants
and relative references; bind it only at the intended callsite, not as a
global replacement. Keep the fallback and all other work unchanged in both
arms. Verify the control can reach the original routine and the variant
removes it only on the intended route.

Treat differences in linkage (for example, a direct AM call versus a Linux
PLT call), cache residency and entry state as separate evidence gaps. An
exact routine body qualifies that routine for the short A/B; it does not turn
the A/B into a measurement of the Linux dispatch or a different call stratum.
Until these gaps are resolved, retain the result only at the scope it proves.

For an AM owner link, attribute unresolved relocations to the retained
functions before choosing providers. Phase-off timing does not mean profile
initializers or locks disappear from the ELF. Reuse pinned archive members
for self-contained math or container code; verify any remaining dependency
on hosted TLS, heap or I/O. If the AM port changes a platform provider, verify
actual lock, allocation, non-LIFO reclaim and failure behavior before using
it in a measured owner. A relocatable object supplies no timing evidence.

### Representative MXFP4 Shape

The user-selected PLDM screening shape is `M=512, N=2048, K=256`, with PLDM
execution speed described as approximately 1 MHz. Use it for the current fusion
campaign unless the user changes the contract; do not apply it to every model.
Record `M=output channels`, `N=tokens/activation rows`, `K=reduction width`:
`X[N,K]`, `W[M,K]`, `gamma[K]`, mathematical output `Y[N,M]`.

This shape can admit high MFU in an optimistic preparation/compute model below;
it does not prove 90% is achievable on the actual implementation. Keep a smaller
shape for fast diagnostic probes without presenting it as final performance.

### Cycle And Clock Accounting

Measure guest/DUT cycles and the timed region. Separate kernel/graph execution
from boot, download, warmup and host overhead. PLDM execution cycles per host
second, DUT design frequency, and testbench `fclks` are different quantities.
Verify the `fclks` conversion; never assume it equals `rdcycle`.
An approximate 1 MHz emulation rate estimates execution wall time, not the
design's intended clock or an additional factor in cycle-based MFU.
Do not trust a benchmark's assumed-frequency tokens/s without checking its source.

## Shape-Aware Roof And Target Feasibility

State assumptions before quoting an MFU ceiling or a "minimum MNK". Let:

```text
G = 2*M*N*K                useful GEMM operations; one MAC counts as two
P                         actual-precision AME peak operations/cycle
V                         instantiated F32 lane-multiplies/cycle
a                         F32 multiplications per prepared activation
Tg = G/P                  optimistic GEMM cycle floor
Tp = a*N*K/V              optimistic preparation multiplication floor

serial MFU ceiling       = Tg/(Tg+Tp)
perfect-overlap ceiling  = min(1, Tg/Tp) = min(1, 2*M*V/(a*P))
```

These count only selected resources. Reduction, qualification, quantization,
loads/stores, dispatch, synchronization and memory roofs can make the real limit
lower. Count repeated preflight and retry work separately; do not omit it from
measurement or assume that a whole-input preflight can be streamed.

For the audited example `V=8`, `a=3` (F32 square, RMS multiply, gamma multiply),
and FP4 `P=2048`, the overlap ceiling is `min(1,M/384)`. At `M=128`, that
is 33.3%, NOT a universal system/model limit. A 90% steady-state necessary
condition is `M>=345.6`; a full 128-aligned choice is 384. N/K cancel from
this simplified ratio, so it does not specify a unique sufficient minimum MNK.
LMUL groups architectural registers; it does not multiply physical lane throughput.
Reordering addition alone does not change this multiplication-count bound.

For an ideal two-stage pipeline with `Q=N/n` complete token batches, use:

```text
tp = a*n*K/V
tc = 2*M*n*K/P
Tmodel = tp + tc + (Q-1)*max(tp,tc)
model MFU = G/(P*Tmodel)
```

This additionally assumes streamable preparation, independent buffers, no global
barrier or bandwidth contention, ideal compute and no other costs. It is not the
current implementation's guaranteed schedule or an actual performance forecast.
Include fill/drain: at `M=384,n=128`, Q=1 gives 50%, while Q=9 gives 90%.

With `512,2048,256`, `n=128` and the example resources:

```text
G = 536870912 operations
Tg = 262144 cycles
Tp = 196608 cycles
serial multiplication-only ceiling = 57.14%
Q = 16; tp = 12288; tc = 16384
Tmodel = 274432 cycles; model MFU = 95.52%
90% whole-chain budget = Tg/0.90 = 291271.11 cycles
```

This is why the larger shape is a useful screen, not evidence of measured 95.52%.
Increasing M amortizes shared activation preparation; increasing N provides batches
to amortize fill/drain. K affects fixed costs, memory intensity and legal tiles even
though it cancels in the simplified steady-state ratio. Re-derive the roof when
math, precision, resources or the preparation data path changes.

## Standard Runtime Settings

For measured runs:

```text
GGML_AME_PROFILE=1
GGML_AME_LOG=0
GGML_AME_PANEL_LOG=0
GGML_AME_PANEL_PROGRESS_LOG=0
GGML_AME_TILE_PROGRESS_LOG=0
GGML_XSAI_OP_PROGRESS_LOG=0
```

Enable detailed progress logging only for hang localization, never for a performance
number. Keep `GGML_XSAI_OP_PROFILE=1` when graph/operator attribution is required and
record its overhead by one paired control run.

The rootfs workload dispatcher already exposes fixed-shape AME
`test-backend-ops perf` controls such as `XSAI_AME_M`, `XSAI_AME_N`, `XSAI_AME_K`,
and `XSAI_AME_REPEAT`. Read `rootfsimg/xsai-workloads.sh` before inventing a new
entrypoint.

## Repetition And Statistics

- Run one unreported warmup when cache or one-time initialization exists.
- Collect at least three measured repetitions from one immutable binary and bitstream.
- Report each sample plus median; add min/max when variance exceeds 2%.
- Split cold `prepare_cache` from cache-hit execution rather than averaging them.
- Reject timings with timeout, UART loss, skipped work, unintended fallback,
  inconsistent controls or unaccounted progress logging.
- In a declared performance-first screen, retain a numerical failure alongside the
  timing as a failed-light-gate diagnostic only if comparable work completed. It
  cannot enter the performance shortlist or qualify as an accepted speedup. Never
  disable the original checker to manufacture a pass.

## Required Metrics

For an isolated operator, retain:

- logical ops and total cycles;
- ops/cycle and operator MFU;
- `prepare_cache`, `pack_a`, `pack_b`, `zero_c`, `ame_tile_call`,
  `accumulator_initialization`, `scale`, and `store`, in cycles and percent;
- macro-path ops/cycle and MFU;
- tile count, edge-tile count and edge ratio;
- modeled software bytes/cycle if emitted.
- measured memory bytes/cycle and counter boundary when available; logical payload
  bytes, completed-panel counts and host network traffic are not measured DRAM bytes.

For an end-to-end model, additionally retain:

- prompt tokens/s and generation tokens/s separately;
- total benchmark cycles and graph-profile cycles;
- AME fraction of graph cycles;
- model identity, quantization, prompt length, generated length, and any estimated
  layer mode.

Do not use `--estimate-layers 1` as a substitute for a real end-to-end result. If it
is used to project runtime, label the number as an estimate and retain the scaling
assumption.

### Same-hart overlap

For a small probe, reuse `dense-stream` and `dense-serial` in
`nexus-am/tests/ame-async-order`. Keep the hardware build fixed. In the serial
control, move the same RVV or scalar work after the acquire for the final result
store. Choose matrix work that feeds that store; an acquire need not wait for
unrelated computation. Keep tile count, vector operations, inputs, outputs and
checks the same. Use the same start/end events, including fill and tail but
excluding unrelated setup. Resolve marker PCs from each binary's disassembly.
Confirm the serial trace actually separates the units.

For a cycle-resolved trace, use the whole marked interval (ROI), including idle
cycles. At each sample let `P` mean an arithmetic PE stage actually advances,
`V` that at least one relevant vector FU accepts work, and `A` a scalar execution
event. Use one clock and count:

| Quantity | What it measures |
| --- | --- |
| `C2 = count(P && V)` | Distinct matrix/vector overlap cycles; `C2 / count(P)` measures coverage of matrix progress, `C2 / ROI_cycles` the share of the measured interval. |
| `C3 = count(P && V && A)` | Distinct cycles with all three units active. |
| `L2`, `L3` | Longest uninterrupted runs of those conditions, retaining every intervening cycle. |

Repeat the counts for vector **output** handshakes separately. Count simultaneous
lane-uops separately from cycles. Report `count(P)`, matrix and vector duty cycles,
the largest internal matrix gap and any fill/tail; leave a ratio undefined if its
denominator is zero. A measured `L2` cannot exceed the longest PE advance run
in that trace; it does not establish a hardware limit. Use elapsed ROI cycles
for timing; adding concurrent phase times counts cycles twice.

Check the matrix, vector and any scalar results against values that change if work
is omitted. Verify tile counts; on RTL, match normal arithmetic retirements across
commit lanes to the expected work per PC, accounting for unrolling. Compare ROI
cycles for matched work; use a representative workload to establish application
performance. A same-seed replay tests reproducibility of that execution. See
the [worked RTL measurements](../../../../docs/zames-memory-proof.md) §6 and the
[waveform instructions](../../xsai-rtl-debug/SKILL.md#same-hart-ame-overlap).

#### Panel-ready reference for fused activation preparation

Reuse the original two activation slots in the fused `serial` schedule. Pack
identical payloads and scales before each measured window. Start at the first
tile call for the ready panel; end after the last matching store completion and
CPU output scatter. Preserve weight policy, matrix work and output checks. This
envelope includes loads, synchronization, stores and scatter; it is neither PE
busy time nor the time available for vector work on a shared hart.

Keep preflight and first-panel packing separate from steady-state handoffs.
For panel `i`, pair its serial consumer envelope `M_i` with the preparation
time `P_(i+1)` of the next panel. The final consumer has no such pair. The
diagnostic reports all consumer cycles and the handoff subset excluding that
tail. Under an ideal independent-stage model with these fixed service times,
`sum(max(P_(i+1) - M_i, 0))` is residual preparation; subtract it from the
later-panel pack total for the accounting-only hideable ceiling. The estimate
does not prove which cycles are usable, PE/RVV intersection, or graph savings.

Replay the original graph analyzer on a serial-ready diagnostic log:

```bash
.agents/skills/xsai-ame-optimization/scripts/analyze-ame-profile.py \
  --peak-ops-per-cycle 2048 --require-serial-ready log/<uart-log>.log
```

Use the verified peak for the design and precision. Strict mode requires a
valid matching profile window for every observed measured `serial` case, and
at least one per input. Still use the existing collector to validate the
expected sample set, boot/binary identities and terminal status. Do not use
this diagnostic as the callback-placement-only serial control or as final
timing; repeat the timed comparison with the diagnostic off.

## Performance And PPA Screening

Use representative shapes and the measured bottleneck, not peak MAC throughput or
maximum frequency alone. Alongside cycles/MFU, compare effective throughput/latency,
memory traffic and bandwidth demand, workspace/on-chip storage pressure, and relevant
area/timing estimates. If memory supply already limits the graph, a faster array may
leave end-to-end throughput unchanged; extra pipelining can hurt short-task latency.

For a single design-clock domain, compare `latency = cycles / design_frequency`,
not cycles alone. For example, 10% fewer cycles at 20% lower realizable frequency
means `0.90/0.80 = 1.125`, or 12.5% worse latency. Use the relevant timing model for
multi-clock paths; emulator execution rate is never the design frequency.

For fast-synthesis PPA, retain source/design identity, tool/version, constraints,
target frequency, technology/library/PVT, hierarchy coverage and implementation stage.
Label estimates and state which memory macros, interconnect or physical effects
are omitted. Compare like-for-like baselines; unresolved timing or missing context
cannot support an implemented-PPA claim. Record power/energy only when supported by
measurement or a declared activity/workload-based estimate; otherwise say unavailable.
Do not require redundant synthesis when hardware/constraints are unchanged.

Set retention thresholds before screening and make them exceed measurement spread
and relevant estimation uncertainty. Weigh the useful gain against area, power,
storage pressure and validation complexity/cost. Marginal or inconclusive results
need targeted evidence, not automatic promotion to expensive full validation.

## Correctness And Quality Acceptance

Apply these to light-gate-passing, shortlisted performance winners before final
acceptance, not as an exhaustive prerequisite to every exploratory timing probe.
Select full validation by the changed scope, record exclusions and their reasons:

1. Exact shape/filter reaches the AME backend.
2. `test-backend-ops` reports pass against the CPU reference.
3. Record maximum absolute, relative, and normalized error when available.
4. Test aligned and edge shapes.
5. Test zero, sign-extreme, and overflow-stressing inputs for integer changes.
6. For changed quantization granularity, evaluate representative real-model tensors
   and an end-to-end quality measure, not only synthetic random inputs.
7. For async/synchronization changes, exercise buffer reuse, the final tile and
   every exit with pending work. Use difftest for comparable architectural results;
   use a timed RTL trace for physical overlap. Record which checks actually ran.
8. For RMS/quantization changes, distinguish exact bytes/rounding/flags/fallback
   equivalence from a declared approximate contract. Measure RMS factors, normalized
   values, packed-block differences, GEMM output errors and model-level quality.
   Do not silently substitute an old relaxed-tolerance stress test for this contract.
9. For RTL changes, complete affected functional/integration regressions, boundary
   and exception scenarios, applicable formal verification and relevant CDC/RDC
   checks. A light directed pass does not substitute for these.
10. Recheck PPA after implementation with comparable constraints and activity
    assumptions. Track whether frequency, congestion, area or power erased the
    screening benefit; quick synthesis alone is not final implemented PPA.

### Close The Loop On The Validated Revision

After full validation, freeze the final source/binary/design identities and repeat
representative performance and relevant PPA measurements against the qualified
baseline. Retain all samples, raw logs, tool/constraint context and error/quality
results for that exact revision. Check the declared benefit threshold again.

Any subsequent correctness, timing or implementation fix invalidates earlier
performance/PPA claims for the delivered revision until remeasured; rerun affected
validation too. Keep earlier results as historical evidence, not final proof.
If full correctness passes but the final gain disappears, reject the optimization
or reopen it rather than claiming success from the earlier faster revision.

## Single-Variable Experiment Rule

Each experiment must state:

```text
hypothesis
declared variable
fixed controls
predicted counter movement
correctness risk
lightweight gate and declared numerical contract
retention threshold including uncertainty and PPA/validation cost
full acceptance scope and final same-revision remeasurement
```

Build separate binaries or provide immutable runtime knobs for variants. Hash the
binary. A run where multiple optimizations changed together can establish an upper
bound, but cannot prove causality.

## Analysis Command

Summarize every AME profile group in a UART log:

```bash
.agents/skills/xsai-ame-optimization/scripts/analyze-ame-profile.py \
  --peak-ops-per-cycle 1024 \
  --format markdown \
  log/fpga-uart-YYYYMMDD-HHMMSS-PID.log
```

Here 1024 is the known INT8 example. Set the peak for the actual precision/config,
even if only precision changes; the audited FP4 example uses 2048. Verify support
for the producer's record format and do not treat absent parsed samples as success.
Archive the raw log; the summary is derived evidence, not a replacement for it.

The same parser also supports `mxfp4_k32`/`mxfp4_k64` single-line records.
For fusion logs it associates CASE/BEGIN/END by mode, phase and sample, checks
useful work against the shape, and reports `whole_graph_mfu_pct` separately
from operator and macro MFU. Incomplete windows and untimed extra-test aggregates
are not graph samples. Bare MX profiles remain operator-only, never whole-graph
results. `graph_exact=PASS` is one invocation's check, not final acceptance:
verify the full sample set, original workload/host exits, inputs and resource
release independently before accepting an experiment.

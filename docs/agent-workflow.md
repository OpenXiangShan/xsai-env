# Workspace workflow gates

These checks are for long-running performance campaigns in this workspace. Keep planning-with-files as the plan and stop-hook owner, the existing analyzers and collectors as evidence producers, and the existing Make/PLDM entrypoints as runners. The guard is a read-only preflight: `0` means ready for the next applicable check, `1` means blocked or unmeasured, and `2` means invalid input or an unreadable required input. Direct shell/runner calls are not intercepted.

## Keep the active plan small

Run `python3 scripts/agent-workflow-guard.py plan "$PLAN_DIR"` before resuming a campaign and after changing its active plan. Pass the actual plan directory, not the repo root unless that is where the active files live.

| File | Maximum | Keep active |
|---|---:|---|
| `task_plan.md` | 12 KiB, 512 bytes per line | Goal, frozen baseline, current phase, blockers, next three decisions |
| `findings.md` | 64 KiB | Decisions and evidence references that still inform active work |
| `progress.md` | 24 KiB | Current handoff, terminal jobs and pending IDs; no copied UART/tool output |

When over budget, pause at a stable handoff. Preserve a byte-for-byte copy of the old files in approved durable storage with checksums and record its location in the short plan. Check for other writers before replacing active files; leave raw evidence intact. Re-attest changes using the existing planning skill when required. Resume from the active plan and only the evidence relevant to the next decision. Do not re-inject archives or add status-only events to keep an unattended stop gate alive.

## Admit a bounded attempt

Record the decision before launching work, and run `python3 scripts/agent-workflow-guard.py admit request.json`. Required fields: `lane`, `decision_key`, `hypothesis`, `max_minutes` (positive integer), `stop_condition`, and `prior_attempts` (array of `{ "receipt": "…", "outcome": "…" }` with outcomes `pending`, `failed`, `inconclusive` or `passed`). Keep the key stable for the same model, baseline and hypothesis; a renamed flag or rebuilt payload does not reset its budget. Record submitted job IDs and reconcile their terminal state with the canonical runner before retrying. Apply the time limit through that runner; the guard does not start jobs, enforce a timeout or discover concurrent submissions.

- `screen` also needs `baseline_evidence` and `priority_reason`. Rank by measured, non-overlapping baseline cost; if the gain cannot yet be estimated, state what this short experiment will resolve. After two attempts, park or change the mechanism. A pending or passing attempt is a reason to reattach or reuse, not to resubmit.
- `platform` also needs `unlocks_call`, `expected_runnable_artifact`, and `independent_screen`. It gets one bounded attempt. Linking fewer unresolved symbols or passing a provider-only smoke test is not the promised runnable artifact. Park it and continue the independent screen; reopening needs new evidence and an explicit decision, not a new name for the same check.

## Qualify an integrated performance checkpoint

```sh
python3 scripts/agent-workflow-guard.py checkpoint frozen.json owners.jsonl \
  --candidate-sha256 "$CANDIDATE_BUNDLE_SHA256"
```

Freeze one JSON manifest per model/baseline. Set `version: 1`, `model`, `workload`, `design`, `baseline_sha256`, `profile_sha256`, `run_config_sha256` and `threshold_bps` (`3000` means strictly greater than 30%). Set `expected_calls` independently from the executed profile. Each non-overlapping `cases` entry has `id`, `calls`, `state` (`cold`, `warm` or `stateless`), and `binding_sha256` from the immutable callsite/shape/strides/input/expected-work binding. Keep the manifest and its underlying evidence immutable; do not trim missing cases or reduce the threshold to pass. The run-config digest names the required comparable workload/design/timing conditions, excluding the intentionally changed bundle.

Populate `owners.jsonl` from the existing collector and runtime evidence, at most one entry per frozen ID for the exact candidate. Keep discovery screens elsewhere. Each entry has:

- `id`, `state`, `binding_sha256`, `manifest_sha256` (digest of the exact `frozen.json` bytes), `candidate_sha256`.
- `scope: "owner"`, `input: "captured"` or `"production"`, `metric: "dut_cycles"`, and literal `true` for `phase_off`, `work_equal`, `correctness`, `entry_state`, `path_hit`, `terminal` and `released`. Derive those proofs from both arms' evidence, including reset before cold samples, completed work, production dispatch, terminal exits and resource release as applicable.
- `baseline` and `candidate` objects, each with its `bundle_sha256`, `run_config_sha256`, `payload_sha256`, actual `placement`, `warmups`, and formal `cycles` array. The A/B placements and sampling schedules must match; each arm needs at least three formal cycles samples and a warm-up for `warm`. Each arm also supplies `receipt` (absolute path or relative to the ledger directory) and `receipt_sha256` for the immutable collector/runtime evidence.

The guard checks manifest/receipt bindings, hashes the referenced receipt files, and computes call-weighted medians and the max-B/min-A spread from the samples. It does not re-parse UART logs or independently prove the producer's assertions; reuse the existing collector's checks before emitting entries. Missing or excluded strata make the whole model `unmeasured`, with no partial percentage. A hot weight comparison or prepared fill is not a complete owner, even when its timing was on the same board. A valid warm production owner is a different scope and can qualify against its own frozen row.

Only `ready` with both reductions strictly above the frozen threshold admits one matched integrated run. Save its job ID under the model/manifest/candidate key and reattach rather than resubmit. The weighted result is not a measured prefill speedup; that claim requires the matched integrated run itself. See the existing [measurement protocol](../.agents/skills/xsai-ame-optimization/references/measurement-protocol.md#model-hotspots-and-cumulative-checkpoints) for execution and rebase rules.

## Prefill campaigns

Use v2 manifests and a single `experiments/results.jsonl` for attempts, results
and closure decisions. The v1 commands above remain available for older uses.

```sh
guard=scripts/agent-workflow-guard.py
python3 "$guard" admit request.json --manifest "$frozen" --ledger "$ledger"
python3 "$guard" launch request.json --manifest "$frozen" --ledger "$ledger"
python3 "$guard" status "$ledger" "$stories" "$qwen" --output "$PLAN_DIR/STATUS.md"
python3 "$guard" status "$ledger" "$stories" "$qwen" --show-budgets --queue request.json
```

- **Before work:** Use `admit` to check a v2 request: `manifest_sha256`, `lane`
  (`screen`, `platform` or `checkpoint`), `attempt_id`, stable `decision_key`
  and `mechanism`, hypothesis, `stop_condition`, and positive `max_minutes`.
  A screen declares `target_scope: "operator"`, or `"leaf"` with
  `required_prerequisite: true`, `unlocks_call` and `expected_runnable_artifact`.
  A platform request declares those last two fields, `dependency`, and
  `one_validation`. Both carry an `approach` (`local_tuning` or `new_mechanism`),
  `cost` (`build`, `pldm`, `integration_risk` in comparable points), and
  `forecast` rows: frozen `id`, proven affected `calls`, `baseline_cycles` and
  `candidate_cycles` per call, `state_and_applicability`, and pinned `evidence`
  (`path` and `sha256`). Forecasts are not paired measurements. The guard rejects
  missing or overlapping forecasts, below 1% of full prefill, and local tuning
  below the budget wall. Local requests may name their narrower `phase_pool`.
  Only a full frozen score can reduce the planning gap (`starting_candidate_sha256`
  pins that revision). The prerequisite exception budgets the downstream owner,
  not an under-floor leaf by itself.
- **Execution:** `launch` requires a `launcher` and `preflight_evidence` (each a
  path and SHA-256). It reserves the attempt in the ledger **before** running the
  existing pinned shell recipe. The recipe still owns the bounded runtime,
  capacity, placement, release and payload checks; a shell exit alone does not
  reconcile a durable job. Record a terminal receipt, rather than resubmitting.
  `checkpoint` lane instead binds the exact `candidate_sha256` and runs the
  complete two-bound checkpoint gate before launching; once per model/revision.
- **Results:** Existing `analyze-ame-profile.py collect-prefill` can import an
  accepted `MXMODEL_AB` activation/weight leaf using raw log, `--sidecar`,
  `--tag`, the existing `--result-receipt` and optional `--collector-receipt`.
  Pass `--manifest` and `--ledger` to append through `record`. Complete owner
  collectors use `record -` after their own work/dispatch oracle and terminal/release
  checks. V2 adds `version: 2`, `kind: "result"`, `model`, `job_id`, `mechanism`,
  `calls_per_prefill`, `comparison_only`, and matched `cold` `reset_ids` to the
  provenance above; use `scope: "operator"` for the complete owner and `scope:
  "model"` with `id: "prefill"` for the integrated pair. Store sample cycles per
  production call, not inner work counts. Cross-placement, synthetic, fill and
  comparison screens never score. Missing proof stays `unmeasured`. The guard
  derives claim/verdict and rejects `max(B) > min(A)` separately from the model gate.
- **Reporting:** `status` never unions different merged revisions or displays a
  partial percentage. `--show-budgets` shows diagnostic pool ceilings and the
  unscored graph remainder, separate from formal owner sample medians. Count
  every frozen call with its actual state/stride/dispatch binding before enabling
  a checkpoint; missing per-key evidence stays null. Keep reports generated,
  small, and tied to the frozen receipts. Only rebase the accepted model.

#!/usr/bin/env python3
"""Check workspace plans and gate, record and score prefill experiments."""

import argparse
import fcntl
import hashlib
import json
import os
import re
import subprocess
import sys
from fractions import Fraction
from pathlib import Path


PLAN_LIMITS = {"task_plan.md": 12 * 1024, "findings.md": 64 * 1024, "progress.md": 24 * 1024}
PLAN_LINE_LIMIT = 512
STATES = ("cold", "warm", "stateless")
PROOFS = ("work_equal", "correctness", "entry_state", "path_hit", "terminal", "released")
PREFILL_FLOOR_BPS = 100
PREFILL_CHECKPOINT_BPS = 3000


def require(condition, message):
    if not condition:
        raise ValueError(message)


def fields(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, f"duplicate JSON key: {key}")
        result[key] = value
    return result


def invalid_constant(value):
    raise ValueError(f"invalid JSON constant: {value}")


def decode(raw):
    value = json.loads(raw, object_pairs_hook=fields, parse_constant=invalid_constant)
    require(isinstance(value, dict), "expected a JSON object")
    return value


def text(value):
    return isinstance(value, str) and bool(value.strip())


def sha256(value):
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def positive_int(value):
    return type(value) is int and value > 0


def plan(directory):
    sizes = {}
    issues = []
    for name, limit in PLAN_LIMITS.items():
        path = directory / name
        if not path.is_file():
            issues.append(f"{name}: missing regular file")
            continue
        with path.open("rb") as stream:
            size = stream.seek(0, 2)
            sizes[name] = size
            if size > limit:
                issues.append(f"{name}: {size} > {limit} bytes; archive history offline")
            elif name == "task_plan.md":
                stream.seek(0)
                for line, content in enumerate(stream.read(limit + 1).splitlines(), 1):
                    if len(content) > PLAN_LINE_LIMIT:
                        issues.append(f"{name}:{line}: exceeds {PLAN_LINE_LIMIT} bytes")
    return {"status": "blocked" if issues else "ready", "bytes": sizes, "issues": issues}


def admit(path):
    request = decode(path.read_bytes())
    lane = request.get("lane")
    require(lane in ("screen", "platform"), "lane must be screen or platform")
    for key in ("decision_key", "hypothesis", "stop_condition"):
        require(text(request.get(key)), f"missing {key}")
    require(positive_int(request.get("max_minutes")), "max_minutes must be a positive integer")
    prior = request.get("prior_attempts")
    require(isinstance(prior, list), "prior_attempts must be an array (empty for a new decision)")
    seen = set()
    for attempt in prior:
        require(isinstance(attempt, dict) and text(attempt.get("receipt")), "attempt needs a receipt")
        require(attempt["receipt"] not in seen, "duplicate attempt receipt")
        seen.add(attempt["receipt"])
        require(attempt.get("outcome") in ("pending", "failed", "inconclusive", "passed"),
                "invalid attempt outcome")
    issues = []
    if any(attempt["outcome"] in ("pending", "passed") for attempt in prior):
        issues.append("reuse or reconcile the existing attempt; do not resubmit")
    if lane == "screen":
        for key in ("baseline_evidence", "priority_reason"):
            require(text(request.get(key)), f"screen needs {key}")
        if len(prior) >= 2:
            issues.append("screen budget exhausted for this hypothesis; change the mechanism or park")
    else:
        for key in ("unlocks_call", "expected_runnable_artifact", "independent_screen"):
            require(text(request.get(key)), f"platform attempt needs {key}")
        if prior:
            issues.append("platform budget exhausted; park and continue the independent screen")
    return {"status": "blocked" if issues else "ready", "lane": lane,
            "decision_key": request["decision_key"], "issues": issues}


def load_manifest(path):
    raw = path.read_bytes()
    data = decode(raw)
    require(type(data.get("version")) is int and data["version"] in (1, 2), "unsupported manifest version")
    for key in ("model", "workload", "design"):
        require(text(data.get(key)), f"manifest needs {key}")
    for key in ("baseline_sha256", "profile_sha256", "run_config_sha256"):
        require(sha256(data.get(key)), f"manifest needs {key}")
    threshold = data.get("threshold_bps")
    require(type(threshold) is int and 0 < threshold < 10_000, "invalid threshold_bps")
    require(positive_int(data.get("expected_calls")), "invalid expected_calls")
    entries = data.get("cases")
    require(isinstance(entries, list) and entries, "manifest needs nonempty cases")
    cases = {}
    for case in entries:
        require(isinstance(case, dict) and text(case.get("id")), "case needs an id")
        case_id = case["id"]
        require(case_id not in cases, f"duplicate case: {case_id}")
        require(positive_int(case.get("calls")), f"{case_id}: invalid calls")
        if data["version"] == 1 or case.get("state") is not None:
            require(case.get("state") in STATES, f"{case_id}: invalid production state")
        if data["version"] == 1 or case.get("binding_sha256") is not None:
            require(sha256(case.get("binding_sha256")), f"{case_id}: invalid binding digest")
        cases[case_id] = case
    require(sum(case["calls"] for case in cases.values()) == data["expected_calls"],
            "frozen call count does not match case weights")
    if data["version"] == 2:
        validate_budget(data, cases, path.parent)
    return data, cases, hashlib.sha256(raw).hexdigest()


def receipt_hash(path, hashes):
    if path not in hashes:
        require(path.is_file(), f"missing receipt file: {path}")
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(65536), b""):
                digest.update(chunk)
        hashes[path] = digest.hexdigest()
    return hashes[path]


def checked_receipt(receipt, directory, hashes):
    require(isinstance(receipt, dict) and text(receipt.get("path")) and sha256(receipt.get("sha256")),
            "missing path or digest for evidence")
    require(receipt_hash(directory / receipt["path"], hashes) == receipt["sha256"],
            f"evidence digest mismatch: {receipt['path']}")


def validate_budget(data, cases, directory):
    require(data["threshold_bps"] == PREFILL_CHECKPOINT_BPS, "prefill requires the frozen strict 30% threshold")
    cycles = data.get("whole_prefill_samples")
    require(isinstance(cycles, list) and len(cycles) >= 3 and all(map(positive_int, cycles)),
            "missing formal whole-prefill samples")
    hashes = {}
    checked_receipt(data.get("baseline_receipt"), directory, hashes)
    checked_receipt(data.get("profile_receipt"), directory, hashes)
    baseline = data["baseline_receipt"]
    source = directory / baseline["path"]
    if "line" in baseline:
        lines = source.read_bytes().splitlines()
        line = baseline["line"]
        require(positive_int(line) and line <= len(lines), "invalid baseline sample line")
        require(decode(lines[line - 1]).get("samples_cycles") == cycles, "whole-prefill samples differ from receipt")
    if "json_key" in baseline:
        arm = decode(source.read_bytes()).get(baseline["json_key"])
        require(isinstance(arm, dict) and arm.get("samples_cycles") == cycles,
                "whole-prefill samples differ from receipt")
        require(arm.get("elf_sha256") == data["baseline_sha256"], "whole-prefill receipt uses another ELF")
    if "run_config" in data:
        raw = json.dumps(data["run_config"], sort_keys=True, separators=(",", ":")).encode()
        require(hashlib.sha256(raw).hexdigest() == data["run_config_sha256"], "run config digest mismatch")
    require(data["profile_receipt"]["sha256"] == data["profile_sha256"], "wrong profile evidence")
    require(positive_int(data.get("profile_graphs")) and positive_int(data.get("profile_total_cycles")),
            "missing diagnostic graph normalization")
    total_calls = data.get("profile_total_calls")
    require(total_calls is None or (positive_int(total_calls) and total_calls >= data["expected_calls"]),
            "invalid full-graph call count")
    buckets = data.get("budget_buckets")
    require(isinstance(buckets, list) and buckets, "missing disjoint diagnostic budget buckets")
    covered = set()
    names = set()
    for bucket in buckets:
        require(isinstance(bucket, dict) and text(bucket.get("id")) and positive_int(bucket.get("cycles")),
                "invalid budget bucket")
        require(bucket["id"] not in names, "duplicate budget bucket")
        names.add(bucket["id"])
        members = bucket.get("case_ids")
        require(isinstance(members, list) and members, "empty budget bucket")
        for case_id in members:
            require(text(case_id) and case_id in cases and case_id not in covered, "unknown or overlapping budget case")
            covered.add(case_id)
    require(covered == cases.keys(), "diagnostic buckets do not cover frozen calls")
    require(sum(bucket["cycles"] for bucket in buckets) <= data["profile_total_cycles"],
            "diagnostic buckets exceed their full graph")
    pools = data.get("phase_pools")
    require(isinstance(pools, dict) and all(text(key) and positive_int(value) for key, value in pools.items()),
            "invalid warmup-inclusive phase pools")


def ledger_rows(stream):
    for line_number, line in enumerate(stream, 1):
        if line.strip():
            try:
                yield decode(line)
            except ValueError as error:
                raise ValueError(f"{stream.name}:{line_number}: {error}") from error


def read_ledger(path):
    with path.open(encoding="utf-8") as stream:
        fcntl.flock(stream, fcntl.LOCK_SH)
        return list(ledger_rows(stream))


def model_records(records, data, manifest_sha):
    return [row for row in records if row.get("model") == data["model"]
            and row.get("manifest_sha256") == manifest_sha]


def classify_result(record, cases, data, manifest_sha, directory, hashes):
    result = {**record, "claim_class": "unmeasured", "ledger_credit": False,
              "performance_verdict": "unmeasured", "placement_match": None,
              "baseline_median": None, "candidate_median": None}
    try:
        require(record.get("version") == 2 and record.get("kind") == "result", "expected a v2 collector result")
        require(record.get("model") == data["model"] and record.get("manifest_sha256") == manifest_sha,
                "wrong model or frozen manifest")
        require(text(record.get("job_id")) and text(record.get("mechanism")), "missing job or mechanism")
        scope = record.get("scope")
        require(scope in ("leaf", "operator", "model"), "missing timed scope")
        case_id = record.get("id")
        require(text(case_id) and (case_id == "prefill" if scope == "model" else case_id in cases),
                "missing frozen call id")
        input_state, cache_state = record.get("input"), record.get("state")
        require(input_state in ("synthetic", "captured", "production"), "missing input provenance")
        require(cache_state in (*STATES, "preallocated"), "missing cache state")
        require(isinstance(record.get("comparison_only"), bool), "missing timing boundary declaration")
        require(record.get("metric") == "dut_cycles" and record.get("phase_off") is True,
                "missing raw phase-off DUT cycles")
        require(all(record.get(key) is True for key in ("work_equal", "correctness", "terminal", "released")),
                "missing equal-work, correctness, terminal or release proof")
        require(all(isinstance(record.get(key), bool) for key in ("entry_state", "path_hit")),
                "missing entry-state or dispatch declaration")
        measured_calls = record.get("calls_per_prefill")
        require(positive_int(measured_calls) and measured_calls <= (1 if scope == "model" else cases[case_id]["calls"]),
                "missing or oversized call coverage")
        arms = []
        for key in ("baseline", "candidate"):
            arm = record.get(key)
            require(isinstance(arm, dict) and text(arm.get("placement")), f"{key}: missing actual placement")
            require(sha256(arm.get("payload_sha256")), f"{key}: missing payload identity")
            checked_receipt({"path": arm.get("receipt"), "sha256": arm.get("receipt_sha256")}, directory, hashes)
            cycles, warmups = arm.get("cycles"), arm.get("warmups")
            require(isinstance(cycles, list) and len(cycles) >= 3 and all(map(positive_int, cycles)),
                    f"{key}: need at least three formal samples")
            require(type(warmups) is int and warmups >= (0 if cache_state == "cold" else 1),
                    f"{key}: invalid warmup count")
            if cache_state == "cold":
                resets = arm.get("reset_ids")
                require(isinstance(resets, list) and len(resets) == len(cycles) and all(map(text, resets))
                        and len(set(resets)) == len(resets), f"{key}: need an independent reset per cold sample")
            arms.append(arm)
        baseline, candidate = arms
        require(len(baseline["cycles"]) == len(candidate["cycles"]) and baseline["warmups"] == candidate["warmups"],
                "unequal sample schedule")
        if cache_state == "cold":
            require(not set(baseline["reset_ids"]).intersection(candidate["reset_ids"]), "cold reset reused across arms")
        matched = baseline["placement"] == candidate["placement"]
        baseline_median, candidate_median = (Fraction(twice_median(arm["cycles"]), 2) for arm in arms)
        separated = max(candidate["cycles"]) <= min(baseline["cycles"])
        claim = ("diagnostic" if not matched else "synthetic-screen" if input_state == "synthetic"
                 else "fill-screen" if cache_state == "preallocated" else "comparison-screen" if record["comparison_only"]
                 else "screen_only" if scope == "leaf" else "integrated-model" if scope == "model" else "owner")
        verdict = ("diagnostic" if not matched else "REJECT" if not separated else
                   "retained" if candidate_median < baseline_median else "unchanged")
        result.update(claim_class=claim, placement_match=matched, performance_verdict=verdict,
                      baseline_median=json_number(baseline_median), candidate_median=json_number(candidate_median))
        if claim in ("owner", "integrated-model"):
            case = cases[case_id] if claim == "owner" else {
                "state": cache_state, "binding_sha256": data["run_config_sha256"], "calls": 0}
            require(sha256(case.get("binding_sha256")) and cache_state == case["state"],
                    "frozen production state or binding is unmeasured")
            if claim == "owner":
                require(measured_calls == case["calls"], "only complete frozen call weights qualify")
            revision = record.get("candidate_sha256")
            require(sha256(revision) and revision != data["baseline_sha256"], "missing distinct merged revision")
            checked_samples({**record, "scope": "owner"}, case, data, manifest_sha, revision, directory, hashes)
            result["ledger_credit"] = separated and claim == "owner"
            if not separated:
                result["reason"] = "candidate max exceeds baseline min"
    except (OSError, ValueError) as error:
        result.update(claim_class="unmeasured", ledger_credit=False, performance_verdict="unmeasured", reason=str(error))
    return result


def checked_samples(record, case, data, manifest_sha, candidate_sha, ledger_dir, hashes):
    require(record.get("manifest_sha256") == manifest_sha, "wrong frozen manifest")
    require(record.get("candidate_sha256") == candidate_sha, "wrong merged candidate")
    require(record.get("binding_sha256") == case["binding_sha256"], "wrong call/input/work binding")
    require(record.get("scope") == "owner", "only complete production owners qualify")
    require(record.get("input") in ("captured", "production"), "synthetic or unspecified input")
    require(record.get("state") == case["state"], "wrong production state")
    require(record.get("metric") == "dut_cycles", "require raw DUT cycles, not t/s or host time")
    require(record.get("phase_off") is True, "require phase-off timing")
    require(all(record.get(key) is True for key in PROOFS), "required execution proofs missing")
    arms = []
    for key, bundle_sha in (("baseline", data["baseline_sha256"]), ("candidate", candidate_sha)):
        arm = record.get(key)
        require(isinstance(arm, dict), f"missing {key} arm")
        require(arm.get("bundle_sha256") == bundle_sha, f"{key}: wrong bundle")
        require(arm.get("run_config_sha256") == data["run_config_sha256"], f"{key}: wrong run config")
        require(sha256(arm.get("payload_sha256")) and sha256(arm.get("receipt_sha256"))
                and text(arm.get("receipt")), f"{key}: missing provenance")
        require(receipt_hash(ledger_dir / arm["receipt"], hashes) == arm["receipt_sha256"],
                f"{key}: receipt digest mismatch")
        require(text(arm.get("placement")), f"{key}: missing actual placement")
        samples = arm.get("cycles")
        require(isinstance(samples, list) and len(samples) >= 3 and all(map(positive_int, samples)),
                f"{key}: need at least three positive formal samples")
        warmups = arm.get("warmups")
        require(type(warmups) is int and warmups >= (1 if case["state"] == "warm" else 0),
                f"{key}: invalid warmup count")
        arms.append(arm)
    baseline, candidate = arms
    require(baseline["placement"] == candidate["placement"], "cross-placement comparison")
    require(baseline["warmups"] == candidate["warmups"] and len(baseline["cycles"]) == len(candidate["cycles"]),
            "unequal sample schedule")
    return baseline["cycles"], candidate["cycles"]


def twice_median(samples):
    ordered = sorted(samples)
    middle = len(ordered) // 2
    return ordered[(len(ordered) - 1) // 2] + ordered[middle]


def json_number(value):
    return value.numerator if value.denominator == 1 else float(value)


def checkpoint(manifest_path, ledger_path, candidate_sha, records=None):
    data, cases, manifest_sha = load_manifest(manifest_path)
    require(sha256(candidate_sha) and candidate_sha != data["baseline_sha256"],
            "need an exact merged candidate hash distinct from the baseline")
    rows = {}
    excluded = {}
    seen = set()
    hashes = {}
    if records is None:
        records = read_ledger(ledger_path)
    if data["version"] == 2:
        for record in model_records(records, data, manifest_sha):
            if record.get("kind") != "result" or record.get("scope") != "operator" or record.get("candidate_sha256") != candidate_sha:
                continue
            case_id = record.get("id")
            if not text(case_id) or case_id not in cases:
                continue
            if case_id in seen:
                rows.pop(case_id, None)
                excluded[case_id] = "overlapping or duplicate owner results"
                continue
            normalized = classify_result(record, cases, data, manifest_sha, ledger_path.parent, hashes)
            if not normalized["ledger_credit"]:
                excluded[case_id] = normalized.get("reason", normalized["claim_class"])
                continue
            seen.add(case_id)
            excluded.pop(case_id, None)
            rows[case_id] = tuple(record[arm]["cycles"] for arm in ("baseline", "candidate"))
    else:
        for record in records:
            case_id = record.get("id")
            require(isinstance(case_id, str) and case_id in cases, "unknown frozen case id")
            require(case_id not in seen, f"duplicate receipt for {case_id}")
            seen.add(case_id)
            try:
                rows[case_id] = checked_samples(record, cases[case_id], data, manifest_sha, candidate_sha,
                                                ledger_path.parent, hashes)
            except (OSError, ValueError) as error:
                excluded[case_id] = str(error)

    missing = sorted(cases.keys() - rows.keys())
    summary = {"status": "unmeasured", "model": data["model"], "manifest_sha256": manifest_sha,
               "candidate_sha256": candidate_sha, "covered_calls": sum(cases[key]["calls"] for key in rows),
               "expected_calls": data["expected_calls"], "missing": missing, "excluded": excluded}
    if missing:
        return summary

    median_a = median_b = spread_a = spread_b = 0
    for case_id, (baseline, candidate) in rows.items():
        calls = cases[case_id]["calls"]
        median_a += calls * twice_median(baseline)
        median_b += calls * twice_median(candidate)
        spread_a += calls * min(baseline)
        spread_b += calls * max(candidate)

    def score(baseline, candidate):
        saved = baseline - candidate
        return {"saving_pct": round(100 * (saved / baseline), 4),
                "clears_threshold": 10_000 * saved > data["threshold_bps"] * baseline}

    median = score(median_a, median_b)
    spread = score(spread_a, spread_b)
    return {**summary, "status": "ready" if median["clears_threshold"] and spread["clears_threshold"]
            else "below_threshold", "threshold_bps": data["threshold_bps"],
            "median": {**median, "baseline_twice_cycles": median_a, "candidate_twice_cycles": median_b},
            "spread": {**spread, "baseline_cycles": spread_a, "candidate_cycles": spread_b}}


def campaign_admit(request, manifest_path, ledger, records):
    data, cases, digest = load_manifest(manifest_path)
    require(data["version"] == 2 and request.get("version") == 2, "prefill launch requires a v2 budget and request")
    require(request.get("manifest_sha256") == digest, "request does not target the frozen manifest")
    for key in ("attempt_id", "decision_key", "mechanism", "hypothesis", "stop_condition"):
        require(text(request.get(key)), f"missing {key}")
    require(positive_int(request.get("max_minutes")), "missing bounded max_minutes")
    lane = request.get("lane")
    require(lane in ("screen", "platform", "checkpoint"), "unknown prefill lane")
    own = model_records(records, data, digest)
    result = {"status": "blocked", "model": data["model"], "lane": lane, "decision_key": request["decision_key"],
              "mechanism": request["mechanism"], "issues": []}
    if any(row.get("kind") == "attempt" and row.get("attempt_id") == request["attempt_id"] for row in records):
        result["issues"].append("attempt id already used; reconcile, do not resubmit")
    for row in records:
        if (row.get("kind") == "decision" and row.get("model") == data["model"]
                and row.get("mechanism") == request["mechanism"]):
            if row.get("state") in ("closed", "parked"):
                checked_receipt(row.get("evidence"), ledger.parent, {})
                result["issues"].append(f"{row['state']}: {row['reason']}")
    if result["issues"]:
        return result

    if lane == "checkpoint":
        merged = request.get("candidate_sha256")
        if any(row.get("kind") == "attempt" and row.get("lane") == "checkpoint"
               and row.get("candidate_sha256") == merged for row in own):
            result["issues"].append("one integrated launch per model and merged candidate")
        score = checkpoint(manifest_path, ledger, merged, records)
        if score["status"] != "ready":
            result["issues"].append(f"integrated checkpoint is {score['status']}")
        result["checkpoint"] = score
    else:
        attempts = {row.get("attempt_id") for row in own if row.get("kind") == "attempt"
                    and row.get("mechanism") == request["mechanism"] and row.get("lane") == lane}
        terminals = {}
        for row in own:
            attempt_id = row.get("attempt_id")
            if row.get("kind") in ("result", "terminal") and "outcome" in row and attempt_id in attempts:
                terminals.setdefault(attempt_id, set()).add(row["outcome"])
        if (attempts - terminals.keys()) or any("passed" in outcomes for outcomes in terminals.values()):
            result["issues"].append("pending or passing attempt; reconcile or reuse before submitting")
        if sum(bool(outcomes & {"failed", "inconclusive"}) for outcomes in terminals.values()) >= 2:
            result["issues"].append("two failures on this mechanism: switch mechanism or park")

        if lane == "platform":
            for key in ("dependency", "unlocks_call", "expected_runnable_artifact", "one_validation"):
                require(text(request.get(key)), f"platform needs {key}")
        else:
            scope = request.get("target_scope")
            require(scope in ("leaf", "operator"), "screen needs leaf or complete operator target scope")
            if scope == "leaf":
                require(request.get("required_prerequisite") is True and text(request.get("unlocks_call"))
                        and text(request.get("expected_runnable_artifact")),
                        "leaf must unlock a qualifying downstream owner; forecast that owner, not the leaf")

        predictions = request.get("forecast")
        require(isinstance(predictions, list) and predictions, "no attributable forecast for whole prefill")
        divisor = twice_median(data["whole_prefill_samples"])
        savings = 0
        covered = set()
        hashes = {}
        for prediction in predictions:
            require(isinstance(prediction, dict), "invalid forecast row")
            case = prediction.get("id")
            require(text(case) and case in cases and case not in covered, "unknown or overlapping forecast row")
            count = prediction.get("calls")
            require(positive_int(count) and count <= cases[case]["calls"], "forecast exceeds frozen call weight")
            require(text(prediction.get("state_and_applicability")), "forecast needs state and applicability evidence")
            for key in ("baseline_cycles", "candidate_cycles"):
                require(positive_int(prediction.get(key)), f"forecast needs positive {key} per affected call")
            checked_receipt(prediction.get("evidence"), ledger.parent, hashes)
            savings += count * (prediction["baseline_cycles"] - prediction["candidate_cycles"])
            covered.add(case)

        buckets = [bucket for bucket in data["budget_buckets"] if covered.intersection(bucket["case_ids"])]
        ceiling = Fraction(sum(bucket["cycles"] for bucket in buckets), data["profile_graphs"])
        if savings > ceiling:
            result["issues"].append("forecast exceeds the entire affected diagnostic budget")
        approach = request.get("approach")
        require(approach in ("local_tuning", "new_mechanism"), "classify change as local_tuning or new_mechanism")
        if approach == "local_tuning":
            gap_bps = Fraction(PREFILL_CHECKPOINT_BPS)
            if "starting_candidate_sha256" in request:
                prior_score = checkpoint(manifest_path, ledger, request["starting_candidate_sha256"], records)
                require(prior_score["status"] != "unmeasured", "partial merged results cannot shrink the budget gap")
                median_score = prior_score["median"]
                spread_score = prior_score["spread"]
                accepted = 10_000 * (1 - max(
                    Fraction(median_score["candidate_twice_cycles"], median_score["baseline_twice_cycles"]),
                    Fraction(spread_score["candidate_cycles"], spread_score["baseline_cycles"])))
                gap_bps = max(0, gap_bps - accepted)
            diagnostic_bps = Fraction(sum(bucket["cycles"] for bucket in buckets) * 10_000, data["profile_total_cycles"])
            if "phase_pool" in request:
                phase = request["phase_pool"]
                require(text(phase) and phase in data["phase_pools"], "unknown phase budget pool")
                diagnostic_bps = min(diagnostic_bps,
                                     Fraction(data["phase_pools"][phase] * 10_000, sum(data["whole_prefill_samples"])))
            result.update(budget_wall_ceiling_pct=float(diagnostic_bps / 100), remaining_gap_pct=float(gap_bps / 100))
            if diagnostic_bps <= gap_bps and request.get("target_scope") != "leaf":
                result["issues"].append("budget wall: even removing the local pool cannot clear the batch target; change mechanism")
        if savings * 20_000 < PREFILL_FLOOR_BPS * divisor:
            result["issues"].append("forecast is below 1% of the complete prefill baseline")
        costs = request.get("cost")
        require(isinstance(costs, dict) and all(positive_int(costs.get(key)) for key in
                ("build", "pldm", "integration_risk")), "missing build, PLDM or integration-risk cost")
        gain = Fraction(savings * 200, divisor)
        result.update(expected_saved_cycles=savings, whole_prefill_baseline_cycles=json_number(Fraction(divisor, 2)),
                      expected_gain_pct=float(gain), priority=float(gain / sum(costs[key] for key in
                      ("build", "pldm", "integration_risk"))))
    if not result["issues"]:
        result["status"] = "ready"
    return result


def append_row(stream, value):
    stream.seek(0, os.SEEK_END)
    stream.write(json.dumps(value, sort_keys=True, allow_nan=False) + "\n")
    stream.flush()
    os.fsync(stream.fileno())


def checked_launcher(request, ledger):
    recipe = request.get("launcher")
    require(isinstance(recipe, dict) and text(recipe.get("path")) and sha256(recipe.get("sha256")),
            "missing sealed existing launcher")
    script = (ledger.parent / recipe["path"]).read_bytes()
    require(hashlib.sha256(script).hexdigest() == recipe["sha256"], "launcher digest mismatch")
    checked_receipt(request.get("preflight_evidence"), ledger.parent, {})
    return script


def launch(request, manifest, ledger):
    with ledger.open("r+", encoding="utf-8") as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        decision = campaign_admit(request, manifest, ledger, list(ledger_rows(stream)))
        if decision["status"] != "ready":
            return decision, 1
        script = checked_launcher(request, ledger)
        require(subprocess.run(["bash", "-n"], input=script, check=False).returncode == 0, "invalid launcher syntax")
        attempt = {"version": 2, "kind": "attempt", "model": decision["model"], "lane": decision["lane"],
                   **{key: request[key] for key in ("attempt_id", "decision_key", "mechanism", "manifest_sha256")},
                   "candidate_sha256": request.get("candidate_sha256"), "request": request, "admission": decision}
        append_row(stream, attempt)
    print(json.dumps({**decision, "attempt_id": attempt["attempt_id"]}, sort_keys=True), flush=True)
    env = {**os.environ, "PREFILL_ATTEMPT_ID": attempt["attempt_id"], "PREFILL_MANIFEST_SHA256": attempt["manifest_sha256"]}
    code = subprocess.run(["bash"], input=script, env=env, check=False).returncode
    return None, code if code >= 0 else 128 - code


def record_result(record, manifest, ledger):
    data, cases, digest = load_manifest(manifest)
    require(data["version"] == 2 and record.get("version") == 2, "need v2 result and budget")
    require(record.get("model") == data["model"] and record.get("manifest_sha256") == digest,
            "refusing result for another model or baseline")
    require(text(record.get("mechanism")), "missing mechanism")
    kind = record.get("kind")
    require(kind in ("result", "terminal", "decision"), "expected result, terminal or decision")
    hashes = {}
    if kind != "result":
        checked_receipt(record.get("evidence"), ledger.parent, hashes)
        require(text(record.get("reason")), "missing terminal/decision reason")
    if kind == "decision":
        require(record.get("state") in ("closed", "parked"), "unknown mechanism decision")
    attempt_id = record.get("attempt_id")
    with ledger.open("r+", encoding="utf-8") as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        own = model_records(ledger_rows(stream), data, digest)
        attempts = [row for row in own if row.get("kind") == "attempt" and row.get("attempt_id") == attempt_id]
        if attempt_id is not None or kind == "terminal":
            require(text(attempt_id) and len(attempts) == 1 and attempts[0]["mechanism"] == record["mechanism"],
                    "terminal/result does not match an admitted attempt")
            previous = [row for row in own if row.get("attempt_id") == attempt_id and row.get("kind") != "attempt"]
            require(not any(row.get("kind") == "terminal" or (kind == "terminal" and "outcome" in row) for row in previous),
                    "attempt already has a terminal outcome")
            if kind == "result":
                require(all(row.get("job_id") == record.get("job_id") for row in previous), "attempt already bound to another job")
                if record.get("scope") == "model":
                    require(attempts[0]["lane"] == "checkpoint" and attempts[0]["candidate_sha256"] == record.get("candidate_sha256"),
                            "integrated result does not match its qualified checkpoint launch")
        if kind == "result":
            require(text(record.get("job_id")), "need an actual job id")
            require(not any(row.get("kind") == kind and row.get("job_id") == record["job_id"]
                            and row.get("id") == record.get("id") for row in own), "duplicate job/call result")
            record = classify_result(record, cases, data, digest, ledger.parent, hashes)
            record.pop("outcome", None)
            if attempt_id is not None and record["claim_class"] != "unmeasured":
                if record["claim_class"] in ("diagnostic", "synthetic-screen"):
                    record["outcome"] = "inconclusive"
                else:
                    record["outcome"] = "passed" if record["performance_verdict"] == "retained" else "failed"
        elif kind == "terminal":
            require(record.get("outcome") in ("not_started", "failed", "inconclusive", "passed"), "invalid terminal outcome")
            if record["outcome"] == "passed":
                require(attempts[0]["lane"] == "platform" and record.get("validation_pass") is True,
                        "only a validated runnable platform artifact is a pass without performance samples")
                checked_receipt(record.get("runnable_elf"), ledger.parent, hashes)
                require(record["runnable_elf"]["path"] == attempts[0]["request"]["expected_runnable_artifact"],
                        "wrong runnable platform artifact")
                with (ledger.parent / record["runnable_elf"]["path"]).open("rb") as elf:
                    header = elf.read(64)
                require(len(header) == 64 and header[:6] == b"\x7fELF\x02\x01"
                        and header[16:20] in (b"\x02\x00\xf3\x00", b"\x03\x00\xf3\x00"),
                        "platform artifact must be an executable RISC-V ELF, not an object or text receipt")
        append_row(stream, record)
    status = "unmeasured" if record.get("claim_class") == "unmeasured" else "ready"
    return {**record, "status": status}


def status_report(ledger, manifests, queue, show_budgets=False):
    records = read_ledger(ledger)
    lines = ["# Prefill status", "", "Generated from frozen manifests and `experiments/results.jsonl`. Raw DUT cycles only.", ""]
    for manifest in manifests:
        data, cases, digest = load_manifest(manifest)
        require(data["version"] == 2, "status requires a v2 prefill budget")
        own = model_records(records, data, digest)
        hashes = {}
        results = [classify_result(row, cases, data, digest, ledger.parent, hashes) for row in own if row.get("kind") == "result"]
        revisions = {row["candidate_sha256"] for row in results if row["ledger_credit"]}
        score = checkpoint(manifest, ledger, next(iter(revisions)), records) if len(revisions) == 1 else None
        median = Fraction(twice_median(data["whole_prefill_samples"]), 2)
        profile = data["profile_total_cycles"]
        formal_sum = sum(data["whole_prefill_samples"])
        covered = score["covered_calls"] if score else 0
        shown = score and score["status"] != "unmeasured"
        candidate = next(iter(revisions)) if len(revisions) == 1 else None
        launched = {row["attempt_id"] for row in own if row.get("kind") == "attempt" and row.get("lane") == "checkpoint"
                    and row.get("candidate_sha256") == candidate}
        measured = next((row for row in results if row.get("attempt_id") in launched
                         and row.get("candidate_sha256") == candidate and row["claim_class"] == "integrated-model"
                         and row["performance_verdict"] == "retained"), None)
        integrated = "already launched" if launched else "ready" if shown and score["status"] == "ready" else "closed"
        lines.extend([f"## {data['model']}", "", f"- Complete prefill baseline (median, packed phase-off): **{json_number(median):,} cycles**.",
                      f"- Scored coverage on one exact merged revision: **{covered}/{data['expected_calls']} calls**; "
                      f"{data['expected_calls'] - covered} unmeasured.",
                      f"- Merged score: **{score['median']['saving_pct']:.4f}%** median and "
                      f"**{score['spread']['saving_pct']:.4f}%** spread." if shown else "- Merged score: **unmeasured**.",
                      f"- Integrated checkpoint: **{integrated}**."])
        if measured:
            saved = measured["baseline_median"] - measured["candidate_median"]
            lines.append(f"- Accepted integrated saving: **{saved:,} cycles** ({measured['job_id']}).")
        else:
            lines.append("- Accepted integrated saving: **unmeasured**.")
        if shown:
            remaining = max(0, PREFILL_CHECKPOINT_BPS / 100 - min(score["median"]["saving_pct"], score["spread"]["saving_pct"]))
            lines.append(f"- Remaining weighted gap to 30%: **{remaining:.4f} points** (strictly greater still required).")
        else:
            lines.append("- Remaining weighted gap: **unmeasured**. Planning still budgets the full 30-point target.")
        if len(revisions) > 1:
            lines.append("Multiple measured merged revisions; coverage is not unioned.")
        if show_budgets:
            gross = sum(bucket["cycles"] for bucket in data["budget_buckets"])
            lines.extend([f"- 1% floor: **{-(median // -100):,} cycles**. "
                          f"30% of full prefill: {float(median * Fraction(3, 10)):,.1f} cycles (planning only).",
                          "", f"Diagnostic budget across {data['profile_graphs']} graph(s), not formal savings:", "",
                          "| Bucket | Calls/prefill | Profile cycles (sum) | Max share in that profile |",
                          "|---|---:|---:|---:|"])
            for bucket in sorted(data["budget_buckets"], key=lambda item: -item["cycles"]):
                count = sum(cases[case]["calls"] for case in bucket["case_ids"])
                lines.append(f"| {bucket['id']} | {count} | {bucket['cycles']:,} | {100 * bucket['cycles'] / profile:.2f}% |")
            residual_calls = data.get("profile_total_calls")
            residual_calls = residual_calls - data["expected_calls"] if residual_calls is not None else "unmeasured"
            lines.append(f"| outside frozen cases / remaining | {residual_calls} | {profile - gross:,} | {100 * (profile - gross) / profile:.2f}% |")
            parts = data["phase_pools"]
            caps = ", ".join(f"{key} ≤ {100 * value / formal_sum:.2f}%" for key, value in parts.items())
            lines.extend(["", f"Generous phase ceilings (W1+R3 pool / formal R3 sum): {caps or 'unmeasured'}. "
                          "Nested in owner scopes; not additive with the diagnostic rows.", ""])
            prep = sum(parts.get(key, 0) for key in ("activation_prepare", "weight_prepare"))
            if prep:
                lines.append(f"Even removing both prep phases is bounded by **{100 * prep / formal_sum:.2f}%** "
                             "of full formal prefill under these timers. This is a ceiling, not a forecast.")
            for row in records:
                if row.get("kind") == "decision" and row.get("model") == data["model"]:
                    checked_receipt(row.get("evidence"), ledger.parent, hashes)
                    lines.append(f"- {row['mechanism']}: **{row['state']}** — {row['reason']}")
        offers = []
        for request in queue:
            if request.get("manifest_sha256") == digest:
                try:
                    decision = campaign_admit(request, manifest, ledger, records)
                    if decision["status"] == "ready":
                        checked_launcher(request, ledger)
                except (OSError, ValueError) as error:
                    decision = {"status": "blocked", "issues": [str(error)]}
                offers.append((request.get("decision_key"), decision))
        ready = sorted(((key, item) for key, item in offers if item["status"] == "ready"),
                       key=lambda offer: -offer[1].get("priority", 0))
        lines.append("")
        if ready:
            for key, item in ready[:3]:
                estimate = f" ({item['expected_saved_cycles']:,} expected cycles)" if "expected_saved_cycles" in item else ""
                lines.append(f"- Runnable queue: `{key}`{estimate}.")
        else:
            lines.append("- Next experiment: **none admitted**.")
        for key, item in offers:
            if item["status"] != "ready":
                cycles = item.get("expected_saved_cycles")
                reason = "; ".join(item["issues"])
                lines.append(f"- `{key}`: blocked — {reason}{f' ({cycles:,} expected cycles)' if cycles is not None else ''}.")
        lines.append("")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("plan").add_argument("directory", type=Path)
    for name in ("admit", "launch", "record"):
        subcommand = commands.add_parser(name)
        subcommand.add_argument("request", type=Path)
        subcommand.add_argument("--manifest", type=Path, required=name != "admit")
        subcommand.add_argument("--ledger", type=Path, required=name != "admit")
    scoring = commands.add_parser("checkpoint")
    scoring.add_argument("manifest", type=Path)
    scoring.add_argument("ledger", type=Path)
    scoring.add_argument("--candidate-sha256", required=True)
    status = commands.add_parser("status")
    status.add_argument("ledger", type=Path)
    status.add_argument("manifests", type=Path, nargs="+")
    status.add_argument("--queue", type=Path, nargs="*", default=[])
    status.add_argument("--output", type=Path)
    status.add_argument("--show-budgets", action="store_true")
    args = parser.parse_args()
    try:
        if args.command == "plan":
            result = plan(args.directory)
        elif args.command == "admit" and args.manifest is None and args.ledger is None:
            require(decode(args.request.read_bytes()).get("version") != 2, "prefill admission needs frozen manifest and ledger")
            result = admit(args.request)
        elif args.command == "checkpoint":
            result = checkpoint(args.manifest, args.ledger, args.candidate_sha256)
        elif args.command == "status":
            output = status_report(args.ledger, args.manifests, [decode(path.read_bytes()) for path in args.queue], args.show_budgets)
            if args.output:
                args.output.write_text(output, encoding="utf-8")
            else:
                print(output, end="")
            return 0
        else:
            require(args.manifest is not None and args.ledger is not None, "need both --manifest and --ledger")
            request = decode(sys.stdin.buffer.read() if args.request == Path("-") else args.request.read_bytes())
            if args.command == "admit":
                result = campaign_admit(request, args.manifest, args.ledger, read_ledger(args.ledger))
            elif args.command == "record":
                result = record_result(request, args.manifest, args.ledger)
            else:
                result, returncode = launch(request, args.manifest, args.ledger)
                if result is not None:
                    print(json.dumps(result, sort_keys=True))
                return returncode
    except (OSError, ValueError) as error:
        print(f"agent-workflow-guard: {error}", file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] == "ready" else 1


if __name__ == "__main__":
    sys.exit(main())

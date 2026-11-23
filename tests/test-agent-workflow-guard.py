import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


GUARD = Path(__file__).resolve().parents[1] / "scripts" / "agent-workflow-guard.py"
CANDIDATE = "b" * 64


class WorkflowGuardTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.directory = Path(directory.name)
        self.manifest = {
            "version": 1, "model": "fixture", "workload": "PP256", "design": "fixture-design",
            "profile_sha256": "c" * 64, "baseline_sha256": "a" * 64, "threshold_bps": 3000,
            "run_config_sha256": "f" * 64,
            "expected_calls": 5,
            "cases": [{"id": "hot", "calls": 4, "state": "warm", "binding_sha256": "d" * 64},
                      {"id": "cold", "calls": 1, "state": "cold", "binding_sha256": "e" * 64}],
        }
        raw = json.dumps(self.manifest).encode()
        self.manifest_path = self.directory / "manifest.json"
        self.manifest_path.write_bytes(raw)
        self.ledger = self.directory / "owners.jsonl"
        self.rows = []
        for case in self.manifest["cases"]:
            row = {
                "id": case["id"], "binding_sha256": case["binding_sha256"], "state": case["state"],
                "manifest_sha256": hashlib.sha256(raw).hexdigest(), "candidate_sha256": CANDIDATE,
                "scope": "owner", "input": "captured", "metric": "dut_cycles", "phase_off": True,
                "work_equal": True, "correctness": True, "entry_state": True,
                "path_hit": True, "terminal": True, "released": True,
            }
            for arm, cycles in (("baseline", [100, 102, 101]), ("candidate", [60, 61, 62])):
                name = f"{case['id']}-{arm}.receipt"
                receipt = name.encode()
                (self.directory / name).write_bytes(receipt)
                row[arm] = {"cycles": cycles, "warmups": int(case["state"] == "warm"),
                            "placement": "board6+7", "receipt": name,
                            "receipt_sha256": hashlib.sha256(receipt).hexdigest(),
                            "bundle_sha256": "a" * 64 if arm == "baseline" else CANDIDATE,
                            "run_config_sha256": self.manifest["run_config_sha256"],
                            "payload_sha256": ("1" if arm == "baseline" else "2") * 64}
            self.rows.append(row)

    def guard(self, expected, *args):
        result = subprocess.run([sys.executable, GUARD, *args], capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, expected, result.stderr + result.stdout)
        return json.loads(result.stdout) if expected != 2 else result.stderr

    def score(self, expected, rows=None):
        if rows is None:
            rows = self.rows
        self.ledger.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
        return self.guard(expected, "checkpoint", self.manifest_path, self.ledger, "--candidate-sha256", CANDIDATE)

    def test_plan_budget_and_line_length(self):
        for name in ("task_plan.md", "progress.md", "findings.md"):
            (self.directory / name).write_text("# current\n", encoding="utf-8")
        self.assertEqual(self.guard(0, "plan", self.directory)["status"], "ready")
        (self.directory / "progress.md").write_bytes(b"a" * 24_577)
        (self.directory / "task_plan.md").write_text("界" * 171, encoding="utf-8")
        self.assertEqual(len(self.guard(1, "plan", self.directory)["issues"]), 2)
        (self.directory / "findings.md").unlink()
        self.assertEqual(len(self.guard(1, "plan", self.directory)["issues"]), 3)

    def test_lane_budgets_and_duplicate_pending_work(self):
        request = {"lane": "screen", "decision_key": "fixture/scan", "hypothesis": "isolate cost",
                   "max_minutes": 10, "stop_condition": "terminal or deadline", "prior_attempts": [],
                   "baseline_evidence": "profile", "priority_reason": "high baseline share"}
        path = self.directory / "request.json"

        def admit(expected):
            path.write_text(json.dumps(request), encoding="utf-8")
            return self.guard(expected, "admit", path)

        admit(0)
        request["prior_attempts"] = [{"receipt": "job-1", "outcome": "pending"}]
        admit(1)
        request["prior_attempts"][0]["outcome"] = "failed"
        admit(0)
        request["prior_attempts"].append({"receipt": "job-2", "outcome": "inconclusive"})
        admit(1)
        request.update(lane="platform", prior_attempts=[])
        self.assertIn("unlocks_call", admit(2))
        request.update(unlocks_call="real call", expected_runnable_artifact="owner ELF",
                       independent_screen="another family")
        admit(0)
        request["prior_attempts"] = [{"receipt": "provider smoke", "outcome": "failed"}]
        self.assertIn("park", admit(1)["issues"][0])
        request["max_minutes"] = True
        self.assertIn("max_minutes", admit(2))

    def test_full_coverage_and_weighting_with_even_sample_counts(self):
        for row in self.rows:
            row["baseline"]["cycles"].append(103)
        self.rows[0]["candidate"]["cycles"].append(63)
        self.rows[1]["candidate"]["cycles"] = [94, 95, 96, 97]
        result = self.score(0)
        self.assertEqual(result["covered_calls"], 5)
        self.assertEqual(result["median"]["baseline_twice_cycles"], 1015)
        self.assertEqual(result["median"]["candidate_twice_cycles"], 683)
        self.assertEqual(result["spread"]["candidate_cycles"], 349)

    def test_missing_row_suppresses_score(self):
        result = self.score(1, self.rows[:1])
        self.assertEqual(result["missing"], ["cold"])
        self.assertEqual(result["covered_calls"], 4)
        self.assertNotIn("median", result)
        self.assertNotIn("spread", result)

    def test_exclusions_never_enter_model_score(self):
        for key, value in {"scope": "leaf", "input": "synthetic", "state": "preallocated",
                           "metric": "tok/s", "phase_off": False, "terminal": False,
                           "released": False, "work_equal": 1, "binding_sha256": "0" * 64,
                           "candidate_sha256": "0" * 64, "manifest_sha256": "0" * 64}.items():
            with self.subTest(key=key):
                rows = copy.deepcopy(self.rows)
                rows[0][key] = value
                result = self.score(1, rows)
                self.assertEqual(result["status"], "unmeasured")
                self.assertIn("hot", result["excluded"])
                self.assertNotIn("median", result)
        for key, value in {"placement": "other-board", "warmups": 0, "cycles": [60, 61],
                           "bundle_sha256": "0" * 64, "run_config_sha256": "0" * 64}.items():
            with self.subTest(arm_key=key):
                rows = copy.deepcopy(self.rows)
                rows[0]["candidate"][key] = value
                self.assertIn("hot", self.score(1, rows)["excluded"])

    def test_replaced_or_missing_receipt_is_unmeasured(self):
        path = self.directory / self.rows[0]["baseline"]["receipt"]
        path.write_text("replaced", encoding="utf-8")
        self.assertIn("digest mismatch", self.score(1)["excluded"]["hot"])
        path.unlink()
        self.assertIn("missing receipt file", self.score(1)["excluded"]["hot"])

    def test_exact_threshold_and_spread_do_not_pass(self):
        for row in self.rows:
            row["baseline"]["cycles"] = [100, 100, 100]
            row["candidate"]["cycles"] = [69, 70, 70]
        result = self.score(1)
        self.assertEqual(result["median"]["saving_pct"], 30)
        self.assertFalse(result["median"]["clears_threshold"])
        for row in self.rows:
            row["candidate"]["cycles"] = [69, 69, 70]
        result = self.score(1)
        self.assertTrue(result["median"]["clears_threshold"])
        self.assertFalse(result["spread"]["clears_threshold"])

    def test_bad_frozen_inputs_fail_closed(self):
        self.assertIn("duplicate receipt", self.score(2, self.rows + self.rows[:1]))
        self.assertIn("unknown frozen case", self.score(2, [{**self.rows[0], "id": "other model"}]))
        self.manifest["expected_calls"] = 6
        self.manifest_path.write_text(json.dumps(self.manifest), encoding="utf-8")
        self.assertIn("frozen call count", self.score(2))
        self.manifest_path.write_text('{"version":1,"version":1}', encoding="utf-8")
        self.assertIn("duplicate JSON key", self.score(2))

    def prefill_budget(self):
        receipt_path = self.directory / "prefill.receipt"
        full_samples = [9_990, 10_000, 10_010]
        receipt = json.dumps({"b": {"samples_cycles": full_samples, "elf_sha256": self.manifest["baseline_sha256"]}})
        receipt_path.write_text(receipt, encoding="utf-8")
        evidence = {"path": str(receipt_path), "sha256": hashlib.sha256(receipt.encode()).hexdigest()}
        self.manifest.update(version=2, whole_prefill_samples=full_samples,
                             baseline_receipt={**evidence, "json_key": "b"}, profile_receipt=evidence,
                             profile_sha256=evidence["sha256"], profile_graphs=1, profile_total_cycles=11_000,
                             profile_total_calls=6, phase_pools={"weight_prepare": 900},
                             budget_buckets=[{"id": "native", "case_ids": ["hot", "cold"], "cycles": 5_000}])
        raw = json.dumps(self.manifest).encode()
        self.manifest_path.write_bytes(raw)
        self.ledger.write_text("")
        digest = hashlib.sha256(raw).hexdigest()
        for case, row in zip(self.manifest["cases"], self.rows):
            row.update(version=2, kind="result", model="fixture", job_id="job-1234", mechanism="tile-combined",
                       scope="operator", comparison_only=False, calls_per_prefill=case["calls"], manifest_sha256=digest)
            if case["state"] == "cold":
                for key in ("baseline", "candidate"):
                    row[key]["reset_ids"] = [f"{key}-reset-{index}" for index in range(3)]
        return digest, evidence

    def campaign(self, verb, value):
        return subprocess.run([sys.executable, GUARD, verb, "-", "--manifest", self.manifest_path,
                               "--ledger", self.ledger], input=json.dumps(value), text=True, capture_output=True)

    def launch_request(self, digest, evidence):
        marker = self.directory / "child-ran"
        recipe = f'''printf '%s' "$PREFILL_ATTEMPT_ID" > '{marker}'\n'''
        launcher = self.directory / "existing.launcher"
        launcher.write_text(recipe, encoding="utf-8")
        return marker, {
            "version": 2, "lane": "screen", "attempt_id": "fixture-attempt-1", "manifest_sha256": digest,
            "decision_key": "activation+weight", "mechanism": "tile-combined", "hypothesis": "amortize repeated work",
            "approach": "new_mechanism", "target_scope": "operator",
            "max_minutes": 1, "stop_condition": "one capped pair", "preflight_evidence": evidence,
            "launcher": {"path": str(launcher), "sha256": hashlib.sha256(recipe.encode()).hexdigest()},
            "forecast": [{"id": "hot", "calls": 4, "baseline_cycles": 100, "candidate_cycles": 50,
                          "state_and_applicability": "same owner boundary and input", "evidence": evidence}],
            "cost": {"build": 3, "pldm": 5, "integration_risk": 2},
        }

    def test_budget_rejects_before_existing_launcher_and_registers_pending(self):
        digest, evidence = self.prefill_budget()
        marker, request = self.launch_request(digest, evidence)
        for updates, expected in (({"forecast": []}, 2),
                                  ({"forecast": [{**request["forecast"][0], "calls": 5}]}, 2),
                                  ({"forecast": [{**request["forecast"][0], "candidate_cycles": 99}]}, 1),
                                  ({"forecast": request["forecast"] * 2}, 2),
                                  ({"launcher": {"path": request["launcher"]["path"], "sha256": "0" * 64}}, 2)):
            result = self.campaign("launch", {**request, **updates})
            self.assertEqual(result.returncode, expected, result.stderr + result.stdout)
            self.assertFalse(marker.exists())
        result = self.campaign("launch", request)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(marker.read_text(), "fixture-attempt-1")
        self.assertEqual(json.loads(result.stdout)["expected_saved_cycles"], 200)
        self.assertEqual(json.loads(result.stdout)["expected_gain_pct"], 2)
        self.assertIn("pending", self.campaign("launch", {**request, "attempt_id": "fixture-attempt-2"}).stdout)
        self.assertEqual(len(self.ledger.read_text().splitlines()), 1)

    def test_local_pool_wall_and_leaf_requires_a_downstream_owner(self):
        digest, evidence = self.prefill_budget()
        marker, request = self.launch_request(digest, evidence)
        result = self.campaign("launch", {**request, "approach": "local_tuning", "phase_pool": "weight_prepare"})
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("budget wall", result.stdout)
        self.assertFalse(marker.exists())
        self.assertEqual(self.campaign("admit", {**request, "target_scope": "leaf"}).returncode, 2)

    def test_mechanism_stops_after_two_terminal_failures_and_explicit_close(self):
        digest, evidence = self.prefill_budget()
        _, request = self.launch_request(digest, evidence)
        for index in (1, 2):
            request["attempt_id"] = f"closure-{index}"
            self.assertEqual(self.campaign("launch", request).returncode, 0)
            terminal = {"version": 2, "kind": "terminal", "model": "fixture", "manifest_sha256": digest,
                        "mechanism": request["mechanism"], "attempt_id": request["attempt_id"], "outcome": "failed",
                        "reason": "canonical collector terminal", "evidence": evidence}
            self.assertEqual(self.campaign("record", terminal).returncode, 0)
            self.assertEqual(self.campaign("record", terminal).returncode, 2)
        request["attempt_id"] = "closure-3"
        self.assertIn("two failures", self.campaign("admit", request).stdout)
        decision = {"version": 2, "kind": "decision", "model": "fixture", "manifest_sha256": digest,
                    "mechanism": "disallowed", "state": "closed", "reason": "measured regression", "evidence": evidence}
        self.assertEqual(self.campaign("record", decision).returncode, 0)
        self.assertIn("closed", self.campaign("admit", {**request, "mechanism": "disallowed"}).stdout)

    def test_v2_requires_spread_only_on_exact_production_rows(self):
        self.prefill_budget()
        for update, claim in (({"input": "synthetic"}, "synthetic-screen"),
                              ({"state": "preallocated"}, "fill-screen"),
                              ({"scope": "leaf"}, "screen_only"),
                              ({"comparison_only": True}, "comparison-screen"),
                              ({"entry_state": None}, "unmeasured"),
                              ({"calls_per_prefill": 1}, "unmeasured")):
            with self.subTest(update=update):
                self.ledger.write_text("")
                receipt = self.campaign("record", {**self.rows[0], **update, "ledger_credit": True})
                result = json.loads(receipt.stdout)
                self.assertEqual(result["claim_class"], claim)
                self.assertFalse(result["ledger_credit"])
        self.ledger.write_text("")
        other = {**self.rows[0], "candidate": {**self.rows[0]["candidate"], "placement": "unmatched"}}
        self.assertEqual(json.loads(self.campaign("record", other).stdout)["claim_class"], "diagnostic")
        self.assertEqual(self.score(0)["covered_calls"], 5)
        self.assertNotIn("median", self.score(1, self.rows[:1]))
        self.assertNotIn("median", self.score(1, self.rows + self.rows[:1]))
        mixed = copy.deepcopy(self.rows)
        mixed[0]["candidate_sha256"] = "e" * 64
        self.assertNotIn("median", self.score(1, mixed))
        cold = copy.deepcopy(self.rows)
        cold[1]["candidate"]["reset_ids"] = cold[1]["baseline"]["reset_ids"]
        self.assertIn("cold reset reused", self.score(1, cold)["excluded"]["cold"])
        overlap = copy.deepcopy(self.rows)
        overlap[0]["baseline"]["cycles"] = [100, 200, 300]
        overlap[0]["candidate"]["cycles"] = [50, 50, 101]
        self.assertEqual(self.score(1, overlap)["excluded"]["hot"], "candidate max exceeds baseline min")

    def test_v2_checkpoint_is_strict_and_launched_once(self):
        digest, evidence = self.prefill_budget()
        marker, request = self.launch_request(digest, evidence)
        request.update(lane="checkpoint", candidate_sha256=CANDIDATE)
        self.assertEqual(self.campaign("launch", request).returncode, 1)
        self.assertFalse(marker.exists())
        self.score(0)
        self.assertEqual(self.campaign("launch", request).returncode, 0)
        request["attempt_id"] = "wrong-duplicate"
        self.assertIn("one integrated launch", self.campaign("launch", request).stdout)
        for row in self.rows:
            row["baseline"]["cycles"] = [100, 100, 100]
            row["candidate"]["cycles"] = [69, 69, 70]
        self.assertFalse(self.score(1)["spread"]["clears_threshold"])


if __name__ == "__main__":
    unittest.main()

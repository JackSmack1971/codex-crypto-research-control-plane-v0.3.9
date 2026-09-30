from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "control_plane"))
from fin_data_source import (build_manifest, materialize, qualify, verify_materialization,
                             _evaluate_qualification, _bind_snapshot_to_ledger, _rows, assemble_capture,
                             _value_matches_schema)  # noqa: E402
from common import digest  # noqa: E402
from source_evidence import validate_bundle, validate_source_manifest  # noqa: E402
from build_evidence_bundle import build as build_bundle  # noqa: E402


class FinDataQualificationTests(unittest.TestCase):
    def setUp(self):
        self.config = json.loads((ROOT / "config/source-capabilities/fin-data.json").read_text(encoding="utf-8"))
        self.now = "2026-09-29T12:00:00Z"
        self.tools = [item["tool_name"] for item in self.config["capabilities"]]
        self.snapshot = {"endpoint_url": self.config["runtime"], "deployment_id": "dep-prod-1",
                         "reachability": "SUCCEEDED", "initialization": "SUCCEEDED", "tools": self.tools,
                         "representative_results": {}, "response_contracts": {}}
        self.test_contracts = {"schema_version": "1.0", "source_id": "fin_data_mcp_render_prod", "contracts": []}
        for cap in self.config["capabilities"]:
            self.snapshot["representative_results"][cap["capability_id"]] = {
                "observed_at": "2026-09-29T11:59:30Z", "isError": False,
                "pagination_complete": True,
                "structuredContent": {"rows": [{"ts": "2026-09-29T11:59:00Z", "rate": 0.001}]}}
            contract = {"capability_id": cap["capability_id"], "status": "REGISTERED",
                        "required_fields": ["ts", "rate"], "field_types": {"ts": "string", "rate": "number"},
                        "max_age_seconds": 200000, "pagination_mode": "SINGLE_RESPONSE"}
            self.test_contracts["contracts"].append(contract)
            self.snapshot["response_contracts"][cap["capability_id"]] = contract

    def test_unavailable_endpoint_is_explicit(self):
        self.snapshot["reachability"] = "FAILED"
        result = _evaluate_qualification(self.snapshot, self.config, self.now, self.test_contracts)
        self.assertEqual("UNAVAILABLE", result["status"])
        self.assertEqual("endpoint_unreachable_or_cold", result["endpoint_reason"])
        self.assertTrue(all(item["status"] == "UNAVAILABLE" and not item["admitted"] for item in result["capabilities"].values()))
        self.assertEqual("NONE", result["fallback"])

    def test_unprobed_endpoint_is_blocked_as_unverified_not_reported_unavailable(self):
        self.snapshot["reachability"] = "UNKNOWN"
        result = _evaluate_qualification(self.snapshot, self.config, self.now, self.test_contracts)
        self.assertEqual("BLOCKED", result["status"])
        self.assertEqual("endpoint_reachability_unverified", result["endpoint_reason"])

    def test_missing_tool_is_unavailable_for_only_that_capability(self):
        missing = self.config["capabilities"][0]
        self.snapshot["tools"].remove(missing["tool_name"])
        result = _evaluate_qualification(self.snapshot, self.config, self.now, self.test_contracts)
        self.assertEqual("UNAVAILABLE", result["capabilities"][missing["capability_id"]]["status"])
        self.assertEqual("QUALIFIED", result["capabilities"][self.config["capabilities"][1]["capability_id"]]["status"])

    def test_malformed_response_blocks_capability(self):
        cap = self.config["capabilities"][0]
        self.snapshot["representative_results"][cap["capability_id"]]["structuredContent"] = "not-json-rows"
        result = _evaluate_qualification(self.snapshot, self.config, self.now, self.test_contracts)
        self.assertEqual("malformed_or_empty_representative_response", result["capabilities"][cap["capability_id"]]["reason"])

    def test_stale_response_degrades_capability(self):
        cap = self.config["capabilities"][0]
        self.snapshot["representative_results"][cap["capability_id"]]["observed_at"] = "2026-09-26T10:00:00Z"
        result = _evaluate_qualification(self.snapshot, self.config, self.now, self.test_contracts)
        status = result["capabilities"][cap["capability_id"]]
        self.assertEqual("DEGRADED", status["status"])
        self.assertEqual("representative_response_stale", status["reason"])

    def test_schema_drift_fails_closed(self):
        cap = self.config["capabilities"][0]
        row = self.snapshot["representative_results"][cap["capability_id"]]["structuredContent"]["rows"][0]
        row["rate"] = "not-numeric"
        result = _evaluate_qualification(self.snapshot, self.config, self.now, self.test_contracts)
        self.assertEqual("response_schema_type_drift", result["capabilities"][cap["capability_id"]]["reason"])

    def test_partial_capability_loss_does_not_promote_missing_capability(self):
        cap = self.config["capabilities"][3]
        self.snapshot["representative_results"].pop(cap["capability_id"])
        result = _evaluate_qualification(self.snapshot, self.config, self.now, self.test_contracts)
        self.assertEqual("DEGRADED", result["status"])
        self.assertEqual("BLOCKED", result["capabilities"][cap["capability_id"]]["status"])
        self.assertEqual("QUALIFIED", result["capabilities"][self.config["capabilities"][0]["capability_id"]]["status"])

    def test_incomplete_provider_page_is_reported_before_unregistered_contract(self):
        cap = self.config["capabilities"][0]
        self.snapshot["representative_results"][cap["capability_id"]] = {
            "isError": False, "pagination_complete": False,
            "structuredContent": "truncated provider page"}
        contracts = {"schema_version": "1.0", "source_id": "fin_data_mcp_render_prod",
                     "contracts": [{"capability_id": cap["capability_id"], "status": "UNREGISTERED"}]}
        result = _evaluate_qualification(self.snapshot, self.config, self.now, contracts)
        self.assertEqual("pagination_completion_unverified",
                         result["capabilities"][cap["capability_id"]]["reason"])

    def test_successful_qualification_is_separate_from_evidence_admission(self):
        result = _evaluate_qualification(self.snapshot, self.config, self.now, self.test_contracts)
        self.assertEqual("QUALIFIED", result["status"])
        self.assertTrue(all(item["status"] == "QUALIFIED" for item in result["capabilities"].values()))
        self.assertTrue(all(not item["admitted"] for item in result["capabilities"].values()))

    def test_endpoint_qualification_does_not_require_unattested_render_deployment_id(self):
        self.snapshot["deployment_id"] = None
        result = _evaluate_qualification(self.snapshot, self.config, self.now, self.test_contracts)
        self.assertEqual("AVAILABLE", result["endpoint_status"])
        self.assertEqual("QUALIFIED", result["status"])

    def test_production_policy_keeps_unregistered_contracts_blocked(self):
        result = qualify(self.snapshot, self.config, self.now)
        self.assertEqual("BLOCKED", result["status"])
        self.assertEqual("verified_request_ledger_required",
                         result["capabilities"][self.config["capabilities"][0]["capability_id"]]["reason"])

    def test_qualified_looking_snapshot_with_missing_or_unsealed_ledger_is_blocked(self):
        missing = qualify(self.snapshot, self.config, self.now)
        self.assertEqual("verified_request_ledger_required", missing["endpoint_reason"])
        unsealed = qualify(self.snapshot, self.config, self.now,
                           {"source_id": "fin_data_mcp_render_prod", "status": "OPEN", "calls": [],
                            "tainted": False, "policy_digest": "sha256:" + "0" * 64})
        self.assertEqual("BLOCKED", unsealed["status"])
        self.assertEqual("request_ledger_evidence_invalid", unsealed["endpoint_reason"])

    def test_bound_response_receive_time_overrides_untrusted_snapshot_freshness(self):
        cap = self.config["capabilities"][0]
        args = {"instId": "BTC-USDT"}
        envelope = {"source_id": "fin_data_mcp_render_prod", "request_id": "req-freshness",
                    "permit_id": "permit-1", "capability_id": cap["capability_id"],
                    "tool_name": cap["tool_name"], "endpoint_url": self.config["runtime"],
                    "deployment_id": "dep-prod-1",
                    "arguments_digest": digest(args), "isError": False,
                    "received_at": "2026-09-29T11:59:00Z", "pagination_complete": True,
                    "result": {"rows": [{"ts": "2026-09-29T11:58:00Z", "rate": 0.001}]}}
        policy = json.loads((ROOT / "config/fin-data-request-policy.json").read_text(encoding="utf-8"))
        ledger = {"source_id": "fin_data_mcp_render_prod", "policy_digest": digest(policy),
                  "status": "SEALED", "tainted": False, "calls": [{
                      "request_id": "req-freshness", "permit_id": "permit-1",
                      "capability_id": cap["capability_id"], "tool_name": cap["tool_name"],
                      "endpoint_url": self.config["runtime"], "arguments_digest": digest(args),
                      "completed_at": "2026-09-29T11:59:01Z", "result_digest": digest(envelope)}]}
        ledger["content_digest"] = digest(ledger)
        snapshot = {"endpoint_url": self.config["runtime"], "deployment_id": "dep-prod-1",
                    "representative_results": {cap["capability_id"]: {
                        "observed_at": "2026-09-29T11:59:59Z", "request_envelope": envelope}}}
        errors = _bind_snapshot_to_ledger(snapshot, ledger)
        self.assertEqual({"mcp_control_operation_missing:fin.mcp.initialize",
                          "mcp_control_operation_missing:fin.mcp.initialized_notification",
                          "mcp_control_operation_missing:fin.mcp.tools_list"}, set(errors))
        bound = snapshot["representative_results"][cap["capability_id"]]
        self.assertEqual(envelope["received_at"], bound["observed_at"])
        self.assertTrue(bound["pagination_complete"])

    def test_positional_provider_rows_and_nested_orderbook_schema_are_deterministic(self):
        rows = _rows({"structuredContent": {"data": [["1790736000000", "1.4"]]}})
        self.assertEqual([{"0": "1790736000000", "1": "1.4"}], rows)
        schema = {"type": "array", "minItems": 1, "maxItems": 2,
                  "items": {"type": "array", "minItems": 4, "maxItems": 4,
                            "items": {"type": "string"}}}
        self.assertTrue(_value_matches_schema([["1", "2", "0", "4"]], schema))
        self.assertFalse(_value_matches_schema([["1", "2", "0"]], schema))

    def test_qualification_cli_uses_repository_policy_and_validates_its_report(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "qualification.json"
            ledger = Path(directory) / "ledger.json"
            subprocess.run([sys.executable, str(ROOT / "scripts/control_plane/fin_data_request_gate.py"),
                            "init", "--attempt-id", "qualification-test", "--ledger", str(ledger)],
                           cwd=ROOT, check=True, capture_output=True, text=True)
            subprocess.run([sys.executable, str(ROOT / "scripts/control_plane/fin_data_request_gate.py"),
                            "seal", "--ledger", str(ledger)], cwd=ROOT, check=True, capture_output=True, text=True)
            proc = subprocess.run([sys.executable, str(ROOT / "scripts/control_plane/fin_data_source.py"),
                                   "qualify", str(ROOT / "research/sources/fin-data-qualification-observation-2026-09-30.json"),
                                   "--now", self.now, "--ledger", str(ledger), "--out", str(output)], cwd=ROOT,
                                  capture_output=True, text=True)
            self.assertEqual(1, proc.returncode, proc.stdout + proc.stderr)
            report = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual("BLOCKED", report["status"])
            validation = subprocess.run([sys.executable, str(ROOT / "scripts/control_plane/validate_artifact.py"),
                                          str(output), str(ROOT / "schemas/fin_data_qualification_report.schema.json")],
                                         cwd=ROOT, capture_output=True, text=True)
            self.assertEqual(0, validation.returncode, validation.stdout + validation.stderr)

    def test_wrong_production_endpoint_identity_is_blocked(self):
        self.snapshot["endpoint_url"] = "https://fin-data-mcp-http-v2.onrender.com/mcp"
        result = _evaluate_qualification(self.snapshot, self.config, self.now, self.test_contracts)
        self.assertEqual("BLOCKED", result["endpoint_status"])
        self.assertEqual("configured_endpoint_identity_mismatch", result["endpoint_reason"])

    def test_materialization_stays_diagnostic_without_separate_admission(self):
        cap = self.config["capabilities"][0]
        report = qualify(self.snapshot, self.config, self.now)
        self.snapshot["qualification_report"] = report
        manifest, rows = build_manifest(self.snapshot, cap, "2026-09-29-eod", "attempt-1",
                                        "2026-09-30T00:00:00Z", self.now)
        self.assertEqual([], manifest["datasets"])
        self.assertEqual("NOT_ADMITTED", manifest["admissibility"])
        self.assertEqual(0, len(rows))
        self.assertEqual([], validate_source_manifest(manifest))

    def test_source_materialization_binds_raw_and_normalized_files(self):
        cap = self.config["capabilities"][0]
        self.snapshot["qualification_report"] = qualify(self.snapshot, self.config, self.now)
        with tempfile.TemporaryDirectory() as directory:
            manifest = materialize(self.snapshot, cap, "2026-09-29-eod", "attempt-1",
                                   "2026-09-30T00:00:00Z", self.now, Path(directory))
            self.assertEqual([], verify_materialization(manifest))
            manifest_obj = json.loads(manifest.read_text(encoding="utf-8"))
            self.assertEqual([], manifest_obj["datasets"])
            raw = manifest.parent / manifest_obj["adapter_payload"]["raw_path"]
            raw.write_text("{}\n", encoding="utf-8")
            self.assertIn("raw_response_digest_mismatch", verify_materialization(manifest))

    def test_captured_production_qualification_and_materializations_bind_to_evidence_bundle(self):
        capture = ROOT / "research/sources/fin-data-prod-probe-2026-09-30-v2"
        report = json.loads((capture / "qualification-report.json").read_text(encoding="utf-8"))
        ledger = json.loads((capture / "request-ledger.json").read_text(encoding="utf-8"))
        snapshot = assemble_capture(capture)
        self.assertEqual("AVAILABLE", report["endpoint_status"])
        self.assertEqual("DEGRADED", report["status"])
        self.assertEqual(9, sum(item["status"] == "QUALIFIED" for item in report["capabilities"].values()))
        self.assertEqual("pagination_completion_unverified",
                         report["capabilities"]["fin.crypto.instrument_discovery"]["reason"])
        self.assertTrue(all(not item["admitted"] for item in report["capabilities"].values()))
        self.assertEqual("SEALED", ledger["status"])
        self.assertEqual(report["ledger_digest"], ledger["content_digest"])
        snapshot["verified_request_ledger"] = ledger
        replayed = qualify(snapshot, self.config, report["observed_at"], ledger)
        self.assertEqual(report["snapshot_digest"], replayed["snapshot_digest"])
        self.assertTrue(all(call["result_digest"] for call in ledger["calls"]))
        self.assertTrue(all(json.loads(path.read_text(encoding="utf-8")).get("protocol_method")
                            for path in capture.glob("*.result.json")))

        materialized = capture / "materialized"
        manifests = sorted(materialized.glob("*.manifest.json"))
        self.assertEqual(10, len(manifests))
        for manifest_path in manifests:
            self.assertEqual([], verify_materialization(manifest_path))
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            for dataset in manifest["datasets"]:
                self.assertEqual("DIAGNOSTIC", dataset["evidence_role"])
                self.assertEqual("NOT_ADMITTED", dataset["admissibility"])
        selected = next(path for path in manifests if "fin_crypto_open_interest" in path.name)
        bundle = build_bundle([selected], "2026-09-30-eod", "fin-data-prod-probe-2026-09-30-v2",
                              "2026-10-01T00:00:00Z", materialized)
        self.assertEqual([], validate_bundle(bundle, materialized))

    def test_unprobed_source_seals_explicit_blocked_manifest_without_fabricated_rows(self):
        cap = self.config["capabilities"][0]
        self.snapshot["reachability"] = "UNKNOWN"
        self.snapshot["initialization"] = "UNKNOWN"
        self.snapshot["tools"] = []
        self.snapshot["representative_results"] = {}
        with tempfile.TemporaryDirectory() as directory:
            manifest_path = materialize(self.snapshot, cap, "2026-09-29-eod", "attempt-unknown",
                                         "2026-09-30T00:00:00Z", self.now, Path(directory))
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual("BLOCKED", manifest["status"])
            self.assertEqual("UNKNOWN", manifest["availability_status"])
            self.assertEqual([], manifest["datasets"])
            self.assertEqual([], verify_materialization(manifest_path))
            bundle = build_bundle([manifest_path], "2026-09-29-eod", "attempt-unknown",
                                  "2026-09-30T00:00:00Z", Path(directory))
            self.assertEqual([], validate_bundle(bundle, Path(directory)))
            self.snapshot["reachability"] = "COLD"
            cold_path = materialize(self.snapshot, cap, "2026-09-29-eod", "attempt-cold",
                                    "2026-09-30T00:00:00Z", self.now, Path(directory) / "cold")
            cold = json.loads(cold_path.read_text(encoding="utf-8"))
            self.assertEqual("UNAVAILABLE", cold["status"])
            self.assertEqual("UNAVAILABLE", cold["availability_status"])
            self.assertEqual([], verify_materialization(cold_path))


if __name__ == "__main__":
    unittest.main()

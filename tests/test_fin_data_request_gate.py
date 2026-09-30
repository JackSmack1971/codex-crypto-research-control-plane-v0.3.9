from __future__ import annotations

import json
import io
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts/control_plane"))
from common import digest  # noqa: E402
from fin_data_use_authorization import (authorization_error, evidence_binding_authorized,
                                        load_policy, policy_digest)  # noqa: E402
import fin_data_request_gate  # noqa: E402


class FinDataRequestGateTests(unittest.TestCase):
    def run_gate(self, *args):
        return subprocess.run([sys.executable, str(ROOT / "scripts/control_plane/fin_data_request_gate.py"),
                               *map(str, args)], cwd=ROOT, capture_output=True, text=True)

    def run_gate_with_authorization_fixture(self, policy, *args):
        output = io.StringIO()
        with patch.object(fin_data_request_gate, "load_policy", return_value=policy), \
                patch.object(fin_data_request_gate, "authorization_error", return_value=None), \
                patch.object(sys, "argv", ["fin_data_request_gate.py", *map(str, args)]), \
                redirect_stdout(output):
            result = fin_data_request_gate.main()
        return result, output.getvalue()

    def test_permit_binding_seal_and_tamper_detection(self):
        with tempfile.TemporaryDirectory() as td:
            ledger = Path(td) / "ledger.json"
            arguments = Path(td) / "args.json"
            result_file = Path(td) / "result.json"
            call_args = {"name": "crypto_ticker", "arguments": {"instId": "BTC-USDT"}}
            arguments.write_text(json.dumps(call_args), encoding="utf-8")
            self.assertEqual(0, self.run_gate("init", "--attempt-id", "attempt-test", "--ledger", ledger).returncode)
            authorization = load_policy()
            permit = self.run_gate("permit", "--ledger", ledger, "--capability-id", "fin.crypto.ticker",
                                   "--tool-name", "crypto_ticker", "--request-id", "req-1",
                                   "--arguments-file", arguments)
            if authorization_error(authorization):
                self.assertEqual(4, permit.returncode)
                self.assertIn("SOURCE_RUNTIME_AUTHORIZATION_BLOCKED", permit.stdout)
                saved = json.loads(ledger.read_text(encoding="utf-8"))
                self.assertEqual(policy_digest(authorization), saved["provider_use_authorization_digest"])
                self.assertEqual([], saved["calls"])
                self.assertEqual(0, self.run_gate("seal", "--ledger", ledger).returncode)
                self.assertEqual(0, self.run_gate("verify", "--ledger", ledger).returncode)
                return
            self.assertEqual(0, permit.returncode, permit.stdout + permit.stderr)
            binding = json.loads(permit.stdout)
            raw = {"data": [{"instId": "BTC-USDT", "last": "100"}]}
            envelope = {"source_id": "fin_data_mcp_render_prod", "request_id": "req-1",
                        "schema_version": "1.0", "requested_at": "2026-09-29T11:59:00Z",
                        "received_at": "2026-09-29T11:59:01Z", "deployment_id": "dep-test",
                        "permit_id": binding["permit_id"], "capability_id": "fin.crypto.ticker",
                        "tool_name": "crypto_ticker", "protocol_method": "tools/call",
                        "endpoint_url": "https://fin-data-mcp-http-v02-prod.onrender.com/mcp",
                        "arguments_digest": digest(call_args), "isError": False,
                        "pagination_complete": True,
                        "http_status": 200, "content_type": "application/json",
                        "raw_response_digest": digest(raw), "result": raw}
            result_file.write_text(json.dumps(envelope), encoding="utf-8")
            recorded = self.run_gate("record", "--ledger", ledger, "--request-id", "req-1", "--result-file", result_file)
            self.assertEqual(0, recorded.returncode, recorded.stdout + recorded.stderr)
            self.assertEqual(0, self.run_gate("seal", "--ledger", ledger).returncode)
            self.assertEqual(0, self.run_gate("verify", "--ledger", ledger).returncode)
            saved = json.loads(ledger.read_text(encoding="utf-8"))
            saved["calls"][0]["outcome"] = "ERROR"
            ledger.write_text(json.dumps(saved), encoding="utf-8")
            self.assertNotEqual(0, self.run_gate("verify", "--ledger", ledger).returncode)

    def test_ledger_refuses_next_call_until_prior_result_is_recorded(self):
        with tempfile.TemporaryDirectory() as td:
            ledger = Path(td) / "ledger.json"
            arguments = Path(td) / "args.json"
            arguments.write_text("{}", encoding="utf-8")
            self.run_gate("init", "--attempt-id", "attempt-test", "--ledger", ledger)
            first = self.run_gate("permit", "--ledger", ledger, "--capability-id", "fin.crypto.ticker",
                                  "--tool-name", "crypto_ticker", "--request-id", "req-1", "--arguments-file", arguments)
            if authorization_error(load_policy()):
                self.assertEqual(4, first.returncode)
                self.assertIn("SOURCE_RUNTIME_AUTHORIZATION_BLOCKED", first.stdout)
                return
            self.assertEqual(0, first.returncode)
            second = self.run_gate("permit", "--ledger", ledger, "--capability-id", "fin.crypto.ticker",
                                   "--tool-name", "crypto_ticker", "--request-id", "req-2", "--arguments-file", arguments)
            self.assertEqual(4, second.returncode)

    def test_sealed_ledger_binds_use_authorization_policy_digest(self):
        with tempfile.TemporaryDirectory() as td:
            ledger = Path(td) / "ledger.json"
            self.assertEqual(0, self.run_gate("init", "--attempt-id", "attempt-rights", "--ledger", ledger).returncode)
            self.assertEqual(0, self.run_gate("seal", "--ledger", ledger).returncode)
            saved = json.loads(ledger.read_text(encoding="utf-8"))
            self.assertEqual(policy_digest(load_policy()), saved["provider_use_authorization_digest"])
            saved["provider_use_authorization_digest"] = "sha256:" + "0" * 64
            saved["content_digest"] = digest({key: value for key, value in saved.items() if key != "content_digest"})
            ledger.write_text(json.dumps(saved), encoding="utf-8")
            verified = self.run_gate("verify", "--ledger", ledger)
            self.assertEqual(1, verified.returncode)
            self.assertIn("LEDGER_PROVIDER_USE_AUTHORIZATION_IDENTITY_MISMATCH", verified.stdout)

    def test_authorized_admission_requires_exact_current_policy_in_report_and_ledger(self):
        policy = load_policy()
        policy["status"] = "AUTHORIZED"
        policy["authorization_decision"] = {
            "approved_by": "authorized-reviewer",
            "approved_at": "2026-09-30T04:00:00Z",
            "approved_scope": policy["scope"],
            "rights_document": "research/rights/okx-license.pdf",
            "rights_document_digest": "sha256:" + "1" * 64,
            "review_reference": "https://github.com/example/policy-review/pull/1",
            "reviewed_commit": "a" * 40,
            "independent_reviewer": "independent-reviewer",
        }
        current = policy_digest(policy)
        report = {"runtime_authorization": {"status": "AUTHORIZED", "policy_digest": current}}
        ledger = {"provider_use_authorization_digest": current}
        # Isolate the binding predicate from actual rights-document verification.
        with patch("fin_data_use_authorization.authorization_error", return_value=None):
            self.assertTrue(evidence_binding_authorized(policy, ledger, report))
        self.assertFalse(evidence_binding_authorized(policy, {}, report))
        self.assertFalse(evidence_binding_authorized(policy,
                                                    {"provider_use_authorization_digest": "sha256:" + "2" * 64},
                                                    report))
        self.assertFalse(evidence_binding_authorized(policy, ledger,
                                                    {"runtime_authorization": {
                                                        "status": "AUTHORIZED",
                                                        "policy_digest": "sha256:" + "3" * 64}}))
        missing_decision = dict(policy)
        missing_decision.pop("authorization_decision")
        self.assertFalse(evidence_binding_authorized(
            missing_decision, ledger,
            {"runtime_authorization": {"status": "AUTHORIZED", "policy_digest": policy_digest(missing_decision)}}))

    def test_authorization_rejects_missing_or_unbound_rights_document(self):
        policy = load_policy()
        policy["status"] = "AUTHORIZED"
        policy["authorization_decision"] = {
            "approved_by": "approver", "approved_at": "2026-09-30T04:00:00Z",
            "approved_scope": policy["scope"], "rights_document": "research/rights/no-such-license.pdf",
            "rights_document_digest": "sha256:" + "1" * 64,
            "review_reference": "https://github.com/example/policy-review/pull/1",
            "reviewed_commit": "a" * 40, "independent_reviewer": "reviewer",
        }
        self.assertEqual("provider_use_authorization_rights_document_missing", authorization_error(policy))
        policy["authorization_decision"]["rights_document"] = "config/fin-data-use-authorization.json"
        self.assertEqual("provider_use_authorization_rights_digest_mismatch", authorization_error(policy))
        policy["authorization_decision"]["approved_by"] = "reviewer"
        self.assertEqual("provider_use_authorization_reviewer_not_independent", authorization_error(policy))

    def test_authorized_fixture_exercises_positive_permit_record_and_seal_path(self):
        policy = load_policy()
        policy["status"] = "AUTHORIZED"
        policy["authorization_decision"] = {
            "approved_by": "authorized-reviewer",
            "approved_at": "2026-09-30T04:00:00Z",
            "approved_scope": policy["scope"],
            "rights_document": "research/rights/okx-license.pdf",
            "rights_document_digest": "sha256:" + "1" * 64,
            "review_reference": "https://github.com/example/policy-review/pull/1",
            "reviewed_commit": "a" * 40,
            "independent_reviewer": "independent-reviewer",
        }
        with tempfile.TemporaryDirectory() as td:
            ledger_path = Path(td) / "ledger.json"
            arguments_path = Path(td) / "arguments.json"
            result_path = Path(td) / "result.json"
            wire_arguments = {"name": "crypto_ticker", "arguments": {"instId": "BTC-USDT"}}
            arguments_path.write_text(json.dumps(wire_arguments), encoding="utf-8")
            rc, _ = self.run_gate_with_authorization_fixture(
                policy, "init", "--attempt-id", "authorized-fixture", "--ledger", ledger_path)
            self.assertEqual(0, rc)
            rc, permit_output = self.run_gate_with_authorization_fixture(
                policy, "permit", "--ledger", ledger_path, "--capability-id", "fin.crypto.ticker",
                "--tool-name", "crypto_ticker", "--request-id", "req-authorized",
                "--arguments-file", arguments_path)
            self.assertEqual(0, rc, permit_output)
            permit = json.loads(permit_output)
            raw = {"data": [{"instId": "BTC-USDT", "last": "100"}]}
            result = {"source_id": "fin_data_mcp_render_prod", "request_id": "req-authorized",
                      "schema_version": "1.0", "requested_at": "2026-09-30T04:00:00Z",
                      "received_at": "2026-09-30T04:00:01Z", "deployment_id": "dep-fixture",
                      "permit_id": permit["permit_id"], "capability_id": "fin.crypto.ticker",
                      "tool_name": "crypto_ticker", "protocol_method": "tools/call",
                      "endpoint_url": "https://fin-data-mcp-http-v02-prod.onrender.com/mcp",
                      "arguments_digest": digest(wire_arguments), "isError": False,
                      "pagination_complete": True, "http_status": 200,
                      "content_type": "application/json", "raw_response_digest": digest(raw), "result": raw}
            result_path.write_text(json.dumps(result), encoding="utf-8")
            rc, _ = self.run_gate_with_authorization_fixture(
                policy, "record", "--ledger", ledger_path, "--request-id", "req-authorized",
                "--result-file", result_path)
            self.assertEqual(0, rc)
            rc, _ = self.run_gate_with_authorization_fixture(policy, "seal", "--ledger", ledger_path)
            self.assertEqual(0, rc)
            rc, _ = self.run_gate_with_authorization_fixture(policy, "verify", "--ledger", ledger_path)
            self.assertEqual(0, rc)

    def test_mcp_initialization_and_catalog_have_governed_operation_identities(self):
        for capability_id, tool_name in (("fin.mcp.initialize", "initialize"),
                                         ("fin.mcp.tools_list", "tools/list")):
            with self.subTest(operation=tool_name), tempfile.TemporaryDirectory() as td:
                ledger = Path(td) / "ledger.json"
                arguments = Path(td) / "args.json"
                arguments.write_text("{}", encoding="utf-8")
                self.run_gate("init", "--attempt-id", "attempt-control", "--ledger", ledger)
                permit = self.run_gate("permit", "--ledger", ledger, "--capability-id", capability_id,
                                       "--tool-name", tool_name, "--request-id", "req-control",
                                       "--arguments-file", arguments)
                if authorization_error(load_policy()):
                    self.assertEqual(4, permit.returncode)
                    self.assertIn("SOURCE_RUNTIME_AUTHORIZATION_BLOCKED", permit.stdout)
                else:
                    self.assertEqual(0, permit.returncode, permit.stdout + permit.stderr)

    def test_diagnostic_read_operation_requires_bound_policy_and_tool_arguments(self):
        with tempfile.TemporaryDirectory() as td:
            ledger = Path(td) / "ledger.json"
            arguments = Path(td) / "args.json"
            init = self.run_gate("init", "--attempt-id", "attempt-diagnostic", "--ledger", ledger)
            self.assertEqual(0, init.returncode)
            arguments.write_text(json.dumps({"name": "crypto_all_tickers",
                                             "arguments": {"instType": "INVALID"}}), encoding="utf-8")
            invalid = self.run_gate("permit", "--ledger", ledger,
                                    "--capability-id", "fin.mcp.diagnostic.crypto_all_tickers",
                                    "--tool-name", "crypto_all_tickers", "--request-id", "req-invalid",
                                    "--arguments-file", arguments)
            self.assertEqual(4, invalid.returncode)
            if authorization_error(load_policy()):
                self.assertIn("SOURCE_RUNTIME_AUTHORIZATION_BLOCKED", invalid.stdout)
                return
            self.assertIn("DIAGNOSTIC_ARGUMENTS_INVALID", invalid.stdout)
            arguments.write_text(json.dumps({"name": "crypto_all_tickers",
                                             "arguments": {"instType": "SWAP"}}), encoding="utf-8")
            valid = self.run_gate("permit", "--ledger", ledger,
                                  "--capability-id", "fin.mcp.diagnostic.crypto_all_tickers",
                                  "--tool-name", "crypto_all_tickers", "--request-id", "req-valid",
                                  "--arguments-file", arguments)
            self.assertEqual(0, valid.returncode, valid.stdout + valid.stderr)


if __name__ == "__main__":
    unittest.main()

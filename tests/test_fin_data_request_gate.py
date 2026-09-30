from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts/control_plane"))
from common import digest  # noqa: E402


class FinDataRequestGateTests(unittest.TestCase):
    def run_gate(self, *args):
        return subprocess.run([sys.executable, str(ROOT / "scripts/control_plane/fin_data_request_gate.py"),
                               *map(str, args)], cwd=ROOT, capture_output=True, text=True)

    def test_permit_binding_seal_and_tamper_detection(self):
        with tempfile.TemporaryDirectory() as td:
            ledger = Path(td) / "ledger.json"
            arguments = Path(td) / "args.json"
            result_file = Path(td) / "result.json"
            call_args = {"name": "crypto_ticker", "arguments": {"instId": "BTC-USDT"}}
            arguments.write_text(json.dumps(call_args), encoding="utf-8")
            self.assertEqual(0, self.run_gate("init", "--attempt-id", "attempt-test", "--ledger", ledger).returncode)
            permit = self.run_gate("permit", "--ledger", ledger, "--capability-id", "fin.crypto.ticker",
                                   "--tool-name", "crypto_ticker", "--request-id", "req-1",
                                   "--arguments-file", arguments)
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
            self.assertEqual(0, first.returncode)
            second = self.run_gate("permit", "--ledger", ledger, "--capability-id", "fin.crypto.ticker",
                                   "--tool-name", "crypto_ticker", "--request-id", "req-2", "--arguments-file", arguments)
            self.assertEqual(4, second.returncode)

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

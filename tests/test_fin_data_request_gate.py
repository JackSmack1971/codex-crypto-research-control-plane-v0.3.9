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
            arguments.write_text('{"instId":"BTC-USDT"}', encoding="utf-8")
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
                        "tool_name": "crypto_ticker", "endpoint_url": "https://fin-data-mcp-http-v02-prod.onrender.com/mcp",
                        "arguments_digest": digest({"instId": "BTC-USDT"}), "isError": False,
                        "pagination_complete": True,
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


if __name__ == "__main__":
    unittest.main()

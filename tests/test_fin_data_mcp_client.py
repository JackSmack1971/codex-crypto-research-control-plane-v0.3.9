from __future__ import annotations

import sys
import tempfile
import unittest
import json
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts/control_plane"))
from fin_data_mcp_client import (_complete_payload, _rate_limit_signal, _wire_authorization_error,
                                 invoke)  # noqa: E402


class FinDataMcpClientTests(unittest.TestCase):
    def test_partial_or_cursor_truncated_payload_is_not_complete(self):
        self.assertFalse(_complete_payload({"content": [{"type": "text", "text": "[{\"id\":"}]}))
        self.assertFalse(_complete_payload({"nextCursor": "next-page"}))
        self.assertTrue(_complete_payload({"content": [{"type": "text", "text": "[{\"id\":1}]"}]}))

    def test_rate_limit_signal_detects_http_and_mcp_error_payloads(self):
        self.assertTrue(_rate_limit_signal(429, {}))
        self.assertTrue(_rate_limit_signal(200, {"code": -32000, "message": "RATE_LIMIT exceeded"}))
        self.assertTrue(_rate_limit_signal(200, {"message": "Too many requests"}))
        self.assertFalse(_rate_limit_signal(200, {"message": "invalid instrument"}))

    def test_diagnostic_tool_is_explicit_read_only_and_schema_bounded(self):
        capability = "fin.mcp.diagnostic.crypto_all_tickers"
        self.assertIsNone(_wire_authorization_error(
            capability, "crypto_all_tickers", "tools/call",
            {"name": "crypto_all_tickers", "arguments": {"instType": "SWAP"}}))
        self.assertEqual("diagnostic_operation_identity_mismatch", _wire_authorization_error(
            capability, "crypto_list_instruments", "tools/call",
            {"name": "crypto_list_instruments", "arguments": {"instType": "SWAP"}}))
        self.assertEqual("diagnostic_tool_arguments_invalid", _wire_authorization_error(
            capability, "crypto_all_tickers", "tools/call",
            {"name": "crypto_all_tickers", "arguments": {"instType": "OPTION"}}))

    def test_client_rejects_nonproduction_endpoint_before_permit_or_network(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            outcome = invoke("https://fin-data-mcp-http-v2.onrender.com/mcp", "dep-wrong",
                             root / "ledger.json", "fin.mcp.initialize", "initialize",
                             "initialize", {}, root / "result.json")
            self.assertEqual("configured_endpoint_identity_mismatch", outcome["transport_error"])
            self.assertFalse((root / "ledger.json").exists())
            self.assertFalse((root / "result.json").exists())

    def test_client_rejects_unbound_method_and_tool_before_permit_or_network(self):
        endpoint = "https://fin-data-mcp-http-v02-prod.onrender.com/mcp"
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            wrong_method = invoke(endpoint, "dep-prod", root / "ledger.json", "fin.crypto.ticker",
                                  "crypto_ticker", "initialize", {}, root / "method.json")
            wrong_tool = invoke(endpoint, "dep-prod", root / "ledger.json", "fin.crypto.ticker",
                                "crypto_ticker", "tools/call",
                                {"name": "write_orders", "arguments": {}}, root / "tool.json")
            self.assertEqual("runtime_authorization_denied:protocol_method_not_authorized_for_capability",
                             wrong_method["transport_error"])
            self.assertEqual("runtime_authorization_denied:wire_tool_name_mismatch",
                             wrong_tool["transport_error"])
            self.assertFalse((root / "ledger.json").exists())
            self.assertFalse((root / "method.json").exists())
            self.assertFalse((root / "tool.json").exists())

    def test_successful_client_envelope_records_method_and_http_metadata(self):
        endpoint = "https://fin-data-mcp-http-v02-prod.onrender.com/mcp"
        captured = {}

        class Response:
            status = 200
            headers = {"Content-Type": "application/json"}

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self):
                request = json.loads(request_body[0])
                return json.dumps({"jsonrpc": "2.0", "id": request["id"],
                                   "result": {"isError": False, "structuredContent": {"rows": []}}}).encode()

        def fake_urlopen(request, timeout):
            request_body.append(request.data)
            return Response()

        request_body = []
        with tempfile.TemporaryDirectory() as td, \
                patch("fin_data_mcp_client._permit", return_value={"permit_id": "permit-test"}), \
                patch("fin_data_mcp_client._record", side_effect=lambda _ledger, _id, _file, value:
                      captured.update(value) or "RECORDED:SUCCESS"), \
                patch("fin_data_mcp_client.urllib.request.urlopen", side_effect=fake_urlopen):
            root = Path(td)
            outcome = invoke(endpoint, "dep-prod", root / "ledger.json", "fin.crypto.ticker",
                             "crypto_ticker", "tools/call",
                             {"name": "crypto_ticker", "arguments": {"instId": "BTC-USDT"}},
                             root / "result.json")
        self.assertEqual(200, outcome["http_status"])
        self.assertEqual("tools/call", captured["protocol_method"])
        self.assertEqual(200, captured["http_status"])
        self.assertEqual("application/json", captured["content_type"])


if __name__ == "__main__":
    unittest.main()

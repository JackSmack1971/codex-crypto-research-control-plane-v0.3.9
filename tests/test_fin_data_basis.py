from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts/control_plane"))
from common import digest  # noqa: E402
from derive_fin_data_basis import _bar_map, derive  # noqa: E402
from validate_artifact import validate  # noqa: E402


class FinDataBasisDerivationTests(unittest.TestCase):
    def setUp(self):
        self.capture = ROOT / "research/sources/fin-data-basis-1m-probe-2026-09-30"
        self.spot = json.loads((self.capture / "candles-spot.result.json").read_text(encoding="utf-8"))
        self.perpetual = json.loads((self.capture / "candles-swap.result.json").read_text(encoding="utf-8"))
        self.index = json.loads((self.capture / "index-candles.result.json").read_text(encoding="utf-8"))
        self.ledger = json.loads((self.capture / "request-ledger.json").read_text(encoding="utf-8"))

    def test_latest_jointly_confirmed_bar_derives_same_quote_basis_and_preserves_index_unit_gap(self):
        result = derive(self.spot, self.perpetual, self.index, self.ledger, "2026-10-01T00:00:00Z")
        schema = json.loads((ROOT / "schemas/fin_data_basis_observation.schema.json").read_text(encoding="utf-8"))
        self.assertEqual([], validate(result, schema))
        self.assertEqual("2026-09-30T03:30:00Z", result["bar_timestamp"])
        self.assertTrue(result["confirm"])
        self.assertEqual("-43.7", result["spot_perpetual_basis"]["absolute"])
        self.assertEqual("-5.246502", result["spot_perpetual_basis"]["basis_points_of_spot"])
        self.assertEqual("NOT_COMPARABLE_WITH_USDT_QUOTES_WITHOUT_FX_CONVERSION",
                         result["index_comparability"])
        self.assertEqual(76, result["age_seconds_since_provider_bar_timestamp_at_retrieval"])
        self.assertEqual("NOT_ADMITTED", result["admissibility"])
        self.assertEqual(result, derive(self.spot, self.perpetual, self.index, self.ledger,
                                        "2026-10-01T00:00:00Z"))

    def test_no_jointly_confirmed_bar_fails_closed(self):
        spot = copy.deepcopy(self.spot)
        rows = spot["result"]["structuredContent"]["data"]
        for row in rows:
            row[8] = "0"
        spot["raw_response_digest"] = digest(spot["result"])
        ledger = copy.deepcopy(self.ledger)
        call = next(item for item in ledger["calls"] if item["request_id"] == spot["request_id"])
        call["result_digest"] = digest(spot)
        ledger["content_digest"] = digest({key: value for key, value in ledger.items() if key != "content_digest"})
        with self.assertRaisesRegex(ValueError, "no_jointly_confirmed_basis_bar"):
            derive(spot, self.perpetual, self.index, ledger, "2026-10-01T00:00:00Z")

    def test_input_envelope_tampering_fails_ledger_binding(self):
        spot = copy.deepcopy(self.spot)
        spot["result"]["structuredContent"]["data"][0][4] = "1"
        with self.assertRaisesRegex(ValueError, "basis_input_ledger_binding_invalid"):
            derive(spot, self.perpetual, self.index, self.ledger, "2026-10-01T00:00:00Z")

    def test_bar_end_must_be_strictly_before_cutoff(self):
        for cutoff in ("2026-09-30T03:30:59.999Z", "2026-09-30T03:31:00Z"):
            with self.subTest(cutoff=cutoff), self.assertRaisesRegex(
                    ValueError, "basis_bar_end_at_or_after_cutoff"):
                derive(self.spot, self.perpetual, self.index, self.ledger, cutoff)

    def test_retrieval_at_or_after_cutoff_is_rejected(self):
        spot = copy.deepcopy(self.spot)
        spot["received_at"] = "2026-09-30T03:32:00Z"
        ledger = copy.deepcopy(self.ledger)
        ledger_call = next(item for item in ledger["calls"] if item["request_id"] == spot["request_id"])
        ledger_call["result_digest"] = digest(spot)
        ledger["content_digest"] = digest({key: value for key, value in ledger.items() if key != "content_digest"})
        with self.assertRaisesRegex(ValueError, "basis_retrieval_at_or_after_cutoff"):
            derive(spot, self.perpetual, self.index, ledger, "2026-09-30T03:32:00Z")

    def test_non_minute_aligned_bar_timestamp_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "basis_input_timestamp_not_minute_aligned"):
            _bar_map([["1790739030000", "1", "1", "1", "1", "1", "1", "1", "1"]], 9, 8)


if __name__ == "__main__":
    unittest.main()

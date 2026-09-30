from __future__ import annotations

"""Derive a diagnostic same-quote spot/perpetual spread from sealed Fin Data MCP bars."""

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "control_plane"))
from common import digest, parse_timestamp, write_new_json  # noqa: E402


def _read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("expected_json_object")
    return value


def _rows(envelope: dict[str, Any]) -> list[list[Any]]:
    if envelope.get("isError") is not False or envelope.get("pagination_complete") is not True:
        raise ValueError("basis_input_failed_or_incomplete")
    if envelope.get("protocol_method") != "tools/call" or envelope.get("tool_name") not in {
        "crypto_candles", "crypto_index_candles"
    }:
        raise ValueError("basis_input_operation_identity_invalid")
    result = envelope.get("result", {})
    structured = result.get("structuredContent", {}) if isinstance(result, dict) else {}
    values = structured.get("data") if isinstance(structured, dict) else None
    if not isinstance(values, list) or not values:
        raise ValueError("basis_input_rows_missing")
    if any(not isinstance(row, list) for row in values):
        raise ValueError("basis_input_row_shape_invalid")
    return values


def _bar_map(rows: list[list[Any]], expected_length: int, confirm_index: int) -> dict[int, list[Any]]:
    output: dict[int, list[Any]] = {}
    for row in rows:
        if len(row) != expected_length:
            raise ValueError("basis_input_schema_drift")
        try:
            timestamp = int(row[0])
        except (ValueError, TypeError) as exc:
            raise ValueError("basis_input_timestamp_invalid") from exc
        if timestamp in output:
            raise ValueError("basis_input_duplicate_bar")
        output[timestamp] = row
        if str(row[confirm_index]) not in {"0", "1"}:
            raise ValueError("basis_input_confirmation_invalid")
    return output


def _close(row: list[Any], index: int) -> Decimal:
    try:
        value = Decimal(str(row[index]))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError("basis_input_close_invalid") from exc
    if not value.is_finite() or value <= 0:
        raise ValueError("basis_input_close_invalid")
    return value


def _call_for(ledger: dict[str, Any], envelope: dict[str, Any], capability_id: str,
             tool_name: str) -> dict[str, Any]:
    endpoint = _read(ROOT / "config/source-capabilities/fin-data.json")["runtime"]
    call = next((item for item in ledger.get("calls", [])
                 if item.get("request_id") == envelope.get("request_id")), None)
    if (not call or call.get("result_digest") != digest(envelope)
            or call.get("permit_id") != envelope.get("permit_id")
            or call.get("tool_name") != envelope.get("tool_name")
            or call.get("capability_id") != envelope.get("capability_id")
            or envelope.get("source_id") != ledger.get("source_id")
            or envelope.get("endpoint_url") != endpoint
            or call.get("arguments_digest") != envelope.get("arguments_digest")):
        raise ValueError("basis_input_ledger_binding_invalid")
    if envelope.get("capability_id") != capability_id or envelope.get("tool_name") != tool_name:
        raise ValueError("basis_input_capability_identity_mismatch")
    arguments = call.get("arguments", {})
    if (not isinstance(arguments, dict) or arguments.get("name") != envelope.get("tool_name")
            or arguments.get("arguments", {}).get("bar") != "1m"):
        raise ValueError("basis_input_parameters_unregistered")
    return arguments.get("arguments", {})


def derive(spot: dict[str, Any], perpetual: dict[str, Any], index: dict[str, Any],
           ledger: dict[str, Any], cutoff: str) -> dict[str, Any]:
    """Select the latest jointly confirmed 1m bar and derive a same-quote spread."""
    policy = _read(ROOT / "config/fin-data-request-policy.json")
    if (ledger.get("source_id") != "fin_data_mcp_render_prod" or ledger.get("status") != "SEALED"
            or ledger.get("tainted") or ledger.get("policy_digest") != digest(policy)
            or ledger.get("content_digest") != digest({k: v for k, v in ledger.items() if k != "content_digest"})):
        raise ValueError("basis_request_ledger_invalid")
    spot_args = _call_for(ledger, spot, "fin.crypto.candles", "crypto_candles")
    perpetual_args = _call_for(ledger, perpetual, "fin.crypto.candles", "crypto_candles")
    index_args = _call_for(ledger, index, "fin.crypto.index_candles", "crypto_index_candles")
    if (spot_args.get("instId") != "BTC-USDT" or perpetual_args.get("instId") != "BTC-USDT-SWAP"
            or index_args.get("instId") != "BTC-USD"):
        raise ValueError("basis_instrument_identity_mismatch")
    spot_bars = _bar_map(_rows(spot), 9, 8)
    perpetual_bars = _bar_map(_rows(perpetual), 9, 8)
    index_bars = _bar_map(_rows(index), 6, 5)
    common = set(spot_bars) & set(perpetual_bars) & set(index_bars)
    closed = [ts for ts in common if str(spot_bars[ts][8]) == "1"
              and str(perpetual_bars[ts][8]) == "1" and str(index_bars[ts][5]) == "1"]
    if not closed:
        raise ValueError("no_jointly_confirmed_basis_bar")
    timestamp = max(closed)
    spot_close = _close(spot_bars[timestamp], 4)
    perpetual_close = _close(perpetual_bars[timestamp], 4)
    index_close = _close(index_bars[timestamp], 4)
    spread = perpetual_close - spot_close
    bps = (spread / spot_close * Decimal(10000)).quantize(Decimal("0.000001"))
    bar_start_utc = datetime.fromtimestamp(timestamp / 1000, timezone.utc)
    cutoff_time = parse_timestamp(cutoff, "research_cutoff")
    if bar_start_utc >= cutoff_time:
        raise ValueError("basis_bar_at_or_after_cutoff")
    receive_times = [parse_timestamp(envelope["received_at"], "received_at")
                     for envelope in (spot, perpetual, index)]
    received_at = max(receive_times)
    age = int((received_at - bar_start_utc).total_seconds())
    if age < 0:
        raise ValueError("basis_bar_end_after_retrieval")
    bar_end_utc = bar_start_utc.replace(second=0, microsecond=0) + timedelta(minutes=1)
    if bar_end_utc >= cutoff_time:
        raise ValueError("basis_bar_end_at_or_after_cutoff")
    if any(received >= cutoff_time for received in receive_times):
        raise ValueError("basis_retrieval_at_or_after_cutoff")
    return {
        "schema_version": "1.0",
        "status": "DIAGNOSTIC",
        "evidence_role": "DIAGNOSTIC",
        "source_id": "fin_data_mcp_render_prod",
        "attempt_id": ledger["attempt_id"],
        "ledger_digest": ledger["content_digest"],
        "bar_interval": "1m",
        "bar_timestamp": bar_start_utc.isoformat().replace("+00:00", "Z"),
        "provider_timestamp_semantics": "BAR_START_INFERRED_FROM_SEQUENCE",
        "confirm": True,
        "received_at": received_at.isoformat().replace("+00:00", "Z"),
        "age_seconds_since_provider_bar_timestamp_at_retrieval": age,
        "instruments": {
            "spot": {"instrument_id": spot_args["instId"], "quote_currency": "USDT",
                     "close": format(spot_close, "f"), "raw_response_digest": digest(spot.get("result")),
                     "response_envelope_digest": digest(spot)},
            "perpetual": {"instrument_id": perpetual_args["instId"], "quote_currency": "USDT",
                           "close": format(perpetual_close, "f"),
                           "raw_response_digest": digest(perpetual.get("result")),
                           "response_envelope_digest": digest(perpetual)},
            "index": {"instrument_id": index_args["instId"], "quote_currency": "USD",
                      "close": format(index_close, "f"), "raw_response_digest": digest(index.get("result")),
                      "response_envelope_digest": digest(index)},
        },
        "spot_perpetual_basis": {
            "definition": "perpetual_close_minus_spot_close",
            "quote_currency": "USDT",
            "absolute": format(spread, "f"),
            "basis_points_of_spot": format(bps, "f"),
        },
        "index_comparability": "NOT_COMPARABLE_WITH_USDT_QUOTES_WITHOUT_FX_CONVERSION",
        "admissibility": "NOT_ADMITTED",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spot", required=True)
    parser.add_argument("--perpetual", required=True)
    parser.add_argument("--index", required=True)
    parser.add_argument("--ledger", required=True)
    parser.add_argument("--cutoff", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    try:
        value = derive(_read(Path(args.spot)), _read(Path(args.perpetual)), _read(Path(args.index)),
                       _read(Path(args.ledger)), args.cutoff)
        schema = _read(ROOT / "schemas/fin_data_basis_observation.schema.json")
        from validate_artifact import validate as validate_schema
        errors = validate_schema(value, schema)
        if errors:
            raise ValueError("basis_observation_schema:" + ";".join(errors))
        write_new_json(args.out, value)
        print("DIAGNOSTIC:" + args.out)
        return 0
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        print(f"FIN_DATA_BASIS_ERROR:{exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

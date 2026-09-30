from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "control_plane"))
from common import digest  # noqa: E402
from validate_artifact import validate as validate_schema  # noqa: E402


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("expected_json_object")
    return value


def _write(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def main() -> int:
    parser = argparse.ArgumentParser(description="Attempt-scoped Fin Data MCP call permit/result ledger")
    sub = parser.add_subparsers(dest="command", required=True)
    init = sub.add_parser("init"); init.add_argument("--attempt-id", required=True); init.add_argument("--ledger", required=True)
    permit = sub.add_parser("permit"); permit.add_argument("--ledger", required=True); permit.add_argument("--capability-id", required=True); permit.add_argument("--tool-name", required=True); permit.add_argument("--request-id", required=True); permit.add_argument("--arguments-file", required=True)
    record = sub.add_parser("record"); record.add_argument("--ledger", required=True); record.add_argument("--request-id", required=True); record.add_argument("--result-file", required=True)
    seal = sub.add_parser("seal"); seal.add_argument("--ledger", required=True)
    verify = sub.add_parser("verify"); verify.add_argument("--ledger", required=True)
    args = parser.parse_args()
    try:
        path = Path(args.ledger)
        if args.command == "init":
            if path.exists():
                print("IMMUTABLE_CONFLICT:" + str(path)); return 3
            policy = _read(ROOT / "config/fin-data-request-policy.json")
            _write(path, {"schema_version": "1.0", "source_id": "fin_data_mcp_render_prod",
                          "attempt_id": args.attempt_id, "created_at": _now(), "policy_digest": digest(policy),
                          "status": "OPEN", "tainted": False, "calls": []})
            print("LEDGER_READY:" + str(path)); return 0
        ledger = _read(path)
        if args.command == "verify":
            policy = _read(ROOT / "config/fin-data-request-policy.json")
            if ledger.get("policy_digest") != digest(policy):
                print("LEDGER_POLICY_IDENTITY_MISMATCH"); return 1
            expected = ledger.get("content_digest")
            actual = digest({key: value for key, value in ledger.items() if key != "content_digest"})
            if ledger.get("status") != "SEALED" or expected != actual:
                print("LEDGER_INVALID_OR_UNSEALED"); return 1
            if ledger.get("tainted") or any(call.get("completed_at") is None for call in ledger.get("calls", [])):
                print("LEDGER_INCOMPLETE_OR_TAINTED"); return 1
            print("PASS:" + str(path)); return 0
        if args.command == "seal":
            if ledger.get("status") != "OPEN" or ledger.get("tainted"):
                print("LEDGER_CANNOT_SEAL"); return 4
            if any(call.get("completed_at") is None for call in ledger.get("calls", [])):
                print("LEDGER_PENDING_RESULT"); return 4
            ledger["status"] = "SEALED"; ledger["sealed_at"] = _now()
            ledger["content_digest"] = digest({key: value for key, value in ledger.items() if key != "content_digest"})
            _write(path, ledger)
            print("SEALED:" + str(path)); return 0
        if ledger.get("status") != "OPEN" or ledger.get("tainted"):
            print("LEDGER_HALTED_OR_CLOSED"); return 4
        if args.command == "permit":
            caps = _read(ROOT / "config/source-capabilities/fin-data.json")["capabilities"]
            allowed = next((item for item in caps if item["capability_id"] == args.capability_id), None)
            if allowed is None or allowed["tool_name"] != args.tool_name:
                print("REQUEST_NOT_REGISTERED"); return 4
            if not args.request_id or any(item["request_id"] == args.request_id for item in ledger["calls"]):
                print("REQUEST_ID_INVALID_OR_DUPLICATE"); return 4
            if any(item.get("completed_at") is None for item in ledger["calls"]):
                print("PREVIOUS_RESULT_NOT_RECORDED"); return 4
            arguments = json.loads(Path(args.arguments_file).read_text(encoding="utf-8"))
            if not isinstance(arguments, dict):
                print("REQUEST_ARGUMENTS_NOT_OBJECT"); return 4
            runtime = _read(ROOT / "config/source-capabilities/fin-data.json")["runtime"]
            call = {"request_id": args.request_id, "permit_id": "fdp-" + uuid.uuid4().hex,
                    "capability_id": args.capability_id, "tool_name": args.tool_name,
                    "endpoint_url": runtime, "arguments": arguments, "arguments_digest": digest(arguments),
                    "permitted_at": _now(), "completed_at": None, "outcome": None, "result_digest": None}
            ledger["calls"].append(call); _write(path, ledger)
            print(json.dumps({"permit_id": call["permit_id"], "request_id": args.request_id,
                              "tool_name": args.tool_name, "call_index": len(ledger["calls"]) - 1}, sort_keys=True))
            return 0
        match = next((item for item in ledger["calls"] if item["request_id"] == args.request_id), None)
        if match is None or match.get("completed_at") is not None:
            print("PERMITTED_REQUEST_NOT_FOUND_OR_ALREADY_RECORDED"); return 4
        result = _read(Path(args.result_file))
        result_schema = _read(ROOT / "schemas/fin_data_result.schema.json")
        schema_errors = validate_schema(result, result_schema)
        if schema_errors:
            print("RESULT_SCHEMA_INVALID:" + ";".join(schema_errors)); return 4
        for key, expected in (("source_id", ledger["source_id"]), ("request_id", match["request_id"]),
                              ("permit_id", match["permit_id"]), ("capability_id", match["capability_id"]),
                              ("tool_name", match["tool_name"]), ("endpoint_url", match["endpoint_url"]),
                              ("arguments_digest", match["arguments_digest"])):
            if result.get(key) != expected:
                print(f"RESULT_BINDING_MISMATCH:{key}"); return 4
        if result.get("raw_response_digest") != digest(result.get("result")):
            print("RESULT_RAW_DIGEST_MISMATCH"); return 4
        match["completed_at"] = _now(); match["outcome"] = "ERROR" if result.get("isError") else "SUCCESS"
        match["result_digest"] = digest(result)
        warning = str(result.get("warning", "")).upper()
        if "RATE_LIMIT" in warning or result.get("error_code") == "RATE_LIMIT":
            match["outcome"] = "RATE_LIMIT"; ledger["tainted"] = True; ledger["status"] = "HALTED_RATE_LIMIT"
        _write(path, ledger)
        print(f"RECORDED:{match['outcome']}:{args.request_id}")
        return 0
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        print(f"FIN_DATA_GATE_ERROR:{exc}"); return 2


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

"""Deterministic qualification and materialization for Fin Data MCP snapshots.

Provider access is performed by the configured MCP client. This module accepts
captured MCP observations and never makes a network/API call itself.
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "control_plane"))
from common import digest, parse_timestamp, write_new_json  # noqa: E402
from source_evidence import expected_manifest_id, validate_source_manifest  # noqa: E402


def _read(path: str | Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("expected_json_object")
    return value


def _rows(value: Any) -> list[dict[str, Any]]:
    """Extract JSON object rows from the normalized MCP structured result."""
    if isinstance(value, dict):
        if isinstance(value.get("rows"), list):
            return [row for row in value["rows"] if isinstance(row, dict)]
        if isinstance(value.get("data"), list):
            return [row for row in value["data"] if isinstance(row, dict)]
        if isinstance(value.get("data"), dict):
            return [value["data"]]
        return [value]
    if isinstance(value, list):
        return [row for row in value if isinstance(row, dict)]
    return []


def _health(severity: str, status: str, reason: str | None = None) -> dict[str, Any]:
    return {"severity": severity, "status": status, "reason": reason}


def _verify_ledger(ledger: dict[str, Any]) -> list[str]:
    policy = _read(ROOT / "config/fin-data-request-policy.json")
    expected = ledger.get("content_digest")
    actual = digest({key: value for key, value in ledger.items() if key != "content_digest"})
    errors = []
    if ledger.get("source_id") != "fin_data_mcp_render_prod":
        errors.append("ledger_source_identity_mismatch")
    if ledger.get("policy_digest") != digest(policy):
        errors.append("ledger_policy_digest_mismatch")
    if ledger.get("status") != "SEALED" or expected != actual:
        errors.append("ledger_unsealed_or_digest_invalid")
    if ledger.get("tainted") or any(call.get("completed_at") is None for call in ledger.get("calls", [])):
        errors.append("ledger_incomplete_or_tainted")
    return errors


def _bind_snapshot_to_ledger(snapshot: dict[str, Any], ledger: dict[str, Any]) -> list[str]:
    errors = _verify_ledger(ledger)
    calls = {item.get("request_id"): item for item in ledger.get("calls", [])}
    contracts = {item["capability_id"]: item for item in _read(ROOT / "config/fin-data-response-contracts.json")["contracts"]}
    for operation_id, operation_name, key in (
        ("fin.mcp.initialize", "initialize", "initialization_envelope"),
        ("fin.mcp.tools_list", "tools/list", "catalog_envelope"),
    ):
        envelope = snapshot.get(key)
        if not isinstance(envelope, dict):
            errors.append(f"mcp_control_operation_missing:{operation_id}")
            continue
        call = calls.get(envelope.get("request_id"))
        if (not call or call.get("capability_id") != operation_id or call.get("tool_name") != operation_name
                or call.get("result_digest") != digest(envelope)
                or call.get("permit_id") != envelope.get("permit_id")
                or call.get("endpoint_url") != envelope.get("endpoint_url")
                or call.get("arguments_digest") != envelope.get("arguments_digest")
                or envelope.get("source_id") != ledger.get("source_id")
                or envelope.get("endpoint_url") != snapshot.get("endpoint_url")
                or envelope.get("deployment_id") != snapshot.get("deployment_id")):
            errors.append(f"mcp_control_operation_ledger_binding_invalid:{operation_id}")
            continue
        if envelope.get("isError") is not False:
            errors.append(f"mcp_control_operation_failed:{operation_id}")
        elif operation_id == "fin.mcp.initialize":
            snapshot["initialization"] = "SUCCEEDED"
            snapshot["reachability"] = "SUCCEEDED"
        else:
            payload = envelope.get("result")
            tools = payload.get("tools") if isinstance(payload, dict) else None
            if not isinstance(tools, list) or any(not isinstance(item, dict) or not isinstance(item.get("name"), str)
                                                  for item in tools):
                errors.append("mcp_tools_list_response_malformed")
            else:
                snapshot["tools"] = [item["name"] for item in tools]
    for capability in _read(ROOT / "config/source-capabilities/fin-data.json")["capabilities"]:
        cid = capability["capability_id"]
        result = snapshot.get("representative_results", {}).get(cid)
        if not isinstance(result, dict):
            continue
        envelope = result.get("request_envelope")
        if not isinstance(envelope, dict):
            errors.append(f"representative_result_missing_ledger_envelope:{cid}")
            continue
        call = calls.get(envelope.get("request_id"))
        if not call or call.get("capability_id") != cid or call.get("tool_name") != capability["tool_name"]:
            errors.append(f"representative_call_not_in_ledger:{cid}")
            continue
        if call.get("result_digest") != digest(envelope):
            errors.append(f"representative_envelope_digest_mismatch:{cid}")
            continue
        if (envelope.get("source_id") != ledger.get("source_id")
                or envelope.get("endpoint_url") != snapshot.get("endpoint_url")
                or envelope.get("permit_id") != call.get("permit_id")
                or envelope.get("arguments_digest") != call.get("arguments_digest")
                or envelope.get("deployment_id") != snapshot.get("deployment_id")):
            errors.append(f"representative_envelope_binding_mismatch:{cid}")
            continue
        observed_at = envelope.get("received_at")
        contract = contracts.get(cid, {})
        effective_field = contract.get("effective_time_field")
        if effective_field:
            rows = _rows(envelope.get("result"))
            timestamps = [row.get(effective_field) for row in rows]
            try:
                parsed = [parse_timestamp(value, f"representative.{effective_field}") for value in timestamps]
                if not parsed or any(value.utcoffset() is None for value in parsed):
                    raise ValueError("effective_time_missing_or_timezone_naive")
                observed_at = max(parsed).astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
            except (ValueError, TypeError, AttributeError):
                errors.append(f"representative_effective_time_invalid:{cid}")
                continue
        result.update({"isError": envelope.get("isError"),
                       "structuredContent": envelope.get("result"),
                       "observed_at": observed_at,
                       "pagination_complete": envelope.get("pagination_complete")})
    return errors


def _evaluate_qualification(snapshot: dict[str, Any], capabilities: dict[str, Any], now: str,
                            contract_registry: dict[str, Any]) -> dict[str, Any]:
    """Evaluate endpoint and per-capability evidence without inferring success."""
    expected_url = capabilities["runtime"]
    endpoint_match = snapshot.get("endpoint_url") == expected_url
    reachable = snapshot.get("reachability") == "SUCCEEDED"
    initialized = snapshot.get("initialization") == "SUCCEEDED"
    tools = set(snapshot.get("tools", [])) if isinstance(snapshot.get("tools", []), list) else set()
    deployment = snapshot.get("deployment_id")
    contracts = {item.get("capability_id"): item for item in contract_registry.get("contracts", [])}
    endpoint_ok = endpoint_match and reachable and initialized and bool(deployment)
    if not endpoint_match:
        endpoint_status, reason = "BLOCKED", "configured_endpoint_identity_mismatch"
    elif snapshot.get("reachability") in {"FAILED", "COLD", "UNAVAILABLE"}:
        endpoint_status, reason = "UNAVAILABLE", "endpoint_unreachable_or_cold"
    elif not reachable:
        endpoint_status, reason = "BLOCKED", "endpoint_reachability_unverified"
    elif not initialized:
        endpoint_status, reason = "BLOCKED", "mcp_initialization_failed"
    elif not deployment:
        endpoint_status, reason = "BLOCKED", "render_deployment_identity_missing"
    else:
        endpoint_status, reason = "AVAILABLE", None

    evaluated: dict[str, Any] = {}
    for capability in capabilities["capabilities"]:
        cid, tool_name = capability["capability_id"], capability["tool_name"]
        contract = contracts.get(cid)
        if not endpoint_ok:
            state, why = endpoint_status, reason
            age = None
        elif tool_name not in tools:
            state, why, age = "UNAVAILABLE", "required_tool_missing_from_production_catalog", None
        elif not isinstance(contract, dict) or contract.get("status") != "REGISTERED":
            state, why, age = "BLOCKED", "response_schema_and_freshness_contract_unregistered", None
        elif contract.get("pagination_mode") not in {"SINGLE_RESPONSE", "CURSOR", "PAGE_TOKEN", "NONE"}:
            state, why, age = "BLOCKED", "pagination_semantics_unregistered", None
        else:
            result = snapshot.get("representative_results", {}).get(cid)
            if not isinstance(result, dict) or result.get("isError") is True:
                state, why, age = "BLOCKED", "representative_retrieval_failed_or_missing", None
            elif result.get("pagination_complete") is not True:
                state, why, age = "BLOCKED", "pagination_completion_unverified", None
            else:
                normalized = result.get("structuredContent", result.get("result"))
                rows = _rows(normalized)
                if not rows:
                    state, why, age = "BLOCKED", "malformed_or_empty_representative_response", None
                elif (not isinstance(contract, dict)
                      or not isinstance(contract.get("required_fields"), list)
                      or not contract.get("required_fields")
                      or not isinstance(contract.get("field_types"), dict)
                      or not set(contract.get("required_fields", [])).issubset(contract.get("field_types", {}))):
                    state, why, age = "BLOCKED", "response_schema_contract_unregistered", None
                elif any(not all(field in row for field in contract["required_fields"]) for row in rows):
                    state, why, age = "BLOCKED", "response_schema_drift", None
                elif any(not _field_type_matches(row.get(field), kind)
                         for row in rows for field, kind in contract.get("field_types", {}).items()):
                    state, why, age = "BLOCKED", "response_schema_type_drift", None
                else:
                    observed = result.get("observed_at")
                    max_age = contract.get("max_age_seconds")
                    try:
                        cutoff = parse_timestamp(now, "qualification.now")
                        observation = parse_timestamp(observed, "representative.observed_at")
                        if cutoff.utcoffset() is None or observation.utcoffset() is None:
                            raise ValueError("timezone_required")
                        age = int((cutoff - observation).total_seconds())
                        if age < 0:
                            state, why = "BLOCKED", "representative_observation_in_future"
                        elif not isinstance(max_age, int) or max_age < 0:
                            state, why = "BLOCKED", "freshness_limit_unregistered"
                        elif age > max_age:
                            state, why = "DEGRADED", "representative_response_stale"
                        else:
                            state, why = "QUALIFIED", None
                    except (ValueError, TypeError, AttributeError):
                        state, why, age = "BLOCKED", "representative_observation_time_invalid", None
        severity = capability["severity"]
        evaluated[cid] = {"tool_name": tool_name, "status": state, "severity": severity,
                          "reason": why, "age_seconds": age,
                          "admitted": state == "QUALIFIED" and capability.get("admission") == "ADMITTED"}

    states = [item["status"] for item in evaluated.values()]
    if endpoint_status == "UNAVAILABLE":
        overall = "UNAVAILABLE"
    elif endpoint_status == "BLOCKED" or any(
        item["status"] != "QUALIFIED" and item["severity"] == "BLOCKING" for item in evaluated.values()
    ):
        overall = "BLOCKED"
    elif any(s != "QUALIFIED" for s in states):
        overall = "DEGRADED"
    else:
        overall = "QUALIFIED"
    source = next(item for item in _read(ROOT / "config/source-registry.json")["sources"]
                  if item["source_id"] == "fin_data_mcp_render_prod")
    if endpoint_status != "AVAILABLE" or any(item["severity"] == "BLOCKING" and item["status"] != "QUALIFIED"
                                               for item in evaluated.values()):
        health_severity = "BLOCKING"
    elif overall != "QUALIFIED":
        health_severity = "DEGRADED"
    else:
        health_severity = "INFO"
    return {"schema_version": "1.0", "source_id": "fin_data_mcp_render_prod",
            "identity_digest": source["identity_digest"], "endpoint_status": endpoint_status,
            "endpoint_reason": reason, "status": overall, "observed_at": now,
            "deployment_id": deployment, "endpoint_url": expected_url,
            "observed_endpoint_url": snapshot.get("endpoint_url"),
            "capabilities": evaluated, "health_severity": health_severity, "fallback": "NONE",
            "snapshot_digest": digest({k: v for k, v in snapshot.items() if k != "qualification_report"}),
            "capability_policy_digest": digest(capabilities),
            "response_contract_policy_digest": digest(contract_registry)}


def qualify(snapshot: dict[str, Any], capabilities: dict[str, Any], now: str,
            ledger: dict[str, Any] | None = None) -> dict[str, Any]:
    """Evaluate against repository-owned capability and response policies."""
    contract_registry = _read(ROOT / "config/fin-data-response-contracts.json")
    if ledger is None:
        result = _evaluate_qualification(snapshot, capabilities, now, contract_registry)
        result.update({"status": "BLOCKED", "endpoint_status": "BLOCKED",
                       "endpoint_reason": "verified_request_ledger_required",
                       "health_severity": "BLOCKING", "ledger_digest": None,
                       "ledger_errors": ["verified_request_ledger_required"]})
        for state in result["capabilities"].values():
            state.update({"status": "BLOCKED", "admitted": False,
                          "reason": "verified_request_ledger_required"})
        return result
    ledger_errors = _bind_snapshot_to_ledger(snapshot, ledger)
    result = _evaluate_qualification(snapshot, capabilities, now, contract_registry)
    result["ledger_digest"] = ledger.get("content_digest")
    result["ledger_errors"] = ledger_errors
    if ledger_errors:
        result.update({"status": "BLOCKED", "endpoint_status": "BLOCKED",
                       "endpoint_reason": "request_ledger_evidence_invalid",
                       "health_severity": "BLOCKING"})
        for state in result["capabilities"].values():
            state.update({"status": "BLOCKED", "admitted": False,
                          "reason": "request_ledger_evidence_invalid"})
    return result


def normalize_result(result: dict[str, Any], capability_id: str) -> list[dict[str, Any]]:
    """Add provenance fields while retaining each full provider-native row."""
    payload = result.get("structuredContent", result.get("result"))
    rows = _rows(payload)
    normalized = []
    for index, row in enumerate(rows):
        normalized.append({"source_id": "fin_data_mcp_render_prod", "capability_id": capability_id,
                           "provider_row_index": index, "provider_native": row})
    return normalized


def _field_type_matches(value: Any, kind: str) -> bool:
    checks = {"string": lambda item: isinstance(item, str),
              "number": lambda item: isinstance(item, (int, float)) and not isinstance(item, bool),
              "integer": lambda item: isinstance(item, int) and not isinstance(item, bool),
              "boolean": lambda item: isinstance(item, bool),
              "array": lambda item: isinstance(item, list),
              "object": lambda item: isinstance(item, dict)}
    return kind in checks and checks[kind](value)


def build_manifest(snapshot: dict[str, Any], capability: dict[str, Any], run_id: str,
                   attempt_id: str, cutoff: str, observed_at: str,
                   response_contract: dict[str, Any] | None = None) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Create a generalized source manifest plus normalized durable rows.

    Only diagnostics are emitted unless a prior endpoint-bound qualification is
    supplied and the declared response/freshness contract passes.
    """
    cid = capability["capability_id"]
    registered_caps = _read(ROOT / "config/source-capabilities/fin-data.json")
    registered_capability = next((item for item in registered_caps["capabilities"] if item["capability_id"] == cid), None)
    if registered_capability is None or registered_capability != capability:
        raise ValueError("fin_data_capability_not_registered")
    result = snapshot.get("representative_results", {}).get(cid)
    contract_registry = _read(ROOT / "config/fin-data-response-contracts.json")
    registered_contract = next((item for item in contract_registry["contracts"] if item["capability_id"] == cid), None)
    if response_contract is not None and response_contract != registered_contract:
        raise ValueError("fin_data_response_contract_not_registered")
    response_contract = registered_contract if registered_contract and registered_contract.get("status") == "REGISTERED" else None
    rows = normalize_result(result, cid) if isinstance(result, dict) and response_contract else []
    raw_digest = digest(result) if isinstance(result, dict) else None
    normalized_digest = digest(rows)
    report = snapshot.get("qualification_report", {})
    cap_report = report.get("capabilities", {}).get(cid, {}) if isinstance(report, dict) else {}
    has_observation = bool(response_contract and isinstance(result, dict)
                           and result.get("isError") is not True and rows)
    qualified = bool(report.get("source_id") == "fin_data_mcp_render_prod"
                     and report.get("snapshot_digest") == digest({k: v for k, v in snapshot.items() if k != "qualification_report"})
                     and report.get("capability_policy_digest") == digest(registered_caps)
                     and report.get("response_contract_policy_digest") == digest(contract_registry)
                     and report.get("endpoint_url") == snapshot.get("endpoint_url")
                     and report.get("deployment_id") == snapshot.get("deployment_id")
                     and cap_report.get("status") == "QUALIFIED" and cap_report.get("admitted") is True
                     and report.get("ledger_digest") == snapshot.get("verified_request_ledger", {}).get("content_digest")
                     and not _verify_ledger(snapshot.get("verified_request_ledger", {}))
                     and registered_capability.get("admission") == "ADMITTED"
                     and response_contract)
    max_age = response_contract.get("max_age_seconds") if response_contract else 0
    if has_observation and (not isinstance(max_age, int) or max_age < 0):
        raise ValueError("fin_data_freshness_limit_unregistered")
    try:
        observation = result.get("observed_at") if result else observed_at
        age = max(0, int((parse_timestamp(cutoff, "cutoff") - parse_timestamp(observation, "observed_at")).total_seconds()))
    except (ValueError, TypeError):
        observation, age = observed_at, 0
        qualified = False
    datasets = []
    if has_observation:
        datasets.append({"dataset_id": f"{cid}:{attempt_id}", "data_digest": normalized_digest,
                         "evidence_role": "RESEARCH_INPUT" if qualified else "DIAGNOSTIC",
                         "status": "COMPLETE" if qualified else "DEGRADED",
                         "pagination_complete": result.get("pagination_complete") is True,
                         "row_count": len(rows), "observed_at": observation, "published_at": None,
                         "available_at": observed_at, "freshness_seconds": age,
                         "max_age_seconds": max_age, "qualification": "QUALIFIED" if qualified else "UNQUALIFIED",
                         "admissibility": "ADMITTED" if qualified else "NOT_ADMITTED"})
    if qualified:
        manifest_status, availability, reason = "COMPLETE", "AVAILABLE", None
    elif snapshot.get("reachability") in {"FAILED", "COLD", "UNAVAILABLE"}:
        manifest_status, availability, reason = "UNAVAILABLE", "UNAVAILABLE", "endpoint_unreachable_or_cold"
    elif snapshot.get("reachability") == "SUCCEEDED":
        manifest_status, availability, reason = "DEGRADED", "AVAILABLE", "fin_data_capability_not_qualified"
    else:
        manifest_status, availability, reason = "BLOCKED", "UNKNOWN", "endpoint_reachability_unverified"
    source = next(item for item in _read(ROOT / "config/source-registry.json")["sources"]
                  if item["source_id"] == "fin_data_mcp_render_prod")
    manifest = {"schema_version": "1.0", "manifest_id": "", "run_id": run_id,
                "attempt_id": attempt_id, "created_at": observed_at, "research_cutoff": cutoff,
                "source": source, "capability_id": cid,
                "discovery_status": "DISCOVERED" if snapshot.get("initialization") == "SUCCEEDED" else "UNKNOWN",
                "availability_status": availability,
                "qualification": "QUALIFIED" if qualified else "UNQUALIFIED",
                "admissibility": "ADMITTED" if qualified else "NOT_ADMITTED",
                "status": manifest_status,
                "degradation_reason": reason,
                "adapter_payload": {"deployment_id": snapshot.get("deployment_id"),
                                    "endpoint_url": snapshot.get("endpoint_url"), "raw_response_digest": raw_digest,
                                    "normalized_rows_digest": normalized_digest,
                                    "normalization_version": "fin-data-native-envelope-v1"},
                "datasets": datasets, "content_digest": ""}
    manifest["manifest_id"] = expected_manifest_id(manifest)
    manifest["content_digest"] = digest({key: value for key, value in manifest.items() if key != "content_digest"})
    return manifest, rows


def materialize(snapshot: dict[str, Any], capability: dict[str, Any], run_id: str,
                attempt_id: str, cutoff: str, observed_at: str, out_dir: Path,
                response_contract: dict[str, Any] | None = None) -> Path:
    """Write immutable raw, normalized JSONL and generalized source manifest."""
    cid = capability["capability_id"]
    safe_id = cid.replace(".", "_")
    result = snapshot.get("representative_results", {}).get(cid)
    if not isinstance(result, dict):
        result = {"isError": True, "error": "representative_result_missing"}
    manifest, rows = build_manifest(snapshot, capability, run_id, attempt_id, cutoff,
                                    observed_at, response_contract)
    raw_path = out_dir / f"{safe_id}.raw.json"
    normalized_path = out_dir / f"{safe_id}.normalized.jsonl"
    manifest_path = out_dir / f"{safe_id}.manifest.json"
    write_new_json(raw_path, result)
    normalized_path.parent.mkdir(parents=True, exist_ok=True)
    with normalized_path.open("x", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n")
    manifest["adapter_payload"].update({
        "raw_path": raw_path.name, "raw_file_digest": digest(result), "raw_response_digest": digest(result),
        "normalized_path": normalized_path.name,
        "normalized_file_digest": "sha256:" + __import__("hashlib").sha256(normalized_path.read_bytes()).hexdigest(),
    })
    manifest["manifest_id"] = expected_manifest_id(manifest)
    manifest["content_digest"] = digest({key: value for key, value in manifest.items() if key != "content_digest"})
    errors = validate_source_manifest(manifest)
    if errors:
        raise ValueError("fin_data_manifest_invalid:" + ";".join(errors))
    write_new_json(manifest_path, manifest)
    return manifest_path


def verify_materialization(manifest_path: Path) -> list[str]:
    """Check source manifest plus exact raw/normalized file bindings."""
    errors: list[str] = []
    try:
        manifest = _read(manifest_path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return [f"manifest_unreadable:{exc}"]
    errors.extend(validate_source_manifest(manifest))
    payload = manifest.get("adapter_payload", {})
    base = manifest_path.resolve().parent
    resolved: dict[str, Path] = {}
    for name in ("raw_path", "normalized_path"):
        candidate = (base / str(payload.get(name, ""))).resolve()
        try:
            candidate.relative_to(base)
        except ValueError:
            errors.append(f"{name}_escapes_manifest_directory")
            continue
        resolved[name] = candidate
        if not candidate.is_file():
            errors.append(f"{name}_missing")
    if "raw_path" in resolved and resolved["raw_path"].is_file():
        try:
            raw = _read(resolved["raw_path"])
            if digest(raw) != payload.get("raw_file_digest") or digest(raw) != payload.get("raw_response_digest"):
                errors.append("raw_response_digest_mismatch")
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            errors.append(f"raw_response_invalid:{exc}")
    if "normalized_path" in resolved and resolved["normalized_path"].is_file():
        try:
            path = resolved["normalized_path"]
            if "sha256:" + __import__("hashlib").sha256(path.read_bytes()).hexdigest() != payload.get("normalized_file_digest"):
                errors.append("normalized_file_digest_mismatch")
            rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
            datasets = manifest.get("datasets", [])
            if not datasets and (rows or digest(rows) != payload.get("normalized_rows_digest")):
                errors.append("empty_dataset_payload_mismatch")
            elif len(datasets) > 1:
                errors.append("expected_at_most_one_dataset")
            elif datasets and digest(rows) != datasets[0].get("data_digest"):
                errors.append("normalized_dataset_digest_mismatch")
            elif datasets and len(rows) != datasets[0].get("row_count"):
                errors.append("normalized_row_count_mismatch")
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            errors.append(f"normalized_rows_invalid:{exc}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    qualification = sub.add_parser("qualify")
    qualification.add_argument("snapshot")
    qualification.add_argument("--now", required=True)
    qualification.add_argument("--ledger", required=True)
    qualification.add_argument("--out", required=True)
    materialization = sub.add_parser("materialize")
    materialization.add_argument("snapshot")
    materialization.add_argument("--capability-id", required=True)
    materialization.add_argument("--run-id", required=True)
    materialization.add_argument("--attempt-id", required=True)
    materialization.add_argument("--research-cutoff", required=True)
    materialization.add_argument("--created-at", required=True)
    materialization.add_argument("--qualification-report", required=True)
    materialization.add_argument("--ledger", required=True)
    materialization.add_argument("--out-dir", required=True)
    verification = sub.add_parser("verify")
    verification.add_argument("manifest")
    args = parser.parse_args()
    try:
        if args.command == "verify":
            errors = verify_materialization(Path(args.manifest))
            if errors:
                print("\n".join(errors)); return 1
            print("PASS:" + args.manifest); return 0
        snapshot = _read(args.snapshot)
        capabilities = _read(ROOT / "config/source-capabilities/fin-data.json")
        ledger = _read(args.ledger)
        ledger_errors = _bind_snapshot_to_ledger(snapshot, ledger)
        snapshot["verified_request_ledger"] = ledger
        if args.command == "qualify":
            result = qualify(snapshot, capabilities, args.now, ledger)
            schema = _read(ROOT / "schemas/fin_data_qualification_report.schema.json")
            sys.path.insert(0, str(ROOT / "scripts" / "control_plane"))
            from validate_artifact import validate as validate_schema
            errors = validate_schema(result, schema)
            if errors:
                raise ValueError("qualification_report_schema:" + ";".join(errors))
            write_new_json(args.out, result)
            print(f"{result['status']}:{args.out}")
            return 0 if result["status"] == "QUALIFIED" else 1
        capability = next((item for item in capabilities["capabilities"]
                           if item["capability_id"] == args.capability_id), None)
        if capability is None:
            raise ValueError("capability_not_registered")
        qualification_report = _read(args.qualification_report)
        report_schema = _read(ROOT / "schemas/fin_data_qualification_report.schema.json")
        sys.path.insert(0, str(ROOT / "scripts" / "control_plane"))
        from validate_artifact import validate as validate_schema
        report_errors = validate_schema(qualification_report, report_schema)
        if report_errors:
            raise ValueError("qualification_report_schema:" + ";".join(report_errors))
        if ledger_errors or qualification_report.get("ledger_digest") != ledger.get("content_digest"):
            raise ValueError("fin_data_request_ledger_evidence_invalid")
        snapshot["qualification_report"] = qualification_report
        path = materialize(snapshot, capability, args.run_id, args.attempt_id,
                           args.research_cutoff, args.created_at, Path(args.out_dir),
                           None)
        print(path)
        return 0
    except FileExistsError:
        print("IMMUTABLE_CONFLICT:" + args.out)
        return 3
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        print(f"FIN_DATA_QUALIFICATION_ERROR:{exc}")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

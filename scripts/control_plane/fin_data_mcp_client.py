from __future__ import annotations

"""Permit-ledgered Streamable HTTP MCP client for the configured Fin Data source."""

import argparse
import json
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "control_plane"))
from common import digest  # noqa: E402


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("expected_json_object")
    return value


def _write(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(value, handle, indent=2, sort_keys=True)
        handle.write("\n")


def _rpc_message(body: bytes) -> dict[str, Any]:
    text = body.decode("utf-8", errors="replace")
    try:
        message = json.loads(text)
        if isinstance(message, dict):
            return message
    except json.JSONDecodeError:
        pass
    for line in text.splitlines():
        if line.startswith("data:"):
            try:
                message = json.loads(line[5:].strip())
                if isinstance(message, dict):
                    return message
            except json.JSONDecodeError:
                continue
    raise ValueError("mcp_response_not_json_rpc")


def _complete_payload(payload: dict[str, Any]) -> bool:
    if payload.get("nextCursor"):
        return False
    structured = payload.get("structuredContent")
    if structured is not None:
        return not (isinstance(structured, dict) and structured.get("nextCursor"))
    content = payload.get("content")
    if isinstance(content, list):
        for block in content:
            if not isinstance(block, dict) or not isinstance(block.get("text"), str):
                continue
            text = block["text"].lstrip()
            if text.startswith(("[", "{")):
                try:
                    json.loads(text)
                except json.JSONDecodeError:
                    return False
    return True


def _rate_limit_signal(status_code: int | None, payload: Any) -> bool:
    if status_code == 429:
        return True
    if isinstance(payload, dict):
        rendered = " ".join(str(payload.get(key, "")) for key in ("code", "message", "error"))
        normalized = rendered.lower().replace("_", " ").replace("-", " ")
        return "rate limit" in normalized or "too many requests" in normalized
    return False


def _permit(ledger: Path, capability_id: str, tool_name: str, request_id: str,
            arguments: dict[str, Any], workdir: Path) -> dict[str, Any]:
    args_file = workdir / f"{request_id}.arguments.json"
    _write(args_file, arguments)
    command = [sys.executable, str(ROOT / "scripts/control_plane/fin_data_request_gate.py"),
               "permit", "--ledger", str(ledger), "--capability-id", capability_id,
               "--tool-name", tool_name, "--request-id", request_id,
               "--arguments-file", str(args_file)]
    completed = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, check=False)
    if completed.returncode:
        raise RuntimeError(f"permit_denied:{completed.stdout.strip()}:{completed.stderr.strip()}")
    return json.loads(completed.stdout)


def _wire_authorization_error(capability_id: str, tool_name: str, method: str,
                              params: dict[str, Any]) -> str | None:
    """Bind the JSON-RPC operation and actual tool call to the governed identity."""
    control = {
        "fin.mcp.initialize": ("initialize", "initialize"),
        "fin.mcp.tools_list": ("tools/list", "tools/list"),
        "fin.mcp.initialized_notification": ("notifications/initialized", "notifications/initialized"),
    }
    if capability_id in control:
        expected_method, expected_tool = control[capability_id]
        if tool_name != expected_tool or method != expected_method:
            return "protocol_operation_identity_mismatch"
        if method in {"tools/list", "notifications/initialized"} and params:
            return "unexpected_control_operation_parameters"
        return None
    capabilities = _read(ROOT / "config/source-capabilities/fin-data.json")["capabilities"]
    registered = next((item for item in capabilities if item["capability_id"] == capability_id), None)
    if registered is None or registered.get("tool_name") != tool_name:
        return "capability_tool_identity_mismatch"
    if method != "tools/call":
        return "protocol_method_not_authorized_for_capability"
    if set(params) != {"name", "arguments"} or params.get("name") != tool_name:
        return "wire_tool_name_mismatch"
    if not isinstance(params.get("arguments"), dict):
        return "wire_tool_arguments_invalid"
    return None


def _record(ledger: Path, request_id: str, result_file: Path, envelope: dict[str, Any]) -> str:
    _write(result_file, envelope)
    completed = subprocess.run([sys.executable, str(ROOT / "scripts/control_plane/fin_data_request_gate.py"),
                                "record", "--ledger", str(ledger), "--request-id", request_id,
                                "--result-file", str(result_file)], cwd=ROOT,
                               capture_output=True, text=True, check=False)
    if completed.returncode:
        raise RuntimeError(f"result_record_failed:{completed.stdout.strip()}:{completed.stderr.strip()}")
    return completed.stdout.strip()


def invoke(endpoint: str, deployment_id: str, ledger: Path, capability_id: str,
           tool_name: str, method: str, params: dict[str, Any], result_file: Path,
           session_file: Path | None = None, timeout: int = 45) -> dict[str, Any]:
    configured = _read(ROOT / "config/source-capabilities/fin-data.json")["runtime"]
    if endpoint != configured:
        return {"transport_error": "configured_endpoint_identity_mismatch", "endpoint": endpoint}
    authorization_error = _wire_authorization_error(capability_id, tool_name, method, params)
    if authorization_error:
        return {"transport_error": f"runtime_authorization_denied:{authorization_error}"}
    request_id = "fin-" + uuid.uuid4().hex
    permit_id = None
    started = _now()
    status_code: int | None = None
    content_type = ""
    body = b""
    try:
        with tempfile.TemporaryDirectory(prefix="fin-data-mcp-args-") as temp_dir:
            permit = _permit(ledger, capability_id, tool_name, request_id, params, Path(temp_dir))
        permit_id = permit["permit_id"]
        message_id = int(time.time() * 1000) % 2_000_000_000
        is_notification = method.startswith("notifications/")
        rpc: dict[str, Any] = {"jsonrpc": "2.0", "method": method, "params": params}
        if not is_notification:
            rpc["id"] = message_id
        headers = {"Accept": "application/json, text/event-stream",
                   "Content-Type": "application/json", "User-Agent": "fin-data-governed-source/0.1"}
        if method != "initialize":
            headers["MCP-Protocol-Version"] = "2024-11-05"
        if session_file and session_file.exists():
            session_id = session_file.read_text(encoding="utf-8").strip()
            if session_id:
                headers["Mcp-Session-Id"] = session_id
        request = urllib.request.Request(endpoint, data=json.dumps(rpc).encode("utf-8"),
                                         headers=headers, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                body = response.read()
                status_code = response.status
                content_type = response.headers.get("Content-Type", "")
                session_id = response.headers.get("Mcp-Session-Id")
        except urllib.error.HTTPError as exc:
            body = exc.read()
            status_code = exc.code
            content_type = exc.headers.get("Content-Type", "")
            session_id = exc.headers.get("Mcp-Session-Id")
        if session_id and session_file:
            session_file.write_text(session_id, encoding="utf-8")
        if is_notification and status_code in {200, 202, 204}:
            payload = {"http_status": status_code, "notification_acknowledged": True}
            is_error = False
            pagination_complete = True
        else:
            response_rpc = _rpc_message(body)
            if response_rpc.get("id") != message_id:
                raise ValueError("mcp_response_id_mismatch")
            is_error = "error" in response_rpc or status_code is None or status_code < 200 or status_code >= 300
            payload = response_rpc.get("error") if is_error else response_rpc.get("result")
            if not isinstance(payload, dict):
                raise ValueError("mcp_response_result_not_object")
            pagination_complete = _complete_payload(payload)
            if method == "tools/call":
                is_error = is_error or bool(payload.get("isError", False))
        envelope = {"schema_version": "1.0", "source_id": "fin_data_mcp_render_prod",
                    "capability_id": capability_id, "tool_name": tool_name, "request_id": request_id,
                    "permit_id": permit_id, "endpoint_url": endpoint, "deployment_id": deployment_id,
                    "protocol_method": method,
                    "arguments_digest": digest(params), "requested_at": started, "received_at": _now(),
                    "isError": is_error, "pagination_complete": pagination_complete,
                    "raw_response_digest": digest(payload), "result": payload,
                    "http_status": status_code, "content_type": content_type}
        if _rate_limit_signal(status_code, payload):
            envelope["warning"] = "RATE_LIMIT"
            envelope["error_code"] = "RATE_LIMIT"
        record_status = _record(ledger, request_id, result_file, envelope)
        return {"request_id": request_id, "permit_id": permit_id, "record_status": record_status,
                "http_status": status_code, "content_type": content_type, "isError": is_error,
                "pagination_complete": pagination_complete, "result_file": str(result_file),
                "result_digest": digest(envelope)}
    except Exception as exc:
        if permit_id is not None:
            payload = {"transport_error": f"{type(exc).__name__}:{exc}", "http_status": status_code,
                       "body": body.decode("utf-8", errors="replace")}
            envelope = {"schema_version": "1.0", "source_id": "fin_data_mcp_render_prod",
                        "capability_id": capability_id, "tool_name": tool_name, "request_id": request_id,
                        "permit_id": permit_id, "endpoint_url": endpoint, "deployment_id": deployment_id,
                        "protocol_method": method,
                        "arguments_digest": digest(params), "requested_at": started, "received_at": _now(),
                        "isError": True, "pagination_complete": False,
                        "raw_response_digest": digest(payload), "result": payload,
                        "http_status": status_code, "content_type": content_type,
                        "warning": "RATE_LIMIT" if status_code == 429 else "TRANSPORT_ERROR",
                        "error_code": "RATE_LIMIT" if status_code == 429 else "TRANSPORT_ERROR"}
            try:
                record_status = _record(ledger, request_id, result_file, envelope)
            except Exception as record_exc:
                return {"request_id": request_id, "permit_id": permit_id,
                        "transport_error": f"{type(exc).__name__}:{exc}",
                        "record_error": f"{type(record_exc).__name__}:{record_exc}"}
            return {"request_id": request_id, "permit_id": permit_id, "record_status": record_status,
                    "transport_error": f"{type(exc).__name__}:{exc}", "http_status": status_code,
                    "result_file": str(result_file)}
        return {"request_id": request_id, "permit_id": permit_id, "requested_at": started,
                "transport_error": f"{type(exc).__name__}:{exc}"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--endpoint", required=True)
    parser.add_argument("--deployment-id", required=True)
    parser.add_argument("--ledger", required=True)
    parser.add_argument("--capability-id", required=True)
    parser.add_argument("--tool-name", required=True)
    parser.add_argument("--method", required=True)
    parser.add_argument("--params-file", required=True)
    parser.add_argument("--result-file", required=True)
    parser.add_argument("--session-file")
    parser.add_argument("--timeout", type=int, default=45)
    args = parser.parse_args()
    params = _read(Path(args.params_file))
    outcome = invoke(args.endpoint, args.deployment_id, Path(args.ledger), args.capability_id,
                     args.tool_name, args.method, params, Path(args.result_file),
                     Path(args.session_file) if args.session_file else None, args.timeout)
    print(json.dumps(outcome, sort_keys=True))
    return 0 if "transport_error" not in outcome else 1


if __name__ == "__main__":
    raise SystemExit(main())

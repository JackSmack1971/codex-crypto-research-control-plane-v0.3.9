from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from common import digest
from validate_artifact import validate as validate_schema

ROOT = Path(__file__).resolve().parents[2]
RIGHTS_REQUIRED_USES = ("research", "durable_storage", "deterministic_derivation",
                        "ai_llm_processing", "institutional_commercial")


def snapshot_digest(snapshot: dict[str, Any]) -> str:
    return digest(snapshot)


def validate_snapshot(snapshot: dict[str, Any]) -> list[str]:
    schema = json.loads((ROOT / "schemas/source_rights_qualification.schema.json").read_text(encoding="utf-8"))
    errors = validate_schema(snapshot, schema)
    if snapshot.get("qualification_result") == "PASS" and not snapshot.get("review", {}).get("authorization_documented"):
        errors.append("rights.pass_without_documented_authorization")
    for index, item in enumerate(snapshot.get("evidence", [])):
        path = item.get("provenance_path") if isinstance(item, dict) else None
        if not path:
            errors.append(f"rights.evidence[{index}].provenance_missing")
            continue
        target = (ROOT / path).resolve()
        try:
            target.relative_to(ROOT)
        except ValueError:
            errors.append(f"rights.evidence[{index}].path_escapes_root")
            continue
        if not target.is_file() or "sha256:" + hashlib.sha256(target.read_bytes()).hexdigest() != item.get("digest"):
            errors.append(f"rights.evidence[{index}].digest_mismatch")
    return errors


def rights_result(snapshot: dict[str, Any], now: str | None = None) -> str:
    """Fail closed. Rights pass only on documented authorization and all required uses permitted."""
    matrix = snapshot.get("use_matrix", {})
    if snapshot.get("qualification_result") == "BLOCK" or any(matrix.get(k) == "PROHIBITED" for k in RIGHTS_REQUIRED_USES):
        return "BLOCK"
    if snapshot.get("qualification_result") != "PASS" or not snapshot.get("review", {}).get("authorization_documented"):
        return "UNKNOWN"
    if any(matrix.get(k) != "PERMITTED" for k in RIGHTS_REQUIRED_USES):
        return "UNKNOWN"
    if not snapshot.get("evidence"):
        return "UNKNOWN"
    for item in snapshot["evidence"]:
        path = item.get("provenance_path")
        if not path:
            return "UNKNOWN"
        target = (ROOT / path).resolve()
        try:
            target.relative_to(ROOT)
        except ValueError:
            return "UNKNOWN"
        if not target.is_file() or "sha256:" + hashlib.sha256(target.read_bytes()).hexdigest() != item.get("digest"):
            return "UNKNOWN"
    current = datetime.fromisoformat((now or datetime.now(timezone.utc).isoformat()).replace("Z", "+00:00"))
    expiry = snapshot.get("expires_at")
    if expiry and datetime.fromisoformat(expiry.replace("Z", "+00:00")) <= current:
        return "UNKNOWN"
    return "PASS"


def snapshot_for_capability(capability_id: str, config: dict[str, Any] | None = None) -> dict[str, Any] | None:
    if config is None:
        config = json.loads((ROOT / "config/source-rights.json").read_text(encoding="utf-8"))
    mapping = next((m for m in config.get("capability_sources", []) if m.get("capability_id") == capability_id), None)
    if mapping is None:
        return None
    return next((s for s in config.get("rights_snapshots", [])
                 if s.get("upstream_provider_id") == mapping.get("upstream_provider_id")
                 and s.get("upstream_dataset_id") == mapping.get("upstream_dataset_id")), None)


def admission_rights_result(capability_id: str, runtime_status: str,
                            config: dict[str, Any] | None = None) -> tuple[str, str | None]:
    """Runtime qualification is necessary but can never grant data-source rights."""
    if runtime_status != "PASS":
        return "BLOCK", None
    snapshot = snapshot_for_capability(capability_id, config)
    if snapshot is None:
        return "UNKNOWN", None
    result = rights_result(snapshot)
    if result != "PASS":
        return result, snapshot_digest(snapshot)
    return "PASS", snapshot_digest(snapshot)

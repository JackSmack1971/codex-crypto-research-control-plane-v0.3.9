from __future__ import annotations

import json
import hashlib
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "control_plane"))
from common import digest  # noqa: E402
from validate_artifact import validate as validate_schema  # noqa: E402


def load_policy() -> dict[str, Any]:
    policy = json.loads((ROOT / "config/fin-data-use-authorization.json").read_text(encoding="utf-8"))
    if not isinstance(policy, dict):
        raise ValueError("fin_data_use_authorization_policy_not_object")
    return policy


def policy_errors(policy: dict[str, Any]) -> list[str]:
    schema = json.loads((ROOT / "schemas/fin_data_use_authorization.schema.json").read_text(encoding="utf-8"))
    return validate_schema(policy, schema)


def authorization_error(policy: dict[str, Any]) -> str | None:
    errors = policy_errors(policy)
    if errors:
        return "provider_use_authorization_policy_invalid"
    if policy.get("source_id") != "fin_data_mcp_render_prod":
        return "provider_use_authorization_identity_mismatch"
    if policy.get("status") != "AUTHORIZED":
        return "provider_use_authorization_blocked:" + str(policy.get("status", "MISSING"))
    decision = policy.get("authorization_decision")
    if not isinstance(decision, dict) or decision.get("approved_scope") != policy.get("scope"):
        return "provider_use_authorization_decision_invalid"
    if decision.get("approved_by", "").strip().casefold() == decision.get("independent_reviewer", "").strip().casefold():
        return "provider_use_authorization_reviewer_not_independent"
    reference = decision.get("review_reference", "")
    if not reference or not decision.get("reviewed_commit"):
        return "provider_use_authorization_review_evidence_missing"
    relative = Path(decision.get("rights_document", ""))
    if relative.is_absolute() or ".." in relative.parts:
        return "provider_use_authorization_rights_path_invalid"
    target = (ROOT / relative).resolve()
    try:
        target.relative_to(ROOT)
    except ValueError:
        return "provider_use_authorization_rights_path_invalid"
    if not target.is_file():
        return "provider_use_authorization_rights_document_missing"
    actual = "sha256:" + hashlib.sha256(target.read_bytes()).hexdigest()
    if actual != decision.get("rights_document_digest"):
        return "provider_use_authorization_rights_digest_mismatch"
    return None


def policy_digest(policy: dict[str, Any]) -> str:
    return digest(policy)


def evidence_binding_authorized(policy: dict[str, Any], ledger: dict[str, Any],
                               report: dict[str, Any]) -> bool:
    """Require current authorization to be bound into both qualification and acquisition."""
    if authorization_error(policy):
        return False
    current_digest = policy_digest(policy)
    runtime_auth = report.get("runtime_authorization", {})
    return (ledger.get("provider_use_authorization_digest") == current_digest
            and runtime_auth.get("status") == "AUTHORIZED"
            and runtime_auth.get("policy_digest") == current_digest)

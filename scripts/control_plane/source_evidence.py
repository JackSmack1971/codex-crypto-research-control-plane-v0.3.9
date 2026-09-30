from __future__ import annotations

import hashlib
import json
import hashlib
from datetime import datetime
from pathlib import Path
from typing import Any

from common import canonical_bytes, digest, parse_timestamp, validate_daily_cutoff_contract
from validate_artifact import validate as validate_schema
from validate_sources import identity_payload

ROOT = Path(__file__).resolve().parents[2]


def _schema_errors(obj: dict[str, Any], schema_file: str, label: str) -> list[str]:
    schema = json.loads((ROOT / "schemas" / schema_file).read_text(encoding="utf-8"))
    return [f"{label}.schema:{item}" for item in validate_schema(obj, schema)]


def without_digest(obj: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in obj.items() if key != "content_digest"}


def expected_manifest_id(obj: dict[str, Any]) -> str:
    identity = {key: value for key, value in obj.items() if key not in {"manifest_id", "content_digest"}}
    return "sm-" + hashlib.sha256(canonical_bytes(identity)).hexdigest()[:24]


def expected_bundle_id(bundle: dict[str, Any]) -> str:
    identity = {key: bundle.get(key) for key in ("schema_version", "run_id", "attempt_id", "research_cutoff", "members")}
    return "eb-" + hashlib.sha256(canonical_bytes(identity)).hexdigest()[:24]


def _load_registry(registry: dict[str, Any] | None) -> dict[str, Any]:
    if registry is not None:
        return registry
    return json.loads((ROOT / "config" / "source-registry.json").read_text(encoding="utf-8"))


def validate_source_manifest(obj: dict[str, Any], registry: dict[str, Any] | None = None) -> list[str]:
    errors: list[str] = _schema_errors(obj, "source_acquisition_manifest.schema.json", "manifest")
    for key in ("manifest_id", "run_id", "attempt_id", "created_at", "research_cutoff", "source", "capability_id", "status", "datasets", "content_digest"):
        if key not in obj:
            errors.append(f"manifest.missing:{key}")
    if obj.get("manifest_id") != expected_manifest_id(obj):
        errors.append("manifest.manifest_id_mismatch")
    source = obj.get("source", {})
    if not isinstance(source, dict):
        errors.append("manifest.source_must_be_object")
        source = {}
    for key in ("source_id", "identity_digest", "provider", "runtime", "transport", "adapter_id", "adapter_version", "capability_ids"):
        if not source.get(key):
            errors.append(f"manifest.source_missing:{key}")
    if obj.get("capability_id") not in source.get("capability_ids", []):
        errors.append("manifest.capability_identity_mismatch")
    identity = identity_payload(source)
    if source.get("identity_digest") != digest(identity):
        errors.append("manifest.source_identity_digest_mismatch")
    try:
        registered = {item["source_id"]: item for item in _load_registry(registry).get("sources", [])}
        trusted = registered.get(source.get("source_id"))
        if trusted is None:
            errors.append("manifest.source_not_registered")
        elif trusted != {**identity, "identity_digest": source.get("identity_digest")}:
            errors.append("manifest.source_registry_identity_mismatch")
        elif obj.get("capability_id") not in trusted.get("capability_ids", []):
            errors.append("manifest.capability_not_registered_for_source")
    except (OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
        errors.append(f"manifest.source_registry_invalid:{exc}")
    if obj.get("discovery_status") not in {"DISCOVERED", "NOT_DISCOVERED", "UNKNOWN"}:
        errors.append("manifest.invalid_discovery_status")
    if obj.get("availability_status") not in {"AVAILABLE", "UNAVAILABLE", "UNKNOWN"}:
        errors.append("manifest.invalid_availability_status")
    if obj.get("qualification") not in {"QUALIFIED", "UNQUALIFIED", "EXPIRED"}:
        errors.append("manifest.invalid_qualification")
    if obj.get("admissibility") not in {"ADMITTED", "NOT_ADMITTED"}:
        errors.append("manifest.invalid_admissibility")
    if obj.get("status") not in {"COMPLETE", "DEGRADED", "PARTIAL", "BLOCKED", "UNAVAILABLE"}:
        errors.append("manifest.invalid_status")
    if obj.get("status") == "DEGRADED" and not obj.get("degradation_reason"):
        errors.append("manifest.degraded_reason_required")
    if obj.get("status") == "UNAVAILABLE" and not obj.get("degradation_reason"):
        errors.append("manifest.unavailable_reason_required")
    if obj.get("availability_status") == "UNAVAILABLE" and any(isinstance(d, dict) and d.get("evidence_role") == "RESEARCH_INPUT" for d in obj.get("datasets", [])):
        errors.append("manifest.unavailable_source_has_research_input")
    has_research = any(isinstance(d, dict) and d.get("evidence_role") == "RESEARCH_INPUT" for d in obj.get("datasets", []))
    if has_research and obj.get("availability_status") != "AVAILABLE":
        errors.append("manifest.research_input_source_not_available")
    if has_research and obj.get("discovery_status") != "DISCOVERED":
        errors.append("manifest.research_input_source_not_discovered")
    if obj.get("qualification") != "QUALIFIED" and any(isinstance(d, dict) and d.get("evidence_role") == "RESEARCH_INPUT" for d in obj.get("datasets", [])):
        errors.append("manifest.unqualified_source_has_research_input")
    if obj.get("admissibility") != "ADMITTED" and any(isinstance(d, dict) and d.get("evidence_role") == "RESEARCH_INPUT" for d in obj.get("datasets", [])):
        errors.append("manifest.not_admitted_source_has_research_input")
    try:
        cutoff = parse_timestamp(obj.get("research_cutoff", ""), "manifest.research_cutoff")
        created = parse_timestamp(obj.get("created_at", ""), "manifest.created_at")
        if cutoff.utcoffset() is None or cutoff.utcoffset().total_seconds() != 0:
            errors.append("manifest.research_cutoff_must_be_utc")
        if created.utcoffset() is None:
            errors.append("manifest.created_at_must_be_timezone_aware")
        errors.extend(validate_daily_cutoff_contract(obj.get("run_id", ""), obj.get("research_cutoff", ""), "EXCLUSIVE_UTC_BOUNDARY", "manifest"))
    except (ValueError, TypeError, AttributeError) as exc:
        errors.append(str(exc)); cutoff = None
    datasets = obj.get("datasets")
    if not isinstance(datasets, list):
        errors.append("manifest.datasets_must_be_list"); datasets = []
    ids: set[str] = set()
    for i, ds in enumerate(datasets):
        label = f"dataset[{i}]"
        if not isinstance(ds, dict):
            errors.append(f"{label}.must_be_object"); continue
        did = ds.get("dataset_id")
        if not isinstance(did, str) or not did:
            errors.append(f"{label}.missing:dataset_id")
        elif did in ids:
            errors.append(f"{label}.duplicate_dataset_id:{did}")
        ids.add(did)
        for key in ("data_digest", "evidence_role", "pagination_complete", "row_count", "observed_at"):
            if key not in ds: errors.append(f"{label}.missing:{key}")
        if ds.get("evidence_role") not in {"RESEARCH_INPUT", "DIAGNOSTIC"}:
            errors.append(f"{label}.invalid_evidence_role")
        if ds.get("evidence_role") == "RESEARCH_INPUT":
            if ds.get("rights_result") != "PASS":
                errors.append(f"{label}.research_input_rights_not_qualified")
            if not ds.get("rights_snapshot_id"):
                errors.append(f"{label}.research_input_rights_snapshot_missing")
            rights_digest = ds.get("rights_snapshot_digest")
            if (not isinstance(rights_digest, str) or len(rights_digest) != 71
                    or not rights_digest.startswith("sha256:")
                    or any(char not in "0123456789abcdef" for char in rights_digest[7:])):
                errors.append(f"{label}.research_input_rights_digest_missing")
        if ds.get("evidence_role") == "RESEARCH_INPUT" and (ds.get("admissibility") != "ADMITTED" or ds.get("qualification") != "QUALIFIED"):
            errors.append(f"{label}.research_input_not_qualified_and_admitted")
        if ds.get("evidence_role") == "RESEARCH_INPUT" and (ds.get("pagination_complete") is not True or ds.get("status") != "COMPLETE"):
            errors.append(f"{label}.research_input_incomplete")
        if cutoff is not None:
            try:
                observed = parse_timestamp(ds.get("observed_at", ""), f"{label}.observed_at")
                if observed.utcoffset() is None:
                    errors.append(f"{label}.observed_at_must_be_timezone_aware")
                    continue
                if observed >= cutoff: errors.append(f"{label}.observation_at_or_after_cutoff")
                max_age = ds.get("max_age_seconds")
                # Stale observations remain durable diagnostic evidence. Only
                # research inputs are rejected for exceeding their age bound.
                if (ds.get("evidence_role") == "RESEARCH_INPUT" and isinstance(max_age, int)
                        and cutoff is not None and (cutoff-observed).total_seconds() > max_age):
                    errors.append(f"{label}.stale_observation")
                freshness = ds.get("freshness_seconds")
                if isinstance(freshness, int) and cutoff is not None and freshness != int((cutoff-observed).total_seconds()):
                    errors.append(f"{label}.freshness_metadata_mismatch")
                for timestamp_field in ("published_at", "available_at"):
                    timestamp_value = ds.get(timestamp_field)
                    if timestamp_value is None:
                        continue
                    try:
                        timestamp = parse_timestamp(timestamp_value, f"{label}.{timestamp_field}")
                        if timestamp.utcoffset() is None:
                            errors.append(f"{label}.{timestamp_field}_must_be_timezone_aware")
                        elif timestamp >= cutoff:
                            errors.append(f"{label}.{timestamp_field}_at_or_after_cutoff")
                    except (ValueError, TypeError, AttributeError) as exc:
                        errors.append(str(exc))
            except (ValueError, TypeError, AttributeError) as exc: errors.append(str(exc))
        if ds.get("status") == "UNAVAILABLE" and ds.get("evidence_role") == "RESEARCH_INPUT":
            errors.append(f"{label}.unavailable_cannot_be_research_input")
        if obj.get("status") == "COMPLETE" and ds.get("status") != "COMPLETE":
            errors.append(f"{label}.noncomplete_dataset_in_complete_manifest")
    if obj.get("content_digest") != digest(without_digest(obj)):
        errors.append("manifest.content_digest_mismatch")
    return errors


def validate_bundle(bundle: dict[str, Any], base: Path, registry: dict[str, Any] | None = None) -> list[str]:
    errors: list[str] = _schema_errors(bundle, "evidence_bundle.schema.json", "bundle")
    for key in ("bundle_id", "run_id", "attempt_id", "research_cutoff", "members", "content_digest"):
        if key not in bundle: errors.append(f"bundle.missing:{key}")
    if bundle.get("content_digest") != digest(without_digest(bundle)):
        errors.append("bundle.content_digest_mismatch")
    if bundle.get("bundle_id") != expected_bundle_id(bundle):
        errors.append("bundle.bundle_id_mismatch")
    try:
        cutoff = parse_timestamp(bundle.get("research_cutoff", ""), "bundle.research_cutoff")
        if cutoff.utcoffset() is None or cutoff.utcoffset().total_seconds() != 0:
            errors.append("bundle.research_cutoff_must_be_utc")
        errors.extend(validate_daily_cutoff_contract(bundle.get("run_id", ""), bundle.get("research_cutoff", ""), "EXCLUSIVE_UTC_BOUNDARY", "bundle"))
    except (ValueError, TypeError, AttributeError) as exc:
        errors.append(str(exc))
    members = bundle.get("members", [])
    if not isinstance(members, list): return errors + ["bundle.members_must_be_list"]
    if not members: errors.append("bundle.members_must_be_nonempty")
    seen: set[str] = set()
    seen_manifest_ids: set[str] = set()
    for i, member in enumerate(members):
        label = f"member[{i}]"
        if not isinstance(member, dict): errors.append(f"{label}.must_be_object"); continue
        sid = member.get("source_id")
        if sid in seen: errors.append(f"{label}.duplicate_source_identity:{sid}")
        seen.add(sid)
        manifest_id = member.get("manifest_id")
        if manifest_id in seen_manifest_ids: errors.append(f"{label}.duplicate_manifest_identity:{manifest_id}")
        seen_manifest_ids.add(manifest_id)
        path = (base / str(member.get("manifest_path", ""))).resolve()
        try:
            path.relative_to(base.resolve())
        except ValueError:
            errors.append(f"{label}.manifest_path_escapes_bundle_root"); continue
        try:
            manifest = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f"{label}.manifest_unreadable:{exc}"); continue
        errors.extend(validate_source_manifest(manifest, registry))
        if manifest.get("manifest_id") != member.get("manifest_id"):
            errors.append(f"{label}.manifest_identity_mismatch")
        if manifest.get("source", {}).get("source_id") != sid:
            errors.append(f"{label}.source_identity_mismatch")
        if manifest.get("content_digest") != member.get("manifest_digest"):
            errors.append(f"{label}.manifest_digest_binding_mismatch")
        for field in ("status", "qualification", "admissibility"):
            if manifest.get(field) != member.get(field):
                errors.append(f"{label}.{field}_state_mismatch")
        if manifest.get("run_id") != bundle.get("run_id") or manifest.get("attempt_id") != bundle.get("attempt_id"):
            errors.append(f"{label}.run_attempt_identity_mismatch")
        if manifest.get("research_cutoff") != bundle.get("research_cutoff"):
            errors.append(f"{label}.cutoff_identity_mismatch")
    return errors

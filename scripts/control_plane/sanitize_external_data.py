from __future__ import annotations

"""Deterministic boundary for untrusted JSON supplied by external providers."""

import argparse
import hashlib
import json
import math
import re
import sys
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "control_plane"))
from common import canonical_bytes, digest, write_new_json  # noqa: E402


class SanitizationError(ValueError):
    pass


class DuplicateKeyError(SanitizationError):
    pass


def _pairs_no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise DuplicateKeyError(f"duplicate_json_key:{key[:100]}")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise SanitizationError(f"unsupported_json_constant:{value}")


def load_external_json(raw: bytes, max_bytes: int) -> Any:
    if len(raw) > max_bytes:
        raise SanitizationError("payload_byte_limit_exceeded")
    try:
        text = raw.decode("utf-8", errors="strict")
        return json.loads(text, object_pairs_hook=_pairs_no_duplicates, parse_constant=_reject_constant)
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
        raise SanitizationError(f"malformed_or_unsupported_json:{type(exc).__name__}") from exc


def _walk(value: Any, depth: int = 0):
    yield value, depth
    if isinstance(value, dict):
        for key, child in value.items():
            yield from _walk(key, depth + 1)
            yield from _walk(child, depth + 1)
    elif isinstance(value, list):
        for child in value:
            yield from _walk(child, depth + 1)


def _strip_text(text: str, max_chars: int) -> tuple[str, list[str]]:
    # Keep hostile prose visible as inert quoted evidence. Remove control/format
    # characters and all URL destinations; HTML-escape prevents active markup.
    import html

    notes: list[str] = []
    normalized = unicodedata.normalize("NFKC", text)
    clean = "".join(ch for ch in normalized if unicodedata.category(ch) not in {"Cc", "Cf", "Cs"})
    if clean != normalized:
        notes.append("control_or_format_removed")
    url_pattern = r"(?i)\b[a-z][a-z0-9+.-]{1,20}://\S+|\b(?:javascript|data|file|mailto):\S+|\bwww\.\S+"
    if re.search(url_pattern, clean):
        clean = re.sub(url_pattern, "[url removed]", clean)
        notes.append("url_redacted")
    # Keep the text inert in both HTML and Markdown renderers.
    clean = clean.replace("\\", "／").replace("`", "´").replace("[", "［").replace("]", "］")
    clean = clean.replace("(", "（").replace(")", "）")
    if len(clean) > max_chars:
        clean = clean[:max_chars]
        notes.append("text_truncated")
    return html.escape(clean, quote=True), notes


def _depth_and_sizes(value: Any, policy: dict[str, Any]) -> list[dict[str, str]]:
    diagnostics: list[dict[str, str]] = []
    max_depth = int(policy["max_depth"])
    max_items = int(policy["max_collection_items"])
    for item, depth in _walk(value):
        if depth > max_depth:
            raise SanitizationError("nesting_depth_limit_exceeded")
        if isinstance(item, (list, dict)) and len(item) > max_items:
            raise SanitizationError("collection_size_limit_exceeded")
    return diagnostics


def _texts(value: Any, path: str, policy: dict[str, Any], out: list[dict[str, str]], diagnostics: list[dict[str, str]]) -> None:
    if isinstance(value, str):
        safe, notes = _strip_text(value, int(policy["max_string_chars"]))
        out.append({"path": path[:512], "text": safe})
        for note in notes:
            action = "TRUNCATED" if note == "text_truncated" else "REDACTED"
            diagnostics.append({"code": note, "path": path[:512], "action": action})
    elif isinstance(value, dict):
        for key, child in value.items():
            _texts(child, f"{path}.{key}", policy, out, diagnostics)
    elif isinstance(value, list):
        for i, child in enumerate(value):
            _texts(child, f"{path}[{i}]", policy, out, diagnostics)


def _numeric_records(payload: Any, policy: dict[str, Any], diagnostics: list[dict[str, str]]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    allowed = policy["record_fields"]
    aliases = policy["aliases"]
    wrappers = {"records", "data", "results", "structuredContent"}
    metadata = set(policy["metadata_fields"])

    def visit(node: Any, path: str) -> None:
        if isinstance(node, list):
            for i, item in enumerate(node[: int(policy["max_records"]) + 1]):
                visit(item, f"{path}[{i}]")
            if len(node) > int(policy["max_records"]):
                diagnostics.append({"code": "record_limit_exceeded", "path": path, "action": "REJECTED"})
            return
        if not isinstance(node, dict):
            diagnostics.append({"code": "unexpected_record_shape", "path": path, "action": "REJECTED"})
            return
        row = {k: v for k, v in node.items() if k in allowed or k in aliases}
        if not row:
            descended = False
            for key in wrappers:
                if key in node:
                    descended = True
                    visit(node[key], f"{path}.{key}")
            if not descended and node:
                diagnostics.append({"code": "unexpected_record_shape", "path": path[:512], "action": "REJECTED"})
            return
        normalized: dict[str, Any] = {}
        origins: dict[str, str] = {}
        conflicted = False
        for key, value in row.items():
            target = aliases.get(key, key)
            if target in normalized and normalized[target] != value:
                diagnostics.append({"code": "conflicting_semantic_alias", "path": f"{path}.{key}", "action": "REJECTED"})
                conflicted = True
                continue
            normalized[target] = value
            origins[target] = key
        for key in node:
            if key in allowed or key in aliases or key in metadata:
                continue
            diagnostics.append({"code": "unexpected_field_dropped", "path": f"{path}.{key}"[:512], "action": "DROPPED"})
        if conflicted:
            return
        for key, value in normalized.items():
            kind = allowed[key]
            if kind == "number":
                if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
                    diagnostics.append({"code": "invalid_numeric_field", "path": f"{path}.{origins[key]}", "action": "REJECTED"})
                    return
            elif kind == "integer":
                if isinstance(value, bool) or not isinstance(value, int):
                    diagnostics.append({"code": "invalid_integer_field", "path": f"{path}.{origins[key]}", "action": "REJECTED"})
                    return
            elif kind == "timestamp":
                if not isinstance(value, str):
                    diagnostics.append({"code": "invalid_timestamp_field", "path": f"{path}.{origins[key]}", "action": "REJECTED"})
                    return
                try:
                    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
                    if dt.utcoffset() is None:
                        raise ValueError
                except ValueError:
                    diagnostics.append({"code": "invalid_timestamp_field", "path": f"{path}.{origins[key]}", "action": "REJECTED"})
                    return
            elif kind == "identifier":
                if not isinstance(value, str) or not re.fullmatch(policy["identifier_pattern"], value) or re.search(r"\.\.", value):
                    diagnostics.append({"code": "invalid_or_path_like_identifier", "path": f"{path}.{origins[key]}", "action": "REJECTED"})
                    return
            elif kind == "interval":
                if not isinstance(value, str) or not re.fullmatch(policy["interval_pattern"], value):
                    diagnostics.append({"code": "invalid_interval_label", "path": f"{path}.{origins[key]}", "action": "REJECTED"})
                    return
        for key, value in list(normalized.items()):
            if allowed[key] == "identifier":
                opaque = hashlib.sha256(canonical_bytes({"policy_id": policy["policy_id"], "policy_version": policy["policy_version"], "field": key, "external_identifier": value})).hexdigest()
                normalized[key] = "extid:" + opaque
        records.append(normalized)

    if not isinstance(payload, dict):
        raise SanitizationError("top_level_payload_must_be_object")
    unexpected = set(payload) - set(policy["allowed_top_level_fields"])
    for key in sorted(unexpected):
        diagnostics.append({"code": "unexpected_top_level_field_dropped", "path": f"$.{key}"[:512], "action": "DROPPED"})
    for key in wrappers:
        if key in payload:
            visit(payload[key], f"$.{key}")
    if len(records) > int(policy["max_records"]):
        raise SanitizationError("record_limit_exceeded")
    return records


def build_artifacts(raw: bytes, spec: dict[str, Any], policy: dict[str, Any], raw_path: str,
                    raw_record_path: str | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
    payload = load_external_json(raw, int(policy["max_payload_bytes"]))
    _depth_and_sizes(payload, policy)
    if not isinstance(payload, dict):
        raise SanitizationError("top_level_payload_must_be_object")
    source = spec.get("source")
    if not isinstance(source, dict) or not source.get("source_id") or not re.fullmatch(r"sha256:[0-9a-f]{64}", source.get("identity_digest", "")):
        raise SanitizationError("source_identity_provenance_required")
    for field in ("capability_id", "dataset_id", "retrieval_id", "retrieved_at"):
        if not isinstance(spec.get(field), str) or not spec[field]:
            raise SanitizationError(f"raw_provenance_missing:{field}")
    raw_digest = "sha256:" + hashlib.sha256(raw).hexdigest()
    raw_base = {
        "schema_version": "1.0", "raw_artifact_id": "raw-" + hashlib.sha256(canonical_bytes({"source": source, "capability_id": spec["capability_id"], "dataset_id": spec["dataset_id"], "retrieval_id": spec["retrieval_id"], "raw_digest": raw_digest})).hexdigest()[:24],
        "source": source, "capability_id": spec["capability_id"], "dataset_id": spec["dataset_id"],
        "retrieved_at": spec["retrieved_at"], "retrieval_id": spec["retrieval_id"], "encoding": "utf-8", "byte_length": len(raw), "raw_digest": raw_digest, "raw_path": raw_path,
    }
    raw_record = {**raw_base, "content_digest": digest(raw_base)}
    diagnostics: list[dict[str, str]] = []
    text_evidence: list[dict[str, str]] = []
    _texts(payload, "$", policy, text_evidence, diagnostics)
    records = _numeric_records(payload, policy, diagnostics)
    policy_identity = {k: v for k, v in policy.items() if k != "content_digest"}
    base = {
        "schema_version": "1.0", "raw_artifact_id": raw_record["raw_artifact_id"], "raw_digest": raw_digest, "raw_path": raw_path,
        "raw_record_path": raw_record_path or (raw_path + ".artifact.json"),
        "raw_artifact_record_digest": raw_record["content_digest"],
        "retrieval_id": spec["retrieval_id"], "retrieved_at": spec["retrieved_at"],
        "source": source, "capability_id": spec["capability_id"], "dataset_id": spec["dataset_id"],
        "policy": {"policy_id": policy["policy_id"], "policy_version": policy["policy_version"], "policy_digest": digest(policy_identity)},
        "records": records, "text_evidence": text_evidence, "diagnostics": diagnostics,
    }
    base["sanitized_artifact_id"] = "san-" + hashlib.sha256(canonical_bytes(base)).hexdigest()[:24]
    sanitized = {**base, "content_digest": digest(base)}
    return raw_record, sanitized


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw", required=True, help="immutable captured raw JSON bytes")
    parser.add_argument("--spec", required=True, help="file-bound source/retrieval provenance JSON")
    parser.add_argument("--policy", default=str(ROOT / "config" / "external-data-sanitization-policy.json"))
    parser.add_argument("--raw-out", required=True)
    parser.add_argument("--raw-bytes-out", required=True)
    parser.add_argument("--sanitized-out", required=True)
    args = parser.parse_args()
    try:
        raw_path = Path(args.raw)
        raw = raw_path.read_bytes()
        spec = json.loads(Path(args.spec).read_text(encoding="utf-8"))
        policy = json.loads(Path(args.policy).read_text(encoding="utf-8"))
        raw_bytes_out = Path(args.raw_bytes_out)
        raw_bytes_out.parent.mkdir(parents=True, exist_ok=True)
        with raw_bytes_out.open("xb") as handle:
            handle.write(raw)
        raw_record, sanitized = build_artifacts(raw, spec, policy, raw_bytes_out.as_posix(), Path(args.raw_out).as_posix())
        write_new_json(args.raw_out, raw_record)
        write_new_json(args.sanitized_out, sanitized)
    except (OSError, json.JSONDecodeError, SanitizationError, FileExistsError, KeyError, TypeError, ValueError) as exc:
        print(f"SANITIZATION_BLOCKED:{exc}")
        return 2
    print(f"PASS:{args.raw_out}:{args.sanitized_out}:{sanitized['sanitized_artifact_id']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

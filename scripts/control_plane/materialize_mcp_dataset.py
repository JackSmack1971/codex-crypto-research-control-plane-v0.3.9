from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Iterable

sys.dont_write_bytecode = True

from common import DAILY_CUTOFF_SEMANTICS, validate_daily_cutoff_contract

TRUNCATION_MARKERS = ("[truncated:", "... truncated", "<truncated>")


def _load_rows(path: Path) -> list[dict[str, Any]]:
    text = path.read_text(encoding="utf-8")
    lower = text.lower()
    if any(marker in lower for marker in TRUNCATION_MARKERS):
        raise ValueError(f"truncation_marker:{path}")
    suffix = path.suffix.lower()
    if suffix == ".jsonl":
        rows = [json.loads(line) for line in text.splitlines() if line.strip()]
    elif suffix == ".json":
        obj = json.loads(text)
        rows = obj.get("rows") if isinstance(obj, dict) and "rows" in obj else obj
        if not isinstance(rows, list):
            raise ValueError(f"expected_json_array_or_rows:{path}")
    elif suffix == ".csv":
        rows = list(csv.DictReader(text.splitlines()))
    else:
        raise ValueError(f"unsupported_chunk_extension:{path.suffix}")
    if not all(isinstance(row, dict) for row in rows):
        raise ValueError(f"rows_must_be_objects:{path}")
    return rows


def _canonical_row(row: dict[str, Any]) -> str:
    return json.dumps(row, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _sha256_bytes(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _parse_csv_list(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def _key(row: dict[str, Any], fields: list[str]) -> tuple[str, ...]:
    return tuple(str(row.get(field, "")) for field in fields)


def _sort_rows(rows: list[dict[str, Any]], fields: list[str]) -> None:
    if fields:
        rows.sort(key=lambda row: _key(row, fields))
    else:
        rows.sort(key=_canonical_row)


def _validate_unique(rows: Iterable[dict[str, Any]], fields: list[str]) -> None:
    if not fields:
        return
    seen: set[tuple[str, ...]] = set()
    for idx, row in enumerate(rows):
        missing = [field for field in fields if field not in row]
        if missing:
            raise ValueError(f"row[{idx}].missing_key_fields:{','.join(missing)}")
        key = _key(row, fields)
        if key in seen:
            raise ValueError(f"duplicate_key:{fields}:{key}")
        seen.add(key)


def _load_spec(path: Path) -> dict[str, Any]:
    obj = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(obj, dict):
        raise ValueError("spec_must_be_object")
    allowed = {
        "schema_version", "chunks", "dataset_id", "capability_id", "evidence_role", "run_id", "attempt_id", "market",
        "endpoint_path", "params", "requirement", "research_cutoff", "research_cutoff_semantics", "retrieved_at",
        "as_of", "expected_rows", "sort_fields", "key_fields", "out_dir",
    }
    extra = sorted(set(obj) - allowed)
    if extra:
        raise ValueError(f"spec_unexpected_fields:{','.join(extra)}")
    required = allowed - {"out_dir"}
    missing = sorted(k for k in required if k not in obj)
    if missing:
        raise ValueError(f"spec_missing_fields:{','.join(missing)}")
    if obj.get("schema_version") != 1:
        raise ValueError("spec_schema_version_must_equal_1")
    if not isinstance(obj.get("chunks"), list) or not obj["chunks"] or not all(isinstance(x, str) and x for x in obj["chunks"]):
        raise ValueError("spec_chunks_must_be_nonempty_string_array")
    for key in ("dataset_id", "capability_id", "run_id", "attempt_id", "market", "endpoint_path", "research_cutoff", "research_cutoff_semantics", "retrieved_at", "as_of"):
        if not isinstance(obj.get(key), str) or not obj[key]:
            raise ValueError(f"spec_{key}_must_be_nonempty_string")
    if not obj["endpoint_path"].startswith("/"):
        raise ValueError("spec_endpoint_path_must_start_slash")
    if obj.get("research_cutoff_semantics") != DAILY_CUTOFF_SEMANTICS:
        raise ValueError("spec_research_cutoff_semantics_invalid")
    contract_errors = validate_daily_cutoff_contract(obj["run_id"], obj["research_cutoff"], obj["research_cutoff_semantics"], "materialization_spec")
    if contract_errors:
        raise ValueError(";".join(contract_errors))
    if not isinstance(obj.get("params"), dict):
        raise ValueError("spec_params_must_be_object")
    if obj.get("evidence_role") not in {"RESEARCH_INPUT", "DIAGNOSTIC"}:
        raise ValueError("spec_evidence_role_invalid")
    if obj.get("requirement") not in {"CORE", "ENRICHMENT", "EVENT_OPTIONAL"}:
        raise ValueError("spec_requirement_invalid")
    if not isinstance(obj.get("expected_rows"), int) or isinstance(obj.get("expected_rows"), bool) or obj["expected_rows"] < 0:
        raise ValueError("spec_expected_rows_must_be_nonnegative_integer")
    for key in ("sort_fields", "key_fields"):
        if not isinstance(obj.get(key), list) or not all(isinstance(x, str) and x for x in obj[key]):
            raise ValueError(f"spec_{key}_must_be_string_array")
    if "out_dir" in obj and (not isinstance(obj["out_dir"], str) or not obj["out_dir"]):
        raise ValueError("spec_out_dir_must_be_nonempty_string")
    return obj


def main() -> int:
    ap = argparse.ArgumentParser(description="Materialize bounded Massive MCP query_data chunks into an immutable canonical JSONL dataset.")
    ap.add_argument("chunks", nargs="*")
    ap.add_argument("--spec-file")
    ap.add_argument("--dataset-id")
    ap.add_argument("--run-id")
    ap.add_argument("--attempt-id")
    ap.add_argument("--market")
    ap.add_argument("--endpoint-path")
    ap.add_argument("--params-json")
    ap.add_argument("--requirement", choices=["CORE", "ENRICHMENT", "EVENT_OPTIONAL"])
    ap.add_argument("--research-cutoff")
    ap.add_argument("--retrieved-at")
    ap.add_argument("--as-of")
    ap.add_argument("--expected-rows", type=int)
    ap.add_argument("--sort-fields")
    ap.add_argument("--key-fields")
    ap.add_argument("--out-dir")
    args = ap.parse_args()

    try:
        if args.spec_file:
            spec = _load_spec(Path(args.spec_file))
            if args.chunks or any(getattr(args, name) is not None for name in (
                "dataset_id", "run_id", "attempt_id", "market", "endpoint_path", "requirement",
                "research_cutoff", "retrieved_at", "as_of", "expected_rows",
                "params_json", "sort_fields", "key_fields", "out_dir",
            )):
                raise ValueError("spec_file_cannot_be_combined_with_inline_materialization_metadata")
            chunks = spec["chunks"]
            dataset_id = spec["dataset_id"]
            capability_id = spec["capability_id"]
            evidence_role = spec["evidence_role"]
            run_id = spec["run_id"]
            attempt_id = spec["attempt_id"]
            market = spec["market"]
            endpoint_path = spec["endpoint_path"]
            params = spec["params"]
            requirement = spec["requirement"]
            research_cutoff = spec["research_cutoff"]
            research_cutoff_semantics = spec["research_cutoff_semantics"]
            retrieved_at = spec["retrieved_at"]
            as_of = spec["as_of"]
            expected_rows = spec["expected_rows"]
            sort_fields = list(spec["sort_fields"])
            key_fields = list(spec["key_fields"])
            out_root = spec.get("out_dir", "research/data")
        else:
            required_inline = {
                "dataset_id": args.dataset_id, "run_id": args.run_id, "attempt_id": args.attempt_id,
                "market": args.market, "endpoint_path": args.endpoint_path, "requirement": args.requirement,
                "research_cutoff": args.research_cutoff, "retrieved_at": args.retrieved_at,
                "as_of": args.as_of, "expected_rows": args.expected_rows,
            }
            missing = [k for k, v in required_inline.items() if v is None]
            if not args.chunks:
                missing.append("chunks")
            if missing:
                raise ValueError(f"missing_inline_arguments:{','.join(missing)}")
            chunks = args.chunks
            dataset_id = args.dataset_id
            capability_id = dataset_id
            evidence_role = "RESEARCH_INPUT"
            run_id = args.run_id
            attempt_id = args.attempt_id
            market = args.market
            endpoint_path = args.endpoint_path
            params = json.loads(args.params_json or "{}")
            requirement = args.requirement
            research_cutoff = args.research_cutoff
            research_cutoff_semantics = DAILY_CUTOFF_SEMANTICS
            contract_errors = validate_daily_cutoff_contract(run_id, research_cutoff, research_cutoff_semantics, "materialization_inline")
            if contract_errors:
                raise ValueError(";".join(contract_errors))
            retrieved_at = args.retrieved_at
            as_of = args.as_of
            expected_rows = args.expected_rows
            sort_fields = _parse_csv_list(args.sort_fields or "")
            key_fields = _parse_csv_list(args.key_fields or "")
            out_root = args.out_dir or "research/data"

        if not isinstance(params, dict):
            raise ValueError("params_json_must_be_object")
        rows: list[dict[str, Any]] = []
        chunk_paths = [Path(value) for value in chunks]
        for path in chunk_paths:
            rows.extend(_load_rows(path))
        if len(rows) != expected_rows:
            raise ValueError(f"row_count_mismatch:expected={expected_rows}:actual={len(rows)}")
        _validate_unique(rows, key_fields)
        _sort_rows(rows, sort_fields)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"MATERIALIZATION_ERROR:{exc}")
        return 2

    out_dir = Path(out_root) / attempt_id
    data_path = out_dir / f"{dataset_id}.jsonl"
    meta_path = out_dir / f"{dataset_id}.meta.json"
    out_dir.mkdir(parents=True, exist_ok=True)
    if data_path.exists() or meta_path.exists():
        print(f"IMMUTABLE_CONFLICT:{data_path if data_path.exists() else meta_path}")
        return 3

    body = "".join(_canonical_row(row) + "\n" for row in rows).encode("utf-8")
    data_digest = _sha256_bytes(body)
    metadata = {
        "dataset_id": dataset_id,
        "capability_id": capability_id,
        "evidence_role": evidence_role,
        "run_id": run_id,
        "attempt_id": attempt_id,
        "market": market,
        "endpoint_path": endpoint_path,
        "params": params,
        "requirement": requirement,
        "research_cutoff": research_cutoff,
        "research_cutoff_semantics": research_cutoff_semantics,
        "retrieved_at": retrieved_at,
        "as_of": as_of,
        "row_count": len(rows),
        "sort_fields": sort_fields,
        "key_fields": key_fields,
        "data_path": data_path.as_posix(),
        "data_digest": data_digest,
        "source_chunks": [path.as_posix() for path in chunk_paths],
        "materialization_status": "VERIFIED",
    }
    try:
        with data_path.open("xb") as handle:
            handle.write(body)
        with meta_path.open("x", encoding="utf-8", newline="\n") as handle:
            json.dump(metadata, handle, indent=2, sort_keys=True, ensure_ascii=False)
            handle.write("\n")
    except FileExistsError:
        print(f"IMMUTABLE_CONFLICT:{data_path}")
        return 3

    print(json.dumps({"data": data_path.as_posix(), "metadata": meta_path.as_posix(), "row_count": len(rows), "data_digest": data_digest}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


def load_json(path: str | Path) -> dict[str, Any]:
    p = Path(path)
    with p.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError(f"{p}: expected a JSON object")
    return data


def canonical_bytes(data: Any) -> bytes:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def digest(data: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical_bytes(data)).hexdigest()


def write_new_json(path: str | Path, data: Any) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    if p.exists():
        raise FileExistsError(f"immutable artifact already exists: {p}")
    payload = json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    with p.open("x", encoding="utf-8", newline="\n") as f:
        f.write(payload)
    return p


def require_fields(obj: dict[str, Any], fields: list[str], label: str) -> list[str]:
    missing = [field for field in fields if field not in obj or obj[field] in ("", None)]
    return [f"{label}.missing:{field}" for field in missing]


def parse_timestamp(value: str, label: str) -> datetime:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label}: invalid ISO-8601 timestamp: {value!r}") from exc


DAILY_CUTOFF_SEMANTICS = "EXCLUSIVE_UTC_BOUNDARY"


def expected_daily_cutoff(run_id: str) -> datetime:
    match = __import__("re").fullmatch(r"(\d{4}-\d{2}-\d{2})-eod", run_id or "")
    if not match:
        raise ValueError(f"run_id_not_daily_eod:{run_id!r}")
    research_date = datetime.fromisoformat(match.group(1)).replace(tzinfo=timezone.utc)
    return research_date + timedelta(days=1)


def validate_daily_cutoff_contract(run_id: str, cutoff_value: str, semantics: str, label: str) -> list[str]:
    errors: list[str] = []
    if __import__("re").fullmatch(r"\d{4}-\d{2}-\d{2}-eod", run_id or "") is None:
        return errors
    if semantics != DAILY_CUTOFF_SEMANTICS:
        errors.append(f"{label}.cutoff_semantics_must_be_{DAILY_CUTOFF_SEMANTICS}")
        return errors
    try:
        actual = parse_timestamp(cutoff_value, f"{label}.research_cutoff")
        expected = expected_daily_cutoff(run_id)
        if actual != expected:
            errors.append(
                f"{label}.research_cutoff_must_equal_next_utc_midnight:"
                f"expected={expected.isoformat().replace('+00:00','Z')}:actual={cutoff_value}"
            )
    except ValueError as exc:
        errors.append(str(exc))
    return errors

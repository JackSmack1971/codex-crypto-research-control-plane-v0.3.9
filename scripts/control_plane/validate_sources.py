from __future__ import annotations
import json, sys
from pathlib import Path
sys.dont_write_bytecode = True
from common import digest
from validate_artifact import validate as validate_schema

ROOT=Path(__file__).resolve().parents[2]
def identity_payload(source: dict) -> dict:
    return {key:source.get(key) for key in ("source_id","provider","runtime","transport","adapter_id","adapter_version","capability_ids")}

def validate(registry: dict) -> list[str]:
    schema=json.loads((ROOT/"schemas/source_registry.schema.json").read_text(encoding="utf-8"))
    errors=[f"registry.schema:{e}" for e in validate_schema(registry,schema)]; seen=set()
    sources = registry.get("sources", []) if isinstance(registry,dict) else []
    if not isinstance(sources,list): return errors
    for i, source in enumerate(sources):
        if not isinstance(source,dict): continue
        sid=source.get("source_id")
        if sid in seen: errors.append(f"source[{i}].duplicate_source_id:{sid}")
        seen.add(sid)
        identity=identity_payload(source)
        if source.get("identity_digest") != digest(identity): errors.append(f"source[{i}].identity_digest_mismatch")
    return errors

def validate_qualification(record: dict, registry: dict, now: str) -> list[str]:
    schema=json.loads((ROOT/"schemas/source_qualification.schema.json").read_text(encoding="utf-8"))
    errors=[f"qualification.schema:{e}" for e in validate_schema(record,schema)]
    sources={item.get("source_id"):item for item in registry.get("sources",[])}
    source=sources.get(record.get("source_id"))
    if source is None: errors.append("qualification.source_not_registered")
    elif record.get("identity_digest") != source.get("identity_digest"): errors.append("qualification.source_identity_mismatch")
    try:
        from common import parse_timestamp
        observed=parse_timestamp(record.get("observed_at",""),"qualification.observed_at")
        expires=parse_timestamp(record.get("expires_at",""),"qualification.expires_at")
        instant=parse_timestamp(now,"qualification.validation_time")
        if any(value.utcoffset() is None for value in (observed,expires,instant)): errors.append("qualification.timestamps_must_be_timezone_aware")
        if expires <= observed: errors.append("qualification.expiry_not_after_observation")
        if expires <= instant and record.get("status") != "EXPIRED": errors.append("qualification.expired_status_required")
        if expires > instant and record.get("status") == "QUALIFIED" and (record.get("discovery_status") != "DISCOVERED" or record.get("access_status") != "SUCCEEDED" or not record.get("evidence")): errors.append("qualification.missing_observed_qualification_evidence")
    except (ValueError,TypeError,AttributeError) as exc: errors.append(str(exc))
    return errors
def main() -> int:
    p=Path(sys.argv[1]) if len(sys.argv)>1 else ROOT/"config/source-registry.json"
    obj=json.loads(p.read_text(encoding="utf-8")); errors=validate(obj)
    if errors: print("\n".join(errors)); return 1
    print(f"PASS:{p}"); return 0
if __name__=="__main__": raise SystemExit(main())

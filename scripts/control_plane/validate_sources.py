from __future__ import annotations
import json, sys
from pathlib import Path
sys.dont_write_bytecode = True
from common import digest

ROOT=Path(__file__).resolve().parents[2]
def validate(registry: dict) -> list[str]:
    errors=[]; seen=set()
    for i, source in enumerate(registry.get("sources", [])):
        sid=source.get("source_id")
        if sid in seen: errors.append(f"source[{i}].duplicate_source_id:{sid}")
        seen.add(sid)
        identity={k:v for k,v in source.items() if k!="identity_digest"}
        if source.get("identity_digest") != digest(identity): errors.append(f"source[{i}].identity_digest_mismatch")
    return errors
def main() -> int:
    p=Path(sys.argv[1]) if len(sys.argv)>1 else ROOT/"config/source-registry.json"
    obj=json.loads(p.read_text(encoding="utf-8")); errors=validate(obj)
    if errors: print("\n".join(errors)); return 1
    print(f"PASS:{p}"); return 0
if __name__=="__main__": raise SystemExit(main())

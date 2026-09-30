from __future__ import annotations
import argparse, hashlib, json, sys
from pathlib import Path
sys.dont_write_bytecode = True
from common import digest, write_new_json
from source_evidence import validate_source_manifest

def build(paths: list[Path], run_id: str, attempt_id: str, cutoff: str, root: Path) -> dict:
    members=[]; seen=set()
    for raw in paths:
        path=raw.resolve(); obj=json.loads(path.read_text(encoding="utf-8")); errors=validate_source_manifest(obj)
        if errors: raise ValueError(f"{path}:"+";".join(errors))
        source=obj["source"]["source_id"]
        if source in seen: raise ValueError(f"duplicate_source_identity:{source}")
        seen.add(source)
        if obj.get("run_id") != run_id or obj.get("attempt_id") != attempt_id or obj.get("research_cutoff") != cutoff:
            raise ValueError(f"source_manifest_identity_mismatch:{source}")
        members.append({"source_id":source,"manifest_id":obj["manifest_id"],"manifest_path":path.relative_to(root.resolve()).as_posix(),"manifest_digest":obj["content_digest"],"status":obj["status"],"qualification":obj["qualification"],"admissibility":obj["admissibility"]})
    members.sort(key=lambda item:item["source_id"])
    base={"schema_version":"1.0","run_id":run_id,"attempt_id":attempt_id,"research_cutoff":cutoff,"members":members}
    bundle_id="eb-"+hashlib.sha256(json.dumps(base,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()).hexdigest()[:24]
    obj={"bundle_id":bundle_id,**base}; obj["content_digest"]=digest(obj)
    return obj

def main() -> int:
    ap=argparse.ArgumentParser(); ap.add_argument("--run-id",required=True); ap.add_argument("--attempt-id",required=True); ap.add_argument("--research-cutoff",required=True); ap.add_argument("--root",default="."); ap.add_argument("--out",required=True); ap.add_argument("manifests",nargs="+"); args=ap.parse_args()
    out=Path(args.out); out.parent.mkdir(parents=True,exist_ok=True)
    try:
        obj=build([Path(p) for p in args.manifests],args.run_id,args.attempt_id,args.research_cutoff,Path(args.root))
        write_new_json(out,obj)
    except (OSError,ValueError,json.JSONDecodeError) as exc:
        print(f"BUNDLE_BLOCKED:{exc}"); return 2
    except FileExistsError:
        print(f"IMMUTABLE_CONFLICT:{out}"); return 3
    print(out); return 0
if __name__=="__main__": raise SystemExit(main())

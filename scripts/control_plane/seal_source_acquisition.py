from __future__ import annotations
import argparse, json, sys
from pathlib import Path
sys.dont_write_bytecode = True
from common import digest, write_new_json
from source_evidence import validate_source_manifest

def main() -> int:
    ap=argparse.ArgumentParser(); ap.add_argument("payload"); ap.add_argument("--out", required=True); args=ap.parse_args()
    obj=json.loads(Path(args.payload).read_text(encoding="utf-8")); obj["content_digest"]=digest({k:v for k,v in obj.items() if k!="content_digest"})
    errors=validate_source_manifest(obj)
    if errors: print("\n".join(errors)); return 2
    try: write_new_json(args.out,obj)
    except FileExistsError: print("IMMUTABLE_CONFLICT:"+args.out); return 3
    print(args.out); return 0
if __name__=="__main__": raise SystemExit(main())

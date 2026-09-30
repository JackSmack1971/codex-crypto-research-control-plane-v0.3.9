from __future__ import annotations
import argparse, json, sys
from pathlib import Path
sys.dont_write_bytecode = True
from source_evidence import validate_bundle

def main() -> int:
    ap=argparse.ArgumentParser(); ap.add_argument("bundle"); ap.add_argument("--root",default="."); args=ap.parse_args(); path=Path(args.bundle)
    bundle=json.loads(path.read_text(encoding="utf-8")); errors=validate_bundle(bundle,Path(args.root))
    if errors: print("\n".join(errors)); return 2
    print("PASS:"+str(path)); return 0
if __name__=="__main__": raise SystemExit(main())

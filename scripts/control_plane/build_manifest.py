from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import date
from pathlib import Path

sys.dont_write_bytecode = True

from path_policy import include_in_release_manifest

ROOT = Path(__file__).resolve().parents[2]
def include(path: Path) -> bool:
    return include_in_release_manifest(path, ROOT)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--generated-at", default=date.today().isoformat())
    args = ap.parse_args()

    version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    entries = []
    for path in sorted((p for p in ROOT.rglob("*") if include(p)), key=lambda p: p.as_posix()):
        data = path.read_bytes()
        entries.append({
            "path": path.relative_to(ROOT).as_posix(),
            "sha256": hashlib.sha256(data).hexdigest(),
            "bytes": len(data),
        })
    manifest = {
        "name": "codex-crypto-research-control-plane",
        "version": version,
        "generated_at": args.generated_at,
        "file_count": len(entries),
        "files": entries,
    }
    out = ROOT / "CONTROL_PLANE_MANIFEST.json"
    out.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"wrote {out} with {len(entries)} files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

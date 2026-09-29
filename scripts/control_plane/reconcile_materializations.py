from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

sys.dont_write_bytecode = True

from common import load_json, write_new_json


def _norm(value: Any) -> str:
    return Path(str(value)).as_posix()


def reconcile(acquisition_path: Path, data_root: Path) -> dict[str, Any]:
    acquisition = load_json(acquisition_path)
    run_id = acquisition.get("run_id")
    attempt_id = acquisition.get("attempt_id")
    attempt_dir = data_root / str(attempt_id)

    manifested_inputs: list[str] = []
    diagnostics: list[str] = []
    orphaned_inputs: list[str] = []
    mismatches: list[str] = []

    manifest_by_id: dict[str, dict[str, Any]] = {}
    for item in acquisition.get("datasets", []):
        if isinstance(item, dict) and item.get("materialization_status") == "VERIFIED":
            dataset_id = item.get("dataset_id")
            if isinstance(dataset_id, str):
                manifest_by_id[dataset_id] = item

    seen_research_inputs: set[str] = set()
    if attempt_dir.exists():
        meta_paths = sorted(attempt_dir.glob("*.meta.json"))
    else:
        meta_paths = []

    for meta_path in meta_paths:
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception as exc:
            mismatches.append(f"invalid_metadata:{meta_path.as_posix()}:{exc}")
            continue
        dataset_id = meta.get("dataset_id")
        role = meta.get("evidence_role")
        label = str(dataset_id or meta_path.stem)
        if meta.get("run_id") != run_id or meta.get("attempt_id") != attempt_id:
            mismatches.append(f"identity_mismatch:{label}")
            continue
        if role == "DIAGNOSTIC":
            diagnostics.append(label)
            if label in manifest_by_id:
                mismatches.append(f"diagnostic_listed_as_research_input:{label}")
            continue
        if role != "RESEARCH_INPUT":
            orphaned_inputs.append(f"unclassified:{label}")
            continue
        manifest = manifest_by_id.get(label)
        if manifest is None:
            orphaned_inputs.append(label)
            continue
        seen_research_inputs.add(label)
        checks = {
            "path": (_norm(meta.get("data_path")), _norm(manifest.get("materialized_path"))),
            "digest": (str(meta.get("data_digest")), str(manifest.get("materialized_digest"))),
            "row_count": (str(meta.get("row_count")), str(manifest.get("materialized_row_count"))),
            "capability_id": (str(meta.get("capability_id")), str(manifest.get("capability_id"))),
            "requirement": (str(meta.get("requirement")), str(manifest.get("requirement"))),
        }
        bad = [name for name, (left, right) in checks.items() if left != right]
        if bad:
            mismatches.append(f"manifest_metadata_mismatch:{label}:{','.join(bad)}")
        else:
            manifested_inputs.append(label)

    for dataset_id in sorted(manifest_by_id):
        if dataset_id not in seen_research_inputs:
            mismatches.append(f"manifested_materialization_missing_metadata:{dataset_id}")

    status = "PASS" if not orphaned_inputs and not mismatches else "BLOCK"
    return {
        "run_id": run_id,
        "attempt_id": attempt_id,
        "acquisition_path": acquisition_path.as_posix(),
        "data_dir": attempt_dir.as_posix(),
        "status": status,
        "manifested_inputs": sorted(set(manifested_inputs)),
        "diagnostics": sorted(set(diagnostics)),
        "orphaned_inputs": sorted(set(orphaned_inputs)),
        "mismatches": sorted(set(mismatches)),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Reconcile durable materializations against the sealed acquisition manifest.")
    ap.add_argument("acquisition")
    ap.add_argument("--data-root", default="research/data")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    try:
        report = reconcile(Path(args.acquisition), Path(args.data_root))
        write_new_json(args.out, report)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"MATERIALIZATION_RECONCILIATION_ERROR:{exc}")
        return 2
    print(json.dumps(report, sort_keys=True))
    return 0 if report["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())

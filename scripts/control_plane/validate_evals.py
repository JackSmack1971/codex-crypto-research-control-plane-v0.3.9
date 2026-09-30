from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_SKILLS = {
    "daily-research-run",
    "factor-research",
    "candidate-validation",
    "methodology-audit",
    "oos-scorekeeping",
}


def load_jsonl(path: Path) -> list[dict]:
    rows = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}:{number}: {exc}") from exc
        if not isinstance(row, dict):
            raise ValueError(f"{path}:{number}: expected JSON object")
        rows.append(row)
    return rows


def main() -> int:
    errors: list[str] = []
    routing = load_jsonl(ROOT / "evals" / "routing_cases.jsonl")
    counts = Counter(row.get("kind") for row in routing)
    expected_counts = {"positive": 20, "negative": 20, "neighbor": 10}
    if dict(counts) != expected_counts:
        errors.append(f"routing-counts:{dict(counts)} expected:{expected_counts}")
    ids = [row.get("id") for row in routing]
    if len(ids) != len(set(ids)):
        errors.append("routing-duplicate-ids")
    for row in routing:
        skill = row.get("expected_skill")
        if skill is not None and skill not in WORKFLOW_SKILLS:
            errors.append(f"routing-unknown-skill:{row.get('id')}:{skill}")
    positive_by_skill = Counter(row.get("expected_skill") for row in routing if row.get("kind") == "positive")
    if set(positive_by_skill) != WORKFLOW_SKILLS or any(count != 4 for count in positive_by_skill.values()):
        errors.append(f"routing-positive-balance:{dict(positive_by_skill)}")

    tasks = load_jsonl(ROOT / "evals" / "task_cases.jsonl")
    task_counts = Counter(row.get("kind") for row in tasks)
    if task_counts != Counter({"task": 10, "failure": 20}):
        errors.append(f"task-counts:{dict(task_counts)}")
    for row in tasks:
        if row.get("skill") not in WORKFLOW_SKILLS:
            errors.append(f"task-unknown-skill:{row.get('id')}:{row.get('skill')}")
        if not row.get("success_criteria"):
            errors.append(f"task-missing-rubric:{row.get('id')}")

    fin_data = load_jsonl(ROOT / "evals" / "fin_data_qualification_cases.jsonl")
    fin_ids = [row.get("id") for row in fin_data]
    fin_scenarios = {row.get("scenario") for row in fin_data}
    required_fin_scenarios = {
        "unavailable_endpoint", "missing_tool", "malformed_response", "stale_response",
        "schema_drift", "partial_capability_loss", "successful_qualification",
    }
    if len(fin_ids) != len(set(fin_ids)) or fin_scenarios != required_fin_scenarios:
        errors.append(f"fin-data-eval-coverage:{sorted(fin_scenarios)}")

    if errors:
        print("\n".join(errors))
        return 1
    print("PASS: routing corpus 20 positive / 20 negative / 10 neighbor; task corpus 10 representative / 20 failure; Fin Data qualification 7 scenarios")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

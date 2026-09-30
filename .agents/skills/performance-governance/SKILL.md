---
name: performance-governance
description: Govern trust in forecasts/signals from accumulated immutable out-of-sample outcomes. Use for hedge-fund performance review, calibration/drift assessment, or policy-authorized continued use, research, quarantine, or retirement decisions; do not use for scoring one forecast, backtest discovery, or rewriting historical forecasts.
---

**Repository path contract:** paths such as `config/...`, `scripts/...`, `docs/...`, `schemas/...`, `research/...`, and `workflows/...` are relative to the active project root (the directory containing `AGENTS.md` and `.codex/config.toml`), **not** relative to this installed Skill directory. Never walk `..` from the Skill installation to find project files. Never synthesize or reuse an absolute repository path from memory, prior runs, package names, or examples. First inspect the current working directory and verify the two project-root sentinels. If they are absent, do not guess a drive/path; fail project-root resolution explicitly.

# Performance governance

Own the feedback loop from matured OOS evidence back into research and signal governance. It evaluates evidence about live-like research performance; it does not manufacture new backtests or alter historical forecasts.

## Inputs

Use only immutable forecasts plus provenance-complete outcome records created by `$oos-scorekeeping`. Read the repository's authoritative performance, research-state, risk, and promotion/retirement policies when present. If the repository does not define a decision threshold or state transition, keep the result advisory and do not invent one.

## Workflow

1. Define the review population before calculating results: forecast/signal identity, horizons, assets/universe, date range, and inclusion/exclusion rules. Exclude unmatured horizons from performance metrics rather than treating them as failures or zeros.
2. Verify one-to-one binding between each included frozen forecast and its outcome record; detect missing outcomes, duplicate scores, rewritten forecasts, or inconsistent scorer versions. Material identity/provenance defects block quantitative conclusions.
3. Use repository-owned deterministic aggregation/calibration code when available. If no authoritative aggregator exists, report the missing mechanism rather than inventing formulas or thresholds.
4. Evaluate the dimensions the repository actually records: realized return/error, hit rate or rank quality, calibration, turnover/cost realization, drawdown/tail behavior, regime stability, concentration/correlation, and degradation versus preregistered expectations. Do not infer unavailable dimensions.
5. Separate sampling uncertainty from true deterioration. A small sample is `INSUFFICIENT_EVIDENCE`, not proof of robustness or failure.
6. Reconcile performance evidence with the current research-state policy. Recommend only states/actions authorized by that policy (for example continued use, deeper review, quarantine, retirement, or new preregistered research). Promotion or retirement transitions themselves must use repository-owned deterministic mechanisms.
7. Persist or update evidence only through repository-defined artifacts if such a mechanism exists. Never mutate frozen forecasts or prior outcome records.

## Escalation criteria

Escalate to fresh research/audit instead of silently adjusting a live signal when there is sustained OOS deterioration, calibration failure, regime-specific instability, realized costs materially worse than assumptions, unexplained exposure concentration, scorer/version discontinuity, or evidence suggesting data/methodology leakage. The authoritative repository policy decides thresholds; absence of a threshold is an unresolved governance gap.

## Completion

Complete when the review population and evidence identities are inspectable, deterministic aggregation was used or explicitly unavailable, uncertainty is reported, the conclusion is consistent with authoritative policy, historical artifacts remain immutable, and the next lifecycle action is explicit without inventing an unauthorized state transition.

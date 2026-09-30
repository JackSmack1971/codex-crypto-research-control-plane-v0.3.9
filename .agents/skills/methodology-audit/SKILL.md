---
name: methodology-audit
description: Adversarially audit a completed research candidate or daily run for methodological validity, including Massive MCP acquisition provenance. Use when the relevant evidence is complete and an independent final trust review is required; do not use as the primary factor researcher, statistical validator, or promotion mechanism.
---

**Repository path contract:** paths such as `config/...`, `scripts/...`, `docs/...`, `schemas/...`, `research/...`, and `workflows/...` are relative to the active project root (the directory containing `AGENTS.md` and `.codex/config.toml`), **not** relative to this installed Skill directory. Never walk `..` from the Skill installation to find project files. Never synthesize or reuse an absolute repository path from memory, prior runs, package names, or examples. First inspect the current working directory and verify the two project-root sentinels. If they are absent, do not guess a drive/path; fail project-root resolution explicitly.

# Methodology audit

Own the final adversarial review. The objective is to find defensible reasons the conclusion should not be trusted.

## Inputs

Identify one audit subject: a candidate or a daily run. Read `docs/data-capability-boundary.md` and `docs/massive-mcp-data-plane.md`; for candidate promotion work also read `docs/research-state-model.md`. Use `schemas/audit_report.schema.json` for the persisted result.

## Workflow

1. Delegate to a fresh `methodology-auditor` context. If fresh independent review cannot be obtained, return `INCONCLUSIVE` rather than self-auditing the originating analysis.
2. Test survivorship/lookahead, timestamp leakage, post-selection inference, multiple-testing-family errors, sample dependence, small-regime claims, turnover/cost optimism, fabricated precision, unsupported causal language, and data-capability violations.
3. Audit source acquisition: required Massive data came through MCP; Basic snapshot status supports the used capability; current endpoint details were verified; parameters/cutoff are explicit; pagination completed; no access-denied/unknown capability was silently substituted; and no post-cutoff refetch leaked into the fixed run. For daily runs, independently inspect the sealed request ledger: provider-call permits must satisfy `config/massive-request-policy.json`, every provider call must be complete, and no `RATE_LIMIT` warning may appear. A tainted ledger is FAIL even if retries later returned complete data.
4. Reconcile every material finding to an inspectable artifact or identify the missing evidence explicitly. Absence of evidence is not a pass.
5. Persist a schema-compatible audit artifact under `research/audits/`. For `daily_run`, include both `run_id` and the exact `attempt_id`. Do not edit the audited artifacts or mutate promotion state. Candidate promotion, when authorized by a PASS audit and the research-state model, belongs to `$candidate-promotion`.

## Completion

Return exactly `PASS`, `FAIL`, or `INCONCLUSIVE` with reason codes and evidence. Complete only when the audit subject identity is unambiguous and every material finding is traceable or explicitly marked unsupported.

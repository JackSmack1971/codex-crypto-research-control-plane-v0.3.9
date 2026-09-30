# Codex CLI Crypto Hedge Fund — Subagent Architecture

Version: 0.4.0

## Design principle

The root Codex session, operating under `$crypto-fund-cio`, is the CIO and final integrator. It should not be replaced by a CIO subagent. Subagents are used for bounded, independently checkable workstreams; dependent state transitions remain in the root workflow or deterministic repository code.

## Daily fund topology

1. Root/CIO establishes the governed run and fixed evidence set through `$daily-research-run`.
2. `data-steward` gates dataset trust before interpretation.
3. Once data are admissible, independent analytical agents may run in parallel when their required inputs are fixed: `macro-regime`, `crypto-internals`, `relative-value`, and `institutional-intelligence`.
4. The deterministic pipeline forms the authoritative research proposal; agents interpret rather than overwrite it.
5. `portfolio-risk` independently challenges the proposal against policy and aggregate exposure.
6. `methodology-auditor` independently challenges the complete evidence chain and any material overlays.
7. `investment-committee-challenger` performs portfolio-level contradiction/falsification review. Prefer an evidence-first pass before exposing it to the CIO narrative to reduce conformity.
8. Root/CIO reconciles conflicts and freezes the strongest valid conclusion. Failed hard gates cannot be voted away.
9. Matured forecasts are scored by repository mechanisms and reviewed by `performance-governor` under `$performance-governance`.

## Alpha R&D topology

`factor-researcher` -> `statistical-validator` -> `methodology-auditor` -> deterministic `$candidate-promotion` gate.

The researcher never validates itself. The validator never mutates state. The auditor never repairs while auditing. Promotion is not a subagent opinion; it is a repository-owned deterministic transition.

## Authority hierarchy

- Repository policy, schemas, deterministic artifacts, and immutable identities outrank agent prose.
- Data-steward can block use of an invalid dataset.
- Statistical validator can render a candidate ineligible for promotion.
- Methodology auditor can block trust in a candidate or daily attempt.
- Portfolio-risk is authoritative for research risk acceptability under repository policy.
- Investment-committee challenger has challenge authority, not decision authority.
- Root/CIO may choose among policy-permitted conclusions but may not override failed hard gates.
- No agent in this package has live brokerage execution authority.

## Concurrency

Use parallelism only after shared inputs are fixed. Good parallel groups include the four market-analysis agents above. Keep ordered chains such as research -> validation -> audit -> promotion sequential. Avoid multiple agents writing the same mutable artifact.

## Handoff standard

Every agent handoff should identify the exact run/candidate/evidence identity, distinguish facts from interpretation, state coverage and uncertainty, surface contradictions, cite inspectable evidence paths, and end with a bounded status or next authorized action. Confidence language must not substitute for missing evidence.

## Why the challenger is separate

The methodology auditor attacks scientific validity. The investment-committee challenger attacks the portfolio thesis and correlated failure modes after valid evidence exists. Combining them would blur model-risk review with investment judgment and increase the chance that a single framing error propagates through the organization.

## Why there is no execution agent

The v0.4.0 skill package deliberately ends at research/portfolio-decision control. Live execution requires a separate explicitly authorized control plane with account identity, pre-trade checks, order idempotency, venue/broker controls, best-execution policy, reconciliation, kill switches, and external-side-effect authorization.

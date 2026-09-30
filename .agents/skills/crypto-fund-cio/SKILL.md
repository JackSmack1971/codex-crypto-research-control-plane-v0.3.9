---
name: crypto-fund-cio
description: Orchestrate the crypto research control plane as a hedge-fund CIO across research, promotion, daily portfolio decision, risk, audit, forecast freezing, and OOS learning. Use for “run the fund”, CIO/investment-committee review, or a full governed investment cycle; do not use for a single data pull, isolated factor test, or live trade execution.
---

**Repository path contract:** paths such as `config/...`, `scripts/...`, `docs/...`, `schemas/...`, `research/...`, and `workflows/...` are relative to the active project root (the directory containing `AGENTS.md` and `.codex/config.toml`), **not** relative to this installed Skill directory. Never walk `..` from the Skill installation to find project files. Never synthesize or reuse an absolute repository path from memory, prior runs, package names, or examples. First inspect the current working directory and verify the two project-root sentinels. If they are absent, do not guess a drive/path; fail project-root resolution explicitly.

# Crypto fund CIO

Own cross-workflow orchestration and investment accountability. This skill does **not** replace specialist research, validation, risk, audit, or scoring skills; it selects the correct lifecycle path, enforces separation of duties, and requires one portfolio-level conclusion grounded in inspectable evidence.

## Mandate boundary

- Treat the repository's authoritative mandate, universe, risk policy, research-state model, and execution boundary as controlling. Locate and read them before making a portfolio decision; do not invent leverage, exposure, liquidity, turnover, drawdown, concentration, or loss limits.
- Research forecasts and model-book recommendations are not brokerage instructions. Do not place, route, or simulate live orders unless a separately authorized execution control plane exists and the user explicitly invokes it.
- No specialist may certify its own work when an independent reviewer is required. Missing independent context yields `INCONCLUSIVE`/`BLOCKED`, not a self-review substitute.
- Preserve point-in-time evidence. Do not refresh fixed-run inputs after seeing downstream results.

## Route the fund lifecycle

Choose the smallest complete path that matches the user's objective:

1. **Daily portfolio cycle** — invoke `$daily-research-run`; require its governed acquisition, deterministic pipeline, specialist handoffs, portfolio-risk review, methodology audit, and immutable forecast. Do not recreate those stages in CIO prose.
2. **New signal / alpha R&D** — require preregistration, then `$factor-research` → `$candidate-validation` → `$methodology-audit` → `$candidate-promotion`. Stop at the first non-passing gate.
3. **Matured forecast learning** — invoke `$oos-scorekeeping`; when enough outcome evidence exists for a decision about trust, calibration, or continued use, hand to `$performance-governance`.
4. **CIO / investment-committee review** — reconcile only already-produced authoritative evidence. Separate deterministic facts from analyst interpretation, risk constraints, and unavailable evidence. Use the repository's portfolio-risk output as the risk authority; do not override it with conviction language.

## CIO decision model

For any portfolio-level conclusion, explicitly resolve:

- **Evidence state:** what is deterministic, independently reviewed, degraded, unavailable, or stale?
- **Expected-return thesis:** which assets/signals contribute and what evidence supports direction/ranking? Do not fabricate precision the artifacts do not provide.
- **Regime and cross-asset context:** distinguish measured regime evidence from narrative explanation.
- **Risk capacity:** apply authoritative portfolio constraints, liquidity/turnover/cost evidence, concentration/correlation exposure, and downside scenarios from inspected artifacts.
- **OOS trust:** use only matured immutable outcomes. Poor or insufficient OOS evidence can reduce confidence or trigger research/governance review, but must not rewrite past forecasts.
- **Action class:** choose exactly one of `INCREASE_RISK`, `HOLD_RISK`, `REDUCE_RISK`, `NO_NEW_RISK`, or `INCONCLUSIVE` **only when the repository has an authoritative mapping from evidence to those classes**. Otherwise report the strongest supported portfolio conclusion without inventing a control state.

## Stopping rules

Stop rather than force a fund decision when CORE data are invalid, required independent review is unavailable, the methodology audit fails, risk constraints are missing or violated, forecast identity is ambiguous, or evidence required by the authoritative mandate is absent. A degraded conclusion is allowed only when the underlying workflow explicitly permits degradation and no material claim depends on the missing evidence.

## Completion

Complete only when the requested lifecycle path has reached its strongest valid terminal state, every delegated workflow has inspectable evidence, conflicts are reconciled without silently overriding lower-level gates, and the final CIO report states: objective; evidence state; portfolio/risk conclusion; gate status; immutable forecast/outcome identities when applicable; unresolved limitations; and the next authorized lifecycle action.

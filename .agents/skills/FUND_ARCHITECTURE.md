# Crypto Research Control Plane — Fund Skill Topology

Version: 0.4.0

## Operating model

The skill set is organized as a separation-of-duties hedge-fund research system, not a collection of analyst personas. `$crypto-fund-cio` is the explicit top-level router/orchestrator. Specialist skills own bounded workflows and produce evidence; they do not self-certify downstream decisions.

### Daily portfolio lifecycle

`$crypto-fund-cio` → `$daily-research-run` → `$massive-mcp-data-plane` (with `$massive-basic-endpoints` as static entitlement guard) → deterministic pipeline → repository specialist agents → portfolio-risk agent → `$methodology-audit` → immutable forecast → `$oos-scorekeeping` → `$performance-governance`.

### Alpha lifecycle

preregistered hypothesis → `$factor-research` → `$candidate-validation` → candidate-bound `$methodology-audit` → `$candidate-promotion` → authorized signal state → future daily runs → OOS outcomes → `$performance-governance` → policy-authorized continue/research/quarantine/retirement path.

## Separation of duties

- Data acquisition proves provenance; it does not form investment conclusions.
- Factor research discovers; it does not validate or promote.
- Candidate validation tests preregistered criteria; it does not change state.
- Methodology audit attacks trustworthiness; it does not repair the subject or promote it.
- Candidate promotion alone owns a repository-authorized promotion transition.
- Daily research owns the fixed-cutoff EOD forecast workflow; it does not score future outcomes.
- OOS scorekeeping records realized evidence; performance governance interprets accumulated matured evidence.
- The CIO layer reconciles evidence and portfolio risk; it does not override failed gates or invent risk limits.

## Live-execution boundary

This package is a research/portfolio-decision control plane. It deliberately does not place external orders. A live execution skill should be a separate, explicitly authorized package with brokerage identity, order validation, pre-trade risk, idempotency, reconciliation, kill-switch, and external-side-effect controls.

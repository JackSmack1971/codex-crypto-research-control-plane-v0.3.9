---
name: candidate-promotion
description: Apply the repository’s deterministic promotion gate to an independently validated and methodology-audited signal candidate. Use when a candidate is ready for an actual research-state promotion decision; do not use for factor discovery, statistical validation, or discretionary override of failed gates.
---

**Repository path contract:** paths such as `config/...`, `scripts/...`, `docs/...`, `schemas/...`, `research/...`, and `workflows/...` are relative to the active project root (the directory containing `AGENTS.md` and `.codex/config.toml`), **not** relative to this installed Skill directory. Never walk `..` from the Skill installation to find project files. Never synthesize or reuse an absolute repository path from memory, prior runs, package names, or examples. First inspect the current working directory and verify the two project-root sentinels. If they are absent, do not guess a drive/path; fail project-root resolution explicitly.

# Candidate promotion

Own only the state-transition gate from researched candidate to the repository's next authorized signal state. Validation eligibility is not promotion.

## Inputs

Read `docs/research-state-model.md` and inspect the candidate, its validation artifact, and its methodology-audit artifact. Locate the repository-owned promotion command/mechanism and any schema or policy it names. Do not infer a command, state name, or file format from this skill.

## Mandatory gate

1. Bind one candidate identity to one immutable hypothesis identity and the exact source acquisition/evidence identities used by research.
2. Require the candidate-validation verdict required by the authoritative state model. A validation `PROMOTE` means only “eligible for this gate.”
3. Require a candidate-bound methodology audit with the authoritative passing result. `FAIL`, `INCONCLUSIVE`, missing audit, identity mismatch, or stale evidence blocks promotion.
4. Verify every additional repository-defined promotion precondition from the state model, including any OOS, cost, liquidity, reproducibility, approval, or deterministic-artifact requirements. Never weaken them because the candidate looks attractive.
5. Execute only the repository-owned deterministic promotion mechanism. If no authoritative mechanism exists, stop `BLOCKED_MISSING_PROMOTION_MECHANISM`; do not emulate the state transition by editing files manually.
6. Independently inspect the resulting state/artifact and verify that the transition changed only the intended candidate state and preserved prior evidence.

## Failure handling

- Identity mismatch or invalid experiment → stop; do not repair by relabeling evidence.
- Missing/ambiguous authoritative state model → `BLOCKED`.
- Promotion command fails → preserve output and inspect before retrying; never hand-edit around the gate.
- Pre-existing repository failure unrelated to promotion → distinguish it from an introduced failure and report whether it prevents independent verification.
- Any request to promote despite a failed mandatory gate is refused as an unauthorized methodological override.

## Completion

Complete only with inspectable evidence that the authoritative deterministic promotion mechanism ran, all required preconditions passed, the resulting candidate state is verified, and no unrelated state changed. Otherwise report the exact blocker and leave promotion state untouched.

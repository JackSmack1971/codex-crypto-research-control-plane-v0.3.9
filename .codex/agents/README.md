# Crypto Hedge Fund Codex Subagents v0.4.0

These agents are designed to pair with the `full-skillset-v0.4.0` crypto research control plane.

Key changes from the supplied package:

- rewrote all nine role contracts around explicit evidence, authority, stopping, and handoff boundaries;
- aligned research/validation/audit roles with the new factor -> validation -> audit -> candidate-promotion lifecycle;
- aligned daily agents with the CIO -> daily run -> risk -> audit -> immutable forecast lifecycle;
- added `performance-governor` for the new OOS performance-governance loop;
- added `investment-committee-challenger` for independent portfolio-level effective challenge;
- kept the root Codex session as CIO rather than creating a competing CIO subagent;
- preserved the no-live-execution boundary.

Copy the TOML role files into the repository's `.codex/agents/` directory and register them using the repository's existing Codex configuration pattern. Do not replace repository-specific model, sandbox, or permission settings with guessed defaults.

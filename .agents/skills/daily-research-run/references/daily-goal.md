# Daily `/goal`

Use one stable daily `run_id` derived from the completed research date and a fresh `attempt_id` for every retry.

```text
/goal Execute one complete governed end-of-day crypto research attempt for <DATE> through the strongest valid terminal state.

Use the repository control plane exactly. Do not stop after planning.

0. NATIVE BOOTSTRAP / ATTEMPT IDENTITY
- Do not guess the repository path. Start from the current working directory and verify `AGENTS.md` plus `.codex/config.toml`; if either is absent, stop project-root resolution instead of synthesizing an absolute path.
- On Windows, **do not start with bare `python`, `python3`, a PATH shim, or direct execution of an unsigned `.ps1` file**. Invoke `scripts\control_plane\bootstrap.cmd` from the verified project root. The CMD launcher applies process-scoped PowerShell `-ExecutionPolicy Bypass` and does not modify machine policy.
- Unless the user supplied an explicit research date, bootstrap resolves the most recently completed UTC calendar day as `research_date`, sets `run_id=<research_date>-eod`, sets `research_cutoff` to the next UTC midnight with `research_cutoff_semantics=EXCLUSIVE_UTC_BOUNDARY`, and creates a unique attempt_id. Never derive run_id from the wall-clock execution date when the research cutoff belongs to the prior completed day. Never overwrite a prior attempt. Repository paths are rooted at the directory containing `AGENTS.md` and `.codex/config.toml`; never resolve project files by walking upward from an installed Skill directory. The bootstrap performs required-file/writability/source-identity/prior-attempt checks without Python and always writes `research/runs/<attempt>.bootstrap.json` plus `research/runs/<attempt>.python-runtime.json`.
- The runtime resolver tests an attempt-bound runtime, repo `.venv`, versioned `py` launchers, Windows Python registry installs, common CPython/Conda/Scoop paths, existing uv-managed interpreters recursively, every PATH/`where.exe` Python candidate, and `uv python find >=3.11`. Any successful launcher is rebound to `sys.executable`; governed scripts thereafter execute the resolved interpreter directly, not the launcher/shim.
- If no existing interpreter executes and uv is available, bootstrap is authorized to provision CPython 3.12 **only inside `.runtime/python` in this repository** using `uv python install --install-dir ... --no-bin`. It must not modify system PATH or perform a global Python install. `.runtime/` is untracked disposable infrastructure. Acquisition is still forbidden until the newly provisioned interpreter passes the same executable probe.
- If bootstrap remains BLOCKED after bounded repo-local provisioning, stop before MCP calls and preserve the full candidate/provisioning diagnostics. Git unavailability is a reported verification limitation, not by itself a research blocker.
- If bootstrap is READY, validate `research/runs/<attempt>.python-runtime.json` against `schemas/python_runtime.schema.json`, then run all repository Python scripts on Windows through `scripts/control_plane/run_python.cmd -RuntimeFile research/runs/<attempt>.python-runtime.json ...`. The CMD wrapper is the canonical external entrypoint and invokes the PowerShell implementation with process-scoped bypass. Do not call `run_python.ps1` directly. Do not revert to bare `python` later in the attempt.
- Run Python `preflight.py` and `discover_run.py` through that bound runtime before acquisition, then initialize `research/runs/<attempt>.massive-request-ledger.json` through the same wrapper with `massive_request_gate.py init`. For each provider-facing permit, persist `research/staging/<attempt>/requests/<sequence>.request.json` conforming to `schemas/massive_request_spec.schema.json` and call `permit --request-file <path>`; never pass `--params-json` through PowerShell. Persist completion metadata to a `*.result.json` conforming to `schemas/massive_request_result.schema.json` and call `complete --result-file <path>` so warnings/IDs/pagination metadata are never shell-parsed.
- The default provider-facing budget is defined in `config/massive-request-policy.json` and currently enforces at most five Massive `call_api` starts per rolling 60 seconds with at least 12 seconds between permits.
- Before any planned multi-call phase, run `massive_request_gate.py plan --request-count <N>` through the bound runtime and record the minimum start span. Reconcile any newer user pacing instruction before that phase. If the user tightens the provider-rate constraint below the attempt's sealed policy snapshot, stop issuing permits and start a fresh attempt under the tighter policy; do not retroactively relabel earlier calls compliant.

1. EFFECTIVE MASSIVE CAPABILITY PROBE
- Read config/daily-capabilities.json.
- Through Massive MCP, independently record endpoint discovery, dated Basic snapshot status, and actual authenticated access for each applicable capability. Every provider-facing `call_api` probe requires a request-gate permit and immediate completion record.
- Write an attempt-scoped capability probe report and run evaluate_capabilities.py.
- CORE failure => BLOCKED.
- ENRICHMENT failure => DEGRADED coverage, not automatic BLOCK.
- EVENT_OPTIONAL unavailable => record unavailable/skip unless this run explicitly requires it.
- Never bypass Massive MCP.

2. FIX AND DURABLY MATERIALIZE THE SOURCE SET
- Acquire point-in-time crypto universe and cutoff-day grouped crypto cross-section first. Every provider-facing `call_api` acquisition must pass through the attempt request gate; do not issue parallel provider calls.
- For each dataset, persist `research/staging/<attempt>/materializations/<dataset>.spec.json` with explicit `capability_id` and `evidence_role` (`RESEARCH_INPUT` or `DIAGNOSTIC`) conforming to `schemas/massive_materialization_spec.schema.json`, including the exact chunk paths, endpoint path/template, params object, cutoff/retrieval timestamps, expected row count, and key/sort fields. On Windows, materialize only with `scripts\control_plane\materialize_mcp_dataset.cmd <runtime.json> <spec.json>`; on non-Windows invoke `materialize_mcp_dataset.py --spec-file <path>` through the bound runtime. Never pass those structured values inline through PowerShell; transient MCP workspace tables do not count as durable evidence.
- From that fixed cross-section, deterministically select the configured top-N eligible USD pairs and anchors according to config/daily-model.json.
- Acquire the configured historical lookback for that fixed selected universe through Massive MCP, using bounded calls and complete pagination.
- For the per-ticker history phase, plan the full request count before starting. The request gate, not model timing judgment, owns waiting between provider calls.
- For workspace tables, export ordered 100-200 row `query_data` chunks, write the materialization spec, then materialize canonical JSONL from that spec; verify exact staged/local row counts, unique keys, and SHA-256 digests.
- Acquire/materialize accessible ENRICHMENT inputs (FX, stock, index) and relevant EVENT_OPTIONAL inputs without broadening the run after downstream results are seen.
- Capture exact client UTC timestamps around MCP calls when server timestamps/request IDs are unavailable; do not estimate them.
- After every provider call, complete its ledger entry with outcome, warning, row count, request ID when exposed, and pagination state. On the first `RATE_LIMIT` warning, stop the batch immediately: the gate marks the attempt TAINTED and no later retry may rehabilitate that attempt. Finish it BLOCKED and create a new attempt for recovery.
- Seal the acquisition only after durable materialization. PARTIAL is not downstream-eligible. DEGRADED is downstream-eligible only when every CORE dataset is COMPLETE and verified.

2.5 MATERIALIZATION RECONCILIATION
- After sealing the acquisition, run `scripts/control_plane/reconcile_materializations.py` through the bound runtime against the sealed acquisition. Persist `research/runs/<attempt>.materialization-reconciliation.json` and validate it against `schemas/materialization_reconciliation.schema.json`.
- Every durable `RESEARCH_INPUT` materialization must appear exactly once in the sealed acquisition with matching path, digest, row count, capability_id, and requirement. Any unmanifested or unclassified research materialization is BLOCKING.
- Durable capability/access probes that are retained only for diagnostics must declare `evidence_role=DIAGNOSTIC`; they may remain outside the acquisition but must never be consumed by the deterministic pipeline.
- A BLOCK reconciliation stops the attempt before data-steward/pipeline.

3. DATA-STEWARD GATE
- Delegate data-steward against the sealed acquisition, capability evaluation, and materialized metadata/data.
- CORE missing/denied/transient/incomplete/post-cutoff => BLOCK.
- Missing ENRICHMENT => normally DEGRADED if core remains valid.
- Validate the handoff against schemas/agent_handoff.schema.json and the data-quality artifact against schemas/data_quality_report.schema.json with validate_artifact.py.

4. DETERMINISTIC PIPELINE
- If data quality permits continuation, run scripts/pipeline/run_daily_pipeline.py through the bound runtime over the verified materialized data.
- Code owns feature calculations, rankings, residual model, market state, ensemble, research-only risk sizing, persistence, and forecast payload creation.
- Validate pipeline-result.json against schemas/daily_pipeline_result.schema.json.
- If the deterministic pipeline cannot execute or history coverage is insufficient, BLOCK rather than substituting prose calculations.

5. PARALLEL ANALYSIS
Run crypto-internals, relative-value, macro-regime, and institutional-intelligence in parallel over the fixed deterministic artifacts.
- Missing macro ENRICHMENT must be reported as DEGRADED/UNAVAILABLE coverage, never invented or silently neutralized.
- Institutional source unavailability is distinct from no material event.
- No agent may independently refresh the fixed run dataset.
- On Windows validate each handoff with `scripts\control_plane\validate_artifact.cmd <runtime.json> <handoff.json> schemas\agent_handoff.schema.json`; do not invoke `run_python.ps1` directly. On non-Windows use the bound runtime with `validate_artifact.py`.

6. SYNTHESIS -> PORTFOLIO-RISK -> METHODOLOGY AUDIT
- Primary Codex reconciles deterministic outputs and the four handoffs.
- Run portfolio-risk on the deterministic research-only proposal.
- Before methodology audit, run `massive_request_gate.py audit --ledger <ledger> --seal`. Any spacing/window violation, incomplete request record, or observed `RATE_LIMIT` is blocking and requires a new attempt.
- Run methodology-auditor fresh and bind the artifact to both `run_id` and `attempt_id`. A denied ENRICHMENT is acceptable only when explicitly degraded and no claim depends on it. CORE failure, direct-network workaround, transient-only core data, cutoff leakage, or request-ledger noncompliance is blocking.
- Validate audit artifact against audit_report.schema.json.

7. FREEZE FORECAST
- If mandatory gates permit it, freeze the deterministic forecast payload with `freeze_forecast.py --request-ledger <sealed-ledger> --materialization-reconciliation <PASS-reconciliation> --methodology-audit <PASS-audit>` before its target outcome exists. The freeze command independently rejects a noncompliant/unsealed ledger, a non-PASS audit, or an audit bound to a different attempt.
- Verify immutable rewrite rejection.
- A DEGRADED forecast is permitted only when CORE is complete, the data-steward permits continuation, the deterministic pipeline completes, and methodology audit passes while preserving the degradation in source evidence.

8. VERIFY
- Do not assume `rg`/ripgrep exists. Use `scripts\control_plane\search_repo.cmd "<pattern>" <paths...>` for repository search on Windows, or native PowerShell `Get-ChildItem ... | Select-String`. Missing `rg` is not a blocker.
- Validate every produced JSON artifact against its declared schema. On Windows use `scripts\control_plane\validate_artifact.cmd <runtime.json> <artifact.json> <schema.json>`; never invoke `run_python.ps1` directly. On non-Windows use `validate_artifact.py` through the bound runtime. Validate the native bootstrap artifact against `schemas/windows_bootstrap.schema.json` and the runtime-resolution artifact against `schemas/python_runtime.schema.json` once Python is available.
- On Windows run control-plane validation through `scripts\control_plane\validate_control_plane.cmd <runtime.json>` and tests through `scripts\control_plane\run_tests.cmd <runtime.json>`; on non-Windows use the bound runtime directly. Run Git checks when a Git checkout is actually available.
- Report exact commands and outcomes, not inferred success.

Final report: status; run_id/attempt_id; cutoff; effective capability matrix; acquisition/materialization digests; data-quality result; deterministic pipeline result; four analytical handoffs; portfolio-risk result; methodology audit; frozen forecast path/digest if any; executed verification; files created; unresolved limitations.
```

**Component-location contract:** named independent reviewer roles such as `data-steward` are Codex agents under `.codex/agents/<name>.toml`, not Skills under `.agents/skills/`. The acquisition schema is `schemas/massive_acquisition_manifest.schema.json`. Do not invent shorter schema filenames or Skill paths; use the repository search helper when uncertain.


**Half-open UTC-day contract:** `research_cutoff` is an exclusive boundary at the start of the next UTC day. An observation belongs to the research day iff its effective timestamp is strictly `< research_cutoff`. Thus `2026-09-28T23:59:59.999Z` is valid for the 2026-09-28 run, while `2026-09-29T00:00:00Z` is not. Never require an EOD provider bar to end exactly at the cutoff.

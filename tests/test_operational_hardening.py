import csv
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONTROL = ROOT / "scripts" / "control_plane"
PIPELINE = ROOT / "scripts" / "pipeline"


def run(path, *args, cwd=ROOT):
    return subprocess.run([sys.executable, str(path), *map(str, args)], cwd=cwd, text=True, capture_output=True)


def write_materialized(root: Path, attempt: str, dataset_id: str, rows: list[dict], market="Crypto") -> Path:
    out = root / attempt
    out.mkdir(parents=True, exist_ok=True)
    data = out / f"{dataset_id}.jsonl"
    body = "".join(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n" for row in rows)
    body_bytes = body.encode("utf-8")
    data.write_bytes(body_bytes)
    digest = "sha256:" + hashlib.sha256(body_bytes).hexdigest()
    meta = {
        "dataset_id": dataset_id,
        "capability_id": dataset_id,
        "evidence_role": "RESEARCH_INPUT",
        "run_id": "2026-09-28-eod",
        "attempt_id": attempt,
        "market": market,
        "endpoint_path": "/test",
        "params": {},
        "requirement": "CORE",
        "research_cutoff": "2026-09-29T00:00:00Z",
        "research_cutoff_semantics": "EXCLUSIVE_UTC_BOUNDARY",
        "retrieved_at": "2026-09-29T00:00:01Z",
        "as_of": "2026-09-28",
        "row_count": len(rows),
        "sort_fields": [],
        "key_fields": [],
        "data_path": data.as_posix(),
        "data_digest": digest,
        "source_chunks": [],
        "materialization_status": "VERIFIED",
    }
    (out / f"{dataset_id}.meta.json").write_text(json.dumps(meta), encoding="utf-8")
    return data


class OperationalHardeningTests(unittest.TestCase):


    def test_windows_bootstrap_policy_has_bounded_repo_local_repair_and_diagnostics(self):
        policy = json.loads((ROOT / "config" / "python-runtime-policy.json").read_text(encoding="utf-8"))
        self.assertEqual("3.11", policy["minimum_version"])
        self.assertEqual("3.12", policy["preferred_provision_version"])
        self.assertTrue(policy["allow_windows_registry_scan"])
        self.assertTrue(policy["allow_uv_managed_scan"])
        self.assertTrue(policy["allow_repo_local_uv_provision"])
        self.assertEqual("REPO_LOCAL_ONLY", policy["auto_install_scope"])
        bootstrap = (CONTROL / "bootstrap.ps1").read_text(encoding="utf-8")
        resolver = (CONTROL / "run_python.ps1").read_text(encoding="utf-8")
        self.assertIn("bootstrap.json", bootstrap)
        self.assertIn("python-runtime.json", bootstrap)
        self.assertIn("-AllowProvision", bootstrap)
        self.assertIn("Get-RegistryPythonCandidates", resolver)
        self.assertIn("Get-UvManagedCandidates", resolver)
        self.assertIn("Get-PathPythonCandidates", resolver)
        self.assertIn("uv_python_install", resolver)
        self.assertIn("--install-dir", resolver)
        self.assertIn("--no-bin", resolver)
        self.assertIn("probes = @($Diagnostics)", resolver)
        self.assertTrue((CONTROL / "bootstrap.cmd").is_file())
        self.assertTrue((CONTROL / "run_python.cmd").is_file())
        self.assertIn("-ExecutionPolicy Bypass", (CONTROL / "bootstrap.cmd").read_text(encoding="utf-8"))
        self.assertIn("-ExecutionPolicy Bypass", (CONTROL / "run_python.cmd").read_text(encoding="utf-8"))

    def test_skill_paths_are_project_root_relative_and_daily_workflow_is_bundled(self):
        for skill_md in (ROOT / ".agents" / "skills").glob("*/SKILL.md"):
            text = skill_md.read_text(encoding="utf-8")
            self.assertIn("Repository path contract:", text, skill_md.as_posix())
            self.assertNotIn("../../../", text, skill_md.as_posix())
        bundled = ROOT / ".agents" / "skills" / "daily-research-run" / "references" / "daily-goal.md"
        self.assertTrue(bundled.is_file())
        self.assertEqual((ROOT / "workflows" / "daily-goal.md").read_bytes(), bundled.read_bytes())

    def test_python_runtime_schema_accepts_ready_and_blocked_evidence(self):
        schema = ROOT / "schemas" / "python_runtime.schema.json"
        ready = {
            "status": "READY",
            "mode": "native",
            "source": "windows_registry",
            "executable": "C:/Python312/python.exe",
            "resolved_executable": "C:/Python312/python.exe",
            "prefix": [],
            "version": "3.12.7",
            "checked_at": "2026-09-29T12:00:00Z",
            "provisioned_repo_runtime": False,
            "provisioning": [],
            "probes": [{"source":"windows_registry","candidate":"C:/Python312/python.exe","status":"READY","detail":"version=3.12.7"}],
        }
        blocked = {
            "status": "BLOCKED",
            "reason": "NO_WORKING_PYTHON_3_11_PLUS",
            "checked_at": "2026-09-29T12:00:00Z",
            "minimum_version": "3.11",
            "repo_local_provision_allowed": True,
            "provisioning_attempted": True,
            "provisioning": [{"status":"FAILED","method":"uv_python_install"}],
            "probes": [{"source":"path_enumeration","candidate":"python.exe","status":"FAILED","detail":"permission denied"}],
            "remediation": ["repair runtime"],
        }
        with tempfile.TemporaryDirectory() as td:
            for name, obj in (("ready", ready), ("blocked", blocked)):
                path = Path(td) / f"{name}.json"
                path.write_text(json.dumps(obj), encoding="utf-8")
                proc = run(CONTROL / "validate_artifact.py", path, schema)
                self.assertEqual(0, proc.returncode, proc.stdout + proc.stderr)

    def test_windows_workflow_forbids_bare_python_after_runtime_binding(self):
        workflow = (ROOT / "workflows" / "daily-goal.md").read_text(encoding="utf-8")
        agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
        self.assertIn("bootstrap.cmd", workflow)
        self.assertIn("run_python.cmd", workflow)
        self.assertIn("Do not revert to bare `python`", workflow)
        self.assertIn("make **zero Massive provider calls**", agents)
        self.assertIn("bounded self-repair", agents)
        self.assertIn(".runtime/python", agents)

    def test_windows_bootstrap_owns_research_date_identity_and_forbids_guessed_paths(self):
        bootstrap = (CONTROL / "bootstrap.ps1").read_text(encoding="utf-8")
        workflow = (ROOT / "workflows" / "daily-goal.md").read_text(encoding="utf-8")
        agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
        self.assertIn("Date.AddDays(-1)", bootstrap)
        self.assertIn('$ExpectedRunId = "$ResolvedResearchDate-eod"', bootstrap)
        self.assertIn("run_id_research_date_mismatch", bootstrap)
        self.assertIn("attempt_id_run_id_mismatch", bootstrap)
        self.assertIn("Never derive run_id from the wall-clock execution date", workflow)
        self.assertIn("Never synthesize an absolute repository path", agents)

    def test_windows_external_entrypoints_are_cmd_wrappers_not_direct_ps1(self):
        workflow = (ROOT / "workflows" / "daily-goal.md").read_text(encoding="utf-8")
        daily_skill = (ROOT / ".agents" / "skills" / "daily-research-run" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("bootstrap.cmd", workflow)
        self.assertIn("run_python.cmd", workflow)
        self.assertIn("unsigned `.ps1`", workflow)
        self.assertIn("canonical external entrypoint", daily_skill)
        self.assertNotIn("First run `scripts/control_plane/bootstrap.ps1`", daily_skill)

    def test_request_gate_plan_enforces_five_per_minute(self):
        proc = run(CONTROL / "massive_request_gate.py", "plan", "--request-count", "25")
        self.assertEqual(0, proc.returncode, proc.stdout + proc.stderr)
        result = json.loads(proc.stdout)
        starts = result["scheduled_start_offsets_seconds"]
        self.assertEqual(25, len(starts))
        self.assertGreaterEqual(result["minimum_start_span_seconds"], 288.0)
        for idx in range(1, len(starts)):
            self.assertGreaterEqual(starts[idx] - starts[idx - 1] + 1e-9, 12.0)
        for idx, start in enumerate(starts):
            in_window = sum(1 for prior in starts[: idx + 1] if start - prior < 60.0)
            self.assertLessEqual(in_window, 5)

    def test_request_gate_rate_limit_taints_and_refuses_next_permit(self):
        with tempfile.TemporaryDirectory() as td:
            ledger = Path(td) / "ledger.json"
            init = run(CONTROL / "massive_request_gate.py", "init", "--run-id", "r", "--attempt-id", "a", "--ledger", ledger)
            self.assertEqual(0, init.returncode, init.stdout + init.stderr)
            permit = run(CONTROL / "massive_request_gate.py", "permit", "--ledger", ledger, "--label", "history", "--endpoint-path", "/v2/aggs/test", "--params-json", "{}")
            self.assertEqual(0, permit.returncode, permit.stdout + permit.stderr)
            permit_id = json.loads(permit.stdout)["permit_id"]
            done = run(CONTROL / "massive_request_gate.py", "complete", "--ledger", ledger, "--permit-id", permit_id, "--outcome", "RATE_LIMIT", "--warning", "Warning [RATE_LIMIT]")
            self.assertEqual(4, done.returncode)
            obj = json.loads(ledger.read_text(encoding="utf-8"))
            self.assertEqual("TAINTED", obj["status"])
            self.assertTrue(obj["halt_required"])
            refused = run(CONTROL / "massive_request_gate.py", "permit", "--ledger", ledger, "--label", "history2", "--endpoint-path", "/v2/aggs/test2", "--params-json", "{}")
            self.assertEqual(4, refused.returncode)
            self.assertIn("NEW_ATTEMPT_REQUIRED", refused.stdout)
            audit = run(CONTROL / "massive_request_gate.py", "audit", "--ledger", ledger, "--seal")
            self.assertEqual(2, audit.returncode)

    def test_request_gate_requires_serial_completion_and_seals_clean_ledger(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            ledger = td / "ledger.json"
            self.assertEqual(0, run(CONTROL / "massive_request_gate.py", "init", "--run-id", "r", "--attempt-id", "a", "--ledger", ledger).returncode)
            permit = run(CONTROL / "massive_request_gate.py", "permit", "--ledger", ledger, "--label", "probe", "--endpoint-path", "/v3/reference/tickers", "--params-json", "{}")
            self.assertEqual(0, permit.returncode, permit.stdout + permit.stderr)
            refused = run(CONTROL / "massive_request_gate.py", "permit", "--ledger", ledger, "--label", "probe2", "--endpoint-path", "/v3/reference/tickers", "--params-json", "{}")
            self.assertEqual(4, refused.returncode)
            self.assertIn("OUTSTANDING_PERMIT", refused.stdout)
            permit_id = json.loads(permit.stdout)["permit_id"]
            complete = run(CONTROL / "massive_request_gate.py", "complete", "--ledger", ledger, "--permit-id", permit_id, "--outcome", "SUCCESS", "--row-count", "1", "--pagination-terminal", "TRUE", "--next-url-present", "FALSE")
            self.assertEqual(0, complete.returncode, complete.stdout + complete.stderr)
            seal = run(CONTROL / "massive_request_gate.py", "audit", "--ledger", ledger, "--seal")
            self.assertEqual(0, seal.returncode, seal.stdout + seal.stderr)
            sealed = json.loads(ledger.read_text(encoding="utf-8"))
            self.assertEqual("SEALED", sealed["status"])
            self.assertTrue(sealed["content_digest"].startswith("sha256:"))
            validate = run(CONTROL / "validate_artifact.py", ledger, ROOT / "schemas" / "massive_request_ledger.schema.json")
            self.assertEqual(0, validate.returncode, validate.stdout + validate.stderr)

    def test_capability_evaluation_degrades_for_stock_index_denial(self):
        matrix = json.loads((ROOT / "config" / "daily-capabilities.json").read_text(encoding="utf-8"))
        caps = []
        for item in matrix["capabilities"]:
            access = "SUCCEEDED"
            if item["capability_id"] in {"stock_macro_proxies", "index_macro_proxies"}:
                access = "NOT_ENTITLED"
            caps.append({
                "capability_id": item["capability_id"],
                "discovery_status": "VERIFIED",
                "basic_snapshot_status": "INCLUDED",
                "access_status": access,
                "endpoint_path": "/test",
                "probe_params": {},
                "probed_at": "2026-09-29T00:00:00Z",
                "evidence": ["test"],
            })
        report = {
            "run_id": "2026-09-28-eod",
            "attempt_id": "a1",
            "created_at": "2026-09-29T00:00:00Z",
            "research_cutoff": "2026-09-29T00:00:00Z",
            "capabilities": caps,
        }
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "probe.json"
            path.write_text(json.dumps(report), encoding="utf-8")
            proc = run(CONTROL / "evaluate_capabilities.py", path)
            self.assertEqual(0, proc.returncode, proc.stdout + proc.stderr)
            result = json.loads(proc.stdout)
            self.assertEqual("DEGRADED", result["status"])
            self.assertFalse(result["core_failures"])
            self.assertEqual(2, len(result["degradations"]))

    def test_capability_evaluation_blocks_for_core_denial(self):
        matrix = json.loads((ROOT / "config" / "daily-capabilities.json").read_text(encoding="utf-8"))
        caps = []
        for item in matrix["capabilities"]:
            caps.append({
                "capability_id": item["capability_id"],
                "discovery_status": "VERIFIED",
                "basic_snapshot_status": "INCLUDED",
                "access_status": "NOT_ENTITLED" if item["capability_id"] == "crypto_history" else "SUCCEEDED",
                "endpoint_path": "/test",
                "probe_params": {},
                "probed_at": "2026-09-29T00:00:00Z",
                "evidence": ["test"],
            })
        report = {"run_id": "r", "attempt_id": "a", "created_at": "2026-09-29T00:00:00Z", "research_cutoff": "2026-09-29T00:00:00Z", "research_cutoff_semantics": "EXCLUSIVE_UTC_BOUNDARY", "capabilities": caps}
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "probe.json"
            path.write_text(json.dumps(report), encoding="utf-8")
            proc = run(CONTROL / "evaluate_capabilities.py", path)
            self.assertEqual(2, proc.returncode)
            self.assertEqual("BLOCKED", json.loads(proc.stdout)["status"])

    def test_materializer_verifies_count_digest_and_immutability(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            c1 = td / "one.csv"
            c2 = td / "two.csv"
            c1.write_text("ticker,t,c\nX:BTCUSD,1,10\n", encoding="utf-8")
            c2.write_text("ticker,t,c\nX:ETHUSD,1,20\n", encoding="utf-8")
            out = td / "data"
            args = [c1, c2, "--dataset-id", "crypto", "--run-id", "r", "--attempt-id", "a", "--market", "Crypto", "--endpoint-path", "/test", "--params-json", "{}", "--requirement", "CORE", "--research-cutoff", "2026-09-29T00:00:00Z", "--retrieved-at", "2026-09-29T00:00:01Z", "--as-of", "2026-09-28", "--expected-rows", "2", "--sort-fields", "ticker,t", "--key-fields", "ticker,t", "--out-dir", out]
            first = run(CONTROL / "materialize_mcp_dataset.py", *args)
            self.assertEqual(0, first.returncode, first.stdout + first.stderr)
            result = json.loads(first.stdout)
            self.assertEqual(2, result["row_count"])
            meta = Path(result["metadata"])
            self.assertTrue(meta.exists())
            second = run(CONTROL / "materialize_mcp_dataset.py", *args)
            self.assertEqual(3, second.returncode)


    def test_materializer_accepts_file_spec_with_timestamps_and_endpoint_template(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            c1 = td / "spy.csv"
            c2 = td / "qqq.csv"
            c1.write_text("ticker,t,c\nSPY,1,500\n", encoding="utf-8")
            c2.write_text("ticker,t,c\nQQQ,1,450\n", encoding="utf-8")
            spec = td / "stock_history.spec.json"
            spec.write_text(json.dumps({
                "schema_version": 1,
                "chunks": [str(c1), str(c2)],
                "dataset_id": "stock_history",
                "capability_id": "stock_macro_proxies",
                "evidence_role": "RESEARCH_INPUT",
                "run_id": "2026-09-28-eod",
                "attempt_id": "2026-09-28-eod-attempt-file-spec",
                "market": "Stocks",
                "endpoint_path": "/v2/aggs/ticker/{stocksTicker}/range/{multiplier}/{timespan}/{from}/{to}",
                "params": {"adjusted": True, "limit": 50000, "sort": "asc"},
                "requirement": "ENRICHMENT",
                "research_cutoff": "2026-09-29T00:00:00Z",
                "research_cutoff_semantics": "EXCLUSIVE_UTC_BOUNDARY",
                "retrieved_at": "2026-09-29T22:54:58Z",
                "as_of": "2026-09-28",
                "expected_rows": 2,
                "sort_fields": ["ticker", "t"],
                "key_fields": ["ticker", "t"],
                "out_dir": str(td / "data"),
            }), encoding="utf-8")
            proc = run(CONTROL / "materialize_mcp_dataset.py", "--spec-file", spec)
            self.assertEqual(0, proc.returncode, proc.stdout + proc.stderr)
            result = json.loads(proc.stdout)
            meta = json.loads(Path(result["metadata"]).read_text(encoding="utf-8"))
            self.assertEqual("2026-09-29T00:00:00Z", meta["research_cutoff"])
            self.assertEqual("2026-09-29T22:54:58Z", meta["retrieved_at"])
            self.assertEqual("/v2/aggs/ticker/{stocksTicker}/range/{multiplier}/{timespan}/{from}/{to}", meta["endpoint_path"])
            self.assertEqual({"adjusted": True, "limit": 50000, "sort": "asc"}, meta["params"])

    def test_materializer_spec_rejects_inline_metadata_mix(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            chunk = td / "one.csv"
            chunk.write_text("ticker,t,c\nX:BTCUSD,1,10\n", encoding="utf-8")
            spec = td / "spec.json"
            spec.write_text(json.dumps({
                "schema_version": 1,
                "chunks": [str(chunk)],
                "dataset_id": "crypto",
                "capability_id": "crypto_history",
                "evidence_role": "RESEARCH_INPUT",
                "run_id": "r",
                "attempt_id": "a",
                "market": "Crypto",
                "endpoint_path": "/test",
                "params": {},
                "requirement": "CORE",
                "research_cutoff": "2026-09-29T00:00:00Z",
                "research_cutoff_semantics": "EXCLUSIVE_UTC_BOUNDARY",
                "retrieved_at": "2026-09-29T00:00:01Z",
                "as_of": "2026-09-28",
                "expected_rows": 1,
                "sort_fields": ["ticker", "t"],
                "key_fields": ["ticker", "t"]
            }), encoding="utf-8")
            proc = run(CONTROL / "materialize_mcp_dataset.py", "--spec-file", spec, "--dataset-id", "override")
            self.assertEqual(2, proc.returncode)
            self.assertIn("spec_file_cannot_be_combined", proc.stdout)

    def test_materializer_rejects_truncated_chunk(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            chunk = td / "bad.csv"
            chunk.write_text("ticker,t,c\nX:BTCUSD,1,[truncated: 9 more chars]\n", encoding="utf-8")
            proc = run(CONTROL / "materialize_mcp_dataset.py", chunk, "--dataset-id", "crypto", "--run-id", "r", "--attempt-id", "a", "--market", "Crypto", "--endpoint-path", "/test", "--params-json", "{}", "--requirement", "CORE", "--research-cutoff", "2026-09-29T00:00:00Z", "--retrieved-at", "2026-09-29T00:00:01Z", "--as-of", "2026-09-28", "--expected-rows", "1", "--out-dir", td / "out")
            self.assertEqual(2, proc.returncode)
            self.assertIn("truncation_marker", proc.stdout)

    def test_degraded_acquisition_allows_denied_enrichment_but_complete_core(self):
        payload = json.loads((ROOT / "examples" / "acquisition.example.json").read_text(encoding="utf-8"))
        payload["status"] = "DEGRADED"
        payload["limitations"] = ["stock_macro_proxies:not_entitled"]
        payload["datasets"].append({
            "dataset_id": "stock_macro",
            "capability_id": "stock_macro_proxies",
            "requirement": "ENRICHMENT",
            "market": "Stocks",
            "purpose": "macro",
            "method": "GET",
            "endpoint_path": "/v2/aggs/grouped/locale/us/market/stocks/2026-09-28",
            "params": {},
            "retrieved_at": "2026-09-29T00:03:00Z",
            "retrieval_time_source": "CLIENT_CAPTURED",
            "as_of": "2026-09-28",
            "discovery_status": "VERIFIED",
            "basic_snapshot_status": "INCLUDED",
            "access_status": "NOT_ENTITLED",
            "pagination_complete": True,
            "row_count": 0,
            "workspace_table": None,
            "request_ids": [],
            "materialization_status": "NOT_REQUIRED",
            "materialized_path": None,
            "materialized_digest": None,
            "materialized_row_count": None,
            "status": "ACCESS_DENIED",
            "notes": ["provider denial"],
        })
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            src = td / "payload.json"
            src.write_text(json.dumps(payload), encoding="utf-8")
            proc = run(CONTROL / "seal_acquisition.py", src, "--out-dir", td / "out")
            self.assertEqual(0, proc.returncode, proc.stdout + proc.stderr)

    def test_validate_artifact_enforces_additional_properties(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            artifact = json.loads((ROOT / "examples" / "data-quality.example.json").read_text(encoding="utf-8"))
            artifact["unexpected"] = True
            src = td / "dq.json"
            src.write_text(json.dumps(artifact), encoding="utf-8")
            proc = run(CONTROL / "validate_artifact.py", src, ROOT / "schemas" / "data_quality_report.schema.json")
            self.assertEqual(1, proc.returncode)
            self.assertIn("additionalProperty:unexpected", proc.stdout)

    def test_deterministic_pipeline_runs_with_verified_crypto_core_and_degraded_macro(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            attempt = "2026-09-28-eod-attempt-test"
            tickers = ["X:BTCUSD", "X:ETHUSD", "X:SOLUSD", "X:XRPUSD", "X:LTCUSD", "X:ADAUSD"]
            universe = [{"ticker": t, "active": True} for t in tickers]
            cutoff = []
            history = []
            start = datetime(2026, 7, 26, tzinfo=timezone.utc)
            for j, ticker in enumerate(tickers):
                base = 100 + j * 20
                for i in range(65):
                    price = base * (1 + 0.002 * (j + 1) * i)
                    ts = int((start + timedelta(days=i)).timestamp() * 1000)
                    history.append({"ticker": ticker, "t": ts, "o": price * 0.997, "h": price * 1.01, "l": price * 0.99, "c": price, "v": 100000 + 1000 * j, "vw": price * 0.999, "n": 1000 + i})
                last = history[-1]
                cutoff.append({"T": ticker, "t_2": last["t"], "o": last["o"], "h": last["h"], "l": last["l"], "c": last["c"], "v": last["v"], "vw": last["vw"], "n": last["n"]})
            data_root = td / "data"
            p_universe = write_materialized(data_root, attempt, "crypto_universe", universe)
            p_cutoff = write_materialized(data_root, attempt, "crypto_grouped_cutoff", cutoff)
            p_history = write_materialized(data_root, attempt, "crypto_history", history)
            dq = td / "dq.json"
            dq.write_text(json.dumps({"run_id": "2026-09-28-eod", "status": "PASS", "cutoff": "2026-09-29T00:00:00Z", "cutoff_semantics": "EXCLUSIVE_UTC_BOUNDARY", "datasets": ["crypto_universe", "crypto_grouped_cutoff", "crypto_history"], "findings": []}), encoding="utf-8")
            caps = td / "caps.json"
            caps.write_text(json.dumps({"run_id": "2026-09-28-eod", "attempt_id": attempt, "status": "DEGRADED", "core_failures": [], "degradations": ["stock_macro_proxies:NOT_ENTITLED", "index_macro_proxies:NOT_ENTITLED"], "optional_unavailable": [], "evaluated_capabilities": []}), encoding="utf-8")
            out = td / "pipeline"
            proc = run(PIPELINE / "run_daily_pipeline.py", "--run-id", "2026-09-28-eod", "--attempt-id", attempt, "--research-cutoff", "2026-09-29T00:00:00Z", "--crypto-universe", p_universe, "--crypto-cutoff", p_cutoff, "--crypto-history", p_history, "--data-quality", dq, "--capability-evaluation", caps, "--config", ROOT / "config" / "daily-model.json", "--out-dir", out)
            self.assertEqual(0, proc.returncode, proc.stdout + proc.stderr)
            result = json.loads((out / attempt / "pipeline-result.json").read_text(encoding="utf-8"))
            self.assertEqual("DEGRADED", result["status"])
            self.assertEqual(6, result["history_qualified_assets"])
            self.assertIn(result["market_state"], {"RISK_ON", "TRANSITION", "RISK_OFF"})
            self.assertTrue((out / attempt / "forecast-payload.json").exists())


    def test_request_gate_accepts_file_transport_for_colons_booleans_and_dates(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            ledger = td / "ledger.json"
            init = run(CONTROL / "massive_request_gate.py", "init", "--run-id", "2026-09-28-eod", "--attempt-id", "a-file", "--ledger", ledger)
            self.assertEqual(0, init.returncode, init.stdout + init.stderr)
            spec = td / "request.json"
            spec.write_text(json.dumps({
                "schema_version": 1,
                "label": "capability:crypto_universe_pit",
                "endpoint_path": "/v3/reference/tickers",
                "params": {"active": True, "date": "2026-09-28", "limit": 1000, "market": "crypto", "order": "asc", "sort": "ticker"},
            }), encoding="utf-8")
            permit = run(CONTROL / "massive_request_gate.py", "permit", "--ledger", ledger, "--request-file", spec)
            self.assertEqual(0, permit.returncode, permit.stdout + permit.stderr)
            permit_id = json.loads(permit.stdout)["permit_id"]
            result = td / "result.json"
            result.write_text(json.dumps({
                "schema_version": 1,
                "permit_id": permit_id,
                "outcome": "SUCCESS",
                "warning": None,
                "request_id": "provider:req:1",
                "row_count": 625,
                "pagination_terminal": "TRUE",
                "next_url_present": "FALSE",
            }), encoding="utf-8")
            complete = run(CONTROL / "massive_request_gate.py", "complete", "--ledger", ledger, "--result-file", result)
            self.assertEqual(0, complete.returncode, complete.stdout + complete.stderr)
            stored = json.loads(ledger.read_text(encoding="utf-8"))
            self.assertEqual("capability:crypto_universe_pit", stored["requests"][0]["label"])
            self.assertEqual("provider:req:1", stored["requests"][0]["request_id"])
            self.assertEqual(625, stored["requests"][0]["row_count"])

    def test_windows_shell_contract_uses_file_transport_and_rg_fallback(self):
        workflow = (ROOT / "workflows" / "daily-goal.md").read_text(encoding="utf-8")
        agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
        runner = (CONTROL / "run_python.ps1").read_text(encoding="utf-8")
        self.assertIn("--request-file", workflow)
        self.assertIn("--result-file", workflow)
        self.assertIn("--spec-file", workflow)
        self.assertIn("massive_materialization_spec.schema.json", workflow)
        self.assertIn("materialize_mcp_dataset.cmd", workflow)
        self.assertTrue((CONTROL / "materialize_mcp_dataset.cmd").exists())
        self.assertIn("search_repo.cmd", workflow)
        self.assertIn("Do not assume optional developer CLIs", agents)
        self.assertIn("INLINE_STRUCTURED_ARGUMENT_FORBIDDEN", runner)
        self.assertIn("INLINE_MATERIALIZATION_ARGUMENTS_FORBIDDEN", runner)
        self.assertTrue((CONTROL / "search_repo.cmd").exists())
        self.assertTrue((CONTROL / "search_repo.ps1").exists())
        self.assertNotIn("GetRelativePath", (CONTROL / "search_repo.ps1").read_text(encoding="utf-8"))

    def test_network_scanner_ignores_repo_runtime_dependencies_but_not_project_code(self):
        runtime_file = ROOT / ".runtime" / "scanner-fixture" / "Lib" / "site-packages" / "pip" / "_vendor" / "requests" / "api.py"
        runtime_file.parent.mkdir(parents=True, exist_ok=True)
        runtime_file.write_text("import " + "requests\n", encoding="utf-8")
        project_file = CONTROL / "_network_bypass_fixture.py"
        try:
            clean = run(CONTROL / "validate_control_plane.py")
            self.assertEqual(0, clean.returncode, clean.stdout + clean.stderr)
            project_file.write_text("import " + "requests\n", encoding="utf-8")
            caught = run(CONTROL / "validate_control_plane.py")
            self.assertEqual(1, caught.returncode)
            self.assertIn("direct-network-bypass:scripts/control_plane/_network_bypass_fixture.py:requests", caught.stdout)
        finally:
            if project_file.exists():
                project_file.unlink()
            import shutil
            shutil.rmtree(ROOT / ".runtime" / "scanner-fixture", ignore_errors=True)

    def test_materialization_reconciliation_blocks_orphan_research_input_and_allows_diagnostic(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            attempt = "2026-09-28-eod-attempt-reconcile"
            data_dir = td / "data" / attempt
            data_dir.mkdir(parents=True)
            acquisition = td / "acq.json"
            acquisition.write_text(json.dumps({
                "run_id": "2026-09-28-eod",
                "attempt_id": attempt,
                "datasets": []
            }), encoding="utf-8")
            meta = {
                "dataset_id": "btc_probe",
                "capability_id": "crypto_history",
                "evidence_role": "RESEARCH_INPUT",
                "run_id": "2026-09-28-eod",
                "attempt_id": attempt,
                "requirement": "CORE",
                "data_path": (data_dir / "btc_probe.jsonl").as_posix(),
                "data_digest": "sha256:" + "a" * 64,
                "row_count": 1
            }
            meta_path = data_dir / "btc_probe.meta.json"
            meta_path.write_text(json.dumps(meta), encoding="utf-8")
            blocked_out = td / "blocked.json"
            blocked = run(CONTROL / "reconcile_materializations.py", acquisition, "--data-root", td / "data", "--out", blocked_out)
            self.assertEqual(2, blocked.returncode, blocked.stdout + blocked.stderr)
            blocked_report = json.loads(blocked_out.read_text(encoding="utf-8"))
            self.assertEqual("BLOCK", blocked_report["status"])
            self.assertIn("btc_probe", blocked_report["orphaned_inputs"])

            meta["evidence_role"] = "DIAGNOSTIC"
            meta_path.write_text(json.dumps(meta), encoding="utf-8")
            pass_out = td / "pass.json"
            allowed = run(CONTROL / "reconcile_materializations.py", acquisition, "--data-root", td / "data", "--out", pass_out)
            self.assertEqual(0, allowed.returncode, allowed.stdout + allowed.stderr)
            report = json.loads(pass_out.read_text(encoding="utf-8"))
            self.assertEqual("PASS", report["status"])
            self.assertIn("btc_probe", report["diagnostics"])


    def test_daily_cutoff_contract_is_exclusive_next_midnight(self):
        from importlib.util import spec_from_file_location, module_from_spec
        spec = spec_from_file_location("cp_common", CONTROL / "common.py")
        mod = module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(mod)
        self.assertEqual([], mod.validate_daily_cutoff_contract(
            "2026-09-28-eod", "2026-09-29T00:00:00Z", "EXCLUSIVE_UTC_BOUNDARY", "fixture"
        ))
        errors = mod.validate_daily_cutoff_contract(
            "2026-09-28-eod", "2026-09-28T23:59:59Z", "EXCLUSIVE_UTC_BOUNDARY", "fixture"
        )
        self.assertTrue(any("next_utc_midnight" in item for item in errors), errors)
        bootstrap = (CONTROL / "bootstrap.ps1").read_text(encoding="utf-8")
        self.assertIn("AddDays(1)", bootstrap)
        self.assertIn("EXCLUSIVE_UTC_BOUNDARY", bootstrap)

    def test_subsecond_eod_timestamp_is_pre_cutoff_but_next_midnight_is_not(self):
        cutoff = datetime.fromisoformat("2026-09-29T00:00:00+00:00")
        last_millisecond = datetime.fromisoformat("2026-09-28T23:59:59.999+00:00")
        next_midnight = datetime.fromisoformat("2026-09-29T00:00:00+00:00")
        self.assertLess(last_millisecond, cutoff)
        self.assertFalse(next_midnight < cutoff)
        auditor = (ROOT / ".codex" / "agents" / "methodology-auditor.toml").read_text(encoding="utf-8")
        steward = (ROOT / ".codex" / "agents" / "data-steward.toml").read_text(encoding="utf-8")
        self.assertIn("23:59:59.999Z", auditor)
        self.assertIn("23:59:59.999Z", steward)

    def test_windows_validation_has_execution_policy_safe_cmd_wrappers(self):
        workflow = (ROOT / "workflows" / "daily-goal.md").read_text(encoding="utf-8")
        for name in ("validate_artifact.cmd", "validate_control_plane.cmd", "run_tests.cmd"):
            self.assertTrue((CONTROL / name).is_file(), name)
            self.assertIn(name, workflow)
        self.assertIn("do not invoke `run_python.ps1` directly", workflow.lower())


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import argparse
import json
import re
import sys
import tomllib
from pathlib import Path

sys.dont_write_bytecode = True

from path_policy import TRANSIENT_PARTS, TRANSIENT_SUFFIXES, is_project_source

ROOT = Path(__file__).resolve().parents[2]

AGENTS = [
    "data-steward", "crypto-internals", "relative-value", "macro-regime",
    "institutional-intelligence", "factor-researcher", "statistical-validator",
    "portfolio-risk", "methodology-auditor",
]
WORKFLOW_SKILLS = [
    "daily-research-run", "factor-research", "candidate-validation",
    "methodology-audit", "oos-scorekeeping",
]
SUPPORT_SKILLS = ["massive-basic-endpoints", "massive-mcp-data-plane", "candidate-promotion", "performance-governance", "fin-data-mcp"]
SKILLS = WORKFLOW_SKILLS + SUPPORT_SKILLS
SCHEMAS = [
    "hypothesis.schema.json", "agent_handoff.schema.json", "validation_report.schema.json",
    "audit_report.schema.json", "data_quality_report.schema.json", "forecast_record.schema.json",
    "outcome_record.schema.json", "promotion_decision.schema.json",
    "massive_acquisition_manifest.schema.json",
    "capability_probe_report.schema.json", "capability_evaluation.schema.json",
    "materialized_dataset.schema.json", "daily_pipeline_result.schema.json",
    "massive_request_ledger.schema.json",
    "windows_bootstrap.schema.json", "python_runtime.schema.json",
    "massive_request_spec.schema.json", "massive_request_result.schema.json",
    "massive_materialization_spec.schema.json", "materialization_reconciliation.schema.json",
    "source_registry.schema.json", "source_qualification.schema.json",
    "source_acquisition_manifest.schema.json", "evidence_bundle.schema.json",
    "fin_data_request.schema.json", "fin_data_result.schema.json",
    "fin_data_qualification_report.schema.json",
    "fin_data_response_contracts.schema.json",
]
MASSIVE_MCP_URL = "https://mcp.massive.com/"


def parse_skill_frontmatter(path: Path) -> tuple[dict[str, str], str]:
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise ValueError("missing opening YAML frontmatter delimiter")
    try:
        end = next(i for i in range(1, len(lines)) if lines[i].strip() == "---")
    except StopIteration as exc:
        raise ValueError("missing closing YAML frontmatter delimiter") from exc
    meta: dict[str, str] = {}
    for line in lines[1:end]:
        if not line.strip():
            continue
        if ":" not in line:
            raise ValueError(f"unsupported frontmatter line: {line}")
        key, value = line.split(":", 1)
        meta[key.strip()] = value.strip().strip('"\'')
    return meta, "\n".join(lines[end + 1:]).strip()


def check_skill(name: str, errors: list[str]) -> None:
    skill_dir = ROOT / ".agents" / "skills" / name
    path = skill_dir / "SKILL.md"
    if not path.is_file():
        errors.append(f"missing-skill:{name}")
        return
    try:
        meta, body = parse_skill_frontmatter(path)
    except ValueError as exc:
        errors.append(f"invalid-skill-frontmatter:{name}:{exc}")
        return
    if meta.get("name") != name:
        errors.append(f"skill-name-mismatch:{name}:{meta.get('name', '')}")
    description = meta.get("description", "")
    if not description:
        errors.append(f"skill-missing-description:{name}")
    elif len(description) > 1024:
        errors.append(f"skill-description-too-long:{name}:{len(description)}")
    elif "use " not in description.lower():
        errors.append(f"skill-description-missing-activation-boundary:{name}")
    if not body:
        errors.append(f"skill-empty-body:{name}")

    if "../../../" in body or "..\\..\\..\\" in body:
        errors.append(f"skill-parent-relative-project-reference:{name}")
    if "Repository path contract:" not in body:
        errors.append(f"skill-missing-project-root-contract:{name}")
    if name == "daily-research-run":
        bundled = skill_dir / "references" / "daily-goal.md"
        authoritative = ROOT / "workflows" / "daily-goal.md"
        if not bundled.is_file():
            errors.append("daily-skill-missing-bundled-workflow-reference")
        elif bundled.read_bytes() != authoritative.read_bytes():
            errors.append("daily-skill-workflow-reference-drift")

    for nested in re.findall(r"\$([a-z0-9][a-z0-9-]*)", body):
        if nested not in SKILLS:
            errors.append(f"skill-unknown-nested-skill:{name}:{nested}")

    sidecar = skill_dir / "agents" / "openai.yaml"
    if not sidecar.is_file():
        errors.append(f"skill-missing-openai-yaml:{name}")
        return
    text = sidecar.read_text(encoding="utf-8")
    for field in ("display_name:", "short_description:", "default_prompt:"):
        if field not in text:
            errors.append(f"skill-openai-yaml-missing:{name}:{field[:-1]}")
    match = re.search(r'^\s*short_description:\s*"([^"]*)"\s*$', text, re.MULTILINE)
    if match and not 25 <= len(match.group(1)) <= 64:
        errors.append(f"skill-short-description-length:{name}:{len(match.group(1))}")
    if f"${name}" not in text:
        errors.append(f"skill-default-prompt-missing-explicit-name:{name}")

    if name == "massive-mcp-data-plane":
        required_fragments = [
            'type: "mcp"', 'value: "massive"',
            'transport: "streamable_http"', f'url: "{MASSIVE_MCP_URL}"',
        ]
        for fragment in required_fragments:
            if fragment not in text:
                errors.append(f"massive-mcp-skill-dependency-missing:{fragment}")


def check_agent(name: str, errors: list[str]) -> None:
    path = ROOT / ".codex" / "agents" / f"{name}.toml"
    if not path.is_file():
        errors.append(f"missing-agent:{name}")
        return
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        errors.append(f"invalid-agent-toml:{name}:{exc}")
        return
    for field in ("name", "description", "developer_instructions"):
        if not data.get(field):
            errors.append(f"agent-missing:{name}:{field}")
    if data.get("name") != name:
        errors.append(f"agent-name-mismatch:{name}:{data.get('name', '')}")
    if "sandbox_mode" in data:
        errors.append(f"agent-role-sandbox-mode-not-enforced:{name}")


def check_python_network_bypass(errors: list[str]) -> None:
    forbidden = {
        "import requests": "requests",
        "from requests": "requests",
        "import httpx": "httpx",
        "from httpx": "httpx",
        "import urllib.request": "urllib.request",
        "MASSIVE_API_KEY": "MASSIVE_API_KEY",
        "POLYGON_API_KEY": "POLYGON_API_KEY",
    }
    validator_path = Path(__file__).resolve()
    governed_mcp_path = ROOT / "scripts" / "control_plane" / "fin_data_mcp_client.py"
    governed_mcp_text = governed_mcp_path.read_text(encoding="utf-8") if governed_mcp_path.is_file() else ""
    governed_mcp_transport = all(marker in governed_mcp_text for marker in (
        "configured_endpoint_identity_mismatch", "fin_data_request_gate.py",
        "MCP-Protocol-Version", "Streamable HTTP MCP client"))
    for path in ROOT.rglob("*.py"):
        if path.resolve() == validator_path or not is_project_source(path, ROOT):
            continue
        text = path.read_text(encoding="utf-8")
        for needle, label in forbidden.items():
            # urllib is allowed only inside the source-specific Streamable HTTP
            # MCP client after its endpoint, permit/record, and protocol guards
            # remain present. This is MCP transport, not provider REST access.
            if (label == "urllib.request" and path.resolve() == governed_mcp_path.resolve()
                    and governed_mcp_transport):
                continue
            if needle in text:
                errors.append(f"direct-network-bypass:{path.relative_to(ROOT).as_posix()}:{label}")


def check_package_hygiene(errors: list[str]) -> None:
    for path in ROOT.rglob("*"):
        rel = path.relative_to(ROOT)
        if any(part in TRANSIENT_PARTS for part in rel.parts):
            errors.append(f"transient-path:{rel.as_posix()}")
        elif path.is_file() and path.suffix.lower() in TRANSIENT_SUFFIXES:
            errors.append(f"transient-file:{rel.as_posix()}")



def check_daily_config(errors: list[str]) -> None:
    try:
        matrix = json.loads((ROOT / "config" / "daily-capabilities.json").read_text(encoding="utf-8"))
        capabilities = matrix.get("capabilities", [])
        ids = [item.get("capability_id") for item in capabilities if isinstance(item, dict)]
        if len(ids) != len(set(ids)):
            errors.append("daily-capabilities:duplicate-capability-id")
        requirements = {item.get("requirement") for item in capabilities if isinstance(item, dict)}
        if not {"CORE", "ENRICHMENT", "EVENT_OPTIONAL"}.issubset(requirements):
            errors.append(f"daily-capabilities:missing-requirement-class:{sorted(requirements)}")
        required_core = {"crypto_universe_pit", "crypto_grouped_eod", "crypto_history"}
        core_ids = {item.get("capability_id") for item in capabilities if isinstance(item, dict) and item.get("requirement") == "CORE"}
        if not required_core.issubset(core_ids):
            errors.append(f"daily-capabilities:missing-core:{sorted(required_core-core_ids)}")
    except Exception as exc:
        errors.append(f"daily-capabilities:invalid:{exc}")


def check_fin_data_config(errors: list[str]) -> None:
    try:
        source = json.loads((ROOT / "config" / "source-capabilities" / "fin-data.json").read_text(encoding="utf-8"))
        policy = json.loads((ROOT / "config" / "fin-data-request-policy.json").read_text(encoding="utf-8"))
        contracts = json.loads((ROOT / "config" / "fin-data-response-contracts.json").read_text(encoding="utf-8"))
        response_schema = json.loads((ROOT / "schemas" / "fin_data_response_contracts.schema.json").read_text(encoding="utf-8"))
        from validate_artifact import validate as validate_schema
        errors.extend(f"fin-data-response-contracts.schema:{item}" for item in validate_schema(contracts, response_schema))
        ids = [item.get("capability_id") for item in source.get("capabilities", [])]
        if source.get("source_id") != "fin_data_mcp_render_prod":
            errors.append("fin-data-capabilities:source-identity-mismatch")
        if len(ids) != len(set(ids)) or not ids:
            errors.append("fin-data-capabilities:duplicate-or-empty-identities")
        for item in source.get("capabilities", []):
            if item.get("requirement") not in {"CORE", "ENRICHMENT", "ASSET_OPTIONAL", "EVENT_OPTIONAL"}:
                errors.append(f"fin-data-capabilities:invalid-requirement:{item.get('capability_id')}")
            if item.get("severity") not in {"INFO", "DEGRADED", "BLOCKING"}:
                errors.append(f"fin-data-capabilities:invalid-severity:{item.get('capability_id')}")
            if item.get("admission") != "DISABLED_UNTIL_QUALIFIED":
                errors.append(f"fin-data-capabilities:unexpected-admission:{item.get('capability_id')}")
            if not str(item.get("tool_name", "")).startswith("crypto_"):
                errors.append(f"fin-data-capabilities:non-crypto-tool:{item.get('capability_id')}")
        if policy.get("source_id") != source.get("source_id") or policy.get("require_permit_before_call") is not True:
            errors.append("fin-data-request-policy:invalid-source-or-permit")
        if policy.get("record_result_immediately") is not True or policy.get("halt_on_rate_limit_warning") is not True:
            errors.append("fin-data-request-policy:missing-result-or-rate-limit-control")
        if policy.get("max_in_flight") != 1 or policy.get("rate_limit_recovery") != "NEW_ATTEMPT_REQUIRED":
            errors.append("fin-data-request-policy:invalid-concurrency-or-recovery")
        contract_ids = [item.get("capability_id") for item in contracts.get("contracts", [])]
        if contracts.get("source_id") != source.get("source_id") or set(contract_ids) != set(ids) or len(contract_ids) != len(set(contract_ids)):
            errors.append("fin-data-response-contracts:capability-identity-mismatch")
        for contract in contracts.get("contracts", []):
            if contract.get("status") == "REGISTERED" and (
                not contract.get("required_fields") or not contract.get("field_types")
                or not isinstance(contract.get("max_age_seconds"), int)
                or contract.get("pagination_mode") not in {"SINGLE_RESPONSE", "CURSOR", "PAGE_TOKEN", "NONE"}
            ):
                errors.append(f"fin-data-response-contracts:incomplete:{contract.get('capability_id')}")
    except Exception as exc:
        errors.append(f"fin-data-config:invalid:{exc}")
    try:
        model = json.loads((ROOT / "config" / "daily-model.json").read_text(encoding="utf-8"))
        weights = model.get("factor_weights", {})
        if abs(sum(float(value) for value in weights.values()) - 1.0) > 1e-9:
            errors.append("daily-model:factor-weights-must-sum-to-1")
        if int(model.get("minimum_history_observations", 0)) < 30:
            errors.append("daily-model:minimum-history-too-small")
        if int(model.get("eligible_top_n", 0)) < 5:
            errors.append("daily-model:eligible-top-n-too-small")
    except Exception as exc:
        errors.append(f"daily-model:invalid:{exc}")
    try:
        policy = json.loads((ROOT / "config" / "massive-request-policy.json").read_text(encoding="utf-8"))
        if policy.get("covered_operation") != "call_api":
            errors.append("massive-request-policy:covered-operation-must-be-call-api")
        maximum = int(policy.get("max_requests_per_window", 0))
        window = float(policy.get("window_seconds", 0))
        interval = float(policy.get("minimum_interval_seconds", -1))
        if maximum < 1 or window <= 0:
            errors.append("massive-request-policy:invalid-window")
        elif interval + 1e-9 < window / maximum:
            errors.append("massive-request-policy:minimum-interval-too-small")
        if policy.get("halt_on_rate_limit_warning") is not True:
            errors.append("massive-request-policy:must-halt-on-rate-limit")
        if policy.get("rate_limit_recovery") != "NEW_ATTEMPT_REQUIRED":
            errors.append("massive-request-policy:recovery-must-require-new-attempt")
    except Exception as exc:
        errors.append(f"massive-request-policy:invalid:{exc}")
    try:
        runtime = json.loads((ROOT / "config" / "python-runtime-policy.json").read_text(encoding="utf-8"))
        if runtime.get("minimum_version") != "3.11":
            errors.append("python-runtime-policy:minimum-version-must-be-3.11")
        if runtime.get("allow_uv_locator") is not True:
            errors.append("python-runtime-policy:uv-locator-must-be-enabled")
        if runtime.get("allow_windows_registry_scan") is not True:
            errors.append("python-runtime-policy:registry-scan-must-be-enabled")
        if runtime.get("allow_uv_managed_scan") is not True:
            errors.append("python-runtime-policy:uv-managed-scan-must-be-enabled")
        if runtime.get("allow_repo_local_uv_provision") is not True:
            errors.append("python-runtime-policy:repo-local-provision-must-be-enabled")
        if runtime.get("auto_install_scope") != "REPO_LOCAL_ONLY":
            errors.append("python-runtime-policy:auto-install-scope-must-be-repo-local-only")
    except Exception as exc:
        errors.append(f"python-runtime-policy:invalid:{exc}")


def check_release_state_clean(errors: list[str]) -> None:
    governed = ["research/acquisitions", "research/runs", "research/forecasts", "research/data", "research/pipeline"]
    for rel in governed:
        root = ROOT / rel
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if path.is_file() and path.name != ".gitkeep":
                errors.append(f"release-seeded-runtime-artifact:{path.relative_to(ROOT).as_posix()}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--package", action="store_true", help="also fail on transient packaging artifacts")
    args = ap.parse_args()

    errors: list[str] = []
    required = [
        "AGENTS.md", ".codex/config.toml", "workflows/daily-goal.md", "workflows/research-goal.md",
        "docs/data-capability-boundary.md", "docs/massive-mcp-data-plane.md",
        "docs/research-state-model.md", "contracts/agent-handoff.md",
        "scripts/control_plane/seal_acquisition.py",
        "scripts/control_plane/preflight.py", "scripts/control_plane/discover_run.py",
        "scripts/control_plane/evaluate_capabilities.py", "scripts/control_plane/materialize_mcp_dataset.py", "scripts/control_plane/materialize_mcp_dataset.cmd", "scripts/control_plane/reconcile_materializations.py", "scripts/control_plane/path_policy.py",
        "scripts/control_plane/massive_request_gate.py",
        "scripts/control_plane/fin_data_source.py", "scripts/control_plane/fin_data_request_gate.py",
        "scripts/control_plane/fin_data_mcp_client.py",
        "scripts/control_plane/source_evidence.py", "scripts/control_plane/validate_sources.py",
        "scripts/control_plane/seal_source_acquisition.py", "scripts/control_plane/build_evidence_bundle.py", "scripts/control_plane/verify_evidence_bundle.py",
        "scripts/control_plane/bootstrap.cmd", "scripts/control_plane/bootstrap.ps1",
        "scripts/control_plane/search_repo.cmd", "scripts/control_plane/search_repo.ps1",
        "scripts/control_plane/validate_artifact.py", "scripts/control_plane/validate_artifact.cmd", "scripts/control_plane/validate_control_plane.cmd", "scripts/control_plane/run_tests.cmd", "scripts/control_plane/run_python.cmd", "scripts/control_plane/run_python.ps1", "scripts/control_plane/run_tests.py", "scripts/pipeline/run_daily_pipeline.py",
        ".agents/skills/massive-basic-endpoints/scripts/endpoint_lookup.ps1",
        "config/daily-capabilities.json", "config/daily-model.json", "config/massive-request-policy.json", "config/python-runtime-policy.json",
        "config/source-registry.json", "docs/evidence-bundle-contract.md",
        "config/source-capabilities/fin-data.json", "config/fin-data-request-policy.json",
        "config/fin-data-response-contracts.json",
    ]
    for rel in required:
        if not (ROOT / rel).is_file():
            errors.append(f"missing:{rel}")

    try:
        config = tomllib.loads((ROOT / ".codex" / "config.toml").read_text(encoding="utf-8"))
        agent_cfg = config.get("agents", {})
        if "job_max_runtime_seconds" in agent_cfg:
            errors.append("obsolete-agent-config:job_max_runtime_seconds")
        if "max_threads" in agent_cfg:
            errors.append("legacy-agent-config:max_threads")
        if agent_cfg.get("max_depth") != 1:
            errors.append(f"agent-config-max-depth:{agent_cfg.get('max_depth', 'MISSING')}")
        massive_cfg = config.get("mcp_servers", {}).get("massive", {})
        if massive_cfg.get("url") != MASSIVE_MCP_URL:
            errors.append(f"massive-mcp-config-url:{massive_cfg.get('url', 'MISSING')}")
        fin_cfg = config.get("mcp_servers", {}).get("fin_data", {})
        if fin_cfg.get("url") != "https://fin-data-mcp-http-v02-prod.onrender.com/mcp":
            errors.append(f"fin-data-mcp-config-url:{fin_cfg.get('url', 'MISSING')}")
    except (OSError, tomllib.TOMLDecodeError) as exc:
        errors.append(f"invalid-config-toml:{exc}")

    agents_text = (ROOT / "AGENTS.md").read_text(encoding="utf-8") if (ROOT / "AGENTS.md").is_file() else ""
    for phrase in ("Massive MCP", "$massive-mcp-data-plane", "Do not bypass", "bootstrap.cmd", "run_python.cmd", "request-file", "materialization spec", "materialize_mcp_dataset.cmd", "search_repo.cmd"):
        if phrase not in agents_text:
            errors.append(f"agents-missing-massive-policy:{phrase}")

    for name in AGENTS:
        check_agent(name, errors)
    for name in SKILLS:
        check_skill(name, errors)
    for name in SCHEMAS:
        path = ROOT / "schemas" / name
        try:
            json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            errors.append(f"invalid-schema-json:{name}:{exc}")

    check_daily_config(errors)
    check_fin_data_config(errors)
    try:
        from validate_sources import validate as validate_source_registry
        source_registry = json.loads((ROOT / "config" / "source-registry.json").read_text(encoding="utf-8"))
        errors.extend(validate_source_registry(source_registry))
        source_ids = {item.get("source_id") for item in source_registry.get("sources", [])}
        if "massive_mcp" not in source_ids:
            errors.append("source-registry:massive-mcp-identity-missing")
        if "fin_data_mcp_render_prod" not in source_ids:
            errors.append("source-registry:fin-data-identity-missing")
    except Exception as exc:
        errors.append(f"source-registry:invalid:{exc}")
    check_python_network_bypass(errors)
    if args.package:
        check_package_hygiene(errors)
        check_release_state_clean(errors)

    if errors:
        print("\n".join(sorted(set(errors))))
        return 1
    print(
        f"PASS: {len(AGENTS)} agents, {len(SKILLS)} skills "
        f"({len(WORKFLOW_SKILLS)} workflow + {len(SUPPORT_SKILLS)} support), "
        f"{len(SCHEMAS)} schemas, Massive and Fin Data MCP configured, deterministic daily pipeline present"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

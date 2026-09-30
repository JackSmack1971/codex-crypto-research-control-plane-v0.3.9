from __future__ import annotations

import copy
import hashlib
import json
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts/control_plane"))
from common import digest
from source_rights import admission_rights_result, rights_result, snapshot_digest, validate_snapshot


def permitted_snapshot(provider="provider-a", dataset="data-a", expires_at=None):
    evidence_path = "research/sources/rights/okx-terms-review-2026-09-30.md"
    evidence_digest = "sha256:" + hashlib.sha256((ROOT / evidence_path).read_bytes()).hexdigest()
    return {"schema_version": "1.0", "rights_snapshot_id": provider + "-rights-1",
            "upstream_provider_id": provider, "upstream_dataset_id": dataset,
            "terms": {"url": "https://example.org/terms", "version": "v1", "effective_date": None,
                      "contracting_entity": None, "jurisdiction": None},
            "intended_use": "institutional research and durable storage",
            "use_matrix": {"research": "PERMITTED", "durable_storage": "PERMITTED",
                           "deterministic_derivation": "PERMITTED", "ai_llm_processing": "PERMITTED",
                           "redistribution_publication": "UNKNOWN", "institutional_commercial": "PERMITTED"},
            "required_evidence": ["license"], "evidence": [{"url": "https://example.org/terms", "digest": evidence_digest,
                           "captured_at": "2026-09-30T00:00:00Z", "provenance": "test evidence fixture",
                           "provenance_path": evidence_path}], "qualification_result": "PASS",
            "review": {"reviewer": "human-reviewer", "rationale": "scope-matched signed license", "authorization_documented": True},
            "effective_at": "2026-09-30T00:00:00Z", "expires_at": expires_at}


class SourceRightsTests(unittest.TestCase):
    def test_current_upstream_rights_inventory_validates_and_stays_blocked(self):
        config = json.loads((ROOT / "config/source-rights.json").read_text(encoding="utf-8"))
        self.assertEqual(2, len(config["rights_snapshots"]))
        for snapshot in config["rights_snapshots"]:
            self.assertEqual([], validate_snapshot(snapshot))
        self.assertEqual("BLOCK", admission_rights_result("fin.crypto.funding", "PASS", config)[0])
        self.assertEqual("BLOCK", admission_rights_result("fin.crypto.open_interest", "PASS", config)[0])

    def test_runtime_pass_and_rights_block_blocks_admission(self):
        config = {"rights_snapshots": [{**permitted_snapshot(), "qualification_result": "BLOCK"}],
                  "capability_sources": [{"capability_id": "cap-a", "upstream_provider_id": "provider-a", "upstream_dataset_id": "data-a"}]}
        self.assertEqual("BLOCK", admission_rights_result("cap-a", "PASS", config)[0])

    def test_unknown_rights_fail_closed_for_research_inputs(self):
        config = {"rights_snapshots": [{**permitted_snapshot(), "qualification_result": "UNKNOWN"}],
                  "capability_sources": [{"capability_id": "cap-a", "upstream_provider_id": "provider-a", "upstream_dataset_id": "data-a"}]}
        self.assertEqual("UNKNOWN", admission_rights_result("cap-a", "PASS", config)[0])

    def test_mcp_registration_cannot_confer_upstream_rights(self):
        config = {"rights_snapshots": [], "mcp_sources": ["registered-server"],
                  "capability_sources": [{"capability_id": "cap-a", "upstream_provider_id": "provider-a", "upstream_dataset_id": "data-a"}]}
        self.assertEqual("UNKNOWN", admission_rights_result("cap-a", "PASS", config)[0])

    def test_one_blocked_provider_does_not_block_unrelated_qualified_provider(self):
        snapshots = [{**permitted_snapshot("a", "da"), "qualification_result": "BLOCK"}, permitted_snapshot("b", "db")]
        config = {"rights_snapshots": snapshots, "capability_sources": [
            {"capability_id": "cap-a", "upstream_provider_id": "a", "upstream_dataset_id": "da"},
            {"capability_id": "cap-b", "upstream_provider_id": "b", "upstream_dataset_id": "db"}]}
        self.assertEqual("BLOCK", admission_rights_result("cap-a", "PASS", config)[0])
        self.assertEqual("PASS", admission_rights_result("cap-b", "PASS", config)[0])

    def test_provider_substitution_requires_exact_capability_mapping(self):
        config = {"rights_snapshots": [permitted_snapshot("a", "da"), permitted_snapshot("b", "db")],
                  "capability_sources": [{"capability_id": "cap-a", "upstream_provider_id": "a", "upstream_dataset_id": "da"}]}
        status, bound = admission_rights_result("cap-a", "PASS", config)
        self.assertEqual("PASS", status)
        self.assertEqual(snapshot_digest(config["rights_snapshots"][0]), bound)
        self.assertEqual(("UNKNOWN", None), admission_rights_result("cap-a-from-b", "PASS", config))

    def test_expiry_affects_new_snapshot_only_and_old_provenance_digest_is_stable(self):
        old = permitted_snapshot(expires_at="2026-09-29T00:00:00Z")
        prior_digest = snapshot_digest(old)
        self.assertEqual("UNKNOWN", rights_result(old, "2026-09-30T00:00:00Z"))
        self.assertEqual(prior_digest, snapshot_digest(old))
        refreshed = copy.deepcopy(old); refreshed["rights_snapshot_id"] = "provider-a-rights-2"
        refreshed["expires_at"] = None
        self.assertEqual("PASS", rights_result(refreshed, "2026-09-30T00:00:00Z"))
        self.assertNotEqual(prior_digest, snapshot_digest(refreshed))

    def test_unknown_or_missing_rights_snapshot_cannot_be_marked_pass(self):
        snap = permitted_snapshot(); snap["review"]["authorization_documented"] = False
        self.assertEqual("UNKNOWN", rights_result(snap))
        self.assertIn("rights.pass_without_documented_authorization", validate_snapshot(snap))

    def test_frozen_rights_snapshot_is_not_rewritten_by_current_policy_change(self):
        frozen = permitted_snapshot(); frozen_digest = snapshot_digest(frozen)
        current = copy.deepcopy(frozen); current["qualification_result"] = "BLOCK"
        self.assertEqual("BLOCK", rights_result(current))
        self.assertEqual(frozen_digest, snapshot_digest(frozen))


if __name__ == "__main__":
    unittest.main()

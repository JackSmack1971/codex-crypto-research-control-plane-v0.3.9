from __future__ import annotations
import json, sys, tempfile, unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"scripts/control_plane"))
from common import digest
from source_evidence import validate_bundle, validate_source_manifest
from build_evidence_bundle import build

class SourceEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.root=Path(self.tmp.name)
        self.manifest={"schema_version":"1.0","manifest_id":"m-1","run_id":"2026-09-28-eod","attempt_id":"a-1","created_at":"2026-09-29T01:00:00Z","research_cutoff":"2026-09-29T00:00:00Z","source":{"source_id":"source-a","identity_digest":"sha256:"+"b"*64,"provider":"Fixture","runtime":"test","transport":"offline","adapter_id":"fixture","adapter_version":"1","capability_ids":["prices"]},"capability_id":"prices","discovery_status":"DISCOVERED","availability_status":"AVAILABLE","qualification":"QUALIFIED","admissibility":"ADMITTED","status":"COMPLETE","degradation_reason":None,"datasets":[{"dataset_id":"prices-1","data_digest":"sha256:"+"a"*64,"evidence_role":"RESEARCH_INPUT","status":"COMPLETE","pagination_complete":True,"row_count":1,"observed_at":"2026-09-28T23:59:00Z","freshness_seconds":60,"max_age_seconds":86400,"qualification":"QUALIFIED","admissibility":"ADMITTED"}]}
        self.manifest["source"]["identity_digest"]=digest({k:v for k,v in self.manifest["source"].items() if k!="identity_digest"})
        self.manifest["content_digest"]=digest(self.manifest)
        (self.root/"manifest.json").write_text(json.dumps(self.manifest),encoding="utf-8")
    def tearDown(self): self.tmp.cleanup()
    def bundle(self, members=None):
        b={"schema_version":"1.0","bundle_id":"b-1","run_id":self.manifest["run_id"],"attempt_id":self.manifest["attempt_id"],"research_cutoff":self.manifest["research_cutoff"],"members":members or [{"source_id":"source-a","manifest_id":"m-1","manifest_path":"manifest.json","manifest_digest":self.manifest["content_digest"],"status":"COMPLETE","qualification":"QUALIFIED","admissibility":"ADMITTED"}]}
        b["content_digest"]=digest(b); return b
    def test_valid_manifest_and_bundle(self):
        self.assertEqual([],validate_source_manifest(self.manifest)); self.assertEqual([],validate_bundle(self.bundle(),self.root))
    def test_builder_sorts_members_and_binds_exact_manifest(self):
        output=build([self.root/"manifest.json"],self.manifest["run_id"],self.manifest["attempt_id"],self.manifest["research_cutoff"],self.root)
        self.assertEqual([],validate_bundle(output,self.root)); self.assertEqual(self.manifest["content_digest"],output["members"][0]["manifest_digest"])
    def test_duplicate_source_identity_rejected(self):
        m=self.bundle()["members"][0]; self.assertTrue(any("duplicate_source_identity" in e for e in validate_bundle(self.bundle([m,m]),self.root)))
    def test_manifest_digest_tampering_rejected(self):
        changed=dict(self.manifest); changed["status"]="DEGRADED"
        self.assertIn("manifest.content_digest_mismatch",validate_source_manifest(changed))
    def test_source_identity_digest_cannot_be_substituted(self):
        changed=json.loads(json.dumps(self.manifest)); changed["source"]["provider"]="Imposter"; changed["content_digest"]=digest({k:v for k,v in changed.items() if k!="content_digest"})
        self.assertIn("manifest.source_identity_digest_mismatch",validate_source_manifest(changed))
    def test_bundle_digest_binding_tampering_and_substitution_rejected(self):
        b=self.bundle(); b["members"][0]["manifest_digest"]="sha256:"+"f"*64; b["content_digest"]=digest({k:v for k,v in b.items() if k!="content_digest"})
        self.assertTrue(any("manifest_digest_binding_mismatch" in e for e in validate_bundle(b,self.root)))
        b=self.bundle(); b["members"][0]["source_id"]="substituted"; b["content_digest"]=digest({k:v for k,v in b.items() if k!="content_digest"})
        self.assertTrue(any("source_identity_mismatch" in e for e in validate_bundle(b,self.root)))
    def test_unavailable_degraded_stale_unqualified_and_not_admitted(self):
        cases=[("availability_status","UNAVAILABLE"),("status","DEGRADED"),("qualification","UNQUALIFIED"),("admissibility","NOT_ADMITTED")]
        for key,value in cases:
            with self.subTest(key=key):
                m=json.loads(json.dumps(self.manifest)); m[key]=value
                if key=="status": m["degradation_reason"]="fixture unavailable"
                m["content_digest"]=digest({k:v for k,v in m.items() if k!="content_digest"})
                # DEGRADED is a valid, explicitly represented source state; invalid trust states cannot feed research.
                if key == "status":
                    self.assertEqual([], validate_source_manifest(m))
                    member=self.bundle()["members"][0]; member["status"]="DEGRADED"; member["manifest_digest"]=m["content_digest"]
                    b=self.bundle([member]); b["content_digest"]=digest({k:v for k,v in b.items() if k!="content_digest"})
                    (self.root/"manifest.json").write_text(json.dumps(m),encoding="utf-8")
                    self.assertEqual([], validate_bundle(b,self.root))
                    self.assertNotEqual("COMPLETE",b["members"][0]["status"])
                    (self.root/"manifest.json").write_text(json.dumps(self.manifest),encoding="utf-8")
                else:
                    self.assertTrue(validate_source_manifest(m))
        stale=json.loads(json.dumps(self.manifest)); stale["datasets"][0]["observed_at"]="2026-09-29T00:00:00Z"; stale["content_digest"]=digest({k:v for k,v in stale.items() if k!="content_digest"})
        self.assertTrue(any("at_or_after_cutoff" in e for e in validate_source_manifest(stale)))
        stale=json.loads(json.dumps(self.manifest)); stale["datasets"][0]["max_age_seconds"]=1; stale["content_digest"]=digest({k:v for k,v in stale.items() if k!="content_digest"})
        self.assertIn("dataset[0].stale_observation",validate_source_manifest(stale))
        missing_bound=json.loads(json.dumps(self.manifest)); del missing_bound["datasets"][0]["max_age_seconds"]; missing_bound["content_digest"]=digest({k:v for k,v in missing_bound.items() if k!="content_digest"})
        self.assertTrue(any("missing:max_age_seconds" in e for e in validate_source_manifest(missing_bound)))
        m=json.loads(json.dumps(self.manifest)); m["datasets"][0]["qualification"]="UNQUALIFIED"; m["content_digest"]=digest({k:v for k,v in m.items() if k!="content_digest"})
        self.assertTrue(any("not_qualified_and_admitted" in e for e in validate_source_manifest(m)))

from __future__ import annotations

import json
import unittest
from pathlib import Path

from helpyou_core.source_registry import (
    CurrencyStatus,
    SourceRegistryError,
    SourceRole,
    load_manifest,
    manifest_from_mapping,
)


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "fixtures" / "sq23_source_manifest_rev20.json"
SQ23_FIXTURE = ROOT / "fixtures" / "sq23_oei_etp1_1d.json"


class SourceRegistryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.manifest = load_manifest(MANIFEST)
        cls.fixture = json.loads(SQ23_FIXTURE.read_text(encoding="utf-8"))

    def test_bundle_is_metadata_only(self) -> None:
        self.assertFalse(self.manifest.raw_files_committed)
        self.assertTrue(all(not item.raw_content_in_repository for item in self.manifest.sources))

    def test_primary_fcom_is_rev20(self) -> None:
        fcom = next(
            item for item in self.manifest.sources
            if item.source_id == "SIA-A350-FCOM-REV20"
        )
        self.assertEqual(fcom.revision, "Rev 20")
        self.assertEqual(fcom.issue_date, "06.05.26")
        self.assertTrue(fcom.controlling)
        self.assertEqual(fcom.currency_status, CurrencyStatus.CURRENT_FOR_BUNDLE)

    def test_om_rev32_is_current_controlling_policy_source(self) -> None:
        om = next(
            item for item in self.manifest.sources
            if item.source_id == "SIA-OM-REV32"
        )
        self.assertTrue(om.controlling)
        self.assertEqual(om.role, SourceRole.CONTROLLED_OPERATIONAL)
        self.assertEqual(om.issue_date, "01.04.26")
        self.assertIn("document priority", om.authority_scope)
        self.assertIn("EDTO", om.authority_scope)
        self.assertIn("nearest suitable airport", om.authority_scope)

    def test_fctm_is_current_operator_guidance_but_cannot_override(self) -> None:
        fctm = next(
            item for item in self.manifest.sources
            if item.source_id == "SIA-A350-FCTM-V2-REV1"
        )
        self.assertTrue(fctm.controlling)
        self.assertEqual(fctm.role, SourceRole.CONTROLLED_OPERATOR_GUIDANCE)
        prohibited = " ".join(fctm.prohibited_uses)
        self.assertIn("overriding", prohibited)
        self.assertIn("OM", prohibited)
        self.assertIn("FCOM", prohibited)
        self.assertIn("MEL", prohibited)

    def test_qrh_requires_explicit_currency_reconciliation(self) -> None:
        qrh = next(
            item for item in self.manifest.sources
            if item.source_id == "SIA-A350-QRH-REV18"
        )
        self.assertTrue(qrh.controlling)
        self.assertEqual(qrh.currency_status, CurrencyStatus.CURRENCY_CHECK_REQUIRED)

    def test_training_aids_cannot_be_operational_authority(self) -> None:
        ids = {
            "A350-FLS-FAPP-TRAINING-REF",
            "A350-FCOM20-LIMITATIONS-STUDY-GUIDE",
            "AIRBUS-MAIN-CHANGES-OCT25",
        }
        for source in self.manifest.sources:
            if source.source_id in ids:
                self.assertFalse(source.controlling)
                self.assertEqual(source.role, SourceRole.SUPPORTING_SYNTHESIS)

    def test_cognitive_sources_do_not_generate_aircraft_procedures(self) -> None:
        cognitive = [
            item for item in self.manifest.sources
            if item.role is SourceRole.COGNITIVE_FOUNDATION
        ]
        self.assertTrue(cognitive)
        self.assertTrue(all(not item.controlling for item in cognitive))
        prohibited = " ".join(
            item
            for source in cognitive
            for item in source.prohibited_uses
        )
        self.assertIn("aircraft procedure", prohibited)

    def test_production_gaps_are_updated_after_om_review(self) -> None:
        text = " ".join(self.manifest.required_missing_sources)
        self.assertNotIn("Current SIA OM-A", text)
        self.assertIn("MEL and CDL source text", text)
        self.assertIn("FCTM Volume 1", text)
        self.assertIn("Airport-specific approved EFB", text)
        self.assertIn("live operational weather", text)

    def test_private_source_bytes_are_rejected(self) -> None:
        data = json.loads(MANIFEST.read_text(encoding="utf-8"))
        data["sources"][1]["raw_content_in_repository"] = True
        with self.assertRaises(SourceRegistryError):
            manifest_from_mapping(data)

    def test_sq23_fixture_uses_registered_bundle(self) -> None:
        self.assertEqual(self.fixture["source_bundle_id"], self.manifest.bundle_id)
        self.assertEqual(
            self.fixture["source_manifest"],
            "sq23_source_manifest_rev20.json",
        )

    def test_sq23_fixture_has_no_rev18a_fcom_citation(self) -> None:
        revisions = {
            citation.get("revision")
            for item in self.fixture["evidence"]
            for citation in item.get("citations", [])
            if citation.get("document") == "A350 FCOM"
        }
        self.assertEqual(revisions, {"Rev 20"})
        self.assertNotIn("Rev 18A", SQ23_FIXTURE.read_text(encoding="utf-8"))

    def test_landing_performance_method_and_result_are_separate(self) -> None:
        method = next(
            item for item in self.fixture["evidence"]
            if item["claim_id"] == "A350-LDG-PERF-FRAMEWORK"
        )
        result = next(
            item for item in self.fixture["evidence"]
            if item["claim_id"] == "TEST-LDG-PERF-ASSUMPTION"
        )
        self.assertEqual(method["status"], "authoritative")
        self.assertTrue(method["support_verified"])
        self.assertEqual(result["status"], "scenario_assumption")
        self.assertFalse(result["support_verified"])

    def test_notam_and_mel_are_explicit_test_assumptions(self) -> None:
        by_id = {item["claim_id"]: item for item in self.fixture["evidence"]}
        for claim_id in ("TEST-NOTAM-ASSUMPTION", "TEST-MEL-ASSUMPTION"):
            item = by_id[claim_id]
            self.assertEqual(item["status"], "scenario_assumption")
            self.assertFalse(item["support_verified"])
            self.assertTrue(item["assumptions"])

    def test_fixture_does_not_fabricate_airport_specific_landing_values(self) -> None:
        prohibited_keys = {
            "lda_m",
            "ld_m",
            "fld_m",
            "rld_m",
            "landing_distance_m",
            "runway_required_m",
        }
        for candidate in self.fixture["candidates"]:
            self.assertTrue(prohibited_keys.isdisjoint(candidate.keys()))

    def test_om_evidence_is_in_fixture(self) -> None:
        ids = {item["claim_id"] for item in self.fixture["evidence"]}
        self.assertIn("SIA-OM-DOCUMENT-PRIORITY", ids)
        self.assertIn("SIA-OM-OEI-DIVERSION", ids)


if __name__ == "__main__":
    unittest.main()

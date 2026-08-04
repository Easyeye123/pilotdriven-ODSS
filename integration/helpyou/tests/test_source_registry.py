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


class SourceRegistryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.manifest = load_manifest(MANIFEST)

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
        self.assertTrue(
            any(
                "generation of the correct aircraft procedure" in item.prohibited_uses
                for item in cognitive
            )
        )

    def test_production_gaps_remain_visible(self) -> None:
        text = " ".join(self.manifest.required_missing_sources)
        self.assertIn("OM-A", text)
        self.assertIn("MEL", text)
        self.assertIn("EFB landing-performance", text)
        self.assertIn("NOTAM", text)

    def test_private_source_bytes_are_rejected(self) -> None:
        data = json.loads(MANIFEST.read_text(encoding="utf-8"))
        data["sources"][1]["raw_content_in_repository"] = True
        with self.assertRaises(SourceRegistryError):
            manifest_from_mapping(data)


if __name__ == "__main__":
    unittest.main()

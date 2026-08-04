from __future__ import annotations

import unittest

from helpyou_core.contracts import (
    Citation,
    CoreInvariantError,
    EvidenceItem,
    EvidenceStatus,
)


class CoreContractTests(unittest.TestCase):
    def test_citation_format_uses_dd_mm_yy_and_eff(self) -> None:
        citation = Citation(
            owner="SIA",
            document="A350 FCOM",
            revision="Rev 18A",
            eff="13.08.25",
            section="PER-LDG-50",
            page="pp.1-3/4",
        )
        self.assertEqual(
            citation.compact(),
            "[SIA | A350 FCOM | Rev 18A | eff 13.08.25 | PER-LDG-50 | pp.1-3/4]",
        )

    def test_invalid_citation_date_is_rejected(self) -> None:
        with self.assertRaises(CoreInvariantError):
            Citation("SIA", "FCOM", eff="2025-08-13")

    def test_authoritative_evidence_requires_verified_citation(self) -> None:
        item = EvidenceItem(
            claim_id="C1",
            claim="Authoritative statement",
            status=EvidenceStatus.AUTHORITATIVE,
        )
        with self.assertRaises(CoreInvariantError):
            item.validate()

    def test_authoritative_evidence_accepts_verified_current_applicable_source(self) -> None:
        item = EvidenceItem(
            claim_id="C2",
            claim="Authoritative statement",
            status=EvidenceStatus.AUTHORITATIVE,
            citations=(Citation("SIA", "FCOM", section="PER-LDG-50"),),
            applicable=True,
            current=True,
            support_verified=True,
        )
        item.validate()

    def test_scenario_assumption_must_be_explicit(self) -> None:
        item = EvidenceItem(
            claim_id="A1",
            claim="Assume landing performance suitable.",
            status=EvidenceStatus.SCENARIO_ASSUMPTION,
        )
        with self.assertRaises(CoreInvariantError):
            item.validate()

    def test_pilot_report_cannot_be_source_verified(self) -> None:
        item = EvidenceItem(
            claim_id="P1",
            claim="A pilot reported a technique.",
            status=EvidenceStatus.PILOT_REPORTED,
            support_verified=True,
        )
        with self.assertRaises(CoreInvariantError):
            item.validate()


if __name__ == "__main__":
    unittest.main()

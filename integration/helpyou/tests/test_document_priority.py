from __future__ import annotations

import unittest

from helpyou_core.document_priority import (
    AuthorityBand,
    DocumentClass,
    INSTALLED_EFB_PRIMARY_DOCUMENTS,
    OM_MORE_RESTRICTIVE_RULE_APPLIES,
    PrecedenceRelation,
    authority_for,
    explicit_descending_sequence,
    latest_copy_rule,
    precedence_between,
)


class DocumentPriorityTests(unittest.TestCase):
    def test_exact_om_descending_sequence_is_preserved(self) -> None:
        sequence = dict(explicit_descending_sequence())
        self.assertEqual(sequence[1], (DocumentClass.INTAM,))
        self.assertEqual(sequence[2], (DocumentClass.FSI,))
        self.assertEqual(sequence[3], (DocumentClass.MEL,))
        self.assertEqual(
            sequence[4],
            (
                DocumentClass.OM_VOL_A,
                DocumentClass.FCOM,
                DocumentClass.JEPPESEN_REFERENCE,
                DocumentClass.SQNP,
                DocumentClass.SQSP,
            ),
        )
        self.assertEqual(sequence[5], (DocumentClass.SEP,))
        self.assertEqual(
            sequence[6],
            (
                DocumentClass.FCTM,
                DocumentClass.TECHNICAL_BULLETIN,
                DocumentClass.AIRPORT_BRIEFING,
                DocumentClass.CIRCULAR,
            ),
        )
        self.assertEqual(
            sequence[7],
            (DocumentClass.CREW_ADMINISTRATION, DocumentClass.FLIGHT_SECURITY),
        )

    def test_mel_has_higher_om_priority_than_fcom_and_fctm(self) -> None:
        self.assertEqual(
            precedence_between(DocumentClass.MEL, DocumentClass.FCOM),
            PrecedenceRelation.A_HIGHER,
        )
        self.assertEqual(
            precedence_between(DocumentClass.MEL, DocumentClass.FCTM),
            PrecedenceRelation.A_HIGHER,
        )

    def test_fcom_and_om_are_same_explicit_level(self) -> None:
        self.assertEqual(
            precedence_between(DocumentClass.FCOM, DocumentClass.OM_VOL_A),
            PrecedenceRelation.SAME_OM_LEVEL,
        )

    def test_fctm_is_lower_than_fcom_for_operational_authority(self) -> None:
        self.assertEqual(
            precedence_between(DocumentClass.FCOM, DocumentClass.FCTM),
            PrecedenceRelation.A_HIGHER,
        )

    def test_qrh_is_linked_component_without_invented_rank(self) -> None:
        qrh = authority_for(DocumentClass.QRH)
        self.assertEqual(qrh.band, AuthorityBand.LINKED_VOLUME_B_COMPONENT)
        self.assertIsNone(qrh.priority_rank)
        self.assertEqual(
            precedence_between(DocumentClass.QRH, DocumentClass.FCOM),
            PrecedenceRelation.SCOPE_RECONCILIATION_REQUIRED,
        )

    def test_statutory_and_afm_require_combined_compliance(self) -> None:
        afm = authority_for(DocumentClass.AFM)
        self.assertEqual(afm.band, AuthorityBand.MANDATORY_AIRWORTHINESS)
        self.assertEqual(
            precedence_between(DocumentClass.AFM, DocumentClass.MEL),
            PrecedenceRelation.COMBINED_COMPLIANCE_REQUIRED,
        )

    def test_lower_authority_may_be_more_restrictive(self) -> None:
        self.assertTrue(OM_MORE_RESTRICTIVE_RULE_APPLIES)

    def test_installed_efb_primary_copy_rule_is_limited(self) -> None:
        self.assertEqual(
            INSTALLED_EFB_PRIMARY_DOCUMENTS,
            {DocumentClass.AFM, DocumentClass.MEL, DocumentClass.CDL},
        )
        text = latest_copy_rule()
        self.assertIn("latest revision", text)
        self.assertIn("AFM, MEL and CDL", text)


if __name__ == "__main__":
    unittest.main()

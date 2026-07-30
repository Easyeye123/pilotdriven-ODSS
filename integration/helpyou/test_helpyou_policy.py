from __future__ import annotations

from datetime import date
import unittest

from helpyou_policy import (
    CitationReference,
    Claim,
    EvidenceClass,
    MemoryRecordType,
    PilotMemoryRecord,
    PolicyError,
    RequestContext,
    RequestRoute,
    interrogative_questions,
    minimum_sufficient_sections,
    route_request,
    validate_odss_evidence,
)


class HelpyouPolicyTests(unittest.TestCase):
    def test_lido_cfp_routes_to_odss_without_cognitive_layers(self) -> None:
        plan = route_request(
            RequestContext(attachment_names=("SQ304_LIDO_CFP.pdf",), pilot_reasoning_present=True)
        )
        odss = plan.subrequests[0]
        self.assertEqual(odss.route, RequestRoute.ODSS_CFP)
        self.assertFalse(odss.rasmussen)
        self.assertFalse(odss.endsley)
        self.assertFalse(odss.cbta)

    def test_manual_compilation_has_no_rasmussen_or_cbta(self) -> None:
        plan = route_request(RequestContext(intents=("compile_manuals",)))
        item = plan.subrequests[0]
        self.assertEqual(item.route, RequestRoute.AUTHORITATIVE_COMPILATION)
        self.assertFalse(item.rasmussen)
        self.assertFalse(item.cbta)

    def test_reasoning_review_activates_all_developmental_layers(self) -> None:
        plan = route_request(
            RequestContext(
                intents=("review_my_reasoning",),
                pilot_reasoning_present=True,
                developmental_review_requested=True,
            )
        )
        item = plan.subrequests[0]
        self.assertTrue(item.rasmussen)
        self.assertTrue(item.endsley)
        self.assertTrue(item.cbta)

    def test_decision_question_without_reasoning_does_not_fake_cognitive_review(self) -> None:
        item = route_request(
            RequestContext(intents=("decision_factors",), pilot_reasoning_present=False)
        ).subrequests[0]
        self.assertFalse(item.rasmussen)
        self.assertFalse(item.endsley)
        self.assertFalse(item.cbta)

    def test_loft_scenario_prompts_for_cfp(self) -> None:
        item = route_request(RequestContext(loft_style=True)).subrequests[0]
        self.assertEqual(item.route, RequestRoute.CFP_GROUNDED_SCENARIO)
        self.assertTrue(item.requires_cfp_upload)
        self.assertFalse(item.flight_specific_options_permitted)
        self.assertIn("Upload the applicable Lido CFP", interrogative_questions(item)[0])

    def test_loft_scenario_with_cfp_permits_flight_specific_options(self) -> None:
        plan = route_request(
            RequestContext(
                intents=("scenario",),
                has_lido_cfp=True,
                pilot_reasoning_present=True,
                developmental_review_requested=True,
            )
        )
        scenario = next(
            item for item in plan.subrequests
            if item.route is RequestRoute.CFP_GROUNDED_SCENARIO
        )
        self.assertFalse(scenario.requires_cfp_upload)
        self.assertTrue(scenario.flight_specific_options_permitted)
        self.assertTrue(scenario.rasmussen)
        self.assertTrue(scenario.endsley)
        self.assertTrue(scenario.cbta)

    def test_generic_scenario_remains_non_flight_specific(self) -> None:
        item = route_request(
            RequestContext(
                loft_style=True,
                generic_scenario_explicitly_selected=True,
            )
        ).subrequests[0]
        self.assertFalse(item.requires_cfp_upload)
        self.assertFalse(item.flight_specific_options_permitted)

    def test_mixed_request_is_split(self) -> None:
        plan = route_request(
            RequestContext(
                intents=("compile_manuals", "review_my_reasoning"),
                has_lido_cfp=True,
                pilot_reasoning_present=True,
            )
        )
        routes = {item.route for item in plan.subrequests}
        self.assertEqual(
            routes,
            {
                RequestRoute.ODSS_CFP,
                RequestRoute.AUTHORITATIVE_COMPILATION,
                RequestRoute.PILOT_REASONING_REVIEW,
            },
        )

    def test_citation_uses_dd_mm_yy_and_eff(self) -> None:
        citation = CitationReference(
            owner="SIA",
            document="OM-B",
            revision="Rev 18",
            effective_date=date(2025, 8, 13),
            section="§4.6.2",
            page=214,
        )
        self.assertEqual(
            citation.compact(),
            "[SIA | OM-B | Rev 18 | eff 13.08.25 | §4.6.2 | p.214]",
        )

    def test_authoritative_claim_requires_verified_citation(self) -> None:
        claim = Claim("Dispatch is permitted.", EvidenceClass.AUTHORITATIVE)
        with self.assertRaises(PolicyError):
            claim.validate()

    def test_authoritative_claim_accepts_current_applicable_verified_source(self) -> None:
        claim = Claim(
            text="The stated condition applies.",
            evidence_class=EvidenceClass.AUTHORITATIVE,
            citations=(CitationReference("Operator", "OM-A", section="§8"),),
            applicable=True,
            current=True,
            source_support_verified=True,
        )
        claim.validate()

    def test_superseded_source_cannot_support_current_claim(self) -> None:
        claim = Claim(
            text="Old rule",
            evidence_class=EvidenceClass.AUTHORITATIVE,
            citations=(CitationReference("Operator", "OM-A"),),
            current=False,
            source_support_verified=True,
        )
        with self.assertRaises(PolicyError):
            claim.validate()

    def test_pilot_report_cannot_be_promoted_by_authoritative_verifier(self) -> None:
        claim = Claim(
            text="Reported technique",
            evidence_class=EvidenceClass.SINGLE_PILOT_REPORT,
            source_support_verified=True,
        )
        with self.assertRaises(PolicyError):
            claim.validate()

    def test_odss_rejects_pilot_experience_and_ai_possibility(self) -> None:
        with self.assertRaises(PolicyError):
            validate_odss_evidence(
                [EvidenceClass.AUTHORITATIVE, EvidenceClass.SINGLE_PILOT_REPORT]
            )
        with self.assertRaises(PolicyError):
            validate_odss_evidence([EvidenceClass.AI_POSSIBILITY])

    def test_odss_accepts_authoritative_and_supported_synthesis(self) -> None:
        validate_odss_evidence(
            [EvidenceClass.AUTHORITATIVE, EvidenceClass.SUPPORTED_SYNTHESIS]
        )

    def test_direct_lookup_minimum_detail(self) -> None:
        item = route_request(RequestContext(intents=("manual_lookup",))).subrequests[0]
        self.assertEqual(
            minimum_sufficient_sections(item),
            ("Answer", "Material conditions", "Reference"),
        )

    def test_cognitive_sections_only_appear_when_activated(self) -> None:
        no_reasoning = route_request(
            RequestContext(intents=("decision_discussion",))
        ).subrequests[0]
        self.assertNotIn("Cognitive review", minimum_sufficient_sections(no_reasoning))

        with_reasoning = route_request(
            RequestContext(
                intents=("decision_discussion",),
                pilot_reasoning_present=True,
                developmental_review_requested=True,
            )
        ).subrequests[0]
        sections = minimum_sufficient_sections(with_reasoning)
        self.assertIn("Situational-awareness check", sections)
        self.assertIn("Cognitive review", sections)
        self.assertIn("Developmental CBTA reflection", sections)

    def test_memory_preserves_raw_wording_and_interpretation(self) -> None:
        record = PilotMemoryRecord(
            record_id="PKR-001",
            raw_pilot_wording="I configure earlier on short visuals.",
            ai_interpretation="Earlier configuration was reported as a workload-management technique.",
            record_type=MemoryRecordType.PILOT_TECHNIQUE,
            evidence_class=EvidenceClass.SINGLE_PILOT_REPORT,
        )
        record.validate()

    def test_memory_rejects_identical_raw_and_interpreted_fields(self) -> None:
        record = PilotMemoryRecord(
            record_id="PKR-002",
            raw_pilot_wording="Same text",
            ai_interpretation="Same text",
            record_type=MemoryRecordType.PILOT_OBSERVATION,
            evidence_class=EvidenceClass.SINGLE_PILOT_REPORT,
        )
        with self.assertRaises(PolicyError):
            record.validate()

    def test_pilot_authoritative_correction_requires_source_reference(self) -> None:
        record = PilotMemoryRecord(
            record_id="PKR-003",
            raw_pilot_wording="The manual says this is not permitted.",
            ai_interpretation="Pilot asserts a source-backed correction.",
            record_type=MemoryRecordType.PILOT_CORRECTION,
            evidence_class=EvidenceClass.AUTHORITATIVE,
        )
        with self.assertRaises(PolicyError):
            record.validate()


if __name__ == "__main__":
    unittest.main()

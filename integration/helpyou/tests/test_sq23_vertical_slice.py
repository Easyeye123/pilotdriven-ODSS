from __future__ import annotations

import unittest
from pathlib import Path

from helpyou_core.axiomatic_decision import build_decision_structure, viable_unranked_options
from helpyou_core.contracts import (
    DevelopmentalStatus,
    EvidenceStatus,
    PilotReasoning,
    TaskRoute,
)
from helpyou_core.facilitator import FacilitationPolicy, next_step
from helpyou_core.odss_adapter import load_baseline
from helpyou_core.orchestrator import OrchestrationRequest, run


FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "sq23_oei_etp1_1d.json"


def complete_reasoning() -> PilotReasoning:
    return PilotReasoning(
        raw_text=(
            "At ETP1-1D I would divert to CYQX because it remains an ODSS candidate and "
            "reduces distance while preserving the flight-plan diversion time. I would change "
            "to EINN if CYQX weather, runway, approach or landing performance becomes unsuitable."
        ),
        confirmed_facts=(
            "Stable OEI at ETP1-1D, ACTM 03:18.",
            "CYQX and EINN are the CFP EDTO pair.",
        ),
        assumptions=("Landing performance is suitable under the prototype assumption.",),
        operational_meaning=(
            "The nearest airport is not sufficient; the selected airport must remain suitable.",
        ),
        projected_state=(
            "Both candidates have a planned 2:23 diversion time at the 1D ETP.",
            "EINN has a forecast deterioration trend during the checked period.",
        ),
        disconfirming_information=(
            "A weather, runway, approach or aircraft-condition change may invalidate CYQX.",
        ),
        system_or_automation_behaviour=(
            "The scenario assumes a stable one-engine-inoperative diversion state.",
        ),
        degraded_capabilities=(
            "One-engine climb, cruise and operational flexibility are reduced.",
        ),
        retained_capabilities=(
            "The aircraft remains controllable and can divert to a suitable EDTO aerodrome.",
        ),
        safety_constraints=(
            "Maintain terrain clearance, fuel margin and approved landing suitability.",
        ),
        operational_objective="Reach the nearest suitable landing aerodrome while retaining a fallback.",
        options_considered=("CYQX", "EINN"),
        selected_option="CYQX",
        rationale=(
            "CYQX is an ODSS candidate with the shorter stated distance.",
            "Suitability remains conditional on current data and approved landing performance.",
        ),
        decision_gate=(
            "Change to EINN if CYQX weather, runway, approach availability or landing performance becomes unsuitable."
        ),
        implementation=(
            "Maintain flight-path control and complete the approved OEI procedure.",
            "Establish the diversion route and obtain current airport information.",
        ),
        monitoring=(
            "Monitor aircraft condition, weather, fuel, runway and approach status.",
        ),
        fallback="EINN",
        crew_plan=(
            "PF maintains flight path; PM completes procedure, obtains data and briefs ATC and cabin.",
        ),
        self_correction=(
            "Changed the initial 'nearest airport' framing to 'nearest suitable airport'.",
        ),
    )


class SQ23VerticalSliceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.baseline = load_baseline(FIXTURE)

    def test_fixture_is_exact_sq23_case(self) -> None:
        self.assertEqual(self.baseline.flight_number, "SQ23")
        self.assertEqual(self.baseline.aircraft_type, "A350-941")
        self.assertEqual(self.baseline.registration, "9V-SGE")
        self.assertEqual(self.baseline.anchor.waypoint, "ETP1-1D")
        self.assertEqual(self.baseline.anchor.actm, "03:18")

    def test_fixture_preserves_landing_performance_as_assumption(self) -> None:
        statuses = {item.status for item in self.baseline.evidence}
        self.assertIn(EvidenceStatus.SCENARIO_ASSUMPTION, statuses)
        self.assertTrue(any("Code 4E" in item for item in self.baseline.assumptions))

    def test_options_are_initially_unranked(self) -> None:
        structure = build_decision_structure(self.baseline)
        self.assertIsNone(structure.selected_option)
        self.assertEqual(
            tuple(option.option_id for option in viable_unranked_options(structure)),
            ("CYQX", "EINN"),
        )

    def test_incomplete_reasoning_asks_first_material_question(self) -> None:
        reasoning = PilotReasoning(raw_text="I would divert to CYQX.", selected_option="CYQX")
        step = next_step(self.baseline, reasoning)
        self.assertEqual(step.phase, "eliciting_situation_awareness")
        self.assertEqual(
            step.prompt,
            "What information is confirmed at this point, and what remains assumed?",
        )

    def test_complete_reasoning_reaches_teacher_phase(self) -> None:
        step = next_step(
            self.baseline,
            complete_reasoning(),
            FacilitationPolicy(diagnosis_uncertain=False),
        )
        self.assertEqual(step.phase, "ready_to_teach")
        self.assertIsNone(step.prompt)

    def test_orchestrator_generates_conditional_teacher_answer(self) -> None:
        result = run(
            OrchestrationRequest(
                route=TaskRoute.CFP_GROUNDED_SCENARIO,
                baseline=self.baseline,
                reasoning=complete_reasoning(),
                developmental_review_requested=True,
            )
        )
        self.assertEqual(result.phase, "ready_to_teach")
        self.assertIsNotNone(result.teaching_plan)
        self.assertEqual(result.teaching_plan.status, EvidenceStatus.CONDITIONAL)
        self.assertIn("nearest suitable aerodrome", result.teaching_plan.answer)
        self.assertEqual(result.decision_structure.selected_option, "CYQX")

    def test_cbta_is_developmental_and_selective(self) -> None:
        result = run(
            OrchestrationRequest(
                route=TaskRoute.CFP_GROUNDED_SCENARIO,
                baseline=self.baseline,
                reasoning=complete_reasoning(),
            )
        )
        competencies = {item.competency for item in result.cbta_observations}
        self.assertTrue({"KNO", "PSD", "SAW", "WLM", "FLD"}.issubset(competencies))
        self.assertNotIn("FPM", competencies)
        self.assertTrue(
            all("not observed" in item.evidence_limitation.lower() for item in result.cbta_observations)
        )

    def test_flight_discipline_is_identified_as_pilotdriven_adapted(self) -> None:
        result = run(
            OrchestrationRequest(
                route=TaskRoute.CFP_GROUNDED_SCENARIO,
                baseline=self.baseline,
                reasoning=complete_reasoning(),
            )
        )
        fld = next(item for item in result.cbta_observations if item.competency == "FLD")
        self.assertIn("PilotDriven adapted competency", fld.evidence_limitation)
        self.assertIn(
            fld.status,
            {
                DevelopmentalStatus.DEMONSTRATED_IN_DISCUSSION,
                DevelopmentalStatus.STRONG_AND_ADAPTIVE,
            },
        )

    def test_memory_keeps_raw_and_interpreted_reasoning_separate(self) -> None:
        result = run(
            OrchestrationRequest(
                route=TaskRoute.CFP_GROUNDED_SCENARIO,
                baseline=self.baseline,
                reasoning=complete_reasoning(),
            )
        )
        memory = result.memory_candidate
        self.assertIsNotNone(memory)
        self.assertNotEqual(memory.raw_pilot_wording, memory.ai_interpretation)
        self.assertTrue(memory.private)
        self.assertEqual(memory.context["case_id"], self.baseline.case_id)

    def test_non_scenario_route_is_delegated(self) -> None:
        result = run(
            OrchestrationRequest(
                route=TaskRoute.AUTHORITATIVE_RETRIEVAL,
                baseline=self.baseline,
                reasoning=complete_reasoning(),
            )
        )
        self.assertEqual(result.phase, "delegated_to_specialist_engine")
        self.assertIsNone(result.teaching_plan)


if __name__ == "__main__":
    unittest.main()

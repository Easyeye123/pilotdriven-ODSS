from __future__ import annotations

import unittest

from helpyou_core import endsley, rasmussen
from helpyou_core.contracts import PilotReasoning
from helpyou_core.facilitator import FacilitationPolicy, next_step


class CognitiveModelTests(unittest.TestCase):
    def test_endsley_asks_picture_now_first(self) -> None:
        reasoning = PilotReasoning(raw_text="I would divert to CYQX.", selected_option="CYQX")
        observations = endsley.review(reasoning)
        self.assertEqual(
            endsley.first_material_prompt(observations),
            "What information is confirmed at this point, and what remains assumed?",
        )

    def test_endsley_asks_projection_when_present_picture_and_meaning_are_complete(self) -> None:
        reasoning = PilotReasoning(
            raw_text="CYQX and EINN are candidates.",
            selected_option="CYQX",
            confirmed_facts=("ETP1-1D at ACTM 03:18",),
            operational_meaning=("Both airports remain candidate diversion options.",),
        )
        observations = endsley.review(reasoning)
        self.assertIn("next decision point", endsley.first_material_prompt(observations))

    def test_endsley_does_not_diagnose_tunnel_vision(self) -> None:
        reasoning = PilotReasoning(
            raw_text="I would take the nearer airport.",
            selected_option="CYQX",
            confirmed_facts=("CYQX is closer in distance.",),
            operational_meaning=("It may reduce time to land.",),
            projected_state=("Arrival is expected in 2:23.",),
        )
        scan = next(item for item in endsley.review(reasoning) if item.area == "Widen the scan")
        self.assertIn("tunnel-vision risk", scan.safety_effect)
        self.assertNotIn("you have tunnel vision", (scan.material_gap or "").lower())

    def test_rasmussen_moves_from_failure_label_to_capability(self) -> None:
        reasoning = PilotReasoning(
            raw_text="One engine failed; divert to CYQX.",
            selected_option="CYQX",
            confirmed_facts=("One engine failed.",),
            system_or_automation_behaviour=("Stable engine shutdown and OEI flight.",),
        )
        observations = rasmussen.review(reasoning)
        capability = next(item for item in observations if item.area == "Aircraft and crew capability")
        self.assertIsNotNone(capability.prompt)
        self.assertIn("still do safely", capability.prompt)

    def test_rasmussen_does_not_reward_higher_abstraction_without_action(self) -> None:
        reasoning = PilotReasoning(
            raw_text="The objective is to land safely.",
            selected_option="CYQX",
            operational_objective="Secure the safest suitable landing option.",
            safety_constraints=("Maintain terrain and fuel margin.",),
        )
        action = next(
            item for item in rasmussen.review(reasoning)
            if item.area == "Action and feedback"
        )
        self.assertIsNotNone(action.material_gap)

    def test_facilitator_does_not_require_system_diagnosis_when_case_is_defined(self) -> None:
        reasoning = PilotReasoning(
            raw_text="I select CYQX.",
            selected_option="CYQX",
            confirmed_facts=("Stable OEI at ETP1-1D.",),
            operational_meaning=("Diversion suitability controls the decision.",),
            projected_state=("Both options require about 2:23 from the ETP.",),
            disconfirming_information=("Weather or runway closure could invalidate the choice.",),
            decision_gate="Change option if CYQX weather or runway becomes unsuitable.",
            degraded_capabilities=("One-engine cruise and climb capability.",),
            retained_capabilities=("Controlled flight and diversion capability.",),
            safety_constraints=("Maintain terrain, fuel and landing suitability margins.",),
            operational_objective="Reach the nearest suitable landing aerodrome.",
            implementation=("Complete approved procedure and establish diversion route.",),
            monitoring=("Monitor weather, fuel, aircraft condition and runway status.",),
            fallback="EINN",
        )
        step = next_step(
            baseline=None,
            reasoning=reasoning,
            policy=FacilitationPolicy(diagnosis_uncertain=False),
        )
        self.assertEqual(step.phase, "awaiting_cfp")


if __name__ == "__main__":
    unittest.main()

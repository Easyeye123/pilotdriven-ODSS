"""Pilot-facing Rasmussen abstraction-decomposition review.

Academic labels remain in backend comments. User-facing observations use aviation
language: indications, system behaviour, capability, safety margin, objective,
action and feedback.
"""

from __future__ import annotations

from .contracts import CognitiveObservation, DevelopmentalStatus, PilotReasoning


def _status(present: bool, strong: bool = False) -> DevelopmentalStatus:
    if not present:
        return DevelopmentalStatus.INSUFFICIENT_EVIDENCE
    if strong:
        return DevelopmentalStatus.STRONG_AND_ADAPTIVE
    return DevelopmentalStatus.DEMONSTRATED_IN_DISCUSSION


def review(reasoning: PilotReasoning) -> tuple[CognitiveObservation, ...]:
    if not reasoning.is_present:
        return ()

    indications = CognitiveObservation(
        model="Rasmussen",
        area="Information and indications",
        status=_status(bool(reasoning.confirmed_facts)),
        evidence=reasoning.confirmed_facts,
        material_gap=None if reasoning.confirmed_facts else "The reasoning does not establish the indications and flight facts being used.",
        prompt=None if reasoning.confirmed_facts else "Which indications, CFP values or operational reports are you using as established facts?",
        safety_effect=None if reasoning.confirmed_facts else "A decision built on unspecified facts cannot be checked against the actual flight state.",
        evidence_limitation="Only information stated in the discussion is reviewed.",
    )

    system = CognitiveObservation(
        model="Rasmussen",
        area="System and automation behaviour",
        status=_status(bool(reasoning.system_or_automation_behaviour)),
        evidence=reasoning.system_or_automation_behaviour,
        material_gap=None if reasoning.system_or_automation_behaviour else "The system or automation behaviour producing the operational condition has not been explained.",
        prompt=None if reasoning.system_or_automation_behaviour else "What do you believe the aircraft systems or automation are doing, and what confirms that view?",
        safety_effect=None if reasoning.system_or_automation_behaviour else "A mistaken process model can lead to an unsuitable control action even when individual indications are correct.",
        evidence_limitation="The module does not infer an unspoken diagnosis.",
    )

    capability_evidence = reasoning.degraded_capabilities + reasoning.retained_capabilities
    capability = CognitiveObservation(
        model="Rasmussen",
        area="Aircraft and crew capability",
        status=_status(bool(capability_evidence), bool(reasoning.degraded_capabilities and reasoning.retained_capabilities)),
        evidence=capability_evidence,
        material_gap=None if capability_evidence else "The reasoning remains at the failure label and has not translated it into degraded and retained capability.",
        prompt=None if capability_evidence else "What can the aircraft and crew still do safely, and what capability has been lost or degraded?",
        safety_effect=None if capability_evidence else "Airport or route suitability cannot be judged from a component failure label alone.",
        evidence_limitation="Actual aircraft handling capability was not demonstrated in chat.",
    )

    constraints = CognitiveObservation(
        model="Rasmussen",
        area="Safety constraints and margins",
        status=_status(bool(reasoning.safety_constraints)),
        evidence=reasoning.safety_constraints,
        material_gap=None if reasoning.safety_constraints else "The controlling safety margin or unacceptable state has not been stated.",
        prompt=None if reasoning.safety_constraints else "Which safety margin now controls the decision, and what condition must not be allowed to occur?",
        safety_effect=None if reasoning.safety_constraints else "Without a controlling constraint, convenience can silently displace safety suitability.",
        evidence_limitation="The review assesses the constraints stated by the pilot against the case model.",
    )

    objective_present = bool(reasoning.operational_objective and reasoning.operational_objective.strip())
    objective = CognitiveObservation(
        model="Rasmussen",
        area="Crew objective",
        status=_status(objective_present),
        evidence=(reasoning.operational_objective,) if objective_present else (),
        material_gap=None if objective_present else "The operational objective has not been explicitly set or reframed.",
        prompt=None if objective_present else "What is the crew now trying to achieve: preserve the original plan, or secure the safest suitable outcome?",
        safety_effect=None if objective_present else "An unchanged destination objective may remain dominant after the flight's purpose should have shifted.",
        evidence_limitation="The objective is assessed from the pilot's stated intent.",
    )

    action_evidence = reasoning.implementation + reasoning.monitoring
    action = CognitiveObservation(
        model="Rasmussen",
        area="Action and feedback",
        status=_status(bool(action_evidence), bool(reasoning.implementation and reasoning.monitoring and reasoning.fallback)),
        evidence=action_evidence,
        material_gap=None if action_evidence else "The objective has not been translated into actions, monitoring and a fallback.",
        prompt=None if action_evidence else "How will the crew implement the decision, confirm it remains valid and recover if the preferred option is lost?",
        safety_effect=None if action_evidence else "A high-level decision without feedback may not control the actual flight situation.",
        evidence_limitation="Intended actions are recorded; execution was not observed.",
    )

    return (indications, system, capability, constraints, objective, action)


def first_material_prompt(observations: tuple[CognitiveObservation, ...]) -> str | None:
    priority = (
        "Information and indications",
        "System and automation behaviour",
        "Aircraft and crew capability",
        "Safety constraints and margins",
        "Crew objective",
        "Action and feedback",
    )
    by_area = {item.area: item for item in observations}
    for area in priority:
        item = by_area.get(area)
        if item and item.prompt:
            return item.prompt
    return None

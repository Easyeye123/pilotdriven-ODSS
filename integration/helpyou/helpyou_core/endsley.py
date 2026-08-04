"""Pilot-facing Endsley situation-awareness review.

The module does not diagnose a pilot's mental state. It reviews only what the pilot
explicitly stated in the discussion and returns the first material missing link.
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

    picture_present = bool(reasoning.confirmed_facts)
    picture = CognitiveObservation(
        model="Endsley",
        area="Picture now",
        status=_status(picture_present),
        evidence=reasoning.confirmed_facts,
        material_gap=None if picture_present else "The present situation has not been separated into confirmed facts and assumptions.",
        prompt=None if picture_present else "What information is confirmed at this point, and what remains assumed?",
        safety_effect=None if picture_present else "An incomplete present picture can invalidate later interpretation and projection.",
        evidence_limitation="Written discussion only; cockpit scan and actual monitoring were not observed.",
    )

    meaning_present = bool(reasoning.operational_meaning)
    meaning = CognitiveObservation(
        model="Endsley",
        area="What it means",
        status=_status(meaning_present),
        evidence=reasoning.operational_meaning,
        material_gap=None if meaning_present else "The operational significance of the available information has not been stated.",
        prompt=None if meaning_present else "What does the present information change about the aircraft's safe operating options?",
        safety_effect=None if meaning_present else "Raw indications without operational meaning can support an unsuitable plan.",
        evidence_limitation="The review covers the explanation stated by the pilot, not unspoken understanding.",
    )

    projection_present = bool(reasoning.projected_state)
    projection_strong = projection_present and bool(reasoning.decision_gate) and bool(reasoning.monitoring)
    projection = CognitiveObservation(
        model="Endsley",
        area="Projection ahead",
        status=_status(projection_present, projection_strong),
        evidence=reasoning.projected_state,
        material_gap=None if projection_present else "The future aircraft, weather, fuel or option state has not been projected.",
        prompt=None if projection_present else "At the next decision point, which margin is changing and which option could be lost first?",
        safety_effect=None if projection_present else "Without projection, a presently acceptable option can become unavailable before the crew acts.",
        evidence_limitation="Projection is assessed from the pilot's stated forecast, not from actual later performance.",
    )

    scan_present = bool(reasoning.disconfirming_information)
    scan = CognitiveObservation(
        model="Endsley",
        area="Widen the scan",
        status=_status(scan_present),
        evidence=reasoning.disconfirming_information,
        material_gap=None if scan_present else "No disconfirming cue or neglected operational area has been identified.",
        prompt=None if scan_present else "What information would show that your present diagnosis or preferred option is no longer valid?",
        safety_effect=None if scan_present else "A narrow comparison can create a tunnel-vision risk without proving that tunnel vision occurred.",
        evidence_limitation="Helpyou identifies a possible attention gap; it does not diagnose tunnel vision as a trait.",
    )

    gate_present = bool(reasoning.decision_gate)
    gate = CognitiveObservation(
        model="Endsley",
        area="Decision gate",
        status=_status(gate_present, gate_present and bool(reasoning.fallback)),
        evidence=(reasoning.decision_gate,) if reasoning.decision_gate else (),
        material_gap=None if gate_present else "The condition that changes the plan has not been defined.",
        prompt=None if gate_present else "What exact condition changes the plan, and what action follows when it is reached?",
        safety_effect=None if gate_present else "Qualitative monitoring alone may allow the safe decision window to narrow unnoticed.",
        evidence_limitation="The discussion records an intended gate; actual adherence was not observed.",
    )

    return (picture, meaning, projection, scan, gate)


def first_material_prompt(observations: tuple[CognitiveObservation, ...]) -> str | None:
    """Return one question only, following the minimum-sufficient-detail rule."""
    priority = ("Picture now", "What it means", "Projection ahead", "Widen the scan", "Decision gate")
    by_area = {item.area: item for item in observations}
    for area in priority:
        observation = by_area.get(area)
        if observation and observation.prompt:
            return observation.prompt
    return None

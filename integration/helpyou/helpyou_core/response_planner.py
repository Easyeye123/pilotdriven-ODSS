"""Minimum-sufficient-detail teacher response planner."""

from __future__ import annotations

from .axiomatic_decision import selected_option_assessment, viable_unranked_options
from .contracts import (
    CBTAObservation,
    Citation,
    CognitiveObservation,
    DecisionStructure,
    EvidenceStatus,
    FlightBaseline,
    OptionState,
    TeachingPlan,
)
from .evidence_guard import overall_support_status


def _dedupe_citations(citations) -> tuple[Citation, ...]:
    result: list[Citation] = []
    for citation in citations:
        if citation not in result:
            result.append(citation)
    return tuple(result)


def _first_gap(observations: tuple[CognitiveObservation, ...]) -> str | None:
    for item in observations:
        if item.material_gap:
            return item.material_gap
    return None


def _developmental_points(items: tuple[CBTAObservation, ...]) -> tuple[str, ...]:
    # Surface at most three relevant competencies. Full mappings remain expandable.
    return tuple(
        f"{item.competency}: {item.interpretation}"
        for item in items[:3]
    )


def build_teaching_plan(
    baseline: FlightBaseline,
    structure: DecisionStructure,
    endsley_observations: tuple[CognitiveObservation, ...],
    rasmussen_observations: tuple[CognitiveObservation, ...],
    cbta_observations: tuple[CBTAObservation, ...],
) -> TeachingPlan:
    status = overall_support_status(baseline)
    selected = selected_option_assessment(structure)
    viable = viable_unranked_options(structure)

    if structure.selected_option and selected is None:
        headline = "Selected option is outside the ODSS candidate set"
        answer = (
            "Helpyou cannot validate the selected aerodrome from the current flight baseline. "
            "Add it through authoritative airport, weather, route, fuel and landing-performance data before comparing it."
        )
        status = EvidenceStatus.INSUFFICIENT_SUPPORT
        conditions = ("Do not promote an unverified aerodrome to a flight-specific recommendation.",)
        option_citations: tuple[Citation, ...] = ()
    elif selected is not None and selected.state is OptionState.NOT_VIABLE:
        headline = f"{selected.option_id} is not viable under the stated baseline"
        answer = (
            f"The selected option fails one or more hard requirements: "
            + ", ".join(selected.requirements_not_satisfied)
            + "."
        )
        status = EvidenceStatus.CONDITIONAL
        conditions = selected.conditions + selected.residual_risks
        option_citations = selected.citations
    elif selected is not None:
        headline = f"{selected.option_id} remains {selected.state.value.replace('_', ' ')}"
        answer = (
            f"The selection of {selected.option_id} is supportable only within the ODSS conditions shown. "
            "The decisive standard is the nearest suitable aerodrome, not distance alone."
        )
        conditions = selected.conditions + selected.residual_risks
        option_citations = selected.citations
        if selected.state in {OptionState.CONDITIONAL, OptionState.UNRESOLVED}:
            status = EvidenceStatus.CONDITIONAL
    else:
        headline = "Viable options remain deliberately unranked"
        option_labels = ", ".join(option.option_id for option in viable) or "none"
        answer = (
            f"The current ODSS baseline leaves these candidates for pilot comparison: {option_labels}. "
            "Helpyou will not rank them until the pilot states a decision and the material constraints are verified."
        )
        conditions = tuple(
            condition
            for option in viable
            for condition in option.conditions
        )
        option_citations = tuple(
            citation
            for option in viable
            for citation in option.citations
        )

    baseline_citations = tuple(
        citation
        for item in baseline.evidence
        for citation in item.citations
    )

    return TeachingPlan(
        status=status,
        headline=headline,
        answer=answer,
        conditions=tuple(dict.fromkeys(conditions)),
        decision_gate=structure.decision_gate,
        key_sa_point=_first_gap(endsley_observations),
        key_cognitive_point=_first_gap(rasmussen_observations),
        developmental_points=_developmental_points(cbta_observations),
        citations=_dedupe_citations(baseline_citations + option_citations),
        expandable_sections=(
            "Option comparison",
            "Full situational-awareness review",
            "Rasmussen cognitive review",
            "CBTA evidence",
            "Source traceability",
        ),
    )

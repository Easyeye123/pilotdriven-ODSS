"""Axiomatic Design decision structure for CFP-grounded scenarios."""

from __future__ import annotations

from .contracts import (
    Citation,
    DecisionStructure,
    FlightBaseline,
    FunctionalRequirement,
    OptionAssessment,
    OptionState,
    PilotReasoning,
)


DEFAULT_CUSTOMER_NEED = (
    "Safely manage the aircraft condition and reach an operationally suitable landing aerodrome."
)


def _source_citations(baseline: FlightBaseline) -> tuple[Citation, ...]:
    citations: list[Citation] = []
    for item in baseline.evidence:
        for citation in item.citations:
            if citation not in citations:
                citations.append(citation)
    return tuple(citations)


def functional_requirements(baseline: FlightBaseline) -> tuple[FunctionalRequirement, ...]:
    citations = _source_citations(baseline)
    return (
        FunctionalRequirement(
            "FR1",
            "Maintain controllability and an acceptable one-engine flight path.",
            source_basis=citations,
        ),
        FunctionalRequirement(
            "FR2",
            "Remain clear of terrain and hazardous weather.",
            source_basis=citations,
        ),
        FunctionalRequirement(
            "FR3",
            "Use an aerodrome compatible with the aircraft condition, runway, approach and landing-performance requirements.",
            source_basis=citations,
        ),
        FunctionalRequirement(
            "FR4",
            "Preserve the applicable fuel and time margins.",
            source_basis=citations,
        ),
        FunctionalRequirement(
            "FR5",
            "Maintain manageable workload and disciplined flight-path control while the decision is implemented.",
            source_basis=citations,
        ),
        FunctionalRequirement(
            "FR6",
            "Retain a viable fallback if the preferred aerodrome becomes unavailable.",
            source_basis=citations,
        ),
        FunctionalRequirement(
            "FR7",
            "Complete the required aircraft, ATC, cabin and operational coordination.",
            source_basis=citations,
        ),
    )


def _option_assessment(candidate) -> OptionAssessment:
    requirements_satisfied = ["FR1", "FR2", "FR4"]
    requirements_not_satisfied: list[str] = []

    state = candidate.option_state
    if state is OptionState.NOT_VIABLE:
        requirements_not_satisfied.extend(("FR2", "FR3", "FR4"))
    elif state is OptionState.UNRESOLVED:
        requirements_not_satisfied.append("FR3")
    elif state is OptionState.CONDITIONAL:
        # Conditional means the option remains available only when listed conditions
        # and assumptions are verified. It is not automatically ranked below another
        # conditional option.
        requirements_satisfied.append("FR3")
    else:
        requirements_satisfied.append("FR3")

    return OptionAssessment(
        option_id=candidate.icao,
        label=f"Divert to {candidate.icao}",
        state=state,
        requirements_satisfied=tuple(dict.fromkeys(requirements_satisfied)),
        requirements_not_satisfied=tuple(dict.fromkeys(requirements_not_satisfied)),
        conditions=candidate.conditions,
        residual_risks=candidate.residual_risks,
        citations=candidate.citations + (candidate.weather.citations if candidate.weather else ()),
    )


def build_decision_structure(
    baseline: FlightBaseline,
    reasoning: PilotReasoning | None = None,
) -> DecisionStructure:
    """Create an unranked option structure from an ODSS baseline.

    The function does not determine which aerodrome is operationally preferred.
    It preserves input order and exposes conditions and coupling for the teacher.
    """

    requirements = functional_requirements(baseline)
    options = tuple(_option_assessment(candidate) for candidate in baseline.candidates)

    hard_constraints = (
        "The aircraft must remain controllable on an acceptable one-engine flight path.",
        "The route and arrival must remain clear of terrain and hazardous weather.",
        "The selected aerodrome must be operationally suitable for the aircraft condition.",
        "Landing Distance Available must satisfy the applicable approved landing-performance requirement.",
        "The fuel and time state must remain within the applicable operational policy.",
    )
    preferences = (
        "Company, passenger, maintenance and schedule convenience are considered only after hard constraints are met.",
    )

    couplings = (
        "A nearer aerodrome may reduce time-to-land but may offer less weather, runway or approach margin.",
        "A farther aerodrome may improve runway or weather suitability but consume more fuel and time.",
        "Troubleshooting may improve diagnosis but can reduce flight-path and workload margin if prolonged.",
    )

    selected = reasoning.selected_option if reasoning else None
    gate = reasoning.decision_gate if reasoning else None
    monitoring = reasoning.monitoring if reasoning else ()
    fallback = reasoning.fallback if reasoning else None

    return DecisionStructure(
        customer_need=DEFAULT_CUSTOMER_NEED,
        functional_requirements=requirements,
        hard_constraints=hard_constraints,
        preferences=preferences,
        options=options,
        couplings=couplings,
        selected_option=selected,
        decision_gate=gate,
        monitoring=monitoring,
        fallback=fallback,
    )


def selected_option_assessment(structure: DecisionStructure) -> OptionAssessment | None:
    if not structure.selected_option:
        return None
    normalized = structure.selected_option.strip().upper()
    for option in structure.options:
        if option.option_id.upper() == normalized:
            return option
    return None


def viable_unranked_options(structure: DecisionStructure) -> tuple[OptionAssessment, ...]:
    return tuple(
        option
        for option in structure.options
        if option.state in {OptionState.VIABLE, OptionState.CONDITIONAL, OptionState.UNRESOLVED}
    )

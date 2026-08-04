"""Developmental CBTA mapping for discussion evidence only."""

from __future__ import annotations

from .contracts import CBTAObservation, DevelopmentalStatus, PilotReasoning


DISCUSSION_LIMIT = (
    "Written or spoken intentions were reviewed; actual handling, callouts, checklist execution and crew coordination were not observed."
)


def _status(count: int, adaptive: bool = False) -> DevelopmentalStatus:
    if count == 0:
        return DevelopmentalStatus.INSUFFICIENT_EVIDENCE
    if adaptive:
        return DevelopmentalStatus.STRONG_AND_ADAPTIVE
    if count == 1:
        return DevelopmentalStatus.PARTIALLY_DEMONSTRATED
    return DevelopmentalStatus.DEMONSTRATED_IN_DISCUSSION


def map_observations(reasoning: PilotReasoning) -> tuple[CBTAObservation, ...]:
    """Map only explicitly demonstrated discussion evidence.

    The output is not a formal operator, licensing or training grade.
    """

    if not reasoning.is_present:
        return ()

    observations: list[CBTAObservation] = []

    kno_evidence = (
        reasoning.system_or_automation_behaviour
        + reasoning.degraded_capabilities
        + reasoning.retained_capabilities
    )
    if kno_evidence:
        observations.append(
            CBTAObservation(
                competency="KNO",
                observable_evidence=kno_evidence,
                status=_status(len(kno_evidence)),
                interpretation="The pilot applied aircraft-system or operational knowledge to the stated scenario.",
                evidence_limitation=DISCUSSION_LIMIT,
            )
        )

    pro_evidence = tuple(
        item for item in reasoning.implementation if any(
            token in item.casefold()
            for token in ("procedure", "ecam", "checklist", "sop", "manual")
        )
    )
    if pro_evidence:
        observations.append(
            CBTAObservation(
                competency="PRO",
                observable_evidence=pro_evidence,
                status=_status(len(pro_evidence)),
                interpretation="The pilot identified intended use of approved procedures or operating instructions.",
                evidence_limitation=DISCUSSION_LIMIT,
            )
        )

    psd_evidence = (
        reasoning.options_considered
        + ((reasoning.selected_option,) if reasoning.selected_option else ())
        + reasoning.rationale
        + ((reasoning.decision_gate,) if reasoning.decision_gate else ())
        + ((reasoning.fallback,) if reasoning.fallback else ())
    )
    if psd_evidence:
        observations.append(
            CBTAObservation(
                competency="PSD",
                observable_evidence=psd_evidence,
                status=_status(
                    len(psd_evidence),
                    adaptive=bool(reasoning.decision_gate and reasoning.fallback),
                ),
                interpretation="The pilot generated, selected and conditionally reviewed a course of action.",
                evidence_limitation=DISCUSSION_LIMIT,
            )
        )

    saw_evidence = (
        reasoning.confirmed_facts
        + reasoning.operational_meaning
        + reasoning.projected_state
        + reasoning.disconfirming_information
    )
    if saw_evidence:
        observations.append(
            CBTAObservation(
                competency="SAW",
                observable_evidence=saw_evidence,
                status=_status(
                    len(saw_evidence),
                    adaptive=bool(reasoning.projected_state and reasoning.disconfirming_information),
                ),
                interpretation="The pilot described the present state, operational meaning and future development of the scenario.",
                evidence_limitation=DISCUSSION_LIMIT,
            )
        )

    wlm_evidence = reasoning.crew_plan + tuple(
        item for item in reasoning.implementation if any(
            token in item.casefold()
            for token in ("delegate", "task", "pf", "pm", "workload", "priorit")
        )
    )
    if wlm_evidence:
        observations.append(
            CBTAObservation(
                competency="WLM",
                observable_evidence=wlm_evidence,
                status=_status(len(wlm_evidence)),
                interpretation="The pilot considered task priority, distribution or available crew capacity.",
                evidence_limitation=DISCUSSION_LIMIT,
            )
        )

    communication_evidence = tuple(
        item for item in reasoning.crew_plan if any(
            token in item.casefold()
            for token in ("brief", "tell", "advise", "atc", "cabin", "dispatch", "communicat")
        )
    )
    if communication_evidence:
        observations.append(
            CBTAObservation(
                competency="COM/LTW",
                observable_evidence=communication_evidence,
                status=_status(len(communication_evidence)),
                interpretation="The pilot described intended communication, participation or crew coordination.",
                evidence_limitation=DISCUSSION_LIMIT,
            )
        )

    fld_evidence = (
        ((reasoning.decision_gate,) if reasoning.decision_gate else ())
        + reasoning.monitoring
        + reasoning.crew_plan
        + ((reasoning.self_correction,) if reasoning.self_correction else ())
    )
    if fld_evidence:
        observations.append(
            CBTAObservation(
                competency="FLD",
                observable_evidence=fld_evidence,
                status=_status(
                    len(fld_evidence),
                    adaptive=bool(reasoning.decision_gate and reasoning.monitoring and reasoning.fallback),
                ),
                interpretation=(
                    "PilotDriven Flight Discipline: the pilot described operational gates, monitoring, role discipline or timely self-correction."
                ),
                evidence_limitation=(
                    DISCUSSION_LIMIT
                    + " FLD is a PilotDriven adapted competency, not an additional QCAA core competency."
                ),
            )
        )

    return tuple(observations)

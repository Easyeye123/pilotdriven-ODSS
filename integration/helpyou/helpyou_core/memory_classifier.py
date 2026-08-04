"""Governed pilot-memory candidate generation."""

from __future__ import annotations

from .contracts import (
    EvidenceStatus,
    FlightBaseline,
    MemoryCandidate,
    MemoryRecordType,
    PilotReasoning,
)


def classify_reasoning(
    reasoning: PilotReasoning | None,
    baseline: FlightBaseline | None,
) -> MemoryCandidate | None:
    if reasoning is None or not reasoning.is_present:
        return None

    selected = reasoning.selected_option or "no option stated"
    gate = reasoning.decision_gate or "no decision gate stated"
    interpretation = (
        f"In case {baseline.case_id if baseline else 'unlinked'}, the pilot selected {selected}; "
        f"the stated decision gate was {gate}."
    )
    record = MemoryCandidate(
        raw_pilot_wording=reasoning.raw_text,
        ai_interpretation=interpretation,
        record_type=MemoryRecordType.REASONING_EVIDENCE,
        evidence_status=EvidenceStatus.PILOT_REPORTED,
        private=True,
        context={
            "case_id": baseline.case_id if baseline else None,
            "flight_number": baseline.flight_number if baseline else None,
            "aircraft": baseline.aircraft_type if baseline else None,
            "route": (
                f"{baseline.departure}-{baseline.destination}" if baseline else None
            ),
            "anchor": baseline.anchor.waypoint if baseline else None,
        },
    )
    record.validate()
    return record

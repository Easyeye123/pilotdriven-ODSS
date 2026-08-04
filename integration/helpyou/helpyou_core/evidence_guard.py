"""Evidence, source and authority boundaries for Helpyou Core."""

from __future__ import annotations

from collections.abc import Iterable

from .contracts import (
    CoreInvariantError,
    EvidenceItem,
    EvidenceStatus,
    FlightBaseline,
)


ODSS_ALLOWED = {
    EvidenceStatus.AUTHORITATIVE,
    EvidenceStatus.SUPPORTED_SYNTHESIS,
    EvidenceStatus.CONDITIONAL,
    EvidenceStatus.SCENARIO_ASSUMPTION,
}

ODSS_PROHIBITED = {
    EvidenceStatus.PILOT_REPORTED,
    EvidenceStatus.AI_POSSIBILITY,
    EvidenceStatus.DISPUTED,
    EvidenceStatus.INSUFFICIENT_SUPPORT,
}


def validate_evidence(items: Iterable[EvidenceItem]) -> None:
    for item in items:
        item.validate()


def validate_odss_baseline(baseline: FlightBaseline) -> None:
    """Confirm Chat receives a complete, traceable ODSS baseline.

    Scenario assumptions may be carried in the baseline only when they are visibly
    labelled. They cannot be treated as ODSS-computed facts.
    """

    baseline.validate()
    validate_evidence(baseline.evidence)
    invalid = sorted(
        {
            item.status.value
            for item in baseline.evidence
            if item.status in ODSS_PROHIBITED
        }
    )
    if invalid:
        raise CoreInvariantError(
            "ODSS baseline contains prohibited evidence classes: " + ", ".join(invalid)
        )


def has_authoritative_basis(baseline: FlightBaseline) -> bool:
    return any(
        item.status in {EvidenceStatus.AUTHORITATIVE, EvidenceStatus.SUPPORTED_SYNTHESIS}
        for item in baseline.evidence
    )


def overall_support_status(baseline: FlightBaseline) -> EvidenceStatus:
    """Return the most conservative user-facing evidence status."""

    statuses = {item.status for item in baseline.evidence}
    if EvidenceStatus.INSUFFICIENT_SUPPORT in statuses:
        return EvidenceStatus.INSUFFICIENT_SUPPORT
    if EvidenceStatus.DISPUTED in statuses:
        return EvidenceStatus.DISPUTED
    if EvidenceStatus.SCENARIO_ASSUMPTION in statuses or baseline.assumptions:
        return EvidenceStatus.CONDITIONAL
    if EvidenceStatus.CONDITIONAL in statuses:
        return EvidenceStatus.CONDITIONAL
    if EvidenceStatus.SUPPORTED_SYNTHESIS in statuses:
        return EvidenceStatus.SUPPORTED_SYNTHESIS
    if EvidenceStatus.AUTHORITATIVE in statuses:
        return EvidenceStatus.AUTHORITATIVE
    return EvidenceStatus.INSUFFICIENT_SUPPORT

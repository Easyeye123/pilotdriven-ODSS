"""Stable data contracts for the Helpyou Core v0.2 vertical slice.

The contracts deliberately separate:
- ODSS-owned flight facts;
- pilot-provided scenario assumptions;
- the pilot's stated reasoning;
- deterministic cognitive observations;
- the Axiomatic Design decision structure;
- developmental CBTA evidence; and
- pilot-memory candidates.

No class in this module performs aircraft-performance calculations.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping, Sequence


class CoreInvariantError(ValueError):
    """Raised when a Helpyou hard boundary would be violated."""


class EvidenceStatus(str, Enum):
    AUTHORITATIVE = "authoritative"
    SUPPORTED_SYNTHESIS = "supported_synthesis"
    CONDITIONAL = "conditional"
    SCENARIO_ASSUMPTION = "scenario_assumption"
    PILOT_REPORTED = "pilot_reported"
    AI_POSSIBILITY = "ai_possibility"
    DISPUTED = "disputed"
    INSUFFICIENT_SUPPORT = "insufficient_support"


class TaskRoute(str, Enum):
    ODSS_CFP = "odss_cfp"
    CFP_GROUNDED_SCENARIO = "cfp_grounded_scenario"
    AUTHORITATIVE_RETRIEVAL = "authoritative_retrieval"
    AUTHORITATIVE_COMPILATION = "authoritative_compilation"
    DETERMINISTIC_CALCULATION = "deterministic_calculation"
    DECISION_DISCUSSION = "decision_discussion"
    PILOT_REASONING_REVIEW = "pilot_reasoning_review"
    PILOT_KNOWLEDGE_CONTRIBUTION = "pilot_knowledge_contribution"
    AUTHORITATIVE_RESEARCH = "authoritative_research"


class OptionState(str, Enum):
    VIABLE = "viable"
    CONDITIONAL = "conditional"
    NOT_VIABLE = "not_viable"
    UNRESOLVED = "unresolved"


class DevelopmentalStatus(str, Enum):
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    EMERGING = "emerging"
    PARTIALLY_DEMONSTRATED = "partially_demonstrated"
    DEMONSTRATED_IN_DISCUSSION = "demonstrated_in_discussion"
    STRONG_AND_ADAPTIVE = "strong_and_adaptive"
    CONFLICTING_EVIDENCE = "conflicting_evidence"


class MemoryRecordType(str, Enum):
    PILOT_EXPERIENCE = "pilot_experience"
    PILOT_OBSERVATION = "pilot_observation"
    PILOT_CORRECTION = "pilot_correction"
    PILOT_TECHNIQUE = "pilot_technique"
    PILOT_HYPOTHESIS = "pilot_hypothesis"
    REASONING_EVIDENCE = "reasoning_evidence"
    LEARNING_INTEREST = "learning_interest"
    INTERACTION_PREFERENCE = "interaction_preference"
    SOURCE_REFERENCE = "source_reference"


@dataclass(frozen=True)
class Citation:
    owner: str
    document: str
    revision: str | None = None
    eff: str | None = None
    section: str | None = None
    page: str | int | None = None
    applicability: str | None = None
    source_id: str | None = None

    def __post_init__(self) -> None:
        if not self.owner.strip() or not self.document.strip():
            raise CoreInvariantError("Citation owner and document are required.")
        if self.eff is not None:
            parts = self.eff.split(".")
            if len(parts) != 3 or any(not part.isdigit() for part in parts):
                raise CoreInvariantError("Citation eff date must use DD.MM.YY.")
            day, month, year = (int(value) for value in parts)
            if not 1 <= day <= 31 or not 1 <= month <= 12 or not 0 <= year <= 99:
                raise CoreInvariantError("Citation eff date is outside DD.MM.YY ranges.")

    def compact(self) -> str:
        parts = [self.owner.strip(), self.document.strip()]
        if self.revision:
            parts.append(self.revision.strip())
        if self.eff:
            parts.append(f"eff {self.eff}")
        if self.section:
            parts.append(self.section.strip())
        if self.page is not None:
            page = str(self.page).strip()
            parts.append(page if page.startswith(("p.", "pp.")) else f"p.{page}")
        if self.applicability:
            parts.append(self.applicability.strip())
        return "[" + " | ".join(parts) + "]"


@dataclass(frozen=True)
class EvidenceItem:
    claim_id: str
    claim: str
    status: EvidenceStatus
    citations: tuple[Citation, ...] = ()
    applicable: bool = True
    current: bool = True
    support_verified: bool = False
    assumptions: tuple[str, ...] = ()

    def validate(self) -> None:
        if not self.claim_id.strip() or not self.claim.strip():
            raise CoreInvariantError("Evidence item requires a claim ID and text.")
        if self.status in {EvidenceStatus.AUTHORITATIVE, EvidenceStatus.SUPPORTED_SYNTHESIS}:
            if not self.citations:
                raise CoreInvariantError("Authoritative evidence requires at least one citation.")
            if not self.current:
                raise CoreInvariantError("Superseded evidence cannot support a current claim.")
            if not self.applicable:
                raise CoreInvariantError("Inapplicable evidence cannot support the claim.")
            if not self.support_verified:
                raise CoreInvariantError("The citation must be verified against the actual claim.")
        if self.status is EvidenceStatus.SCENARIO_ASSUMPTION and not self.assumptions:
            raise CoreInvariantError("Scenario assumptions must be stated explicitly.")
        if self.status in {
            EvidenceStatus.PILOT_REPORTED,
            EvidenceStatus.AI_POSSIBILITY,
            EvidenceStatus.INSUFFICIENT_SUPPORT,
        } and self.support_verified:
            raise CoreInvariantError("Non-authoritative evidence cannot be marked source-verified.")


@dataclass(frozen=True)
class ScenarioAnchor:
    waypoint: str | None = None
    actm: str | None = None
    utc: str | None = None
    flight_phase: str | None = None
    latitude: float | None = None
    longitude: float | None = None

    @property
    def is_anchored(self) -> bool:
        return any((self.waypoint, self.actm, self.utc, self.flight_phase))


@dataclass(frozen=True)
class WeatherState:
    airport: str
    projected_arrival_utc: str
    source_period: str
    summary: str
    assessment: OptionState
    limitations: tuple[str, ...] = ()
    citations: tuple[Citation, ...] = ()


@dataclass(frozen=True)
class AerodromeCandidate:
    icao: str
    role: str
    diversion_time: str | None = None
    distance_nm: int | None = None
    planned_level: int | None = None
    weather: WeatherState | None = None
    odss_suitability: OptionState = OptionState.UNRESOLVED
    hard_constraint_failures: tuple[str, ...] = ()
    conditions: tuple[str, ...] = ()
    residual_risks: tuple[str, ...] = ()
    citations: tuple[Citation, ...] = ()

    @property
    def option_state(self) -> OptionState:
        if self.hard_constraint_failures or self.odss_suitability is OptionState.NOT_VIABLE:
            return OptionState.NOT_VIABLE
        if self.odss_suitability is OptionState.VIABLE:
            return OptionState.VIABLE
        if self.odss_suitability is OptionState.CONDITIONAL:
            return OptionState.CONDITIONAL
        return OptionState.UNRESOLVED


@dataclass(frozen=True)
class FlightBaseline:
    case_id: str
    flight_number: str
    flight_date: str
    aircraft_type: str
    registration: str
    departure: str
    destination: str
    scheduled_departure_utc: str
    scheduled_arrival_utc: str
    source_snapshot_id: str
    source_document: str
    anchor: ScenarioAnchor
    candidates: tuple[AerodromeCandidate, ...]
    evidence: tuple[EvidenceItem, ...] = ()
    assumptions: tuple[str, ...] = ()
    odss_complete: bool = True

    def validate(self) -> None:
        required = {
            "case_id": self.case_id,
            "flight_number": self.flight_number,
            "flight_date": self.flight_date,
            "aircraft_type": self.aircraft_type,
            "departure": self.departure,
            "destination": self.destination,
            "source_snapshot_id": self.source_snapshot_id,
            "source_document": self.source_document,
        }
        missing = [key for key, value in required.items() if not str(value).strip()]
        if missing:
            raise CoreInvariantError(f"Flight baseline is missing: {', '.join(missing)}")
        if not self.odss_complete:
            raise CoreInvariantError("Flight-specific scenario options require completed ODSS processing.")
        if not self.anchor.is_anchored:
            raise CoreInvariantError("A flight-specific scenario requires waypoint, ACTM, UTC or phase.")
        if not self.candidates:
            raise CoreInvariantError("The ODSS baseline must provide candidate or explicitly unresolved aerodromes.")
        for item in self.evidence:
            item.validate()


@dataclass(frozen=True)
class PilotReasoning:
    raw_text: str
    confirmed_facts: tuple[str, ...] = ()
    assumptions: tuple[str, ...] = ()
    operational_meaning: tuple[str, ...] = ()
    projected_state: tuple[str, ...] = ()
    disconfirming_information: tuple[str, ...] = ()
    system_or_automation_behaviour: tuple[str, ...] = ()
    degraded_capabilities: tuple[str, ...] = ()
    retained_capabilities: tuple[str, ...] = ()
    safety_constraints: tuple[str, ...] = ()
    operational_objective: str | None = None
    options_considered: tuple[str, ...] = ()
    selected_option: str | None = None
    rationale: tuple[str, ...] = ()
    decision_gate: str | None = None
    implementation: tuple[str, ...] = ()
    monitoring: tuple[str, ...] = ()
    fallback: str | None = None
    crew_plan: tuple[str, ...] = ()
    self_correction: str | None = None

    @property
    def is_present(self) -> bool:
        return bool(self.raw_text.strip())


@dataclass(frozen=True)
class CognitiveObservation:
    model: str
    area: str
    status: DevelopmentalStatus
    evidence: tuple[str, ...]
    material_gap: str | None = None
    prompt: str | None = None
    safety_effect: str | None = None
    evidence_limitation: str | None = None


@dataclass(frozen=True)
class FunctionalRequirement:
    code: str
    statement: str
    hard: bool = True
    source_basis: tuple[Citation, ...] = ()


@dataclass(frozen=True)
class OptionAssessment:
    option_id: str
    label: str
    state: OptionState
    requirements_satisfied: tuple[str, ...]
    requirements_not_satisfied: tuple[str, ...]
    conditions: tuple[str, ...]
    residual_risks: tuple[str, ...]
    citations: tuple[Citation, ...]


@dataclass(frozen=True)
class DecisionStructure:
    customer_need: str
    functional_requirements: tuple[FunctionalRequirement, ...]
    hard_constraints: tuple[str, ...]
    preferences: tuple[str, ...]
    options: tuple[OptionAssessment, ...]
    couplings: tuple[str, ...]
    selected_option: str | None
    decision_gate: str | None
    monitoring: tuple[str, ...]
    fallback: str | None


@dataclass(frozen=True)
class CBTAObservation:
    competency: str
    observable_evidence: tuple[str, ...]
    status: DevelopmentalStatus
    interpretation: str
    evidence_limitation: str


@dataclass(frozen=True)
class MemoryCandidate:
    raw_pilot_wording: str
    ai_interpretation: str
    record_type: MemoryRecordType
    evidence_status: EvidenceStatus
    private: bool
    context: Mapping[str, Any]

    def validate(self) -> None:
        if not self.raw_pilot_wording.strip():
            raise CoreInvariantError("Memory candidate must preserve pilot wording.")
        if not self.ai_interpretation.strip():
            raise CoreInvariantError("Memory candidate requires a separate AI interpretation.")
        if self.raw_pilot_wording.strip() == self.ai_interpretation.strip():
            raise CoreInvariantError("Pilot wording and AI interpretation must be distinct fields.")
        if self.evidence_status is EvidenceStatus.AUTHORITATIVE:
            raise CoreInvariantError("A reasoning-memory record cannot be authoritative by itself.")


@dataclass(frozen=True)
class TeachingPlan:
    status: EvidenceStatus
    headline: str
    answer: str
    conditions: tuple[str, ...]
    decision_gate: str | None
    key_sa_point: str | None
    key_cognitive_point: str | None
    developmental_points: tuple[str, ...]
    citations: tuple[Citation, ...]
    expandable_sections: tuple[str, ...]


@dataclass(frozen=True)
class OrchestrationResult:
    route: TaskRoute
    phase: str
    next_prompt: str | None
    baseline: FlightBaseline | None
    cognitive_observations: tuple[CognitiveObservation, ...]
    decision_structure: DecisionStructure | None
    cbta_observations: tuple[CBTAObservation, ...]
    teaching_plan: TeachingPlan | None
    memory_candidate: MemoryCandidate | None
    audit: Mapping[str, Any] = field(default_factory=dict)


def tuple_of_strings(values: Sequence[Any] | None) -> tuple[str, ...]:
    if not values:
        return ()
    return tuple(str(value).strip() for value in values if str(value).strip())

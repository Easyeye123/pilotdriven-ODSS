"""Deterministic request, evidence and cognitive-activation policy for Helpyou.

This module does not answer aviation questions. It decides which specialist
workflow owns a request, which cognitive layers are permitted, which evidence
classes may support a claim, and which user-facing sections are necessary.

ODSS remains authoritative for Lido CFP analysis. Pilot memories and pilot
experience are prohibited as ODSS evidence inputs.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from enum import Enum
from typing import Iterable, Sequence


class RequestRoute(str, Enum):
    ODSS_CFP = "odss_cfp"
    CFP_GROUNDED_SCENARIO = "cfp_grounded_scenario"
    AUTHORITATIVE_COMPILATION = "authoritative_compilation"
    AUTHORITATIVE_RETRIEVAL = "authoritative_retrieval"
    DETERMINISTIC_CALCULATION = "deterministic_calculation"
    DECISION_DISCUSSION = "decision_discussion"
    PILOT_REASONING_REVIEW = "pilot_reasoning_review"
    PILOT_KNOWLEDGE_CONTRIBUTION = "pilot_knowledge_contribution"
    AUTHORITATIVE_RESEARCH = "authoritative_research"


class EvidenceClass(str, Enum):
    AUTHORITATIVE = "authoritative"
    SUPPORTED_SYNTHESIS = "supported_synthesis"
    CORROBORATED_PILOT_EXPERIENCE = "corroborated_pilot_experience"
    SINGLE_PILOT_REPORT = "single_pilot_report"
    AI_POSSIBILITY = "ai_possibility"
    DISPUTED = "disputed"
    SUPERSEDED = "superseded"
    UNSUPPORTED = "unsupported"


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


class PolicyError(ValueError):
    """Raised when a Helpyou invariant would be violated."""


@dataclass(frozen=True)
class CitationReference:
    owner: str
    document: str
    revision: str | None = None
    effective_date: date | None = None
    section: str | None = None
    page: str | int | None = None
    applicability: str | None = None

    @staticmethod
    def _date(value: date) -> str:
        return value.strftime("%d.%m.%y")

    def compact(self) -> str:
        parts: list[str] = [self.owner.strip(), self.document.strip()]
        if self.revision:
            parts.append(self.revision.strip())
        if self.effective_date:
            parts.append(f"eff {self._date(self.effective_date)}")
        if self.section:
            parts.append(self.section.strip())
        if self.page is not None:
            page_text = str(self.page).strip()
            parts.append(page_text if page_text.startswith("p.") else f"p.{page_text}")
        if self.applicability:
            parts.append(self.applicability.strip())
        return "[" + " | ".join(parts) + "]"


@dataclass(frozen=True)
class Claim:
    text: str
    evidence_class: EvidenceClass
    citations: tuple[CitationReference, ...] = ()
    applicable: bool = True
    current: bool = True
    source_support_verified: bool = False
    assumptions: tuple[str, ...] = ()

    def validate(self) -> None:
        if not self.text.strip():
            raise PolicyError("A claim cannot be empty.")

        if self.evidence_class in {
            EvidenceClass.AUTHORITATIVE,
            EvidenceClass.SUPPORTED_SYNTHESIS,
        }:
            if not self.citations:
                raise PolicyError(
                    "Authoritative and supported-synthesis claims require citations."
                )
            if not self.applicable:
                raise PolicyError("An inapplicable source cannot support the claim.")
            if not self.current:
                raise PolicyError("A superseded source cannot support a current claim.")
            if not self.source_support_verified:
                raise PolicyError(
                    "The cited source must be verified to support the actual claim."
                )

        if self.evidence_class is EvidenceClass.SUPERSEDED and self.current:
            raise PolicyError("Superseded evidence cannot be marked current.")

        if self.evidence_class in {
            EvidenceClass.SINGLE_PILOT_REPORT,
            EvidenceClass.CORROBORATED_PILOT_EXPERIENCE,
            EvidenceClass.AI_POSSIBILITY,
            EvidenceClass.DISPUTED,
            EvidenceClass.UNSUPPORTED,
        } and self.source_support_verified and self.evidence_class is not EvidenceClass.DISPUTED:
            raise PolicyError(
                "Non-authoritative evidence must not be promoted by the authoritative verifier."
            )


@dataclass(frozen=True)
class RequestContext:
    intents: tuple[str, ...] = ()
    attachment_names: tuple[str, ...] = ()
    has_lido_cfp: bool = False
    loft_style: bool = False
    pilot_reasoning_present: bool = False
    developmental_review_requested: bool = False
    generic_scenario_explicitly_selected: bool = False
    operator: str | None = None
    aircraft: str | None = None
    scenario_date: date | None = None


@dataclass(frozen=True)
class SubrequestPlan:
    route: RequestRoute
    specialist_engine: str
    axiomatic_design: bool = True
    rasmussen: bool = False
    endsley: bool = False
    cbta: bool = False
    requires_cfp_upload: bool = False
    flight_specific_options_permitted: bool = False
    notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class RequestPlan:
    subrequests: tuple[SubrequestPlan, ...]

    @property
    def is_mixed(self) -> bool:
        return len(self.subrequests) > 1


@dataclass(frozen=True)
class PilotMemoryRecord:
    record_id: str
    raw_pilot_wording: str
    ai_interpretation: str
    record_type: MemoryRecordType
    evidence_class: EvidenceClass
    private: bool = True
    aircraft: str | None = None
    operator: str | None = None
    phase_of_flight: str | None = None
    airport_or_route: str | None = None
    source_references: tuple[CitationReference, ...] = ()
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    version: int = 1
    supersedes: str | None = None

    def validate(self) -> None:
        if not self.record_id.strip():
            raise PolicyError("Memory record requires an ID.")
        if not self.raw_pilot_wording.strip():
            raise PolicyError("Pilot wording must be preserved.")
        if not self.ai_interpretation.strip():
            raise PolicyError("AI interpretation must be stored separately.")
        if self.raw_pilot_wording.strip() == self.ai_interpretation.strip():
            raise PolicyError(
                "Raw pilot wording and AI interpretation must remain distinct fields."
            )
        if self.version < 1:
            raise PolicyError("Memory version must be at least 1.")
        if self.evidence_class is EvidenceClass.AUTHORITATIVE and not self.source_references:
            raise PolicyError(
                "A pilot contribution cannot be authoritative without verified source references."
            )


INTENT_ALIASES: dict[str, RequestRoute] = {
    "cfp": RequestRoute.ODSS_CFP,
    "cfp_analysis": RequestRoute.ODSS_CFP,
    "lido_cfp": RequestRoute.ODSS_CFP,
    "loft": RequestRoute.CFP_GROUNDED_SCENARIO,
    "scenario": RequestRoute.CFP_GROUNDED_SCENARIO,
    "scenario_discussion": RequestRoute.CFP_GROUNDED_SCENARIO,
    "compile_manuals": RequestRoute.AUTHORITATIVE_COMPILATION,
    "compare_manuals": RequestRoute.AUTHORITATIVE_COMPILATION,
    "consolidate_procedures": RequestRoute.AUTHORITATIVE_COMPILATION,
    "manual_lookup": RequestRoute.AUTHORITATIVE_RETRIEVAL,
    "procedure_lookup": RequestRoute.AUTHORITATIVE_RETRIEVAL,
    "limitation_lookup": RequestRoute.AUTHORITATIVE_RETRIEVAL,
    "regulatory_lookup": RequestRoute.AUTHORITATIVE_RETRIEVAL,
    "calculate": RequestRoute.DETERMINISTIC_CALCULATION,
    "conversion": RequestRoute.DETERMINISTIC_CALCULATION,
    "decision_discussion": RequestRoute.DECISION_DISCUSSION,
    "decision_factors": RequestRoute.DECISION_DISCUSSION,
    "what_would_you_do": RequestRoute.DECISION_DISCUSSION,
    "review_my_reasoning": RequestRoute.PILOT_REASONING_REVIEW,
    "decision_review": RequestRoute.PILOT_REASONING_REVIEW,
    "pilot_experience": RequestRoute.PILOT_KNOWLEDGE_CONTRIBUTION,
    "pilot_correction": RequestRoute.PILOT_KNOWLEDGE_CONTRIBUTION,
    "contribute_knowledge": RequestRoute.PILOT_KNOWLEDGE_CONTRIBUTION,
    "research": RequestRoute.AUTHORITATIVE_RESEARCH,
}


def _attachment_is_lido_cfp(names: Sequence[str]) -> bool:
    return any(
        "lido" in name.lower() and ("cfp" in name.lower() or name.lower().endswith(".pdf"))
        for name in names
    )


def _plan_for_route(route: RequestRoute, context: RequestContext) -> SubrequestPlan:
    if route is RequestRoute.ODSS_CFP:
        return SubrequestPlan(
            route=route,
            specialist_engine="ODSS",
            rasmussen=False,
            endsley=False,
            cbta=False,
            notes=(
                "ODSS owns all deterministic CFP analysis.",
                "Pilot memory and pilot experience are prohibited as evidence inputs.",
            ),
        )

    if route is RequestRoute.CFP_GROUNDED_SCENARIO:
        has_cfp = context.has_lido_cfp or _attachment_is_lido_cfp(context.attachment_names)
        generic = context.generic_scenario_explicitly_selected
        return SubrequestPlan(
            route=route,
            specialist_engine="ODSS baseline + Helpyou scenario engine",
            rasmussen=context.pilot_reasoning_present,
            endsley=context.pilot_reasoning_present,
            cbta=context.pilot_reasoning_present
            and context.developmental_review_requested,
            requires_cfp_upload=not has_cfp and not generic,
            flight_specific_options_permitted=has_cfp,
            notes=(
                "Flight-specific options require an ODSS-processed Lido CFP.",
                "Scenario weather must use the same ODSS weather-selection and validity logic.",
                "Options are initially presented without AI ranking.",
            ),
        )

    if route is RequestRoute.AUTHORITATIVE_COMPILATION:
        return SubrequestPlan(
            route=route,
            specialist_engine="Helpyou Compiler",
            rasmussen=False,
            endsley=False,
            cbta=False,
        )

    if route is RequestRoute.AUTHORITATIVE_RETRIEVAL:
        return SubrequestPlan(
            route=route,
            specialist_engine="Authoritative Retrieval",
            rasmussen=False,
            endsley=False,
            cbta=False,
        )

    if route is RequestRoute.DETERMINISTIC_CALCULATION:
        return SubrequestPlan(
            route=route,
            specialist_engine="Deterministic Calculator",
            rasmussen=False,
            endsley=False,
            cbta=False,
        )

    if route is RequestRoute.DECISION_DISCUSSION:
        return SubrequestPlan(
            route=route,
            specialist_engine="Helpyou Decision Teaching",
            rasmussen=context.pilot_reasoning_present,
            endsley=context.pilot_reasoning_present,
            cbta=context.pilot_reasoning_present
            and context.developmental_review_requested,
        )

    if route is RequestRoute.PILOT_REASONING_REVIEW:
        return SubrequestPlan(
            route=route,
            specialist_engine="Helpyou Decision Teaching",
            rasmussen=context.pilot_reasoning_present,
            endsley=context.pilot_reasoning_present,
            cbta=context.pilot_reasoning_present,
            notes=(
                "CBTA output is developmental, not an operator or licensing grade.",
                "Flight Discipline is a PilotDriven adapted competency.",
            ),
        )

    if route is RequestRoute.PILOT_KNOWLEDGE_CONTRIBUTION:
        return SubrequestPlan(
            route=route,
            specialist_engine="Pilot Memory and Knowledge Commons",
            rasmussen=False,
            endsley=False,
            cbta=False,
        )

    return SubrequestPlan(
        route=route,
        specialist_engine="Authoritative Research and Synthesis",
        rasmussen=False,
        endsley=False,
        cbta=False,
    )


def route_request(context: RequestContext) -> RequestPlan:
    """Create a deterministic route plan, splitting mixed requests.

    A Lido CFP attachment always creates an ODSS subrequest. An explicit scenario
    intent may additionally create a CFP-grounded scenario subrequest.
    """
    routes: list[RequestRoute] = []

    has_cfp = context.has_lido_cfp or _attachment_is_lido_cfp(context.attachment_names)
    if has_cfp:
        routes.append(RequestRoute.ODSS_CFP)

    for intent in context.intents:
        route = INTENT_ALIASES.get(intent.strip().lower())
        if route is not None and route not in routes:
            routes.append(route)

    if context.loft_style and RequestRoute.CFP_GROUNDED_SCENARIO not in routes:
        routes.append(RequestRoute.CFP_GROUNDED_SCENARIO)

    if not routes:
        routes.append(RequestRoute.AUTHORITATIVE_RESEARCH)

    return RequestPlan(tuple(_plan_for_route(route, context) for route in routes))


def minimum_sufficient_sections(plan: SubrequestPlan) -> tuple[str, ...]:
    """Return only the user-facing sections needed for the routed task."""
    if plan.route is RequestRoute.ODSS_CFP:
        return ("ODSS findings", "Flight-specific references")
    if plan.route is RequestRoute.AUTHORITATIVE_RETRIEVAL:
        return ("Answer", "Material conditions", "Reference")
    if plan.route is RequestRoute.DETERMINISTIC_CALCULATION:
        return ("Result", "Inputs and source", "Method and assumptions")
    if plan.route is RequestRoute.AUTHORITATIVE_COMPILATION:
        return (
            "Consolidated conclusion",
            "Conditions and exceptions",
            "Conflicts and precedence",
            "Citation matrix",
        )
    if plan.route is RequestRoute.CFP_GROUNDED_SCENARIO:
        sections = [
            "ODSS scenario baseline",
            "Viable unranked options",
            "Decision gates",
            "References",
        ]
        if plan.endsley:
            sections.append("Situational-awareness check")
        if plan.rasmussen:
            sections.append("Cognitive review")
        if plan.cbta:
            sections.append("Developmental CBTA reflection")
        return tuple(sections)
    if plan.route in {
        RequestRoute.DECISION_DISCUSSION,
        RequestRoute.PILOT_REASONING_REVIEW,
    }:
        sections = ["Teaching answer", "Controlling considerations", "References"]
        if plan.endsley:
            sections.append("Situational-awareness check")
        if plan.rasmussen:
            sections.append("Cognitive review")
        if plan.cbta:
            sections.append("Developmental CBTA reflection")
        return tuple(sections)
    if plan.route is RequestRoute.PILOT_KNOWLEDGE_CONTRIBUTION:
        return ("Contribution classification", "What Helpyou learned", "Memory controls")
    return ("Answer", "Evidence status", "References")


def validate_odss_evidence(classes: Iterable[EvidenceClass]) -> None:
    """Block non-authoritative knowledge from ODSS operational conclusions."""
    prohibited = {
        EvidenceClass.CORROBORATED_PILOT_EXPERIENCE,
        EvidenceClass.SINGLE_PILOT_REPORT,
        EvidenceClass.AI_POSSIBILITY,
        EvidenceClass.DISPUTED,
        EvidenceClass.SUPERSEDED,
        EvidenceClass.UNSUPPORTED,
    }
    found = sorted({item.value for item in classes if item in prohibited})
    if found:
        raise PolicyError(
            "ODSS evidence boundary violation: " + ", ".join(found)
        )


def interrogative_questions(plan: SubrequestPlan) -> tuple[str, ...]:
    """Return only questions that materially affect the routed result."""
    if plan.route is RequestRoute.AUTHORITATIVE_RETRIEVAL:
        return (
            "Which operator, aircraft/configuration and scenario date apply?",
        )
    if plan.route is RequestRoute.AUTHORITATIVE_COMPILATION:
        return (
            "Which topic, operator, aircraft, date and document set should be compiled?",
        )
    if plan.route is RequestRoute.DETERMINISTIC_CALCULATION:
        return (
            "What are the input values, units, source and governing assumptions?",
        )
    if plan.route is RequestRoute.CFP_GROUNDED_SCENARIO:
        if plan.requires_cfp_upload:
            return ("Upload the applicable Lido CFP or select an existing CFP case.",)
        return (
            "Where in the flight does the scenario occur: waypoint, ACTM, UTC or flight phase?",
            "Which option would you select, what drives it, and what changes the plan?",
        )
    if plan.route in {
        RequestRoute.DECISION_DISCUSSION,
        RequestRoute.PILOT_REASONING_REVIEW,
    }:
        return (
            "What information is confirmed rather than assumed?",
            "What does it change about aircraft capability and the main safety margin?",
            "What is likely to happen next, and what exact condition changes the plan?",
        )
    if plan.route is RequestRoute.PILOT_KNOWLEDGE_CONTRIBUTION:
        return (
            "Was this your direct experience, a report from another pilot, or a source-backed correction?",
            "Which aircraft, route, phase and conditions applied, and should it remain private?",
        )
    return ()

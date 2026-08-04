"""Deterministic request segregation for Helpyou Core v0.2."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .contracts import TaskRoute


@dataclass(frozen=True)
class RequestEnvelope:
    intents: tuple[str, ...] = ()
    attachment_names: tuple[str, ...] = ()
    has_odss_case: bool = False
    pilot_reasoning_present: bool = False
    asks_for_developmental_review: bool = False


@dataclass(frozen=True)
class RoutedTask:
    route: TaskRoute
    requires_odss: bool
    cognitive_models_permitted: bool
    cbta_permitted: bool


ALIASES: dict[str, TaskRoute] = {
    "cfp": TaskRoute.ODSS_CFP,
    "lido_cfp": TaskRoute.ODSS_CFP,
    "cfp_analysis": TaskRoute.ODSS_CFP,
    "loft": TaskRoute.CFP_GROUNDED_SCENARIO,
    "loft_style": TaskRoute.CFP_GROUNDED_SCENARIO,
    "scenario": TaskRoute.CFP_GROUNDED_SCENARIO,
    "scenario_discussion": TaskRoute.CFP_GROUNDED_SCENARIO,
    "manual_lookup": TaskRoute.AUTHORITATIVE_RETRIEVAL,
    "procedure_lookup": TaskRoute.AUTHORITATIVE_RETRIEVAL,
    "limitation_lookup": TaskRoute.AUTHORITATIVE_RETRIEVAL,
    "compile_manuals": TaskRoute.AUTHORITATIVE_COMPILATION,
    "compare_manuals": TaskRoute.AUTHORITATIVE_COMPILATION,
    "calculate": TaskRoute.DETERMINISTIC_CALCULATION,
    "decision_discussion": TaskRoute.DECISION_DISCUSSION,
    "decision_factors": TaskRoute.DECISION_DISCUSSION,
    "review_my_reasoning": TaskRoute.PILOT_REASONING_REVIEW,
    "decision_review": TaskRoute.PILOT_REASONING_REVIEW,
    "pilot_experience": TaskRoute.PILOT_KNOWLEDGE_CONTRIBUTION,
    "pilot_correction": TaskRoute.PILOT_KNOWLEDGE_CONTRIBUTION,
    "research": TaskRoute.AUTHORITATIVE_RESEARCH,
}


def _looks_like_lido_cfp(name: str) -> bool:
    lowered = name.casefold()
    explicit = "lido" in lowered and ("cfp" in lowered or lowered.endswith(".pdf"))
    sia_pattern = lowered.startswith("sq0") and lowered.endswith(".pdf")
    return explicit or sia_pattern


def _task(route: TaskRoute, envelope: RequestEnvelope) -> RoutedTask:
    cognitive = route in {
        TaskRoute.CFP_GROUNDED_SCENARIO,
        TaskRoute.DECISION_DISCUSSION,
        TaskRoute.PILOT_REASONING_REVIEW,
    } and envelope.pilot_reasoning_present
    return RoutedTask(
        route=route,
        requires_odss=route in {TaskRoute.ODSS_CFP, TaskRoute.CFP_GROUNDED_SCENARIO},
        cognitive_models_permitted=cognitive,
        cbta_permitted=cognitive and envelope.asks_for_developmental_review,
    )


def route_request(envelope: RequestEnvelope) -> tuple[RoutedTask, ...]:
    """Split mixed requests while preserving specialist ownership.

    A Lido CFP attachment creates an ODSS task. It does not, by itself, create a
    cognitive assessment. A scenario intent creates a separate scenario task.
    """

    routes: list[TaskRoute] = []
    has_cfp_attachment = any(_looks_like_lido_cfp(name) for name in envelope.attachment_names)
    if has_cfp_attachment:
        routes.append(TaskRoute.ODSS_CFP)

    for raw_intent in envelope.intents:
        route = ALIASES.get(raw_intent.strip().casefold())
        if route is not None and route not in routes:
            routes.append(route)

    if not routes:
        routes.append(TaskRoute.AUTHORITATIVE_RESEARCH)

    return tuple(_task(route, envelope) for route in routes)


def routes_only(tasks: Iterable[RoutedTask]) -> tuple[TaskRoute, ...]:
    return tuple(item.route for item in tasks)

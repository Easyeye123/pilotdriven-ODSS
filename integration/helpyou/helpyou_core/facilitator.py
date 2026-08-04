"""Guided inquiry state machine for Helpyou."""

from __future__ import annotations

from dataclasses import dataclass

from .contracts import CognitiveObservation, FlightBaseline, PilotReasoning
from . import endsley, rasmussen


@dataclass(frozen=True)
class FacilitationPolicy:
    diagnosis_uncertain: bool = False
    require_widen_scan: bool = True
    require_decision_gate: bool = True
    ask_option_before_cognitive_probe: bool = True


@dataclass(frozen=True)
class FacilitationStep:
    phase: str
    prompt: str | None
    rationale: str | None
    endsley_observations: tuple[CognitiveObservation, ...] = ()
    rasmussen_observations: tuple[CognitiveObservation, ...] = ()


def _endsley_prompt(
    observations: tuple[CognitiveObservation, ...],
    policy: FacilitationPolicy,
) -> str | None:
    allowed = ["Picture now", "What it means", "Projection ahead"]
    if policy.require_widen_scan:
        allowed.append("Widen the scan")
    if policy.require_decision_gate:
        allowed.append("Decision gate")
    by_area = {item.area: item for item in observations}
    for area in allowed:
        item = by_area.get(area)
        if item and item.prompt:
            return item.prompt
    return None


def _rasmussen_prompt(
    observations: tuple[CognitiveObservation, ...],
    policy: FacilitationPolicy,
) -> str | None:
    priority = []
    if policy.diagnosis_uncertain:
        priority.extend(("Information and indications", "System and automation behaviour"))
    priority.extend(
        (
            "Aircraft and crew capability",
            "Safety constraints and margins",
            "Crew objective",
            "Action and feedback",
        )
    )
    by_area = {item.area: item for item in observations}
    for area in priority:
        item = by_area.get(area)
        if item and item.prompt:
            return item.prompt
    return None


def next_step(
    baseline: FlightBaseline | None,
    reasoning: PilotReasoning | None,
    policy: FacilitationPolicy | None = None,
) -> FacilitationStep:
    policy = policy or FacilitationPolicy()

    if baseline is None:
        return FacilitationStep(
            phase="awaiting_cfp",
            prompt="Upload the applicable Lido CFP or select an existing ODSS case.",
            rationale="Flight-specific options require an ODSS-processed flight baseline.",
        )

    if not baseline.anchor.is_anchored:
        return FacilitationStep(
            phase="awaiting_anchor",
            prompt="Where in the flight does the scenario occur: waypoint, ACTM, UTC or flight phase?",
            rationale="The scenario time and position determine the relevant fuel, weather and diversion conditions.",
        )

    if reasoning is None or not reasoning.is_present:
        return FacilitationStep(
            phase="awaiting_pilot_reasoning",
            prompt=(
                "Which viable option would you select, what is the controlling reason, and what would make you change the plan?"
            ),
            rationale="Helpyou facilitates the pilot's own reasoning before providing the teaching answer.",
        )

    if policy.ask_option_before_cognitive_probe and not reasoning.selected_option:
        return FacilitationStep(
            phase="awaiting_option",
            prompt="Which option would you select, and what is the principal factor driving that choice?",
            rationale="A decision discussion needs an explicit course of action before its structure can be reviewed.",
        )

    endsley_observations = endsley.review(reasoning)
    rasmussen_observations = rasmussen.review(reasoning)

    prompt = _endsley_prompt(endsley_observations, policy)
    if prompt:
        return FacilitationStep(
            phase="eliciting_situation_awareness",
            prompt=prompt,
            rationale="This is the first material missing link in the pilot's present, meaning or projection model.",
            endsley_observations=endsley_observations,
            rasmussen_observations=rasmussen_observations,
        )

    prompt = _rasmussen_prompt(rasmussen_observations, policy)
    if prompt:
        return FacilitationStep(
            phase="eliciting_operational_model",
            prompt=prompt,
            rationale="This is the first material missing link between the flight facts, aircraft capability, safety constraints and action.",
            endsley_observations=endsley_observations,
            rasmussen_observations=rasmussen_observations,
        )

    return FacilitationStep(
        phase="ready_to_teach",
        prompt=None,
        rationale="The minimum decision model is complete enough for a source-grounded teaching response.",
        endsley_observations=endsley_observations,
        rasmussen_observations=rasmussen_observations,
    )

"""End-to-end deterministic Helpyou Core v0.2 orchestrator."""

from __future__ import annotations

from dataclasses import dataclass

from .axiomatic_decision import build_decision_structure
from .cbta_mapper import map_observations
from .contracts import (
    FlightBaseline,
    OrchestrationResult,
    PilotReasoning,
    TaskRoute,
)
from .evidence_guard import validate_odss_baseline
from .facilitator import FacilitationPolicy, next_step
from .memory_classifier import classify_reasoning
from .response_planner import build_teaching_plan


POLICY_VERSION = "helpyou-core-v0.2"


@dataclass(frozen=True)
class OrchestrationRequest:
    route: TaskRoute
    baseline: FlightBaseline | None = None
    reasoning: PilotReasoning | None = None
    developmental_review_requested: bool = True
    facilitation_policy: FacilitationPolicy = FacilitationPolicy()


def run(request: OrchestrationRequest) -> OrchestrationResult:
    if request.route is not TaskRoute.CFP_GROUNDED_SCENARIO:
        return OrchestrationResult(
            route=request.route,
            phase="delegated_to_specialist_engine",
            next_prompt=None,
            baseline=request.baseline,
            cognitive_observations=(),
            decision_structure=None,
            cbta_observations=(),
            teaching_plan=None,
            memory_candidate=classify_reasoning(request.reasoning, request.baseline),
            audit={
                "policy_version": POLICY_VERSION,
                "note": "This vertical slice implements CFP-grounded scenario discussion only.",
            },
        )

    if request.baseline is not None:
        validate_odss_baseline(request.baseline)

    step = next_step(
        baseline=request.baseline,
        reasoning=request.reasoning,
        policy=request.facilitation_policy,
    )

    cognitive = step.endsley_observations + step.rasmussen_observations
    decision_structure = None
    cbta = ()
    teaching_plan = None

    if request.baseline is not None:
        decision_structure = build_decision_structure(request.baseline, request.reasoning)

    if step.phase == "ready_to_teach" and request.reasoning is not None and request.baseline is not None:
        if request.developmental_review_requested:
            cbta = map_observations(request.reasoning)
        teaching_plan = build_teaching_plan(
            baseline=request.baseline,
            structure=decision_structure,
            endsley_observations=step.endsley_observations,
            rasmussen_observations=step.rasmussen_observations,
            cbta_observations=cbta,
        )

    return OrchestrationResult(
        route=request.route,
        phase=step.phase,
        next_prompt=step.prompt,
        baseline=request.baseline,
        cognitive_observations=cognitive,
        decision_structure=decision_structure,
        cbta_observations=cbta,
        teaching_plan=teaching_plan,
        memory_candidate=classify_reasoning(request.reasoning, request.baseline),
        audit={
            "policy_version": POLICY_VERSION,
            "source_snapshot_id": (
                request.baseline.source_snapshot_id if request.baseline else None
            ),
            "facilitation_rationale": step.rationale,
            "authoritative_answer_generated": teaching_plan is not None,
            "actual_flight_performance_observed": False,
        },
    )

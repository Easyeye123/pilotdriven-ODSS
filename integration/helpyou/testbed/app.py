"""Browser test bed for PilotDriven Helpyou flight discussions.

This app is intentionally deterministic. It exposes the existing Helpyou Core
state machine through a chat-like interface so a pilot can teach Helpyou,
explain a decision and inspect the resulting teaching plan. Flight-specific
facts remain owned by Flight Briefing and are loaded from immutable fixtures or
future Flight Briefing snapshots.
"""

from __future__ import annotations

from dataclasses import asdict, fields, is_dataclass
from enum import Enum
import json
import os
from pathlib import Path
from typing import Any, Mapping

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

from helpyou_core.contracts import PilotReasoning, TaskRoute
from helpyou_core.odss_adapter import load_baseline
from helpyou_core.orchestrator import OrchestrationRequest, run
from helpyou_core.terminology import PUBLIC_PRODUCT_NAME

from .store import TestbedStore


TESTBED_DIR = Path(__file__).resolve().parent
HELPYOU_DIR = TESTBED_DIR.parent
FIXTURE_DIR = HELPYOU_DIR / "fixtures"
TEMPLATE_DIR = TESTBED_DIR / "templates"
STATIC_DIR = TESTBED_DIR / "static"
DEFAULT_DB = TESTBED_DIR / "data" / "helpyou_testbed.db"
DB_PATH = Path(os.environ.get("HELPYOU_TESTBED_DB", DEFAULT_DB))
SQ23_FIXTURE = FIXTURE_DIR / "sq23_oei_etp1_1d.json"

SQ23_CASE_ID = "SQ23-25JUL26-OEI-ETP1-1D"
SQ23_SCENARIO = (
    "Stable one-engine-inoperative condition at ETP1-1D. Compare the Flight "
    "Briefing candidates CYQX and EINN and explain the decision gate."
)
FORBIDDEN_SQ23_MUTATIONS = (
    "fire",
    "smoke",
    "severe damage",
    "uncontained",
    "depressur",
    "dual engine",
)

store = TestbedStore(DB_PATH)
templates = Jinja2Templates(directory=TEMPLATE_DIR)
app = FastAPI(
    title="PilotDriven Helpyou Flight Discussion Test Bed",
    version="0.1.0",
)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


class SessionCreate(BaseModel):
    mode: str = Field(pattern="^(flight_scenario|teach_helpyou)$")
    case_id: str | None = None
    scenario: str = Field(min_length=3, max_length=4000)


class AnswerSubmit(BaseModel):
    question_key: str = Field(min_length=2, max_length=120)
    values: dict[str, Any] = Field(default_factory=dict)


class TeachSubmit(BaseModel):
    record_type: str = Field(
        pattern=(
            "^(pilot_experience|pilot_observation|pilot_correction|pilot_technique|"
            "pilot_hypothesis|source_reference|interaction_preference)$"
        )
    )
    raw_pilot_wording: str = Field(min_length=3, max_length=12000)
    context: str = Field(default="", max_length=4000)
    privacy_scope: str = Field(default="private", pattern="^(private|shared_candidate)$")


class MessageSubmit(BaseModel):
    content: str = Field(min_length=1, max_length=12000)


def _enum_json(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value):
        return {key: _enum_json(item) for key, item in asdict(value).items()}
    if isinstance(value, Mapping):
        return {str(key): _enum_json(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_enum_json(item) for item in value]
    return value


def _reasoning_from_mapping(data: Mapping[str, Any] | None) -> PilotReasoning | None:
    if not data:
        return None
    allowed = {item.name for item in fields(PilotReasoning)}
    kwargs: dict[str, Any] = {}
    tuple_fields = {
        "confirmed_facts",
        "assumptions",
        "operational_meaning",
        "projected_state",
        "disconfirming_information",
        "system_or_automation_behaviour",
        "degraded_capabilities",
        "retained_capabilities",
        "safety_constraints",
        "options_considered",
        "rationale",
        "implementation",
        "monitoring",
        "crew_plan",
    }
    for key, value in data.items():
        if key not in allowed:
            continue
        if key in tuple_fields:
            if isinstance(value, str):
                value = [value]
            kwargs[key] = tuple(str(item).strip() for item in (value or []) if str(item).strip())
        else:
            kwargs[key] = value
    raw = str(kwargs.get("raw_text", "")).strip()
    if not raw:
        return None
    kwargs["raw_text"] = raw
    return PilotReasoning(**kwargs)


def _append_text(reasoning: dict[str, Any], *, label: str, values: list[str]) -> None:
    cleaned = [item.strip() for item in values if item and item.strip()]
    if not cleaned:
        return
    block = f"{label}: " + " | ".join(cleaned)
    current = str(reasoning.get("raw_text", "")).strip()
    reasoning["raw_text"] = f"{current}\n{block}".strip()


def _list_value(values: Mapping[str, Any], key: str) -> list[str]:
    value = values.get(key)
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value).strip()
    if not text:
        return []
    return [part.strip() for part in text.replace("\r", "").split("\n") if part.strip()]


def _apply_answer(
    reasoning: dict[str, Any], question_key: str, values: Mapping[str, Any]
) -> dict[str, Any]:
    reasoning = dict(reasoning)

    if question_key == "decision.initial":
        selected = str(values.get("selected_option", "")).strip().upper()
        rationale = _list_value(values, "rationale")
        if not selected or not rationale:
            raise ValueError("Select an option and state the controlling reason.")
        reasoning["selected_option"] = selected
        reasoning["options_considered"] = list(
            dict.fromkeys([*reasoning.get("options_considered", []), selected])
        )
        reasoning["rationale"] = rationale
        _append_text(reasoning, label="Initial decision", values=[selected, *rationale])
        return reasoning

    if question_key == "endsley.picture_now":
        confirmed = _list_value(values, "confirmed_facts")
        assumptions = _list_value(values, "assumptions")
        if not confirmed:
            raise ValueError("State at least one confirmed fact.")
        reasoning["confirmed_facts"] = confirmed
        reasoning["assumptions"] = assumptions
        _append_text(
            reasoning,
            label="Picture now",
            values=[*confirmed, *[f"Assumption: {item}" for item in assumptions]],
        )
        return reasoning

    mapping = {
        "endsley.meaning": ("operational_meaning", "Operational meaning"),
        "endsley.projection": ("projected_state", "Projection ahead"),
        "endsley.widen_scan": ("disconfirming_information", "Widen the scan"),
        "rasmussen.constraints": ("safety_constraints", "Safety constraints"),
    }
    if question_key in mapping:
        target, label = mapping[question_key]
        items = _list_value(values, "answer")
        if not items:
            raise ValueError("Provide a material answer before continuing.")
        reasoning[target] = items
        _append_text(reasoning, label=label, values=items)
        return reasoning

    if question_key == "endsley.decision_gate":
        gate = str(values.get("decision_gate", "")).strip()
        fallback = str(values.get("fallback", "")).strip().upper()
        if not gate:
            raise ValueError("State the condition that changes the plan and the action that follows.")
        reasoning["decision_gate"] = gate
        reasoning["fallback"] = fallback or None
        _append_text(
            reasoning,
            label="Decision gate",
            values=[gate, f"Fallback: {fallback}" if fallback else ""],
        )
        return reasoning

    if question_key == "rasmussen.capability":
        degraded = _list_value(values, "degraded_capabilities")
        retained = _list_value(values, "retained_capabilities")
        if not degraded or not retained:
            raise ValueError("State both degraded and retained capability.")
        reasoning["degraded_capabilities"] = degraded
        reasoning["retained_capabilities"] = retained
        _append_text(
            reasoning,
            label="Aircraft and crew capability",
            values=[
                *[f"Degraded: {item}" for item in degraded],
                *[f"Retained: {item}" for item in retained],
            ],
        )
        return reasoning

    if question_key == "rasmussen.objective":
        objective = str(values.get("operational_objective", "")).strip()
        if not objective:
            raise ValueError("State the crew's operational objective.")
        reasoning["operational_objective"] = objective
        _append_text(reasoning, label="Crew objective", values=[objective])
        return reasoning

    if question_key == "rasmussen.action_feedback":
        implementation = _list_value(values, "implementation")
        monitoring = _list_value(values, "monitoring")
        crew_plan = _list_value(values, "crew_plan")
        if not implementation or not monitoring:
            raise ValueError("State both implementation actions and monitoring/feedback.")
        reasoning["implementation"] = implementation
        reasoning["monitoring"] = monitoring
        reasoning["crew_plan"] = crew_plan
        _append_text(
            reasoning,
            label="Action and feedback",
            values=[*implementation, *monitoring, *crew_plan],
        )
        return reasoning

    raise ValueError(f"Unsupported test-bed question: {question_key}")


def _question_for_result(result: Any) -> dict[str, Any] | None:
    if result.phase in {"awaiting_pilot_reasoning", "awaiting_option"}:
        options = []
        if result.decision_structure:
            options = [
                {
                    "value": item.option_id,
                    "label": item.label,
                    "state": item.state.value,
                }
                for item in result.decision_structure.options
                if item.state.value != "not_viable"
            ]
        return {
            "key": "decision.initial",
            "model": "Decision",
            "title": "Your initial decision",
            "prompt": result.next_prompt,
            "fields": [
                {
                    "name": "selected_option",
                    "label": "Selected option",
                    "type": "options",
                    "options": options,
                },
                {
                    "name": "rationale",
                    "label": "Controlling reason",
                    "type": "textarea",
                    "placeholder": "State the main operational reason. One material point per line.",
                },
            ],
        }

    if result.phase not in {"eliciting_situation_awareness", "eliciting_operational_model"}:
        return None

    prompted = next(
        (item for item in result.cognitive_observations if item.prompt == result.next_prompt),
        None,
    )
    if prompted is None:
        return None
    key_map = {
        ("Endsley", "Picture now"): "endsley.picture_now",
        ("Endsley", "What it means"): "endsley.meaning",
        ("Endsley", "Projection ahead"): "endsley.projection",
        ("Endsley", "Widen the scan"): "endsley.widen_scan",
        ("Endsley", "Decision gate"): "endsley.decision_gate",
        ("Rasmussen", "Aircraft and crew capability"): "rasmussen.capability",
        ("Rasmussen", "Safety constraints and margins"): "rasmussen.constraints",
        ("Rasmussen", "Crew objective"): "rasmussen.objective",
        ("Rasmussen", "Action and feedback"): "rasmussen.action_feedback",
    }
    key = key_map.get((prompted.model, prompted.area))
    if key is None:
        return None
    fields_by_key: dict[str, list[dict[str, Any]]] = {
        "endsley.picture_now": [
            {
                "name": "confirmed_facts",
                "label": "Confirmed facts",
                "type": "textarea",
                "placeholder": "One confirmed fact per line.",
            },
            {
                "name": "assumptions",
                "label": "Assumptions or unresolved items",
                "type": "textarea",
                "placeholder": "Optional. One assumption per line.",
            },
        ],
        "endsley.meaning": [
            {"name": "answer", "label": "Operational meaning", "type": "textarea"}
        ],
        "endsley.projection": [
            {
                "name": "answer",
                "label": "Projection ahead",
                "type": "textarea",
                "placeholder": "What changes at the next decision point? Which option or margin may be lost?",
            }
        ],
        "endsley.widen_scan": [
            {
                "name": "answer",
                "label": "Disconfirming information or neglected area",
                "type": "textarea",
            }
        ],
        "endsley.decision_gate": [
            {
                "name": "decision_gate",
                "label": "Decision gate",
                "type": "textarea",
                "placeholder": "Condition + limit/trigger + action.",
            },
            {
                "name": "fallback",
                "label": "Fallback option",
                "type": "text",
                "placeholder": "e.g. EINN",
            },
        ],
        "rasmussen.capability": [
            {
                "name": "degraded_capabilities",
                "label": "Degraded or lost capability",
                "type": "textarea",
            },
            {
                "name": "retained_capabilities",
                "label": "Retained capability",
                "type": "textarea",
            },
        ],
        "rasmussen.constraints": [
            {
                "name": "answer",
                "label": "Controlling safety margins",
                "type": "textarea",
            }
        ],
        "rasmussen.objective": [
            {
                "name": "operational_objective",
                "label": "Crew objective",
                "type": "textarea",
            }
        ],
        "rasmussen.action_feedback": [
            {
                "name": "implementation",
                "label": "Implementation actions",
                "type": "textarea",
            },
            {
                "name": "monitoring",
                "label": "Monitoring and feedback",
                "type": "textarea",
            },
            {
                "name": "crew_plan",
                "label": "PF/PM and communication plan",
                "type": "textarea",
                "placeholder": "Optional in this written test.",
            },
        ],
    }
    return {
        "key": key,
        "model": prompted.model,
        "title": prompted.area,
        "prompt": prompted.prompt,
        "why_it_matters": prompted.safety_effect,
        "fields": fields_by_key[key],
    }


def _baseline_summary(baseline: Any) -> dict[str, Any]:
    return {
        "case_id": baseline.case_id,
        "flight_number": baseline.flight_number,
        "flight_date": baseline.flight_date,
        "aircraft": baseline.aircraft_type,
        "registration": baseline.registration,
        "route": f"{baseline.departure}–{baseline.destination}",
        "anchor": {
            "waypoint": baseline.anchor.waypoint,
            "actm": baseline.anchor.actm,
            "utc": baseline.anchor.utc,
            "phase": baseline.anchor.flight_phase,
        },
        "source_snapshot_id": baseline.source_snapshot_id,
        "source_document": baseline.source_document,
        "assumptions": list(baseline.assumptions),
    }


def _option_cards(result: Any) -> list[dict[str, Any]]:
    if not result.decision_structure:
        return []
    cards: list[dict[str, Any]] = []
    candidates = {
        item.icao: item for item in (result.baseline.candidates if result.baseline else ())
    }
    for option in result.decision_structure.options:
        candidate = candidates.get(option.option_id)
        weather = candidate.weather if candidate else None
        cards.append(
            {
                "id": option.option_id,
                "label": option.label,
                "state": option.state.value,
                "distance_nm": candidate.distance_nm if candidate else None,
                "diversion_time": candidate.diversion_time if candidate else None,
                "planned_level": candidate.planned_level if candidate else None,
                "weather": _enum_json(weather) if weather else None,
                "conditions": list(option.conditions),
                "residual_risks": list(option.residual_risks),
            }
        )
    return cards


def _build_session_snapshot(session_id: str) -> dict[str, Any]:
    session = store.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    if session["mode"] == "teach_helpyou":
        return {
            "session": session,
            "phase": "teach_helpyou",
            "question": None,
            "baseline": None,
            "options": [],
            "teaching_plan": None,
            "cbta": [],
            "memory": store.list_memories(session_id),
            "messages": store.list_messages(session_id),
            "audit": {
                "authoritative_answer_generated": False,
                "note": "Pilot contribution mode does not convert experience into operational authority.",
            },
        }

    baseline = load_baseline(SQ23_FIXTURE)
    reasoning = _reasoning_from_mapping(session.get("reasoning"))
    result = run(
        OrchestrationRequest(
            route=TaskRoute.CFP_GROUNDED_SCENARIO,
            baseline=baseline,
            reasoning=reasoning,
            developmental_review_requested=True,
        )
    )
    if result.memory_candidate:
        memory = result.memory_candidate
        store.upsert_memory(
            session_id,
            record_type=memory.record_type.value,
            raw_pilot_wording=memory.raw_pilot_wording,
            ai_interpretation=memory.ai_interpretation,
            evidence_status=memory.evidence_status.value,
            privacy_scope="private",
            context=memory.context,
        )
    status = "complete" if result.phase == "ready_to_teach" else "active"
    store.update_reasoning(session_id, session.get("reasoning", {}), status=status)
    return {
        "session": store.get_session(session_id),
        "phase": result.phase,
        "question": _question_for_result(result),
        "baseline": _baseline_summary(baseline),
        "options": _option_cards(result),
        "decision_structure": _enum_json(result.decision_structure),
        "teaching_plan": _enum_json(result.teaching_plan),
        "cognitive_observations": _enum_json(result.cognitive_observations),
        "cbta": _enum_json(result.cbta_observations),
        "memory": store.list_memories(session_id),
        "messages": store.list_messages(session_id),
        "audit": _enum_json(result.audit),
    }


def _validate_sq23_scenario(text: str) -> None:
    lowered = text.casefold()
    forbidden = [term for term in FORBIDDEN_SQ23_MUTATIONS if term in lowered]
    if forbidden:
        raise HTTPException(
            status_code=422,
            detail=(
                "The SQ23 golden case is fixed as stable OEI. Start a separate future case for "
                + ", ".join(forbidden)
                + "."
            ),
        )


@app.get("/", response_class=HTMLResponse)
def index(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "title": "PilotDriven Helpyou Test Bed",
            "flight_briefing_name": PUBLIC_PRODUCT_NAME,
            "sessions": store.list_sessions(),
            "default_scenario": SQ23_SCENARIO,
        },
    )


@app.get("/healthz")
def health() -> JSONResponse:
    return JSONResponse({"status": "ok", "version": "0.1.0"})


@app.get("/api/cases")
def cases() -> JSONResponse:
    baseline = load_baseline(SQ23_FIXTURE)
    return JSONResponse(
        {
            "cases": [
                {
                    "case_id": SQ23_CASE_ID,
                    "label": "SQ23 stable OEI at ETP1-1D",
                    "flight": f"{baseline.flight_number} {baseline.departure}–{baseline.destination}",
                    "aircraft": f"{baseline.aircraft_type} {baseline.registration}",
                    "anchor": f"{baseline.anchor.waypoint} | ACTM {baseline.anchor.actm} | {baseline.anchor.utc}",
                    "scenario": SQ23_SCENARIO,
                    "source_snapshot_id": baseline.source_snapshot_id,
                }
            ]
        }
    )


@app.get("/api/sessions")
def sessions() -> JSONResponse:
    return JSONResponse({"sessions": store.list_sessions()})


@app.post("/api/sessions", status_code=201)
def create_session(payload: SessionCreate) -> JSONResponse:
    case_id = payload.case_id
    if payload.mode == "flight_scenario":
        if case_id not in {None, SQ23_CASE_ID}:
            raise HTTPException(status_code=404, detail="Unknown Flight Briefing test case")
        case_id = SQ23_CASE_ID
        _validate_sq23_scenario(payload.scenario)
    else:
        case_id = None
    session_id = store.create_session(
        mode=payload.mode,
        case_id=case_id,
        scenario=payload.scenario.strip(),
    )
    if payload.mode == "flight_scenario":
        store.add_message(
            session_id,
            role="system",
            kind="scenario",
            content=(
                "Flight Briefing baseline loaded. The options are initially unranked. "
                "Explain your decision; Helpyou will ask one material question at a time."
            ),
        )
    else:
        store.add_message(
            session_id,
            role="system",
            kind="teaching",
            content=(
                "Teach Helpyou using your own words. The contribution remains private and "
                "non-authoritative unless independently supported by a current applicable source."
            ),
        )
    return JSONResponse(_build_session_snapshot(session_id), status_code=201)


@app.get("/api/sessions/{session_id}")
def get_session(session_id: str) -> JSONResponse:
    return JSONResponse(_build_session_snapshot(session_id))


@app.post("/api/sessions/{session_id}/answer")
def answer(session_id: str, payload: AnswerSubmit) -> JSONResponse:
    session = store.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    if session["mode"] != "flight_scenario":
        raise HTTPException(status_code=409, detail="This session is not a scenario discussion")
    current = _build_session_snapshot(session_id)
    question = current.get("question")
    if not question or question["key"] != payload.question_key:
        raise HTTPException(
            status_code=409,
            detail="The submitted answer does not match the current question",
        )
    try:
        reasoning = _apply_answer(
            session.get("reasoning", {}), payload.question_key, payload.values
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    store.update_reasoning(session_id, reasoning)
    human_text = "\n".join(
        str(value).strip()
        for value in payload.values.values()
        if str(value).strip()
    )
    store.add_message(
        session_id,
        role="pilot",
        kind=payload.question_key,
        content=human_text,
        metadata={"question": question["prompt"]},
    )
    snapshot = _build_session_snapshot(session_id)
    next_question = snapshot.get("question")
    if next_question:
        store.add_message(
            session_id,
            role="helpyou",
            kind="facilitator_question",
            content=next_question["prompt"],
            metadata={
                "question_key": next_question["key"],
                "model": next_question["model"],
            },
        )
    elif snapshot.get("teaching_plan"):
        plan = snapshot["teaching_plan"]
        store.add_message(
            session_id,
            role="helpyou",
            kind="teaching_answer",
            content=f"{plan['headline']}\n{plan['answer']}",
            metadata={"status": plan["status"]},
        )
    return JSONResponse(_build_session_snapshot(session_id))


@app.post("/api/sessions/{session_id}/teach")
def teach(session_id: str, payload: TeachSubmit) -> JSONResponse:
    session = store.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    context = payload.context.strip()
    interpretation = (
        f"Pilot contribution classified as {payload.record_type.replace('_', ' ')}. "
        + (f"Context supplied: {context}. " if context else "No additional context was supplied. ")
        + "This record is not operational authority without independent source verification."
    )
    memory_id = store.upsert_memory(
        session_id,
        record_type=payload.record_type,
        raw_pilot_wording=payload.raw_pilot_wording.strip(),
        ai_interpretation=interpretation,
        evidence_status="pilot_reported",
        privacy_scope=payload.privacy_scope,
        context={"context": context, "case_id": session.get("case_id")},
    )
    store.add_message(
        session_id,
        role="pilot",
        kind="teach_helpyou",
        content=payload.raw_pilot_wording,
        metadata={"record_type": payload.record_type},
    )
    return JSONResponse({"memory_id": memory_id, **_build_session_snapshot(session_id)})


@app.post("/api/sessions/{session_id}/message")
def add_free_message(session_id: str, payload: MessageSubmit) -> JSONResponse:
    if store.get_session(session_id) is None:
        raise HTTPException(status_code=404, detail="Session not found")
    store.add_message(
        session_id,
        role="pilot",
        kind="free_discussion_note",
        content=payload.content,
    )
    return JSONResponse(_build_session_snapshot(session_id))


@app.post("/api/sessions/{session_id}/reset")
def reset(session_id: str) -> JSONResponse:
    try:
        store.reset_session(session_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return JSONResponse(_build_session_snapshot(session_id))


@app.delete("/api/sessions/{session_id}/memories/{memory_id}")
def delete_memory(session_id: str, memory_id: int) -> JSONResponse:
    try:
        store.delete_memory(session_id, memory_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return JSONResponse(_build_session_snapshot(session_id))


@app.get("/api/sessions/{session_id}/export")
def export_session(session_id: str) -> Response:
    try:
        payload = store.export_session(session_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    body = json.dumps(payload, ensure_ascii=False, indent=2)
    return Response(
        body,
        media_type="application/json",
        headers={
            "Content-Disposition": f'attachment; filename="helpyou-session-{session_id}.json"'
        },
    )

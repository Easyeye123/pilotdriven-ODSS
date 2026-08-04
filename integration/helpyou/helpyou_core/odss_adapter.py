"""Adapter for immutable ODSS scenario baselines.

The adapter validates and normalizes an existing ODSS result. It does not parse a
Lido CFP and does not recalculate weather, NOTAM, EDTO, ACTM, performance or
terrain findings.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from .contracts import (
    AerodromeCandidate,
    Citation,
    CoreInvariantError,
    EvidenceItem,
    EvidenceStatus,
    FlightBaseline,
    OptionState,
    ScenarioAnchor,
    WeatherState,
    tuple_of_strings,
)
from .evidence_guard import validate_odss_baseline


def _citation(data: Mapping[str, Any]) -> Citation:
    return Citation(
        owner=str(data["owner"]),
        document=str(data["document"]),
        revision=data.get("revision"),
        eff=data.get("eff"),
        section=data.get("section"),
        page=data.get("page"),
        applicability=data.get("applicability"),
        source_id=data.get("source_id"),
    )


def _state(value: str | None) -> OptionState:
    if value is None:
        return OptionState.UNRESOLVED
    try:
        return OptionState(value)
    except ValueError as exc:
        raise CoreInvariantError(f"Unknown option state: {value}") from exc


def _evidence(data: Mapping[str, Any]) -> EvidenceItem:
    return EvidenceItem(
        claim_id=str(data["claim_id"]),
        claim=str(data["claim"]),
        status=EvidenceStatus(str(data["status"])),
        citations=tuple(_citation(item) for item in data.get("citations", ())),
        applicable=bool(data.get("applicable", True)),
        current=bool(data.get("current", True)),
        support_verified=bool(data.get("support_verified", False)),
        assumptions=tuple_of_strings(data.get("assumptions")),
    )


def _weather(data: Mapping[str, Any] | None) -> WeatherState | None:
    if not data:
        return None
    return WeatherState(
        airport=str(data["airport"]),
        projected_arrival_utc=str(data["projected_arrival_utc"]),
        source_period=str(data["source_period"]),
        summary=str(data["summary"]),
        assessment=_state(data.get("assessment")),
        limitations=tuple_of_strings(data.get("limitations")),
        citations=tuple(_citation(item) for item in data.get("citations", ())),
    )


def _candidate(data: Mapping[str, Any]) -> AerodromeCandidate:
    return AerodromeCandidate(
        icao=str(data["icao"]),
        role=str(data.get("role", "candidate")),
        diversion_time=data.get("diversion_time"),
        distance_nm=int(data["distance_nm"]) if data.get("distance_nm") is not None else None,
        planned_level=int(data["planned_level"]) if data.get("planned_level") is not None else None,
        weather=_weather(data.get("weather")),
        odss_suitability=_state(data.get("odss_suitability")),
        hard_constraint_failures=tuple_of_strings(data.get("hard_constraint_failures")),
        conditions=tuple_of_strings(data.get("conditions")),
        residual_risks=tuple_of_strings(data.get("residual_risks")),
        citations=tuple(_citation(item) for item in data.get("citations", ())),
    )


def baseline_from_mapping(data: Mapping[str, Any]) -> FlightBaseline:
    anchor_data = data.get("anchor") or {}
    anchor = ScenarioAnchor(
        waypoint=anchor_data.get("waypoint"),
        actm=anchor_data.get("actm"),
        utc=anchor_data.get("utc"),
        flight_phase=anchor_data.get("flight_phase"),
        latitude=float(anchor_data["latitude"]) if anchor_data.get("latitude") is not None else None,
        longitude=float(anchor_data["longitude"]) if anchor_data.get("longitude") is not None else None,
    )
    baseline = FlightBaseline(
        case_id=str(data["case_id"]),
        flight_number=str(data["flight_number"]),
        flight_date=str(data["flight_date"]),
        aircraft_type=str(data["aircraft_type"]),
        registration=str(data.get("registration", "")),
        departure=str(data["departure"]),
        destination=str(data["destination"]),
        scheduled_departure_utc=str(data["scheduled_departure_utc"]),
        scheduled_arrival_utc=str(data["scheduled_arrival_utc"]),
        source_snapshot_id=str(data["source_snapshot_id"]),
        source_document=str(data["source_document"]),
        anchor=anchor,
        candidates=tuple(_candidate(item) for item in data.get("candidates", ())),
        evidence=tuple(_evidence(item) for item in data.get("evidence", ())),
        assumptions=tuple_of_strings(data.get("assumptions")),
        odss_complete=bool(data.get("odss_complete", False)),
    )
    validate_odss_baseline(baseline)
    return baseline


def load_baseline(path: str | Path) -> FlightBaseline:
    file_path = Path(path)
    with file_path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise CoreInvariantError("ODSS fixture root must be a JSON object.")
    return baseline_from_mapping(data)

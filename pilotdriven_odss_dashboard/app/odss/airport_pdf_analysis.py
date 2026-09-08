"""Flight-specific airport consequences for the concise PDF publication.

Raw NOTAM text is input to bounded scope recognition only. It is never an
output field. Unresolved clauses are collected for the single closing review
record, and never acquire a guessed runway, active time or map position.
The existing dashboard's airport cards and raw disclosures are unchanged.
"""
from __future__ import annotations

from collections import OrderedDict
from datetime import datetime
import re
from typing import Any


_SURFACE = re.compile(r"\b(?:RWY|RUNWAY)\s*((?:0[1-9]|[12]\d|3[0-6])[LCR]?(?:\s*/\s*(?:0[1-9]|[12]\d|3[0-6])[LCR]?)?)", re.I)
_TWY = re.compile(r"\b(?:TWY|TAXIWAY|TXL|TAXILANE)\s+([A-Z](?:\d{1,2}[A-Z]?)?)(?=\b)", re.I)
_KINDS = {"airport_closure", "runway_closure", "runway_approach_restriction", "taxiway_closure", "approach_navaid_closure"}


def _time(value: Any) -> datetime | None:
    try:
        result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return result if result.tzinfo else None
    except (ValueError, TypeError):
        return None


def _clock(value: Any) -> str:
    parsed = _time(value)
    return parsed.strftime("%d %b %H%MZ").upper() if parsed else "time not held"


def _timing(record: dict[str, Any], role: str) -> tuple[str | None, str]:
    """Use this role's assessment rather than an airport-wide interval union."""
    assessed = next((r for r in record.get("role_applicability") or [] if r.get("role") == role), record)
    state = assessed.get("stateAtReference")
    reference = assessed.get("referenceAt") or record.get("referenceAt")
    name = "departure" if role == "departure" else "arrival" if role == "destination" else "alternate reference"
    if not _time(reference):
        return None, "unresolved reference time"
    if assessed.get("applicability") == "review" or state == "unknown_at_reference":
        return None, "unresolved applicability"
    if state == "ended_before_reference":
        return None, "ended"
    if state == "active_at_reference":
        return f"at {name} {_clock(reference)}", "active"
    if state == "begins_after_reference":
        start, anchor = _time(record.get("valid_from_utc")), _time(reference)
        if start and anchor and start >= anchor:
            minutes = int((start - anchor).total_seconds() // 60)
            return f"begins {minutes} min after {name} {_clock(reference)}; actual taxi timing determines exposure", "scheduled"
    if state == "outside_schedule_at_reference":
        return f"outside the active schedule at {name} {_clock(reference)}, but overlaps the checked window", "scheduled"
    return None, "unresolved reference time"


def analyse_airport_for_pdf(panel: dict[str, Any], *, role: str, planned_runway: Any) -> dict[str, Any]:
    """Group equal consequences, retaining every contributing inline ID."""
    planned = str(planned_runway or "").strip().upper()
    groups: OrderedDict[tuple[str, str, str], dict[str, Any]] = OrderedDict()
    unresolved = []
    excluded = []
    source_ids = []
    for notice in panel.get("selected_notams") or []:
        notice_id = str(notice.get("notam_id") or "").strip()
        if not notice_id:
            continue
        source_ids.append(notice_id)
        kind = str(notice.get("pertinence_kind") or "")
        if kind not in _KINDS and notice.get("approach_affected") is not True:
            excluded.append(notice_id)
            continue
        # The shared dashboard already resolves explicit dated runway regimes
        # inside complex supplements. Reuse that analysis, never its generic
        # summary/raw fallback, even when other clauses remain unresolved.
        from .briefing import _compact_runway_schedule_text
        assessed = next((r for r in notice.get("role_applicability") or [] if r.get("role") == role), notice)
        schedule_line = _compact_runway_schedule_text(
            notice, role=role, planned_runways=set(planned.split("/")) - {""},
            reference_time=_time(assessed.get("referenceAt") or notice.get("referenceAt")),
        )
        if schedule_line:
            groups[("runway", schedule_line, "scheduled")] = {
                "family": "runway", "consequence": schedule_line,
                "state": "scheduled", "timing": "dated planned-runway schedule",
                "notam_ids": [notice_id], "source_pages": [notice.get("source_page")],
            }
            # Other unresolved clauses retain their single closing receipt.
            if assessed.get("applicability") == "review":
                unresolved.append(notice_id)
            continue
        timing, state = _timing(notice, role)
        if state == "ended":
            continue
        if timing is None:
            unresolved.append(notice_id)
            continue
        # This never prints the matched raw clause. Only identifiers and the
        # classifier's bounded result enter a consequence template.
        raw = str(notice.get("item_e_text") or "")
        runways = list(dict.fromkeys(m.replace(" ", "").upper() for m in _SURFACE.findall(raw)))
        if notice.get("approach_affected") or kind == "approach_navaid_closure":
            from .pilot_briefing import _bound_unavailable, _APPROACH_SYSTEM
            # The dashboard's approach flag also admits signal interference.
            # It cannot, by itself, establish a component outage.
            if not _bound_unavailable(raw.upper(), _APPROACH_SYSTEM):
                unresolved.append(notice_id)
                continue
            component = re.search(r"\b(ILS|DME|VOR|LOC|GP|GS|NDB|GLS)(?:[ -]+PART)\b", raw, re.I)
            systems = [aid for aid in dict.fromkeys(re.findall(r"\b(?:ILS|DME|VOR|LOC|GP|GS|NDB|GLS)\b", raw.upper()))
                       if _bound_unavailable(raw.upper(), re.escape(aid))]
            subject = component.group(1).upper() if component else "/".join(systems)
            if not subject:
                unresolved.append(notice_id)
                continue
            scope = "RWY " + ", ".join(runways) if runways else "published approach aid"
            planned_relation = f"; this concerns planned RWY {planned}" if planned and any(planned in r.split("/") for r in runways) else f"; the notice names a different runway from planned {planned}" if planned and runways else "; planned-runway procedure applicability is not established"
            consequence = f"{subject} unavailable for {scope} {timing}{planned_relation}."
            family = "approach"
        elif kind == "airport_closure":
            consequence = f"Airport use is restricted {timing}; the planned movement depends on reopening."
            family = "runway"
        elif kind == "taxiway_closure":
            taxiways = list(dict.fromkeys(_TWY.findall(raw.upper())))
            if not taxiways:
                unresolved.append(notice_id)
                continue
            # An entity-only record cannot establish the extent of a partial
            # closure. State the routing effect without colouring a whole way.
            consequence = f"Taxi access involving {', '.join(taxiways)} is constrained {timing}."
            family = "taxiway"
        elif runways:
            runway_label = "RWY " + ", ".join(runways)
            civil = bool(re.search(r"\b(?:NOT\s+AVBL|NOT\s+AVAILABLE)\s+(?:FOR\s+)?CIV(?:IL)?\s+USE\b", raw, re.I))
            closed = kind == "runway_closure"
            if civil:
                operation = "not available for civil use"
            elif closed:
                operation = "closed to the affected movement"
            else:
                # No general paraphrase of an unrecognised operational rule.
                unresolved.append(notice_id)
                continue
            matches = bool(planned and any(planned in r.split("/") for r in runways))
            relation = f"planned RWY {planned} is affected" if matches else f"this does not close planned RWY {planned}; other notices still apply" if planned else "the planned runway is not held"
            if timing.startswith("begins"):
                consequence = f"{runway_label} closure {timing}; {relation}."
            else:
                consequence = f"{runway_label} {operation} {timing}; {relation}."
            family = "runway"
        else:
            unresolved.append(notice_id)
            continue
        key = (family, consequence, state)
        row = groups.setdefault(key, {"family": family, "consequence": consequence, "state": state, "timing": timing, "notam_ids": [], "source_pages": []})
        if family == "taxiway":
            row["entities"] = taxiways
        if family == "approach":
            row["aid"] = subject
            row["scope"] = scope
            row["planned_match"] = bool(planned and any(planned in r.split("/") for r in runways))
        if notice_id not in row["notam_ids"]:
            row["notam_ids"].append(notice_id)
        if notice.get("source_page") is not None and notice["source_page"] not in row["source_pages"]:
            row["source_pages"].append(notice["source_page"])
    lines = []
    taxi_groups = OrderedDict()
    approach_groups = OrderedDict()
    for row in groups.values():
        if row["family"] == "approach":
            combined = approach_groups.setdefault((row["timing"], row["state"]), {"family": "approach", "state": row["state"], "timing": row["timing"], "segments": [], "notam_ids": [], "source_pages": [], "planned_match": False})
            combined["segments"].append(f"{row['scope']} {row['aid']} ({', '.join(row['notam_ids'])})")
            combined["notam_ids"].extend(row["notam_ids"])
            combined["source_pages"].extend(row["source_pages"])
            combined["planned_match"] = combined["planned_match"] or row["planned_match"]
            continue
        if row["family"] != "taxiway":
            lines.append(row)
            continue
        key = (row["timing"], row["state"])
        combined = taxi_groups.setdefault(key, {"family": "taxiway", "state": row["state"], "timing": row["timing"], "segments": [], "notam_ids": [], "source_pages": []})
        combined["segments"].append(f"{', '.join(row['entities'])} ({', '.join(row['notam_ids'])})")
        combined["notam_ids"].extend(row["notam_ids"])
        combined["source_pages"].extend(row["source_pages"])
    for row in lines:
        row["text"] = f"{row['consequence']} ({', '.join(row['notam_ids'])})"
    for row in approach_groups.values():
        relation = f"The affected aids include planned RWY {planned}." if row["planned_match"] else f"Planned RWY {planned} differs from the named affected runway(s)." if planned and all("published approach aid" not in s for s in row["segments"]) else "This component outage does not establish a whole-approach outage."
        prefix = "Approach-aid outage " if row["timing"].startswith("begins") else "Unavailable approach aids "
        row["consequence"] = prefix + row['timing'] + ": " + "; ".join(row["segments"]) + ". " + relation
        row["text"] = row["consequence"]
        lines.append(row)
    for row in taxi_groups.values():
        prefix = "Taxi restriction " if row["timing"].startswith("begins") else "Taxi access is constrained "
        row["consequence"] = prefix + row['timing'] + ": " + "; ".join(row["segments"]) + "."
        row["text"] = row["consequence"]
        lines.append(row)
    return {"icao": panel.get("icao"), "role": role, "planned_runway": planned or None, "lines": lines, "unresolved_ids": unresolved, "supporting_ids": excluded, "selected_ids": source_ids}


def airport_pdf_analysis(flight: dict[str, Any], panels: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [analyse_airport_for_pdf(
        next((p for p in panels if p.get("icao") == flight.get(role)), {"icao": flight.get(role)}),
        role=role, planned_runway=flight.get(f"{role}_runway"),
    ) for role in ("departure", "destination")]


def alternate_pdf_analysis(flight: dict[str, Any], panels: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Constrain alternate consequences to its own role and planned runway."""
    from .briefing import _notam_runway_designators
    result = []
    for alternate in flight.get("alternates") or []:
        panel = next((p for p in panels if p.get("icao") == alternate.get("airport")), {"icao": alternate.get("airport")})
        notices = []
        for notice in panel.get("selected_notams") or []:
            roles = {r.get("role") for r in notice.get("role_applicability") or []} | {notice.get("role")}
            if "destination alternate" not in roles:
                continue
            runways = _notam_runway_designators(notice.get("item_e_text"))
            if not runways or str(alternate.get("runway")) in runways:
                notices.append(notice)
        result.append(analyse_airport_for_pdf({**panel, "selected_notams": notices}, role="destination alternate", planned_runway=alternate.get("runway")))
    return result

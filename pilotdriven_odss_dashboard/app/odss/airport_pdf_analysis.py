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

from .airport_taxi_consequences import taxi_routing_scopes


_SURFACE = re.compile(r"\b(?:RWY|RUNWAY)\s*((?:0[1-9]|[12]\d|3[0-6])[LCR]?(?:\s*/\s*(?:0[1-9]|[12]\d|3[0-6])[LCR]?)?)", re.I)
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


def _complete_runway_closures(raw: str) -> tuple[dict[str, list[str]], bool]:
    """Recognise complete bounded closure clauses, never discard their suffix.

    Unrecognised extent, aircraft limits, exceptions or additional operational
    clauses remain unresolved. Date/time prefixes use the existing role timing
    assessment; only known works/maintenance reasons can be omitted from prose.
    """
    from .notam_restriction_line import strip_publication_envelope

    body = strip_publication_envelope(raw) or raw
    day = r"(?:MON|TUE|WED|THU|FRI|SAT|SUN)"
    month = r"(?:JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)"
    timing_prefix = rf"(?:(?:DAILY|DLY|{day}(?:-{day})?|{month}|[0-9][0-9,/-]*(?:UTC)?)[, ]+)*"
    reason = r"(?:\s+(?:DUE(?:\s+TO)?|FOR)\s+(?:WIP|MAINT(?:ENANCE)?(?:\s+WIP)?|RWY\s+INSPECTION|RUBBER\s+DEPOSIT\s+REMOVAL|RWY\s+MARKING\s+REPAINTING\s+WIP|TIRE\s+TRACK\s+WIPING\s+WORKS|CONST(?:RUCTION)?(?:\s+WORKS)?))?"
    predicates = (
        (r"(?:IS\s+|WILL\s+)?NOT\s+(?:BE\s+)?(?:AVBL|AVAILABLE)\s+(?:FOR\s+)?CIV(?:IL)?\s+USE", "not available for civil use"),
        (r"(?:IS\s+|ARE\s+|WILL\s+BE\s+)?(?:CLSD|CLOSED)", "closed to the affected movement"),
        (r"(?:IS\s+)?NOT\s+(?:AVBL|AVAILABLE)(?:\s+FOR\s+OPS)?", "not available for operations"),
    )
    patterns = [(re.compile(timing_prefix + _SURFACE.pattern + r"\s+" + predicate + reason, re.I), operation)
                for predicate, operation in predicates]
    scopes: dict[str, list[str]] = {}
    unreduced = []
    for clause in filter(None, (part.strip() for part in re.split(r"\.(?=\s|$)|;", body))):
        for pattern, operation in patterns:
            match = pattern.fullmatch(clause)
            if match:
                runway = match.group(1).replace(" ", "").upper()
                if runway not in scopes.setdefault(operation, []):
                    scopes[operation].append(runway)
                break
        else:
            unreduced.append(clause)
    affected = {end for pairs in scopes.values() for pair in pairs for end in pair.split("/")}
    for clause in unreduced:
        # A period does not make a qualifier independent. Keep an affirmative
        # closure only beside clearly independent statements with their own
        # subject and predicate; an ambiguous continuation blocks the claim.
        if re.fullmatch(r"(?:ILS|DME|VOR|LOC|GP|GS|NDB|GLS)\s+" + _SURFACE.pattern
                        + r"\s+(?:U/S|UNSERVICEABLE|UNAVAILABLE|AVAILABLE)", clause, re.I):
            continue
        other_runway_statements = (
            _SURFACE.pattern + r"\s+(?:(?:IS|REMAINS)\s+)?(?:AVBL|AVAILABLE|OPEN|SERVICEABLE)",
            r"ACFT CONCERNED SHALL PLAN\s+" + _SURFACE.pattern + r"\s+FOR TKOF AND LDG OPS",
            r"TAXI VIA TWY [A-Z0-9/-]+ TO\s+" + _SURFACE.pattern,
        )
        independent = False
        for pattern in other_runway_statements:
            match = re.fullmatch(pattern, clause, re.I)
            if match and not affected.intersection(match.group(1).replace(" ", "").upper().split("/")):
                independent = True
                break
        if not independent:
            return {}, True
    return scopes, bool(unreduced)


def _approach_chart_restrictions(raw: str) -> list[tuple[str, str]] | None:
    """Keep each explicitly withdrawn/suspended chart bound to its own title.

    This narrow source grammar is a chart-status statement, not evidence that
    an ILS/VOR facility failed. Unrecognised clauses make the notice unresolved.
    Supporting data tables must match an actual named chart before deduplication.
    """
    pattern = re.compile(
        r"(?P<kind>IAC|AERONAUTICAL DATA TABULATION)\s+[A-Z]+-\d+[A-Z]?\s+"
        r"(?P<title>(?:ILS|VOR|RNAV(?:\s*\(GNSS\))?)(?:\s+[A-Z])?\s+"
        r"RWY\s+(?:0[1-9]|[12]\d|3[0-6])[LCR]?(?:\s+CAT\s+I{1,3})?)\s+"
        r"DATED\s+\d{1,2}\s+[A-Z]{3}\s+\d{4}\s+(?P<state>SUSPENDED|WITHDRAWN)", re.I,
    )
    charts, tables = [], []
    for clause in filter(None, (part.strip() for part in re.split(r"\.(?=\s|$)|;", raw))):
        match = pattern.fullmatch(clause)
        if not match:
            return None
        item = (" ".join(match.group("title").upper().split()), match.group("state").lower())
        target = charts if match.group("kind").upper() == "IAC" else tables
        if item not in target:
            target.append(item)
    if not charts or any(item not in charts for item in tables):
        return None
    return charts


def analyse_airport_for_pdf(panel: dict[str, Any], *, role: str, planned_runway: Any, route_text: str | None = None) -> dict[str, Any]:
    """Group equal consequences, retaining every contributing inline ID."""
    planned = str(planned_runway or "").strip().upper()
    groups: OrderedDict[tuple[str, str, str], dict[str, Any]] = OrderedDict()
    unresolved = []
    excluded = []
    source_ids = []
    surface_effects = []
    for notice in panel.get("selected_notams") or []:
        notice_id = str(notice.get("notam_id") or "").strip()
        if not notice_id:
            continue
        source_ids.append(notice_id)
        # A notice explicitly limited to departures on one named ATS route
        # must not create an unresolved arrival/other-route release condition.
        # The raw dashboard record remains available under its existing rules.
        departure_scope = re.match(r"^\s*FLIGHTS DEPARTING ([A-Z]{4}) ON ATS ROUTE ([A-Z]\d+)\s*:", str(notice.get("item_e_text") or ""), re.I)
        if departure_scope and departure_scope.group(1).upper() == str(panel.get("icao") or "").upper():
            route = departure_scope.group(2).upper()
            if role != "departure" or (route_text and not re.search(r"\b" + re.escape(route) + r"\b", route_text.upper())):
                excluded.append(notice_id)
                continue
        kind = str(notice.get("pertinence_kind") or "")
        if kind not in _KINDS and notice.get("approach_affected") is not True:
            excluded.append(notice_id)
            continue
        # The shared dashboard already resolves explicit dated runway regimes
        # inside complex supplements. Reuse that analysis, never its generic
        # summary/raw fallback, even when other clauses remain unresolved.
        from .briefing import _runway_schedule_at_reference
        assessed = next((r for r in notice.get("role_applicability") or [] if r.get("role") == role), notice)
        raw = str(notice.get("item_e_text") or "")
        runways = list(dict.fromkeys(m.replace(" ", "").upper() for m in _SURFACE.findall(raw)))
        has_schedule = False
        # Other runway closures affect the available options for this flight.
        # Reuse the existing date/weekday/time evaluator for each source-named
        # pair, while keeping the actual planned runway explicit.
        for runway in runways:
            schedule = _runway_schedule_at_reference(
                notice, role=role, planned_runways=set(runway.split("/")),
                reference_time=_time(assessed.get("referenceAt") or notice.get("referenceAt")),
            )
            if not schedule:
                continue
            schedule_line = schedule["text"]
            surface_effects.append({**schedule, "notam_id": notice_id, "markClass": "closure", "scope": "whole_entity"})
            if planned and not set(planned.split("/")) & set(runway.split("/")):
                schedule_line += f" Planned RWY {planned} differs from this affected runway."
            groups[("runway", schedule_line, "scheduled")] = {
                "family": "runway", "consequence": schedule_line,
                "state": "scheduled", "timing": "dated runway schedule",
                "notam_ids": [notice_id], "source_pages": [notice.get("source_page")],
            }
            has_schedule = True
        if has_schedule:
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
        # A chart's suspension is not a physical aid outage. Keep title/runway
        # tuples local to their source clauses, before any equipment grouping.
        if re.search(r"\b(?:IAC|AERONAUTICAL DATA TABULATION)\b", raw, re.I):
            charts = _approach_chart_restrictions(raw)
            if not charts:
                unresolved.append(notice_id)
                continue
            by_state: OrderedDict[str, list[str]] = OrderedDict()
            for title, chart_state in charts:
                by_state.setdefault(chart_state, []).append(title)
            for chart_state, titles in by_state.items():
                consequence = f"Published approach charts {chart_state} {timing}: " + "; ".join(titles) + "."
                key = ("approach_chart", consequence, state)
                row = groups.setdefault(key, {"family": "approach_chart", "consequence": consequence,
                                               "state": state, "timing": timing, "notam_ids": [], "source_pages": []})
                if notice_id not in row["notam_ids"]:
                    row["notam_ids"].append(notice_id)
                if notice.get("source_page") is not None and notice["source_page"] not in row["source_pages"]:
                    row["source_pages"].append(notice["source_page"])
            continue
        # This never prints the matched raw clause. Only identifiers and the
        # classifier's bounded result enter a consequence template.
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
            component_name = component.group(1).upper() if component else None
            subject = component_name if component_name in systems else "/".join(systems)
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
            taxiways = taxi_routing_scopes(raw)
            if not taxiways:
                unresolved.append(notice_id)
                continue
            # An entity-only record cannot establish the extent of a partial
            # closure. State the routing effect without colouring a whole way.
            consequence = f"Taxi access involving {', '.join(taxiways)} is constrained {timing}."
            family = "taxiway"
        elif runways:
            scopes, has_unresolved_clause = _complete_runway_closures(raw)
            if has_unresolved_clause or not scopes:
                unresolved.append(notice_id)
            for operation, affected_runways in scopes.items():
                # This path publishes only complete recognised source clauses.
                # Other clauses retain their closing receipt even when this
                # notice also contains a valid, independent runway closure.
                if operation == "not available for civil use":
                    surface_effects.append({"runways": sorted({end for pair in affected_runways for end in pair.split("/")}),
                                            "notam_id": notice_id, "markClass": "closure", "scope": "whole_entity",
                                            "stateAtReference": assessed.get("stateAtReference"),
                                            "referenceAt": assessed.get("referenceAt") or notice.get("referenceAt")})
                matches = bool(planned and any(planned in r.split("/") for r in affected_runways))
                relation = f"planned RWY {planned} is affected" if matches else f"this does not close planned RWY {planned}; other notices still apply" if planned else "the planned runway is not held"
                runway_label = "RWY " + ", ".join(affected_runways)
                future_operation = operation.replace("not available", "unavailable")
                consequence = (f"{runway_label} will be {future_operation}; restriction {timing}; {relation}." if timing.startswith("begins")
                               else f"{runway_label} {operation} {timing}; {relation}.")
                key = ("runway", consequence, state)
                row = groups.setdefault(key, {"family": "runway", "consequence": consequence,
                                               "state": state, "timing": timing, "notam_ids": [], "source_pages": []})
                if notice_id not in row["notam_ids"]:
                    row["notam_ids"].append(notice_id)
                if notice.get("source_page") is not None and notice["source_page"] not in row["source_pages"]:
                    row["source_pages"].append(notice["source_page"])
            continue
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
    return {"icao": panel.get("icao"), "role": role, "planned_runway": planned or None, "lines": lines,
            "surface_effects": surface_effects, "unresolved_ids": unresolved, "supporting_ids": excluded, "selected_ids": source_ids}


def airport_pdf_analysis(flight: dict[str, Any], panels: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [analyse_airport_for_pdf(
        next((p for p in panels if p.get("icao") == flight.get(role)), {"icao": flight.get(role)}),
        role=role, planned_runway=flight.get(f"{role}_runway"), route_text=flight.get("route_text"),
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
        result.append(analyse_airport_for_pdf({**panel, "selected_notams": notices}, role="destination alternate", planned_runway=alternate.get("runway"), route_text=flight.get("route_text")))
    return result

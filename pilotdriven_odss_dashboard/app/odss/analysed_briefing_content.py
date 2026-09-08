"""Flight-specific publication of held calculations and source constraints.

This projection never supplies missing weather, aircraft limits or a release
decision. Source quotations stay in the app. Rules identify only consequences
supported by a declaration; an unresolved manual constraint stays open.
"""
from __future__ import annotations

import math
import re

from .report_facts import operational_reference_times
from .vaa import _utc


def clean(value) -> str:
    return " ".join(str(value or "").split())


def flight_window(flight):
    return operational_reference_times(flight)


def window_label(flight) -> str:
    start, end = flight_window(flight)
    if start and end:
        return f"{start:%d%b %H%MZ}-{end:%d%b %H%MZ}".upper()
    return "the unresolved flight UTC window"


def level_profile_label(flight) -> str:
    tokens = clean(flight.get("planned_level_profile")).split("/")
    if len(tokens) < 2 or len(tokens) % 2 or any(not re.fullmatch(r"\d{3}", tokens[i]) for i in range(1, len(tokens), 2)):
        return "Level profile not held"
    return " / ".join(f"{tokens[i]} FL{tokens[i + 1]}" for i in range(0, len(tokens), 2))


def cyclone_content(flight):
    """Use the existing time-matched track screening, never movement alone."""
    review = flight.get("tropical_cyclone_review") or {}
    track = flight.get("tropical_cyclone_track_review") or review.get("track_context") or {}
    start, end = flight_window(flight)
    lines, markers = [], []
    for cyclone in track.get("cyclones") or []:
        closest = cyclone.get("closest_route_screening") or {}
        when = _utc(closest.get("time_utc"))
        distance = closest.get("distance_nm")
        position = closest.get("cyclone_centre_position") or {}
        if not (start and end and when and start <= when <= end
                and isinstance(distance, (int, float)) and math.isfinite(distance) and distance >= 0):
            continue
        name = clean(cyclone.get("name")) or "Named cyclone"
        leg = "-".join(filter(None, [clean(closest.get("route_from")), clean(closest.get("route_to"))]))
        lines.append(f"{name}: centre about {distance:.0f} NM from {leg or 'the timed route'} at {when:%d%b %H%MZ}. Interpolated official-position screening; this distance is not a wind-field clearance.")
        if (all(isinstance(position.get(k), (int, float)) and math.isfinite(position[k]) for k in ("latitude", "longitude"))
                and abs(position["latitude"]) <= 90 and abs(position["longitude"]) <= 180):
            markers.append({"kind": "TC", "label": name, "position": position, "time_utc": closest["time_utc"], "distance_nm": distance})
    if not lines:
        lines = [f"No time-matched cyclone centre-distance result is held for {window_label(flight)}. Later live tracks cannot establish cyclone conditions for this flight."]
    return {"lines": lines, "markers": markers, "time_matched": bool(markers)}


def deferred_consequence_rows(view):
    """Bind practical consequences to typed source segments, not MEL numbers.

    A reference number never determines an effect. Only explicit, non-negated
    source constraints activate the narrow rules below. Unknown effects are
    named and sent to the closing record instead of inventing a procedure.
    """
    rows = []
    for gate in view.get("deferred_dispatch_gates") or []:
        sources = gate.get("source_segments") or []
        title = clean(gate.get("title"))
        # Titles from unresolved declarations may contain an old UI warning.
        title = re.sub(r"\s*REVIEW REQUIRED\s*", "", title, flags=re.I).strip() or "Deferred item"
        effects = []
        subjects = []
        for source in sources:
            description = clean(source.get("description"))
            raw = clean(source.get("source_text") or " ".join((description, clean(source.get("restriction"))))).upper()
            if not raw:
                continue
            subject = re.sub(r"^(?:MAINT ENTRY\s*:?\s*|WAC FOUND\s*)+", "", description, flags=re.I).strip(" :")
            if subject:
                subjects.append(subject)
            # Explicit uplift is a catering action, never an inferred MEL
            # allowance, dry-ice quantity or aircraft dispatch approval.
            if re.search(r"\b(?:UPLIFT(?:ED)?\s+DRY[- ]?ICE|DRY[- ]?ICE\s+(?:NEEDS TO BE UPLIFTED|REQ(?:UIRED)?))\b", raw) and not re.search(r"\b(?:NO|NOT|DO NOT)\s+(?:NEED\s+TO\s+)?UPLIFT\s+DRY[- ]?ICE|DRY[- ]?ICE\s+NOT\s+REQ", raw):
                effects.append("Catering must arrange the source-requested dry-ice uplift before departure; quantity and carriage limits are not established by the defect entry.")
            if re.search(r"\bUPLIFT\s+TRASH\s+BAGS?\b", raw) and not re.search(r"\b(?:NO|NOT|DO NOT)\s+UPLIFT\s+TRASH", raw):
                effects.append("Waste handling needs the source-requested trash bags for the unavailable compactor; the declaration supplies no aircraft performance penalty.")
            if "DO NOT USE LAVATORIES ON GROUND" in raw:
                effects.append("Ground turnaround must avoid using the affected lavatories; the source restriction is specific to ground use.")
            seat = re.search(r"\bSEAT\s+(\d{1,2}[A-K])\b", raw)
            if seat and re.search(r"\bARMREST\b[^.]*\bSTUCK\b", raw) and not re.search(r"\b(?:NOT|NO LONGER)\s+STUCK\b", raw):
                effects.append(f"Seat {seat.group(1)} needs a seating-configuration decision for its stuck armrest before allocation; the declaration does not establish an occupied-seat allowance.")
            if re.search(r"\b(?:CHECKED|INSPECT\w*)\b.*\b(?:PRIOR|BEFORE)\s+(?:TO\s+)?EVERY\s+DEPARTURE\b", raw):
                effects.append("The source makes inspection a condition of every departure; carry that check into this flight's turnaround and operative Tech Log.")
            limit = re.search(r"\bZFW RESTRICTED TO\s+([\d,]+)\s*KGS?\b", raw)
            if limit:
                limit_kg = int(limit.group(1).replace(",", ""))
                mass = ((view.get("fuel_summary") or {}).get("masses_kg") or {}).get("pzfw")
                comparison = f"Planned ZFW {mass:,.0f} kg gives {limit_kg - mass:,.0f} kg margin." if isinstance(mass, (int, float)) else "Planned ZFW is not held for comparison."
                effects.append(f"The declaration limits ZFW to {limit_kg:,.0f} kg. {comparison}")
            if source.get("item_type") == "CDL":
                effects.append("Reconcile this deferred external component with the approved CDL performance allowance for this aircraft; the declaration alone does not quantify a fuel or weight correction.")
        if not effects:
            # Keep an unanalysable defect identifiable, but do not reproduce
            # its prose or invent an airworthiness/dispatch conclusion.
            effects.append("The declaration does not establish the permitted configuration or flight limitation; its exact effect remains open in the closing release record.")
        subject = "; ".join(dict.fromkeys(subjects))
        rows.append({"title": title, "subject": subject, "consequences": list(dict.fromkeys(effects)),
                     "references": gate.get("references") or [], "source_item_indices": gate.get("source_item_indices") or [],
                     "gate_id": gate.get("gate_id")})
    # Several gates can share a single action; publish their identities once.
    grouped = {}
    for row in rows:
        key = tuple(row["consequences"])
        grouped.setdefault(key, []).append(row)
    lines = []
    for consequences, group in grouped.items():
        titles = "; ".join(dict.fromkeys(r["title"] for r in group))
        subjects = list(dict.fromkeys(r["subject"] for r in group if r["subject"]))
        # Subjects only identify an otherwise unassessed item. Supported
        # effects already identify the affected operation (catering, waste,
        # ground lavatories, aircraft performance).
        unresolved = consequences[0].startswith("The declaration does not establish")
        identity = f"{titles}: " + (("; ".join(subjects) + ". ") if unresolved else "")
        lines.append({
            "text": identity + " ".join(consequences),
            "references": list(dict.fromkeys(reference for row in group for reference in row["references"])),
            "source_item_indices": list(dict.fromkeys(index for row in group for index in row["source_item_indices"])),
            "source_gate_ids": list(dict.fromkeys(row["gate_id"] for row in group if row["gate_id"])),
        })
    return lines


def deferred_consequences(view):
    return [row["text"] for row in deferred_consequence_rows(view)]


def release_conditions(flight, view, receipt, airport_analysis, alternate_analysis, extracts):
    """A numbered action list driven by unresolved states of this flight."""
    complete = {"HELD", "FOUND", "CHECKED · NO MATCH", "CHECKED · NO TRIGGER", "NOT APPLICABLE"}
    pending = {r["key"]: r for r in receipt["rows"] if r["state"] not in complete}
    result = []
    weather_keys = {"metar_taf": "METAR/TAF", "sigmet": "SIGMET", "vaa_vaac": "VAA/VAAC", "tropical_cyclone": "TC advisory/SIGMET"}
    missing = [label for key, label in weather_keys.items() if key in pending]
    if missing:
        result.append(f"Obtain {', '.join(missing)} covering {window_label(flight)} on {flight.get('departure', '?')}-{flight.get('destination', '?')}; held coverage does not close that flight window.")
    unresolved_sigmets = [clean(r.get("name")) for r in (view.get("hazards") or {}).get("sigmet_cards") or []
                          if r.get("disposition") == "REVIEW REQUIRED" and "does not intersect the polygon" not in str(r.get("screening") or "")]
    unassessed_ash = [clean(r.get("volcano") or r.get("name")) for r in (view.get("vaa") or {}).get("cfp_advisories") or []
                     if r.get("advisory_kind") == "CFP_VAA_NOTICE"]
    if unresolved_sigmets or unassessed_ash:
        affected = list(dict.fromkeys(filter(None, unresolved_sigmets + unassessed_ash)))
        result.append("Resolve the held advisory applicability for " + ", ".join(affected) + "; source geometry, timing or a route-specific ash assessment is incomplete.")
    cat = [label for key, label in (("wafs_sigwx", "WAFS/SIGWX"), ("airep_pirep", "AIREP/PIREP")) if key in pending]
    if cat:
        vws = (view.get("terrain") or {}).get("vws_review") or {}
        near = clean(vws.get("maximum_waypoint"))
        result.append(f"Complete route-specific {' and '.join(cat)} corroboration" + (f" around {near} (OFP maximum VWS {vws.get('maximum_display')})" if near else "") + "; OFP VWS alone does not establish CAT.")
    declared = view.get("deferred_dispatch_gates") or []
    if declared:
        names = ", ".join(dict.fromkeys(re.sub(r"\s*REVIEW REQUIRED", "", clean(g.get("title"))) for g in declared))
        result.append(f"Confirm {names} against this aircraft's operative Tech Log and applicable procedures; record completion of the actions on page 8.")
    # Keep the source-bound choice and the exact fact needed to resolve it
    # together. A generic Tech Log reminder would lose the candidate boundary.
    candidate_groups = {}
    for extract in extracts:
        if extract.get("match_status") == "candidate":
            candidate_groups.setdefault(extract.get("deferred_entry_id"), []).append(extract)
    for candidates in candidate_groups.values():
        names = ", ".join(dict.fromkeys(f"{e['item_type']} {e['reference']}" for e in candidates))
        conditions = " ".join(dict.fromkeys(
            clean(e.get("ambiguity_reason")) + " " + clean(e.get("confirmation_required"))
            for e in candidates
        ))
        result.append(f"MEL/CDL candidates: {names}; no candidate selected. {conditions}")
    airports = []
    for row in [*airport_analysis, *alternate_analysis]:
        if row.get("unresolved_ids"):
            airports.append(f"{row['icao']} ({len(row['unresolved_ids'])})")
    if airports:
        result.append("Resolve flight-window or scope ambiguities in the app: " + ", ".join(dict.fromkeys(airports)) + "; check the planned movement against current NOTAM/ATIS.")
    missing_geometry = [a["icao"] for a in airport_analysis if not any(o.get("icao") == a["icao"] for o in view.get("surface_overlays") or [])]
    if missing_geometry:
        result.append("Obtain official surface charts for " + ", ".join(missing_geometry) + "; this pack has no validated surface figure for them.")
    if "airport_intelligence" in pending:
        stations = list(dict.fromkeys(a["icao"] for a in airport_analysis))
        result.append("Check current Airport Notes for " + "/".join(stations) + "; their applicable released coverage is incomplete.")
    if "depressurisation_profile" in pending:
        events = (view.get("terrain") or {}).get("events") or []
        legs = [f"{(e.get('first_high') or {}).get('name', '?')}-{(e.get('last_high') or {}).get('name', '?')}" for e in events]
        result.append("Bind the controlled escape/depressurisation profile for " + ", ".join(legs) + "; high MSA does not define an escape procedure.")
    if "edto" in pending:
        stations = list(dict.fromkeys(clean(a.get("airport")) for a in (view.get("edto") or {}).get("airports") or []))
        result.append("Resolve EDTO suitability" + (" for " + "/".join(stations) if stations else " for the held route declaration") + " across the checked periods on page 2.")
    if "enroute_notam" in pending:
        firs = list(dict.fromkeys(clean(w.get("fir_boundary")) for w in flight.get("route_waypoints") or [] if w.get("fir_boundary")))
        result.append("Obtain bounded enroute NOTAM coverage for " + ("/".join(firs) or "the filed route") + "; no complete route-airspace assessment is held.")
    for key in ("ofp_parse", "flight_timing", "fuel_performance", "vws", "airports_alternates", "airport_notam"):
        if key in pending:
            result.append(pending[key]["detail"])
    if not result:
        result = ["No unresolved automated source condition is recorded for this flight; record the crew's operational release separately."]
    return [f"{i}. {line}" for i, line in enumerate(dict.fromkeys(result), 1)]

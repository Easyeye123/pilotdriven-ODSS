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


def deferred_item_label(value, fallback="Deferred item"):
    """Publish a declaration's identity without the app's item-level badge.

    ``build_deferred_dispatch_gates`` falls back to "<TYPE> REVIEW REQUIRED"
    when a declaration cannot be resolved to a subject or a reference. That is
    an in-app review badge, not an analysed statement, and the published
    briefing rejects repeated item-level badges on its analysed pages.
    """
    cleaned = re.sub(r"\s*REVIEW REQUIRED\s*", " ", str(value or ""), flags=re.I)
    return " ".join(cleaned.split()).strip(" -") or fallback


# Abbreviations that carry a vowel and would otherwise read as an English
# word once lowercased. Everything else that has no vowel, carries a digit or
# is a single letter is already recognised as source shorthand.
_SOURCE_ABBREVIATIONS = frozenset({
    "ACARS", "ADIRU", "APU", "ATA", "AUX", "AVOD", "ECAM", "EDTO", "EICAS",
    "ELT", "ETOPS", "FTE", "IATA", "ICAO", "IDG", "IFE", "IRU", "MAF", "NPE",
    "OXY", "PA", "PAX", "VCRU", "WAC",
})
_SOURCE_ENTRY_PREFIX = re.compile(r"^(?:MAINT ENTRY\s*:?\s*|WAC FOUND\s*)+", re.I)
_SENTENCE_START = re.compile(r"(^|[.!?]\s+)([a-z])")


def _readable_word(match: re.Match[str]) -> str:
    """Lower a block-capital source word unless it is source shorthand.

    Punctuation splits the word, so "AFT-MOST" cases as two words while
    "I/B", "D4L" and "FC2161F1FK" keep the shorthand the source wrote.
    """
    word = match.group(0)
    if not word.isupper():
        return word
    if len(word) == 1 or any(character.isdigit() for character in word):
        return word
    if word in _SOURCE_ABBREVIATIONS:
        return word
    if not set("AEIOU") & set(word):
        return word
    return word.lower()


def source_subject_sentence(value) -> str:
    """Publish a declaration's own subject in sentence case, not block capitals.

    David, 9 Sep 2026 21:28: "by copying in blocks and capital is very hard to
    read". His reference briefing still names the defect - "The aft-most
    fan-cowl latch access-panel latch is loose" - so the answer to the block
    capitals is to case them, never to drop the subject: a deferred card that
    does not say what is wrong with the aircraft is not a finding.

    Nothing is added or re-worded: this only changes letter case, and only for
    words the source wrote in full capitals that are not source shorthand.
    """
    subject = clean(value)
    if not subject or subject != subject.upper():
        # A source that already wrote mixed case is readable as it stands;
        # only block capitals are re-cased, and only ever in case.
        return subject
    cased = re.sub(r"[A-Za-z0-9]+", _readable_word, subject)
    return _SENTENCE_START.sub(lambda match: match.group(1) + match.group(2).upper(), cased)


def deferred_subject(value) -> str:
    """The declaration's identification of the defect, made readable."""
    return source_subject_sentence(
        _SOURCE_ENTRY_PREFIX.sub("", clean(value)).strip(" :")
    )


def deferred_consequence_rows(view):
    """Bind practical consequences to typed source segments, not MEL numbers.

    A reference number never determines an effect. Only explicit, non-negated
    source constraints activate the narrow rules below. Unknown effects are
    named and sent to the closing record instead of inventing a procedure.
    """
    rows = []
    for gate in view.get("deferred_dispatch_gates") or []:
        sources = gate.get("source_segments") or []
        # Titles from unresolved declarations may contain an old UI warning.
        title = deferred_item_label(clean(gate.get("title")))
        for source in sources or [{}]:
            # A shared MEL reference can cover different physical defects.
            # Analyse every segment before grouping identical consequences;
            # one recognised action must not hide an unassessed sibling.
            effects = []
            subjects = []
            description = clean(source.get("description"))
            raw = clean(source.get("source_text") or " ".join((description, clean(source.get("restriction"))))).upper()
            subject = deferred_subject(description)
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
            if ("FWD CARGO DOOR CTRL ACCESS PNL NOT FLUSH" in raw
                    and "TO INSPECT HST CONDITION AND REAPPLIED" in raw
                    and not re.search(r"\b(?:DO NOT|NOT TO)\s+INSPECT\b", raw)):
                effects.append("Forward cargo-door control-panel fit needs maintenance acceptance, including the source-requested HST inspection and reapplication; completion and an acceptable panel condition are not established.")
            if ("WASTE CONTAINER DOOR" in raw and "LATCH MISSING" in raw
                    and not re.search(r"\b(?:LATCH (?:IS )?NOT MISSING|NO MISSING LATCH)\b", raw)):
                effects.append("Waste-container door retention needs a permitted-configuration decision for the missing latch; the declaration does not establish an acceptable securing method or permission to use it.")
            seat = re.search(r"\bSEAT\s+(\d{1,2}[A-K])\b", raw)
            if seat and re.search(r"\bARMREST\b[^.]*\bSTUCK\b", raw) and not re.search(r"\b(?:NOT|NO LONGER)\s+STUCK\b", raw):
                effects.append(f"Seat {seat.group(1)} needs a seating-configuration decision for its stuck armrest before allocation; the declaration does not establish an occupied-seat allowance.")
            if re.search(r"\b(?:CHECKED|INSPECT\w*)\b.*\b(?:PRIOR|BEFORE)\s+(?:TO\s+)?EVERY\s+DEPARTURE\b", raw):
                effects.append("The source makes inspection a condition of every departure; carry that check into this flight's turnaround and operative Tech Log.")
            # An interim repair the declaration records is part of the state of
            # the aircraft, not a conclusion about it: publish that it is
            # applied and decline to say how long it stays acceptable.
            if (re.search(r"\bHST\s+(?:IS\s+|HAS\s+BEEN\s+)?(?:RE-?)?APPLIED\b", raw)
                    and not re.search(r"\bHST\b[^.]*\b(?:NOT|NEVER)\s+(?:RE-?)?APPLIED\b", raw)
                    and not any("HST" in effect for effect in effects)):
                effects.append("The declaration records HST applied as an interim condition; it does not establish how long that condition stays acceptable.")
            limit = re.search(r"\bZFW RESTRICTED TO\s+([\d,]+)\s*KGS?\b", raw)
            if limit:
                limit_kg = int(limit.group(1).replace(",", ""))
                mass = ((view.get("fuel_summary") or {}).get("masses_kg") or {}).get("pzfw")
                comparison = f"Planned ZFW {mass:,.0f} kg gives {limit_kg - mass:,.0f} kg margin." if isinstance(mass, (int, float)) else "Planned ZFW is not held for comparison."
                effects.append(f"The declaration limits ZFW to {limit_kg:,.0f} kg. {comparison}")
            if source.get("item_type") == "CDL":
                effects.append("Reconcile this deferred external component with the approved CDL performance allowance for this aircraft; the declaration alone does not quantify a fuel or weight correction.")
            if not effects:
                # Keep an unanalysable defect identifiable, but do not invent
                # an airworthiness/dispatch conclusion.
                effects.append("The declaration does not establish the permitted configuration or flight limitation; its exact effect remains open in the closing release record.")
            subject = "; ".join(dict.fromkeys(subjects))
            indices = ([source["source_item_index"]] if isinstance(source.get("source_item_index"), int)
                       else gate.get("source_item_indices") or [])
            rows.append({"title": title, "subject": subject, "consequences": list(dict.fromkeys(effects)),
                         "references": gate.get("references") or [], "source_item_indices": indices,
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
        # The subject is what is wrong with the aircraft, and it is published
        # whether or not a rule could analyse it. An analysed consequence that
        # does not say what it is a consequence OF is not a finding: David's
        # own reference card names the defect ("The aft-most fan-cowl latch
        # access-panel latch is loose") before it states the condition.
        subject = "; ".join(value.rstrip(" .;") for value in subjects)
        identity = f"{titles}: " + (f"{subject}. " if subject else "")
        lines.append({
            "text": identity + " ".join(consequences),
            # The declaration's own subject, for a caller that lays the card
            # out itself (the ranked decision page) instead of printing
            # ``text``.
            "subject": subject,
            # The analysed sentences on their own, so a caller that already
            # names the item (a ranked decision card) does not repeat it.
            "consequences": list(consequences),
            "references": list(dict.fromkeys(reference for row in group for reference in row["references"])),
            "source_item_indices": list(dict.fromkeys(index for row in group for index in row["source_item_indices"])),
            "source_gate_ids": list(dict.fromkeys(row["gate_id"] for row in group if row["gate_id"])),
        })
    return lines


def deferred_consequences(view):
    return [row["text"] for row in deferred_consequence_rows(view)]


def airport_review_constraints(view, analyses):
    """Name the unresolved conclusion, never publish raw clauses or counts.

    These labels describe gaps in the existing assessment. They do not turn
    an unrecognised clause into a closure or declare a runway available.
    """
    from .airport_pdf_analysis import _SURFACE
    result = []
    for analysis in analyses:
        ids = set(analysis.get("unresolved_ids") or [])
        if not ids:
            continue
        panel = next((p for p in view.get("airport_operational_panels") or [] if p.get("icao") == analysis.get("icao")), {})
        topics = []
        for notice in panel.get("selected_notams") or []:
            if notice.get("notam_id") not in ids:
                continue
            raw = clean(notice.get("item_e_text")).upper()
            runways = list(dict.fromkeys(m.replace(" ", "") for m in _SURFACE.findall(raw)))
            scope = "RWY " + "/".join(dict.fromkeys(r for pair in runways for r in pair.split("/"))) if runways else "planned movement"
            if "RETIL" in raw:
                topic = f"{scope} exit-lighting effect"
            elif re.search(r"\b(?:LOC|LOCALISER|LOCALIZER)\b", raw) and re.search(r"\b(?:INTRP|OSCILLATIONS|INTERFERENCE)\b", raw):
                topic = f"{scope} localizer interference"
            elif "FRICTION" in raw:
                topic = f"{scope} braking-performance effect"
            elif re.search(r"\b\d+-MIN\s+INSPECTION\b", raw):
                topic = "short-inspection timing"
            elif route := re.search(r"\bATS ROUTE\s+([A-Z]\d+)\b", raw):
                topic = f"{route.group(1)} clearance/equipment applicability"
            else:
                names = {"runway_closure": "runway closure timing", "taxiway_closure": "taxiway restriction extent", "approach_navaid_closure": "approach-aid serviceability", "runway_approach_restriction": "runway/procedure restrictions"}
                topic = names.get(notice.get('pertinence_kind'), 'obstacle effects on the approach' if notice.get('approach_affected') else 'movement restriction scope')
            topics.append(topic)
        if not topics:
            topics = ["source-linked movement assessment"]
        planned = clean(analysis.get("planned_runway"))
        role = "alternate" if analysis.get("role") == "destination alternate" else clean(analysis.get("role"))
        result.append(f"{analysis['icao']} {role}" + (f" RWY {planned}" if planned else "") + ": unresolved " + "; ".join(dict.fromkeys(topics)) + ".")
    return result


def release_condition_groups(flight, view, receipt, airport_analysis, alternate_analysis, extracts):
    """Specific source limits, grouped for a readable single closing page."""
    complete = {"HELD", "FOUND", "CHECKED · NO MATCH", "CHECKED · NO TRIGGER", "NOT APPLICABLE"}
    pending = {r["key"]: r for r in receipt["rows"] if r["state"] not in complete}
    groups = {"weather": [], "operations": [], "technical": []}
    weather, operations, technical = groups.values()
    weather_keys = {"metar_taf": "METAR/TAF", "sigmet": "SIGMET", "vaa_vaac": "VAA/VAAC", "tropical_cyclone": "TC advisory/SIGMET"}
    missing = [label for key, label in weather_keys.items() if key in pending]
    if missing:
        weather.append(f"{flight.get('departure', '?')}-{flight.get('destination', '?')} {window_label(flight)}: complete {', '.join(missing)} coverage is not established.")
    unresolved_sigmets = [clean(r.get("name")) for r in (view.get("hazards") or {}).get("sigmet_cards") or []
                          if r.get("disposition") == "REVIEW REQUIRED" and "does not intersect the polygon" not in str(r.get("screening") or "")]
    unassessed_ash = [clean(r.get("volcano") or r.get("name")) for r in (view.get("vaa") or {}).get("cfp_advisories") or []
                     if r.get("advisory_kind") == "CFP_VAA_NOTICE"]
    if unresolved_sigmets or unassessed_ash:
        affected = list(dict.fromkeys(filter(None, unresolved_sigmets + unassessed_ash)))
        weather.append(", ".join(affected) + ": held advisory route/time/level assessment is incomplete (weather / route hazards page).")
    cat = [label for key, label in (("wafs_sigwx", "WAFS/SIGWX"), ("airep_pirep", "AIREP/PIREP")) if key in pending]
    if cat:
        vws = (view.get("terrain") or {}).get("vws_review") or {}
        near = clean(vws.get("maximum_waypoint"))
        weather.append((f"VWS {vws.get('maximum_display')} at {near}: " if near else "CAT: ") + f"{' and '.join(cat)} corroboration missing; VWS alone does not establish CAT.")
    declared = view.get("deferred_dispatch_gates") or []
    if declared:
        names = ", ".join(dict.fromkeys(re.sub(r"\s*REVIEW REQUIRED", "", clean(g.get("title"))) for g in declared))
        technical.append(f"{names}: operative Tech Log confirmation and completion of the technical status actions are not recorded in this briefing.")
    candidate_groups = {}
    for extract in extracts:
        if extract.get("match_status") == "candidate":
            candidate_groups.setdefault(extract.get("deferred_entry_id"), []).append(extract)
    for candidates in candidate_groups.values():
        names = ", ".join(dict.fromkeys(f"{e['item_type']} {e['reference']}" for e in candidates))
        conditions = " ".join(dict.fromkeys(clean(e.get("ambiguity_reason")) + " " + clean(e.get("confirmation_required")) for e in candidates))
        technical.append(f"MEL/CDL candidates: {names}; no candidate selected. {conditions}")
    operations.extend(airport_review_constraints(view, [*airport_analysis, *alternate_analysis]))
    missing_geometry = [a["icao"] for a in airport_analysis if not any(
        o.get("icao") == a["icao"] and o.get("role") == a["role"] and o.get("bounds")
        and (o.get("featureCollection") or {}).get("features") for o in view.get("surface_overlays") or [])]
    if missing_geometry:
        operations.append("No validated surface figure: " + ", ".join(missing_geometry) + ". Official surface charts remain necessary.")
    if "airport_intelligence" in pending:
        stations = list(dict.fromkeys(a["icao"] for a in airport_analysis))
        operations.append("Released Airport Notes coverage incomplete: " + "/".join(stations) + ".")
    if "depressurisation_profile" in pending:
        events = (view.get("terrain") or {}).get("events") or []
        legs = ["-".join(dict.fromkeys([(e.get("first_high") or {}).get("name", "?"), (e.get("last_high") or {}).get("name", "?")])) for e in events]
        technical.append("Escape/depressurisation profile not bound" + (": " + ", ".join(legs) if legs else "") + "; high MSA alone is not an escape procedure.")
    if "edto" in pending:
        stations = list(dict.fromkeys(clean(a.get("airport")) for a in (view.get("edto") or {}).get("airports") or []))
        technical.append("EDTO checked-period suitability unresolved" + (": " + "/".join(stations) if stations else "") + " (weather / route hazards page).")
    if "enroute_notam" in pending:
        technical.append("Complete route-airspace assessment is not held for the filed route.")
    for key in ("ofp_parse", "flight_timing", "fuel_performance", "vws", "airports_alternates", "airport_notam"):
        if key in pending:
            target = weather if key == "vws" else operations if key in {"airports_alternates", "airport_notam"} else technical
            target.append(pending[key]["detail"])
    number = 1
    for key, lines in groups.items():
        groups[key] = []
        for line in dict.fromkeys(lines):
            groups[key].append(f"{number}. {line}")
            number += 1
    return groups


def release_conditions(flight, view, receipt, airport_analysis, alternate_analysis, extracts):
    groups = release_condition_groups(flight, view, receipt, airport_analysis, alternate_analysis, extracts)
    return [line for lines in groups.values() for line in lines] or ["1. No unresolved automated source condition is recorded; crew operational release remains separate."]

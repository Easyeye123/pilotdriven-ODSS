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
        # ITEM 3 (14 Oct 2026): "begins" is measured to the start of the occurrence the shared decision found - the
        # next Item D occurrence, not the validity start - so the PDF says what the chart's scheduled mark says. An
        # assessment held before the shared rules carries no interval and still reads the validity start.
        interval = assessed.get("referenceInterval") if isinstance(assessed.get("referenceInterval"), dict) else {}
        start, anchor = _time(interval.get("startsAt")) or _time(record.get("valid_from_utc")), _time(reference)
        if start and anchor and start >= anchor:
            minutes = int((start - anchor).total_seconds() // 60)
            return f"begins {minutes} min after {name} {_clock(reference)}; actual taxi timing determines exposure", "scheduled"
    # A stored assessment (before the shared rules) can still hold this state; a new one never does.
    if state == "outside_schedule_at_reference":
        return f"outside the active schedule at {name} {_clock(reference)}, but overlaps the checked window", "scheduled"
    return None, "unresolved reference time"


# The movements a closure clause may name for itself.
#
# SQ352 15 Aug 2026, EKCH A1380/26, real OFP page 36:
#
#     DAILY 0400-1600
#     RWY 12/30 CLSD FOR TKOF AND LDG DUE TO WIP.
#
# The recognised clause was `timing + surface + predicate + reason` and had to
# match the whole clause, so this movement scope - sitting between predicate
# and reason - matched neither and the entire notice fell to unresolved. Page 1
# then published nothing for a destination whose closure page 2 printed
# (independent live QA of release 392).
#
# The scope is carried, not stripped: "closed" and "closed for take-off and
# landing" are different facts, and a reader deciding whether an arrival is
# affected needs the second.
_MOVEMENT_WORD = r"TKOF|TAKE[\s-]?OFF|LDG|LANDING|ARR(?:IVAL)?S?|DEP(?:ARTURE)?S?"
_MOVEMENT_SCOPE = (
    r"(?:\s+(?:FOR|TO)\s+(?P<movement>(?:" + _MOVEMENT_WORD + r")"
    r"(?:\s*(?:,|AND|OR|/)\s*(?:" + _MOVEMENT_WORD + r"))*))?"
)
_MOVEMENT_TEXT = {
    "TKOF": "take-off", "TAKEOFF": "take-off",
    "LDG": "landing", "LANDING": "landing",
    "ARR": "arrival", "ARRIVAL": "arrival", "ARRIVALS": "arrivals",
    "DEP": "departure", "DEPARTURE": "departure", "DEPARTURES": "departures",
}


def _with_movement_scope(operation: str, movement: str | None) -> str:
    """The operation, saying which movements the source named."""
    if not movement:
        return operation
    words: list[str] = []
    for token in re.split(r"[,/]|\bAND\b|\bOR\b", movement.upper()):
        key = re.sub(r"[\s-]+", "", token.strip())
        text = _MOVEMENT_TEXT.get(key)
        if text and text not in words:
            words.append(text)
    if not words:
        return operation
    named = " and ".join(words) if len(words) < 3 else ", ".join(words[:-1]) + " and " + words[-1]
    # "closed to the affected movement" is the unscoped wording; when the
    # source names the movements, it says them instead of that placeholder.
    if operation == "closed to the affected movement":
        return f"closed for {named}"
    return f"{operation} for {named}"


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
    patterns = [(re.compile(timing_prefix + _SURFACE.pattern + r"\s+" + predicate + _MOVEMENT_SCOPE + reason, re.I), operation)
                for predicate, operation in predicates]
    scopes: dict[str, list[str]] = {}
    unreduced = []
    for clause in filter(None, (part.strip() for part in re.split(r"\.(?=\s|$)|;", body))):
        for pattern, operation in patterns:
            match = pattern.fullmatch(clause)
            if match:
                runway = match.group(1).replace(" ", "").upper()
                scoped = _with_movement_scope(operation, match.groupdict().get("movement"))
                if runway not in scopes.setdefault(scoped, []):
                    scopes[scoped].append(runway)
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


# A notice that limits one approach CATEGORY on one runway, and says nothing
# else. SQ352 15 Aug 2026, EKCH A1312/26, real OFP page 36:
#
#     RWY 22L CAT II/III OPS NOT AVBL DUE TO WIP.
#
# The planned arrival runway is 22L. The notice names no aid, so the outage
# path below could not phrase it and the notice fell to the unreduced count -
# on page 1, on the dashboard card that prints page 1's statement, and on the
# AIRPORTS page - while the dashboard's own card had named it correctly in
# release 394 (independent candidate review, 22 Sep 2026). It is not an ILS
# outage and not a runway closure: the consequence says the category and the
# predicate the source used, on the runway it named, and nothing broader.
#
# The same statement in the US form, `ORD ILS RWY 28L CAT II/III NA` or
# `PHL ILS RWY 27R SPECIAL AUTH CAT II NA` (KORD A5362/26, KPHL A2969/26 in
# the held corpus), names the procedure's category; NA is "not authorized".
# Every clause of the notice must be one of these statements, or the notice
# stays unresolved: "ILS CAT IIIB OPS UNAFFECTED" (FACT A2781/26) and an
# obstacle "EXC IN RWY 25R CAT II/III OPS" never become a restriction.
_RUNWAY_END = r"(?:0[1-9]|[12]\d|3[0-6])[LCR]?"
_CATEGORY = (r"CAT\s*(?P<category>(?:I{1,3}|[123])[A-C]?"
             r"(?:\s*(?:/|\bAND\b)\s*(?:CAT\s*)?(?:I{1,3}|[123])[A-C]?)*)")
_CATEGORY_PREDICATE = {
    "NOT AVBL": "not available", "NOT AVAILABLE": "not available",
    "NA": "not authorized", "NOT AUTHORIZED": "not authorized", "NOT AUTHORISED": "not authorized",
    "SUSPENDED": "suspended",
}
_CATEGORY_PREDICATES = r"(?P<predicate>NOT\s+AVBL|NOT\s+AVAILABLE|NA|NOT\s+AUTHORI[SZ]ED|SUSPENDED)"
_CATEGORY_REASON = (r"(?:\s+DUE(?:\s+TO)?\s+(?:WIP|MAINT(?:ENANCE)?(?:\s+WIP)?|WORKS?|"
                    r"CONST(?:RUCTION)?(?:\s+WORKS)?|RWY\s+RESURFACING(?:\s+WIP)?))?")


def _category_restrictions(raw: str, icao: Any) -> list[dict[str, Any]] | None:
    """Each clause's (runway, category, procedure, predicate), or None.

    None whenever any clause is anything else, so the notice keeps its
    unresolved receipt rather than a partial reading.
    """
    from .notam_restriction_line import strip_publication_envelope

    body = " ".join((strip_publication_envelope(raw) or raw).upper().split())
    station = str(icao or "").strip().upper()
    location = re.escape(station[1:]) if len(station) == 4 else None
    prefix = rf"(?:{location}\s+)?(?:NAV\s+)?" if location else r"(?:NAV\s+)?"
    patterns = (
        re.compile(rf"(?:RWY|RUNWAY)\s*(?P<runway>{_RUNWAY_END})\s+{_CATEGORY}\s+(?:OPS|OPR|OPERATIONS?)\s+"
                   rf"{_CATEGORY_PREDICATES}{_CATEGORY_REASON}"),
        re.compile(rf"{prefix}(?P<procedure>ILS)\s+(?:RWY|RUNWAY)\s*(?P<runway>{_RUNWAY_END})\s+"
                   rf"(?P<special>SPECIAL\s+AUTH(?:ORI[SZ]ATION)?\s+)?{_CATEGORY}\s+{_CATEGORY_PREDICATES}"),
    )
    found: list[dict[str, Any]] = []
    for clause in filter(None, (part.strip() for part in re.split(r"\.(?=\s|$)|;", body))):
        match = next((m for m in (p.fullmatch(clause) for p in patterns) if m), None)
        if not match:
            return None
        categories = [token for token in re.split(r"\s*(?:/|\bAND\b)\s*(?:CAT\s*)?", match.group("category")) if token]
        item = {
            "runway": match.group("runway"),
            "category": "CAT " + "/".join(categories),
            "procedure": match.groupdict().get("procedure") or "",
            "special": bool(match.groupdict().get("special")),
            "predicate": _CATEGORY_PREDICATE[" ".join(match.group("predicate").split())],
        }
        if item not in found:
            found.append(item)
    return found or None


def _category_label(item: dict[str, Any]) -> str:
    """`RWY 22L CAT II/III operations not available` - the source's own scope."""
    procedure = f"{item['procedure']} " if item["procedure"] else ""
    special = "special-authorization " if item["special"] else ""
    return f"RWY {item['runway']} {procedure}{special}{item['category']} operations {item['predicate']}"


def _planned_relation(planned: str, runways: list[str]) -> tuple[bool, str]:
    """Whether the named runways include the planned one, and the short words."""
    matches = bool(planned and any(planned in runway.split("/") for runway in runways))
    if matches:
        return True, "planned runway"
    return False, (f"not planned RWY {planned}" if planned and runways else "")


def _brief_timing(state: str, timing: str) -> str:
    """The page-1 words for when a consequence applies, beyond the reference."""
    if state == "active":
        return ""
    begins = re.match(r"begins (\d+) min after (departure|arrival|alternate reference)", timing or "")
    if begins:
        return f" from {begins.group(1)} min after {begins.group(2)}"
    outside = re.match(r"outside the active schedule at (departure|arrival|alternate reference)", timing or "")
    if outside:
        return f" outside its schedule at {outside.group(1)}"
    return ""


def _chart_brief(titles: list[str], state: str, when: str, planned: str) -> str:
    """Page 1's words for suspended/withdrawn charts: the planned runway's first."""
    def runway(title: str) -> str | None:
        found = re.search(r"\bRWY\s+(" + _RUNWAY_END + r")\b", title)
        return found.group(1) if found else None
    mine = [title for title in titles if planned and runway(title) == planned]
    if mine:
        others = len(titles) - len(mine)
        tail = f"; {others} other chart(s)" if others else ""
        return f"Planned RWY {planned} approach charts {state}{when}: " + "; ".join(mine) + tail + "."
    listed = "; ".join(titles)
    if len(listed) <= 60:
        return _with_relation(f"Approach charts {state}{when}: {listed}", f"not planned RWY {planned}" if planned else "")
    return _with_relation(f"{len(titles)} approach charts {state}{when}", f"not planned RWY {planned}" if planned else "")


def _with_relation(text: str, relation: str) -> str:
    return f"{text} ({relation})." if relation else f"{text}."


def analyse_airport_for_pdf(panel: dict[str, Any], *, role: str, planned_runway: Any, route_text: str | None = None) -> dict[str, Any]:
    """Group equal consequences, retaining every contributing inline ID."""
    planned = str(planned_runway or "").strip().upper()
    groups: OrderedDict[tuple[str, str, str], dict[str, Any]] = OrderedDict()
    unresolved = []
    unresolved_detail: list[dict[str, Any]] = []

    def leave_unresolved(notice_id: str, raw: str, reason: str) -> None:
        # What page 1 may say of a notice this analysis cannot reduce: the
        # runways the notice itself names, and which part of it - its timing
        # or its effect - is not resolved. Never a guessed restriction.
        unresolved.append(notice_id)
        named = list(dict.fromkeys(m.replace(" ", "").upper() for m in _SURFACE.findall(raw)))
        unresolved_detail.append({
            "notam_id": notice_id, "runways": named, "reason": reason,
            "names_planned": bool(planned and any(planned in runway.split("/") for runway in named)),
        })
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
        # A complex supplement can print dated closure regimes for several
        # runways. The notice has ONE assessment of them, shared with the
        # dashboard card and the decision page (runway_closure_schedule): other
        # runways' closures limit this flight's options, so every regime in
        # effect is published, and the planned runway only annotates the line.
        from .runway_closure_schedule import assess_runway_closure_schedule, notice_reference_time
        assessed = next((r for r in notice.get("role_applicability") or [] if r.get("role") == role), notice)
        raw = str(notice.get("item_e_text") or "")
        runways = list(dict.fromkeys(m.replace(" ", "").upper() for m in _SURFACE.findall(raw)))
        assessment = assess_runway_closure_schedule(
            raw, role=role, reference_time=notice_reference_time(notice, role), planned_runway=planned,
        )
        for schedule in (assessment or {}).get("statements") or []:
            surface_effects.append({
                "text": schedule["text"], "runways": schedule["runways"],
                "referenceAt": schedule["referenceAt"], "referenceInterval": schedule["referenceInterval"],
                "stateAtReference": schedule["stateAtReference"],
                "notam_id": notice_id, "markClass": "closure", "scope": "whole_entity",
            })
            affected = schedule.get("plannedRunwayAffected")
            # One notice, one assessment: page 1 prints the schedule's own
            # sentence whole, as page 2, page 4 and the dashboard do, and says
            # whether it is the planned runway in a sentence of its own.
            relation = " Planned runway." if affected else f" Not planned RWY {planned}." if affected is False else ""
            groups[("runway", schedule["line"], "scheduled")] = {
                "family": "runway", "consequence": schedule["line"],
                "state": "scheduled", "timing": "dated runway schedule",
                "notam_ids": [notice_id], "source_pages": [notice.get("source_page")],
                "brief": schedule["text"] + relation,
                "relevance": 1 if affected else 2, "planned_match": bool(affected),
            }
        if (assessment or {}).get("statements"):
            # Other unresolved clauses retain their single closing receipt.
            if assessed.get("applicability") == "review":
                leave_unresolved(notice_id, raw, "timing")
            continue
        timing, state = _timing(notice, role)
        if state == "ended":
            continue
        if timing is None:
            leave_unresolved(notice_id, raw, "timing")
            continue
        # A chart's suspension is not a physical aid outage. Keep title/runway
        # tuples local to their source clauses, before any equipment grouping.
        if re.search(r"\b(?:IAC|AERONAUTICAL DATA TABULATION)\b", raw, re.I):
            charts = _approach_chart_restrictions(raw)
            if not charts:
                leave_unresolved(notice_id, raw, "effect")
                continue
            by_state: OrderedDict[str, list[str]] = OrderedDict()
            for title, chart_state in charts:
                by_state.setdefault(chart_state, []).append(title)
            for chart_state, titles in by_state.items():
                consequence = f"Published approach charts {chart_state} {timing}: " + "; ".join(titles) + "."
                key = ("approach_chart", consequence, state)
                chart_runways = [m for title in titles for m in re.findall(r"\bRWY\s+(" + _RUNWAY_END + r")\b", title)]
                chart_match = bool(planned and planned in chart_runways)
                row = groups.setdefault(key, {"family": "approach_chart", "consequence": consequence,
                                               "state": state, "timing": timing, "notam_ids": [], "source_pages": [],
                                               "brief": _chart_brief(titles, chart_state, _brief_timing(state, timing), planned),
                                               "relevance": 1 if chart_match else 3, "planned_match": chart_match})
                if notice_id not in row["notam_ids"]:
                    row["notam_ids"].append(notice_id)
                if notice.get("source_page") is not None and notice["source_page"] not in row["source_pages"]:
                    row["source_pages"].append(notice["source_page"])
            continue
        # This never prints the matched raw clause. Only identifiers and the
        # classifier's bounded result enter a consequence template.
        if notice.get("approach_affected") or kind == "approach_navaid_closure":
            from .pilot_briefing import _bound_unavailable, _APPROACH_SYSTEM
            categories = _category_restrictions(raw, panel.get("icao"))
            if categories:
                for item in categories:
                    matches, relation = _planned_relation(planned, [item["runway"]])
                    label = _category_label(item)
                    stated = (f"this concerns planned RWY {planned}" if matches
                              else f"planned RWY {planned} is a different runway" if planned
                              else "the planned runway is not held")
                    consequence = (f"{label}; restriction {timing}; {stated}." if timing.startswith("begins")
                                   else f"{label} {timing}; {stated}.")
                    row = groups.setdefault(("approach_category", consequence, state), {
                        "family": "approach_category", "consequence": consequence, "state": state,
                        "timing": timing, "notam_ids": [], "source_pages": [],
                        "brief": _with_relation(label + _brief_timing(state, timing), relation),
                        "relevance": 1 if matches else 3, "planned_match": matches,
                    })
                    if notice_id not in row["notam_ids"]:
                        row["notam_ids"].append(notice_id)
                    if notice.get("source_page") is not None and notice["source_page"] not in row["source_pages"]:
                        row["source_pages"].append(notice["source_page"])
                continue
            # The dashboard's approach flag also admits signal interference.
            # It cannot, by itself, establish a component outage.
            if not _bound_unavailable(raw.upper(), _APPROACH_SYSTEM):
                leave_unresolved(notice_id, raw, "effect")
                continue
            component = re.search(r"\b(ILS|DME|VOR|LOC|GP|GS|NDB|GLS)(?:[ -]+PART)\b", raw, re.I)
            systems = [aid for aid in dict.fromkeys(re.findall(r"\b(?:ILS|DME|VOR|LOC|GP|GS|NDB|GLS)\b", raw.upper()))
                       if _bound_unavailable(raw.upper(), re.escape(aid))]
            component_name = component.group(1).upper() if component else None
            subject = component_name if component_name in systems else "/".join(systems)
            if not subject:
                leave_unresolved(notice_id, raw, "effect")
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
                # ITEM 4 (F3-R460): the scope the card states, when the routing reader holds none (EGKK SX67/25,
                # VRMM SX5/26). Nothing is stated here that the card does not state.
                from .engines import taxiway_closure_stated_scopes
                taxiways = taxiway_closure_stated_scopes(raw)
            if not taxiways:
                leave_unresolved(notice_id, raw, "effect")
                continue
            # An entity-only record cannot establish the extent of a partial
            # closure. State the routing effect without colouring a whole way.
            consequence = f"Taxi access involving {', '.join(taxiways)} is constrained {timing}."
            family = "taxiway"
        elif runways:
            scopes, has_unresolved_clause = _complete_runway_closures(raw)
            if has_unresolved_clause or not scopes:
                leave_unresolved(notice_id, raw, "effect")
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
                                               "state": state, "timing": timing, "notam_ids": [], "source_pages": [],
                                               "brief": _with_relation(f"{runway_label} {operation}{_brief_timing(state, timing)}",
                                                                       _planned_relation(planned, affected_runways)[1]),
                                               "relevance": 1 if matches else 2, "planned_match": matches})
                if notice_id not in row["notam_ids"]:
                    row["notam_ids"].append(notice_id)
                if notice.get("source_page") is not None and notice["source_page"] not in row["source_pages"]:
                    row["source_pages"].append(notice["source_page"])
            continue
        else:
            leave_unresolved(notice_id, raw, "effect")
            continue
        key = (family, consequence, state)
        row = groups.setdefault(key, {"family": family, "consequence": consequence, "state": state, "timing": timing, "notam_ids": [], "source_pages": []})
        if kind == "airport_closure":
            row.setdefault("brief", f"Airport use is restricted{_brief_timing(state, timing)}; the planned movement depends on reopening.")
            row.setdefault("relevance", 0)
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
            combined = approach_groups.setdefault((row["timing"], row["state"]), {"family": "approach", "state": row["state"], "timing": row["timing"], "segments": [], "plain": [], "notam_ids": [], "source_pages": [], "planned_match": False})
            combined["segments"].append(f"{row['scope']} {row['aid']} ({', '.join(row['notam_ids'])})")
            combined["plain"].append(f"{row['scope']} {row['aid']}")
            combined["notam_ids"].extend(row["notam_ids"])
            combined["source_pages"].extend(row["source_pages"])
            combined["planned_match"] = combined["planned_match"] or row["planned_match"]
            continue
        if row["family"] != "taxiway":
            lines.append(row)
            continue
        key = (row["timing"], row["state"])
        combined = taxi_groups.setdefault(key, {"family": "taxiway", "state": row["state"], "timing": row["timing"], "segments": [], "plain": [], "notam_ids": [], "source_pages": []})
        combined["segments"].append(f"{', '.join(row['entities'])} ({', '.join(row['notam_ids'])})")
        combined["plain"].append(", ".join(row["entities"]))
        combined["notam_ids"].extend(row["notam_ids"])
        combined["source_pages"].extend(row["source_pages"])
    for row in lines:
        row["text"] = f"{row['consequence']} ({', '.join(row['notam_ids'])})"
    for row in approach_groups.values():
        relation = f"The affected aids include planned RWY {planned}." if row["planned_match"] else f"Planned RWY {planned} differs from the named affected runway(s)." if planned and all("published approach aid" not in s for s in row["segments"]) else "This component outage does not establish a whole-approach outage."
        prefix = "Approach-aid outage " if row["timing"].startswith("begins") else "Unavailable approach aids "
        row["consequence"] = prefix + row['timing'] + ": " + "; ".join(row["segments"]) + ". " + relation
        row["text"] = row["consequence"]
        short = (f"includes planned RWY {planned}" if row["planned_match"]
                 else f"not planned RWY {planned}" if planned and all("published approach aid" not in s for s in row["segments"])
                 else "")
        row["brief"] = _with_relation("; ".join(row.pop("plain")) + " unavailable" + _brief_timing(row["state"], row["timing"]), short)
        row["relevance"] = 1 if row["planned_match"] else 3
        lines.append(row)
    for row in taxi_groups.values():
        prefix = "Taxi restriction " if row["timing"].startswith("begins") else "Taxi access is constrained "
        row["consequence"] = prefix + row['timing'] + ": " + "; ".join(row["segments"]) + "."
        row["text"] = row["consequence"]
        # Page 1 names the places when they are few; a long list is counted,
        # and every place stays on the AIRPORTS page.
        places = "; ".join(row.pop("plain"))
        when = _brief_timing(row["state"], row["timing"])
        notices = len(dict.fromkeys(row["notam_ids"]))
        row["brief"] = (f"Taxi access constrained{when}: {places}." if len(places) <= 48
                        else f"Taxi access constrained{when} by {notices} notice(s).")
        row["relevance"] = 4
        lines.append(row)
    return {"icao": panel.get("icao"), "role": role, "planned_runway": planned or None, "lines": lines,
            "surface_effects": surface_effects, "unresolved_ids": unresolved, "unresolved_detail": unresolved_detail,
            "supporting_ids": excluded, "selected_ids": source_ids}


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

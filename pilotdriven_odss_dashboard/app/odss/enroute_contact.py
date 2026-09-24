"""Early ATC / FIR calls - the concise, source-governed record (PDF side).

The dashboard rule is web/src/lib/enroute-contact.mjs; this is the same rule
in Python, pinned to it token for token by the app's
tests/fixtures/enroute-contact-vectors.json and by the genuine-source
fixtures under tests/fixtures/enroute-contact/. Read that file's header for
the boss's words (27 Jul, 30 Jul, 24 Sep 2026) and the non-inference contract.

ATC-RADIO-SOURCE-418 (24 Sep 2026). Release 418 admitted only FIR-headed
CPDLC / ADS-C notices and then asserted a blanket "lead times and frequencies
are not held" over the genuine SQ366 and SQ23 OFPs, whose pages print TIBA,
contact and voice instructions with frequencies and lead times. The parser
now holds every printed communication instruction under a FIR or airway-
segment heading (parser._parse_notam_procedure_records), and this
composition derives, from each uploaded source alone:
  association  the crossing a record belongs to - its FIR heading; an
               ICAO/NAME FIR pair its body prints; the FIR in effect at its
               segment's waypoints on the parsed route (the last boundary row
               before them); else the association is stated unresolved;
  conditions   the notice's own printed conditions against the OFP's own
               facts - the validity window against the crossing instant,
               overflight / aerodrome / FIR-exit scope against the route's
               boundary rows, the direction between two named FIRs against
               the order of their crossings, named route segments against
               the filed route, a printed level band against the planned
               level profile; temporary-purpose and similar markers stay
               unresolved;
  quotation    the scope-compatible instruction sentence, verbatim, with the
               source's own printed frequencies, lead and interval; the only
               arithmetic is a printed lead before a printed boundary ACTM;
  details      approved-library findings keep their details (action /
               frequency / backup / lead / notes) - none is approved today;
  repeats      a consecutive duplicate boundary row is a repeated row; a
               repeat after a different FIR is a re-entry.
No flight, FIR, notice, frequency or expected string is special-cased.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any

ENROUTE_CONTACT_RULE = "enroute-contact-v2"

JAKARTA_AFN_NOTE = "CPDLC limited trial: pilot initiates AFN logon only when requested by ATC; address WIIF."
_JAKARTA_TOKENS = ("ADS-C/CPDLC", "REQUESTED BY ATC", "AFN LOGON", "ADDRESS FOR JAKARTA FIR IS WIIF")

# OCR / line-wrap splits joined for classification and evaluation only; every
# quotation keeps the source spelling. CALL SIGN is joined so that a bare CALL
# is an instruction and a call sign is not.
_OCR_JOINS = (
    ("CON TACT", "CONTACT"), ("BROAD CAST", "BROADCAST"), ("LOG ON", "LOGON"), ("LOG-ON", "LOGON"),
    ("TRANS MISSION", "TRANSMISSION"), ("FREQ UENCY", "FREQUENCY"), ("CALL SIGN", "CALLSIGN"), ("CALLSIGNS", "CALLSIGN"),
)
_UNIT = r"(?:ACC|ACCS|CTL|CONTROL|RADAR|RADIO|APP|APPROACH|TWR|TOWER|CENTER|CENTRE|ATC|ATS|FIR|INFORMATION|UNIT|SECTOR|CTR|OCC|ARTCC|ATSU)"
# A communication instruction, by its own printed verb and object: contact /
# CTC / call a unit or a frequency as an obligation or imperative (a state
# such as "in positive contact with" is not), establish or maintain contact,
# report a position, monitor a frequency; comply with TIBA, broadcast (as an
# obligation) or transmit; logon; CPDLC / ADS-C. A reference to TIBA
# procedures, a broadcast made by the ground, a phone number to call, a
# report "to ATC" of an occurrence or monitoring a selection are not.
_KIND_RULES = (
    ("contact_logon", re.compile(r"\bAFN LOGON\b|\bLOGON\b")),
    ("voice_contact", re.compile(
        r"\b(?:ESTABLISH(?:ED|ING)?|MAINTAIN(?:ING)?|MAKE|MAKING|REGAIN)\s+(?:RADIO\s+|TWO-WAY\s+|INITIAL\s+|VOICE\s+|DIRECT\s+)?(?:CONTACT|COMMUNICATIONS?)\b"
        r"|(?:^|[.;:]\s+|\b(?:SHALL|MUST|SHOULD|WILL|TO|IMMEDIATELY|THEN)\s+(?:[A-Z]+\s+)?)(?:CONTACT(?:ED|ING)?|CTC)\s+(?:THE\s+|WITH\s+)?(?:RELEVANT\s+|APPROPRIATE\s+|NEXT\s+|RESPECTIVE\s+)?(?:[A-Z][A-Z,/-]*\s+){0,4}?" + _UNIT + r"\b"
        r"|\b(?:SHALL|MUST|WILL|SHOULD|TO|AND)\s+CALL\s+(?:[A-Z][A-Z/-]*\s+){0,2}?(?:" + _UNIT + r"\b|ON\s+(?:FREQ(?:UENCY)?\s+)?\d{2,3}\.\d)"
        r"|\bREPORT(?:ING)?\s+(?:POSITION|PASSING|REACHING|ENTERING|CROSSING|ABEAM)\b"
        r"|\bMONITOR(?:ING)?\s+(?:CONTINUOUSLY\s+)?(?:THE\s+)?(?:VHF|UHF|HF|FREQ|FREQUENCY|GUARD|EMERGENCY|\d{2,3}\.\d)",
    )),
    ("tiba_broadcast", re.compile(
        r"\bCOMPLY WITH (?:THE )?TIBA\b|\bTIBA (?:FREQ(?:UENCY|UENCIES)?|BROADCASTS?|PROCEDURES? (?:FOR|ON|DEFINED|AS))\b|\bON (?:THE )?(?:RELEVANT |APPROPRIATE )?TIBA\b"
        r"|\b(?:SHALL|MUST|WILL|SHOULD|ARE REQUIRED TO|IS REQUIRED TO|ARE TO|IS TO|TO)\s+(?:[A-Z-]+\s+){0,3}?BROADCAST(?:ING)?\b|\bBROADCAST(?:ING)? (?:THEIR |YOUR )?INTENTIONS\b"
        r"|\bTRANSMISSIONS? SHALL\b",
    )),
    ("datalink_other", re.compile(r"\bCPDLC\b|\bADS-C\b")),
)
_KIND_RANK = {"voice_contact": 0, "tiba_broadcast": 1, "contact_logon": 2, "datalink_other": 3}
_STATE_RANK = {"conditions_held": 0, "conditions_unresolved": 1, "not_applicable": 2}
# A sentence ends at "." or ";" after a word of two or more characters; a list
# marker ("A.", "1.") and a unit abbreviation ("MIN.", "HRS.") do not end one.
_SENTENCE_SPLIT = re.compile(r"(?<=\S\S[.;])\s+")
_ABBREVIATION = re.compile(r"\b(?:MIN|MINS|HR|HRS|NM|FT|SEC|SECS|KT|KTS|DEG|APPROX)\.$")
_FREQUENCY = re.compile(r"\b\d{2,3}\.\d{1,3} ?MHZ\b")
_LEAD_NOUN = r"(?:FIR|FIRS|BOUNDARY|POINT|ENTRY|ENTRANCE|TAKEOFF|TAKE-OFF|DEPARTURE|AIRSPACE|SECTOR|TMA|CTA|UTA|CROSSING)"
# The lead as printed: an amount, up to two words, a relation word and the
# anchor noun phrase it names (the FIR, the boundary point, the entry, the
# take-off), never a following proper name or clause.
_LEAD = re.compile(
    r"\b((?:(?:NOT LESS THAN|NOT LATER THAN|NOT EARLIER THAN|AT LEAST|WI|WITHIN|MINIMUM|MIN|MAXIMUM|MAX|APPROX(?:IMATELY)?|BETWEEN \d{1,3} AND) )?\d{1,3} ?MIN(?:S|UTES)?\.?"
    r"(?: [A-Z-]+){0,2}? (?:PRIOR|BEFORE|TO THE ENTRANCE|OF ENTRY|AHEAD OF|IN ADVANCE OF)"
    r"(?:(?: [A-Z][A-Z'-]*){0,5}? " + _LEAD_NOUN + r"(?: " + _LEAD_NOUN + r")*)?)",
)
_INTERVAL = re.compile(r"\bEVERY \d{1,3} ?MIN(?:S|UTES)?\b")
_VALIDITY = re.compile(r"^(\d{2})-([A-Z]{3})-(\d{2}) (\d{4})\s*-\s*(?:(\d{2})-([A-Z]{3})-(\d{2}) (\d{4})(?:\s*EST)?|(UFN|PERM))\s*$")
_MONTHS = {m: i + 1 for i, m in enumerate(("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"))}
_NAME = r"[A-Z][A-Z-]*(?: [A-Z][A-Z-]*)*?"
_NAMES = _NAME + r"(?:(?:, | AND | OR |, AND |, OR )" + _NAME + r")*?"
# "FM A FIR TO B FIR" / "ENTERING B AND C FIRS FM A FIR": the notice's own direction between named FIRs.
_DIRECTIONS = (
    re.compile(r"\bF(?:RO)?M (?:THE )?(?P<from>" + _NAMES + r") FIRS? (?:TO|INTO) (?:THE )?(?P<to>" + _NAMES + r") FIRS?\b"),
    re.compile(r"\bENTERING (?:THE )?(?P<to>" + _NAMES + r") FIRS? F(?:RO)?M (?:THE )?(?P<from>" + _NAMES + r") FIRS?\b"),
)
_BODY_FIR = re.compile(r"\b([A-Z]{4})/([A-Z][A-Z -]*?) FIR\b")
_ROUTE_LIST = re.compile(r"\b([A-Z]{5})-([A-Z]{1,2}\d{1,3})-([A-Z]{5})(?:-([A-Z]{1,2}\d{1,3})-([A-Z]{5}))?\s*(?:\(FL(\d{3})-FL(\d{3})\))?")
_ROUTE_PAIR = re.compile(r"(?:\(|, )([A-Z]{1,2}\d{1,3}) ([A-Z]{5})(?=[,)])")
# A printed contact table row: airway, transfer point, the unit, its primary and secondary frequency.
_ROUTE_FREQ_ROW = re.compile(r"\b([A-Z]{1,2}\d{1,3}) ([A-Z]{5}) ((?:[A-Z]+ ){1,4}?)(\d{2,3}\.\d{1,3} MHZ)(?: (\d{2,3}\.\d{1,3} MHZ))?")
_OVERFLIGHT = re.compile(r"\bOVERFLIGHTS?\b|\bOVERFLYING\b|\bTRANSIT(?:ING)?\b")
_AERODROME = re.compile(r"\bAERODROMES?\b|\bTAKE-?OFF\b|\bLANDING\b|\bARRIVAL AND DEPARTURE\b|\bARRIVING OR DEPARTING\b|\bAPPROACH\b")
_FIR_EXIT = re.compile(r"\bDEPARTING (?:THE )?(?:[A-Z]+ )?FIR\b|\bLEAVING (?:THE )?(?:[A-Z]+ )?FIR\b|\bNEXT FIR\b")
_FIR_ENTRY = re.compile(r"\bENTERING\b|\bENTRY\b|\bENTRANCE\b")
_UNRESOLVED = re.compile(r"\bTEMPORARY PURPOSE\b|\bAS REQUIRED\b|\bUNLESS OTHERWISE\b|\bSUBJECT TO\b|\bWHEN INSTRUCTED\b")

STATE_SENTENCES = {
    "no_fir_rows_held": "No FIR boundary row is held in the parsed OFP; early-contact requirements are not established from this source.",
    "no_procedure_held": "No early-contact requirement is held in this OFP's FIR notices or in an approved reference; lead times and frequencies are not held and are not inferred from crossing times.",
}
NO_ALLOCATION_SENTENCE = "No slot-control allocation is printed in this OFP."


def _normalise(value: Any) -> str:
    return " ".join(str(value if value is not None else "").split())


def _integer(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def actm_text(minutes: int) -> str:
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def classify_text(text: Any) -> str:
    """Upper-cased, whitespace-collapsed, OCR / wrap splits joined - for classification and evaluation, never for a quotation."""
    upper = _normalise(text).upper()
    for split, joined in _OCR_JOINS:
        upper = upper.replace(split, joined)
    return upper


def procedure_kind(text: Any) -> str | None:
    """The notice's own instruction decides the kind; its FIR or region never does. None: not a communication instruction."""
    upper = classify_text(text)
    for kind, pattern in _KIND_RULES:
        if pattern.search(upper):
            return kind
    return None


def sentences(text: Any) -> list[str]:
    clean = _normalise(text)
    if not clean:
        return []
    parts: list[str] = []
    for fragment in _SENTENCE_SPLIT.split(clean):
        if parts and _ABBREVIATION.search(parts[-1]):
            parts[-1] = f"{parts[-1]} {fragment}"
        else:
            parts.append(fragment)
    return [part.strip() for part in parts if part.strip()]


def contact_instruction(text: Any) -> str:
    """The first printed sentence carrying a communication instruction (a verbatim substring of the source)."""
    parts = sentences(text)
    if not parts:
        return ""
    return next((s for s in parts if procedure_kind(s)), parts[0])


def shorten(text: Any, limit: int = 200) -> str:
    """A whole-word prefix of at most ``limit`` characters, "…" when cut."""
    clean = _normalise(text)
    if len(clean) <= limit:
        return clean
    cut = clean[: limit - 1]
    space = cut.rfind(" ")
    return (cut[:space] if space > 40 else cut).strip() + "…"


def _governed_note(record: dict[str, Any]) -> str | None:
    heading = _normalise(record.get("heading")).upper()
    text = _normalise(record.get("text")).upper()
    if "JAKARTA FIR" in heading and all(token in text for token in _JAKARTA_TOKENS):
        return JAKARTA_AFN_NOTE
    return None


def _page_range(pages: list[int]) -> str:
    """His provenance style: "p12"; a contiguous run "pp8-14"; runs listed "p67, p85, pp88-89"."""
    runs: list[list[int]] = []
    for page in pages:
        if runs and page == runs[-1][-1] + 1:
            runs[-1].append(page)
        else:
            runs.append([page])
    return ", ".join(f"pp{run[0]}-{run[-1]}" if len(run) > 1 else f"p{run[0]}" for run in runs)


def _utc(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _hhmm_z(value: datetime | None) -> str | None:
    return f"{value:%H%M}Z" if value else None


def validity_window(validity: Any) -> tuple[datetime | None, datetime | None] | None:
    """The printed VALID window as UTC instants; an open end (UFN / PERM) is None; unreadable text is None."""
    match = _VALIDITY.match(_normalise(validity).upper())
    if not match:
        return None

    def stamp(day: str, mon: str, year: str, hhmm: str) -> datetime | None:
        month = _MONTHS.get(mon)
        if not month:
            return None
        try:
            return datetime(2000 + int(year), month, int(day), int(hhmm[:2]), int(hhmm[2:]), tzinfo=timezone.utc)
        except ValueError:
            return None

    start = stamp(match.group(1), match.group(2), match.group(3), match.group(4))
    if start is None:
        return None
    if match.group(9):
        return start, None
    end = stamp(match.group(5), match.group(6), match.group(7), match.group(8))
    return (start, end) if end is not None else None


# ---------------------------------------------------------------- the route the OFP prints


def _route(flight: dict[str, Any]) -> dict[str, Any]:
    names: list[str] = []
    fir_in_effect: list[str | None] = []
    current: str | None = None
    for waypoint in flight.get("route_waypoints") or []:
        if not isinstance(waypoint, dict):
            continue
        boundary = _normalise(waypoint.get("fir_boundary")).upper() or None
        if boundary:
            current = boundary
        names.append(_normalise(waypoint.get("name")).upper().lstrip("-"))
        fir_in_effect.append(current)
    profile: list[tuple[str, int]] = []
    tokens = [t for t in _normalise(flight.get("planned_level_profile")).upper().split("/") if t]
    for index in range(0, len(tokens) - 1, 2):
        if tokens[index + 1].isdigit():
            profile.append((tokens[index], int(tokens[index + 1])))
    return {"names": names, "fir_in_effect": fir_in_effect, "profile": profile}


def _planned_level_at(route: dict[str, Any], waypoint: str) -> int | None:
    """The FL in effect at a route waypoint: the last profile step at or before it in route order (the departure step first)."""
    if not route["profile"] or waypoint not in route["names"]:
        return None
    target = route["names"].index(waypoint)
    level = route["profile"][0][1]
    for name, flight_level in route["profile"][1:]:
        if name in route["names"] and route["names"].index(name) <= target:
            level = flight_level
    return level


def _fir_names(flight: dict[str, Any], records: list[dict[str, Any]]) -> dict[str, str]:
    """ICAO -> name from the OFP's own FIR headings and from ICAO/NAME FIR pairs the notices print."""
    names: dict[str, str] = {}
    held = flight.get("notam_fir_names")
    if isinstance(held, dict):
        for icao, name in held.items():
            if isinstance(icao, str) and isinstance(name, str) and len(icao) == 4:
                names[icao.upper()] = _normalise(name).upper()
    for record in records:
        match = re.match(r"^([A-Z]{4}) (.+?) FIR$", classify_text(record.get("heading")))
        if match:
            names.setdefault(match.group(1), match.group(2).strip())
        for icao, name in _BODY_FIR.findall(classify_text(record.get("text"))):
            names.setdefault(icao, name.strip())
    return names


# ---------------------------------------------------------------- crossings


def _crossings(flight: dict[str, Any]) -> list[dict[str, Any]]:
    crossings: list[dict[str, Any]] = []
    seen: set[str] = set()
    previous: str | None = None
    for waypoint in flight.get("route_waypoints") or []:
        if not isinstance(waypoint, dict):
            continue
        fir = _normalise(waypoint.get("fir_boundary")).upper()
        minutes = _integer(waypoint.get("actm_minutes"))
        if not fir or minutes is None:
            continue
        repeated = fir == previous
        crossings.append({
            "sequence": len(crossings) + 1,
            "fir": fir,
            "actm": actm_text(minutes),
            "actm_minutes": minutes,
            "source_page": _integer(waypoint.get("source_page")),
            "reentry": fir in seen and not repeated,
            "repeated": repeated,
            "utc": None,
            "day": "",
        })
        seen.add(fir)
        previous = fir
    return crossings


def _relation(crossings: list[dict[str, Any]], fir: str) -> str:
    """overflight: the route enters the FIR and later crosses into another; arrival: it is the last FIR entered; else unresolved."""
    entries = [row for row in crossings if row["fir"] == fir]
    if not entries:
        return "unresolved"
    if any(row["sequence"] > entries[0]["sequence"] and row["fir"] != fir for row in crossings):
        return "overflight"
    return "arrival" if crossings[-1]["fir"] == fir else "unresolved"


def _next_fir(crossings: list[dict[str, Any]], fir: str) -> dict[str, Any] | None:
    entries = [row for row in crossings if row["fir"] == fir]
    if not entries:
        return None
    for row in crossings:
        if row["sequence"] > entries[0]["sequence"] and row["fir"] != fir:
            return {"fir": row["fir"], "actm": row["actm"]}
    return None


# ---------------------------------------------------------------- one notice against the OFP


def sentence_scope(sentence: Any) -> str:
    upper = classify_text(sentence)
    if _OVERFLIGHT.search(upper):
        return "overflight"
    if _FIR_EXIT.search(upper):
        return "fir_exit"
    if _AERODROME.search(upper):
        return "aerodrome"
    if _FIR_ENTRY.search(upper):
        return "fir_entry"
    return "unscoped"


def _scope_compatible(scope: str, relation: str) -> bool:
    if scope in ("unscoped", "fir_entry"):
        return True
    if scope in ("overflight", "fir_exit"):
        return relation == "overflight"
    return relation == "arrival"


def printed_details(sentence: Any) -> dict[str, Any]:
    """The frequencies, lead and interval a sentence prints, in the source's own words."""
    upper = classify_text(sentence)
    frequencies: list[str] = []
    for match in _FREQUENCY.findall(upper):
        if match not in frequencies:
            frequencies.append(match)
    lead = _LEAD.search(upper)
    interval = _INTERVAL.search(upper)
    return {"frequencies": frequencies, "lead": lead.group(1).strip() if lead else None, "interval": interval.group(0) if interval else None}


def _lead_minutes(lead: str | None) -> int | None:
    """The latest lead the phrase allows: its smallest printed amount ("BETWEEN 15 AND 30 MINUTES" -> 15)."""
    amounts = [int(n) for n in re.findall(r"\b(\d{1,3})\b", lead or "")]
    return min(amounts) if amounts else None


def _route_tokens(text: str) -> list[dict[str, Any]]:
    """Waypoint / airway tokens the notice prints, each with any level band printed beside it."""
    upper = classify_text(text)
    tokens: list[dict[str, Any]] = []
    for match in _ROUTE_LIST.finditer(upper):
        band = (int(match.group(6)), int(match.group(7))) if match.group(6) else None
        pairs = ((match.group(1), match.group(2)), (match.group(3), match.group(2)), (match.group(3), match.group(4)), (match.group(5), match.group(4)))
        for waypoint, airway in pairs:
            if waypoint and airway:
                tokens.append({"waypoint": waypoint, "airway": airway, "band": band, "text": match.group(0).strip()})
    for airway, waypoint in _ROUTE_PAIR.findall(upper):
        tokens.append({"waypoint": waypoint, "airway": airway, "band": None, "text": f"{airway} {waypoint}"})
    for airway, waypoint, unit, primary, secondary in _ROUTE_FREQ_ROW.findall(upper):
        frequencies = [f for f in (primary, secondary) if f]
        tokens.append({"waypoint": waypoint, "airway": airway, "band": None, "frequencies": frequencies,
                       "text": f"{airway} {waypoint} {unit.strip()} {' '.join(frequencies)}"})
    return tokens


def effective_scopes(parts: list[str]) -> list[str]:
    """A sentence's own scope; an unscoped sentence takes the scope of the notice's opening sentence, which states its subject."""
    own = [sentence_scope(s) for s in parts]
    opening = own[0] if own else "unscoped"
    return [scope if scope != "unscoped" else opening for scope in own]


def _instruction_index(parts: list[str], scopes: list[str], kind: str, relation: str) -> int:
    """The scope-compatible sentence of the record's own kind carrying printed values; then compatible; then any communication sentence."""
    communication = [i for i, s in enumerate(parts) if procedure_kind(s)]
    if not communication:
        return 0
    def rank(i: int) -> tuple[int, int, int, int]:
        return (
            0 if _scope_compatible(scopes[i], relation) else 1,
            0 if procedure_kind(parts[i]) == kind else 1,
            0 if any(printed_details(parts[i]).values()) else 1,
            i,
        )
    return min(communication, key=rank)


def _resolve_names(printed: str, names: dict[str, str]) -> list[tuple[str, str | None]]:
    """The FIR names a direction phrase lists, each with the ICAO the OFP's own headings or bodies give it."""
    by_name = {name: icao for icao, name in names.items()}
    return [(name, by_name.get(name)) for name in re.split(r", AND | AND |, OR | OR |, ", printed.strip()) if name.strip()]


def _compose_procedure(record: dict[str, Any], route: dict[str, Any], crossings: list[dict[str, Any]],
                       names: dict[str, str], departure: datetime | None) -> dict[str, Any] | None:
    """One source-held notice against this flight's OFP; None when the notice's airspace is not on the parsed route."""
    text = _normalise(record.get("text"))
    kind = procedure_kind(text)
    if kind is None:
        return None
    heading = classify_text(record.get("heading"))
    heading_kind = _normalise(record.get("heading_kind")) or ("fir" if re.match(r"^[A-Z]{4}\b", heading) else "segment")
    crossed = {row["fir"] for row in crossings}
    first_by_fir: dict[str, dict[str, Any]] = {}
    for row in crossings:
        first_by_fir.setdefault(row["fir"], row)
    segment = record.get("segment") if isinstance(record.get("segment"), dict) else None
    segment_waypoints = [str(w).upper() for w in ((segment or {}).get("from"), (segment or {}).get("to")) if isinstance(w, str)]

    association, fir = "unresolved", ""
    if heading_kind == "fir":
        heading_fir = _normalise(record.get("fir")).upper() or heading.split(" ")[0]
        if heading_fir not in crossed:
            return None
        association, fir = "fir_heading", heading_fir
    else:
        body_firs = [icao for icao, _ in _BODY_FIR.findall(classify_text(text)) if icao in crossed]
        on_route = [w for w in segment_waypoints if w in route["names"]]
        if body_firs:
            association, fir = "body_fir", body_firs[0]
        elif on_route:
            in_effect = route["fir_in_effect"][route["names"].index(on_route[0])]
            if in_effect and in_effect in crossed:
                association, fir = "segment_on_route", in_effect
        elif segment_waypoints:
            return None
    entry = first_by_fir.get(fir) if fir else None
    relation = _relation(crossings, fir) if fir else "unresolved"

    parts = sentences(text)
    scopes = effective_scopes(parts)
    index = _instruction_index(parts, scopes, kind, relation)
    instruction = parts[index] if parts else ""
    scope = scopes[index] if parts else "unscoped"
    conditions: list[dict[str, Any]] = []

    validity = _normalise(record.get("validity"))
    window = validity_window(validity)
    instant = departure + timedelta(minutes=entry["actm_minutes"]) if departure and entry else None
    if window is None or instant is None:
        conditions.append({"kind": "validity", "text": validity, "result": "unresolved"})
    else:
        start, end = window
        conditions.append({"kind": "validity", "text": validity, "result": "met" if start <= instant and (end is None or instant <= end) else "not_met"})

    if scope == "overflight":
        conditions.append({"kind": "scope", "text": "overflight", "result": "met" if relation == "overflight" else "not_met" if relation == "arrival" else "unresolved"})
    elif scope == "aerodrome":
        conditions.append({"kind": "scope", "text": "arrival/departure operations at aerodromes in the FIR", "result": "met" if relation == "arrival" else "not_met" if relation == "overflight" else "unresolved"})
    elif scope == "fir_exit":
        conditions.append({"kind": "scope", "text": "departing the FIR", "result": "met" if relation == "overflight" else "not_met" if relation == "arrival" else "unresolved"})

    direction = next((m for m in (pattern.search(classify_text(instruction)) for pattern in _DIRECTIONS) if m), None)
    if direction:
        origins = _resolve_names(direction.group("from"), names)
        targets = _resolve_names(direction.group("to"), names)
        origin_rows = [first_by_fir[icao] for _, icao in origins if icao in first_by_fir]
        target_rows = [first_by_fir[icao] for _, icao in targets if icao in first_by_fir]
        if any(icao is None for _, icao in origins) and not origin_rows or all(icao is None for _, icao in targets):
            result = "unresolved"
        elif not origin_rows or not target_rows:
            result = "not_met"
        else:
            result = "met" if any(o["sequence"] < t["sequence"] for o in origin_rows for t in target_rows) else "not_met"
        conditions.append({
            "kind": "direction",
            "text": "/".join(icao or name for name, icao in origins) + " → " + "/".join(icao or name for name, icao in targets),
            "result": result,
        })

    route_frequencies: list[str] | None = None
    tokens = _route_tokens(text)
    if segment is not None and heading_kind == "segment":
        tokens = [{"waypoint": w, "airway": segment.get("airway"), "band": None, "text": _normalise(record.get("heading"))} for w in segment_waypoints] + tokens
    if tokens:
        on_route_tokens = [t for t in tokens if t["waypoint"] in route["names"]]
        matched = on_route_tokens[0] if on_route_tokens else None
        conditions.append({"kind": "route", "text": matched["text"] if matched else tokens[0]["text"], "result": "met" if matched else "not_met"})
        if matched and matched.get("frequencies"):
            route_frequencies = list(matched["frequencies"])
        band_token = next((t for t in on_route_tokens if t["band"]), None)
        if band_token:
            level = _planned_level_at(route, band_token["waypoint"])
            low, high = band_token["band"]
            conditions.append({
                "kind": "level", "text": f"FL{low}-FL{high} at {band_token['waypoint']}",
                "result": "unresolved" if level is None else "met" if low <= level <= high else "not_met",
                "note": f"planned FL{level}" if level is not None else "planned level not held",
            })
    unresolved = _UNRESOLVED.search(classify_text(instruction))
    if unresolved:
        conditions.append({"kind": "other", "text": unresolved.group(0).lower().replace(" ", "-"), "result": "unresolved"})
    if association == "unresolved":
        conditions.append({"kind": "association", "text": "FIR in effect at the segment not derivable from the boundary rows", "result": "unresolved"})

    results = [c["result"] for c in conditions]
    state = "not_applicable" if "not_met" in results else "conditions_unresolved" if "unresolved" in results else "conditions_held"

    details = printed_details(instruction)
    if route_frequencies is not None:
        details["frequencies"] = route_frequencies
    lead_minutes = _lead_minutes(details["lead"])
    next_fir = _next_fir(crossings, fir) if fir and scope == "fir_exit" else None
    latest = None
    if lead_minutes is not None:
        anchor = None
        if scope == "fir_exit":
            anchor = next((row for row in crossings if next_fir and row["fir"] == next_fir["fir"] and row["actm"] == next_fir["actm"]), None)
        elif entry:
            anchor = entry
        if anchor and anchor["actm_minutes"] >= lead_minutes:
            latest = actm_text(anchor["actm_minutes"] - lead_minutes)

    return {
        "fir": fir,
        "notam_id": _normalise(record.get("notam_id")).upper(),
        "source_page": _integer(record.get("source_page")),
        "validity": validity,
        "heading": _normalise(record.get("heading")),
        "heading_kind": heading_kind,
        "kind": kind,
        "association": association,
        "instruction": instruction,
        "instruction_short": shorten(instruction),
        "note": _governed_note(record),
        "printed_details": details,
        "conditions": conditions,
        "applicability_state": state,
        "next_fir": next_fir,
        "latest_actm": latest,
        "actm": entry["actm"] if entry else None,
        "sequence": entry["sequence"] if entry else None,
        "on_route": True,
        "applicability": "not_inferred",
    }


def _minutes(actm: str | None) -> int | None:
    if not actm:
        return None
    hours, minutes = actm.split(":")
    return int(hours) * 60 + int(minutes)


def _time_order(row: dict[str, Any]) -> tuple[int, int, int, str]:
    """Rows in the order their actions fall due: the latest ACTM a printed lead gives, else the entry; then state, kind, identity."""
    anchor = _minutes(row.get("latest_actm")) if row.get("latest_actm") else _minutes(row.get("actm"))
    return (anchor if anchor is not None else 10 ** 6, _STATE_RANK[row["applicability_state"]], _KIND_RANK[row["kind"]], row["notam_id"])


def is_call_line(line: dict[str, Any]) -> bool:
    """A voice / broadcast / logon row whose printed conditions are not failed."""
    return line["kind"] != "datalink_other" and line["applicability_state"] != "not_applicable"


def has_printed_values(line: dict[str, Any]) -> bool:
    details = line.get("printed_details") or {}
    return bool(details.get("frequencies") or details.get("lead") or details.get("interval"))


def primary_procedure_line(lines: list[dict[str, Any]]) -> dict[str, Any] | None:
    """The one row every page-6 ladder step prints in full and parity binds on both surfaces: in time order, the first
    call row that prints a frequency, else the first with any printed value, else the first call row, else the first row."""
    return (
        next((l for l in lines if is_call_line(l) and (l.get("printed_details") or {}).get("frequencies")), None)
        or next((l for l in lines if is_call_line(l) and has_printed_values(l)), None)
        or next((l for l in lines if is_call_line(l)), None)
        or (lines[0] if lines else None)
    )


def printed_values(line: dict[str, Any]) -> list[str]:
    """The parts both surfaces print after the instruction: the frequencies, lead and interval as printed, the next FIR for an exit call, the latest ACTM a printed lead gives."""
    details = line.get("printed_details") or {}
    parts: list[str] = []
    if details.get("frequencies"):
        parts.append(", ".join(details["frequencies"]))
    if details.get("lead"):
        parts.append(details["lead"])
    if details.get("interval"):
        parts.append(details["interval"])
    if line.get("next_fir"):
        parts.append(f"next FIR {line['next_fir']['fir']} at {line['next_fir']['actm']}")
    if line.get("latest_actm"):
        parts.append(f"not later than ACTM {line['latest_actm']}")
    return parts


def condition_phrase(condition: dict[str, Any]) -> str:
    kind, result, text = condition["kind"], condition["result"], condition.get("text") or ""
    if kind == "validity":
        return f"validity {text}: " + {"met": "covers this crossing", "not_met": "outside this crossing", "unresolved": "not evaluable"}[result]
    if kind == "route":
        return f"route {text}: " + {"met": "on the filed route", "not_met": "not on the filed route", "unresolved": "unresolved"}[result]
    if kind == "level":
        return f"level {text}: {condition.get('note') or ''} " + {"met": "within", "not_met": "outside", "unresolved": "not evaluable"}[result]
    if kind == "direction":
        return f"direction {text}: " + {"met": "met", "not_met": "not met", "unresolved": "unresolved"}[result]
    if kind == "scope":
        return f"{text}: " + {"met": "met", "not_met": "not met", "unresolved": "unresolved"}[result]
    if kind == "association":
        return text
    return f"{text} condition not evaluable"


STATE_PHRASES = {"conditions_held": "conditions held", "conditions_unresolved": "conditions unresolved", "not_applicable": "not applicable"}


def conditions_summary(row: dict[str, Any]) -> str:
    phrases = [condition_phrase(c) for c in row.get("conditions") or []]
    phrases.append(STATE_PHRASES[row["applicability_state"]])
    return " · ".join(phrases)


def procedure_lines(procedures: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One printed row per FIR, text and applicability; notices that carry the same instruction share the row. Composed order kept."""
    lines: list[dict[str, Any]] = []
    for row in procedures:
        text = row["note"] or row["instruction_short"]
        line = next((item for item in lines if item["fir"] == row["fir"] and item["text"] == text and item["applicability_state"] == row["applicability_state"]), None)
        if line is not None:
            if row["notam_id"] not in line["notam_ids"]:
                line["notam_ids"].append(row["notam_id"])
            if row["source_page"] is not None and row["source_page"] not in line["source_pages"]:
                line["source_pages"].append(row["source_page"])
            continue
        lines.append({
            "fir": row["fir"], "actm": row["actm"], "sequence": row["sequence"], "text": text, "kind": row["kind"],
            "association": row["association"], "applicability_state": row["applicability_state"],
            "printed_details": {"frequencies": list(row["printed_details"]["frequencies"]), "lead": row["printed_details"]["lead"], "interval": row["printed_details"]["interval"]},
            "latest_actm": row["latest_actm"], "next_fir": dict(row["next_fir"]) if row["next_fir"] else None,
            "conditions_summary": conditions_summary(row),
            "notam_ids": [row["notam_id"]], "source_pages": [row["source_page"]] if row["source_page"] is not None else [],
        })
    for line in lines:
        line["source_pages"].sort()
    return lines


# ---------------------------------------------------------------- slot control


def _slot_control(flight: dict[str, Any]) -> dict[str, Any] | None:
    bobcat = flight.get("bobcat")
    if not isinstance(bobcat, dict) or not bobcat.get("waypoint"):
        return None
    waypoint = str(bobcat["waypoint"]).upper()
    ctot_at = _utc(bobcat.get("ctot_utc"))
    cto_at = _utc(bobcat.get("cto_utc"))
    # The engine's own rule: an allocated CTO printed before the CTOT is the next UTC day.
    if ctot_at and cto_at and cto_at < ctot_at:
        cto_at = cto_at + timedelta(days=1)
    row = next((w for w in flight.get("route_waypoints") or [] if isinstance(w, dict) and str(w.get("name") or "").upper() == waypoint), None)
    actm_minutes = _integer(row.get("actm_minutes")) if row else None
    computed = ctot_at + timedelta(minutes=actm_minutes) if actm_minutes is not None and ctot_at else None
    difference = round((computed - cto_at).total_seconds() / 60) if computed and cto_at else None
    evidence = flight.get("source_evidence") if isinstance(flight.get("source_evidence"), dict) else {}
    pages = sorted({p for p in (_integer(evidence.get("page1")), _integer(row.get("source_page")) if row else None) if p is not None and p > 0})
    level = bobcat.get("flight_level")
    return {
        "system": "BOBCAT",
        "waypoint": waypoint,
        "flight_level": _integer(level) if _integer(level) is not None else (int(level) if level is not None else None),
        "ctot": _hhmm_z(_utc(bobcat.get("ctot_utc"))),
        "cto": _hhmm_z(_utc(bobcat.get("cto_utc"))),
        "actm": actm_text(actm_minutes) if actm_minutes is not None else None,
        "computed_cto": _hhmm_z(computed),
        "difference_minutes": difference,
        "source_pages": pages,
    }


def slot_sentence(slot: dict[str, Any] | None) -> str:
    if not slot:
        return NO_ALLOCATION_SENTENCE
    pages = f" (OFP {', '.join(f'p{p}' for p in slot['source_pages'])})" if slot["source_pages"] else ""
    level = f"FL{slot['flight_level']}" if slot["flight_level"] is not None else "level not found"
    if slot["actm"] is None or slot["computed_cto"] is None or slot["difference_minutes"] is None:
        return (
            f"{slot['system']} {slot['waypoint']} {level}: CTOT {slot['ctot'] or 'not found'}, "
            f"CTO {slot['cto'] or 'not found'}; ACTM for {slot['waypoint']} not found in the OFP{pages}."
        )
    difference = slot["difference_minutes"]
    delta = "matches CTO" if difference == 0 else f"{abs(difference)} min {'before' if difference < 0 else 'after'} CTO"
    return (
        f"{slot['system']} {slot['waypoint']} {level}: CTOT {slot['ctot']} + ACTM {slot['actm']} = "
        f"{slot['computed_cto']}, {delta} {slot['cto']}{pages}."
    )


# ---------------------------------------------------------------- the composition


def compose_enroute_contact(flight: dict[str, Any] | None, findings: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    source = flight if isinstance(flight, dict) else {}
    crossings = _crossings(source)
    route = _route(source)
    departure = _utc(source.get("scheduled_departure_utc"))
    records = [r for r in source.get("notam_procedure_records") or [] if isinstance(r, dict)]
    names = _fir_names(source, records)
    procedures: list[dict[str, Any]] = []
    other_procedure_count = 0
    for record in records:
        composed = _compose_procedure(record, route, crossings, names, departure)
        if composed is None:
            other_procedure_count += 1
        else:
            procedures.append(composed)
    procedures.sort(key=_time_order)

    required_calls: list[dict[str, Any]] = []
    for item in findings or []:
        if not isinstance(item, dict) or item.get("engine") != "communications":
            continue
        data = item.get("data") if isinstance(item.get("data"), dict) else {}
        minutes = _integer(data.get("action_actm_minutes"))
        if minutes is None:
            continue
        required_calls.append({
            "title": _normalise(item.get("title")),
            "summary": _normalise(item.get("summary")),
            "details": [_normalise(d) for d in (item.get("details") if isinstance(item.get("details"), list) else []) if _normalise(d)],
            "actm": actm_text(minutes),
            "actm_minutes": minutes,
        })

    source_pages = sorted({row["source_page"] for row in crossings if row["source_page"] is not None})
    voice = sum(1 for row in procedures if row["kind"] in ("voice_contact", "tiba_broadcast"))
    met = sum(1 for row in procedures if row["applicability_state"] == "conditions_held")
    unresolved = sum(1 for row in procedures if row["applicability_state"] == "conditions_unresolved")
    not_applicable = sum(1 for row in procedures if row["applicability_state"] == "not_applicable")
    if required_calls:
        state = "library_rules_held"
        state_sentence = f"{len(required_calls)} early-call requirement(s) from the approved reference library."
    elif procedures:
        state = "source_procedures_held"
        state_sentence = (
            f"No approved early-call rule is held. {len(procedures)} source-held communication notice(s) on the parsed route "
            f"({voice} voice/broadcast, {len(procedures) - voice} datalink): printed conditions met on {met}, unresolved on {unresolved}, "
            f"not applicable on {not_applicable}. Frequencies and lead times are the source's own printed values; none is inferred from crossing times."
        )
    elif crossings:
        state = "no_procedure_held"
        state_sentence = STATE_SENTENCES[state]
    else:
        state = "no_fir_rows_held"
        state_sentence = STATE_SENTENCES[state]

    notam_pages = sorted({row["source_page"] for row in procedures if row["source_page"] is not None})
    if crossings:
        provenance = f"FPL {_page_range(source_pages) or 'page not held'}"
        if notam_pages:
            provenance += f" / NOTAM {_page_range(notam_pages)}"
    else:
        provenance = "FPL boundary rows not held"

    slot = _slot_control(source)
    return {
        "rule": ENROUTE_CONTACT_RULE,
        "state": state,
        "state_sentence": state_sentence,
        "crossings": crossings,
        "crossing_sequence": " · ".join(f"{row['fir']} {row['actm']}" for row in crossings),
        "source_pages": source_pages,
        "procedures": procedures,
        "procedure_lines": procedure_lines(procedures),
        "other_procedure_count": other_procedure_count,
        "required_calls": required_calls,
        "slot_control": slot,
        "slot_sentence": slot_sentence(slot),
        "provenance": provenance,
    }


def crossing_sequence_limited(crossings: list[dict[str, Any]], limit: int = 24) -> str:
    """The PDF's whole-pair prefix rule: never a cut pair; the deferral is stated."""
    pairs = [f"{row['fir']} {row['actm']}" for row in crossings]
    if len(pairs) <= limit:
        return " · ".join(pairs)
    return " · ".join(pairs[:limit]) + f" · +{len(pairs) - limit} more (ordered list with derived UTC on the dashboard)"

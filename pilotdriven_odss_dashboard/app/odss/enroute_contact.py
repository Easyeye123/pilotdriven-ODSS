"""Early ATC / FIR calls - the concise, source-governed record (PDF side).

The dashboard rule is web/src/lib/enroute-contact.mjs; this is the same rule
in Python, pinned to it token for token by the app's
tests/fixtures/enroute-contact-vectors.json. Read that file's header for the
boss's words (27 Jul, 30 Jul, 24 Sep 2026) and the non-inference contract.

What is composed, and from what the analysis already holds:
  crossings       route_waypoints[].fir_boundary + actm_minutes, in OFP order,
                  a repeated FIR named a re-entry, with the source page;
  procedures      notam_procedure_records whose FIR heading is on the parsed
                  route, quoted (first instruction sentence), identified
                  (NOTAM id, page), classified by their own instruction
                  (contact/logon vs other datalink), applicability not
                  inferred; David's governed note for the one recognised
                  Jakarta AFN procedure;
  required_calls  approved-reference-library findings (none is approved
                  today, so none prints);
  slot_control    flight.bobcat with the CTOT + ACTM reconciliation the engine
                  performs, and the OFP pages;
  state           library_rules_held | source_procedures_held |
                  no_procedure_held | no_fir_rows_held, each with one factual
                  sentence and no reminder wording (R2).
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any

ENROUTE_CONTACT_RULE = "enroute-contact-v1"

JAKARTA_AFN_NOTE = "CPDLC limited trial: pilot initiates AFN logon only when requested by ATC; address WIIF."
_JAKARTA_TOKENS = ("ADS-C/CPDLC", "REQUESTED BY ATC", "AFN LOGON", "ADDRESS FOR JAKARTA FIR IS WIIF")

_CONTACT_LOGON = re.compile(
    r"\bAFN LOGON\b|\bLOG[- ]?ON\b|\bINITIAL CONTACT\b|\bCONTACT\b[^.;]{0,60}\b(?:PRIOR|BEFORE)\b"
    r"|\b(?:PRIOR TO|BEFORE) ENTERING\b|\bENTERING\b[^.;]{0,40}\b(?:CONTACT|LOGON)\b"
)
_DATALINK = re.compile(r"\bCPDLC\b|\bADS-C\b")
# A sentence ends at "." or ";" after a word of two or more characters; a list marker ("A.", "1.") does not end one.
_SENTENCE_SPLIT = re.compile(r"(?<=\S\S[.;])\s+")
_FIR_HEADING = re.compile(r"^([A-Z]{4})\b")

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


def contact_procedure_kind(text: Any) -> str:
    """The notice's own instruction decides the kind; its FIR or region never does."""
    return "contact_logon" if _CONTACT_LOGON.search(_normalise(text).upper()) else "datalink_other"


def contact_instruction(text: Any) -> str:
    """The first printed sentence carrying the instruction (a verbatim substring of the source)."""
    clean = _normalise(text)
    if not clean:
        return ""
    sentences = _SENTENCE_SPLIT.split(clean)
    hit = (
        next((s for s in sentences if _CONTACT_LOGON.search(s.upper())), None)
        or next((s for s in sentences if _DATALINK.search(s.upper())), None)
        or sentences[0]
    )
    return hit.strip()


def shorten(text: Any, limit: int = 160) -> str:
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
    """His provenance style: "p12", a contiguous run "pp8-14", otherwise the pages listed."""
    if not pages:
        return ""
    if len(pages) == 1:
        return f"p{pages[0]}"
    contiguous = all(page == pages[index - 1] + 1 for index, page in enumerate(pages) if index)
    return f"pp{pages[0]}-{pages[-1]}" if contiguous else ", ".join(f"p{page}" for page in pages)


def procedure_lines(procedures: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One printed row per FIR crossing and procedure text; notices that carry the same procedure share the row."""
    lines: list[dict[str, Any]] = []
    for row in procedures:
        text = row["note"] or row["instruction_short"]
        line = next((item for item in lines if item["fir"] == row["fir"] and item["text"] == text), None)
        if line is not None:
            if row["notam_id"] not in line["notam_ids"]:
                line["notam_ids"].append(row["notam_id"])
            if row["source_page"] is not None and row["source_page"] not in line["source_pages"]:
                line["source_pages"].append(row["source_page"])
            if row["kind"] == "contact_logon":
                line["kind"] = "contact_logon"
            continue
        lines.append({
            "fir": row["fir"], "actm": row["actm"], "sequence": row["sequence"], "text": text, "kind": row["kind"],
            "notam_ids": [row["notam_id"]], "source_pages": [row["source_page"]] if row["source_page"] is not None else [],
        })
    for line in lines:
        line["source_pages"].sort()
    return lines


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
    row = next(
        (w for w in flight.get("route_waypoints") or [] if isinstance(w, dict) and str(w.get("name") or "").upper() == waypoint),
        None,
    )
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


def compose_enroute_contact(flight: dict[str, Any] | None, findings: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    source = flight if isinstance(flight, dict) else {}
    crossings: list[dict[str, Any]] = []
    seen: set[str] = set()
    for waypoint in source.get("route_waypoints") or []:
        if not isinstance(waypoint, dict):
            continue
        fir = _normalise(waypoint.get("fir_boundary")).upper()
        minutes = _integer(waypoint.get("actm_minutes"))
        if not fir or minutes is None:
            continue
        crossings.append({
            "sequence": len(crossings) + 1,
            "fir": fir,
            "actm": actm_text(minutes),
            "actm_minutes": minutes,
            "source_page": _integer(waypoint.get("source_page")),
            "reentry": fir in seen,
            "utc": None,
            "day": "",
        })
        seen.add(fir)
    first_by_fir: dict[str, dict[str, Any]] = {}
    for row in crossings:
        first_by_fir.setdefault(row["fir"], row)
    source_pages = sorted({row["source_page"] for row in crossings if row["source_page"] is not None})

    procedures: list[dict[str, Any]] = []
    other_procedure_count = 0
    for record in source.get("notam_procedure_records") or []:
        if not isinstance(record, dict):
            continue
        match = _FIR_HEADING.match(_normalise(record.get("heading")).upper())
        fir = match.group(1) if match else ""
        first = first_by_fir.get(fir) if fir else None
        if not first:
            other_procedure_count += 1
            continue
        text = _normalise(record.get("text"))
        instruction = contact_instruction(text)
        procedures.append({
            "fir": fir,
            "notam_id": _normalise(record.get("notam_id")).upper(),
            "source_page": _integer(record.get("source_page")),
            "validity": _normalise(record.get("validity")),
            "kind": contact_procedure_kind(text),
            "instruction": instruction,
            "instruction_short": shorten(instruction),
            "note": _governed_note(record),
            "actm": first["actm"],
            "sequence": first["sequence"],
            "on_route": True,
            "applicability": "not_inferred",
        })
    procedures.sort(key=lambda row: (row["sequence"], row["notam_id"]))

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
            "actm": actm_text(minutes),
            "actm_minutes": minutes,
        })

    if required_calls:
        state = "library_rules_held"
        state_sentence = f"{len(required_calls)} early-call requirement(s) from the approved reference library."
    elif procedures:
        state = "source_procedures_held"
        state_sentence = (
            f"No approved early-call rule is held. {len(procedures)} FIR datalink/contact notice(s) are held in this OFP "
            "for FIRs on the parsed route; lead times and frequencies are not held and are not inferred from crossing times."
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

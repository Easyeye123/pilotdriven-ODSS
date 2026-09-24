"""ATC-RADIO-SOURCE-418 (independent production QA of release 418, 24 Sep 2026).

F1: the genuine SQ366 OFP prints voice / TIBA / contact instructions on pp88-89
(1G216/26, 1G197/26, 1G220/26 under Kabul FIR and segment headings, AX1/23
under ENRON/RANAHL750) and SQ23 prints 1G216/26 and 1G197/26 on pp108-109,
while the restored panel and the six-page PDF said lead times and frequencies
were not held. Common cause: `_parse_notam_procedure_records` admitted only
records under a named FIR heading that print CPDLC / ADS-C, so voice-only and
airway-headed procedures never reached the composed record, and the composer
then asserted a blanket absence.

The general rule replacing it (no flight, FIR, notice or frequency is special-
cased; every answer is derived from the uploaded source):
  headings   FIR ("OAKX  KABUL FIR"), airway segment ("ENRON/RANAHL750",
             "ZB    /BIROSL750"), NOTAM-series labels ("UT O0287/26" - a
             continuation, the heading stays), airports and anything else
             (excluded, as before);
  admission  any printed communication instruction - contact / call /
             report / monitor with a unit or frequency, TIBA / broadcast /
             transmission, logon, CPDLC / ADS-C - with OCR-split words joined
             for the test only; the quote stays verbatim;
  record     identity, validity, heading, heading kind, FIR (from the
             heading), segment (waypoints + airway), page, text, and the
             parser's holding contract `applicability: not_inferred`.
The composition (enroute_contact.py = enroute-contact.mjs, vector-pinned)
then associates each record to a crossing from the OFP itself (FIR heading;
an ICAO/NAME FIR pair in the body; the FIR in effect at the segment's
waypoints on the parsed route), evaluates the conditions the notice prints
against the OFP's own facts (validity window vs the crossing time, overflight
vs aerodrome scope, direction between named FIRs, named route segments, the
planned level band, unresolvable temporary-purpose markers), quotes the
scope-compatible instruction with the source's own printed frequencies and
lead times, and keeps every unresolved or not-applicable state explicit.

F2: approved-library findings keep `finding.details` (action / frequency /
backup / lead / notes) on both surfaces; the library stays unapproved.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import fitz
import pytest

from app.analysis import run_odss_analysis
from app.odss import reference_conformance as conformance
from app.odss.combined_brief import render_combined_briefing
from app.odss.concise_pdf_gate import normalized
from app.odss.enroute_contact import compose_enroute_contact, primary_procedure_line, procedure_kind
from app.odss.parser import _detect_sections, _parse_notam_procedure_records, extract_pages
from tests.test_r2_reminder_wording import david_format_labels, reminder_lines, source_quotations

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT.parent / "private_cfp_corpus"
MANIFEST_PATH = ROOT / "tests" / "boss_reference_format_manifest.json"
SOURCES = {"SQ366": "SQ36604082026SIN.pdf", "SQ23": "SQ02325072026JFK.pdf", "SQ882": "lido-briefing_SQ_882_10Sep2026_SIN_HKG.pdf"}
ENROUTE_PAGE = 5

_PAGES: dict[str, list[str]] = {}
_RENDERED: dict[str, dict] = {}


def genuine_pages(key: str) -> list[str]:
    if key not in _PAGES:
        source = CORPUS / SOURCES[key]
        if not source.is_file():
            pytest.skip(f"private CFP corpus file {SOURCES[key]} is not available")
        _PAGES[key] = extract_pages(source)
    return _PAGES[key]


def genuine_procedures(key: str) -> list[dict]:
    pages = genuine_pages(key)
    return _parse_notam_procedure_records(pages, _detect_sections(pages).get("notam"))


def rendered(key: str, tmp_path_factory) -> dict:
    if key in _RENDERED:
        return _RENDERED[key]
    source = CORPUS / SOURCES[key]
    if not source.is_file():
        pytest.skip(f"private CFP corpus file {SOURCES[key]} is not available")
    root = tmp_path_factory.mktemp(f"atc-{key}")
    result = run_odss_analysis(source, root / "analysis", root / "reports", 1)
    payload = json.loads(Path(result["analysis_path"]).read_text(encoding="utf-8"))
    path = root / f"{key}_Flight_Briefing.pdf"
    render_combined_briefing(
        payload["flight"], payload["findings"], payload.get("view", {}).get("warnings") or [], path,
        source_pdf_path=str(source), weather_charts=payload.get("weather_charts") or {},
    )
    with fitz.open(path) as document:
        pages = [page.get_text() for page in document]
    _RENDERED[key] = {"payload": payload, "path": path, "pages": pages, "folded": [normalized(p) for p in pages]}
    return _RENDERED[key]


def by_id(records: list[dict], identity: str) -> dict:
    match = [r for r in records if r["notam_id"] == identity]
    assert match, f"{identity} not among {[r['notam_id'] for r in records]}"
    return match[0]


# ---------------------------------------------------------------- the parser (F1 extraction)


def test_sq366_source_admits_the_voice_tiba_and_contact_procedures_the_ofp_prints():
    records = genuine_procedures("SQ366")
    ids = {r["notam_id"] for r in records}
    assert {"1G216/26", "1G197/26", "1G220/26", "AX1/23", "1A1891/26", "SX50/25", "1G803/26"} <= ids
    # Not communication instructions: transponder, spacing, permissions, route closures, a prohibition.
    assert not {"1G218/26", "1G199/26", "1G223/26", "1O288/26", "1O275/26", "1G269/26", "1G217/26"} & ids
    tiba = by_id(records, "1G216/26")
    assert tiba["heading"] == "OAKX KABUL FIR" and tiba["heading_kind"] == "fir" and tiba["fir"] == "OAKX"
    assert tiba["source_page"] == 88 and tiba["validity"] == "10-JUN-26 0600 - 05-SEP-26 2359 EST"
    assert "BROADCAST INTENTIONS ON FREQ 125.2MHZ 10 MINS PRIOR ENTERING TO FIR" in tiba["text"]
    contact = by_id(records, "1G197/26")
    assert contact["fir"] == "OAKX" and "NOT LESS THAN 15 MINUTES BEFORE THE FIR BOUNDARY POINT" in contact["text"]
    # A segment heading: waypoints and airway are kept, the FIR is not guessed from the previous heading.
    routes = by_id(records, "1G220/26")
    assert routes["heading"] == "BIROS/GODSIL750" and routes["heading_kind"] == "segment"
    assert routes["segment"] == {"from": "BIROS", "to": "GODSI", "airway": "L750"} and routes["fir"] is None
    # The record continues over the page break (p88 -> p89): both halves are held.
    assert "TRANSMISSION SHALL TAKE PLACE EVERY 5 MINUTES ON TIBA FREQ 125.2MHZ" in routes["text"]
    assert "FOR THE TEMPORARY PURPOSE ONLY" in routes["text"] and routes["source_page"] == 88
    aic = by_id(records, "AX1/23")
    assert aic["heading"] == "ENRON/RANAHL750" and aic["segment"] == {"from": "ENRON", "to": "RANAH", "airway": "L750"}
    assert aic["source_page"] == 89 and aic["validity"] == "12-JUL-23 0000 - UFN"
    assert "CON TACT WITH TURKMENABAT-CTL ON 134.5 MHZ" in aic["text"], "the source spelling is kept verbatim"
    for record in records:
        assert record["applicability"] == "not_inferred", "the parser's holding contract is unchanged"
        assert record["heading"] and record["source_page"] and record["text"]


def test_sq366_source_fir_names_are_read_from_its_own_headings():
    pages = genuine_pages("SQ366")
    from app.odss.parser import _parse_notam_fir_names
    names = _parse_notam_fir_names(pages, _detect_sections(pages).get("notam"))
    assert names["OAKX"] == "KABUL" and names["WIIF"] == "JAKARTA" and names["LIRR"] == "ROME"
    assert "UTAV" not in names, "Turkmenabat has no FIR heading in this OFP; its name comes from the AX1/23 body"


def test_sq23_source_admits_the_kabul_instructions_and_the_opposite_direction_turkmenabat_notice():
    records = genuine_procedures("SQ23")
    ids = {r["notam_id"] for r in records}
    assert {"1G216/26", "1G197/26", "1G220/26", "1G272/26", "1A1531/26", "SX33/26", "AX1/23"} <= ids
    assert by_id(records, "1G216/26")["source_page"] == 108 and by_id(records, "1G197/26")["fir"] == "OAKX"
    routes = by_id(records, "1G220/26")
    assert routes["heading"] == "LEMOD/PAGMAN644" and routes["segment"] == {"from": "LEMOD", "to": "PAGMA", "airway": "N644"}
    assert "FOR THE TEMPORARY PURPOSE ONLY" in routes["text"]
    # The reviewer's excerpt covered pp108-109; the same OFP also prints the Turkmenabat AIC on p107 under the
    # airway heading of this flight's direction (A909 NINOP-LEMOD). It is held; the composition decides its direction.
    aic = by_id(records, "AX1/23")
    assert aic["heading"] == "NINOP/LEMODA909" and aic["segment"] == {"from": "NINOP", "to": "LEMOD", "airway": "A909"} and aic["source_page"] == 107
    karachi = by_id(records, "SX33/26")
    assert karachi["heading"] == "OPLR LAHORE FIR" and "SHALL CTC KARACHI, LAHORE OR ISLAMABAD ACC AT LEAST 15 MIN PRIOR TO ENTERING" in karachi["text"]
    # Not communication instructions: a phone number to call, GNSS-jamming vigilance, VOR selection, spoofed-call caution.
    assert not {"1A141/25", "1A412/26", "1A1533/26", "1A582/26"} & ids


def test_synthetic_layouts_series_label_continuation_ocr_split_and_airport_exclusion():
    pages = [
        "SUMMARY CFP",
        (
            "NOTAM\n\nZAMIR/KEMORB449\n---------------\n"
            "            UT O0287/26\n-----------------------\n"
            "1O287/26 VALID: 03-AUG-26 0200 - 31-AUG-26 1700\n"
            "  ACFT ENTERING THE SECTOR SHALL ESTABLISH CON TACT WITH SYNTH-CTL ON 123.45 MHZ 10 MIN PRIOR.\n"
            "WSSS /SIN SINGAPORE/CHANGI - DETAILED INFO\n--------------------------------------------\n"
            "1A2382/26 VALID: 08-AUG-26 0000 - PERM\n  CONTACT TOWER ON 118.6MHZ BEFORE START.\n"
            "XXXX        NOWHERE FIR\n-----------------------\n"
            "1X1/26 VALID: 01-JAN-26 0000 - PERM\n  SSR TRANSPONDERS SHALL BE OPERATED AT ALL TIMES.\n"
        ),
    ]
    records = _parse_notam_procedure_records(pages, (1, 2))
    assert [r["notam_id"] for r in records] == ["1O287/26"]
    assert records[0]["heading"] == "ZAMIR/KEMORB449", "a NOTAM-series label under a segment heading is a continuation, not a new section"
    assert records[0]["segment"] == {"from": "ZAMIR", "to": "KEMOR", "airway": "B449"}
    assert "CON TACT" in records[0]["text"]
    assert procedure_kind(records[0]["text"]) == "voice_contact", "OCR-split CON TACT is recognised for classification"


def test_the_kind_is_decided_by_the_printed_instruction_only():
    assert procedure_kind("ALL OVERFLIGHTS SHALL COMPLY WITH TIBA PROCEDURE FOR BROADCAST INTENTIONS ON FREQ 125.2MHZ") == "tiba_broadcast"
    assert procedure_kind("FLIGHTS DEPARTING THE KABUL FIR SHALL CONTACT THE RELEVANT ACC IN THE NEXT FIR ENTERED") == "voice_contact"
    assert procedure_kind("MUST ESTABLISH CON TACT WITH TURKMENABAT-CTL ON 134.5 MHZ FREQ") == "voice_contact"
    assert procedure_kind("AFN LOGON PROCESS WILL BE INITIATED BY THE PILOT") == "contact_logon"
    assert procedure_kind("ADS-C/CPDLC OPERATIONAL TRIAL ... 10 MINUTES SEPARATION") == "datalink_other"
    assert procedure_kind("ALL TFC ENTERING KARACHI AND LAHORE FIRS FM KABUL FIR SHALL CTC KARACHI, LAHORE OR ISLAMABAD ACC AT LEAST 15 MIN PRIOR") == "voice_contact"
    assert procedure_kind("SSR TRANSPONDERS SHALL BE OPERATED AT ALL TIMES. SQUAWK A2000.") is None
    assert procedure_kind("RADIOTELEPHONY CALL SIGN ASSIGNED TO AD OPERATOR") is None
    # Found by running the rule over all 28 corpus OFPs: none of these is an instruction to the crew.
    assert procedure_kind("FOR QUESTIONS, CALL BOSTON/ZBW/ARTCC TM TFC MANAGEMENT 1-603-879-6666.") is None
    assert procedure_kind("AIR CREWS TO REMAIN VIGILANT AND REPORT TO ATC.") is None
    assert procedure_kind("FLIGHT CREWS ARE ADVISED TO MONITOR THE CORRECT SELECTION OF THE VOR FOR EN-ROUTE OPERATIONS.") is None
    assert procedure_kind("TIMELY UPDATES REGARDING THE ZONES AND AREAS AFFECTED CAN BE BROADCAST ON GROUND/AIR/GROUND FREQUENCIES.") is None
    assert procedure_kind("FOR AVAILABILITY OF FLT LEVELS AND TIBA PROCEDURES IN KABUL FIR SEE LATEST NOTAM ISSUED BY KABUL NOF IN THIS REGARD.") is None
    assert procedure_kind("PILOTS SHALL DISREGARD ANY NON-STANDARD CALLS AND IF IN DOUBT, VERIFY THE CALL AND REPORT TIME, LOCATION AND FL OF THE OCCURRENCE TO ATC UNIT IN CTC.") is None
    assert procedure_kind("IT IS HIGHLY RECOMMENDED THAT A PILOT CONTINUOUSLY MONITOR VHF FREQUENCY 121.5 OR UHF FREQUENCY 243.0 FOR EMERGENCY INSTRUCTIONS") == "voice_contact"


# ---------------------------------------------------------------- the composition (F1 association, applicability, details)


def test_sq366_composition_publishes_the_source_held_calls_with_their_printed_conditions(tmp_path_factory):
    case = rendered("SQ366", tmp_path_factory)
    composed = case["payload"]["view"]["briefing"]["enroute_contact"]
    assert composed == compose_enroute_contact(case["payload"]["flight"], case["payload"]["findings"])
    rows = {row["notam_id"]: row for row in composed["procedures"]}
    tiba = rows["1G216/26"]
    assert tiba["kind"] == "tiba_broadcast" and tiba["fir"] == "OAKX" and tiba["actm"] == "05:35" and tiba["association"] == "fir_heading"
    assert tiba["applicability_state"] == "conditions_held"
    assert tiba["printed_details"]["frequencies"] == ["125.2MHZ"]
    assert tiba["printed_details"]["lead"] == "10 MINS PRIOR ENTERING TO FIR"
    assert tiba["latest_actm"] == "05:25", "the source's own 10-minute lead before the OAKX boundary at 05:35"
    assert tiba["instruction"].startswith("ALL OVERFLIGHTS SHALL COMPLY WITH TIBA PROCEDURE FOR BROADCAST INTENTIONS ON FREQ 125.2MHZ 10 MINS PRIOR ENTERING TO FIR")
    assert {c["kind"]: c["result"] for c in tiba["conditions"]} == {"validity": "met", "scope": "met"}
    contact = rows["1G197/26"]
    assert contact["kind"] == "voice_contact" and contact["fir"] == "OAKX"
    assert contact["next_fir"] == {"fir": "UTAV", "actm": "06:22"}
    assert contact["printed_details"]["lead"] == "NOT LESS THAN 15 MINUTES BEFORE THE FIR BOUNDARY POINT" and contact["printed_details"]["frequencies"] == []
    assert contact["latest_actm"] == "06:07"
    assert contact["applicability_state"] == "conditions_held"
    routes = rows["1G220/26"]
    assert routes["association"] == "segment_on_route" and routes["fir"] == "OAKX" and routes["actm"] == "05:35"
    assert routes["applicability_state"] == "conditions_unresolved"
    results = {c["kind"]: c["result"] for c in routes["conditions"]}
    assert results["validity"] == "met" and results["scope"] == "met" and results["route"] == "met" and results["level"] == "met" and results["other"] == "unresolved"
    assert routes["printed_details"]["frequencies"] == ["125.2MHZ"] and routes["printed_details"]["interval"] == "EVERY 5 MINUTES"
    aic = rows["AX1/23"]
    assert aic["kind"] == "voice_contact" and aic["association"] == "body_fir" and aic["fir"] == "UTAV" and aic["actm"] == "06:22"
    assert aic["printed_details"]["frequencies"] == ["134.5 MHZ", "128.5 MHZ"]
    assert aic["printed_details"]["lead"] == "WI 10 MIN. TO THE ENTRANCE TO THE FIR"
    assert aic["latest_actm"] == "06:12"
    results = {c["kind"]: c["result"] for c in aic["conditions"]}
    assert results["validity"] == "met" and results["direction"] == "met" and results["route"] == "met"
    assert aic["applicability_state"] == "conditions_held"
    assert "CON TACT WITH TURKMENABAT-CTL ON 134.5 MHZ FREQ (BACKUP FREQ 128.5 MHZ)" in aic["instruction"]
    assert rows["1A1891/26"]["kind"] == "contact_logon" and rows["1G803/26"]["kind"] == "datalink_other"
    # The Karachi contingency supplement is for traffic entering Karachi / Lahore FROM Kabul; this flight flies the other way.
    karachi = rows["SX33/26"]
    assert karachi["kind"] == "voice_contact" and karachi["fir"] == "OPKR" and karachi["applicability_state"] == "not_applicable"
    assert {c["kind"]: c["result"] for c in karachi["conditions"]} == {"validity": "met", "direction": "not_met", "route": "met"}
    assert next(c for c in karachi["conditions"] if c["kind"] == "direction")["text"] == "OAKX → OPKR/LAHORE"
    assert karachi["printed_details"]["lead"] == "AT LEAST 15 MIN PRIOR TO ENTERING KARACHI OR LAHORE FIR"
    # The aerodrome TIBA notice (arrival / departure operations) does not apply to an overflight.
    aerodrome = rows["1G272/26"]
    assert aerodrome["applicability_state"] == "not_applicable" and any(c["kind"] == "scope" and c["result"] == "not_met" for c in aerodrome["conditions"])
    assert set(rows) == {"1A1891/26", "SX50/25", "1G803/26", "SX33/26", "1G272/26", "1G216/26", "1G197/26", "1G220/26", "AX1/23"}
    assert composed["state"] == "source_procedures_held"
    assert composed["state_sentence"] == (
        "No approved early-call rule is held. 9 source-held communication notice(s) on the parsed route "
        "(6 voice/broadcast, 3 datalink): printed conditions met on 6, unresolved on 1, not applicable on 2. "
        "Frequencies and lead times are the source's own printed values; none is inferred from crossing times."
    )
    assert composed["other_procedure_count"] == 1, "the Vienna CPDLC logon notice is held but LOVV is not on this route; the firefighting, VOR and spoofed-call notices are not instructions"
    assert composed["provenance"] == "FPL pp8-14 / NOTAM p67, pp85-89"
    # Display rows fall due in time order: the latest ACTM a printed lead gives, else the boundary ACTM.
    lines = composed["procedure_lines"]
    anchors = [line["latest_actm"] or line["actm"] for line in lines]
    assert anchors == sorted(anchors), anchors
    assert [line["notam_ids"][0] for line in lines if line["fir"] == "OAKX"] == ["1G216/26", "1G220/26", "1G272/26", "1G197/26"]
    assert primary_procedure_line(lines)["notam_ids"] == ["1G216/26"], "the first call row that prints a frequency (page 6 always prints it)"
    assert all(line["applicability_state"] and line["conditions_summary"] for line in lines)


def test_sq23_composition_keeps_the_opposite_direction_control_distinct(tmp_path_factory):
    case = rendered("SQ23", tmp_path_factory)
    composed = case["payload"]["view"]["briefing"]["enroute_contact"]
    assert composed == compose_enroute_contact(case["payload"]["flight"], case["payload"]["findings"])
    rows = {row["notam_id"]: row for row in composed["procedures"]}
    crossed = {row["fir"] for row in composed["crossings"]}
    tiba, contact = rows["1G216/26"], rows["1G197/26"]
    assert tiba["fir"] == "OAKX" and tiba["actm"] == "11:18" and tiba["applicability_state"] == "conditions_held"
    assert tiba["printed_details"]["frequencies"] == ["125.2MHZ"] and tiba["latest_actm"] == "11:08"
    assert contact["fir"] == "OAKX" and contact["applicability_state"] == "conditions_held"
    assert contact["next_fir"] == {"fir": "OPLR", "actm": "11:56"} and contact["latest_actm"] == "11:41"
    aerodrome = rows["1G272/26"]
    assert aerodrome["applicability_state"] == "not_applicable"
    assert any(c["kind"] == "scope" and c["result"] == "not_met" for c in aerodrome["conditions"]), "arrival/departure aerodrome instruction; this flight overflies OAKX"
    assert rows["1G220/26"]["fir"] in crossed and rows["1G220/26"]["association"] == "segment_on_route"
    # The Turkmenabat AIC names Kabul FIR -> Turkmenabat FIR; this flight crosses UTAV before OAKX, so it is not applicable here.
    aic = rows["AX1/23"]
    assert aic["association"] == "body_fir" and aic["fir"] == "UTAV" and aic["applicability_state"] == "not_applicable"
    assert {c["kind"]: c["result"] for c in aic["conditions"]} == {"validity": "met", "direction": "not_met", "route": "met"}
    assert aic["printed_details"]["frequencies"] == ["134.5 MHZ", "128.5 MHZ"], "the printed values are kept even where the notice does not apply"
    # The Karachi contingency table: traffic entering Lahore FIR from Kabul via N644 DOBAT contacts Lahore ACC West.
    karachi = rows["SX33/26"]
    assert karachi["fir"] == "OPLR" and karachi["association"] == "fir_heading" and karachi["applicability_state"] == "conditions_held"
    assert {c["kind"]: c["result"] for c in karachi["conditions"]} == {"validity": "met", "direction": "met", "route": "met"}
    assert next(c for c in karachi["conditions"] if c["kind"] == "route")["text"] == "N644 DOBAT LAHORE ACC WEST 124.100 MHZ 118.950 MHZ"
    assert karachi["printed_details"] == {"frequencies": ["124.100 MHZ", "118.950 MHZ"], "lead": "AT LEAST 15 MIN PRIOR TO ENTERING KARACHI OR LAHORE FIR", "interval": None}
    assert karachi["latest_actm"] == "11:41"


def test_sq882_composition_still_states_the_genuine_absence(tmp_path_factory):
    case = rendered("SQ882", tmp_path_factory)
    composed = case["payload"]["view"]["briefing"]["enroute_contact"]
    assert composed["procedures"] == [] and composed["state"] == "no_procedure_held"
    assert composed["state_sentence"] == "No early-contact requirement is held in this OFP's FIR notices or in an approved reference; lead times and frequencies are not held and are not inferred from crossing times."


def test_consecutive_duplicate_boundary_rows_are_repeated_rows_not_re_entries(tmp_path_factory):
    case = rendered("SQ366", tmp_path_factory)
    composed = case["payload"]["view"]["briefing"]["enroute_contact"]
    lirr = [row for row in composed["crossings"] if row["fir"] == "LIRR"]
    assert len(lirr) == 2 and lirr[0]["reentry"] is False and lirr[0]["repeated"] is False
    assert lirr[1]["repeated"] is True and lirr[1]["reentry"] is False, "the source prints LIRR twice with no FIR between; that is a repeated row, not an exit and re-entry"
    wsjc = [row for row in composed["crossings"] if row["fir"] == "WSJC"]
    assert wsjc[1]["reentry"] is True and wsjc[1]["repeated"] is False, "WMFC intervenes, so the second WSJC row is a re-entry"


# ---------------------------------------------------------------- F2: approved-library details survive


REVIEWER_SYNTHETIC_FINDING = {
    "engine": "communications",
    "title": "Early ATC/FIR action before TEST",
    "summary": "ACTM 00.20 - SYNTHETIC agency.",
    "details": ["Boundary ACTM 00.30; lead 10 min.", "Action: SYNTHETIC CONTACT ACTION.", "Frequency SYNTHETIC-FREQUENCY; backup SYNTHETIC-BACKUP."],
    "data": {"action_actm_minutes": 20, "reference_status": "approved", "reference_library_version": "SYNTHETIC-QA"},
}


def test_approved_rule_details_are_kept_by_the_composition():
    flight = {"route_waypoints": [{"name": "TEST", "fir_boundary": "TEST", "actm_minutes": 30, "source_page": 1}]}
    composed = compose_enroute_contact(flight, [REVIEWER_SYNTHETIC_FINDING])
    assert composed["state"] == "library_rules_held"
    assert composed["required_calls"][0]["details"] == REVIEWER_SYNTHETIC_FINDING["details"]
    text = json.dumps(composed["required_calls"])
    assert "SYNTHETIC CONTACT ACTION" in text and "SYNTHETIC-FREQUENCY" in text and "SYNTHETIC-BACKUP" in text


# ---------------------------------------------------------------- page 6


def test_sq366_page_six_prints_the_applicable_voice_row_with_the_printed_frequency_and_lead(tmp_path_factory):
    case = rendered("SQ366", tmp_path_factory)
    page, raw = case["folded"][ENROUTE_PAGE], case["pages"][ENROUTE_PAGE]
    assert "FIR / COMMUNICATION" in raw
    assert normalized("No approved early-call rule is held. 9 source-held communication notice(s) on the parsed route") in page
    assert normalized("lead times and frequencies are not held") not in page
    assert normalized("+05:35 OAKX entry.") in page and "125.2MHZ" in raw and "1G216/26" in raw
    assert normalized("10 MINS PRIOR ENTERING TO FIR") in page
    assert normalized("BOBCAT BIROS FL380: CTOT 1752Z + ACTM 05:35 = 2327Z, 1 min before CTO 2328Z (OFP p1, p11).") in page
    assert reminder_lines(raw, source_quotations(case["payload"]), david_format_labels()) == []
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    result = conformance.check_reference_conformance(case["path"], structure=manifest["reference_structure"], contract_extensions=manifest["contract_extensions"])
    assert result["valid"], result["violations"]
    assert len(case["pages"]) == 6

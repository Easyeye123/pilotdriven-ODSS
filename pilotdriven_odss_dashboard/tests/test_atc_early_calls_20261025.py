"""ATC-EARLY-CALLS (25 Oct 2026). David, a line pilot, on his SQ301 MAN-SIN of 24 Oct: "And the early ATC call content
is missing still. That was available at the beginning when I handed over from gpt to you.. over time it went missing".

The brief GPT handed over (SQ303 BRU-SIN, 16 Jul) printed two calls and put both on its timeline: the Kabul TIBA
broadcast on 125.2 MHz 10 minutes before OAKX entry (ACTM 05:11) and the Lahore ACC West contact 15 minutes before
OPLR entry (ACTM 05:52, 124.100 / 118.950 MHz). The OFP's own notices print both; PilotDriven read both.

Root cause (shared design, not a flight): "early call" existed only as an approved reference-library finding. That
library (a hand-typed per-FIR table, constants.COMMUNICATION_RULES) is correctly not approved, so the timeline, the
FIR / NEXT CONTACT tile and the state line had no early call at all, while the OFP's own call instructions were held
only as one more "source-held notice" among 25-35 - ranked on page 6 by a ladder whose last steps keep ONE primary
row and the first untimed service status (CPDLC not available, ATS not provided). On the inbound Kabul route the
Lahore call lost its place to those statuses.

The repair: every crew call row that prints a lead before an entry is an early call, composed once (both runtimes):
its call time from the OFP entry ACTM and the printed lead read as printed (WITHIN 10 MIN is a window ending at the
entry, never "not later than"), the unit the instruction or the table row the filed route selects names, the
frequencies, the lead and the entry. Page 6 prints every timed early call first at every ladder step (generic notices
defer first; a call the page cannot hold whole is named by time, FIR, identity and page), the decision timeline
carries each one, the shared communications list leads with them, and the dashboard lists them first.

Genuine OFPs come from the private CFP corpus (PILOTDRIVEN_PRIVATE_CFP_CORPUS_DIR) and are skipped where not held;
David's SQ301 and the SQ302 of 21 Oct are not corpus members and are read only when that directory holds them.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

import fitz
import pytest

from app.analysis import run_odss_analysis
from app.odss.combined_brief import render_combined_briefing
from app.odss.concise_pdf_gate import normalized

ROOT = Path(__file__).resolve().parents[1]
SOURCES = {
    "SQ301": "SQ30124102026MAN.pdf",                          # David's 24 Oct MAN-SIN (inbound Kabul / Lahore)
    "SQ303": "SQ30316072026BRU 81.pdf",                        # GPT's handed-over brief: same inbound route type
    "SQ304": "lido-briefing_SQ_304_12Jul2026_SIN_BRU.pdf",    # outbound: Kabul, Kabul exit, Turkmenabat
    "SQ23": "SQ02325072026JFK.pdf",                           # inbound via Kabul / Lahore, 36 crossings
    "SQ326": "lido-briefing_SQ_326_16Aug2026_SIN_FRA.pdf",
    "SQ352": "lido-briefing_SQ_352_15Aug2026_SIN_CPH.pdf",
    "SQ302": "SQ30221102026SIN.pdf",                          # outbound SIN-MAN 21 Oct
}
_RENDERED: dict[str, dict] = {}


def _source(key: str) -> Path:
    configured = os.environ.get("PILOTDRIVEN_PRIVATE_CFP_CORPUS_DIR")
    corpus = Path(configured) if configured else ROOT.parent / "private_cfp_corpus"
    if not corpus.is_dir():
        if configured:
            raise FileNotFoundError(f"Configured PILOTDRIVEN_PRIVATE_CFP_CORPUS_DIR is missing: {corpus}")
        pytest.skip("the private CFP corpus is not available")
    source = corpus / SOURCES[key]
    if not source.is_file():
        pytest.skip(f"{SOURCES[key]} is not held in the private CFP corpus")
    return source


def rendered(key: str, tmp_path_factory) -> dict:
    if key in _RENDERED:
        return _RENDERED[key]
    source = _source(key)
    root = tmp_path_factory.mktemp(f"early-calls-{key}")
    result = run_odss_analysis(source, root / "analysis", root / "reports", 1)
    payload = json.loads(Path(result["analysis_path"]).read_text(encoding="utf-8"))
    path = root / f"{key}_Flight_Briefing.pdf"
    render_combined_briefing(payload["flight"], payload["findings"], payload.get("view", {}).get("warnings") or [], path,
                             source_pdf_path=str(source), weather_charts=payload.get("weather_charts") or {})
    with fitz.open(path) as document:
        pages = [page.get_text() for page in document]
    assert len(pages) == 6
    record = (payload.get("view", {}).get("briefing") or {}).get("enroute_contact") or {}
    _RENDERED[key] = {"payload": payload, "record": record, "pages": pages, "folded": [normalized(p) for p in pages]}
    return _RENDERED[key]


def card(case: dict) -> str:
    """Page 6's FIR / COMMUNICATION card, folded, up to the crossing line."""
    page = case["folded"][5]
    return page.split(normalized("FIR / COMMUNICATION"), 1)[1].split(normalized("FIR crossings (OFP ACTM)"), 1)[0]


def timeline(case: dict) -> str:
    """Page 2's FLIGHT-PHASE DECISION TIMELINE, folded."""
    return case["folded"][1].split(normalized("FLIGHT-PHASE DECISION TIMELINE"), 1)[1]


def printed_whole(card_text: str, *parts: str) -> bool:
    """Every part, in order, inside one stretch of the card (an early call printed whole, not scattered)."""
    cursor = 0
    for part in parts:
        found = card_text.find(normalized(part), cursor)
        if found < 0:
            return False
        cursor = found + len(normalized(part))
    return True


# ---------------------------------------------------------------- David's SQ301 and GPT's SQ303 (the inbound route)


@pytest.mark.parametrize("key, tiba, lahore, entries", [
    # SQ301 24 Oct: OAKX entry 06:03, OPLR entry 06:46 (OFP ACTM).
    ("SQ301", "05:53", "06:31", ("06:03", "06:46")),
    # SQ303 16 Jul: GPT printed "ACTM 05:11 ... OAKX entry at RANAH 05:21" and "ACTM 05:52 ... OPLR entry at 06:07".
    ("SQ303", "05:11", "05:52", ("05:21", "06:07")),
])
def test_inbound_kabul_route_prints_the_tiba_broadcast_and_the_lahore_acc_west_call(key, tiba, lahore, entries, tmp_path_factory):
    case = rendered(key, tmp_path_factory)
    text = card(case)
    # The Kabul TIBA broadcast: its time, the frequency, the printed lead and the entry it precedes.
    assert printed_whole(text, f"not later than ACTM {tiba}", "TIBA broadcast", "125.2MHZ", "10 MINS PRIOR ENTERING TO FIR",
                         f"OAKX entry ACTM {entries[0]}"), text
    # The Lahore ACC West contact: the unit and both frequencies the table row for the filed route L750 BIROS gives.
    assert printed_whole(text, f"not later than ACTM {lahore}", "LAHORE ACC WEST", "124.100 MHZ, 118.950 MHZ",
                         "AT LEAST 15 MIN PRIOR TO ENTERING KARACHI OR LAHORE FIR", f"OPLR entry ACTM {entries[1]}",
                         "L750 BIROS", "NOTAM SX33/26"), text
    # Its prerequisite (ATS non-availability in Kabul) is not evaluable from the OFP: it stays unresolved, never "held".
    assert printed_whole(text, "NOTAM SX33/26", "conditions unresolved"), text
    # Both calls are on the decision timeline at their own ACTM.
    line = timeline(case)
    assert normalized("OAKX TIBA") in line and normalized(f"ACTM {tiba}") in line, line
    assert normalized("OPLR CALL") in line and normalized(f"ACTM {lahore}") in line, line


@pytest.mark.parametrize("key", ["SQ301", "SQ303"])
def test_early_calls_precede_generic_communications_notices_on_page_six(key, tmp_path_factory):
    """CPDLC not available / ATS not provided / limited radio coverage rank below the early calls for page space."""
    case = rendered(key, tmp_path_factory)
    text = card(case)
    # The first early-call sentence (the state line's "early call(s)" count is not a call).
    first_call = min((at for at in (text.find(normalized(f"Early call {when}")) for when in ("not later than", "between", "about"))
                      if at >= 0), default=-1)
    assert first_call >= 0, text
    for generic in ("CPDLC AT MAASTRICHT UAC", "ATS IS NOT PROVIDED", "EXPECT LIMITED RADIO COVERAGE", "IRIS SERVICE"):
        position = text.find(normalized(generic))
        assert position < 0 or position > first_call, (generic, text)


@pytest.mark.parametrize("key", ["SQ301", "SQ303", "SQ304", "SQ23", "SQ326", "SQ352", "SQ302"])
def test_every_early_call_the_ofp_prints_is_on_page_six_and_every_timed_one_on_the_timeline(key, tmp_path_factory):
    """Census over the genuine flights: every early call is printed (its sentence, its compact form or - when the page
    cannot hold it whole - named by time, FIR, identity and page); a call with no derived time is quoted or named."""
    from app.odss.enroute_contact import compose_enroute_contact, early_call_sentence, named_early_call, untimed_call_pointer

    case = rendered(key, tmp_path_factory)
    composed = compose_enroute_contact(case["payload"]["flight"], case["payload"]["findings"])
    text = card(case)
    line = timeline(case)
    for call in composed["early_calls"]:
        if call["call_window"]:
            forms = (early_call_sentence(call), early_call_sentence(call, compact=True), named_early_call(call))
            assert any(normalized(form) in text for form in forms), (call["notam_ids"], text)
            assert normalized(f"ACTM {call['due_actm']}") in line, (call["notam_ids"], line)
        else:
            assert normalized(untimed_call_pointer(call)) in text or normalized(call["text"]) in text, (call["notam_ids"], text)
    # The published record is the composed one (the dashboard and page 6 read it).
    assert case["record"]["early_calls"] == composed["early_calls"]


@pytest.mark.parametrize("key, expected", [
    # Release 452 printed these calls; each still prints with its frequencies and time.
    ("SQ304", (("1G216/26", "125.2MHZ", "not later than ACTM 05:22"), ("AX1/23", "134.5 MHZ, 128.5 MHZ", "between ACTM 06:09 and ACTM 06:19"))),
    ("SQ352", (("1G216/26", "125.2MHZ", "not later than ACTM 05:25"), ("AX1/23", "134.5 MHZ, 128.5 MHZ", "between ACTM 06:05 and ACTM 06:15"))),
    ("SQ326", (("1G216/26", "125.2MHZ", "not later than ACTM 05:24"), ("AX1/23", "134.5 MHZ, 128.5 MHZ", "between ACTM 06:09 and ACTM 06:19"))),
    ("SQ23", (("1G216/26", "125.2MHZ", "not later than ACTM 11:08"), ("SX33/26", "124.100 MHZ, 118.950 MHZ", "not later than ACTM 11:41"))),
])
def test_outbound_and_earlier_qa_flights_keep_their_calls(key, expected, tmp_path_factory):
    text = card(rendered(key, tmp_path_factory))
    for notam_id, frequencies, when in expected:
        assert printed_whole(text, when, frequencies, f"NOTAM {notam_id}"), (notam_id, text)


def test_turkmenabat_within_ten_minutes_is_a_window_not_a_deadline(tmp_path_factory):
    """AX1/23 prints "WI 10 MIN. TO THE ENTRANCE TO THE FIR": the call is made in the ten minutes before the entry; the
    page no longer tells the crew to have called ten minutes before it ("not later than")."""
    case = rendered("SQ352", tmp_path_factory)
    turkmenabat = next(line for line in case["record"]["procedure_lines"] if line["notam_ids"] == ["AX1/23"])
    assert turkmenabat["call_window"] == {"relation": "window", "from_actm": "06:05", "by_actm": "06:15", "anchor_actm": "06:15"}
    assert "not later than ACTM 06:05" not in " ".join(case["pages"][5].split())


# ---------------------------------------------------------------- the shared rule, labelled synthetic inputs


def test_labelled_call_windows_read_the_printed_lead_as_printed():
    from app.odss.enroute_contact import call_time_phrase, call_window

    cases = {
        "10 MINS PRIOR ENTERING TO FIR": "not later than ACTM 05:11",
        "NOT LESS THAN 15 MINUTES BEFORE THE FIR BOUNDARY POINT": "not later than ACTM 05:06",
        "AT LEAST 15 MIN PRIOR TO ENTERING KARACHI OR LAHORE FIR": "not later than ACTM 05:06",
        "WI 10 MIN. TO THE ENTRANCE TO THE FIR": "between ACTM 05:11 and ACTM 05:21",
        "BETWEEN 15 AND 30 MINUTES BEFORE THE PILOT'S ESTIMATED ENTERING JAKARTA FIR": "between ACTM 04:51 and ACTM 05:06",
        "MAXIMUM 30 MIN BEFORE ENTRY": "between ACTM 04:51 and ACTM 05:21",
        "APPROX 5 MIN BEFORE THE BOUNDARY": "about ACTM 05:16",
    }
    for lead, phrase in cases.items():
        assert call_time_phrase(call_window(lead, 5 * 60 + 21)) == phrase, lead
    # A window reaching back before take-off is not derived.
    assert call_window("BETWEEN 15 AND 30 MINUTES BEFORE ENTERING", 20) is None


def test_labelled_call_unit_is_the_instructions_own_words():
    from app.odss.enroute_contact import call_unit

    assert call_unit("ACFT MUST ESTABLISH CON TACT WITH TURKMENABAT-CTL ON 134.5 MHZ FREQ") == "TURKMENABAT-CTL"
    assert call_unit("ALL TFC ... SHALL CTC KARACHI, LAHORE OR ISLAMABAD ACC AT LEAST 15 MIN PRIOR") == "KARACHI, LAHORE OR ISLAMABAD ACC"
    assert call_unit("FLIGHTS DEPARTING THE KABUL FIR SHALL CONTACT THE RELEVANT ACC IN THE NEXT FIR ENTERED") == "THE RELEVANT ACC"
    assert call_unit("ALL OVERFLIGHTS SHALL COMPLY WITH TIBA PROCEDURE FOR BROADCAST INTENTIONS ON FREQ 125.2MHZ") is None


def _flight(lead: str, *, extra: str = "") -> dict:
    """LABELLED SYNTHETIC: three FIR boundary rows; one crew contact notice under the middle FIR's heading."""
    from app.odss.extraction_rules import EXTRACTION_RULES

    return {
        "scheduled_departure_utc": "2026-10-24T09:35:00Z",
        "extraction_rules": EXTRACTION_RULES,
        "route_waypoints": [
            {"name": "AAAAA", "fir_boundary": "ZZAA", "actm_minutes": 60, "source_page": 3, "airway_in": "DCT"},
            {"name": "BBBBB", "fir_boundary": "ZZBB", "actm_minutes": 200, "source_page": 4, "airway_in": "DCT"},
            {"name": "CCCCC", "fir_boundary": "ZZCC", "actm_minutes": 260, "source_page": 4, "airway_in": "DCT"},
            {"name": "DDDDD", "fir_boundary": None, "actm_minutes": 300, "source_page": 5, "airway_in": "DCT"},
        ],
        "notam_procedure_records": [{
            "notam_id": "SYN1/26", "validity": "01-OCT-26 0000 - 31-DEC-26 2359", "heading": "ZZBB SYNTH FIR", "heading_kind": "fir",
            "fir": "ZZBB", "segment": None, "heading_page": 9, "source_page": 9, "applicability": "not_inferred",
            "text": f"ALL OVERFLIGHTS SHALL CONTACT SYNTH CONTROL ON 123.45 MHZ {lead}.{extra}",
        }],
    }


def test_labelled_a_lead_from_take_off_derives_no_fir_clock():
    from app.odss.enroute_contact import compose_enroute_contact

    composed = compose_enroute_contact(_flight("NOT LESS THAN 10 MINUTES BEFORE TAKEOFF"))
    call = composed["early_calls"][0]
    assert call["call_window"] is None and call["due_actm"] is None
    assert call["untimed_reason"] == "the lead is measured from take-off, not from a FIR entry"
    assert composed["procedures"][0]["latest_actm"] is None


def test_labelled_early_call_names_its_unit_values_entry_and_actual_take_off_clock():
    from app.odss.enroute_contact import compose_enroute_contact, early_call_sentence

    flight = _flight("AT LEAST 15 MIN PRIOR TO ENTERING THE FIR")
    flight["actual_takeoff_utc"] = "2026-10-24T09:50:00Z"
    composed = compose_enroute_contact(flight)
    [call] = composed["early_calls"]
    assert call["due_actm"] == "03:05" and call["due_utc"] == "1255Z"
    assert early_call_sentence(call) == ("Early call not later than ACTM 03:05 (1255Z): Contact SYNTH CONTROL on 123.45 MHZ; "
                                         "lead AT LEAST 15 MIN PRIOR TO ENTERING THE FIR - ZZBB entry ACTM 03:20.")
    assert composed["state_sentence"].startswith("1 early call(s) are read from this OFP's FIR notices (1 with a call time")


def test_labelled_failed_condition_is_no_early_call_and_nothing_is_invented():
    from app.odss.enroute_contact import compose_enroute_contact

    flight = _flight("AT LEAST 15 MIN PRIOR TO ENTERING THE FIR")
    flight["notam_procedure_records"][0]["validity"] = "01-JAN-26 0000 - 31-JAN-26 2359"
    composed = compose_enroute_contact(flight)
    assert composed["procedures"][0]["applicability_state"] == "not_applicable"
    assert composed["early_calls"] == []
    assert composed["state_sentence"].startswith("No approved early-call rule is held.")


def test_labelled_dense_page_six_keeps_every_early_call_and_names_what_it_cannot_hold(tmp_path_factory):
    """A page with no room left: the early calls print before every other row; any the page cannot hold whole are
    named by time, FIR, identity and page - none disappears unnamed, and the generic statuses go to the dashboard."""
    from app.odss.enroute_contact import compose_enroute_contact, early_call_sentence, named_early_call

    case = rendered("SQ303", tmp_path_factory)
    payload = json.loads(json.dumps(case["payload"]))
    # LABELLED SYNTHETIC: a long personal note fills the closing record's REMAINING RELEASE INPUTS card.
    payload["flight"]["personal_notes"] = [{"note_text": "SYNTHETIC CAPACITY NOTE " + "X" * 120, "include_level1": True}]
    path = tmp_path_factory.mktemp("early-calls-dense") / "dense.pdf"
    render_combined_briefing(payload["flight"], payload["findings"], payload.get("view", {}).get("warnings") or [], path,
                             source_pdf_path=None, weather_charts=payload.get("weather_charts") or {})
    with fitz.open(path) as document:
        page6 = normalized(document[5].get_text())
    text = page6.split(normalized("FIR / COMMUNICATION"), 1)[1].split(normalized("FIR crossings (OFP ACTM)"), 1)[0]
    composed = compose_enroute_contact(payload["flight"], payload["findings"])
    for call in (c for c in composed["early_calls"] if c["call_window"]):
        forms = (early_call_sentence(call), early_call_sentence(call, compact=True), named_early_call(call))
        assert any(normalized(form) in text for form in forms), (call["notam_ids"], text)
    assert normalized("CPDLC AT MAASTRICHT UAC (EDYY) NOT AVBL") not in text
    assert re.search(r"\b\d+ FURTHER ROWS ON THE DASHBOARD\b", text), text


def test_the_audit_compositions_measured_timeline_band_is_unchanged(tmp_path_factory):
    """The early-call anchors belong to the six-page decision timeline. The lossless audit composition's REV3-measured
    timeline band keeps its own anchors (the private corpus gate's physical scan found early-call labels overlapping
    there), and its FIR / NEXT CONTACT tile carries the calls instead."""
    from app.odss.briefing import build_briefing_view
    from app.odss.combined_brief import _route_anchor_entries, early_call_anchor_entries

    case = rendered("SQ303", tmp_path_factory)
    flight = case["payload"]["flight"]
    view = build_briefing_view(flight, case["payload"]["findings"], [], timing_view=flight.get("timing_view"))
    assert not any(entry["label"].endswith((" TIBA", " CALL", " LOGON")) for entry in _route_anchor_entries(flight, view))
    assert [(entry["label"], entry["sub"]) for entry in early_call_anchor_entries(flight, view)] == [
        ("OAKX TIBA", "ACTM 05:11"), ("OPLR CALL", "ACTM 05:52")]

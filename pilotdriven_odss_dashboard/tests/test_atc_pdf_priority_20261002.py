"""ATC-PDF-PRIORITY (2 Oct 2026, ITEM1 independent production recheck of release 446).

Fresh genuine uploads on pilotdriven.com showed the dashboard rows correct but the compact page 6 choosing its
printed ATC rows by time / source-page order alone:

* SQ304 (12 Jul) page 6 printed three unresolved rows - SX50/25 WIIF, 1A2393/26 VTBB and 1B818/26 EHAA - and
  deferred the held Kabul 1G216/26 TIBA broadcast (125.2 MHz, 10 min before entry) and the held Turkmenabat AX1/23
  call (134.5 MHz) to the dashboard.
* SQ23 (25 Jul) page 6 prints Washington KZDC 1A1513/26 "COM CPDLC ROUTE MESSAGING NOT AVBL" (p94) and names the
  identical New York KZNY 1A487/26 (p98) as a deferred dashboard row. Printing both in one row is refused by the reviewed
  dashboard/PDF parity guard (differing validity and conditions); a separate row does not fit beside the Karachi call.
  That stays as it is (attempt 13 gate 10).
* 1A2393/26 "ALL ACFT VIA RTE B346, R474, W21 AND G473 ADVICE CTC BANGKOK ACC ..." stayed unresolved although the
  OFP's own route through VTBB files A334, W14 and L759 only.

The generic repairs: the primary and the next valued call prefer rows whose printed conditions are held, then fall
back to the existing time order; an airway-only route list is evaluated against the airways the OFP files inside that
notice's own FIR (met when one is filed there, not met only when every leg there is
known and none is). Nothing is inferred for a departure FIR the OFP does not name.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import fitz
import pytest

from app.analysis import run_odss_analysis
from app.odss.combined_brief import render_combined_briefing
from app.odss.concise_pdf_gate import normalized
from app.odss.enroute_contact import compose_enroute_contact, primary_procedure_line
from app.odss.operational_format import _primary_and_next_valued_call
from tests.atc_test_inputs import private_cfp_source

SOURCES = {
    "SQ304": ("lido-briefing_SQ_304_12Jul2026_SIN_BRU.pdf", "ffb63085badc026e1db590b289be80590d551a58b6a699a1c8d1c4f79ac9baef"),
    "SQ23": ("SQ02325072026JFK.pdf", "45c781ab4a8644f92e4cde7c13da8d7ec13cd4b4cc9b0bb827011b9dbabfc016"),
}
_RENDERED: dict[str, dict] = {}


def rendered(key: str, tmp_path_factory) -> dict:
    if key in _RENDERED:
        return _RENDERED[key]
    filename, digest = SOURCES[key]
    source = private_cfp_source(filename)
    assert hashlib.sha256(source.read_bytes()).hexdigest() == digest
    root = tmp_path_factory.mktemp(f"atc-priority-{key}")
    result = run_odss_analysis(source, root / "analysis", root / "reports", 1)
    payload = json.loads(Path(result["analysis_path"]).read_text(encoding="utf-8"))
    path = root / f"{key}_Flight_Briefing.pdf"
    render_combined_briefing(payload["flight"], payload["findings"], payload.get("view", {}).get("warnings") or [], path,
                             source_pdf_path=str(source), weather_charts=payload.get("weather_charts") or {})
    with fitz.open(path) as document:
        pages = [page.get_text() for page in document]
    model = compose_enroute_contact(payload["flight"], payload["findings"])
    _RENDERED[key] = {"payload": payload, "model": model, "page6": normalized(pages[5])}
    return _RENDERED[key]


def row(model: dict, notam_id: str) -> dict:
    return next(r for r in model["procedures"] if r["notam_id"] == notam_id)


def test_genuine_sq304_page_six_prints_the_held_kabul_and_turkmenabat_calls(tmp_path_factory):
    case = rendered("SQ304", tmp_path_factory)
    model, page = case["model"], case["page6"]
    assert row(model, "1G216/26")["applicability_state"] == "conditions_held"
    assert row(model, "AX1/23")["applicability_state"] == "conditions_held"
    assert primary_procedure_line(model["procedure_lines"])["notam_ids"] == ["1G216/26"]
    for printed in ("NOTAM 1G216/26, OFP p91", "FREQ 125.2MHZ 10 MINS PRIOR ENTERING TO FIR", "not later than ACTM 05:22",
                    "NOTAM AX1/23, OFP p92", "134.5 MHZ, 128.5 MHZ"):
        assert normalized(printed) in page, printed
    # Every row still reaches the dashboard; the deferral line still counts what page 6 does not print.
    assert normalized("further rows on the dashboard") in page


def test_genuine_sq304_bangkok_airway_list_is_not_met_on_the_filed_vtbb_airways(tmp_path_factory):
    model = rendered("SQ304", tmp_path_factory)["model"]
    bangkok = row(model, "1A2393/26")
    assert {"kind": "route", "text": "VIA RTE B346, R474, W21 AND G473", "result": "not_met"} in bangkok["conditions"]
    assert bangkok["applicability_state"] == "not_applicable"
    assert bangkok["printed_details"]["frequencies"] == ["126.500MHZ", "122.00MHZ"]
    # A notice with a printed route segment keeps that waypoint evaluation; the airway list adds no second route condition.
    trang = [c for c in row(model, "SX12/25")["conditions"] if c["kind"] == "route"]
    assert trang == [{"kind": "route", "text": "HTY/PADPAW14", "result": "met"}]


def test_genuine_sq23_page_six_keeps_its_valued_calls_and_names_the_new_york_cpdlc_outage_it_defers(tmp_path_factory):
    """The reviewed parity guard keeps differing validity/conditions out of one printed row, and page 6 cannot hold a
    separate KZNY row without dropping the Karachi crew call: KZNY 1A487/26 stays an explicitly named dashboard row."""
    case = rendered("SQ23", tmp_path_factory)
    model, page = case["model"], case["page6"]
    for printed in ("NOTAM 1G216/26, OFP p108", "NOTAM SX33/26, OFP p110", "NOTAM 1A1513/26, OFP p94", "KZNY 1A487/26 (p98)"):
        assert normalized(printed) in page, printed
    line = next(l for l in model["procedure_lines"] if "1A487/26" in l["notam_ids"])
    assert (line["text"], line["fir"], line["source_pages"], line["actm"]) == ("COM CPDLC ROUTE MESSAGING NOT AVBL", "KZNY", [98], None)
    assert row(model, "1A487/26")["applicability_state"] == "conditions_unresolved"


def _line(notam_id, fir, state, *, kind="voice_contact", effect="instruction", frequencies=(), lead=None, actm="01:00", text="SYNTHETIC", summary="conditions"):
    return {"notam_ids": [notam_id], "fir": fir, "applicability_state": state, "kind": kind, "actor": "crew",
            "instruction_effect": effect, "actm": actm, "text": text, "conditions_summary": summary, "further_actions": 0,
            "printed_details": {"frequencies": list(frequencies), "lead": lead, "interval": None, "addresses": []},
            "source_pages": [1], "conditions": []}


def test_labelled_primary_and_next_call_prefer_held_conditions_then_keep_time_order():
    early = _line("SYN1/26", "ZZAA", "conditions_unresolved", frequencies=["121.1MHZ"], actm="00:10")
    held = _line("SYN2/26", "ZZBB", "conditions_held", frequencies=["122.2MHZ"], actm="02:00")
    later = _line("SYN3/26", "ZZCC", "conditions_unresolved", lead="10 MIN", actm="03:00")
    held_lead = _line("SYN4/26", "ZZDD", "conditions_held", lead="15 MIN", actm="04:00")
    lines = [early, held, later, held_lead]
    assert primary_procedure_line(lines) is held
    assert _primary_and_next_valued_call(lines, held) == [held, held_lead]
    # With no held call the existing time order stands.
    unresolved = [early, later]
    assert primary_procedure_line(unresolved) is early
    assert _primary_and_next_valued_call(unresolved, early) == [early, later]


def _flight(airways_in_fir, text, *, other_fir_airways=()):
    """LABELLED SYNTHETIC: one ZZAA crossing whose filed legs inside ZZAA carry the given airways."""
    waypoints = [{"name": "SYNA", "actm_minutes": 5, "fir_boundary": None, "source_page": 1, "airway_in": "Q1"},
                 {"name": "-ZZAA", "actm_minutes": 30, "fir_boundary": "ZZAA", "source_page": 1, "airway_in": None}]
    for index, airway in enumerate(airways_in_fir):
        waypoints.append({"name": f"SYNB{index}", "actm_minutes": 35 + index, "fir_boundary": None, "source_page": 1, "airway_in": airway})
    waypoints.append({"name": "-ZZBB", "actm_minutes": 90, "fir_boundary": "ZZBB", "source_page": 1, "airway_in": None})
    for index, airway in enumerate(other_fir_airways or ("Q9",)):
        waypoints.append({"name": f"SYNC{index}", "actm_minutes": 95 + index, "fir_boundary": None, "source_page": 1, "airway_in": airway})
    return {"departure": "WSSS", "destination": "VHHH", "scheduled_departure_utc": "2026-06-01T01:00:00Z", "route_waypoints": waypoints,
            "notam_procedure_records": [{"notam_id": "SYNTHETIC/26", "validity": "01-JAN-26 0000 - 31-DEC-26 2359",
                                         "heading": "ZZAA SYNTHETIC FIR", "heading_kind": "fir", "fir": "ZZAA", "source_page": 2, "text": text}]}


AIRWAY_CALL = "ALL ACFT VIA RTE B346, R474 AND G473 SHALL CTC SYNTHETIC ACC ON 126.500MHZ."


@pytest.mark.parametrize("airways,other,expected", [
    (["A334", "W14", "DCT"], (), "not_met"),          # every leg inside ZZAA is known; none is listed
    (["A334", "G473"], (), "met"),                     # a listed airway is filed inside ZZAA
    (["A334", None], (), None),                        # a leg inside ZZAA has no airway held: not evaluated
    (["A334"], ("B346",), "met"),                      # the airway leaving ZZAA across its exit boundary is flown in ZZAA too
    (["A334"], ("Q9", "B346"), "not_met"),             # the same designator filed only deeper in another FIR is not this FIR's
])
def test_labelled_airway_only_route_list_is_evaluated_inside_the_notice_fir(airways, other, expected):
    procedure = compose_enroute_contact(_flight(airways, AIRWAY_CALL, other_fir_airways=other))["procedures"][0]
    route = [c for c in procedure["conditions"] if c["kind"] == "route"]
    if expected is None:
        assert route == []
        assert procedure["applicability_state"] == "conditions_unresolved"
    else:
        assert route == [{"kind": "route", "text": "VIA RTE B346, R474 AND G473", "result": expected}]
        assert procedure["applicability_state"] == ("not_applicable" if expected == "not_met" else procedure["applicability_state"])
    assert procedure["printed_details"]["frequencies"] == ["126.500MHZ"]


@pytest.mark.parametrize("text", [
    "CPDLC SHALL BE USED EXC ON ROUTE G473.",
    "ALL ACFT EXCEPT THOSE VIA RTE G473 SHALL CTC SYNTHETIC ACC ON 126.500MHZ.",
    "ACFT NOT ON ATS RTE G473 SHALL CTC SYNTHETIC ACC ON 126.500MHZ.",
])
def test_labelled_an_airway_list_inside_an_exception_or_negation_is_not_a_route_condition(text):
    """LABELLED SYNTHETIC: "EXC ON ROUTE X" applies everywhere but X; reading it as "only on X" would invert the duty."""
    for airways in (["A334", "W14"], ["A334", "G473"]):
        procedure = compose_enroute_contact(_flight(airways, text))["procedures"][0]
        assert [c for c in procedure["conditions"] if c["kind"] == "route"] == []
        assert procedure["applicability_state"] != "not_applicable"


def test_genuine_sq23_page_six_keeps_every_vws_event_beside_its_calls(tmp_path_factory):
    """Codex QA of release 468: SQ023's restored 5350N VWS 005 event (ACTM 02.26-02.39) took the line holding the Karachi
    call row. The page now packs the VWS events at its last content step before a FIR row is deferred - both events,
    each with its span and maximum, and the Karachi row stay on page 6."""
    page = rendered("SQ23", tmp_path_factory)["page6"]
    for printed in ("02.26-02.39", "07.45-07.52", "NOTAM SX33/26, OFP p110"):
        assert normalized(printed) in page, printed

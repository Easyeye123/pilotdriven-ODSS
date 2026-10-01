"""ATC-FIR-BOBCAT-416 (Jabe via Codex, 24 Sep 2026): the FIR / COMMUNICATION
column of David's own reference page 6 ("+00:02  WIIF entry. CPDLC limited
trial: pilot initiates AFN logon only when requested by ATC; address WIIF.",
provenance "FPL p12 / NOTAM p32") restored to the six-page briefing, with the
BOBCAT allocation and the ordered FIR crossing ACTM line beside it; one
composition (app/odss/enroute_contact.py) shared, token for token, with the
dashboard rule (web/src/lib/enroute-contact.mjs) through the frozen vectors.

Nothing is inferred: no call, lead time or frequency from a crossing time or a
region; a held notice is quoted with its identity and page and its
applicability is stated as not inferred.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import re
from pathlib import Path

import fitz
import pytest

from app.analysis import run_odss_analysis
from app.odss import reference_conformance as conformance
from app.odss.combined_brief import render_combined_briefing
from app.odss.concise_pdf_gate import normalized
from app.odss.enroute_contact import ENROUTE_CONTACT_RULE, compose_enroute_contact, primary_procedure_line, procedure_kind
from tests.test_r2_reminder_wording import david_format_labels, reminder_lines, source_quotations

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT.parent / "private_cfp_corpus"
MANIFEST_PATH = ROOT / "tests" / "boss_reference_format_manifest.json"
APP_ROOT = Path(os.environ.get("PILOTDRIVEN_APP_ROOT") or ROOT.parent.parent / "pd-code-e-helpyou-20260921")
VECTORS = APP_ROOT / "tests" / "fixtures" / "enroute-contact-vectors.json"
ENROUTE_PAGE = 5  # page 6, zero-based

FLIGHTS = {
    "SQ366": "SQ36604082026SIN.pdf",              # BOBCAT allocation + Jakarta AFN notice, 24 crossings
    "SQ882": "lido-briefing_SQ_882_10Sep2026_SIN_HKG.pdf",  # conditional ash/equipage notices; no unconditional early call/allocation
    "SQ23": "SQ02325072026JFK.pdf",                # 36 crossings: the page-6 capacity case
}

_RENDERED: dict[str, dict] = {}


def rendered(key: str, tmp_path_factory, mutate=None) -> dict:
    cache_key = key if mutate is None else f"{key}:{mutate.__name__}"
    if cache_key in _RENDERED:
        return _RENDERED[cache_key]
    source = CORPUS / FLIGHTS[key]
    if not source.is_file():
        pytest.skip(f"exact private CFP source for {key} is not available: {source}")
    manifest = json.loads((ROOT / "tests/private_cfp_corpus_manifest.json").read_text())
    pinned = next(case for case in manifest["cases"] if case["filename"] == source.name)
    assert hashlib.sha256(source.read_bytes()).hexdigest() == pinned["source_sha256"], key
    root = tmp_path_factory.mktemp(f"enroute-{cache_key.replace(':', '-')}")
    result = run_odss_analysis(source, root / "analysis", root / "reports", 1)
    payload = json.loads(Path(result["analysis_path"]).read_text(encoding="utf-8"))
    if mutate is not None:
        payload = mutate(payload)
    path = root / f"{key}_Flight_Briefing.pdf"
    render_combined_briefing(
        payload["flight"], payload["findings"], payload.get("view", {}).get("warnings") or [], path,
        source_pdf_path=str(source), weather_charts=payload.get("weather_charts") or {},
    )
    with fitz.open(path) as document:
        pages = [page.get_text() for page in document]
    _RENDERED[cache_key] = {"payload": payload, "path": path, "pages": pages, "folded": [normalized(p) for p in pages]}
    return _RENDERED[cache_key]


def _printed_pairs(page_text: str) -> tuple[list[tuple[str, str]], str]:
    """The FIR / ACTM pairs the crossing line prints, read across wrapped lines
    up to the deferral marker or the next card."""
    line = " ".join(page_text.split("FIR crossings (OFP ACTM):", 1)[1].split())
    for stop in ("AIRPORT ASSESSMENTS", "WEATHER COVERAGE", "SOURCE CONTROL", "SOURCE / CALCULATION", "REMAINING RELEASE", "PUBLICATION STATE"):
        line = line.split(stop, 1)[0]
    return re.findall(r"\b([A-Z]{4}) (\d{2}:\d{2})\b", line.split(" more", 1)[0]), line


def _conforms(path: Path) -> dict:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    return conformance.check_reference_conformance(
        path, structure=manifest["reference_structure"], contract_extensions=manifest["contract_extensions"])


# ---------------------------------------------------------------- the rule


def test_the_rule_classifies_a_notice_by_its_printed_instruction_only():
    # ATC-RADIO-SOURCE-418: four kinds, decided by the printed verb and object; a notice without one is not held.
    assert procedure_kind("... AFN LOGON PROCESS WILL BE INITIATED BY THE PILOT WHEN REQUESTED BY ATC") == "contact_logon"
    assert procedure_kind("ALL DATA LINK EQUIPPED AIRCRAFT (CPDLC ATN VDL MODE 2) ARE REQUESTED TO LOGON TO LOVV") == "contact_logon"
    assert procedure_kind("PILOTS SHALL CONTACT MUMBAI RADAR PRIOR TO ENTERING THE FIR") == "voice_contact"
    assert procedure_kind("ALL OVERFLIGHTS SHALL COMPLY WITH TIBA PROCEDURE FOR BROADCAST INTENTIONS ON FREQ 125.2MHZ") == "tiba_broadcast"
    assert procedure_kind("ADS-C/CPDLC OPERATIONAL TRIAL WITHIN JAKARTA FIR ... 10 MINUTES SEPARATION") == "datalink_other"
    assert procedure_kind("OPPORTUNITY BASED APPLICATION OF 10 MINUTES SEPARATION ON XNG TRACKS BTN ADS-B EQUIPPED ACFT") is None
    assert procedure_kind("") is None


def test_the_composition_reproduces_the_frozen_vectors_the_dashboard_rule_pins():
    if not VECTORS.is_file():
        pytest.skip(f"vectors not frozen at {VECTORS}")
    vectors = json.loads(VECTORS.read_text(encoding="utf-8"))
    assert vectors["rule"] == ENROUTE_CONTACT_RULE
    for vector in vectors["cases"]:
        composed = compose_enroute_contact(vector["input"]["flight"], vector["input"]["findings"])
        assert composed == vector["expected"], vector["name"]


def test_sq366_composition_from_the_genuine_analysis(tmp_path_factory):
    case = rendered("SQ366", tmp_path_factory)
    composed = compose_enroute_contact(case["payload"]["flight"], case["payload"]["findings"])
    assert composed["state"] == "source_procedures_held"
    assert len(composed["crossings"]) == 24
    assert composed["crossings"][0] == {"sequence": 1, "fir": "WIIF", "actm": "00:03", "actm_minutes": 3, "source_page": 8, "reentry": False, "repeated": False, "utc": None, "day": ""}
    assert composed["crossing_sequence"].startswith("WIIF 00:03 · WSJC 00:06 · WMFC 00:07 · WSJC 00:07 · WMFC 00:08 · ")
    assert any(row["fir"] == "WSJC" and row["reentry"] for row in composed["crossings"])
    jakarta = next(row for row in composed["procedures"] if row["notam_id"] == "1A1891/26")
    assert jakarta["fir"] == "WIIF" and jakarta["source_page"] == 67 and jakarta["kind"] == "contact_logon" and jakarta["on_route"]
    assert jakarta["note"] == "CPDLC limited trial: pilot initiates AFN logon only when requested by ATC; address WIIF."
    assert jakarta["applicability"] == "not_inferred"
    assert composed["slot_control"] == {
        "system": "BOBCAT", "waypoint": "BIROS", "flight_level": 380, "ctot": "1752Z", "cto": "2328Z", "actm": "05:35",
        "computed_cto": "2327Z", "difference_minutes": -1, "source_pages": [1, 11],
    }
    assert composed["slot_sentence"] == "BOBCAT BIROS FL380: CTOT 1752Z + ACTM 05:35 = 2327Z, 1 min before CTO 2328Z (OFP p1, p11)."
    # ATC-RADIO-SOURCE-418: every printed instruction is held, so the Kabul, Karachi and Turkmenabat pages join the provenance.
    # AIRSPACE-HEADINGS-436: p93 is 1A2595/26 (UAV flights, voice contact) under the topic heading "UAV 401614N 0250927E".
    assert composed["provenance"] == "FPL pp8-14 / NOTAM p67, pp85-90, pp93-94, pp98-100"
    assert [line["notam_ids"] for line in composed["procedure_lines"] if line["fir"] == "WIIF"] == [["1A1891/26"], ["SX50/25"]]
    # The composition is published on the view so the dashboard and the PDF read one record.
    assert case["payload"]["view"]["briefing"]["enroute_contact"] == composed


# ---------------------------------------------------------------- page 6


def test_sq366_page_six_prints_his_fir_communication_column_with_the_allocation_and_the_crossing_line(tmp_path_factory):
    case = rendered("SQ366", tmp_path_factory)
    page = case["folded"][ENROUTE_PAGE]
    raw = case["pages"][ENROUTE_PAGE]
    assert "FIR / COMMUNICATION" in raw
    # ATC-CLEARANCE-FAMILY (1 Oct 2026): CO188/02 adds one source-held notice whose conditions are unresolved.
    assert normalized("No approved early-call rule held. 27 source-held ATC/communications notices: 8 conditions met, 17 unresolved, 2 not applicable.") in page
    # ATC-RADIO-SOURCE-418: page 6 holds one full row on this OFP (the first call row with a printed frequency, by the
    # shared rule) and names every deferred row; the Jakarta note is on the dashboard and named here.
    composed = case["payload"]["view"]["briefing"]["enroute_contact"]
    primary = primary_procedure_line(composed["procedure_lines"])
    assert primary["notam_ids"] == ["1G216/26"]
    assert normalized("+05:35 OAKX entry. ALL OVERFLIGHTS SHALL COMPLY WITH TIBA PROCEDURE FOR BROADCAST INTENTIONS ON FREQ 125.2MHZ 10 MINS PRIOR ENTERING TO FIR. Printed: not later than ACTM 05:25. NOTAM 1G216/26, OFP p88; validity 10-JUN-26 0600 - 05-SEP-26 2359 EST: covers this crossing (at scheduled departure 1730Z + ACTM) · overflight: met · conditions held.") in page
    assert normalized("Source FIR LIMM; route/time unresolved. STATION 'MILANO ACC/FIC' SERVICE 'EMERGENCY' FREQUENCY 243.000MHZ COMPLETELY WITHDRAWN REF AIP ENR 2.1.1.1-3 NOTAM 1E1741/26, OFP p98; valid 10-JUL-26 0000 - PERM (time unresolved) · conditions unresolved.") in page
    assert normalized("+24 further rows on the dashboard (WIIF 2, VABF 1, OPKR 2, OAKX 9, UTAV 1, LTAA 1, LGGG 1, LIBB 1, LOVV 2, FIR not derived 1, LSAS 1, LIMM 2).") in page
    # The topic row is source-held without a FIR/clock, included in that exact
    # whole-row deferral; no individual identity is invented in a count group.
    topic = next(row for row in composed["procedures"] if row["notam_id"] == "1A2595/26")
    assert not topic["fir"] and topic["actm"] is None and topic["on_route"] is None
    assert normalized("BOBCAT BIROS FL380: CTOT 1752Z + ACTM 05:35 = 2327Z, 1 min before CTO 2328Z (OFP p1, p11).") in page
    assert normalized("FIR crossings (OFP ACTM): WIIF 00:03 · WSJC 00:06 · WMFC 00:07 · WSJC 00:07 · WMFC 00:08") in page
    assert "FPL pp8-14 / NOTAM p67, pp85-90, pp93-94, pp98-100" in raw
    # Whole pairs only, in the OFP order; when the page cannot hold all 24 the deferral is stated.
    printed_pairs, line = _printed_pairs(raw)
    expected = [(row["fir"], row["actm"]) for row in composed["crossings"]]
    assert printed_pairs and printed_pairs == expected[:len(printed_pairs)]
    assert len(printed_pairs) in (len(expected), 12, 8)
    if len(printed_pairs) < len(expected):
        assert f"+{len(expected) - len(printed_pairs)} more" in line
    labels = david_format_labels()
    quotations = source_quotations(case["payload"])
    assert reminder_lines(raw, quotations, labels) == []
    result = _conforms(case["path"])
    assert result["valid"], result["violations"]
    assert len(case["pages"]) == 6


def test_sq882_page_six_keeps_conditional_source_duties_without_an_unconditional_early_call(tmp_path_factory):
    case = rendered("SQ882", tmp_path_factory)
    page = case["folded"][ENROUTE_PAGE]
    raw = case["pages"][ENROUTE_PAGE]
    assert "FIR / COMMUNICATION" in raw
    composed = case["payload"]["view"]["briefing"]["enroute_contact"]
    assert [row["notam_id"] for row in composed["procedures"]] == ["1A3438/26", "1A1997/26"]
    assert composed["required_calls"] == []
    assert all(row["applicability_state"] == "conditions_unresolved" and row["latest_actm"] is None
               and row["printed_details"]["lead"] is None and not row["printed_details"]["frequencies"]
               for row in composed["procedures"])
    report = next(row for row in composed["procedures"] if row["notam_id"] == "1A3438/26")
    assert any(c["text"] == "report trigger: VOLCANIC ASH" and c["result"] == "unresolved" for c in report["conditions"])
    equipage = next(row for row in composed["procedures"] if row["notam_id"] == "1A1997/26")
    assert equipage["kind"] == "atc_duty" and equipage["instruction_effect"] == "prohibited"
    assert any(c["text"] == "WITHOUT OPERABLE ADS-B OUT EQUIPAGE" and c["result"] == "unresolved" for c in equipage["conditions"])
    assert normalized(composed["state_sentence"]) in page
    assert "NOTAM 1A3438/26" in raw
    assert normalized("reporting condition: VOLCANIC ASH: not evaluable from the OFP") in page
    assert normalized("report trigger: VOLCANIC ASH: not evaluable from the OFP") not in page
    assert "ATC restriction" in raw and "NOTAM 1A1997/26" in raw
    assert "not later than ACTM" not in raw
    assert normalized("No slot-control allocation is printed in this OFP.") in page
    assert normalized("FIR crossings (OFP ACTM):") in page
    assert "BOBCAT" not in raw.replace("No slot-control", "")
    assert reminder_lines(raw, source_quotations(case["payload"]), david_format_labels()) == []
    assert _conforms(case["path"])["valid"]


def _strip_fir_rows(payload: dict) -> dict:
    """LABELLED SYNTHETIC: the genuine SQ882 analysis with every FIR boundary
    marker AND held notice removed - the true absent-source case. Retained
    untimed notices are a separate positive control in completeness tests."""
    payload = copy.deepcopy(payload)
    for waypoint in payload["flight"].get("route_waypoints") or []:
        waypoint["fir_boundary"] = None
    payload["flight"]["notam_procedure_records"] = []
    return payload


def test_synthetic_no_fir_rows_page_six_states_the_unresolved_source(tmp_path_factory):
    case = rendered("SQ882", tmp_path_factory, mutate=_strip_fir_rows)
    page = case["folded"][ENROUTE_PAGE]
    assert normalized("No FIR boundary row is held in the parsed OFP; early-contact requirements are not established from this source.") in page
    assert "FPL boundary rows not held" in case["pages"][ENROUTE_PAGE]
    assert _conforms(case["path"])["valid"]


def test_sq23_the_longest_crossing_sequence_fits_page_six_or_defers_whole_pairs_to_the_dashboard(tmp_path_factory):
    case = rendered("SQ23", tmp_path_factory)
    raw = case["pages"][ENROUTE_PAGE]
    composed = case["payload"]["view"]["briefing"]["enroute_contact"]
    assert len(composed["crossings"]) >= 30
    assert "FIR / COMMUNICATION" in raw
    printed_pairs, line = _printed_pairs(raw)
    assert printed_pairs, "the crossing line is printed"
    # Either every pair or a whole-pair prefix with the deferral stated; never a cut pair.
    expected = [(row["fir"], row["actm"]) for row in composed["crossings"]]
    assert printed_pairs == expected[:len(printed_pairs)]
    if len(printed_pairs) < len(expected):
        assert f"+{len(expected) - len(printed_pairs)} more" in line
        assert "dashboard" in line.lower()
    assert len(case["pages"]) == 6
    assert _conforms(case["path"])["valid"]


# ---------------------------------------------------------------- the concise gate


def test_the_concise_gate_explains_only_the_identities_the_composed_record_names(tmp_path_factory):
    """The gate admits a NOTAM identity on page 6 only when the published
    enroute_contact record names it; with that record withheld the same page
    is refused for the actually printed numeric source identities. Count-only
    deferred SX50/25 is no longer a printed-ID control."""
    from app.odss.concise_pdf_gate import check_concise_pdf
    from app.odss.airport_pdf_analysis import airport_pdf_analysis, alternate_pdf_analysis

    case = rendered("SQ366", tmp_path_factory)
    flight, view = case["payload"]["flight"], case["payload"]["view"]["briefing"]
    panels = view.get("airport_operational_panels") or []
    kwargs = dict(flight=flight, airport_analysis=airport_pdf_analysis(flight, panels), alternate_analysis=alternate_pdf_analysis(flight, panels))
    assert check_concise_pdf(case["path"], view=view, **kwargs)["valid"]
    withheld = {key: value for key, value in view.items() if key != "enroute_contact"}
    result = check_concise_pdf(case["path"], view=withheld, **kwargs)
    codes = [(v["code"], v["message"]) for v in result["violations"] if v["code"] == "NON_INLINE_NOTAM_ID"]
    assert codes and any("1G216/26" in message for _, message in codes), result["violations"]
    assert any("1E1741/26" in message for _, message in codes), result["violations"]


@pytest.mark.parametrize("damaged", ["1G216/260", "1G2160/26", "1G216/26X", "1G216/26x", "ZZ1G216/26", "1z99999/26", "SX99999/26", "SX8/13", "NOTAM ZZ1/260", "NOTAM: ZZ1/260"])
def test_labelled_synthetic_unknown_or_damaged_printed_identity_fails_the_native_gate(tmp_path_factory, damaged):
    """Mutate only the actual local PDF copy; originals and genuine PDFs stay exact."""
    from app.odss.concise_pdf_gate import check_concise_pdf
    from app.odss.airport_pdf_analysis import airport_pdf_analysis, alternate_pdf_analysis
    case = rendered("SQ366", tmp_path_factory)
    flight, view = case["payload"]["flight"], case["payload"]["view"]["briefing"]
    assert all(damaged not in line["notam_ids"] for line in view["enroute_contact"]["procedure_lines"])
    directory = tmp_path_factory.mktemp("synthetic-id-corruption")
    candidate = directory / "labelled-synthetic-corrupted-id.pdf"
    with fitz.open(case["path"]) as document:
        page = document[ENROUTE_PAGE]
        hits = page.search_for("1G216/26")
        assert len(hits) == 1
        rect = hits[0]
        page.add_redact_annot(rect, fill=(1, 1, 1))
        page.apply_redactions()
        page.insert_text((rect.x0, rect.y1 - 1), damaged, fontsize=6)
        document.save(candidate)
    panels = view.get("airport_operational_panels") or []
    result = check_concise_pdf(candidate, view=view, flight=flight,
                              airport_analysis=airport_pdf_analysis(flight, panels),
                              alternate_analysis=alternate_pdf_analysis(flight, panels))
    identity = damaged.split()[-1]
    assert any(v["code"] == "NON_INLINE_NOTAM_ID" and v["message"].endswith(f": {identity}.") for v in result["violations"]), result["violations"]


def test_labelled_synthetic_aviation_values_are_not_notice_identities(tmp_path_factory):
    """Exercise physical PDF scanning with ordinary value grammars, not IDs."""
    from app.odss.concise_pdf_gate import check_concise_pdf
    from app.odss.airport_pdf_analysis import airport_pdf_analysis, alternate_pdf_analysis
    case = rendered("SQ366", tmp_path_factory)
    flight, view = case["payload"]["flight"], case["payload"]["view"]["briefing"]
    candidate = tmp_path_factory.mktemp("synthetic-value-control") / "labelled-synthetic-values.pdf"
    values = "TX32/1006Z TN26/0922Z FL330/350 TAS450/460 02C/20C 04L/22R 409FT/1200M 200FT/550M"
    with fitz.open(case["path"]) as document:
        document[4].insert_text((24, 24), "LABELLED SYNTHETIC VALUE CONTROL " + values, fontsize=4)
        document.save(candidate)
    with fitz.open(candidate) as document:
        assert values in document[4].get_text(), "the complete value control must be physically present"
    panels = view.get("airport_operational_panels") or []
    result = check_concise_pdf(candidate, view=view, flight=flight,
                              airport_analysis=airport_pdf_analysis(flight, panels),
                              alternate_analysis=alternate_pdf_analysis(flight, panels))
    assert result["valid"], result["violations"]

"""ITEM1 ATC-ABSENCE-WORDING (04 Oct 2026).

Codex's review of release 452: the genuine SQ882 09 Sep OFP prints Ho Chi Minh
1A2345/26 (p46), a radio-check frequency list for periods of low traffic and
no adverse weather. It is not an early-contact instruction and correctly
stays out of the call list. But page 6 and the dashboard then said "lead times
and frequencies are not held", and the communications finding on every flight
said "Early-contact, frequency and reporting requirements are not held" under
the title "FIR communication procedures unavailable" - while the same flights
print source-held calls with their frequencies (SQ304 Kabul 1G216/26 125.2).

Root cause: an empty call list (or an unapproved reference library) was
reported as the absence of the source information itself. The repair states
only what the analysis established: no early-contact instruction identified,
no approved reference held, nothing inferred from crossing times, and where
other communications information is kept. No notice becomes a call; no
frequency, lead, actor or condition is selected or inferred.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import fitz
import pytest

from app.analysis import run_odss_analysis
from app.odss.combined_brief import render_combined_briefing
from app.odss.concise_pdf_gate import normalized
from app.odss.engines import analyse
from app.odss.enroute_contact import STATE_SENTENCES, compose_enroute_contact
from app.odss.extraction_rules import EXTRACTION_RULES
from app.odss.parser import extract_pages
from tests.test_engine_regressions import _flight

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT.parent / "private_cfp_corpus" / "lido-briefing_SQ_882_09Sep2026_SIN_HKG.pdf"
ENROUTE_PAGE = 5

# An absence claim about values the source can print. The release-452 wording is
# the planted fault each assertion below must reject.
ABSENCE = re.compile(
    r"(?:frequenc|lead time)[^.;]*\bnot held|requirements are not held|procedures (?:are )?unavailable",
    re.IGNORECASE,
)
RELEASE_452_SENTENCE = (
    "No early-contact requirement is held in this OFP's FIR notices or in an approved reference; "
    "lead times and frequencies are not held and are not inferred from crossing times."
)
RELEASE_452_FINDING = (
    "FIR communication procedures unavailable",
    "Current approved communication procedures are unavailable.",
    "Early-contact, frequency and reporting requirements are not held.",
)

_RENDERED: dict = {}


def flat(text: str) -> str:
    return re.sub(r"\s+", " ", text)


def rendered(tmp_path_factory) -> dict:
    if _RENDERED:
        return _RENDERED
    if not SOURCE.is_file():
        pytest.skip(f"private CFP corpus file {SOURCE.name} is not available")
    root = tmp_path_factory.mktemp("atc-sq882-09sep")
    result = run_odss_analysis(SOURCE, root / "analysis", root / "reports", 1)
    payload = json.loads(Path(result["analysis_path"]).read_text(encoding="utf-8"))
    path = root / "SQ882_09SEP_Flight_Briefing.pdf"
    render_combined_briefing(
        payload["flight"], payload["findings"], payload.get("view", {}).get("warnings") or [], path,
        source_pdf_path=str(SOURCE), weather_charts=payload.get("weather_charts") or {},
    )
    with fitz.open(path) as document:
        pages = [page.get_text() for page in document]
    _RENDERED.update(payload=payload, pages=pages, source_pages=extract_pages(SOURCE))
    return _RENDERED


def test_the_absence_guard_rejects_the_release_452_wording():
    assert ABSENCE.search(RELEASE_452_SENTENCE)
    assert all(ABSENCE.search(text) for text in (RELEASE_452_FINDING[0], RELEASE_452_FINDING[2]))


def test_no_state_sentence_claims_source_values_are_absent():
    for state, sentence in STATE_SENTENCES.items():
        assert not ABSENCE.search(sentence), state
    assert "not inferred from crossing times" in STATE_SENTENCES["no_procedure_held"]
    assert "full FIR NOTAM source records" in STATE_SENTENCES["no_procedure_held"]


def test_an_empty_call_list_is_reported_as_no_instruction_identified_not_as_absent_values():
    flight = {
        "route_waypoints": [
            {"name": "-VVHM", "actm_minutes": 57, "fir_boundary": "VVHM", "source_page": 9},
            {"name": "-ZJSA", "actm_minutes": 127, "fir_boundary": "ZJSA", "source_page": 9},
        ],
        "notam_procedure_records": [],
        "extraction_rules": EXTRACTION_RULES,
    }
    composed = compose_enroute_contact(flight, [])
    assert composed["state"] == "no_procedure_held"
    assert not composed["procedures"] and not composed["required_calls"]
    assert composed["state_sentence"] == STATE_SENTENCES["no_procedure_held"]
    assert not ABSENCE.search(composed["state_sentence"])


def test_the_unapproved_reference_finding_does_not_claim_source_values_are_absent():
    waypoint = {"name": "-VOMF", "actm_minutes": 10, "fir_boundary": "VOMF", "msa_hundreds_ft": None, "vws": None, "airway_in": None}
    findings, _ = analyse(_flight(route_waypoints=[waypoint]))
    communication = next(item for item in findings if item["engine"] == "communications")
    assert communication["severity"] == "unknown"
    assert communication["data"]["reference_status"] != "approved"
    text = " ".join([communication["title"], communication["summary"], *communication["details"]])
    assert not ABSENCE.search(text), text
    assert "not inferred from crossing times" in text
    # The unapproved sample library still never reaches a pilot surface.
    assert "Chennai ATS/FIS" not in json.dumps(findings) and "ACTM 00.00" not in text


def test_sq882_09sep_reference_frequencies_stay_source_records_and_no_absence_is_claimed(tmp_path_factory):
    case = rendered(tmp_path_factory)
    source = flat("\n".join(case["source_pages"]))
    # The source fact: the OFP prints the Ho Chi Minh radio-check frequency list.
    assert "1A2345/26" in source and "RADIO CHECK ON THE FOLLOWING FREQ" in source and "134.050 MHZ (PRI)" in source

    composed = case["payload"]["view"]["briefing"]["enroute_contact"]
    # No call is invented from a reference frequency list.
    assert composed["state"] == "no_procedure_held"
    assert not composed["procedures"] and not composed["required_calls"]
    assert composed["state_sentence"] == STATE_SENTENCES["no_procedure_held"]

    communication = [item for item in case["payload"]["findings"] if item["engine"] == "communications"]
    assert len(communication) == 1
    finding_text = " ".join([communication[0]["title"], communication[0]["summary"], *communication[0]["details"]])
    assert not ABSENCE.search(finding_text), finding_text

    pages = case["pages"]
    assert normalized(composed["state_sentence"]) in normalized(pages[ENROUTE_PAGE])
    for number, page in enumerate(pages, start=1):
        assert not ABSENCE.search(flat(page)), f"PDF page {number} claims source values are absent"

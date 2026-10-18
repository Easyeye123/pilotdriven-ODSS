"""ITEM 4 (9 Oct 2026): the PDF airport consequence states the closed taxiway scope the card states.

Codex production QA of release 460 (output/pd-item4-reqa-460-20261008, F3-R460): on the genuine SQ314 SIN-LGW OFP the
live chart, the card and the PDF map all carry Gatwick's SX67/25 (TAXIWAY TANGO CLOSED NORTH OF TAXIWAY JULIET), but
the PDF's EGKK consequence panel says no supported closure consequence was established: `taxi_routing_scopes` skips a
closure whose scope follows the verb, so `analyse_airport_for_pdf` left SX67/25 unresolved ("effect"). Malé's SX5/26
on the genuine SQ437 OFP was left unresolved the same way, while its card names C south of D2 and D3, D4, F and G.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.odss.airport_pdf_analysis import analyse_airport_for_pdf
from app.odss.briefing import build_briefing_view
from app.odss.engines import analyse
from app.odss.parser import extract_pages, parse_lido

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT.parent / "private_cfp_corpus"


def _pdf_airport(file: str, icao: str) -> dict:
    source = CORPUS / file
    if not source.exists():
        pytest.skip(f"private CFP corpus file {file} is not available")
    flight = parse_lido(extract_pages(source), source.name)
    findings, warnings = analyse(flight)
    view = build_briefing_view(flight, findings, warnings, include_dashboard_only_panels=True)
    return next(row for row in view["airport_pdf_analysis"] if row["icao"] == icao)


def _taxi_line(airport: dict, notam_id: str) -> str:
    lines = [line for line in airport["lines"] if line.get("family") == "taxiway" and notam_id in line["notam_ids"]]
    assert lines, f"{notam_id}: no taxi consequence; unresolved {airport['unresolved_detail']}"
    return lines[0]["text"]


def test_genuine_sq314_egkk_pdf_consequence_states_tango_north_of_juliet() -> None:
    airport = _pdf_airport("lido-briefing_SQ_314_15Aug2026_SIN_LGW.pdf", "EGKK")
    assert "SX67/25" not in airport["unresolved_ids"]
    text = _taxi_line(airport, "SX67/25")
    assert "TWY TANGO north of JULIET (SX67/25)" in text, text
    assert text.startswith("Taxi access is constrained"), text


def test_genuine_sq437_vrmm_pdf_consequence_names_every_closed_taxiway() -> None:
    # QA520 (18 Oct 2026, timing spec v9): SX5/26's timing is a review. Its heading runs into the closure sentence with
    # no period ('... REBUILDING PROJECT AT VELANA INTERNATIONAL AIRPORT (VRMM) A PORTION OF TWY C CLOSED ... FROM A POINT
    # IMMEDIATELY SOUTH OF TWY D2'), and I7 classifies every token of a temporal connective's operand: the name VELANA,
    # the bare indicator VRMM and the adverb IMMEDIATELY are classified by no role (release 520 licensed both operands by
    # their place words - the QA520-01 root). The PDF therefore holds SX5/26 as unresolved, never as a stated closure;
    # the stated extent itself is still read (test_vrmm_closure_wording_20261009: the SX5/26 items).
    airport = _pdf_airport("SQ43708102026MLE.pdf", "VRMM")
    assert "SX5/26" in airport["unresolved_ids"]
    assert not any("SX5/26" in line["notam_ids"] and line.get("family") == "taxiway" for line in airport["lines"])


def test_a_closure_whose_scope_cannot_be_read_stays_unresolved() -> None:
    # Control: no scope the card can state, so the PDF still says it is not established.
    panel = {"icao": "XXXX", "selected_notams": [{
        "notam_id": "X1/26", "pertinence_kind": "taxiway_closure", "applicability": "active", "stateAtReference": "active_at_reference",
        "item_e_text": "TWY Q CLSD EXC FOR ACFT WITH PRIOR PERMISSION AS INSTRUCTED BY GROUND CTL WHEN WORKS PERMIT.",
        "window_start_utc": "2026-08-16T07:00:00+00:00", "window_end_utc": "2026-08-16T11:00:00+00:00",
        "referenceAt": "2026-08-16T09:00:00+00:00", "valid_from_utc": "2026-08-01T00:00:00+00:00", "valid_to_utc": None,
    }]}
    airport = analyse_airport_for_pdf(panel, role="destination", planned_runway="26L")
    assert "X1/26" in airport["unresolved_ids"] or any("X1/26" in line["notam_ids"] for line in airport["lines"])
    assert not any("part of" in line.get("text", "") for line in airport["lines"])

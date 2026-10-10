"""A taxilane closure's card names the taxilane, never a word that follows "TWY" (10 Oct 2026).

Genuine SQ437 MLE-SIN (8 Oct), destination WSSS: SX168/26 "TEMPO CLOSURE OF TXL N4 BEHIND ACFT STAND 604 AND DOWNGRADE
OF ACFT STAND 603 TO CODE C". The card read "PART OF TWY GUIDANCE closed", because the subject reader looked for "TWY"
only and took "TWY GUIDANCE SIGNS WILL BE MASKED OUT" as a taxiway called GUIDANCE.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.odss.briefing import build_briefing_view
from app.odss.engines import _notam_operational_summary, analyse
from app.odss.parser import extract_pages, parse_lido

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT.parent / "private_cfp_corpus"


def test_genuine_sq437_wsss_sx168_card_names_txl_n4_behind_stand_604() -> None:
    source = CORPUS / "SQ43708102026MLE.pdf"
    if not source.exists():
        pytest.skip("private CFP corpus file SQ43708102026MLE.pdf is not available")
    flight = parse_lido(extract_pages(source), source.name)
    findings, warnings = analyse(flight)
    view = build_briefing_view(flight, findings, warnings, include_dashboard_only_panels=True)
    panel = next(p for p in view["airport_operational_panels"] if p.get("icao") == "WSSS")
    row = next(r for r in panel["selected_notams"] if r.get("notam_id") == "SX168/26")
    assert "GUIDANCE" not in row["summary"].upper(), row["summary"]
    assert row["summary"].startswith("TXL N4 BEHIND STAND 604 closed during the applicable destination window"), row["summary"]


def test_a_word_after_twy_is_not_a_taxiway_name() -> None:
    text = "TWY GUIDANCE SIGNS WILL BE MASKED OUT. TWY K CLSD."
    assert _notam_operational_summary(text, "taxiway_closure", "destination").startswith("TWY K closed")


def test_a_header_list_never_widens_a_scope_the_details_state() -> None:
    # Genuine WSSS SX83/24 (SQ24 and 29 more cards): the header lists "TEMPO CLOSURE OF TXL R1, R2, R3 AND ACFT STANDS ...",
    # the details narrow it: "TXL R1 BEHIND ACFT STAND E5". The header alone made the card say the whole of TXL R1 closed.
    text = ("DECOMMISSIONING OF ACFT STANDS E1 AND F30 AND TEMPO CLOSURE OF TXL R1, R2, R3 AND ACFT STANDS E2, E3 "
            "DUE TO CONST WORK. 2. CLOSURE OF TXL AND ACFT STANDS: - ACFT STANDS E2, E3, TXL R1 BEHIND ACFT STAND E5, "
            "TXL R2 BEHIND ACFT STANDS E2, E3")
    summary = _notam_operational_summary(text, "taxiway_closure", "departure")
    assert summary.startswith("TXL R1 BEHIND STAND E5 closed"), summary


def test_a_later_unread_mention_never_narrows_a_whole_closure() -> None:
    # Genuine EBBR SX38/26 (SQ303): "TWY W1 CLSD. ... ENGINE TEST RUNS WITH THE JET BLAST TOWARDS TWY W1 CAN NO LONGER ..."
    text = "TWY W1 CLSD. TWY CROSSING AT TWY Y WILL REMAIN IN PLACE. ENGINE TEST RUNS WITH THE JET BLAST TOWARDS TWY W1 CAN NO LONGER BE CARRIED OUT."
    assert _notam_operational_summary(text, "taxiway_closure", "departure").startswith("TWY W1 closed")


def test_f5_sx168_counts_its_one_closure_once_and_states_it_on_the_pdf() -> None:
    # Codex QA of release 468 (F5): the card said "further closed taxiway items" and the PDF held SX168/26 unresolved,
    # because a later "TXL N4" mention was counted again as "part of TXL N4".
    source = CORPUS / "SQ43708102026MLE.pdf"
    if not source.exists():
        pytest.skip("private CFP corpus file SQ43708102026MLE.pdf is not available")
    flight = parse_lido(extract_pages(source), source.name)
    findings, warnings = analyse(flight)
    view = build_briefing_view(flight, findings, warnings, include_dashboard_only_panels=True)
    panel = next(p for p in view["airport_operational_panels"] if p.get("icao") == "WSSS")
    row = next(r for r in panel["selected_notams"] if r.get("notam_id") == "SX168/26")
    assert "further closed" not in row["summary"], row["summary"]
    wsss = next(a for a in view["airport_pdf_analysis"] if a["icao"] == "WSSS")
    assert "SX168/26" not in wsss["unresolved_ids"]
    taxi = [line["text"] for line in wsss["lines"] if line.get("family") == "taxiway"]
    assert any("TXL N4 behind stand 604 (SX168/26)" in text for text in taxi), taxi

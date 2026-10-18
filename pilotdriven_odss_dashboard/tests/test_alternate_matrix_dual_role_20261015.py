"""The alternate matrix reads the same held station records as the station's cards (QA504 dual-role, 15 Oct 2026).

Codex reconfirmed it live on release 504: SQ606 RKPC printed FORECAST UNAVAILABLE and CONSTRAINT UNAVAILABLE in the
alternate matrix while its weather card held the TAF and its airport card held SX56/26 (PDF page 4 even printed the
RWY 07 ILS/DME consequence); SQ437 WMKK the same. Root cause: briefing._alternate_assessment_rows kept only weather
whose LIDO print heading (``source_role``) was an alternate heading, and only notices whose single primary engine role
was "destination alternate" and whose print heading was an alternate one. LIDO prints a station that is also the
fuel-enroute airport once, under FUEL ENROUTE AIRPORT, and a notice active in both windows takes the fuel-enroute role
as primary - so the matrix found nothing while the cards (and page 4's alternate analysis, which reads the per-role
assessment) held the records. The matrix now reads the card's TAF (else METAR) and the card's notices the engine
assessed for the destination-alternate window.

For every station in the 30 held originals that is a planned alternate and holds another role, the matrix row (which
the dashboard and PDF page 4 both print) must hold what the station's card holds.
"""
from __future__ import annotations

import os
from pathlib import Path
import tempfile

import fitz
import pytest

from app.odss.briefing import build_briefing_view
from app.odss.combined_brief import render_combined_briefing
from app.odss.engines import analyse
from app.odss.parser import extract_pages, parse_lido

ROOT = Path(__file__).resolve().parents[1]
ALTERNATE = "destination alternate"


def _corpus() -> Path:
    configured = os.environ.get("PILOTDRIVEN_PRIVATE_CFP_CORPUS_DIR")
    corpus = Path(configured) if configured else ROOT.parent / "private_cfp_corpus"
    if not corpus.is_dir():
        if configured:
            raise FileNotFoundError(f"Configured PILOTDRIVEN_PRIVATE_CFP_CORPUS_DIR is missing: {corpus}")
        pytest.skip("the private CFP corpus is not available")
    return corpus


def _alternate_window_notices(panel: dict) -> list[str]:
    """The card's notices the engine assessed for the destination-alternate window (active or review)."""
    held = []
    for notice in panel.get("selected_notams") or []:
        assessed = [row for row in notice.get("role_applicability") or [] if row.get("role") == ALTERNATE]
        relevant = any(row.get("applicability") in {"active", "review"} for row in assessed) if assessed else (
            notice.get("role") == ALTERNATE)
        if relevant:
            held.append(notice.get("notam_id"))
    return held


def _view(pdf: Path) -> tuple[dict, list, list, dict]:
    flight = parse_lido(extract_pages(pdf), pdf.name)
    findings, warnings = analyse(flight)
    return flight, findings, warnings, build_briefing_view(
        flight, findings, warnings, None, None, include_dashboard_only_panels=True)


def test_every_dual_role_alternate_matrix_row_holds_what_its_cards_hold() -> None:
    checked: list[str] = []
    problems: list[str] = []
    for pdf in sorted(_corpus().glob("*.pdf")):
        _, _, _, view = _view(pdf)
        panels = {panel.get("icao"): panel for panel in view["airport_operational_panels"]}
        for row in view["alternate_assessment_rows"]:
            if (row.get("assessment") or {}).get("row_not_read"):
                continue
            panel = panels.get(row["airport"]) or {}
            if not [role for role in panel.get("roles") or [] if role != ALTERNATE]:
                continue
            label = f"{pdf.name} {row['airport']} {panel.get('roles')}"
            checked.append(label)
            weather = panel.get("weather") or {}
            card_forecast = weather.get("taf") or weather.get("metar")
            if card_forecast:
                if row["forecast"]["status"] != "held" or row["forecast"]["text"] != card_forecast["text"].strip() \
                        or row["forecast"]["source_page"] != card_forecast["source_page"]:
                    problems.append(f"{label}: the card holds {card_forecast['record_type']} p{card_forecast['source_page']}, "
                                    f"the matrix {row['forecast']['status']}")
            elif row["forecast"]["status"] != "unavailable":
                problems.append(f"{label}: the matrix holds a forecast the card does not")
            notices = _alternate_window_notices(panel)
            if notices and row["constraint"]["status"] != "held":
                problems.append(f"{label}: the card holds {notices} for the alternate window, the matrix holds none")
            if row["constraint"]["status"] == "held" and row["constraint"]["notam_id"] not in notices:
                problems.append(f"{label}: the matrix holds {row['constraint']['notam_id']}, not a card notice {notices}")
    assert len(checked) >= 8, checked
    for station in ("SQ60606092026SIN.pdf RKPC", "SQ43708102026MLE.pdf WMKK", "lido-briefing_SQ_297_16Aug2026_SIN_CHC.pdf YBBN",
                    "SQ43807102026SIN.pdf VCBI"):
        assert any(label.startswith(station) for label in checked), station
    assert not problems, "\n".join(problems)


def test_sq606_rkpc_reads_one_source_on_the_dashboard_matrix_and_pdf_page_4() -> None:
    """The dashboard matrix row holds RKPC's TAF and an alternate-window notice; PDF page 4 (which prints the plan line
    from the same matrix row and the consequences from the same card notices) keeps the RKPC line and its SX56/26
    consequence, and nothing on it says a forecast is unavailable."""
    pdf = _corpus() / "SQ60606092026SIN.pdf"
    if not pdf.is_file():
        pytest.skip("SQ606 is not in the corpus")
    flight, findings, warnings, view = _view(pdf)
    rkpc = next(row for row in view["alternate_assessment_rows"] if row["airport"] == "RKPC")
    card = next(panel for panel in view["airport_operational_panels"] if panel["icao"] == "RKPC")
    assert rkpc["forecast"]["status"] == rkpc["constraint"]["status"] == "held"
    assert (rkpc["forecast"]["record_type"], rkpc["forecast"]["source_page"]) == ("TAF", 24)
    assert rkpc["forecast"]["text"] == card["weather"]["taf"]["text"]
    assert rkpc["constraint"]["notam_id"] in {"A1100/26", "SX56/26"}
    with tempfile.TemporaryDirectory() as scratch:
        out = Path(scratch) / "six-pages.pdf"
        render_combined_briefing(flight, findings, warnings, out, source_pdf_path=str(pdf))
        with fitz.open(out) as document:
            assert document.page_count == 6
            page4 = " ".join(document[3].get_text().split())
    assert "RKPC/07 ALTERNATE" in page4 and "RWY 07 ILS/DME (SX56/26)" in page4
    assert "UNAVAILABLE" not in page4

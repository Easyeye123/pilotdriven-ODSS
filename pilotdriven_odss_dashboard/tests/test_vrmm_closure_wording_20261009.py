"""ITEM 4, VRMM (9 Oct 2026): the airport card names every taxiway Malé's SX5/26 closes.

David, 7 Oct: "The NOTAMS for VRMM was not highlighted at all ... You check the wordings ... Male". On his genuine
SQ437 MLE-SIN OFP (8 Oct) the departure card read "PART OF TWY C closed during the applicable departure window. Its
bounds could not be read completely from the notice" - while SX5/26 states the extent ("FROM A POINT IMMEDIATELY
SOUTH OF TWY D2 (EXCLUDING TWY D2) TO A DISTANCE OF APPROXIMATELY 1,440M") and closes four more taxiways ("TWYS D3,
D4, F, AND G ARE ALSO CLOSED DURING THIS PERIOD"), which the card never named.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.odss.airport_taxi_consequences import taxiway_closure_items
from app.odss.briefing import build_briefing_view
from app.odss.engines import analyse
from app.odss.parser import extract_pages, parse_lido

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT.parent / "private_cfp_corpus"

SX5_ITEM_E = (
    "TEMPORARY CHANGES TO AERODROME OPERATIONS TO TWY C (PHASE 3) REBUILDING PROJECT AT VELANA INTERNATIONAL "
    "AIRPORT (VRMM) A PORTION OF TWY C CLOSED TO ALL AIRCRAFT OPERATIONS FROM A POINT IMMEDIATELY SOUTH OF TWY D2 "
    "(EXCLUDING TWY D2) TO A DISTANCE OF APPROXIMATELY 1,440M. TWYS D3, D4, F, AND G ARE ALSO CLOSED DURING THIS "
    "PERIOD. RUNWAY HOLDING POSITION (RHP) AND INTERMEDIATE HOLDING POSITION (IHP) MARKINGS - A RUNWAY HOLDING "
    "POSITION (RHP) WILL BE ESTABLISHED ON TWY D2, LOCATED 110M FROM RWY CENTERLINE."
)


def _card(file: str, role: str) -> str:
    source = CORPUS / file
    if not source.exists():
        pytest.skip(f"private CFP corpus file {file} is not available")
    flight = parse_lido(extract_pages(source), source.name)
    findings, warnings = analyse(flight)
    view = build_briefing_view(flight, findings, warnings, include_dashboard_only_panels=True)
    panel = next(p for p in view["airport_operational_panels"] if p.get("icao") == "VRMM" or "VRMM" in str(p.get("title")))
    rows = [row for row in panel["selected_notams"] if "SX5/26" in str(row.get("notam_id") or row.get("title") or "")]
    assert rows, f"no SX5/26 row on the VRMM {role} card"
    return str(rows[0]["summary"])


def test_sx5_items_are_read_with_the_stated_extent_and_the_listed_taxiways() -> None:
    items, exact = taxiway_closure_items(SX5_ITEM_E)
    assert exact
    assert items == [
        ("partial", "TWY C south of D2 for about 1,440 m"),
        ("surface", "TWY D3"),
        ("surface", "TWY D4"),
        ("surface", "TWY F"),
        ("surface", "TWY G"),
    ]


@pytest.mark.parametrize(("file", "role"), [("SQ43708102026MLE.pdf", "departure"), ("SQ43807102026SIN.pdf", "destination")])
def test_genuine_vrmm_card_states_c_south_of_d2_and_names_d3_d4_f_g(file: str, role: str) -> None:
    summary = _card(file, role)
    assert summary.startswith("TWY C SOUTH OF D2 FOR ABOUT 1,440 M closed during the applicable"), summary
    assert "TWY D3, D4, F and G are also closed" in summary, summary
    assert "could not be read" not in summary and "further closed taxiway item" not in summary, summary


def test_a_listed_whole_closure_is_still_counted_when_an_item_is_unread() -> None:
    # Control: the count-only wording stays wherever any listed element was not read.
    items, exact = taxiway_closure_items("TWY A AND TWY B CLSD. TWY C CLSD DUE WIP EXC ACFT WITH PRIOR PERMISSION FROM ATC.")
    assert ("surface", "TWY A") in items and ("surface", "TWY B") in items

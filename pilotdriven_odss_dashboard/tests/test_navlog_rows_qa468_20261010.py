"""Every printed navlog row keeps its own coordinate, MSA and VWS (Codex QA of release 468, 10 Oct 2026).

Codex's independent QA (output/pd-odss-etp-taxilane-qa-468/REPORT.md) found four more ways a navlog row was lost or
misread, the first of the same class as the ETP rows fixed on 468:
- F1: ARINC 424 latitude/longitude fix names ("5350N" = 53N 050W, "18E30" = 18N 130E) were not waypoint rows, so the row
  before each (a FIR boundary or ENTRY point) took their coordinates: SQ34's -KZAK 706 NM off, SQ023's 5350N VWS 005
  event missing.
- F2: a navlog whose first row is alone at the foot of a page (the column header is on that page) started a page late:
  SQ365 SOSAK, SQ297/SQ304 IBIXU dropped.
- F3: "EXITI" (SQ304), an ordinary fix, was treated as a computed EDTO EXIT point and its MSA 069 dropped.
- F4: a row with a blank MSA column (each destination) took the first three digits of its distance as the MSA.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.odss.engines import detect_vws_events
from app.odss.parser import extract_pages, parse_lido

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT.parent / "private_cfp_corpus"
_CACHE: dict[str, list[dict]] = {}


def _waypoints(file: str) -> list[dict]:
    if file not in _CACHE:
        source = CORPUS / file
        if not source.exists():
            pytest.skip(f"private CFP corpus file {file} is not available")
        _CACHE[file] = parse_lido(extract_pages(source), source.name)["route_waypoints"]
    return _CACHE[file]


def _at(waypoints: list[dict], name: str, actm: int | None = None) -> dict:
    return next(w for w in waypoints if w["name"] == name and (actm is None or w["actm_minutes"] == actm))


def _position(waypoint: dict) -> tuple[float, float]:
    return round(waypoint["latitude"], 4), round(waypoint["longitude"], 4)


def test_f1_sq023_named_latitude_longitude_fixes_are_waypoints_with_their_own_rows() -> None:
    waypoints = _waypoints("SQ02325072026JFK.pdf")
    for name, position in {"5350N": (53.0, -50.0), "5640N": (56.0, -40.0), "5730N": (57.0, -30.0), "5620N": (56.0, -20.0)}.items():
        fix = _at(waypoints, name)
        assert _position(fix) == position and fix["msa_hundreds_ft"] == 20, (name, fix)
    assert _position(_at(waypoints, "-CZQX", 133)) == (52.1517, -53.2933)  # 02.13: N52 09.1 W053 17.6
    assert _position(_at(waypoints, "ENTRY1")) == (54.0883, -46.835)  # N54 05.3 W046 50.1
    assert _at(waypoints, "5350N")["vws"] == 5
    assert "5350N" in [event["first_high"]["name"] for event in detect_vws_events(waypoints)]


def test_f1_sq34_pacific_fixes_and_the_kzak_boundary_keep_their_own_positions() -> None:
    waypoints = _waypoints("lido-briefing_SQ_34_15Aug2026_SIN_SFO.pdf")
    names = [w["name"] for w in waypoints]
    for name in ("18E30", "24E40", "32E50", "38E60", "42E70", "44E80"):
        assert name in names, name
    assert _position(_at(waypoints, "18E30")) == (18.0, 130.0)
    assert _position(_at(waypoints, "-KZAK", 509)) == (40.1667, 165.0)  # 08.29: N40 10.0 E165 00.0
    # SQ34 enters Oakland FIR first at 04.07 exactly on 18E30 (N18 00.0 E130 00.0): same point, both rows printed.
    assert _position(_at(waypoints, "-KZAK", 247)) == _position(_at(waypoints, "18E30")) == (18.0, 130.0)


@pytest.mark.parametrize(("file", "first"), [
    ("SQ36507082026FCO.pdf", "SOSAK"),
    ("lido-briefing_SQ_297_16Aug2026_SIN_CHC.pdf", "IBIXU"),
    ("lido-briefing_SQ_304_12Jul2026_SIN_BRU.pdf", "IBIXU"),
])
def test_f2_a_navlog_whose_first_row_is_alone_at_the_foot_of_a_page_keeps_it(file: str, first: str) -> None:
    assert _waypoints(file)[0]["name"] == first


def test_f3_exiti_is_an_ordinary_fix_with_its_own_msa() -> None:
    waypoints = _waypoints("lido-briefing_SQ_304_12Jul2026_SIN_BRU.pdf")
    assert _at(waypoints, "EXITI")["msa_hundreds_ft"] == 69


@pytest.mark.parametrize(("file", "destination"), [
    ("SQ02422072026SIN.pdf", "KJFK"),
    ("lido-briefing_SQ_482_14Aug2026_SIN_JNB.pdf", "FAOR"),
])
def test_f4_a_blank_msa_column_is_no_msa_not_the_distance(file: str, destination: str) -> None:
    assert _at(_waypoints(file), destination)["msa_hundreds_ft"] is None


def test_f4_an_asterisked_msa_keeps_its_asterisk() -> None:
    # "137*0060": the asterisk joins the MSA to the distance; the MSA is 137 and marked, as before (SQ438 OKABU).
    okabu = _at(_waypoints("SQ43807102026SIN.pdf"), "OKABU")
    assert okabu["msa_hundreds_ft"] == 137 and okabu["msa_asterisk"] is True

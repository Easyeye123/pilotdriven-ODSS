"""The navlog's ETP rows with a scenario suffix are waypoints of their own (10 Oct 2026).

David, 8 Oct, on his genuine SQ437 MLE-SIN OFP: "OBDAL waypoint had triggered the depress for SQ438 ... Look at OBDAL and
see 114?". Reading it showed a parser defect: LIDO prints equal-time points with a scenario suffix ("**ETP1 -1D   02.03
0.10 ..."), which `_WAYPOINT_LINE` did not recognise. The row before it (OBDAL) stayed open and took the ETP's
coordinate line - the ETP's position, and the first three digits of its leg distance as its MSA (0074 -> 007). 28 such
rows in 14 of the 30 originals. A high-MSA waypoint followed by an ETP would have lost its terrain trigger.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.odss.parser import extract_pages, parse_lido

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT.parent / "private_cfp_corpus"


def _waypoints(file: str) -> tuple[list[dict], list[str]]:
    source = CORPUS / file
    if not source.exists():
        pytest.skip(f"private CFP corpus file {file} is not available")
    pages = extract_pages(source)
    printed = [line.strip() for text in pages for line in text.splitlines() if line.strip().startswith("**ETP")]
    return parse_lido(pages, source.name)["route_waypoints"], printed


def _named(waypoints: list[dict], name: str) -> dict:
    return next(w for w in waypoints if w["name"] == name)


def _etp_positions(file: str) -> list[tuple[float, float]]:
    """The coordinate line printed under each "**ETPn -xx" navlog row."""
    lines = [line.strip() for text in extract_pages(CORPUS / file) for line in text.splitlines()]
    positions = []
    for index, line in enumerate(lines):
        if re.match(r"^\*\*ETP\S*\s+-\d[A-Z]\s", line):
            coordinate = next(row for row in lines[index + 1:index + 4] if re.match(r"^[NS]\d{2}\s", row))
            parts = coordinate.split()
            lat = (1 if parts[0][0] == "N" else -1) * (int(parts[0][1:]) + float(parts[1]) / 60)
            lon = (1 if parts[2][0] == "E" else -1) * (int(parts[2][1:]) + float(parts[3]) / 60)
            positions.append((round(lat, 4), round(lon, 4)))
    return positions


def test_genuine_sq437_obdal_keeps_its_own_position_and_msa() -> None:
    waypoints, _ = _waypoints("SQ43708102026MLE.pdf")
    obdal = _named(waypoints, "OBDAL")  # N03 18.8 E087 44.8 020 0114 410
    assert obdal["msa_hundreds_ft"] == 20
    assert (round(obdal["latitude"], 4), round(obdal["longitude"], 4)) == (3.3133, 87.7467)
    names = [w["name"] for w in waypoints]
    assert names[names.index("OBDAL") + 1] == "VIPIG", "the ETP row closes OBDAL and is not a route waypoint"


def test_genuine_sq438_obdal_keeps_its_own_position_and_msa() -> None:
    waypoints, _ = _waypoints("SQ43807102026SIN.pdf")
    obdal = _named(waypoints, "OBDAL")  # N03 18.8 E087 44.8 020 0187 400
    assert obdal["msa_hundreds_ft"] == 20
    assert (round(obdal["latitude"], 4), round(obdal["longitude"], 4)) == (3.3133, 87.7467)


def test_genuine_sq24_62n20_keeps_its_high_msa_and_the_terrain_window_reaches_it() -> None:
    from app.odss.engines import detect_terrain_events
    waypoints, _ = _waypoints("lido-briefing_SQ_24_15Aug2026_SIN_JFK.pdf")
    assert _named(waypoints, "62N20")["msa_hundreds_ft"] == 111
    windows = [(e["first_high"]["name"], e["last_high"]["name"], (e.get("drop") or {}).get("name")) for e in detect_terrain_events(waypoints)]
    assert ("63N30", "62N20", "59N10") in windows, windows


@pytest.mark.parametrize("file", ["lido-briefing_SQ_34_15Aug2026_SIN_SFO.pdf", "SQ48125082026JNB.pdf", "lido-briefing_SQ_297_16Aug2026_SIN_CHC.pdf"])
def test_no_waypoint_takes_an_etp_position(file: str) -> None:
    waypoints, _ = _waypoints(file)
    etps = _etp_positions(file)
    assert etps, file
    held = {(round(w["latitude"] or 0, 4), round(w["longitude"] or 0, 4)): w["name"] for w in waypoints}
    assert not [held[position] for position in etps if position in held]
    assert not [w for w in waypoints if w["name"].startswith("**ETP")]

"""Route-map aerodrome anchors: every drawn airport and route vertex sits where the OFP puts it (item 11, 13 Oct 2026).

David, WhatsApp 3 Oct 2026: "Your routing has gone haywire ... It ended up instead of Singapore now is in Bali."

Root cause (release 494): the map layers took aerodrome identity from list position and from name matching, never from
evidence. ``build_map_contract`` and ``build_route_map`` renamed whichever coordinate-bearing route row came first or
last to the departure/destination ICAO, and ``_significance_index`` keyed the departure/destination/NOTAM-airport roles
by waypoint name, so every other row sharing that name inherited them. The labelled schematic fallback also threaded
the route line through every marker, EDTO ETPs included. Nothing checked that a row given an airport identity is the
airport, so any route row lost at the start (or end) of the parsed log moves "WSSS" to wherever the first (or last)
held row happens to be. On the genuine SQ297 SIN-CHC route that row can be BLI, the Bali VOR (S08 45.0 E115 09.8).

Tolerances, stated once:
- route vertex: the OFP-printed coordinate of that row (print resolution 0.1 minute), checked to 0.1 NM;
- destination aerodrome: the OFP prints the aerodrome row; it must be within 2 NM of the AIP reference point;
- departure aerodrome: LIDO never prints the departure aerodrome, only its first fix (4.6-14.2 NM away across the 30
  originals); a departure label must be within 25 NM of the AIP reference point.
Truth is independent of the parser: route rows are re-read here from the PDF text, aerodromes come from an AIP table.
"""
from __future__ import annotations

from copy import deepcopy
from functools import lru_cache
import json
import math
from pathlib import Path
import re

import fitz
import pytest

from app.odss.briefing import build_route_map
from app.odss.engines import analyse
from app.odss.parser import extract_pages, parse_lido
from app.odss_map_v06.aws_location import _static_overlay
from app.odss_map_v06.config import MapSettings
from app.odss_map_v06.geojson import build_map_contract
from app.odss_map_v06.schematic import _render_svg

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT.parent / "private_cfp_corpus"
ARP = {
    code: tuple(value)
    for code, value in json.loads(
        (ROOT / "tests" / "fixtures" / "aerodrome_reference_points_20261013.json").read_text(encoding="utf-8")
    )["points"].items()
}
VERTEX_TOLERANCE_NM = 0.1
DESTINATION_TOLERANCE_NM = 2.0
DEPARTURE_TOLERANCE_NM = 25.0
AIRPORT_ROLES = {"departure", "destination", "notam_airport"}
BALI_BLI = (-8.75, 115.16333)  # BLI as printed in the genuine SQ297 navlog: S08 45.0 E115 09.8
# The app states an unplaced aerodrome in this exact sentence (web/src/lib/route-endpoint-status.ts; pinned in the
# app's tests/route-endpoint-status-20261013.test.mjs).
SQ297_DEPARTURE_STATEMENT = (
    "Departure aerodrome WSSS not drawn: the held route is 929 NM shorter than the OFP ground distance (4601 NM), "
    "so its first held row is not the start of the route. The route is drawn from BLI."
)


def _nm(first: tuple[float, float], second: tuple[float, float]) -> float:
    lat1, lon1, lat2, lon2 = map(math.radians, (*first, *second))
    value = math.sin(lat1) * math.sin(lat2) + math.cos(lat1) * math.cos(lat2) * math.cos(lon2 - lon1)
    return 3440.065 * math.acos(max(-1.0, min(1.0, value)))


def _corpus_files() -> list[Path]:
    files = sorted(CORPUS.glob("*.pdf")) if CORPUS.is_dir() else []
    if len(files) != 30:
        pytest.skip(f"the 30-OFP private corpus is not mounted at {CORPUS} ({len(files)} PDFs)")
    return files


_COORDINATE = re.compile(r"^([NS])(\d{2}) (\d{2}\.\d) ([EW])(\d{3}) (\d{2}\.\d)\b")
_ROW = re.compile(r"^(\S+)\s+(?:\d{3}(?:\.\d+)?\s+)?(\d{2}\.\d{2})\b")


@lru_cache(maxsize=None)
def _printed_route(path: str, destination: str) -> tuple[tuple[str, float, float], ...]:
    """Navlog rows re-read from the PDF text, independently of the parser.

    From the "POSN FREQ ACTM" header on, each printed coordinate line belongs to the nearest row above it that names a
    position and its ACTM. Equal-time-point scenario rows are not route rows. Reading stops at the destination row.
    """
    document = fitz.open(path)
    try:
        lines = [line.strip() for page in document for line in page.get_text("text").splitlines()]
    finally:
        document.close()
    start = next(index for index, line in enumerate(lines) if re.match(r"^POSN\s+FREQ\s+ACTM\b", line))
    rows: list[tuple[str, float, float]] = []
    owner: str | None = None
    for line in lines[start:]:
        coordinate = _COORDINATE.match(line)
        if coordinate and owner:
            name, owner = owner, None
            if name.startswith("**ETP"):
                continue
            latitude = (int(coordinate[2]) + float(coordinate[3]) / 60) * (1 if coordinate[1] == "N" else -1)
            longitude = (int(coordinate[5]) + float(coordinate[6]) / 60) * (1 if coordinate[4] == "E" else -1)
            rows.append((name, latitude, longitude))
            if name == destination:
                break
            continue
        row = _ROW.match(line)
        if row:
            owner = row[1]
    return tuple(rows)


@lru_cache(maxsize=None)
def _parsed(path: str) -> dict:
    source = Path(path)
    return parse_lido(extract_pages(source), source.name)


def _surfaces(flight: dict) -> dict:
    findings, _warnings = analyse(deepcopy(flight))
    contract = build_map_contract(deepcopy(flight), findings, MapSettings())
    return {"contract": contract, "route_map": build_route_map(deepcopy(flight))}


@lru_cache(maxsize=None)
def _genuine(path: str) -> tuple[dict, dict]:
    flight = _parsed(path)
    return flight, _surfaces(flight)


def _route_vertices(contract) -> list[tuple[float, float]]:
    geometry = contract.route_geojson["features"][0]["geometry"]
    segments = [geometry["coordinates"]] if geometry["type"] == "LineString" else geometry["coordinates"]
    return [(float(lat), float(lon)) for segment in segments for lon, lat in segment]


def _route_markers(contract) -> list[dict]:
    return [feature for feature in contract.markers_geojson["features"] if str(feature["id"]).startswith("wp-")]


def _airport_violations(flight: dict, labelled: list[tuple[str, str, set[str], tuple[float, float]]]) -> list[str]:
    """``labelled``: (surface id, drawn name, airport roles, position) for every drawn point.

    A point that carries an aerodrome's name or an aerodrome role must be at that aerodrome. The NOTAM-airport role
    names no aerodrome of its own, so it is only valid on the flight's departure or destination aerodrome.
    """
    departure, destination = flight["departure"], flight["destination"]
    failures = []
    for surface, name, roles, position in labelled:
        claims = set()
        if name == departure or "departure" in roles:
            claims.add(departure)
        if name == destination or "destination" in roles:
            claims.add(destination)
        if "notam_airport" in roles and not claims:
            failures.append(f"{surface}: {name} is drawn as a NOTAM airport but is not an aerodrome of this flight")
        for code in claims:
            limit = DESTINATION_TOLERANCE_NM if code == destination and code != departure else DEPARTURE_TOLERANCE_NM
            distance = _nm(ARP[code], position)
            if distance > limit:
                failures.append(f"{surface}: {name} drawn as {code} {distance:.0f} NM from {code} (limit {limit:g} NM)")
    return failures


def _contract_labels(contract) -> list[tuple[str, str, set[str], tuple[float, float]]]:
    rows = []
    for feature in contract.markers_geojson["features"]:
        properties = feature["properties"]
        roles = {properties.get("role"), *(properties.get("roles") or [])} & AIRPORT_ROLES
        lon, lat = feature["geometry"]["coordinates"]
        rows.append((f"contract {feature['id']}", str(properties.get("name")), roles, (lat, lon)))
    return rows


def _route_map_labels(route_map: dict) -> list[tuple[str, str, set[str], tuple[float, float]]]:
    return [
        (f"route_map[{index}]", str(point.get("display_name")), {point.get("role")} & AIRPORT_ROLES,
         (point["latitude"], point["longitude"]))
        for index, point in enumerate(route_map.get("points") or [])
    ]


def _static_labels(contract) -> list[tuple[str, str, set[str], tuple[float, float]]]:
    rows = []
    for feature in _static_overlay(contract)["features"]:
        if feature["geometry"]["type"] != "Point" or "label" not in feature["properties"]:
            continue
        lon, lat = feature["geometry"]["coordinates"]
        source = next(
            marker for marker in contract.markers_geojson["features"]
            if marker["geometry"]["coordinates"] == [lon, lat]
            and str(marker["properties"].get("name") or "")[:12] == feature["properties"]["label"]
        )
        properties = source["properties"]
        roles = {properties.get("role"), *(properties.get("roles") or [])} & AIRPORT_ROLES
        rows.append((f"static overlay {feature['properties']['label']}", feature["properties"]["label"], roles, (lat, lon)))
    return rows


_POLYLINE = re.compile(r'<polyline points="([^"]+)"')


def _schematic_vertex_failures(contract, printed: tuple[tuple[str, float, float], ...]) -> list[str]:
    """The schematic draws the route line only through the printed route, in order (one polyline per side of the
    antimeridian, as the canonical route geometry is split)."""
    width, height = 1600, 900
    svg = _render_svg(contract, width=width, height=height)
    lines = _POLYLINE.findall(svg)
    geometry = contract.route_geojson["features"][0]["geometry"]
    segments = 1 if geometry["type"] == "LineString" else len(geometry["coordinates"])
    if len(lines) != segments:
        return [f"schematic: {len(lines)} route polylines for {segments} route segment(s)"]
    drawn = [tuple(float(value) for value in pair.split(",")) for line in lines for pair in line.split()]
    bounds = contract.bounds
    span_x, span_y = max(bounds.east - bounds.west, 0.1), max(bounds.north - bounds.south, 0.1)
    expected = [
        (30 + (lon - bounds.west) / span_x * (width - 60), height - 30 - (lat - bounds.south) / span_y * (height - 60))
        for _name, lat, lon in printed
    ]
    if len(drawn) != len(expected):
        extra = len(drawn) - len(expected)
        return [f"schematic: route line has {len(drawn)} vertices for {len(expected)} printed rows ({extra:+d})"]
    return [
        f"schematic: vertex {index} drawn at {got} instead of printed {printed[index][0]} {want}"
        for index, (got, want) in enumerate(zip(drawn, expected))
        if abs(got[0] - want[0]) > 0.11 or abs(got[1] - want[1]) > 0.11
    ][:3]


def _vertex_failures(surface: str, drawn: list[tuple[float, float]], printed) -> list[str]:
    if len(drawn) != len(printed):
        return [f"{surface}: {len(drawn)} drawn vertices for {len(printed)} printed rows"]
    return [
        f"{surface}: vertex {index} ({name}) drawn {_nm((lat, lon), position):.2f} NM from its printed position"
        for index, ((name, lat, lon), position) in enumerate(zip(printed, drawn))
        if _nm((lat, lon), position) > VERTEX_TOLERANCE_NM
    ][:3]


def _invariant_failures(path: Path) -> list[str]:
    flight, surfaces = _genuine(str(path))
    contract, route_map = surfaces["contract"], surfaces["route_map"]
    printed = _printed_route(str(path), flight["destination"])
    failures = []
    failures += _vertex_failures("contract route line", _route_vertices(contract), printed)
    failures += _vertex_failures(
        "contract route markers",
        [(marker["geometry"]["coordinates"][1], marker["geometry"]["coordinates"][0]) for marker in _route_markers(contract)],
        printed,
    )
    failures += _vertex_failures(
        "PDF/SVG route map", [(point["latitude"], point["longitude"]) for point in route_map["points"]], printed,
    )
    failures += _schematic_vertex_failures(contract, printed)
    failures += _airport_violations(
        flight, _contract_labels(contract) + _route_map_labels(route_map) + _static_labels(contract),
    )
    return [f"{path.name}: {failure}" for failure in failures]


def test_aerodrome_reference_table_agrees_with_every_printed_destination_row() -> None:
    files = _corpus_files()
    checked = set()
    for path in files:
        flight = _parsed(str(path))
        name, lat, lon = _printed_route(str(path), flight["destination"])[-1]
        assert name == flight["destination"], path.name
        assert _nm(ARP[name], (lat, lon)) < 1.0, (path.name, name)
        checked.add(name)
    assert {code for path in files for code in (_parsed(str(path))["departure"], _parsed(str(path))["destination"])} <= set(ARP)
    assert len(checked) == 19


def test_independent_navlog_reader_agrees_with_the_parser_on_all_30_originals() -> None:
    """The truth source is not the code under test, but it must describe the same printed rows."""
    for path in _corpus_files():
        flight = _parsed(str(path))
        printed = _printed_route(str(path), flight["destination"])
        parsed = [(row["name"], row["latitude"], row["longitude"]) for row in flight["route_waypoints"]]
        assert [row[0] for row in printed] == [row[0] for row in parsed], path.name
        assert all(abs(a[1] - b[1]) < 1e-9 and abs(a[2] - b[2]) < 1e-9 for a, b in zip(printed, parsed)), path.name


def test_every_drawn_airport_and_route_vertex_is_where_the_ofp_puts_it_on_all_30_originals() -> None:
    """Corpus-wide invariant over the map contract (dashboard map, print snapshot, static fallback), the labelled
    schematic fallback, and the route map drawn in the PDF/SVG reports."""
    failures = [failure for path in _corpus_files() for failure in _invariant_failures(path)]
    assert not failures, f"{len(failures)} placement failures:\n" + "\n".join(failures)


def test_genuine_sq023_second_kzbw_boundary_is_not_drawn_as_the_departure_airport() -> None:
    """Genuine SQ23 JFK-SIN: two rows share the name -KZBW. The first is the first held row; the second (37 NM on,
    52 NM from JFK) inherited "departure" and "NOTAM airport" by name and was drawn in departure colour."""
    path = CORPUS / "SQ02325072026JFK.pdf"
    if not path.is_file():
        pytest.skip("genuine SQ23 OFP is not available")
    _flight, surfaces = _genuine(str(path))
    second = _route_markers(surfaces["contract"])[1]
    assert second["properties"]["name"] == "KZBW"
    assert second["properties"]["role"] == "fir"
    assert not ({"departure", "destination", "notam_airport"} & set(second["properties"]["roles"]))


def test_genuine_edto_schematic_route_line_ends_at_the_destination_not_at_an_etp() -> None:
    """Genuine SQ214 PER-SIN: the schematic fallback drew WSSS and then carried the route line on to the EDTO ETP
    south of Java (S15 20 E112 40) - a route that ends nowhere near Singapore."""
    path = CORPUS / "lido-briefing_SQ_214_16Aug2026_PER_SIN.pdf"
    if not path.is_file():
        pytest.skip("genuine SQ214 OFP is not available")
    flight, surfaces = _genuine(str(path))
    contract = surfaces["contract"]
    assert any(feature["properties"]["role"] == "edto_etp" for feature in contract.markers_geojson["features"])
    assert _schematic_vertex_failures(contract, _printed_route(str(path), flight["destination"])) == []


# ---------------------------------------------------------------------------------------------------------------
# Labelled synthetic cases. Each starts from a genuine OFP and damages only the parsed route the way a lost or
# unreadable navlog page would; nothing here claims a production OFP looked like this.
# ---------------------------------------------------------------------------------------------------------------

def _sq297() -> dict:
    path = CORPUS / "lido-briefing_SQ_297_16Aug2026_SIN_CHC.pdf"
    if not path.is_file():
        pytest.skip("genuine SQ297 OFP is not available")
    return deepcopy(_parsed(str(path)))


def _bali_start(flight: dict) -> int:
    return next(index for index, row in enumerate(flight["route_waypoints"]) if row["name"] == "BLI")


def test_synthetic_sq297_rows_before_bali_lost_never_draws_singapore_at_bali() -> None:
    """SYNTHETIC: genuine SQ297 SIN-CHC with the 23 navlog rows before BLI removed. Release 494 drew "WSSS", in
    departure colour and as the route's start, at BLI - Singapore in Bali."""
    flight = _sq297()
    flight["route_waypoints"] = flight["route_waypoints"][_bali_start(flight):]
    surfaces = _surfaces(flight)
    contract, route_map = surfaces["contract"], surfaces["route_map"]
    failures = _airport_violations(flight, _contract_labels(contract) + _route_map_labels(route_map) + _static_labels(contract))
    assert not failures, "\n".join(failures)
    first = _route_markers(contract)[0]
    assert (first["geometry"]["coordinates"][1], first["geometry"]["coordinates"][0]) == pytest.approx(BALI_BLI, abs=1e-4)
    assert first["properties"]["name"] == "BLI"
    assert route_map["points"][0]["display_name"] == "BLI"
    # Said, not drawn: the departure aerodrome is reported as not placed, on the contract and on the report map.
    departure = contract.metadata["route_endpoints"]["departure"]
    assert departure["status"] == "not_placed"
    assert departure["icao"] == "WSSS"
    assert departure["marker_id"] is None
    assert contract.warnings[0] == SQ297_DEPARTURE_STATEMENT
    assert "WSSS" in route_map["note"] and "not drawn" in route_map["note"]
    # The destination is still the printed NZCH row and keeps its identity.
    destination = contract.metadata["route_endpoints"]["destination"]
    assert destination["status"] == "placed"
    assert _route_markers(contract)[-1]["properties"]["name"] == "NZCH"


def test_synthetic_sq297_leading_rows_without_coordinates_never_draws_singapore_at_bali() -> None:
    """SYNTHETIC: the same 23 rows held but with no coordinate line (an unreadable page). The map skips rows without
    coordinates, so in release 494 the first coordinate-bearing row - BLI - became "WSSS"."""
    flight = _sq297()
    for row in flight["route_waypoints"][:_bali_start(flight)]:
        row["latitude"] = row["longitude"] = None
    surfaces = _surfaces(flight)
    contract, route_map = surfaces["contract"], surfaces["route_map"]
    failures = _airport_violations(flight, _contract_labels(contract) + _route_map_labels(route_map))
    assert not failures, "\n".join(failures)
    assert contract.metadata["route_endpoints"]["departure"]["status"] == "not_placed"


def test_synthetic_sq214_truncated_log_does_not_name_its_last_held_row_singapore() -> None:
    """SYNTHETIC: genuine SQ214 PER-SIN with the navlog cut after its first 20 rows. Release 494 named the last held
    row "WSSS"; the destination aerodrome must instead be reported as not placed."""
    path = CORPUS / "lido-briefing_SQ_214_16Aug2026_PER_SIN.pdf"
    if not path.is_file():
        pytest.skip("genuine SQ214 OFP is not available")
    flight = deepcopy(_parsed(str(path)))
    flight["route_waypoints"] = flight["route_waypoints"][:20]
    surfaces = _surfaces(flight)
    contract, route_map = surfaces["contract"], surfaces["route_map"]
    failures = _airport_violations(flight, _contract_labels(contract) + _route_map_labels(route_map) + _static_labels(contract))
    assert not failures, "\n".join(failures)
    assert contract.metadata["route_endpoints"]["destination"]["status"] == "not_placed"
    assert route_map["points"][-1]["display_name"] == flight["route_waypoints"][-1]["name"].lstrip("-")


def test_controls_genuine_endpoints_keep_their_aerodrome_labels_and_route_hash() -> None:
    """CONTROL: on all 30 originals both aerodromes stay placed and labelled exactly as before, and the canonical
    route hash pinned in the corpus manifest is unchanged."""
    manifest = json.loads((ROOT / "tests" / "private_cfp_corpus_manifest.json").read_text(encoding="utf-8"))
    pinned = {case["filename"]: case["route_hash"] for case in manifest["cases"]}
    for path in _corpus_files():
        flight, surfaces = _genuine(str(path))
        contract, route_map = surfaces["contract"], surfaces["route_map"]
        markers = _route_markers(contract)
        assert markers[0]["properties"]["name"] == flight["departure"], path.name
        assert markers[0]["properties"]["role"] == "departure", path.name
        assert markers[-1]["properties"]["name"] == flight["destination"], path.name
        assert markers[-1]["properties"]["role"] == "destination", path.name
        assert route_map["points"][0]["display_name"] == flight["departure"], path.name
        assert route_map["points"][-1]["display_name"] == flight["destination"], path.name
        endpoints = contract.metadata["route_endpoints"]
        assert endpoints["departure"]["status"] == endpoints["destination"]["status"] == "placed", path.name
        assert endpoints["departure"]["marker_id"] == markers[0]["id"], path.name
        assert endpoints["destination"]["marker_id"] == markers[-1]["id"], path.name
        assert not any("not drawn" in warning for warning in contract.warnings), path.name
        assert "not drawn" not in route_map["note"], path.name
        if path.name in pinned:
            assert contract.route_hash == pinned[path.name], path.name


def test_app_states_an_unplaced_aerodrome_in_the_same_sentence() -> None:
    """Cross-runtime: the app's pinned statement for the synthetic SQ297 case is the one ODSS publishes."""
    import os

    app_root = os.environ.get("PILOTDRIVEN_APP_ROOT")
    if not app_root:
        pytest.skip("PILOTDRIVEN_APP_ROOT is not set")
    pinned = Path(app_root) / "tests" / "route-endpoint-status-20261013.test.mjs"
    if not pinned.is_file():
        pytest.skip("the app's route-endpoint statement test is not in this app checkout")
    assert f"'{SQ297_DEPARTURE_STATEMENT}'" in pinned.read_text(encoding="utf-8")


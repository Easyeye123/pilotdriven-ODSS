"""Route-map aerodromes: drawn only at their governed reference points; route rows keep their own names.

David, WhatsApp 3 Oct 2026: "Your routing has gone haywire ... It ended up instead of Singapore now is in Bali."
Codex QA496-03, 13 Oct 2026: with leading parsed rows removed, release 496 still drew JUDDS (67 NM out) as KJFK.

Root cause: every route map gave an aerodrome's identity to a route row - release 494 to whichever coordinate-bearing
row came first or last, release 496 to the first row when a route-length allowance (25 NM + 1% of GND) was met. A
distance bound is not airport identity. The rule now: an aerodrome is drawn only at a position from an identity-proven
source - (a) the governed LIDO table, keyed by ICAO code, or (b) the OpenStreetMap aerodrome the app published for this
analysis, matched on its exact ICAO tag - recorded per marker as provenance; no route row ever carries an aerodrome's
name or role; an aerodrome neither source holds is not drawn and every map says so.

Tolerances, stated once:
- route vertex: the OFP-printed coordinate of that row (print resolution 0.1 minute), checked to 0.1 NM;
- a drawn aerodrome: within 0.1 NM of the official CAAS/FAA reference point (WSSS, KJFK), within 0.05 NM of the
  aerodrome record its OFP prints when drawn from the LIDO table, within 0.01 NM of the published OpenStreetMap centre
  when drawn from OSM, and within 1.5 NM of every other independent source held for it (OFP record vs OSM measured at
  most 1.11 NM, EDDF, over the 18 corpus aerodromes with a published outline).
Truth is independent of the code under test: route rows and aerodrome records are re-read here from the PDF text;
official points come from the State AIPs as cited by Codex; OSM centres from what PD itself published. No recalled
value is used.
"""
from __future__ import annotations

from copy import deepcopy
from functools import lru_cache
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess

import fitz
import pytest

from app.odss.briefing import build_route_map, project_route_map, render_route_svg
from app.odss.engines import analyse
from app.odss.parser import extract_pages, parse_lido
from app.odss_map_v06.aws_location import _static_overlay
from app.odss_map_v06.config import MapSettings
from app.odss_map_v06.geojson import build_map_contract
from app.odss_map_v06.schematic import _render_svg

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT.parent / "private_cfp_corpus"
_TRUTH = json.loads((ROOT / "tests" / "fixtures" / "aerodrome_reference_points_20261013.json").read_text(encoding="utf-8"))
OFFICIAL = {code: tuple(value) for code, value in _TRUTH["points"].items()}
_OSM = json.loads((ROOT / "tests" / "fixtures" / "osm_aerodromes_published_20261014.json").read_text(encoding="utf-8"))
OSM_CENTRES = {code: tuple(entry["centre"]) for code, entry in _OSM["centres"].items()}
OSM_OUTLINES = _OSM["outlines"]
VERTEX_TOLERANCE_NM = 0.1
OFFICIAL_TOLERANCE_NM = 0.1
CROSS_SOURCE_TOLERANCE_NM = 1.5
AERODROME_TOLERANCE_NM = CROSS_SOURCE_TOLERANCE_NM
AIRPORT_ROLES = {"departure", "destination", "notam_airport"}
BALI_BLI = (-8.75, 115.16333)  # BLI as printed in the genuine SQ297 navlog: S08 45.0 E115 09.8


def _nm(first: tuple[float, float], second: tuple[float, float]) -> float:
    lat1, lon1, lat2, lon2 = map(math.radians, (*first, *second))
    value = math.sin(lat1) * math.sin(lat2) + math.cos(lat1) * math.cos(lat2) * math.cos(lon2 - lon1)
    return 3440.065 * math.acos(max(-1.0, min(1.0, value)))


def _corpus_files() -> list[Path]:
    files = sorted(CORPUS.glob("*.pdf")) if CORPUS.is_dir() else []
    if len(files) != 30:
        pytest.skip(f"the 30-OFP private corpus is not mounted at {CORPUS} ({len(files)} PDFs)")
    return files


def _corpus_file(name: str) -> Path:
    path = CORPUS / name
    if not path.is_file():
        pytest.skip(f"genuine {name} is not available")
    return path


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


@lru_cache(maxsize=1)
def _printed_records() -> dict[str, tuple[float, float]]:
    """Each corpus aerodrome as its own OFP prints it on the destination row, re-read here from the PDF text."""
    records: dict[str, tuple[float, float]] = {}
    for path in _corpus_files():
        name, lat, lon = _printed_route(str(path), _parsed(str(path))["destination"])[-1]
        records.setdefault(name, (lat, lon))
    return records


def _truths(code: str) -> list[tuple[str, tuple[float, float], float]]:
    """Independent positions held for an aerodrome, each with the tolerance a drawn marker must meet."""
    truths = []
    if code in OFFICIAL:
        truths.append(("official AIP reference point", OFFICIAL[code], OFFICIAL_TOLERANCE_NM))
    if CORPUS.is_dir() and code in _printed_records():
        truths.append(("OFP-printed aerodrome record", _printed_records()[code], CROSS_SOURCE_TOLERANCE_NM))
    if code in OSM_CENTRES:
        truths.append(("published OpenStreetMap aerodrome", OSM_CENTRES[code], CROSS_SOURCE_TOLERANCE_NM))
    return truths


def _osm_overlay(code: str, role: str, *, icao: str | None = None) -> dict:
    """A published surface overlay carrying PD's own OpenStreetMap outline for ``code`` (only the fields the map reads)."""
    outline = OSM_OUTLINES[code]
    return {
        "schemaVersion": "1.0",
        "icao": icao or code,
        "name": outline["name"],
        "role": role,
        "source": {
            "provider": "openstreetmap",
            "fetchedAt": outline["fetchedAt"],
            "sourceUpdatedAt": outline["sourceUpdatedAt"],
            "attribution": "© OpenStreetMap contributors",
            "licenceUrl": "https://www.openstreetmap.org/copyright",
            "referenceOnly": True,
        },
        "aerodromeBoundary": deepcopy(outline["aerodromeBoundary"]),
    }


def _surfaces(flight: dict, *, with_findings: bool = True) -> dict:
    findings = analyse(deepcopy(flight))[0] if with_findings else []
    contract = build_map_contract(deepcopy(flight), findings, MapSettings())
    route_map = build_route_map(deepcopy(flight))
    return {"contract": contract, "route_map": route_map}


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


def _own_name(row: dict) -> str:
    return str(row.get("fir_boundary") or row.get("name") or "").upper().lstrip("-")


def _drawn(flight: dict, surfaces: dict) -> list[dict]:
    """Every drawn point on every surface: (surface, name, airport roles, position, route row or not, own name)."""
    contract, route_map = surfaces["contract"], surfaces["route_map"]
    held = [row for row in flight["route_waypoints"] if row.get("latitude") is not None and row.get("longitude") is not None]
    rows = []
    route_markers = iter(held)
    for feature in contract.markers_geojson["features"]:
        properties = feature["properties"]
        lon, lat = feature["geometry"]["coordinates"]
        route_row = str(feature["id"]).startswith("wp-")
        rows.append({
            "surface": f"contract {feature['id']}", "name": str(properties.get("name")),
            "roles": {properties.get("role"), *(properties.get("roles") or [])} & AIRPORT_ROLES,
            "position": (lat, lon), "route_row": route_row,
            "own": _own_name(next(route_markers)) if route_row else None,
        })
    for index, point in enumerate(route_map.get("points") or []):
        rows.append({
            "surface": f"route_map[{index}]", "name": str(point.get("display_name")),
            "roles": {point.get("role")} & AIRPORT_ROLES, "position": (point["latitude"], point["longitude"]),
            "route_row": True, "own": _own_name(held[index]),
        })
    for aerodrome in route_map.get("aerodromes") or []:
        rows.append({
            "surface": f"route_map aerodrome {aerodrome['icao']}", "name": aerodrome["display_name"],
            "roles": set(aerodrome.get("roles") or [aerodrome["role"]]) & AIRPORT_ROLES,
            "position": (aerodrome["latitude"], aerodrome["longitude"]), "route_row": False, "own": None,
        })
    for feature in _static_overlay(contract)["features"]:
        if feature["geometry"]["type"] != "Point" or "label" not in feature["properties"]:
            continue
        lon, lat = feature["geometry"]["coordinates"]
        source = next(
            marker for marker in contract.markers_geojson["features"]
            if marker["geometry"]["coordinates"] == [lon, lat]
            and str(marker["properties"].get("name") or "")[:12] == feature["properties"]["label"]
        )
        rows.append({
            "surface": f"static overlay {feature['properties']['label']}", "name": feature["properties"]["label"],
            "roles": {source["properties"].get("role"), *(source["properties"].get("roles") or [])} & AIRPORT_ROLES,
            "position": (lat, lon), "route_row": str(source["id"]).startswith("wp-"), "own": None,
        })
    return rows


def _identity_failures(flight: dict, surfaces: dict) -> list[str]:
    """No route row is an aerodrome; every drawn aerodrome is at its AIP reference point; held aerodromes are drawn."""
    departure, destination = flight["departure"], flight["destination"]
    failures = []
    drawn = _drawn(flight, surfaces)
    for row in drawn:
        if row["route_row"] and row["roles"]:
            failures.append(f"{row['surface']}: route row {row['name']} carries aerodrome role(s) {sorted(row['roles'])}")
        if row["route_row"] and row["own"] is not None and row["name"] != row["own"]:
            failures.append(f"{row['surface']}: route row {row['own']} is drawn as {row['name']}")
        claims = {code for code in (departure, destination) if row["name"] == code}
        if "departure" in row["roles"]:
            claims.add(departure)
        if "destination" in row["roles"]:
            claims.add(destination)
        if "notam_airport" in row["roles"] and not claims:
            failures.append(f"{row['surface']}: {row['name']} is drawn as a NOTAM airport but is not this flight's aerodrome")
        for code in claims:
            truths = _truths(code)
            if not truths:
                failures.append(f"{row['surface']}: {row['name']} drawn as {code} with no independent position to check")
            for label, position, tolerance in truths:
                distance = _nm(position, row["position"])
                if distance > tolerance:
                    failures.append(f"{row['surface']}: {row['name']} drawn as {code} {distance:.2f} NM from its {label}")
    for code in {departure, destination}:
        if not any(row["name"] == code and not row["route_row"] and row["surface"].startswith("contract") for row in drawn):
            failures.append(f"contract: aerodrome {code} is not drawn at its reference point")
        if not any(row["name"] == code and row["surface"].startswith("route_map aerodrome") for row in drawn):
            failures.append(f"route_map: aerodrome {code} is not drawn at its reference point")
    return failures


_POLYLINE = re.compile(r'<polyline points="([^"]+)"')
_CIRCLE = re.compile(r'<circle cx="([-\d.]+)" cy="([-\d.]+)"')


def _schematic_failures(contract, printed: tuple[tuple[str, float, float], ...], aerodromes: list[str]) -> list[str]:
    """``aerodromes``: the codes the contract draws; each must have a schematic marker at the contract's position."""
    """The schematic draws the route line only through the printed route, in order, and each aerodrome at its point."""
    width, height = 1600, 900
    svg = _render_svg(contract, width=width, height=height)
    bounds = contract.bounds
    span_x, span_y = max(bounds.east - bounds.west, 0.1), max(bounds.north - bounds.south, 0.1)

    def project(lat: float, lon: float) -> tuple[float, float]:
        return (30 + (lon - bounds.west) / span_x * (width - 60), height - 30 - (lat - bounds.south) / span_y * (height - 60))

    failures = []
    lines = _POLYLINE.findall(svg)
    geometry = contract.route_geojson["features"][0]["geometry"]
    segments = 1 if geometry["type"] == "LineString" else len(geometry["coordinates"])
    if len(lines) != segments:
        failures.append(f"schematic: {len(lines)} route polylines for {segments} route segment(s)")
    drawn = [tuple(float(value) for value in pair.split(",")) for line in lines for pair in line.split()]
    expected = [project(lat, lon) for _name, lat, lon in printed]
    if len(drawn) != len(expected):
        failures.append(f"schematic: route line has {len(drawn)} vertices for {len(expected)} printed rows")
    else:
        failures += [
            f"schematic: vertex {index} drawn at {got} instead of printed {printed[index][0]} {want}"
            for index, (got, want) in enumerate(zip(drawn, expected))
            if abs(got[0] - want[0]) > 0.11 or abs(got[1] - want[1]) > 0.11
        ][:3]
    circles = [(float(x), float(y)) for x, y in _CIRCLE.findall(svg)]
    positions = {
        feature["properties"]["name"]: feature["geometry"]["coordinates"]
        for feature in contract.markers_geojson["features"] if str(feature["id"]).startswith("aerodrome-")
    }
    for code in aerodromes:
        if code not in positions:
            failures.append(f"schematic: contract draws no {code} aerodrome")
            continue
        lon, lat = positions[code]
        want = project(lat, lon)
        tolerance = 0.11
        if not any(abs(x - want[0]) <= tolerance and abs(y - want[1]) <= tolerance for x, y in circles):
            failures.append(f"schematic: no marker drawn at {code}")
    return failures


def _projected_failures(route_map: dict) -> list[str]:
    """PDF/SVG maps draw each aerodrome in the same frame as the route points, at its reference point."""
    projection = project_route_map(route_map, 1000.0, 600.0, 20.0)
    frame = projection.get("frame") or {}
    failures = []
    drawn = {item["icao"]: item for item in projection.get("aerodromes") or []}
    for aerodrome in route_map.get("aerodromes") or []:
        item = drawn.get(aerodrome["icao"])
        if item is None:
            failures.append(f"projection: aerodrome {aerodrome['icao']} is not projected")
            continue
        lat, lon = aerodrome["latitude"], aerodrome["longitude"]
        candidates = [
            (frame["offset_x"] + ((lon + shift) * frame["longitude_factor"] - frame["min_x"]) * frame["scale"],
             frame["offset_y"] + (lat - frame["min_y"]) * frame["scale"])
            for shift in (-360, 0, 360)
        ]
        tolerance = 0.01
        if not any(abs(item["x"] - x) <= tolerance and abs(item["y"] - y) <= tolerance for x, y in candidates):
            failures.append(f"projection: {aerodrome['icao']} drawn at ({item['x']:.1f}, {item['y']:.1f}), not at its reference point")
        if not (0 <= item["x"] <= 1000 and 0 <= item["y"] <= 600):
            failures.append(f"projection: {aerodrome['icao']} falls outside the map frame")
    svg = render_route_svg(route_map)
    for aerodrome in route_map.get("aerodromes") or []:
        if f">{aerodrome['icao']}<" not in svg:
            failures.append(f"route SVG: {aerodrome['icao']} is not labelled")
    return failures


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
    failures += _schematic_failures(contract, printed, sorted({flight["departure"], flight["destination"]}))
    failures += _projected_failures(route_map)
    failures += _identity_failures(flight, surfaces)
    return [f"{path.name}: {failure}" for failure in failures]


def test_independent_aerodrome_sources_agree_for_every_corpus_aerodrome() -> None:
    """Truth sources, checked against each other: the OFP-printed records of all 19 corpus aerodromes; the official
    CAAS/FAA points for WSSS and KJFK (within 0.1 NM); PD's published OpenStreetMap aerodrome for 18 of them (YPAD has
    none held) within 1.5 NM - measured at most 1.11 NM (EDDF)."""
    files = _corpus_files()
    records = _printed_records()
    codes = {code for path in files for code in (_parsed(str(path))["departure"], _parsed(str(path))["destination"])}
    assert set(records) == codes and len(codes) == 19
    for code, position in OFFICIAL.items():
        assert _nm(position, records[code]) <= OFFICIAL_TOLERANCE_NM, code
    offsets = {code: _nm(records[code], OSM_CENTRES[code]) for code in codes if code in OSM_CENTRES}
    assert set(codes) - set(offsets) == {"YPAD"}
    assert max(offsets.values()) <= CROSS_SOURCE_TOLERANCE_NM, offsets
    assert round(max(offsets.values()), 2) == 1.11 and max(offsets, key=offsets.get) == "EDDF"


def test_independent_navlog_reader_agrees_with_the_parser_on_all_30_originals() -> None:
    """The truth source is not the code under test, but it must describe the same printed rows."""
    for path in _corpus_files():
        flight = _parsed(str(path))
        printed = _printed_route(str(path), flight["destination"])
        parsed = [(row["name"], row["latitude"], row["longitude"]) for row in flight["route_waypoints"]]
        assert [row[0] for row in printed] == [row[0] for row in parsed], path.name
        assert all(abs(a[1] - b[1]) < 1e-9 and abs(a[2] - b[2]) < 1e-9 for a, b in zip(printed, parsed)), path.name


def test_every_drawn_aerodrome_and_route_vertex_is_where_it_belongs_on_all_30_originals() -> None:
    """Corpus-wide invariant over the map contract (dashboard map, print snapshot, static fallback), the labelled
    schematic fallback, and the route map drawn in the PDF/SVG reports."""
    failures = [failure for path in _corpus_files() for failure in _invariant_failures(path)]
    assert not failures, f"{len(failures)} placement failures:\n" + "\n".join(failures[:60])


def _drops(count: int) -> list[int]:
    return sorted({drop for drop in (1, 2, 3, 5, 6, 10, count // 4, count // 2, count - 3) if 1 <= drop <= count - 2})


def test_synthetic_leading_and_trailing_row_loss_never_moves_an_aerodrome_on_any_original() -> None:
    """SYNTHETIC: every original, with 1..n-3 leading or trailing parsed rows removed (the PDFs are not changed).
    Whatever rows survive, each aerodrome stays at its reference point and every surviving row keeps its own name."""
    failures = []
    variants = 0
    for path in _corpus_files():
        flight = _parsed(str(path))
        count = len(flight["route_waypoints"])
        for drop in _drops(count):
            for side, rows in (("leading", flight["route_waypoints"][drop:]), ("trailing", flight["route_waypoints"][:-drop])):
                damaged = deepcopy(flight)
                damaged["route_waypoints"] = deepcopy(rows)
                surfaces = _surfaces(damaged, with_findings=False)
                variants += 1
                failures += [f"{path.name} {side} -{drop}: {failure}" for failure in _identity_failures(damaged, surfaces)]
                if surfaces["contract"].warnings and any("not drawn" in warning for warning in surfaces["contract"].warnings):
                    failures.append(f"{path.name} {side} -{drop}: a held aerodrome is reported as not drawn")
    assert variants > 400
    assert not failures, f"{len(failures)} failures in {variants} variants:\n" + "\n".join(failures[:40])


@pytest.mark.parametrize(
    ("file", "drop", "first_fix", "aerodrome"),
    [
        ("SQ02325072026JFK.pdf", 1, "KZBW", "KJFK"),
        ("SQ02325072026JFK.pdf", 3, "JUDDS", "KJFK"),
        ("lido-briefing_SQ_24_15Aug2026_SIN_JFK.pdf", 5, "MUMDU", "WSSS"),
        ("lido-briefing_SQ_297_16Aug2026_SIN_CHC.pdf", 8, "VASTI", "WSSS"),
        ("lido-briefing_SQ_34_15Aug2026_SIN_SFO.pdf", 9, "VEBMA", "WSSS"),
    ],
)
def test_codex_qa496_03_cases_keep_the_first_fix_under_its_own_name(file, drop, first_fix, aerodrome) -> None:
    """SYNTHETIC (Codex QA496-03): release 496 drew these first fixes as the departure aerodrome, 32-67 NM out."""
    flight = deepcopy(_parsed(str(_corpus_file(file))))
    flight["route_waypoints"] = flight["route_waypoints"][drop:]
    surfaces = _surfaces(flight)
    contract, route_map = surfaces["contract"], surfaces["route_map"]
    first = _route_markers(contract)[0]
    assert first["properties"]["name"] == first_fix
    assert not ({"departure", "destination", "notam_airport"} & {first["properties"]["role"], *first["properties"]["roles"]})
    assert route_map["points"][0]["display_name"] == first_fix
    departure = next(feature for feature in contract.markers_geojson["features"] if feature["properties"]["role"] == "departure")
    lon, lat = departure["geometry"]["coordinates"]
    assert departure["properties"]["name"] == aerodrome
    assert _nm(OFFICIAL[aerodrome], (lat, lon)) <= OFFICIAL_TOLERANCE_NM, "official CAAS/FAA reference point"
    assert not _identity_failures(flight, surfaces)


def test_synthetic_sq297_rows_before_bali_lost_draws_singapore_at_singapore_and_bali_as_bli() -> None:
    """SYNTHETIC: genuine SQ297 SIN-CHC with the 23 navlog rows before BLI removed. Release 494 drew "WSSS" at BLI;
    release 496 refused to draw WSSS at all. WSSS is now drawn at its reference point and BLI under its own name."""
    flight = deepcopy(_parsed(str(_corpus_file("lido-briefing_SQ_297_16Aug2026_SIN_CHC.pdf"))))
    start = next(index for index, row in enumerate(flight["route_waypoints"]) if row["name"] == "BLI")
    flight["route_waypoints"] = flight["route_waypoints"][start:]
    surfaces = _surfaces(flight)
    contract, route_map = surfaces["contract"], surfaces["route_map"]
    assert not _identity_failures(flight, surfaces)
    first = _route_markers(contract)[0]
    assert (first["geometry"]["coordinates"][1], first["geometry"]["coordinates"][0]) == pytest.approx(BALI_BLI, abs=1e-4)
    assert first["properties"]["name"] == "BLI"
    assert route_map["points"][0]["display_name"] == "BLI"
    assert contract.metadata["route_endpoints"]["departure"]["status"] == "reference_point"
    assert contract.metadata["route_endpoints"]["departure"]["marker_id"] == "aerodrome-departure"
    assert not any("not drawn" in warning for warning in contract.warnings)


def test_genuine_sq023_second_kzbw_boundary_is_not_drawn_as_the_departure_airport() -> None:
    """Genuine SQ23 JFK-SIN: two rows share the name -KZBW; neither is an aerodrome (release 494 drew the second,
    52 NM from JFK, as the departure and a NOTAM airport; release 496 still named the first one KJFK)."""
    _flight, surfaces = _genuine(str(_corpus_file("SQ02325072026JFK.pdf")))
    first, second = _route_markers(surfaces["contract"])[:2]
    for marker in (first, second):
        assert marker["properties"]["name"] == "KZBW"
        assert marker["properties"]["role"] == "fir"
        assert not ({"departure", "destination", "notam_airport"} & set(marker["properties"]["roles"]))


def test_genuine_edto_schematic_route_line_ends_at_the_destination_not_at_an_etp() -> None:
    """Genuine SQ214 PER-SIN: the schematic fallback in release 494 carried the route line on from WSSS to the EDTO
    ETP south of Java."""
    path = _corpus_file("lido-briefing_SQ_214_16Aug2026_PER_SIN.pdf")
    flight, surfaces = _genuine(str(path))
    contract = surfaces["contract"]
    assert any(feature["properties"]["role"] == "edto_etp" for feature in contract.markers_geojson["features"])
    assert _schematic_failures(contract, _printed_route(str(path), flight["destination"]), ["WSSS", "YPPH"]) == []


def _without(code: str):
    from app.odss import route_anchors

    table = {key: value for key, value in route_anchors.aerodrome_reference_points().items() if key != code}
    return table


def test_an_aerodrome_absent_from_both_sources_is_not_drawn_and_said(monkeypatch) -> None:
    """An aerodrome neither the governed table nor a published OpenStreetMap aerodrome holds is never borrowed from a
    route row: it is not drawn, and the contract, its metadata and the report route-map note say why. (Simulated by
    removing VHHH from the table; no surface overlay is published.)"""
    from app.odss import route_anchors

    reduced = _without("VHHH")
    monkeypatch.setattr(route_anchors, "aerodrome_reference_points", lambda: reduced)
    flight = deepcopy(_parsed(str(_corpus_file("lido-briefing_SQ_882_09Sep2026_SIN_HKG.pdf"))))
    surfaces = _surfaces(flight)
    contract, route_map = surfaces["contract"], surfaces["route_map"]
    statement = (
        "Destination aerodrome VHHH not drawn: no governed aerodrome reference point is held for VHHH, and no "
        "OpenStreetMap aerodrome matched on its ICAO tag was published for this analysis. The route is drawn to VHHH."
    )
    assert contract.metadata["route_endpoints"]["destination"]["status"] == "not_placed"
    assert contract.metadata["route_endpoints"]["destination"]["marker_id"] is None
    assert statement in contract.warnings
    assert statement in route_map["note"]
    assert [item["icao"] for item in route_map["aerodromes"]] == ["WSSS"]
    assert not any(
        feature["properties"]["role"] == "destination" or "destination" in feature["properties"]["roles"]
        for feature in contract.markers_geojson["features"]
    )
    # The printed VHHH navlog row is still drawn - as the route's last row under its own printed name, not as the
    # aerodrome.
    last = _route_markers(contract)[-1]
    assert last["properties"]["name"] == "VHHH" and last["properties"]["role"] == "route"
    app_root = os.environ.get("PILOTDRIVEN_APP_ROOT")
    node = shutil.which("node")
    helper = Path(app_root or "") / "web" / "src" / "lib" / "route-endpoint-status.ts"
    if app_root and node and helper.is_file():
        script = (
            f"import {{ routeEndpointStatements }} from {json.dumps(str(helper))};"
            f"console.log(JSON.stringify(routeEndpointStatements({json.dumps(contract.metadata)})));"
        )
        completed = subprocess.run([node, "--input-type=module", "-e", script], capture_output=True, text=True, check=True)
        assert json.loads(completed.stdout) == [statement], "the dashboard states it in the same words"


def test_controls_genuine_route_hash_unchanged_and_both_aerodromes_drawn() -> None:
    """CONTROL: on all 30 originals the canonical route hash pinned in the corpus manifest is unchanged, every route
    row is drawn under its own printed name, and both aerodromes are drawn at their reference points."""
    manifest = json.loads((ROOT / "tests" / "private_cfp_corpus_manifest.json").read_text(encoding="utf-8"))
    pinned = {case["filename"]: case["route_hash"] for case in manifest["cases"]}
    for path in _corpus_files():
        flight, surfaces = _genuine(str(path))
        contract, route_map = surfaces["contract"], surfaces["route_map"]
        endpoints = contract.metadata["route_endpoints"]
        assert endpoints["departure"]["status"] == endpoints["destination"]["status"] == "reference_point", path.name
        for role in ("departure", "destination"):
            assert endpoints[role]["reference"]["kind"] == "lido_ofp_destination_aerodrome_record", path.name
            marker = next(f for f in contract.markers_geojson["features"] if f["id"] == f"aerodrome-{role}")
            lon, lat = marker["geometry"]["coordinates"]
            assert _nm(_printed_records()[flight[role]], (lat, lon)) <= 0.05, (path.name, role)
            assert marker["properties"]["aerodrome_reference"]["kind"] == "lido_ofp_destination_aerodrome_record"
        assert endpoints["departure"]["marker_id"] == "aerodrome-departure", path.name
        assert endpoints["destination"]["marker_id"] == "aerodrome-destination", path.name
        assert not any("not drawn" in warning for warning in contract.warnings), path.name
        assert "not drawn" not in route_map["note"], path.name
        assert [marker["properties"]["name"] for marker in _route_markers(contract)] == [
            _own_name(row) for row in flight["route_waypoints"]
        ], path.name
        if path.name in pinned:
            assert contract.route_hash == pinned[path.name], path.name



# ---------------------------------------------------------------------------------------------------------------
# Second identity-proven source: the OpenStreetMap aerodrome the app published for this analysis, matched on its exact
# ICAO tag (app osm-airport-surface.mjs chooseAerodrome; ODSS stores it as flight["surface_overlays"]).
# ---------------------------------------------------------------------------------------------------------------

def _kul_flight(**overrides) -> dict:
    """SYNTHETIC SIN-KUL flight: WMKK is not in the governed LIDO table. The route rows are fixes near each end."""
    flight = {
        "flight_number": "SQ106",
        "departure": "WSSS",
        "destination": "WMKK",
        "ground_distance_nm": 170,
        "route_waypoints": [
            {"name": "IBIXU", "latitude": 1.27333, "longitude": 103.96167, "actm_minutes": 2},
            {"name": "VMR", "latitude": 2.38, "longitude": 102.5, "actm_minutes": 20},
            {"name": "KIBOL", "latitude": 2.6, "longitude": 101.9, "actm_minutes": 30},
        ],
    }
    flight.update(overrides)
    return flight


def _aerodrome_marker(contract, role: str) -> dict | None:
    return next((f for f in contract.markers_geojson["features"] if f["id"] == f"aerodrome-{role}"), None)


def test_an_aerodrome_outside_the_lido_table_is_drawn_at_its_published_osm_aerodrome_on_every_surface() -> None:
    """WMKK is not in the governed table. With the app's published OpenStreetMap WMKK aerodrome (relation 11579113,
    matched on icao=WMKK), every surface draws WMKK at that aerodrome's centre and records where it came from."""
    flight = _kul_flight(surface_overlays=[_osm_overlay("WMKK", "destination")])
    surfaces = _surfaces(flight, with_findings=False)
    contract, route_map = surfaces["contract"], surfaces["route_map"]
    marker = _aerodrome_marker(contract, "destination")
    assert marker is not None and marker["properties"]["name"] == "WMKK"
    lon, lat = marker["geometry"]["coordinates"]
    assert _nm(OSM_CENTRES["WMKK"], (lat, lon)) <= 0.01
    osm = _OSM["centres"]["WMKK"]["osm"]
    assert _nm((osm["latitude"], osm["longitude"]), (lat, lon)) <= 0.01, "the app's own OSM aerodrome centre"
    reference = marker["properties"]["aerodrome_reference"]
    assert reference["kind"] == "osm_aerodrome_published_outline"
    assert reference["icao"] == "WMKK"
    assert reference["fetchedAt"] == OSM_OUTLINES["WMKK"]["fetchedAt"]
    assert reference["attribution"] == "© OpenStreetMap contributors"
    endpoint = contract.metadata["route_endpoints"]["destination"]
    assert endpoint["status"] == "reference_point" and endpoint["marker_id"] == "aerodrome-destination"
    assert endpoint["reference"]["kind"] == "osm_aerodrome_published_outline"
    assert not any("not drawn" in warning for warning in contract.warnings)
    aerodromes = {item["icao"]: item for item in route_map["aerodromes"]}
    assert _nm(OSM_CENTRES["WMKK"], (aerodromes["WMKK"]["latitude"], aerodromes["WMKK"]["longitude"])) <= 0.01
    assert aerodromes["WMKK"]["reference"]["kind"] == "osm_aerodrome_published_outline"
    assert "not drawn" not in route_map["note"]
    assert _schematic_failures(contract, tuple((r["name"], r["latitude"], r["longitude"]) for r in flight["route_waypoints"]), ["WSSS", "WMKK"]) == []
    assert _projected_failures(route_map) == []
    assert not _identity_failures(flight, surfaces)
    assert any(f["properties"].get("label") == "WMKK" for f in _static_overlay(contract)["features"] if f["geometry"]["type"] == "Point")


def test_genuine_sq882_draws_vhhh_from_the_published_osm_aerodrome_when_the_table_lacks_it(monkeypatch) -> None:
    """Genuine SQ882 SIN-HKG with VHHH removed from the governed table and the app's published OSM VHHH aerodrome held:
    VHHH is drawn at the OSM centre (0.32 NM from the printed LIDO record), never at the printed VHHH route row."""
    from app.odss import route_anchors

    reduced = _without("VHHH")
    monkeypatch.setattr(route_anchors, "aerodrome_reference_points", lambda: reduced)
    flight = deepcopy(_parsed(str(_corpus_file("lido-briefing_SQ_882_09Sep2026_SIN_HKG.pdf"))))
    flight["surface_overlays"] = [_osm_overlay("VHHH", "destination")]
    surfaces = _surfaces(flight)
    contract = surfaces["contract"]
    marker = _aerodrome_marker(contract, "destination")
    lon, lat = marker["geometry"]["coordinates"]
    assert _nm(OSM_CENTRES["VHHH"], (lat, lon)) <= 0.01
    assert marker["properties"]["aerodrome_reference"]["kind"] == "osm_aerodrome_published_outline"
    assert 0.2 < _nm(_printed_records()["VHHH"], (lat, lon)) < 0.5
    last = _route_markers(contract)[-1]
    assert last["properties"]["name"] == "VHHH" and last["properties"]["role"] == "route"
    assert not _identity_failures(flight, surfaces)


def test_the_governed_lido_table_takes_precedence_over_a_published_osm_aerodrome() -> None:
    flight = deepcopy(_parsed(str(_corpus_file("lido-briefing_SQ_882_09Sep2026_SIN_HKG.pdf"))))
    flight["surface_overlays"] = [_osm_overlay("VHHH", "destination")]
    contract = _surfaces(flight, with_findings=False)["contract"]
    marker = _aerodrome_marker(contract, "destination")
    assert marker["properties"]["aerodrome_reference"]["kind"] == "lido_ofp_destination_aerodrome_record"
    lon, lat = marker["geometry"]["coordinates"]
    assert _nm(_printed_records()["VHHH"], (lat, lon)) <= 0.05


def test_an_osm_aerodrome_published_under_another_code_never_places_an_aerodrome() -> None:
    """Identity is the exact ICAO tag, never distance: an outline published for WMKP (Penang) does not stand for WMKK,
    and an overlay with no outline places nothing."""
    for overlays in (
        [_osm_overlay("WMKK", "destination", icao="WMKP")],
        [{**_osm_overlay("WMKK", "destination"), "aerodromeBoundary": None}],
        [],
    ):
        contract = _surfaces(_kul_flight(surface_overlays=overlays), with_findings=False)["contract"]
        assert _aerodrome_marker(contract, "destination") is None
        assert contract.metadata["route_endpoints"]["destination"]["status"] == "not_placed"
        assert any(warning.startswith("Destination aerodrome WMKK not drawn:") for warning in contract.warnings)
        assert _aerodrome_marker(contract, "departure") is not None, "WSSS still comes from the governed table"


from tests.test_service_api_v06 import (  # noqa: E402
    _authorization,
    _build_lido_pdf,
    _surface_contract,
    service_app,  # noqa: F401  (pytest fixture)
)


def test_publishing_the_osm_surface_overlay_draws_an_aerodrome_the_table_lacks(service_app, monkeypatch) -> None:
    """Service path: the analysis is created before the app's surface lookup finishes, so an aerodrome outside the
    governed table starts as not drawn. When the app publishes its exact-ICAO OpenStreetMap overlay, ODSS rebuilds the
    stored map contract and report route map from it; the route itself (route hash) is unchanged."""
    from app.odss import route_anchors

    reduced = _without("EBBR")
    monkeypatch.setattr(route_anchors, "aerodrome_reference_points", lambda: reduced)
    headers = _authorization()
    created = service_app.post(
        "/v1/analyses", headers=headers, files={"file": ("SQ304.pdf", _build_lido_pdf(), "application/pdf")},
    )
    assert created.status_code == 201
    analysis_id = created.json()["analysis_id"]
    flight = created.json()["flight"]
    assert flight["destination"] == "EBBR"
    before = service_app.get(f"/v1/analyses/{analysis_id}/map-contract", headers=headers).json()
    assert before["metadata"]["route_endpoints"]["destination"]["status"] == "not_placed"

    destination = _surface_contract("EBBR", "destination")
    destination["aerodromeBoundary"] = {"outer": [[[4.46, 50.89], [4.51, 50.89], [4.51, 50.915], [4.46, 50.915], [4.46, 50.89]]], "inner": []}
    published = service_app.post(
        f"/v1/analyses/{analysis_id}/surface-overlays",
        headers=headers,
        json={"overlays": [_surface_contract("WSSS", "departure"), destination]},
    )
    assert published.status_code == 200, published.text
    after = service_app.get(f"/v1/analyses/{analysis_id}/map-contract", headers=headers).json()
    assert after["route_hash"] == before["route_hash"]
    endpoint = after["metadata"]["route_endpoints"]["destination"]
    assert endpoint["status"] == "reference_point"
    assert endpoint["reference"]["kind"] == "osm_aerodrome_published_outline"
    marker = next(f for f in after["markers_geojson"]["features"] if f["id"] == "aerodrome-destination")
    assert marker["geometry"]["coordinates"] == pytest.approx([4.485, 50.9025], abs=1e-9)
    assert not any("EBBR not drawn" in warning for warning in after["warnings"])

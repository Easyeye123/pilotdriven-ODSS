"""Route-map aerodromes: drawn only at their governed reference points; route rows keep their own names.

David, WhatsApp 3 Oct 2026: "Your routing has gone haywire ... It ended up instead of Singapore now is in Bali."
Codex QA496-03, 13 Oct 2026: with leading parsed rows removed, release 496 still drew JUDDS (67 NM out) as KJFK.

Root cause: every route map gave an aerodrome's identity to a route row - release 494 to whichever coordinate-bearing
row came first or last, release 496 to the first row when a route-length allowance (25 NM + 1% of GND) was met. A
distance bound is not airport identity. The rule now: an aerodrome is drawn only at the reference point the governed
table holds for its ICAO code; no route row ever carries an aerodrome's name or role; an aerodrome the table does not
hold is not drawn and every map says so.

Tolerances, stated once:
- route vertex: the OFP-printed coordinate of that row (print resolution 0.1 minute), checked to 0.1 NM;
- any drawn aerodrome (departure, destination, or any feature named with or given the role of either): within 1 NM of
  the AIP aerodrome reference point (official CAAS/FAA values for WSSS and KJFK).
Truth is independent of the code under test: route rows are re-read here from the PDF text, aerodromes come from an
AIP table, not from the product's table.
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
ARP = {code: tuple(value) for code, value in _TRUTH["points"].items()}
VERTEX_TOLERANCE_NM = 0.1
AERODROME_TOLERANCE_NM = 1.0
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
            distance = _nm(ARP[code], row["position"])
            if distance > AERODROME_TOLERANCE_NM:
                failures.append(f"{row['surface']}: {row['name']} drawn as {code} {distance:.1f} NM from {code}")
    for code in {departure, destination}:
        if not any(row["name"] == code and not row["route_row"] and row["surface"].startswith("contract") for row in drawn):
            failures.append(f"contract: aerodrome {code} is not drawn at its reference point")
        if not any(row["name"] == code and row["surface"].startswith("route_map aerodrome") for row in drawn):
            failures.append(f"route_map: aerodrome {code} is not drawn at its reference point")
    return failures


_POLYLINE = re.compile(r'<polyline points="([^"]+)"')
_CIRCLE = re.compile(r'<circle cx="([-\d.]+)" cy="([-\d.]+)"')


def _schematic_failures(contract, printed: tuple[tuple[str, float, float], ...], aerodromes: list[str]) -> list[str]:
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
    for code in aerodromes:
        lat, lon = ARP[code]
        want = project(lat, lon)
        tolerance = AERODROME_TOLERANCE_NM / 60 / min(span_x, span_y) * (width - 60) + 0.11
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
        lat, lon = ARP[aerodrome["icao"]]
        candidates = [
            (frame["offset_x"] + ((lon + shift) * frame["longitude_factor"] - frame["min_x"]) * frame["scale"],
             frame["offset_y"] + (lat - frame["min_y"]) * frame["scale"])
            for shift in (-360, 0, 360)
        ]
        tolerance = AERODROME_TOLERANCE_NM / 60 * frame["scale"] + 0.01
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


def test_aerodrome_truth_table_agrees_with_every_printed_destination_row() -> None:
    files = _corpus_files()
    checked = set()
    for path in files:
        flight = _parsed(str(path))
        name, lat, lon = _printed_route(str(path), flight["destination"])[-1]
        assert name == flight["destination"], path.name
        assert _nm(ARP[name], (lat, lon)) < AERODROME_TOLERANCE_NM, (path.name, name)
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
    assert _nm(ARP[aerodrome], (lat, lon)) <= 0.1, "official CAAS/FAA reference point"
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


def test_an_aerodrome_without_a_governed_reference_point_is_not_drawn_and_said(monkeypatch) -> None:
    """An aerodrome the governed table does not hold is never borrowed from a route row: it is not drawn, and the
    contract, its metadata and the report route-map note say why. (Simulated by removing VHHH from the table.)"""
    from app.odss import route_anchors

    reduced = _without("VHHH")
    monkeypatch.setattr(route_anchors, "aerodrome_reference_points", lambda: reduced)
    flight = deepcopy(_parsed(str(_corpus_file("lido-briefing_SQ_882_09Sep2026_SIN_HKG.pdf"))))
    surfaces = _surfaces(flight)
    contract, route_map = surfaces["contract"], surfaces["route_map"]
    statement = (
        "Destination aerodrome VHHH not drawn: no governed aerodrome reference point is held for VHHH. "
        "The route is drawn to VHHH."
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
        assert endpoints["departure"]["marker_id"] == "aerodrome-departure", path.name
        assert endpoints["destination"]["marker_id"] == "aerodrome-destination", path.name
        assert not any("not drawn" in warning for warning in contract.warnings), path.name
        assert "not drawn" not in route_map["note"], path.name
        assert [marker["properties"]["name"] for marker in _route_markers(contract)] == [
            _own_name(row) for row in flight["route_waypoints"]
        ], path.name
        if path.name in pinned:
            assert contract.route_hash == pinned[path.name], path.name

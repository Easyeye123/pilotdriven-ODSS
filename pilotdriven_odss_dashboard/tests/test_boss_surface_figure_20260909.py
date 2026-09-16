"""The airport surface figures David rejected on 9 Sep 2026.

21:23:28 [photo: "WSSS DEPARTURE SURFACE" - an empty black panel with one
centred line "Airport surface geometry is not held in this analysis."]
    "This doesn't work?"
21:23:42 [photo: "VHHH DESTINATION SURFACE" - three bare diagonal runway
lines, no taxiways, no apron, no scale]
    "This is also rubbish generated"
21:22:28
    "Even the alignment is centred .. it is not what's asked"

Verified still live on production on 15 Sep 2026 (STATUS-CHECK item F): the
aerodrome outline the app computes for the eligibility test is discarded, the
apron polygons never reach the renderer, there is no scale bar or north arrow,
the fallback sentence is drawn dead centre, and the 4,200-byte Amazon Location
overlay cap has no test.

The geometry here is the real OpenStreetMap extract for VHHH the app captured
on 9 Sep 2026 - the destination of the SIN-HKG flight in his video - so the
figure asserted below is the one he would see for that flight once the app
carries the boundary and the aprons into the contract.
"""
from __future__ import annotations

import asyncio
import json
import math
from pathlib import Path
import re
from urllib.parse import parse_qs, urlsplit

import fitz
import pytest
from pydantic import ValidationError
from reportlab.pdfgen.canvas import Canvas

from app.odss.operational_format import (
    draw_airport_figure,
    surface_figure_gap,
)
from app.odss.surface_overlays import (
    STATIC_MAP_OVERLAY_LIMIT,
    SurfaceOverlayContract,
    SurfaceOverlayRenderError,
    _styled_surface_overlay,
    fit_static_map_overlay,
    render_surface_static_map,
)
from app.odss_map_v06.config import MapSettings


FIXTURE = Path(__file__).resolve().parent / "fixtures" / "vhhh-surface-report-20260909.json"
CORPUS = Path(__file__).resolve().parents[2] / "private_cfp_corpus"
HIS_SIN_HKG_OFP = "lido-briefing_SQ_882_09Sep2026_SIN_HKG.pdf"

PAGE = (600.0, 420.0)
FIGURE = (12.0, 12.0, 576.0, 396.0)  # x, y, width, height on that page

METRES_PER_DEGREE = 111_320.0


def vhhh_extract() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def vhhh_contract(*, role: str = "destination", with_boundary: bool = True,
                  mapped: list | None = None) -> dict:
    """The exact payload the app must publish for his VHHH destination."""
    extract = vhhh_extract()
    features = extract["featureCollection"]["features"]
    payload = {
        "schemaVersion": "1.0",
        "icao": "VHHH",
        "name": extract["name"],
        "role": role,
        "window": {
            "startsAt": "2026-09-09T16:00:00+00:00",
            "endsAt": "2026-09-09T20:30:00+00:00",
            "basis": "filed-std-sta",
        },
        "source": {
            "provider": "openstreetmap",
            "fetchedAt": "2026-09-09T18:50:40+00:00",
            "sourceUpdatedAt": "2026-05-26T15:18:52+00:00",
            "attribution": "(c) OpenStreetMap contributors",
            "licenceUrl": "https://www.openstreetmap.org/copyright",
            "referenceOnly": True,
        },
        "bounds": extract["bounds"],
        "featureCollection": {"type": "FeatureCollection", "features": features},
        "mapped": mapped or [],
        "reviewRequired": [],
        "counts": {
            "mapped": len(mapped or []),
            "reviewRequired": 0,
            "runways": sum(f["properties"]["aeroway"] == "runway" for f in features),
        },
    }
    if with_boundary:
        payload["aerodromeBoundary"] = extract["aerodromeBoundary"]
    # Validate through the strict contract so the test uses exactly what the
    # service would accept, then hand the renderer the JSON-mode dump the
    # service stores.
    return SurfaceOverlayContract.model_validate(payload).model_dump(mode="json")


def render_figure(tmp_path, overlay, *, planned_runway=None) -> fitz.Page:
    path = tmp_path / "figure.pdf"
    canvas = Canvas(str(path), pagesize=PAGE)
    draw_airport_figure(canvas, overlay, *FIGURE, planned_runway=planned_runway)
    canvas.save()
    document = fitz.open(path)
    return document[0]


def spans(page) -> list[dict]:
    return [span for block in page.get_text("dict")["blocks"]
            for line in block.get("lines", []) for span in line["spans"]]


def to_pdf_y(page, fitz_y: float) -> float:
    """PyMuPDF measures from the top; ReportLab draws from the bottom."""
    return page.rect.height - fitz_y


def geometry_area(page) -> fitz.Rect:
    """The part of the figure that holds drawn pavement (not the chrome)."""
    x, y, width, height = FIGURE
    return fitz.Rect(x, to_pdf_y(page, y + height - 17), x + width, to_pdf_y(page, y + 28))


def path_length(drawing) -> float:
    total = 0.0
    for item in drawing["items"]:
        if item[0] == "l":
            total += math.dist(item[1], item[2])
    return total


def geodesic_length(coordinates) -> float:
    total = 0.0
    for (lon_a, lat_a), (lon_b, lat_b) in zip(coordinates, coordinates[1:]):
        cos_lat = math.cos(math.radians((lat_a + lat_b) / 2))
        total += math.hypot((lon_b - lon_a) * cos_lat, lat_b - lat_a) * METRES_PER_DEGREE
    return total


# --------------------------------------------------------------- contract


def test_contract_accepts_the_exact_aerodrome_boundary_the_app_computes():
    """`exactAerodromeBoundary` (osm-airport-surface.mjs:424) returns
    `{outer: [ring...], inner: [ring...]}` and is then discarded. The contract
    now carries that shape, and an overlay without it stays valid so a browser
    on the previous bundle cannot break its publish."""
    contract = vhhh_contract()
    assert contract["aerodromeBoundary"]["outer"][0][0] == contract["aerodromeBoundary"]["outer"][0][-1]
    assert contract["aerodromeBoundary"]["inner"] == []
    legacy = vhhh_contract(with_boundary=False)
    assert legacy["aerodromeBoundary"] is None


@pytest.mark.parametrize("ring", [
    # not closed
    [[113.88, 22.29], [113.94, 22.29], [113.94, 22.34], [113.88, 22.34]],
    # closed but degenerate: three distinct points are a triangle, two are not a ring
    [[113.88, 22.29], [113.94, 22.29], [113.88, 22.29]],
    # invalid coordinate
    [[113.88, 22.29], [190.0, 22.29], [113.94, 22.34], [113.88, 22.29]],
])
def test_contract_rejects_an_open_or_degenerate_boundary_ring(ring):
    extract = vhhh_extract()
    payload = vhhh_contract()
    payload["aerodromeBoundary"] = {"outer": [ring], "inner": []}
    with pytest.raises(ValidationError):
        SurfaceOverlayContract.model_validate(payload)
    assert extract["aerodromeBoundary"]["outer"][0][0] == extract["aerodromeBoundary"]["outer"][0][-1]


# ----------------------------------------------------------------- figure


def test_figure_strokes_the_aerodrome_boundary_as_the_field_outline(tmp_path):
    """His VHHH photo: three bare lines floating in black. The field outline
    the app already computes must be drawn around them."""
    page = render_figure(tmp_path, vhhh_contract())
    dashed = [d for d in page.get_drawings()
              if d.get("dashes") and d["dashes"] not in ("[] 0", "[]")]
    assert dashed, "no dashed field outline was drawn"
    outline = max(dashed, key=lambda d: d["rect"].width * d["rect"].height)
    runway_strokes = [d for d in page.get_drawings() if abs((d.get("width") or 0) - 2.4) < 0.05]
    assert len(runway_strokes) >= 3, "runway strokes are missing"
    for stroke in runway_strokes:
        assert outline["rect"].contains(stroke["rect"]), "the outline does not enclose the runways"
    # The outline is the whole extract, not a rectangle of the bounds: the
    # synthetic ring has five distinct vertices, so five segments.
    assert sum(1 for item in outline["items"] if item[0] == "l") == 5
    # The figure was refitted to the outline: nothing is drawn outside it.
    area = geometry_area(page)
    assert area.contains(outline["rect"]), "the outline does not fit the figure area"


def test_figure_fills_apron_polygons_as_pavement_areas(tmp_path):
    """VHHH's six apron polygons are in the extract; they must read as areas,
    not be dropped or drawn as hairlines."""
    page = render_figure(tmp_path, vhhh_contract())
    area = geometry_area(page)
    # Runway label plates are opaque; pavement areas are translucent so the
    # taxiway lines stay readable through them.
    filled = [d for d in page.get_drawings()
              if d.get("fill") is not None and d["type"] in {"f", "fs"}
              and 0 < (d.get("fill_opacity") or 1.0) < 1.0
              and area.contains(d["rect"]) and max(d["rect"].width, d["rect"].height) > 4]
    assert len(filled) == 6, f"expected the six apron areas, found {len(filled)}"
    plates = [d for d in page.get_drawings()
              if d.get("fill") is not None and (d.get("fill_opacity") or 1.0) >= 1.0
              and area.contains(d["rect"]) and max(d["rect"].width, d["rect"].height) > 4]
    assert len(plates) == 3, "the three runway label plates must still be opaque"


def test_figure_carries_a_scale_bar_that_matches_the_runway_length(tmp_path):
    """No scale was his third objection. The bar's label and its drawn length
    must agree with the drawn runway, checked against the real OSM 07R/25L way."""
    page = render_figure(tmp_path, vhhh_contract())
    labels = [s for s in spans(page) if re.fullmatch(r"\d+(\.\d+)? (m|km)", s["text"].strip())]
    assert len(labels) == 1, [s["text"] for s in spans(page)]
    label = labels[0]
    assert label["size"] >= 8.9
    value, unit = label["text"].split()
    metres = float(value) * (1000 if unit == "km" else 1)
    label_middle = (label["bbox"][1] + label["bbox"][3]) / 2
    bars = [d for d in page.get_drawings()
            if d["type"] == "s" and d["rect"].height <= 8
            and abs((d["rect"].y0 + d["rect"].y1) / 2 - label_middle) <= 8
            and 0 <= label["bbox"][0] - d["rect"].x1 <= 14]
    assert len(bars) == 1, "no scale bar beside the scale label"
    bar_points = bars[0]["rect"].width
    assert bar_points >= 40, "scale bar too short to read"
    points_per_metre = bar_points / metres

    extract = vhhh_extract()
    runway = next(f for f in extract["featureCollection"]["features"] if f["id"] == "way/4956469")
    true_length = geodesic_length(runway["geometry"]["coordinates"])
    drawn = [d for d in page.get_drawings() if abs((d.get("width") or 0) - 2.4) < 0.05]
    drawn_length = max(path_length(d) for d in drawn)
    assert abs(drawn_length / points_per_metre - true_length) / true_length < 0.02, (
        f"scale bar says {drawn_length / points_per_metre:.0f} m for a {true_length:.0f} m runway")


def test_figure_carries_a_north_arrow(tmp_path):
    page = render_figure(tmp_path, vhhh_contract())
    x, y, width, height = FIGURE
    norths = [s for s in spans(page) if s["text"].strip() == "N"
              and s["bbox"][0] > x + width - 40 and s["bbox"][3] < to_pdf_y(page, y + height - 40)]
    assert len(norths) == 1, "no N marker in the top-right corner"
    north = norths[0]
    assert north["size"] >= 8.9
    heads = [d for d in page.get_drawings()
             if d.get("fill") is not None and d["type"] in {"f", "fs"}
             and abs(d["rect"].x0 - north["bbox"][0]) < 14
             and 0 <= d["rect"].y0 - north["bbox"][3] < 20]
    assert heads, "no arrowhead under the N"


@pytest.mark.parametrize(("overlay", "expected_reason"), [
    (None, "no OpenStreetMap surface overlay was published"),
    ({"icao": "WSSS", "role": "departure", "bounds": None,
      "featureCollection": {"type": "FeatureCollection", "features": []},
      "mapped": [], "reviewRequired": []},
     "held no report-eligible runway, taxiway or apron geometry"),
])
def test_fallback_is_left_aligned_and_names_the_missing_source(tmp_path, overlay, expected_reason):
    """His WSSS photo: one centred sentence in an empty panel. "Even the
    alignment is centred .. it is not what's asked."""
    headline, reason = surface_figure_gap(overlay)
    assert headline == "Airport surface geometry is not held in this analysis."
    assert expected_reason in reason
    page = render_figure(tmp_path, overlay)
    x, y, width, height = FIGURE
    drawn = [s for s in spans(page) if s["text"].strip()]
    assert [s["text"] for s in drawn][:1] == [headline]
    for span in drawn:
        assert span["size"] >= 8.9
        assert span["bbox"][0] <= x + 8, f"{span['text']!r} is not left-aligned"
        assert span["bbox"][0] < x + width / 2 - 100, f"{span['text']!r} reads as centred"
    assert any(expected_reason in s["text"] for s in drawn), [s["text"] for s in drawn]
    # The fallback sits at the top of the panel like a paragraph, not mid-air.
    assert to_pdf_y(page, drawn[0]["bbox"][1]) > y + height - 24


# ---------------------------------------------------- static-map overlay cap


def _line(feature_id: str, offset: float, *, aeroway: str = "taxiway", points: int = 16) -> dict:
    return {
        "type": "Feature",
        "id": feature_id,
        "properties": {"featureId": feature_id, "aeroway": aeroway, "ref": feature_id.upper()},
        "geometry": {
            "type": "LineString",
            "coordinates": [[103.98 + offset + index / 10_000, 1.35 + index / 10_000]
                            for index in range(points)],
        },
    }


def _contract(features: list[dict], mapped: list[dict] | None = None) -> dict:
    return {
        "featureCollection": {"type": "FeatureCollection", "features": features},
        "mapped": mapped or [],
    }


def test_static_map_overlay_cap_is_pinned_at_4200_bytes():
    assert STATIC_MAP_OVERLAY_LIMIT == 4_200


def test_overlay_at_the_cap_is_sent_unchanged_and_one_byte_over_is_simplified():
    contract = _contract([_line(f"tw-{index}", index / 100) for index in range(6)])
    baseline = json.dumps(_styled_surface_overlay(contract), separators=(",", ":"), ensure_ascii=True)
    at_cap, receipt = fit_static_map_overlay(contract, limit=len(baseline))
    assert at_cap == baseline
    assert receipt["bytes"] == len(baseline) and receipt["rung"] == "full"
    over, receipt = fit_static_map_overlay(contract, limit=len(baseline) - 1)
    assert len(over) <= len(baseline) - 1
    assert over != baseline
    assert receipt["rung"] != "full"
    # Deterministic: the same input always simplifies the same way.
    assert fit_static_map_overlay(contract, limit=len(baseline) - 1) == (over, receipt)


def test_simplification_never_drops_a_runway_a_mark_or_a_marker():
    marked = _line("tw-closed", 0.5)
    runway = _line("rwy", 0.7, aeroway="runway", points=12)
    context = [_line(f"tw-{index}", index / 100) for index in range(40)]
    contract = _contract([runway, *context, marked], mapped=[{
        "notamNumber": "A0001/26", "featureIds": ["tw-closed"], "markClass": "closure",
        "stateAtReference": "active_at_reference",
        "markers": [{"type": "Feature", "properties": {},
                     "geometry": {"type": "Point", "coordinates": [104.48, 1.35]}}],
    }])
    raw = json.dumps(_styled_surface_overlay(contract), separators=(",", ":"))
    assert len(raw) > STATIC_MAP_OVERLAY_LIMIT, "fixture must exceed the cap to prove anything"
    text, receipt = fit_static_map_overlay(contract)
    assert len(text) <= STATIC_MAP_OVERLAY_LIMIT
    overlay = json.loads(text)
    colours = [f["properties"].get("color") for f in overlay["features"]]
    assert "#EF4444" in colours, "the closure mark was dropped"
    assert any(f["geometry"]["type"] == "Point" and f["properties"].get("label") == "X"
               for f in overlay["features"]), "the closure marker was dropped"
    lines = [f for f in overlay["features"] if f["geometry"]["type"] == "LineString"]
    assert len(lines) >= 2, "the runway was dropped"
    assert receipt["kept"]["runways"] == 1 and receipt["kept"]["marked"] == 1


def test_overlay_that_cannot_fit_without_dropping_a_mark_fails_closed():
    """Runways and marks are never thinned away to fit a picture: the
    satellite render is refused and the validated schematic stands."""
    runways = [_line(f"rwy-{index}", index / 50, aeroway="runway") for index in range(40)]
    with pytest.raises(SurfaceOverlayRenderError):
        fit_static_map_overlay(_contract(runways))


def test_static_map_request_for_his_vhhh_extract_respects_the_cap(monkeypatch, tmp_path):
    requested: list[str] = []

    class FakeResponse:
        status_code = 200
        content = b"png-data"
        headers = {"content-type": "image/png"}

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def get(self, url: str):
            requested.append(url)
            return FakeResponse()

    monkeypatch.setattr("app.odss.surface_overlays.httpx.AsyncClient", lambda **kwargs: FakeClient())
    contract = vhhh_contract()
    raw = json.dumps(_styled_surface_overlay(contract), separators=(",", ":"))
    assert len(raw) > STATIC_MAP_OVERLAY_LIMIT, "his extract must exceed the cap for this to matter"
    result = asyncio.run(render_surface_static_map(
        contract, MapSettings(aws_location_server_api_key="server-static-key"), tmp_path / "vhhh"))
    assert result["mode"] == "static"
    assert len(requested) == 1
    overlay_text = parse_qs(urlsplit(requested[0]).query)["geojson-overlay"][0]
    assert len(overlay_text.encode("utf-8")) <= STATIC_MAP_OVERLAY_LIMIT
    assert len(json.loads(overlay_text)["features"]) >= 7, "the runways must survive"


# -------------------------------------------------- his SIN-HKG flight, page 4


def test_his_sin_hkg_destination_figure_shows_the_field_on_page_four(tmp_path):
    """The whole production download path for the flight in his video, with
    the VHHH contract the app must publish: the AIRPORTS / ALTERNATES page
    carries the field outline, the aprons, a scale bar and a north arrow, and
    the publication gate, the physical scan and the readable floor all accept it."""
    source = CORPUS / HIS_SIN_HKG_OFP
    if not source.is_file():
        pytest.skip(f"private CFP corpus file {HIS_SIN_HKG_OFP} is not available")
    from app.analysis import run_odss_analysis
    from app.odss.briefing import build_briefing_view
    from app.odss.combined_brief import render_combined_briefing
    from app.odss.concise_pdf_gate import AIRPORTS_PAGE, check_concise_pdf
    from scripts.run_private_cfp_corpus import scan_physical_pdf

    result = run_odss_analysis(source, tmp_path / "analysis", tmp_path / "reports", 1)
    payload = json.loads(Path(result["analysis_path"]).read_text(encoding="utf-8"))
    flight, findings = payload["flight"], payload["findings"]
    warnings = payload.get("view", {}).get("warnings") or []
    assert flight["destination"] == "VHHH"
    flight["surface_overlays"] = [vhhh_contract()]
    path = tmp_path / "SQ882_Flight_Briefing.pdf"
    render_combined_briefing(flight, findings, warnings, path,
                             weather_charts=payload.get("weather_charts") or {})
    view = build_briefing_view(flight, findings, warnings, timing_view=flight.get("timing_view"),
                               weather_charts=payload.get("weather_charts") or {})
    gate = check_concise_pdf(path, flight=flight, view=view,
                             airport_analysis=view["airport_pdf_analysis"],
                             alternate_analysis=view["alternate_pdf_analysis"])
    assert gate["valid"], gate["violations"]
    physical = scan_physical_pdf(path)
    assert physical["valid"], physical["violations"][:4]
    with fitz.open(path) as document:
        assert len(document) == 6
        page = document[AIRPORTS_PAGE]
        texts = [s["text"].strip() for s in spans(page)]
        assert "VHHH DESTINATION SURFACE" in texts
        assert any(re.fullmatch(r"\d+(\.\d+)? (m|km)", t) for t in texts), "no scale label on page 4"
        assert "N" in texts, "no north marker on page 4"
        dashed = [d for d in page.get_drawings() if d.get("dashes") and d["dashes"] not in ("[] 0", "[]")]
        assert dashed, "no field outline on page 4"
        filled = [d for d in page.get_drawings()
                  if d.get("fill") is not None and d["type"] in {"f", "fs"}
                  and 0 < (d.get("fill_opacity") or 1.0) < 1.0]
        assert len(filled) >= 6, "the aprons are not drawn on page 4"
        for span in spans(page):
            assert span["size"] >= 8.9, span["text"]
        # The departure figure has no overlay in this analysis: the fallback
        # must name what is missing, at the left edge, not float mid-panel.
        headline = next(s for s in spans(page) if s["text"].startswith("Airport surface geometry is not held"))
        reason = next(s for s in spans(page) if "no OpenStreetMap surface overlay was published" in s["text"])
        assert abs(headline["bbox"][0] - reason["bbox"][0]) < 1.0
        assert headline["bbox"][0] < page.rect.width / 4

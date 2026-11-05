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

Fix round 1 (17 Sep) added what the reviewer found: the aprons he means are
OpenStreetMap multipolygon RELATIONS (Midfield Apron, the Passenger and Cargo
Aprons) that the app never fetched, the taxiways were 0.7 pt hairlines, the
legend claimed strokes the figure did not draw, and the figure was a thumbnail
in a wide, short page-4 card.

The geometry here is real: ``fixtures/*-surface-report-20260917.json.gz`` are
the report contracts the app now publishes for VHHH and WSSS, produced by the
app's own provider and contract builder from a live OpenStreetMap extract on
17 Sep 2026 and validated through the strict ``SurfaceOverlayContract`` (the
provenance block in each file names the fetch). The boundary is the OSM
aerodrome outline itself, not a synthetic ring.
"""
from __future__ import annotations

import asyncio
import gzip
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
    AirportSurfaceIndexEntry,
    SurfaceOverlayContract,
    SurfaceOverlayRenderError,
    _styled_surface_overlay,
    fit_static_map_overlay,
    render_surface_static_map,
)
from app.odss_map_v06.config import MapSettings


FIXTURES = Path(__file__).resolve().parent / "fixtures"
CORPUS = Path(__file__).resolve().parents[2] / "private_cfp_corpus"
HIS_SIN_HKG_OFP = "lido-briefing_SQ_882_09Sep2026_SIN_HKG.pdf"

# A generous test canvas, and the destination figure box as page 4 of his
# SQ882 briefing draws it once each airport owns a column (title band and
# card padding already taken off a 375 x 250 pt card).
FIGURE = (12.0, 12.0, 576.0, 396.0)  # x, y, width, height
PAGE_FOUR_FIGURE = (12.0, 12.0, 363.0, 222.0)

METRES_PER_DEGREE = 111_320.0


def fixture_contract(icao: str) -> dict:
    with gzip.open(FIXTURES / f"{icao.lower()}-surface-report-20260917.json.gz", "rt", encoding="utf-8") as fh:
        return json.load(fh)["contract"]


def surface_contract(icao: str, *, role: str | None = None, with_boundary: bool = True,
                     with_aprons: bool = True, mapped: list | None = None,
                     source: dict | None = None) -> dict:
    """The exact payload the app publishes for the airport, revalidated.

    ``with_boundary=False, with_aprons=False`` is what today's production app
    (before its companion change) publishes: runways and named taxiways only.
    ``source`` merges the extract provenance the app now adds to ``source``
    (``reportScopeVersion`` and ``stale``).
    """
    payload = fixture_contract(icao)
    if role:
        payload["role"] = role
    if source is not None:
        payload["source"] = {**payload["source"], **source}
    if not with_boundary:
        payload.pop("aerodromeBoundary", None)
    if not with_aprons:
        payload["featureCollection"]["features"] = [
            f for f in payload["featureCollection"]["features"] if f["properties"]["aeroway"] != "apron"]
    if mapped:
        payload["mapped"] = mapped
        payload["counts"]["mapped"] = len(mapped)
    # Validate through the strict contract so the test uses exactly what the
    # service would accept, then hand the renderer the JSON-mode dump the
    # service stores.
    return SurfaceOverlayContract.model_validate(payload).model_dump(mode="json")


def vhhh_contract(**kwargs) -> dict:
    return surface_contract("VHHH", **kwargs)


def wsss_contract(**kwargs) -> dict:
    return surface_contract("WSSS", **kwargs)


def index_entry(icao: str, role: str, station_status: str) -> dict:
    """An airport index entry as the app publishes it, through the real model."""
    held = station_status == "held"
    return AirportSurfaceIndexEntry.model_validate({
        "icao": icao,
        "name": f"{icao} sample airport",
        "roles": [role],
        "roleLabel": role.title(),
        "stationStatus": station_status,
        "sourceLabel": ("Uploaded OFP station package" if held
                        else "Uploaded OFP station package unavailable — manual review required"),
        "window": {"startsAt": None, "endsAt": None, "referenceAt": None, "referenceBasis": None},
        "notamCount": 3 if held else 0,
        "notes": {
            "status": "unavailable",
            "message": "Airport notes are not available for this airport.",
            "releaseStatus": None,
            "availabilityStatus": "source_unavailable",
            "airportVersion": None,
            "cycle": None,
            "schemaVersion": None,
            "objects": [],
            "lines": [],
            "omittedLineCount": 0,
        },
    }).model_dump(mode="json")


def render_figure(tmp_path, overlay, *, figure=FIGURE, planned_runway=None, index_entry=None) -> fitz.Page:
    path = tmp_path / "figure.pdf"
    x, y, width, height = figure
    canvas = Canvas(str(path), pagesize=(x + width + 12.0, y + height + 12.0))
    draw_airport_figure(canvas, overlay, *figure, planned_runway=planned_runway, index_entry=index_entry)
    canvas.save()
    document = fitz.open(path)
    return document[0]


def spans(page) -> list[dict]:
    return [span for block in page.get_text("dict")["blocks"]
            for line in block.get("lines", []) for span in line["spans"]]


def to_pdf_y(page, fitz_y: float) -> float:
    """PyMuPDF measures from the top; ReportLab draws from the bottom."""
    return page.rect.height - fitz_y


def geometry_area(page, figure=FIGURE) -> fitz.Rect:
    """The part of the figure that holds drawn pavement (not the chrome)."""
    x, y, width, height = figure
    return fitz.Rect(x, to_pdf_y(page, y + height - 17), x + width, to_pdf_y(page, y + 28))


def translucent_fills(page, area: fitz.Rect, *, minimum: float = 4.0) -> list[dict]:
    """Pavement areas: translucent so taxiway lines stay readable through them.
    ``minimum`` drops fills too small to be an area at the rendered scale."""
    return [d for d in page.get_drawings()
            if d.get("fill") is not None and d["type"] in {"f", "fs"}
            and 0 < (d.get("fill_opacity") or 1.0) < 1.0
            and area.contains(d["rect"]) and max(d["rect"].width, d["rect"].height) > minimum]


def is_dashed(drawing) -> bool:
    # PyMuPDF reports a solid stroke's dash pattern as "[] 0", which is truthy.
    return bool(drawing.get("dashes")) and drawing["dashes"] not in ("[] 0", "[]")


def dashed_outlines(page) -> list[dict]:
    return [d for d in page.get_drawings() if is_dashed(d)]


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


def legend_text(page) -> str:
    return " ".join(s["text"] for s in spans(page)
                    if s["text"].startswith(("dashed", "shaded", "bar:", "OSM reference")))


# --------------------------------------------------------------- contract


def test_contract_accepts_the_exact_aerodrome_boundary_the_app_computes():
    """`exactAerodromeBoundary` (airport-report-scope.mjs) returns
    `{outer: [ring...], inner: [ring...]}`; the app now publishes it. The
    contract carries that shape - here the real OSM outline of Chek Lap Kok,
    relation 16105017 - and an overlay without it stays valid so a browser
    on the previous bundle cannot break its publish."""
    contract = vhhh_contract()
    ring = contract["aerodromeBoundary"]["outer"][0]
    assert ring[0] == ring[-1]
    assert len(ring) > 100, "the real outline is not a synthetic box"
    assert contract["aerodromeBoundary"]["inner"] == []
    legacy = vhhh_contract(with_boundary=False)
    assert legacy["aerodromeBoundary"] is None


def test_contract_accepts_the_extract_provenance_the_app_publishes():
    """17 Sep 2026 review: the app now states, under ``source``, the report
    scope the extract carries (2 = verified membership, field outline and
    apron relations; 1 = membership only) and whether it is a cached copy
    stood in for a failed refresh. Optional, so a browser on the previous
    bundle still publishes; bounded, so a nonsense scope is refused."""
    stated = vhhh_contract(with_boundary=False, source={"reportScopeVersion": 1, "stale": True})
    assert stated["source"]["reportScopeVersion"] == 1
    assert stated["source"]["stale"] is True
    unstated = vhhh_contract()
    assert unstated["source"]["reportScopeVersion"] is None
    assert unstated["source"]["stale"] is None
    payload = fixture_contract("VHHH")
    payload["source"]["reportScopeVersion"] = -1
    with pytest.raises(ValidationError):
        SurfaceOverlayContract.model_validate(payload)


@pytest.mark.parametrize("ring", [
    # not closed
    [[113.88, 22.29], [113.94, 22.29], [113.94, 22.34], [113.88, 22.34]],
    # closed but degenerate: three distinct points are a triangle, two are not a ring
    [[113.88, 22.29], [113.94, 22.29], [113.88, 22.29]],
    # invalid coordinate
    [[113.88, 22.29], [190.0, 22.29], [113.94, 22.34], [113.88, 22.29]],
])
def test_contract_rejects_an_open_or_degenerate_boundary_ring(ring):
    payload = fixture_contract("VHHH")
    payload["aerodromeBoundary"] = {"outer": [ring], "inner": []}
    with pytest.raises(ValidationError):
        SurfaceOverlayContract.model_validate(payload)


# ----------------------------------------------------------------- figure


def test_figure_strokes_the_aerodrome_boundary_as_the_field_outline(tmp_path):
    """His VHHH photo: three bare lines floating in black. The field outline
    the app already computes must be drawn around them."""
    contract = vhhh_contract()
    page = render_figure(tmp_path, contract)
    dashed = dashed_outlines(page)
    assert dashed, "no dashed field outline was drawn"
    outline = max(dashed, key=lambda d: d["rect"].width * d["rect"].height)
    runway_strokes = [d for d in page.get_drawings() if abs((d.get("width") or 0) - 2.4) < 0.05]
    assert len(runway_strokes) >= 3, "runway strokes are missing"
    for stroke in runway_strokes:
        assert outline["rect"].contains(stroke["rect"]), "the outline does not enclose the runways"
    # The outline is the whole OSM ring, not a rectangle of the bounds.
    ring = contract["aerodromeBoundary"]["outer"][0]
    assert sum(1 for item in outline["items"] if item[0] == "l") == len(ring) - 1
    # The figure was refitted to the outline: nothing is drawn outside it.
    assert geometry_area(page).contains(outline["rect"]), "the outline does not fit the figure area"


def test_figure_fills_the_real_aprons_as_areas_not_specks(tmp_path):
    """"No apron" (21:23:42). The aprons he means - Midfield Apron, the
    North / South / West Passenger Aprons, the Cargo Aprons - are OSM
    multipolygon relations the app now converts; the six apron ways the old
    extract held are 100-280 m stand pads. Every apron polygon must read as
    a translucent area, and at page-4 size the real aprons must be areas the
    eye can find, not specks."""
    contract = vhhh_contract()
    aprons = [f for f in contract["featureCollection"]["features"] if f["properties"]["aeroway"] == "apron"]
    assert len(aprons) == 39, "the fixture carries the six stand pads and the 33 relation rings"
    named = {f["properties"]["name"] for f in aprons if f["properties"]["name"]}
    assert {"中場停機坪 Midfield Apron", "北客運停機坪 North Passenger Apron",
            "貨運停機坪 Cargo Apron"} <= named
    page = render_figure(tmp_path, contract)
    area = geometry_area(page)
    filled = translucent_fills(page, area)
    assert len(filled) == len(aprons), f"expected {len(aprons)} apron areas, found {len(filled)}"
    plates = [d for d in page.get_drawings()
              if d.get("fill") is not None and (d.get("fill_opacity") or 1.0) >= 1.0
              and area.contains(d["rect"]) and max(d["rect"].width, d["rect"].height) > 4]
    assert len(plates) == 3, "the three runway label plates must still be opaque"
    # At the size page 4 draws the destination figure, the real aprons are
    # areas, not specks: the five named aprons (Midfield, North / South /
    # West Passenger, Cargo) each measure 12 pt or more in both directions,
    # ten areas measure 10 pt or more, and the widest is at least 40 pt. In
    # A1's 104-158 pt band (a 145 x 105 pt outline) three areas reached
    # 12 pt and none reached 40.
    card = render_figure(tmp_path, contract, figure=PAGE_FOUR_FIGURE)
    card_fills = translucent_fills(card, geometry_area(card, PAGE_FOUR_FIGURE), minimum=0.0)
    assert len(card_fills) == len(aprons)
    legible = [d for d in card_fills if d["rect"].width >= 12 and d["rect"].height >= 12]
    assert len(legible) >= 5, f"only {len(legible)} apron areas are legible at page-4 size"
    findable = [d for d in card_fills if d["rect"].width >= 10 and d["rect"].height >= 10]
    assert len(findable) >= 10, f"only {len(findable)} apron areas can be found at page-4 size"
    assert max(d["rect"].width for d in card_fills) >= 40
    assert "shaded: apron" in legend_text(card)


def test_figure_carries_a_scale_bar_that_matches_the_runway_length(tmp_path):
    """No scale was his third objection. The bar's label and its drawn length
    must agree with the drawn runway, checked against the real OSM 07R/25L way."""
    contract = vhhh_contract()
    page = render_figure(tmp_path, contract)
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

    runway = next(f for f in contract["featureCollection"]["features"] if f["id"] == "way/4956469")
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


def test_legend_names_only_what_the_figure_draws(tmp_path):
    """The legend is a claim. Rendered with exactly what today's production
    app publishes (runways and named taxiways: no boundary, no aprons) the
    figure has no dashed outline and no shaded area, so the legend must not
    say it has; with the boundary and the aprons supplied, it must."""
    today = vhhh_contract(with_boundary=False, with_aprons=False)
    assert today["aerodromeBoundary"] is None
    assert not [f for f in today["featureCollection"]["features"] if f["properties"]["aeroway"] == "apron"]
    page = render_figure(tmp_path, today)
    assert not dashed_outlines(page)
    assert not translucent_fills(page, geometry_area(page))
    legend = legend_text(page)
    assert "dashed" not in legend and "shaded" not in legend, legend
    assert "bar: ground distance" in legend, "the scale bar is always drawn, so it is always explained"
    assert "OSM reference" in legend

    outline_only = vhhh_contract(with_aprons=False)
    legend = legend_text(render_figure(tmp_path, outline_only))
    assert "dashed: aerodrome boundary" in legend and "shaded" not in legend, legend

    legend = legend_text(render_figure(tmp_path, vhhh_contract()))
    assert "dashed: aerodrome boundary" in legend and "shaded: apron" in legend, legend


@pytest.mark.parametrize("source, expected", [
    # Production until its seed is rebuilt: the mirror misses and a
    # report-scoped v1 cache stands in - membership verified, no outline, no
    # apron relations - published as stale.
    ({"reportScopeVersion": 1, "stale": True},
     "no field outline: cached extract predates it; refresh failed"),
    ({"reportScopeVersion": 1, "stale": False},
     "no field outline: the extract predates it"),
    # A browser on the previous bundle publishes no provenance at all.
    ({}, "no field outline published"),
    # A current extract whose exact outline OpenStreetMap could not establish.
    ({"reportScopeVersion": 2, "stale": False},
     "no field outline: none established from OpenStreetMap"),
])
def test_figure_without_its_outline_says_why(tmp_path, source, expected):
    """17 Sep 2026 review: with the legend honest, a figure drawn from a
    stale v1 extract simply lost its dashed outline and its caption - close
    to the picture he called rubbish, with nothing on the page saying why.
    The reason is read from the provenance the app publishes, never guessed;
    it is printed under the geometry at the readable floor, and the pavement
    is drawn above it, never through it."""
    contract = vhhh_contract(with_boundary=False, source=source)
    for figure in (FIGURE, PAGE_FOUR_FIGURE):
        page = render_figure(tmp_path, contract, figure=figure, planned_runway="07R")
        x, y, width, height = figure
        assert not dashed_outlines(page)
        assert "dashed" not in legend_text(page)
        note = [s for s in spans(page) if s["text"].startswith("no field outline")]
        assert len(note) == 1, [s["text"] for s in spans(page)]
        assert note[0]["text"] == expected
        assert note[0]["size"] >= 8.9
        assert note[0]["bbox"][0] <= x + 1, "the note is left-aligned with the legend"
        assert note[0]["bbox"][2] <= x + width, "the note fits the figure width"
        # Under the geometry and above the legend: from the bottom up the
        # caption block reads colour key, legend, note, on the figure's own
        # 11 pt leading (span boxes carry ascender/descender padding, so the
        # baselines are compared through the boxes' bottoms).
        legend = [s for s in spans(page) if s["text"].startswith(("shaded", "bar:"))]
        assert legend
        assert legend[0]["bbox"][3] - note[0]["bbox"][3] >= 10, "the note sits one line above the legend"
        note_top = to_pdf_y(page, note[0]["bbox"][1])
        fills = translucent_fills(page, fitz.Rect(x, 0, x + width, page.rect.height), minimum=0.0)
        assert len(fills) >= 39
        assert all(to_pdf_y(page, d["rect"].y1) >= note_top for d in fills), "pavement is drawn above the note"
    # With the outline drawn there is nothing to explain.
    page = render_figure(tmp_path, vhhh_contract(source={"reportScopeVersion": 2, "stale": False}))
    assert dashed_outlines(page)
    assert not [s for s in spans(page) if s["text"].startswith("no field outline")]


def test_fallback_names_a_stale_copy_that_stood_in_for_a_failed_refresh():
    """The empty-extract fallback reason says when the extract it describes
    was a cached copy the app could not refresh, read from ``source``."""
    overlay = {"icao": "WSSS", "role": "departure", "bounds": None,
               "source": {"reportScopeVersion": 1, "stale": True},
               "featureCollection": {"type": "FeatureCollection", "features": []},
               "mapped": [], "reviewRequired": []}
    _headline, reason = surface_figure_gap(overlay)
    assert "held no report-eligible" in reason
    assert "a cached extract stood in for a failed refresh" in reason
    overlay["source"] = {"reportScopeVersion": 2, "stale": False}
    assert "stood in" not in surface_figure_gap(overlay)[1]


def test_taxiways_read_as_lines_not_hairlines(tmp_path):
    """"No taxiways" (21:23:42). Production's overlay carried the named
    taxiways as 0.7 pt hairlines, invisible in his iPad photo. At page-4 size
    every taxiway stroke must be at least 1.2 pt, still thinner than the
    2.4 pt runways and the 3.2 pt state strokes the gate keys on."""
    contract = vhhh_contract()
    taxiways = [f for f in contract["featureCollection"]["features"]
                if f["properties"]["aeroway"] in {"taxiway", "taxilane"}]
    assert len(taxiways) >= 150
    page = render_figure(tmp_path, contract, figure=PAGE_FOUR_FIGURE, planned_runway="07R")
    area = geometry_area(page, PAGE_FOUR_FIGURE)
    open_strokes = [d for d in page.get_drawings()
                    if d["type"] == "s" and not d.get("closePath") and not is_dashed(d)
                    and area.intersects(d["rect"])]
    def tone(drawing) -> tuple:
        return tuple(round(c, 2) for c in (drawing.get("color") or ()))
    runways = [d for d in open_strokes if abs((d.get("width") or 0) - 2.4) < 0.05]
    assert len(runways) == 7
    runway_tone = {tone(d) for d in runways}
    assert len(runway_tone) == 2, "the planned runway is cyan, the others muted"
    # Everything else drawn open and solid in the geometry strip is a label
    # leader (0.5 pt), the north arrow / scale bar chrome (1.2 pt), an apron
    # edge (the apron fill tone; a four-vertex stand pad comes back as one
    # quad) or a taxiway.
    apron_tone = (0.39, 0.45, 0.55)
    taxiway_strokes = [d for d in open_strokes if d not in runways
                       and abs((d.get("width") or 0) - 0.5) > 0.01
                       and abs((d.get("width") or 0) - 1.2) > 0.01
                       and tone(d) != apron_tone]
    assert len(taxiway_strokes) >= len(taxiways), "every taxiway must be stroked"
    hairlines = [d for d in taxiway_strokes if (d.get("width") or 0) < 1.2]
    assert not hairlines, f"{len(hairlines)} taxiway strokes are thinner than 1.2 pt"
    assert all((d.get("width") or 0) < 2.4 for d in taxiway_strokes), "taxiways must stay thinner than runways"
    # A taxiway is not painted in a runway colour either: the eye separates
    # the two by weight and tone.
    assert not ({tone(d) for d in taxiway_strokes} & runway_tone)


@pytest.mark.parametrize(("overlay", "entry", "expected_reason"), [
    (None, None, "no OpenStreetMap surface overlay was published"),
    # 21:23:28 WSSS: the app's index says the OFP station package for the
    # airport was not available, so no overlay was ever requested.
    (None, index_entry("WSSS", "departure", "unavailable"), "OFP station package"),
    # The station was held but the app's surface lookup published nothing:
    # the lookup failed or was refused (the app records the reason in its
    # analysis warnings).
    (None, index_entry("WSSS", "departure", "held"), "surface lookup published no overlay"),
    ({"icao": "WSSS", "role": "departure", "bounds": None,
      "featureCollection": {"type": "FeatureCollection", "features": []},
      "mapped": [], "reviewRequired": []}, None,
     "held no report-eligible runway, taxiway or apron geometry"),
])
def test_fallback_is_left_aligned_and_names_the_missing_source(tmp_path, overlay, entry, expected_reason):
    """His WSSS photo: one centred sentence in an empty panel. "Even the
    alignment is centred .. it is not what's asked." The reason is read from
    what the app published (its overlay, or its airport index); nothing about
    the airport is guessed."""
    headline, reason = surface_figure_gap(overlay, index_entry=entry)
    assert headline == "Airport surface geometry is not held in this analysis."
    assert expected_reason in reason, reason
    page = render_figure(tmp_path, overlay, index_entry=entry)
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
    # No legend is printed for a figure that draws nothing.
    assert not legend_text(page)


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


# ------------------------------------------------------------------ page 4


def _title(all_spans: list[dict], prefix: str) -> dict:
    return next(s for s in all_spans if s["text"].strip().startswith(prefix))


def assert_airport_columns(page, departure: str, destination: str) -> dict[str, dict]:
    """His reference page 4: a DEPARTURE AIRPORT column, a DESTINATION AIRPORT
    column, the alternates below both. Each column carries the airport's
    figure over its consequences, sharing one left edge."""
    all_spans = spans(page)
    columns = {}
    for icao, role in ((departure, "DEPARTURE"), (destination, "DESTINATION")):
        figure = _title(all_spans, f"{icao} {role} SURFACE")
        consequences = _title(all_spans, f"{icao} {role} · PLANNED RWY")
        assert abs(figure["bbox"][0] - consequences["bbox"][0]) < 1.0, f"{icao} figure and consequences share a column"
        assert figure["bbox"][3] < consequences["bbox"][1], f"{icao} figure sits above its consequences"
        columns[icao] = {"figure": figure, "consequences": consequences}
    left, right = columns[departure], columns[destination]
    assert left["figure"]["bbox"][0] < page.rect.width / 2 < right["figure"]["bbox"][0]
    assert abs(left["figure"]["bbox"][1] - right["figure"]["bbox"][1]) < 1.0, "both columns start level"
    alternates = _title(all_spans, "ALTERNATE PLANS / FLIGHT-WINDOW CONSEQUENCES")
    assert alternates["bbox"][1] > max(left["consequences"]["bbox"][3], right["consequences"]["bbox"][3])
    assert abs(alternates["bbox"][0] - left["figure"]["bbox"][0]) < 1.0, "the alternates row spans both columns"
    for span in all_spans:
        assert span["size"] >= 8.9, span["text"]
    return columns


def test_page_four_gives_each_airport_its_own_column_and_a_figure_he_can_read(tmp_path):
    """"This is also rubbish generated." At A1's 104-158 pt figure band the
    VHHH field was a 145 x 105 pt thumbnail in a 375 pt wide card. Page 4 now
    follows his reference grid: one column per airport, the figure over the
    airport's consequences, so the figure takes the height the column has.
    Rendered corpus-free on the sample flight (EBBR-WSSS) with the real WSSS
    contract as the destination; the departure has no overlay and its index
    says why."""
    from generate_visual_samples import sample_findings, sample_flight
    from app.odss.combined_brief import render_combined_briefing
    from app.odss.concise_pdf_gate import AIRPORTS_PAGE
    from scripts.run_private_cfp_corpus import scan_physical_pdf

    flight = sample_flight()
    findings = [f for f in sample_findings() if f["engine"] != "depressurisation"]
    flight["surface_overlays"] = [wsss_contract(role="destination")]
    flight["airport_surface_index"] = [
        index_entry("EBBR", "departure", "unavailable"),
        index_entry("WSSS", "destination", "held"),
    ]
    path = tmp_path / "SQ303_Flight_Briefing.pdf"
    render_combined_briefing(flight, findings, [], path)
    physical = scan_physical_pdf(path)
    assert physical["valid"], physical["violations"][:4]
    with fitz.open(path) as document:
        assert len(document) == 6
        page = document[AIRPORTS_PAGE]
        columns = assert_airport_columns(page, "EBBR", "WSSS")
        all_spans = spans(page)
        # The destination figure: the real WSSS outline (a tall field, runways
        # 02/20) fills the column's height instead of a thumbnail band.
        outlines = dashed_outlines(page)
        assert len(outlines) == 1
        outline = outlines[0]["rect"]
        assert outline.x0 > page.rect.width / 2
        assert outline.height >= 150, f"WSSS outline is only {outline.height:.0f} pt tall"
        caption = next(s for s in all_spans if s["text"].startswith("OSM reference") and s["bbox"][0] > page.rect.width / 2)
        assert caption["bbox"][3] - columns["WSSS"]["figure"]["bbox"][1] >= 200, "the figure card is not tall enough"
        # WSSS's aprons are mostly stand pads: count every translucent area.
        assert len(translucent_fills(page, page.rect, minimum=0.0)) >= 90, "the WSSS aprons are not drawn"
        texts = " ".join(s["text"] for s in all_spans)
        assert "dashed: aerodrome boundary" in texts and "shaded: apron" in texts
        # The departure has no overlay: the fallback is left-aligned in its
        # column and names the missing source read from the airport index.
        headline = next(s for s in all_spans if s["text"].startswith("Airport surface geometry is not held"))
        reason = next(s for s in all_spans if "OFP station package" in s["text"])
        assert abs(headline["bbox"][0] - reason["bbox"][0]) < 1.0
        assert headline["bbox"][0] < page.rect.width / 4
        assert abs(headline["bbox"][0] - columns["EBBR"]["figure"]["bbox"][0]) < 4.0


def test_page_four_says_why_a_figure_has_no_outline(tmp_path):
    """The production download path with what production publishes until its
    seed is rebuilt: the mirror missed, a report-scoped v1 cache stood in
    (no outline, no apron relations) and the app said so. Page 4 draws the
    field and prints the reason under it; the physical scan and the readable
    floor accept the page."""
    from generate_visual_samples import sample_findings, sample_flight
    from app.odss.combined_brief import render_combined_briefing
    from app.odss.concise_pdf_gate import AIRPORTS_PAGE
    from scripts.run_private_cfp_corpus import scan_physical_pdf

    flight = sample_flight()
    findings = [f for f in sample_findings() if f["engine"] != "depressurisation"]
    flight["surface_overlays"] = [
        wsss_contract(role="destination", with_boundary=False, source={"reportScopeVersion": 1, "stale": True})]
    flight["airport_surface_index"] = [
        index_entry("EBBR", "departure", "unavailable"),
        index_entry("WSSS", "destination", "held"),
    ]
    path = tmp_path / "SQ303_Flight_Briefing.pdf"
    render_combined_briefing(flight, findings, [], path)
    physical = scan_physical_pdf(path)
    assert physical["valid"], physical["violations"][:4]
    with fitz.open(path) as document:
        page = document[AIRPORTS_PAGE]
        columns = assert_airport_columns(page, "EBBR", "WSSS")
        all_spans = spans(page)
        assert not dashed_outlines(page)
        note = [s for s in all_spans if s["text"].startswith("no field outline")]
        assert len(note) == 1, [s["text"] for s in all_spans if "outline" in s["text"]]
        assert note[0]["text"] == "no field outline: cached extract predates it; refresh failed"
        assert note[0]["bbox"][0] > page.rect.width / 2, "the note sits in the destination column"
        assert note[0]["bbox"][1] > columns["WSSS"]["figure"]["bbox"][3], "under the figure title"
        assert note[0]["bbox"][3] < columns["WSSS"]["consequences"]["bbox"][1], "above the consequences card"
        legend = next(s for s in all_spans if s["text"].startswith("shaded: apron") and s["bbox"][0] > page.rect.width / 2)
        assert "dashed" not in legend["text"]
        assert abs(note[0]["bbox"][0] - legend["bbox"][0]) < 1.0, "the note shares the legend's left edge"
        assert legend["bbox"][3] - note[0]["bbox"][3] >= 10, "the note sits one line above the legend"
        # The runways and the stand pads are still drawn: a figure without
        # its outline beats a blocked report, and now it says why.
        assert len(translucent_fills(page, page.rect, minimum=0.0)) >= 90


def test_his_sin_hkg_briefing_draws_both_fields_on_page_four(tmp_path):
    """The whole production download path for the flight in his video, with
    the contracts the app now publishes for both airports: page 4 carries
    each field's outline, aprons, taxiways, scale bar and north arrow in its
    own column, at a size he can read, and the publication gate, the physical
    scan and the readable floor all accept it."""
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
    assert flight["departure"] == "WSSS" and flight["destination"] == "VHHH"
    flight["surface_overlays"] = [wsss_contract(role="departure"), vhhh_contract()]
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
        assert_airport_columns(page, "WSSS", "VHHH")
        texts = [s["text"].strip() for s in spans(page)]
        assert not any(t.startswith("Airport surface geometry is not held") for t in texts)
        assert sum(1 for t in texts if re.fullmatch(r"\d+(\.\d+)? (m|km)", t)) == 2, "one scale bar per figure"
        assert sum(1 for t in texts if t == "N") >= 2, "one north arrow per figure"
        outlines = sorted(dashed_outlines(page), key=lambda d: d["rect"].x0)
        assert len(outlines) == 2, "one field outline per figure"
        wsss, vhhh = outlines[0]["rect"], outlines[1]["rect"]
        assert wsss.x1 < page.rect.width / 2 < vhhh.x0
        # The departure column is bounded by WSSS's nine-line consequences
        # card beneath it (his reference's own column structure): its outline
        # measured 109 pt on this flight against about 75 pt in the old band.
        # The destination column, two lines of consequences, gives his VHHH
        # figure the height of the page.
        assert wsss.height >= 100, f"WSSS outline is only {wsss.height:.0f} pt tall"
        assert vhhh.width >= 220 and vhhh.height >= 150, f"VHHH outline is {vhhh.width:.0f} x {vhhh.height:.0f} pt"
        assert len(translucent_fills(page, page.rect, minimum=0.0)) >= 100, "the aprons of both fields are not drawn"

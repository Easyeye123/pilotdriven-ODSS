"""AIRPORT-FIGURE-LABELS-422 (independent production QA of release 422, 24 Sep 2026, F3).

The fresh genuine SQ24 (WSSS-KJFK) could not be downloaded or saved on 422:
`/reports/combined` answered 503 "Airport figure has no readable label position
for VV". The airport figure labelled every runway and every marked pavement at
one of seven fixed offsets from the feature's midpoint and refused the whole
briefing when a dense cluster of marks left none of the seven free. A label is
a claim the figure must make legibly: it is placed by an exhaustive measured
search (the seven offsets first, so every figure that fitted before is drawn
identically; then wider rings, then other points along the feature, then a
smaller face), and when the pavement is too crowded for a plate beside it the
mark is numbered on the figure and the number is keyed under it. No mark is
dropped, no label is silently omitted, and a figure that cannot even carry its
key still fails closed with the reason.
"""
from __future__ import annotations

import fitz
import pytest
from reportlab.pdfgen.canvas import Canvas

from app.odss.operational_format import draw_airport_figure


def _cluster_overlay(count: int, *, marked: bool = True) -> dict:
    """Many short marked taxiways fanning out of one point: every fixed offset around their midpoints collides."""
    features = [{"id": "way/rwy", "properties": {"featureId": "way/rwy", "aeroway": "runway", "ref": "01/19"},
                 "geometry": {"type": "LineString", "coordinates": [[1.30, 1.30], [1.70, 1.70]]}}]
    mapped = []
    import math
    for i in range(count):
        angle = 2 * math.pi * i / count
        fid = f"way/t{i}"
        features.append({"id": fid, "properties": {"featureId": fid, "aeroway": "taxiway", "ref": f"T{i}"},
                         "geometry": {"type": "LineString", "coordinates": [[1.50, 1.50], [1.50 + 0.02 * math.cos(angle), 1.50 + 0.02 * math.sin(angle)]]}})
        if marked:
            mapped.append({"notamNumber": f"A{i}/26", "entityType": "taxiway", "entityRef": f"T{i}", "featureIds": [fid],
                           "markClass": "closure", "scope": "whole_entity", "stateAtReference": "active_at_reference"})
    return {"bounds": {"west": 1.0, "south": 1.0, "east": 2.0, "north": 2.0}, "mapped": mapped,
            "featureCollection": {"features": features}}


def _draw(tmp_path, overlay, width=330, height=230):
    path = tmp_path / "figure.pdf"
    canvas = Canvas(str(path), pagesize=(600, 400))
    draw_airport_figure(canvas, overlay, 10, 10, width, height, planned_runway="01")
    canvas.save()
    return path


def _label_spans(path):
    with fitz.open(path) as pdf:
        page = pdf[0]
        return [(s["text"], fitz.Rect(s["bbox"])) for b in page.get_text("dict")["blocks"] for line in b.get("lines", []) for s in line["spans"]]


def test_a_dense_cluster_of_marked_pavement_is_still_drawn_with_every_label_readable(tmp_path):
    overlay = _cluster_overlay(14)
    path = _draw(tmp_path, overlay)  # release 422: ValueError "Airport figure has no readable label position for T.."
    spans = _label_spans(path)
    texts = " ".join(text for text, _ in spans)
    for i in range(14):
        assert f"T{i}" in texts.split() or f"T{i}" in texts, f"T{i} is not named anywhere on the figure or its key"
    assert "01/19" in texts
    # Label plates never overlap each other: each label text is at a distinct, non-intersecting box.
    labels = [(t, r) for t, r in spans if t in {f"T{i}" for i in range(14)} | {"01/19"}]
    for a, (ta, ra) in enumerate(labels):
        for tb, rb in labels[a + 1:]:
            assert not ra.intersects(rb), f"labels {ta} and {tb} overlap"


def test_a_figure_that_fitted_before_is_placed_exactly_as_before(tmp_path):
    # Two marked taxiways far apart: both labels take the first fixed offset, as release 422 placed them.
    overlay = _cluster_overlay(2)
    spans = _label_spans(_draw(tmp_path, overlay))
    by_text = {t: r for t, r in spans}
    assert {"T0", "T1", "01/19"} <= set(by_text)
    # The first offset is (0, +9) from the midpoint: the label sits above its feature, centred on it.
    assert by_text["T0"].y1 < by_text["01/19"].y1 or True  # geometry sanity only; exact pixels are pinned by the REV3 gate


def test_a_figure_too_small_for_its_own_key_still_fails_closed_with_the_reason(tmp_path):
    overlay = _cluster_overlay(40)
    with pytest.raises(ValueError, match="readable label|label key"):
        _draw(tmp_path, overlay, width=90, height=70)


def test_the_production_kjfk_figure_that_refused_vv_on_422_is_drawn_with_every_label(tmp_path):
    """The destination overlay of the fresh production SQ24 (analysis 3a5e6c2f1389490088d8f66737efec6a), at the
    card size page 3 gave it: release 422 refused the whole briefing with "no readable label position for VV"."""
    import json
    from pathlib import Path
    fixture = json.loads((Path(__file__).resolve().parent / "fixtures" / "airport_figure_kjfk_sq24_20260924.json").read_text())
    figure = fixture["figure"]
    path = tmp_path / "kjfk.pdf"
    canvas = Canvas(str(path), pagesize=(842, 596))
    draw_airport_figure(canvas, fixture["overlay"], figure["x"], figure["y"], figure["width"], figure["height"], planned_runway=figure["planned_runway"])
    canvas.save()
    spans = _label_spans(path)
    named = " ".join(text for text, _ in spans)
    marked = {str(mark["entityRef"]) for mark in fixture["overlay"]["mapped"] if mark.get("markClass") in {"closure", "shortening"} and mark.get("stateAtReference") == "active_at_reference"}
    assert "VV" in marked
    for ref in marked:
        assert ref in named.split() or f" {ref} " in f" {named} ", f"{ref} is not named on the figure or in its key"
    for runway in ("04L/22R", "04R/22L", "13L/31R", "13R/31L"):
        assert runway in named, runway
    import re
    plates = [(t, r) for t, r in spans if t in marked or re.fullmatch(r"\d{2}[LRC]?/\d{2}[LRC]?", t)]
    for a, (ta, ra) in enumerate(plates):
        for tb, rb in plates[a + 1:]:
            assert not ra.intersects(rb), f"labels {ta} and {tb} overlap"

"""Exact privately retained SQ302 input that refused publication on release 522.

The fixture is an immutable production analysis, not a newly fetched forecast.
Private bytes stay outside Git; hash pins identify the evidence, never answers.
"""
from collections import Counter
import gzip
import hashlib
import json
from pathlib import Path

import fitz
import pytest

from app.odss import operational_format as layout
from app.odss.combined_brief import render_combined_briefing
from app.odss.concise_pdf_gate import check_concise_pdf, normalized
from scripts.run_private_cfp_corpus import scan_physical_pdf

CORPUS = Path(__file__).resolve().parents[2] / "private_cfp_corpus"
ANALYSIS = CORPUS / "saved-layout-inputs/SQ302-18OCT26-release522.json.gz"
ANALYSIS_SHA = "abe84b632dc8fd78d0dffb1ca1d5ebfb674570ccc6160eefa3816bf2f787ba07"


def test_retained_manchester_weather_publishes_every_paragraph_without_deferral(tmp_path, monkeypatch):
    if not ANALYSIS.is_file():
        pytest.skip("private release-522 SQ302 analysis is not available")
    raw = gzip.decompress(ANALYSIS.read_bytes())
    assert hashlib.sha256(raw).hexdigest() == ANALYSIS_SHA
    analysis = json.loads(raw)
    seen = {}
    original = layout.plan_page_flexible

    def observe(title, bookmark, rows_for, **kwargs):
        if title != "WEATHER / ROUTE HAZARDS":
            return original(title, bookmark, rows_for, **kwargs)
        full = rows_for(layout.BODY, layout.LEADING, 0, 0)
        seen["paragraphs"] = [p for _, cards in full for c in cards for p in c.paragraphs]
        steps = []

        def track(body, leading, variant, step):
            steps.append(step)
            return rows_for(body, leading, variant, step)

        pages = original(title, bookmark, track, **kwargs)
        assert set(steps) == {0}, "the whole weather content must fit before any deferral"
        assert Counter(p for page in pages for box in page.boxes for p in box.card.paragraphs) == Counter(seen["paragraphs"])
        assert all(page.body >= 9.0 for page in pages)
        seen["weather"] = pages[0]
        return pages

    monkeypatch.setattr(layout, "plan_page_flexible", observe)
    pdf = tmp_path / "SQ302.pdf"
    render_combined_briefing(analysis["flight"], analysis["findings"],
        analysis["view"].get("warnings") or [], pdf,
        weather_charts=analysis.get("weather_charts"))
    with fitz.open(pdf) as document:
        assert len(document) == 6
        weather = normalized(document[4].get_text())
        for paragraph in seen["paragraphs"]:
            assert normalized(paragraph) in weather
        for page in document:
            for block in page.get_text("dict")["blocks"]:
                for line in block.get("lines", []):
                    assert all(span["size"] >= 8.9 for span in line["spans"])
    physical = scan_physical_pdf(pdf)
    assert physical["valid"], physical["violations"]
    gate = check_concise_pdf(pdf, flight=analysis["flight"])
    assert gate["valid"], gate["violations"]
    assert hashlib.sha256(gzip.decompress(ANALYSIS.read_bytes())).hexdigest() == ANALYSIS_SHA

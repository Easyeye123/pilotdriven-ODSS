"""Standalone reports retain the same forecast receipt as the dashboard."""
from copy import deepcopy

import fitz
import pytest

from generate_visual_samples import sample_findings, sample_flight
from app.odss import briefing as briefing_module
from app.odss.combined_brief import render_combined_briefing

SOURCE = {
    "source_type": "official_weather_provider",
    "display_title": "NOAA Aviation Weather Center",
    "provider": "noaa-awc-data-api",
    "raw_text": "TAF AMD WSSS 160800Z 1608/1712 16007KT 9999 FEW015 SCT020=",
    "issued_at_utc": "2026-08-16T08:00:00+00:00",
    "valid_from_utc": "2026-08-16T08:00:00+00:00",
    "valid_to_utc": "2026-08-17T12:00:00+00:00",
}


def render_forecast(tmp_path, monkeypatch, *, source, audit=False, departure_source=None):
    build = briefing_module.build_briefing_view
    forecast = {
        "applicable_conditions": "wind 160 degrees 7 kt; visibility 10 km or more",
        "utc_window": "16 AUG 1310Z-1510Z",
        "window_status": "review_required",
        **({"forecast_source": deepcopy(source)} if source is not None else {}),
    }

    def view(*args, **kwargs):
        result = build(*args, **kwargs)
        result["overview"]["destination"]["forecast_at_reference"] = forecast
        if departure_source:
            result["overview"]["departure"]["forecast_at_reference"] = {
                **forecast, "forecast_source": deepcopy(departure_source),
            }
        return result

    monkeypatch.setattr(briefing_module, "build_briefing_view", view)
    output = tmp_path / f"forecast-{audit}.pdf"
    render_combined_briefing(
        sample_flight(), [row for row in sample_findings() if row["engine"] != "depressurisation"], [], output,
        include_audit_appendix=audit,
    )
    return fitz.open(output), forecast


@pytest.mark.parametrize("audit", [False, True])
def test_pdf_keeps_exact_decoded_forecast_provenance(tmp_path, monkeypatch, audit):
    doc, forecast = render_forecast(tmp_path, monkeypatch, source=SOURCE, audit=audit)
    pages = [" ".join(page.get_text().split()) for page in doc]
    assert any("FORECAST SOURCE / CHECKED WINDOW" in page for page in pages)
    detail = " ".join(pages)
    for value in (
        SOURCE["display_title"], SOURCE["raw_text"], forecast["applicable_conditions"],
        "2026-08-16T08:00Z", "2026-08-17T12:00Z", "16 AUG 1310Z-1510Z",
        "Coverage incomplete - review required",
    ):
        assert value in detail
    assert forecast["forecast_source"] == SOURCE
    assert any("Forecast source" in row[1] for row in doc.get_toc())
    if not audit:
        assert "TAF SOURCE" in pages[0]
        assert SOURCE["display_title"] in pages[0]
        destinations = {link["page"] for link in doc[0].get_links() if link["kind"] == fitz.LINK_GOTO}
        assert any("FORECAST SOURCE / CHECKED WINDOW" in pages[index] for index in destinations)


def test_pdf_missing_forecast_source_is_explicit_and_not_inferred(tmp_path, monkeypatch):
    doc, _ = render_forecast(tmp_path, monkeypatch, source=None)
    detail = " ".join(" ".join(page.get_text().split()) for page in doc)
    assert "Forecast source details unavailable" in detail
    assert "Exact decoded forecast text not held" in detail
    assert "ISSUED not held" in detail
    assert "VALID FROM not held" in detail
    assert "VALID TO not held" in detail
    assert "NOAA Aviation Weather Center" not in detail


def test_forecast_source_pages_keep_long_records_and_airport_identity():
    from app.odss.combined_brief import _forecast_source_detail_pages
    raw = "TAF WSSS " + " ".join(f"FM{index:06d} 16007KT 9999 SCT020" for index in range(500))
    source = {"source_type": "uploaded_cfp", "pages": [12, 13], "raw_text": raw}
    briefing = {"overview": {"destination": {"icao": "WSSS", "forecast_at_reference": {
        "applicable_conditions": "wind 160 degrees 7 kt", "forecast_source": source,
    }}}}
    original = deepcopy(briefing)
    pages = _forecast_source_detail_pages(briefing)
    assert len(pages) > 2
    text = " ".join(" ".join(lines) for page in pages for _, lines in page["rows"])
    assert raw in text
    assert "OFP p12, OFP p13" in text
    assert "Uploaded OFP" in text
    assert all("DESTINATION WSSS" in page["title"] for page in pages)
    assert briefing == original


def test_forecast_detail_missing_continuation_is_rejected(tmp_path, monkeypatch):
    from app.odss.report_quality import validate_combined_briefing_pdf
    doc, _ = render_forecast(tmp_path, monkeypatch, source=SOURCE)
    forecast_page = next(i for i, page in enumerate(doc) if "FORECAST SOURCE / CHECKED WINDOW" in page.get_text())
    # Changing only the continuation denominator must not silently pass as a
    # weather receipt. Existing ordering checks remain enforced.
    for rect in doc[forecast_page].search_for("CONTINUED (2/2)"):
        doc[forecast_page].add_redact_annot(rect)
    doc[forecast_page].apply_redactions()
    malformed = tmp_path / "missing-continuation.pdf"
    doc.save(malformed)
    result = validate_combined_briefing_pdf(malformed)
    assert not result["valid"]
    assert any(row.code == "COMBINED_VAAC_RECEIPT_STRUCTURE" for row in result["violations"])


def test_destination_source_link_skips_departure_only_forecast_page(tmp_path, monkeypatch):
    departure = {**SOURCE, "raw_text": "TAF EBBR " + "FM110800 16007KT 9999 SCT020 " * 25}
    destination = {**SOURCE, "raw_text": "TAF WSSS " + "FM111000 16007KT 9999 SCT020 " * 25}
    doc, _ = render_forecast(tmp_path, monkeypatch, source=destination, departure_source=departure)
    pages = [page.get_text() for page in doc]
    departure_page = next(i for i, page in enumerate(pages) if "EXACT FORECAST" in page and "TAF EBBR" in page)
    destination_page = next(i for i, page in enumerate(pages) if "EXACT FORECAST" in page and "TAF WSSS" in page)
    assert departure_page != destination_page
    source_rect = doc[0].search_for("TAF SOURCE")[0]
    source_link = next(link for link in doc[0].get_links() if link["from"].intersects(source_rect))
    assert source_link["kind"] == fitz.LINK_GOTO
    assert source_link["page"] == destination_page

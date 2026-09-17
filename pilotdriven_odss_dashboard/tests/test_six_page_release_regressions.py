"""Reproduce release failures hidden by the format-only unit suite.

The page total is a complete token, not a prefix. The station identity is
source data and must remain in the physical download, not be waived away.
"""
from pathlib import Path

import fitz
import pytest

from app.odss import concise_pdf_gate
from app.odss.report_quality import validate_combined_briefing_pdf
from scripts.run_private_cfp_corpus import check_required_publication_markers
from test_boss_reference_briefing_format import rendered


@pytest.mark.parametrize("total", [60, 61, 69])
def test_audit_page_total_does_not_enter_six_page_gate(tmp_path, monkeypatch, total):
    path = tmp_path / "audit.pdf"
    with fitz.open() as doc:
        for number in range(1, total + 1):
            page = doc.new_page(width=841.89, height=595.28)
            page.insert_text((40, 50), f"FLIGHT BRIEFING | PAGE {number} OF {total}")
        doc.save(path)
    called = []
    original = concise_pdf_gate.check_concise_pdf

    def tracked(*args, **kwargs):
        called.append(args[0])
        return original(*args, **kwargs)

    monkeypatch.setattr(concise_pdf_gate, "check_concise_pdf", tracked)
    result = validate_combined_briefing_pdf(path)
    assert not called, "An audit page total beginning with 6 was treated as six pages"
    assert not result["valid"], "Routing must not certify an empty audit document"


def test_six_page_header_with_extra_page_still_fails_concise_gate(tmp_path, monkeypatch):
    path = tmp_path / "extra.pdf"
    with fitz.open() as doc:
        for number in range(1, 8):
            page = doc.new_page(width=841.89, height=595.28)
            page.insert_text((40, 50), f"FLIGHT BRIEFING | PAGE {number} OF 6")
        doc.save(path)
    called = []
    original = concise_pdf_gate.check_concise_pdf

    def tracked(*args, **kwargs):
        called.append(args[0])
        return original(*args, **kwargs)

    monkeypatch.setattr(concise_pdf_gate, "check_concise_pdf", tracked)
    result = validate_combined_briefing_pdf(path)
    assert called == [path]
    assert not result["valid"]


@pytest.mark.parametrize("key", ["SQ910", "SQ882"])
def test_real_download_preserves_both_station_identity_pairs(key, tmp_path_factory):
    result = rendered(key, tmp_path_factory)
    flight = result["flight"]
    page_one = " ".join(result["pages"][0].split())
    for role in ("departure", "destination"):
        assert f"{flight[role + '_iata']} / {flight[role]}" in page_one
    # The actual release helper must accept that very physical download.
    case = {key: flight[key] for key in (
        "departure", "departure_iata", "destination", "destination_iata"
    )}
    audit = "FLIGHT BRIEFING " + " ".join(
        f"{flight[role + '_iata']} / {flight[role]}" for role in ("departure", "destination")
    )
    assert check_required_publication_markers(case, audit, "\n".join(result["pages"])) == []

"""An old pack re-created under the current rules loses nothing the OFP prints.

Second independent review, 19 Sep 2026. ``source_verified_flight`` re-read the
page-1 declarations from the held OFP but copied back only ``deferred_items``.
The new parser correctly moves SQ24's "ZFW RESTRICTED TO 161,229KGS" out of the
door-seal CDL and into ``page1_remarks`` - so for a pack stored before that
domain existed, the restriction left the declaration and arrived nowhere: the
re-created download printed no 161,229 at all, while a fresh analysis of the
same OFP did.

The fields a re-read of page 1 produces belong together. They are migrated as
one set, from one parse, only when that parse is unmistakably the held flight,
and what an old pack publishes from its OFP is then the same as a fresh one.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from app.odss.analysed_briefing_content import held_page1_remarks
from app.odss.combined_brief import (
    SOURCE_DERIVED_PUBLICATION_FIELDS,
    render_combined_briefing,
    source_verified_flight,
)
from app.odss.parser import extract_pages, parse_lido

CORPUS = Path(__file__).resolve().parents[2] / "private_cfp_corpus"
REVIEWED = json.loads((Path(__file__).parent / "fixtures/page1_source_declarations.json").read_text())


def _fresh(filename: str) -> dict:
    source = CORPUS / filename
    if not source.is_file():
        pytest.skip(f"private source {filename} not available")
    return parse_lido(extract_pages(source), filename)


def _as_stored_before_the_remarks_domain(fresh: dict) -> dict:
    """The shape release-30 and the first candidate stored: no remarks domain,
    and every remark printed after the last declaration folded into it."""
    old = copy.deepcopy(fresh)
    remarks = old.pop("page1_remarks")
    if old["deferred_items"] and remarks:
        last = old["deferred_items"][-1]
        first_line = min(
            (row["source_line"] for row in remarks), default=0,
        )
        trailing = [row["text"] for row in remarks if row["source_line"] >= first_line]
        last["company_remark"] = " ".join(filter(None, [last.get("company_remark"), *trailing]))
    return old


def test_the_fields_a_page_one_re_read_produces_are_named_in_one_place() -> None:
    assert set(SOURCE_DERIVED_PUBLICATION_FIELDS) >= {"deferred_items", "page1_remarks"}


def test_old_sq24_keeps_its_zfw_restriction_when_re_read_from_the_held_ofp() -> None:
    fresh = _fresh("lido-briefing_SQ_24_15Aug2026_SIN_JFK.pdf")
    stored = _as_stored_before_the_remarks_domain(fresh)
    assert "161,229" in json.dumps(stored["deferred_items"]), "the old parse held the limit inside the CDL"
    before = copy.deepcopy(stored)

    refreshed = source_verified_flight(stored, CORPUS / "lido-briefing_SQ_24_15Aug2026_SIN_JFK.pdf")

    assert stored == before, "the held analysis is never rewritten"
    assert "161,229" not in json.dumps(refreshed["deferred_items"])
    assert any("161,229" in row["text"] for row in held_page1_remarks(refreshed))
    for field in SOURCE_DERIVED_PUBLICATION_FIELDS:
        assert refreshed[field] == fresh[field], field


def test_the_re_read_moves_no_input_time_and_no_identity() -> None:
    fresh = _fresh("lido-briefing_SQ_24_15Aug2026_SIN_JFK.pdf")
    stored = _as_stored_before_the_remarks_domain(fresh)
    stored["actual_takeoff_utc"] = "2026-08-15T17:05:00+00:00"
    stored["timing_view"] = {"actual_takeoff_utc": "2026-08-15T17:05:00+00:00"}

    refreshed = source_verified_flight(stored, CORPUS / "lido-briefing_SQ_24_15Aug2026_SIN_JFK.pdf")

    changed = {key for key in set(stored) | set(refreshed) if stored.get(key) != refreshed.get(key)}
    assert changed <= set(SOURCE_DERIVED_PUBLICATION_FIELDS), changed


def test_a_held_file_that_is_not_this_flights_ofp_is_not_read_into_it() -> None:
    fresh = _fresh("lido-briefing_SQ_24_15Aug2026_SIN_JFK.pdf")
    stored = _as_stored_before_the_remarks_domain(fresh)
    other = CORPUS / "lido-briefing_SQ_882_10Sep2026_SIN_HKG.pdf"
    if not other.is_file():
        pytest.skip("second private source not available")

    assert source_verified_flight(stored, other) is stored


def test_without_the_held_ofp_the_restriction_is_still_published_not_lost(tmp_path) -> None:
    import fitz

    from app.odss.briefing import build_briefing_view

    stored = _as_stored_before_the_remarks_domain(_fresh("lido-briefing_SQ_24_15Aug2026_SIN_JFK.pdf"))
    stored["briefing"] = build_briefing_view(stored, [], [])
    path = tmp_path / "no-source.pdf"
    render_combined_briefing(stored, [], [], path, source_pdf_path=None)
    with fitz.open(path) as document:
        whole = " ".join(" ".join(page.get_text().split()) for page in document)

    assert "OFP remark: ZFW restricted to 161,229 kg." in whole


@pytest.mark.parametrize("filename", sorted(REVIEWED["flights"]))
def test_an_old_pack_and_a_fresh_one_publish_the_same_technical_page(filename: str, tmp_path) -> None:
    """Every reviewed OFP, not the two flights the first audit happened to use."""
    import fitz

    from app.odss.briefing import build_briefing_view

    fresh = _fresh(filename)
    stored = _as_stored_before_the_remarks_domain(fresh)
    source = CORPUS / filename
    pages = {}
    for name, flight in (("fresh", fresh), ("old", stored)):
        flight = copy.deepcopy(flight)
        flight["briefing"] = build_briefing_view(flight, [], [])
        path = tmp_path / f"{name}.pdf"
        render_combined_briefing(flight, [], [], path, source_pdf_path=source)
        with fitz.open(path) as document:
            pages[name] = [" ".join(page.get_text().split()) for page in document]

    assert pages["old"][2] == pages["fresh"][2]
    assert pages["old"][1] == pages["fresh"][1]

from __future__ import annotations

from app.odss.parser import _parse_alternates

_ROW = "WMKK/14L   LOCDME    446FT/1400M  0287  200 M002  0055 04680"
_SECOND_ROW = "WSSS/20R   ILS       200FT/0550M  0301  210 M003  0061 05120"


def test_reads_an_alternate_that_spills_past_the_first_page():
    """Long-haul plans push the alternate table onto a later CFP page."""
    alternates = _parse_alternates(["SUMMARY PAGE WITH NO TABLE", _ROW])

    assert len(alternates) == 1
    assert alternates[0]["airport"] == "WMKK"
    assert alternates[0]["runway"] == "14L"
    assert alternates[0]["approach"] == "LOCDME"
    assert alternates[0]["distance_nm"] == 287
    assert alternates[0]["time_minutes"] == 55
    assert alternates[0]["fuel_kg"] == 4680


def test_keeps_a_restated_row_once():
    """A summary page can repeat the same alternate row."""
    alternates = _parse_alternates([_ROW, "INTERVENING TEXT", _ROW])

    assert len(alternates) == 1
    assert alternates[0]["airport"] == "WMKK"


def test_keeps_distinct_alternates_in_document_order():
    alternates = _parse_alternates([_ROW, _SECOND_ROW])

    assert [item["airport"] for item in alternates] == ["WMKK", "WSSS"]


def test_returns_nothing_when_no_alternate_table_is_present():
    assert _parse_alternates(["ROUTE LOG ONLY", "NOTAM SECTION"]) == []

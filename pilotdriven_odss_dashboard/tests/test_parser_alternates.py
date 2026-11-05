from __future__ import annotations

from app.odss.parser import _parse_alternates

_ROW = "WMKK/14L   LOCDME    446FT/1400M  0287  200 M002  0055 04680"
# QA512: TIME is printed HHMM; this fixture printed an impossible "0061" (61 minutes is 0101), which the table-cell rules
# now hold as an invalid time cell. The row is otherwise unchanged.
_SECOND_ROW = "WSSS/20R   ILS       200FT/0550M  0301  210 M003  0101 05120"
_MULTIWORD_APPROACH_ROW = (
    "LIMC/17R RNAV GPS LN 606FT/2900M  0331  320 P006  0056 04989"
)
_TABLE_HEADER = "ALTN/RWY  APPROACH      MINIMA    DIST  FL  COMP  TIME  FUEL"


def test_reads_an_alternate_that_spills_past_the_first_page():
    """Long-haul plans push the alternate table onto a later CFP page.

    QA504-01 (15 Oct 2026): rows are read inside the table their header opens, so the spilled row follows its header
    across the page break (it used to be read wherever a row-shaped line stood in the CFP section).
    """
    alternates = _parse_alternates([f"SUMMARY PAGE\n{_TABLE_HEADER}\nPage 1 of 40", _ROW])

    assert len(alternates) == 1
    assert alternates[0]["airport"] == "WMKK"
    assert alternates[0]["runway"] == "14L"
    assert alternates[0]["approach"] == "LOCDME"
    assert alternates[0]["distance_nm"] == 287
    assert alternates[0]["time_minutes"] == 55
    assert alternates[0]["fuel_kg"] == 4680


def test_keeps_a_restated_row_once():
    """A summary page can repeat the same alternate row."""
    alternates = _parse_alternates([f"{_TABLE_HEADER}\n{_ROW}\nWMKK RTE: X", "INTERVENING TEXT",
                                    f"{_TABLE_HEADER}\n{_ROW}\nWMKK RTE: X"])

    assert len(alternates) == 1
    assert alternates[0]["airport"] == "WMKK"


def test_keeps_distinct_alternates_in_document_order():
    alternates = _parse_alternates([f"{_TABLE_HEADER}\n{_ROW}\n{_SECOND_ROW}"])

    assert [item["airport"] for item in alternates] == ["WMKK", "WSSS"]


def test_keeps_an_alternate_with_a_multiword_approach_name():
    """The SQ366 LIMC alternate uses the printed name ``RNAV GPS LN``."""
    alternates = _parse_alternates([f"{_TABLE_HEADER}\n{_MULTIWORD_APPROACH_ROW}"])

    assert len(alternates) == 1
    assert alternates[0] == {
        "airport": "LIMC",
        "runway": "17R",
        "approach": "RNAV GPS LN",
        "minima": "606FT/2900M",
        "distance_nm": 331,
        "time_minutes": 56,
        "fuel_kg": 4989,
    }


def test_table_header_cannot_join_the_next_row_as_a_fake_alternate():
    alternates = _parse_alternates([f"{_TABLE_HEADER}\n{_MULTIWORD_APPROACH_ROW}"])

    assert [item["airport"] for item in alternates] == ["LIMC"]


def test_returns_nothing_when_no_alternate_table_is_present():
    assert _parse_alternates(["ROUTE LOG ONLY", "NOTAM SECTION"]) == []


def test_a_row_shaped_line_outside_any_alternate_table_is_not_an_alternate():
    """QA504-01: a table is bounded by its header and its trailer; nothing outside it is read as a planned alternate."""
    assert _parse_alternates([f"{_ROW}\n{_TABLE_HEADER}\n{_SECOND_ROW}\nWSSS RTE: X\n{_MULTIWORD_APPROACH_ROW}"]) == [
        _parse_alternates([f"{_TABLE_HEADER}\n{_SECOND_ROW}"])[0]]

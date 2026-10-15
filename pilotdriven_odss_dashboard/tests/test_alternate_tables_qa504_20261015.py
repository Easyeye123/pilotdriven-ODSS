"""QA504-01: an alternate table is bounded by the LIDO layout and every line inside it is accounted.

Codex's QA of release 504 (15 Oct 2026, P2, confirmed live): in a labelled synthetic copy of genuine SQ279 SIN-ADL,
changing only "YMML/34" to "YMML/??" in both printings of the FLT PLANNING ALTN SUMMARY table made the briefing list
YSSY and YMAV, with both unread arrays empty: YMML vanished from the dashboard matrix and PDF page 4 with no review.
"YMML/" did the same, and a YMML fuel value wrapped onto its own line got a review for YMML but closed the table, so an
unreadable YMAV after it disappeared. Root cause: the accounting set the table position to None whenever a line did not
open as a readable row, and the row-start pattern required a readable runway; the page-1 fallback names only the first
alternate.

The repair (parser._read_alternate_tables, and cfp.readAlternateTables in the app by the same rules):
  - a table opens at its column header (the EDTO table at its section heading too) and closes at the LIDO layout's own
    end - the destination table's "<ICAO> RTE:" trailer, a section heading, another table header - never at a damaged
    row; page furniture inside is skipped;
  - every line inside is a row start (a readable identity), a continuation (a line without an identity that makes the
    row before it read whole - a wrapped row), or an unread line held with its raw text;
  - nothing is inferred: a row with a readable identity and an unreadable runway (or any other cell) is held unread
    with its airport and the reason, and no runway is assumed;
  - the two printings are reconciled by printed identity: a row read in one printing is read and its damaged copy is
    not a second review; printings that give one alternate different rows analyse neither; a line without a readable
    identity is held as printed; every alternate the OFP declares in a route line and that is neither read nor held is
    held too.

SYNTHETIC mutations are LABELLED and applied to text extracted from genuine originals; no PDF is changed. The exhaustive
mutation test applies every mutation to every row of every alternate table the 30 held originals print.
"""
from __future__ import annotations

import os
from pathlib import Path
import re
import tempfile

import fitz
import pytest

from app.odss import parser as lido_parser
from app.odss.briefing import build_briefing_view
from app.odss.combined_brief import render_combined_briefing
from app.odss.engines import analyse
from app.odss.parser import extract_pages, parse_lido

ROOT = Path(__file__).resolve().parents[1]
SQ279 = "lido-briefing_SQ_279_15Aug2026_SIN_ADL.pdf"
HEADER = "ALTN/RWY  APPROACH      MINIMA    DIST  FL  COMP  TIME  FUEL"
_ROW = lido_parser._ALTERNATE_ROW
_EDTO_ROW = lido_parser._EDTO_ALTERNATE_ROW


def _corpus() -> Path:
    configured = os.environ.get("PILOTDRIVEN_PRIVATE_CFP_CORPUS_DIR")
    corpus = Path(configured) if configured else ROOT.parent / "private_cfp_corpus"
    if not corpus.is_dir():
        if configured:
            raise FileNotFoundError(f"Configured PILOTDRIVEN_PRIVATE_CFP_CORPUS_DIR is missing: {corpus}")
        pytest.skip("the private CFP corpus is not available")
    return corpus


def _pages(name: str) -> list[str]:
    path = _corpus() / name
    if not path.is_file():
        pytest.skip(f"private source {name} not available")
    return extract_pages(path)


def _row(airport, runway, approach, minima, distance, time, fuel) -> dict:
    return {"airport": airport, "runway": runway, "approach": approach, "minima": minima,
            "distance_nm": distance, "time_minutes": time, "fuel_kg": fuel}


SQ279_ROWS = [
    _row("YSSY", "16R", "", "1479FT/7000M", 705, 102, 9186),
    _row("YMML", "34", "", "700FT/2500M", 396, 65, 5817),
    _row("YMAV", "18", "", "1295FT/7000M", 384, 63, 5673),
]


# ------------------------------------------------------------------------- Codex's five cases (LABELLED SYNTHETIC)
# The same text mutations as Codex's runner (output/pd-504-codex-qa-20261015/scripts/unread_probe.py), applied to both
# printings of genuine SQ279's table. On release 504 the three damaged cases lose an alternate without a review.

def _codex_case(name: str) -> list[str]:
    pages = _pages(SQ279)
    if name == "missing_runway":
        return [re.sub(r"(?m)^(\s*YMML)/34", r"\1/", page) for page in pages]
    if name == "bad_runway":
        return [re.sub(r"(?m)^(\s*YMML)/34", r"\1/??", page) for page in pages]
    if name == "split_row_then_unread":
        return [re.sub(r"(?m)^(\s*YMAV/18.*?)\s+\d{5}\s*$", r"\1",
                       re.sub(r"(?m)^(\s*YMML/34.*?)\s+(\d{5})\s*$", r"\1\n\2", page)) for page in pages]
    if name == "missing_fuel_control":
        return [re.sub(r"(?m)^(\s*YMAV/18.*?)\s+\d{5}\s*$", r"\1", page) for page in pages]
    return pages


def _accounted(flight: dict) -> tuple[list[str], list[tuple]]:
    return ([row["airport"] for row in flight["alternates"]],
            [(row["airport"], row["runway"], row["text"]) for row in flight["alternates_unread"]])


def test_qa504_codex_control_reads_all_three() -> None:
    flight = parse_lido(_codex_case("control"), SQ279)
    assert flight["alternates"] == SQ279_ROWS
    assert flight["alternates_unread"] == []


def test_qa504_codex_bad_runway_holds_ymml_as_unread_and_reads_the_rest() -> None:
    flight = parse_lido(_codex_case("bad_runway"), SQ279)
    assert flight["alternates"] == [SQ279_ROWS[0], SQ279_ROWS[2]]
    assert _accounted(flight)[1] == [("YMML", None, "YMML/?? 700FT/2500M 0396 330 P007 0105 05817")]
    unread = flight["alternates_unread"][0]
    assert (unread["table"], unread["source_page"], unread["position"]) == ("destination_alternates", 1, 1)
    assert 'runway is not readable ("??")' in unread["reason"] and "no runway is assumed" in unread["reason"]


def test_qa504_codex_missing_runway_holds_ymml_as_unread() -> None:
    flight = parse_lido(_codex_case("missing_runway"), SQ279)
    assert flight["alternates"] == [SQ279_ROWS[0], SQ279_ROWS[2]]
    assert _accounted(flight)[1] == [("YMML", None, "YMML/ 700FT/2500M 0396 330 P007 0105 05817")]


def test_qa504_codex_wrapped_fuel_reads_ymml_whole_and_never_ends_the_table() -> None:
    flight = parse_lido(_codex_case("split_row_then_unread"), SQ279)
    assert flight["alternates"] == SQ279_ROWS[:2], "YMML's own wrapped fuel completes its row"
    assert _accounted(flight)[1] == [("YMAV", "18", "YMAV/18 1295FT/7000M 0384 330 P007 0103")]


def test_qa504_codex_missing_fuel_control() -> None:
    flight = parse_lido(_codex_case("missing_fuel_control"), SQ279)
    assert _accounted(flight) == (["YSSY", "YMML"], [("YMAV", "18", "YMAV/18 1295FT/7000M 0384 330 P007 0103")])


def test_qa504_the_live_synthetic_form_names_ymml_from_its_route_line() -> None:
    """How Codex's live synthetic PDF extracts: the identity cell is overlaid, so the row prints without it and the
    overlaid "YMML/??" lands at the end of the page text (both printings). The row is held as printed and YMML, which
    the OFP's route line declares, is held by name."""
    pages = [re.sub(r"(?m)^(\s*)YMML/34", lambda m: m.group(1) + " " * 7, page) + ("\nYMML/??\n" if "YMML/34" in page else "")
             for page in _pages(SQ279)]
    flight = parse_lido(pages, SQ279)
    assert flight["alternates"] == [SQ279_ROWS[0], SQ279_ROWS[2]]
    assert _accounted(flight)[1] == [
        (None, None, "700FT/2500M 0396 330 P007 0105 05817"),
        ("YMML", None, "YMML RTE: YPAD DCT BENDO Y218 TYNDI DCT ALAXO DCT"),
    ]
    assert "declares this planned alternate in its route line" in flight["alternates_unread"][1]["reason"]


@pytest.mark.skipif(not os.environ.get("PILOTDRIVEN_QA504_SYNTHETIC_PDF"),
                    reason="PILOTDRIVEN_QA504_SYNTHETIC_PDF (Codex's labelled synthetic SQ279) is not set")
def test_qa504_codex_live_synthetic_pdf_holds_ymml() -> None:
    path = Path(os.environ["PILOTDRIVEN_QA504_SYNTHETIC_PDF"])
    flight = parse_lido(extract_pages(path), path.name)
    assert [row["airport"] for row in flight["alternates"]] == ["YSSY", "YMAV"]
    held = [(row["table"], row["airport"]) for row in flight["alternates_unread"]]
    assert ("destination_alternates", "YMML") in held
    assert ("destination_alternates", None) in held


def test_qa504_an_unread_alternate_reaches_the_findings_the_matrix_and_pdf_page_4() -> None:
    flight = parse_lido(_codex_case("bad_runway"), SQ279)
    findings, warnings = analyse(flight)
    review = [item for item in findings if item["title"] == "Planned alternate row not read"]
    assert len(review) == 1 and "YMML" in review[0]["summary"] and review[0]["severity"] == "warning"
    view = build_briefing_view(flight, findings, warnings, None, None, include_dashboard_only_panels=True)
    rows = view["alternate_assessment_rows"]
    assert [row["airport"] for row in rows] == ["YSSY", "YMML", "YMAV"], "the review keeps its printed place"
    assert rows[1]["assessment"]["row_not_read"] is True and "YMML/??" in rows[1]["assessment"]["text"]
    with tempfile.TemporaryDirectory() as scratch:
        pdf = Path(scratch) / "six-pages.pdf"
        render_combined_briefing(flight, findings, warnings, pdf, source_pdf_path=str(_corpus() / SQ279))
        with fitz.open(pdf) as document:
            printed = " ".join(" ".join(page.get_text().split()) for page in document)
    assert "YMML ALTERNATE · REVIEW - OFP p1" in printed and "YMML/??" in printed


def test_an_unidentified_unread_line_is_worded_without_an_airport() -> None:
    finding, warning = analyse.__globals__["_alternate_row_not_read_finding"]({
        "table": "destination_alternates", "airport": None, "runway": None, "text": "700FT/2500M 0396",
        "source_page": 8, "position": 1, "reason": "r"})
    assert "AN ALTERNATE" not in finding["summary"]
    assert finding["summary"].startswith('OFP p8 prints a line in its planned alternate table that was not read')
    assert finding["data"]["airport"] is None and warning == finding["summary"]


# --------------------------------------------------------------------------------------- the rules, LABELLED SYNTHETIC

def _table(*rows: str, trailer: str = "ZZZY RTE: WSSS DCT") -> str:
    return "\n".join([HEADER, *rows, "", "", trailer, "", "EXCESS FUEL REASON:"])


ZZZY = "ZZZY/27    CAT1DME   200FT/550M   0085   060 P003   0021 04014"
ZZZX = "ZZZX/09    VORDME    3000FT/5000M 0085  140 M003  0020 01802"


def test_a_stray_line_after_an_unreadable_row_is_held_and_the_table_reads_on() -> None:
    pages = [_table(ZZZY, "ZZZZ/09    VORDME    3000FT/5000M XYZ 0085  140 M003  0020 01802", "01802", ZZZX)]
    tables = lido_parser._read_alternate_tables(pages, 3)
    assert [row["airport"] for row in tables["alternates"]] == ["ZZZY", "ZZZX"]
    assert [(row["airport"], row["text"], row["position"]) for row in tables["unread"]] == [
        ("ZZZZ", "ZZZZ/09 VORDME 3000FT/5000M XYZ 0085 140 M003 0020 01802", 1), (None, "01802", 2)]
    assert "neither opens a row nor completes the row before it" in tables["unread"][1]["reason"]


def test_a_line_without_an_identity_after_a_whole_row_is_its_own_entry() -> None:
    """A complete row has no continuation: the next row printed without its identity cannot join it."""
    pages = [_table(ZZZY, "    /09    VORDME    3000FT/5000M 0085  140 M003  0020 01802", ZZZX)]
    tables = lido_parser._read_alternate_tables(pages, 1)
    assert [row["airport"] for row in tables["alternates"]] == ["ZZZY", "ZZZX"]
    assert [(row["airport"], row["text"]) for row in tables["unread"]] == [
        (None, "/09 VORDME 3000FT/5000M 0085 140 M003 0020 01802")]


def test_a_row_damaged_in_one_printing_is_read_from_the_other_without_a_second_review() -> None:
    damaged = ZZZY.replace("ZZZY/27", "ZZZY/??")
    pages = [_table(damaged, ZZZX), _table(ZZZY, ZZZX)]
    tables = lido_parser._read_alternate_tables(pages, 1)
    assert [row["airport"] for row in tables["alternates"]] == ["ZZZY", "ZZZX"], "printed order is kept"
    assert tables["unread"] == []


def test_printings_that_disagree_analyse_neither() -> None:
    pages = [_table(ZZZY, ZZZX), _table(ZZZY.replace("04014", "04015"), ZZZX)]
    tables = lido_parser._read_alternate_tables(pages, 1)
    assert [row["airport"] for row in tables["alternates"]] == ["ZZZX"]
    assert [row["airport"] for row in tables["unread"]] == ["ZZZY"]
    assert "printings give this alternate different rows" in tables["unread"][0]["reason"]


def test_a_declared_alternate_with_no_row_is_held_by_its_route_line() -> None:
    pages = [_table(ZZZY, trailer="ZZZY RTE: WSSS DCT\nZZZW RTE: WSSS DCT ABC")]
    tables = lido_parser._read_alternate_tables(pages, 5)
    assert [(row["airport"], row["text"], row["source_page"], row["position"]) for row in tables["unread"]] == [
        ("ZZZW", "ZZZW RTE: WSSS DCT ABC", 5, 1)]


def test_a_wrapped_edto_row_reads_whole_and_a_stray_word_is_never_an_approach() -> None:
    text = ("EDTO ENROUTE ALTN AIRPORTS:\nAPT      PERIOD CHKD       RWY           APCH             MINIMA\n"
            "ZZZZ     1900-2220          03       CAT1DME+VOR\n                                    492FT/2000M\n"
            "ZZZY     2155-0140          28                          400FT/2409M\n????\n"
            "Page 9 of 55\nSTATION WEATHER REPORTS!\n-----------------------\n")
    tables = lido_parser._read_alternate_tables([text], 9)
    assert [(m.group("airport"), m.group("approach"), m.group("minima")) for m in tables["edto_rows"]] == [
        ("ZZZZ", "CAT1DME+VOR", "492FT/2000M"), ("ZZZY", None, "400FT/2409M")]
    assert [(row["table"], row["airport"], row["text"]) for row in tables["unread"]] == [("edto_alternates", None, "????")]


def test_the_edto_table_is_bounded_by_its_heading_when_its_column_header_is_damaged() -> None:
    text = ("EDTO ENROUTE ALTN AIRPORTS:\nAPT      PERIOD CHKD       RWY      APCH       MINI??\n"
            "ZZZZ     1900-2220          03       CAT1DME        492FT/2000M\nSTATION WEATHER REPORTS!\n----------\n")
    tables = lido_parser._read_alternate_tables([text], 1)
    assert [m.group("airport") for m in tables["edto_rows"]] == ["ZZZZ"]
    assert [row["text"] for row in tables["unread"]] == ["APT PERIOD CHKD RWY APCH MINI??"]


def test_the_destination_table_opens_at_its_section_heading_when_its_column_header_is_missing() -> None:
    pages = ["FLT PLANNING ALTN SUMMARY:\n--------------------------\n\n" + ZZZY + "\n\nZZZY RTE: WSSS DCT\n"]
    tables = lido_parser._read_alternate_tables(pages, 1)
    assert [row["airport"] for row in tables["alternates"]] == ["ZZZY"] and tables["unread"] == []


@pytest.mark.parametrize("end", ["SID: WSSS/20C VMR9B", "EXCESS FUEL REASON:", "ARR ATIS ......................",
                                 "DISP BY: X"])
def test_a_table_without_its_trailer_closes_at_the_next_block(end: str) -> None:
    """LIDO always prints the route-line trailer; without it the next block's heading, labelled field or dot-leader form
    line still bounds the table, and the EDTO table closes at its underlined STATION WEATHER REPORTS heading, so nothing
    after them is taken for a table line. (QA508-01: the package's mixed-case text is no longer an end; see
    tests/test_alternate_tables_qa508_20261015.py.)"""
    pages = [f"{HEADER}\n{ZZZY}\n{end}\nRTOW(PERF) 285609 FLAPS 2\nEDTO ENROUTE ALTN AIRPORTS:\n"
             "ZZZZ     1900-2220          03       CAT1DME        492FT/2000M\nSTATION WEATHER REPORTS\n"
             "-----------------------\nSA 121320 04009KT CAVOK=\n"]
    tables = lido_parser._read_alternate_tables(pages, 1)
    assert [row["airport"] for row in tables["alternates"]] == ["ZZZY"]
    assert [m.group("airport") for m in tables["edto_rows"]] == ["ZZZZ"]
    assert tables["unread"] == []


# The exhaustive mutation test over the 30 held originals is extended with QA508-01's damage classes (case changes,
# form-leader dots, mixed junk, on every cell) in tests/test_alternate_tables_qa508_20261015.py.

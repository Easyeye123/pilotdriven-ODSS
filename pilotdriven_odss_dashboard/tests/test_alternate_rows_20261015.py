"""Every planned alternate the OFP prints is read; a blank column stays blank; a row not read is a stated review.

Found by the QA500-03 identity census (15 Oct 2026): ``parser._parse_alternates`` required a word in the APPROACH
column and a word in the MINIMA column, and skipped any row that did not fit without saying so. The LIDO "FLT
PLANNING ALTN SUMMARY" table prints those columns blank. Across the 30 held originals 104 planned alternates are
printed and 88 were read: 16 alternates in 9 OFPs had no NOTAM, weather, card or PDF analysis, and genuine SQ279
SIN-ADL had no alternates at all. The forms the corpus prints:

    EGKK/26L    CAT1DME   200FT/550M   0085   060 P003   0021 04014    approach and minima      (SQ322)
    YSSY/16R               1479FT/7000M 0705   350 P013   0142 09186    APPROACH blank           (SQ279, SQ297, SQ437, SQ481)
    RJBB/06R                   0M       0519   330 P004   0122 07729    APPROACH blank, "0M"     (SQ23, SQ297, SQ326, SQ437, SQ438, SQ606)
    WIDD/22                           0085  140 M003  0020 01802       APPROACH and MINIMA blank (SQ303)

The table also continues across a page break (SQ437: the package footer and running header sit between its third and
fourth rows). The EDTO "EDTO ENROUTE ALTN AIRPORTS:" table prints APCH blank too (SQ34 PASY); its reader split the
last word off as the minima whatever it was, so an approach printed with a blank MINIMA would have become the minima.

The repair reads APPROACH and MINIMA as optional columns by word shape (a minima word is digits with FT and/or M; an
approach word holds a letter and is never minima-shaped), keeps a blank column blank, and accounts for every row
printed inside an alternate table: a row the grammar cannot read is held in ``flight["alternates_unread"]`` with its
text, page and reason, reaches the findings as a warning, and stands in the alternate matrix as a review.

The corpus test reads the tables with an independent oracle: poppler's ``pdftotext -bbox`` words (ODSS reads with
PyMuPDF), split into APPROACH and MINIMA by page geometry (the nearer header-word centre), never by word shape.
"""
from __future__ import annotations

from datetime import datetime, timezone
import html
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

import fitz
import pytest

from app.odss.briefing import build_briefing_view
from app.odss.combined_brief import render_combined_briefing
from app.odss.engines import analyse
from app.odss import parser as lido_parser
from app.odss.parser import _parse_alternates, _parse_edto_airports, extract_pages, parse_lido

ROOT = Path(__file__).resolve().parents[1]
SQ279 = "lido-briefing_SQ_279_15Aug2026_SIN_ADL.pdf"
SQ303 = "SQ30316072026BRU 81.pdf"
SQ322 = "lido-briefing_SQ_322_16Aug2026_SIN_LHR.pdf"
SQ437 = "SQ43708102026MLE.pdf"
SQ606 = "SQ60606092026SIN.pdf"
HEADER = "ALTN/RWY  APPROACH      MINIMA    DIST  FL  COMP  TIME  FUEL"


def _corpus() -> Path:
    configured = os.environ.get("PILOTDRIVEN_PRIVATE_CFP_CORPUS_DIR")
    corpus = Path(configured) if configured else ROOT.parent / "private_cfp_corpus"
    if not corpus.is_dir():
        if configured:
            raise FileNotFoundError(f"Configured PILOTDRIVEN_PRIVATE_CFP_CORPUS_DIR is missing: {corpus}")
        pytest.skip("the private CFP corpus is not available")
    return corpus


def _genuine(name: str) -> tuple[list[str], dict]:
    path = _corpus() / name
    if not path.is_file():
        pytest.skip(f"private source {name} not available")
    pages = extract_pages(path)
    return pages, parse_lido(pages, name)


def _row(airport, runway, approach, minima, distance, time, fuel) -> dict:
    return {"airport": airport, "runway": runway, "approach": approach, "minima": minima,
            "distance_nm": distance, "time_minutes": time, "fuel_kg": fuel}


# ----------------------------------------------------------------------------------------------- labelled synthetic
# SYNTHETIC rows, labelled: the airport ZZZZ / ZZZY / ZZZX is not a real station. The genuine forms are quoted from
# the originals named beside them.

@pytest.mark.parametrize(("line", "expected"), [
    pytest.param("EGKK/26L    CAT1DME   200FT/550M   0085   060 P003   0021 04014",
                 _row("EGKK", "26L", "CAT1DME", "200FT/550M", 85, 21, 4014), id="genuine-SQ322-both-columns"),
    pytest.param("LIMC/17R RNAV GPS LN 606FT/2900M  0331  320 P006  0056 04989",
                 _row("LIMC", "17R", "RNAV GPS LN", "606FT/2900M", 331, 56, 4989), id="genuine-SQ366-multiword"),
    pytest.param("EHAM/27     CAT1DME        550M       0157   200 M002   0032 03003",
                 _row("EHAM", "27", "CAT1DME", "550M", 157, 32, 3003), id="genuine-SQ304-metres-only"),
    pytest.param("YSSY/16R               1479FT/7000M 0705    350 P013   0142 09186",
                 _row("YSSY", "16R", "", "1479FT/7000M", 705, 102, 9186), id="genuine-SQ279-approach-blank"),
    pytest.param("RJBB/06R                   0M       0519   330 P004   0122 07729",
                 _row("RJBB", "06R", "", "0M", 519, 82, 7729), id="genuine-SQ606-approach-blank-0M"),
    pytest.param("WIDD/22                           0085  140 M003  0020 01802",
                 _row("WIDD", "22", "", "", 85, 20, 1802), id="genuine-SQ303-approach-and-minima-blank"),
    pytest.param("ZZZZ/09    VORDME                 0085  140 M003  0020 01802",
                 _row("ZZZZ", "09", "VORDME", "", 85, 20, 1802), id="synthetic-minima-blank"),
    pytest.param("ZZZZ/09 RNAV GPS LN               0085  140 M003  0020 01802",
                 _row("ZZZZ", "09", "RNAV GPS LN", "", 85, 20, 1802), id="synthetic-multiword-minima-blank"),
    pytest.param("ZZZZ/09    CAT1DME   200FT        0085  140 M003  0020 01802",
                 _row("ZZZZ", "09", "CAT1DME", "200FT", 85, 20, 1802), id="synthetic-feet-only"),
])
def test_an_alternate_row_reads_each_column_it_prints_and_keeps_a_blank_one_blank(line: str, expected: dict) -> None:
    pages = [f"{HEADER}\n{line}\n\n\nZZZZ RTE: WSSS DCT\n"]
    assert _parse_alternates(pages) == [expected]
    assert lido_parser._alternate_rows_not_read(pages, 1) == []


@pytest.mark.parametrize(("line", "why"), [
    pytest.param("ZZZZ/09    VORDME    3000FT/5000M 0085  140 M003  0020", "FUEL wrapped onto the next line",
                 id="synthetic-wrapped"),
    pytest.param("ZZZZ/09    VORDME    3000FT/5000M XYZ 0085  140 M003  0020 01802", "a word after the minima",
                 id="synthetic-word-after-minima"),
    pytest.param("ZZZZ/09    1234      0085  140 M003  0020 01802", "a bare number is never an approach",
                 id="synthetic-number-as-approach"),
    pytest.param("ZZZZ/09    VORDME    3000FT/5000M 85  140 M003  0020 01802", "DIST not four digits",
                 id="synthetic-short-distance"),
    pytest.param("ZZZZ/09", "nothing but the airport", id="synthetic-bare-airport"),
])
def test_a_row_inside_the_table_the_grammar_cannot_read_is_held_as_a_stated_review(line: str, why: str) -> None:
    pages = [f"{HEADER}\nZZZY/27    CAT1DME   200FT/550M   0085   060 P003   0021 04014\n{line}\n01802\n\n"
             "ZZZY RTE: WSSS DCT\nZZZZ RTE: WSSS DCT\n"]
    assert [row["airport"] for row in _parse_alternates(pages)] == ["ZZZY"], why
    unread = lido_parser._alternate_rows_not_read(pages, 7)
    assert [(row["airport"], row["runway"], row["text"], row["source_page"], row["table"], row["position"])
            for row in unread] == [("ZZZZ", "09", " ".join(line.split()), 7, "destination_alternates", 1)], why
    assert "not read" in unread[0]["reason"]


def test_a_table_split_by_a_page_break_is_read_whole() -> None:
    """The genuine SQ437 form: the footer and running header sit between the third and fourth rows."""
    pages = [
        f"{HEADER}\nWMKK/14L   LOCDME    446FT/1400M  0287  200 M003  0055 04902\n"
        "WSAP/20              3000FT/5000M 0090  110 M004  0022 01957\n"
        "WMKJ/16              3000FT/5000M 0085  090 M002  0021 01820\n"
        "SIA 437/08Oct26/VRMM-WSSS Reg:9VSHQ OFP:3/0/1\nPage 1 of 65\n",
        "\n \nWIDD/22                   0M      0085  100 P003  0021 01840\n \n \nWMKK RTE: WSSS MASBO A457 GUPTA\n",
    ]
    assert [row["airport"] for row in _parse_alternates(pages)] == ["WMKK", "WSAP", "WMKJ", "WIDD"]
    assert lido_parser._alternate_rows_not_read(pages, 1) == []


def test_an_unreadable_row_after_a_page_break_is_still_accounted() -> None:
    pages = [f"{HEADER}\nWMKK/14L   LOCDME    446FT/1400M  0287  200 M003  0055 04902\nPage 1 of 65\n",
             "PAGE   2 OF 10 SIA437 MLE/SIN 08OCT26\n\nZZZZ/22   ??   0085  100 P003  0021 01840\n\nWMKK RTE: X\n"]
    assert [(row["airport"], row["source_page"], row["position"]) for row in lido_parser._alternate_rows_not_read(pages, 3)] == [
        ("ZZZZ", 4, 1)]


def test_the_route_string_and_rows_outside_the_table_are_not_alternate_rows() -> None:
    """Page 1 starts the route string with the departure airport and runway; it is not an alternate row."""
    pages = [
        "WSSS/20C ANITO DCT 0400S10700E DCT IGUNA DCT 0800S10900E DCT SAPDA\nDCT YPAD/05\n"
        f"{HEADER}\nYSSY/16R               1479FT/7000M 0705    350 P013   0142 09186\n\n"
        "YSSY RTE: YPAD DCT BENDO\n"
        "STAR: YPAD/05 ALAXO1\n"
    ]
    assert [row["airport"] for row in _parse_alternates(pages)] == ["YSSY"]
    assert lido_parser._alternate_rows_not_read(pages, 1) == []


def test_a_restated_unreadable_row_is_held_once() -> None:
    table = f"{HEADER}\nZZZZ/09    VORDME    3000FT/5000M 0085  140 M003  0020\n\nZZZZ RTE: X\n"
    assert len(lido_parser._alternate_rows_not_read([table, "INTERVENING", table], 1)) == 1


EDTO_HEADER = "EDTO ENROUTE ALTN AIRPORTS:\nAPT      PERIOD CHKD        RWY               APCH               MINIMA"
DEPARTURE = datetime(2026, 8, 15, 15, 25, tzinfo=timezone.utc)
ARRIVAL = datetime(2026, 8, 16, 5, 9, tzinfo=timezone.utc)


@pytest.mark.parametrize(("line", "approach", "minima"), [
    pytest.param("PGUM     1737-2046          24R         CIRC VORDME@06L       1035FT/4316M", "CIRC VORDME@06L",
                 "1035FT/4316M", id="genuine-SQ34-both"),
    pytest.param("PASY     2155-0140           28                                400FT/2409M", "", "400FT/2409M",
                 id="genuine-SQ34-apch-blank"),
    pytest.param("ZZZZ     2155-0140           28            CAT1DME", "CAT1DME", "", id="synthetic-minima-blank"),
    pytest.param("ZZZZ     2155-0140           28        RNAV GPS LNAV/VNAV", "RNAV GPS LNAV/VNAV", "",
                 id="synthetic-multiword-minima-blank"),
    pytest.param("ZZZZ     2155-0140           28", "", "", id="synthetic-both-blank"),
])
def test_an_edto_alternate_row_keeps_a_blank_column_blank(line: str, approach: str, minima: str) -> None:
    text = f"{EDTO_HEADER}\n{line}\n\n"
    rows = _parse_edto_airports(text, DEPARTURE, ARRIVAL)
    assert [(row["airport"], row["approach"], row["minima"]) for row in rows] == [(line[:4], approach, minima)]
    assert lido_parser._alternate_rows_not_read([text], 1) == []


def test_an_edto_row_the_grammar_cannot_read_is_held_as_a_stated_review() -> None:
    text = (f"{EDTO_HEADER}\nWIMM     1940-2257           05            CAT1DME           407FT/1600M\n"
            "ZZZZ     19:40-2257          05            CAT1DME           407FT/1600M\n\nSTATION WEATHER REPORTS\n")
    assert [row["airport"] for row in _parse_edto_airports(text, DEPARTURE, ARRIVAL)] == ["WIMM"]
    unread = lido_parser._alternate_rows_not_read([text], 9)
    assert [(row["airport"], row["table"], row["source_page"], row["position"]) for row in unread] == [
        ("ZZZZ", "edto_alternates", 9, 1)]


# --------------------------------------------------------------------------------------------------------- genuine

def test_genuine_sq279_reads_all_three_planned_alternates_with_the_approach_column_blank() -> None:
    """SQ279 SIN-ADL 15 Aug, CFP p1 (and restated in the full CFP): every alternate prints APPROACH blank."""
    _, flight = _genuine(SQ279)
    assert flight["alternates"] == [
        _row("YSSY", "16R", "", "1479FT/7000M", 705, 102, 9186),
        _row("YMML", "34", "", "700FT/2500M", 396, 65, 5817),
        _row("YMAV", "18", "", "1295FT/7000M", 384, 63, 5673),
    ]
    assert flight["alternates_unread"] == []
    findings, warnings = analyse(flight)
    view = build_briefing_view(flight, findings, warnings, None, None, include_dashboard_only_panels=True)
    rows = view["alternate_assessment_rows"]
    assert [(row["airport"], row["role"], row["approach"], row["minima"]) for row in rows] == [
        ("YSSY", "preferred", "", "1479FT/7000M"), ("YMML", "alternate", "", "700FT/2500M"),
        ("YMAV", "alternate", "", "1295FT/7000M")]
    held = {record["location"] for record in flight["notams"]}
    assert {"YSSY", "YMML", "YMAV"} <= held, "each planned alternate's printed NOTAM block is analysed"
    panels = {panel["icao"] for panel in view["airport_operational_panels"]}
    assert {"YSSY", "YMML", "YMAV"} <= panels


@pytest.mark.parametrize(("name", "expected"), [
    pytest.param(SQ303, _row("WIDD", "22", "", "", 85, 20, 1802), id="SQ303-WIDD-both-blank"),
    pytest.param(SQ606, _row("RJFF", "34R", "", "0M", 388, 67, 6327), id="SQ606-RJFF-0M"),
    pytest.param(SQ437, _row("WIDD", "22", "", "0M", 85, 21, 1840), id="SQ437-WIDD-after-page-break"),
])
def test_genuine_rows_with_blank_columns_are_read_as_printed(name: str, expected: dict) -> None:
    _, flight = _genuine(name)
    assert expected in flight["alternates"]
    assert flight["alternates_unread"] == []


def test_an_unreadable_row_in_a_genuine_ofp_reaches_the_findings_and_the_alternate_matrix_as_a_review() -> None:
    """LABELLED SYNTHETIC injection into genuine SQ322: the EGSS row loses its FUEL column in both printings."""
    pages, _ = _genuine(SQ322)
    injected = [re.sub(r"(?m)^(\s*EGSS/22\s.*?)\s+\d{5}\s*$", r"\1", page) for page in pages]
    assert injected != pages
    flight = parse_lido(injected, SQ322)
    assert [row["airport"] for row in flight["alternates"]] == ["EGKK", "EGCC", "LFPG"]
    assert [(row["airport"], row["runway"], row["position"], row["table"]) for row in flight["alternates_unread"]] == [
        ("EGSS", "22", 1, "destination_alternates")]
    unread = flight["alternates_unread"][0]
    assert unread["text"].startswith("EGSS/22") and unread["source_page"] >= 1
    findings, warnings = analyse(flight)
    review = [item for item in findings if item["title"] == "Planned alternate row not read"]
    assert len(review) == 1 and review[0]["severity"] == "warning" and "EGSS" in review[0]["summary"]
    assert any("EGSS" in warning for warning in warnings)
    view = build_briefing_view(flight, findings, warnings, None, None, include_dashboard_only_panels=True)
    rows = view["alternate_assessment_rows"]
    assert [row["airport"] for row in rows] == ["EGKK", "EGSS", "EGCC", "LFPG"], "the review keeps its printed place"
    egss = rows[1]
    assert egss["assessment"]["status"] == "review_required"
    assert egss["approach"] is None and egss["minima"] is None and egss["fuel_kg"] is None
    assert "not read" in egss["assessment"]["text"] and "EGSS/22" in egss["assessment"]["text"]
    with tempfile.TemporaryDirectory() as scratch:
        pdf = Path(scratch) / "six-pages.pdf"
        render_combined_briefing(flight, findings, warnings, pdf, source_pdf_path=str(_corpus() / SQ322))
        with fitz.open(pdf) as document:
            printed = " ".join(" ".join(page.get_text().split()) for page in document)
    assert "EGSS ALTERNATE · REVIEW - OFP p" in printed and "its row was not read" in printed, (
        "the pilot's PDF states the review")


def test_an_unreadable_edto_row_in_a_genuine_ofp_is_an_edto_review() -> None:
    """LABELLED SYNTHETIC injection into genuine SQ34: the PASY row's period is printed with a colon."""
    name = "lido-briefing_SQ_34_15Aug2026_SIN_SFO.pdf"
    pages, flight = _genuine(name)
    assert "PASY" in [row["airport"] for row in flight["edto"]["airports"]]
    injected = [re.sub(r"(?m)^(\s*PASY\s+)2155-0140", r"\g<1>21:55-0140", page) for page in pages]
    assert injected != pages
    flight = parse_lido(injected, name)
    assert "PASY" not in [row["airport"] for row in flight["edto"]["airports"]]
    assert [(row["airport"], row["table"]) for row in flight["alternates_unread"]] == [("PASY", "edto_alternates")]
    findings, warnings = analyse(flight)
    review = [item for item in findings if item["title"] == "EDTO alternate row not read"]
    assert len(review) == 1 and review[0]["engine"] == "edto" and review[0]["severity"] == "warning"
    assert "PASY" in review[0]["summary"] and any("PASY" in warning for warning in warnings)


# -------------------------------------------------------------------------------- corpus, against an independent oracle

_WORD = re.compile(r'<word xMin="([0-9.]+)" yMin="([0-9.]+)" xMax="([0-9.]+)" yMax="[0-9.]+">(.*?)</word>')
_ORACLE_ROW = re.compile(r"^([A-Z]{4})/([0-9]{2}[LCR]?)$")
_ORACLE_FURNITURE = re.compile(r"^(?:Page \d+ of \d+|SIA ?\d+/\d{2}[A-Za-z]{3}\d{2}/\S+.*|PAGE \d+ OF \d+ .*)$")


def _poppler_lines(pdf: Path) -> list[tuple[int, list[tuple[float, float, str]]]]:
    out = subprocess.run(["pdftotext", "-bbox", str(pdf), "-"], check=True, capture_output=True, text=True).stdout
    lines = []
    for number, page in enumerate(out.split("<page ")[1:], start=1):
        rows: dict[float, list] = {}
        for x0, y0, x1, word in _WORD.findall(page):
            rows.setdefault(round(float(y0), 1), []).append((float(x0), float(x1), html.unescape(word)))
        lines.extend((number, sorted(rows[y])) for y in sorted(rows))
    return lines


def _oracle_tables(lines, header: list[str], approach_word: str, minima_word: str, row_start, middle):
    """Rows under each printed header, split into APPROACH / MINIMA by the nearer header-word centre."""
    tables = []
    for index, (_, words) in enumerate(lines):
        if [w for _, _, w in words[:len(header)]] != header:
            continue
        centre = {w: (x0 + x1) / 2 for x0, x1, w in words}
        rows = []
        for number, row in lines[index + 1:]:
            if _ORACLE_FURNITURE.match(" ".join(w for _, _, w in row)):
                continue
            if not row_start(row):
                break
            nearer_minima = [abs((x0 + x1) / 2 - centre[minima_word]) < abs((x0 + x1) / 2 - centre[approach_word])
                             for x0, x1, _ in middle(row)]
            rows.append({
                "page": number,
                "words": [w for _, _, w in row],
                "approach": " ".join(w for (_, _, w), is_minima in zip(middle(row), nearer_minima) if not is_minima),
                "minima": " ".join(w for (_, _, w), is_minima in zip(middle(row), nearer_minima) if is_minima),
            })
        tables.append(rows)
    return tables


def _alternate_oracle(lines) -> list[list[dict]]:
    tables = _oracle_tables(lines, ["ALTN/RWY", "APPROACH", "MINIMA"], "APPROACH", "MINIMA",
                            lambda row: bool(_ORACLE_ROW.match(row[0][2])), lambda row: row[1:-5])
    for rows in tables:
        for row in rows:
            airport, runway = row["words"][0].split("/")
            dist, _, _, time, fuel = row["words"][-5:]
            row.update(airport=airport, runway=runway, distance_nm=int(dist),
                       time_minutes=int(time[:2]) * 60 + int(time[2:]), fuel_kg=int(fuel))
    return tables


def _edto_oracle(lines) -> list[list[dict]]:
    tables = _oracle_tables(lines, ["APT", "PERIOD", "CHKD", "RWY", "APCH", "MINIMA"], "APCH", "MINIMA",
                            lambda row: len(row) >= 3 and bool(re.match(r"^[A-Z]{4}$", row[0][2]))
                            and bool(re.match(r"^\d{4}-\d{4}$", row[1][2])), lambda row: row[3:])
    for rows in tables:
        for row in rows:
            row.update(airport=row["words"][0], runway=row["words"][2])
    return tables


def test_every_alternate_the_corpus_prints_is_read_column_for_column() -> None:
    if not shutil.which("pdftotext"):
        pytest.skip("poppler pdftotext (the independent oracle) is not installed")
    pdfs = sorted(_corpus().glob("*.pdf"))
    problems: list[str] = []
    printed_total = edto_total = 0
    for pdf in pdfs:
        lines = _poppler_lines(pdf)
        pages = extract_pages(pdf)
        flight = parse_lido(pages, pdf.name)
        if "alternates_unread" not in flight:
            problems.append(f"{pdf.name}: the rows printed in its alternate tables are not accounted")
        elif flight["alternates_unread"]:
            problems.append(f"{pdf.name}: rows held unread {flight['alternates_unread']}")
        printings = _alternate_oracle(lines)
        if not printings or not printings[0]:
            problems.append(f"{pdf.name}: the oracle found no alternate table")
            continue
        fields = ("airport", "runway", "approach", "minima", "distance_nm", "time_minutes", "fuel_kg")
        first = [{key: row[key] for key in fields} for row in printings[0]]
        for again in printings[1:]:
            if [{key: row[key] for key in fields} for row in again] != first:
                problems.append(f"{pdf.name}: the two printings of the alternate table disagree")
        printed_total += len(first)
        parsed = [{key: row[key] for key in fields} for row in flight["alternates"]]
        if parsed != first:
            problems.append(f"{pdf.name}: parsed {parsed} != printed {first}")
        page_one = ((flight.get("fuel_summary") or {}).get("alternate") or {}).get("icao")
        if page_one != first[0]["airport"]:
            problems.append(f"{pdf.name}: page 1 names {page_one}, the table starts with {first[0]['airport']}")
        edto_printed = [row for rows in _edto_oracle(lines) for row in rows]
        edto_total += len(edto_printed)
        edto_parsed = [(row["airport"], row["runway"], " ".join(row["approach"].split()), row["minima"])
                       for row in flight["edto"]["airports"]]
        edto_expected = list(dict.fromkeys((row["airport"], row["runway"], row["approach"], row["minima"])
                                           for row in edto_printed))
        if edto_parsed != edto_expected:
            problems.append(f"{pdf.name}: EDTO parsed {edto_parsed} != printed {edto_expected}")
    print(f"{len(pdfs)} OFPs: {printed_total} planned alternates and {edto_total} EDTO alternate rows compared")
    assert printed_total > 0
    assert not problems, f"{len(problems)} OFP(s) not read as printed:\n" + "\n".join(problems)

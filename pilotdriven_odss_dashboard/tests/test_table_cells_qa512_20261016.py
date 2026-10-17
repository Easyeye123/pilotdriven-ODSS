"""QA512: a table cell is promoted only when it is semantically valid, and no single cell can abort an analysis.

Codex's QA of release 512 (16 Oct 2026, two P1s, confirmed live):
  QA512-01 - a labelled SQ279 copy whose YPDN EDTO period "1946-2327" is printed "1960-2327" failed the whole analysis
             (CFP_FORMAT_UNSUPPORTED_OR_INVALID, Download PDF disabled): the EDTO row grammar accepts any four digits, the
             row was promoted, and _edto_period -> utc_on_date raised "minute must be in 0..59, not 60" outside any row
             isolation. Nine invalid start/end clocks do it.
  QA512-02 - "YMML/99" (destination table) and YPDN runway "99" (EDTO table) were published as plans on the dashboard
             and PDF pages 4 and 5: the runway cell was checked for shape ("\\d{2}[LCR]?") only. 00, 37, 99, 00L do it.

Root cause: the table readers validated a cell's shape, never its meaning, and a row's conversion ran outside any
row-level isolation. The repair:
  - every numeric or coded cell a table reader promotes has a rule in ONE place per runtime (app/odss/table_cell_rules.json
    via table_cells.py; byte-identical to the app's table-cell-rules.json via table-cells.mjs), and both runtimes run the
    same vectors (tests/fixtures/table-cell-vectors.json). Runway numbering is FAA AIM 2-3-3's range (01-36, L/C/R) -
    range validation, never an airport's runway inventory;
  - a row with an invalid cell keeps its airport and its printed row, is held unread naming the invalid field, and
    publishes no value; nothing is chosen or inferred;
  - any exception while reading one row (destination conversion, EDTO period, fuel-enroute station row) holds that row;
  - Codex's nine exploratory observations: a heading-shaped line wrapped out of a row no longer ends the table when the
    table goes on after it (the EDTO table's own trailer, STATION WEATHER REPORTS, still always ends it); a body-less
    fragment after an EDTO row that stops before its MINIMA belongs to that row, which is held; EDTO printings that give
    one airport different rows analyse neither.

SYNTHETIC mutations are LABELLED and applied to text extracted from genuine originals; no PDF is changed.
"""
from __future__ import annotations

import copy
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import tempfile

import fitz
import pytest

from app.odss import enrichment
from app.odss import parser as lido_parser
from app.odss import table_cells
from app.odss.briefing import build_briefing_view
from app.odss.combined_brief import render_combined_briefing
from app.odss.engines import analyse
from app.odss.parser import extract_pages, parse_lido

ROOT = Path(__file__).resolve().parents[1]
SQ279 = "lido-briefing_SQ_279_15Aug2026_SIN_ADL.pdf"
SQ606 = "SQ60606092026SIN.pdf"
RULES = ROOT / "app" / "odss" / "table_cell_rules.json"
VECTORS = ROOT / "tests" / "fixtures" / "table-cell-vectors.json"
# The shared files are byte-identical in the app (table-cell-rules.json, tests/fixtures/table-cell-vectors.json) and
# pinned by the same digests in its suite.
RULES_SHA256 = "265688879a049778e1bef0c1fc4552e9ed8c9d45e9abbd7c9ebcb0f43a573c57"
VECTORS_SHA256 = "884dbbe4cd64e71a0221a032a10bd831272e39f864b9f3ad02c7ba397d0bb280"


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


def _mutated(opening: str, old: str, new: str, name: str = SQ279) -> list[str]:
    """Genuine ``name`` with ``old`` (a regex) replaced by ``new`` once on every printed line that opens with ``opening``."""
    return [
        "\n".join(re.sub(old, new, line, count=1) if re.match(opening, line) else line for line in page.split("\n"))
        for page in _pages(name)
    ]


def _held(flight: dict, table: str) -> list[tuple]:
    return [(row["airport"], row["text"], row.get("invalid_fields")) for row in flight["alternates_unread"]
            if row["table"] == table]


# ------------------------------------------------------------------------------------------------- the shared rules
def test_the_rules_and_vectors_are_the_pinned_shared_files() -> None:
    assert sha256(RULES.read_bytes()).hexdigest() == RULES_SHA256
    assert sha256(VECTORS.read_bytes()).hexdigest() == VECTORS_SHA256
    app = os.environ.get("PILOTDRIVEN_APP_ROOT")
    if app and Path(app, "table-cell-rules.json").is_file():
        assert Path(app, "table-cell-rules.json").read_bytes() == RULES.read_bytes()
        assert Path(app, "tests", "fixtures", "table-cell-vectors.json").read_bytes() == VECTORS.read_bytes()


def test_every_shared_vector_is_judged_as_stated() -> None:
    vectors = json.loads(VECTORS.read_text())["vectors"]
    assert len(vectors) == 151  # QA516: + 25 non-ASCII cells, all invalid
    wrong = [vector for vector in vectors if (table_cells.cell_problem(vector["kind"], vector["value"]) is None)
             != vector["valid"]]
    assert wrong == []
    assert {vector["kind"] for vector in vectors} == set(table_cells.CELLS)


def test_runway_numbering_is_the_faa_aim_range_not_an_inventory() -> None:
    assert "FAA AIM 2-3-3" in table_cells.CELLS["runway"]["rule"]
    for number in range(1, 37):
        for suffix in ("", "L", "C", "R"):
            assert table_cells.cell_problem("runway", f"{number:02d}{suffix}") is None
    for value in ("00", "37", "99", "00L", "37R", "36X", "4", "036"):
        assert table_cells.cell_problem("runway", value) is not None, value


def test_a_clock_has_hours_0_to_23_and_minutes_0_to_59_and_no_2400() -> None:
    assert table_cells.cell_problem("clock", "0000") is None and table_cells.cell_problem("clock", "2359") is None
    for value in ("2400", "2460", "2360", "2500", "9999", "2401", "1960", "0060"):
        assert table_cells.cell_problem("clock", value) is not None, value


# ----------------------------------------------------------------------- Codex's failing cases (LABELLED SYNTHETIC)
# The same text mutations as Codex's runner (output/pd-512-codex-qa-20261016/scripts/adversarial_tables.py); RED on 512.
CLOCKS = [("start", "2460"), ("start", "2500"), ("start", "2360"), ("start", "9999"), ("start", "2401"),
          ("start", "1960"), ("end", "2360"), ("end", "2500"), ("end", "9999")]


@pytest.mark.parametrize(("side", "value"), CLOCKS)
def test_qa512_01_an_invalid_edto_clock_holds_ypdn_and_the_analysis_completes(side: str, value: str) -> None:
    old = "1946" if side == "start" else "2327"
    flight = parse_lido(_mutated(r"^\s*YPDN\s+1946-", old, value), SQ279)
    assert [row["airport"] for row in flight["edto"]["airports"]] == ["WAAA", "YPAD"]
    printed = "YPDN 1946-2327 29 CAT1DME 409FT/1600M".replace(old, value)
    assert _held(flight, "edto_alternates") == [("YPDN", printed, [f"period {side}"])]
    findings, warnings = analyse(flight)
    view = build_briefing_view(flight, findings, warnings, None, None, include_dashboard_only_panels=True)
    [review] = view["edto"]["unread_rows"]
    assert f"(period {side} not valid)" in review["review"] and printed in review["review"]
    assert not any(value[:2] + ":" + value[2:] in json.dumps(row) for row in view["edto"]["airports"])


@pytest.mark.parametrize(("table", "value"), [(t, v) for t in ("destination", "edto") for v in ("00", "37", "99", "00L")])
def test_qa512_02_an_impossible_runway_is_held_never_published(table: str, value: str) -> None:
    if table == "destination":
        flight = parse_lido(_mutated(r"^\s*YMML/", r"^(\s*YMML)/34", rf"\1/{value}"), SQ279)
        assert [row["airport"] for row in flight["alternates"]] == ["YSSY", "YMAV"]
        [held] = [row for row in flight["alternates_unread"] if row["airport"] == "YMML"]
    else:
        flight = parse_lido(_mutated(r"^\s*YPDN\s+1946-", r"(?<=\s)29(?=\s)", value), SQ279)
        assert [row["airport"] for row in flight["edto"]["airports"]] == ["WAAA", "YPAD"]
        [held] = [row for row in flight["alternates_unread"] if row["airport"] == "YPDN"]
    assert held["invalid_fields"] == ["runway"] and held["runway"] is None
    assert f'its runway cell "{value}" is not valid' in held["reason"] and "FAA AIM 2-3-3" in held["reason"]
    findings, warnings = analyse(flight)
    view = build_briefing_view(flight, findings, warnings, None, None, include_dashboard_only_panels=True)
    published = [(row.get("airport"), row.get("runway")) for row in view["alternate_assessment_rows"]]
    published += [(row.get("airport"), row.get("runway")) for row in view["edto"].get("airports") or []]
    assert not any(runway == value for _, runway in published)


@pytest.mark.parametrize(("label", "path_env"), [("CLOCK", "PILOTDRIVEN_QA512_CLOCK_PDF"),
                                                 ("RUNWAY", "PILOTDRIVEN_QA512_RUNWAY_PDF")])
def test_qa512_codex_live_synthetic_completes_holds_and_prints_no_invalid_plan(label: str, path_env: str) -> None:
    """Codex's live repro PDFs through the analysis and the six-page Flight Briefing: the analysis completes, the
    damaged rows are reviews (their printed row quoted), and no invalid value is printed as a plan."""
    if not os.environ.get(path_env):
        pytest.skip(f"{path_env} (Codex's labelled synthetic SQ279 {label}) is not set")
    path = Path(os.environ[path_env])
    flight = parse_lido(extract_pages(path), path.name)
    findings, warnings = analyse(flight)
    held = {(row["table"], row["airport"], tuple(row.get("invalid_fields") or [])) for row in flight["alternates_unread"]}
    if label == "CLOCK":
        assert held == {("edto_alternates", "YPDN", ("period start",))}
    else:
        assert held == {("destination_alternates", "YMML", ("runway",)), ("edto_alternates", "YPDN", ("runway",))}
    with tempfile.TemporaryDirectory() as scratch:
        pdf = Path(scratch) / "six-pages.pdf"
        render_combined_briefing(flight, findings, warnings, pdf, source_pdf_path=str(path))
        with fitz.open(pdf) as document:
            assert document.page_count == 6
            pages = [" ".join(page.get_text().split()) for page in document]
    unquoted = [re.sub(r'"[^"]*"', '""', page) for page in pages]
    for needle in ("YMML/99", "YPDN/99", "19:60", "1960Z"):
        assert not any(needle in page for page in unquoted), needle
    assert "YPDN · REVIEW - OFP p9 prints this EDTO alternate, but its row was not read (" in pages[4]


# --------------------------------------------------------------- Codex's exploratory observations (LABELLED SYNTHETIC)
WRAPPED = ["MINIMA: BAD", "CHECK NOW!", "-----", "ARR ATIS ......", "SID: TEST", "......"]


@pytest.mark.parametrize("junk", WRAPPED)
def test_a_wrapped_edto_minima_holds_ypdn_and_the_table_reads_on_to_ypad(junk: str) -> None:
    flight = parse_lido(_mutated(r"^\s*YPDN\s+1946-", "409FT/1600M", "\n" + junk), SQ279)
    assert [row["airport"] for row in flight["edto"]["airports"]] == ["WAAA", "YPAD"]
    [(airport, text, _)] = _held(flight, "edto_alternates")
    assert airport == "YPDN" and text == f"YPDN 1946-2327 29 CAT1DME {junk}"
    reason = [row["reason"] for row in flight["alternates_unread"] if row["airport"] == "YPDN"][0]
    assert "continues on the next line" in reason


@pytest.mark.parametrize(("label", "old", "new"), [("runway", r"(?<=\s)29(?=\s)", "11"),
                                                   ("minima", "409FT/1600M", "709FT/1600M"),
                                                   ("approach", "CAT1DME", "RNAV"), ("identical", "", "")])
def test_edto_printings_that_give_an_airport_different_rows_analyse_neither(label: str, old: str, new: str) -> None:
    pages = _pages(SQ279)
    at = next(i for i, page in enumerate(pages) if "EDTO ENROUTE ALTN AIRPORTS:" in page)
    block = pages[at].split("EDTO ENROUTE ALTN AIRPORTS:")[1].split("STATION WEATHER REPORTS")[0]
    copy_ = "\n".join(re.sub(old, new, line, count=1) if old and re.match(r"^YPDN\s", line) else line
                      for line in block.splitlines())
    pages = [*pages[:at], pages[at] + "\nEDTO ENROUTE ALTN AIRPORTS:" + copy_ + "\nSTATION WEATHER REPORTS!\n",
             *pages[at + 1:]]
    flight = parse_lido(pages, SQ279)
    if label == "identical":
        assert [row["airport"] for row in flight["edto"]["airports"]] == ["WAAA", "YPDN", "YPAD"]
        assert flight["alternates_unread"] == []
        return
    assert [row["airport"] for row in flight["edto"]["airports"]] == ["WAAA", "YPAD"]
    [row] = flight["alternates_unread"]
    assert row["airport"] == "YPDN" and "different rows" in row["reason"] and " / " in row["text"]


def test_a_heading_shaped_line_ends_the_table_only_when_the_table_does_not_go_on() -> None:
    header = "EDTO ENROUTE ALTN AIRPORTS:\nAPT      PERIOD CHKD       RWY           APCH             MINIMA"
    goes_on = f"{header}\nZZZZ 1900-2220 03 CAT1DME 492FT/2000M\nCHECK NOW!\nZZZY 2155-0140 28 400FT/2409M\n"
    tables = lido_parser._read_alternate_tables([goes_on + "STATION WEATHER REPORTS!\n-----\n"], 1)
    assert [m.group("airport") for m in tables["edto_rows"]] == ["ZZZZ", "ZZZY"]
    assert [(row["airport"], row["text"]) for row in tables["unread"]] == [(None, "CHECK NOW!")]
    # The EDTO table's own trailer always ends it, whatever follows.
    trailer = f"{header}\nZZZZ 1900-2220 03 CAT1DME 492FT/2000M\nSTATION WEATHER REPORTS!\nZZZY 2155-0140 28 400FT/2409M\n"
    tables = lido_parser._read_alternate_tables([trailer], 1)
    assert [m.group("airport") for m in tables["edto_rows"]] == ["ZZZZ"] and tables["unread"] == []


def test_a_line_whose_only_defect_is_its_airport_cell_names_that_field() -> None:
    flight = parse_lido(_mutated(r"^\s*YPDN\s+1946-", "YPDN", "YP1N"), SQ279)
    held = [row for row in flight["alternates_unread"] if row["table"] == "edto_alternates"]
    assert (held[0]["airport"], held[0].get("invalid_fields")) == (None, ["airport"])
    assert 'its airport cell "YP1N" is not valid' in held[0]["reason"]
    assert held[1]["airport"] == "YPDN" and "ETP lines name this EDTO alternate" in held[1]["reason"]


# ------------------------------------------------------------------------------------------ fuel-enroute station rows
@pytest.mark.parametrize(("cells", "field", "airport"), [("RK5C/CJU", "airport", None), ("rkpc/CJU", "airport", None),
                                                         ("RKPC/CJ1", "IATA code", "RKPC"), ("RKPC/CJUX", "IATA code", "RKPC")])
def test_an_invalid_fuel_enroute_station_row_is_held_once_naming_its_field(cells: str, field: str, airport) -> None:
    icao, iata = cells.split("/")
    pages = [re.sub(r"(?m)^(\s*)RKPC(\s*/\s*)CJU\b", lambda m: m.group(1) + icao + m.group(2) + iata, page)
             for page in _pages(SQ606)]
    flight = parse_lido(pages, SQ606)
    assert "RKPC" not in [row["airport"] for row in flight["fuel_enroute_airports"]]
    held = [row for row in flight["alternates_unread"] if row["table"] == "fuel_enroute_airports"]
    assert [(row["airport"], row["invalid_fields"]) for row in held] == [(airport, [field])]
    findings, warnings = analyse(flight)
    assert [item["title"] for item in findings].count("Fuel-enroute airport row not read") == 1
    view = build_briefing_view(flight, findings, warnings, None, None, include_dashboard_only_panels=True)
    [review] = view["fuel_enroute_unread_rows"]
    assert f"({field} not valid)" in review["review"]


def test_a_held_fuel_enroute_station_row_is_printed_on_pdf_page_5_and_its_value_is_not() -> None:
    pages = [re.sub(r"(?m)^(\s*)RKPC(\s*/\s*)CJU\b", lambda m: m.group(1) + "RKPC" + m.group(2) + "CJ1", page)
             for page in _pages(SQ606)]
    flight = parse_lido(pages, SQ606)
    findings, warnings = analyse(flight)
    with tempfile.TemporaryDirectory() as scratch:
        pdf = Path(scratch) / "six-pages.pdf"
        render_combined_briefing(flight, findings, warnings, pdf, source_pdf_path=str(_corpus() / SQ606))
        with fitz.open(pdf) as document:
            assert document.page_count == 6
            page5 = " ".join(document[4].get_text().split())
    windows = page5[page5.index("EDTO AIRPORT WINDOWS"):]
    assert "RKPC · REVIEW - OFP p" in windows and "(IATA code not valid)" in windows
    assert "Not applicable - this flight is NON-EDTO." in windows, "a NON-EDTO flight keeps its one line"
    assert "RKPC/CJ1" not in re.sub(r'"[^"]*"', '""', " ".join(windows.split()))


# ------------------------------------------------------------------------- no single cell can abort an analysis
def _analysed(source: Path) -> dict:
    from app.analysis import run_odss_analysis
    with tempfile.TemporaryDirectory() as scratch:
        result = run_odss_analysis(source, Path(scratch) / "analysis", Path(scratch) / "reports", 1)
        return json.loads(Path(result["analysis_path"]).read_text())


def test_a_throw_in_the_destination_row_reader_holds_that_row_and_the_analysis_completes(monkeypatch) -> None:
    source = _corpus() / SQ279
    original = lido_parser._destination_alternate_row

    def reader(match):
        if match.group("apt") == "YMML":
            raise RuntimeError("injected destination-row failure")
        return original(match)

    monkeypatch.setattr(lido_parser, "_destination_alternate_row", reader)
    flight = _analysed(source)["flight"]
    assert [row["airport"] for row in flight["alternates"]] == ["YSSY", "YMAV"]
    [held] = flight["alternates_unread"]
    assert held["airport"] == "YMML" and "reading it failed (RuntimeError: injected destination-row failure)" in held["reason"]


def test_a_throw_in_the_edto_period_reader_holds_that_row_and_the_analysis_completes(monkeypatch) -> None:
    source = _corpus() / SQ279
    original = lido_parser._edto_period

    def reader(start, end, *args, **kwargs):
        if start == "1946":
            raise ValueError("minute must be in 0..59, not 60 (injected)")
        return original(start, end, *args, **kwargs)

    monkeypatch.setattr(lido_parser, "_edto_period", reader)
    flight = _analysed(source)["flight"]
    assert [row["airport"] for row in flight["edto"]["airports"]] == ["WAAA", "YPAD"]
    [held] = flight["alternates_unread"]
    assert (held["table"], held["airport"], held["source_page"]) == ("edto_alternates", "YPDN", 9)
    assert "reading it failed (ValueError: minute must be in 0..59, not 60 (injected))" in held["reason"]


def test_a_throw_in_the_cell_rules_holds_that_row_and_the_analysis_completes(monkeypatch) -> None:
    source = _corpus() / SQ279
    original = table_cells.row_problems

    def rules(cells):
        if any(value == "YMAV" for _, value, *_ in cells):
            raise KeyError("injected cell-rule failure")
        return original(cells)

    monkeypatch.setattr(table_cells, "row_problems", rules)
    flight = _analysed(source)["flight"]
    assert [row["airport"] for row in flight["alternates"]] == ["YSSY", "YMML"]
    [held] = flight["alternates_unread"]
    assert held["airport"] == "YMAV" and "reading it failed (KeyError" in held["reason"]


def test_a_throw_in_the_fuel_enroute_row_reader_holds_that_row_and_the_analysis_completes(monkeypatch) -> None:
    source = _corpus() / SQ606
    if not source.is_file():
        pytest.skip(f"private source {SQ606} not available")
    original = enrichment.classify_bulletin_station_line

    def reader(line):
        if re.match(r"\s*RKPC\s*/", line):
            raise RuntimeError("injected station-row failure")
        return original(line)

    monkeypatch.setattr(enrichment, "classify_bulletin_station_line", reader)
    flight = _analysed(source)["flight"]
    assert "RKPC" not in [row["airport"] for row in flight["fuel_enroute_airports"]]
    held = [row for row in flight["alternates_unread"] if row["table"] == "fuel_enroute_airports"]
    assert [row["airport"] for row in held] == ["RKPC"]
    assert "reading it failed (RuntimeError: injected station-row failure)" in held[0]["reason"]


# ------------------------------ the semantic mutation test over the 30 held originals: every numeric and coded cell
_ROW = lido_parser._ALTERNATE_ROW
_EDTO_ROW = lido_parser._EDTO_ALTERNATE_ROW


def _semantic_values(kind: str, token: str) -> list[str]:
    """Semantically invalid values of the right shape (and identity damage) for one printed cell."""
    if kind == "icao":
        return [token[:2] + "1" + token[3], token[:3], token + "X"]
    if kind == "runway":
        return ["00", "37", "99", "00L", "37R"]
    if kind == "clock":
        return ["2400", "2460", "2360", "2500", "9999", "0060"]
    if kind == "minima":
        values = []
        if "FT" in token:
            values.append(re.sub(r"\d+FT", "20001FT", token))
        if token.endswith("M"):
            values.append(re.sub(r"\d+M$", "10001M", token))
        return values
    return {
        "distance_nm": ["0000", "3001", "9999"],
        "flight_level": ["000", "005", "520", "999"],
        "wind_component_kt": ["M251", "P999"],
        "duration": ["0000", "0060", "1001", "9999"],
        "fuel_kg": ["00000"],
    }[kind]


def _put(line: str, match: re.Match[str], group: str, value: str) -> str:
    return line[:match.start(group)] + value + line[match.end(group):]


def _places(cfp_pages: list[str], expression: re.Pattern[str], matches) -> list[tuple[int, int]]:
    return [(page_index, line_index)
            for page_index, page in enumerate(cfp_pages)
            for line_index, line in enumerate(page.split("\n"))
            if expression.fullmatch(line) and matches(expression.fullmatch(line))]


def _mutate(cfp_pages: list[str], places: list[tuple[int, int]], text: str) -> list[str]:
    pages = [page.split("\n") for page in cfp_pages]
    for page_index, line_index in places:
        pages[page_index][line_index] = text
    return ["\n".join(lines) for lines in pages]


def _edto_key(match: re.Match[str]) -> tuple:
    return (match.group("airport"), match.group("start"), match.group("end"), match.group("runway"),
            " ".join((match.group("approach") or "").split()), match.group("minima") or "")


_DESTINATION_CELLS = [("apt", "icao", "airport"), ("rwy", "runway", "runway"), ("minima", "minima", "minima"),
                      ("dist", "distance_nm", "distance"), ("fl", "flight_level", "flight level"),
                      ("comp", "wind_component_kt", "wind component"), ("time", "duration", "time"),
                      ("fuel", "fuel_kg", "fuel")]
_EDTO_CELLS = [("airport", "icao", "airport"), ("start", "clock", "period start"), ("end", "clock", "period end"),
               ("runway", "runway", "runway"), ("minima", "minima", "minima")]
_FUEL_MUTATIONS = {"airport": [lambda c: c[:2] + "5" + c[3], lambda c: c[:3], lambda c: c.lower()],
                   "IATA code": [lambda c: c[:2] + "1", lambda c: c + "X"]}


def test_every_semantically_invalid_cell_of_every_table_row_is_held_naming_it_never_published() -> None:
    """For every row of every destination, EDTO and fuel-enroute table the 30 originals print, and every numeric or coded
    cell of it, each semantically invalid value of the right shape - out-of-range clocks (24xx, xx60+), runways
    00/37/99/00L/37R, absurd distances, flight levels, wind components, times and fuel, minima above the stated bounds,
    invalid ICAO and IATA identifiers - in every printing and in each printing alone: the row is read from a printing
    whose cells are valid, or held unread naming the invalid field; every other row reads exactly as before; nothing
    raises; and the invalid value is never read (published). EDTO clocks are also run through the whole parse, where the
    invalid period used to abort the analysis."""
    pdfs = sorted(_corpus().glob("*.pdf"))
    checked = destination_rows = edto_rows = fuel_rows = 0
    problems: list[str] = []
    for pdf in pdfs:
        pages = extract_pages(pdf)
        cfp_start, cfp_end = lido_parser._detect_sections(pages)["cfp"]
        cfp_pages = pages[cfp_start:cfp_end]
        read = lambda mutated: lido_parser._read_alternate_tables(mutated, cfp_start + 1)  # noqa: E731
        control = read(cfp_pages)
        flight = parse_lido(pages, pdf.name)
        assert control["unread"] == flight["alternates_unread"] == []
        control_edto = [_edto_key(match) for match in control["edto_rows"]]

        for alternate in control["alternates"]:
            places = _places(cfp_pages, _ROW, lambda m, a=alternate: lido_parser._destination_alternate_row(m) == a)
            destination_rows += 1
            others = [row for row in control["alternates"] if row["airport"] != alternate["airport"]]
            line = cfp_pages[places[0][0]].split("\n")[places[0][1]]
            match = _ROW.fullmatch(line)
            scopes = [("every printing", places)] + ([("first printing", places[:1]), ("last printing", places[-1:])]
                                                     if len(places) > 1 else [])
            for group, kind, field in _DESTINATION_CELLS:
                if not match.group(group):
                    continue
                for value in _semantic_values(kind, match.group(group)):
                    text = _put(line, match, group, value)
                    printed = " ".join(text.split())
                    for scope, chosen in scopes:
                        checked += 1
                        label = f"{pdf.name} {alternate['airport']} {field}={value} ({scope})"
                        try:
                            result = read(_mutate(cfp_pages, chosen, text))
                        except Exception as error:  # noqa: BLE001
                            problems.append(f"{label}: raised {type(error).__name__}: {error}")
                            continue
                        held = [(row["airport"], row["text"], row.get("invalid_fields")) for row in result["unread"]]
                        if scope != "every printing":
                            expected = control["alternates"]
                            expected_held = [(None, printed, ["airport"])] if kind == "icao" else []
                        elif kind == "icao":
                            expected, expected_held = others, None
                            if held[:1] != [(None, printed, ["airport"])] or [row[0] for row in held[1:]] != [
                                    alternate["airport"]]:
                                problems.append(f"{label}: held {held}")
                        else:
                            expected, expected_held = others, [(alternate["airport"], printed, [field])]
                        if result["alternates"] != expected:
                            problems.append(f"{label}: read {[row['airport'] for row in result['alternates']]}")
                        if expected_held is not None and held != expected_held:
                            problems.append(f"{label}: held {held}")
                        if [_edto_key(m) for m in result["edto_rows"]] != control_edto:
                            problems.append(f"{label}: the EDTO table changed")

        for edto_match in control["edto_rows"]:
            key = _edto_key(edto_match)
            places = _places(cfp_pages, _EDTO_ROW, lambda m, k=key: _edto_key(m) == k)
            edto_rows += 1
            others = [other for other in control_edto if other != key]
            named_elsewhere = any(other[0] == key[0] for other in others)
            line = cfp_pages[places[0][0]].split("\n")[places[0][1]]
            match = _EDTO_ROW.fullmatch(line)
            for group, kind, field in _EDTO_CELLS:
                if not match.group(group):
                    continue
                for value in _semantic_values(kind, match.group(group)):
                    checked += 1
                    text = _put(line, match, group, value)
                    printed = " ".join(text.split())
                    label = f"{pdf.name} EDTO {key[0]} {field}={value}"
                    try:
                        result = read(_mutate(cfp_pages, places, text))
                    except Exception as error:  # noqa: BLE001
                        problems.append(f"{label}: raised {type(error).__name__}: {error}")
                        continue
                    read_rows = [_edto_key(m) for m in result["edto_rows"]]
                    held = [(row["airport"], row["text"], row.get("invalid_fields")) for row in result["unread"]]
                    if kind == "icao":
                        expected_held = [(None, printed, ["airport"])] + ([] if named_elsewhere else [
                            (key[0], held[1][1] if len(held) > 1 else None, None)])
                    else:
                        expected_held = [(key[0], printed, [field])]
                    if read_rows != others:
                        problems.append(f"{label}: read {read_rows}")
                    if held != expected_held:
                        problems.append(f"{label}: held {held}")
                    if result["alternates"] != control["alternates"]:
                        problems.append(f"{label}: the destination table changed")
                    # The checked period is built only for a valid clock: the whole parse never raises on one.
                    if kind == "clock" and value in {"2400", "2360", "9999"}:
                        checked += 1
                        whole = [*pages[:cfp_start], *_mutate(cfp_pages, places, text), *pages[cfp_end:]]
                        try:
                            parsed = parse_lido(whole, pdf.name)
                        except Exception as error:  # noqa: BLE001
                            problems.append(f"{label} (whole parse): raised {type(error).__name__}: {error}")
                            continue
                        expected_airports = [
                            row for row in flight["edto"]["airports"]
                            if (row["airport"], row["period_start_utc"][11:16].replace(":", ""),
                                row["period_end_utc"][11:16].replace(":", ""), row["runway"], row["approach"],
                                row["minima"]) != key
                        ]
                        if parsed["edto"]["airports"] != expected_airports:
                            problems.append(f"{label} (whole parse): EDTO airports {parsed['edto']['airports']}")
                        if [(row["airport"], row.get("invalid_fields")) for row in parsed["alternates_unread"]] != [
                                (key[0], [field])]:
                            problems.append(f"{label} (whole parse): held {parsed['alternates_unread']}")

        for station in flight["fuel_enroute_airports"]:
            fuel_rows += 1
            icao, iata = station["airport"], station["iata"]
            header = re.compile(r"^(\s*)" + icao + r"(\s*/\s*)" + iata + r"\b")
            # The station row of each appendix: the first line under its FUEL ENROUTE AIRPORT heading.
            places = []
            for page_index, page in enumerate(pages):
                opened = False
                for line_index, line in enumerate(page.split("\n")):
                    if enrichment._FUEL_ENROUTE_HEADING.fullmatch(line.strip()):
                        opened = True
                        continue
                    if opened and line.strip() and not enrichment._FUEL_ENROUTE_RULE.fullmatch(line.strip()):
                        if header.match(line):
                            places.append((page_index, line_index))
                        opened = False
            if not places:
                problems.append(f"{pdf.name} FUEL {icao}: station row not found")
                continue
            scopes = [("every printing", places)] + ([("first printing", places[:1]), ("last printing", places[-1:])]
                                                     if len(places) > 1 else [])
            others = [row["airport"] for row in flight["fuel_enroute_airports"] if row["airport"] != icao]
            for field, mutations in _FUEL_MUTATIONS.items():
                for number, mutation in enumerate(mutations):
                    new_icao = mutation(icao) if field == "airport" else icao
                    new_iata = mutation(iata) if field == "IATA code" else iata
                    identity_valid = re.fullmatch(r"[A-Z]{4}", new_icao) is not None
                    for scope, chosen in scopes:
                        checked += 1
                        label = f"{pdf.name} FUEL {icao}/{iata} {field}={new_icao}/{new_iata} ({scope})"
                        split = [page.split("\n") for page in pages]
                        for page_index, line_index in chosen:
                            split[page_index][line_index] = header.sub(
                                lambda m: m.group(1) + new_icao + m.group(2) + new_iata, split[page_index][line_index])
                        mutated = ["\n".join(lines) for lines in split]
                        probe = {"fuel_enroute_airports": [], "alternates_unread": []}
                        try:
                            enrichment._discover_fuel_enroute_stations(probe, mutated)
                            enrichment._discover_fuel_enroute_stations(probe, mutated)  # idempotent: it runs twice
                        except Exception as error:  # noqa: BLE001
                            problems.append(f"{label}: raised {type(error).__name__}: {error}")
                            continue
                        fuel = [row["airport"] for row in probe["fuel_enroute_airports"]]
                        held = [(row["airport"], row.get("invalid_fields")) for row in probe["alternates_unread"]]
                        if scope == "every printing":
                            expected = (others, [(icao if identity_valid else None, [field])])
                        else:
                            expected = ([*others, icao], [] if identity_valid else [(None, [field])])
                        if (sorted(fuel), held) != (sorted(expected[0]), expected[1]):
                            problems.append(f"{label}: fuel {fuel} held {held}")
                        if scope == "every printing" and number == 0:
                            # The whole parse: nothing raises, and no other station's records or rows change.
                            checked += 1
                            parsed = parse_lido(mutated, pdf.name)
                            if parsed["alternates"] != flight["alternates"] or parsed["edto"] != flight["edto"]:
                                problems.append(f"{label}: an alternate or EDTO row changed")
                            for records in ("notams", "weather"):
                                before = [r for r in flight[records] if r.get("location") != icao]
                                after = [r for r in parsed[records] if r.get("location") != icao]
                                if before != after:
                                    problems.append(f"{label}: other stations' {records} changed")
    print(f"{len(pdfs)} OFPs: {destination_rows} destination rows, {edto_rows} EDTO rows, {fuel_rows} fuel-enroute rows, "
          f"{checked} semantic mutations")
    assert (destination_rows, edto_rows, fuel_rows) == (104, 52, 27)
    assert not problems, f"{len(problems)} mutation(s) not accounted:\n" + "\n".join(problems[:40])


# ------------------------------------------------------------- QA516: a table cell is ASCII in both runtimes (fail-closed)
@pytest.mark.parametrize(("table", "old", "new"), [("destination", "0396", "０３９６"), ("destination", "0396", "٠٣٩٦"),
                                                   ("edto", "1946", "１９４６"), ("edto", "1946", "١٩٤٦"),
                                                   ("edto", "1946", "19​46")])
def test_qa516_a_cell_with_a_non_ascii_character_is_held_in_both_runtimes(table: str, old: str, new: str) -> None:
    """Codex's local QA516 observation: Python's \\d and int() read full-width and Arabic-Indic digits, JavaScript's \\d
    does not, so ODSS read the row and the app held it. Both runtimes now read a cell only in ASCII (rules "text"):
    the row is held, fail-closed (the app twin runs the same cases)."""
    opening = r"^\s*YMML/" if table == "destination" else r"^\s*YPDN\s+1946-"
    flight = parse_lido(_mutated(opening, old, new), SQ279)
    airport = "YMML" if table == "destination" else "YPDN"
    read = flight["alternates"] if table == "destination" else flight["edto"]["airports"]
    assert airport not in [row["airport"] for row in read]
    assert airport in [row["airport"] for row in flight["alternates_unread"]]


def test_qa516_table_cells_and_timing_differ_in_normalisation_on_purpose() -> None:
    """The table-cell rules are ASCII-only with no normalisation; the NOTAM timing rules normalise (NFKC, Cf dropped).
    Both are fail-closed for their direction: an unrecognised clock reads as no schedule, so timing recognises more; a
    recognised cell publishes its value, so table cells recognise less. This pins the two stated contracts."""
    text = table_cells.RULES["text"]
    assert (text["characters"], text["digits"], text["normalisation"]) == ("ASCII", "0-9", None)
    timing = json.loads((ROOT / "app" / "odss" / "notam_timing_rules.json").read_text())["scheduleField"]["normalisation"]
    assert timing == {"form": "NFKC", "drop": "Cf"}

"""QA508-01: an alternate table ends only at the LIDO layout's own structure, never on what a cell holds.

Codex's QA of release 508 (15 Oct 2026, P1, confirmed live): the table-end test still read cell content - any lowercase
letter or any run of dots closed the table - and it ran before a line could be read or held. In a labelled synthetic
SQ279 whose YMML fuel and YPDN minima are printed ".....", the destination table kept YSSY only (YMML and the untouched
YMAV recovered as names from the route lines) and the EDTO table kept WAAA only: YPDN and the untouched YPAD were lost
with no EDTO warning, and the dashboard and PDF page 5 showed one EDTO airport window of three. "700ft" and "cat1dme"
did the same. Root cause: parser._alternate_table_ends (and cfp.mjs alternateTableEnds) closed on lowercase or a dot
run, before the row could be read or held; the EDTO table had no name recovery.

The repair (parser._read_alternate_tables, and cfp.readAlternateTables by the same rules):
  - a line that opens a row (its identity is readable) is a table line whatever its cells hold;
  - any other line ends the table only when its whole line is the next block's structure: the "<ICAO> RTE:" trailer,
    a section heading in words ending in ":" or "!" or underlined by a rule, a rule, a labelled field in words, a form
    line of words and a dot leader, or another table's opener. Lowercase, dots, junk or a damaged cell are damage;
  - a table that reaches the end of the section with no such boundary holds its remainder as one unread block;
  - an approach word starts with a letter, so a damaged minima is never taken for an approach;
  - the EDTO table gets the destination table's recovery: printings reconciled by airport and place, and every EDTO
    alternate the ETP lines name that is neither read nor held is held by name.

SYNTHETIC mutations are LABELLED and applied to text extracted from genuine originals; no PDF is changed.
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
EDTO_HEADER = "EDTO ENROUTE ALTN AIRPORTS:\nAPT      PERIOD CHKD       RWY           APCH             MINIMA"
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


def _mutated(airport_line: str, old: str, new: str) -> list[str]:
    """Genuine SQ279 with ``old`` replaced by ``new`` on every printed line that opens with ``airport_line``."""
    return [
        "\n".join(re.sub(re.escape(old), new, line) if re.match(airport_line, line) else line for line in page.split("\n"))
        for page in _pages(SQ279)
    ]


def _edto(flight: dict) -> tuple[list[str], list[tuple]]:
    return ([row["airport"] for row in flight["edto"]["airports"]],
            [(row["airport"], row["text"]) for row in flight["alternates_unread"] if row["table"] == "edto_alternates"])


# ------------------------------------------------------------------------- Codex's failing cases (LABELLED SYNTHETIC)
# The same text mutations as Codex's runner (output/pd-508-codex-qa-20261015/scripts/new_tables.py); RED on 510.

def test_qa508_codex_lower_minima_both_holds_ymml_and_reads_ymav() -> None:
    flight = parse_lido(_mutated(r"^\s*YMML/", "700FT", "700ft"), SQ279)
    assert [row["airport"] for row in flight["alternates"]] == ["YSSY", "YMAV"]
    assert [(row["airport"], row["text"]) for row in flight["alternates_unread"]] == [
        ("YMML", "YMML/34 700ft/2500M 0396 330 P007 0105 05817")]


def test_qa508_codex_dot_damage_both_holds_ymml_with_its_raw_row_and_reads_ymav() -> None:
    flight = parse_lido(_mutated(r"^\s*YMML/", "05817", "....."), SQ279)
    assert [row["airport"] for row in flight["alternates"]] == ["YSSY", "YMAV"]
    assert [(row["airport"], row["text"]) for row in flight["alternates_unread"]] == [
        ("YMML", "YMML/34 700FT/2500M 0396 330 P007 0105 .....")]


def test_qa508_codex_edto_lower_approach_holds_ypdn_and_reads_ypad() -> None:
    flight = parse_lido(_mutated(r"^\s*YPDN\s+\d{4}-", "CAT1DME", "cat1dme"), SQ279)
    assert _edto(flight) == (["WAAA", "YPAD"], [("YPDN", "YPDN 1946-2327 29 cat1dme 409FT/1600M")])
    findings, _ = analyse(flight)
    review = [item for item in findings if item["title"] == "EDTO alternate row not read"]
    assert len(review) == 1 and "YPDN" in review[0]["summary"]


def test_qa508_codex_edto_dot_minima_holds_ypdn_and_reads_ypad() -> None:
    flight = parse_lido(_mutated(r"^\s*YPDN\s+\d{4}-", "409FT/1600M", "....."), SQ279)
    assert _edto(flight) == (["WAAA", "YPAD"], [("YPDN", "YPDN 1946-2327 29 CAT1DME .....")])
    periods = {row["airport"]: row["period_start_utc"] for row in flight["edto"]["airports"]}
    assert periods["YPAD"].endswith("20:47:00+00:00"), "the untouched YPAD row keeps its printed period"


def test_qa508_a_held_edto_row_stands_with_the_windows_on_the_dashboard_and_pdf_page_5() -> None:
    """Codex saw one EDTO window of three and no review. The held YPDN row is a review in its printed place on both EDTO
    surfaces (view edto.unread_rows, which the dashboard renders, and the PDF's EDTO AIRPORT WINDOWS on page 5), and
    the untouched YPAD keeps its window."""
    pages = _mutated(r"^\s*YPDN\s+\d{4}-", "409FT/1600M", ".....")
    flight = parse_lido(pages, SQ279)
    findings, warnings = analyse(flight)
    view = build_briefing_view(flight, findings, warnings, None, None, include_dashboard_only_panels=True)
    [review] = view["edto"]["unread_rows"]
    assert (review["airport"], review["position"], review["source_page"]) == ("YPDN", 1, 9)
    assert review["review"] == ('REVIEW - OFP p9 prints this EDTO alternate, but its row was not read: '
                                '"YPDN 1946-2327 29 CAT1DME ....."; its checked period is not analysed.')
    with tempfile.TemporaryDirectory() as scratch:
        pdf = Path(scratch) / "six-pages.pdf"
        render_combined_briefing(flight, findings, warnings, pdf, source_pdf_path=str(_corpus() / SQ279))
        with fitz.open(pdf) as document:
            assert document.page_count == 6
            page5 = " ".join(document[4].get_text().split())
    windows = page5[page5.index("EDTO AIRPORT WINDOWS"):]
    assert windows.index("WAAA/03") < windows.index("YPDN · REVIEW - OFP p9") < windows.index("YPAD/05")


def test_qa508_an_edto_row_with_no_readable_identity_is_held_and_named_by_its_etp_line() -> None:
    flight = parse_lido(_mutated(r"^\s*YPDN\s+\d{4}-", "YPDN", "Y?DN"), SQ279)
    airports, held = _edto(flight)
    assert airports == ["WAAA", "YPAD"]
    assert held[0] == (None, "Y?DN 1946-2327 29 CAT1DME 409FT/1600M")
    assert held[1][0] == "YPDN" and held[1][1].startswith("1E ..... E11658.9 YPDN")
    reason = [row for row in flight["alternates_unread"] if row["airport"] == "YPDN"][0]["reason"]
    assert "ETP lines name this EDTO alternate" in reason


@pytest.mark.skipif(not os.environ.get("PILOTDRIVEN_QA508_DOT_CELLS_PDF"),
                    reason="PILOTDRIVEN_QA508_DOT_CELLS_PDF (Codex's labelled synthetic SQ279 DOT-CELLS) is not set")
def test_qa508_codex_live_dot_cells_pdf_reads_or_holds_every_row() -> None:
    path = Path(os.environ["PILOTDRIVEN_QA508_DOT_CELLS_PDF"])
    flight = parse_lido(extract_pages(path), path.name)
    assert [row["airport"] for row in flight["alternates"]] == ["YSSY", "YMAV"]
    assert [row["airport"] for row in flight["edto"]["airports"]] == ["WAAA", "YPAD"]
    held = {(row["table"], row["airport"]) for row in flight["alternates_unread"]}
    assert {("destination_alternates", "YMML"), ("edto_alternates", "YPDN")} <= held


# --------------------------------------------------------------------------------------- the rules, LABELLED SYNTHETIC
ZZZY = "ZZZY/27    CAT1DME   200FT/550M   0085   060 P003   0021 04014"
ZZZX = "ZZZX/09    VORDME    3000FT/5000M 0085  140 M003  0020 01802"


@pytest.mark.parametrize("damage", [
    "ZZZW/09 vordme 3000FT/5000M 0085 140 M003 0020 01802",
    "ZZZW/09 VORDME ..... 0085 140 M003 0020 01802",
    "ZZZW/09 VORDME 3000FT/5000M 0085 140 M003 0020 .....",
    "ZZZW/09 x.Y: 3000FT/5000M 0085 140 M003 0020 01802",
    "ZZZW/09 ARR ATIS ........",
])
def test_a_row_whatever_its_cells_hold_never_ends_the_table(damage: str) -> None:
    pages = [f"{HEADER}\n{ZZZY}\n{damage}\n{ZZZX}\n\nZZZY RTE: X\nZZZW RTE: X\nZZZX RTE: X\nEXCESS FUEL REASON:\n"]
    tables = lido_parser._read_alternate_tables(pages, 1)
    assert [row["airport"] for row in tables["alternates"]] == ["ZZZY", "ZZZX"]
    assert [(row["airport"], row["text"]) for row in tables["unread"]] == [("ZZZW", " ".join(damage.split()))]


@pytest.mark.parametrize("line", ["Airport WX List", ".....", "lower case words", "?#! x.Y:", "...... 0085 140"])
def test_a_line_that_is_not_the_next_blocks_structure_is_held_and_the_table_reads_on(line: str) -> None:
    pages = [f"{HEADER}\n{ZZZY}\n{line}\n{ZZZX}\n\nZZZY RTE: X\nZZZX RTE: X\nEXCESS FUEL REASON:\n"]
    tables = lido_parser._read_alternate_tables(pages, 1)
    assert [row["airport"] for row in tables["alternates"]] == ["ZZZY", "ZZZX"]
    assert [(row["airport"], row["text"]) for row in tables["unread"]] == [(None, " ".join(line.split()))]


def test_an_underlined_heading_ends_the_edto_table_even_when_its_mark_is_unmapped() -> None:
    """The app's text layer reads LIDO's "STATION WEATHER REPORTS!" as "STATION WEATHER REPORTS \\x00"; the rule under
    it is what makes it a heading."""
    text = (f"{EDTO_HEADER}\nZZZZ     1900-2220          03       CAT1DME        492FT/2000M\n"
            "STATION WEATHER REPORTS \x00\n-----------------------\nZZZY 2155-0140 28 400FT/2409M\n")
    tables = lido_parser._read_alternate_tables([text], 1)
    assert [m.group("airport") for m in tables["edto_rows"]] == ["ZZZZ"] and tables["unread"] == []


def test_a_table_with_no_positively_identified_end_holds_its_remainder_as_one_block() -> None:
    pages = [f"{HEADER}\n{ZZZY}\nRTOW(PERF) 285609 FLAPS 2\nsome package text\n" + "\n".join(f"LINE {n}" for n in range(40))]
    tables = lido_parser._read_alternate_tables(pages, 1)
    assert [row["airport"] for row in tables["alternates"]] == ["ZZZY"]
    [block] = tables["unread"]
    assert block["airport"] is None and block["text"].startswith("RTOW(PERF) 285609 FLAPS 2 / some package text")
    assert block["text"].endswith("(42 lines)") and "no heading or trailer after it" in block["reason"]


def test_a_damaged_edto_copy_in_another_printing_is_reconciled_by_airport_and_place() -> None:
    good = f"{EDTO_HEADER}\nZZZZ 1900-2220 03 CAT1DME 492FT/2000M\nZZZY 2155-0140 28 400FT/2409M\nSTATION WEATHER REPORTS!\n"
    bad = good.replace("ZZZY 2155-0140 28 400FT/2409M", "ZZZY 2155-0140 28 .....")
    tables = lido_parser._read_alternate_tables([bad, good], 1)
    assert [m.group("airport") for m in tables["edto_rows"]] == ["ZZZZ", "ZZZY"]
    assert tables["unread"] == []


def test_a_damaged_minima_is_never_taken_for_an_approach() -> None:
    pages = [f"{HEADER}\nZZZW/09 VORDME 3000FT/500 0085 140 M003 0020 01802\n\nZZZW RTE: X\nEXCESS FUEL REASON:\n"]
    tables = lido_parser._read_alternate_tables(pages, 1)
    assert tables["alternates"] == [] and [row["airport"] for row in tables["unread"]] == ["ZZZW"]


# ------------------------------------------------- the exhaustive mutation test over the 30 held originals (QA504/508)
VARIANTS = ("blank", "??", "truncated", "lower", "dots", "junk", "mixed junk")


def _variant(token: str, variant: str) -> str:
    return {
        "blank": " " * len(token),
        "??": "??",
        "truncated": token[:max(1, len(token) - 2)],
        "lower": token.lower(),
        "dots": ".....",
        "junk": "?#!",
        "mixed junk": "x.Y:",
    }[variant]


def _spans(line: str) -> list[tuple[int, int]]:
    return [match.span() for match in re.finditer(r"\S+", line)]


def _put(line: str, span: tuple[int, int], value: str) -> str:
    return line[:span[0]] + value + line[span[1]:]


def _cells(line: str, table: str, approach: str, minima: str) -> list[tuple[str, tuple[int, int]]]:
    """Every cell of a printed row, by its printed place: identity, runway (or period and runway), each approach word,
    the minima, and the destination row's five numeric cells."""
    spans = _spans(line)
    if table == "destination":
        start, end = spans[0]
        slash = line.index("/", start)
        cells = [("airport", (start, slash)), ("runway", (slash + 1, end))]
        middle, tail = spans[1:-5], spans[-5:]
    else:
        cells = [("airport", spans[0]), ("period", spans[1]), ("runway", spans[2])]
        middle, tail = spans[3:], []
    words = len(approach.split())
    cells += [(f"approach {index + 1}", span) for index, span in enumerate(middle[:words])]
    if minima:
        cells.append(("minima", middle[words]))
    cells += list(zip(("dist", "fl", "comp", "time", "fuel"), tail))
    return cells


def _outcome(table: str, cell: str, variant: str, mutated_token: str) -> str:
    """What the mutation must do, stated from the printed layout:
    - "identity": the line no longer opens a row (its airport is unreadable, or its runway - destination - or period
      - EDTO - cell holds a letter that a runway designator cannot), so it is held as printed and the alternate is held
      by name from the OFP's independent listing (route lines, ETP lines);
    - "read": an approach word blanked or truncated (still a word), or the minima blanked, is a row printed that way -
      read exactly as printed;
    - "held": any other damage - the row is held by its airport with its printed text."""
    if cell == "airport":
        return "identity"
    letters = re.sub(r"[LCR]$", "", mutated_token) if cell == "runway" else mutated_token
    if (table == "destination" and cell == "runway" or table == "edto" and cell == "period") and \
            re.search(r"[A-Z]", letters) and not (cell == "period" and re.fullmatch(r"\d{2}[LCR]?", mutated_token)):
        return "identity"
    if cell.startswith("approach") and variant in {"blank", "truncated"}:
        return "read"
    if cell == "minima" and variant == "blank":
        return "read"
    return "held"


def _printed(cfp_pages: list[str], expression: re.Pattern[str], matches) -> list[tuple[int, int]]:
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


def _expected_read(row: dict, cell: str, variant: str, token: str) -> dict:
    words = row["approach"].split()
    if cell == "minima":
        return {**row, "minima": ""}
    index = int(cell.split()[1]) - 1
    words = [*words[:index], *([] if variant == "blank" else [_variant(token, variant)]), *words[index + 1:]]
    return {**row, "approach": " ".join(words)}


def test_every_damage_of_every_cell_of_every_alternate_row_is_read_as_printed_or_held_never_lost() -> None:
    """For every row of every alternate table the 30 originals print, and every cell of it (identity, runway or period,
    each approach word, the minima, each numeric cell): blank, "??", truncated, lower case, a form-leader dot run, junk
    and mixed junk - in every printing, and in each printing alone - plus wraps onto the next line and the row cut after
    its runway or period. The damaged row is read exactly as printed or held with its printed text (by airport when its
    identity is readable, by name from the OFP's own listing when it is not); every other row of the table is read
    exactly; nothing else is held."""
    pdfs = sorted(_corpus().glob("*.pdf"))
    checked = destination_rows = edto_rows = 0
    problems: list[str] = []
    for pdf in pdfs:
        pages = extract_pages(pdf)
        cfp_start, cfp_end = lido_parser._detect_sections(pages)["cfp"]
        cfp_pages = pages[cfp_start:cfp_end]
        read = lambda mutated: lido_parser._read_alternate_tables(mutated, cfp_start + 1)  # noqa: E731
        control = read(cfp_pages)
        flight = parse_lido(pages, pdf.name)
        assert control["alternates"] == flight["alternates"] and control["unread"] == flight["alternates_unread"] == []
        control_edto = [_edto_key(match) for match in control["edto_rows"]]

        for alternate in control["alternates"]:
            places = _printed(cfp_pages, _ROW, lambda m, a=alternate: lido_parser._destination_alternate_row(m) == a)
            if not places:
                problems.append(f"{pdf.name} {alternate['airport']}: printed row not found")
                continue
            destination_rows += 1
            others = [row for row in control["alternates"] if row["airport"] != alternate["airport"]]
            line = cfp_pages[places[0][0]].split("\n")[places[0][1]]
            scopes = [("every printing", places)] + ([("first printing", places[:1]), ("last printing", places[-1:])]
                                                     if len(places) > 1 else [])
            mutations = []
            for cell, span in _cells(line, "destination", alternate["approach"], alternate["minima"]):
                token = line[span[0]:span[1]]
                for variant in VARIANTS:
                    value = _variant(token, variant)
                    if value != token:
                        mutations.append((cell, variant, _put(line, span, value), _outcome("destination", cell, variant, value), token))
            spans = _spans(line)
            mutations.append(("wrap", "fuel onto the next line",
                              line[:spans[-1][0]].rstrip() + "\n" + " " * spans[-1][0] + line[spans[-1][0]:], "wrap", ""))
            mutations.append(("wrap", "after the runway", line[:spans[0][1]] + "\n" + " " * spans[0][1] + line[spans[0][1]:],
                              "wrap", ""))
            mutations.append(("row", "cut after the runway", line[:spans[0][1]], "held", ""))
            for cell, variant, text, outcome, token in mutations:
                printed = " ".join(text.split())
                for scope, chosen in scopes:
                    checked += 1
                    result = read(_mutate(cfp_pages, chosen, text))
                    label = f"{pdf.name} {alternate['airport']} {cell} {variant} ({scope})"
                    held = [(row["airport"], row["text"]) for row in result["unread"]]
                    single = scope != "every printing"
                    if outcome == "wrap":
                        expected, expected_held = control["alternates"], []
                    elif outcome == "read" and not single:
                        mutated_row = _expected_read(alternate, cell, variant, token)
                        expected = [mutated_row if row is alternate else row for row in control["alternates"]]
                        expected_held = []
                    elif outcome == "read":
                        # One printing now prints another row for the alternate: the printings disagree.
                        expected, expected_held = others, None
                        if [airport for airport, _ in held] != [alternate["airport"]] or printed not in held[0][1] or \
                                "different rows" not in result["unread"][0]["reason"]:
                            problems.append(f"{label}: held {held}")
                    elif single:
                        expected = control["alternates"]
                        expected_held = [(None, printed)] if outcome == "identity" else []
                    elif outcome == "identity":
                        expected, expected_held = others, None
                        if held[:1] != [(None, printed)] or [airport for airport, _ in held[1:]] != [alternate["airport"]] \
                                or not held[1][1].startswith(f"{alternate['airport']} RTE:"):
                            problems.append(f"{label}: held {held}")
                    else:
                        expected, expected_held = others, [(alternate["airport"], printed)]
                    if result["alternates"] != expected:
                        problems.append(f"{label}: read {[row['airport'] for row in result['alternates']]}")
                    if expected_held is not None and held != expected_held:
                        problems.append(f"{label}: held {held}")
                    if [_edto_key(match) for match in result["edto_rows"]] != control_edto:
                        problems.append(f"{label}: the EDTO table changed")

        for match in control["edto_rows"]:
            key = _edto_key(match)
            places = _printed(cfp_pages, _EDTO_ROW, lambda m, k=key: _edto_key(m) == k)
            if not places:
                problems.append(f"{pdf.name} EDTO {key[0]}: printed row not found")
                continue
            edto_rows += 1
            others = [other for other in control_edto if other != key]
            line = cfp_pages[places[0][0]].split("\n")[places[0][1]]
            mutations = []
            for cell, span in _cells(line, "edto", key[4], key[5]):
                token = line[span[0]:span[1]]
                for variant in VARIANTS:
                    value = _variant(token, variant)
                    if value != token:
                        mutations.append((cell, variant, _put(line, span, value), _outcome("edto", cell, variant, value), token))
            spans = _spans(line)
            if len(spans) > 3:
                mutations.append(("wrap", "last cell onto the next line",
                                  line[:spans[-1][0]].rstrip() + "\n" + " " * spans[-1][0] + line[spans[-1][0]:], "wrap", ""))
            mutations.append(("row", "cut after the period", line[:spans[1][1]], "held", ""))
            for cell, variant, text, outcome, token in mutations:
                checked += 1
                printed = " ".join(text.split())
                result = read(_mutate(cfp_pages, places, text))
                label = f"{pdf.name} EDTO {key[0]} {cell} {variant}"
                read_rows = [_edto_key(row) for row in result["edto_rows"]]
                held = [(row["table"], row["airport"], row["text"]) for row in result["unread"]]
                if outcome == "wrap":
                    expected, expected_held = control_edto, []
                elif outcome == "read":
                    words = key[4].split()
                    if cell == "minima":
                        changed = (*key[:5], "")
                    else:
                        index = int(cell.split()[1]) - 1
                        words = [*words[:index], *([] if variant == "blank" else [_variant(token, variant)]), *words[index + 1:]]
                        changed = (*key[:4], " ".join(words), key[5])
                    expected = [changed if other == key else other for other in control_edto]
                    expected_held = []
                elif outcome == "identity":
                    expected, expected_held = others, None
                    if held[:1] != [("edto_alternates", None, printed)] or [row[1] for row in held[1:]] != [key[0]] \
                            or "ETP" not in result["unread"][1]["reason"]:
                        problems.append(f"{label}: held {held}")
                else:
                    expected, expected_held = others, [("edto_alternates", key[0], printed)]
                if read_rows != expected:
                    problems.append(f"{label}: read {read_rows}")
                if expected_held is not None and held != expected_held:
                    problems.append(f"{label}: held {held}")
                if result["alternates"] != control["alternates"]:
                    problems.append(f"{label}: the destination table changed")
    print(f"{len(pdfs)} OFPs: {destination_rows} destination rows and {edto_rows} EDTO rows, {checked} mutations")
    assert destination_rows == 104 and edto_rows == 52
    assert not problems, f"{len(problems)} mutation(s) not accounted:\n" + "\n".join(problems[:40])

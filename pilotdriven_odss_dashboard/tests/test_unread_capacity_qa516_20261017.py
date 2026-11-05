"""QA516-01: accounting is never truncated - every held, unread or read table row is kept in full, in both runtimes.

Codex's QA of release 516 (17 Oct 2026, P2): a labelled SQ279 copy with thirteen invalid-runway destination rows
(QAAA-QAAM) gave 13 held rows in ODSS but 12 in the app's parse response - QAAM was absent from the whole response -
because the app cut alternatesUnread to 12 (cfp.mjs) and cut the merged destination/EDTO/fuel list to 12 again. The
principle: a parse or analysis payload holds every record; a display limit lives only in the presentation layer and says
what it leaves out ("+N further ... on the dashboard"); a genuine size bound is an explicit, signalled overflow.

ODSS never cut these lists; this file proves it for more rows of every held/unread table record type than any cap either
runtime has had (12, 32, 64), through the parse, the analysis view and the six-page PDF (which states what it defers),
and - when the app root is available - that the app parser holds exactly the same rows.

SYNTHETIC rows are LABELLED: synthetic identities ("Q" + three letters) added to text extracted from genuine originals.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess
import tempfile

import fitz
import pytest

from app.odss.briefing import build_briefing_view
from app.odss.combined_brief import render_combined_briefing
from app.odss.engines import analyse
from app.odss.parser import extract_pages, parse_lido

ROOT = Path(__file__).resolve().parents[1]
SQ279 = "lido-briefing_SQ_279_15Aug2026_SIN_ADL.pdf"
SQ023 = "SQ02325072026JFK.pdf"
N = 70  # more than any cap either runtime has had (12 unread rows, 12 alternates, 32, 64)


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


def _ident(i: int) -> str:
    return "Q" + chr(65 + i // 676 % 26) + chr(65 + i // 26 % 26) + chr(65 + i % 26)


def _after(pages: list[str], pattern: str, extra: str) -> list[str]:
    return [re.sub(pattern, lambda m: m.group(0) + "\n" + extra, page, flags=re.M) for page in pages]


def _destination_rows(n: int, runway: str) -> str:
    return "\n".join(f"{_ident(i)}/{runway}              700FT/2500M  0396  330 P007  0105 05817" for i in range(n))


def _edto_rows(n: int, runway: str, start: int = 0) -> str:
    return "\n".join(f"{_ident(start + i)}     1946-2327          {runway}         CAT1DME          409FT/1600M"
                     for i in range(n))


def _fuel_rows(n: int) -> str:
    # NOTAM-bulletin station rows, each underlined; a digit in the ICAO cell holds every one.
    return "".join(f"Q{_ident(i)[2]}9{_ident(i)[3]} /HKT   SYNTHETIC QA516 STATION\n------------------------------\n"
                   for i in range(n))


def _cases() -> dict[str, tuple[list[str], str, dict[str, int]]]:
    sq279, sq023 = _pages(SQ279), _pages(SQ023)
    mixed = _after(sq279, r"^YMML/34[^\n]*$", _destination_rows(8, "99"))
    mixed = _after(mixed, r"^YPDN     1946-2327[^\n]*$", _edto_rows(8, "99", start=100))
    fuel = [re.sub(r"(?m)(^FUEL ENROUTE AIRPORT\n=+\n \nVTSP /HKT[^\n]*\n-+\n)", lambda m: m.group(1) + _fuel_rows(N), page)
            for page in sq023]
    assert fuel != sq023, "the SQ023 bulletin's FUEL ENROUTE AIRPORT section moved"
    return {
        "destination_unread": (_after(sq279, r"^YMML/34[^\n]*$", _destination_rows(N, "99")), SQ279,
                               {"destination_alternates": N}),
        "edto_unread": (_after(sq279, r"^YPDN     1946-2327[^\n]*$", _edto_rows(N, "99")), SQ279, {"edto_alternates": N}),
        "fuel_unread": (fuel, SQ023, {"fuel_enroute_airports": N}),
        "mixed_unread": (mixed, SQ279, {"destination_alternates": 8, "edto_alternates": 8}),
        "destination_read": (_after(sq279, r"^YMML/34[^\n]*$", _destination_rows(N, "34")), SQ279, {"alternates": N}),
        "edto_read": (_after(sq279, r"^YPDN     1946-2327[^\n]*$", _edto_rows(N, "29")), SQ279, {"edto_airports": N}),
    }


def _counts(flight: dict) -> dict[str, int]:
    unread = flight["alternates_unread"]
    return {
        "alternates": sum(1 for row in flight["alternates"] if row["airport"].startswith("Q")),
        "edto_airports": sum(1 for row in flight["edto"]["airports"] if row["airport"].startswith("Q")),
        **{table: sum(1 for row in unread if row["table"] == table)
           for table in ("destination_alternates", "edto_alternates", "fuel_enroute_airports")},
    }


@pytest.mark.parametrize("name", ["destination_unread", "edto_unread", "fuel_unread", "mixed_unread",
                                  "destination_read", "edto_read"])
def test_more_rows_than_any_cap_are_all_held_or_read_and_all_published(name: str) -> None:
    pages, source, expected = _cases()[name]
    flight = parse_lido(pages, f"SYNTHETIC-QA516-{name}.pdf")
    counts = _counts(flight)
    for key, value in expected.items():
        assert counts[key] == value, (key, counts)
    findings, warnings = analyse(flight)
    view = build_briefing_view(flight, findings, warnings, None, None, include_dashboard_only_panels=True)
    held = sum(counts[t] for t in ("destination_alternates", "edto_alternates", "fuel_enroute_airports"))
    assert sum(1 for item in findings if item["title"].endswith("row not read")) == held
    assert sum(1 for row in view["alternate_assessment_rows"] if (row.get("assessment") or {}).get("row_not_read")) \
        == counts["destination_alternates"]
    assert sum(1 for row in view["alternate_assessment_rows"] if str(row.get("airport")).startswith("Q")) \
        == counts["destination_alternates"] + counts["alternates"]
    assert len(view["edto"]["unread_rows"]) == counts["edto_alternates"]
    assert len(view["fuel_enroute_unread_rows"]) == counts["fuel_enroute_airports"]
    assert sum(1 for row in view["edto"]["airports"] if str(row.get("airport")).startswith("Q")) == counts["edto_airports"]


@pytest.mark.parametrize("name", ["destination_unread", "edto_unread", "destination_read"])
def test_the_pdf_prints_what_fits_and_states_what_it_leaves_to_the_dashboard(name: str) -> None:
    """A display limit says what it leaves out: page 4 (alternates) and page 5 (EDTO windows and reviews) print whole
    rows and then "+N further ... on the dashboard", where N is exactly the rows not printed - never a silent cut,
    never a failed page (page 4 raised "capacity exceeded" with seventy alternate rows)."""
    pages, source, _ = _cases()[name]
    flight = parse_lido(pages, f"SYNTHETIC-QA516-{name}.pdf")
    findings, warnings = analyse(flight)
    with tempfile.TemporaryDirectory() as scratch:
        pdf = Path(scratch) / "six-pages.pdf"
        render_combined_briefing(flight, findings, warnings, pdf, source_pdf_path=str(_corpus() / source))
        with fitz.open(pdf) as document:
            assert document.page_count == 6
            text = [" ".join(page.get_text().split()) for page in document]
    if name.startswith("destination"):
        page, unit, genuine = text[3], "alternate row(s)", ("YSSY", "YMML", "YMAV")
        heads = r"\b((?:Q|Y)[A-Z]{3})(?:/[0-9]{2}[LCR]?)? (?:ALTERNATE|PREFERRED) ·"  # each printed row's head
    else:
        page, unit, genuine = text[4], "EDTO airport window(s)", ("WAAA", "YPDN", "YPAD")
        heads = r"\b((?:Q|W|Y)[A-Z]{3})(?:/[0-9]{2}[LCR]?:| · REVIEW)"
    printed = set(re.findall(heads, page))
    stated = re.search(rf"\+(\d+) further {re.escape(unit)} on the dashboard", page)
    assert stated, f"no stated deferral on the page ({unit})"
    # Whole rows print in table order (the synthetic rows follow YMML / YPDN, so YMAV / YPAD are among the deferred);
    # every row is either printed or counted in the statement - exactly.
    assert len(printed & {_ident(i) for i in range(N)} | printed & set(genuine)) + int(stated.group(1)) == len(genuine) + N


def test_codex_qa516_capacity_case_holds_all_thirteen() -> None:
    """Codex's reproducer (output/pd-516-codex-qa-20261017/scripts/unread_capacity.py): thirteen invalid-runway rows
    QAAA-QAAM after YMML in the destination table; every one is held, in the parse and in the published view."""
    airports = ["QAA" + chr(65 + i) for i in range(13)]
    extra = "\n".join(a + "/99              700FT/2500M  0396  330 P007  0105 05817" for a in airports)
    pages = [re.sub(r"(?m)^(YMML/34[^\n]*)$", lambda m: m.group() + "\n" + extra, page) for page in _pages(SQ279)]
    flight = parse_lido(pages, "SYNTHETIC-QA516-CAPACITY.pdf")
    assert [row["airport"] for row in flight["alternates_unread"]] == airports
    findings, warnings = analyse(flight)
    view = build_briefing_view(flight, findings, warnings, None, None, include_dashboard_only_panels=True)
    assert [row["airport"] for row in view["alternate_assessment_rows"] if row["airport"] in airports] == airports


def test_a_second_damaged_row_of_an_airport_in_one_printing_is_held_not_reconciled_away() -> None:
    """Reconciliation is by slot: a damaged row is the copy of the row its airport has at the same slot in another
    printing. A second, different row of an airport inside one printing is a row of its own and is held (it was dropped
    whenever the airport was read anywhere)."""
    extra = "YMML/99              700FT/2500M  0396  330 P007  0105 05817"
    pages = _pages(SQ279)
    seen = {"n": 0}

    def second_printing_only(match):
        seen["n"] += 1
        return match.group(0) + ("\n" + extra if seen["n"] == 2 else "")

    mutated = [re.sub(r"(?m)^YMML/34[^\n]*$", second_printing_only, page) for page in pages]
    flight = parse_lido(mutated, "SYNTHETIC-QA516-SECOND-ROW.pdf")
    assert [row["airport"] for row in flight["alternates"]] == ["YSSY", "YMML", "YMAV"]
    assert [(row["airport"], row["text"]) for row in flight["alternates_unread"]] == [("YMML", " ".join(extra.split()))]


@pytest.mark.skipif(not os.environ.get("PILOTDRIVEN_APP_ROOT"), reason="PILOTDRIVEN_APP_ROOT (the app's cfp.mjs) is not set")
def test_the_app_parser_holds_exactly_the_same_rows() -> None:
    """Runtime parity: the same pages through the app's parseCfpPages hold the same rows (table, airport, text), in
    the same order, for every case - no row is cut in the app's parse response."""
    app = Path(os.environ["PILOTDRIVEN_APP_ROOT"])
    script = ("import fs from 'node:fs';import {parseCfpPages} from './cfp.mjs';"
              "const cases=JSON.parse(fs.readFileSync(process.argv[1],'utf8'));const out={};"
              "for(const [name,pages] of Object.entries(cases)){const p=parseCfpPages(pages.map((text,i)=>({pageNumber:i+1,text})),"
              "{fileName:'SYNTHETIC-QA516-'+name+'.pdf'}).pertinent;out[name]={unread:p.alternatesUnread.map(r=>[r.table,r.icao,r.text]),"
              "alternates:p.alternates.map(r=>r.icao),edto:p.edto.alternates.map(r=>r.icao)};}"
              "process.stdout.write(JSON.stringify(out));")
    cases = _cases()
    with tempfile.TemporaryDirectory() as scratch:
        request = Path(scratch) / "cases.json"
        request.write_text(json.dumps({name: pages for name, (pages, _, _) in cases.items()}))
        result = subprocess.run(["node", "--input-type=module", "-e", script, str(request)], cwd=app,
                                capture_output=True, text=True, timeout=600)
    assert result.returncode == 0, result.stderr
    app_rows = json.loads(result.stdout)
    for name, (pages, _, _) in cases.items():
        flight = parse_lido(pages, f"SYNTHETIC-QA516-{name}.pdf")
        odss = {"unread": [[row["table"], row["airport"], row["text"]] for row in flight["alternates_unread"]],
                "alternates": [row["airport"] for row in flight["alternates"]],
                "edto": [row["airport"] for row in flight["edto"]["airports"]]}
        assert app_rows[name] == odss, name

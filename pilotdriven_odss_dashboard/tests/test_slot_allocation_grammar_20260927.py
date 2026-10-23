"""SLOT-ALLOCATION-434 (independent QA of release 434, 27 Sep 2026, F3).

Production SQ322's updated briefing drew BIROS FL360 CTO 2100 CTOT 1527 on its dashboard while page 6 of its PDF said
"No slot-control allocation is printed in this OFP." Genuine page 1 prints
``* BOBCAT ALLOCATION: WPT-BIROS | FL-360 | CTO-2100 | CTOT-1527 *``; SQ352 prints
``BOBCAT ALLOCATION:WPT DOBAT FL:360 CTO:2202 CTOT:1627 (2MINS DELAY)``. The parser accepted whitespace and commas
between the fields and nothing else, so both read as no allocation, and the composition turned "not read" into "not
printed". The dashboard's value came from its own AI slot fill, not from either grammar.

The shared grammar (both runtimes, identical): the fields WPT, FL, CTO, CTOT in that order, optionally after a
``<SYSTEM> ALLOCATION`` label; between a key and its value nothing, spaces, or one of ``: - = –``; between fields spaces
or one of ``, | ; /``; the sequence may wrap across lines; times are 24-hour UTC clocks, with or without a colon or Z;
the level is a flight level (FL10-FL600). What the grammar cannot read is not absence: an allocation label of a flow
system, or a line printing WPT with CTO/CTOT, that does not read is held verbatim as printed-but-not-read, with its page
and why. Only an OFP that prints neither says no allocation is printed. All synthetic cases are LABELLED SYNTHETIC and
carry invented waypoints, levels and clocks: the grammar generalises over the print, never over a flight.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import fitz
import pytest

from app.analysis import run_odss_analysis
from app.odss.combined_brief import COMBINED_BRIEFING_SCHEMA_VERSION, render_combined_briefing
from app.odss.enroute_contact import ENROUTE_CONTACT_RULE, NO_ALLOCATION_SENTENCE, compose_enroute_contact
from app.odss.extraction_rules import EXTRACTION_RULES
from app.odss import parser as odss_parser
from app.odss.parser import extract_pages, parse_lido

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT.parent / "private_cfp_corpus"
FORM = "not in the WPT / FL / CTO / CTOT form"


def pages(*texts: str | list[str], start: int = 1) -> list[tuple[int, str]]:
    """LABELLED SYNTHETIC pages: each argument is one page (a string or its lines), numbered from ``start``."""
    return [(start + index, text if isinstance(text, str) else "\n".join(text)) for index, text in enumerate(texts)]


def remarks(*lines: str) -> str:
    return "\n".join(["OFP", "PAGE 1 OF 19 SIA999 AAA/BBB 04AUG26", "TEST AIRLINE - SUMMARY STANDARD CFP", "REMARKS:", *lines,
                      "EXCESS FUEL:", "1.INTAM 3200KG FUEL ALL FLEETS-9008"])


def read(system, waypoint, level, cto, ctot, note="", page=1):
    return {"allocation": {"system": system, "waypoint": waypoint, "level": level, "cto": cto, "ctot": ctot, "note": note, "page": page},
            "unread": None}


def unread(text, reason, page=1):
    return {"allocation": None, "unread": {"text": text, "page": page, "reason": reason}}


NEITHER = {"allocation": None, "unread": None}


def parse_slot_allocation(pages):
    return odss_parser.parse_slot_allocation(pages)

GRAMMAR_CASES = [
    # ---- printed forms that read
    ("spaced fields", pages(remarks("**BOBCAT ALLOCATION: WPT ZULAB FL 380 CTO 2328 CTOT 1752")),
     read("BOBCAT", "ZULAB", 380, "2328", "1752")),
    ("label wrapped onto its own line, commas, trailing delay note",
     pages(remarks("BOBCAT ALLOCATION:", "WPT KIPOR, FL360, CTO 2158, CTOT 1625(10MIN)DLY")),
     read("BOBCAT", "KIPOR", 360, "2158", "1625", "(10MIN)DLY")),
    ("hyphen and pipe separators inside decoration", pages(remarks("* BOBCAT ALLOCATION: WPT-TAPAN | FL-340 | CTO-0105 | CTOT-1942 *")),
     read("BOBCAT", "TAPAN", 340, "0105", "1942")),
    ("colon separators, no space after the label", pages(remarks("BOBCAT ALLOCATION:WPT RELAX FL:320 CTO:0002 CTOT:1845 (5MINS DELAY)")),
     read("BOBCAT", "RELAX", 320, "0002", "1845", "(5MINS DELAY)")),
    ("equals and semicolons under another flow system", pages(remarks("ATFM ALLOCATION - WPT=OKTAR; FL=300; CTO=1210; CTOT=0655")),
     read("ATFM", "OKTAR", 300, "1210", "0655")),
    ("clock times with a colon and Z", pages(remarks("BOBCAT ALLOCATION: WPT SUBUM FL 370 CTO 22:05Z CTOT 16:31Z")),
     read("BOBCAT", "SUBUM", 370, "2205", "1631")),
    ("slash separators", pages(remarks("BOBCAT ALLOCATION: WPT ABDAN / FL 330 / CTO 0045 / CTOT 1920")),
     read("BOBCAT", "ABDAN", 330, "0045", "1920")),
    ("en dash separators after the label and each key", pages(remarks("BOBCAT ALLOCATION \u2013 WPT\u2013KOBAL FL\u2013350 CTO\u20132130 CTOT\u20131555")),
     read("BOBCAT", "KOBAL", 350, "2130", "1555")),
    ("space before the label colon", pages(remarks("BOBCAT ALLOCATION : WPT MUTIS FL 350 CTO 2012 CTOT 1437")),
     read("BOBCAT", "MUTIS", 350, "2012", "1437")),
    ("the field sequence wrapped between two fields", pages(remarks("BOBCAT ALLOCATION: WPT-DESDI | FL-350 |", "CTO-2344 | CTOT-1811")),
     read("BOBCAT", "DESDI", 350, "2344", "1811")),
    ("the field sequence wrapped between a key and its value", pages(remarks("BOBCAT ALLOCATION: WPT GIRTO FL 360 CTO", "2117 CTOT 1540")),
     read("BOBCAT", "GIRTO", 360, "2117", "1540")),
    ("a blank line between the label and its fields", pages(remarks("BOBCAT ALLOCATION:", "", "WPT KOVAL FL 360 CTO 2158 CTOT 1625")),
     read("BOBCAT", "KOVAL", 360, "2158", "1625")),
    ("mixed case", pages(remarks("Bobcat Allocation: wpt Nokit fl 330 cto 0045 ctot 1920")),
     read("BOBCAT", "NOKIT", 330, "0045", "1920")),
    ("no label: the neutral system name, not an invented one", pages(remarks("WPT LAMOS FL380 CTO 2250 CTOT 1712")),
     read("SLOT", "LAMOS", 380, "2250", "1712")),
    ("printed on a later OFP page only", pages(remarks("NIL"), "PAGE 5 OF 19\nBOBCAT ALLOCATION: WPT SOPIT FL 360 CTO 2201 CTOT 1626"),
     read("BOBCAT", "SOPIT", 360, "2201", "1626", page=2)),
    ("an unreadable copy on page 1 and a readable one later: the readable one",
     pages(remarks("BOBCAT ALLOCATION: WPT SOPIT FL 360 CTO 2261 CTOT 1626"), "BOBCAT ALLOCATION: WPT SOPIT FL 360 CTO 2201 CTOT 1626"),
     read("BOBCAT", "SOPIT", 360, "2201", "1626", page=2)),
    # ---- printed but not read: held verbatim, never absence
    ("CTO that is not a clock", pages(remarks("BOBCAT ALLOCATION: WPT NOLAX FL 360 CTO 2460 CTOT 1527")),
     unread("BOBCAT ALLOCATION: WPT NOLAX FL 360 CTO 2460 CTOT 1527", "CTO 2460 is not a UTC clock time")),
    ("CTOT minutes that are not a clock", pages(remarks("BOBCAT ALLOCATION: WPT NOLAX FL 360 CTO 2100 CTOT 15:75")),
     unread("BOBCAT ALLOCATION: WPT NOLAX FL 360 CTO 2100 CTOT 15:75", "CTOT 15:75 is not a UTC clock time")),
    ("a level that is not a flight level", pages(remarks("BOBCAT ALLOCATION: WPT NOLAX FL 700 CTO 2100 CTOT 1527")),
     unread("BOBCAT ALLOCATION: WPT NOLAX FL 700 CTO 2100 CTOT 1527", "FL700 is not a flight level")),
    ("CTOT missing", pages(remarks("BOBCAT ALLOCATION: WPT NOLAX FL 360 CTO 2100")),
     unread("BOBCAT ALLOCATION: WPT NOLAX FL 360 CTO 2100", FORM)),
    ("fields out of order", pages(remarks("BOBCAT ALLOCATION: CTOT 1527 CTO 2100 WPT NOLAX FL 360")),
     unread("BOBCAT ALLOCATION: CTOT 1527 CTO 2100 WPT NOLAX FL 360", FORM)),
    ("a label with no fields", pages(remarks("BOBCAT ALLOCATION: TO BE ADVISED")),
     unread("BOBCAT ALLOCATION: TO BE ADVISED", FORM)),
    ("a wrapped label whose fields do not read: the label and its next line",
     pages(remarks("SLOT ALLOCATION:", "BIROS 360 2100 1527")),
     unread("SLOT ALLOCATION: BIROS 360 2100 1527", FORM)),
    ("field keywords without a label", pages(remarks("WPT NOLAX CTOT 1527")), unread("WPT NOLAX CTOT 1527", FORM)),
    ("a five-digit time", pages(remarks("BOBCAT ALLOCATION: WPT NOLAX FL 360 CTO 21000 CTOT 1527")),
     unread("BOBCAT ALLOCATION: WPT NOLAX FL 360 CTO 21000 CTOT 1527", FORM)),
    ("a long unreadable line is quoted to 120 characters",
     pages(remarks("BOBCAT ALLOCATION: " + "SEE ATTACHED SLOT MESSAGE " * 6)),
     unread(("BOBCAT ALLOCATION: " + "SEE ATTACHED SLOT MESSAGE " * 6)[:119].rstrip() + "…", FORM)),
    # ---- nothing printed: absence
    ("remarks without an allocation", pages(remarks("1.CHECK MEL 21-52-01")), NEITHER),
    ("another kind of allocation", pages(remarks("GATE ALLOCATION: B5", "EXCESS ALLOCATION: TANKER")), NEITHER),
    ("a CTOT word without an allocation", pages(remarks("EXPECT CTOT FROM ATC IF REGULATED")), NEITHER),
    ("a waypoint-log header", pages(remarks("WPT MT TT FL WIND COMP")), NEITHER),
    ("no pages", [], NEITHER),
]


@pytest.mark.parametrize("name,source,expected", GRAMMAR_CASES, ids=[case[0] for case in GRAMMAR_CASES])
def test_the_shared_grammar_reads_the_print_and_never_turns_unread_into_absent(name, source, expected):
    assert parse_slot_allocation(source) == expected


def _js_grammar() -> Path | None:
    configured = os.environ.get("PILOTDRIVEN_APP_ROOT")
    app_root = Path(configured) if configured else ROOT.parent.parent / "pd-code-e-helpyou-20260921"
    module = app_root / "cfp.mjs"
    return module if module.is_file() and shutil.which("node") else None


def test_the_dashboard_grammar_reads_every_case_exactly_as_the_pdf_grammar():
    module = _js_grammar()
    if module is None:
        pytest.skip("the app's cfp.mjs and Node are not available")
    script = ("import {parseSlotAllocation} from " + json.dumps(module.as_uri()) + ";import fs from 'node:fs';"
              "const cases=JSON.parse(fs.readFileSync(0,'utf8'));"
              "process.stdout.write(JSON.stringify(cases.map((c)=>parseSlotAllocation(c.map(([pageNumber,text])=>({pageNumber,text}))))));")
    result = subprocess.run(["node", "--input-type=module", "-e", script], input=json.dumps([case[1] for case in GRAMMAR_CASES]),
                            text=True, capture_output=True, check=True)
    js = json.loads(result.stdout)
    assert len(js) == len(GRAMMAR_CASES)
    assert [(case[0], parse_slot_allocation(case[1])) for case in GRAMMAR_CASES] == [(case[0], row) for case, row in zip(GRAMMAR_CASES, js)]


# ---------------------------------------------------------------- genuine sources

GENUINE = {
    # label: (file, waypoint, level, CTO, CTOT) - as each physical page 1 prints it
    "SQ366": ("SQ36604082026SIN.pdf", "BIROS", 380, "23:28", "17:52"),
    "SQ304": ("lido-briefing_SQ_304_12Jul2026_SIN_BRU.pdf", "BIROS", 360, "21:58", "16:25"),
    "SQ322": ("lido-briefing_SQ_322_16Aug2026_SIN_LHR.pdf", "BIROS", 360, "21:00", "15:27"),
    "SQ352": ("lido-briefing_SQ_352_15Aug2026_SIN_CPH.pdf", "DOBAT", 360, "22:02", "16:27"),
}
_PARSED: dict[str, dict] = {}


def genuine(name: str) -> dict:
    if name not in _PARSED:
        source = CORPUS / name
        if not source.is_file():
            pytest.skip(f"private corpus file {name} is not on this machine")
        _PARSED[name] = parse_lido(extract_pages(source), name)
    return _PARSED[name]


@pytest.mark.parametrize("label", sorted(GENUINE))
def test_every_genuine_printed_allocation_is_read_from_page_one(label):
    name, waypoint, level, cto, ctot = GENUINE[label]
    flight = genuine(name)
    bobcat = flight["bobcat"]
    assert bobcat is not None, label
    assert (bobcat["system"], bobcat["waypoint"], bobcat["flight_level"], bobcat["source_page"]) == ("BOBCAT", waypoint, level, 1)
    assert bobcat["cto_utc"][11:16] == cto and bobcat["ctot_utc"][11:16] == ctot
    assert flight["slot_allocation_unread"] is None
    composed = compose_enroute_contact(flight)
    assert composed["slot_control"]["waypoint"] == waypoint
    assert composed["slot_sentence"].startswith(f"BOBCAT {waypoint} FL{level}: CTOT {ctot.replace(':', '')}Z + ACTM ")
    assert composed["slot_sentence"] != NO_ALLOCATION_SENTENCE


def test_no_other_genuine_source_holds_an_allocation_or_an_unread_one():
    """Negative control over the whole private corpus: the grammar finds nothing where nothing is printed."""
    others = sorted(path for path in CORPUS.glob("*.pdf") if path.name not in {row[0] for row in GENUINE.values()})
    if not others:
        pytest.skip("private corpus is not on this machine")
    held = {path.name: (genuine(path.name)["bobcat"], genuine(path.name)["slot_allocation_unread"]) for path in others}
    assert {name: value for name, value in held.items() if value != (None, None)} == {}
    # 26 since 9 Oct 2026: David's genuine SQ437 MLE-SIN (8 Oct) and SQ438 SIN-MLE (7 Oct) OFPs joined the corpus
    # (ITEM 4, VRMM); neither prints an allocation.
    assert len(held) == 26


# ---------------------------------------------------------------- the composition: read, unread, stale, absent

def _flight(**overrides) -> dict:
    flight = {"route_waypoints": [{"name": "NOLAX", "fir_boundary": None, "actm_minutes": 334, "source_page": 9}],
              "scheduled_departure_utc": "2026-08-16T15:00:00Z", "source_evidence": {"page1": 1},
              "extraction_rules": EXTRACTION_RULES, "bobcat": None, "slot_allocation_unread": None, "notam_procedure_records": []}
    flight.update(overrides)
    return flight


def test_an_unread_allocation_is_stated_as_printed_and_not_read():
    composed = compose_enroute_contact(_flight(slot_allocation_unread={
        "text": "BOBCAT ALLOCATION: WPT NOLAX FL 360 CTO 2460 CTOT 1527", "source_page": 1, "reason": "CTO 2460 is not a UTC clock time"}))
    assert composed["slot_control"] is None
    assert composed["slot_unread"] == {"text": "BOBCAT ALLOCATION: WPT NOLAX FL 360 CTO 2460 CTOT 1527", "source_page": 1,
                                       "reason": "CTO 2460 is not a UTC clock time"}
    assert composed["slot_sentence"] == (
        'A slot-control allocation is printed on OFP p1 but was not read (CTO 2460 is not a UTC clock time): '
        '"BOBCAT ALLOCATION: WPT NOLAX FL 360 CTO 2460 CTOT 1527". Use the OFP\'s printed allocation; no CTOT + ACTM check was made.')


def test_a_held_extraction_older_than_the_grammar_does_not_assert_absence():
    composed = compose_enroute_contact(_flight(extraction_rules="2026-09-26-notam-heading-continuity-v3"))
    assert composed["slot_sentence"] == (
        "No slot-control allocation is held by this extraction (2026-09-26-notam-heading-continuity-v3), which predates "
        "the current parser; Create updated briefing re-reads the OFP.")
    assert composed["slot_sentence"] != NO_ALLOCATION_SENTENCE


def test_absence_is_stated_only_when_the_current_extraction_found_nothing_printed():
    assert compose_enroute_contact(_flight())["slot_sentence"] == NO_ALLOCATION_SENTENCE


def test_the_printed_system_and_page_are_the_ones_the_composition_names():
    composed = compose_enroute_contact(_flight(bobcat={"waypoint": "NOLAX", "flight_level": 360, "cto_utc": "2026-08-16T20:34:00+00:00",
                                                       "ctot_utc": "2026-08-16T15:00:00+00:00", "system": "ATFM", "source_page": 5}))
    assert composed["slot_control"]["system"] == "ATFM"
    assert composed["slot_control"]["source_pages"] == [5, 9]
    assert composed["slot_sentence"] == "ATFM NOLAX FL360: CTOT 1500Z + ACTM 05:34 = 2034Z, matches CTO 2034Z (OFP p5, p9)."


def test_an_allocation_held_before_the_grammar_named_its_system_still_reads_as_bobcat():
    """Saved analyses hold ``bobcat`` without ``system`` / ``source_page``: the old grammar read BOBCAT labels on page 1 only."""
    composed = compose_enroute_contact(_flight(bobcat={"waypoint": "NOLAX", "flight_level": 360, "cto_utc": "2026-08-16T20:34:00+00:00",
                                                       "ctot_utc": "2026-08-16T15:00:00+00:00"}))
    assert composed["slot_control"]["system"] == "BOBCAT" and composed["slot_control"]["source_pages"] == [1, 9]


# ---------------------------------------------------------------- the physical PDF page 6

_RENDERED: dict[str, str] = {}


def page_six(label: str, tmp_path_factory, mutate=None) -> str:
    key = label if mutate is None else f"{label}:{mutate.__name__}"
    if key not in _RENDERED:
        names = {**{k: v[0] for k, v in GENUINE.items()}, "SQ882": "lido-briefing_SQ_882_10Sep2026_SIN_HKG.pdf"}
        source = CORPUS / names[label]
        if not source.is_file():
            pytest.skip(f"private corpus file for {label} is not on this machine")
        root = tmp_path_factory.mktemp(key.replace(":", "-"))
        result = run_odss_analysis(source, root / "analysis", root / "reports", 1)
        payload = json.loads(Path(result["analysis_path"]).read_text(encoding="utf-8"))
        if mutate is not None:
            payload = mutate(payload)
        target = root / f"{label}.pdf"
        render_combined_briefing(payload["flight"], payload["findings"], payload.get("view", {}).get("warnings") or [], target,
                                 source_pdf_path=str(source), weather_charts=payload.get("weather_charts") or {})
        with fitz.open(target) as document:
            assert document.page_count == 6, key
            _RENDERED[key] = " ".join(document[5].get_text().split())
    return _RENDERED[key]


@pytest.mark.parametrize("label,waypoint,ctot", [("SQ322", "BIROS", "1527"), ("SQ352", "DOBAT", "1627")])
def test_page_six_prints_the_allocation_the_source_prints(label, waypoint, ctot, tmp_path_factory):
    text = page_six(label, tmp_path_factory)
    assert "No slot-control allocation is printed" not in text
    assert f"BOBCAT {waypoint} FL360: CTOT {ctot}Z + ACTM " in text


def test_page_six_prints_an_unread_allocation_as_printed_not_absent(tmp_path_factory):
    def unreadable_allocation(payload):
        payload["flight"]["slot_allocation_unread"] = {"text": "BOBCAT ALLOCATION: WPT NOLAX FL 360 CTO 2460 CTOT 1527",
                                                      "source_page": 1, "reason": "CTO 2460 is not a UTC clock time"}
        payload.get("view", {}).pop("enroute_contact", None)
        return payload
    text = page_six("SQ882", tmp_path_factory, unreadable_allocation)
    assert "No slot-control allocation is printed" not in text
    assert 'A slot-control allocation is printed on OFP p1 but was not read (CTO 2460 is not a UTC clock time): "BOBCAT ALLOCATION:' in text


def test_the_tokens_move_together():
    assert EXTRACTION_RULES == "2026-10-24-volcano-notice-stream-v25"
    assert ENROUTE_CONTACT_RULE == "enroute-contact-v16"
    assert COMBINED_BRIEFING_SCHEMA_VERSION == "2026-10-24-source-status-vocabulary-v115"

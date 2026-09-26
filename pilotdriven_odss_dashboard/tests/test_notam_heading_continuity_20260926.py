"""HEADING-CONTINUITY-432 (independent production QA of release 432, 26 Sep 2026, F2).

The genuine SQ322 OFP prints the heading `OAKX        KABUL FIR` as the last line of p70; its underline is the first line of
p71. The page text reads: ... `OAKX        KABUL FIR`, the running header `SIA 322/16Aug26/...`, the footer `Page 70 of
112`, then on p71 a blank line and the underline. Both NOTAM heading readers (`_parse_notam_fir_names`,
`_parse_notam_procedure_records`) required the underline on the very next line of the same page, so the Kabul heading was
not seen: the Kabul notices on pp71-72 (1G272/26, 1G216/26, 1G197/26) stayed under the previous airway-segment heading
`ZB/BIROSL750`, the composition bound them to the Lahore FIR (OPLR ACTM 05:20, lead 05:10 instead of OAKX 05:34 / 05:24),
the page-6 PDF grouped them under OPLR and the source FIR-name map lost KABUL. The same layout drops the FIR names of
SQ304 (WSJC SINGAPORE) and SQ352 (EDWW BREMEN).

The general rule (no flight, FIR, notice, frequency or time is special-cased): the NOTAM section is read as one stream in
which a page break is a line break - the page's running header, its package footer and the blank lines at its edges are
not text. A heading is a line whose underline (a hyphen rule) follows it; a line in the FIR / segment / series heading
grammar may have blank lines before its underline; a title is a line between two `=` bars. Every held record names the
page of its heading. Where the source is ambiguous the record is held with its owner unresolved, never the previous
owner: a FIR / segment heading printed without its underline directly above a notice, or a rule with no heading above
it. Airport, title and other headings end the enroute scope wherever they fall.

The synthetic pages below are LABELLED SYNTHETIC and reproduce the order the PDF text extraction prints a LIDO page in.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from app.odss.enroute_contact import compose_enroute_contact
from app.odss.parser import _parse_notam_fir_names, _parse_notam_procedure_records, extract_pages, parse_lido

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT.parent / "private_cfp_corpus"

HEADER = "SIA 900/01Jan26/ZZAA-ZZCC Reg:9VQAA OFP:1/0/0"
RULE = "---------------------"
ALPHA = ["1G899/26                      VALID: 01-JAN-26 0000 - 31-DEC-26 2359",
         "  ALL OVERFLIGHTS SHALL MONITOR 125.2MHZ."]
BETA = ["1G900/26                      VALID: 01-JAN-26 0000 - 31-DEC-26 2359",
        "  ALL OVERFLIGHTS SHALL COMPLY WITH TIBA PROCEDURE FOR BROADCAST INTENTIONS ON FREQ 125.2MHZ 10 MINS PRIOR",
        "  ENTERING TO FIR."]
GAMMA = ["1G901/26                      VALID: 01-JAN-26 0000 - 31-DEC-26 2359",
         "  ALL FLIGHTS SHALL CONTACT SYNTHETIC CONTROL ON 132.1MHZ."]


def page(number: int, total: int, body: list[str], *, header_first: bool = False) -> str:
    """LABELLED SYNTHETIC: one LIDO page as the text extraction prints it (furniture after the page's own lines)."""
    if header_first:
        return "\n".join([HEADER, " ", *body, " ", f"Page {number} of {total}"])
    return "\n".join([" ", *body, HEADER, f"Page {number} of {total}"])


def records(pages: list[str], route_names: set[str] | None = None) -> list[dict]:
    return _parse_notam_procedure_records(pages, (0, len(pages)), route_names)


def names(pages: list[str]) -> dict[str, str]:
    return _parse_notam_fir_names(pages, (0, len(pages)))


def record(recs: list[dict], notam_id: str) -> dict:
    found = [r for r in recs if r["notam_id"] == notam_id]
    assert len(found) == 1, f"{notam_id}: {found}"
    return found[0]


# ------------------------------------------------------------------------------------------ same page (control)

def test_same_page_heading_owns_its_notices_and_names_its_fir():
    pages = [page(1, 1, ["ZZAA        ALPHA FIR", RULE, *ALPHA, " ", "ZZBB        BETA FIR", RULE, *BETA])]
    recs = records(pages)
    beta = record(recs, "1G900/26")
    assert (beta["heading"], beta["heading_kind"], beta["fir"], beta["segment"]) == ("ZZBB BETA FIR", "fir", "ZZBB", None)
    assert (beta["source_page"], beta["heading_page"]) == (1, 1)
    assert names(pages) == {"ZZAA": "ALPHA", "ZZBB": "BETA"}


# ------------------------------------------------------------------------------------------ across a page break

@pytest.mark.parametrize("header_first", [False, True], ids=["furniture-after-text", "header-before-text"])
def test_a_heading_at_the_foot_of_a_page_owns_the_notices_under_its_underline_on_the_next(header_first):
    pages = [
        page(1, 2, ["ZZAA        ALPHA FIR", RULE, *ALPHA, " ", "ZZBB        BETA FIR", " "], header_first=header_first),
        page(2, 2, [RULE, *BETA], header_first=header_first),
    ]
    recs = records(pages)
    beta = record(recs, "1G900/26")
    assert (beta["heading"], beta["heading_kind"], beta["fir"]) == ("ZZBB BETA FIR", "fir", "ZZBB")
    assert (beta["source_page"], beta["heading_page"]) == (2, 1)
    alpha = record(recs, "1G899/26")
    assert alpha["fir"] == "ZZAA" and "BETA FIR" not in alpha["text"]
    assert names(pages) == {"ZZAA": "ALPHA", "ZZBB": "BETA"}


def test_a_bare_running_header_is_furniture_too():
    """The operator's running header in its shortest form (the reviewer's probe prints 'SIA SYNTHETIC QA'): the parser
    already treats a line opening 'SIA ' as furniture inside a notice; at a page edge it is furniture as well."""
    pages = [
        "\n".join(["ZZAA        ALPHA FIR", RULE, *ALPHA, "ZZBB        BETA FIR", "Page 1 of 2"]),
        "\n".join(["SIA SYNTHETIC QA", "", RULE, *BETA]),
    ]
    beta = record(records(pages), "1G900/26")
    assert (beta["fir"], beta["heading_kind"], beta["heading_page"]) == ("ZZBB", "fir", 1)
    assert names(pages) == {"ZZAA": "ALPHA", "ZZBB": "BETA"}


def test_blank_lines_between_a_fir_heading_and_its_underline_on_the_same_page():
    pages = [page(1, 1, ["ZZAA        ALPHA FIR", RULE, *ALPHA, " ", "ZZBB        BETA FIR", " ", " ", RULE, *BETA])]
    beta = record(records(pages), "1G900/26")
    assert (beta["fir"], beta["heading_kind"], beta["heading_page"]) == ("ZZBB", "fir", 1)
    assert names(pages)["ZZBB"] == "BETA"


def test_a_segment_heading_split_across_pages_opens_its_segment_scope():
    pages = [
        page(1, 2, ["ZZAA        ALPHA FIR", RULE, *ALPHA, " ", "SYNAA/SYNBBL750"]),
        page(2, 2, [RULE, *GAMMA]),
    ]
    gamma = record(records(pages, {"SYNAA", "SYNBB"}), "1G901/26")
    assert gamma["heading_kind"] == "segment" and gamma["fir"] is None
    assert gamma["segment"] == {"from": "SYNAA", "to": "SYNBB", "airway": "L750"}
    assert gamma["heading_page"] == 1


# ------------------------------------------------------------------------------------------ transitions that end the scope

def test_an_airport_heading_split_across_pages_ends_the_fir_scope():
    pages = [
        page(1, 2, ["ZZAA        ALPHA FIR", RULE, *ALPHA, " ", "ZZCC /ZZC   SYNTHETIC/AIRPORT"]),
        page(2, 2, [RULE, *GAMMA]),
    ]
    recs = records(pages)
    assert [r["notam_id"] for r in recs] == ["1G899/26"], "an airport section is never held under the FIR before it"
    assert "SYNTHETIC/AIRPORT" not in recs[0]["text"]


def test_a_title_split_across_pages_ends_the_fir_scope():
    pages = [
        page(1, 2, ["ZZAA        ALPHA FIR", RULE, *ALPHA, " ", "=========================================", "AREA ENROUTE DESTINATION - DESTINATION ALTERNATE(S)"]),
        page(2, 2, ["=========================================", *GAMMA]),
    ]
    recs = records(pages)
    assert [r["notam_id"] for r in recs] == ["1G899/26"]
    assert "AREA ENROUTE" not in recs[0]["text"]


def test_a_notice_line_before_a_title_bar_on_the_next_page_stays_in_the_notice():
    pages = [
        page(1, 2, ["ZZAA        ALPHA FIR", RULE, *ALPHA, "  F) SFC G) FL400"]),
        page(2, 2, ["===============================", "EXTENDED AREA AROUND DESTINATION", "===============================", "ZZBB        BETA FIR", RULE, *BETA]),
    ]
    recs = records(pages)
    assert record(recs, "1G899/26")["text"].endswith("F) SFC G) FL400")
    assert record(recs, "1G900/26")["fir"] == "ZZBB"


def test_a_notam_series_label_split_across_pages_continues_the_section():
    pages = [
        page(1, 2, ["ZZAA        ALPHA FIR", RULE, *ALPHA, " ", "ZZ A0001/26"]),
        page(2, 2, [RULE, *GAMMA]),
    ]
    recs = records(pages)
    assert record(recs, "1G901/26")["fir"] == "ZZAA", "a series label is a continuation inside the section"
    assert "A0001/26" not in record(recs, "1G899/26")["text"]


# ------------------------------------------------------------------------------------------ ambiguity fails safe

def test_a_fir_heading_printed_without_its_underline_above_a_notice_leaves_the_owner_unresolved():
    pages = [page(1, 1, ["ZZAA        ALPHA FIR", RULE, *ALPHA, " ", "ZZBB        BETA FIR", *BETA])]
    recs = records(pages)
    beta = record(recs, "1G900/26")
    assert beta["heading_kind"] == "unresolved" and beta["fir"] is None and beta["segment"] is None
    assert beta["heading"] == "ZZBB BETA FIR" and beta["heading_page"] == 1
    assert "BETA FIR" not in record(recs, "1G899/26")["text"]
    assert "ZZBB" not in names(pages), "a name is held only from a heading its underline confirms"


def test_a_rule_with_no_heading_above_it_inside_a_fir_section_leaves_the_owner_unresolved():
    pages = [page(1, 1, ["ZZAA        ALPHA FIR", RULE, *ALPHA, " ", RULE, *GAMMA])]
    gamma = record(records(pages), "1G901/26")
    assert gamma["heading_kind"] == "unresolved" and gamma["fir"] is None


def test_a_notice_sentence_in_the_fir_heading_grammar_stays_notice_text():
    body = ["1G902/26                      VALID: 01-JAN-26 0000 - 31-DEC-26 2359",
            "  WEST BOUND FLT OPTG OVER THE BAY OF BENGAL THROUGH SYNTHETIC FIR",
            "  BTN 1430/1730 SHALL CONTACT SYNTHETIC CONTROL ON 132.1MHZ."]
    pages = [page(1, 1, ["ZZAA        ALPHA FIR", RULE, *body])]
    held = record(records(pages), "1G902/26")
    assert held["fir"] == "ZZAA" and "THROUGH SYNTHETIC FIR BTN 1430/1730" in held["text"]


# ------------------------------------------------------------------------------------------ genuine sources

def genuine(name: str) -> dict:
    path = CORPUS / name
    if not path.is_file():
        pytest.skip(f"{name} is not on this machine")
    return parse_lido(extract_pages(path), name)


def test_genuine_sq322_kabul_notices_belong_to_the_kabul_heading_of_page_70():
    flight = genuine("lido-briefing_SQ_322_16Aug2026_SIN_LHR.pdf")
    held = {r["notam_id"]: r for r in flight["notam_procedure_records"]}
    for notam_id, page_number in (("1G272/26", 71), ("1G216/26", 71), ("1G197/26", 72)):
        r = held[notam_id]
        assert (r["heading"], r["heading_kind"], r["fir"], r["segment"]) == ("OAKX KABUL FIR", "fir", "OAKX", None), notam_id
        assert (r["heading_page"], r["source_page"]) == (70, page_number), notam_id
    assert flight["notam_fir_names"]["OAKX"] == "KABUL"
    assert not any(r["text"].rstrip().endswith("KABUL FIR") for r in flight["notam_procedure_records"])


def test_genuine_sq322_kabul_tiba_lead_derives_from_the_kabul_crossing():
    flight = genuine("lido-briefing_SQ_322_16Aug2026_SIN_LHR.pdf")
    composed = {p["notam_id"]: p for p in compose_enroute_contact(flight)["procedures"]}
    tiba = composed["1G216/26"]
    assert (tiba["fir"], tiba["association"], tiba["actm"], tiba["latest_actm"]) == ("OAKX", "fir_heading", "05:34", "05:24")
    assert tiba["printed_details"]["lead"] == "10 MINS PRIOR ENTERING TO FIR"
    for notam_id in ("1G272/26", "1G197/26"):
        assert composed[notam_id]["fir"] == "OAKX", notam_id
    named = [c for a in tiba["actions"] for c in a["conditions"] if c["kind"] == "fir_scope" and "KABUL" in c["text"]]
    assert named and all(c["result"] == "met" and c.get("note") == "OAKX" for c in named)


@pytest.mark.parametrize(("name", "icao", "fir_name"), [
    ("lido-briefing_SQ_304_12Jul2026_SIN_BRU.pdf", "WSJC", "SINGAPORE"),
    ("lido-briefing_SQ_352_15Aug2026_SIN_CPH.pdf", "EDWW", "BREMEN"),
])
def test_genuine_split_fir_headings_keep_their_names(name, icao, fir_name):
    assert genuine(name)["notam_fir_names"].get(icao) == fir_name


def test_every_genuine_record_names_the_page_of_its_heading():
    if not CORPUS.is_dir():
        pytest.skip("private corpus is not on this machine")
    for path in sorted(CORPUS.glob("*.pdf")):
        pages = extract_pages(path)
        flight = parse_lido(pages, path.name)
        for r in flight["notam_procedure_records"]:
            heading_page = r["heading_page"]
            assert isinstance(heading_page, int) and heading_page <= r["source_page"], (path.name, r["notam_id"])
            printed = " ".join(" ".join(line.split()) for line in pages[heading_page - 1].splitlines())
            assert " ".join(r["heading"].split()) in printed or r["heading"] in printed.replace(" ", ""), (path.name, r["notam_id"])


# ------------------------------------------------------------------------------------------ composition: unresolved owner

def test_a_record_whose_owner_is_unresolved_is_not_bound_to_any_crossing():
    flight = genuine("lido-briefing_SQ_322_16Aug2026_SIN_LHR.pdf")
    kabul = next(r for r in flight["notam_procedure_records"] if r["notam_id"] == "1G216/26")
    flight = {**flight, "notam_procedure_records": [{**kabul, "heading_kind": "unresolved", "fir": None, "segment": None}]}
    (row,) = compose_enroute_contact(flight)["procedures"]
    assert (row["fir"], row["association"], row["actm"], row["latest_actm"]) == ("", "unresolved", None, None)
    association = [c for c in row["conditions"] if c["kind"] == "association"]
    assert association == [{"kind": "association", "text": "section heading not established from the source layout", "result": "unresolved"}]
    assert row["applicability_state"] == "conditions_unresolved"

"""ITEM2-VOLCANIC: does ODSS recognise every volcano notice the OFP prints?

An offline audit of the 30 genuine corpus PDFs (24 Oct 2026) found 16 of 17 "VAA <volcano>" notices and all 20 VA
SIGMETs captured, no false positive - but four notices dropped and four cut short, because the reader went page by
page and kept one NOTAM per heading:

A. a heading at the foot of a page with its notice on the next (genuine SQ910 VAA BULUSAN 1B4120/26);
B. every NOTAM after the first under one heading (genuine SQ223 18 Aug AX114/26 and SQ223 16 Aug AX106/26, Darwin
   VAAC ash advisories with their +6/+12/+18 h clouds);
C. a volcanic-ash NOTAM printed under its FIR heading, no VAA heading (genuine SQ882 10 Sep 1A3438/26, Mount Krakatau);
D. a notice running onto the next page (four ASHTAMs; SQ223 16 Aug AX3654/26 ended at "E)ORANGE ALERT", before F)).

Synthetic pages mimic the LIDO layout and are LABELLED SYNTHETIC; genuine assertions read the private corpus.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.odss.enrichment import _parse_cfp_volcano_advisories

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT.parent / "private_cfp_corpus"
FALLBACK = datetime(2026, 8, 1, tzinfo=timezone.utc)
FOOTER = ["SIA 900/01Aug26/ZZAA-ZZBB Reg:9VSXX OFP:1/0/0", "Page {n} of 9"]


def page(n: int, lines: list[str], *, title: str | None = None) -> str:
    head = [" ", title] if title else [" "]
    return "\n".join(head + lines + [line.format(n=n) for line in FOOTER])


def notam_pages(*bodies: list[str]) -> list[str]:
    """LABELLED SYNTHETIC: page 1 is the plan, then a NOTAM section of ``bodies`` pages, then INTAM."""
    pages = ["PLAN PAGE"]
    for index, lines in enumerate(bodies):
        pages.append(page(index + 2, lines, title="NOTAM" if index == 0 else None))
    pages.append(page(len(pages) + 1, ["  1.OPS ALL FLEETS-0001", "  REFER TO OM-A FOR GUIDANCE ON SUSPECTED VOLCANIC",
                                       "  ASH CONTAMINATION."], title="INTAM"))
    return pages


AREA = ["====================================", "AREA ENROUTE DEPARTURE - DESTINATION",
        "====================================", " "]


def captured(pages):
    return [(row["volcano"], row["notam_id"], row["source_page"], row["text"])
            for row in _parse_cfp_volcano_advisories(pages, FALLBACK)]


def test_a_heading_at_the_foot_of_a_page_keeps_its_notice_on_the_next():
    pages = notam_pages(
        AREA + ["            VAA SYNTHA", "-----------------------",
                "1B0001/26                 VALID: 14-AUG-26 0131 - 15-AUG-26 0100 EST"],
        ["  SYNTHA VOLCANO (1246N 12403E) ON ALERT LVL 1.", "  F) SFC G) FL110"],
    )
    assert captured(pages) == [("SYNTHA", "1B0001/26", 2, "SYNTHA VOLCANO (1246N 12403E) ON ALERT LVL 1. F) SFC G) FL110")]


def test_every_notam_under_one_heading_is_a_notice_of_that_volcano():
    pages = notam_pages(AREA + [
        "            VAA SYNTHB", "------------------------",
        "AX0001/26                     VALID: 17-AUG-26 1424 - 18-AUG-26 1424",
        "  AX0001/26 ASHTAM", "  C)SYNTHB 602-00", "  E)ORANGE ALERT",
        "AX0002/26                      VALID: 17-AUG-26 2000 - 18-AUG-26 0200",
        "  AX0002/26 ASH ADVISORY", "  VOLCANO: SYNTHB 262000", "  FCST VA CLD +6 HR: 18/0130Z SFC/FL070",
        " ",
        "            WI A0003/26", "-----------------------",
        "1A0003/26                     VALID: 13-AUG-26 1000 - 18-AUG-26 1100",
        "  AIRSPACE RESERVATION FOR WEATHER MODIFICATION FLT.",
    ])
    assert [(v, n) for v, n, _, _ in captured(pages)] == [("SYNTHB", "AX0001/26"), ("SYNTHB", "AX0002/26")]


def test_a_notice_running_onto_the_next_page_is_held_whole():
    pages = notam_pages(
        AREA + ["            VAA SYNTHC", "------------------------",
                "AX0004/26                     VALID: 15-AUG-26 0529 - 16-AUG-26 0529",
                "  AX0004/26 ASHTAM", "  C)SYNTHC 602-00", "  E)ORANGE ALERT"],
        ["  F)SFC/FL040 VA NOT IDENTIFIABLE FM SATELLITE DATA", "  K)ADVISORY TERMINATED."],
    )
    [(_, _, _, text)] = captured(pages)
    assert text.endswith("E)ORANGE ALERT F)SFC/FL040 VA NOT IDENTIFIABLE FM SATELLITE DATA K)ADVISORY TERMINATED.")


def test_a_volcanic_ash_notam_under_its_fir_heading_is_a_notice_of_the_volcano_it_names():
    pages = notam_pages([
        "ZZZZ        SYNTHETIC FIR", "-----------------------",
        "1A0005/26                     VALID: 09-SEP-26 0500 - 10-SEP-26 0525",
        "  AIRSPACE RESERVATION FOR WEATHER MODIFICATION FLT.",
        "1A0006/26                     VALID: 08-SEP-26 2326 - 11-SEP-26 0700",
        "  ALL TFC ARE REQUESTED TO MAINTAIN CONTINUOUS VIGILANCE DUE TO",
        "  VOLCANIC ASH FROM ERUPTION OF MOUNT SYNTHD AND IMMEDIATELY REPORT",
        "  ANY VOLCANIC ASH SIGHTING TO ATC.",
    ])
    [(volcano, notam_id, page_number, _)] = captured(pages)
    assert (volcano, notam_id, page_number) == ("SYNTHD", "1A0006/26", 2)


def test_volcanic_wording_without_a_named_volcano_or_outside_the_notam_section_is_not_a_notice():
    pages = notam_pages([
        "ZZZZ        SYNTHETIC FIR", "-----------------------",
        "1A0007/26                     VALID: 09-SEP-26 0500 - 10-SEP-26 0525",
        "  PILOTS SHALL REPORT ANY VOLCANIC ASH ENCOUNTER TO ATC.",
    ])
    assert captured(pages) == []   # nor the INTAM company guidance on page 3


GENUINE = [
    # (file, volcano, NOTAM id, words the notice must hold)
    ("lido-briefing_SQ_910_15Aug2026_SIN_MNL.pdf", "BULUSAN", "1B4120/26", "F) SFC G) FL110"),             # A
    ("SQ22318082026SIN.pdf", "KRAKATAU", "AX114/26", "FCST VA CLD +18 HR"),                                # B
    ("lido-briefing_SQ_223_16Aug2026_SIN_PER.pdf", "KRAKATAU", "AX106/26", "NO FURTHER ADVISORIES"),       # B
    ("lido-briefing_SQ_882_10Sep2026_SIN_HKG.pdf", "KRAKATAU", "1A3438/26", "ERUPTION OF MOUNT KRAKATAU"),  # C
    ("lido-briefing_SQ_223_16Aug2026_SIN_PER.pdf", "KRAKATAU", "AX3654/26", "F)SFC/FL040"),                # D
    ("SQ22318082026SIN.pdf", "KRAKATAU", "AX3661/26", "MODEL GUIDANCE."),                                  # D
    ("lido-briefing_SQ_297_16Aug2026_SIN_CHC.pdf", "SEMERU", "AX9451/26", "GROUND REPORTS"),               # D
    ("SQ36507082026FCO.pdf", "STROMBOLI", "1W3205/26", "F) GND G) UNL"),                                   # D
]


@pytest.mark.parametrize("name,volcano,notam_id,words", GENUINE, ids=[f"{g[0][:24]}-{g[2]}" for g in GENUINE])
def test_genuine_volcano_notices_are_held_whole(name, volcano, notam_id, words):
    from app.odss.parser import extract_pages

    source = CORPUS / name
    if not source.is_file():
        pytest.skip(f"private corpus file {name} is not on this machine")
    held = {(row["volcano"], row["notam_id"]): row for row in
            _parse_cfp_volcano_advisories(extract_pages(source), FALLBACK)}
    assert (volcano, notam_id) in held, sorted(held)
    assert words in held[(volcano, notam_id)]["text"]

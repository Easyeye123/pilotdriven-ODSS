"""C1: a derived airport NOTAM line is analysis, never a copy of the NOTAM.

Release-22's mandatory private-corpus gate rendered the 28 pinned flights with
app ``b9c14b6`` and ODSS ``48d4d75``: 26 passed and two were refused before any
AWS change (``output/pd-boss-09sep-review/release-22/release-gates/
private-cfp-corpus/private-cfp-corpus-receipt.json``):

    SQ326-SIN-FRA: Concise briefing publication failed: Source Item E copied
                   into PDF: 1A4143/26
    SQ352-SIN-CPH: Concise briefing publication failed: Source Item E copied
                   into PDF: 1A1353/26

``check_concise_pdf`` refuses a published page that reproduces a source record,
and ``render_analysed_briefing`` deletes the PDF and raises when it does, so in
production a real flight carrying a notice of either shape makes Download PDF
fail outright. David, on the block-capital copies: "by copying in blocks and
capital is very hard to read... I always say this many many many times and yet
it's still there." A sentence-cased copy is still a copy.

The copy rule is re-stated here rather than imported from the derivation, so
these tests fail if the derivation ever decides for itself what counts as a
copy. The corpus sweep is the deliverable: the two receipts above are the
records that were caught, not the class.
"""
from __future__ import annotations

import gzip
import json
from pathlib import Path
import re

import pytest

from app.odss.concise_pdf_gate import normalized
from app.odss.notam_restriction_line import (
    CONTRACTIONS,
    NOTICE_TYPES,
    PHRASES,
    derive_notam_restriction_line,
)

FIXTURE = Path(__file__).parent / "fixtures/notam_restriction_source_corpus.json.gz"
ROWS = json.loads(gzip.decompress(FIXTURE.read_bytes()))["rows"]
PRIVATE_CORPUS = Path(__file__).resolve().parents[2] / "private_cfp_corpus"

# The gate's thresholds, held here as this test's own copy.
COPY_RUN = 18
COPY_MIN_WORDS = 3

# Fixed sentences the line may end with. Copied, not imported: a renderer that
# renames one must not be excused by the test that checks it.
MARKER_SENTENCES = (
    "This analysis could not reduce the notice to one restriction line; open the full NOTAM.",
    "This NOTAM has further content; open the full NOTAM.",
    "This analysis could not read a statement from the held NOTAM text.",
    "The source NOTAM text is not held in this analysis, so no concise line can be derived.",
)

# The two refused records, verbatim as ODSS holds them.
EKCH_A1353 = (
    "RWY 04R/22L PAVEMENT STRUCTURE AND FRICTION MAY VARY ON AFFECTED RWY SURFACE "
    "PARTS DUE TO PARTIAL RESURFACING."
)
EDDF_A4143 = (
    "OCA(H) VALUES RAISED: LPV APCH Z RWY 07C: A 652(324), B 665(337), C 692(364), "
    "D 701(373)FT. LPV APCH Y RWY 07C: A 652(324), B 665(337), C 692(364), D 701(373)FT. "
    "LPV APCH Z RWY 07R: A 652(325), B 665(338), C 673(346), D 715(388)FT. "
    "LPV APCH Y RWY 07R: A 652(325), B 665(338), C 673(346), D 715(388)FT. "
    "LPV APCH Z RWY 25L: A 726(365), B 738(377), C 747(386), D 757(396)FT. "
    "LPV APCH Y RWY 25L: A 729(368), B 742(381), C 750(389), D 760(399)FT. "
    "LPV APCH Z RWY 25C: A 691(328), B 700(337), C 706(343), D 714(351)FT. "
    "LPV APCH Y RWY 25C: A 694(331), B 703(340), C 709(346), D 716(353)FT DUE TO "
    "INADEQUATE PROTECTION PROVIDED IN MISSED APCH SEGMENT FOR SOME NAV SYSTEMS "
    "AUTHORIZED FOR LPV OPS."
)

# What release 22 actually published for them, from the same receipt. These are
# the strings the gate refused; they keep this test's own rule honest.
REFUSED_BY_RELEASE_22 = {
    EKCH_A1353: (
        "RWY 04R/22L pavement structure and friction may vary on affected RWY surface parts due to "
        "partial resurfacing. This analysis could not reduce the notice to one restriction line; "
        "open the full NOTAM."
    ),
    EDDF_A4143: (
        "OCA(H) values raised: LPV APCH Z RWY 07C: A 652(324), B 665(337), C 692(364), D 701(373)FT. "
        "This NOTAM has further content; open the full NOTAM."
    ),
}


def gate_copy_rule(line: str, source: str) -> bool:
    """``check_concise_pdf``'s copy rule, applied to one published line."""
    raw = normalized(source)
    words = raw.split()
    body = normalized(line)
    if len(words) >= COPY_MIN_WORDS and raw in body:
        return True
    return len(words) >= COPY_RUN and any(
        " ".join(words[index:index + COPY_RUN]) in body
        for index in range(len(words) - COPY_RUN + 1)
    )


def published_body(line: str) -> str:
    """The line without the fixed marker sentences it may end with."""
    body = line.strip()
    trimmed = True
    while trimmed:
        trimmed = False
        for sentence in MARKER_SENTENCES:
            if body.endswith(sentence):
                body = body[: -len(sentence)].rstrip()
                trimmed = True
    return body


def composed_words() -> set[str]:
    """Every word the derivation may print that the NOTAM does not hold."""
    words = {"for"}
    for expansion in CONTRACTIONS.values():
        words.update(re.split(r"[\s-]+", expansion.lower()))
    for _, replacement in PHRASES:
        words.update(replacement.lower().split())
    for _, label in NOTICE_TYPES:
        words.update(label.lower().split())
    for sentence in MARKER_SENTENCES:
        words.update(word for word in re.split(r"[\s,;:.]+", sentence.lower()) if word)
    return words


def test_the_copy_rule_this_module_checks_is_the_gate_s_own():
    """Release 22's own published lines must fail the rule stated above."""
    for source, published in REFUSED_BY_RELEASE_22.items():
        assert gate_copy_rule(published_body(published), source), published
    # A line that states the restriction in its own shape is not a copy.
    assert not gate_copy_rule("RWY 02L closed.", "RWY 02L CLSD.")


@pytest.mark.parametrize(("notam_id", "source", "subject"), [
    ("A1353/26", EKCH_A1353, "RWY 04R/22L"),
    ("A4143/26", EDDF_A4143, "RWY 07C"),
])
def test_the_refused_records_publish_an_analysed_line_the_gate_accepts(notam_id, source, subject):
    assert any(row["text"] == source for row in ROWS), f"{notam_id} must stay in the real corpus"
    derived = derive_notam_restriction_line(source)
    line = derived["text"]
    assert not gate_copy_rule(published_body(line), source), line
    assert not gate_copy_rule(line, source), line
    # It still says what the notice is about, and adds no word of its own.
    assert subject in line, line
    held = set(re.findall(r"[a-z]+", source.lower()))
    composed = composed_words()
    invented = [
        word for word in re.findall(r"[a-z]+", published_body(line).lower())
        if word not in held and word not in composed
    ]
    assert not invented, f"{notam_id} printed {invented} which its source does not hold"
    numbers = set(re.findall(r"\d+", source))
    assert not [
        number for number in re.findall(r"\d+", published_body(line)) if number not in numbers
    ], line


def test_the_minima_declaration_publishes_its_scope_without_the_value_list():
    """The 1A4143/26 shape: the heading and the runways its list names."""
    derived = derive_notam_restriction_line(EDDF_A4143)
    assert derived["basis"] == "restriction_clause"
    assert derived["text"].startswith("OCA(H) values raised: RWY 07C, RWY 07R, RWY 25L, RWY 25C.")
    assert "This NOTAM has further content; open the full NOTAM." in derived["text"]
    # Never an approach letter or a runway the list does not name for it.
    assert "652" not in derived["text"] and "APCH Z" not in derived["text"]


def test_the_single_clause_shape_cuts_before_its_cause_and_stays_unresolved():
    """The 1A1353/26 shape: no state word, so the notice keeps its marker."""
    derived = derive_notam_restriction_line(EKCH_A1353)
    assert derived["basis"] == "no_clause"
    assert derived["text"].startswith(
        "RWY 04R/22L pavement structure and friction may vary on affected RWY surface parts …"
    )
    assert derived["text"].endswith(
        "This analysis could not reduce the notice to one restriction line; open the full NOTAM."
    )
    assert "resurfacing" not in derived["text"]


def test_no_source_in_the_real_corpus_publishes_a_line_the_gate_would_refuse():
    sources = list(dict.fromkeys(row["text"] for row in ROWS))
    assert len(sources) >= 1100, f"expected the real corpus, saw {len(sources)} sources"
    refused = []
    for source in sources:
        line = derive_notam_restriction_line(source)["text"]
        if gate_copy_rule(published_body(line), source) or gate_copy_rule(line, source):
            refused.append(f"{source[:70]}\n   {line[:160]}")
    assert not refused, f"{len(refused)} of {len(sources)} derived lines copy their source:\n" + "\n".join(refused[:6])


def test_no_derived_line_in_the_real_corpus_invents_a_word_or_a_number():
    composed = composed_words()
    faults = []
    checked = 0
    for source in dict.fromkeys(row["text"] for row in ROWS):
        checked += 1
        body = published_body(derive_notam_restriction_line(source)["text"])
        held = set(re.findall(r"[a-z]+", source.lower()))
        numbers = set(re.findall(r"\d+", source))
        for word in re.findall(r"[a-z]+", body.lower()):
            if word not in held and word not in composed:
                faults.append(f'"{word}" in {body[:120]}')
        for number in re.findall(r"\d+", body):
            if number not in numbers:
                faults.append(f"number {number} in {body[:120]}")
    assert checked >= 1100
    assert not faults, f"{len(faults)} derived words or numbers are not in the source:\n" + "\n".join(faults[:6])


# The shortenings the guard falls back on must not buy a publishable line by
# dropping what limits the restriction. Each source below is a shape where the
# only non-copying line that keeps the state would have to lose its exception,
# its time window or its aircraft limit — so the row abstains instead.
WARR_SX25 = (
    "SX0025/26 AIP SUPPLEMENT WARR/SURABAYA VALIDITY:14MAY26-30APR27 RWY 10/28 CLSD DUE TO WIP "
    "DAILY 1700-2159 RMK: - EXCEPT MILITARY FLIGHT EXERCISE AND MEDIVAC HELICOPTER - NO PERMITTED "
    "TO ALTERNATE AERODROME AND TAKE OFF ALTERNATE - HEAVY EQUIPMENT PRESENT"
)
CLOSURE_STATE_RE = re.compile(r"\bclos(?:ed|ure|es)\b", re.I)
OUTAGE_STATE_RE = re.compile(r"\b(?:unserviceable|out of service|not available|unavailable)\b", re.I)


@pytest.mark.parametrize(("label", "source", "state", "qualifier"), [
    # WARR SX0025/26, verbatim: the closure is qualified by an exception two
    # bullets below it. A line stating the closure without that exception tells
    # a pilot the runway is shut to everything, which its own NOTAM denies.
    ("WARR SX25/26", WARR_SX25, CLOSURE_STATE_RE, "EXCEPT MILITARY"),
    # The same trap inside a declaration: the heading states the closure and
    # the list it introduces carries the exception.
    ("declared list", "RWY 04/22 CLOSED AS FOLLOWS: - 2200-0400 EXCEPT FOR MEDEVAC AIRCRAFT"
     " - 0400-0600 FOR ALL AIRCRAFT MOVEMENTS ON THE SOUTH SIDE", CLOSURE_STATE_RE, "EXCEPT"),
    # LGTS A2683/26 shape: the outage holds only inside the filed windows.
    ("dated outage", "AUG 16 1530-1930, AUG 23 1530-1930, AUG 30 1530-1930 ILS 'IMS' 109.7 RWY 16 U/S",
     OUTAGE_STATE_RE, "1530-1930"),
])
def test_a_shortening_never_states_a_restriction_without_what_qualifies_it(label, source, state, qualifier):
    line = derive_notam_restriction_line(source)["text"]
    if state.search(line):
        assert qualifier.lower() in line.lower(), f"{label} states its restriction without {qualifier}: {line}"


def test_a_shortening_still_drops_the_reason_and_keeps_the_window():
    """The rule above must not be a blanket refusal: a cause is still cut."""
    line = derive_notam_restriction_line(
        "RWY 25L CLOSED BETWEEN 2200 AND 0400 DAILY FOR PAVEMENT REPAIRS ON THE NORTHERN SECTION")["text"]
    assert line.startswith("RWY 25L closed between 2200 and 0400 daily")
    assert "northern" not in line.lower()


# Shaped on the real pattern behind fix round 2 ("a runway closure is never
# lost to a busier clause that states no closure"): when the clause that bites
# hardest cannot be shortened without dropping its exception, the row must
# abstain rather than publish the weaker clause beside it. Printing the taxiway
# work and marking the rest would leave the closure unsaid on the card.
HIDDEN_CLOSURE = (
    "RWY 07/25 CLOSED EXCEPT FOR EMERGENCY MEDICAL FLIGHTS AUTHORISED BY THE AERODROME OPERATOR "
    "ON THE NORTHERN SECTION. TWY B WIP."
)


def test_a_weaker_clause_never_stands_in_for_the_closure_it_would_hide():
    derived = derive_notam_restriction_line(HIDDEN_CLOSURE)
    assert "TWY B" not in derived["text"], derived["text"]
    assert "work in progress" not in derived["text"], derived["text"]
    assert "RWY 07/25" in derived["text"], derived["text"]
    assert derived["text"].endswith(MARKER_SENTENCES[0]), derived["text"]


CORPUS_RENDER_CASES = {
    "SQ326-SIN-FRA": "lido-briefing_SQ_326_16Aug2026_SIN_FRA.pdf",
    "SQ352-SIN-CPH": "lido-briefing_SQ_352_15Aug2026_SIN_CPH.pdf",
}


@pytest.mark.parametrize("case_id", sorted(CORPUS_RENDER_CASES))
def test_the_refused_private_corpus_flights_publish_their_download(case_id, tmp_path):
    """The production Download PDF call, on the two flights release 22 refused."""
    source = PRIVATE_CORPUS / CORPUS_RENDER_CASES[case_id]
    if not source.is_file():
        pytest.skip(f"private CFP corpus file {CORPUS_RENDER_CASES[case_id]} is not on this machine")
    from app.analysis import run_odss_analysis
    from app.odss.combined_brief import render_combined_briefing

    result = run_odss_analysis(source, tmp_path / "analysis", tmp_path / "reports", 1)
    payload = json.loads(Path(result["analysis_path"]).read_text(encoding="utf-8"))
    published = tmp_path / f"{case_id}_Operational_Flight_Briefing.pdf"
    render_combined_briefing(
        payload["flight"],
        payload["findings"],
        payload.get("view", {}).get("warnings") or [],
        published,
        source_pdf_path=str(source),
        weather_charts=payload.get("weather_charts") or {},
        include_audit_appendix=False,
    )
    assert published.is_file()
    # And the published pages hold no source record of this flight.
    import fitz

    with fitz.open(published) as document:
        body = " ".join(normalized(page.get_text()) for page in document)
    copied = [
        str(record.get("notam_id") or "")
        for record in payload["flight"].get("notams") or []
        if gate_copy_rule(body, record.get("item_e_text") or record.get("text") or "")
    ]
    assert not copied, f"{case_id} still copies {copied}"

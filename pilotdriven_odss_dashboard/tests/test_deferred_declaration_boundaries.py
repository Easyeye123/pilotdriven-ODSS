"""Every page-1 declaration the OFP prints is its own item, with its own words.

Production audit, 19 Sep 2026 (F2). David's SQ882 SIN/HKG OFP of 10 Sep prints
seven declarations, AA to GG. The parser recognised a closed list of sequence
labels (AA-EE) and a closed list of kinds (MEL, CDL, CDDL, IFEDDL, IN), so
``FF CDL 57-16`` and ``GG EN A35MEN-21-28871`` were never declarations at all:
their lines were appended to EE's remark. Everything downstream then worked on
a wing-slat seal that "said" UPLIFT DRY ICE FOR ALL CHILLERS, and the download
told catering to arrange dry ice for CDL 27-06 while CDL 57-16 and the
engineering notice were absent from all six pages.

The same closed lists lose declarations on four other corpus flights (SQ214
19 Aug ``FF CDL 53-66``, SQ606 ``AA WEIGHT AND BALANCE MANUAL`` and ``EE EN``,
SQ322 ``BB EN``, SQ482 ``BB INFO IN``), so this is the parser's boundary rule,
not one OFP.

The label sequence is the OFP's own structure: a declaration starts at a line
whose first token is a doubled capital letter later in the alphabet than the
previous declaration's. What follows the label decides only how the item is
classified, never whether it exists.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from app.odss.analysed_briefing_content import deferred_consequence_rows
from app.odss.deferred_dispatch import build_deferred_dispatch_gates
from app.odss.parser import _parse_deferred_items, extract_pages

CORPUS = Path(__file__).resolve().parents[2] / "private_cfp_corpus"
SOURCE_DECLARATIONS = json.loads(
    (Path(__file__).parent / "fixtures/page1_source_declarations.json").read_text()
)

# Page 1 of SQ882 SIN/HKG 10 Sep 2026 exactly as the OFP prints it, including
# the wrapped chiller line that starts in column 0.
SQ882_BLOCK = """\
               SINGAPORE AIRLINES - SUMMARY STANDARD CFP
REMARKS:
ATTN ALL CONCERN FR MAINTROL
AA MEL 25-20-50A
   MAINT ENTRY
   FROM CDL 004580 JCL D1 GALLEY COMP
213/214/215/309/310/311/312/314/315 AIR CHILLER NOT COLD
   FWD GALLEY
   PLS UPLIFT DRY ICE
BB MEL 31-19-03A
   VIDEO PB ON ECP NOT RESPONSIVE.
CC CDL 27-20
   MAINT ENTRY: O/B FLAP, O/B CUSHION SEAL FOUND WORN.
   RHW
   X PERFORMANCE [P]
DD CDL 27-25
   MAINT ENTRY: LH WING, AILERON TRAILING EDGE PANEL
   573BB AND 573DB SEALS FOUND TORN
   LH WING
EE CDL 27-06
   MAINT ENTRY: LH WING, SLAT #6 LOWER SEAL FOUND
   DETERIORATED (QTY: 04 OFF)
   LH WING
FF CDL 57-16
   MAINT ENTRY: LH WING, TRAILING EDGE ACCESS PANEL
   572HB SEAL FOUND TORN
   LH WING
GG EN A35MEN-21-28871
   MAINT ENTRY DUE EN A35MEN-21-28871 VCRU #3 DEACTIVATED
   AND RCCB 1003HW TRIPPED UNTIL 10 JUNE 2027
   UPLIFT DRY ICE FOR ALL CHILLERS

        PLAN 8
RTE NO SINHKG01              A350-941     CAPT TEST A B
"""


def _items(block: str) -> list[dict]:
    return _parse_deferred_items(block)


def _words(item: dict) -> str:
    """Everything the parsed item holds of the source, in any field."""
    return " ".join([
        *(
            str(item.get(field) or "")
            for field in ("source_declaration", "reference", "description", "company_remark")
        ),
        *(str(line.get("text") or "") for line in item.get("source_lines") or []),
    ])


def _rows(items: list[dict]) -> list[dict]:
    return deferred_consequence_rows(
        {"deferred_dispatch_gates": build_deferred_dispatch_gates(items)}
    )


def test_sq882_prints_seven_declarations_and_seven_are_held() -> None:
    items = _items(SQ882_BLOCK)

    assert [item["source_declaration"] for item in items] == [
        "AA MEL 25-20-50A",
        "BB MEL 31-19-03A",
        "CC CDL 27-20",
        "DD CDL 27-25",
        "EE CDL 27-06",
        "FF CDL 57-16",
        "GG EN A35MEN-21-28871",
    ]


def test_each_sq882_declaration_keeps_only_its_own_conditions() -> None:
    items = {item["source_declaration"][:2]: item for item in _items(SQ882_BLOCK)}

    slat, panel, notice = items["EE"], items["FF"], items["GG"]
    assert slat["description"] == "MAINT ENTRY: LH WING, SLAT #6 LOWER SEAL FOUND"
    assert slat["company_remark"] == "DETERIORATED (QTY: 04 OFF) LH WING"
    assert (panel["item_type"], panel["reference"]) == ("CDL", "57-16")
    assert panel["description"] == "MAINT ENTRY: LH WING, TRAILING EDGE ACCESS PANEL"
    assert panel["company_remark"] == "572HB SEAL FOUND TORN LH WING"
    assert (notice["item_type"], notice["reference"]) == ("EN", "A35MEN-21-28871")
    assert "VCRU #3 DEACTIVATED" in _words(notice)
    assert "UPLIFT DRY ICE FOR ALL CHILLERS" in _words(notice)
    # The wrapped column-0 line belongs to AA, the declaration it continues.
    assert "AIR CHILLER NOT COLD" in _words(items["AA"])
    for label in ("EE", "FF"):
        assert "DRY ICE" not in _words(items[label])
        assert "VCRU" not in _words(items[label])
    assert "572HB" not in _words(slat)


def test_an_action_printed_under_a_neighbour_is_not_this_defects_action() -> None:
    rows = _rows(_items(SQ882_BLOCK))

    def consequences(index: int) -> str:
        return " ".join(
            sentence
            for row in rows
            if index in row["source_item_indices"]
            for sentence in row["consequences"]
        )

    # EE (4) slat seal and FF (5) access-panel seal print no catering request.
    assert "dry-ice" not in consequences(4)
    assert "dry-ice" not in consequences(5)
    # AA (0) and GG (6) each print their own.
    assert "dry-ice uplift" in consequences(0)
    assert "dry-ice uplift" in consequences(6)


def test_no_declaration_loses_its_printed_identity_in_the_analysed_rows() -> None:
    text = " ".join(row["text"] for row in _rows(_items(SQ882_BLOCK)))

    for identity in ("25-20-50A", "31-19-03A", "27-20", "27-25", "27-06", "57-16",
                     "A35MEN-21-28871"):
        assert identity in text, identity


@pytest.mark.parametrize("count", [6, 7, 12, 26])
def test_the_label_sequence_is_open_ended(count: int) -> None:
    letters = [chr(ord("A") + index) for index in range(count)]
    block = "REMARKS:\n" + "".join(
        f"{letter * 2} MEL 2{index:01d}-10-0{index % 9 + 1}A\n   DEFECT {letter} FOUND\n"
        for index, letter in enumerate(letters)
    ) + "PLAN 1\n"

    items = _items(block)

    assert [item["source_declaration"][:2] for item in items] == [
        letter * 2 for letter in letters
    ]
    assert [item["description"] for item in items] == [
        f"DEFECT {letter} FOUND" for letter in letters
    ]


def test_a_skipped_label_still_starts_the_next_declaration() -> None:
    # SQ366 4 Aug and SQ322 16 Aug print AA then CC.
    items = _items(
        "AA MEL 29-10-03A - RESERVOIR AIR BLEED VALVE\n"
        "   DM HYD G RSVR AIR BLEED\n"
        "CC CDL 27-27 - FLAP TRACK FAIRING LINK BRACKET SEAL\n"
        "   FOUND DAMAGED\n"
        "PLAN 2\n"
    )

    assert [item["reference"] for item in items] == ["29-10-03A", "27-27"]
    assert items[0]["company_remark"] == "DM HYD G RSVR AIR BLEED"
    assert items[1]["company_remark"] == "FOUND DAMAGED"


def test_engineering_notice_with_revision_and_inline_request_is_its_own_item() -> None:
    # SQ606 6 Sep prints the notice, its revision and its request on one line,
    # directly under an unrelated MEL.
    items = _items(
        "FROM MAINTROL\n"
        "DD MEL 30-81-01A ICE DETECTION SYSTEM\n"
        "EE EN A35MEN-21-27688 R1 TO UPLIFT DRY ICE FOR ALL CHILLERS\n"
        "PLAN 3\n"
    )

    assert [item["item_type"] for item in items] == ["MEL", "EN"]
    assert items[0]["company_remark"] is None
    assert items[1]["reference"] == "A35MEN-21-27688 R1"
    assert items[1]["description"] == "TO UPLIFT DRY ICE FOR ALL CHILLERS"
    rows = _rows(items)
    ice_detection = " ".join(
        sentence for row in rows if 0 in row["source_item_indices"]
        for sentence in row["consequences"]
    )
    assert "dry-ice" not in ice_detection


@pytest.mark.parametrize(("header", "body"), [
    ("AA WEIGHT AND BALANCE MANUAL CHAPTER 8",
     "AFT CGO COMPT SINGLE LATCH U/S BETWEEN 42P & 42L"),
    ("BB INFO IN", "INFO NOTED.  APU REMAIN SERVICEABLE TO START ON GND."),
])
def test_a_declaration_of_unrecognised_kind_is_held_unresolved_not_dropped(
    header: str, body: str,
) -> None:
    block = (
        ("" if header.startswith("AA") else "AA MEL 21-26-08A\n   DM VENT AVNCS FILTER CLOGGED\n")
        + f"{header}\n   {body}\n"
        + "CC CDL 57-23 RH HINGED DOOR SEAL MISSING 30CM OF MATERIAL\n"
        + "PLAN 4\n"
    )

    items = _items(block)
    held = next(item for item in items if item["source_declaration"] == header)

    assert " ".join(body.split()) in " ".join(_words(held).split())
    # Its class is not guessed, and it says so.
    assert held["item_type"] == "UNCLASSIFIED"
    assert held["classification_status"] == "unresolved"
    assert held["governed_match_status"] == "manual_review_required"
    # Neither neighbour absorbs it.
    for other in items:
        if other is not held:
            assert " ".join(body.split()) not in " ".join(_words(other).split())
    assert items[-1]["reference"] == "57-23"


def test_same_governing_code_on_two_labels_stays_two_declarations() -> None:
    items = _items(
        "AA MEL 25-20-50A - NON-ESSENTIAL EQUIPMENT AND NEF\n"
        "   LAV L53 TOILET BOWL NIL WATER\n"
        "BB MEL 25-20-50A - NON-ESSENTIAL EQUIPMENT AND NEF\n"
        "   JCL GALLEY 2 AIR CHILLER NOT WORKING\n"
        "   TO UPLIFT DRY ICE\n"
        "PLAN 5\n"
    )

    assert len(items) == 2
    assert "DRY ICE" not in _words(items[0])
    assert "TOILET" not in _words(items[1])


def test_similar_adjacent_seal_defects_are_not_merged() -> None:
    items = _items(
        "EE CDL 27-06\n   MAINT ENTRY: LH WING, SLAT #6 LOWER SEAL FOUND\n   DETERIORATED\n"
        "FF CDL 27-06\n   MAINT ENTRY: RH WING, SLAT #2 LOWER SEAL FOUND\n   DETERIORATED\n"
        "PLAN 6\n"
    )

    assert [item["source_declaration"] for item in items] == ["EE CDL 27-06", "FF CDL 27-06"]
    assert "RH WING" not in _words(items[0])
    assert "LH WING" not in _words(items[1])


@pytest.mark.parametrize("continuation", [
    # Out of sequence: AA cannot follow CC.
    "AA BATTERY CHARGER FAULT NOTED",
    # Same label again is a wrapped line, not a new declaration.
    "CC DUCT CLAMP RE-TORQUED",
    # Two letters that are not a doubled label.
    "LH WING",
    "IN SIA/00-017 R1 REFERS",
    # Later in the alphabet, but indented as body text: headers sit at the
    # block's own margin, continuation text sits inside it.
    "   EE BAY DOOR SEAL ALSO CHECKED",
])
def test_a_wrapped_line_that_only_resembles_a_label_stays_in_its_declaration(
    continuation: str,
) -> None:
    items = _items(
        "BB MEL 21-60-11A\n   AFT GALLEY HEATER FAULT\n"
        "CC CDL 57-23\n   LH MLG HINGED DOOR AFT SEAL MISSING\n"
        f"{continuation}\n"
        "   X PERFORMANCE [P]\n"
        "PLAN 7\n"
    )

    assert [item["source_declaration"] for item in items] == ["BB MEL 21-60-11A", "CC CDL 57-23"]
    assert continuation.strip() in _words(items[1])


def test_opaque_ecdl_grouping_is_not_limited_to_the_first_five_labels() -> None:
    items = _items(
        "EE MEL 25-21-05A\n   SEAT 12A OUTSIDE ARMREST EXTEND STUCK\n"
        "FF SEAT 21A TRAY TABLE UNABLE TO STOW\n   X CLASS B\n   ECDL007905\n"
        "GG SEAT 21A TRAY TABLE UNABLE TO STOW\n   X CLASS B\n"
        "PLAN 8\n"
    )

    assert [item["item_type"] for item in items] == ["MEL", "UNCLASSIFIED"]
    assert items[0]["company_remark"] is None
    assert items[1]["source_group_tokens"] == ["FF", "GG"]
    assert items[1]["reference"] == "ECDL007905"


# --------------------------------------------------------------------------
# The real OFPs. The expected declarations were read from each page 1 by a
# person and cross-checked against a second extractor (Poppler ``pdftotext``);
# they are NOT minted from this parser's output.
# --------------------------------------------------------------------------

@pytest.mark.parametrize("filename", sorted(SOURCE_DECLARATIONS["flights"]))
def test_real_ofp_declarations_all_survive_parsing(filename: str) -> None:
    source = CORPUS / filename
    if not source.is_file():
        pytest.skip(f"private source {filename} not available")
    expected = SOURCE_DECLARATIONS["flights"][filename]

    items = _parse_deferred_items(extract_pages(source)[0])

    held_labels = [
        label
        for item in items
        for label in (item.get("source_group_tokens") or [str(item["source_declaration"])[:2]])
    ]
    assert held_labels == [row["declaration"][:2] for row in expected]
    by_label = {
        label: item
        for item in items
        for label in (item.get("source_group_tokens") or [str(item["source_declaration"])[:2]])
    }
    for index, row in enumerate(expected):
        item = by_label[row["declaration"][:2]]
        words = " ".join(_words(item).upper().split())
        for phrase in row["own_words"]:
            assert phrase in words, (row["declaration"], phrase)
        # No declaration carries a neighbour's identity or distinguishing words.
        for other_index, other in enumerate(expected):
            if other_index == index or by_label[other["declaration"][:2]] is item:
                continue
            for phrase in other["own_words"]:
                if phrase in " ".join(row["own_words"]):
                    continue
                assert phrase not in words, (row["declaration"], "borrowed", phrase)


def test_source_oracle_counts_label_lines_without_the_parser() -> None:
    """The fixture is checked against the raw page text, not against the parser."""
    checked = 0
    for filename, expected in SOURCE_DECLARATIONS["flights"].items():
        source = CORPUS / filename
        if not source.is_file():
            continue
        checked += 1
        raw = extract_pages(source)[0]
        for row in expected:
            pattern = r"(?m)^" + r"\s+".join(map(re.escape, row["declaration"].split())) + r"\s*$"
            assert re.search(pattern, raw), (filename, row["declaration"])
    if not checked:
        pytest.skip("private corpus not available")


# --------------------------------------------------------------------------
# An engineering notice (EN) is a kind the OFP prints. It is carried under
# its own word through every stage, like the information notice (IN) before it.
# --------------------------------------------------------------------------

def _analysed(block: str):
    from app.odss.engines import analyse
    from tests.test_deferred_dispatch_gates import _parsed_flight

    flight = _parsed_flight()
    flight["deferred_items"] = _items(block)
    findings, _warnings = analyse(flight)
    return flight, findings


def test_engine_carries_an_engineering_notice_verbatim_not_as_a_missing_cdl_reference() -> None:
    _flight, findings = _analysed(SQ882_BLOCK)

    notice = [f for f in findings if "A35MEN-21-28871" in json.dumps(f)]
    assert len(notice) == 1, [f["title"] for f in notice]
    finding = notice[0]
    assert finding["engine"] == "deferred_declaration"
    assert finding["title"] == "GG EN A35MEN-21-28871"
    assert "Engineering notice" in finding["summary"]
    assert "configuration-deviation" not in finding["summary"]
    assert any("VCRU #3 DEACTIVATED" in detail for detail in finding["details"])
    assert any("UPLIFT DRY ICE FOR ALL CHILLERS" in detail for detail in finding["details"])
    # The slat seal's own finding no longer carries the notice's words.
    slat = next(f for f in findings if f["engine"] == "cdl" and "27-06" in f["title"])
    assert "DRY ICE" not in json.dumps(slat)
    assert "57-16" not in json.dumps(slat)


def test_every_sq882_declaration_has_its_own_engine_finding() -> None:
    _flight, findings = _analysed(SQ882_BLOCK)
    titles = " | ".join(f["title"] for f in findings if f["engine"] in {"mel", "cdl", "cddl", "deferred_declaration"})

    for identity in ("25-20-50A", "31-19-03A", "27-20", "27-25", "27-06", "57-16", "A35MEN-21-28871"):
        assert identity in titles, (identity, titles)


def test_engineering_notice_gate_rides_with_the_technical_items() -> None:
    gates = build_deferred_dispatch_gates(_items(SQ882_BLOCK))
    order = [gate["item_types"][0] for gate in gates]

    assert order.index("EN") > order.index("MEL")
    assert order == sorted(order, key=["CDDL", "OPERATIONAL_RESTRICTION", "CDL", "MEL", "IN", "EN", "IFEDDL", "UNCLASSIFIED"].index)
    notice = next(gate for gate in gates if gate["item_types"] == ["EN"])
    assert notice["title"] == "EN A35MEN-21-28871"
    assert notice["source_item_indices"] == [6]


def test_unrecognised_kind_names_its_gate_by_its_printed_words_and_its_defect_by_its_body() -> None:
    # SQ606 6 Sep. "WEIGHT AND BALANCE MANUAL CHAPTER 8" stands where
    # "MEL 30-81-01A" would: it names the governing document. The defect is the
    # line printed under it, exactly as for a block-shaped MEL declaration.
    items = _items(
        "FROM MAINTROL\n"
        "AA WEIGHT AND BALANCE MANUAL CHAPTER 8\n"
        "   AFT CGO COMPT SINGLE LATCH U/S BETWEEN 42P & 42L\n"
        "BB MEL 25-20-50A LAV L53 TOILET BOWL NIL WATER\n"
        "PLAN 9\n"
    )

    assert items[0]["source_declaration"] == "AA WEIGHT AND BALANCE MANUAL CHAPTER 8"
    assert items[0]["description"] == "AFT CGO COMPT SINGLE LATCH U/S BETWEEN 42P & 42L"
    assert items[0]["company_remark"] is None
    gate = next(g for g in build_deferred_dispatch_gates(items) if g["source_item_indices"] == [0])
    assert gate["title"] == "WEIGHT AND BALANCE MANUAL CHAPTER 8"
    row = next(r for r in _rows(items) if 0 in r["source_item_indices"])
    assert "WEIGHT AND BALANCE MANUAL CHAPTER 8" in row["text"]
    assert "single latch U/S between 42P & 42L" in row["text"]


def test_unrecognised_kind_printed_on_one_line_keeps_its_words_as_the_defect() -> None:
    items = _items("AA MEL 21-26-08A\n   DM VENT\nBB CREW REST DOOR PLACARD MISSING\nPLAN 1\n")

    assert items[1]["source_declaration"] == "BB CREW REST DOOR PLACARD MISSING"
    assert items[1]["description"] == "CREW REST DOOR PLACARD MISSING"


# --------------------------------------------------------------------------
# A pack saved before this correction holds the old parse. Its download is
# re-created from that held analysis - and from the OFP the service still
# holds, which is the evidence the old parse misread.
# --------------------------------------------------------------------------

def test_a_download_recreated_from_an_old_stored_analysis_reads_the_held_ofp(tmp_path) -> None:
    import fitz

    from app.odss.combined_brief import render_combined_briefing
    from app.odss.parser import parse_lido

    source = CORPUS / "lido-briefing_SQ_882_10Sep2026_SIN_HKG.pdf"
    if not source.is_file():
        pytest.skip("private source for SQ882 10 Sep not available")
    stored = json.loads((Path(__file__).parent / "fixtures/deferred_subject_continuations.json").read_text())
    release_30_items = next(row["deferred_items"] for row in stored["flights"] if row["flight"] == "SQ882-10Sep")
    assert len(release_30_items) == 5, "fixture is release-30's own five-item parse"
    flight = parse_lido(extract_pages(source), source.name)
    flight["deferred_items"] = json.loads(json.dumps(release_30_items))
    held_before = json.loads(json.dumps(flight["deferred_items"]))

    path = tmp_path / "recreated.pdf"
    render_combined_briefing(flight, [], [], path, source_pdf_path=source)

    with fitz.open(path) as document:
        pages = [" ".join(page.get_text().split()) for page in document]
    whole = " ".join(pages)
    assert "57-16" in whole
    assert "A35MEN-21-28871" in whole
    slat = pages[2].split("27-06", 1)[1].split("MEL 25-20-50A", 1)[0]
    assert "dry-ice" not in slat, slat
    # The held analysis itself is evidence of what was stored; it is not rewritten.
    assert flight["deferred_items"] == held_before


def test_without_a_held_ofp_the_stored_parse_is_published_as_held(tmp_path) -> None:
    from app.odss.combined_brief import source_verified_flight

    flight = {"deferred_items": [{"item_type": "MEL", "reference": "25-20-50A", "description": "X", "company_remark": None}]}

    assert source_verified_flight(flight, None) is flight
    assert source_verified_flight(flight, tmp_path / "missing.pdf") is flight


def test_a_dispatcher_remark_that_begins_with_the_word_plan_is_not_the_plan_block() -> None:
    # SQ38 SIN/LAX 29 Aug prints "PLAN VIA PACOTS TRK 2" and "PLAN WITH PACKS
    # OFF" above its declarations. Only Lido's own "PLAN 27/0/1" line (or RTE
    # NO) ends the remarks block.
    items = _items(
        "REMARKS:\n"
        "PLAN VIA PACOTS TRK 2\n"
        "\n"
        "PLAN WITH PACKS OFF\n"
        "\n"
        "ATTN ALL CONCERN FR MAINTROL\n"
        "AA CDL 57-23 - HINGED DOOR SEAL\n"
        "   HINGED DOOR RUBBER SEAL TORN 6 INCHES\n"
        "   L/H MAIN L/G\n"
        "BB INFO IN\n"
        "   PLAN TO RECHECK AT NEXT STATION\n"
        "\n"
        "        PLAN 27/0/1\n"
        "RTE NO SINLAXT2              A350-941     CAPT TEST\n"
        "CC MEL 99-99-99A NEVER A DECLARATION\n"
    )

    assert [item["source_declaration"] for item in items] == [
        "AA CDL 57-23 - HINGED DOOR SEAL", "BB INFO IN",
    ]
    assert items[0]["company_remark"] == "HINGED DOOR RUBBER SEAL TORN 6 INCHES L/H MAIN L/G"
    assert items[1]["description"] == "PLAN TO RECHECK AT NEXT STATION"

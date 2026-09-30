"""TIMING-BASIS-432 (independent production QA of release 432, 26 Sep 2026, O2).

Release 432's own gate-6 PDFs of genuine SQ23, SQ314, SQ322 and SQ326 printed the FIR / COMMUNICATION validity clause
cut at "(at…" / "(at scheduled…"; the reviewer's signed-in production PDFs of the same four flights printed it whole.
The cause is the page, not the renderer: the gate renders without the production-held reference data (validated
airport surface figures, released Airport Notes, bound depressurisation profiles), so its page 6 carries three more
open items (AIRPORT ASSESSMENTS 6-7, REMAINING RELEASE INPUTS 8) and the FIR card, sharing that page, falls to the
ladder's clause-cut steps; production resolves those items and the card fits whole. The cut itself is the defect: the
shared compaction treated the validity clause - the window, whether it covers the crossing and the timing basis it was
evaluated at (scheduled departure or ATOT + ACTM) - like any other quoted clause.

The layout policy now: compaction cuts quoted condition clauses, never the validity clause. These tests render the four
genuine cards exactly as the gate does (live OPMET disabled by tests/conftest.py, no production reference data).
The 30 Sep ITEM1 format also admits source-held availability without a derived
crossing. Its compact `valid` label preserves the full window; the row must
retain its own source FIR/page and explicit time uncertainty, never a guessed
scheduled-departure-plus-ACTM basis.
"""
from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

import fitz
import pytest

from app.analysis import run_odss_analysis
from app.odss.combined_brief import render_combined_briefing

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT.parent / "private_cfp_corpus"
CASES = {
    "SQ23": "SQ02325072026JFK.pdf",
    "SQ314": "lido-briefing_SQ_314_15Aug2026_SIN_LGW.pdf",
    "SQ322": "lido-briefing_SQ_322_16Aug2026_SIN_LHR.pdf",
    "SQ326": "lido-briefing_SQ_326_16Aug2026_SIN_FRA.pdf",
}
ROW_START = re.compile(r"\+\d{2}:\d{2} [A-Z]{4}\b|Source FIR [A-Z]{4}; route/time unresolved\.")
CITATION = re.compile(r"\bNOTAM (?P<ids>[A-Z0-9]+/\d{2}(?:, [A-Z0-9]+/\d{2})*), OFP p(?P<page>\d+)(?=[;,])")


@pytest.fixture(scope="module")
def page_six(tmp_path_factory) -> dict[str, dict]:
    pages: dict[str, dict] = {}
    for label, name in CASES.items():
        source = CORPUS / name
        if not source.is_file():
            continue
        root = tmp_path_factory.mktemp(label)
        result = run_odss_analysis(source, root / "analysis", root / "reports", 1)
        payload = json.loads(Path(result["analysis_path"]).read_text(encoding="utf-8"))
        target = root / f"{label}.pdf"
        render_combined_briefing(payload["flight"], payload["findings"], payload.get("view", {}).get("warnings") or [], target,
                                 source_pdf_path=str(source), weather_charts=payload.get("weather_charts") or {})
        with fitz.open(target) as document:
            assert document.page_count == 6, label
            pages[label] = {"text": " ".join(document[5].get_text().split()),
                            "composed": payload["view"]["briefing"]["enroute_contact"]}
    if not pages:
        pytest.skip("private corpus is not on this machine")
    return pages


def fir_card(text: str) -> str:
    start = text.index("FIR / COMMUNICATION")
    end = text.index("FIR crossings (OFP ACTM)", start)
    return text[start:end]


def assert_printed_timing_basis(card: str, composed: dict) -> list[dict]:
    """Bind each printed row's own citation and complete validity to its source model.

    Availability has an approved shorter label, but never a shorter window or
    an invented crossing. The original timed-row contract remains strict.
    """
    assert "(at…" not in card and "(at scheduled…" not in card and "(at ATOT…" not in card, card
    starts = list(ROW_START.finditer(card))
    citations = list(CITATION.finditer(card))
    assert starts and len(starts) == len(citations), card
    rows = {row["notam_id"]: row for row in composed["procedures"]}
    published = []
    for index, start in enumerate(starts):
        block = card[start.start():starts[index + 1].start() if index + 1 < len(starts) else len(card)]
        own = list(CITATION.finditer(block))
        assert len(own) == 1, block
        citation = own[0]
        identities = citation["ids"].split(", ")
        assert all(identity in rows for identity in identities), identities
        line = next((line for line in composed["procedure_lines"] if line["notam_ids"] == identities), None)
        assert line is not None, identities
        assert line["source_pages"] == [int(citation["page"])], block
        row = rows[identities[0]]
        validity = next(condition for condition in row["conditions"] if condition["kind"] == "validity")
        window = re.escape(validity["text"])
        suffix = block[citation.end():]
        if line["actm"]:
            assert block.startswith(f"+{line['actm']} {line['fir']}"), block
            basis = composed["timing_basis"]
            assert basis["kind"] in {"scheduled_departure", "atot"} and basis["utc"]
            clock = basis["utc"][11:16].replace(":", "")
            kind = "scheduled departure" if basis["kind"] == "scheduled_departure" else "ATOT"
            result = {"met": "covers this crossing", "not_met": "outside this crossing", "unresolved": "not evaluable"}[validity["result"]]
            clause = rf"\bvalid(?:ity)? {window}: {result} \(at {kind} {clock}Z \+ ACTM\)"
            assert re.search(clause, suffix), block
        else:
            assert block.startswith(f"Source FIR {line['fir']}; route/time unresolved."), block
            assert row["actm"] is None and row["on_route"] is None and row["latest_actm"] is None
            assert row["heading"].startswith(f"{line['fir']} ") and row["heading_kind"] == "fir"
            assert type(row["heading_page"]) is int and 0 < row["heading_page"] <= row["source_page"]
            assert row["source_page"] == int(citation["page"])
            assert validity["result"] == "unresolved" and line["applicability_state"] == "conditions_unresolved"
            full = rf"\bvalidity {window}: not evaluable \(at no FIR crossing time held\)"
            compact = rf"\bvalid {window} \(time unresolved\)"
            assert re.search(full, suffix) or re.search(compact, suffix), block
            assert "covers this crossing" not in suffix and "+ ACTM" not in suffix, block
        final_state = {"conditions_held": "conditions held", "conditions_unresolved": "conditions unresolved", "not_applicable": "not applicable"}[line["applicability_state"]]
        assert final_state in suffix, block
        published.append(line)
    return published


@pytest.mark.parametrize("label", list(CASES))
def test_every_printed_validity_clause_keeps_its_timing_basis(page_six, label):
    if label not in page_six:
        pytest.skip(f"{label} source is not on this machine")
    case = page_six[label]
    assert_printed_timing_basis(fir_card(case["text"]), case["composed"])


def test_the_page_still_defers_rather_than_failing_closed(page_six):
    # Count the actual own-model states independently of the PDF formatter.
    for label, case in page_six.items():
        text, composed = case["text"], case["composed"]
        counts = Counter(row["applicability_state"] for row in composed["procedures"])
        compact = (f"No approved early-call rule held. {len(composed['procedures'])} source-held ATC/communications notices: "
                   f"{counts['conditions_held']} conditions met, {counts['conditions_unresolved']} unresolved, "
                   f"{counts['not_applicable']} not applicable.")
        assert (compact in text or composed["state_sentence"] in text) and "FIR crossings (OFP ACTM):" in text, label
        assert composed["provenance"] in text and not composed["required_calls"], label
        card = fir_card(text)
        published = assert_printed_timing_basis(card, composed)
        deferred = re.findall(r"\+(\d+) further rows on the dashboard \(", card)
        assert len(deferred) == 1 and len(published) + int(deferred[0]) == len(composed["procedure_lines"]), card
        assert any(line["notam_ids"] == ["1G216/26"] for line in published), label


@pytest.mark.parametrize("before,after", [
    ("OFP p108;", "OFP p1080;"),
    ("scheduled departure 0215Z + ACTM", "scheduled departure 0315Z + ACTM"),
    ("Source FIR KZDC; route/time unresolved.", "Source FIR KZNY; route/time unresolved."),
    ("valid 02-JUN-26 1822 - 02-JUN-27 2359 (time unresolved)",
     "valid 02-JUN-26 1822 - 02-JUN-27 2359: covers this crossing (at scheduled departure 0215Z + ACTM)"),
])
def test_genuine_row_timing_or_own_citation_corruption_is_rejected(page_six, before, after):
    if "SQ23" not in page_six:
        pytest.skip("SQ23 source is not on this machine")
    case = page_six["SQ23"]
    card = fir_card(case["text"])
    assert before in card
    with pytest.raises(AssertionError):
        assert_printed_timing_basis(card.replace(before, after, 1), case["composed"])


# ------------------------------------------------------------------------------------------ the shared compaction policy

SUMMARY = ("ATC provision · validity 01-JUL-26 0000 - 31-DEC-26 2359: covers this crossing (at ATOT 1800Z + ACTM) · "
           "route N644 DOBAT LAHORE ACC WEST 124.100 MHZ 118.950 MHZ: on the filed route · direction OAKX → OPKR/OPLR: met · "
           "DRG THE NON AVAILABILITY OF ATS (ATS) IN KABUL FIR: not evaluable from the OFP · conditions unresolved")


@pytest.mark.parametrize("limit", [72, 44, 24])
def test_every_cut_keeps_the_validity_clause_its_timing_basis_and_the_state(limit):
    from app.odss.operational_format import compact_conditions_summary
    parts = compact_conditions_summary(SUMMARY, limit).split(" · ")
    assert parts[1] == "validity 01-JUL-26 0000 - 31-DEC-26 2359: covers this crossing (at ATOT 1800Z + ACTM)"
    assert parts[0] == "ATC provision" and parts[-1] == "conditions unresolved"
    assert all(len(part) <= limit for part in parts[2:-1]) and any(part.endswith("…") for part in parts[2:-1])


def test_the_last_resort_counts_the_other_clauses_and_never_hides_the_timing_or_the_state():
    from app.odss.operational_format import compact_conditions_summary
    assert compact_conditions_summary(SUMMARY, 0) == (
        "ATC provision · validity 01-JUL-26 0000 - 31-DEC-26 2359: covers this crossing (at ATOT 1800Z + ACTM) · "
        "+3 further condition(s) on the dashboard · conditions unresolved")
    assert compact_conditions_summary("validity 01-JUL-26 0000 - 31-DEC-26 2359: outside this crossing (at scheduled departure 0215Z + ACTM) · not applicable", 0) == (
        "validity 01-JUL-26 0000 - 31-DEC-26 2359: outside this crossing (at scheduled departure 0215Z + ACTM) · not applicable")
    assert compact_conditions_summary(SUMMARY, None) == SUMMARY

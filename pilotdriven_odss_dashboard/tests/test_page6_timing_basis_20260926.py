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
"""
from __future__ import annotations

import json
import re
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
VALIDITY = re.compile(r"validity [^:;]+?: (?:covers this crossing|outside this crossing|not evaluable) \((?P<basis>[^)]*)\)")


@pytest.fixture(scope="module")
def page_six(tmp_path_factory) -> dict[str, str]:
    pages: dict[str, str] = {}
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
            pages[label] = " ".join(document[5].get_text().split())
    if not pages:
        pytest.skip("private corpus is not on this machine")
    return pages


def fir_card(text: str) -> str:
    start = text.index("FIR / COMMUNICATION")
    end = text.index("FIR crossings (OFP ACTM)", start)
    return text[start:end]


@pytest.mark.parametrize("label", list(CASES))
def test_every_printed_validity_clause_keeps_its_timing_basis(page_six, label):
    if label not in page_six:
        pytest.skip(f"{label} source is not on this machine")
    card = fir_card(page_six[label])
    assert "(at…" not in card and "(at scheduled…" not in card and "(at ATOT…" not in card, card
    rows = len(re.findall(r"\bNOTAM [A-Z0-9]+/\d{2}(?:, [A-Z0-9]+/\d{2})*, OFP p", card))  # one per printed notice row
    clauses = [m.group("basis") for m in VALIDITY.finditer(card)]
    assert rows and len(clauses) == rows, (label, rows, clauses, card)
    assert all(re.fullmatch(r"at (?:scheduled departure|ATOT) \d{4}Z \+ ACTM", basis) for basis in clauses), clauses


def test_the_page_still_defers_rather_than_failing_closed(page_six):
    # The four cards keep their state line and the crossing line; nothing fails closed for the kept clause.
    for label, text in page_six.items():
        assert "No approved early-call rule is held." in text and "FIR crossings (OFP ACTM):" in text, label


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

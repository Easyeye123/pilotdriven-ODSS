"""R2 - "CUT OUT ALL the damn reminder words".

David, 22 Sep 2026 13:38-13:40, relayed by Jabe; the agreed requirement
(output/pd-boss-feedback-review-20260922/FIX-LIST.md item 2): one general
statement on the front page, and no generic review / cross-check /
confirmation / refresh reminder anywhere else in the briefing. The
independent review of 23 Sep (output/pd-r2-wording-review-408-20260923)
reopened R2: counting the one banner was not the requirement.

What must stay: the one page-1 statement, facts and states (what is held,
what is unresolved, what is incomplete), source quotations, MEL/CDL
declarations and operational restrictions. What must go: the sentence that
tells the reader to review, confirm, cross-check or refresh something - on
the six pages the pilot downloads and in every analysis string the dashboard
prints.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import re

import fitz
import pytest

from app.analysis import run_odss_analysis
from app.odss.briefing import _SIGMET_TIME_DISPOSITION
from app.odss.combined_brief import render_combined_briefing
from app.odss.engines import _HAZARD_REVIEWS
from app.odss.operational_format import CREW_REVIEW, deferred_gate_value
from app.odss.runway_closure_schedule import RESIDUAL_REVIEW_SENTENCE
from app.odss.weather_timing import summarize_taf_for_window


CORPUS = Path(__file__).resolve().parents[2] / "private_cfp_corpus"
# The two flights the reviewer captured on 404, and a distinct control.
FLIGHTS = {
    "SQ303": "SQ30316072026BRU 81.pdf",
    "SQ365": "SQ36507082026FCO.pdf",
    "SQ910": "SQ91021082026SIN.pdf",
}

# App-authored reminder prose. Sentence-case phrases only: raw source text is
# block capitals and is not this module's business.
REMINDER = re.compile(
    r"review required|review-required|manual review|must be confirmed|before use|"
    r"cross-check|cross check|refresh current products|refresh from the latest|dispatch confirmation|"
    r"confirmation required|verification required|"
    r"\bconfirm (?:the|those|route|current|every|any)\b|"
    r"(?<!not )\bverify (?:the|every|against|current)\b|"
    r"\breview (?:the|current|official|level)\b",
    re.I,
)
# Raw source quotations carried in the analysis: never rewritten, never
# audited here.
SOURCE_KEYS = {
    "text", "raw", "icao_message", "item_e", "source_text", "company_remark",
    "description", "restriction", "raw_text", "notam_text", "body_text", "remark",
    "source_declaration", "note_text", "personal_notes", "e_line",
}

_RENDERED: dict[str, dict] = {}


def rendered(key: str, tmp_path_factory) -> dict:
    if key in _RENDERED:
        return _RENDERED[key]
    source = CORPUS / FLIGHTS[key]
    if not source.is_file():
        pytest.skip(f"private CFP corpus file {FLIGHTS[key]} is not available")
    root = tmp_path_factory.mktemp(f"r2-{key}")
    result = run_odss_analysis(source, root / "analysis", root / "reports", 1)
    payload = json.loads(Path(result["analysis_path"]).read_text(encoding="utf-8"))
    path = root / f"{key}_Flight_Briefing.pdf"
    render_combined_briefing(
        payload["flight"], payload["findings"], payload.get("view", {}).get("warnings") or [], path,
        weather_charts=payload.get("weather_charts") or {},
    )
    with fitz.open(path) as document:
        pages = [page.get_text() for page in document]
    _RENDERED[key] = {"payload": payload, "pages": pages}
    return _RENDERED[key]


def reminder_lines(page_text: str) -> list[str]:
    """Lines of app prose that still tell the reader to review something."""
    found = []
    for line in page_text.replace(CREW_REVIEW, " ").splitlines():
        if not re.search(r"[a-z]", line):
            continue  # block capitals: source quotation or a David-format label
        if REMINDER.search(line):
            found.append(" ".join(line.split()))
    return found


def strings(node, path="$"):
    if isinstance(node, dict):
        for key, value in node.items():
            if key in SOURCE_KEYS:
                continue
            yield from strings(value, f"{path}.{key}")
    elif isinstance(node, list):
        for value in node:
            yield from strings(value, f"{path}[]")
    elif isinstance(node, str) and not re.fullmatch(r"[a-z0-9_-]+", node):
        yield path, node  # identifier-shaped values are status codes, not prose


@pytest.mark.parametrize("key", sorted(FLIGHTS))
def test_the_general_statement_is_printed_once_on_page_one_only(key, tmp_path_factory):
    pages = rendered(key, tmp_path_factory)["pages"]
    assert len(pages) == 6
    assert pages[0].count(CREW_REVIEW) == 1
    assert [page.count(CREW_REVIEW) for page in pages[1:]] == [0, 0, 0, 0, 0]


@pytest.mark.parametrize("key", sorted(FLIGHTS))
def test_no_page_carries_a_generic_reminder(key, tmp_path_factory):
    pages = rendered(key, tmp_path_factory)["pages"]
    offending = {index + 1: reminder_lines(page) for index, page in enumerate(pages)}
    offending = {page: lines for page, lines in offending.items() if lines}
    assert not offending, json.dumps(offending, indent=1)


@pytest.mark.parametrize("key", sorted(FLIGHTS))
def test_analysis_strings_the_dashboard_prints_carry_no_generic_reminder(key, tmp_path_factory):
    payload = rendered(key, tmp_path_factory)["payload"]
    offending = sorted({f"{path}: {value[:140]}" for path, value in strings(payload) if REMINDER.search(value)})
    assert not offending, "\n".join(offending[:40])


def test_sq303_keeps_its_facts_declarations_and_publication_state(tmp_path_factory):
    pages = rendered("SQ303", tmp_path_factory)["pages"]
    analysis = " ".join(pages[1].split())
    # The unresolved destination restriction stays as a fact, without the suffix.
    assert "Published RWY 02L/20R restriction could not be resolved for the applicable destination window" in analysis
    # The route-airspace card keeps its count, pages and the non-inference.
    assert re.search(r"\d+ source-held route-airspace notice\(s\) \(OFP p", analysis)
    assert "no polygon intersection is inferred" in analysis
    # The deferred declarations stay on the technical page.
    technical = " ".join(pages[2].split())
    for declaration in ("CDL 57-23", "MEL 44-15-02A", "MEL 21-60-11A", "MEL 25-22-01A"):
        assert declaration in technical, declaration
    # The closing page keeps the publication state itself.
    closing = " ".join(pages[5].split())
    assert ("Conditional briefing; the unresolved assessments above prevent an automated release conclusion." in closing
            or "No unresolved automated source condition; crew operational release remains separate." in closing)


def test_sq365_keeps_the_unevaluated_schedule_fact(tmp_path_factory):
    analysis = " ".join(rendered("SQ365", tmp_path_factory)["pages"][1].split())
    assert "Other scheduled clauses in this notice are not evaluated" in analysis


# ---- builders that need no corpus: they fail on the 408 wording today ----

def test_hazard_review_titles_and_warnings_state_the_gap_not_an_instruction():
    for review in _HAZARD_REVIEWS:
        for field in ("review_title", "review_summary", "unresolved_warning"):
            assert not REMINDER.search(review[field]), (review["review_key"], field, review[field])


def test_sigmet_time_dispositions_name_a_state():
    assert all("REVIEW" not in value for value in _SIGMET_TIME_DISPOSITION.values()), _SIGMET_TIME_DISPOSITION


def test_the_technical_status_tile_names_the_declaration_not_an_instruction():
    value = deferred_gate_value({"status": "dispatch-confirmation-required", "item_types": [], "title": "CDL 57-23"})
    assert value != "CONFIRM"
    assert not REMINDER.search(value)


def test_an_incomplete_taf_window_states_the_gap_without_the_suffix():
    window_start = datetime(2026, 7, 25, 20, 30, tzinfo=timezone.utc)
    window_end = datetime(2026, 7, 25, 22, 30, tzinfo=timezone.utc)
    summary = summarize_taf_for_window("FT 241700 2418/2518 16009KT 9999 FEW015 SCT020=", window_start, window_end)
    assert summary is not None
    assert summary["status"] == "review_required"  # the state is unchanged
    assert summary["window_status_text"] == "Forecast coverage is incomplete."


def test_the_residual_schedule_sentence_states_what_is_not_evaluated():
    assert RESIDUAL_REVIEW_SENTENCE == "Other scheduled clauses in this notice are not evaluated."

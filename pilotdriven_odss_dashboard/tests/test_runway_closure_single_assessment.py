"""One notice, one time basis, one assessment - on every surface.

Production audit, 19 Sep 2026 (F1). SIA605 RKSI-WSSS, ETA Tue 8 Sep 2128Z,
planned RWY 20R. WSSS SX120/25 prints four dated closure regimes for two
runways: 02L/20R on SUN and WED, 02C/20C on TUE and FRI, both 1730-2130Z.

The download said, on pages 1 and 4, that RWY 02C/20C closes 1730-2130Z and
the ETA is within it - and on page 2, and on the dashboard card, that a
"RWY 02L/20R restriction could not be resolved". Both came from the same
evaluator. The Airports page asked it about every runway the notice names; the
card asked it only about the planned runway, got no regime for a Tuesday, and
treated "no regime applies" as "cannot tell", falling back to the engine's
review sentence whose subject is simply the first runway in the text.

So the evaluation is not a property of who asks. It belongs to the notice and
the reference time, and every surface reads the same one - whether the
analysis is fresh or was stored by an older build.
"""
from __future__ import annotations

import copy
import json
import re
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.odss.airport_pdf_analysis import analyse_airport_for_pdf

HELD = json.loads(
    (Path(__file__).parent / "fixtures/wsss_sx120_runway_closure_schedule.json").read_text()
)
NOTICE = HELD["notice"]
FINDING = HELD["finding"]
CORPUS = Path(__file__).resolve().parents[2] / "private_cfp_corpus"
UNRESOLVED = "could not be resolved"


def utc(text: str) -> datetime:
    return datetime.fromisoformat(text).astimezone(timezone.utc)


def assess(reference: str, planned: str | None = "20R", text: str | None = None, role: str = "destination"):
    # Imported where used, so the surface tests below still run - and fail on
    # the behaviour - against a build that predates the shared module.
    from app.odss.runway_closure_schedule import assess_runway_closure_schedule

    return assess_runway_closure_schedule(
        text if text is not None else NOTICE["item_e_text"],
        role=role,
        reference_time=utc(reference),
        planned_runway=planned,
    )


# ------------------------------------------------------------ the evaluator

def test_tuesday_eta_is_inside_the_centre_runway_closure_not_the_planned_one() -> None:
    result = assess("2026-09-08T21:28:00+00:00")

    assert [row["runways"] for row in result["statements"]] == [["02C", "20C"]]
    statement = result["statements"][0]
    assert statement["stateAtReference"] == "active_at_reference"
    assert statement["text"] == "RWY 02C/20C closes 1730-2130Z; ETA 2128Z is within the closure."
    assert statement["line"] == (
        "RWY 02C/20C closes 1730-2130Z; ETA 2128Z is within the closure. "
        "Planned RWY 20R differs from this affected runway."
    )
    # The planned runway's own regime is evaluated too, and it is a resolved
    # fact - not an unknown - that it does not apply on a Tuesday.
    planned = [row for row in result["regimes"] if "20R" in row["runways"] and row["inDateRange"]]
    assert planned and all(row["appliesOnReferenceDay"] is False for row in planned)


def test_wednesday_eta_is_inside_the_planned_runways_own_closure() -> None:
    result = assess("2026-09-09T21:28:00+00:00")

    assert [row["runways"] for row in result["statements"]] == [["02L", "20R"]]
    assert result["statements"][0]["line"] == (
        "RWY 02L/20R closes 1730-2130Z; ETA 2128Z is within the closure."
    )


@pytest.mark.parametrize("planned", [None, "", "20R", "20C", "02C", "20L", "02L/20R", "09"])
def test_which_regimes_apply_never_depends_on_who_asks(planned) -> None:
    baseline = assess("2026-09-08T21:28:00+00:00", planned="20R")
    result = assess("2026-09-08T21:28:00+00:00", planned=planned)

    assert [(r["runways"], r["stateAtReference"], r["text"]) for r in result["statements"]] == [
        (r["runways"], r["stateAtReference"], r["text"]) for r in baseline["statements"]
    ]


@pytest.mark.parametrize(("reference", "state", "fragment"), [
    ("2026-09-08T15:10:00+00:00", "begins_after_reference", "precedes closure by 2h20"),
    ("2026-09-08T17:30:00+00:00", "active_at_reference", "is within the closure"),
    ("2026-09-08T21:30:00+00:00", "ended_before_reference", "ends 0h00 before"),
    ("2026-09-08T23:05:00+00:00", "ended_before_reference", "ends 1h35 before"),
])
def test_closure_window_edges(reference, state, fragment) -> None:
    statement = assess(reference)["statements"][0]

    assert statement["stateAtReference"] == state
    assert fragment in statement["text"]


def test_a_day_with_no_regime_publishes_no_closure_claim() -> None:
    # Monday: neither runway's regime applies. Nothing is claimed, so every
    # surface keeps the one shared review sentence.
    assert assess("2026-09-07T21:28:00+00:00")["statements"] == []


def test_superseded_dated_regime_is_not_used_outside_its_own_dates() -> None:
    # 04SEP25-30SEP25 printed 1800-2200 for 02C/20C; from 30SEP25 it is 1730-2130.
    early = assess("2025-09-09T21:45:00+00:00")["statements"][0]
    late = assess("2026-09-08T21:45:00+00:00")["statements"][0]

    assert "1800-2200Z" in early["text"] and early["stateAtReference"] == "active_at_reference"
    assert "1730-2130Z" in late["text"] and late["stateAtReference"] == "ended_before_reference"


def test_two_runways_closed_on_the_same_day_are_both_published() -> None:
    text = (
        "RWY 02L/20R WILL BE CLSD BTN 1730UTC TO 2130UTC EV TUE FM 30SEP25 TO 31MAR27 FOR MAINT. "
        "RWY 02C/20C WILL BE CLSD BTN 2000UTC TO 2300UTC EV TUE AND FRI FM 30SEP25 TO 31MAR27 FOR MAINT."
    )
    result = assess("2026-09-08T21:28:00+00:00", text=text)

    assert [row["runways"] for row in result["statements"]] == [["02L", "20R"], ["02C", "20C"]]
    assert "Planned RWY 20R differs" not in result["statements"][0]["line"]
    assert "Planned RWY 20R differs" in result["statements"][1]["line"]


def test_closure_that_crosses_midnight_is_active_the_next_morning() -> None:
    text = "RWY 07R/25L WILL BE CLSD BTN 2300UTC TO 0300UTC EV MON FM 01SEP26 TO 30SEP26 FOR MAINT."
    # Tuesday 0110Z is inside Monday night's closure.
    statement = assess("2026-09-08T01:10:00+00:00", planned="25L", text=text, role="departure")["statements"][0]

    assert statement["stateAtReference"] == "active_at_reference"
    assert statement["text"] == "RWY 07R/25L closes 2300-0300Z; ETD 0110Z is within the closure."


def test_notice_without_a_dated_regime_is_left_to_the_existing_analysis() -> None:
    assert assess("2026-09-08T21:28:00+00:00", text="RWY 16R/34L CLSD DUE WIP.") is None


# ------------------------------------------- one statement on every surface

def published_runway_closure_statement(*args, **kwargs):
    from app.odss.runway_closure_schedule import published_runway_closure_statement as shared

    return shared(*args, **kwargs)


def reconcile_runway_closure_findings(*args, **kwargs):
    from app.odss.runway_closure_schedule import reconcile_runway_closure_findings as shared

    return shared(*args, **kwargs)


def _pdf_lines(planned: str = "20R") -> list[str]:
    result = analyse_airport_for_pdf(
        {"icao": "WSSS", "selected_notams": [copy.deepcopy(NOTICE)]},
        role="destination", planned_runway=planned,
    )
    return [row["consequence"] for row in result["lines"] if "SX120/25" in row["notam_ids"]]


def test_card_decision_page_and_airports_page_publish_the_same_statement() -> None:
    from app.odss.briefing import _compact_notam_family, _compact_notam_text

    notice = copy.deepcopy(NOTICE)
    card = _compact_notam_text(
        notice, _compact_notam_family(notice), role="destination",
        planned_runways={"20R"}, reference_time=utc(NOTICE["referenceAt"]), dashboard=True,
    )
    airports = _pdf_lines()

    assert airports == [
        "RWY 02C/20C closes 1730-2130Z; ETA 2128Z is within the closure. "
        "Planned RWY 20R differs from this affected runway."
    ]
    assert card == airports[0]
    decision = published_runway_closure_statement(
        NOTICE["item_e_text"], role="destination",
        reference_time=utc(NOTICE["referenceAt"]), planned_runway="20R",
    )
    assert decision["text"].startswith(airports[0])
    for surface in (card, decision["text"], *airports):
        assert UNRESOLVED not in surface
        assert "02L/20R" not in surface


def test_the_card_uses_the_notices_own_reference_not_a_second_clock() -> None:
    """The engine assessed the notice at ``referenceAt``. A caller holding a
    different clock must not get a second, different answer about the same
    notice."""
    from app.odss.briefing import _compact_notam_family, _compact_notam_text

    notice = copy.deepcopy(NOTICE)
    card = _compact_notam_text(
        notice, _compact_notam_family(notice), role="destination",
        planned_runways={"20R"}, reference_time=utc("2026-09-08T23:40:00+00:00"), dashboard=True,
    )

    assert card == _pdf_lines()[0]


def test_unevaluated_clauses_stay_open_without_contradicting_the_evaluated_one() -> None:
    # The supplement also prints short inspection closures this evaluator does
    # not read. The published statement says so; it does not pretend the whole
    # notice is resolved, and it does not claim an unresolved 02L/20R either.
    decision = published_runway_closure_statement(
        NOTICE["item_e_text"], role="destination",
        reference_time=utc(NOTICE["referenceAt"]), planned_runway="20R",
    )

    assert decision["residualReview"] is True
    assert decision["text"].endswith("review required.")
    assert "02L/20R" not in decision["text"]


# ------------------------------------------------------- old stored analyses

def test_an_old_stored_finding_is_reconciled_to_the_statement_a_fresh_one_gets() -> None:
    stored = [copy.deepcopy(FINDING)]
    assert UNRESOLVED in stored[0]["summary"]
    before = copy.deepcopy(stored)

    reconciled = reconcile_runway_closure_findings(stored, {"destination_runway": "20R"})

    assert stored == before, "the held analysis is never mutated"
    assert UNRESOLVED not in reconciled[0]["summary"]
    assert reconciled[0]["summary"].startswith(_pdf_lines()[0])
    # Idempotent: a fresh analysis already carries this sentence.
    assert reconcile_runway_closure_findings(reconciled, {"destination_runway": "20R"}) == reconciled


def test_reconciliation_touches_nothing_it_cannot_evaluate() -> None:
    other = copy.deepcopy(FINDING)
    other["data"]["raw_text"] = "RWY 16R/34L CLSD DUE WIP."
    other["summary"] = "Rwy 16R/34L closed or unavailable during the applicable destination window."
    monday = copy.deepcopy(FINDING)
    for row in monday["data"]["role_applicability"]:
        row["referenceAt"] = "2026-09-07T21:28:00+00:00"
    monday["data"]["referenceAt"] = "2026-09-07T21:28:00+00:00"
    weather = {"engine": "weather", "summary": "x", "data": {}}

    result = reconcile_runway_closure_findings([other, monday, weather], {"destination_runway": "20R"})

    assert result == [other, monday, weather]


# -------------------------------------------------- the real OFP, end to end

def test_real_sia605_download_and_dashboard_agree_about_sx120(tmp_path) -> None:
    import fitz

    from app.analysis import run_odss_analysis
    from app.odss.combined_brief import render_combined_briefing

    source = CORPUS / "SQ60508092026ICN.pdf"
    if not source.is_file():
        pytest.skip("private source SQ60508092026ICN.pdf not available")
    result = run_odss_analysis(
        source, tmp_path / "analysis", tmp_path / "reports", 605,
        actual_takeoff_utc="2026-09-08T16:00:00+00:00",
    )
    payload = json.loads(Path(result["analysis_path"]).read_text())
    flight, findings, warnings = payload["flight"], payload["findings"], payload["view"]["warnings"]
    view = payload["view"]["briefing"]
    path = tmp_path / "Flight_Briefing.pdf"
    render_combined_briefing(flight, findings, warnings, path, weather_charts=payload.get("weather_charts") or {})
    with fitz.open(path) as document:
        pages = [" ".join(page.get_text().split()) for page in document]

    expected = "RWY 02C/20C closes 1730-2130Z; ETA 2128Z is within the closure."
    # Dashboard: every field the card, the Airports tab and the decision list read.
    panel = next(p for p in view["airport_operational_panels"] if p["icao"] == "WSSS" and p.get("role_key", "destination") != "departure")
    notice = next(n for n in panel["selected_notams"] if n["notam_id"] == "SX120/25")
    dashboard = [notice["summary"], notice["compact_text"]]
    dashboard += [line["text"] for line in panel["card_summary_lines"] if line.get("notam_id") == "SX120/25" or line.get("label") == "SX120/25"]
    dashboard += [row["summary"] for row in view["decision_findings"] if "SX120/25" in json.dumps(row)]
    dashboard += [f["summary"] for f in findings if (f.get("data") or {}).get("notam_id") == "SX120/25"]
    assert dashboard
    for statement in dashboard:
        assert expected in statement, statement
        assert UNRESOLVED not in statement.split("SX151/26")[0], statement
    # Download: no page may describe this notice as an unresolved 02L/20R.
    whole = " ".join(pages)
    assert expected in pages[0] and expected in pages[3]
    assert expected in pages[1], pages[1][:1500]
    assert "SX120/25 - Published RWY 02L/20R restriction could not be resolved" not in whole
    assert not re.search(r"SX120/25\W{1,4}Published RWY 02L/20R", whole)


# ------------------------------------------------ stored copies of the old story

def test_a_briefing_stored_under_release_30s_contract_is_not_served_as_current() -> None:
    """A saved pack keeps the PDF it downloaded, and a server keeps a rendered
    copy per analysis. Both were produced by the derivation that described one
    notice two ways and dropped declarations, so neither may be handed back as
    the current briefing for the same held analysis."""
    from app.odss.combined_brief import (
        COMBINED_BRIEFING_PUBLICATION_FORMAT,
        COMBINED_BRIEFING_SCHEMA_VERSION,
        combined_briefing_cache_token,
    )

    release_30_format = "six-page-reference-briefing-2026-09-15"
    release_30_schema = "2026-09-18-page1-signed-tile-values-v60"
    assert COMBINED_BRIEFING_PUBLICATION_FORMAT != release_30_format
    assert COMBINED_BRIEFING_SCHEMA_VERSION != release_30_schema
    assert combined_briefing_cache_token("held", 605) != combined_briefing_cache_token(
        "held", 605, schema_version=release_30_schema,
    )

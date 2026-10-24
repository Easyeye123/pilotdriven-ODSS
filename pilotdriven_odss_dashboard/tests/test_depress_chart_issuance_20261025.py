"""One issued chart per profile; a chart that covers part of a window is issued.

David, 24 Oct 2026 (SQ301 MAN-SIN): "Depress chart issued has a duplicate. And
the second chart is not issued. ... One set over waypoint REBLO is one chart
but now pd giving two charts. The other is over waypoint RANAH - that's 10-4
chart but is missing from the analysis."

Two shared-design defects, neither specific to a flight, chart or waypoint:

1. The issued unit was the per-window match. One chart that protects two
   separate terrain windows (8-7 over TBN-EDATA and RASAM) was issued once per
   window. A chart is now issued once per flight and names every window and
   leg it covers; no window loses its coverage statement.
2. A governed chart that covers only part of a window was demoted to a
   "candidate" with no artifact (21 Oct hand patch), so 10-4 silently vanished.
   It is now issued with exactly the legs it covers, the legs no indexed chart
   covers are stated as such, and the window never reads as fully covered. The
   publication gate still fails closed when any issued chart, complete or
   partial, has no governed artifact.

The genuine OFPs are read from the private CFP corpus and skipped where a
member is not held. The profile rows are route metadata from the controlled
index (tests/fixtures/depress_route_metadata_profiles.json); no chart content
is reproduced.
"""

from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path

import pytest

from app.odss import engines
from app.odss.controlled_library import DEPRESS_LIBRARY_METADATA, _normalise_profile
from app.odss.parser import extract_pages, parse_lido
from app.odss.profile_chart_gate import (
    DepressurisationProfileChartPublicationError,
    is_proposed_profile_finding,
    validate_depressurisation_profile_charts,
)

ROOT = Path(__file__).resolve().parents[1]
ROWS = ROOT / "tests" / "fixtures" / "depress_route_metadata_profiles.json"

SQ301_MAN_SIN_24OCT = "SQ30124102026MAN.pdf"  # David's 24 Oct flight
SQ302_SIN_MAN_21OCT = "SQ30221102026SIN.pdf"
SQ23_JFK_SIN = "SQ02325072026JFK.pdf"
SQ303_BRU_SIN = "SQ30316072026BRU 81.pdf"
SQ314_SIN_LGW = "lido-briefing_SQ_314_15Aug2026_SIN_LGW.pdf"
SQ366_SIN_FCO = "SQ36604082026SIN.pdf"
SQ352_SIN_CPH = "lido-briefing_SQ_352_15Aug2026_SIN_CPH.pdf"
SQ24_SIN_JFK = "lido-briefing_SQ_24_15Aug2026_SIN_JFK.pdf"
SQ322_SIN_LHR = "lido-briefing_SQ_322_16Aug2026_SIN_LHR.pdf"
SQ326_SIN_FRA = "lido-briefing_SQ_326_16Aug2026_SIN_FRA.pdf"


def _corpus_member(filename: str) -> Path:
    configured = os.environ.get("PILOTDRIVEN_PRIVATE_CFP_CORPUS_DIR")
    corpus = Path(configured) if configured else ROOT.parent / "private_cfp_corpus"
    if not corpus.is_dir():
        if configured:
            raise FileNotFoundError(f"Configured PILOTDRIVEN_PRIVATE_CFP_CORPUS_DIR is missing: {corpus}")
        pytest.skip("the private CFP corpus is not available")
    source = corpus / filename
    if not source.is_file():
        pytest.skip(f"{filename} is not held in the private CFP corpus")
    return source


@lru_cache(maxsize=None)
def _parsed(path: str) -> dict:
    source = Path(path)
    return parse_lido(extract_pages(source), source.name)


@pytest.fixture
def controlled_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    rows = json.loads(ROWS.read_text(encoding="utf-8"))
    monkeypatch.setattr(
        engines,
        "DEPRESS_PROFILES",
        [_normalise_profile(item) for item in rows["profiles"]],
    )
    monkeypatch.setitem(DEPRESS_LIBRARY_METADATA, "status", "controlled-index-loaded")
    monkeypatch.setitem(DEPRESS_LIBRARY_METADATA, "issue_date", rows["issue_date"])
    monkeypatch.setitem(DEPRESS_LIBRARY_METADATA, "coverage_scope", "partial_issue")


def _analyse(filename: str) -> tuple[dict, list[dict]]:
    flight = json.loads(json.dumps(_parsed(str(_corpus_member(filename)))))
    findings, _ = engines.analyse(flight)
    return flight, findings


def _charts(findings: list[dict]) -> list[dict]:
    return [
        item
        for item in findings
        if item.get("engine") == "depressurisation"
        and (item.get("data") or {}).get("chart_number")
    ]


def _windows(findings: list[dict]) -> list[dict]:
    return [
        item
        for item in findings
        if item.get("engine") == "depressurisation"
        and not (item.get("data") or {}).get("chart_number")
        and (item.get("data") or {}).get("terrain_event_id")
    ]


def _chart(findings: list[dict], number: str) -> dict:
    matches = [item for item in _charts(findings) if item["data"]["chart_number"] == number]
    assert len(matches) == 1, f"chart {number} issued {len(matches)} times"
    return matches[0]


def _event_ids(flight: dict) -> dict[str, str]:
    return {
        f"{event['first_high']['name']}-{event['last_high']['name']}": event["terrain_event_id"]
        for event in engines.detect_terrain_events(flight["route_waypoints"])
    }


# --------------------------------------------------------------------------
# David's flight: SQ301 MAN-SIN 24 Oct 2026.
# --------------------------------------------------------------------------


def test_sq301_issues_8_7_once_and_issues_10_4_over_ranah(controlled_rows) -> None:
    flight, findings = _analyse(SQ301_MAN_SIN_24OCT)
    ids = _event_ids(flight)

    assert [item["data"]["chart_number"] for item in _charts(findings)] == ["8-23", "8-7", "10-4"]

    reblo = _chart(findings, "8-7")
    assert reblo["data"]["critical_point"] == "REBLO"
    assert reblo["data"]["terrain_event_ids"] == [ids["TBN-EDATA"], ids["RASAM-RASAM"]]
    assert [
        (row["terrain_event_id"], row["covered_legs"], row["window_complete"])
        for row in reblo["data"]["window_coverage"]
    ] == [
        (ids["TBN-EDATA"], ["REBLO-EDATA"], True),
        (ids["RASAM-RASAM"], ["RASAM"], True),
    ]
    assert reblo["data"]["coverage_complete"] is True
    assert "Covers REBLO-EDATA of window TBN-EDATA, and RASAM." in reblo["summary"]

    # 8-23 is a genuine split of the TBN-EDATA window: it alone covers TBN-REBLO.
    eridu = _chart(findings, "8-23")
    assert [row["covered_legs"] for row in eridu["data"]["window_coverage"]] == [["TBN-REBLO"]]

    ranah = _chart(findings, "10-4")
    assert ranah["data"]["critical_point"] == "DUDEG"
    assert ranah["data"]["coverage_complete"] is False
    assert [
        (row["covered_legs"], row["window_complete"])
        for row in ranah["data"]["window_coverage"]
    ] == [(["ENRON-DUDEG"], False)]
    assert ranah["data"]["uncovered_legs"] == ["DUDEG-UPVAL"]
    assert "Covers ENRON-DUDEG of window ENRON-UPVAL" in ranah["summary"]
    assert ranah["summary"].endswith("DUDEG-UPVAL is not covered by any indexed chart.")
    assert ranah["severity"] == "unknown"

    # Every issued chart, partial or complete, is a governed chart to publish.
    assert all(is_proposed_profile_finding(item) for item in _charts(findings))

    by_window = {item["data"]["terrain_event_id"]: item for item in _windows(findings)}
    # Complete windows carry no unresolved finding; the partial window says
    # exactly what is and is not covered.
    assert ids["TBN-EDATA"] not in by_window
    assert ids["RASAM-RASAM"] not in by_window
    partial = by_window[ids["ENRON-UPVAL"]]
    assert partial["severity"] == "unknown"
    assert partial["title"] == "Profile coverage incomplete - ENRON to UPVAL"
    assert partial["summary"] == (
        "Chart 10-4 covers ENRON-DUDEG; DUDEG-UPVAL is not covered by any "
        "indexed chart."
    )
    assert partial["data"]["coverage_state"] == "partial"
    assert partial["data"]["issued_chart_numbers"] == ["10-4"]
    assert partial["data"]["uncovered_legs"] == ["DUDEG-UPVAL"]
    assert partial["data"]["coverage_complete"] is False
    assert "Not covered by any indexed chart: DUDEG-GODSI-BIROS-ZB-UPVAL." in partial["details"]
    # The window with no chart at all stays fail-closed and unchanged.
    assert by_window[ids["DINRO-DINRO"]]["title"] == "Profile unresolved - DINRO to DINRO"
    assert "coverage_state" not in by_window[ids["DINRO-DINRO"]]["data"]


def test_sq301_publication_gate_fails_closed_for_every_issued_chart(controlled_rows) -> None:
    flight, findings = _analyse(SQ301_MAN_SIN_24OCT)
    for mode in (1, 2, "combined"):
        with pytest.raises(DepressurisationProfileChartPublicationError) as captured:
            validate_depressurisation_profile_charts({}, findings, mode)
        assert {item["location"] for item in captured.value.violations if item["code"] == "DEPRESSURISATION_PROFILE_CHART_ARTIFACT_MISSING"} == {
            "depressurisation_profile_charts[8-23]",
            "depressurisation_profile_charts[8-7]",
            "depressurisation_profile_charts[10-4]",
        }


def test_sq301_terrain_summary_never_reads_the_ranah_window_as_covered(controlled_rows) -> None:
    from app.odss.briefing import _terrain_summary

    flight, findings = _analyse(SQ301_MAN_SIN_24OCT)
    events = engines.detect_terrain_events(flight["route_waypoints"])
    summary = _terrain_summary(events, findings, flight["route_waypoints"])
    assert "2/4 terrain windows have validated profile matches" in summary
    assert "1 partially covered terrain window; 1 unmatched terrain window" in summary
    assert "1 unmatched terrain window" in summary


def test_sq301_window_join_returns_the_chart_for_each_window_it_covers(controlled_rows) -> None:
    from app.odss.report_facts import (
        is_confirmed_profile_finding,
        profile_coverage_label,
        profile_findings_for_terrain_event,
    )

    flight, findings = _analyse(SQ301_MAN_SIN_24OCT)
    events = {
        f"{event['first_high']['name']}-{event['last_high']['name']}": event
        for event in engines.detect_terrain_events(flight["route_waypoints"])
    }
    rasam = profile_findings_for_terrain_event(events["RASAM-RASAM"], findings)
    assert [item["data"].get("chart_number") for item in rasam] == ["8-7"]
    assert is_confirmed_profile_finding(rasam[0], events["RASAM-RASAM"]["terrain_event_id"])
    tbn = profile_findings_for_terrain_event(events["TBN-EDATA"], findings)
    assert sorted(item["data"].get("chart_number") for item in tbn) == ["8-23", "8-7"]
    ranah = profile_findings_for_terrain_event(events["ENRON-UPVAL"], findings)
    label = profile_coverage_label(ranah, events["ENRON-UPVAL"]["terrain_event_id"])
    assert label == "Partial: 10-4 ENRON-DUDEG; DUDEG-UPVAL not covered by any indexed chart"


def test_sq301_coverage_receipt_states_the_partial_window(controlled_rows) -> None:
    from app.odss.briefing import build_briefing_view
    from app.odss.combined_brief import _operational_coverage_receipt

    flight, findings = _analyse(SQ301_MAN_SIN_24OCT)
    view = build_briefing_view(flight, findings, [])
    rows = {row["key"]: row for row in _operational_coverage_receipt(flight, view, findings, None)["rows"]}
    row = rows["depressurisation_profile"]
    assert row["state"] == "UNRESOLVED"
    assert row["detail"] == (
        "3 controlled depressurisation profile charts issued (8-23, 8-7, 10-4); "
        "ENRON-UPVAL is only partly covered by an indexed chart."
    )


# --------------------------------------------------------------------------
# The same two defects on other genuine routes, and the routes that must not move.
# --------------------------------------------------------------------------


def test_sq302_issues_the_partial_10_4_over_ranah(controlled_rows) -> None:
    _, findings = _analyse(SQ302_SIN_MAN_21OCT)
    assert [item["data"]["chart_number"] for item in _charts(findings)] == ["10-4", "8-5"]
    ranah = _chart(findings, "10-4")
    assert [row["covered_legs"] for row in ranah["data"]["window_coverage"]] == [["DUDEG-RANAH"]]
    assert ranah["data"]["uncovered_legs"] == ["ZB-DUDEG"]
    assert is_proposed_profile_finding(ranah)


@pytest.mark.parametrize(
    ("filename", "chart", "windows", "legs", "statement"),
    [
        (SQ23_JFK_SIN, "8-7", ["TBN-EDATA", "RASAM-RASAM"], [["TBN-EDATA"], ["RASAM"]],
         "Covers TBN-EDATA and RASAM."),
        (SQ303_BRU_SIN, "8-7", ["TBN-EDATA", "RASAM-RASAM"], [["REBLO-EDATA"], ["RASAM"]],
         "Covers REBLO-EDATA of window TBN-EDATA, and RASAM."),
        (SQ24_SIN_JFK, "11-37", ["TED-ORT", "63N30-62N20"], [["TED-ORT"], ["63N30-62N20"]],
         "Covers TED-ORT and 63N30-62N20."),
    ],
)
def test_a_chart_covering_two_windows_is_issued_once(controlled_rows, filename, chart, windows, legs, statement) -> None:
    flight, findings = _analyse(filename)
    ids = _event_ids(flight)
    issued = _chart(findings, chart)
    assert issued["summary"].endswith(statement)
    assert issued["data"]["coverage_statement"] == statement
    assert issued["data"]["terrain_event_ids"] == [ids[name] for name in windows]
    assert [row["covered_legs"] for row in issued["data"]["window_coverage"]] == legs
    assert all(row["window_complete"] for row in issued["data"]["window_coverage"])
    numbers = [item["data"]["chart_number"] for item in _charts(findings)]
    assert len(numbers) == len(set(numbers))
    # Neither window reads as unresolved.
    assert not {ids[name] for name in windows} & {
        item["data"]["terrain_event_id"] for item in _windows(findings)
    }


@pytest.mark.parametrize(
    ("filename", "expected"),
    [
        (SQ314_SIN_LGW, [
            ("10-4", "Proposed depressurisation chart 10-4; critical point DUDEG."),
            ("8-5", "Proposed depressurisation chart 8-5; critical point MATAL."),
        ]),
        (SQ366_SIN_FCO, [
            ("10-4", "Proposed depressurisation chart 10-4; critical point DUDEG."),
            ("8-5", "Proposed depressurisation chart 8-5; critical point MATAL."),
        ]),
        (SQ352_SIN_CPH, [
            ("10-6", "Proposed depressurisation chart 10-6; critical point VUVEN."),
            ("8-29", "Proposed depressurisation chart 8-29; critical point YAVUZ."),
        ]),
    ],
)
def test_one_chart_per_complete_window_keeps_its_published_wording(controlled_rows, filename, expected) -> None:
    _, findings = _analyse(filename)
    assert [
        (item["data"]["chart_number"], item["summary"]) for item in _charts(findings)
    ] == expected
    assert all(item["severity"] == "warning" for item in _charts(findings))
    assert all(item["data"]["coverage_complete"] is True for item in _charts(findings))
    assert all(
        "Covers" not in line and "not covered" not in line
        for item in _charts(findings)
        for line in item["details"]
    )


@pytest.mark.parametrize("filename", [SQ322_SIN_LHR, SQ326_SIN_FRA])
def test_a380_ranah_and_matal_windows_stay_fail_closed(controlled_rows, filename) -> None:
    """SQ322/SQ326 fly the same ZB-RANAH and MATAL-TEMEL windows on an A380.
    The controlled index is the A350 profile set: every row that touches these
    routes is scoped LH/ULR, so no chart applies and nothing is substituted."""
    flight, findings = _analyse(filename)
    assert _charts(findings) == []
    conflict = engines.effectivity_conflict(flight)
    assert conflict is not None and conflict["aircraft_type"] == "A380-841"
    ids = _event_ids(flight)
    unresolved = {item["data"]["terrain_event_id"] for item in _windows(findings)}
    assert {ids["ZB-RANAH"], ids["MATAL-TEMEL"]} <= unresolved


# --------------------------------------------------------------------------
# Shared predicates, independent of any route.
# --------------------------------------------------------------------------


def test_partial_issued_chart_is_served_by_the_chart_loader() -> None:
    from app.odss.depress_analysis_page import _matched_event_findings, _matched_findings

    partial = {
        "engine": "depressurisation",
        "data": {
            "chart_number": "10-4",
            "coverage_complete": False,
            "reference_status": "controlled-index-loaded",
            "terrain_event_id": "terrain:A@1-B@2",
        },
    }
    assert _matched_event_findings([partial]) == [partial]
    assert _matched_findings([partial]) == [partial]


def test_terrain_summary_counts_a_window_covered_by_a_multi_window_chart() -> None:
    from app.odss.briefing import _terrain_summary

    events = [
        {
            "terrain_event_id": "terrain:ALPHA@10-BRAVO@20",
            "first_high": {"name": "ALPHA", "msa_hundreds_ft": 117},
            "last_high": {"name": "BRAVO", "msa_hundreds_ft": 124},
            "maximum": {"name": "BRAVO", "msa_hundreds_ft": 124},
        },
        {
            "terrain_event_id": "terrain:CHARLIE@30-CHARLIE@30",
            "first_high": {"name": "CHARLIE", "msa_hundreds_ft": 108},
            "last_high": {"name": "CHARLIE", "msa_hundreds_ft": 108},
            "maximum": {"name": "CHARLIE", "msa_hundreds_ft": 108},
        },
    ]
    one_chart = {
        "engine": "depressurisation",
        "data": {
            "chart_number": "8-7",
            "coverage_complete": True,
            "reference_status": "controlled-index-loaded",
            "terrain_event_id": events[0]["terrain_event_id"],
            "terrain_event_ids": [event["terrain_event_id"] for event in events],
            "window_coverage": [
                {"terrain_event_id": event["terrain_event_id"], "covered_legs": [], "window_complete": True}
                for event in events
            ],
        },
    }
    assert "2/2 terrain windows have validated profile matches on the terrain page" in _terrain_summary(events, [one_chart])


def test_issued_chart_wording_states_facts_without_reminders(controlled_rows) -> None:
    """R2 (David, 22 Sep 2026): states, never review instructions."""
    import re

    from app.odss.briefing import build_briefing_view
    from app.odss.combined_brief import _operational_coverage_receipt

    reminder = re.compile(r"review[ _-]required|manual review|crew review|requires? review", re.I)
    for filename in (SQ301_MAN_SIN_24OCT, SQ302_SIN_MAN_21OCT, SQ23_JFK_SIN):
        flight, findings = _analyse(filename)
        view = build_briefing_view(flight, findings, [])
        receipt = _operational_coverage_receipt(flight, view, findings, None)
        texts = [view["terrain"]["summary"], *(row["detail"] for row in receipt["rows"] if row["key"] == "depressurisation_profile")]
        for item in findings:
            if item.get("engine") != "depressurisation":
                continue
            data = item.get("data") or {}
            if not data.get("chart_number") and data.get("coverage_state") != "partial":
                continue  # the unchanged no-chart window wording is outside this repair
            texts += [item["title"], item["summary"], *item["details"], str(data.get("coverage_statement") or "")]
        assert [text for text in texts if reminder.search(text)] == [], filename

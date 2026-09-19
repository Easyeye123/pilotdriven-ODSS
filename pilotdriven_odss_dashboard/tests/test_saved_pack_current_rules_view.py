"""A saved pack's dashboard and its re-created download read the same rules.

Independent review, 19 Sep 2026. Download PDF re-creates the briefing from the
held analysis under the rules in service, but a reopened pack's dashboard was
the snapshot stored when it was saved - so after a correction the two surfaces
of one pack could describe the same notice differently, and the app could only
warn about it. The briefing route now does what the download does: for an
analysis stored under older rules it rebuilds the view from the SAME held
flight, findings, timing and OFP. Nothing is re-analysed, no clock or source is
changed, and the held analysis is never rewritten.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from app.odss.combined_brief import COMBINED_BRIEFING_SCHEMA_VERSION
from app.odss.flight_briefing_publication import current_rules_briefing

CORPUS = Path(__file__).resolve().parents[2] / "private_cfp_corpus"
STALE = "Published RWY 02L/20R restriction could not be resolved for the applicable destination window; review required."


@pytest.fixture(scope="module")
def stored(tmp_path_factory):
    from app.analysis import run_odss_analysis

    source = CORPUS / "SQ60508092026ICN.pdf"
    if not source.is_file():
        pytest.skip("private source SQ60508092026ICN.pdf not available")
    root = tmp_path_factory.mktemp("saved-pack")
    result = run_odss_analysis(source, root / "analysis", root / "reports", 605,
                               actual_takeoff_utc="2026-09-08T16:00:00+00:00")
    analysis = json.loads(Path(result["analysis_path"]).read_text())
    assert analysis["view"]["briefing"]["publication_rules"] == COMBINED_BRIEFING_SCHEMA_VERSION
    # Turn it into what release-30 stored: no rules stamp, and the engine's
    # review sentence held in the finding and in every snapshot field.
    old = copy.deepcopy(analysis)
    old["view"]["briefing"].pop("publication_rules")
    for finding in old["findings"]:
        if (finding.get("data") or {}).get("notam_id") == "SX120/25":
            finding["summary"] = STALE
    for panel in old["view"]["briefing"]["airport_operational_panels"]:
        for notice in panel.get("selected_notams") or []:
            if notice.get("notam_id") == "SX120/25":
                notice["summary"] = notice["compact_text"] = STALE
    return old, source


def test_a_fresh_analysis_is_served_as_stored(stored) -> None:
    old, source = stored
    fresh = copy.deepcopy(old)
    fresh["view"]["briefing"]["publication_rules"] = COMBINED_BRIEFING_SCHEMA_VERSION

    result = current_rules_briefing(fresh, source)

    assert result["rebuilt_from_held_analysis"] is False
    assert result["briefing"] is fresh["view"]["briefing"]


def test_an_older_stored_analysis_is_rebuilt_under_the_rules_in_service(stored) -> None:
    old, source = stored
    before = copy.deepcopy(old)

    result = current_rules_briefing(old, source)

    assert old == before, "the held analysis is never rewritten"
    assert result["rebuilt_from_held_analysis"] is True
    assert result["briefing"]["publication_rules"] == COMBINED_BRIEFING_SCHEMA_VERSION
    panel = next(p for p in result["briefing"]["airport_operational_panels"]
                 if any(n.get("notam_id") == "SX120/25" for n in p.get("selected_notams") or []))
    notice = next(n for n in panel["selected_notams"] if n["notam_id"] == "SX120/25")
    for text in (notice["summary"], notice["compact_text"]):
        assert text.startswith("RWY 02C/20C closes 1730-2130Z; ETA 2128Z is within the closure."), text
    assert STALE not in json.dumps(result["briefing"])
    assert all(STALE != row["summary"] for row in result["findings"])


def test_the_rebuild_changes_no_input_time_and_no_source_basis(stored) -> None:
    old, source = stored

    result = current_rules_briefing(old, source)

    for key in ("actual_takeoff_utc", "scheduled_departure_utc", "scheduled_arrival_utc",
                "flight_number", "flight_date", "departure", "destination", "registration"):
        assert result["flight"].get(key) == old["flight"].get(key), key
    assert result["timing"] == old["view"]["timing"]
    assert result["briefing"]["timing"] == old["view"]["briefing"]["timing"] if "timing" in old["view"]["briefing"] else True


def test_a_rebuild_that_cannot_complete_serves_the_stored_view_and_says_so(stored) -> None:
    old, source = stored
    broken = copy.deepcopy(old)
    broken["flight"].pop("route_waypoints", None)
    broken["flight"]["fuel"] = "not a fuel record"

    result = current_rules_briefing(broken, source)

    assert result["rebuilt_from_held_analysis"] is False
    assert result["briefing"] is broken["view"]["briefing"]
    assert result["rebuild_error"]

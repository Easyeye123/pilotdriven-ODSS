"""ITEM2-VOLCANIC (open item #2, Jabe's baseline 30 Sep 2026): "Volcano warnings: The PDF wrongly says a warning
source wasn't checked. We also haven't confirmed that all warnings relevant to the flight are covered."

Genuine SQ314 SIN-LGW (release 440, analysis 7cd4a16b): the VA SIGMET feed answered (118 records), its checklist said
"VA SIGMET feed: reached, not current", and its source row said NOT REACHED - so page 6 printed "VA SIGMET FEED not
reached". The status word carried two facts, reach and currency, and every reached state but one fell into NOT REACHED.

These tests pin the shared vocabulary (app/odss/source_status.py) across affected / reached-no-match / stale /
incomplete / retrieved-outside-the-flight / not-evaluated / coverage-gap / failed / unqueried inputs, through the
composed check, the source-assurance rows, the checklist row and the rendered page-6 source line. Flights and provider
answers are LABELLED SYNTHETIC / SIMULATED; the genuine-PDF test reads the private corpus with sockets blocked.
"""
from __future__ import annotations

import re
import socket
from pathlib import Path

import pytest

from app.odss import source_status as ss
from app.odss import vaa as vaa_module
from app.odss.briefing import build_briefing_view
from app.odss.combined_brief import _operational_coverage_receipt
from app.odss.operational_format import source_assurance_line
from app.odss.sigmet import assess_significant_weather
from app.odss.vaa import build_direct_vaa_source_review, evaluate_vaa

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT.parent / "private_cfp_corpus"
SQ366 = "SQ36604082026SIN.pdf"

DEPARTURE = "2026-07-22T04:00:00+00:00"
BEFORE_DEPARTURE = "2026-07-22T03:55:00+00:00"


# ------------------------------------------------------------------------------------------ SYNTHETIC inputs

def flight(points, *, profile="P0/350", firs=None, names=None) -> dict:
    """LABELLED SYNTHETIC: a flight through ``points``, one hour per leg."""
    firs = firs or [None] * len(points)
    names = names or [f"P{i}" for i in range(len(points))]
    return {
        "flight_number": "SQ900", "departure": "ZZAA", "destination": "ZZBB", "departure_runway": "01",
        "destination_runway": "19", "flight_date": "22JUL26", "scheduled_departure_utc": DEPARTURE,
        "scheduled_arrival_utc": "2026-07-22T10:00:00+00:00", "aircraft_type": "A350-900", "registration": "9V-SXX",
        "ground_distance_nm": 3000, "planned_level_profile": profile,
        "route_waypoints": [
            {"name": name, "actm_minutes": 60 * i, "latitude": lat, "longitude": lon, "fir_boundary": fir,
             "airway_in": "DCT", "msa_hundreds_ft": 4, "vws": 1}
            for i, ((lat, lon), fir, name) in enumerate(zip(points, firs, names))
        ],
        "masses": {}, "fuel": {}, "alternates": [], "edto": {}, "weather": [], "notams": [], "personal_notes": [],
        "bobcat": None,
    }


def feed(advisories=None, *, status="available", freshness="fresh", retrieved=BEFORE_DEPARTURE, warnings=()) -> dict:
    """SIMULATED: the international VA SIGMET feed's answer (current active SIGMETs only, as the live provider)."""
    return {
        "schema_version": "1.0", "provider": "noaa-awc-international-sigmet", "source_url": "https://aviationweather.gov",
        "status": status, "retrieved_at_utc": retrieved, "coverage_status": "global_current_active_sigmet",
        "coverage_start_utc": None, "coverage_end_utc": None, "freshness_status": freshness,
        "advisories": advisories or [], "parse_warnings": list(warnings), "raw_sha256": "simulated",
    }


def box(lon0, lat0, lon1, lat1, *, low=0, high=600, start="2026-07-22T00:00:00+00:00",
        end="2026-07-22T14:00:00+00:00", ident="SIM-VA-1") -> dict:
    """SIMULATED: a VA SIGMET polygon."""
    ring = [[lon0, lat0], [lon1, lat0], [lon1, lat1], [lon0, lat1], [lon0, lat0]]
    return {"advisory_id": ident, "hazard": "VA", "fir_id": "SIMX", "valid_from_utc": start, "valid_to_utc": end,
            "lower_flight_level": low, "upper_flight_level": high,
            "geometry": {"type": "Polygon", "coordinates": [ring]}, "raw_text": "SIMULATED", "raw_sha256": "sim"}


def centres(answers, *, retrieved=BEFORE_DEPARTURE):
    """SIMULATED: {centre: (status, advisory count)} per-centre VAAC answers and the mounted list."""
    snapshots = [
        {"centre": centre, "provider": f"sim-{centre.lower()}", "status": status, "coverage_status": "simulated",
         "retrieved_at_utc": retrieved,
         "advisories": [{"advisory_number": f"2026/{i:03d}", "issued_at_utc": "2026-07-22T02:00:00+00:00",
                         "volcano": "SIMULATED", "raw_sha256": f"{centre}{i}"} for i in range(count)]}
        for centre, (status, count) in answers.items() if status != "not_mounted"
    ]
    mounted = [{"token": centre.lower(), "centre": centre, "provider": f"sim-{centre.lower()}"}
               for centre, (status, _) in answers.items() if status != "not_mounted"]
    return snapshots, mounted


def view_of(route, feed_snapshot, answers, *, vaac_retrieved=BEFORE_DEPARTURE):
    review = evaluate_vaa(route, feed_snapshot or {"status": "disabled"}, {"status": "unavailable"})
    review["product"] = "VA_SIGMET"
    snapshots, mounted = centres(answers, retrieved=vaac_retrieved)
    route["va_sigmet_review"] = review
    route["direct_vaa_source_review"] = build_direct_vaa_source_review(route, snapshots=snapshots, mounted=mounted)
    route["vaa_review"] = dict(review)
    return build_briefing_view(route, [], [])


EQUATOR = [(0.0, 100.0), (0.0, 110.0)]   # Darwin's area, settled
CROSSING = box(104.0, -2.0, 106.0, 2.0)


def rows(view) -> dict[str, dict]:
    return {row["source"]: row for row in view["source_assurance"]}


def checklist_row(view) -> dict:
    receipt = _operational_coverage_receipt({}, view, [], None)
    return next(row for row in receipt["rows"] if row["key"] == "vaa_vaac")


# ------------------------------------------------------------------------------------------ the vocabulary

def test_a_status_is_composed_from_reach_and_qualifiers_in_a_fixed_order():
    assert ss.source_status(ss.REACHED) == "REACHED"
    assert ss.source_status(ss.REACHED, [ss.INCOMPLETE, ss.NOT_CURRENT]) == "REACHED · NOT CURRENT · INCOMPLETE"
    assert ss.source_status(ss.PARTIAL, [ss.NOT_SETTLED]) == "PARTIAL · NOT SETTLED"
    assert ss.source_status(ss.NOT_REACHED, [ss.NOT_SETTLED]) == "NOT REACHED · NOT SETTLED"
    row = ss.source_row("VA SIGMET FEED", ss.REACHED, [ss.NOT_CURRENT], "VA SIGMET feed: reached, not current.")
    assert (row["status"], row["reach"], row["qualifiers"]) == ("REACHED · NOT CURRENT", "REACHED", ["NOT CURRENT"])


def test_the_vocabulary_refuses_unknown_words_and_qualifiers_on_an_unanswered_source():
    with pytest.raises(ValueError):
        ss.source_status("REACHABLE")
    with pytest.raises(ValueError):
        ss.source_status(ss.REACHED, ["LATE"])
    with pytest.raises(ValueError):
        ss.source_status(ss.NOT_REACHED, [ss.NOT_CURRENT])  # no answer, so no answer to call stale


def test_only_a_bare_held_or_reached_is_met():
    assert ss.source_status_met("HELD") and ss.source_status_met("REACHED")
    for label in ("REACHED · NOT CURRENT", "PARTIAL", "NOT REACHED", "NOT QUERIED", "NOT SETTLED", "NOT HELD",
                  "SOMETHING A LATER BUILD ADDS", ""):
        assert not ss.source_status_met(label), label


def test_the_page_six_line_prints_every_status_in_its_own_words():
    line = source_assurance_line([
        {"source": "UPLOADED OFP", "status": "HELD"},
        {"source": "OFP VOLCANO ADVISORIES", "status": "NOT HELD"},
        {"source": "VA SIGMET FEED", "status": "REACHED · NOT CURRENT"},
        {"source": "RESPONSIBLE VAACS", "status": "REACHED · NOT SETTLED"},
        {"source": "FUTURE FEED", "status": "REACHED · LATE"},
        {"source": "DEAD FEED", "status": "NOT REACHED"},
    ])
    # Each group reads as a group: names, a colon, the shared status words (25 Oct 2026 QA).
    assert "VA SIGMET FEED: reached, not current" in line
    assert "RESPONSIBLE VAACS: reached, not settled" in line
    assert "FUTURE FEED: reached, late" in line
    assert "OFP VOLCANO ADVISORIES: not held" in line
    assert "DEAD FEED: not reached" in line
    # A status the old four-word table did not know printed "not held"; a reached answer printed "not reached".
    assert "VA SIGMET FEED: not reached" not in line and "FUTURE FEED: not held" not in line


def test_the_page_six_line_reads_grouped_sources_as_a_group():
    """25 Oct 2026 QA misread "VA SIGMET FEED, RESPONSIBLE VAACS reached, not current, incomplete" as the feed row having
    lost its status words: two names join with "and", three or more with commas and "and", then a colon."""
    line = source_assurance_line([
        {"source": "OFP VOLCANO ADVISORIES", "status": "NOT HELD"},
        {"source": "VA SIGMET FEED", "status": "REACHED · NOT CURRENT · INCOMPLETE"},
        {"source": "OFP VA SIGMET SECTION", "status": "NOT HELD"},
        {"source": "RESPONSIBLE VAACS", "status": "REACHED · NOT CURRENT · INCOMPLETE"},
        {"source": "SYNTHETIC THIRD", "status": "NOT HELD"},
    ])
    assert line == ("SOURCE ASSURANCE: OFP VOLCANO ADVISORIES, OFP VA SIGMET SECTION and SYNTHETIC THIRD: not held; "
                    "VA SIGMET FEED and RESPONSIBLE VAACS: reached, not current, incomplete.")
    assert "UPLOADED OFP" not in line


# ------------------------------------------------------------------------------------------ the feed, row by row

FEED_CASES = {
    # name: (route kwargs, feed snapshot, expected feed status, expected check state, words in the check line)
    "affected": ({}, feed([CROSSING]), "REACHED", "FOUND", "SIM-VA-1 cross the filed route/time/level"),
    "reached_no_match": ({}, feed(), "REACHED", "CHECKED · NO MATCH",
                         "VA SIGMET feed: reached, no current VA SIGMET crosses the route"),
    "stale": ({}, feed(freshness="stale"), "REACHED · NOT CURRENT", "UNRESOLVED", "VA SIGMET feed: reached, not current"),
    # SQ314's own shape: a fresh answer with two VA records the feed could not read.
    "records_incomplete": ({}, feed(warnings=["record_84:VA:missing_vertical_limits",
                                              "record_102:VA:missing_vertical_limits"]),
                           "REACHED · INCOMPLETE", "UNRESOLVED", "VA SIGMET feed: reached, 2 VA SIGMET records not readable"),
    # An analysis of an August flight run in September: today's SIGMETs say nothing about that flight.
    "retrieved_after_the_flight": ({}, feed(retrieved="2026-09-27T12:48:47+00:00"), "REACHED · NOT CURRENT",
                                   "UNRESOLVED", "retrieved 27Sep 1248Z, after the flight"),
    # Current SIGMETs are valid for at most 6 h: an answer 7 h before departure has expired by take-off.
    "retrieved_too_early": ({}, feed(retrieved="2026-07-21T21:00:00+00:00"), "REACHED · NOT CURRENT", "UNRESOLVED",
                            "too early for 22Jul 0400Z departure"),
    "no_retrieval_time": ({}, feed(retrieved=None), "REACHED · CURRENCY UNKNOWN", "UNRESOLVED",
                          "currency not established (retrieval time not held)"),
    "planned_level_not_held": ({"profile": ""}, feed(), "REACHED · NOT EVALUATED", "UNRESOLVED",
                               "route/time/level not evaluated (planned level not held)"),
    "failed": ({}, feed(status="unavailable"), "NOT REACHED", "UNRESOLVED", "VA SIGMET feed: not reached"),
    "unqueried": ({}, None, "NOT QUERIED", "UNRESOLVED", "VA SIGMET feed: not queried"),
}


@pytest.mark.parametrize("case", FEED_CASES, ids=list(FEED_CASES))
def test_the_feed_row_states_reach_and_answer_apart_on_every_surface(case):
    route_kwargs, snapshot, status, state, words = FEED_CASES[case]
    view = view_of(flight(EQUATOR, **route_kwargs), snapshot, {"DARWIN": ("available", 0)})
    check = view["vaa"]["check"]
    row = rows(view)["VA SIGMET FEED"]
    assert row["status"] == status, row
    assert check["feed_status"] == status
    assert check["state"] == state, check["line"]
    assert words in check["line"], check["line"]
    assert checklist_row(view)["state"] == state
    # One response, one fact: a row whose detail says the feed was reached never reads "not reached", and back.
    reached_detail = row["detail"].startswith("VA SIGMET feed: reached") or "cross the filed" in row["detail"]
    assert reached_detail == row["status"].startswith("REACHED"), row
    assert row["reach"] == status.split(" · ")[0] and row["qualifiers"] == status.split(" · ")[1:]
    line = source_assurance_line(view["source_assurance"])
    if ss.source_status_met(status):
        assert "VA SIGMET FEED" not in line
    else:
        assert re.search(rf"VA SIGMET FEED(?:(?:, | and )[A-Z ]+)*: {re.escape(ss.source_status_words(status))}(?:;|\.)", line), line
    assert bool(re.search(r"VA SIGMET FEED(?:(?:, | and )[A-Z ]+)*: not reached(?:;|\.)", line)) == (status == "NOT REACHED"), line


def test_a_route_into_us_domestic_firs_is_a_feed_coverage_gap_never_a_clear_feed():
    # The international feed carries no US domestic-format SIGMET; Oakland ARTCC (KZOA) is a domestic FIR.
    route = flight([(0.0, 100.0), (0.0, 110.0), (0.0, 120.0)], firs=[None, None, "KZOA"])
    view = view_of(route, feed(), {"DARWIN": ("available", 0)})
    check = view["vaa"]["check"]
    assert rows(view)["VA SIGMET FEED"]["status"] == "REACHED · COVERAGE GAP"
    assert "US domestic-format SIGMETs (KZOA) are not in this feed" in check["line"]
    assert check["state"] == "UNRESOLVED"


def test_an_unknown_evaluator_reason_is_never_turned_into_not_reached():
    route = flight(EQUATOR)
    review = evaluate_vaa(route, feed(), {"status": "unavailable"})
    review["reason_codes"] = sorted(set(review["reason_codes"]) | {"some_future_reason"})
    route["va_sigmet_review"] = review
    snapshots, mounted = centres({"DARWIN": ("available", 0)})
    route["direct_vaa_source_review"] = build_direct_vaa_source_review(route, snapshots=snapshots, mounted=mounted)
    view = build_briefing_view(route, [], [])
    assert rows(view)["VA SIGMET FEED"]["status"] == "REACHED · NOT EVALUATED"
    assert "some future reason" in view["vaa"]["check"]["line"]


def test_a_feed_answer_at_the_provider_record_cap_is_incomplete_never_complete():
    import httpx

    from app.odss.vaa import AWC_MAX_RESULTS, fetch_awc_snapshot

    # SIMULATED: the AWC API returns at most 400 entries; a full page may have been cut.
    record = {"hazard": "TS", "validTimeFrom": 1784678400, "validTimeTo": 1784692800, "base": 0, "top": 45000,
              "coords": [{"lat": 0, "lon": 100}, {"lat": 1, "lon": 100}, {"lat": 1, "lon": 101}], "firId": "SIMX"}
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=[record] * AWC_MAX_RESULTS))
    with httpx.Client(transport=transport) as client:
        snapshot = fetch_awc_snapshot(client=client, hazard_code="ALL")
    assert "response_at_provider_cap:400" in snapshot["parse_warnings"]
    route = flight(EQUATOR)
    projected = vaa_module.filter_awc_snapshot(snapshot, {"VA"})
    view = view_of(route, {**projected, "retrieved_at_utc": BEFORE_DEPARTURE}, {"DARWIN": ("available", 0)})
    assert rows(view)["VA SIGMET FEED"]["status"] == "REACHED · INCOMPLETE"
    assert "answer at the provider's record cap; SIGMETs may be missing" in view["vaa"]["check"]["line"]
    assert assess_significant_weather(route, snapshot={**snapshot, "retrieved_at_utc": BEFORE_DEPARTURE})[
        "clean_current_feed_no_match"] is False


# ------------------------------------------------------------------------------------------ the VAAC row

def test_a_centre_that_answered_incompletely_is_reached_but_never_a_clear_check():
    view = view_of(flight(EQUATOR), feed(), {"DARWIN": ("partial", 0)})
    check = view["vaa"]["check"]
    assert rows(view)["RESPONSIBLE VAACS"]["status"] == "REACHED · INCOMPLETE"
    assert check["state"] == "UNRESOLVED"
    assert "Responsible VAACs DARWIN: all reached; DARWIN answered incompletely; no advisory held" in check["line"]
    assert check["incomplete_centres"] == ["DARWIN"]


def test_a_centre_asked_after_the_flight_is_not_current():
    view = view_of(flight(EQUATOR), feed(), {"DARWIN": ("available", 0)}, vaac_retrieved="2026-09-27T12:48:47+00:00")
    check = view["vaa"]["check"]
    assert rows(view)["RESPONSIBLE VAACS"]["status"] == "REACHED · NOT CURRENT"
    assert "DARWIN not current for this flight" in check["line"]
    assert check["state"] == "UNRESOLVED"


NORTH_OF_60_CANADA = (63.0, -130.0)   # Canadian FIRs: assigned by name only; no FIR named here, so unsettled


def test_every_centre_reached_with_an_unsettled_point_is_reached_not_settled_not_partial():
    route = flight([(0.0, 110.0), (35.0, 140.0), NORTH_OF_60_CANADA])
    view = view_of(route, feed(), {"DARWIN": ("available", 0), "TOKYO": ("available", 0)})
    check = view["vaa"]["check"]
    assert check["unsettled_points"] == 1
    assert rows(view)["RESPONSIBLE VAACS"]["status"] == "REACHED · NOT SETTLED"
    assert check["state"] == "UNRESOLVED"


def test_partial_reach_with_an_unsettled_point_keeps_both_facts():
    route = flight([(0.0, 110.0), (35.0, 140.0), NORTH_OF_60_CANADA])
    view = view_of(route, feed(), {"DARWIN": ("available", 0), "TOKYO": ("unavailable", 0)})
    assert rows(view)["RESPONSIBLE VAACS"]["status"] == "PARTIAL · NOT SETTLED"


@pytest.mark.parametrize("answer,status,state", [
    ("unavailable", "NOT REACHED", "UNAVAILABLE"),
    ("not_mounted", "NOT QUERIED", "NOT QUERIED"),
])
def test_unanswered_centres_keep_their_reach(answer, status, state):
    view = view_of(flight(EQUATOR), feed(status="unavailable") if answer == "unavailable" else None,
                   {"DARWIN": (answer, 0)})
    assert rows(view)["RESPONSIBLE VAACS"]["status"] == status
    assert view["vaa"]["check"]["state"] == state


def test_sq314_shape_prints_reached_on_every_surface_and_stays_unresolved():
    """SIMULATED replay of the release-440 SQ314 receipts: a fresh feed answer with two unreadable VA records, read on
    27 Sep for a 15 Aug flight; Darwin and London answered with failures, Toulouse completely."""
    route = flight([(0.0, 100.0), (0.0, 110.0)])
    late = "2026-09-27T12:48:47+00:00"
    snapshot = feed(retrieved=late, warnings=["record_84:VA:missing_vertical_limits",
                                              "record_102:VA:missing_vertical_limits"])
    view = view_of(route, snapshot, {"DARWIN": ("partial", 0)}, vaac_retrieved=late)
    check = view["vaa"]["check"]
    feed_row = rows(view)["VA SIGMET FEED"]
    assert feed_row["status"] == "REACHED · NOT CURRENT · INCOMPLETE"
    assert feed_row["detail"].startswith("VA SIGMET feed: reached, not current")
    line = source_assurance_line(view["source_assurance"])
    # Sources with the same status share their words: "VA SIGMET FEED and RESPONSIBLE VAACS: reached, not current, ...".
    assert re.search(r"VA SIGMET FEED(?:(?:, | and )[A-Z ]+)*: reached, not current, incomplete", line), line
    assert not re.search(r"VA SIGMET FEED(?:(?:, | and )[A-Z ]+)*: not reached", line)
    assert check["state"] == checklist_row(view)["state"] == "UNRESOLVED"


# ------------------------------------------------------------------------------------------ the evaluator

def test_the_climb_is_screened_from_the_ground_to_the_level_held_at_toc():
    # SIMULATED: a SFC/FL100 VA SIGMET over the climb-out; cruise FL350. The climb used to be screened at FL350.
    route = flight([(0.0, 100.0), (0.0, 101.0), (0.0, 110.0), (0.0, 111.0)], names=["DEP1", "TOC", "TOD", "ARR1"])
    low = box(100.2, -1.0, 100.8, 1.0, low=0, high=100, ident="SIM-VA-LOW")
    review = evaluate_vaa(route, feed([low]), {"status": "unavailable"})
    assert review["status"] == "affected", review["reason_codes"]
    match = review["matches"][0]
    assert match["route_from"] == "DEP1" and match["planned_level_range"] == [0, 350]
    # The same SIGMET under the cruise segment stays below the aircraft.
    high_route = flight([(0.0, 100.0), (0.0, 101.0), (0.0, 110.0), (0.0, 111.0)], names=["DEP1", "TOC", "TOD", "ARR1"])
    cruise = box(104.0, -1.0, 106.0, 1.0, low=0, high=100, ident="SIM-VA-CRUISE")
    assert evaluate_vaa(high_route, feed([cruise]), {"status": "unavailable"})["matches"] == []


def test_a_current_va_sigmet_on_the_route_that_expires_before_passage_is_held_not_no_crossing():
    # SIMULATED: in force now, over the second leg, but it ends before the aircraft gets there (no successor held).
    route = flight([(0.0, 100.0), (0.0, 105.0), (0.0, 110.0)])
    early = box(107.0, -1.0, 108.0, 1.0, end="2026-07-22T04:30:00+00:00", ident="SIM-VA-EARLY")
    view = view_of(route, feed([early]), {"DARWIN": ("available", 0)})
    check = view["vaa"]["check"]
    assert rows(view)["VA SIGMET FEED"]["status"] == "REACHED"
    assert check["state"] == "UNRESOLVED" and check["tile"] == "HELD"
    assert "SIM-VA-EARLY on the route expires before the flight passes; successor not held" in check["line"]


def test_a_sigmet_answer_from_after_the_flight_is_never_a_clean_sigmet_receipt():
    route = flight(EQUATOR)
    current = assess_significant_weather(route, snapshot={**feed(), "advisories": []})
    assert current["clean_current_feed_no_match"] is True
    late = assess_significant_weather(route, snapshot={**feed(retrieved="2026-09-27T12:48:47+00:00"), "advisories": []})
    assert late["clean_current_feed_no_match"] is False
    assert late["feed_currency"] == "NOT CURRENT"
    blind = assess_significant_weather(flight(EQUATOR, profile=""), snapshot={**feed(), "advisories": []})
    assert blind["clean_current_feed_no_match"] is False


# ------------------------------------------------------------------------------------------ the rendered PDF

def _block_network(monkeypatch):
    def blocked(*_args, **_kwargs):
        raise OSError("network blocked by test_item2_volcanic_source_status_20261024 (offline)")
    monkeypatch.setattr(socket, "getaddrinfo", blocked)
    monkeypatch.setattr(socket, "create_connection", blocked)


def _rendered_pdf(monkeypatch, tmp_path, name, feed_snapshot, vaac_status="available"):
    import fitz

    from app.analysis import run_odss_analysis
    from app.odss.combined_brief import render_combined_briefing
    import json

    source = CORPUS / name
    if not source.is_file():
        pytest.skip(f"private corpus file {name} is not on this machine")
    _block_network(monkeypatch)
    for key in ("ODSS_SIGMET_SOURCE", "ODSS_OPMET_SOURCE", "ODSS_TC_TRACK_SOURCE", "ODSS_TC_SIGMET_SOURCE",
                "ODSS_ADWX_SOURCE", "ODSS_WEATHER_CHART_AI"):
        monkeypatch.setenv(key, "disabled")
    for key in ("ODSS_DIRECT_SIGMET_SOURCES", "ODSS_TCA_ADVISORY_SOURCE", "ODSS_WEATHER_CHART_MODEL"):
        monkeypatch.setenv(key, "")
    monkeypatch.setenv("ODSS_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("ODSS_VA_SIGMET_SOURCE", "awc")
    monkeypatch.setenv("ODSS_VAAC_ADVISORY_SOURCE", "jma-tokyo,anchorage,darwin,toulouse,gts-mirror,wifs-global")
    monkeypatch.setattr(vaa_module, "live_vaa_snapshot", lambda hazard_code="VA": feed_snapshot)
    monkeypatch.setattr(vaa_module, "fetch_mounted_vaac_snapshots", lambda _flight, mounted: [
        {"centre": entry["centre"], "provider": entry.get("provider"), "status": vaac_status,
         "coverage_status": "simulated", "advisories": [], "retrieved_at_utc": feed_snapshot.get("retrieved_at_utc")}
        for entry in mounted])
    result = run_odss_analysis(source, tmp_path / "results", tmp_path / "reports", 1)
    analysis = json.loads(Path(result["analysis_path"]).read_text())
    out = tmp_path / "briefing.pdf"
    render_combined_briefing(analysis["flight"], analysis["findings"], analysis["view"].get("warnings") or [], out,
                             source_pdf_path=str(source), weather_charts=analysis.get("weather_charts"),
                             company_briefing_references=None)
    return analysis, [" ".join(page.get_text().split()) for page in fitz.open(str(out))]


def test_the_rendered_page_six_names_a_stale_feed_reached_never_not_reached(monkeypatch, tmp_path):
    # SQ366 departs 04 Aug 1730Z; SIMULATED: the feed answered 30 min before departure but failed its freshness check.
    analysis, pages = _rendered_pdf(monkeypatch, tmp_path, SQ366,
                                    feed(freshness="stale", retrieved="2026-08-04T17:00:00+00:00"))
    closing = pages[-1]
    # 25 Oct 2026 QA: the group's names, a colon, then its words ("VA SIGMET FEED: reached, not current" alone).
    assert re.search(r"VA SIGMET FEED(?:(?:, | and )[A-Z ]+)*:\s+reached,\s+not current", closing), closing
    assert not re.search(r"VA SIGMET FEED(?:(?:, | and )[A-Z ]+)*:\s+not reached", closing)
    view_rows = {row["source"]: row for row in analysis["view"]["briefing"]["source_assurance"]}
    assert view_rows["VA SIGMET FEED"]["status"] == "REACHED · NOT CURRENT"


def test_the_rendered_page_six_of_a_reached_current_route_claims_every_live_source(monkeypatch, tmp_path):
    analysis, pages = _rendered_pdf(monkeypatch, tmp_path, SQ366, feed(retrieved="2026-08-04T17:00:00+00:00"))
    closing = pages[-1]
    check = analysis["view"]["briefing"]["vaa"]["check"]
    assert check["state"] == "CHECKED · NO MATCH", check["line"]
    assert "VA SIGMET FEED" not in closing.split("SOURCE ASSURANCE:", 1)[1].split(".", 1)[0]

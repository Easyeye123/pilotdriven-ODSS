"""Boss 03 Sep 00:37: "All the NOTAMs also need to be analysed JUST summarised
critical and don't need to show. Can hide and click to be active".

The NOTAM engine already analyses every OFP station package; a station outside
the planning roles (an "informational" station such as EDDM on the JFK-SIN
OFP) was analysed but never panelled, so the dashboard could not show its
critical lines behind its code. Those stations now get a dashboard-only panel;
the PDF and every other publication never see it, so REV3 stays byte-identical.
"""

from __future__ import annotations

from app.odss import briefing as briefing_module
from app.odss.briefing import _airport_operational_panels, build_briefing_view
from app.odss.parser import parse_lido


def _notam_finding(location: str, role: str, notam_id: str, text: str) -> dict:
    return {
        "engine": "notam",
        "title": f"{notam_id} - {location}",
        "summary": f"{text.capitalize()} during the applicable window.",
        "severity": "warning",
        "data": {
            "location": location,
            "role": role,
            "notam_id": notam_id,
            "raw_text": text,
            "valid_from_utc": "2026-08-01T00:00:00Z",
            "valid_to_utc": "2026-09-30T23:59:00Z",
            "source_page": 12,
            "source_role": role,
            "category": "runway",
            "pertinence_rank": 1,
            "pertinence_kind": "runway_closure",
            "applicability": "active",
            "window_start_utc": "2026-08-01T02:00:00Z",
            "window_end_utc": "2026-08-01T06:00:00Z",
            "stateAtReference": "active_at_reference",
        },
    }


FLIGHT = {
    "departure": "WSSS",
    "destination": "VTBS",
    "departure_runway": "20C",
    "destination_runway": "19L",
    "alternates": [],
    "edto": {},
    "fuel_enroute_airports": [],
    "scheduled_departure_utc": "2026-08-01T02:50:00Z",
    "scheduled_arrival_utc": "2026-08-01T05:20:00Z",
}
FINDINGS = [
    _notam_finding("WSSS", "departure", "S1/26", "RWY 02L/20R CLSD"),
    _notam_finding("EDDM", "informational", "E1/26", "RWY 08L/26R CLSD"),
    _notam_finding("EDDM", "informational", "E2/26", "TWY A CLSD"),
]


def test_an_informational_station_gets_a_dashboard_only_enroute_panel() -> None:
    panels = _airport_operational_panels(FLIGHT, FINDINGS)

    by_icao = {panel["icao"]: panel for panel in panels}
    assert list(by_icao) == ["WSSS", "VTBS", "EDDM"], "planning stations first, then the rest"
    assert "dashboard_only" not in by_icao["WSSS"]
    assert "dashboard_only" not in by_icao["VTBS"]

    eddm = by_icao["EDDM"]
    assert eddm["dashboard_only"] is True
    assert eddm["role"] == "enroute"
    assert eddm["role_key"] == "enroute"
    assert eddm["role_keys"] == ["enroute"]
    assert [item["notam_id"] for item in eddm["selected_notams"]] == ["E1/26", "E2/26"]
    assert all(item["compact_text"] for item in eddm["selected_notams"]), "the dashboard line is published on every record"
    assert any(line["kind"] == "notam" for line in eddm["card_summary_lines"])


def _lido_pages() -> list[str]:
    pages = [
        """SUMMARY STANDARD CFP
9VAAA SQ722 SIN/BKK ETD 0250 01AUG26
SCHED DEP 0250 UTC SCHED ARR 0520 UTC
RTE NO 001 A350-941
WSSS/20C
DCT BOBI1 DCT BOBI2
VTBS/19L
GND  MILES    900
AIR  MILES    930
BURNOFF 02.00 010000
TAXI FUEL 001000
FLT PLAN REQMT 03.00 015000
FUEL IN TANKS 04.00 020000
PZFW 180000
PTOW 200000
PLWT 190000
""",
        "",
        "",
        "",
        "",
        "",
        """BOBI1 00.15
N01 20.0 E103 50.0 105*
BOBI2 00.25
N03 10.0 E105 40.0 090
""",
    ]
    return [f"PAGE {index} OF {len(pages)} SQ722 SIN/BKK 01AUG26\n{page}" for index, page in enumerate(pages, start=1)]


def test_only_the_dashboard_view_publishes_the_dashboard_only_panels() -> None:
    flight = parse_lido(_lido_pages(), "SQ722-cfp.pdf")

    published = build_briefing_view(flight, list(FINDINGS), [])
    dashboard = build_briefing_view(flight, list(FINDINGS), [], include_dashboard_only_panels=True)

    assert [panel["icao"] for panel in published["airport_operational_panels"]] == ["WSSS", "VTBS"], "PDF and reports never see the rest-of-route panels"
    assert [panel["icao"] for panel in dashboard["airport_operational_panels"]] == ["WSSS", "VTBS", "EDDM"]
    assert dashboard["airport_operational_panels"][2]["dashboard_only"] is True
    assert not any(panel.get("dashboard_only") for panel in published["airport_operational_panels"])

    # Everything else the two views publish is identical: the rest-of-route
    # panel feeds no overview highlight, decision gate or alternate row.
    volatile = {"airport_operational_panels", "generated_at_utc"}
    published_rest = {key: value for key, value in published.items() if key not in volatile}
    dashboard_rest = {key: value for key, value in dashboard.items() if key not in volatile}
    assert published_rest == dashboard_rest


def test_the_saved_clock_wrapper_forwards_the_dashboard_flag() -> None:
    flight = parse_lido(_lido_pages(), "SQ722-cfp.pdf")
    # app.odss wraps build_briefing_view to inject the saved timing view; the
    # wrapper must pass the new flag through, or the dashboard silently loses
    # the rest-of-route panels.
    dashboard = briefing_module.build_briefing_view(flight, list(FINDINGS), [], include_dashboard_only_panels=True)
    assert [panel["icao"] for panel in dashboard["airport_operational_panels"]] == ["WSSS", "VTBS", "EDDM"]

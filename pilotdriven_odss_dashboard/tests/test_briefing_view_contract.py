from __future__ import annotations

from copy import deepcopy
from datetime import datetime

from app.odss.briefing import (
    _compact_notam_lines,
    _terrain_summary,
    build_briefing_view,
)
from app.odss.parser import parse_lido


LOG_PAGE_HIGH = (
    "ALPHA        01.25 0.27 ... ... ... ... ... ..... 486  005  02.4 ...\n"
    "S08 20.2 E107 49.7 117*0225 410 ... 164 M01 05041 495 1530 023.1 ...\n"
    " \n"
    "BRAVO        02.10 0.20 ... ... ... ... ... ..... 486  004  01.7 ...\n"
    "S12 44.0 E109 50.5 042 0160 410 ... 164 M01 07059 489 1755 025.5 ...\n"
)
LOG_PAGE_LOW = (
    "ALPHA        01.25 0.27 ... ... ... ... ... ..... 486  005  02.4 ...\n"
    "S08 20.2 E107 49.7 056 0225 410 ... 164 M01 05041 495 1530 023.1 ...\n"
    " \n"
    "BRAVO        02.10 0.20 ... ... ... ... ... ..... 486  004  01.7 ...\n"
    "S12 44.0 E109 50.5 042 0160 410 ... 164 M01 07059 489 1755 025.5 ...\n"
)


def _flight(log_page: str) -> dict:
    page1 = (
        "SUMMARY STANDARD CFP\n"
        "9VAAA SQ999 SIN/BKK ETD 0250 01AUG26\n"
        "SCHED DEP 0250 UTC SCHED ARR 0520 UTC\n"
        "RTE NO 001            A350-941 MH  CAPT TESTA B C\n"
        "WSSS/20C\n"
        "DCT ALPHA DCT BRAVO\n"
        "VTBS/19L\n"
        "GND  MILES    900\n"
        "AIR  MILES    930\n"
        "BURNOFF 02.00 010000\n"
        "TAXI FUEL 001000\n"
        "FLT PLAN REQMT 03.00 015000\n"
        "FUEL IN TANKS 04.00 020000\n"
        "PZFW 180000\n"
        "PTOW 200000\n"
        "PLWT 190000\n"
    )
    pages = [page1, "", "", "", "", "", log_page]
    return parse_lido(pages, "briefing-view-contract.pdf")


def test_terrain_key_is_engine_backed_and_always_present() -> None:
    high = build_briefing_view(_flight(LOG_PAGE_HIGH), [], [])
    assert high["terrain"]["events"], "a >100* waypoint must produce a terrain event"
    assert "No strict MSA" not in high["terrain"]["summary"]

    low = build_briefing_view(_flight(LOG_PAGE_LOW), [], [])
    assert low["terrain"]["events"] == []
    assert low["terrain"]["summary"] == "No strict MSA >100* window detected"


def test_terrain_summary_and_events_can_never_disagree() -> None:
    view = build_briefing_view(_flight(LOG_PAGE_HIGH), [], [])
    has_events = bool(view["terrain"]["events"])
    says_none = "No strict MSA" in view["terrain"]["summary"]
    assert has_events != says_none


def test_terrain_summary_requires_a_validated_controlled_profile_match() -> None:
    flight = _flight(LOG_PAGE_HIGH)
    terrain_event_id = build_briefing_view(flight, [], [])["terrain"]["events"][0][
        "terrain_event_id"
    ]
    candidate = {
        "engine": "depressurisation",
        "severity": "unknown",
        "title": "Candidate profile",
        "summary": "Candidate only",
        "details": [],
        "data": {
            "chart_number": "50-17",
            "coverage_complete": True,
            "reference_status": "unavailable",
            "terrain_event_id": terrain_event_id,
        },
    }
    candidate_view = build_briefing_view(flight, [candidate], [])
    assert "0/1 terrain windows have validated profile matches" in candidate_view["terrain"]["summary"]
    assert "manual review required" in candidate_view["terrain"]["summary"]

    stale = {
        **candidate,
        "severity": "warning",
        "title": "Stale validated profile",
        "summary": "Controlled match for another terrain window",
        "data": {
            **candidate["data"],
            "reference_status": "controlled-index-loaded",
            "terrain_event_id": "terrain:UNRELATED@1-STALE@2",
        },
    }
    stale_view = build_briefing_view(flight, [stale], [])
    assert "0/1 terrain windows have validated profile matches" in stale_view["terrain"]["summary"]
    assert "manual review required" in stale_view["terrain"]["summary"]

    validated = {
        **candidate,
        "severity": "warning",
        "title": "Validated profile",
        "summary": "Approved controlled match",
        "data": {
            **candidate["data"],
            "reference_status": "controlled-index-loaded",
        },
    }
    validated_view = build_briefing_view(flight, [validated], [])
    assert "1/1 terrain windows have validated profile matches on the terrain page" in validated_view["terrain"]["summary"]


def test_terrain_summary_requires_every_detected_window_to_have_its_own_match() -> None:
    events = [
        {
            "terrain_event_id": "terrain:ALPHA@10-BRAVO@20",
            "first_high": {"name": "ALPHA", "msa_hundreds_ft": 117},
            "last_high": {"name": "BRAVO", "msa_hundreds_ft": 124},
            "maximum": {"name": "BRAVO", "msa_hundreds_ft": 124},
        },
        {
            "terrain_event_id": "terrain:CHARLIE@30-DELTA@40",
            "first_high": {"name": "CHARLIE", "msa_hundreds_ft": 108},
            "last_high": {"name": "DELTA", "msa_hundreds_ft": 112},
            "maximum": {"name": "DELTA", "msa_hundreds_ft": 112},
        },
    ]
    one_match = {
        "engine": "depressurisation",
        "data": {
            "chart_number": "50-2",
            "coverage_complete": True,
            "reference_status": "controlled-index-loaded",
            "terrain_event_id": events[0]["terrain_event_id"],
        },
    }

    summary = _terrain_summary(events, [one_match])

    assert "1/2 terrain windows have validated profile matches" in summary
    assert "manual review required for 1 unmatched terrain window" in summary


def test_airport_panels_carry_raw_metar_and_taf() -> None:
    flight = _flight(LOG_PAGE_LOW)
    flight["weather"] = [
        {"location": "WSSS", "record_type": "METAR", "text": "SA 172000 11007KT 9999 FEW018", "source_page": 14},
        {"location": "WSSS", "record_type": "TAF", "text": "FT 171700 1718/1900 14008KT 9999", "source_page": 14},
        {"location": "VTBS", "record_type": "METAR", "text": "SA 172000 AUTO 05006KT 9999", "source_page": 15},
    ]
    view = build_briefing_view(flight, [], [])

    assert view["departure"]["weather"]["metar"] == "SA 172000 11007KT 9999 FEW018"
    assert view["departure"]["weather"]["taf"] == "FT 171700 1718/1900 14008KT 9999"
    assert view["destination"]["weather"]["metar"] == "SA 172000 AUTO 05006KT 9999"
    assert view["destination"]["weather"]["taf"] is None


def test_airport_panels_without_records_stay_honest() -> None:
    flight = _flight(LOG_PAGE_LOW)
    flight["weather"] = []
    view = build_briefing_view(flight, [], [])

    assert view["departure"]["weather"]["metar"] is None
    assert view["departure"]["weather"]["taf"] is None


def test_shared_weather_chart_selection_holds_unclassified_pages_for_review() -> None:
    manifest = {
        "status": "held",
        "charts": [
            {
                "chart_number": index,
                "page_number": 30 + index,
                "kind": "unclassified",
                "classification_status": "unclassified",
                "verified": False,
                "image_sha256": f"sha-{index}",
            }
            for index in range(1, 11)
        ],
    }

    selection = build_briefing_view(
        _flight(LOG_PAGE_LOW),
        [],
        [],
        weather_charts=manifest,
    )["hazards"]["weather_chart_selection"]

    assert selection == {
        "status": "manual-review-required",
        "reason": "No governed route-context classification is available.",
        "selected_charts": [],
        "raw_chart_count": 10,
        "held_pages": list(range(31, 41)),
    }


def test_shared_weather_chart_selection_requires_governed_route_match() -> None:
    base = {
        "classification_status": "classified",
        "verified": True,
        "kind": "sigwx_high_level",
        "valid_time_utc": "2026-08-01T04:00:00Z",
        "source": "uploaded_package",
    }
    manifest = {
        "status": "held",
        "charts": [
            {**base, "chart_number": 1, "page_number": 41},
            {
                **base,
                "chart_number": 2,
                "page_number": 42,
                "route_context": {
                    "status": "matched",
                    "governed": True,
                    "basis": "Controlled route-corridor and validity match",
                },
            },
        ],
    }

    selection = build_briefing_view(
        _flight(LOG_PAGE_LOW),
        [],
        [],
        weather_charts=manifest,
    )["hazards"]["weather_chart_selection"]

    assert selection["status"] == "selected"
    assert selection["raw_chart_count"] == 2
    assert [chart["page_number"] for chart in selection["selected_charts"]] == [42]
    assert selection["selected_charts"][0]["route_context"] == {
        "status": "matched",
        "governed": True,
        "basis": "Controlled route-corridor and validity match",
    }


def test_printed_chart_selection_matches_identity_and_nearest_flight_validity() -> None:
    def chart(
        number: int,
        page: int,
        valid_time: str,
        *,
        flight_number: str = "SQ999",
    ) -> dict:
        return {
            "chart_number": number,
            "page_number": page,
            "classification_status": "ocr-classified",
            "verified": True,
            "kind": "sigwx_high_level",
            "valid_time_utc": valid_time,
            "flight_levels": "FL250-FL600",
            "label": f"SIGWX · FL250-FL600 · valid {valid_time}",
            "source": "uploaded_package",
            "route_context": {
                "status": "printed",
                "source": "tesseract_ocr",
                "flight_number": flight_number,
                "departure_iata": "SIN",
                "destination_iata": "BKK",
                "valid_time_utc": valid_time,
                "flight_levels": "FL250-FL600",
                "chart_kind": "sigwx_high_level",
                "title": "FIXED TIME PROGNOSTIC CHART",
                "evidence": "printed-title-route-levels-validity",
            },
        }

    manifest = {
        "charts": [
            chart(1, 45, "2026-08-01T04:00:00+00:00", flight_number="SQ998"),
            chart(2, 46, "2026-08-01T01:00:00+00:00"),
            chart(3, 47, "2026-08-01T04:00:00+00:00"),
        ],
    }

    selection = build_briefing_view(
        _flight(LOG_PAGE_LOW),
        [],
        [],
        weather_charts=manifest,
    )["hazards"]["weather_chart_selection"]

    assert selection["status"] == "selected"
    assert selection["raw_chart_count"] == 3
    assert [item["page_number"] for item in selection["selected_charts"]] == [47]
    selected = selection["selected_charts"][0]
    context = selected["route_context"]
    assert context["status"] == "matched"
    assert context["governed"] is True
    assert context["flight_number"] == "SQ999"
    assert "validity ranked against the CFP flight window" in context["basis"]
    assert selected["valid_time_utc"] == "2026-08-01T04:00:00+00:00"
    assert selected["valid_time_display"] == "01 AUG 0400Z"
    assert selected["display_label"] == "SIGWX · FL250-FL600 · valid 01 AUG 0400Z"
    assert manifest["charts"][2].get("display_label") is None
    assert manifest["charts"][2]["label"].endswith("2026-08-01T04:00:00+00:00")


def test_printed_chart_selection_does_not_invent_carrier_code_aliases() -> None:
    manifest = {
        "charts": [{
            "chart_number": 1,
            "page_number": 47,
            "classification_status": "ocr-classified",
            "verified": True,
            "kind": "sigwx_high_level",
            "valid_time_utc": "2026-08-01T04:00:00+00:00",
            "flight_levels": "FL250-FL600",
            "source": "uploaded_package",
            "route_context": {
                "status": "printed",
                "source": "tesseract_ocr",
                "flight_number": "SIA999",
                "departure_iata": "SIN",
                "destination_iata": "BKK",
                "valid_time_utc": "2026-08-01T04:00:00+00:00",
                "flight_levels": "FL250-FL600",
                "chart_kind": "sigwx_high_level",
                "title": "FIXED TIME PROGNOSTIC CHART",
                "evidence": "printed-title-route-levels-validity",
            },
        }],
    }

    selection = build_briefing_view(
        _flight(LOG_PAGE_LOW),
        [],
        [],
        weather_charts=manifest,
    )["hazards"]["weather_chart_selection"]

    assert selection["status"] == "manual-review-required"
    assert selection["selected_charts"] == []


def test_chart_selection_keeps_nearest_match_per_product_and_level_family() -> None:
    def chart(
        number: int,
        page: int,
        kind: str,
        flight_levels: str,
        valid_time: str,
    ) -> dict:
        return {
            "chart_number": number,
            "page_number": page,
            "classification_status": "classified",
            "verified": True,
            "kind": kind,
            "valid_time_utc": valid_time,
            "flight_levels": flight_levels,
            "source": "uploaded_package",
            "route_context": {
                "status": "matched",
                "governed": True,
                "basis": "Controlled route-corridor and validity match",
            },
        }

    manifest = {
        "charts": [
            chart(1, 41, "sigwx_high_level", "FL 250 - 600", "2026-08-01T03:00:00Z"),
            chart(2, 42, "sigwx_high_level", "FL250-FL600", "2026-08-01T04:00:00Z"),
            chart(3, 43, "sigwx_mid_level", "FL100-FL450", "2026-08-01T04:00:00Z"),
            chart(4, 44, "wind_temperature", "FL340", "2026-08-01T04:00:00Z"),
            chart(5, 45, "wind_temperature", "FL390", "2026-08-01T04:00:00Z"),
            chart(6, 46, "wind_temperature", "FL 340", "2026-08-01T03:00:00Z"),
        ],
    }

    selection = build_briefing_view(
        _flight(LOG_PAGE_LOW),
        [],
        [],
        weather_charts=manifest,
    )["hazards"]["weather_chart_selection"]

    assert selection["status"] == "selected"
    assert selection["raw_chart_count"] == 6
    assert [item["page_number"] for item in selection["selected_charts"]] == [
        42,
        43,
        44,
        45,
    ]
    assert "each distinct product and flight-level family" in selection["reason"]


def test_incomplete_chart_classification_never_publishes_a_partial_selection() -> None:
    valid = {
        "chart_number": 1,
        "page_number": 1,
        "classification_status": "classified",
        "verified": True,
        "kind": "sigwx_high_level",
        "valid_time_utc": "2026-08-01T04:00:00Z",
        "flight_levels": "FL250-FL600",
        "route_context": {
            "status": "matched",
            "governed": True,
            "basis": "Controlled route-corridor and validity match",
        },
    }
    manifest = {
        "status": "manual-review-required",
        "coverage": {
            "held_chart_count": 41,
            "classification_capacity": 40,
            "classification_work_count": 40,
            "unprocessed_chart_count": 1,
            "classification_incomplete": True,
        },
        "charts": [valid] + [
            {
                "chart_number": index,
                "page_number": index,
                "classification_status": "unclassified",
                "verified": False,
                "kind": "unclassified",
            }
            for index in range(2, 42)
        ],
    }

    selection = build_briefing_view(
        _flight(LOG_PAGE_LOW),
        [],
        [],
        weather_charts=manifest,
    )["hazards"]["weather_chart_selection"]

    assert selection["status"] == "manual-review-required"
    assert selection["selected_charts"] == []
    assert selection["raw_chart_count"] == 41
    assert selection["classification_incomplete"] is True
    assert "41 held pages exceed the 40-page analysis capacity" in selection["reason"]


def test_route_matched_chart_outside_flight_window_is_never_selected() -> None:
    manifest = {
        "charts": [
            {
                "chart_number": 1,
                "page_number": 46,
                "classification_status": "ocr-classified",
                "verified": True,
                "kind": "sigwx_high_level",
                "valid_time_utc": "2026-08-01T01:00:00+00:00",
                "route_context": {
                    "status": "printed",
                    "source": "tesseract_ocr",
                    "flight_number": "SQ999",
                    "departure_iata": "SIN",
                    "destination_iata": "BKK",
                    "valid_time_utc": "2026-08-01T01:00:00+00:00",
                    "flight_levels": "FL250-FL600",
                    "chart_kind": "sigwx_high_level",
                    "title": "FIXED TIME PROGNOSTIC CHART",
                    "evidence": "printed-title-route-levels-validity",
                },
            },
        ],
    }

    selection = build_briefing_view(
        _flight(LOG_PAGE_LOW),
        [],
        [],
        weather_charts=manifest,
    )["hazards"]["weather_chart_selection"]

    assert selection["status"] == "manual-review-required"
    assert selection["selected_charts"] == []
    assert selection["closest_validity_delta_minutes"] == 110
    assert selection["closest_validity_relation"] == "before-departure"
    assert "110 minutes before departure" in selection["reason"]


def test_all_governed_product_families_outside_window_require_manual_review() -> None:
    manifest = {
        "charts": [
            {
                "chart_number": 1,
                "page_number": 51,
                "classification_status": "classified",
                "verified": True,
                "kind": "sigwx_high_level",
                "valid_time_utc": "2026-08-01T01:00:00Z",
                "flight_levels": "FL250-FL600",
                "route_context": {
                    "status": "matched",
                    "governed": True,
                    "basis": "Controlled route-corridor and validity match",
                },
            },
            {
                "chart_number": 2,
                "page_number": 52,
                "classification_status": "classified",
                "verified": True,
                "kind": "wind_temperature",
                "valid_time_utc": "2026-08-01T06:00:00Z",
                "flight_levels": "FL340",
                "route_context": {
                    "status": "matched",
                    "governed": True,
                    "basis": "Controlled route-corridor and validity match",
                },
            },
        ],
    }

    selection = build_briefing_view(
        _flight(LOG_PAGE_LOW),
        [],
        [],
        weather_charts=manifest,
    )["hazards"]["weather_chart_selection"]

    assert selection["status"] == "manual-review-required"
    assert selection["selected_charts"] == []
    assert selection["closest_validity_delta_minutes"] == 40
    assert selection["closest_validity_relation"] == "after-arrival"


def test_shared_airport_panels_carry_selected_source_facts_for_every_role() -> None:
    flight = _flight(LOG_PAGE_LOW)
    flight["alternates"] = [{
        "airport": "WMKK",
        "runway": "32L",
        "approach": "ILS",
        "minima": "220FT/800M",
    }]
    flight["edto"]["airports"] = [{
        "airport": "WADD",
        "runway": "27",
        "approach": "RNP",
        "minima": "453FT/1900M",
        "period_start_utc": "2026-08-01T03:00:00+00:00",
        "period_end_utc": "2026-08-01T04:00:00+00:00",
    }]
    flight["fuel_enroute_airports"] = [{
        "airport": "WIII",
        "iata": "CGK",
        "name": "JAKARTA",
        "role": "fuel_enroute_airport",
        "source_pages": [17, 29],
    }]
    stations = ["WSSS", "VTBS", "WMKK", "WADD", "WIII"]
    flight["weather"] = [
        {
            "location": station,
            "record_type": record_type,
            "text": f"{record_type} EXACT {station}",
            "source_page": 10 + index,
            **(
                {"source_role": "fuel_enroute_airport"}
                if station == "WIII"
                else {}
            ),
        }
        for index, station in enumerate(stations)
        for record_type in ("METAR", "TAF")
    ]
    role_by_station = {
        "WSSS": "departure",
        "VTBS": "destination",
        "WMKK": "destination alternate",
        "WADD": "EDTO",
        "WIII": "fuel enroute airport",
    }
    findings = [
        {
            "engine": "notam",
            "severity": "warning",
            "title": f"{role.title()} NOTAM TEST{index}/26",
            "summary": f"Derived summary {station}",
            "details": [],
            "data": {
                "role": role,
                "source_role": (
                    "fuel_enroute_airport" if station == "WIII" else None
                ),
                "location": station,
                "notam_id": f"TEST{index}/26",
                "raw_text": f"EXACT ITEM E {station}",
                "category": "AIRPORT",
                "priority_score": 5,
                "pertinence_rank": 3,
                "pertinence_kind": "runway_approach_restriction",
                "applicability": "active",
                "valid_from_utc": "2026-07-01T00:00:00+00:00",
                "valid_to_utc": "2026-09-01T00:00:00+00:00",
                "window_start_utc": "2026-08-01T02:00:00+00:00",
                "window_end_utc": "2026-08-01T06:00:00+00:00",
                "source_page": 20 + index,
            },
        }
        for index, (station, role) in enumerate(role_by_station.items(), start=1)
    ]

    panels = build_briefing_view(flight, findings, [])["airport_operational_panels"]
    assert [(item["role"], item["icao"]) for item in panels] == list(
        (role, station) for station, role in role_by_station.items()
    )
    for panel in panels:
        station = panel["icao"]
        assert panel["weather"]["metar"]["text"] == f"METAR EXACT {station}"
        assert panel["weather"]["taf"]["text"] == f"TAF EXACT {station}"
        assert len(panel["selected_notams"]) == 1
        selected = panel["selected_notams"][0]
        assert selected["summary"] == f"Derived summary {station}"
        assert selected["item_e_text"] == f"EXACT ITEM E {station}"
        assert selected["valid_from_utc"] == "2026-07-01T00:00:00+00:00"
        assert isinstance(selected["source_page"], int)
        assert [item["kind"] for item in panel["card_summary_lines"]] == [
            "weather",
            "weather",
            "notam",
        ]
        assert panel["card_summary_lines"][-1]["text"] == selected["summary"]


def test_overlapping_airport_roles_share_one_panel_and_keep_all_planning_rows() -> None:
    flight = _flight(LOG_PAGE_LOW)
    flight["edto"]["airports"] = [{
        "airport": "WADD",
        "runway": "27",
        "approach": "RNP",
        "minima": "453FT/1900M",
    }]
    flight["fuel_enroute_airports"] = [{
        "airport": "WADD",
        "iata": "DPS",
        "name": "BALI",
        "role": "fuel_enroute_airport",
        "source_pages": [15, 27],
    }]
    finding = {
        "engine": "notam",
        "severity": "warning",
        "title": "Fuel-enroute WADD NOTAM TEST1/26",
        "summary": "ILS unavailable during the applicable window.",
        "details": [],
        "data": {
            "role": "fuel enroute airport",
            "source_role": "fuel_enroute_airport",
            "location": "WADD",
            "notam_id": "TEST1/26",
            "raw_text": "ILS AND GP RWY 27 U/S",
            "category": "APPROACH PROCEDURE",
            "priority_score": 10,
            "pertinence_rank": 2,
            "pertinence_kind": "approach_navaid_closure",
            "applicability": "active",
            "valid_from_utc": "2026-07-01T00:00:00+00:00",
            "valid_to_utc": "2026-09-01T00:00:00+00:00",
            "source_page": 27,
        },
    }

    view = build_briefing_view(flight, [finding], [])
    wadds = [
        panel
        for panel in view["airport_operational_panels"]
        if panel["icao"] == "WADD"
    ]

    assert len(wadds) == 1
    panel = wadds[0]
    assert panel["role"] == "EDTO"
    assert panel["role_key"] == "edto"
    assert panel["roles"] == ["EDTO", "fuel enroute airport"]
    assert panel["role_keys"] == ["edto", "fuel_enroute_airport"]
    assert [row["planning_role_key"] for row in panel["operational_rows"]] == [
        "edto",
        "fuel_enroute_airport",
    ]
    assert [item["notam_id"] for item in panel["selected_notams"]] == [
        "TEST1/26"
    ]
    assert [item["icao"] for item in view["fuel_enroute_airports"]] == ["WADD"]


def test_metrics_carry_the_captain() -> None:
    view = build_briefing_view(_flight(LOG_PAGE_LOW), [], [])
    assert view["metrics"]["captain"] == "TESTA B C"


def test_shared_overview_is_source_backed_generic_and_does_not_mutate_inputs() -> None:
    flight = _flight(LOG_PAGE_LOW)
    flight.update({
        "flight_number": "ZX451",
        "departure": "KAAA",
        "destination": "KBBB",
        "departure_iata": "AAA",
        "destination_iata": "BBB",
        "departure_runway": "17",
        "destination_runway": "35",
        "sid": "ALFA2",
        "star": "BRAVO1",
        "route_identifier": "GENERIC7",
        # This fixture is a SUMMARY STANDARD CFP whose separate FLT RULES
        # token is RVSM. Both source facts must survive as distinct chips.
        "edto_rvsm": "RVSM",
        "cost_index": 42,
        "apd_percent": 1.7,
        "route_waypoints": [
            {
                "name": "KAAA",
                "actm_minutes": 0,
                "latitude": 10.0,
                "longitude": 20.0,
                "msa_hundreds_ft": 20,
                "msa_asterisk": False,
                "vws": 1,
            },
            {
                "name": "WINDY",
                "actm_minutes": 40,
                "latitude": 11.0,
                "longitude": 21.0,
                "msa_hundreds_ft": 30,
                "msa_asterisk": False,
                "vws": 5,
            },
            {
                "name": "HIGH1",
                "actm_minutes": 70,
                "latitude": 12.0,
                "longitude": 22.0,
                "msa_hundreds_ft": 111,
                "msa_asterisk": True,
                "vws": 2,
            },
            {
                "name": "HIGH2",
                "actm_minutes": 80,
                "latitude": 13.0,
                "longitude": 23.0,
                "msa_hundreds_ft": 124,
                "msa_asterisk": True,
                "vws": 2,
            },
            {
                "name": "KBBB",
                "actm_minutes": 150,
                "latitude": 14.0,
                "longitude": 24.0,
                "msa_hundreds_ft": 50,
                "msa_asterisk": False,
                "vws": 1,
            },
        ],
    })
    flight["edto"]["entry_actm_minutes"] = 25

    def weather(phase: str, location: str, conditions: str) -> dict:
        return {
            "engine": "weather",
            "severity": "information",
            "title": f"{phase} weather",
            "summary": "Engine-decoded window",
            "details": [],
            "data": {
                "phase": phase,
                "location": location,
                "applicable_conditions": conditions,
                "utc_window": "01 AUG 0200-0330Z",
                "timing": "TAF base group at the reference time",
                "window_status": "no_significant_overlap",
                "record_types": ["TAF"],
                "source_references": [
                    {"document_id": "synthetic-cfp.pdf", "source_page": 12}
                ],
            },
        }

    def notam(
        *,
        role: str,
        location: str,
        notam_id: str,
        kind: str,
        summary: str,
        raw_text: str,
        page: int,
    ) -> dict:
        return {
            "engine": "notam",
            "severity": "warning",
            "title": f"{role.title()} NOTAM {notam_id}",
            "summary": summary,
            "details": [],
            "data": {
                "role": role,
                "location": location,
                "notam_id": notam_id,
                "raw_text": raw_text,
                "category": "AIRPORT",
                "priority_score": 10,
                "pertinence_rank": 1,
                "pertinence_kind": kind,
                "applicability": "active",
                "source_page": page,
            },
        }

    findings = [
        weather("Departure", "KAAA", "wind 170 degrees 8 kt · visibility 10 km or more"),
        weather("Destination", "KBBB", "wind 350 degrees 6 kt · few clouds 2,000 ft"),
        notam(
            role="departure",
            location="KAAA",
            notam_id="A1001/26",
            kind="runway_closure",
            summary="RWY 08 closed outside the flight window.",
            raw_text="RWY 08 CLSD",
            page=21,
        ),
        notam(
            role="departure",
            location="KAAA",
            notam_id="A1002/26",
            kind="runway_approach_restriction",
            summary="Localiser signal may be interrupted.",
            raw_text="LOC 'LAA' 110.3 RWY 17 MAY INTERRUPT OR OSCILLATE DUE CRANE",
            page=22,
        ),
        notam(
            role="destination",
            location="KBBB",
            notam_id="B2001/26",
            kind="runway_closure",
            summary="Planned runway closes after arrival.",
            raw_text="RWY 35 CLSD AFTER 0600UTC",
            page=31,
        ),
        notam(
            role="destination",
            location="KBBB",
            notam_id="B2002/26",
            kind="approach_navaid_closure",
            summary="ILS unavailable.",
            raw_text="ILS AND GP RWY 35 U/S",
            page=32,
        ),
    ]
    flight_before = deepcopy(flight)
    findings_before = deepcopy(findings)

    view = build_briefing_view(flight, findings, [])
    overview = view["overview"]

    assert flight == flight_before
    assert findings == findings_before
    departure_panel = next(
        panel
        for panel in view["airport_operational_panels"]
        if "departure" in set(panel.get("role_keys") or [])
    )
    departure_relations = {
        line["notam_id"]: line
        for line in departure_panel["card_summary_lines"]
        if line.get("kind") == "notam"
    }
    assert departure_relations["A1001/26"]["different_runway"] is True
    assert departure_relations["A1001/26"]["planned_match"] is False
    assert departure_relations["A1002/26"]["different_runway"] is False
    assert departure_relations["A1002/26"]["planned_match"] is True
    assert [(chip["key"], chip["label"]) for chip in overview["chips"]] == [
        ("route_identifier", "GENERIC7"),
        ("edto_rvsm", "RVSM"),
        # SUMMARY STANDARD CFP states its classification as a chip (23 Aug).
        ("classification", "NON-EDTO"),
        ("cost_index", "CI 42"),
        ("apd_percent", "APD 1.7%"),
    ]
    assert overview["departure"]["plan"]["display"] == "RWY 17 / ALFA2"
    assert overview["destination"]["plan"]["display"] == "RWY 35 / BRAVO1"
    assert overview["departure"]["schedule"]["scheduled_utc"] == flight[
        "scheduled_departure_utc"
    ]
    assert overview["destination"]["schedule"]["scheduled_utc"] == flight[
        "scheduled_arrival_utc"
    ]
    assert overview["departure"]["forecast_at_reference"] == {
        "applicable_conditions": "wind 170 degrees 8 kt · visibility 10 km or more",
        "utc_window": "01 AUG 0200-0330Z",
        "timing": "TAF base group at the reference time",
        "window_status": "no_significant_overlap",
        "source_references": [
            {"document_id": "synthetic-cfp.pdf", "source_page": 12}
        ],
    }
    departure_highlight = overview["departure"]["primary_operational_highlight"]
    assert departure_highlight["signal_family"] == "approach_navaid"
    assert departure_highlight["notam_id"] == "A1002/26"
    assert departure_highlight["source_page"] == 22
    destination_highlight = overview["destination"]["primary_operational_highlight"]
    assert destination_highlight == {
        "text": "ILS/GP RWY35 unavailable.",
        "signal_family": "approach_navaid",
        "notam_id": "B2002/26",
        "source_page": 32,
    }
    assert [anchor["kind"] for anchor in overview["timeline"]] == [
        "departure",
        "edto",
        "vws",
        "terrain",
        "arrival",
    ]
    assert overview["timeline"][2]["label"] == "WINDY"
    assert overview["timeline"][2]["detail"] == "VWS 005"
    assert overview["timeline"][3]["label"] == "HIGH1-HIGH2"
    assert overview["timeline"][3]["detail"] == "111*-124*"


def test_cfp_weather_count_excludes_live_enrichment_without_source_pages() -> None:
    flight = _flight(LOG_PAGE_LOW)
    flight["weather"] = [
        {
            "location": flight["departure"],
            "record_type": "METAR",
            "text": "METAR LIVE ENRICHMENT",
            "source": "noaa_awc_live",
            "provider": "noaa-awc-data-api",
            "source_page": None,
        },
        {
            "location": flight["departure"],
            "record_type": "METAR",
            "text": "SA 010200 17008KT 9999 FEW020",
            "source_page": 14,
        },
        {
            "location": flight["departure"],
            "record_type": "TAF",
            "text": "FT 010100 0102/0208 17008KT 9999 FEW020",
            "source_page": 14,
        },
    ]

    view = build_briefing_view(flight, [], [])

    assert view["cfp_weather"] == {
        "record_count": 2,
        "source_pages": [14],
    }
    cfp_assurance = next(
        row
        for row in view["source_assurance"]
        if row["source"] == "CFP WEATHER"
    )
    assert cfp_assurance == {
        "source": "CFP WEATHER",
        "status": "HELD",
        "detail": "2 parsed bulletin record(s).",
    }
    departure_panel = next(
        panel
        for panel in view["airport_operational_panels"]
        if "departure" in set(panel.get("role_keys") or [])
    )
    assert departure_panel["weather"]["metar"] == {
        "record_type": "METAR",
        "text": "SA 010200 17008KT 9999 FEW020",
        "source_page": 14,
        "source_role": None,
    }


def test_shared_performance_publication_owns_rtow_selection_and_margin() -> None:
    flight = _flight(LOG_PAGE_LOW)
    flight["performance"].update({
        "obstacle_rtow_kg": 297_400,
        "landing_rtow_kg": 312_027,
        "structural_rtow_kg": 280_000,
        "controlling_rtow_kg": 290_000,
    })

    publication = build_briefing_view(flight, [], [])["performance_publication"]

    assert publication["status"] == "within-limit"
    assert publication["ptow_kg"] == 200_000
    assert publication["selected_rtow_kg"] == 280_000
    assert publication["selected_candidate_keys"] == ["structural"]
    assert publication["margin_kg"] == 80_000
    assert [item["key"] for item in publication["candidate_limits"]] == [
        "performance",
        "landing",
        "structural",
        "cfp_controlling",
    ]
    assert [
        item["key"]
        for item in publication["candidate_limits"]
        if item["selected"]
    ] == ["structural"]


def test_shared_communication_timeline_never_drops_items_after_five() -> None:
    findings = [
        {
            "engine": "communications",
            "severity": "information",
            "title": f"Call {index}",
            "summary": f"Contact point {index}",
            "details": [],
            "data": {"action_actm_minutes": index * 10},
        }
        for index in range(1, 8)
    ]
    view = build_briefing_view(_flight(LOG_PAGE_LOW), findings, [])
    assert len(view["communications"]) == 7
    assert [item["event"] for item in view["communications"]] == [
        f"Call {index}" for index in range(1, 8)
    ]

    timing_view = {
        "early_calls": [
            {
                "utc_clock": f"0{index}00Z",
                "actm": f"0{index}.00",
                "label": f"Timed call {index}",
                "details": f"Timed contact point {index}",
            }
            for index in range(1, 8)
        ],
    }
    timed_view = build_briefing_view(
        _flight(LOG_PAGE_LOW),
        [],
        [],
        timing_view=timing_view,
    )
    assert len(timed_view["communications"]) == 7
    assert timed_view["communications"][-1]["event"] == "Timed call 7"

    long_event = "FULL COMMUNICATION EVENT " + "X" * 90
    long_detail = "FULL COMMUNICATION DETAIL " + "Y" * 110
    long_view = build_briefing_view(
        _flight(LOG_PAGE_LOW),
        [{
            "engine": "communications",
            "severity": "information",
            "title": long_event,
            "summary": long_detail,
            "details": [],
            "data": {"action_actm_minutes": 75},
        }],
        [],
    )
    assert long_view["communications"][0]["event"] == long_event
    assert long_view["communications"][0]["detail"] == long_detail


def test_edto_operational_rows_are_part_of_the_view() -> None:
    view = build_briefing_view(_flight(LOG_PAGE_LOW), [], [])
    rows = view["edto"]["operational_rows"]
    assert rows and rows[0]["label"] == "CLASSIFICATION"
    labels = [row["label"] for row in rows]
    assert labels == ["CLASSIFICATION", "GATE"]
    assert all(isinstance(row["value"], str) and row["value"] for row in rows)


def test_va_sigmet_records_become_named_deduped_advisories() -> None:
    flight = _flight(LOG_PAGE_LOW)
    record = {
        "location": "WIIF",
        "record_type": "VA_SIGMET",
        "text": "WIIF JAKARTA FIR WV SIGMET 08 VALID 172009/180208 WIII- WIIF JAKARTA FIR VA ERUPTION MT KRAKATAU PSN S0606 E10525 VA CLD OBS AT 1930Z WI S0614 E10534 - S0623 E10451 SFC/FL070 MOV NW 10KT NC=",
        "source_page": 13,
    }
    flight["weather"] = [dict(record), dict(record)]
    view = build_briefing_view(flight, [], [])
    advisories = view["vaa"]["cfp_advisories"]
    assert len(advisories) == 1, "identical wx-list reprints collapse to one advisory"
    assert advisories[0]["name"] == "VOLCANIC ASH · MT KRAKATAU · WIIF WV SIGMET 08"
    assert advisories[0]["valid_from"] == "172009" and advisories[0]["valid_to"] == "180208"


def test_va_polygon_screening_derives_closest_approach() -> None:
    flight = _flight(LOG_PAGE_LOW)
    flight["weather"] = [{
        "location": "WIIF",
        "record_type": "VA_SIGMET",
        "text": (
            "WIIF JAKARTA FIR WV SIGMET 08 VALID 172009/180208 VA ERUPTION "
            "MT KRAKATAU PSN S0606 E10525 VA CLD OBS AT 1930Z WI "
            "S0720 E10749 - S0720 E10849 - S0620 E10800 SFC/FL070 MOV NW 10KT NC="
        ),
        "source_page": 13,
    }]
    view = build_briefing_view(flight, [], [])
    derived = view["vaa"]["cfp_advisories"][0]["derived"]
    # Nearest polygon point sits 60 NM north of ALPHA (S08 20.2 E107 49.7):
    # the screening says so with the passage time (ALPHA ACTM 01:25 after the
    # 0250Z departure), the layer, and the no-official-VAAC caveat verbatim.
    # The SIGMET's validity day is nowhere near this synthetic flight date,
    # so no expiry comparison may be printed.
    assert derived.startswith("Closest approach 60 NM near ALPHA; route passes ~0415Z; ash layer SFC/FL070;")
    assert "expiry" not in derived and "validity (to" not in derived
    assert "official VAAC confirmation unavailable" in derived


def test_va_screening_compares_passage_time_with_sigmet_validity() -> None:
    flight = _flight(LOG_PAGE_LOW)
    polygon = "WI S0720 E10749 - S0720 E10849 - S0620 E10800 SFC/FL070"
    # Passage is ~0415Z on 01 Aug (ALPHA ACTM 01:25 after 0250Z departure).
    for valid, expected in (
        ("010300/010500", "inside the SIGMET's validity (to 0500Z)"),
        ("010200/010355", "20 min after the SIGMET's 0355Z expiry"),
    ):
        flight["weather"] = [{
            "location": "WIIF", "record_type": "VA_SIGMET",
            "text": f"WIIF JAKARTA FIR WV SIGMET 08 VALID {valid} VA ERUPTION MT KRAKATAU {polygon}",
        }]
        view = build_briefing_view(flight, [], [])
        derived = view["vaa"]["cfp_advisories"][0]["derived"]
        assert expected in derived, derived


def test_va_caveat_reflects_a_held_official_advisory() -> None:
    flight = _flight(LOG_PAGE_LOW)
    flight["weather"] = [{
        "location": "WIIF", "record_type": "VA_SIGMET",
        "text": (
            "WIIF JAKARTA FIR WV SIGMET 08 VALID 010300/010500 VA ERUPTION "
            "MT KRAKATAU WI S0720 E10749 - S0720 E10849 - S0620 E10800 SFC/FL070"
        ),
    }]
    flight["vaa_review"] = {"direct_vaac_snapshot": {"advisories": [{
        "volcano": "KRAKATAU 262000", "vaac": "DARWIN", "centre": "DARWIN",
        "advisory_number": "2026/116", "issued_at_utc": "2026-08-01T08:00:00+00:00",
        "remarks": "CURRENT SATELLITE IMAGERY INDICATES VA HAS NOW DISSIPATED. ADVISORY TERMINATED.",
    }]}}
    view = build_briefing_view(flight, [], [])
    derived = view["vaa"]["cfp_advisories"][0]["derived"]
    assert "official VAAC confirmation unavailable" not in derived
    assert (
        "official DARWIN advisory 2026/116 (01/0800Z) reports the ash dissipated"
        in derived
    ), derived

    # A held advisory for a DIFFERENT volcano changes nothing: the honest
    # caveat stays, and the manifest may still say DARWIN reached.
    flight["vaa_review"]["direct_vaac_snapshot"]["advisories"][0]["volcano"] = "SEMERU 263300"
    view = build_briefing_view(flight, [], [])
    assert "official VAAC confirmation unavailable" in view["vaa"]["cfp_advisories"][0]["derived"]


def test_va_advisory_without_readable_polygon_has_no_derived_line() -> None:
    flight = _flight(LOG_PAGE_LOW)
    flight["weather"] = [{
        "location": "WIIF",
        "record_type": "VA_SIGMET",
        # Two-point "polygon": unreadable as an area, so no distance may be
        # invented - the card shows only the named advisory.
        "text": "WIIF JAKARTA FIR WV SIGMET 08 VALID 172009/180208 VA ERUPTION MT KRAKATAU WI S0614 E10534 - S0623 E10451 SFC/FL070",
        "source_page": 13,
    }]
    view = build_briefing_view(flight, [], [])
    assert view["vaa"]["cfp_advisories"][0]["derived"] is None


def test_sigmet_cards_split_merged_records_and_carry_verdict_reasons() -> None:
    flight = _flight(LOG_PAGE_LOW)
    # One CFP FIR block printing two SIGMETs, exactly as Lido does. ALPHA is
    # S08 20.2 E107 49.7; the first polygon contains it, the second sits far
    # south of the whole route.
    flight["weather"] = [{
        "location": "YMMM", "record_type": "SIGMET",
        "text": (
            "YMMM MELBOURNE FIR WS SIGMET A01 VALID 010100/010200 YMMC- "
            "YMMM MELBOURNE FIR SEV ICE FCST WI S0700 E10600 - S0700 E10900 - "
            "S0930 E10900 - S0930 E10600 8000FT/FL210 MOV E 50KT NC= "
            "WS SIGMET B02 VALID 010300/010700 YMMC- YMMM MELBOURNE FIR SEV TURB "
            "FCST WI S4900 E08300 - S4400 E09500 - S5000 E11800 FL140/250 MOV E 35KT NC="
        ),
    }]
    view = build_briefing_view(flight, [], [])
    cards = {card["sigmet_id"]: card for card in view["hazards"]["sigmet_cards"]}
    assert set(cards) == {"A01", "B02"}

    # A01 contains ALPHA (ACTM 01:25 -> passes 0415Z) but expired 0200Z:
    # crossing window printed, expiry gap named, NOT PROMOTED.
    a01 = cards["A01"]
    assert a01["layer"] == "8000FT/FL210" and a01["phenomenon"] == "SEV ICE"
    assert a01["disposition"] == "NOT PROMOTED"
    assert "crosses the route" in a01["screening"] and "expires" in a01["screening"]

    # B02 never touches the route: distance + bearing, NOT PROMOTED.
    b02 = cards["B02"]
    assert b02["layer"] == "FL140/250"
    assert b02["disposition"] == "NOT PROMOTED"
    assert "does not intersect" in b02["screening"] and "NM south" in b02["screening"]


def test_sigmet_inside_validity_is_promoted_and_no_polygon_is_review() -> None:
    flight = _flight(LOG_PAGE_LOW)
    flight["weather"] = [{
        "location": "WSJC", "record_type": "SIGMET",
        # Valid 0100-0800Z, ALPHA crossing ~0415Z -> inside validity.
        "text": (
            "WSJC SINGAPORE FIR WS SIGMET C03 VALID 010100/010800 WSSS- "
            "WSJC SINGAPORE FIR EMBD TS FCST WI S0700 E10600 - S0700 E10900 - "
            "S0930 E10900 - S0930 E10600 TOP FL450 MOV W 10KT NC="
        ),
    }, {
        "location": "WIIF", "record_type": "SIGMET",
        "text": "WIIF JAKARTA FIR WS SIGMET D04 VALID 010100/010800 WIII- WIIF JAKARTA FIR SEV TURB FCST ENTIRE FIR FL200/380 MOV E 5KT NC=",
    }]
    view = build_briefing_view(flight, [], [])
    cards = {card["sigmet_id"]: card for card in view["hazards"]["sigmet_cards"]}
    assert cards["C03"]["disposition"] == "PROMOTED"
    assert "inside the product's validity" in cards["C03"]["screening"]
    # ENTIRE FIR carries no polygon: screening honestly unavailable.
    assert cards["D04"]["disposition"] == "REVIEW REQUIRED"
    assert "review the original SIGMET" in cards["D04"]["screening"]


def test_coverage_ledger_marks_absent_sections_unavailable() -> None:
    flight = _flight(LOG_PAGE_LOW)
    view = build_briefing_view(flight, [], [])
    ledger = {row["label"]: row["status"] for row in view["hazards"]["coverage_ledger"]}
    assert ledger == {"AIRMET": "unavailable", "TC SIGMET": "unavailable", "VA SIGMET": "unavailable"}
    flight["weather"] = [{
        "location": "WIIF", "record_type": "VA_SIGMET",
        "text": "WIIF JAKARTA FIR WV SIGMET 08 VALID 010300/010500 VA ERUPTION MT KRAKATAU WI S0720 E10749 - S0720 E10849 - S0620 E10800 SFC/FL070",
    }]
    view = build_briefing_view(flight, [], [])
    ledger = {row["label"]: row["status"] for row in view["hazards"]["coverage_ledger"]}
    assert ledger["VA SIGMET"] == "held"


def test_vaac_reach_is_composed_in_the_view_for_every_surface() -> None:
    # The tally and per-centre strings were once arithmetic inside the PDF
    # renderer, so the dashboard never showed them (deploy #20 comparison).
    flight = _flight(LOG_PAGE_LOW)
    flight["vaa_review"] = {
        "status": "review_required",
        "vaac_centre_ledger": [
            {"centre": "Anchorage", "status": "available"},
            {"centre": "Darwin", "status": "partial"},
            {"centre": "Tokyo", "status": "available"},
            {"centre": "London", "status": "unavailable"},
            {"centre": "Wellington", "status": "not_mounted"},
        ],
    }
    view = build_briefing_view(flight, [], [])
    reach = view["hazards"]["vaac_reach"]
    assert reach["summary"] == "3/5 reached"
    assert reach["centres"][0] == {"centre": "ANCHORAGE", "status": "reached"}
    assert reach["centres"][1] == {"centre": "DARWIN", "status": "partial"}
    assert reach["centres"][4] == {"centre": "WELLINGTON", "status": "not mounted"}

    flight["vaa_review"] = {}
    view = build_briefing_view(flight, [], [])
    # No direct-feed ledger held: the tally states the full centre count, and
    # the Doc 9766 responsibility block still resolves from the route alone
    # (21 Aug: the receipt must say which centre owns this route).
    empty_reach = view["hazards"]["vaac_reach"]
    assert empty_reach["summary"] == "0/9 reached"
    assert empty_reach["centres"] == []
    assert all(row["reached"] is False for row in empty_reach["responsible"])
    assert empty_reach["responsible_source"]["document"].startswith("ICAO Doc 9766")


def test_no_va_records_mean_no_advisories() -> None:
    flight = _flight(LOG_PAGE_LOW)
    flight["weather"] = []
    view = build_briefing_view(flight, [], [])
    assert view["vaa"]["cfp_advisories"] == []


def test_compact_notam_prefers_the_planned_runway_and_resolves_printed_schedule() -> None:
    notices = [{
        "notam_id": "A1000/26",
        "summary": "Other runway is unavailable.",
        "item_e_text": "RWY 02R/20L IS NOT AVAILABLE FOR CIVIL USE",
        "pertinence_kind": "runway_closure",
        "pertinence_rank": 1,
        "severity": "critical",
    }, {
        "notam_id": "A2000/26",
        "summary": "Printed schedule requires review.",
        "item_e_text": (
            "RWY 02L/20R WILL BE CLSD BTN 1700UTC TO 2200UTC EV SUN AND WED "
            "FM 04SEP25 TO 30SEP25. RWY 02L/20R WILL BE CLSD BTN 1730UTC TO "
            "2130UTC EV SUN AND WED FM 30SEP25 TO 31MAR27"
        ),
        "pertinence_kind": "runway_closure",
        "pertinence_rank": 1,
        "severity": "critical",
    }, {
        "notam_id": "A0001/26",
        "summary": "Stand restriction.",
        "item_e_text": (
            "ACFT STAND 504 CLOSED; SURVEY EQUIPMENT NEAR RWY 02L/20R GP "
            "CRITICAL AREA"
        ),
        "pertinence_kind": "apron_stand_closure",
        "pertinence_rank": 1,
        "severity": "warning",
    }]

    lines = _compact_notam_lines(
        notices,
        "destination",
        limit=2,
        planned_runways={"20R"},
        reference_time=datetime.fromisoformat("2026-08-19T14:10:00+00:00"),
    )

    assert [line["notam_id"] for line in lines] == ["A2000/26", "A1000/26"]
    assert lines[0]["text"] == (
        "RWY 02L/20R closes 1730-2130Z; ETA 1410Z precedes closure by 3h20."
    )


def test_compact_notam_holds_wrong_direction_and_prefers_return_runway_signal() -> None:
    notices = [{
        "notam_id": "A1000/26",
        "summary": "Generic restriction.",
        "item_e_text": "FLIGHTS DEPARTING TEST ON ATS ROUTE N571 MAY BE RESTRICTED",
        "pertinence_kind": "runway_approach_restriction",
        "pertinence_rank": 1,
        "severity": "warning",
    }, {
        "notam_id": "A2000/26",
        "summary": "LOC signal may oscillate; runway is not reported closed.",
        "item_e_text": "LOC IGD 109.5 RWY 21 SUBJ TO INTRP DUE CRANE OPS",
        "pertinence_kind": "obstacle",
        "pertinence_rank": 8,
        "severity": "warning",
    }]

    destination = _compact_notam_lines(
        notices,
        "destination",
        limit=2,
        planned_runways={"21"},
    )

    assert [line["notam_id"] for line in destination] == ["A2000/26"]
    assert destination[0]["text"] == (
        "LOC IGD 109.5 RWY21 subject to interruption / possible signal "
        "oscillation due crane operations; runway is not reported closed."
    )

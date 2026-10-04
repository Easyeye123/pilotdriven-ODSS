from datetime import datetime, timedelta, timezone

import pytest

from app.odss.briefing import _compact_runway_schedule_text, _reference_time_for_roles
from app.odss.engines import _notam_reference_at, _notam_role_window, _weather_role_window
from app.odss.opmet import _station_forecast_window
from app.odss.report_facts import operational_reference_times


def _flight():
    # Synthetic timing contract, independent of any airport's real restrictions.
    return {
        "departure": "FAOR", "destination": "WSSS",
        "scheduled_departure_utc": "2026-08-25T18:25:00Z",
        "scheduled_arrival_utc": "2026-08-26T05:00:00Z",
        "actual_takeoff_utc": "2026-08-25T19:00:00Z",
        "route_waypoints": [{"name": "WSSS", "actm_minutes": 601}],
        "alternates": [{"airport": "WMKK"}],
    }


def test_departure_and_arrival_notam_windows_follow_actual_anchor():
    flight = _flight()
    actual = datetime(2026, 8, 25, 19, tzinfo=timezone.utc)
    arrival = actual + timedelta(minutes=601)
    for station, expected_role, reference, margin in (
        ("FAOR", "departure", actual, 60),
        ("WSSS", "destination", arrival, 120),
        ("WMKK", "destination alternate", arrival, 120),
    ):
        role, start, end = _notam_role_window(flight, station, {"WMKK"}, {})
        assert role == expected_role
        assert (start, end) == (reference - timedelta(minutes=margin), reference + timedelta(minutes=margin))
        assert _notam_reference_at(flight, role, start) == reference
    assert flight["scheduled_arrival_utc"] == "2026-08-26T05:00:00Z"


def test_forecast_selection_and_engine_use_the_same_actual_arrival():
    flight = _flight()
    expected = (datetime(2026, 8, 26, 4, 1, tzinfo=timezone.utc), datetime(2026, 8, 26, 6, 1, tzinfo=timezone.utc))
    for station in ("WSSS", "WMKK"):
        assert _station_forecast_window(flight, station) == expected
        assert _weather_role_window(flight, station, {"WMKK"}, {})[1:] == expected


def test_runway_closure_summary_changes_at_actual_arrival_boundary():
    flight = _flight()
    reference = _reference_time_for_roles(flight, {"destination"}, [])
    assert reference == datetime(2026, 8, 26, 5, 1, tzinfo=timezone.utc)
    # Test-only source schedule; no assertion about a real airport closure.
    notice = {"item_e_text": "RWY 02L/20R WILL BE CLSD BTN 0501 TO 0600 EV WED FM 01AUG26 TO 31AUG26"}
    summary = _compact_runway_schedule_text(notice, role="destination", planned_runways={"02L", "20R"}, reference_time=reference)
    assert "ETA 0501Z is within the closure" in summary


def test_no_actual_anchor_keeps_the_original_schedule():
    flight = _flight()
    del flight["actual_takeoff_utc"]
    assert operational_reference_times(flight) == (
        datetime(2026, 8, 25, 18, 25, tzinfo=timezone.utc),
        datetime(2026, 8, 26, 5, 0, tzinfo=timezone.utc),
    )


@pytest.mark.parametrize("value", [None, -1, True, 601.5, "unknown"])
def test_missing_or_invalid_destination_actm_never_reuses_scheduled_arrival(value):
    flight = _flight()
    flight["route_waypoints"][0]["actm_minutes"] = value
    assert operational_reference_times(flight)[1] is None
    assert _station_forecast_window(flight, "WSSS") is None
    with pytest.raises(ValueError, match="exact destination timing: destination ACTM is missing or invalid"):
        _notam_role_window(flight, "WSSS", set(), {})


def test_waypoint_ata_derived_anchor_is_used_without_changing_printed_schedule():
    flight = _flight()
    del flight["actual_takeoff_utc"]
    flight["timing_reference"] = {"actual_takeoff_utc": "2026-08-26T03:00:00+08:00"}
    assert operational_reference_times(flight)[1] == datetime(2026, 8, 26, 5, 1, tzinfo=timezone.utc)
    assert flight["scheduled_departure_utc"] == "2026-08-25T18:25:00Z"

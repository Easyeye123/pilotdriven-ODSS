"""Official tropical-cyclone track context with route-time screening.

Hong Kong Observatory publishes a public XML tropical-cyclone list and timed
track points.  This module keeps only official timed points, interpolates
between those points as a labelled ODSS screening estimate, and compares the
estimated centre position with the time-matched CFP route.

The centre line is not a wind field, forecast cone, SIGMET, or operational
impact boundary.  It therefore never creates a clear/affected verdict by
itself.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from math import asin, atan2, cos, degrees, radians, sin, sqrt
import os
import re
from threading import Lock
import time
from typing import Any
from xml.etree import ElementTree

import httpx


HKO_ORIGIN = "https://www.weather.gov.hk"
HKO_TC_LIST_PATH = "/wxinfo/currwx/tc_list.xml"
_MAX_XML_BYTES = 1024 * 1024
_MAX_CYCLONES = 8
_CACHE: tuple[float, dict[str, Any]] | None = None
_CACHE_LOCK = Lock()
_TC_ID = re.compile(r"^\d{4}$")


def _utc(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _coordinate(value: str | None, *, latitude: bool) -> float | None:
    match = re.fullmatch(r"\s*(\d{1,3}(?:\.\d+)?)\s*([NSEW])\s*", str(value or ""), re.I)
    if not match:
        return None
    number = float(match.group(1))
    direction = match.group(2).upper()
    limit = 90.0 if latitude else 180.0
    if number > limit or (latitude and direction not in {"N", "S"}) or (
        not latitude and direction not in {"E", "W"}
    ):
        return None
    return -number if direction in {"S", "W"} else number


def _safe_xml(raw: bytes) -> ElementTree.Element:
    if len(raw) > _MAX_XML_BYTES:
        raise ValueError("HKO tropical-cyclone XML exceeded the safety limit")
    upper = raw.upper()
    if b"<!DOCTYPE" in upper or b"<!ENTITY" in upper:
        raise ValueError("HKO tropical-cyclone XML contained a prohibited declaration")
    return ElementTree.fromstring(raw)


def _text(element: ElementTree.Element, name: str) -> str:
    child = element.find(name)
    return str(child.text or "").strip() if child is not None else ""


def _point(element: ElementTree.Element, kind: str) -> dict[str, Any] | None:
    when = _utc(_text(element, "Time"))
    latitude = _coordinate(_text(element, "Latitude"), latitude=True)
    longitude = _coordinate(_text(element, "Longitude"), latitude=False)
    # Untimed ForecastInformation records are line-drawing intermediates, not
    # standalone forecast positions.  They are deliberately excluded.
    if when is None or latitude is None or longitude is None:
        return None
    return {
        "kind": kind,
        "time_utc": _iso(when),
        "latitude": latitude,
        "longitude": longitude,
        "intensity": _text(element, "Intensity") or None,
        "maximum_wind": _text(element, "MaximumWind") or None,
    }


def parse_hko_list(raw: bytes) -> list[dict[str, str]]:
    root = _safe_xml(raw)
    result = []
    for item in root.findall(".//TropicalCyclone"):
        tc_id = _text(item, "TropicalCycloneID")
        if not _TC_ID.fullmatch(tc_id):
            continue
        result.append({
            "cyclone_id": tc_id,
            "name": _text(item, "TropicalCycloneEnglishName") or tc_id,
            "track_url": f"{HKO_ORIGIN}/wxinfo/currwx/hko_tctrack_{tc_id}.xml",
        })
        if len(result) >= _MAX_CYCLONES:
            break
    return result


def parse_hko_track(raw: bytes, *, cyclone_id: str, fallback_name: str = "") -> dict[str, Any]:
    if not _TC_ID.fullmatch(cyclone_id):
        raise ValueError("Invalid HKO tropical-cyclone id")
    root = _safe_xml(raw)
    points: list[dict[str, Any]] = []
    for name, kind in (
        ("PastInformation", "past"),
        ("AnalysisInformation", "analysis"),
        ("ForecastInformation", "forecast"),
    ):
        for element in root.findall(f".//{name}"):
            normalized = _point(element, kind)
            if normalized:
                points.append(normalized)
    points.sort(key=lambda item: item["time_utc"])
    report = root.find(".//WeatherReport")
    name = _text(report, "TropicalCycloneName") if report is not None else ""
    bulletin = root.find(".//BulletinHeader")
    return {
        "cyclone_id": cyclone_id,
        "name": name or fallback_name or cyclone_id,
        "bulletin_time_utc": _iso(
            _utc(_text(bulletin, "BulletinTime")) if bulletin is not None else None
        ),
        "positions": points,
        "raw_sha256": sha256(raw).hexdigest(),
    }


def fetch_hko_track_snapshot(
    *,
    client: httpx.Client | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    retrieved_at = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    own_client = client is None
    active_client = client or httpx.Client(
        timeout=httpx.Timeout(12.0, connect=5.0),
        follow_redirects=False,
        headers={
            "User-Agent": os.environ.get(
                "ODSS_WEATHER_USER_AGENT",
                "PilotDriven-ODSS/0.6.1 (operational decision-support QA)",
            ),
            "Accept": "application/xml,text/xml",
        },
    )
    try:
        list_response = active_client.get(f"{HKO_ORIGIN}{HKO_TC_LIST_PATH}")
        list_response.raise_for_status()
        entries = parse_hko_list(list_response.content)
        tracks = []
        errors = []
        for entry in entries:
            try:
                response = active_client.get(entry["track_url"])
                response.raise_for_status()
                tracks.append(parse_hko_track(
                    response.content,
                    cyclone_id=entry["cyclone_id"],
                    fallback_name=entry["name"],
                ))
            except (httpx.HTTPError, ValueError, ElementTree.ParseError) as exc:
                errors.append({
                    "cyclone_id": entry["cyclone_id"],
                    "error": f"{type(exc).__name__}: {str(exc)[:160]}",
                })
        return {
            "schema_version": "1.0",
            "status": "available" if not errors else "partial",
            "provider": "hong-kong-observatory-public-tc-track",
            "source_url": f"{HKO_ORIGIN}{HKO_TC_LIST_PATH}",
            "retrieved_at_utc": _iso(retrieved_at),
            "tracks": tracks,
            "errors": errors,
            "attribution": "Source: Hong Kong Observatory via DATA.GOV.HK",
        }
    except (httpx.HTTPError, ValueError, ElementTree.ParseError) as exc:
        return {
            "schema_version": "1.0",
            "status": "unavailable",
            "provider": "hong-kong-observatory-public-tc-track",
            "source_url": f"{HKO_ORIGIN}{HKO_TC_LIST_PATH}",
            "retrieved_at_utc": _iso(retrieved_at),
            "tracks": [],
            "errors": [{"error": f"{type(exc).__name__}: {str(exc)[:160]}"}],
            "attribution": "Source: Hong Kong Observatory via DATA.GOV.HK",
        }
    finally:
        if own_client:
            active_client.close()


def live_hko_track_snapshot() -> dict[str, Any]:
    global _CACHE
    try:
        seconds = max(300.0, min(1800.0, float(os.environ.get("ODSS_TC_TRACK_CACHE_SECONDS", 300))))
    except ValueError:
        seconds = 300.0
    now_monotonic = time.monotonic()
    with _CACHE_LOCK:
        if _CACHE and now_monotonic - _CACHE[0] < seconds:
            return deepcopy(_CACHE[1])
        snapshot = fetch_hko_track_snapshot()
        _CACHE = (now_monotonic, snapshot)
        return deepcopy(snapshot)


def _unwrap(longitude: float, reference: float) -> float:
    while longitude - reference > 180:
        longitude -= 360
    while longitude - reference < -180:
        longitude += 360
    return longitude


def _interpolate(first: dict[str, Any], second: dict[str, Any], when: datetime) -> tuple[float, float] | None:
    first_time = _utc(first.get("time_utc"))
    second_time = _utc(second.get("time_utc"))
    if not first_time or not second_time or not first_time <= when <= second_time:
        return None
    span = (second_time - first_time).total_seconds()
    fraction = 0.0 if span <= 0 else (when - first_time).total_seconds() / span
    first_lon = float(first["longitude"])
    second_lon = _unwrap(float(second["longitude"]), first_lon)
    longitude = first_lon + (second_lon - first_lon) * fraction
    if longitude > 180:
        longitude -= 360
    if longitude < -180:
        longitude += 360
    return (
        float(first["latitude"]) + (
            float(second["latitude"]) - float(first["latitude"])
        ) * fraction,
        longitude,
    )


def _track_position(positions: list[dict[str, Any]], when: datetime) -> tuple[float, float] | None:
    for first, second in zip(positions, positions[1:]):
        result = _interpolate(first, second, when)
        if result:
            return result
    return None


def _distance_nm(first: tuple[float, float], second: tuple[float, float]) -> float:
    lat1, lon1 = map(radians, first)
    lat2, lon2 = map(radians, second)
    delta_lat = lat2 - lat1
    delta_lon = radians(_unwrap(degrees(lon2), degrees(lon1)) - degrees(lon1))
    value = (
        sin(delta_lat / 2) ** 2
        + cos(lat1) * cos(lat2) * sin(delta_lon / 2) ** 2
    )
    return 3440.065 * 2 * asin(min(1.0, sqrt(value)))


def _bearing(first: tuple[float, float], second: tuple[float, float]) -> float:
    lat1, lon1 = map(radians, first)
    lat2, lon2 = map(radians, second)
    delta_lon = radians(_unwrap(degrees(lon2), degrees(lon1)) - degrees(lon1))
    y = sin(delta_lon) * cos(lat2)
    x = cos(lat1) * sin(lat2) - sin(lat1) * cos(lat2) * cos(delta_lon)
    return (degrees(atan2(y, x)) + 360) % 360


def _movement(track: dict[str, Any]) -> dict[str, Any] | None:
    actual = [
        item
        for item in track.get("positions") or []
        if item.get("kind") in {"past", "analysis"}
    ]
    if len(actual) < 2:
        return None
    first, second = actual[-2:]
    first_time = _utc(first.get("time_utc"))
    second_time = _utc(second.get("time_utc"))
    if not first_time or not second_time or second_time <= first_time:
        return None
    distance = _distance_nm(
        (float(first["latitude"]), float(first["longitude"])),
        (float(second["latitude"]), float(second["longitude"])),
    )
    hours = (second_time - first_time).total_seconds() / 3600
    return {
        "from_utc": first["time_utc"],
        "to_utc": second["time_utc"],
        "bearing_degrees": round(_bearing(
            (float(first["latitude"]), float(first["longitude"])),
            (float(second["latitude"]), float(second["longitude"])),
        )),
        "speed_knots": round(distance / hours, 1),
        "basis": "official timed analysis positions",
    }


def _route_screen(flight: dict[str, Any], positions: list[dict[str, Any]]) -> dict[str, Any] | None:
    anchor = _utc(
        flight.get("actual_takeoff_utc")
        or (flight.get("timing_reference") or {}).get("actual_takeoff_utc")
        or flight.get("scheduled_departure_utc")
    )
    route = [
        item
        for item in (flight.get("route_waypoints") or [])
        if item.get("latitude") is not None
        and item.get("longitude") is not None
        and item.get("actm_minutes") is not None
    ]
    if anchor is None or len(route) < 2 or len(positions) < 2:
        return None
    closest = None
    for index, (start, end) in enumerate(zip(route, route[1:])):
        start_actm = int(start["actm_minutes"])
        end_actm = int(end["actm_minutes"])
        if end_actm < start_actm:
            continue
        for step in range(5):
            fraction = step / 4
            when = anchor + timedelta(
                minutes=start_actm + (end_actm - start_actm) * fraction
            )
            cyclone = _track_position(positions, when)
            if cyclone is None:
                continue
            start_lon = float(start["longitude"])
            end_lon = _unwrap(float(end["longitude"]), start_lon)
            aircraft = (
                float(start["latitude"]) + (
                    float(end["latitude"]) - float(start["latitude"])
                ) * fraction,
                start_lon + (end_lon - start_lon) * fraction,
            )
            distance = _distance_nm(aircraft, cyclone)
            candidate = {
                "route_segment_index": index,
                "route_from": str(start.get("name") or ""),
                "route_to": str(end.get("name") or ""),
                "time_utc": _iso(when),
                "distance_nm": round(distance, 1),
                "aircraft_position": {
                    "latitude": round(aircraft[0], 4),
                    "longitude": round(aircraft[1], 4),
                },
                "cyclone_centre_position": {
                    "latitude": round(cyclone[0], 4),
                    "longitude": round(cyclone[1], 4),
                },
                "position_basis": (
                    "ODSS screening estimate interpolated between official timed "
                    "track positions"
                ),
            }
            if closest is None or distance < closest["distance_nm"]:
                closest = candidate
    return closest


def assess_tropical_cyclone_track(
    flight: dict[str, Any],
    *,
    snapshot: dict[str, Any] | None = None,
) -> dict[str, Any]:
    configured = os.environ.get("ODSS_TC_TRACK_SOURCE", "hko").strip().lower()
    if snapshot is None:
        if configured in {"", "disabled", "off", "none"}:
            snapshot = {
                "status": "disabled",
                "provider": None,
                "tracks": [],
                "errors": [],
            }
        elif configured == "hko":
            snapshot = live_hko_track_snapshot()
        else:
            snapshot = {
                "status": "unavailable",
                "provider": configured,
                "tracks": [],
                "errors": [{"error": "Unsupported ODSS_TC_TRACK_SOURCE setting"}],
            }
    if snapshot.get("status") == "disabled":
        review = {
            "schema_version": "1.0",
            "status": "not_assessed",
            "provider": None,
            "reason_codes": ["source_disabled"],
            "cyclones": [],
        }
        flight["tropical_cyclone_track_review"] = review
        return review
    if snapshot.get("status") not in {"available", "partial"}:
        review = {
            "schema_version": "1.0",
            "status": "review_required",
            "provider": snapshot.get("provider"),
            "retrieved_at_utc": snapshot.get("retrieved_at_utc"),
            "reason_codes": ["source_unavailable"],
            "cyclones": [],
            "errors": snapshot.get("errors") or [],
        }
        flight["tropical_cyclone_track_review"] = review
        return review

    threshold_nm = max(
        100.0,
        min(1000.0, float(os.environ.get("ODSS_TC_TRACK_SCREENING_RADIUS_NM", 500))),
    )
    cyclones = []
    reason_codes = []
    for track in snapshot.get("tracks") or []:
        closest = _route_screen(flight, track.get("positions") or [])
        if closest is None:
            reason_codes.append("route_or_track_timing_unavailable")
        cyclones.append({
            "cyclone_id": track.get("cyclone_id"),
            "name": track.get("name"),
            "bulletin_time_utc": track.get("bulletin_time_utc"),
            "current_position": next(
                (
                    item
                    for item in reversed(track.get("positions") or [])
                    if item.get("kind") == "analysis"
                ),
                None,
            ),
            "official_timed_positions": track.get("positions") or [],
            "movement": _movement(track),
            "closest_route_screening": closest,
            "screening_status": (
                "near_route_centreline_review_required"
                if closest and closest["distance_nm"] <= threshold_nm
                else "outside_centreline_screening_radius"
                if closest
                else "not_assessed"
            ),
        })
    if snapshot.get("status") == "partial":
        reason_codes.append("source_partial")
    review = {
        "schema_version": "1.0",
        "status": "context_available" if cyclones else "no_active_tracks",
        "provider": snapshot.get("provider"),
        "source_url": snapshot.get("source_url"),
        "retrieved_at_utc": snapshot.get("retrieved_at_utc"),
        "attribution": snapshot.get("attribution"),
        "screening_radius_nm": threshold_nm,
        "reason_codes": sorted(set(reason_codes)),
        "cyclones": cyclones,
        "source_note": (
            "Official timed cyclone centre positions and movement context only. "
            "The centre track is not a wind field, forecast cone, SIGMET, or "
            "operational impact boundary."
        ),
    }
    flight["tropical_cyclone_track_review"] = review
    return review


__all__ = [
    "HKO_ORIGIN",
    "HKO_TC_LIST_PATH",
    "assess_tropical_cyclone_track",
    "fetch_hko_track_snapshot",
    "parse_hko_list",
    "parse_hko_track",
]

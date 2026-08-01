"""Official OPMET enrichment for deterministic PilotDriven weather review.

The connector is intentionally narrow:

* NOAA Aviation Weather Center's documented machine-to-machine METAR/TAF API;
* one bounded station batch per product/date;
* raw records retained for audit while the existing timing engine decides
  pilot-facing pertinence;
* source failure never becomes a benign weather conclusion.

The official API contract is documented at
https://aviationweather.gov/data/api/ .
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import os
import re
from threading import Lock
import time
from typing import Any

import httpx

from .snapshot_governance import (
    govern_snapshot,
    mark_snapshot_reused,
    reusable_snapshot,
)


AWC_API_ORIGIN = "https://aviationweather.gov"
AWC_METAR_PATH = "/api/data/metar"
AWC_TAF_PATH = "/api/data/taf"
_MAX_RESPONSE_BYTES = 2 * 1024 * 1024
_MAX_STATIONS = 30
_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
_CACHE_LOCK = Lock()
_ICAO = re.compile(r"^[A-Z]{4}$")


def _utc(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, (int, float)):
        parsed = datetime.fromtimestamp(float(value), tz=timezone.utc)
    else:
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
    return value.astimezone(timezone.utc).isoformat() if value else None


def _setting_float(name: str, default: float, minimum: float, maximum: float) -> float:
    try:
        return max(minimum, min(maximum, float(os.environ.get(name, default))))
    except (TypeError, ValueError):
        return default


def _station_ids(flight: dict[str, Any]) -> list[str]:
    candidates: list[Any] = [
        flight.get("departure"),
        flight.get("destination"),
        *(item.get("airport") for item in (flight.get("alternates") or [])),
        *(
            item.get("airport")
            for item in ((flight.get("edto") or {}).get("airports") or [])
        ),
    ]
    result: list[str] = []
    for value in candidates:
        station = str(value or "").strip().upper()
        if not _ICAO.fullmatch(station) or station in result:
            continue
        result.append(station)
        if len(result) >= _MAX_STATIONS:
            break
    return result


def _user_agent() -> str:
    value = str(
        os.environ.get(
            "ODSS_WEATHER_USER_AGENT",
            "PilotDriven-ODSS/0.6.1 (operational decision-support QA)",
        )
    ).strip()
    return value[:180] or "PilotDriven-ODSS/0.6.1"


def _cache_seconds() -> float:
    # AWC asks clients not to request an endpoint more than once per minute.
    return _setting_float("ODSS_OPMET_CACHE_SECONDS", 60.0, 60.0, 900.0)


def _request_key(path: str, params: dict[str, str]) -> str:
    return f"{path}?{'&'.join(f'{key}={params[key]}' for key in sorted(params))}"


def _product_effective_window(
    path: str,
    records: list[Any],
) -> tuple[datetime | None, datetime | None]:
    if path == AWC_METAR_PATH:
        values = [
            _utc(record.get("reportTime")) or _utc(record.get("obsTime"))
            for record in records
            if isinstance(record, dict)
        ]
        valid = [value for value in values if value]
        return (
            min(valid, default=None),
            max(valid, default=None),
        )
    starts = [
        _utc(record.get("validTimeFrom"))
        for record in records
        if isinstance(record, dict)
    ]
    ends = [
        _utc(record.get("validTimeTo"))
        for record in records
        if isinstance(record, dict)
    ]
    return (
        min((value for value in starts if value), default=None),
        max((value for value in ends if value), default=None),
    )


def _govern_product_snapshot(
    path: str,
    snapshot: dict[str, Any],
    *,
    now: datetime,
) -> dict[str, Any]:
    """Normalize and re-check a fetched or injected source receipt.

    Tests and replay tooling may inject a source receipt instead of calling the
    public endpoint.  Those receipts must pass the same expiry gate as a live
    response; otherwise an old ``status=available`` fixture could silently be
    used as current operational evidence.
    """
    records = list(snapshot.get("records") or [])
    effective_start, effective_end = _product_effective_window(path, records)
    result = govern_snapshot(
        snapshot,
        now=now,
        refresh_after_seconds=_cache_seconds(),
        expires_after_seconds=max(300.0, _cache_seconds() * 3),
        scope=(
            "requested_noaa_awc_metar_records"
            if path == AWC_METAR_PATH
            else "requested_noaa_awc_taf_records"
        ),
        effective_start_utc=effective_start,
        effective_end_utc=effective_end,
    )
    reusable, reason = reusable_snapshot(result, now=now)
    result["reuse_status"] = "reusable" if reusable else "not_reusable"
    result["reuse_reason"] = reason
    return result


def _snapshot_is_usable(snapshot: dict[str, Any], *, now: datetime) -> bool:
    reusable, _ = reusable_snapshot(snapshot, now=now)
    return str(snapshot.get("status") or "").lower() == "available" and reusable


def _weather_window_minutes(flight: dict[str, Any]) -> tuple[int, int]:
    preference = flight.get("weather_window_preference") or {}

    def bounded(name: str) -> int:
        try:
            return max(0, min(720, int(preference.get(name, 60))))
        except (TypeError, ValueError):
            return 60

    return bounded("before_minutes"), bounded("after_minutes")


def _station_forecast_window(
    flight: dict[str, Any],
    station: str,
) -> tuple[datetime, datetime] | None:
    departure = str(flight.get("departure") or "").upper()
    destination = str(flight.get("destination") or "").upper()
    destination_alternates = {
        str(item.get("airport") or "").upper()
        for item in (flight.get("alternates") or [])
        if isinstance(item, dict)
    }
    before_minutes, after_minutes = _weather_window_minutes(flight)
    anchor = (
        _utc(flight.get("scheduled_departure_utc"))
        if station == departure
        else _utc(flight.get("scheduled_arrival_utc"))
        if station == destination or station in destination_alternates
        else None
    )
    if anchor is not None:
        return (
            anchor - timedelta(minutes=before_minutes),
            anchor + timedelta(minutes=after_minutes),
        )
    for airport in ((flight.get("edto") or {}).get("airports") or []):
        if str(airport.get("airport") or "").upper() != station:
            continue
        start = _utc(airport.get("period_start_utc"))
        end = _utc(airport.get("period_end_utc"))
        if start and end and start < end:
            return start, end
    return None


def _forecast_coverage_gaps(
    flight: dict[str, Any],
    records: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    taf_by_station: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        if record.get("record_type") != "TAF":
            continue
        taf_by_station.setdefault(str(record.get("location") or ""), []).append(record)
    gaps: list[dict[str, Any]] = []
    for station in _station_ids(flight):
        window = _station_forecast_window(flight, station)
        if window is None:
            continue
        window_start, window_end = window
        covers_window = any(
            (valid_from := _utc(record.get("valid_from_utc"))) is not None
            and (valid_to := _utc(record.get("valid_to_utc"))) is not None
            and valid_from <= window_start
            and window_end <= valid_to
            for record in taf_by_station.get(station, [])
        )
        if not covers_window:
            gaps.append({
                "station": station,
                "product": "TAF",
                "window_start_utc": _iso(window_start),
                "window_end_utc": _iso(window_end),
                "reason": "forecast_does_not_cover_operating_window",
            })
    return gaps


def _product_review(
    snapshots: list[dict[str, Any]],
    records: list[dict[str, Any]],
    *,
    record_type: str,
    now: datetime,
) -> dict[str, Any]:
    relevant = [record for record in records if record.get("record_type") == record_type]
    source = snapshots[0] if snapshots else {}
    statuses = [
        (
            "available"
            if _snapshot_is_usable(snapshot, now=now)
            else "stale"
            if snapshot.get("reuse_reason") == "snapshot_expired"
            else "unavailable"
        )
        for snapshot in snapshots
    ]
    effective_starts = [_utc(item.get("effective_start_utc")) for item in snapshots]
    effective_ends = [_utc(item.get("effective_end_utc")) for item in snapshots]
    retrieved = [_utc(item.get("retrieved_at_utc")) for item in snapshots]
    return {
        "status": (
            "available"
            if statuses and all(status == "available" for status in statuses)
            else "stale"
            if "stale" in statuses
            else "unavailable"
        ),
        "record_count": len({str(item.get("location") or "") for item in relevant}),
        "source_url": source.get("source_url"),
        "retrieved_at_utc": _iso(max((value for value in retrieved if value), default=None)),
        "effective_start_utc": _iso(min((value for value in effective_starts if value), default=None)),
        "effective_end_utc": _iso(max((value for value in effective_ends if value), default=None)),
        "refresh_after_utc": source.get("refresh_after_utc"),
        "expires_at_utc": source.get("expires_at_utc"),
        "completeness_status": source.get("completeness_status"),
    }


def fetch_awc_product(
    path: str,
    params: dict[str, str],
    *,
    client: httpx.Client | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Fetch one bounded JSON product from the fixed official AWC origin."""
    if path not in {AWC_METAR_PATH, AWC_TAF_PATH}:
        raise ValueError("Unsupported AWC OPMET path")
    retrieved_at = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    request_params = {**params, "format": "json"}
    key = _request_key(path, request_params)
    now_monotonic = time.monotonic()
    cache_seconds = _cache_seconds()
    with _CACHE_LOCK:
        cached = _CACHE.get(key)
        if cached and now_monotonic - cached[0] < cache_seconds:
            return mark_snapshot_reused(cached[1], now=retrieved_at)

    own_client = client is None
    active_client = client or httpx.Client(
        timeout=httpx.Timeout(12.0, connect=5.0),
        follow_redirects=False,
        headers={"User-Agent": _user_agent(), "Accept": "application/json"},
    )
    payload: list[Any] = []
    try:
        response = active_client.get(f"{AWC_API_ORIGIN}{path}", params=request_params)
        if response.status_code == 204:
            payload = []
        else:
            response.raise_for_status()
            raw = response.content
            if len(raw) > _MAX_RESPONSE_BYTES:
                raise ValueError("AWC OPMET response exceeded the safety limit")
            decoded = response.json()
            if not isinstance(decoded, list):
                raise ValueError("AWC OPMET response was not a JSON array")
            payload = decoded
        result = {
            "status": "available",
            "provider": "noaa-awc-data-api",
            "source_url": f"{AWC_API_ORIGIN}{path}",
            "retrieved_at_utc": _iso(retrieved_at),
            "record_count": len(payload),
            "records": payload,
            "error": None,
        }
    except (httpx.HTTPError, ValueError, TypeError) as exc:
        result = {
            "status": "unavailable",
            "provider": "noaa-awc-data-api",
            "source_url": f"{AWC_API_ORIGIN}{path}",
            "retrieved_at_utc": _iso(retrieved_at),
            "record_count": 0,
            "records": [],
            "error": f"{type(exc).__name__}: {str(exc)[:180]}",
        }
    finally:
        if own_client:
            active_client.close()

    effective_start, effective_end = _product_effective_window(path, payload)
    result = govern_snapshot(
        result,
        now=retrieved_at,
        refresh_after_seconds=cache_seconds,
        expires_after_seconds=max(300.0, cache_seconds * 3),
        scope=(
            "requested_noaa_awc_metar_records"
            if path == AWC_METAR_PATH
            else "requested_noaa_awc_taf_records"
        ),
        effective_start_utc=effective_start,
        effective_end_utc=effective_end,
    )
    with _CACHE_LOCK:
        _CACHE[key] = (now_monotonic, result)
    return deepcopy(result)


def _normalize_metar(
    record: dict[str, Any],
    retrieved_at: str | None,
    source_url: str | None,
) -> dict[str, Any] | None:
    station = str(record.get("icaoId") or "").strip().upper()
    raw = " ".join(str(record.get("rawOb") or "").split())
    if not _ICAO.fullmatch(station) or not raw:
        return None
    observed_at = _utc(record.get("reportTime")) or _utc(record.get("obsTime"))
    return {
        "location": station,
        "record_type": "METAR",
        "text": raw,
        "source": "noaa_awc_live",
        "provider": "noaa-awc-data-api",
        "source_url": source_url,
        "observed_at_utc": _iso(observed_at),
        "retrieved_at_utc": retrieved_at,
        "raw_sha256": sha256(raw.encode("utf-8")).hexdigest(),
    }


def _normalize_taf(
    record: dict[str, Any],
    retrieved_at: str | None,
    source_url: str | None,
) -> dict[str, Any] | None:
    station = str(record.get("icaoId") or "").strip().upper()
    raw = " ".join(str(record.get("rawTAF") or "").split())
    if not _ICAO.fullmatch(station) or not raw:
        return None
    return {
        "location": station,
        "record_type": "TAF",
        "text": raw,
        "source": "noaa_awc_live",
        "provider": "noaa-awc-data-api",
        "source_url": source_url,
        "issue_time_utc": _iso(_utc(record.get("issueTime"))),
        "valid_from_utc": _iso(_utc(record.get("validTimeFrom"))),
        "valid_to_utc": _iso(_utc(record.get("validTimeTo"))),
        "retrieved_at_utc": retrieved_at,
        "raw_sha256": sha256(raw.encode("utf-8")).hexdigest(),
    }


def _historical_metar_params(
    stations: list[str],
    departure: datetime | None,
    arrival: datetime | None,
    now: datetime,
) -> dict[str, str]:
    params = {"ids": ",".join(stations)}
    if departure and arrival and arrival <= now + timedelta(hours=1):
        duration_hours = max(0.0, (arrival - departure).total_seconds() / 3600)
        params["hours"] = str(max(6, min(360, int(duration_hours + 5))))
        params["date"] = arrival.strftime("%Y-%m-%dT%H:%M:%SZ")
    else:
        params["hours"] = "6"
    return params


def _taf_dates(
    departure: datetime | None,
    arrival: datetime | None,
    now: datetime,
) -> list[datetime]:
    candidates = [value for value in (departure, arrival) if value]
    if not candidates:
        candidates = [now]
    result: list[datetime] = []
    for value in candidates:
        if not any(abs((value - existing).total_seconds()) < 6 * 3600 for existing in result):
            result.append(value)
    return result[:2]


def enrich_official_opmet(
    flight: dict[str, Any],
    *,
    client: httpx.Client | None = None,
    now: datetime | None = None,
    snapshots: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Append official records and store a fail-closed completeness ledger."""
    configured = os.environ.get("ODSS_OPMET_SOURCE", "awc").strip().lower()
    stations = _station_ids(flight)
    retrieved_at = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    if configured in {"", "disabled", "off", "none"}:
        review = {
            "schema_version": "1.0",
            "status": "not_assessed",
            "provider": None,
            "stations_requested": stations,
            "products": {},
            "missing": [],
            "reason_codes": ["source_disabled"],
        }
        flight["official_weather_review"] = review
        return review
    if configured != "awc":
        review = {
            "schema_version": "1.0",
            "status": "review_required",
            "provider": configured,
            "stations_requested": stations,
            "products": {},
            "missing": [],
            "reason_codes": ["unsupported_source"],
        }
        flight["official_weather_review"] = review
        return review
    if not stations:
        review = {
            "schema_version": "1.0",
            "status": "review_required",
            "provider": "noaa-awc-data-api",
            "stations_requested": [],
            "products": {},
            "missing": [],
            "reason_codes": ["airport_identifiers_unavailable"],
        }
        flight["official_weather_review"] = review
        return review

    departure = _utc(flight.get("scheduled_departure_utc"))
    arrival = _utc(flight.get("scheduled_arrival_utc"))
    supplied = snapshots or {}
    raw_metar_snapshot = supplied.get("metar") or fetch_awc_product(
        AWC_METAR_PATH,
        _historical_metar_params(stations, departure, arrival, retrieved_at),
        client=client,
        now=retrieved_at,
    )
    metar_snapshot = _govern_product_snapshot(
        AWC_METAR_PATH,
        raw_metar_snapshot if isinstance(raw_metar_snapshot, dict) else {},
        now=retrieved_at,
    )
    raw_taf_snapshots = supplied.get("taf")
    if raw_taf_snapshots is None:
        raw_taf_snapshots = [
            fetch_awc_product(
                AWC_TAF_PATH,
                {
                    "ids": ",".join(stations),
                    "time": "valid",
                    "date": target.strftime("%Y-%m-%dT%H:%M:%SZ"),
                },
                client=client,
                now=retrieved_at,
            )
            for target in _taf_dates(departure, arrival, retrieved_at)
        ]
    elif isinstance(raw_taf_snapshots, dict):
        raw_taf_snapshots = [raw_taf_snapshots]
    taf_snapshots = [
        _govern_product_snapshot(
            AWC_TAF_PATH,
            snapshot if isinstance(snapshot, dict) else {},
            now=retrieved_at,
        )
        for snapshot in (raw_taf_snapshots or [])
    ]

    normalized: list[dict[str, Any]] = []
    if _snapshot_is_usable(metar_snapshot, now=retrieved_at):
        for record in metar_snapshot.get("records") or []:
            if not isinstance(record, dict):
                continue
            item = _normalize_metar(
                record,
                metar_snapshot.get("retrieved_at_utc"),
                metar_snapshot.get("source_url"),
            )
            if item:
                normalized.append(item)
    for snapshot in taf_snapshots:
        if not _snapshot_is_usable(snapshot, now=retrieved_at):
            continue
        for record in snapshot.get("records") or []:
            if isinstance(record, dict):
                item = _normalize_taf(
                    record,
                    snapshot.get("retrieved_at_utc"),
                    snapshot.get("source_url"),
                )
                if item:
                    normalized.append(item)

    existing = {
        (
            str(item.get("location") or "").upper(),
            str(item.get("record_type") or "").upper(),
            " ".join(str(item.get("text") or "").split()),
        )
        for item in (flight.get("weather") or [])
    }
    appended: list[dict[str, Any]] = []
    for item in normalized:
        key = (item["location"], item["record_type"], item["text"])
        if key in existing:
            continue
        existing.add(key)
        appended.append(item)
    flight.setdefault("weather", []).extend(appended)

    available_metar = {
        item["location"] for item in normalized if item["record_type"] == "METAR"
    }
    available_taf = {
        item["location"] for item in normalized if item["record_type"] == "TAF"
    }
    essential = [
        station
        for station in (str(flight.get("departure") or ""), str(flight.get("destination") or ""))
        if _ICAO.fullmatch(station)
    ]
    missing = [
        {"station": station, "product": product}
        for station in stations
        for product, available in (("METAR", available_metar), ("TAF", available_taf))
        if station not in available
    ]
    source_stale = any(
        snapshot.get("reuse_reason") == "snapshot_expired"
        for snapshot in [metar_snapshot, *taf_snapshots]
    )
    source_unavailable = any(
        str(snapshot.get("status") or "").lower() != "available"
        or snapshot.get("reuse_reason") not in {None, ""}
        for snapshot in [metar_snapshot, *taf_snapshots]
    )
    essential_missing = any(
        item["station"] in essential and item["product"] == "TAF" for item in missing
    )
    coverage_gaps = _forecast_coverage_gaps(flight, normalized)
    essential_coverage_gap = any(
        item["station"] in essential for item in coverage_gaps
    )
    reason_codes = []
    if source_stale:
        reason_codes.append("source_stale")
    elif source_unavailable:
        reason_codes.append("source_unavailable")
    if essential_missing:
        reason_codes.append("essential_forecast_missing")
    if missing:
        reason_codes.append("station_product_missing")
    if essential_coverage_gap:
        reason_codes.append("essential_forecast_window_not_covered")
    elif coverage_gaps:
        reason_codes.append("forecast_window_not_covered")
    metar_product = _product_review(
        [metar_snapshot],
        normalized,
        record_type="METAR",
        now=retrieved_at,
    )
    taf_product = _product_review(
        taf_snapshots,
        normalized,
        record_type="TAF",
        now=retrieved_at,
    )
    review = {
        "schema_version": "1.0",
        "status": "complete" if not reason_codes else "review_required",
        "provider": "noaa-awc-data-api",
        "retrieved_at_utc": _iso(retrieved_at),
        "stations_requested": stations,
        "records_appended": len(appended),
        "products": {
            "METAR": metar_product,
            "TAF": taf_product,
        },
        "missing": missing,
        "coverage_gaps": coverage_gaps,
        "reason_codes": reason_codes,
        "source_note": (
            "Official NOAA Aviation Weather Center OPMET records. "
            "Pilot-facing wording is produced only after phase and UTC-window evaluation."
        ),
    }
    flight["official_weather_review"] = review
    return review


__all__ = [
    "AWC_API_ORIGIN",
    "AWC_METAR_PATH",
    "AWC_TAF_PATH",
    "enrich_official_opmet",
    "fetch_awc_product",
]

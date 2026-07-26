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
    with _CACHE_LOCK:
        cached = _CACHE.get(key)
        if cached and now_monotonic - cached[0] < _cache_seconds():
            return deepcopy(cached[1])

    own_client = client is None
    active_client = client or httpx.Client(
        timeout=httpx.Timeout(12.0, connect=5.0),
        follow_redirects=False,
        headers={"User-Agent": _user_agent(), "Accept": "application/json"},
    )
    try:
        response = active_client.get(f"{AWC_API_ORIGIN}{path}", params=request_params)
        if response.status_code == 204:
            payload: list[Any] = []
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

    with _CACHE_LOCK:
        _CACHE[key] = (now_monotonic, result)
    return deepcopy(result)


def _normalize_metar(record: dict[str, Any], retrieved_at: str | None) -> dict[str, Any] | None:
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
        "observed_at_utc": _iso(observed_at),
        "retrieved_at_utc": retrieved_at,
        "raw_sha256": sha256(raw.encode("utf-8")).hexdigest(),
    }


def _normalize_taf(record: dict[str, Any], retrieved_at: str | None) -> dict[str, Any] | None:
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
    metar_snapshot = supplied.get("metar") or fetch_awc_product(
        AWC_METAR_PATH,
        _historical_metar_params(stations, departure, arrival, retrieved_at),
        client=client,
        now=retrieved_at,
    )
    taf_snapshots = supplied.get("taf")
    if taf_snapshots is None:
        taf_snapshots = [
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
    elif isinstance(taf_snapshots, dict):
        taf_snapshots = [taf_snapshots]

    normalized: list[dict[str, Any]] = []
    for record in metar_snapshot.get("records") or []:
        if isinstance(record, dict):
            item = _normalize_metar(record, metar_snapshot.get("retrieved_at_utc"))
            if item:
                normalized.append(item)
    for snapshot in taf_snapshots:
        for record in snapshot.get("records") or []:
            if isinstance(record, dict):
                item = _normalize_taf(record, snapshot.get("retrieved_at_utc"))
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
    source_unavailable = (
        metar_snapshot.get("status") != "available"
        or any(snapshot.get("status") != "available" for snapshot in taf_snapshots)
    )
    essential_missing = any(
        item["station"] in essential and item["product"] == "TAF" for item in missing
    )
    reason_codes = []
    if source_unavailable:
        reason_codes.append("source_unavailable")
    if essential_missing:
        reason_codes.append("essential_forecast_missing")
    if missing:
        reason_codes.append("station_product_missing")
    review = {
        "schema_version": "1.0",
        "status": "complete" if not reason_codes else "review_required",
        "provider": "noaa-awc-data-api",
        "retrieved_at_utc": _iso(retrieved_at),
        "stations_requested": stations,
        "records_appended": len(appended),
        "products": {
            "METAR": {
                "status": metar_snapshot.get("status"),
                "record_count": len(available_metar),
                "source_url": metar_snapshot.get("source_url"),
            },
            "TAF": {
                "status": (
                    "available"
                    if taf_snapshots
                    and all(item.get("status") == "available" for item in taf_snapshots)
                    else "unavailable"
                ),
                "record_count": len(available_taf),
                "source_url": (
                    taf_snapshots[0].get("source_url") if taf_snapshots else None
                ),
            },
        },
        "missing": missing,
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

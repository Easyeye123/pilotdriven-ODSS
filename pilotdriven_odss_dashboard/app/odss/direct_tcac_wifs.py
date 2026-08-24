"""Global official tropical-cyclone advisory intake from WIFS.

The authenticated WIFS TAC advisory collection carries TCA messages from the
seven ICAO tropical-cyclone advisory centres. This connector is evidence for
responsible-centre coverage; route impact remains owned by the independently
evaluated official TC SIGMET polygons. Without an approved WIFS key it returns
an explicit unavailable receipt and never substitutes track context for TCA.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
import os
from threading import Lock
import time
from typing import Any

import httpx

from .direct_vaac import (
    advisory_cache_seconds,
    advisory_fields,
    advisory_flight_window,
    advisory_iso,
    advisory_utc,
)
from .direct_vaac_wifs import (
    WIFS_API_ORIGIN,
    bounded_wifs_text,
    wifs_advisory_query_url,
    wifs_tac_records,
)
from .snapshot_governance import govern_snapshot, mark_snapshot_reused


PROVIDER = "noaa-wifs-global-tca"
WIFS_TCAC_CENTRES = (
    "DARWIN",
    "HONOLULU",
    "MIAMI",
    "NADI",
    "NEW DELHI",
    "LA REUNION",
    "TOKYO",
)
_CENTRE_ALIASES = {
    "REUNION": "LA REUNION",
    "LA REUNION": "LA REUNION",
    "LA RÉUNION": "LA REUNION",
}
_CACHE_LOCK = Lock()
_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}


def _centre(value: Any) -> str:
    normalized = " ".join(str(value or "").strip().upper().split())
    return _CENTRE_ALIASES.get(normalized, normalized)


def _issued_at(fields: dict[str, str]) -> datetime | None:
    value = str(fields.get("DTG") or "").strip().upper()
    try:
        return datetime.strptime(value, "%Y%m%d/%H%MZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def parse_wifs_tca_collective(text: str) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    advisories: list[dict[str, Any]] = []
    records, errors = wifs_tac_records(text, "TC ADVISORY")
    for index, record in enumerate(records, start=1):
        fields = advisory_fields(record)
        centre = _centre(fields.get("TCAC"))
        issued = _issued_at(fields)
        if centre not in WIFS_TCAC_CENTRES or issued is None:
            errors.append({
                "record": str(index),
                "error": "TCA centre or DTG could not be verified",
            })
            continue
        forecasts = []
        for hours in (6, 12, 18, 24):
            position = fields.get(f"FCST PSN +{hours} HR")
            maximum_wind = fields.get(f"FCST MAX WIND +{hours} HR")
            if position or maximum_wind:
                forecasts.append({
                    "hours": hours,
                    "position": position,
                    "maximum_wind": maximum_wind,
                })
        advisories.append({
            "provider": PROVIDER,
            "centre": centre,
            "tcac": centre,
            "issued_at_utc": advisory_iso(issued),
            "cyclone": fields.get("TC"),
            "advisory_number": fields.get("ADVISORY NR"),
            "observed_position": fields.get("OBS PSN"),
            "movement": fields.get("MOV"),
            "intensity_change": fields.get("INTST CHANGE"),
            "central_pressure": fields.get("C"),
            "maximum_wind": fields.get("MAX WIND"),
            "forecasts": forecasts,
            "remarks": fields.get("RMK"),
            "next_advisory": fields.get("NXT MSG"),
            "raw_sha256": sha256(record.encode("utf-8")).hexdigest(),
        })
    advisories.sort(key=lambda item: str(item.get("issued_at_utc") or ""), reverse=True)
    return advisories, errors


def _govern(snapshot: dict[str, Any], retrieved_at: datetime) -> dict[str, Any]:
    seconds = advisory_cache_seconds()
    return govern_snapshot(
        snapshot,
        now=retrieved_at,
        refresh_after_seconds=seconds,
        expires_after_seconds=max(1800.0, seconds * 3),
        scope="wifs_global_seven_tcac_tac_advisories",
        completeness_status=snapshot.get("status"),
    )


def fetch_wifs_global_tca_snapshot(
    flight: dict[str, Any],
    *,
    client: httpx.Client | None = None,
    now: datetime | None = None,
    api_key: str | None = None,
) -> dict[str, Any]:
    retrieved_at = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    source_url = wifs_advisory_query_url(retrieved_at, "TCA")
    window = advisory_flight_window(flight)
    key = str(api_key if api_key is not None else os.environ.get("ODSS_WIFS_API_KEY", "")).strip()
    if window is None:
        return _govern({
            "schema_version": "1.0",
            "status": "unavailable",
            "provider": PROVIDER,
            "source_url": source_url,
            "retrieved_at_utc": advisory_iso(retrieved_at),
            "coverage_status": "unavailable",
            "advisories": [],
            "errors": [{"error": "Flight timing is unavailable"}],
        }, retrieved_at)
    if not key:
        return _govern({
            "schema_version": "1.0",
            "status": "unavailable",
            "provider": PROVIDER,
            "source_url": source_url,
            "retrieved_at_utc": advisory_iso(retrieved_at),
            "coverage_status": "not_configured",
            "advisories": [],
            "errors": [{"error": "Approved WIFS API key is not configured"}],
        }, retrieved_at)

    own_client = client is None
    active_client = client or httpx.Client(
        timeout=httpx.Timeout(15.0, connect=5.0),
        follow_redirects=False,
        headers={
            "User-Agent": os.environ.get(
                "ODSS_WEATHER_USER_AGENT",
                "PilotDriven-ODSS/0.6.1 (operational decision-support QA)",
            ),
            "Accept": "text/plain, application/octet-stream",
            "X-API-KEY": key,
        },
    )
    window_start, window_end = window
    try:
        response = active_client.get(source_url, headers={"X-API-KEY": key})
        advisories, errors = parse_wifs_tca_collective(
            bounded_wifs_text(response, "TC ADVISORY"),
        )
        selected = [
            advisory for advisory in advisories
            if (
                (issued := advisory_utc(advisory.get("issued_at_utc"))) is not None
                and window_start <= issued <= window_end
            )
        ]
        status = "available" if not errors else "partial" if advisories else "unavailable"
        return _govern({
            "schema_version": "1.0",
            "status": status,
            "provider": PROVIDER,
            "source_url": source_url,
            "retrieved_at_utc": advisory_iso(retrieved_at),
            "coverage_status": "global_seven_tcac_tac_advisories",
            "requested_issue_window_start_utc": advisory_iso(window_start),
            "requested_issue_window_end_utc": advisory_iso(window_end),
            "centres": list(WIFS_TCAC_CENTRES),
            "centres_received": sorted({str(item["centre"]) for item in advisories}),
            "advisory_count": len(selected),
            "advisories": selected,
            "errors": errors,
            "source_note": (
                "Official global TAC tropical-cyclone advisories distributed "
                "by WIFS. Route impact remains governed by active TC SIGMET "
                "geometry; track context is not substituted for TCA coverage."
            ),
        }, retrieved_at)
    except (httpx.HTTPError, ValueError) as exc:
        return _govern({
            "schema_version": "1.0",
            "status": "unavailable",
            "provider": PROVIDER,
            "source_url": source_url,
            "retrieved_at_utc": advisory_iso(retrieved_at),
            "coverage_status": "unavailable",
            "advisories": [],
            "errors": [{"error": f"{type(exc).__name__}: {str(exc)[:160]}"}],
        }, retrieved_at)
    finally:
        if own_client:
            active_client.close()


def live_wifs_global_tca_snapshot(flight: dict[str, Any]) -> dict[str, Any]:
    window = advisory_flight_window(flight)
    cache_key = "|".join(advisory_iso(value) or "" for value in window) if window else "missing"
    seconds = advisory_cache_seconds()
    now_monotonic = time.monotonic()
    with _CACHE_LOCK:
        cached = _CACHE.get(cache_key)
        if cached and now_monotonic - cached[0] < seconds:
            return mark_snapshot_reused(cached[1])
        snapshot = fetch_wifs_global_tca_snapshot(flight)
        _CACHE[cache_key] = (now_monotonic, snapshot)
        return deepcopy(snapshot)


__all__ = [
    "PROVIDER",
    "WIFS_API_ORIGIN",
    "WIFS_TCAC_CENTRES",
    "fetch_wifs_global_tca_snapshot",
    "live_wifs_global_tca_snapshot",
    "parse_wifs_tca_collective",
]

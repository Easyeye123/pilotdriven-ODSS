"""Governed direct advisory intake from the official Anchorage VAAC.

Anchorage VAAC is operated by the NWS Alaska Aviation Weather Unit and issues
the VA ADVISORY under WMO heading FVAK2x with the office identifier PAWU. The
advisories are retrieved from the National Weather Service public API, which
serves the issued product text as JSON from one fixed HTTPS origin. The centre's
public web pages are not scraped: the hub pages are indexes, and an index is not
evidence.

Like the Tokyo connector this is source evidence separate from the international
SIGMET feed. Only a bounded flight-time window is retrieved, forecast snapshots
are retained as snapshots rather than interpolated into a continuous boundary,
and nothing here is presented as global VAAC coverage. When the advisory cannot
be retrieved or verified, the snapshot says so and the review fails closed; an
absent advisory never becomes "no ash".
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
import json
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
    advisory_phase,
    advisory_utc,
)
from .snapshot_governance import govern_snapshot, mark_snapshot_reused


NWS_API_ORIGIN = "https://api.weather.gov"
NWS_VAA_PRODUCT_PATH = "/products/types/VAA"
# The Alaska Aviation Weather Unit issues as PAWU and signs the advisory
# "VAAC: ANCHORAGE". Both are checked before a record is accepted.
ANCHORAGE_ISSUING_OFFICE = "PAWU"
ANCHORAGE_VAAC_NAME = "ANCHORAGE"
PROVIDER = "nws-anchorage-vaac"

_MAX_JSON_BYTES = 2 * 1024 * 1024
_MAX_ADVISORIES = 32
_CACHE_LOCK = Lock()
_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}


def _bounded_json(response: httpx.Response) -> Any:
    response.raise_for_status()
    raw = response.content
    if len(raw) > _MAX_JSON_BYTES:
        raise ValueError("Anchorage VAAC response exceeded the safety limit")
    try:
        return json.loads(raw.decode("utf-8", errors="replace"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Anchorage VAAC response was not JSON: {exc}") from exc


def _client(client: httpx.Client | None) -> tuple[httpx.Client, bool]:
    if client is not None:
        return client, False
    return httpx.Client(
        timeout=httpx.Timeout(12.0, connect=5.0),
        follow_redirects=False,
        headers={
            "User-Agent": os.environ.get(
                "ODSS_WEATHER_USER_AGENT",
                "PilotDriven-ODSS/0.6.1 (operational decision-support QA)",
            ),
            "Accept": "application/ld+json, application/json",
        },
    ), True


def parse_anchorage_vaac_listing(payload: Any) -> list[dict[str, Any]]:
    """Advisory stubs issued by Anchorage, newest first."""
    graph = (payload or {}).get("@graph") if isinstance(payload, dict) else None
    rows: list[dict[str, Any]] = []
    for item in graph or []:
        if not isinstance(item, dict):
            continue
        office = str(item.get("issuingOffice") or "").strip().upper()
        identifier = str(item.get("id") or "").strip()
        issued_at = advisory_utc(item.get("issuanceTime"))
        if office != ANCHORAGE_ISSUING_OFFICE or not identifier or issued_at is None:
            continue
        rows.append({
            "issued_at_utc": advisory_iso(issued_at),
            "wmo_id": str(item.get("wmoCollectiveId") or "").strip() or None,
            "product_id": identifier,
            "vaa_url": f"{NWS_API_ORIGIN}/products/{identifier}",
        })
    rows.sort(key=lambda row: row["issued_at_utc"], reverse=True)
    return rows


def parse_anchorage_vaac_advisory(
    payload: Any,
    metadata: dict[str, Any],
) -> dict[str, Any]:
    """One Anchorage VA ADVISORY in the shared snapshot shape."""
    text = str((payload or {}).get("productText") or "") if isinstance(payload, dict) else ""
    if not text.strip():
        raise ValueError("Anchorage VAAC advisory carried no product text")
    fields = advisory_fields(text)
    issued_at = advisory_utc(
        metadata.get("issued_at_utc")
        or (payload.get("issuanceTime") if isinstance(payload, dict) else None)
    )
    # Identity is verified from the advisory itself, not from the request that
    # fetched it, so a mislabelled or relayed record cannot enter as Anchorage.
    if issued_at is None or fields.get("VAAC", "").strip().upper() != ANCHORAGE_VAAC_NAME:
        raise ValueError("Anchorage VAAC advisory identity could not be verified")
    phases: list[dict[str, Any]] = []
    observed = fields.get("OBS VA CLD")
    if observed:
        phases.append(advisory_phase(
            "observed",
            f"{fields.get('OBS VA DTG', '')} {observed}".strip(),
            issued_at,
        ))
    for hours in (6, 12, 18):
        value = fields.get(f"FCST VA CLD +{hours} HR")
        if value:
            phases.append(advisory_phase(f"forecast_plus_{hours}_hours", value, issued_at))
    return {
        **metadata,
        "provider": PROVIDER,
        "vaac": fields.get("VAAC"),
        "volcano": fields.get("VOLCANO"),
        "area": fields.get("AREA"),
        "advisory_number": fields.get("ADVISORY NR"),
        "information_source": fields.get("INFO SOURCE"),
        "eruption_details": fields.get("ERUPTION DETAILS"),
        "phases": phases,
        "next_advisory": fields.get("NXT ADVISORY"),
        # Anchorage routinely defers to the neighbouring centre for a volcano
        # inside that centre's area. The remark is retained verbatim so the
        # deferral is visible rather than read as an absence of hazard.
        "remarks": fields.get("RMK"),
        "raw_sha256": sha256(text.encode("utf-8")).hexdigest(),
    }


def _govern(snapshot: dict[str, Any], retrieved_at: datetime) -> dict[str, Any]:
    seconds = advisory_cache_seconds()
    return govern_snapshot(
        snapshot,
        now=retrieved_at,
        refresh_after_seconds=seconds,
        expires_after_seconds=seconds * 4,
        scope="anchorage_vaac_direct_advisory",
        completeness_status=snapshot.get("status"),
    )


def fetch_anchorage_vaac_snapshot(
    flight: dict[str, Any],
    *,
    client: httpx.Client | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    retrieved_at = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    list_url = f"{NWS_API_ORIGIN}{NWS_VAA_PRODUCT_PATH}"
    window = advisory_flight_window(flight)
    if window is None:
        return _govern({
            "schema_version": "1.0",
            "status": "unavailable",
            "provider": PROVIDER,
            "source_url": list_url,
            "retrieved_at_utc": advisory_iso(retrieved_at),
            "advisories": [],
            "error": "Flight timing is unavailable",
        }, retrieved_at)
    window_start, window_end = window
    active_client, own_client = _client(client)
    errors: list[dict[str, str]] = []
    try:
        rows = parse_anchorage_vaac_listing(
            _bounded_json(active_client.get(list_url))
        )
        selected = [
            row
            for row in rows
            if (
                (issued := advisory_utc(row.get("issued_at_utc"))) is not None
                and window_start <= issued <= window_end
            )
        ][:_MAX_ADVISORIES]
        advisories: list[dict[str, Any]] = []
        for row in selected:
            try:
                advisories.append(parse_anchorage_vaac_advisory(
                    _bounded_json(active_client.get(row["vaa_url"])),
                    row,
                ))
            except (httpx.HTTPError, ValueError) as exc:
                errors.append({
                    "source_url": row["vaa_url"],
                    "error": f"{type(exc).__name__}: {str(exc)[:160]}",
                })
        return _govern({
            "schema_version": "1.0",
            "status": "available" if not errors else "partial",
            "provider": PROVIDER,
            "source_url": list_url,
            "retrieved_at_utc": advisory_iso(retrieved_at),
            "coverage_status": "anchorage_vaac_area_direct_advisories",
            "requested_issue_window_start_utc": advisory_iso(window_start),
            "requested_issue_window_end_utc": advisory_iso(window_end),
            "listing_earliest_utc": rows[-1]["issued_at_utc"] if rows else None,
            "listing_latest_utc": rows[0]["issued_at_utc"] if rows else None,
            "advisory_count": len(advisories),
            "advisories": advisories,
            "errors": errors,
            "source_note": (
                "Official Anchorage VAAC VA ADVISORY evidence for its area only, "
                "retrieved as issued product text from the National Weather "
                "Service API. Forecast polygons remain official snapshots and "
                "are not interpolated into a continuous hazard boundary."
            ),
        }, retrieved_at)
    except (httpx.HTTPError, ValueError) as exc:
        return _govern({
            "schema_version": "1.0",
            "status": "unavailable",
            "provider": PROVIDER,
            "source_url": list_url,
            "retrieved_at_utc": advisory_iso(retrieved_at),
            "coverage_status": "unavailable",
            "advisories": [],
            "errors": [{"error": f"{type(exc).__name__}: {str(exc)[:160]}"}],
        }, retrieved_at)
    finally:
        if own_client:
            active_client.close()


def live_anchorage_vaac_snapshot(flight: dict[str, Any]) -> dict[str, Any]:
    window = advisory_flight_window(flight)
    cache_key = "|".join(advisory_iso(value) or "" for value in window) if window else "missing"
    seconds = advisory_cache_seconds()
    now_monotonic = time.monotonic()
    with _CACHE_LOCK:
        cached = _CACHE.get(cache_key)
        if cached and now_monotonic - cached[0] < seconds:
            return mark_snapshot_reused(cached[1])
        snapshot = fetch_anchorage_vaac_snapshot(flight)
        _CACHE[cache_key] = (now_monotonic, snapshot)
        return deepcopy(snapshot)


__all__ = [
    "ANCHORAGE_ISSUING_OFFICE",
    "ANCHORAGE_VAAC_NAME",
    "NWS_API_ORIGIN",
    "NWS_VAA_PRODUCT_PATH",
    "PROVIDER",
    "fetch_anchorage_vaac_snapshot",
    "live_anchorage_vaac_snapshot",
    "parse_anchorage_vaac_advisory",
    "parse_anchorage_vaac_listing",
]

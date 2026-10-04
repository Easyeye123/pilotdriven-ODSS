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
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
import os
import re
from threading import Lock
import time
from typing import Any

import httpx

from .direct_vaac import (
    advisory_cache_seconds,
    advisory_aviation_colour_code,
    advisory_fields,
    advisory_flight_window,
    advisory_iso,
    advisory_is_exercise,
    advisory_next_receipt,
    advisory_phase,
    advisory_utc,
    advisory_volcano_position,
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
_WMO_HEADER = re.compile(
    r"(?m)^\s*(?P<wmo>FVAK\d{2})\s+(?P<office>[A-Z]{4})\s+"
    r"(?P<day>\d{2})(?P<hour>\d{2})(?P<minute>\d{2})\s*$"
)
_BODY_DTG = re.compile(
    r"^(?P<date>\d{6}|\d{8})/"
    r"(?P<hour>\d{2})(?P<minute>\d{2})Z$"
)


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
    if not isinstance(payload, dict) or any(
        not str(metadata.get(key) or "").strip()
        for key in ("issued_at_utc", "product_id", "wmo_id")
    ):
        raise ValueError("Anchorage VAAC listing identity was incomplete")
    if any(
        not str(payload.get(key) or "").strip()
        for key in ("id", "issuingOffice", "issuanceTime", "wmoCollectiveId")
    ):
        raise ValueError("Anchorage VAAC detail identity was incomplete")
    fields = advisory_fields(text)
    if advisory_is_exercise(text, fields):
        raise ValueError("Anchorage VAAC exercise advisory is not operational evidence")
    issued_at = advisory_utc(
        metadata.get("issued_at_utc")
        or (payload.get("issuanceTime") if isinstance(payload, dict) else None)
    )
    # Identity is verified from the advisory itself, not from the request that
    # fetched it, so a mislabelled or relayed record cannot enter as Anchorage.
    if issued_at is None or fields.get("VAAC", "").strip().upper() != ANCHORAGE_VAAC_NAME:
        raise ValueError("Anchorage VAAC advisory identity could not be verified")
    listed_product = str(metadata.get("product_id") or "").strip()
    detail_product = str(payload.get("id") or "").strip()
    if detail_product != listed_product:
        raise ValueError("Anchorage VAAC detail product did not match its listing")
    detail_office = str(payload.get("issuingOffice") or "").strip().upper()
    if detail_office != ANCHORAGE_ISSUING_OFFICE:
        raise ValueError("Anchorage VAAC detail office did not match PAWU")
    detail_issued = advisory_utc(payload.get("issuanceTime"))
    if detail_issued is None or detail_issued != issued_at:
        raise ValueError("Anchorage VAAC detail issuance did not match its listing")
    listed_wmo = str(metadata.get("wmo_id") or "").strip().upper()
    detail_wmo = str(payload.get("wmoCollectiveId") or "").strip().upper()
    if detail_wmo != listed_wmo:
        raise ValueError("Anchorage VAAC detail WMO id did not match its listing")

    header = _WMO_HEADER.search(text)
    if header is None:
        raise ValueError("Anchorage VAAC WMO header was not found")
    if header.group("office") != ANCHORAGE_ISSUING_OFFICE:
        raise ValueError("Anchorage VAAC WMO header office was not PAWU")
    if listed_wmo and header.group("wmo") != listed_wmo:
        raise ValueError("Anchorage VAAC WMO header did not match its listing")
    if header.group("wmo") != "FVAK22" and not header.group("wmo").startswith("FVAK2"):
        raise ValueError("Anchorage VAAC WMO header was outside the VAA series")
    if header.group("day") + header.group("hour") + header.group("minute") != issued_at.strftime("%d%H%M"):
        raise ValueError("Anchorage VAAC WMO issue time did not match its listing")

    body_match = _BODY_DTG.fullmatch(str(fields.get("DTG") or "").strip().upper())
    if body_match is None:
        raise ValueError("Anchorage VAAC advisory DTG could not be verified")
    date_digits = body_match.group("date")
    if len(date_digits) == 6:
        if int(date_digits[:2]) != issued_at.year % 100:
            raise ValueError("Anchorage VAAC advisory DTG year did not match its listing")
        year = issued_at.year
        month = int(date_digits[2:4])
        day = int(date_digits[4:6])
    else:
        year = int(date_digits[:4])
        month = int(date_digits[4:6])
        day = int(date_digits[6:8])
    try:
        body_issue = datetime(
            year,
            month,
            day,
            int(body_match.group("hour")),
            int(body_match.group("minute")),
            tzinfo=timezone.utc,
        )
    except ValueError as exc:
        raise ValueError("Anchorage VAAC advisory DTG could not be verified") from exc
    issue_lag = issued_at - body_issue
    if issue_lag < timedelta(0) or issue_lag > timedelta(hours=6):
        raise ValueError("Anchorage VAAC advisory DTG was outside its issuance vicinity")
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
        "centre": fields.get("VAAC"),
        "volcano": fields.get("VOLCANO"),
        "volcano_position": advisory_volcano_position(fields.get("PSN")),
        "aviation_colour_code": advisory_aviation_colour_code(fields),
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
        next_advisory_due, next_advisory_notes = advisory_next_receipt(advisories)
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
            "next_advisory_due": next_advisory_due,
            "next_advisory_notes": next_advisory_notes,
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

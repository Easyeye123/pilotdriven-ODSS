"""Governed direct VAA/VAG intake from the official Toulouse VAAC site.

Meteo-France publishes its latest operational advisories on a public HTTPS
listing. Only links on that fixed origin and under the bounded advisory path
are accepted. The official text and graphic URLs remain source evidence; the
forecast snapshots are never interpolated into a continuous ash boundary.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
import os
import re
from threading import Lock
import time
from typing import Any
from urllib.parse import urlsplit

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


TOULOUSE_VAAC_ORIGIN = "https://vaac.meteo.fr"
TOULOUSE_VAAC_LIST_PATH = "/docs/"
PROVIDER = "meteo-france-toulouse-vaac"
_MAX_RESPONSE_BYTES = 2 * 1024 * 1024
_MAX_ADVISORIES = 32
_CACHE_LOCK = Lock()
_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
_ADVISORY_LINK = re.compile(
    r"href=[\"'](?:https://vaac\.meteo\.fr)?(?P<path>/advisory/(?P<year>\d{4})/"
    r"(?P<slug>[A-Za-z0-9_-]{12,80})/(?P=slug)/?)[\"']",
    re.IGNORECASE,
)
_SLUG_TIME = re.compile(r"_(\d{14})$")


def _bounded_content(response: httpx.Response) -> bytes:
    response.raise_for_status()
    raw = response.content
    if len(raw) > _MAX_RESPONSE_BYTES:
        raise ValueError("Toulouse VAAC response exceeded the safety limit")
    if not raw.strip():
        raise ValueError("Toulouse VAAC response was empty")
    return raw


def _safe_advisory_url(path: str) -> str | None:
    candidate = f"{TOULOUSE_VAAC_ORIGIN}{path}"
    parsed = urlsplit(candidate)
    if parsed.scheme != "https" or parsed.hostname != "vaac.meteo.fr":
        return None
    if parsed.query or parsed.fragment or not parsed.path.startswith("/advisory/"):
        return None
    return candidate


def parse_toulouse_vaac_listing(raw: bytes) -> list[dict[str, Any]]:
    if len(raw) > _MAX_RESPONSE_BYTES:
        raise ValueError("Toulouse VAAC listing exceeded the safety limit")
    html = raw.decode("utf-8", errors="replace")
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for match in _ADVISORY_LINK.finditer(html):
        slug = match.group("slug")
        if slug in seen:
            continue
        time_match = _SLUG_TIME.search(slug)
        if not time_match:
            continue
        try:
            issued = datetime.strptime(time_match.group(1), "%Y%m%d%H%M%S").replace(
                tzinfo=timezone.utc,
            )
        except ValueError:
            continue
        if str(issued.year) != match.group("year"):
            continue
        page_url = _safe_advisory_url(match.group("path"))
        vaa_url = _safe_advisory_url(
            f"/advisory/{match.group('year')}/{slug}/{slug}_vaa.txt",
        )
        vag_url = _safe_advisory_url(
            f"/advisory/{match.group('year')}/{slug}/{slug}_vag.png",
        )
        if not page_url or not vaa_url or not vag_url:
            continue
        seen.add(slug)
        rows.append({
            "issued_at_utc": advisory_iso(issued),
            "page_url": page_url,
            "vaa_url": vaa_url,
            "vag_url": vag_url,
        })
    rows.sort(key=lambda item: str(item["issued_at_utc"]), reverse=True)
    return rows[:_MAX_ADVISORIES]


def _issued_at(fields: dict[str, str]) -> datetime | None:
    value = str(fields.get("DTG") or "").strip().upper()
    try:
        return datetime.strptime(value, "%Y%m%d/%H%MZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def parse_toulouse_vaac_advisory(
    raw: bytes,
    metadata: dict[str, Any],
) -> dict[str, Any]:
    if len(raw) > _MAX_RESPONSE_BYTES:
        raise ValueError("Toulouse VAAC advisory exceeded the safety limit")
    text = raw.decode("utf-8", errors="replace").strip()
    if "VA ADVISORY" not in text.upper():
        raise ValueError("Toulouse VAAC advisory body was not found")
    fields = advisory_fields(text)
    issued = _issued_at(fields)
    listed = advisory_utc(metadata.get("issued_at_utc"))
    if (
        issued is None
        or listed is None
        or fields.get("VAAC", "").strip().upper() != "TOULOUSE"
        or abs((issued - listed).total_seconds()) > 2 * 3600
    ):
        raise ValueError("Toulouse VAAC advisory identity could not be verified")
    phases: list[dict[str, Any]] = []
    observed = fields.get("OBS VA CLD")
    if observed:
        phases.append(advisory_phase(
            "observed",
            f"{fields.get('OBS VA DTG', '')} {observed}".strip(),
            issued,
        ))
    for hours in (6, 12, 18):
        value = fields.get(f"FCST VA CLD +{hours} HR")
        if value:
            phases.append(advisory_phase(
                f"forecast_plus_{hours}_hours",
                value,
                issued,
            ))
    return {
        **metadata,
        "provider": PROVIDER,
        "centre": "TOULOUSE",
        "vaac": "TOULOUSE",
        "issued_at_utc": advisory_iso(issued),
        "volcano": fields.get("VOLCANO"),
        "area": fields.get("AREA"),
        "advisory_number": fields.get("ADVISORY NR"),
        "information_source": fields.get("INFO SOURCE"),
        "eruption_details": fields.get("ERUPTION DETAILS"),
        "phases": phases,
        "next_advisory": fields.get("NXT ADVISORY"),
        "remarks": fields.get("RMK"),
        "raw_sha256": sha256(text.encode("utf-8")).hexdigest(),
    }


def _govern(snapshot: dict[str, Any], retrieved_at: datetime) -> dict[str, Any]:
    seconds = advisory_cache_seconds()
    return govern_snapshot(
        snapshot,
        now=retrieved_at,
        refresh_after_seconds=seconds,
        expires_after_seconds=max(1800.0, seconds * 3),
        scope="meteo_france_toulouse_vaac_latest_operational_advisories",
        effective_start_utc=snapshot.get("requested_issue_window_start_utc"),
        effective_end_utc=snapshot.get("requested_issue_window_end_utc"),
    )


def fetch_toulouse_vaac_snapshot(
    flight: dict[str, Any],
    *,
    client: httpx.Client | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    retrieved_at = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    window = advisory_flight_window(flight)
    list_url = f"{TOULOUSE_VAAC_ORIGIN}{TOULOUSE_VAAC_LIST_PATH}"
    if window is None:
        return _govern({
            "schema_version": "1.0",
            "status": "unavailable",
            "provider": PROVIDER,
            "source_url": list_url,
            "retrieved_at_utc": advisory_iso(retrieved_at),
            "coverage_status": "unavailable",
            "advisories": [],
            "errors": [{"error": "Flight timing is unavailable"}],
        }, retrieved_at)
    window_start, window_end = window
    own_client = client is None
    active_client = client or httpx.Client(
        timeout=httpx.Timeout(12.0, connect=5.0),
        follow_redirects=False,
        headers={
            "User-Agent": os.environ.get(
                "ODSS_WEATHER_USER_AGENT",
                "PilotDriven-ODSS/0.6.1 (operational decision-support QA)",
            ),
            "Accept": "text/html,text/plain,image/png",
        },
    )
    errors: list[dict[str, str]] = []
    try:
        rows = parse_toulouse_vaac_listing(_bounded_content(active_client.get(list_url)))
        selected = [
            row for row in rows
            if (
                (issued := advisory_utc(row.get("issued_at_utc"))) is not None
                and window_start <= issued <= window_end
            )
        ]
        advisories: list[dict[str, Any]] = []
        for row in selected:
            try:
                advisories.append(parse_toulouse_vaac_advisory(
                    _bounded_content(active_client.get(str(row["vaa_url"]))),
                    row,
                ))
            except (httpx.HTTPError, ValueError) as exc:
                errors.append({
                    "source_url": str(row["vaa_url"]),
                    "error": f"{type(exc).__name__}: {str(exc)[:160]}",
                })
        return _govern({
            "schema_version": "1.0",
            "status": "available" if not errors else "partial",
            "provider": PROVIDER,
            "centre": "TOULOUSE",
            "source_url": list_url,
            "retrieved_at_utc": advisory_iso(retrieved_at),
            "coverage_status": "toulouse_vaac_latest_operational_advisories",
            "requested_issue_window_start_utc": advisory_iso(window_start),
            "requested_issue_window_end_utc": advisory_iso(window_end),
            "listing_earliest_utc": rows[-1]["issued_at_utc"] if rows else None,
            "listing_latest_utc": rows[0]["issued_at_utc"] if rows else None,
            "advisory_count": len(advisories),
            "advisories": advisories,
            "errors": errors,
            "source_note": (
                "Official Toulouse VAAC VAA text and VAG source links for its "
                "area only. Forecast snapshots are not interpolated into a "
                "continuous hazard boundary."
            ),
        }, retrieved_at)
    except (httpx.HTTPError, ValueError) as exc:
        return _govern({
            "schema_version": "1.0",
            "status": "unavailable",
            "provider": PROVIDER,
            "centre": "TOULOUSE",
            "source_url": list_url,
            "retrieved_at_utc": advisory_iso(retrieved_at),
            "coverage_status": "unavailable",
            "advisories": [],
            "errors": [{"error": f"{type(exc).__name__}: {str(exc)[:160]}"}],
        }, retrieved_at)
    finally:
        if own_client:
            active_client.close()


def live_toulouse_vaac_snapshot(flight: dict[str, Any]) -> dict[str, Any]:
    window = advisory_flight_window(flight)
    cache_key = "|".join(advisory_iso(value) or "" for value in window) if window else "missing"
    seconds = advisory_cache_seconds()
    now_monotonic = time.monotonic()
    with _CACHE_LOCK:
        cached = _CACHE.get(cache_key)
        if cached and now_monotonic - cached[0] < seconds:
            return mark_snapshot_reused(cached[1])
        snapshot = fetch_toulouse_vaac_snapshot(flight)
        _CACHE[cache_key] = (now_monotonic, snapshot)
        return deepcopy(snapshot)


__all__ = [
    "PROVIDER",
    "TOULOUSE_VAAC_LIST_PATH",
    "TOULOUSE_VAAC_ORIGIN",
    "fetch_toulouse_vaac_snapshot",
    "live_toulouse_vaac_snapshot",
    "parse_toulouse_vaac_advisory",
    "parse_toulouse_vaac_listing",
]

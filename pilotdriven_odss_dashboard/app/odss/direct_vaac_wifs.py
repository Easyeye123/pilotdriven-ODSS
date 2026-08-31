"""Global official VAA intake from the authenticated WIFS TAC collection.

WIFS is the ICAO-authorised global distribution service operated by NOAA/NWS
and FAA. Its ``tac_advisory_reports`` collection carries VAA messages from all
nine VAACs. Access requires an approved WIFS API key; without that secret this
connector returns an unavailable snapshot and never substitutes a web scrape.

One bounded global request is cached for at least five minutes. The API key is
sent only in the X-API-KEY header and is never copied into a URL, snapshot,
error, or loggable object.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import gzip
from hashlib import sha256
import os
import re
from threading import Lock
import time
from typing import Any
from urllib.parse import urlencode

import httpx

from .direct_vaac import (
    advisory_cache_seconds,
    advisory_fields,
    advisory_flight_window,
    advisory_iso,
    advisory_is_exercise,
    advisory_phase,
    advisory_utc,
)
from .snapshot_governance import govern_snapshot, mark_snapshot_reused


WIFS_API_ORIGIN = "https://aviationweather.gov"
WIFS_TAC_ADVISORY_PATH = "/wifs/api/collections/tac_advisory_reports/locations/GLOBAL"
PROVIDER = "noaa-wifs-global-vaa"
WIFS_VAAC_CENTRES = (
    "ANCHORAGE",
    "BUENOS AIRES",
    "DARWIN",
    "LONDON",
    "MONTREAL",
    "TOKYO",
    "TOULOUSE",
    "WASHINGTON",
    "WELLINGTON",
)

_MAX_RESPONSE_BYTES = 8 * 1024 * 1024
_MAX_ADVISORIES = 128
_CACHE_LOCK = Lock()
_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
_DTG = re.compile(r"^(\d{8})/(\d{4})Z$")


def _rounded_five_minutes(value: datetime) -> datetime:
    utc = value.astimezone(timezone.utc)
    return utc.replace(minute=utc.minute - utc.minute % 5, second=0, microsecond=0)


def wifs_advisory_query_url(now: datetime, parameter_name: str = "VAA") -> str:
    parameter = str(parameter_name).strip().upper()
    if parameter not in {"VAA", "TCA"}:
        raise ValueError("Unsupported WIFS advisory parameter")
    rounded = _rounded_five_minutes(now)
    query = urlencode({
        "datetime": f"{rounded.strftime('%Y-%m-%dT%H:%M:%SZ')}/PT36H",
        "parameter-name": parameter,
    })
    return f"{WIFS_API_ORIGIN}{WIFS_TAC_ADVISORY_PATH}?{query}"


def bounded_wifs_text(response: httpx.Response, advisory_marker: str = "VA ADVISORY") -> str:
    response.raise_for_status()
    raw = response.content
    if len(raw) > _MAX_RESPONSE_BYTES:
        raise ValueError("WIFS VAA response exceeded the safety limit")
    if raw.startswith(b"\x1f\x8b"):
        try:
            raw = gzip.decompress(raw)
        except (OSError, EOFError) as exc:
            raise ValueError("WIFS VAA response carried invalid gzip data") from exc
        if len(raw) > _MAX_RESPONSE_BYTES:
            raise ValueError("WIFS VAA expanded response exceeded the safety limit")
    text = raw.decode("utf-8", errors="replace")
    if not text.strip():
        raise ValueError("WIFS VAA response was empty")
    marker = str(advisory_marker).strip().upper()
    if marker not in text.upper():
        raise ValueError(f"WIFS response carried no {marker} TAC records")
    return text


def _issued_at(fields: dict[str, str]) -> datetime | None:
    match = _DTG.match(str(fields.get("DTG") or "").strip().upper())
    if not match:
        return None
    try:
        return datetime.strptime(
            f"{match.group(1)}{match.group(2)}",
            "%Y%m%d%H%M",
        ).replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def wifs_tac_records(
    text: str,
    advisory_marker: str = "VA ADVISORY",
) -> tuple[list[str], list[dict[str, str]]]:
    # WMO TAC collectives delimit messages with '='. Some test/relay exports
    # omit it; in that case retain one complete advisory rather than guessing
    # boundaries between field continuations.
    normalized = text.replace("\r\n", "\n")
    marker = str(advisory_marker).strip().upper()
    product = "VAA" if marker == "VA ADVISORY" else "TCA" if marker == "TC ADVISORY" else "advisory"
    advisory_markers = normalized.upper().count(marker)
    has_verified_delimiters = bool(re.search(r"(?m)^\s*=\s*$", normalized))
    if advisory_markers > 1 and not has_verified_delimiters:
        return [], [{
            "record": "collective",
            "error": f"Multiple {product} record boundaries could not be verified",
        }]
    chunks = re.split(r"(?m)^\s*=\s*$", normalized)
    records = [chunk.strip("\x01\x03\n ") for chunk in chunks if marker in chunk.upper()]
    errors: list[dict[str, str]] = []
    if len(records) > _MAX_ADVISORIES:
        errors.append({
            "record": "collective",
            "error": f"WIFS {product} collective exceeded the {_MAX_ADVISORIES}-record safety limit",
        })
    return records[:_MAX_ADVISORIES], errors


def parse_wifs_vaa_collective(text: str) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    advisories: list[dict[str, Any]] = []
    records, errors = wifs_tac_records(text)
    for index, record in enumerate(records, start=1):
        fields = advisory_fields(record)
        if advisory_is_exercise(record, fields):
            errors.append({
                "record": str(index),
                "error": "Exercise VAA is not operational evidence",
            })
            continue
        centre = str(fields.get("VAAC") or "").strip().upper()
        issued_at = _issued_at(fields)
        if centre not in WIFS_VAAC_CENTRES or issued_at is None:
            errors.append({
                "record": str(index),
                "error": "VAA centre or DTG could not be verified",
            })
            continue
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
                phases.append(advisory_phase(
                    f"forecast_plus_{hours}_hours",
                    value,
                    issued_at,
                ))
        advisories.append({
            "provider": PROVIDER,
            "centre": centre,
            "vaac": centre,
            "issued_at_utc": advisory_iso(issued_at),
            "volcano": fields.get("VOLCANO"),
            "area": fields.get("AREA"),
            "advisory_number": fields.get("ADVISORY NR"),
            "information_source": fields.get("INFO SOURCE"),
            "eruption_details": fields.get("ERUPTION DETAILS"),
            "phases": phases,
            "next_advisory": fields.get("NXT ADVISORY"),
            "remarks": fields.get("RMK"),
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
        scope="wifs_global_nine_vaac_tac_advisories",
        completeness_status=snapshot.get("status"),
    )


def fetch_wifs_global_vaac_snapshot(
    flight: dict[str, Any],
    *,
    client: httpx.Client | None = None,
    now: datetime | None = None,
    api_key: str | None = None,
) -> dict[str, Any]:
    retrieved_at = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    source_url = wifs_advisory_query_url(retrieved_at)
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
        advisories, errors = parse_wifs_vaa_collective(bounded_wifs_text(response))
        selected = [
            advisory for advisory in advisories
            if (
                (issued := advisory_utc(advisory.get("issued_at_utc"))) is not None
                and window_start <= issued <= window_end
            )
        ]
        status = (
            "available"
            if not errors
            else "partial"
            if advisories
            else "unavailable"
        )
        return _govern({
            "schema_version": "1.0",
            "status": status,
            "provider": PROVIDER,
            "source_url": source_url,
            "retrieved_at_utc": advisory_iso(retrieved_at),
            "coverage_status": "global_nine_vaac_tac_advisories",
            "requested_issue_window_start_utc": advisory_iso(window_start),
            "requested_issue_window_end_utc": advisory_iso(window_end),
            "centres": list(WIFS_VAAC_CENTRES),
            "centres_received": sorted({str(item["centre"]) for item in advisories}),
            "advisory_count": len(selected),
            "advisories": selected,
            "errors": errors,
            "source_note": (
                "Official global TAC volcanic-ash advisories distributed by WIFS. "
                "This source carries VAA text; graphical VAG coverage remains a "
                "separate review item."
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


def wifs_centre_snapshot(snapshot: dict[str, Any], centre: str) -> dict[str, Any]:
    centre_name = str(centre).strip().upper()
    advisories = [
        item for item in (snapshot.get("advisories") or [])
        if str(item.get("centre") or item.get("vaac") or "").strip().upper() == centre_name
    ]
    return {
        **snapshot,
        "centre": centre_name,
        "advisory_count": len(advisories),
        "advisories": advisories,
    }


def live_wifs_global_vaac_snapshot(flight: dict[str, Any]) -> dict[str, Any]:
    window = advisory_flight_window(flight)
    cache_key = "|".join(advisory_iso(value) or "" for value in window) if window else "missing"
    seconds = advisory_cache_seconds()
    now_monotonic = time.monotonic()
    with _CACHE_LOCK:
        cached = _CACHE.get(cache_key)
        if cached and now_monotonic - cached[0] < seconds:
            return mark_snapshot_reused(cached[1])
        snapshot = fetch_wifs_global_vaac_snapshot(flight)
        _CACHE[cache_key] = (now_monotonic, snapshot)
        return deepcopy(snapshot)


__all__ = [
    "PROVIDER",
    "WIFS_API_ORIGIN",
    "WIFS_TAC_ADVISORY_PATH",
    "WIFS_VAAC_CENTRES",
    "bounded_wifs_text",
    "fetch_wifs_global_vaac_snapshot",
    "live_wifs_global_vaac_snapshot",
    "parse_wifs_vaa_collective",
    "wifs_advisory_query_url",
    "wifs_centre_snapshot",
    "wifs_tac_records",
]

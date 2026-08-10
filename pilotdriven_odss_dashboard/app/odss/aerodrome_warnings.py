"""Local met-authority aerodrome warnings for the flight's own airports.

Boss instruction, 10.08.26: "for pd .. Flight Brief, can you get the AI to
scrap the website for the departure airport and destination airport's
meteorological website?" — his examples: Singapore localised thunderstorms /
Sumatran squall line, Hong Kong typhoon.

Design follows ``direct_sigmet.py``'s governed-authority pattern, made
dynamic instead of per-country:

* **GTS floor (every country, no per-country code):** national met services
  publish their issued warning bulletins on the WMO GTS, mirrored publicly by
  NOAA (tgftp.nws.noaa.gov). The engine reads the mirror's warning-family
  indexes once per cache window, keeps the files whose issuing centre matches
  the airport's ICAO country prefix, and serves the authority's own bulletin
  text with NOAA named as the host. A country that publishes nothing there is
  reported as exactly that — never guessed.
* **Official authority APIs (config rows, richer where they exist):** some
  authorities publish structured warnings on their own official endpoints.
  Singapore's MSS heavy-rain / localised-thunderstorm warnings are served via
  the government data API (api-open.data.gov.sg). One mapping row per
  authority; adding a country is data, not code.

Absence never degrades the briefing: no active warning is a normal, honest
state, and an unreachable source is reported per airport without turning the
overall weather review amber (the aggregate SIGMET/METAR/TAF layers remain
the baseline coverage authorities).
"""

from __future__ import annotations

from datetime import datetime, timezone
import os
import re
from threading import Lock
import time
from typing import Any

import httpx

GTS_MIRROR_ORIGIN = "https://tgftp.nws.noaa.gov"
GTS_ALLOWED_HOSTS = frozenset({"tgftp.nws.noaa.gov"})
# Warning-family directories on the mirror. WW carries the general warning
# bulletins (aerodrome warnings included where a centre issues them); WO
# carries "other" warnings some centres use for the same products.
GTS_WARNING_FAMILIES = ("ww", "wo")
_GTS_INDEX_FILE = re.compile(r'href="((w[a-z])([a-z]{2}\d{2})\.([a-z0-9]{4})\.\.txt)"')

# Official structured-warning endpoints, keyed by the ICAO country prefix the
# row serves. The label and URL are the authority's own; adding an authority
# is one row here, never new engine code.
AUTHORITY_API_ROWS: dict[str, dict[str, Any]] = {
    "WS": {
        "provider": "mss-singapore-via-data-gov-sg",
        "authority": "Meteorological Service Singapore",
        "url": "https://api-open.data.gov.sg/v2/real-time/api/weather?api=heavy-rain-warning",
        "env_url": "ODSS_ADWX_SG_URL",
        "allowed_hosts": frozenset({"api-open.data.gov.sg"}),
        "kind": "data_gov_sg_v2",
    },
    "VH": {
        "provider": "hko-via-official-open-data",
        "authority": "Hong Kong Observatory",
        "url": "https://data.weather.gov.hk/weatherAPI/opendata/weather.php?dataType=warnsum&lang=en",
        "env_url": "ODSS_ADWX_HK_URL",
        "allowed_hosts": frozenset({"data.weather.gov.hk"}),
        "kind": "hko_warnsum",
    },
}

# Countries whose ICAO prefix is a single letter; everywhere else two letters
# identify the state of the aerodrome. Deterministic, from the ICAO location
# indicator scheme itself.
_SINGLE_LETTER_PREFIXES = frozenset({"C", "K", "U", "Y"})

_MAX_INDEX_BYTES = 2 * 1024 * 1024
_MAX_BULLETIN_BYTES = 256 * 1024
_MAX_BULLETINS_PER_AIRPORT = 6
_TIMEOUT_SECONDS = 12.0
_ICAO = re.compile(r"^[A-Z]{4}$")
# WMO abbreviated heading line inside a bulletin: TTAAII CCCC DDHHMM
_WMO_HEADING = re.compile(r"\b([A-Z]{4}\d{2})\s+([A-Z]{4})\s+(\d{6})\b")

_CACHE: dict[str, tuple[float, Any]] = {}
_CACHE_LOCK = Lock()


def _cache_seconds() -> float:
    raw = os.environ.get("ODSS_ADWX_CACHE_SECONDS", "600").strip()
    try:
        value = float(raw)
    except ValueError:
        return 600.0
    return min(max(value, 60.0), 3600.0)


def _cached(key: str) -> Any | None:
    with _CACHE_LOCK:
        entry = _CACHE.get(key)
    if not entry:
        return None
    stored_at, value = entry
    if time.monotonic() - stored_at > _cache_seconds():
        return None
    return value


def _store(key: str, value: Any) -> None:
    with _CACHE_LOCK:
        _CACHE[key] = (time.monotonic(), value)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _station_prefixes(icao: str) -> tuple[str, ...]:
    """Country prefixes a bulletin's issuing centre may carry for this airport."""
    if icao[0] in _SINGLE_LETTER_PREFIXES:
        return (icao[0],)
    return (icao[:2],)


def _flight_stations(flight: dict[str, Any]) -> list[str]:
    candidates: list[Any] = [flight.get("departure_icao"), flight.get("destination_icao")]
    for alternate in flight.get("alternates") or []:
        if isinstance(alternate, dict):
            candidates.append(alternate.get("icao"))
        else:
            candidates.append(alternate)
    stations: list[str] = []
    for candidate in candidates:
        code = str(candidate or "").strip().upper()
        if _ICAO.match(code) and code not in stations:
            stations.append(code)
    return stations


def _get(client: httpx.Client, url: str, *, max_bytes: int) -> str | None:
    response = client.get(url, timeout=_TIMEOUT_SECONDS, follow_redirects=False)
    if response.status_code != 200:
        return None
    body = response.text
    if body is None or len(body.encode("utf-8", "ignore")) > max_bytes:
        return None
    return body


def _warning_index(client: httpx.Client) -> dict[str, list[tuple[str, str]]] | None:
    """family -> list of (filename, issuing centre) from the mirror indexes."""
    cached = _cached("gts-index")
    if cached is not None:
        return cached
    index: dict[str, list[tuple[str, str]]] = {}
    any_family = False
    for family in GTS_WARNING_FAMILIES:
        url = f"{GTS_MIRROR_ORIGIN}/data/raw/{family}/"
        try:
            body = _get(client, url, max_bytes=_MAX_INDEX_BYTES)
        except httpx.HTTPError:
            body = None
        if body is None:
            continue
        any_family = True
        rows: list[tuple[str, str]] = []
        for match in _GTS_INDEX_FILE.finditer(body):
            filename, _family_tt, _aaii, centre = match.groups()
            rows.append((filename, centre.upper()))
        index[family] = rows
    if not any_family:
        return None
    _store("gts-index", index)
    return index


def _max_bulletin_age_hours() -> float:
    raw = os.environ.get("ODSS_ADWX_MAX_BULLETIN_AGE_HOURS", "48").strip()
    try:
        value = float(raw)
    except ValueError:
        return 48.0
    return min(max(value, 1.0), 240.0)


def _estimate_issued_utc(day_hour_minute: str | None, now: datetime) -> datetime | None:
    """Resolve a WMO DDHHMM heading against the current or previous month.

    The mirror persists a centre's last file indefinitely, so a bulletin from
    weeks ago still sits at the same URL. The heading carries only the day of
    month; the newest calendar fit that is not in the future is the issue
    time, and anything older than the age ceiling is treated as not current
    rather than shown as a live warning.
    """
    if not day_hour_minute or len(day_hour_minute) != 6:
        return None
    try:
        day = int(day_hour_minute[0:2])
        hour = int(day_hour_minute[2:4])
        minute = int(day_hour_minute[4:6])
    except ValueError:
        return None
    candidates: list[datetime] = []
    year, month = now.year, now.month
    for _ in range(2):
        try:
            candidate = datetime(year, month, day, hour, minute, tzinfo=timezone.utc)
        except ValueError:
            candidate = None
        if candidate is not None and candidate <= now:
            candidates.append(candidate)
        month -= 1
        if month == 0:
            year, month = year - 1, 12
    return max(candidates) if candidates else None


def _bulletin_is_nil(text: str) -> bool:
    """A persisted file whose body after the heading is NIL carries no warning."""
    body = _WMO_HEADING.sub("", text, count=1).strip()
    return bool(re.fullmatch(r"(?:[A-Z]{4}\d{2}\s+[A-Z]{4}\s+\d{6}\s*)?NIL[\s=.]*", body))


def _gts_bulletins_for_station(
    client: httpx.Client,
    icao: str,
    index: dict[str, list[tuple[str, str]]],
    *,
    now: datetime,
) -> dict[str, Any]:
    prefixes = _station_prefixes(icao)
    bulletins: list[dict[str, Any]] = []
    attempted = 0
    failed = 0
    nil_count = 0
    max_age = _max_bulletin_age_hours()
    for family, rows in index.items():
        for filename, centre in rows:
            if attempted >= _MAX_BULLETINS_PER_AIRPORT:
                break
            if not any(centre.startswith(prefix) for prefix in prefixes):
                continue
            attempted += 1
            url = f"{GTS_MIRROR_ORIGIN}/data/raw/{family}/{filename}"
            cache_key = f"gts-bulletin:{url}"
            body = _cached(cache_key)
            if body is None:
                try:
                    body = _get(client, url, max_bytes=_MAX_BULLETIN_BYTES)
                except httpx.HTTPError:
                    body = None
                if body is None:
                    failed += 1
                    continue
                _store(cache_key, body)
            text = str(body).strip()
            if not text or _bulletin_is_nil(text):
                nil_count += 1
                continue
            heading = _WMO_HEADING.search(text)
            issued = _estimate_issued_utc(heading.group(3) if heading else None, now)
            # A heading the age estimate cannot resolve is not evidence of a
            # current warning either; the mirror keeps stale files forever.
            if issued is None or (now - issued).total_seconds() > max_age * 3600.0:
                nil_count += 1
                continue
            bulletins.append({
                "provider": f"{centre.lower()}-issued-warning-via-noaa-gts",
                "header": heading.group(1) + " " + heading.group(2) if heading else filename,
                "issued_utc_estimate": _iso(issued),
                "raw_text": text[:4000],
                "source_url": url,
            })
    return {
        "bulletins": bulletins,
        "attempted": attempted,
        "failed": failed,
        "nil": nil_count,
    }


def _authority_api_warnings(client: httpx.Client, row: dict[str, Any]) -> dict[str, Any]:
    if row["kind"] == "hko_warnsum":
        return _hko_warnsum_warnings(client, row)
    return _data_gov_sg_warnings(client, row)


def _hko_warnsum_warnings(client: httpx.Client, row: dict[str, Any]) -> dict[str, Any]:
    url = os.environ.get(row["env_url"], "").strip() or row["url"]
    try:
        response = client.get(url, timeout=_TIMEOUT_SECONDS, follow_redirects=False)
    except httpx.HTTPError:
        return {"status": "unavailable", "source_url": url, "warnings": []}
    if response.status_code != 200:
        return {"status": "unavailable", "source_url": url, "warnings": []}
    try:
        payload = response.json()
    except ValueError:
        return {"status": "unavailable", "source_url": url, "warnings": []}
    if not isinstance(payload, dict):
        return {"status": "unavailable", "source_url": url, "warnings": []}
    warnings: list[dict[str, Any]] = []
    for entry in payload.values():
        if not isinstance(entry, dict):
            continue
        if str(entry.get("actionCode") or "").upper() == "CANCEL":
            continue
        name = str(entry.get("name") or "").strip()
        if not name:
            continue
        detail = " · ".join(part for part in (
            name,
            str(entry.get("code") or "").strip(),
            f"issued {entry.get('issueTime')}" if entry.get("issueTime") else "",
            f"updated {entry.get('updateTime')}" if entry.get("updateTime") else "",
        ) if part)
        warnings.append({
            "provider": row["provider"],
            "header": row["authority"],
            "raw_text": detail[:4000],
            "source_url": url,
        })
    if not warnings:
        return {"status": "no_active_warning", "source_url": url, "warnings": []}
    return {"status": "active_warnings", "source_url": url, "warnings": warnings}


def _data_gov_sg_warnings(client: httpx.Client, row: dict[str, Any]) -> dict[str, Any]:
    url = os.environ.get(row["env_url"], "").strip() or row["url"]
    try:
        response = client.get(url, timeout=_TIMEOUT_SECONDS, follow_redirects=False)
    except httpx.HTTPError:
        return {"status": "unavailable", "source_url": url, "warnings": []}
    try:
        payload = response.json()
    except ValueError:
        payload = None
    # The API answers code 17 / "Data not found" when no warning is in force —
    # a normal state, reported as exactly that rather than as a failure. It is
    # recognised from the body so an unusual HTTP status cannot disguise it.
    if isinstance(payload, dict) and (
        payload.get("code") == 17
        or str(payload.get("name") or "") == "REAL_TIME_API_DATA_NOT_FOUND"
    ):
        return {"status": "no_active_warning", "source_url": url, "warnings": []}
    if response.status_code != 200 or not isinstance(payload, dict):
        return {"status": "unavailable", "source_url": url, "warnings": []}
    if payload.get("data") in (None, {}, []):
        return {"status": "no_active_warning", "source_url": url, "warnings": []}
    warnings: list[dict[str, Any]] = []
    data = payload.get("data")
    records = data.get("records") if isinstance(data, dict) else None
    for record in records if isinstance(records, list) else [data]:
        if not isinstance(record, dict):
            continue
        warnings.append({
            "provider": row["provider"],
            "header": row["authority"],
            "raw_text": str(record)[:4000],
            "source_url": url,
        })
    if not warnings:
        return {"status": "no_active_warning", "source_url": url, "warnings": []}
    return {"status": "active_warnings", "source_url": url, "warnings": warnings}


def enrich_aerodrome_warnings(
    flight: dict[str, Any],
    *,
    client: httpx.Client | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Attach per-airport local-authority warnings with honest absence states."""
    configured = os.environ.get("ODSS_ADWX_SOURCE", "gts").strip().lower()
    stations = _flight_stations(flight)
    retrieved_at = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    if configured in {"disabled", "off", "none"}:
        review = {
            "schema_version": "1.0",
            "status": "not_assessed",
            "stations_requested": stations,
            "products": {},
            "reason_codes": ["source_disabled"],
        }
        flight["aerodrome_warning_review"] = review
        return review
    if not stations:
        review = {
            "schema_version": "1.0",
            "status": "review_required",
            "stations_requested": [],
            "products": {},
            "reason_codes": ["airport_identifiers_unavailable"],
        }
        flight["aerodrome_warning_review"] = review
        return review

    owns_client = client is None
    http = client or httpx.Client(headers={"User-Agent": "PilotDriven-ODSS (aerodrome warnings)"})
    try:
        index = _warning_index(http)
        products: dict[str, Any] = {}
        reason_codes: list[str] = []
        if index is None:
            reason_codes.append("gts_mirror_unavailable")
        for icao in stations:
            gts = (
                _gts_bulletins_for_station(http, icao, index, now=retrieved_at)
                if index is not None
                else {"bulletins": [], "attempted": 0, "failed": 0, "nil": 0}
            )
            receipts = [{
                "source_url": bulletin["source_url"],
                "retrieved_at_utc": _iso(retrieved_at),
            } for bulletin in gts["bulletins"]]
            warnings = list(gts["bulletins"])
            api_status: str | None = None
            row = AUTHORITY_API_ROWS.get(icao[:2]) or AUTHORITY_API_ROWS.get(icao[0])
            if row is not None:
                api_result = _authority_api_warnings(http, row)
                api_status = api_result["status"]
                receipts.append({
                    "source_url": api_result["source_url"],
                    "retrieved_at_utc": _iso(retrieved_at),
                })
                warnings.extend(api_result["warnings"])
            checked_anything = gts["attempted"] > 0 or api_status is not None
            nothing_verifiable = (
                index is None
                or gts["failed"] > 0
                or api_status == "unavailable"
            )
            if warnings:
                # The authority's issued text is held and shown verbatim with
                # its issued time; validity judgement stays with the pilot.
                status = "warnings_held"
            elif api_status == "no_active_warning" or gts["nil"] > 0:
                status = "no_active_warning"
            elif nothing_verifiable and checked_anything:
                status = "unavailable"
            elif not checked_anything and index is None:
                status = "unavailable"
            else:
                # The country publishes nothing under this airport's prefix on
                # the public mirror and has no configured authority API row.
                status = "no_public_feed"
            products[icao] = {
                "status": status,
                "warnings": warnings,
                "source_receipts": receipts,
            }
        review = {
            "schema_version": "1.0",
            "status": "covered" if products else "review_required",
            "stations_requested": stations,
            "products": products,
            "reason_codes": reason_codes,
        }
        flight["aerodrome_warning_review"] = review
        return review
    finally:
        if owns_client:
            http.close()

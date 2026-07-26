"""Governed direct advisory intake from the official Tokyo VAAC website.

The direct VAA/VAG record is source evidence separate from the international
SIGMET feed. Only the fixed JMA HTTPS origin and a bounded flight-time window
are retrieved. Forecast snapshots are retained as snapshots; they are not
interpolated into a continuous hazard boundary or presented as global VAAC
coverage.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from html import unescape
import os
import re
from threading import Lock
import time
from typing import Any
from urllib.parse import urljoin, urlsplit

import httpx


JMA_VAAC_ORIGIN = "https://www.data.jma.go.jp"
JMA_VAAC_LIST_PATH = "/vaac/data/vaac_list.html"
_MAX_HTML_BYTES = 2 * 1024 * 1024
_MAX_ADVISORIES = 32
_CACHE_LOCK = Lock()
_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
_ROW = re.compile(r"<tr\b[^>]*class=[\"']?mtx[\"']?[^>]*>(.*?)</tr>", re.I | re.S)
_ISSUE = re.compile(
    r"<td\b[^>]*DISPLAY:\s*none[^>]*>\s*"
    r"(\d{4}/\d{2}/\d{2}\s+\d{2}:\d{2}:\d{2})\s*</td>",
    re.I,
)
_TEXT_LINK = re.compile(
    r'href=[\"\'](TextData/\d{4}/[^\"\']+_Text\.html)[\"\']',
    re.I,
)
_VAG_LINK = re.compile(
    r"opennewwide\(['\"](VAG/\d{4}/html/[^'\"]+)[\"']\)",
    re.I,
)
_VOLCANO = re.compile(
    r"</td>\s*<td>([^<]+)</td>\s*<td>([^<]+)</td>\s*"
    r"<td><font[^>]*>([^<]+)</font>",
    re.I,
)
_FIELD = re.compile(r"^([A-Z][A-Z0-9 +/()_-]*):\s*(.*)$")
_COORDINATE = re.compile(
    r"\b([NS])(\d{2})(\d{2})?\s+([EW])(\d{3})(\d{2})?\b"
)


def _utc(value: Any) -> datetime | None:
    text = str(value or "").strip().replace("Z", "+00:00")
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _flight_window(flight: dict[str, Any]) -> tuple[datetime, datetime] | None:
    departure = _utc(
        flight.get("actual_takeoff_utc")
        or (flight.get("timing_reference") or {}).get("actual_takeoff_utc")
        or flight.get("scheduled_departure_utc")
    )
    arrival = _utc(flight.get("scheduled_arrival_utc"))
    if departure is None:
        return None
    if arrival is None:
        route_minutes = max(
            (
                int(item["actm_minutes"])
                for item in (flight.get("route_waypoints") or [])
                if item.get("actm_minutes") is not None
            ),
            default=0,
        )
        arrival = departure + timedelta(minutes=route_minutes)
    if arrival < departure:
        return None
    return departure - timedelta(hours=18), arrival + timedelta(hours=1)


def _bounded_html(response: httpx.Response) -> bytes:
    response.raise_for_status()
    raw = response.content
    if len(raw) > _MAX_HTML_BYTES:
        raise ValueError("Tokyo VAAC response exceeded the safety limit")
    return raw


def _safe_source_url(path: str) -> str | None:
    candidate = urljoin(f"{JMA_VAAC_ORIGIN}{JMA_VAAC_LIST_PATH}", path)
    parsed = urlsplit(candidate)
    if parsed.scheme != "https" or parsed.hostname != "www.data.jma.go.jp":
        return None
    if not parsed.path.startswith("/vaac/data/"):
        return None
    return candidate


def parse_tokyo_vaac_listing(raw: bytes) -> list[dict[str, Any]]:
    if len(raw) > _MAX_HTML_BYTES:
        raise ValueError("Tokyo VAAC listing exceeded the safety limit")
    text = raw.decode("utf-8", errors="replace")
    rows: list[dict[str, Any]] = []
    for match in _ROW.finditer(text):
        row = match.group(1)
        issue_match = _ISSUE.search(row)
        link_match = _TEXT_LINK.search(row)
        if not issue_match or not link_match:
            continue
        try:
            issued = datetime.strptime(
                issue_match.group(1),
                "%Y/%m/%d %H:%M:%S",
            ).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        source_url = _safe_source_url(link_match.group(1))
        if source_url is None:
            continue
        metadata = _VOLCANO.search(row)
        vag_match = _VAG_LINK.search(row)
        rows.append({
            "issued_at_utc": _iso(issued),
            "volcano": unescape(metadata.group(1)).strip() if metadata else None,
            "area": unescape(metadata.group(2)).strip() if metadata else None,
            "advisory_number": (
                unescape(metadata.group(3)).strip() if metadata else None
            ),
            "vaa_url": source_url,
            "vag_url": _safe_source_url(vag_match.group(1)) if vag_match else None,
        })
    rows.sort(key=lambda item: item["issued_at_utc"], reverse=True)
    return rows


def _plain_advisory(raw: bytes) -> str:
    if len(raw) > _MAX_HTML_BYTES:
        raise ValueError("Tokyo VAAC advisory exceeded the safety limit")
    html = raw.decode("utf-8", errors="replace")
    match = re.search(
        r"<!--\s*VAA Text Start\s*-->(.*?)<!--\s*VAA Text End\s*-->",
        html,
        re.I | re.S,
    )
    if not match:
        raise ValueError("Tokyo VAAC advisory body was not found")
    body = re.sub(r"<br\s*/?>", "\n", match.group(1), flags=re.I)
    body = re.sub(r"<[^>]+>", " ", body)
    return "\n".join(
        line.strip()
        for line in unescape(body).splitlines()
        if line.strip()
    )


def _fields(text: str) -> dict[str, str]:
    output: dict[str, str] = {}
    current: str | None = None
    for line in text.splitlines():
        match = _FIELD.match(line)
        if match:
            current = match.group(1).strip()
            output[current] = match.group(2).strip()
        elif current:
            output[current] = f"{output[current]} {line.strip()}".strip()
    return output


def _phase_time(value: str, issued_at: datetime) -> datetime | None:
    match = re.match(r"(\d{2})/(\d{2})(\d{2})Z\b", value)
    if not match:
        return None
    day, hour, minute = map(int, match.groups())
    candidates: list[datetime] = []
    for offset in (-1, 0, 1):
        month_index = issued_at.month - 1 + offset
        year = issued_at.year + month_index // 12
        month = month_index % 12 + 1
        try:
            candidates.append(
                datetime(year, month, day, hour, minute, tzinfo=timezone.utc)
            )
        except ValueError:
            continue
    return min(candidates, key=lambda item: abs(item - issued_at), default=None)


def _position(
    latitude: str,
    lat_degrees: str,
    lat_minutes: str | None,
    longitude: str,
    lon_degrees: str,
    lon_minutes: str | None,
) -> list[float]:
    lat = float(lat_degrees) + float(lat_minutes or 0) / 60
    lon = float(lon_degrees) + float(lon_minutes or 0) / 60
    if latitude == "S":
        lat = -lat
    if longitude == "W":
        lon = -lon
    return [round(lon, 5), round(lat, 5)]


def _phase(label: str, value: str, issued_at: datetime) -> dict[str, Any]:
    upper = value.upper()
    valid_at = _phase_time(upper, issued_at)
    coordinates = [
        _position(*match.groups())
        for match in _COORDINATE.finditer(upper)
    ]
    layer = re.search(r"\b(SFC|FL\d{3})/(SFC|FL\d{3})\b", upper)
    state = (
        "not_available"
        if "NOT AVBL" in upper
        else "no_ash_expected"
        if "NO VA EXP" in upper
        else "not_identifiable"
        if "NOT IDENTIFIABLE" in upper
        else "polygon_available"
        if len(coordinates) >= 3
        else "text_only"
    )
    return {
        "phase": label,
        "valid_at_utc": _iso(valid_at),
        "state": state,
        "lower_limit": layer.group(1) if layer else None,
        "upper_limit": layer.group(2) if layer else None,
        "polygon": coordinates if len(coordinates) >= 3 else None,
    }


def parse_tokyo_vaac_advisory(
    raw: bytes,
    metadata: dict[str, Any],
) -> dict[str, Any]:
    text = _plain_advisory(raw)
    fields = _fields(text)
    issued_at = _utc(metadata.get("issued_at_utc"))
    if issued_at is None or fields.get("VAAC", "").upper() != "TOKYO":
        raise ValueError("Tokyo VAAC advisory identity could not be verified")
    phases: list[dict[str, Any]] = []
    observed = fields.get("OBS VA CLD")
    if observed:
        phases.append(_phase(
            "observed",
            f"{fields.get('OBS VA DTG', '')} {observed}".strip(),
            issued_at,
        ))
    for hours in (6, 12, 18):
        value = fields.get(f"FCST VA CLD +{hours} HR")
        if value:
            phases.append(_phase(f"forecast_plus_{hours}_hours", value, issued_at))
    return {
        **metadata,
        "provider": "jma-tokyo-vaac",
        "vaac": fields.get("VAAC"),
        "volcano": fields.get("VOLCANO") or metadata.get("volcano"),
        "area": fields.get("AREA") or metadata.get("area"),
        "advisory_number": (
            fields.get("ADVISORY NR") or metadata.get("advisory_number")
        ),
        "information_source": fields.get("INFO SOURCE"),
        "eruption_details": fields.get("ERUPTION DETAILS"),
        "phases": phases,
        "next_advisory": fields.get("NXT ADVISORY"),
        "raw_sha256": sha256(text.encode("utf-8")).hexdigest(),
    }


def fetch_tokyo_vaac_snapshot(
    flight: dict[str, Any],
    *,
    client: httpx.Client | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    retrieved_at = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    window = _flight_window(flight)
    list_url = f"{JMA_VAAC_ORIGIN}{JMA_VAAC_LIST_PATH}"
    if window is None:
        return {
            "schema_version": "1.0",
            "status": "unavailable",
            "provider": "jma-tokyo-vaac",
            "source_url": list_url,
            "retrieved_at_utc": _iso(retrieved_at),
            "advisories": [],
            "error": "Flight timing is unavailable",
        }
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
            "Accept": "text/html",
        },
    )
    errors: list[dict[str, str]] = []
    try:
        rows = parse_tokyo_vaac_listing(
            _bounded_html(active_client.get(list_url))
        )
        selected = [
            row
            for row in rows
            if (
                (issued := _utc(row.get("issued_at_utc"))) is not None
                and window_start <= issued <= window_end
            )
        ][:_MAX_ADVISORIES]
        advisories: list[dict[str, Any]] = []
        for row in selected:
            try:
                advisories.append(parse_tokyo_vaac_advisory(
                    _bounded_html(active_client.get(row["vaa_url"])),
                    row,
                ))
            except (httpx.HTTPError, ValueError) as exc:
                errors.append({
                    "source_url": row["vaa_url"],
                    "error": f"{type(exc).__name__}: {str(exc)[:160]}",
                })
        return {
            "schema_version": "1.0",
            "status": "available" if not errors else "partial",
            "provider": "jma-tokyo-vaac",
            "source_url": list_url,
            "retrieved_at_utc": _iso(retrieved_at),
            "coverage_status": "tokyo_vaac_area_direct_advisories",
            "requested_issue_window_start_utc": _iso(window_start),
            "requested_issue_window_end_utc": _iso(window_end),
            "listing_earliest_utc": rows[-1]["issued_at_utc"] if rows else None,
            "listing_latest_utc": rows[0]["issued_at_utc"] if rows else None,
            "advisory_count": len(advisories),
            "advisories": advisories,
            "errors": errors,
            "source_note": (
                "Official Tokyo VAAC VAA/VAG evidence for its area only. "
                "Forecast polygons remain official snapshots and are not "
                "interpolated into a continuous hazard boundary."
            ),
        }
    except (httpx.HTTPError, ValueError) as exc:
        return {
            "schema_version": "1.0",
            "status": "unavailable",
            "provider": "jma-tokyo-vaac",
            "source_url": list_url,
            "retrieved_at_utc": _iso(retrieved_at),
            "coverage_status": "unavailable",
            "advisories": [],
            "errors": [{"error": f"{type(exc).__name__}: {str(exc)[:160]}"}],
        }
    finally:
        if own_client:
            active_client.close()


def live_tokyo_vaac_snapshot(flight: dict[str, Any]) -> dict[str, Any]:
    window = _flight_window(flight)
    cache_key = "|".join(_iso(value) or "" for value in window) if window else "missing"
    try:
        seconds = max(
            300.0,
            min(1800.0, float(os.environ.get("ODSS_VAAC_CACHE_SECONDS", "600"))),
        )
    except ValueError:
        seconds = 600.0
    now_monotonic = time.monotonic()
    with _CACHE_LOCK:
        cached = _CACHE.get(cache_key)
        if cached and now_monotonic - cached[0] < seconds:
            return deepcopy(cached[1])
        snapshot = fetch_tokyo_vaac_snapshot(flight)
        _CACHE[cache_key] = (now_monotonic, snapshot)
        return deepcopy(snapshot)


__all__ = [
    "JMA_VAAC_LIST_PATH",
    "JMA_VAAC_ORIGIN",
    "fetch_tokyo_vaac_snapshot",
    "live_tokyo_vaac_snapshot",
    "parse_tokyo_vaac_advisory",
    "parse_tokyo_vaac_listing",
]

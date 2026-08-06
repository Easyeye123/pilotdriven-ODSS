"""Governed direct SIGMET intake from responsible national authorities.

The named live-weather authorities for this deployment are NOAA, JMA, BOM and
the Hong Kong Observatory (boss instruction, 04.08.26: "Live weather SIGMET,
satellite and METAR and TAF take from NOAA, JMA, BOM and Hong Kong Observatory
website"). NOAA AWC is already the aggregate international-SIGMET feed in
``vaa.py``. This module adds the direct authority-of-record layer on the same
governed-snapshot pattern as ``direct_vaac.py``:

- **BOM** (Australian FIRs YBBB/YMMM): the official public page publishes full
  ICAO raw-text SIGMETs — fetched from bom.gov.au directly.
- **JMA** (RJJJ) and **HKO** (VHHK): their own public pages carry chart imagery
  or prose only (verified 07.08.26 — JMA's QGMA98 series; nothing on hko.gov.hk
  or data.gov.hk). The authorities' ISSUED bulletins are public as raw text on
  NOAA's GTS mirror (tgftp.nws.noaa.gov, headings WSJP31 RJTD and WSSS20 VHHH),
  so those connectors fetch the authority's own words from the NOAA host and
  say so in their provenance.

Direct records strengthen coverage and the map overlay. Their absence never
adds reason codes: the AWC aggregate — which carries RJJJ, YBBB/YMMM and VHHK
SIGMETs — remains the baseline coverage authority, and a direct source that
cannot be fetched must not turn a covered review into an amber one.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from hashlib import sha256
from html import unescape
import os
import re
from threading import Lock
import time
from typing import Any
from urllib.parse import urlsplit

import httpx

from .snapshot_governance import govern_snapshot, mark_snapshot_reused


BOM_SIGMET_URL = "https://www.bom.gov.au/aviation/warnings/sigmet/"
BOM_ALLOWED_HOSTS = frozenset({"www.bom.gov.au", "bom.gov.au"})
BOM_PROVIDER = "bom-australia-sigmet-direct"
BOM_FIR_IDS = frozenset({"YBBB", "YMMM"})

GTS_MIRROR_ORIGIN = "https://tgftp.nws.noaa.gov"
GTS_ALLOWED_HOSTS = frozenset({"tgftp.nws.noaa.gov"})

# Generous bounding boxes. Too large is safe — it only means the direct source
# is consulted more often; the route × geometry evaluation stays exact.
AUSTRALIAN_FIR_BBOX = {
    "lat_min": -60.0,
    "lat_max": -5.0,
    "lon_min": 75.0,
    "lon_max": 170.0,
}

# The authority's own issued bulletin, served as raw text from NOAA's GTS
# mirror. The heading identifies the issuing centre: WSJP31 RJTD is JMA Tokyo
# for the Fukuoka FIR, WSSS20 VHHH is the Hong Kong Observatory for VHHK.
GTS_CENTRES: dict[str, dict[str, Any]] = {
    "jma": {
        "provider": "jma-rjtd-sigmet-via-noaa-gts",
        "path": "/data/raw/ws/wsjp31.rjtd..txt",
        "env_url": "ODSS_JMA_SIGMET_URL",
        "fir_ids": ("RJJJ",),
        "bbox": {"lat_min": 15.0, "lat_max": 55.0, "lon_min": 115.0, "lon_max": 170.0},
    },
    "hko": {
        "provider": "hko-vhhh-sigmet-via-noaa-gts",
        "path": "/data/raw/ws/wsss20.vhhh..txt",
        "env_url": "ODSS_HKO_SIGMET_URL",
        "fir_ids": ("VHHK",),
        "bbox": {"lat_min": 12.0, "lat_max": 27.0, "lon_min": 105.0, "lon_max": 122.0},
    },
}

_MAX_HTML_BYTES = 2 * 1024 * 1024
_MAX_ADVISORIES = 64
_CACHE_LOCK = Lock()
_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}

_PRODUCT_BLOCK = re.compile(r'<p\s+class="product">(.*?)</p>', re.I | re.S)
_BREAK = re.compile(r"<br\s*/?>", re.I)
_TAG = re.compile(r"<[^>]+>")
_ISSUED = re.compile(r"(\d{2}):(\d{2})\s*UTC,\s*(\d{2})/(\d{2})/(\d{4})")
_HEADER = re.compile(
    r"^(?P<fir>[A-Z]{4})\s+SIGMET\s+(?P<series>[A-Z0-9]{1,3})\s+"
    r"VALID\s+(?P<from>\d{6})/(?P<to>\d{6})\s+[A-Z]{4}-"
)
_WMO_HEADING = re.compile(r"^WS[A-Z]{2}\d{2}\s+(?P<centre>[A-Z]{4})\s+(?P<issued>\d{6})")
# The separator is optional: BOM prints "S5000 E12600" while JMA compacts the
# pair to "N3000E13714".
_COORDINATE = re.compile(r"\b([NS])(\d{2})(\d{2})?\s*([EW])(\d{3})(\d{2})?\b")
_LEVEL_BAND = re.compile(r"\bFL(\d{3})/(\d{3})\b")
_LEVEL_SFC_TOP = re.compile(r"\bSFC/FL(\d{3})\b")
_LEVEL_TOP_ONLY = re.compile(r"\bTOPS?\s+(?:ABV\s+|TO\s+)?FL(\d{3})\b")

# Ordered so multi-word phenomena match before their substrings. Only hazards
# the AWC path also supports are accepted; anything else is a parse warning,
# never a guessed classification.
_HAZARD_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("RDOACT CLD", re.compile(r"\bRDOACT\s+CLD\b")),
    ("VA", re.compile(r"\bVA\b|\bVOLCANIC\s+ASH\b")),
    ("TC", re.compile(r"\bTC\b")),
    ("MTW", re.compile(r"\bMTW\b")),
    ("TS", re.compile(r"\bTSGR\b|\bTS\b")),
    ("TURB", re.compile(r"\bTURB\b")),
    ("ICE", re.compile(r"\bICE\b|\bICING\b")),
    ("DS", re.compile(r"\bDS\b|\bDUSTSTORM\b")),
    ("SS", re.compile(r"\bSS\b|\bSANDSTORM\b")),
)
_SURFACE_BASED = frozenset({"DS", "SS", "TC", "TS"})


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime | None) -> str | None:
    return value.astimezone(timezone.utc).isoformat() if value else None


def _float_setting(name: str, default: float, minimum: float, maximum: float) -> float:
    raw = os.environ.get(name, str(default)).strip()
    try:
        value = float(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be numeric") from exc
    if not minimum <= value <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return value


def _cache_seconds() -> float:
    try:
        return _float_setting("ODSS_DIRECT_SIGMET_CACHE_SECONDS", 300.0, 60.0, 1800.0)
    except ValueError:
        return 300.0


def _govern_bom_snapshot(snapshot: dict[str, Any], retrieved_at: datetime) -> dict[str, Any]:
    seconds = _cache_seconds()
    return govern_snapshot(
        snapshot,
        now=retrieved_at,
        refresh_after_seconds=seconds,
        expires_after_seconds=max(900.0, seconds * 3),
        scope="bom_current_australian_fir_sigmet_page",
        effective_start_utc=snapshot.get("coverage_start_utc"),
        effective_end_utc=snapshot.get("coverage_end_utc"),
    )


def _resolve_ddhhmm(token: str, anchor: datetime) -> datetime | None:
    """Resolve a SIGMET DDHHMM token against an anchor instant.

    The candidate shares the anchor's month; a candidate far in the past rolls
    forward one month and one far in the future rolls back, which covers
    month-end validity windows without trusting the page beyond its own data.
    """
    if not re.fullmatch(r"\d{6}", token or ""):
        return None
    day, hour, minute = int(token[0:2]), int(token[2:4]), int(token[4:6])
    if not 1 <= day <= 31 or hour > 23 or minute > 59:
        return None

    def _month_shift(base: datetime, months: int) -> datetime:
        month_index = base.month - 1 + months
        year = base.year + month_index // 12
        month = month_index % 12 + 1
        return base.replace(year=year, month=month)

    for shift in (0, 1, -1):
        try:
            candidate = _month_shift(anchor.replace(day=1), shift).replace(
                day=day, hour=hour, minute=minute, second=0, microsecond=0
            )
        except ValueError:
            continue
        if anchor - timedelta(days=14) <= candidate <= anchor + timedelta(days=14):
            return candidate
    return None


def _parse_coordinates(body: str) -> list[list[float]] | None:
    ring: list[list[float]] = []
    for match in _COORDINATE.finditer(body):
        ns, lat_deg, lat_min, ew, lon_deg, lon_min = match.groups()
        latitude = float(lat_deg) + (float(lat_min) / 60 if lat_min else 0.0)
        longitude = float(lon_deg) + (float(lon_min) / 60 if lon_min else 0.0)
        if ns == "S":
            latitude = -latitude
        if ew == "W":
            longitude = -longitude
        if not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
            return None
        ring.append([longitude, latitude])
    if len(ring) < 3:
        return None
    if ring[0] != ring[-1]:
        ring.append(list(ring[0]))
    return ring


def _parse_levels(body: str, hazard: str) -> tuple[int | None, int | None]:
    band = _LEVEL_BAND.search(body)
    if band:
        return int(band.group(1)), int(band.group(2))
    sfc = _LEVEL_SFC_TOP.search(body)
    if sfc:
        return 0, int(sfc.group(1))
    top_only = _LEVEL_TOP_ONLY.search(body)
    if top_only and hazard in _SURFACE_BASED:
        return 0, int(top_only.group(1))
    return None, None


_FIR_NAME = re.compile(r"^[A-Z]{4}\s+((?:[A-Z][A-Z/-]*\s+)*?FIR)\b")


def parse_icao_sigmet_text(
    block_text: str,
    anchor: datetime,
    provider: str,
) -> tuple[dict[str, Any] | None, str | None]:
    """Parse one raw ICAO SIGMET into the shared advisory schema.

    The grammar covers what BOM, JMA (RJTD) and HKO (VHHH) actually publish:
    ``<FIR> SIGMET <series> VALID <DDHHMM>/<DDHHMM> <issuer>-`` followed by the
    body. Cancellations, non-polygon scopes and unrecognised phenomena come
    back as warnings — never as guessed advisories.
    """
    lines = [" ".join(line.split()) for line in block_text.splitlines()]
    text = " ".join(line for line in lines if line).strip()
    if not text or "SIGMET" not in text:
        return None, None
    header = _HEADER.match(text)
    if not header:
        return None, "unrecognized_header"
    fir = header.group("fir")
    series = header.group("series")
    valid_from = _resolve_ddhhmm(header.group("from"), anchor)
    valid_to = _resolve_ddhhmm(header.group("to"), anchor)
    if not valid_from or not valid_to or valid_to <= valid_from:
        return None, "missing_time_or_geometry"

    body = text[header.end():]
    if "CNL SIGMET" in body:
        return None, "cancellation"
    hazard = next(
        (code for code, pattern in _HAZARD_PATTERNS if pattern.search(body)),
        None,
    )
    if hazard is None:
        return None, "unrecognized_hazard"

    # Only "WI <polygon>" geometry is drawn. Line, radius, point-observation
    # and whole-FIR scopes are real SIGMETs but publish no exact polygon;
    # inventing one would claim precision the source did not state.
    if " WI " not in f" {body} ":
        return None, "unsupported_geometry"
    ring = _parse_coordinates(body)
    if ring is None:
        return None, "missing_time_or_geometry"

    lower_level, upper_level = _parse_levels(body, hazard)
    if lower_level is None or upper_level is None or upper_level < lower_level:
        return None, "invalid_vertical_limits"

    fir_name_match = _FIR_NAME.match(body.strip())
    raw_text = text if text.endswith("=") else f"{text}="
    return {
        "advisory_id": f"{fir}-{series}-{int(valid_from.timestamp())}",
        "hazard": hazard,
        "fir_id": fir,
        "fir_name": fir_name_match.group(1) if fir_name_match else None,
        "series_id": series,
        "valid_from_utc": _iso(valid_from),
        "valid_to_utc": _iso(valid_to),
        "lower_flight_level": lower_level,
        "upper_flight_level": upper_level,
        "geometry": {"type": "Polygon", "coordinates": [ring]},
        "raw_text": raw_text,
        "raw_sha256": sha256(raw_text.encode("utf-8")).hexdigest(),
        "receipt_time_utc": None,
        "source_provider": provider,
    }, None


def parse_bom_sigmet_page(html: str, retrieved_at: datetime) -> dict[str, Any]:
    """Parse the official BOM SIGMET page into advisories plus warnings."""
    advisories: list[dict[str, Any]] = []
    parse_warnings: list[str] = []
    issued_at: datetime | None = None
    blocks = _PRODUCT_BLOCK.findall(html)
    for index, raw_block in enumerate(blocks[:_MAX_ADVISORIES]):
        block_text = unescape(_TAG.sub("", _BREAK.sub("\n", raw_block)))
        if issued_at is None:
            stamp = _ISSUED.search(block_text)
            if stamp:
                hour, minute, day, month, year = (int(part) for part in stamp.groups())
                try:
                    issued_at = datetime(year, month, day, hour, minute, tzinfo=timezone.utc)
                except ValueError:
                    issued_at = None
                if "SIGMET" not in block_text.split("VALID")[0].replace("AUSTRALIAN SIGMETS", ""):
                    continue
        advisory, warning = parse_icao_sigmet_text(
            block_text, issued_at or retrieved_at, BOM_PROVIDER
        )
        if advisory:
            advisories.append(advisory)
        elif warning:
            parse_warnings.append(f"record_{index}:{warning}")
    return {
        "issued_at_utc": _iso(issued_at),
        "advisories": advisories,
        "parse_warnings": parse_warnings,
    }


def parse_gts_sigmet_bulletin(
    bulletin: str,
    retrieved_at: datetime,
    provider: str,
) -> dict[str, Any]:
    """Parse one GTS raw SIGMET bulletin (WMO heading + one or more SIGMETs)."""
    advisories: list[dict[str, Any]] = []
    parse_warnings: list[str] = []
    issued_at: datetime | None = None
    lines = [line.rstrip() for line in bulletin.splitlines()]
    body_start = 0
    for index, line in enumerate(lines):
        heading = _WMO_HEADING.match(line.strip())
        if heading:
            issued_at = _resolve_ddhhmm(heading.group("issued"), retrieved_at)
            body_start = index + 1
            break
    # One bulletin can carry several SIGMETs, each terminated by "=".
    segments = [
        segment.strip()
        for segment in "\n".join(lines[body_start:]).split("=")
        if segment.strip()
    ]
    for index, segment in enumerate(segments[:_MAX_ADVISORIES]):
        advisory, warning = parse_icao_sigmet_text(
            f"{segment}=", issued_at or retrieved_at, provider
        )
        if advisory:
            advisories.append(advisory)
        elif warning:
            parse_warnings.append(f"record_{index}:{warning}")
    return {
        "issued_at_utc": _iso(issued_at),
        "advisories": advisories,
        "parse_warnings": parse_warnings,
    }


def fetch_bom_sigmet_snapshot(
    *,
    client: httpx.Client | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Fetch a bounded, auditable snapshot of current Australian SIGMETs."""
    retrieved_at = (now or _utc_now()).astimezone(timezone.utc)
    url = os.environ.get("ODSS_BOM_SIGMET_URL", BOM_SIGMET_URL).strip() or BOM_SIGMET_URL
    parsed_url = urlsplit(url)

    def _unavailable(error: str) -> dict[str, Any]:
        return _govern_bom_snapshot({
            "schema_version": "1.0",
            "provider": BOM_PROVIDER,
            "source_url": url,
            "status": "unavailable",
            "retrieved_at_utc": _iso(retrieved_at),
            "coverage_status": "unavailable",
            "declared_fir_ids": sorted(BOM_FIR_IDS),
            "freshness_status": "unknown",
            "advisories": [],
            "parse_warnings": [],
            "error": error,
        }, retrieved_at)

    if parsed_url.scheme != "https" or parsed_url.hostname not in BOM_ALLOWED_HOSTS:
        return _unavailable("ODSS_BOM_SIGMET_URL must use the approved bom.gov.au HTTPS host")
    try:
        timeout = _float_setting("ODSS_DIRECT_SIGMET_TIMEOUT_SECONDS", 8.0, 1.0, 30.0)
        freshness_limit = _float_setting("ODSS_DIRECT_SIGMET_FRESHNESS_MINUTES", 60.0, 5.0, 360.0)
    except ValueError as exc:
        return _unavailable(str(exc))

    user_agent = os.environ.get("ODSS_VA_SIGMET_USER_AGENT", "").strip() or (
        "PilotDriven-ODSS/0.6.1 (operational-briefing service)"
    )
    own_client = client is None
    active_client = client or httpx.Client(timeout=timeout, follow_redirects=True)
    try:
        response = active_client.get(url, headers={"User-Agent": user_agent, "Accept": "text/html"})
        response.raise_for_status()
        if len(response.content) > _MAX_HTML_BYTES:
            raise ValueError("BOM SIGMET page exceeded the safety limit")
        html = response.text
    except (httpx.HTTPError, ValueError) as exc:
        return _unavailable(f"{type(exc).__name__}: {str(exc)[:180]}")
    finally:
        if own_client:
            active_client.close()

    parsed = parse_bom_sigmet_page(html, retrieved_at)
    issued_at = parsed.get("issued_at_utc")
    freshness_minutes: float | None = None
    freshness_status = "unknown"
    if issued_at:
        issued = datetime.fromisoformat(issued_at)
        freshness_minutes = abs((retrieved_at - issued).total_seconds()) / 60
        freshness_status = "fresh" if freshness_minutes <= freshness_limit else "stale"
    advisories = parsed["advisories"]
    valid_starts = [item["valid_from_utc"] for item in advisories]
    valid_ends = [item["valid_to_utc"] for item in advisories]
    return _govern_bom_snapshot({
        "schema_version": "1.0",
        "provider": BOM_PROVIDER,
        "source_url": url,
        "status": "available",
        "retrieved_at_utc": _iso(retrieved_at),
        "issued_at_utc": issued_at,
        "coverage_status": "australian_firs_only",
        "declared_fir_ids": sorted(BOM_FIR_IDS),
        "coverage_start_utc": min(valid_starts) if valid_starts else None,
        "coverage_end_utc": max(valid_ends) if valid_ends else None,
        "freshness_status": freshness_status,
        "freshness_minutes": freshness_minutes,
        "advisory_count": len(advisories),
        "advisories": advisories,
        "parse_warnings": parsed["parse_warnings"],
    }, retrieved_at)


def live_bom_sigmet_snapshot() -> dict[str, Any]:
    """Serve the governed BOM receipt from a bounded shared cache."""
    cache_seconds = _cache_seconds()
    with _CACHE_LOCK:
        cached = _CACHE.get("bom")
        if cached and time.monotonic() - cached[0] < cache_seconds:
            return mark_snapshot_reused(cached[1])
    snapshot = fetch_bom_sigmet_snapshot()
    with _CACHE_LOCK:
        _CACHE["bom"] = (time.monotonic(), snapshot)
    return snapshot


def fetch_gts_sigmet_snapshot(
    centre_key: str,
    *,
    client: httpx.Client | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Fetch one authority's issued SIGMET bulletin from the NOAA GTS mirror."""
    centre = GTS_CENTRES[centre_key]
    retrieved_at = (now or _utc_now()).astimezone(timezone.utc)
    default_url = f"{GTS_MIRROR_ORIGIN}{centre['path']}"
    url = os.environ.get(centre["env_url"], default_url).strip() or default_url
    parsed_url = urlsplit(url)

    def _unavailable(error: str) -> dict[str, Any]:
        return _govern_bom_snapshot({
            "schema_version": "1.0",
            "provider": centre["provider"],
            "source_url": url,
            "status": "unavailable",
            "retrieved_at_utc": _iso(retrieved_at),
            "coverage_status": "unavailable",
            "declared_fir_ids": list(centre["fir_ids"]),
            "freshness_status": "unknown",
            "advisories": [],
            "parse_warnings": [],
            "error": error,
        }, retrieved_at)

    if parsed_url.scheme != "https" or parsed_url.hostname not in GTS_ALLOWED_HOSTS:
        return _unavailable(
            f"{centre['env_url']} must use the approved tgftp.nws.noaa.gov HTTPS host"
        )
    try:
        timeout = _float_setting("ODSS_DIRECT_SIGMET_TIMEOUT_SECONDS", 8.0, 1.0, 30.0)
        freshness_limit = _float_setting("ODSS_DIRECT_SIGMET_FRESHNESS_MINUTES", 60.0, 5.0, 360.0)
    except ValueError as exc:
        return _unavailable(str(exc))

    user_agent = os.environ.get("ODSS_VA_SIGMET_USER_AGENT", "").strip() or (
        "PilotDriven-ODSS/0.6.1 (operational-briefing service)"
    )
    own_client = client is None
    active_client = client or httpx.Client(timeout=timeout, follow_redirects=True)
    try:
        response = active_client.get(url, headers={"User-Agent": user_agent, "Accept": "text/plain"})
        response.raise_for_status()
        if len(response.content) > _MAX_HTML_BYTES:
            raise ValueError("GTS SIGMET bulletin exceeded the safety limit")
        bulletin = response.text
    except (httpx.HTTPError, ValueError) as exc:
        return _unavailable(f"{type(exc).__name__}: {str(exc)[:180]}")
    finally:
        if own_client:
            active_client.close()

    parsed = parse_gts_sigmet_bulletin(bulletin, retrieved_at, centre["provider"])
    issued_at = parsed.get("issued_at_utc")
    freshness_minutes: float | None = None
    freshness_status = "unknown"
    if issued_at:
        issued = datetime.fromisoformat(issued_at)
        freshness_minutes = abs((retrieved_at - issued).total_seconds()) / 60
        freshness_status = "fresh" if freshness_minutes <= freshness_limit else "stale"
    advisories = parsed["advisories"]
    valid_starts = [item["valid_from_utc"] for item in advisories]
    valid_ends = [item["valid_to_utc"] for item in advisories]
    return _govern_bom_snapshot({
        "schema_version": "1.0",
        "provider": centre["provider"],
        "source_url": url,
        "status": "available",
        "retrieved_at_utc": _iso(retrieved_at),
        "issued_at_utc": issued_at,
        "coverage_status": "issuing_centre_bulletin_only",
        "declared_fir_ids": list(centre["fir_ids"]),
        "coverage_start_utc": min(valid_starts) if valid_starts else None,
        "coverage_end_utc": max(valid_ends) if valid_ends else None,
        "freshness_status": freshness_status,
        "freshness_minutes": freshness_minutes,
        "advisory_count": len(advisories),
        "advisories": advisories,
        "parse_warnings": parsed["parse_warnings"],
    }, retrieved_at)


def live_gts_sigmet_snapshot(centre_key: str) -> dict[str, Any]:
    """Serve one governed GTS-centre receipt from the bounded shared cache."""
    cache_seconds = _cache_seconds()
    with _CACHE_LOCK:
        cached = _CACHE.get(centre_key)
        if cached and time.monotonic() - cached[0] < cache_seconds:
            return mark_snapshot_reused(cached[1])
    snapshot = fetch_gts_sigmet_snapshot(centre_key)
    with _CACHE_LOCK:
        _CACHE[centre_key] = (time.monotonic(), snapshot)
    return snapshot


def route_intersects_bbox(flight: dict[str, Any], bbox: dict[str, float]) -> bool:
    """Coarse bbox check deciding whether a direct source is route-relevant."""
    for waypoint in flight.get("route_waypoints") or []:
        try:
            latitude = float(waypoint["latitude"])
            longitude = float(waypoint["longitude"])
        except (KeyError, TypeError, ValueError):
            continue
        if (
            bbox["lat_min"] <= latitude <= bbox["lat_max"]
            and bbox["lon_min"] <= longitude <= bbox["lon_max"]
        ):
            return True
    return False


def route_intersects_australian_firs(flight: dict[str, Any]) -> bool:
    """Coarse bbox check deciding whether the BOM source is route-relevant."""
    return route_intersects_bbox(flight, AUSTRALIAN_FIR_BBOX)


def merge_direct_sigmet_snapshot(
    base: dict[str, Any],
    direct: dict[str, Any],
    hazard_codes: frozenset[str] | set[str],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Union direct advisories into the aggregate snapshot, fail-open never.

    Direct records are added only when the direct snapshot is available; its
    parse warnings and availability problems stay in the returned merge report
    (for the coverage ledger) and never contaminate the aggregate's own
    warnings — an unreachable direct source must not amber a covered review.
    """
    report = {
        "available": direct.get("status") == "available",
        "provider": direct.get("provider"),
        "retrieved_at_utc": direct.get("retrieved_at_utc"),
        "freshness_status": direct.get("freshness_status"),
        "declared_fir_ids": direct.get("declared_fir_ids"),
        "parse_warnings": list(direct.get("parse_warnings") or []),
        "advisories_offered": 0,
        "advisories_merged": 0,
        "advisories_duplicate": 0,
        "error": direct.get("error"),
    }
    if direct.get("status") != "available":
        return base, report
    selected = {str(code).upper() for code in hazard_codes}
    known_ids = {str(item.get("advisory_id")) for item in base.get("advisories") or []}
    merged = dict(base)
    merged_advisories = list(base.get("advisories") or [])
    for advisory in direct.get("advisories") or []:
        if str(advisory.get("hazard") or "").upper() not in selected:
            continue
        report["advisories_offered"] += 1
        if str(advisory.get("advisory_id")) in known_ids:
            report["advisories_duplicate"] += 1
            continue
        merged_advisories.append(advisory)
        report["advisories_merged"] += 1
    merged["advisories"] = merged_advisories
    merged["advisory_count"] = len(merged_advisories)
    existing_sources = list(base.get("merged_direct_sources") or [])
    merged["merged_direct_sources"] = existing_sources + [direct.get("provider")]
    return merged, report


__all__ = [
    "AUSTRALIAN_FIR_BBOX",
    "BOM_PROVIDER",
    "BOM_SIGMET_URL",
    "GTS_CENTRES",
    "fetch_bom_sigmet_snapshot",
    "fetch_gts_sigmet_snapshot",
    "live_bom_sigmet_snapshot",
    "live_gts_sigmet_snapshot",
    "merge_direct_sigmet_snapshot",
    "parse_bom_sigmet_page",
    "parse_gts_sigmet_bulletin",
    "parse_icao_sigmet_text",
    "route_intersects_australian_firs",
    "route_intersects_bbox",
]

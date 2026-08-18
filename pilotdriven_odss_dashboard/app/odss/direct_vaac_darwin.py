"""Governed direct advisory intake from the official Darwin VAAC.

Darwin VAAC is operated by the Australian Bureau of Meteorology and is the
responsible centre for Indonesia, Papua New Guinea and the southern
Philippines. Its VA ADVISORY bulletins are issued under WMO headings FVAUnn
with the office identifier ADRM. The Bureau's own web pages are not reachable
from every network, so the advisories are retrieved from the NOAA GTS text
mirror, which republishes the issued bulletins verbatim at one fixed HTTPS
origin. The mirror carries the latest bulletin per FVAU slot; each file is
the issued product text, not a portal rendering.

Like the Tokyo and Anchorage connectors this is source evidence separate from
the international SIGMET feed. Only advisories whose own DTG falls inside a
bounded flight-time window are retained, forecast snapshots stay snapshots
rather than being interpolated into a continuous boundary, and nothing here is
presented as global VAAC coverage. When a bulletin cannot be retrieved or its
identity verified, the snapshot says so and the review fails closed; an absent
advisory never becomes "no ash".
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


NOAA_GTS_ORIGIN = "https://tgftp.nws.noaa.gov"
NOAA_GTS_FV_PATH = "/data/raw/fv/"
# Darwin issues under FVAUnn with the routing identifier ADRM and signs the
# advisory "VAAC: DARWIN". Both are checked before a record is accepted.
DARWIN_ROUTING_ID = "ADRM"
DARWIN_VAAC_NAME = "DARWIN"
PROVIDER = "noaa-gts-darwin-vaa"

_MAX_TEXT_BYTES = 256 * 1024
_MAX_BULLETIN_FILES = 24
_CACHE_LOCK = Lock()
_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}

# Bulletin files for Darwin on the mirror: fvau<NN>.adrm..txt (lowercase in
# the index). Other centres' files (fvfe = Tokyo, fvak = Anchorage) and stale
# non-ADRM routings (ammc, nzkl) never match.
_DARWIN_FILE = re.compile(r"\bfvau\d{2}\.adrm\.\.txt\b")
_DARWIN_HEADER = re.compile(r"^FVAU\d{2}\s+ADRM\b", re.MULTILINE)
_DTG = re.compile(r"\b(\d{4})(\d{2})(\d{2})/(\d{2})(\d{2})Z?\b")


def _dtg_utc(value: str) -> datetime | None:
    """The advisory's own DTG field (yyyymmdd/hhmmZ) as an aware datetime."""
    match = _DTG.search(str(value or ""))
    if not match:
        return None
    year, month, day, hour, minute = map(int, match.groups())
    try:
        return datetime(year, month, day, hour, minute, tzinfo=timezone.utc)
    except ValueError:
        return None


def _bounded_text(response: httpx.Response) -> str:
    response.raise_for_status()
    raw = response.content
    if len(raw) > _MAX_TEXT_BYTES:
        raise ValueError("Darwin VAAC response exceeded the safety limit")
    return raw.decode("utf-8", errors="replace")


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
            "Accept": "text/plain, text/html",
        },
    ), True


def parse_darwin_gts_listing(index_html: str) -> list[dict[str, str]]:
    """Darwin bulletin files present in the mirror's directory index."""
    rows: list[dict[str, str]] = []
    seen: set[str] = set()
    for name in _DARWIN_FILE.findall(index_html or ""):
        if name in seen:
            continue
        seen.add(name)
        rows.append({
            "file": name,
            "vaa_url": f"{NOAA_GTS_ORIGIN}{NOAA_GTS_FV_PATH}{name}",
        })
    rows.sort(key=lambda row: row["file"])
    return rows[:_MAX_BULLETIN_FILES]


def parse_darwin_vaac_advisory(
    text: str,
    metadata: dict[str, Any],
) -> dict[str, Any]:
    """One Darwin VA ADVISORY in the shared snapshot shape."""
    if not str(text or "").strip():
        raise ValueError("Darwin VAAC bulletin carried no product text")
    # Identity is verified from the bulletin itself, not from the file name
    # that fetched it: the WMO routing line must be FVAUnn ADRM and the
    # advisory must sign itself VAAC: DARWIN. A relayed or mislabelled record
    # cannot enter as Darwin.
    if not _DARWIN_HEADER.search(text):
        raise ValueError("Darwin VAAC bulletin did not carry an FVAU ADRM heading")
    fields = advisory_fields(text)
    if fields.get("VAAC", "").strip().upper() != DARWIN_VAAC_NAME:
        raise ValueError("Darwin VAAC advisory identity could not be verified")
    issued_at = _dtg_utc(fields.get("DTG", ""))
    if issued_at is None:
        raise ValueError("Darwin VAAC advisory carried no readable DTG")
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
        "issued_at_utc": advisory_iso(issued_at),
        "provider": PROVIDER,
        "vaac": fields.get("VAAC"),
        "volcano": fields.get("VOLCANO"),
        "area": fields.get("AREA"),
        "advisory_number": fields.get("ADVISORY NR"),
        "information_source": fields.get("INFO SOURCE"),
        "eruption_details": fields.get("ERUPTION DETAILS"),
        "phases": phases,
        "next_advisory": fields.get("NXT ADVISORY"),
        # A terminating advisory ("VA HAS NOW DISSIPATED ... ADVISORY
        # TERMINATED") is the update a printed CFP cannot carry. The remark is
        # retained verbatim so termination is visible as an official statement
        # rather than flattened into an absence.
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
        scope="darwin_vaac_direct_advisory",
        completeness_status=snapshot.get("status"),
    )


def fetch_darwin_vaac_snapshot(
    flight: dict[str, Any],
    *,
    client: httpx.Client | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    retrieved_at = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    list_url = f"{NOAA_GTS_ORIGIN}{NOAA_GTS_FV_PATH}"
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
        rows = parse_darwin_gts_listing(
            _bounded_text(active_client.get(list_url))
        )
        advisories: list[dict[str, Any]] = []
        listing_issue_times: list[str] = []
        for row in rows:
            try:
                advisory = parse_darwin_vaac_advisory(
                    _bounded_text(active_client.get(row["vaa_url"])),
                    row,
                )
            except (httpx.HTTPError, ValueError) as exc:
                errors.append({
                    "source_url": row["vaa_url"],
                    "error": f"{type(exc).__name__}: {str(exc)[:160]}",
                })
                continue
            listing_issue_times.append(advisory["issued_at_utc"])
            issued = advisory_utc(advisory["issued_at_utc"])
            if issued is not None and window_start <= issued <= window_end:
                advisories.append(advisory)
        listing_issue_times.sort()
        return _govern({
            "schema_version": "1.0",
            "status": "available" if not errors else "partial",
            "provider": PROVIDER,
            "source_url": list_url,
            "retrieved_at_utc": advisory_iso(retrieved_at),
            "coverage_status": "darwin_vaac_area_direct_advisories",
            "requested_issue_window_start_utc": advisory_iso(window_start),
            "requested_issue_window_end_utc": advisory_iso(window_end),
            "listing_earliest_utc": listing_issue_times[0] if listing_issue_times else None,
            "listing_latest_utc": listing_issue_times[-1] if listing_issue_times else None,
            "advisory_count": len(advisories),
            "advisories": advisories,
            "errors": errors,
            "source_note": (
                "Official Darwin VAAC VA ADVISORY evidence for its area only, "
                "retrieved as issued FVAU/ADRM bulletin text from the NOAA GTS "
                "mirror. The mirror carries the latest bulletin per slot, so "
                "coverage is the current advisory picture, not an archive. "
                "Forecast polygons remain official snapshots and are not "
                "interpolated into a continuous hazard boundary."
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


def live_darwin_vaac_snapshot(flight: dict[str, Any]) -> dict[str, Any]:
    window = advisory_flight_window(flight)
    cache_key = "|".join(advisory_iso(value) or "" for value in window) if window else "missing"
    seconds = advisory_cache_seconds()
    now_monotonic = time.monotonic()
    with _CACHE_LOCK:
        cached = _CACHE.get(cache_key)
        if cached and now_monotonic - cached[0] < seconds:
            return mark_snapshot_reused(cached[1])
        snapshot = fetch_darwin_vaac_snapshot(flight)
        _CACHE[cache_key] = (now_monotonic, snapshot)
        return deepcopy(snapshot)


__all__ = [
    "DARWIN_ROUTING_ID",
    "DARWIN_VAAC_NAME",
    "NOAA_GTS_FV_PATH",
    "NOAA_GTS_ORIGIN",
    "PROVIDER",
    "fetch_darwin_vaac_snapshot",
    "live_darwin_vaac_snapshot",
    "parse_darwin_gts_listing",
    "parse_darwin_vaac_advisory",
]

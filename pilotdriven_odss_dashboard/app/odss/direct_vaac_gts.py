"""Governed direct advisory intake for every ICAO VAAC via the NOAA GTS mirror.

The nine ICAO Volcanic Ash Advisory Centres all transmit their VA ADVISORY
bulletins on the GTS under fixed WMO headings, and the NOAA text mirror
republishes the latest issued bulletin per slot verbatim at one HTTPS origin.
This connector generalises the Darwin pattern (boss's VAA round, 18 Aug) to
the full centre table so a deployment reaches all nine without a portal
scrape or an authenticated feed.

Two properties carry the trust story:

- Identity is verified from the bulletin itself — the WMO routing line and
  the advisory's own ``VAAC:`` signature must both match the centre — never
  from the file name that fetched it.
- The mirror keeps the last bulletin per slot forever (2013-era Anchorage
  bulletins are still served), so every advisory is bounded by its own DTG
  against the flight window and the snapshot carries freshness receipts. A
  stale bulletin is dropped; an absent advisory never becomes "no ash".
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
PROVIDER = "noaa-gts-vaa"

_MAX_TEXT_BYTES = 256 * 1024
_MAX_BULLETIN_FILES_PER_CENTRE = 24
_CACHE_LOCK = Lock()
_CACHE: dict[str, tuple[float, dict[str, dict[str, Any]]]] = {}

# One row per ICAO VAAC: the mirror's file slots and the WMO heading that a
# bulletin must carry. Slots transcribed from the live mirror index on
# 30 Aug 2026; file names are lowercase ``<heading>.<routing>..txt`` and the
# ``..txt`` suffix keeps chart/segment variants (``.par.t2``, ``.vaa.ak1``)
# out so each slot is the plain issued product text.
GTS_CENTRES: dict[str, dict[str, Any]] = {
    "ANCHORAGE": {
        "file": re.compile(r"\bfvak\d{2}\.(?:panc|pawu)\.\.txt\b"),
        "header": re.compile(r"^FVAK\d{2}\s+(?:PANC|PAWU)\b", re.MULTILINE),
    },
    "BUENOS AIRES": {
        # SABM reuses its FVXX slots for WINTEM tables (seen live 30 Aug 2026),
        # so only the FVAG heading is a Buenos Aires VA ADVISORY slot.
        "file": re.compile(r"\bfvag\d{2}\.sabm\.\.txt\b"),
        "header": re.compile(r"^FVAG\d{2}\s+SABM\b", re.MULTILINE),
    },
    "DARWIN": {
        "file": re.compile(r"\bfvau\d{2}\.(?:adrm|ammc)\.\.txt\b"),
        "header": re.compile(r"^FVAU\d{2}\s+(?:ADRM|AMMC)\b", re.MULTILINE),
    },
    "LONDON": {
        "file": re.compile(r"\bfvxx\d{2}\.egrr\.\.txt\b"),
        "header": re.compile(r"^FVXX\d{2}\s+EGRR\b", re.MULTILINE),
    },
    "MONTREAL": {
        "file": re.compile(r"\bfvcn\d{2}\.cwao\.\.txt\b"),
        "header": re.compile(r"^FVCN\d{2}\s+CWAO\b", re.MULTILINE),
    },
    "TOKYO": {
        "file": re.compile(r"\bfvfe\d{2}\.rjtd\.\.txt\b"),
        "header": re.compile(r"^FVFE\d{2}\s+RJTD\b", re.MULTILINE),
    },
    "TOULOUSE": {
        "file": re.compile(r"\bfvxx\d{2}\.lfpw\.\.txt\b"),
        "header": re.compile(r"^FVXX\d{2}\s+LFPW\b", re.MULTILINE),
    },
    "WASHINGTON": {
        "file": re.compile(r"\bfvxx\d{2}\.knes\.\.txt\b"),
        "header": re.compile(r"^FVXX\d{2}\s+KNES\b", re.MULTILINE),
    },
    "WELLINGTON": {
        # The mirror's fvau..nzkl slots hold relayed DARWIN advisories (seen
        # live, 2019-era), so only FVPS headings are Wellington's own issues.
        "file": re.compile(r"\bfvps\d{2}\.nzkl\.\.txt\b"),
        "header": re.compile(r"^FVPS\d{2}\s+NZKL\b", re.MULTILINE),
    },
}

_DTG = re.compile(r"\b(\d{4})(\d{2})(\d{2})/(\d{2})(\d{2})Z?\b")
# "PSN: S0832 E12246" — degrees and minutes, hemisphere-prefixed, as printed
# in every VA ADVISORY. Seconds are never printed; nothing is interpolated.
_PSN = re.compile(
    r"\b([NS])\s?(\d{2})(\d{2})\s+([EW])\s?(\d{3})(\d{2})\b"
)


def parse_advisory_psn(value: str) -> dict[str, float] | None:
    """The advisory's printed volcano position as decimal degrees."""
    match = _PSN.search(str(value or ""))
    if not match:
        return None
    lat_hem, lat_deg, lat_min, lon_hem, lon_deg, lon_min = match.groups()
    latitude = int(lat_deg) + int(lat_min) / 60.0
    longitude = int(lon_deg) + int(lon_min) / 60.0
    if int(lat_min) >= 60 or int(lon_min) >= 60 or latitude > 90 or longitude > 180:
        return None
    if lat_hem == "S":
        latitude = -latitude
    if lon_hem == "W":
        longitude = -longitude
    return {"latitude": round(latitude, 4), "longitude": round(longitude, 4)}


def _dtg_utc(value: str) -> datetime | None:
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
        raise ValueError("GTS mirror response exceeded the safety limit")
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


def parse_gts_listing(index_html: str, centre: str) -> list[dict[str, str]]:
    """The centre's bulletin files present in the mirror's directory index."""
    pattern = GTS_CENTRES[centre]["file"]
    rows: list[dict[str, str]] = []
    seen: set[str] = set()
    for name in pattern.findall(index_html or ""):
        if name in seen:
            continue
        seen.add(name)
        rows.append({
            "file": name,
            "vaa_url": f"{NOAA_GTS_ORIGIN}{NOAA_GTS_FV_PATH}{name}",
        })
    rows.sort(key=lambda row: row["file"])
    return rows[:_MAX_BULLETIN_FILES_PER_CENTRE]


def parse_gts_vaac_advisory(
    text: str,
    metadata: dict[str, Any],
    centre: str,
) -> dict[str, Any]:
    """One VA ADVISORY in the shared snapshot shape, identity-checked."""
    if not str(text or "").strip():
        raise ValueError(f"{centre} VAAC bulletin carried no product text")
    if not GTS_CENTRES[centre]["header"].search(text):
        raise ValueError(
            f"{centre} VAAC bulletin did not carry its expected WMO heading"
        )
    fields = advisory_fields(text)
    if fields.get("VAAC", "").strip().upper() != centre:
        raise ValueError(f"{centre} VAAC advisory identity could not be verified")
    issued_at = _dtg_utc(fields.get("DTG", ""))
    if issued_at is None:
        raise ValueError(f"{centre} VAAC advisory carried no readable DTG")
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
    colour = (
        fields.get("AVIATION COLOUR CODE")
        or fields.get("AVIATION COLOR CODE")
        or None
    )
    return {
        **metadata,
        "issued_at_utc": advisory_iso(issued_at),
        "provider": PROVIDER,
        "centre": centre,
        "vaac": fields.get("VAAC"),
        "volcano": fields.get("VOLCANO"),
        "volcano_position": parse_advisory_psn(fields.get("PSN", "")),
        "aviation_colour_code": str(colour).strip().upper() if colour else None,
        "area": fields.get("AREA"),
        "advisory_number": fields.get("ADVISORY NR"),
        "information_source": fields.get("INFO SOURCE"),
        "eruption_details": fields.get("ERUPTION DETAILS"),
        "phases": phases,
        "next_advisory": fields.get("NXT ADVISORY"),
        "remarks": fields.get("RMK"),
        "raw_sha256": sha256(text.encode("utf-8")).hexdigest(),
    }


def _govern(snapshot: dict[str, Any], retrieved_at: datetime, centre: str) -> dict[str, Any]:
    seconds = advisory_cache_seconds()
    return govern_snapshot(
        snapshot,
        now=retrieved_at,
        refresh_after_seconds=seconds,
        expires_after_seconds=seconds * 4,
        scope=f"gts_vaac_direct_advisory_{centre.lower().replace(' ', '_')}",
        completeness_status=snapshot.get("status"),
    )


def fetch_gts_vaac_snapshots(
    flight: dict[str, Any],
    *,
    client: httpx.Client | None = None,
    now: datetime | None = None,
    centres: tuple[str, ...] | None = None,
) -> dict[str, dict[str, Any]]:
    """One governed snapshot per centre from a single mirror pass.

    The directory index is fetched once and each bulletin file once; every
    centre then carries its own snapshot, freshness receipt and errors, so a
    slot that cannot be read degrades that centre alone.
    """
    retrieved_at = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    list_url = f"{NOAA_GTS_ORIGIN}{NOAA_GTS_FV_PATH}"
    wanted = tuple(centres or tuple(GTS_CENTRES))
    window = advisory_flight_window(flight)

    def unavailable(centre: str, error: str) -> dict[str, Any]:
        return _govern({
            "schema_version": "1.0",
            "status": "unavailable",
            "provider": PROVIDER,
            "source_url": list_url,
            "retrieved_at_utc": advisory_iso(retrieved_at),
            "coverage_status": "unavailable",
            "advisories": [],
            "errors": [{"error": error}],
        }, retrieved_at, centre)

    if window is None:
        return {
            centre: unavailable(centre, "Flight timing is unavailable")
            for centre in wanted
        }
    window_start, window_end = window
    active_client, own_client = _client(client)
    try:
        try:
            index_html = _bounded_text(active_client.get(list_url))
        except (httpx.HTTPError, ValueError) as exc:
            error = f"{type(exc).__name__}: {str(exc)[:160]}"
            return {centre: unavailable(centre, error) for centre in wanted}

        snapshots: dict[str, dict[str, Any]] = {}
        text_cache: dict[str, str | Exception] = {}
        for centre in wanted:
            rows = parse_gts_listing(index_html, centre)
            advisories: list[dict[str, Any]] = []
            errors: list[dict[str, str]] = []
            listing_issue_times: list[str] = []
            next_advisories: list[str] = []
            for row in rows:
                cached = text_cache.get(row["file"])
                if cached is None:
                    try:
                        cached = _bounded_text(active_client.get(row["vaa_url"]))
                    except (httpx.HTTPError, ValueError) as exc:
                        cached = exc
                    text_cache[row["file"]] = cached
                if isinstance(cached, Exception):
                    errors.append({
                        "source_url": row["vaa_url"],
                        "error": f"{type(cached).__name__}: {str(cached)[:160]}",
                    })
                    continue
                try:
                    advisory = parse_gts_vaac_advisory(cached, row, centre)
                except ValueError as exc:
                    errors.append({
                        "source_url": row["vaa_url"],
                        "error": f"{type(exc).__name__}: {str(exc)[:160]}",
                    })
                    continue
                listing_issue_times.append(advisory["issued_at_utc"])
                issued = advisory_utc(advisory["issued_at_utc"])
                if issued is not None and window_start <= issued <= window_end:
                    advisories.append(advisory)
                    if advisory.get("next_advisory"):
                        next_advisories.append(str(advisory["next_advisory"]))
            listing_issue_times.sort()
            snapshots[centre] = _govern({
                "schema_version": "1.0",
                "status": "available" if not errors else "partial",
                "provider": PROVIDER,
                "source_url": list_url,
                "retrieved_at_utc": advisory_iso(retrieved_at),
                "coverage_status": (
                    f"{centre.lower().replace(' ', '_')}_vaac_gts_mirror_advisories"
                ),
                "requested_issue_window_start_utc": advisory_iso(window_start),
                "requested_issue_window_end_utc": advisory_iso(window_end),
                "listing_earliest_utc": listing_issue_times[0] if listing_issue_times else None,
                "listing_latest_utc": listing_issue_times[-1] if listing_issue_times else None,
                "advisory_count": len(advisories),
                "advisories": advisories,
                "next_advisory_due": sorted(next_advisories)[-1] if next_advisories else None,
                "errors": errors,
                "source_note": (
                    f"Official {centre} VAAC VA ADVISORY evidence retrieved as "
                    "issued bulletin text from the NOAA GTS mirror. The mirror "
                    "carries the latest bulletin per slot, so only advisories "
                    "whose own DTG falls inside the flight window are retained "
                    "— a slot's stale historic bulletin is never current "
                    "coverage, and an absent advisory is never 'no ash'."
                ),
            }, retrieved_at, centre)
        return snapshots
    finally:
        if own_client:
            active_client.close()


def live_gts_vaac_snapshots(
    flight: dict[str, Any],
    centres: tuple[str, ...] | None = None,
) -> dict[str, dict[str, Any]]:
    window = advisory_flight_window(flight)
    wanted = tuple(centres or tuple(GTS_CENTRES))
    cache_key = "|".join(
        [advisory_iso(value) or "" for value in window] if window else ["missing"]
    ) + "|" + ",".join(wanted)
    seconds = advisory_cache_seconds()
    now_monotonic = time.monotonic()
    with _CACHE_LOCK:
        cached = _CACHE.get(cache_key)
        if cached and now_monotonic - cached[0] < seconds:
            return {
                centre: mark_snapshot_reused(snapshot)
                for centre, snapshot in cached[1].items()
            }
        snapshots = fetch_gts_vaac_snapshots(flight, centres=wanted)
        _CACHE[cache_key] = (now_monotonic, snapshots)
        return deepcopy(snapshots)


__all__ = [
    "GTS_CENTRES",
    "NOAA_GTS_FV_PATH",
    "NOAA_GTS_ORIGIN",
    "PROVIDER",
    "fetch_gts_vaac_snapshots",
    "live_gts_vaac_snapshots",
    "parse_advisory_psn",
    "parse_gts_listing",
    "parse_gts_vaac_advisory",
]

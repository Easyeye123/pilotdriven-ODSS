"""Route-aware tropical cyclone review.

Mirrors the volcanic-ash review: the same NOAA AWC international SIGMET feed,
the same deterministic route x time x flight-level evaluator, and the same
fail-closed discipline. Nothing here estimates a cyclone position; a segment is
only reported as affected when an official TC SIGMET polygon, its validity
window, and its flight-level band all intersect the planned route.

Forecast-track reasoning (advisory position/movement over time) is deliberately
out of scope: the AWC SIGMET feed carries current active hazard areas, not a
forecast archive, so projecting a track forward would be an estimate.
"""

from __future__ import annotations

from hashlib import sha256
import os
import re
from typing import Any

from .vaa import evaluate_vaa, live_vaa_snapshot

TC_HAZARD_CODE = "TC"


def extract_embedded_tc(pages: list[str]) -> dict[str, Any]:
    """Extract the CFP's tropical-cyclone source statement without interpreting it."""
    for page_number, page in enumerate(pages, start=1):
        match = re.search(r"TROPICAL\s+CYCLONE\s+SIGMETS?\s*:", page, re.IGNORECASE)
        if not match:
            continue
        tail = page[match.end():]
        lines: list[str] = []
        for raw_line in tail.splitlines():
            line = " ".join(raw_line.split())
            if not line:
                continue
            if lines and re.match(
                r"^(?:DESTINATION|VOLCANIC\s+ASH|SIGMETS?|AIRMETS?|NOTAMS?|SPACE\s+WEATHER)\b",
                line,
                re.IGNORECASE,
            ):
                break
            lines.append(line)
            if len(lines) >= 20:
                break
        raw_excerpt = "\n".join(lines).strip()
        unavailable = bool(
            re.search(
                r"\b(?:NO\s+(?:WX|WEATHER)\s+DATA\s+AVAILABLE|DATA\s+NOT\s+AVAILABLE)\b",
                raw_excerpt,
                re.IGNORECASE,
            )
        )
        return {
            "status": "unavailable" if unavailable else "present",
            "source_page": page_number,
            "raw_excerpt": raw_excerpt,
            "raw_sha256": sha256(raw_excerpt.encode("utf-8")).hexdigest(),
        }
    return {
        "status": "not_present",
        "source_page": None,
        "raw_excerpt": "",
        "raw_sha256": None,
    }


def _disabled_snapshot() -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "provider": None,
        "hazard_code": TC_HAZARD_CODE,
        "source_url": None,
        "status": "disabled",
        "coverage_status": "disabled",
        "freshness_status": "unknown",
        "advisories": [],
    }


def _unsupported_snapshot(configured_source: str) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "provider": configured_source,
        "hazard_code": TC_HAZARD_CODE,
        "source_url": None,
        "status": "unavailable",
        "coverage_status": "unavailable",
        "freshness_status": "unknown",
        "advisories": [],
        "error": "Unsupported ODSS_TC_SIGMET_SOURCE setting",
    }


def assess_tropical_cyclone(
    flight: dict[str, Any],
    pages: list[str],
    *,
    snapshot: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Assess planned route against active tropical cyclone SIGMETs."""
    embedded = extract_embedded_tc(pages)
    configured_source = os.environ.get("ODSS_TC_SIGMET_SOURCE", "awc").strip().lower()
    if snapshot is None:
        if configured_source in {"", "disabled", "off", "none"}:
            snapshot = _disabled_snapshot()
        elif configured_source == "awc":
            snapshot = live_vaa_snapshot(TC_HAZARD_CODE)
        else:
            snapshot = _unsupported_snapshot(configured_source)
    review = evaluate_vaa(
        flight,
        snapshot,
        embedded,
        hazard_label="tropical_cyclone",
        default_advisory_id="TC-SIGMET",
    )
    flight["tropical_cyclone_review"] = review
    return review


__all__ = [
    "TC_HAZARD_CODE",
    "assess_tropical_cyclone",
    "extract_embedded_tc",
]

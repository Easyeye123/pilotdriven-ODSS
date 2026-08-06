"""Route-aware review of international SIGMET hazards other than VA and TC.

VA and TC keep their dedicated review paths because they also require
responsible-centre advisory coverage. This module uses the same single,
governed NOAA AWC receipt for thunderstorms, turbulence, icing, mountain wave,
dust/sand storms, and radiological cloud.
"""

from __future__ import annotations

import os
from typing import Any

from .direct_sigmet import (
    live_bom_sigmet_snapshot,
    merge_direct_sigmet_snapshot,
    route_intersects_australian_firs,
)
from .vaa import evaluate_vaa, filter_awc_snapshot, live_awc_snapshot


GENERAL_SIGMET_HAZARDS = frozenset({
    "DS",
    "ICE",
    "MTW",
    "RDOACT CLD",
    "SS",
    "TS",
    "TURB",
})


def _disabled_snapshot() -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "provider": None,
        "hazard_code": "GENERAL",
        "source_url": None,
        "status": "disabled",
        "coverage_status": "disabled",
        "freshness_status": "unknown",
        "advisories": [],
        "parse_warnings": [],
    }


def _unsupported_snapshot(configured_source: str) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "provider": configured_source,
        "hazard_code": "GENERAL",
        "source_url": None,
        "status": "unavailable",
        "coverage_status": "unavailable",
        "freshness_status": "unknown",
        "advisories": [],
        "parse_warnings": [],
        "error": "Unsupported ODSS_SIGMET_SOURCE setting",
    }


def assess_significant_weather(
    flight: dict[str, Any],
    *,
    snapshot: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Assess route, time, and level against active official SIGMET geometry."""
    configured_source = os.environ.get("ODSS_SIGMET_SOURCE", "awc").strip().lower()
    if snapshot is None:
        if configured_source in {"", "disabled", "off", "none"}:
            snapshot = _disabled_snapshot()
        elif configured_source == "awc":
            snapshot = live_awc_snapshot()
        else:
            snapshot = _unsupported_snapshot(configured_source)

    projected = filter_awc_snapshot(snapshot, GENERAL_SIGMET_HAZARDS)

    # Direct authority-of-record sources on top of the AWC aggregate (boss
    # instruction 04.08.26: NOAA, JMA, BOM, HKO). BOM publishes machine-readable
    # raw text and is merged when the route touches the Australian FIRs; JMA and
    # HKO publish no machine-readable general-SIGMET product, which the ledger
    # records without inventing an adapter. A direct source can only ADD held
    # records — its unavailability never ambers a review the aggregate covers.
    configured_direct = {
        token.strip().lower()
        for token in os.environ.get("ODSS_DIRECT_SIGMET_SOURCES", "bom").split(",")
        if token.strip()
    }
    bom_report: dict[str, Any] | None = None
    bom_route_relevant = route_intersects_australian_firs(flight)
    if "bom" in configured_direct and bom_route_relevant and snapshot.get("status") != "disabled":
        projected, bom_report = merge_direct_sigmet_snapshot(
            projected,
            live_bom_sigmet_snapshot(),
            GENERAL_SIGMET_HAZARDS,
        )

    review = evaluate_vaa(
        flight,
        projected,
        hazard_label="sigmet",
        default_advisory_id="SIGMET",
    )
    review["supported_hazard_codes"] = sorted(GENERAL_SIGMET_HAZARDS)
    review["coverage_ledger"] = {
        "active_international_sigmet": {
            "available": projected.get("provider") == "noaa-awc-international-sigmet",
            "provider": projected.get("provider"),
            "retrieved_at_utc": projected.get("retrieved_at_utc"),
            "freshness_status": projected.get("freshness_status"),
            "declared_scope": projected.get("coverage_status"),
            "future_flight_archive": False,
        },
        "direct_bom_australia_sigmet": (
            {
                **(bom_report or {}),
                "configuration_status": "enabled",
                "route_relevant": True,
                "review_required_when_missing": False,
            }
            if bom_report is not None
            else {
                "available": False,
                "provider": None,
                "configuration_status": (
                    "disabled"
                    if "bom" not in configured_direct
                    else "not_route_relevant"
                ),
                "route_relevant": bom_route_relevant,
                "review_required_when_missing": False,
            }
        ),
        # No public machine-readable general-SIGMET text product exists for
        # these authorities (verified 07.08.26): JMA publishes chart imagery
        # (QGMA98 series) and HKO an informational page. Their FIRs (RJJJ,
        # VHHK) are carried by the AWC aggregate above; JMA remains the direct
        # VA authority through the Tokyo VAAC connector.
        "direct_jma_fukuoka_sigmet": {
            "available": False,
            "provider": None,
            "configuration_status": "no_public_machine_readable_product",
            "aggregate_carries_fir": "RJJJ",
            "review_required_when_missing": False,
        },
        "direct_hko_hong_kong_sigmet": {
            "available": False,
            "provider": None,
            "configuration_status": "no_public_machine_readable_product",
            "aggregate_carries_fir": "VHHK",
            "review_required_when_missing": False,
        },
    }
    review["clean_current_feed_no_match"] = bool(
        review.get("status") == "review_required"
        and projected.get("status") == "available"
        and projected.get("freshness_status") == "fresh"
        and not projected.get("parse_warnings")
        and not review.get("matches")
    )
    flight["sigmet_review"] = review
    return review


__all__ = [
    "GENERAL_SIGMET_HAZARDS",
    "assess_significant_weather",
]

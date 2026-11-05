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
    AUSTRALIAN_FIR_BBOX,
    GTS_CENTRES,
    live_bom_sigmet_snapshot,
    live_gts_sigmet_snapshot,
    merge_direct_sigmet_snapshot,
    route_intersects_bbox,
)
from .source_status import answer_currency
from .vaa import evaluate_vaa, filter_awc_snapshot, live_awc_snapshot
from .volcanic_check import VA_SIGMET_MAX_VALIDITY

# The evaluator's reasons that say the route/time/level comparison did not run.
_ROUTE_NOT_EVALUATED = frozenset({
    "route_geometry_unavailable",
    "route_timing_unavailable",
    "flight_level_unavailable",
    "flight_level_change_unresolved",
    "route_timing_non_monotonic",
    "advisory_time_unavailable",
    "advisory_level_unavailable",
    "advisory_geometry_invalid",
})


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
    # instruction 04.08.26: NOAA, JMA, BOM, HKO). BOM publishes raw text on its
    # own site; JMA (RJTD) and HKO (VHHH) publish their issued bulletins as raw
    # text on NOAA's GTS mirror, since their own pages carry imagery only. Each
    # source is consulted when the route touches its region, and can only ADD
    # held records — unavailability never ambers a review the aggregate covers.
    configured_direct = {
        token.strip().lower()
        for token in os.environ.get("ODSS_DIRECT_SIGMET_SOURCES", "bom,jma,hko").split(",")
        if token.strip()
    }
    direct_reports: dict[str, dict[str, Any] | None] = {}
    direct_relevance: dict[str, bool] = {}
    direct_fetchers = {
        "bom": (AUSTRALIAN_FIR_BBOX, live_bom_sigmet_snapshot),
        "jma": (GTS_CENTRES["jma"]["bbox"], lambda: live_gts_sigmet_snapshot("jma")),
        "hko": (GTS_CENTRES["hko"]["bbox"], lambda: live_gts_sigmet_snapshot("hko")),
    }
    for source_key, (bbox, fetcher) in direct_fetchers.items():
        relevant = route_intersects_bbox(flight, bbox)
        direct_relevance[source_key] = relevant
        direct_reports[source_key] = None
        if source_key in configured_direct and relevant and snapshot.get("status") != "disabled":
            projected, direct_reports[source_key] = merge_direct_sigmet_snapshot(
                projected,
                fetcher(),
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
        **{
            ledger_key: (
                {
                    **(direct_reports[source_key] or {}),
                    "configuration_status": "enabled",
                    "route_relevant": True,
                    "review_required_when_missing": False,
                }
                if direct_reports[source_key] is not None
                else {
                    "available": False,
                    "provider": None,
                    "configuration_status": (
                        "disabled"
                        if source_key not in configured_direct
                        else "not_route_relevant"
                    ),
                    "route_relevant": direct_relevance[source_key],
                    "review_required_when_missing": False,
                }
            )
            for source_key, ledger_key in (
                ("bom", "direct_bom_australia_sigmet"),
                ("jma", "direct_jma_fukuoka_sigmet"),
                ("hko", "direct_hko_hong_kong_sigmet"),
            )
        },
    }
    # ITEM2-VOLCANIC (24 Oct 2026): a clean receipt also needs an answer that
    # can speak for this flight - retrieved no later than arrival and no
    # earlier than the longest SIGMET validity (6 h, VA/TC) before departure -
    # a completed route/time/level evaluation, and no SIGMET on the route that
    # expires before the flight passes. A historical analysis re-run weeks
    # later used to read "checked, no match" from today's SIGMETs.
    currency, _ = answer_currency(
        projected.get("retrieved_at_utc"),
        flight,
        lead=VA_SIGMET_MAX_VALIDITY,
    )
    evaluated = not (
        {str(code) for code in review.get("reason_codes") or []}
        & _ROUTE_NOT_EVALUATED
    )
    review["clean_current_feed_no_match"] = bool(
        review.get("status") == "review_required"
        and projected.get("status") == "available"
        and projected.get("freshness_status") == "fresh"
        and not projected.get("parse_warnings")
        and not review.get("matches")
        and not review.get("expiring_on_route")
        and currency is None
        and evaluated
    )
    review["feed_currency"] = currency
    flight["sigmet_review"] = review
    return review


__all__ = [
    "GENERAL_SIGMET_HAZARDS",
    "assess_significant_weather",
]

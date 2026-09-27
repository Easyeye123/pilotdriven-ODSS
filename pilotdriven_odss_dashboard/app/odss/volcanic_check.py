"""One composed volcanic-ash check for every surface (VOLCANIC-CHECK-436).

David, 24 Sep 2026 06:51: "I also recall that I asked you to make sure the AI goes thru the checklist of items it must
perform for each flight. That list has disappeared? What happens next time say to the Pacific with the volcano
advisories?"

PD holds four volcanic-ash sources for a flight, and each surface used to read a different subset of them:

1. the OFP's own "Volcanic Ash SIGMETs:" section (printed with messages, printed as "no data", or not printed);
2. the OFP's volcano notices (NOTAM / ASHTAM records naming a volcano);
3. the live international VA SIGMET feed, evaluated against the filed route, time and planned level;
4. the route-responsible VAACs (ICAO Doc 9766 areas) and the advisories each one returned.

The independent review of release 436 found the PDF's page-6 source line saying "every listed source record is held"
while every responsible VAAC and the feed were unreached (it listed only OFP sources), page 5 printing the same generic
sentence whether the live sources were off, failed or answered with nothing, the page-1 tile reading "HELD" from a
volcano NOTAM alone and "NO DATA" beside a feed SIGMET crossing the route, and the dashboard's VAAC row green while the
route's VAAC responsibility was unsettled - every Pacific crossing leaves points in the Kuril/Kamchatka band and the NE
Pacific that the encoded Doc 9766 table does not assign.

This module composes the four sources once, in that fixed order, into one state and one sentence. Every surface prints
these composed values; none re-derives them. The rules (no flight, route, centre or volcano is special-cased):

- FOUND: the feed's route/time/level evaluation verified an intersection;
- NOT QUERIED: no live source was configured (the feed is disabled and no responsible centre is mounted);
- UNAVAILABLE: live sources were configured but none answered;
- CHECKED · NO MATCH: only when the feed answered with no crossing, every responsible VAAC answered, the route's
  responsibility is settled, no direct advisory is held and the OFP prints no volcanic record - the one case in which
  every source was reached and none holds anything to assess;
- UNRESOLVED in every other case: partial reach, unsettled responsibility, a stale feed, or
  held material whose route applicability is not assessed (direct VAAC advisories, OFP VA SIGMETs, volcano notices).

Missing evidence is never NIL: an unreached source is named as not reached, a disabled one as not queried.
"""
from __future__ import annotations

from typing import Any

CHECK_SCHEMA = "volcanic-ash-check-v1"

_FEED_REACHED_REASONS = frozenset({"coverage_not_complete_for_flight", "cfp_weather_data_unavailable", "verified_no_intersection"})


def _clean(value: Any) -> str:
    return " ".join(str(value or "").split())


def _names(values: list[str]) -> str:
    seen = list(dict.fromkeys(value for value in values if value))
    return ", ".join(seen)


def _feed(va_sigmet_review: dict[str, Any]) -> tuple[str, list[str]]:
    """The live VA SIGMET feed's state: affected, reached, stale, not_reached or not_queried."""
    status = str(va_sigmet_review.get("status") or "").lower()
    reasons = {str(code) for code in va_sigmet_review.get("reason_codes") or []}
    matches = [
        _clean(match.get("advisory_id") or match.get("id") or match.get("fir_id")) or "ID unresolved"
        for match in va_sigmet_review.get("matches") or []
        if isinstance(match, dict)
    ]
    if status == "affected" or matches:
        return "affected", list(dict.fromkeys(matches))
    if not va_sigmet_review or status == "not_assessed" or "source_disabled" in reasons:
        return "not_queried", []
    if "source_unavailable" in reasons:
        return "not_reached", []
    if status == "not_applicable":
        return "reached", []
    if reasons and reasons <= _FEED_REACHED_REASONS:
        return "reached", []
    if {"source_stale", "source_records_incomplete"} & reasons:
        return "stale", []
    return "not_reached", []


def volcanic_ash_check(
    flight: dict[str, Any],
    va_sigmet_review: dict[str, Any] | None,
    direct_review: dict[str, Any] | None,
    cfp_advisories: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    va_sigmet_review = va_sigmet_review or {}
    direct_review = direct_review or {}
    cfp_advisories = [row for row in cfp_advisories or [] if isinstance(row, dict)]

    embedded = str((va_sigmet_review.get("embedded_source") or {}).get("status") or "").lower()
    ofp_sigmets = [row for row in cfp_advisories if row.get("advisory_kind") == "VA_SIGMET"]
    ofp_notices = [row for row in cfp_advisories if row.get("advisory_kind") == "CFP_VAA_NOTICE"]
    if ofp_sigmets or embedded == "present":
        ofp_section = "printed"
    elif embedded == "unavailable":
        ofp_section = "no_data"
    else:
        ofp_section = "not_printed"
    sigmet_names = [_clean(row.get("volcano")) or _clean(row.get("name")) for row in ofp_sigmets]
    notice_names = [
        " ".join(part for part in (_clean(row.get("volcano")), _clean(row.get("notam_id"))) if part)
        for row in ofp_notices
    ]

    feed, feed_matches = _feed(va_sigmet_review)

    receipts = [row for row in direct_review.get("responsible_centre_receipts") or [] if isinstance(row, dict)]
    # A review saved before responsible_centres was carried names its centres by their receipts.
    responsible = [_clean(centre).upper() for centre in direct_review.get("responsible_centres") or [] if _clean(centre)] \
        or list(dict.fromkeys(_clean(row.get("centre")).upper() for row in receipts if _clean(row.get("centre"))))
    reached = [_clean(row.get("centre")).upper() for row in receipts if row.get("reached") is True and _clean(row.get("centre"))]
    not_reached = [centre for centre in responsible if centre not in reached]
    mounted_any = any(str(row.get("status") or "").lower() != "not_mounted" for row in receipts)
    unsettled = int(direct_review.get("unresolved_route_points") or 0)
    settled = bool(responsible) and not direct_review.get("responsibility_review_required") and unsettled == 0
    advisories = int(direct_review.get("official_advisory_count") or len(direct_review.get("official_advisories") or []))

    # ------------------------------------------------------------------ the sentence, in the fixed source order
    parts: list[str] = []
    if ofp_section == "printed":
        count = len(ofp_sigmets)
        parts.append(
            f"OFP VA SIGMET: {count} printed ({_names(sigmet_names)})" if count
            else "OFP VA SIGMET: section printed, no record read")
    elif ofp_section == "no_data":
        parts.append("OFP VA SIGMET: 'no data' printed")
    else:
        parts.append("OFP VA SIGMET section: not printed")
    if ofp_notices:
        parts.append(f"OFP volcano notices: {_names(notice_names)}")
    live: list[str] = []
    live.append({
        "affected": f"VA SIGMET feed: {_names(feed_matches)} cross the filed route/time/level",
        "reached": "VA SIGMET feed: reached, no current VA SIGMET crosses the route",
        "stale": "VA SIGMET feed: reached, not current",
        "not_reached": "VA SIGMET feed: not reached",
        "not_queried": "VA SIGMET feed: not queried",
    }[feed])
    if responsible:
        if not mounted_any and not reached:
            reach = "not queried"
        elif not not_reached:
            reach = "all reached"
        elif not reached:
            reach = "none reached"
        else:
            reach = f"{_names(reached)} reached, NOT reached: {_names(not_reached)}"
        vaac = f"Responsible VAACs {_names(responsible)}: {reach}"
        if reached:
            vaac += (f"; {advisories} advisor{'y' if advisories == 1 else 'ies'} held, route applicability not assessed"
                     if advisories else "; no advisory held")
        if unsettled:
            vaac += f"; responsibility unsettled for {unsettled} route point{'' if unsettled == 1 else 's'}"
        live.append(vaac)
    else:
        live.append("Responsible VAAC: not settled for this route")
    parts.extend(live)

    # ------------------------------------------------------------------ the state
    live_configured = feed != "not_queried" or mounted_any
    live_answered = feed in {"affected", "reached", "stale"} or bool(reached)
    if feed == "affected":
        state = "FOUND"
    elif not live_configured:
        state = "NOT QUERIED"
    elif not live_answered:
        state = "UNAVAILABLE"
    elif (feed == "reached" and settled and not not_reached and advisories == 0
          and not ofp_sigmets and not ofp_notices):
        state = "CHECKED · NO MATCH"
    else:
        state = "UNRESOLVED"

    if feed == "affected":
        tile = "AFFECTING"
    elif ofp_sigmets or advisories:
        tile = "HELD"
    elif ofp_notices:
        tile = "NOTICE"
    else:
        tile = "NO DATA"

    if feed == "not_queried":
        feed_source = "NOT QUERIED"
    elif feed in {"affected", "reached"}:
        feed_source = "REACHED"
    else:
        feed_source = "NOT REACHED"
    if not responsible:
        vaac_source = "NOT SETTLED"
    elif not mounted_any and not reached:
        vaac_source = "NOT QUERIED"
    elif not reached:
        vaac_source = "NOT REACHED"
    elif not_reached or not settled:
        vaac_source = "PARTIAL"
    else:
        vaac_source = "REACHED"

    # The same live facts in counts, for a page at its last capacity step: nothing turns into a pass, only the centre
    # names move to the dashboard.
    feed_short = {
        "affected": f"feed: {_names(feed_matches)} crossing",
        "reached": "feed reached, none crossing",
        "stale": "feed not current",
        "not_reached": "feed not reached",
        "not_queried": "feed not queried",
    }[feed]
    if responsible:
        vaac_short = (f"VAACs not queried ({len(responsible)} responsible)" if not mounted_any and not reached
                      else f"VAACs {len(reached)}/{len(responsible)} reached")
        if reached:
            vaac_short += f", {advisories} advisor{'y' if advisories == 1 else 'ies'} held" if advisories else ", none held"
        if unsettled:
            vaac_short += f", {unsettled} route point{'' if unsettled == 1 else 's'} unsettled"
    else:
        vaac_short = "responsible VAAC not settled"
    return {
        "schema": CHECK_SCHEMA,
        "state": state,
        "line": ". ".join(parts) + ".",
        "live_line": ". ".join(live) + ".",
        "live_compact": f"VA sources: {feed_short}; {vaac_short}.",
        # The OFP section and the live sources in counts: for a fixed-height table cell (the internal composition's
        # two-line checklist cells).
        "short_line": f"{parts[0]}. VA sources: {feed_short}; {vaac_short}.",
        "tile": tile,
        "ofp_section": ofp_section,
        "ofp_va_sigmets": sigmet_names,
        "ofp_notices": notice_names,
        "feed": feed,
        "feed_matches": feed_matches,
        "responsible": responsible,
        "reached": reached,
        "not_reached": not_reached,
        "responsibility_settled": settled,
        "unsettled_points": unsettled,
        "direct_advisories": advisories,
        "sources": [
            {"source": "OFP VA SIGMET SECTION", "status": "HELD" if ofp_sigmets else "NOT HELD",
             "detail": parts[0] + "."},
            {"source": "VA SIGMET FEED", "status": feed_source, "detail": live[0] + "."},
            {"source": "RESPONSIBLE VAACS", "status": vaac_source, "detail": live[-1] + "."},
        ],
    }

"""One composed volcanic-ash check for every surface (VOLCANIC-CHECK-436).

David, 24 Sep 2026 06:51: "I also recall that I asked you to make sure the AI goes thru the checklist of items it must
perform for each flight. That list has disappeared? What happens next time say to the Pacific with the volcano
advisories?"

PD holds four volcanic-ash sources for a flight, and each surface used to read a different subset of them:

1. the OFP's own "Volcanic Ash SIGMETs:" section (printed with messages, printed as "no data", or not printed);
2. the OFP's volcano notices (NOTAM / ASHTAM records naming a volcano);
3. the live international VA SIGMET feed, evaluated against the filed route, time and planned level;
4. the route-responsible VAACs (ICAO Doc 9766 areas) and the advisories each one returned.

This module composes the four sources once, in that fixed order, into one state and one sentence. Every surface prints
these composed values; none re-derives them. The rules (no flight, route, centre or volcano is special-cased):

- FOUND: the feed's route/time/level evaluation verified an intersection;
- NOT QUERIED: no live source was configured (the feed is disabled and no responsible centre is mounted);
- UNAVAILABLE: live sources were configured but none answered;
- CHECKED · NO MATCH: only when the feed's and the VAACs' source statuses are both met (a bare REACHED: answered,
  current for this flight, complete, evaluated, covering the route, responsibility settled), no direct advisory is
  held, no current VA SIGMET on the route expires before the flight passes and the OFP prints no volcanic record;
- UNRESOLVED in every other case.

ITEM2-VOLCANIC (24 Oct 2026, open item #2: "The PDF wrongly says a warning source wasn't checked"). Each live source's
status is composed by source_status.py from two facts kept apart - whether it answered (reach) and whether its answer
speaks for this flight (qualifiers) - so a feed that answered is never "not reached", and an answer that is stale, was
retrieved outside the window it could cover, is incomplete, could not be evaluated or leaves part of the route
uncovered never reads as a met source. The VAAC row likewise separates "every responsible centre answered" from "their
answers are complete and current" and from "responsibility is settled".

Missing evidence is never NIL: an unreached source is named as not reached, a disabled one as not queried, an answer
that does not speak for the flight as what it is.
"""
from __future__ import annotations

from datetime import timedelta
from typing import Any

from . import source_status as ss
from .source_status import answer_currency, flight_window  # noqa: F401 - re-exported for callers of the check

CHECK_SCHEMA = "volcanic-ash-check-v2"

# A VA SIGMET is valid for at most 6 hours (ICAO Doc 9766, 4.5.1 d): "issue a SIGMET information for volcanic ash for a
# validity period of 6 hours"). A feed of currently valid SIGMETs retrieved at R can therefore speak for no instant
# after R + 6 h, and for nothing once the flight has landed.
VA_SIGMET_MAX_VALIDITY = timedelta(hours=6)
# The VAAC connectors retain advisories issued from 18 h before departure (a VAA forecasts to T+18 h, Doc 9766 4.6.1 c)
# to 1 h after arrival (direct_vaac._flight_window). An answer retrieved outside that window cannot hold the advisories
# that govern the flight: before it they were not yet issued, after it the providers carry only their latest products.
VAAC_WINDOW_LEAD = timedelta(hours=18)
VAAC_WINDOW_LAG = timedelta(hours=1)

# Reason codes of the shared route/time/level evaluator (vaa.evaluate_vaa) and what each says about the feed's answer.
_FEED_DESCRIPTIVE = frozenset({
    # The feed is a current-SIGMET receipt by design; "coverage not complete" is that statement, not a defect of
    # this answer. The OFP's own section and the VAAC connectors have their own rows.
    "coverage_not_complete_for_flight", "cfp_weather_data_unavailable", "verified_no_intersection",
    "verified_intersection", "direct_vaac_advisory_source_unavailable", "direct_vaac_advisory_source_not_mounted",
    "direct_vaac_coverage_partial", "route_sigmet_expires_before_passage",
})
_FEED_NOT_CURRENT = frozenset({"source_stale"})
_FEED_INCOMPLETE = frozenset({
    "source_records_incomplete", "advisory_time_unavailable", "advisory_level_unavailable", "advisory_geometry_invalid",
})
_FEED_NOT_EVALUATED_WORDS = {
    "route_geometry_unavailable": "route geometry not held",
    "route_timing_unavailable": "flight timing not held",
    "flight_level_unavailable": "planned level not held",
    "flight_level_change_unresolved": "a level change not placed",
    "route_timing_non_monotonic": "route timing out of order",
}
# The international feed carries no US domestic-format SIGMET (AWC Data API: isigmet "does not include SIGMETs issued by
# the United States in domestic format"). The contiguous-US ARTCC FIRs are the domestic ones; Oakland Oceanic (KZAK)
# and New York Oceanic (KZWY) SIGMETs are international-format and in the feed.
_US_INTERNATIONAL_FORMAT_FIRS = frozenset({"KZAK", "KZWY"})


def _clean(value: Any) -> str:
    return " ".join(str(value or "").split())


def _names(values: list[str]) -> str:
    seen = list(dict.fromkeys(value for value in values if value))
    return ", ".join(seen)


def us_domestic_firs(flight: dict[str, Any]) -> list[str]:
    """The contiguous-US domestic FIRs the route enters, by the OFP's own boundary points and end airports."""
    flight = flight or {}
    named = [_clean(w.get("fir_boundary")).upper() for w in flight.get("route_waypoints") or [] if isinstance(w, dict)]
    firs = [fir for fir in named if len(fir) == 4 and fir.startswith("KZ") and fir not in _US_INTERNATIONAL_FORMAT_FIRS]
    ends = [_clean(flight.get(key)).upper() for key in ("departure", "destination")]
    firs += [airport for airport in ends if len(airport) == 4 and airport.startswith("K")]
    return list(dict.fromkeys(firs))


def _feed(va_sigmet_review: dict[str, Any], flight: dict[str, Any]) -> dict[str, Any]:
    """The live VA SIGMET feed: reach, the qualifiers on its answer, its matches and the clauses that explain them."""
    status = str(va_sigmet_review.get("status") or "").lower()
    reasons = {str(code) for code in va_sigmet_review.get("reason_codes") or []}
    matches = [
        _clean(match.get("advisory_id") or match.get("id") or match.get("fir_id")) or "ID unresolved"
        for match in va_sigmet_review.get("matches") or []
        if isinstance(match, dict)
    ]
    expiring = [
        _clean(item.get("advisory_id")) or "ID unresolved"
        for item in va_sigmet_review.get("expiring_on_route") or []
        if isinstance(item, dict)
    ]
    result: dict[str, Any] = {"matches": list(dict.fromkeys(matches)), "expiring": list(dict.fromkeys(expiring)),
                              "qualifiers": [], "clauses": []}
    if not va_sigmet_review or status == "not_assessed" or "source_disabled" in reasons:
        return {**result, "reach": ss.NOT_QUERIED, "matches": []}
    if "source_unavailable" in reasons and status != "affected" and not matches:
        return {**result, "reach": ss.NOT_REACHED}
    qualifiers: list[str] = []
    clauses: list[str] = []
    if reasons & _FEED_NOT_CURRENT:
        qualifiers.append(ss.NOT_CURRENT)
        clauses.append("not current (source freshness check failed)")
    snapshot = va_sigmet_review.get("source_snapshot") or {}
    currency, words = answer_currency(
        va_sigmet_review.get("retrieved_at_utc") or snapshot.get("retrieved_at_utc"), flight,
        lead=VA_SIGMET_MAX_VALIDITY)
    if currency and currency not in qualifiers:
        qualifiers.append(currency)
        clauses.append(words)
    if reasons & _FEED_INCOMPLETE:
        qualifiers.append(ss.INCOMPLETE)
        warnings = [w for w in snapshot.get("parse_warnings") or [] if isinstance(w, str)]
        unread = [w for w in warnings if w.startswith("record_")]
        capped = [w for w in warnings if w.startswith("response_at_provider_cap")]
        if unread:
            clauses.append(f"{len(unread)} VA SIGMET record{'' if len(unread) == 1 else 's'} not readable")
        if capped:
            clauses.append("answer at the provider's record cap; SIGMETs may be missing")
        if not unread and not capped:
            clauses.append("records incomplete")
    not_evaluated = sorted(reasons - _FEED_DESCRIPTIVE - _FEED_NOT_CURRENT - _FEED_INCOMPLETE
                           - {"source_unavailable"})
    if not_evaluated:
        qualifiers.append(ss.NOT_EVALUATED)
        words = [_FEED_NOT_EVALUATED_WORDS.get(code, code.replace("_", " ")) for code in not_evaluated]
        clauses.append(f"route/time/level not evaluated ({', '.join(dict.fromkeys(words))})")
    domestic = us_domestic_firs(flight)
    if domestic:
        qualifiers.append(ss.COVERAGE_GAP)
        clauses.append(f"US domestic-format SIGMETs ({', '.join(domestic)}) are not in this feed")
    return {**result, "reach": ss.REACHED, "qualifiers": qualifiers, "clauses": clauses}


def _receipt_time(receipt: dict[str, Any], flight: dict[str, Any]) -> Any:
    if receipt.get("retrieved_at_utc"):
        return receipt.get("retrieved_at_utc")
    # A review saved before receipts carried their own retrieval time: the combined direct snapshot's.
    legacy = ((flight or {}).get("vaa_review") or {}).get("direct_vaac_snapshot") or {}
    return legacy.get("retrieved_at_utc")


def volcanic_ash_check(
    flight: dict[str, Any],
    va_sigmet_review: dict[str, Any] | None,
    direct_review: dict[str, Any] | None,
    cfp_advisories: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    flight = flight or {}
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

    feed = _feed(va_sigmet_review, flight)
    feed_matches = feed["matches"]
    affected = bool(feed_matches) or (str(va_sigmet_review.get("status") or "").lower() == "affected"
                                      and feed["reach"] == ss.REACHED)
    feed_status = ss.source_status(feed["reach"], feed["qualifiers"])

    receipts = [row for row in direct_review.get("responsible_centre_receipts") or [] if isinstance(row, dict)]
    # A review saved before responsible_centres was carried names its centres by their receipts.
    responsible = [_clean(centre).upper() for centre in direct_review.get("responsible_centres") or [] if _clean(centre)] \
        or list(dict.fromkeys(_clean(row.get("centre")).upper() for row in receipts if _clean(row.get("centre"))))
    by_centre = {_clean(row.get("centre")).upper(): row for row in receipts if _clean(row.get("centre"))}
    reached = [centre for centre in responsible if (by_centre.get(centre) or {}).get("reached") is True]
    not_reached = [centre for centre in responsible if centre not in reached]
    mounted_any = any(str(row.get("status") or "").lower() != "not_mounted" for row in receipts)
    unsettled = int(direct_review.get("unresolved_route_points") or 0)
    settled = bool(responsible) and not direct_review.get("responsibility_review_required") and unsettled == 0
    advisories = int(direct_review.get("official_advisory_count") or len(direct_review.get("official_advisories") or []))

    # Each reached centre's answer: complete and current for this flight, or not.
    incomplete = [c for c in reached if str(by_centre[c].get("status") or "").lower() != "available"]
    not_current: list[str] = []
    currency_unknown: list[str] = []
    for centre in reached:
        receipt = by_centre[centre]
        if str(receipt.get("freshness_status") or "").lower() == "stale":
            not_current.append(centre)
            continue
        currency, _ = answer_currency(_receipt_time(receipt, flight), flight, lead=VAAC_WINDOW_LEAD, lag=VAAC_WINDOW_LAG)
        if currency == ss.NOT_CURRENT:
            not_current.append(centre)
        elif currency == ss.CURRENCY_UNKNOWN:
            currency_unknown.append(centre)

    if not responsible:
        vaac_reach = ss.NOT_SETTLED
    elif not mounted_any and not reached:
        vaac_reach = ss.NOT_QUERIED
    elif not reached:
        vaac_reach = ss.NOT_REACHED
    elif not_reached:
        vaac_reach = ss.PARTIAL
    else:
        vaac_reach = ss.REACHED
    vaac_qualifiers: list[str] = []
    if not_current:
        vaac_qualifiers.append(ss.NOT_CURRENT)
    if currency_unknown:
        vaac_qualifiers.append(ss.CURRENCY_UNKNOWN)
    if incomplete:
        vaac_qualifiers.append(ss.INCOMPLETE)
    if responsible and not settled:
        vaac_qualifiers.append(ss.NOT_SETTLED)
    vaac_status = ss.source_status(vaac_reach, vaac_qualifiers)

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

    if feed["reach"] == ss.NOT_QUERIED:
        feed_line = "VA SIGMET feed: not queried"
    elif feed["reach"] == ss.NOT_REACHED:
        feed_line = "VA SIGMET feed: not reached"
    else:
        clauses = list(feed["clauses"])
        if feed["expiring"]:
            clauses.append(f"{_names(feed['expiring'])} on the route expire{'s' if len(feed['expiring']) == 1 else ''} "
                           "before the flight passes; successor not held")
        if affected:
            feed_line = "; ".join([f"VA SIGMET feed: {_names(feed_matches)} cross the filed route/time/level", *clauses])
        elif not feed["clauses"]:
            feed_line = "; ".join(["VA SIGMET feed: reached, no current VA SIGMET crosses the route", *clauses])
        else:
            # "reached, not current: retrieved ...": what the answer is, after the fact that it was received.
            feed_line = "VA SIGMET feed: reached, " + "; ".join(clauses)

    live: list[str] = [feed_line]
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
        if not_current:
            vaac += f"; {_names(not_current)} not current for this flight"
        if currency_unknown:
            vaac += f"; {_names(currency_unknown)} currency not established"
        if incomplete:
            vaac += f"; {_names(incomplete)} answered incompletely"
        if reached:
            vaac += (f"; {advisories} advisor{'y' if advisories == 1 else 'ies'} held, route applicability not assessed"
                     if advisories else "; no advisory held")
        if unsettled:
            vaac += f"; responsibility unsettled for {unsettled} route point{'' if unsettled == 1 else 's'}"
        elif not settled:
            vaac += "; responsibility not settled"
        live.append(vaac)
    else:
        live.append("Responsible VAAC: not settled for this route")
    parts.extend(live)

    # ------------------------------------------------------------------ the state
    live_configured = feed["reach"] != ss.NOT_QUERIED or mounted_any
    live_answered = feed["reach"] == ss.REACHED or bool(reached)
    if affected:
        state = "FOUND"
    elif not live_configured:
        state = "NOT QUERIED"
    elif not live_answered:
        state = "UNAVAILABLE"
    elif (ss.source_status_met(feed_status) and ss.source_status_met(vaac_status) and advisories == 0
          and not feed["expiring"] and not ofp_sigmets and not ofp_notices):
        state = "CHECKED · NO MATCH"
    else:
        state = "UNRESOLVED"

    if affected:
        tile = "AFFECTING"
    elif ofp_sigmets or advisories or feed["expiring"]:
        tile = "HELD"
    elif ofp_notices:
        tile = "NOTICE"
    else:
        tile = "NO DATA"

    # The same live facts in counts, for a page at its last capacity step: nothing turns into a pass, only the centre
    # names move to the dashboard.
    if affected:
        feed_short = f"feed: {_names(feed_matches)} crossing"
    elif feed["reach"] != ss.REACHED:
        feed_short = f"feed {ss.source_status_words(feed_status)}"
    elif ss.source_status_met(feed_status):
        feed_short = "feed reached, none crossing"
    else:
        feed_short = f"feed {ss.source_status_words(feed_status)}"
    if feed["expiring"] and not affected:
        feed_short += f", {len(feed['expiring'])} on route expiring"
    if responsible:
        vaac_short = (f"VAACs not queried ({len(responsible)} responsible)" if not mounted_any and not reached
                      else f"VAACs {len(reached)}/{len(responsible)} reached")
        for centres, word in ((not_current, "not current"), (currency_unknown, "currency unknown"),
                              (incomplete, "incomplete")):
            if centres:
                vaac_short += f", {len(centres)} {word}"
        if reached:
            vaac_short += f", {advisories} advisor{'y' if advisories == 1 else 'ies'} held" if advisories else ", none held"
        if unsettled:
            vaac_short += f", {unsettled} route point{'' if unsettled == 1 else 's'} unsettled"
    else:
        vaac_short = "responsible VAAC not settled"

    if feed["reach"] == ss.NOT_QUERIED:
        feed_value = "not_queried"
    elif feed["reach"] == ss.NOT_REACHED:
        feed_value = "not_reached"
    else:
        feed_value = "affected" if affected else "reached"
    ofp_status = ss.HELD if ofp_sigmets else ss.NOT_HELD
    return {
        "schema": CHECK_SCHEMA,
        "vocabulary": ss.SOURCE_STATUS_VOCABULARY,
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
        "feed": feed_value,
        "feed_status": feed_status,
        "feed_qualifiers": feed["qualifiers"],
        "feed_matches": feed_matches,
        "feed_expiring_on_route": feed["expiring"],
        "responsible": responsible,
        "reached": reached,
        "not_reached": not_reached,
        "incomplete_centres": incomplete,
        "not_current_centres": not_current,
        "currency_unknown_centres": currency_unknown,
        "vaac_status": vaac_status,
        "vaac_line": live[-1],
        "responsibility_settled": settled,
        "unsettled_points": unsettled,
        "direct_advisories": advisories,
        "sources": [
            ss.source_row("OFP VA SIGMET SECTION", ofp_status, [], parts[0] + "."),
            ss.source_row("VA SIGMET FEED", feed["reach"], feed["qualifiers"], live[0] + "."),
            ss.source_row("RESPONSIBLE VAACS", vaac_reach, vaac_qualifiers, live[-1] + "."),
        ],
    }

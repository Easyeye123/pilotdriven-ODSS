"""F21 and F22 of Codex's independent re-QA of release 484 (11 Oct 2026): page 2's exclusion cards.

F21: a page-2 exclusion card prints at most two lines, but the count of what it leaves out was taken after each airport
had already been cut to two. Three confirmed exclusions at WSSS printed two lines and no "1 further" note; three at WSSS
and three at VCBI said "2 further" instead of 4. The destination arrival card dropped a third promoted exclusion with
no note at all. Every eligible exclusion is now counted before the display cap, on both cards.

F22: a card carrying an exclusion displaces first a NOTAM card that another selected card already prints - but "already
printed" compared bare NOTAM numbers, so WSSS A101/26 displaced a different notice, VRMM A101/26. A notice is now the
same only when its airport and number are both the same; a finding that names no airport is never called a duplicate.
"""
from __future__ import annotations

import re

import pytest

from app.odss import aircraft_restriction_applicability as rule


def _limit(notam_id: str, stand: int, *, role: str = "departure", aircraft_type: str = "A350-941", **extra) -> dict:
    from app.odss.briefing import _compact_notam_family

    text = f"ACFT STAND {stand} DOWNGRADED TO CODE C"
    item = {
        "notam_id": notam_id, "item_e_text": text, "summary": text, "compact_text": text,
        "pertinence_kind": "taxiway_restriction", "pertinence_rank": 4, "severity": "warning",
        "applicability": "active", "stateAtReference": "active_at_reference", "role": role, "source_page": 26, **extra,
    }
    item.setdefault("signal_family", _compact_notam_family(item))
    check = rule.notam_aircraft_size_check({"aircraft_type": aircraft_type}, item)
    if check:
        item["aircraft_size_check"] = check
    return item


def _panel(icao: str, role: str, role_key: str, *items: dict, summary_lines: list[dict] | None = None) -> dict:
    return {"icao": icao, "roles": [role], "role": role, "role_keys": [role_key], "selected_notams": list(items),
            "card_summary_lines": list(summary_lines or [])}


def _project(panels: list[dict], findings: list[dict] | None = None) -> list[dict]:
    from app.odss.briefing import _decision_finding_projection

    return _decision_finding_projection(list(findings or []), airport_panels=panels)


def _card(panels: list[dict], engine: str) -> dict:
    (card,) = [row for row in _project(panels) if row["engine"] == engine]
    return card


def _further(summary: str) -> int:
    match = re.search(r"(\d+) further aircraft-size exclusions? (?:is|are) held on the dashboard Airports page\.", summary)
    return int(match.group(1)) if match else 0


def _stated(summary: str) -> int:
    return summary.count("above this limit (Code C)")


# --- F21: the count is taken over every eligible exclusion, before the display cap ----------------------------

@pytest.mark.parametrize(("counts", "shown", "further"), [
    ((1,), 1, 0), ((2,), 2, 0), ((3,), 2, 1), ((4,), 2, 2),
    ((2, 2), 2, 2), ((3, 3), 2, 4), ((1, 1, 1), 2, 1), ((0, 5), 2, 3),
])
def test_the_further_count_is_every_eligible_exclusion_the_card_leaves_out(counts, shown, further) -> None:
    airports = [("WSSS", "departure", "departure"), ("VCBI", "destination alternate", "alternate"), ("VOMM", "EDTO", "edto")]
    panels = [
        _panel(icao, role, key, *[_limit(f"{icao[:2]}{index + 1}/26", 600 + index, role=role) for index in range(count)])
        for (icao, role, key), count in zip(airports, counts)
    ]
    summary = _card(panels, "aircraft_exclusion")["summary"]
    assert _stated(summary) == shown
    assert _further(summary) == further


def test_ineligible_notices_are_never_counted_as_further_exclusions() -> None:
    panel = _panel(
        "WSSS", "departure", "departure",
        _limit("A1/26", 601), _limit("A2/26", 602),
        _limit("A3/26", 603, stateAtReference="ended_before_reference"),
        _limit("A4/26", 604, applicability="not_applicable"),
        _limit("A5/26", 605, aircraft_type="737-8"),
        _limit("A6/26", 606, item_e_text="ACFT STAND 606 DOWNGRADED TO CODE C EXC A350 ACFT"),
    )
    summary = _card([panel], "aircraft_exclusion")["summary"]
    assert _stated(summary) == 2 and _further(summary) == 0


@pytest.mark.parametrize(("count", "further"), [(1, 0), (2, 0), (3, 1), (5, 3)])
def test_the_arrival_card_counts_the_destination_exclusions_it_leaves_out(count: int, further: int) -> None:
    panel = _panel("VRMM", "destination", "destination",
                   *[_limit(f"B{index + 1}/26", 700 + index, role="destination") for index in range(count)])
    summary = _card([panel], "arrival_ground")["summary"]
    assert _stated(summary) == min(count, 2)
    assert _further(summary) == further


# --- F22: a duplicate is the same notice at the same airport --------------------------------------------------

def _six(notice_id: str, *, location: str | None) -> list[dict]:
    def finding(engine: str, title: str, severity: str = "warning", **data) -> dict:
        return {"engine": engine, "severity": severity, "title": title, "summary": f"{title} summary.", "data": data}

    notice = {"role": "destination", "notam_id": notice_id, **({"location": location} if location else {})}
    return [
        finding("performance", "Performance check", "critical"),
        finding("notam", "VRMM runway notice", **notice),
        finding("weather", "Weather item"),
        finding("mel", "Informational MEL", "information"),
        finding("route_airspace", "Route airspace"),
    ]


def _wsss_and_vrmm() -> list[dict]:
    held = {"kind": "notam", "label": "A202/26", "notam_id": "A202/26", "text": "TWY C closed.", "signal_family": "taxiway",
            "source_page": 29}
    return [
        _panel("WSSS", "departure", "departure", _limit("A101/26", 603)),
        _panel("VRMM", "destination", "destination", summary_lines=[held]),
    ]


@pytest.mark.parametrize(("notice_id", "location", "kept", "gave_way"), [
    ("A101/26", "VRMM", "VRMM runway notice", "Informational MEL"),   # same number, another airport: not a duplicate
    ("A303/26", "VRMM", "VRMM runway notice", "Informational MEL"),   # different number
    ("A202/26", "VRMM", "Informational MEL", "VRMM runway notice"),   # same airport, same number: the arrival card prints it
    ("A202/26", None, "VRMM runway notice", "Informational MEL"),     # no airport named: never called a duplicate
])
def test_a_duplicate_is_the_same_notice_at_the_same_airport(notice_id, location, kept, gave_way) -> None:
    titles = [row["title"] for row in _project(_wsss_and_vrmm(), _six(notice_id, location=location))]
    assert len(titles) == 6
    assert "Aircraft-size exclusion at WSSS departure" in titles
    assert kept in titles
    assert gave_way not in titles

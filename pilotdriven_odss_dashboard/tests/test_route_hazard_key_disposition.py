"""The FLIGHT HAZARD KEY must state the verdict the SIGMET card already holds.

David, 9 Sep 2026 21:21:57, on our route hazard page for SQ882 WSSS-VHHH
(FLIGHT HAZARD KEY listing VA1/VA2 Krakatau and WX3...WX11):

    "This came up by itself .. hazard analysis okay. But not WX ... that is
    for what???"

On that flight the SIGMET card promotes VVHM/1 and ZJSA/1 - the filed route
crosses each polygon inside the product's validity - and does not promote
ZJSA/2, whose product only becomes valid 81 minutes after the latest possible
crossing. The key printed "flight relevance unverified" for all three, so a
SIGMET the flight meets and one it cannot meet read identically, and neither
line agreed with the verdict card on the same page. ``level_matched`` was never
set for an OFP SIGMET, so the "affects flight" branch was unreachable and the
computed time match was never printed.

These tests pin three things: the three cases print three different plain
sentences, each sentence states the card's disposition (in words, never as a
block-capital badge), and a level verdict is printed only from the SIGMET's
own layer and the OFP's planned level profile.
"""
from __future__ import annotations

import fitz
import pytest

from app.odss.analysed_briefing_map import (
    build_publication_map,
    event_affects_flight,
    event_description,
    key_disposition,
)
from app.odss.briefing import _sigmet_screening_cards, build_briefing_view
from app.odss.combined_brief import render_combined_briefing
from app.odss.concise_pdf_gate import WEATHER_PAGE, check_concise_pdf, normalized


SQUARE = "WI S0100 W00100 - S0100 E00100 - N0100 E00100 - N0100 W00100"
# Two degrees north of the square: a route along the equator never touches it.
NORTH_SQUARE = "WI N0200 W00100 - N0200 E00100 - N0400 E00100 - N0400 W00100"


def fix(lat, lon, actm, name="FIX"):
    return dict(latitude=lat, longitude=lon, actm_minutes=actm, name=name)


def sigmet(identifier, validity, *, area=SQUARE, layer="TOP FL450", fir="WSJC"):
    return (f"WS SIGMET {identifier} VALID {validity} WSSS- {fir} SINGAPORE FIR EMBD TS OBS "
            f"{area} {layer} NC=")


def flight_for(route, *texts, profile="A/390", departure="2026-07-11T10:30:00Z"):
    return {
        "scheduled_departure_utc": departure,
        "route_waypoints": route,
        "planned_level_profile": profile,
        "weather": [{"record_type": "SIGMET", "location": "WSJC", "text": text} for text in texts],
    }


def key_events(flight):
    """The SIGMET cards the weather page prints, and the key events built from them."""
    cards = _sigmet_screening_cards(flight)
    events = [event for event in build_publication_map(flight, {"hazards": {"sigmet_cards": cards}})["publication_events"]
              if event["kind"] == "WX"]
    return cards, events


# A 20-minute leg through the square: filed leg bounds 1030-1050Z.
CROSSING = [fix(0, -2, 0, "A"), fix(0, 2, 20, "B")]


@pytest.mark.parametrize("validity,disposition,phrase,absent", [
    ("111000/111100", "PROMOTED", "crosses route 1030-1050Z inside validity", "outside validity"),
    ("111100/111200", "NOT PROMOTED",
     "crosses route 1030-1050Z outside validity (starts 10 min after latest crossing)", "inside validity"),
    ("110900/111000", "NOT PROMOTED",
     "crosses route 1030-1050Z outside validity (expired 30 min before earliest crossing)", "inside validity"),
])
def test_a_crossing_says_whether_it_is_inside_the_validity_window(validity, disposition, phrase, absent):
    cards, events = key_events(flight_for(CROSSING, sigmet("1", validity)))
    assert cards[0]["disposition"] == disposition
    line = event_description(events[0])
    assert phrase in line
    assert absent not in line
    assert "unverified" not in line
    assert events[0]["disposition"] == disposition
    assert key_disposition(events[0]) == disposition


def test_a_route_that_does_not_cross_says_so_and_is_not_promoted():
    cards, events = key_events(flight_for(CROSSING, sigmet("1", "111000/111100", area=NORTH_SQUARE)))
    assert cards[0]["disposition"] == "NOT PROMOTED"
    line = event_description(events[0])
    assert "route does not cross area" in line
    assert "crosses route" not in line and "validity" not in line.split("Z; ", 1)[-1]
    assert key_disposition(events[0]) == "NOT PROMOTED"


def test_the_three_cases_print_three_different_lines_on_one_flight():
    """His screenshot: one key, several WX rows, every state reading the same."""
    flight = flight_for(
        CROSSING,
        sigmet("1", "111000/111100"),                     # crosses inside validity
        sigmet("2", "111100/111200"),                     # crosses, product starts later
        sigmet("3", "111000/111100", area=NORTH_SQUARE),  # never crossed
    )
    cards, events = key_events(flight)
    assert [card["disposition"] for card in cards] == ["PROMOTED", "NOT PROMOTED", "NOT PROMOTED"]
    lines = [event_description(event) for event in events]
    assert len(set(lines)) == 3
    for card, event in zip(cards, events):
        assert key_disposition(event) == card["disposition"] == event["disposition"]
    assert "inside validity" in lines[0] and "outside validity" in lines[1] and "does not cross" in lines[2]


def test_a_partial_overlap_or_missing_crossing_clock_stays_unresolved_without_a_badge():
    cards, events = key_events(flight_for(CROSSING, sigmet("1", "111040/111045")))
    assert cards[0]["disposition"] == "REVIEW REQUIRED"
    line = event_description(events[0])
    assert "crosses route 1030-1050Z" in line and "timing unresolved" in line
    assert "inside validity" not in line and "outside validity" not in line
    assert "REVIEW REQUIRED" not in line and "affects flight" not in line
    assert key_disposition(events[0]) == "REVIEW REQUIRED"

    cards, events = key_events(flight_for([fix(0, -2, None, "A"), fix(0, 2, None, "B")], sigmet("1", "111000/111100")))
    assert cards[0]["disposition"] == "REVIEW REQUIRED"
    line = event_description(events[0])
    assert "crosses route" in line and "crossing time not held" in line
    assert "does not cross" not in line and "affects flight" not in line
    assert key_disposition(events[0]) == "REVIEW REQUIRED"


# Cruise-phase crossing: TOC and TOD are held and the crossing leg lies between them.
CRUISE = [fix(0, -4, 0, "A"), fix(0, -3, 5, "TOC"), fix(0, -2, 10, "B"), fix(0, 2, 30, "C"),
          fix(0, 3, 35, "TOD"), fix(0, 4, 40, "D")]


def test_level_is_read_from_the_sigmet_layer_and_the_planned_profile():
    # Lido prints EMBD TS with a top only; thunderstorms are surface-based, so
    # planned FL390 under a FL450 top is inside the layer: the full verdict.
    cards, events = key_events(flight_for(CROSSING, sigmet("1", "111000/111100", layer="TOP FL450")))
    assert cards[0]["disposition"] == "PROMOTED"
    assert events[0]["level_matched"] is True
    line = event_description(events[0])
    assert "planned FL390 below top FL450" in line
    assert line.endswith("affects flight: route/time/level match")
    assert event_affects_flight(events[0]) is True

    # An explicit base/top layer that holds the planned level.
    _, events = key_events(flight_for(CROSSING, sigmet("1", "111000/111100", layer="FL250/450")))
    assert events[0]["level_matched"] is True
    assert "planned FL390 within layer FL250/FL450" in event_description(events[0])

    # A crossing outside the validity window is never "affects flight", whatever the level.
    _, events = key_events(flight_for(CROSSING, sigmet("1", "111100/111200", layer="TOP FL450")))
    assert events[0]["level_matched"] is True
    assert "affects flight" not in event_description(events[0])
    assert event_affects_flight(events[0]) is False


def test_a_level_outside_the_layer_is_asserted_only_for_a_cruise_phase_crossing():
    cards, events = key_events(flight_for(CRUISE, sigmet("1", "111000/111100", layer="TOP FL300")))
    assert cards[0]["disposition"] == "PROMOTED"
    assert events[0]["level_matched"] is False
    line = event_description(events[0])
    assert "crosses route 1040-1100Z inside validity" in line
    assert "planned FL390 above top FL300" in line
    assert "affects flight" not in line
    assert key_disposition(events[0]) == "PROMOTED"

    # Without TOC and TOD the crossing may be in the climb or descent: the
    # planned cruise level says nothing about the level at the crossing.
    _, events = key_events(flight_for(CROSSING, sigmet("1", "111000/111100", layer="TOP FL300")))
    assert events[0]["level_matched"] is None
    line = event_description(events[0])
    assert "level not verified" in line and "above" not in line and "affects flight" not in line

    # A step climb at the crossing leg's first fix keeps the previous level in the band.
    _, events = key_events(flight_for(CRUISE, sigmet("1", "111000/111100", layer="FL250/360"),
                                      profile="A/350/B/390"))
    assert events[0]["level_matched"] is True
    assert "planned FL350-FL390 within layer FL250/FL360" in event_description(events[0])

    # No layer in the source at all: nothing is asserted about level.
    _, events = key_events(flight_for(CRUISE, sigmet("1", "111000/111100", layer="")))
    assert events[0]["level_matched"] is None
    assert "layer not held" in event_description(events[0])


def test_the_weather_page_prints_the_three_lines_and_the_gate_reads_them_back(tmp_path):
    from generate_visual_samples import sample_findings, sample_flight

    flight = sample_flight()
    # Every level-change fix resolves to a route waypoint.
    flight["planned_level_profile"] = "BRU/350/ENITA/370/UDROS/390"
    # The UDROS (ACTM 140) - REBLO (ACTM 207) leg, 1205-1312Z after the 0945Z departure.
    box = "WI N4300 E03500 - N4300 E03900 - N4000 E03900 - N4000 E03500 - N4300 E03500"
    far = "WI N1000 E03500 - N1000 E03900 - N0800 E03900 - N0800 E03500 - N1000 E03500"
    flight.setdefault("weather", []).extend(
        {"record_type": "SIGMET", "location": "LTAA", "text": text}
        for text in (sigmet("1", "161100/161500", area=box, fir="LTAA"),
                     sigmet("2", "161400/161800", area=box, fir="LTAA"),
                     sigmet("3", "161100/161500", area=far, fir="LTAA")))
    findings = [f for f in sample_findings() if f["engine"] != "depressurisation"]
    path = tmp_path / "flight.pdf"
    render_combined_briefing(flight, findings, [], path)
    view = build_briefing_view(flight, findings, [])
    events = [event for event in build_publication_map(flight, view)["publication_events"] if event["kind"] == "WX"]
    assert [event["disposition"] for event in events] == ["PROMOTED", "NOT PROMOTED", "NOT PROMOTED"]
    lines = [event_description(event) for event in events]
    assert len(set(lines)) == 3
    assert "crosses route 1205-1312Z inside validity" in lines[0]
    assert "planned FL370-FL390 below top FL450" in lines[0]
    assert "affects flight: route/time/level match" in lines[0]
    assert "outside validity (starts 48 min after latest crossing)" in lines[1]
    assert "route does not cross area" in lines[2]
    with fitz.open(path) as document:
        page = normalized(document[WEATHER_PAGE].get_text())
    for line in lines:
        assert normalized(line) in page
    result = check_concise_pdf(path, flight=flight, view=view)
    assert result["valid"], result["violations"]


def test_a_held_verdict_the_geometry_contradicts_is_published_as_a_disagreement_and_refused(tmp_path):
    """The parity that stops the two pages of one PDF disagreeing again.

    A saved card that says the route stays outside a polygon the current
    geometry crosses is neither trusted nor overruled: the key says the two
    disagree, and the publication gate refuses the page."""
    from copy import deepcopy

    from generate_visual_samples import sample_findings, sample_flight

    flight = sample_flight()
    box = "WI N4300 E03500 - N4300 E03900 - N4000 E03900 - N4000 E03500 - N4300 E03500"
    flight.setdefault("weather", []).append(
        {"record_type": "SIGMET", "location": "LTAA", "text": sigmet("1", "161100/161500", area=box, fir="LTAA")})
    findings = [f for f in sample_findings() if f["engine"] != "depressurisation"]
    path = tmp_path / "flight.pdf"
    render_combined_briefing(flight, findings, [], path)
    view = build_briefing_view(flight, findings, [])
    assert check_concise_pdf(path, flight=flight, view=view)["valid"]

    stale = deepcopy(view)
    card = next(card for card in stale["hazards"]["sigmet_cards"] if card["sigmet_id"] == "1")
    assert card["disposition"] == "PROMOTED"
    card.update(route_intersection="outside", disposition="NOT PROMOTED",
                screening="The filed route does not intersect the polygon. NOT PROMOTED.")
    event = next(event for event in build_publication_map(flight, stale)["publication_events"]
                 if event.get("short_label") == "LTAA/1")
    assert event["disposition_conflict"] is True and event["disposition"] == "NOT PROMOTED"
    assert "disagree" in event_description(event) and "affects flight" not in event_description(event)
    assert event_affects_flight(event) is False
    assert key_disposition(event) == "REVIEW REQUIRED"
    result = check_concise_pdf(path, flight=flight, view=stale)
    assert not result["valid"]
    assert "ROUTE_HAZARD_KEY_DISPOSITION_PARITY" in {violation["code"] for violation in result["violations"]}


def test_sq882_key_lines_agree_with_its_sigmet_cards(tmp_path_factory):
    """His flight, his screenshot: VVHM/1 and ZJSA/1 promoted, ZJSA/2 not."""
    from test_boss_reference_briefing_format import rendered

    briefing = rendered("SQ882", tmp_path_factory)
    flight, view = briefing["flight"], briefing["view"]
    cards = {(card["fir"], card["sigmet_id"]): card for card in view["hazards"]["sigmet_cards"]}
    events = [event for event in build_publication_map(flight, view)["publication_events"] if event["kind"] == "WX"]
    assert len(events) >= 8
    lines = {}
    for event in events:
        card = cards[tuple(event["short_label"].split("/", 1))]
        assert event["disposition"] == card["disposition"]
        assert key_disposition(event) == card["disposition"], event["short_label"]
        lines[event["short_label"]] = event_description(event)
        assert normalized(lines[event["short_label"]]) in briefing["folded"][WEATHER_PAGE]
    assert "crosses route 0215-0247Z inside validity" in lines["VVHM/1"]
    assert "affects flight: route/time/level match" in lines["VVHM/1"]
    assert "crosses route 0241-0308Z inside validity" in lines["ZJSA/1"]
    assert "crosses route 0241-0319Z outside validity (starts 81 min after latest crossing)" in lines["ZJSA/2"]
    assert lines["VVHM/1"] != lines["ZJSA/2"]
    assert "unverified" not in " ".join(lines.values())
    assert "REVIEW REQUIRED" not in " ".join(lines.values())

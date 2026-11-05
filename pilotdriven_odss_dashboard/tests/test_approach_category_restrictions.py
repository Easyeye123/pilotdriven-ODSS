"""A notice that limits one approach category is published with that scope.

SQ352 15 Aug 2026, EKCH A1312/26, real OFP page 36: ``RWY 22L CAT II/III OPS
NOT AVBL DUE TO WIP.`` The planned arrival runway is 22L. The notice names no
aid, so the outage reading could not phrase it and it fell to the unreduced
count on page 1, on the dashboard card that prints page 1's statement, and on
the AIRPORTS page - the release-394 card had named it (independent candidate
review, 22 Sep 2026). It is neither an ILS outage nor a runway closure.

Every notice text below is a real item E from the held corpus (flight and
station named beside it). The panels around them are LABELLED CONSTRUCTED
inputs: one notice, active at the reference, in the analysis's own record
shape - so each case varies only the notice.
"""
from __future__ import annotations

import pytest

from app.odss.airport_pdf_analysis import analyse_airport_for_pdf

REFERENCE = "2026-08-16T05:10:00+00:00"


def notice(notam_id, text, kind, *, approach_affected=True, role="destination"):
    return {
        "notam_id": notam_id, "item_e_text": text, "pertinence_kind": kind,
        "approach_affected": approach_affected, "source_page": 36, "severity": "critical",
        "role_applicability": [{"role": role, "referenceAt": REFERENCE,
                                "stateAtReference": "active_at_reference", "applicability": "active"}],
    }


def analyse(icao, planned, *notices, role="destination"):
    return analyse_airport_for_pdf({"icao": icao, "selected_notams": list(notices)}, role=role, planned_runway=planned)


# SQ352 15 Aug 2026 destination EKCH (and SQ314 alternate EKCH).
A1312 = "RWY 22L CAT II/III OPS NOT AVBL DUE TO WIP."


def test_the_planned_runway_category_restriction_is_published_with_its_own_scope():
    result = analyse("EKCH", "22L", notice("A1312/26", A1312, "approach_navaid_closure"))
    assert result["unresolved_ids"] == []
    [line] = result["lines"]
    assert line["family"] == "approach_category"
    assert line["text"] == ("RWY 22L CAT II/III operations not available at arrival 16 AUG 0510Z; "
                            "this concerns planned RWY 22L. (A1312/26)")
    assert line["brief"] == "RWY 22L CAT II/III operations not available (planned runway)."
    assert line["relevance"] == 1
    # Never an aid outage or a closure.
    assert "ILS" not in line["text"] and "closed" not in line["text"]


def test_the_same_restriction_on_another_runway_says_so():
    result = analyse("EKCH", "04R", notice("A1312/26", A1312, "approach_navaid_closure"))
    [line] = result["lines"]
    assert line["text"].endswith("; planned RWY 04R is a different runway. (A1312/26)")
    assert line["brief"] == "RWY 22L CAT II/III operations not available (not planned RWY 04R)."
    assert line["relevance"] == 3


@pytest.mark.parametrize(("icao", "notam_id", "text", "label"), [
    # SQ24 15 Aug 2026 EDTO KORD; SQ38 29 Aug 2026 alternate KONT; SQ24 alternate KPHL.
    ("KORD", "A5362/26", "ORD ILS RWY 28L CAT II/III NA", "RWY 28L ILS CAT II/III operations not authorized"),
    ("KONT", "A1387/26", "NAV ILS RWY 26R CAT II/III NA", "RWY 26R ILS CAT II/III operations not authorized"),
    ("KPHL", "A2969/26", "NAV ILS RWY 27R SPECIAL AUTH CAT II NA",
     "RWY 27R ILS special-authorization CAT II operations not authorized"),
    ("KPHL", "A4393/26", "PHL ILS RWY 27R SPECIAL AUTH CAT II NA",
     "RWY 27R ILS special-authorization CAT II operations not authorized"),
])
def test_the_us_form_names_the_procedure_category_and_not_authorized(icao, notam_id, text, label):
    runway = label.split()[1]
    result = analyse(icao, runway, notice(notam_id, text, "runway_approach_restriction"))
    [line] = result["lines"]
    assert line["text"].startswith(label + " at arrival 16 AUG 0510Z; this concerns planned RWY"), line["text"]


def test_a_whole_ils_outage_is_still_an_ils_outage():
    # SQ910 21 Aug 2026 destination RPLL B3881/26: the CAT I ILS itself is U/S.
    result = analyse("RPLL", "24", notice("B3881/26", "ILS CAT I RWY 24 U/S.", "approach_navaid_closure"))
    [line] = result["lines"]
    assert line["family"] == "approach"
    assert "RWY 24 ILS (B3881/26)" in line["text"]
    assert "operations" not in line["text"]


@pytest.mark.parametrize(("icao", "notam_id", "text", "kind"), [
    # SQ482 alternate FACT: the category is explicitly unaffected.
    ("FACT", "A2781/26", "15X OUTERMOST PALS CAT III ON RWY 01 U/S. REMAINDER PALS AVBL, ILS CAT IIIB OPS UNAFFECTED.",
     "runway_approach_restriction"),
    # SQ365 fuel-enroute VECC: facilities, beside a monitoring-system outage.
    ("VECC", "A1660/26", "FRI SAT SUN MON 0530-1130 AIRFIELD LGT CONTROL AND MONITORING SYSTEM NOT AVBL. "
     "RMK:CAT II AND CAT III FAC NOT AVBL DUE WIP.", "approach_navaid_closure"),
])
def test_a_notice_that_is_not_only_a_category_restriction_stays_unresolved(icao, notam_id, text, kind):
    result = analyse(icao, "01", notice(notam_id, text, kind))
    assert result["lines"] == []
    assert result["unresolved_ids"] == [notam_id]


def test_an_obstacle_excepted_in_category_operations_is_not_a_category_restriction():
    # SQ303 16 Jul 2026 departure EBBR A1799/26.
    text = ("MOV OBST AS FM 90M SOUTH OF RWY 07L/25R AXIS BTN TWY B1 AND B5 EXC IN RWY 25R CAT II/III OPS. "
            "MAX 20FT AGL. ICAO DAY AND NIGHT MARKED WORK AREA")
    result = analyse("EBBR", "25R", notice("A1799/26", text, "obstacle", approach_affected=False, role="departure"),
                     role="departure")
    assert result["lines"] == [] and result["unresolved_ids"] == []
    assert result["supporting_ids"] == ["A1799/26"]


def test_another_stations_location_prefix_is_not_read_as_this_one():
    # LABELLED MUTATION of the real KORD A5362/26 text: JFK's prefix at KORD.
    result = analyse("KORD", "28L", notice("A5362/26", "JFK ILS RWY 28L CAT II/III NA", "runway_approach_restriction"))
    assert result["lines"] == []
    assert result["unresolved_ids"] == ["A5362/26"]


def test_a_category_restriction_beside_another_statement_is_not_read_in_part():
    # LABELLED MUTATION of A1312/26: a second clause this reader does not own.
    text = "RWY 22L CAT II/III OPS NOT AVBL. RWY 22L CLSD FOR LDG."
    result = analyse("EKCH", "22L", notice("A1312/26", text, "approach_navaid_closure"))
    assert all(line["family"] != "approach_category" for line in result["lines"])
    assert result["unresolved_ids"] == ["A1312/26"]


def test_an_unresolved_notice_records_the_runways_it_names_and_what_is_unresolved():
    # SQ352 15 Aug 2026 destination EKCH A1353/26.
    text = "RWY 04R/22L PAVEMENT STRUCTURE AND FRICTION MAY VARY ON AFFECTED RWY SURFACE PARTS DUE TO PARTIAL RESURFACING."
    result = analyse("EKCH", "22L", notice("A1353/26", text, "runway_approach_restriction", approach_affected=False))
    assert result["unresolved_detail"] == [
        {"notam_id": "A1353/26", "runways": ["04R/22L"], "reason": "effect", "names_planned": True},
    ]

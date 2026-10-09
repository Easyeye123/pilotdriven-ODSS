"""A taxiway closure is published with the places the notice names, whole.

Independent replay, 22 Sep 2026 16:10Z, of two real flights: the extent reader
cut VAAH A1134/26 to "TWY P between C and RAPID" and KJFK A3912/26 to "TWY A4
between A and TERMINAL 5". Its end point was one identifier or one "place word
plus identifier", so a named facility, a rapid exit taxiway or a taxilane was
cut at its first word; and its START point had to be a taxiway, so an extent
that starts at a runway, a ramp, a junction or a taxilane was not recognised
at all - the reader then fell back to the first taxiway it could find and
published the partial closure as a WHOLE taxiway ("TWY Q closed" for WSSS
A2510/26, "TXL Q3 AND TWY P7" being the bounds). The PDF's own reader had the
mirror image of that: its identifier grammar could not read two-letter
taxiways, so it published an extent's end point as the closed taxiway ("A/B"
for KJFK A8688/25, TWY KG between A and B).

Every notice below is quoted from its original OFP (flight and page given);
anything else is a labelled synthetic case. The rule is one grammar of the
places an extent can start or end at, read whole or not at all, shared by both
publication paths. It is not a list of these notices' answers.
"""
from __future__ import annotations

import pytest

from app.odss.airport_taxi_consequences import taxi_routing_scopes
from app.odss.engines import _further_taxiway_extents, _notam_operational_summary, _notam_subject

# Real notices, quoted from the original OFP item E.
VAAH_A1134 = ("0430-1230 PORTION OF TWY P BTN TWY C AND RAPID EXIT TWY R5 CLSD DUE PAVEMENT MAINT WORKS. "
              "PILOTS TO CARRY EXTRA FUEL AND EXP DLA DUE CONGESTION.")  # SQ365 07AUG26, p50
KJFK_A3912 = "JFK TWY A4 BTN TWY A AND TERMINAL 5 RAMP CLSD"  # SQ23 25JUL26, p39
EKCH_A1383 = ("FOLLOWING TWY ARE CLSD DUE TO WIP: TWY B BTN TWY Y AND RWY 12/30. "
              "TWY Y BTN TWY B AND DEICING PLATFORM B. TWY Z BTN TWY D AND DEICING PLATFORM B.")  # SQ352 15AUG26, p36
KJFK_A5882 = "TWY MA BTN TWY B AND TERMINAL 1 RAMP WIP IRREGULAR SFC ADJ EAST EDGE LGTD AND BARRICADED"  # SQ23, p38
KJFK_A2350 = "JFK TWY VA BTN TERMINAL 7 RAMP AND TWY A CLSD"  # SQ23, p40
KJFK_A398 = "JFK TWY TB BTN TERMINAL 8 RAMP AND TWY A CLSD"  # SQ23, p40
KJFK_A9155 = "JFK TWY PB BTN HANGAR 12 RAMP AND TWY Q CLSD"  # SQ23, p40
KJFK_A8968 = "JFK TWY Z BTN RWY 04L/22R AND TWY Y CLSD"  # SQ23, p40
KJFK_A8688 = "JFK TWY KG BTN TWY A AND TWY B CLSD"  # SQ23, p40
KJFK_A6400 = "TWY MB, TWY B BTN TWY Q AND TWY MA, TWY P BTN TWY B AND TWY N CLSD"  # SQ24 22JUL26, p36
KSFO_A3925 = ("TWY L BTN APCH END RWY 19L AND TWY C, TWY E BTN TWY V AND TWY L, "
              "TWY V BTN RWY 01L/19R AND TWY L CLSD")  # SQ34 15AUG26, p27
KSFO_A3927 = ("TWY A1, A2, L2, TWY F BTN TWY B AND TWY L, TWY A BTN TWY B AND TWY A1, TWY M1 BTN TWY B AND "
              "APCH END RWY 01L, TWY M BTN TWY B AND TWY L, TWY L BTN TWY A1 AND TWY G, TWY H BTN RWY 01L/19R "
              "AND RWY 01R/19L, TWY L BTN RWY 10R/28L AND TWY F CLSD")  # SQ34, p27
KLAX_A3579 = "TWY B7 BTN RWY 07L/25R AND TWY B CLSD"  # SQ38 29AUG26, p34
KLAX_A3788 = "TWY C BTN TXL C2 AND TWY C3 CLSD"  # SQ38, p34
KLAX_A4696 = "TWY C BTN TWY C3 AND TXL C3 CLSD"  # SQ38, p33
KLAX_A1974 = "LAX APRON TXL C9 NORTH OF GATE 46B CLSD"  # SQ38, p34
RKSI_A1303 = "TXL R17 BTN TXL R23 AND R24 CLSD DUE TO WIP - RMK : TXL R23 AND R24 NML OPS"  # SQ605 08SEP26, p26
EGLL_A2905 = "TWY BRAVO (SOUTH) CLSD BTN TWY ECHO AND TWY FOXTROT DUE WIP."  # SQ322 16AUG26, p31
LIRF_A3969 = ("APN TWY 'Y' CLOSED BTN ACFT STAND '837' AND ACFT STAND '846' (BOTH EXCLUDED). "
              "RMK: ICAO SGL PROVIDED REF AIP AD 2 LIRF 2-7")  # SQ365, p30
EGKK_SX67 = ("SX0067/25 AIP SUPPLEMENT EGKK/LONDON/GATWICK VALIDITY: 16JUL25-UFN TAXIWAY TANGO CLOSED "
             "NORTH OF TAXIWAY JULIET. DESTINATION ALTERNATE(S)")  # SQ314 15AUG26, p40
EDDF_A3047 = "TWY W SOUTH OF DP2 CLSD. TWY W9 CLSD."  # SQ326 16AUG26, p30
WSSS_A1566 = "TXL P7 BEHIND ACFT STAND E20 CLSD"  # SQ23, p41
WSSS_A2110 = ("FLW TWY CLSD DUE WIP: 1. TWY P8 BTN TWY P2 AND TWY N, INCLUDING JUNCTION OF TWY P8/TWY Q AND "
              "TWY P8/TWY P 2. TWY T BTN TWY P2 AND TWY P, INCLUDING JUNCTION OF TWY T/TWY Q/TWY T1 AND "
              "TWY T/TWY P")  # SQ365, p33
WSSS_A2230 = ("JUL 21-24 26-31 1600-2200, AUG 02-04 1600-2200 FLW TWY/TXL CLSD DUE WIP: 1. TWY Q BTN TWY W AND "
              "TXL Q1, INCLUDING JUNCTION OF TWY Q/TWY V 2. TWY V BTN TWY P AND TWY Q")  # SQ24 22JUL26, p30
WSSS_A2371 = ("FLW TWY CLSD DUE WIP: 1. TXL R1 BEHIND ACFT STAND E7 2. TWY T BTN TWY P5 AND TXL R3, "
              "INCLUDING ALL JUNCTIONS WITHIN 3. TWY T5.")  # SQ366 04AUG26, p31
WSSS_A2422 = ("TWY V BTN TWY V12 NORTHBOUND AND TWY V12 SOUTHBOUND, INCLUDING JUNCTION OF TWY V/TWY V8 "
              "CLSD DUE TO WIP.")  # SQ482 14AUG26, p17
WSSS_A2423 = ("AUG 12 14 15 0200-0900 TWY N2 BEHIND ACFT STANDS 504 TO 512, INCLUDING JUNCTIONS OF "
              "TWY N2/TWY V2 AND TWY N2/TWY V3 CLSD DUE WIP.")  # SQ24 15AUG26, p31
WSSS_A2508 = "TWY Q BTW TXL Q3 AND TWY P7 CLSD."  # SQ24 15AUG26, p31 - "BTW" as printed
WSSS_A2510 = "TWY Q BTN TXL Q3 AND TWY P7 CLSD."  # SQ279 15AUG26, p17
WSSS_A2593 = ("AUG 26-27 29 31 0200-0900, SEP 01-03 05 07-10 12 14-16 0200-0900 TWY N2 BEHIND ACFT STANDS "
              "507 AND 508 CLSD DUE WIP")  # SQ481 25AUG26, p20
WSSS_A2729 = ("FLW TWY CLSD DUE WIP: 1) TWY P8 BTN JUNCTION OF TWY P8/TXL N5/TWY K AND TWY P, INCLUDING "
              "JUNCTION OF TWY P8/TWY N 2) TWY N BTN TXL N4 AND TWY P8 3) TWY T BTN TWY Q AND TWY P, "
              "INCLUDING JUNCTION TWY P/TWY T.")  # SQ605, p31
WSSS_A2744 = ("SEP 08 11 15 1730-2130 FLW TWY CLSD DUE WIP: 1) TXL R1 BEHIND ACFT STANDS E6 TO E7 2) TXL R3 "
              "BEHIND ACFT STANDS F35R TO F36 3) TWY T BTN TWY P5 AND TWY R4 INCLUDING ALL JUNCTIONS WITHIN "
              "4) TWY T5 5) TWY T6")  # SQ605, p31
WSSS_A2748 = "TWY P2 BTN TXL P7 AND TWY P8 CLSD."  # SQ882 10SEP26, p22
WSSS_A2756 = "SEP 08 11 1730-2130 TWY D BTN TWY D7 SB AND TWY D6 NB CLSD DUE WIP."  # SQ605, p31
WSSS_A2757 = "SEP 10 0130-1000, 14 15 0530-0930 TXL N1 NB AFTER ACFT STAND 517L CLSD DUE WIP."  # SQ882 10SEP26, p22
EBBR_A2097 = "TWY OUT-6, B3 AND INT BTN THESE TWY CLSD DUE TO WIP"  # SQ303 16JUL26, p31
WSSS_A2511 = ("FLW TWY CLSD DUE WIP: I:TWY Q BTN TXL Q1 AND TXL Q3, INCLUDING JUNCTION OF TWY Q AND TXL Q3. "
              "II: TXL Q3 BTN TWY P AND TWY Q. III: TXL Q3 BEHIND ACFT STAND D38.")  # SQ279 15AUG26, p17
WSSS_SX68 = ("SX0068/26 AIP SUPPLMEMENT WSSS/SINGAPORE/CHANGI SINGAPORE CHANGI AIRPORT - TEMPORARY CLOSURE AT "
             "TAXIWAY W9 AND JUNCTION OF TAXIWAY W9, TAXIWAY W AND TAXIWAY R VALIDITY: 14MAY26 1430TC - 01OCT26 "
             "2130UTC 1 INTRODUCTION 1.1 TEMPO CLOSURE AT TWY W9 AND THE JUNCTION OF TWY W9, TWY W AND TWY R, IN "
             "SINGAPORE CHANGI AP, 2 DETAILS ON THE CLOSURE OF TWY W9 AND JUNCTION OF TWY W9, TWY W AND TWY R 2.1 "
             "TO FACILITATE UPCOMING CONSTRUCTION WORK ACTIVITIES, TWY W9 AND THE JUNCTION OF TWY W9, TWY W AND "
             "TAXIWAY R WILL BE CLOSED.")  # SQ194 16AUG26, p19
WSSS_SX174 = ("SX0174/24 AIP SUPPLEMENT WSSS/SINGAPORE/CHANGI SINGAPORE CHANGI AP CLOSURE OF TWY ASSOCIATED WITH "
              "RWY02R/20L VALIDITY: 28NOV24 - 22DEC27 CLOSURE OF TWY DETAILS OF THE CLOSURES ARE TABULATED BLW. "
              "TWY CLOSURE PERIOD: 28 NOV 2024, 0000UTC TO 22 DEC 2027, 2359UTC TWY A1, A2, A3, A4, A5, A6, A7, "
              "A8, A9, A10, A11, A12 TWY A TWY B1, B2, B3, B4, B5, B6, F, E, B7, B8, B9, B10, B11, B12, B13, B14 "
              "TWY B TWY G TWY G2, G3 TWY H TWY J8, J9, J10, J12 TWY L BTN TWY U13 C14 ALL MARKINGS LEADING INTO "
              "THE CLSD TWY WILL BE REMOVED.")  # SQ194 16AUG26, p21 (opening paragraphs)
WSSS_SX56 = ("SX0056/26 AIP SUPPLEMENT WSSS/SINGAPORE/CHANGI VALIDITY: 16APR26 0200UTC - 24DEC26 2359UTC "
             "SINGAPORE CHANGI AP - CLOSURE OF TWY C AND K INTRODUCTION: CLOSURE OF TWY C AND K 2.1 TO "
             "FACILITATE UPCOMING CONST WORK ACTIVITIES, TWY C AND K WILL BE CLSD. 2.2 ALL MARKINGS LEADING "
             "INTO THE CLSD TWY WILL BE REMOVED.")  # SQ194 16AUG26, p19 (opening paragraphs)


@pytest.mark.parametrize(("source", "subject"), [
    # The two reported end points, read whole.
    (VAAH_A1134, "TWY P between C and RAPID EXIT TWY R5"),
    (KJFK_A3912, "TWY A4 between A and TERMINAL 5 RAMP"),
    (KJFK_A5882, "TWY MA between B and TERMINAL 1 RAMP"),
    # The SQ352 control: a runway end point and a named platform.
    (EKCH_A1383, "TWY B between Y and RWY 12/30"),
    # Start points that are not taxiways - each used to publish a whole taxiway.
    (KJFK_A2350, "TWY VA between TERMINAL 7 RAMP and A"),
    (KJFK_A398, "TWY TB between TERMINAL 8 RAMP and A"),
    (KJFK_A9155, "TWY PB between HANGAR 12 RAMP and Q"),
    (KJFK_A8968, "TWY Z between RWY 04L/22R and Y"),
    (KLAX_A3579, "TWY B7 between RWY 07L/25R and B"),
    (KSFO_A3925, "TWY L between APCH END RWY 19L and C"),
    (WSSS_A2729, "TWY P8 between P8/TXL N5/K junction and P"),
    # A taxilane is not the taxiway of the same letter: its kind is kept.
    (WSSS_A2510, "TWY Q between TXL Q3 and P7"),
    (WSSS_A2748, "TWY P2 between TXL P7 and P8"),
    (KLAX_A3788, "TWY C between TXL C2 and C3"),
    (KLAX_A4696, "TWY C between C3 and TXL C3"),
    (WSSS_A2371, "TWY T between P5 and TXL R3"),
    (WSSS_A2230, "TWY Q between W and TXL Q1"),
    # Directional taxiway end points.
    (WSSS_A2756, "TWY D between D7 SB and D6 NB"),
    (WSSS_A2422, "TWY V between V12 NORTHBOUND and V12 SOUTHBOUND"),
    # Two-letter and phonetic names, a taxilane extent, the closure stated first.
    (KJFK_A8688, "TWY KG between A and B"),
    (RKSI_A1303, "TXL R17 between R23 and R24"),
    (EGLL_A2905, "TWY BRAVO (SOUTH) between ECHO and FOXTROT"),
    (LIRF_A3969, "TWY Y between ACFT STAND 837 and ACFT STAND 846"),
])
def test_an_extent_is_published_with_both_places_whole(source, subject):
    assert _notam_subject(source, "taxiway_closure") == subject


@pytest.mark.parametrize(("source", "subject"), [
    (EGKK_SX67, "TWY TANGO north of JULIET"),
    (EDDF_A3047, "TWY W south of DP2"),
    (WSSS_A2423, "TWY N2 behind stands 504 to 512"),
    (WSSS_A2593, "TWY N2 behind stands 507 and 508"),
])
def test_a_partial_closure_that_is_not_an_extent_keeps_its_scope(source, subject):
    assert _notam_subject(source, "taxiway_closure") == subject


@pytest.mark.parametrize(("source", "subject"), [
    (WSSS_A1566, "TXL P7 behind stand E20"),
    (KLAX_A1974, "TXL C9 north of GATE 46B"),
    (WSSS_A2757, "part of TXL N1 NB"),
])
def test_a_taxilane_named_outside_an_extent_states_its_own_scope(source, subject):
    """A taxilane is a designation (10 Oct 2026; was the generic "taxiway operational area").

    Reading taxilanes outside an extent once picked the wrong sentence out of long AIP supplements (WSSS SX83/24 names
    TXL R2 first in a decommissioning clause). The subject reader now takes the first designation, lets a later stated
    scope of the same designation replace a bare list-header mention (SX83/24 reads "TXL R1 behind stand E5"), and never
    takes a plain word for a name (SX168/26's "TWY GUIDANCE SIGNS"); a scope it cannot read stays "part of".
    """
    assert _notam_subject(source, "taxiway_closure") == subject


@pytest.mark.parametrize(("source", "subject"), [
    # Real: the source prints "BTW", which is not a bound this reader knows.
    (WSSS_A2508, "part of TWY Q"),
    # Labelled synthetic: an adjective with nothing after it is not an end point.
    ("TWY P BTN TWY C AND RAPID CLSD", "part of TWY P"),
    # Labelled synthetic: a facility cut at its number is not the facility.
    ("TWY A4 BTN TWY A AND TERMINAL 5 CLSD", "part of TWY A4"),
    # Labelled synthetic: a bound that is never closed.
    ("TWY A BTN TWY B CLSD", "part of TWY A"),
    # Labelled synthetic: words after the end point that are not a boundary.
    ("TWY A BTN TWY B AND TWY C WINGTIP CLEARANCE REDUCED", "part of TWY A"),
])
def test_an_unreadable_scope_is_partial_and_unresolved_never_whole_or_truncated(source, subject):
    assert _notam_subject(source, "taxiway_closure") == subject


@pytest.mark.parametrize(("source", "subject"), [
    ("TWY Y CLSD DUE TO WIP", "TWY Y"),
    ("TWY C AND K WILL BE CLSD.", "TWY C"),
    (EBBR_A2097, "TWY OUT-6"),
    (WSSS_SX56, "TWY C"),
    # Pinned before this change and unchanged by it.
    ("TWY B BTN TWY Y AND TWY Z CLSD.", "TWY B between Y and Z"),
    ("PART OF MIKE TWY CLSD TO ACFT WITH ENGINE ON. ACFT WITH ENGINES ON PROHIBITED FROM TAXIING ON "
     "TWY M BTN TWY BM3 AND BM5 EXCLUDED.", "TWY M between BM3 and BM5"),
])
def test_a_whole_closure_still_reads_as_one(source, subject):
    assert _notam_subject(source, "taxiway_closure") == subject


def _summary(source):
    return _notam_operational_summary(source, "taxiway_closure", "destination")


def test_the_sq352_control_keeps_its_end_point_and_its_further_extents():
    assert _summary(EKCH_A1383) == (
        "TWY B BETWEEN Y AND RWY 12/30 closed during the applicable destination window. "
        "This notice states 2 further closed taxiway extent(s); the full record is held with the "
        "airport's notices."
    )
    assert _further_taxiway_extents(EKCH_A1383) == 2


@pytest.mark.parametrize(("source", "remaining"), [
    # Extents that start at a runway, an approach end or a junction are counted.
    (KSFO_A3925, "This notice states 2 further closed taxiway extent(s)"),
    (WSSS_A2729, "This notice states 2 further closed taxiway extent(s)"),
    (WSSS_A2230, "This notice states 1 further closed taxiway extent(s)"),
    (WSSS_A2110, "This notice states 1 further closed taxiway extent(s)"),
    # Whole taxiways and stand-access segments listed beside the extents.
    (KJFK_A6400, "This notice states 2 further closed taxiway item(s)"),
    (KSFO_A3927, "This notice states 9 further closed taxiway item(s)"),
    (WSSS_A2744, "This notice states 4 further closed taxiway item(s)"),
    (EDDF_A3047, "This notice states 1 further closed taxiway item(s)"),
    # Roman list markers, taxilane extents and a stand-access segment.
    (WSSS_A2511, "This notice states 2 further closed taxiway item(s)"),
    # A supplement's prose cannot be itemised exactly; it still says so.
    (WSSS_SX56, "This notice states further closed taxiway items"),
    (EBBR_A2097, "This notice states further closed taxiway items"),
])
def test_further_closed_items_are_never_dropped_silently(source, remaining):
    assert f" {remaining}; the full record is held with the airport's notices." in _summary(source)


@pytest.mark.parametrize("source", [VAAH_A1134, KJFK_A3912, KJFK_A8688, WSSS_A2510, "TWY Y CLSD DUE TO WIP"])
def test_a_single_item_notice_claims_nothing_further(source):
    assert "further" not in _summary(source)


@pytest.mark.parametrize("source", [WSSS_SX68, WSSS_SX174])
def test_a_subject_that_already_names_every_item_claims_nothing_further(source):
    """A compound junction subject and a tabulated list name the whole closure."""
    summary = _summary(source)
    assert "further" not in summary
    assert summary.startswith(("TWY W9 AND W9/W/R JUNCTION", "TWYS A, A1-A12"))


def test_an_unresolved_extent_says_its_bounds_are_unread():
    assert _summary("TWY P BTN TWY C AND RAPID CLSD") == (
        "PART OF TWY P closed during the applicable destination window. Its bounds could not be read "
        "completely from the notice; the full record is held with the airport's notices."
    )


@pytest.mark.parametrize(("source", "scopes"), [
    # The PDF path used to publish an end point as the closed taxiway.
    (KJFK_A8688, ["KG between A and B"]),
    (KJFK_A2350, ["VA between TERMINAL 7 RAMP and A"]),
    (KJFK_A398, ["TB between TERMINAL 8 RAMP and A"]),
    (KJFK_A9155, ["PB between HANGAR 12 RAMP and Q"]),
    # ...and could not read a named end point at all.
    (KJFK_A3912, ["A4 between A and TERMINAL 5 RAMP"]),
    (VAAH_A1134, ["P between C and RAPID EXIT TWY R5"]),
    (KLAX_A3579, ["B7 between RWY 07L/25R and B"]),
    # A taxilane end point keeps its kind.
    (WSSS_A2510, ["Q between TXL Q3 and P7"]),
    (WSSS_A2729, ["P8 between P8/TXL N5/K junction and P, including P8/N junction",
                  "N between TXL N4 and P8", "T between Q and P, including P/T junction"]),
    # Unchanged: same-kind end points, directions, lists and stand access.
    (RKSI_A1303, ["R17 between R23 and R24"]),
    (WSSS_A2756, ["D between D7 SB and D6 NB"]),
    (WSSS_A2744, ["R1 behind stands E6/E7", "R3 behind stands F35R/F36",
                  "T between P5 and R4, including intervening junctions", "T5", "T6"]),
])
def test_the_pdf_reads_the_same_places(source, scopes):
    assert taxi_routing_scopes(source) == scopes


@pytest.mark.parametrize("source", [
    "TWY P BTN TWY C AND RAPID CLSD",
    "TWY A4 BTN TWY A AND TERMINAL 5 CLSD",
    "TWY A AND OTHERS CLSD",
])
def test_the_pdf_publishes_nothing_it_cannot_read_whole(source):
    assert taxi_routing_scopes(source) == []

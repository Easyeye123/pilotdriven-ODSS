from copy import deepcopy

import pytest

from app.odss.airport_pdf_analysis import analyse_airport_for_pdf
from app.odss.airport_taxi_consequences import taxi_routing_scopes


@pytest.mark.parametrize(('source', 'expected'), [
    ('TXL R17 BTN TXL R23 AND R24 CLSD DUE TO WIP - RMK : TXL R23 AND R24 NML OPS',
     ['R17 between R23 and R24']),
    ('TWY D BTN TWY D7 SB AND TWY D6 NB CLSD DUE WIP.', ['D between D7 SB and D6 NB']),
    ('FLW TWY CLSD DUE WIP: 1) TWY T BTN TWY P5 AND TWY R4 INCLUDING ALL JUNCTIONS WITHIN 2) TWY T5 3) TWY T6',
     ['T between P5 and R4, including intervening junctions', 'T5', 'T6']),
    ('FLW TWY CLSD DUE WIP: 1) TWY P8 BTN JUNCTION OF TWY P8/TXL N5/TWY K AND TWY P, INCLUDING JUNCTION OF TWY P8/TWY N 2) TWY N BTN TXL N4 AND TWY P8',
     ['P8 between P8/N5/K junction and P, including P8/N junction', 'N between N4 and P8']),
    ('TXL R1 BEHIND ACFT STANDS E6 TO E7 CLSD.', ['R1 behind stands E6/E7']),
    ('TWY C AND K WILL BE CLSD.', ['C/K']),
    ('TWY W9 AND THE JUNCTION OF TWY W9, TWY W AND TAXIWAY R WILL BE CLOSED.', ['W9 and W9/W/R junction']),
    ('TWY CLOSURE PERIOD: 28 NOV 2024 TO 22 DEC 2027 TWY A1, A2, A3 TWY B TWY L BTN TWY U13 C14 ALL MARKINGS LEADING INTO THE CLSD TWY WILL BE REMOVED.',
     ['A1-A3', 'B', 'L between U13 and C14']),
])
def test_closed_subjects_keep_their_bounds_and_list_siblings(source, expected):
    assert taxi_routing_scopes(source) == expected


def test_pdf_uses_routing_scope_and_timing_without_changing_airport_cards():
    panel = {'icao':'RKSI', 'selected_notams':[{
        'notam_id':'A1303/26', 'source_page':26,
        'item_e_text':'TXL R17 BTN TXL R23 AND R24 CLSD DUE TO WIP - RMK : TXL R23 AND R24 NML OPS',
        'pertinence_kind':'taxiway_closure', 'valid_from_utc':'2026-09-08T15:00:00Z',
        'referenceAt':'2026-09-08T14:50:00Z', 'stateAtReference':'begins_after_reference',
    }]}
    original = deepcopy(panel)
    lines = analyse_airport_for_pdf(panel, role='departure', planned_runway='33R')['lines']
    assert lines[0]['segments'] == ['R17 between R23 and R24 (A1303/26)']
    assert '10 min after departure' in lines[0]['text']
    assert panel == original


@pytest.mark.parametrize('source', [
    'TWY A NOT CLSD. TWY B NML OPS.',
    'TWY A WILL NOT BE CLOSED.',
    'TWY A EXCEPT B CLSD.',
    'TWY A BTN UNSPECIFIED BOUNDS CLSD.',
])
def test_negative_or_unknown_extents_do_not_become_whole_taxiway_restrictions(source):
    assert taxi_routing_scopes(source) == []

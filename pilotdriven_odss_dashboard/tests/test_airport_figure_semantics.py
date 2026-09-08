from copy import deepcopy

import fitz
import pytest
from reportlab.pdfgen.canvas import Canvas

from app.odss.concise_pdf_gate import check_airport_figure_states
from app.odss.operational_format import analysed_airport_overlay, draw_airport_figure


def _overlay():
    return {'bounds': {'west': 1, 'south': 1, 'east': 2, 'north': 2}, 'mapped': [],
            'featureCollection': {'features': [{'id':'way/1', 'properties': {'featureId':'way/1', 'aeroway':'runway', 'ref':'01/19'},
                'geometry': {'type':'LineString', 'coordinates': [[1.2,1.2],[1.8,1.8]]}}]}}


def _analysis(state):
    return {'icao':'ZZZZ', 'surface_effects': [{'notam_id':'A1234/26', 'runways':['01','19'],
        'markClass':'closure', 'scope':'whole_entity', 'stateAtReference':state}]}


@pytest.mark.parametrize(('state','expected'), [('active_at_reference',0xFF5267),
    ('begins_after_reference',0xFFBC38), ('ended_before_reference',0x50D5EF)])
def test_physical_runway_colour_follows_flight_state_without_mutating_app(tmp_path, state, expected):
    original = _overlay()
    original['mapped'] = [{'notamNumber':'A1234/26', 'entityType':'runway', 'featureIds':['way/1'],
                          'markClass':'closure', 'scope':'whole_entity', 'stateAtReference':'active_at_reference'}]
    before = deepcopy(original)
    analysis = _analysis(state)
    overlay = analysed_airport_overlay(original, analysis)
    path = tmp_path / 'figure.pdf'
    canvas = Canvas(str(path), pagesize=(600,400))
    draw_airport_figure(canvas, overlay, 10, 10, 580, 380, planned_runway='01')
    canvas.save()
    with fitz.open(path) as pdf:
        spans = [s for b in pdf[0].get_text('dict')['blocks'] for line in b.get('lines',[]) for s in line['spans']]
        assert next(s for s in spans if s['text'] == '01/19')['color'] == expected
        assert check_airport_figure_states(pdf[0], original, analysis) == []
    assert original == before


def test_another_active_notice_remains_effective_when_one_closure_ends():
    original = _overlay()
    original['mapped'] = [{'notamNumber':'A9999/26', 'entityType':'runway', 'featureIds':['way/1'],
                          'markClass':'closure', 'scope':'whole_entity', 'stateAtReference':'active_at_reference'}]
    result = analysed_airport_overlay(original, _analysis('ended_before_reference'))
    assert result['mapped'][0] == original['mapped'][0]


def test_gate_rejects_old_grey_figure_despite_correct_written_consequence(tmp_path):
    path = tmp_path / 'wrong.pdf'
    canvas = Canvas(str(path), pagesize=(600,400))
    draw_airport_figure(canvas, _overlay(), 10, 10, 580, 350)
    canvas.drawString(10, 380, 'RWY 01/19 closed at this flight arrival (A1234/26).')
    canvas.save()
    with fitz.open(path) as pdf:
        violations = check_airport_figure_states(pdf[0], _overlay(), _analysis('active_at_reference'))
        assert {v['code'] for v in violations} == {'RUNWAY_FIGURE_STATE','RUNWAY_FIGURE_STROKE'}

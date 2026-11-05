"""Production six-page publication acceptance; historical audit is separate."""
from copy import deepcopy

import fitz
import pytest

from generate_visual_samples import sample_findings, sample_flight
from app.odss.combined_brief import render_combined_briefing
from app.odss.concise_pdf_gate import (AIRPORTS_PAGE, ASSURANCE_PAGE,
                                       MAX_BRIEFING_PAGES, NAV_RIBBON,
                                       PAGE_TITLES, check_concise_pdf, normalized)
from app.odss.operational_format import Card, plan_page
from app.odss.airport_pdf_analysis import analyse_airport_for_pdf
from scripts.run_private_cfp_corpus import scan_physical_pdf


def findings():
    return [f for f in sample_findings() if f['engine'] != 'depressurisation']


@pytest.fixture
def published(tmp_path):
    path = tmp_path / 'briefing.pdf'
    render_combined_briefing(sample_flight(), findings(), [], path)
    return path


def test_production_has_six_readable_pages_and_working_navigation(published):
    assert check_concise_pdf(published, flight=sample_flight())['valid']
    with fitz.open(published) as doc:
        assert len(doc) == MAX_BRIEFING_PAGES
        assert len(doc.get_toc()) == MAX_BRIEFING_PAGES
        for index, (title, page) in enumerate(zip(PAGE_TITLES, doc)):
            folded = normalized(page.get_text())
            assert normalized(title) in folded
            assert all(normalized(item) in folded for item in NAV_RIBBON)
            assert normalized(f'Page {index + 1} of 6') in folded
            for block in page.get_text('dict')['blocks']:
                for line in block.get('lines', []):
                    for span in line['spans']:
                        assert span['size'] >= 8.9
            assert any(l.get('page') == 0 for l in page.get_links())
    physical = scan_physical_pdf(published)
    assert physical['valid'], physical['violations']


def test_overflow_fails_instead_of_truncating_or_adding_source_pages():
    with pytest.raises(ValueError, match='capacity exceeded'):
        plan_page('TEST', 'test', [(80, [Card('LINES', ['long ' * 300])])])


@pytest.mark.parametrize('mutation,code', [
    ('extra_page', 'CONCISE_PAGE_CEILING'),
    ('raw_record', 'RAW_ITEM_E_IN_BODY'),
    ('copied_run', 'RAW_ITEM_E_IN_BODY'),
    ('raw_label', 'RAW_NOTAM_PUBLICATION'),
    ('warning', 'REPEATED_ITEM_WARNING'),
    ('attachment', 'SOURCE_ATTACHMENT'),
])
def test_publication_gate_rejects_regressions(published, tmp_path, mutation, code):
    raw = 'RWY 02L CLSD FOR SURFACE WORK FROM NORTH END TO SOUTH END EXCEPT EMERGENCY OPERATIONS SUBJECT TO PRIOR COORDINATION'
    target = tmp_path / 'mutated.pdf'
    with fitz.open(published) as doc:
        if mutation == 'extra_page':
            doc.new_page()
        elif mutation == 'attachment':
            doc.embfile_add('source.txt', raw.encode())
        else:
            value = {'raw_record': raw, 'copied_run': ' '.join(raw.split()[:18]), 'raw_label': 'ITEM E', 'warning': 'REVIEW REQUIRED'}[mutation]
            doc[AIRPORTS_PAGE].insert_textbox(fitz.Rect(30, 115, 810, 220), value, fontsize=10)
        doc.save(target)
    result = check_concise_pdf(target, flight={'notams': [{'notam_id': 'A1/26', 'text': raw}]})
    assert code in {v['code'] for v in result['violations']}


def test_analysed_consequence_and_ids_must_be_on_the_owning_airport_page(published):
    analysis = [{'icao': 'WSSS', 'role': 'destination', 'lines': [{'text': 'RWY 02L closure begins 10 min after arrival (A1/26)', 'notam_ids': ['A1/26']}]}]
    result = check_concise_pdf(published, airport_analysis=analysis)
    assert 'ANALYSED_LINE_PARITY' in {v['code'] for v in result['violations']}


def notice(raw, **fields):
    return {'notam_id': 'A1/26', 'item_e_text': raw, 'pertinence_kind': 'approach_navaid_closure', 'approach_affected': True, 'stateAtReference': 'active_at_reference', 'referenceAt': '2026-07-11T10:30:00Z', 'applicability': 'active', **fields}


def analyse(record, runway='02L'):
    return analyse_airport_for_pdf({'icao': 'WSSS', 'selected_notams': [record]}, role='destination', planned_runway=runway)


def test_dme_component_does_not_remove_ils():
    result = analyse(notice('ILS/DME CH38X, DME PART U/S DUE TO TECH REASON'))
    line = result['lines'][0]['text']
    assert 'DME' in line and 'A1/26' in line and 'ILS' not in line
    assert '11 JUL 1030Z' in line


@pytest.mark.parametrize('raw', [
    "LOC 'IGD' 109.5 RWY 21 SUBJ TO INTRP POSSIBLE SIGNAL OSCILLATIONS DUE CRANE OPS",
    'PARALLEL APPROACH OPERATIONS MAY BE SUSPENDED WHEN ADVISED BY ATC',
    'ILS RWY 02L NOT REPORTED UNSERVICEABLE',
])
def test_conditional_or_interference_is_not_an_outage(raw):
    result = analyse(notice(raw))
    assert result['lines'] == []
    assert result['unresolved_ids'] == ['A1/26']


def test_future_closure_is_tied_to_planned_movement_time():
    result = analyse(notice('RWY 02L CLSD', pertinence_kind='runway_closure', approach_affected=False, stateAtReference='begins_after_reference', valid_from_utc='2026-07-11T10:40:00Z'))
    line = result['lines'][0]['text']
    assert 'begins 10 min after arrival 11 JUL 1030Z' in line
    assert 'planned RWY 02L is affected' in line


def test_other_runway_schedule_still_has_a_flight_time_consequence():
    record = notice('RWY 02C/20C WILL BE CLSD BTN 1730UTC TO 2130UTC EV TUE AND FRI FM 30SEP25 TO 31MAR27',
                    pertinence_kind='runway_closure', approach_affected=False,
                    referenceAt='2026-09-08T21:00:00Z', applicability='review', stateAtReference='unknown_at_reference')
    line = analyse(record, runway='20R')['lines'][0]['text']
    assert '02C/20C closes 1730-2130Z' in line and '2100Z is within the closure' in line
    assert 'Planned RWY 20R differs' in line
    assert 'A1/26' in line
    record['referenceAt'] = '2026-09-07T21:00:00Z'
    assert analyse(record, runway='20R')['lines'] == []


def test_will_not_be_available_for_civil_use_is_not_lost():
    record = notice('RWY 02R/20L WILL NOT BE AVBL FOR CIV USE. RWY 02L/20R REMAINS AVAILABLE.',
                    pertinence_kind='runway_approach_restriction', approach_affected=False)
    line = analyse(record, runway='20R')['lines'][0]['text']
    assert '02R/20L not available for civil use at arrival 11 JUL 1030Z' in line
    assert 'this does not close planned RWY 20R' in line
    assert 'RWY 02R/20L, 02L/20R not available' not in line


def test_unknown_schedule_has_one_closing_owner():
    result = analyse(notice('ILS RWY 02L U/S DLY AT TIMES ADVISED', stateAtReference='unknown_at_reference', applicability='review'))
    assert result['lines'] == [] and result['unresolved_ids'] == ['A1/26']


def test_separate_role_window_wins_over_airport_wide_state():
    record = notice('ILS RWY 02L U/S', role_applicability=[{'role': 'destination', 'stateAtReference': 'outside_schedule_at_reference', 'referenceAt': '2026-07-11T10:30:00Z', 'applicability': 'active'}])
    result = analyse(record)
    assert 'outside the active schedule' in result['lines'][0]['text']


def test_pdf_projection_does_not_mutate_dashboard_airport_analysis():
    panel = {'icao': 'WSSS', 'selected_notams': [notice('ILS RWY 02L U/S')], 'card_summary_lines': [{'text': 'existing dashboard analysis'}]}
    original = deepcopy(panel)
    analyse_airport_for_pdf(panel, role='destination', planned_runway='02L')
    assert panel == original


def test_outage_does_not_include_a_different_serviceable_system():
    result = analyse(notice('DME U/S; ILS RWY 02L AVAILABLE'))
    assert 'DME' in result['lines'][0]['text']
    assert 'ILS' not in result['lines'][0]['text']


def test_split_geometry_has_one_readable_label_per_runway(tmp_path):
    from reportlab.pdfgen import canvas
    from app.odss.operational_format import draw_airport_figure, SIZE
    overlay = {'bounds': {'west': 0, 'south': 0, 'east': 1, 'north': 1},
        'featureCollection': {'features': [
            {'type': 'Feature', 'properties': {'aeroway': 'runway', 'ref': '03/21'},
             'geometry': {'type': 'LineString', 'coordinates': coords}}
            for coords in [[[0.3, 0.1], [0.5, 0.5]], [[0.5, 0.5], [0.7, 0.9]]]
        ]}}
    path = tmp_path / 'geometry.pdf'
    c = canvas.Canvas(str(path), pagesize=SIZE)
    draw_airport_figure(c, overlay, 28, 250, 785, 243, planned_runway='03')
    c.save()
    with fitz.open(path) as doc:
        assert doc[0].get_text().count('03/21') == 1
    assert scan_physical_pdf(path)['valid']


def test_short_item_e_record_is_also_rejected(published, tmp_path):
    path = tmp_path / 'short-source.pdf'
    with fitz.open(published) as doc:
        doc[AIRPORTS_PAGE].insert_text((30, 140), 'RWY 02L CLSD')
        doc.save(path)
    result = check_concise_pdf(path, flight={'notams': [{'notam_id': 'A1/26', 'text': 'RWY 02L CLSD'}]})
    assert 'RAW_ITEM_E_IN_BODY' in {v['code'] for v in result['violations']}


def test_notam_id_outside_consequence_is_rejected(published, tmp_path):
    path = tmp_path / 'stray-id.pdf'
    with fitz.open(published) as doc:
        doc[ASSURANCE_PAGE].insert_text((30, 140), 'A9999/26')
        doc.save(path)
    result = check_concise_pdf(path, airport_analysis=[])
    assert 'NON_INLINE_NOTAM_ID' in {v['code'] for v in result['violations']}


def test_available_component_does_not_override_a_separate_outage():
    result = analyse(notice('DME PART AVAILABLE; ILS RWY 02L U/S'))
    line = result['lines'][0]['text']
    assert 'ILS' in line
    assert 'DME' not in line

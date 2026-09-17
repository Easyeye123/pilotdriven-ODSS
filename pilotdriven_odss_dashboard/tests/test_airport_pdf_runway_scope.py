"""Airport PDF claims must use the runway and movement condition of the source clause."""
import copy
import json
from pathlib import Path

import pytest

from app.odss.airport_pdf_analysis import analyse_airport_for_pdf

HELD = json.loads((Path(__file__).parent/'fixtures/lirf_conditional_runway_notice.json').read_text())


def analyse(record=None, planned='34L'):
    return analyse_airport_for_pdf({'icao':'LIRF','selected_notams':[record or HELD['notice']]},
                                   role='departure',planned_runway=planned)


def test_real_lirf_tsat_eldt_conditions_cannot_become_closure_at_scheduled_departure():
    before=copy.deepcopy(HELD['notice'])
    result=analyse()
    assert result['lines']==[], result['lines']
    assert result['surface_effects']==[]
    assert result['unresolved_ids']==['A2314/26']
    assert HELD['notice']==before


@pytest.mark.parametrize('suffix', [
    ' ACFT CONCERNED SHALL PLAN RWY 16L/34R FOR TKOF AND LDG OPS.',
    ' RWY 16L/34R AVAILABLE.',
    ' TAXI VIA TWY A TO RWY 16L/34R.',
])
def test_other_runway_reference_cannot_inherit_a_direct_closure(suffix):
    record={**HELD['notice'],'item_e_text':'RWY 16R/34L CLSD.'+suffix}
    result=analyse(record,planned='34R')
    assert len(result['lines'])==1
    line=result['lines'][0]['text']
    assert 'RWY 16R/34L closed' in line
    assert '16L/34R' not in line
    assert 'this does not close planned RWY 34R' in line


@pytest.mark.parametrize('condition', ['IF ADVISED BY ATC','WHEN LOW VISIBILITY PROCEDURES ARE IN FORCE','FOR ACFT WITH TSAT BETWEEN 2130-0445'])
def test_unheld_operational_condition_stays_unresolved_even_with_active_metadata(condition):
    record={**HELD['notice'],'notam_id':'TEST9/26','item_e_text':f'RWY 16R/34L CLSD {condition}.'}
    result=analyse(record)
    assert result['lines']==[]
    assert result['unresolved_ids']==['TEST9/26']


def test_two_independently_closed_runways_are_both_retained():
    record={**HELD['notice'],'item_e_text':'RWY 16R/34L CLSD. RWY 16L/34R CLOSED.'}
    line=analyse(record)['lines'][0]['text']
    assert '16R/34L' in line and '16L/34R' in line


@pytest.mark.parametrize(('filename','mode'), [
    ('SQ36507082026FCO.pdf','conditional-runway'),
    ('lido-briefing_SQ_34_15Aug2026_SIN_SFO.pdf','taxi-exception'),
    ('lido-briefing_SQ_482_14Aug2026_SIN_JNB.pdf','charts'),
    ('SQ48125082026JNB.pdf','charts'),
])
def test_fresh_download_keeps_source_scope_and_unresolved_conditions_visible(filename,mode,tmp_path):
    import fitz
    from app.analysis import run_odss_analysis
    from app.odss.briefing import build_briefing_view
    from app.odss.combined_brief import render_combined_briefing

    source=Path(__file__).resolve().parents[2]/'private_cfp_corpus'/filename
    if not source.is_file():
        pytest.skip(f'private source {filename} not available')
    result=run_odss_analysis(source,tmp_path/'analysis',tmp_path/'reports',1)
    payload=json.loads(Path(result['analysis_path']).read_text())
    flight=payload['flight']; findings=payload['findings']; warnings=payload['view']['warnings']
    view=build_briefing_view(flight,findings,warnings,weather_charts=payload.get('weather_charts') or {})
    path=tmp_path/'Flight_Briefing.pdf'
    render_combined_briefing(flight,findings,warnings,path,weather_charts=payload.get('weather_charts') or {})
    with fitz.open(path) as pdf:
        airport=' '.join(pdf[3].get_text().split())
        closing=' '.join(pdf[5].get_text().split())
        if mode=='conditional-runway':
            departure=next(row for row in view['airport_pdf_analysis'] if row['icao']=='LIRF')
            assert 'A2314/26' in departure['unresolved_ids']
            assert not any('A2314/26' in row['notam_ids'] for row in departure['lines'])
            assert '16R/34L, 16L/34R closed' not in airport
            assert 'TSAT/ELDT runway-availability conditions' in closing
        elif mode=='taxi-exception':
            destination=next(row for row in view['airport_pdf_analysis'] if row['icao']=='KSFO')
            assert {'A3918/26','A3920/26'} <= set(destination['unresolved_ids'])
            assert 'RWY 01L/19R closed to the affected movement' not in airport
            assert 'runway closure and taxi-exception extent' in closing
        else:
            for chart in ['ILS Z RWY 03L','VOR Z RWY 21R','RNAV (GNSS) RWY 21L']:
                assert chart in airport
            assert 'Published approach charts suspended' in airport
            assert 'RWY 03L, 21R, 03R, 21L ILS/VOR' not in airport


SCOPE_SOURCES=json.loads((Path(__file__).parent/'fixtures/airport_publication_source_scopes.json').read_text())


@pytest.mark.parametrize('notice_id', ['A3918/26','A3920/26'])
def test_taxi_exception_is_not_erased_by_an_unqualified_runway_closure(notice_id):
    record={**HELD['notice'],**SCOPE_SOURCES[notice_id]}
    result=analyse(record,planned='28R')
    assert result['lines']==[]
    assert result['unresolved_ids']==[notice_id]


@pytest.mark.parametrize(('notice_id','expected','forbidden'), [
    ('A2888/26', ['ILS Z RWY 03L','VOR Z RWY 21R','RNAV (GNSS) RWY 03R','RNAV (GNSS) RWY 21L'], ['ILS/VOR','RWY 03L, 21R']),
    ('A2891/26', ['VOR Y RWY 21R','ILS Y RWY 03L','ILS X RWY 03R','ILS W RWY 03R'], ['VOR/ILS','RWY 21R, 03L']),
    ('A2654/26', ['VOR Z RWY 01','RNAV (GNSS) RWY 01','RNAV (GNSS) RWY 19'], ['RWY 01, 19 VOR']),
    ('A2885/26', ['ILS Z RWY 06 CAT II','ILS Z RWY 24 CAT II'], ['RWY 06, 24 ILS']),
])
def test_suspended_or_withdrawn_charts_keep_each_procedure_bound_to_its_runway(notice_id,expected,forbidden):
    record={**HELD['notice'],**SCOPE_SOURCES[notice_id], 'pertinence_kind':'approach_navaid_closure','approach_affected':True}
    result=analyse(record)
    line=' '.join(row['text'] for row in result['lines'])
    assert 'approach charts' in line.lower(), line
    assert 'suspended' in line.lower() or 'withdrawn' in line.lower()
    assert 'Unavailable approach aids' not in line
    for subject in expected:assert subject in line
    for overclaim in forbidden:assert overclaim not in line


def test_unknown_or_conditional_chart_clause_does_not_fall_through_to_aid_outage():
    source=SCOPE_SOURCES['A2888/26']
    raw=source['item_e_text'].replace('SUSPENDED.','MAY BE SUSPENDED IF ADVISED.',1)
    record={**HELD['notice'],**source,'item_e_text':raw,'pertinence_kind':'approach_navaid_closure','approach_affected':True}
    result=analyse(record)
    assert result['lines']==[]
    assert result['unresolved_ids']==['A2888/26']


def test_a_chart_status_with_a_trailing_condition_stays_unresolved():
    source=SCOPE_SOURCES['A2885/26']
    record={**HELD['notice'],**source,'item_e_text':source['item_e_text'].replace('WITHDRAWN.','WITHDRAWN IF ADVISED BY ATC.',1),
            'pertinence_kind':'approach_navaid_closure','approach_affected':True}
    result=analyse(record)
    assert result['lines']==[] and result['unresolved_ids']==['A2885/26']


@pytest.mark.parametrize('suffix', [
    'BTN TWY A AND TWY B',
    'TO ACFT WITH WINGSPAN MORE THAN 36M',
    'FROM INTERSECTION A TO RWY END',
    'FOR ACFT ABOVE 20 TONNES',
    'TO NON BASED AIRCRAFT',
    'DUE WIP BTN TWY A AND TWY B',
    'DUE TO MAINT ONLY FOR ACFT ABOVE 20 TONNES',
])
def test_unrecognised_closure_scope_is_not_discarded(suffix):
    record={**HELD['notice'],'item_e_text':f'RWY 16R/34L CLSD {suffix}.'}
    result=analyse(record)
    assert result['lines']==[] and result['unresolved_ids']==['A2314/26']


@pytest.mark.parametrize('raw', [
    'RWY 16R/34L CLSD DUE WIP.',
    'DAILY 1010-1025 2300-2345 RWY 04/22 CLSD DUE TO RWY INSPECTION',
    '07 1700-2230, 08 1900-2230, 09-20 1700-2230 RWY 06/24 CLSD DUE TO RUBBER DEPOSIT REMOVAL',
])
def test_complete_closure_with_known_works_reason_remains_published(raw):
    record={**HELD['notice'],'item_e_text':raw}
    result=analyse(record)
    assert result['lines'] and result['unresolved_ids']==[]


def test_a_separate_unreduced_operational_clause_keeps_a_closing_receipt():
    record={**HELD['notice'],'item_e_text':'RWY 16R/34L CLSD. ILS RWY 16L/34R U/S.'}
    result=analyse(record)
    assert 'RWY 16R/34L closed' in result['lines'][0]['text']
    assert result['unresolved_ids']==['A2314/26']

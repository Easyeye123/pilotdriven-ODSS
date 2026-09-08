from datetime import datetime, timedelta, timezone

import fitz

from generate_visual_samples import sample_flight, sample_findings
from app.odss.combined_brief import render_combined_briefing
from app.odss.analysed_briefing_content import cyclone_content, deferred_consequences, release_conditions
from app.odss.analysed_briefing_map import build_publication_map, source_polygon
from app.odss.briefing import build_briefing_view, _clock_from_actm, _va_derived_screening


def _findings():
    return [f for f in sample_findings() if f['engine'] != 'depressurisation']


def test_unrelated_cyclone_movement_is_not_published(tmp_path):
    path = tmp_path / 'flight.pdf'
    findings = _findings() + [{'engine': 'tropical_cyclone', 'title': 'TC', 'severity': 'unknown',
        'summary': 'Source coverage incomplete', 'details': ['UNRELATED centre movement: 14 degrees at 7.2 kt']}]
    render_combined_briefing(sample_flight(), findings, [], path)
    with fitz.open(path) as doc:
        assert 'UNRELATED centre movement' not in doc[3].get_text()


def test_footer_names_the_section_and_release_actions_are_numbered(tmp_path):
    path = tmp_path / 'flight.pdf'
    render_combined_briefing(sample_flight(), _findings(), [], path)
    with fitz.open(path) as doc:
        assert 'MASTER SUMMARY' not in doc[3].get_text()
        assert '1.' in doc[8].get_text()


def test_cyclone_requires_a_time_matched_distance_and_uses_no_invented_radius():
    flight = {'scheduled_departure_utc': '2026-08-16T09:00:00Z', 'scheduled_arrival_utc': '2026-08-16T13:40:00Z',
        'tropical_cyclone_track_review': {'cyclones': [
            {'name': 'HELD', 'closest_route_screening': {'time_utc': '2026-08-16T11:30:00Z', 'distance_nm': 412.4,
                'route_from': 'ALPHA', 'route_to': 'BRAVO', 'cyclone_centre_position': {'latitude': 10, 'longitude': 120}}},
            {'name': 'LATER', 'movement': {'speed_kt': 8}, 'closest_route_screening': {'time_utc': '2026-09-08T11:30:00Z', 'distance_nm': 20}},
        ]}}
    result = cyclone_content(flight)
    assert len(result['markers']) == 1
    assert '412 NM' in result['lines'][0] and 'ALPHA-BRAVO' in result['lines'][0]
    assert 'LATER' not in str(result) and '200 NM' not in str(result)
    flight['tropical_cyclone_track_review']['cyclones'] = []
    empty = cyclone_content(flight)
    assert empty['markers'] == [] and '16AUG' in empty['lines'][0]
    assert 'no cyclone' not in empty['lines'][0].lower()


def test_ash_and_vws_are_on_the_route_map_and_sources_are_not_mutated():
    from copy import deepcopy
    flight = sample_flight()
    flight['route_waypoints'] = [
        {'name': 'AAA', 'latitude': 0, 'longitude': 100, 'actm_minutes': 0, 'vws': 4},
        {'name': 'BBB', 'latitude': 1, 'longitude': 101, 'actm_minutes': 60, 'vws': 5},
        {'name': 'CCC', 'latitude': 2, 'longitude': 102, 'actm_minutes': 120, 'vws': 4},
    ]
    flight['scheduled_departure_utc'] = '2026-08-16T09:00:00Z'
    flight['actual_takeoff_utc'] = '2026-08-16T10:00:00Z'
    view = build_briefing_view(flight, [], [])
    view['vaa']['cfp_advisories'] = [{'advisory_kind':'VA_SIGMET', 'volcano':'TEST', 'valid_from':'160900', 'valid_to':'161200',
        'text':'WI N0030 E10030 - N0130 E10030 - N0130 E10130 - N0030 E10030 SFC/FL050'}]
    original = deepcopy(view)
    result = build_publication_map(flight, view)
    assert {e['kind'] for e in result['publication_events']} == {'VA', 'VWS'}
    assert result['publication_events'][0]['time_matched'] is True
    assert result['publication_events'][0]['label'] == 'TEST SIGMET ash area'
    assert 'BBB' in result['publication_events'][1]['label']
    assert 'BBB-BBB' not in result['publication_events'][1]['label']
    assert 'BBB sample;' in result['publication_events'][1]['label']
    assert view == original


def test_a_volcano_point_and_invalid_coordinates_do_not_become_an_ash_area():
    assert source_polygon('PSN S0606 E10525 SFC/FL050') == []
    assert source_polygon('WI N0065 E10000 - N0100 E10000 - N0200 E10100 SFC/FL050') == []


def _deferred(raw):
    return {'deferred_dispatch_gates': [{'title':'MEL 25-99-01', 'references':['25-99-01'],
        'source_segments':[{'item_type':'MEL','description':'GALLEY CHILLER','source_text':raw}]}]}


def test_a_source_action_becomes_a_consequence_not_a_copied_remark():
    result = ' '.join(deferred_consequences(_deferred('GALLEY CHILLER NOT COLD. PLSE UPLIFT DRY ICE')))
    assert 'Catering must arrange' in result and 'MEL 25-99-01' in result
    assert 'PLSE' not in result and 'dispatch approved' not in result.lower()


def test_a_negated_uplift_instruction_does_not_create_an_action():
    result = ' '.join(deferred_consequences(_deferred('CHILLER SERVICEABLE. DO NOT UPLIFT DRY ICE')))
    assert 'Catering must arrange' not in result


def test_shared_mel_number_keeps_distinct_defects_and_unknown_siblings():
    from app.odss.analysed_briefing_content import deferred_consequence_rows
    view = _deferred('GALLEY CHILLER TO UPLIFT DRY ICE')
    gate = view['deferred_dispatch_gates'][0]
    gate.update(gate_id='same-reference', source_item_indices=[0, 1, 2])
    gate['source_segments'][0]['source_item_index'] = 0
    gate['source_segments'] += [
        {'item_type':'MEL', 'source_item_index':1, 'description':'CARGO ACCESS PANEL',
         'source_text':'FWD CARGO DOOR CTRL ACCESS PNL NOT FLUSH WHEN CLOSED TO INSPECT HST CONDITION AND REAPPLIED'},
        {'item_type':'MEL', 'source_item_index':2, 'description':'UNASSESSED CABIN DEFECT', 'source_text':'UNASSESSED CABIN DEFECT'},
    ]
    rows = deferred_consequence_rows(view)
    assert len(rows) == 3
    assert [r['source_item_indices'] for r in rows] == [[0], [1], [2]]
    assert 'dry-ice uplift' in rows[0]['text']
    assert 'HST inspection and reapplication' in rows[1]['text']
    assert 'UNASSESSED CABIN DEFECT' in rows[2]['text']
    assert 'does not establish' in rows[2]['text']


def test_missing_waste_latch_has_no_invented_securing_or_use_allowance():
    result = ' '.join(deferred_consequences(_deferred('AFT GALLEY LH WASTE CONTAINER DOOR IN GALLEY LATCH MISSING')))
    assert 'Waste-container door retention' in result
    assert 'does not establish an acceptable securing method or permission to use it' in result
    negated = ' '.join(deferred_consequences(_deferred('WASTE CONTAINER DOOR LATCH NOT MISSING')))
    assert 'Waste-container door retention' not in negated


def test_release_list_is_scoped_to_unresolved_inputs_without_zero_counts():
    flight = {'departure':'WSSS','destination':'YPPH','scheduled_departure_utc':'2026-07-11T10:30:00Z','scheduled_arrival_utc':'2026-07-11T15:30:00Z'}
    receipt = {'rows':[{'key':'tropical_cyclone','state':'REVIEW REQUIRED','detail':'Gap'},
                       {'key':'edto','state':'NOT APPLICABLE','detail':'Not applicable'},
                       {'key':'fuel_performance','state':'HELD','detail':'Verified'}]}
    lines = release_conditions(flight, {}, receipt, [], [], [])
    assert len(lines) == 1 and lines[0].startswith('1. ')
    assert '11JUL 1030Z' in lines[0] and 'WSSS-YPPH' in lines[0]
    assert 'EDTO' not in str(lines) and '0 SIGMET' not in str(lines)


def test_ash_and_sigmet_passage_use_the_entered_atot():
    flight = {'scheduled_departure_utc':'2026-08-16T09:00:00Z','actual_takeoff_utc':'2026-08-16T10:00:00Z'}
    assert _clock_from_actm(flight, 60).hour == 11
    raw = 'VALID 161200/161400 WI N0030 E10030 - N0130 E10030 - N0130 E10130 - N0030 E10030 SFC/FL050'
    points = [{'name':'AAA','latitude':0,'longitude':100,'actm_minutes':0}, {'name':'BBB','latitude':2,'longitude':102,'actm_minutes':120}]
    result = _va_derived_screening(raw, points, 'AAA/400', flight)
    assert 'before' in result and 'start' in result and 'inside' not in result


def test_invalid_cyclone_position_is_not_drawn():
    flight = {'scheduled_departure_utc':'2026-08-16T09:00:00Z', 'scheduled_arrival_utc':'2026-08-16T13:00:00Z',
        'tropical_cyclone_track_review': {'cyclones':[{'name':'HELD', 'closest_route_screening':{
            'time_utc':'2026-08-16T11:00:00Z','distance_nm':20,'cyclone_centre_position':{'latitude':95,'longitude':100}}}]}}
    assert cyclone_content(flight)['markers'] == []


def test_same_area_with_different_validities_is_not_silently_deduplicated():
    flight = sample_flight()
    view = build_briefing_view(flight, [], [])
    raw = 'WI N0030 E10030 - N0130 E10030 - N0130 E10130 - N0030 E10030'
    view['vaa']['cfp_advisories'] = [dict(advisory_kind='VA_SIGMET', text=raw, valid_from=start, valid_to=end)
                                    for start,end in [('160900','161000'),('161100','161200')]]
    assert len([e for e in build_publication_map(flight,view)['publication_events'] if e['kind']=='VA']) == 2


def test_live_matched_area_and_hole_survive_without_unrelated_dates():
    flight = sample_flight()
    flight.update(scheduled_departure_utc='2026-08-16T09:00:00Z', scheduled_arrival_utc='2026-08-16T14:00:00Z')
    view = build_briefing_view(flight, [], [])
    view['route_map']['hazard_features'] = [{'geometry':{'type':'Polygon','coordinates':[
        [[100,0],[103,0],[103,3],[100,3],[100,0]], [[101,1],[102,1],[102,2],[101,2],[101,1]]]},
        'properties':{'advisory_id':'live-ash', 'hazard':'volcanic_ash','hazard_state':'affecting',
        'valid_from_utc':'2026-08-16T10:00:00Z','valid_to_utc':'2026-08-16T12:00:00Z'}}]
    result = build_publication_map(flight, view)
    live = next(e for e in result['publication_events'] if e['source_id']=='live-ash')
    assert len(live['rings']) == 2 and live['level_matched'] is True
    view['route_map']['hazard_features'][0]['properties']['valid_from_utc'] = '2026-09-08T10:00:00Z'
    assert all(e['source_id']!='live-ash' for e in build_publication_map(flight,view)['publication_events'])


def test_incomplete_held_advisory_is_a_closing_condition_even_if_live_sources_are_complete():
    view = {'vaa':{'cfp_advisories':[{'advisory_kind':'CFP_VAA_NOTICE','volcano':'SEMERU'}]}}
    lines = release_conditions({}, view, {'rows':[]}, [], [], [])
    assert len(lines) == 1 and 'SEMERU' in lines[0] and 'incomplete' in lines[0]


def test_removed_cyclone_content_fails_the_release_gate(tmp_path):
    from app.odss.concise_pdf_gate import check_concise_pdf
    path, changed = tmp_path/'original.pdf', tmp_path/'changed.pdf'
    flight = sample_flight()
    render_combined_briefing(flight, _findings(), [], path)
    with fitz.open(path) as doc:
        for rect in doc[3].search_for('No time-matched cyclone centre-distance result'):
            doc[3].add_redact_annot(rect)
        doc[3].apply_redactions()
        doc.save(changed)
    result = check_concise_pdf(changed, flight=flight)
    assert 'CYCLONE_TIME_DISTANCE_PARITY' in {v['code'] for v in result['violations']}


def test_stuck_seat_armrest_needs_a_configuration_decision_not_an_invented_seat_block():
    result = ' '.join(deferred_consequences(_deferred('SEAT 12A OUTSIDE ARMREST EXTEND STUCK')))
    assert 'Seat 12A needs a seating-configuration decision' in result
    assert 'seat blocked' not in result.lower() and 'dispatch permitted' not in result.lower()
    assert 'seating-configuration decision' not in ' '.join(deferred_consequences(_deferred('SEAT 12A ARMREST NOT STUCK')))


def test_closing_page_uses_named_sections_and_attaches_body_to_heading(tmp_path):
    from app.odss.concise_pdf_gate import check_concise_pdf
    path = tmp_path / 'flight.pdf'
    render_combined_briefing(sample_flight(), _findings(), [], path)
    with fitz.open(path) as doc:
        page = doc[8]
        assert 'BEFORE RELEASE' not in page.get_text()
        assert 'WEATHER COVERAGE' in page.get_text()
        title, body = page.search_for('WEATHER COVERAGE')[0], page.search_for('1.')[0]
        assert 0 < body.y0 - title.y1 < 25
        assert len(page.search_for('PUBLICATION STATE')) == 1
    assert check_concise_pdf(path)['valid']


def test_missing_closing_condition_is_rejected(tmp_path):
    from app.odss.concise_pdf_gate import check_concise_pdf
    path = tmp_path / 'flight.pdf'
    render_combined_briefing(sample_flight(), _findings(), [], path)
    result = check_concise_pdf(path, closing_lines=['A required source-bound condition that was lost.'])
    assert 'REVIEW_CONDITION_PARITY' in {v['code'] for v in result['violations']}


def test_airport_closing_record_names_unresolved_conclusions_without_counts():
    from app.odss.analysed_briefing_content import airport_review_constraints
    analyses = [{'icao':'WSSS', 'role':'destination', 'planned_runway':'20R', 'unresolved_ids':['A1234/26']}]
    view = {'airport_operational_panels':[{'icao':'WSSS','selected_notams':[
        {'notam_id':'A1234/26','item_e_text':'A 5-MIN INSPECTION CONDUCTED WITHIN A LARGER WINDOW', 'pertinence_kind':'runway_closure'}]}]}
    line = airport_review_constraints(view, analyses)[0]
    assert 'WSSS destination RWY 20R' in line and 'short-inspection timing' in line
    assert '(1)' not in line and 'A1234/26' not in line and 'CONDUCTED' not in line


def test_departure_route_notice_does_not_become_an_arrival_release_condition():
    from app.odss.airport_pdf_analysis import analyse_airport_for_pdf
    panel = {'icao':'WSSS','selected_notams':[
        {'notam_id':'A1234/26','item_e_text':'FLIGHTS DEPARTING WSSS ON ATS ROUTE N571: EQUIPMENT CONDITIONS APPLY', 'pertinence_kind':'runway_approach_restriction'}]}
    for role, route in [('destination',None), ('destination alternate',None), ('departure','WSSS/20C DCT BOBAG N884 YPPH/21')]:
        result = analyse_airport_for_pdf(panel, role=role, planned_runway='20C', route_text=route)
        assert result['unresolved_ids'] == []
        assert result['supporting_ids'] == ['A1234/26']
    for route in [None, 'WSSS/20C N571 ABCDE']:
        assert analyse_airport_for_pdf(panel, role='departure', planned_runway='20C', route_text=route)['unresolved_ids'] == ['A1234/26']

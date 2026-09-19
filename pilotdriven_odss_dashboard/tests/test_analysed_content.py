from datetime import datetime, timedelta, timezone

import fitz

from generate_visual_samples import sample_flight, sample_findings
from app.odss.concise_pdf_gate import (AIRPORTS_PAGE, ASSURANCE_PAGE,
                                        WEATHER_PAGE)
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
        assert 'UNRELATED centre movement' not in doc[WEATHER_PAGE].get_text()


def test_footer_names_the_section_and_release_actions_are_numbered(tmp_path):
    path = tmp_path / 'flight.pdf'
    render_combined_briefing(sample_flight(), _findings(), [], path)
    with fitz.open(path) as doc:
        assert 'PAGE 4 OF 6' in ' '.join(doc[AIRPORTS_PAGE].get_text().split())
        assert '1.' in doc[ASSURANCE_PAGE].get_text()


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
    assert 'Unassessed cabin defect' in rows[2]['text']
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
    from app.odss.analysed_briefing_map import event_description
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
    assert live['route_intersects'] is True and live['time_matched'] is True
    assert 'affects flight: route/time/level match' in event_description(live)
    view['route_map']['hazard_features'][0]['properties']['valid_from_utc'] = '2026-09-08T10:00:00Z'
    assert all(e['source_id']!='live-ash' for e in build_publication_map(flight,view)['publication_events'])


def test_weather_marker_names_and_key_preserve_type_validity_and_uncertainty():
    from app.odss.analysed_briefing_map import phenomenon_label, event_description
    assert phenomenon_label('EMBD TS') == 'Thunderstorms'
    assert phenomenon_label('SEV TURB') == 'Severe turbulence'
    assert phenomenon_label('UNKNOWN') == 'Weather advisory'
    event = dict(id='WX1', marker_label='Thunderstorms 1', label='VHHK SIGMET 2', polygon=[[0,0]],
                 valid_from_utc='2026-09-09T00:00:00Z', valid_to_utc='2026-09-09T04:00:00Z',
                 route_intersects=True, time_matched=True)
    line = event_description(event)
    assert 'Thunderstorms 1' in line and 'VHHK SIGMET 2' in line
    assert '09SEP 0000-0400Z' in line
    # Route and time matched, level not held: the crossing is stated, the
    # full verdict is not claimed (David, 9 Sep 2026: "not WX ... that is for what???").
    assert 'crosses route inside validity' in line and 'affects flight' not in line and 'WX1' not in line
    event['route_intersects'] = False
    assert 'route does not cross area' in event_description(event)
    event['level_matched'] = True
    assert 'affects flight' not in event_description(event)
    event['route_intersects'] = None
    assert 'affects flight' not in event_description(event)
    event['route_intersects'] = True
    assert 'route/time/level match' in event_description(event)


def test_missing_inside_fix_times_do_not_establish_route_nonintersection():
    from app.odss.analysed_briefing_map import event_description
    for waypoints in [
        [{'name':'AAA','latitude':1,'longitude':99,'actm_minutes':0}, {'name':'BBB','latitude':1,'longitude':103,'actm_minutes':120}],
        [{'name':'AAA','latitude':1,'longitude':101}, {'name':'BBB','latitude':1,'longitude':103}],
    ]:
        flight = sample_flight()
        flight.update(route_waypoints=waypoints, scheduled_departure_utc='2026-08-16T09:00:00Z')
        view = build_briefing_view(flight, [], [])
        view['hazards']['sigmet_cards'] = [{'phenomenon':'TS','fir':'SYNTHETIC','sigmet_id':'2',
            'valid_from':'160900','valid_to':'161200', 'text':'WI N0030 E10000 - N0130 E10000 - N0130 E10200 - N0030 E10200 - N0030 E10000'}]
        event = next(e for e in build_publication_map(flight,view)['publication_events'] if e['kind']=='WX')
        assert event['route_intersects'] is True
        assert 'distance_nm' not in event
        assert 'route does not cross' not in event_description(event)
        assert 'affects flight' not in event_description(event)


def test_map_uses_full_crossing_leg_time_bounds_and_explicit_spatial_result():
    flight = sample_flight()
    flight.update(route_waypoints=[
        {'name':'AAA','latitude':1,'longitude':99,'actm_minutes':0},
        {'name':'BBB','latitude':1,'longitude':103,'actm_minutes':120},
    ], scheduled_departure_utc='2026-08-16T09:00:00Z')
    view = build_briefing_view(flight, [], [])
    # The nearest-point estimate can lie inside validity while the full filed
    # leg spans 0900-1100Z. That does not establish crossing-time applicability.
    card = {'phenomenon':'TS','fir':'SYNTHETIC','sigmet_id':'2',
            'valid_from':'160930','valid_to':'161000',
            'text':'WI N0030 E10000 - N0130 E10000 - N0130 E10200 - N0030 E10200'}
    view['hazards']['sigmet_cards'] = [card]
    event = next(e for e in build_publication_map(flight, view)['publication_events'] if e['kind'] == 'WX')
    assert event['route_intersects'] is True
    assert event['time_matched'] is False
    card.update(valid_from='160800', valid_to='161200')
    event = next(e for e in build_publication_map(flight, view)['publication_events'] if e['kind'] == 'WX')
    assert event['time_matched'] is True
    flight['route_waypoints'][0]['latitude'] = 3
    flight['route_waypoints'][1]['latitude'] = 3
    event = next(e for e in build_publication_map(flight, view)['publication_events'] if e['kind'] == 'WX')
    assert event['route_intersects'] is False


def _dense_publication_map(count):
    flight = sample_flight()
    route = build_publication_map(flight, build_briefing_view(flight, [], []))
    route['publication_events'] = [dict(
        id=f'WX{i}', kind='WX', marker_label=f'Thunderstorms {i}',
        label=f'SYNTHETIC/{i}', polygon=[(60, 100), (61, 100), (61, 101)],
        position={'latitude':60, 'longitude':100},
        valid_from_utc='2026-09-08T21:45:00Z', valid_to_utc='2026-09-09T01:00:00Z',
    ) for i in range(1, count + 1)]
    return route


def test_dense_route_key_preserves_every_description_at_readable_size(tmp_path, monkeypatch):
    from reportlab.pdfgen.canvas import Canvas
    from app.odss import analysed_briefing_map as maps
    from app.odss.operational_format import SIZE, MARGIN, TOP
    route = _dense_publication_map(12)
    projected_widths = []
    project = maps.project_route_map
    def record_projection(route, width, *args):
        projected_widths.append(width)
        return project(route, width, *args)
    monkeypatch.setattr(maps, 'project_route_map', record_projection)
    path = tmp_path / 'dense-map.pdf'
    canvas = Canvas(str(path), pagesize=SIZE)
    maps.draw_publication_map(canvas, route, MARGIN, 233, SIZE[0] - 2*MARGIN, TOP - 233)
    canvas.save()
    assert min(projected_widths) >= 320
    with fitz.open(path) as doc:
        text = ' '.join(doc[0].get_text().split())
        for event in route['publication_events']:
            assert maps.event_description(event) in text
        spans = [span for block in doc[0].get_text('dict')['blocks'] if 'lines' in block
                 for line in block['lines'] for span in line['spans']]
        assert min(span['size'] for span in spans) >= 9


def test_unrepresentable_route_key_still_rejects_publication(tmp_path):
    import pytest
    from reportlab.pdfgen.canvas import Canvas
    from app.odss.analysed_briefing_map import draw_publication_map
    from app.odss.operational_format import SIZE, MARGIN, TOP
    canvas = Canvas(str(tmp_path/'overflow.pdf'), pagesize=SIZE)
    with pytest.raises(ValueError, match='Route hazard key exceeds readable capacity'):
        draw_publication_map(canvas, _dense_publication_map(60), MARGIN, 233,
                             SIZE[0] - 2*MARGIN, TOP - 233)


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
        for rect in doc[WEATHER_PAGE].search_for('No time-matched cyclone centre-distance result'):
            doc[WEATHER_PAGE].add_redact_annot(rect)
        doc[WEATHER_PAGE].apply_redactions()
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
        page = doc[ASSURANCE_PAGE]
        assert 'BEFORE RELEASE' not in page.get_text()
        assert 'WEATHER COVERAGE' in page.get_text()
        # The first numbered condition must sit under this heading, in this
        # heading's own column. A bare search for '1.' matches published
        # figures elsewhere on the page ('... ACTM 00.41.'), which is why the
        # publication gate scopes the same rule to the column.
        title = page.search_for('WEATHER COVERAGE')[0]
        below = [hit for hit in page.search_for('1.')
                 if hit.y0 > title.y1 and hit.x0 < title.x1 and hit.x1 > title.x0 - 12]
        assert below and 0 < min(hit.y0 for hit in below) - title.y1 < 25
        assert len(page.search_for('PUBLICATION STATE')) == 1
    result = check_concise_pdf(path)
    assert result['valid'], result['violations']
    assert 'REVIEW_BODY_ALIGNMENT' not in {v['code'] for v in result['violations']}


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


def test_a_block_capital_defect_is_cased_without_losing_source_shorthand():
    """David, 9 Sep 2026 21:28: "by copying in blocks and capital is very hard
    to read". The answer is sentence case; dropping the subject leaves a card
    that never says what is wrong with the aircraft.
    """
    from app.odss.analysed_briefing_content import deferred_subject
    assert deferred_subject('ENG 2 FAN COWLS LATCH ACCESS PANEL AFT-MOST LATCH IS LOOSE.') == (
        'ENG 2 fan cowls latch access panel aft-most latch is loose.')
    # Shorthand the source wrote stays shorthand. It is kept because the
    # lexicon does not recognise it as English, not because it happens to have
    # no vowel or to sit on a hand-written list.
    assert deferred_subject('MAINT ENTRY: WAC FOUND RH WING FTE PANEL 3 SEAL TORN') == (
        'RH wing FTE panel 3 seal torn')
    assert deferred_subject('D4L COMMS PA HANDSET INOP.') == 'D4L comms PA handset INOP.'
    assert deferred_subject('ATTENDANT CREW SEAT DOOR 3R I/B DIFFICULT') == (
        'Attendant crew seat door 3R I/B difficult')
    assert deferred_subject('SEAT IFE (YCL), AUDIO JACK, NO AUDIO') == (
        'Seat IFE (YCL), audio jack, no audio')
    assert deferred_subject('AFT GALLEY HEATER FAULT FC2161F1FK') == (
        'Aft galley heater fault FC2161F1FK')
    # A source that already wrote mixed case is readable and is untouched.
    assert deferred_subject('Bay 21 WIP with a 43 ft crane.') == 'Bay 21 WIP with a 43 ft crane.'
    assert deferred_subject(None) == ''


# Abbreviations a pilot reads as one unit. Every one carries a vowel and sits
# outside the 25-item allowlist the earlier rule shipped, so every one was
# destroyed by it: "MEL" became "mel" - the single most load-bearing
# abbreviation in this feature - "NEF" became "nef", "ILS" became "Ils" and
# "CAT II/III INOP" became "cat ii/iii inop".
OPERATIONAL_ABBREVIATIONS = (
    'MEL', 'CDL', 'CDDL', 'IFEDDL', 'NEF', 'ECP', 'ILS', 'CAT', 'TCAS', 'GPU',
    'IRS', 'EGT', 'EFB', 'AOG', 'VHF', 'EMER', 'ACRFT', 'INOP', 'REQ', 'FWD',
    'ACARS', 'ADIRU', 'EICAS', 'ECAM', 'ETOPS', 'EDTO', 'METAR', 'SIGMET',
    'NOTAM', 'INTAM', 'ATIS', 'SELCAL', 'SATCOM', 'AUTOLAND', 'STAR', 'MET',
    'TOD', 'ETA', 'ETD', 'PAX', 'LAV', 'APU', 'AUX', 'OXY', 'ELT', 'IFE',
    'VCRU', 'WAC', 'JCL', 'YCL', 'PDU', 'MLG', 'DND', 'AVNCS', 'HST', 'RWY',
    'SID', 'TAF', 'ZFW', 'RTOW', 'MTOW', 'EOSID', 'DME', 'ALT', 'FTE', 'NPE',
    'MAF', 'IDG', 'ATA', 'AVOD', 'IATA', 'ICAO', 'IRU', 'PA', 'QTY', 'REV',
    'PLS', 'COM', 'CMS', 'ENG', 'FAP', 'RCCB',
)


def test_sentence_casing_never_lowercases_an_operational_abbreviation():
    """The rule must keep an abbreviation because it is one, not by luck.

    The rule this replaced kept a word uppercase only when it was one letter,
    carried a digit, had no vowel, or was on a 25-item allowlist. Vowel
    presence measures nothing about abbreviation-ness, so everything else was
    destroyed. Nothing below is on any allowlist in the shipped code beyond the
    small reserved set; the rest survive because the lexicon does not claim
    them as English words.
    """
    from app.odss.analysed_briefing_content import source_subject_sentence
    for abbreviation in OPERATIONAL_ABBREVIATIONS:
        published = source_subject_sentence(f'{abbreviation} 2 FAULT')
        assert published == f'{abbreviation} 2 fault', published
    # Whole phrases, as the source writes them.
    assert source_subject_sentence('ILS RWY 24 U/S') == 'ILS RWY 24 U/S'
    assert source_subject_sentence('CAT II/III INOP') == 'CAT II/III INOP'
    assert source_subject_sentence('TCAS 1 INOP') == 'TCAS 1 INOP'
    assert source_subject_sentence('AUTOLAND CAT IIIB DOWNGRADED') == (
        'AUTOLAND CAT IIIB downgraded')
    assert source_subject_sentence('SECTION MEL AND CMS REV 18NOV 25') == (
        'Section MEL and CMS REV 18NOV 25')
    assert source_subject_sentence('NON-ESSENTIAL EQUIPMENT AND NEF') == (
        'Non-essential equipment and NEF')
    assert source_subject_sentence('VIDEO PB ON ECP NOT RESPONSIVE') == (
        'Video PB on ECP not responsive')
    assert source_subject_sentence('DM COM VHF EMER SUPPLY REDUNDANCY') == (
        'DM COM VHF EMER supply redundancy')


def test_sentence_casing_does_not_half_case_one_phrase():
    """Every capital left standing must be an abbreviation, every lowered word
    an English word - not a per-word coin toss on whether it holds a vowel.

    "WHOLE ACRFT CHILLERS INOP X DRY ICE REQ" came out as "Whole acrft chillers
    inop X DRY ice req": ACRFT and INOP destroyed, DRY shouted.
    """
    from app.odss.analysed_briefing_content import source_subject_sentence
    assert source_subject_sentence('WHOLE ACRFT CHILLERS INOP X DRY ICE REQ') == (
        'Whole ACRFT chillers INOP X dry ice REQ')
    assert source_subject_sentence('MAINT ENTRY PDU WITH STATUS FWD 12L(B) AFT 3L(X)') == (
        'MAINT entry PDU with status FWD 12L(B) aft 3L(X)')


def test_a_truncated_or_form_debris_subject_is_not_published():
    """The OFP deferred table is a form, and its description cell is not prose.

    It wraps mid-sentence into the company-remark cell, repeats the selected
    drop-down, leaves the unselected "OTHERS (PLS ENTER COMMENTS)" behind and
    sometimes holds a manual section heading instead of a defect. None of that
    is a statement this briefing can stand behind, so none of it is published.
    """
    from app.odss.analysed_briefing_content import deferred_subject
    # Cut mid-sentence: the rest of each one lives in the company remark.
    assert deferred_subject('MAINT ENTRY: BOTH VCRU (101HW & 103HW) REMOVED AS PER') == ''
    assert deferred_subject('FOUND LH INNER WING LEADING EDGE DND FIXED SEAL WITH') == ''
    assert deferred_subject('MAINT ENTRY: LH WING, SLAT #6 LOWER SEAL FOUND') == ''
    assert deferred_subject('JCL D1 GALLEY 213/214/215 CHILLING COMPARTMENT:') == ''
    assert deferred_subject('JCL D1 GALLEY 309/310/311/312/314/315 CHILLING') == ''
    # A slice out of the middle of the cell: no opening, unbalanced bracket.
    assert deferred_subject('- GALLEY WASTE COMPARTMENT ACCESS DOOR INSTALLED)') == ''
    # A manual heading and a bare cross-reference are provenance, not defects.
    assert deferred_subject('SECTION MEL AND CMS REV 18NOV 25') == ''
    assert deferred_subject('MAINT ENTRY : WRT CDL 006028, CDL 006029 AND CDL 006032') == ''
    # The form's drop-down, written twice, with the unselected option left in.
    assert deferred_subject(
        'TRASH COMPACTOR, TRASH COMPACTOR, OTHERS (PLS ENTER COMMENTS)',
        'TRASH COMPACTORS',
    ) == ''
    assert deferred_subject(
        'TRASH COMPACTOR, TRASH COMPACTOR, NO POWER', 'TRASH COMPACTORS'
    ) == 'No power'
    assert deferred_subject(
        'HINGED DOOR SEAL X HINGED DOOR SEAL AT RH FWD SIDE'
    ) == 'Hinged door seal at RH FWD side'


def test_a_well_formed_subject_is_still_published():
    """The contract abstains on debris; it must not abstain on a real defect.

    Round 2 dropped the subject for every declaration a rule could analyse,
    which is most of them, and the card stopped saying what was wrong with the
    aircraft. These are the shapes that must survive.
    """
    from app.odss.analysed_briefing_content import deferred_subject
    for description, expected in (
        ('ENG 2 FAN COWLS LATCH ACCESS PANEL AFT-MOST LATCH IS LOOSE.',
         'ENG 2 fan cowls latch access panel aft-most latch is loose.'),
        ('SEAT 21A TRAY TABLE UNABLE TO STOW', 'Seat 21A tray table unable to stow'),
        ('LAV L53 TOILET BOWL NIL WATER', 'LAV L53 toilet bowl nil water'),
        ('D4L GALLEY CHILLER NO.1 RED LIGHT BLINKING',
         'D4L galley chiller no.1 red light blinking'),
        ('VIDEO PB ON ECP NOT RESPONSIVE.', 'Video PB on ECP not responsive.'),
        ('MAINT ENTRY: WAC FOUND RH WING HINGED DOOR SEAL (QTY 01) TORN',
         'RH wing hinged door seal (QTY 01) torn'),
        ('LH MLG HINGED DOOR AFT SEAL WITH 30CM LENGTH MISSING.',
         'LH MLG hinged door aft seal with 30CM length missing.'),
        ('OTHER GALLEY CHILLER INOP', 'Other galley chiller INOP'),
    ):
        assert deferred_subject(description) == expected, description


def test_an_analysed_deferred_item_still_names_the_defect_it_analysed():
    result = ' '.join(deferred_consequences(_deferred('GALLEY CHILLER NOT COLD. PLSE UPLIFT DRY ICE')))
    # 19 Sep 2026 review: this asserted 'Galley chiller.' - the description
    # cell alone, with the condition the source wrapped under it ("NOT COLD")
    # dropped. Naming the defect means naming what is wrong with it.
    assert 'Galley chiller not cold.' in result
    assert 'uplift dry ice' not in result.lower().split('catering')[0]
    assert 'Catering must arrange' in result
    assert 'GALLEY CHILLER' not in result


def test_a_declared_interim_repair_is_published_without_a_serviceability_claim():
    result = ' '.join(deferred_consequences(_deferred(
        'ENG 2 FAN COWLS LATCH IS LOOSE. HST APPLIED, CONDITION TO BE CHECKED PRIOR EVERY DEPARTURE')))
    assert 'The declaration records HST applied as an interim condition' in result
    assert 'does not establish how long that condition stays acceptable' in result
    # No conclusion about airworthiness, and never the remark itself.
    assert 'serviceable' not in result.lower()
    assert 'PRIOR EVERY DEPARTURE' not in result
    negated = ' '.join(deferred_consequences(_deferred('ENG 2 LATCH LOOSE. HST NOT APPLIED')))
    assert 'HST applied as an interim condition' not in negated

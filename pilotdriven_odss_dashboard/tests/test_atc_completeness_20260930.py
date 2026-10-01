"""ITEM 1: genuine missing-boundary FIR notices and LABELLED SYNTHETIC semantic controls."""
from pathlib import Path
from copy import deepcopy

import fitz
import pytest

from app.odss.enroute_contact import compose_enroute_contact, is_call_line, primary_procedure_line
from app.odss.extraction_rules import EXTRACTION_RULES
from app.odss.parser import extract_pages, parse_lido
from tests.atc_test_inputs import private_cfp_source


@pytest.mark.parametrize('label', ['ZZAA A1234/26', 'ZZ A1234/26', 'ZZBB A1234/26', 'ZY A1234/26'])
def test_series_location_matches_the_proved_owner_or_becomes_a_literal_topic(label):
    # LABELLED SYNTHETIC structural ownership control, not a real instruction.
    from app.odss.parser import _parse_notam_procedure_records
    rule = '------------------'
    declaration = lambda identity, body: f'{identity} VALID: 01-JAN-26 0000 - 31-DEC-26 2359\n{body}'
    page = '\n'.join(['==================', 'AREA ENROUTE DEPARTURE - DESTINATION', '==================',
                      'ZZAA SYNTHETIC ALPHA FIR', rule, declaration('1G900/26', 'COM HF SERVICE U/S.'),
                      label, rule, declaration('1A1234/26', 'AIRCRAFT SHALL SQUAWK THE ASSIGNED SSR CODE.')])
    row = next(row for row in _parse_notam_procedure_records([page], (0, 1)) if row['notam_id'] == '1A1234/26')
    changed = not 'ZZAA'.startswith(label.split()[0])
    assert row['fir'] == (None if changed else 'ZZAA')
    assert row['heading'] == (label if changed else 'ZZAA SYNTHETIC ALPHA FIR')
    assert row['heading_kind'] == ('topic' if changed else 'fir')
    assert row['source_label'] == label and row['source_label_page'] == 1


def test_an_internal_underlined_title_without_a_new_declaration_keeps_complete_communications_body():
    # LABELLED SYNTHETIC: unknown body title is not a bulletin-owner boundary.
    from app.odss.parser import _parse_notam_procedure_records
    text = '\n'.join(['ZZAA SYNTHETIC ALPHA FIR', '------------------',
                      '1G900/26 VALID: 01-JAN-26 0000 - 31-DEC-26 2359', 'COM HF SERVICE U/S.',
                      'FALLBACK COMMUNICATIONS', '------------------',
                      'ALL FLIGHTS SHALL CONTACT SYNTHETIC CONTROL ON 132.1MHZ.'])
    rows = _parse_notam_procedure_records([text], (0, 1))
    assert len(rows) == 1
    assert rows[0]['text'] == 'COM HF SERVICE U/S. FALLBACK COMMUNICATIONS ALL FLIGHTS SHALL CONTACT SYNTHETIC CONTROL ON 132.1MHZ.'
    assert rows[0]['fir'] == 'ZZAA'


def test_genuine_tfr_location_labels_do_not_inherit_boston_owner_or_clock():
    import hashlib
    source = private_cfp_source('lido-briefing_SQ_24_15Aug2026_SIN_JFK.pdf')
    assert hashlib.sha256(source.read_bytes()).hexdigest() == 'ef773ec3cc808f2269522ae608750e4bd1cdab33a17603842c3fd7837815e240'
    parsed = parse_lido(extract_pages(source), source.name)
    composed = compose_enroute_contact(parsed)
    for identity, heading, heading_page, source_page in [('1A664/26', 'KZNY A0664/26', 92, 92), ('1A1973/26', 'KZDC A1973/26', 93, 94)]:
        record = next(row for row in parsed['notam_procedure_records'] if row['notam_id'] == identity)
        assert record['heading'] == heading and record['heading_page'] == heading_page
        assert record['heading_kind'] == 'topic' and record['fir'] is None and record['source_page'] == source_page
        assert record['source_label'] == heading and record['source_label_page'] == heading_page
        row = next(row for row in composed['procedures'] if row['notam_id'] == identity)
        assert row['actm'] is None and row['latest_actm'] is None and row['on_route'] is None
        assert row['applicability_state'] == 'conditions_unresolved'
        assert row['heading_page'] == heading_page
        assert row['source_label'] == heading and row['source_label_page'] == heading_page
        assert any(condition['kind'] == 'association' and condition['result'] == 'unresolved' for condition in row['conditions'])


@pytest.mark.parametrize('filename,identity', [
    ('SQ02325072026JFK.pdf', '1A487/26'),
    ('SQ30316072026BRU 81.pdf', '1B578/26'),
    ('lido-briefing_SQ_304_12Jul2026_SIN_BRU.pdf', '1F1665/25'),
    ('SQ36604082026SIN.pdf', '1A1531/26'),
    ('lido-briefing_SQ_322_16Aug2026_SIN_LHR.pdf', '1F1665/25'),
])
def test_genuine_fir_notice_without_timed_boundary_is_retained_unresolved_and_cited(filename, identity):
    source = private_cfp_source(filename)
    flight = parse_lido(extract_pages(source), source.name)
    original = next(r for r in flight['notam_procedure_records'] if r['notam_id'] == identity)
    composed = compose_enroute_contact(flight)
    held = [r for r in composed['procedures'] if r['notam_id'] == identity]
    assert len(held) == 1, f'{identity} disappeared at the missing-boundary filter'
    row = held[0]
    assert row['fir'] == original['fir']
    assert row['source_page'] == original['source_page']
    assert row['heading_page'] == original['heading_page']
    assert row['actm'] is None and row['latest_actm'] is None
    assert row['on_route'] is None
    assert row['applicability_state'] == 'conditions_unresolved'
    assert any(c['kind'] == 'association' and c['result'] == 'unresolved' for c in row['conditions'])
    assert 'NOTAM' in composed['provenance']
    assert 'notice(s) on the parsed route' not in composed['state_sentence']


def synthetic_flight(text):
    return {'departure': 'WSSS', 'destination': 'VHHH', 'scheduled_departure_utc': '2026-06-01T01:00:00Z',
            'extraction_rules': EXTRACTION_RULES,
            'route_waypoints': [{'name': 'ZZAA', 'fir_boundary': 'ZZAA', 'actm_minutes': 60, 'source_page': 1}],
            'notam_procedure_records': [{'notam_id': 'SYNTHETIC-QA/26', 'validity': '01-JAN-26 0000 - 31-DEC-26 2359',
             'heading': 'ZZAA SYNTHETIC ALPHA FIR', 'heading_kind': 'fir', 'fir': 'ZZAA', 'heading_page': 2, 'source_page': 2, 'text': text}]}


@pytest.mark.parametrize('text', ['COM CPDLC ROUTE MESSAGING NOT AVBL', 'CPDLC AT SYNTHETIC UAC (ZZYY) NOT AVBL.',
                                 'VHF RADIO 132.1MHZ U/S.',
                                 'HF RT ALONG WITH SELCAL WILL REMAIN UN-AVBL DUE UNSERVICEABILITY.'])
def test_service_outage_is_availability_evidence_not_a_crew_call(text):
    composed = compose_enroute_contact(synthetic_flight(text))
    row = composed['procedures'][0]
    assert row['instruction_effect'] == 'availability'
    assert row['actor'] == 'service'
    assert row['instruction'] == text
    assert row['latest_actm'] is None
    assert not composed['required_calls']
    assert not is_call_line(composed['procedure_lines'][0])
    assert 'Communications availability' in composed['procedure_lines'][0]['conditions_summary']


@pytest.mark.parametrize('text,effect', [
    ('ALL FLIGHTS ARE NOT REQUIRED TO CONTACT SYNTHETIC CONTROL ON 132.1MHZ 10 MIN BEFORE ENTRY.', 'not_required'),
    ('ALL FLIGHTS SHALL NOT CONTACT SYNTHETIC CONTROL ON 132.1MHZ 10 MIN BEFORE ENTRY.', 'prohibited'),
    ('ALL FLIGHTS ARE NOT REQUIRED TO REPORT TO ATS ON 132.1MHZ 10 MIN BEFORE ENTRY.', 'not_required'),
    ('ALL FLIGHTS SHALL NOT NOTIFY ATC ON 132.1MHZ 10 MIN BEFORE ENTRY.', 'prohibited'),
])
def test_negated_call_preserves_words_and_does_not_invent_a_deadline(text, effect):
    composed = compose_enroute_contact(synthetic_flight(text))
    row = composed['procedures'][0]
    assert row['instruction_effect'] == effect
    assert row['instruction'] == text
    assert row['latest_actm'] is None
    assert not is_call_line(composed['procedure_lines'][0])


def test_notice_with_no_boundary_rows_still_names_its_notam_pages_and_no_route_success():
    flight = synthetic_flight('COM CPDLC ROUTE MESSAGING NOT AVBL')
    flight['route_waypoints'] = []
    composed = compose_enroute_contact(flight)
    assert len(composed['procedures']) == 1
    assert composed['procedures'][0]['on_route'] is None
    assert 'NOTAM p2' in composed['provenance']
    assert not composed['crossings']


@pytest.mark.parametrize('filename,identity,page,effect', [
    ('lido-briefing_SQ_304_12Jul2026_SIN_BRU.pdf', '1A2393/26', 76, 'instruction'),
    ('SQ36604082026SIN.pdf', '1E1936/26', 98, 'instruction'),
    ('SQ36604082026SIN.pdf', '1E1548/26', 98, 'instruction'),
    ('SQ36604082026SIN.pdf', '1A582/26', 100, 'instruction'),
    ('SQ36604082026SIN.pdf', '1A1816/26', 93, 'availability'),
    ('SQ36604082026SIN.pdf', '1E1916/26', 94, 'availability'),
    ('SQ36604082026SIN.pdf', '1E1741/26', 98, 'availability'),
    ('SQ21419082026PER.pdf', '1F2673/26', 29, 'availability'),
    ('lido-briefing_SQ_297_16Aug2026_SIN_CHC.pdf', '1N2616/26', 38, 'availability'),
    ('SQ02325072026JFK.pdf', 'AX6/24', 100, 'instruction'),
    ('SQ02325072026JFK.pdf', '1A1533/26', 100, 'instruction'),
    ('SQ02325072026JFK.pdf', '1A412/26', 103, 'instruction'),
    ('SQ02325072026JFK.pdf', '1A46/22', 97, 'instruction'),
    ('SQ02422072026SIN.pdf', '1A173/26', 87, 'not_required'),
    ('SQ48125082026JNB.pdf', '1A689/26', 34, 'not_required'),
    ('lido-briefing_SQ_314_15Aug2026_SIN_LGW.pdf', 'SX45/26', 92, 'availability'),
    ('lido-briefing_SQ_322_16Aug2026_SIN_LHR.pdf', 'SX45/26', 70, 'availability'),
    ('lido-briefing_SQ_326_16Aug2026_SIN_FRA.pdf', 'SX45/26', 57, 'availability'),
    ('lido-briefing_SQ_352_15Aug2026_SIN_CPH.pdf', 'SX45/26', 77, 'availability'),
    ('lido-briefing_SQ_352_15Aug2026_SIN_CPH.pdf', '1C576/26', 88, 'instruction'),
    ('lido-briefing_SQ_24_15Aug2026_SIN_JFK.pdf', '1F4441/26', 86, 'availability'),
    ('lido-briefing_SQ_24_15Aug2026_SIN_JFK.pdf', '1F4057/26', 86, 'availability'),
    ('lido-briefing_SQ_24_15Aug2026_SIN_JFK.pdf', '1G2801/26', 87, 'availability'),
    ('SQ30316072026BRU 81.pdf', '1E45/26', 73, 'instruction'),
])
def test_independent_original_duty_and_availability_classes(filename, identity, page, effect):
    source = private_cfp_source(filename)
    flight = parse_lido(extract_pages(source), source.name)
    original = next(r for r in flight['notam_procedure_records'] if r['notam_id'] == identity)
    row = next(r for r in compose_enroute_contact(flight)['procedures'] if r['notam_id'] == identity)
    assert row['source_page'] == page == original['source_page']
    assert row['instruction'] in original['text']
    assert row['instruction_effect'] == effect
    assert row['latest_actm'] is None, 'no printed early-call lead on these originals'
    if effect == 'availability':
        assert row['actor'] == 'service'
    elif effect == 'not_required':
        assert not is_call_line(row)
    else:
        assert row['actor'] == 'crew'
        assert row['applicability_state'] == 'conditions_unresolved'
    if identity == '1E1936/26':
        assert row['printed_details']['frequencies'] == ['135.075MHZ', '124.925MHZ']
        assert any('128.925MHZ' in a['sentence'] for a in row['actions'])
        assert any(c['text'] == 'IN CASE OF NO CONTACT' for c in row['conditions'])
    if identity == '1A1816/26':
        assert row['printed_details']['frequencies'] == ['5637 KHZ', '2989 KHZ']
    if identity == '1A2393/26':
        assert row['printed_details']['frequencies'] == ['126.500MHZ', '122.00MHZ']
        assert 'B346, R474, W21 AND G473' in row['instruction']
    if identity == 'SX45/26':
        # Genuine SQ314 crosses after midnight; SQ352 crosses before start.
        validity = next(c for c in row['conditions'] if c['kind'] == 'validity')
        assert validity['result'] == ('not_met' if 'SQ_352_' in filename else 'met')
        assert row['applicability_state'] == ('not_applicable' if 'SQ_352_' in filename else 'conditions_held')
        assert 'UN-AVBL' in original['text'] and 'SELCAL' in original['text']
        assert not is_call_line(row)
    if identity in ('1F4441/26', '1G2801/26'):
        assert 'UNMONITORED' in row['instruction'] and '0300-0430 0730-0900' in row['instruction']
        assert '780-890-8557' not in row['printed_details']['frequencies']
        assert not is_call_line(row)
    if identity == '1C576/26':
        assert 'REPORT TO ATS' in row['instruction']
        assert any(c['text'] == 'report trigger: GNSS JAMMING' for c in row['conditions'])
    if identity == '1E45/26':
        assert row['instruction'] == 'CHECK ACT WITH OOSTENDE APP AND BRUSSELS FIC.'
        assert not row['printed_details']['lead'] and not row['printed_details']['frequencies']


@pytest.mark.parametrize('text', ['TRANG DVOR/DME FREQ 116.6 MHZ UNAVAILABLE ON ATS RTE W14.',
                                 'AVIANO NDB FREQ 390.00KHZ UNSERVICEABLE.',
                                 'WEATHER RADAR OUT OF SERVICE.',
                                 'RADIO ALTIMETER FREQ 4.3 GHZ U/S.',
                                 'NDB FREQ 390KHZ UNMONITORED.',
                                 'CALL ATFM OFFICE AT TEL 123456789 FOR OPTIONAL QUERIES.'])
def test_frequency_navigation_weather_and_telephone_are_not_crew_contact_evidence(text):
    from app.odss.enroute_contact import procedure_kind
    assert procedure_kind(text) is None


@pytest.mark.parametrize('filename,identity,page', [
    ('SQ02325072026JFK.pdf', '1G218/26', 108),
    ('SQ36604082026SIN.pdf', '1G218/26', 88),
    ('SQ30316072026BRU 81.pdf', 'SX16/25', 83),
    ('SQ91021082026SIN.pdf', '1A1846/26', 37),
    ('lido-briefing_SQ_194_16Aug2026_SIN_HAN.pdf', '1A86/26', 37),
    ('lido-briefing_SQ_882_10Sep2026_SIN_HKG.pdf', '1A1997/26', 47),
    ('SQ02325072026JFK.pdf', '1G269/26', 108),
    ('SQ02325072026JFK.pdf', '1G221/26', 108),
])
def test_genuine_nonvoice_atc_duties_keep_source_population_and_never_become_calls(filename, identity, page):
    source = private_cfp_source(filename)
    flight = parse_lido(extract_pages(source), filename)
    original = next(r for r in flight['notam_procedure_records'] if r['notam_id'] == identity)
    composed = compose_enroute_contact(flight)
    row = next(r for r in composed['procedures'] if r['notam_id'] == identity)
    assert row['kind'] == 'atc_duty' and row['source_page'] == page
    assert row['instruction'] in original['text']
    assert not is_call_line(row) and row['latest_actm'] is None
    assert row['printed_details'] == {'frequencies': [], 'lead': None, 'interval': None, 'addresses': []}
    if identity == '1G218/26':
        entry = next(a for a in row['actions'] if 'LAST ASSIGNED SSR CODE' in a['sentence'])
        departure = next(a for a in row['actions'] if 'A2000' in a['sentence'])
        assert 'A2000' not in entry['sentence'] and 'LAST ASSIGNED' not in departure['sentence']
        assert entry['scope'] == 'fir_entry' and entry['applicability_state'] == 'conditions_held'
        assert departure['scope'] == 'aerodrome' and departure['applicability_state'] == 'not_applicable'
        assert 'LAST ASSIGNED SSR CODE' in row['instruction'] and 'A2000' not in row['instruction']
    elif identity in ('1G269/26', '1G221/26'):
        assert row['actor'] == 'crew' and row['conditions']
        if identity == '1G269/26':
            assert row['instruction_effect'] == 'prohibited'
            assert 'EXCEPT IN CASE OF TRAFFIC AVOIDANCE OR EMERGENCY' in row['instruction']
            assert row['applicability_state'] == 'conditions_unresolved'
        else:
            assert row['instruction_effect'] == 'instruction'
            assert row['applicability_state'] == 'conditions_held'
    else:
        assert row['applicability_state'] == 'conditions_unresolved'
        assert row['conditions'], 'area/equipage/prior approval is not held for this aircraft'


@pytest.mark.parametrize('text', [
    'ATS NOT AVAILABLE IN THE SYNTHETIC FIR.',
    'ATS IS NOT PROVIDED.',
    'AIR TRAFFIC SERVICES ARE TEMPORARILY NOT PROVIDED.',
])
def test_ats_service_status_is_nonvoice_availability_without_a_call(text):
    composed = compose_enroute_contact(synthetic_flight(text))
    row = composed['procedures'][0]
    assert row['kind'] == 'atc_duty' and row['actor'] == 'service'
    assert row['instruction_effect'] == 'availability' and row['latest_actm'] is None
    assert not is_call_line(row)


def test_independent_unpunctuated_transponder_subjects_do_not_share_aerodrome_scope():
    # LABELLED SYNTHETIC: two duties, new subjects, no inserted source punctuation.
    flight = synthetic_flight('FLIGHTS ENTERING THE SYNTHETIC ALPHA FIR SHALL SQUAWK THE ASSIGNED SSR CODE '
                              'AIRCRAFT DEPARTING AERODROMES IN THE SYNTHETIC ALPHA FIR MUST SQUAWK CODE A3000.')
    flight['route_waypoints'].append({'name': 'ZZBB', 'fir_boundary': 'ZZBB', 'actm_minutes': 120, 'source_page': 1})
    row = compose_enroute_contact(flight)['procedures'][0]
    assert len(row['actions']) == 2
    assert row['actions'][0]['scope'] == 'fir_entry'
    assert row['actions'][0]['applicability_state'] == 'conditions_held'
    assert row['actions'][1]['scope'] == 'aerodrome'
    assert row['actions'][1]['applicability_state'] == 'not_applicable'
    assert row['kind'] == 'atc_duty' and not is_call_line(row) and row['latest_actm'] is None


def test_sq23_physical_pdf_keeps_outage_text_and_source_identity_in_its_six_page_format(tmp_path):
    from app.analysis import run_odss_analysis
    from app.odss.combined_brief import render_combined_briefing
    source = private_cfp_source('SQ02325072026JFK.pdf')
    import json
    result = run_odss_analysis(source, tmp_path / 'analysis', tmp_path / 'reports', 1)
    payload = json.loads(Path(result['analysis_path']).read_text())
    target = tmp_path / 'SQ23-Flight-Briefing.pdf'
    render_combined_briefing(payload['flight'], payload['findings'], payload.get('view', {}).get('warnings') or [], target,
                            source_pdf_path=str(source), weather_charts=payload.get('weather_charts') or {})
    with fitz.open(target) as document:
        assert len(document) == 6
        text = ' '.join(' '.join(page.get_text().split()) for page in document)
    assert 'COM CPDLC ROUTE MESSAGING NOT AVBL' in text
    assert '1A487/26' in text
    assert 'p98' in text


@pytest.mark.parametrize('minutes,result', [(119, 'not_met'), (120, 'met'), (121, 'met')])
def test_hf_outage_validity_uses_actual_crossing_instant_over_midnight(minutes, result):
    # LABELLED SYNTHETIC: the service starts after departure, at midnight.
    flight = synthetic_flight('HF RT ALONG WITH SELCAL WILL REMAIN UN-AVBL DUE UNSERVICEABILITY.')
    flight['scheduled_departure_utc'] = '2026-08-15T22:00:00Z'
    flight['route_waypoints'][0]['actm_minutes'] = minutes
    flight['notam_procedure_records'][0]['validity'] = '16-AUG-26 0000 - 15-FEB-27 2359'
    composed = compose_enroute_contact(flight)
    row = composed['procedures'][0]
    assert next(c for c in row['conditions'] if c['kind'] == 'validity')['result'] == result
    assert row['instruction_effect'] == 'availability' and not is_call_line(row)
    assert not composed['required_calls'] and row['latest_actm'] is None


def test_same_fir_quote_with_different_windows_keeps_separate_display_rows():
    flight = synthetic_flight('COM CPDLC ROUTE MESSAGING NOT AVBL')
    second = {**flight['notam_procedure_records'][0], 'notam_id': 'SYNTHETIC-SECOND/26',
              'validity': '01-JUN-26 0000 - 31-DEC-26 2359', 'source_page': 3}
    flight['notam_procedure_records'].append(second)
    composed = compose_enroute_contact(flight)
    assert len(composed['procedure_lines']) == 2
    assert {line['notam_ids'][0] for line in composed['procedure_lines']} == {'SYNTHETIC-QA/26', 'SYNTHETIC-SECOND/26'}
    assert all(line['applicability_state'] == 'conditions_held' for line in composed['procedure_lines'])


@pytest.mark.parametrize('difference', [None, 'validity', 'condition', 'timed', 'further_actions'])
def test_pdf_identical_untimed_status_grouping_preserves_identity_and_never_changes_held_rows(difference):
    from app.odss.operational_format import _compact_untimed_availability_lines
    flight = synthetic_flight('COM CPDLC ROUTE MESSAGING NOT AVBL')
    flight['route_waypoints'] = []
    flight['notam_procedure_records'].append({**flight['notam_procedure_records'][0], 'notam_id': 'SYNTHETIC-SECOND/26',
                                             'fir': 'ZZBB', 'heading': 'ZZBB SYNTHETIC BRAVO FIR', 'source_page': 3})
    lines = compose_enroute_contact(flight)['procedure_lines']
    if difference == 'validity':
        lines[1]['conditions_summary'] = lines[1]['conditions_summary'].replace('01-JAN-26', '01-JUN-26')
    elif difference == 'condition':
        lines[1]['conditions_summary'] += ' · SYNTHETIC equipment approval unresolved'
    elif difference == 'timed':
        lines[1]['actm'] = '01:00'
    elif difference == 'further_actions':
        lines[1]['further_actions'] += 1
    original = deepcopy(lines)
    rendered = _compact_untimed_availability_lines(lines)
    assert lines == original
    assert len(rendered) == (1 if difference is None else 2)
    assert {identity for row in rendered for identity in row['notam_ids']} == {'SYNTHETIC-QA/26', 'SYNTHETIC-SECOND/26'}
    assert {page for row in rendered for page in row['source_pages']} == {2, 3}
    assert {fir for row in rendered for fir in row['fir'].split('/')} == {'ZZAA', 'ZZBB'}
    if difference is None:
        assert 'source FIR ZZAA/ZZBB;' in rendered[0]['conditions_summary']


def test_last_capacity_step_uses_source_order_and_defers_whole_distinct_untimed_rows():
    from app.odss.operational_format import _first_untimed_status_lines
    flight = synthetic_flight('COM CPDLC ROUTE MESSAGING NOT AVBL')
    flight['route_waypoints'] = []
    base = flight['notam_procedure_records'][0]
    flight['notam_procedure_records'] = [
        {**base, 'source_page': 4, 'text': 'VHF RADIO 132.1MHZ U/S.'},
        {**base, 'notam_id': 'SYNTHETIC-SECOND/26', 'source_page': 2},
        {**base, 'notam_id': 'SYNTHETIC-THIRD/26', 'fir': 'ZZBB', 'heading': 'ZZBB SYNTHETIC BRAVO FIR', 'source_page': 3},
        {**base, 'notam_id': 'SYNTHETIC-SECOND/26', 'source_page': 2, 'validity': '01-JUN-26 0000 - 31-DEC-26 2359'},
    ]
    lines = compose_enroute_contact(flight)['procedure_lines']
    original = deepcopy(lines)
    shown = _first_untimed_status_lines(lines)
    assert len(shown) == 2
    assert {page for row in shown for page in row['source_pages']} == {2, 3}
    assert all('01-JAN-26' in row['conditions_summary'] for row in shown)
    deferred = [row for row in lines if row not in shown]
    assert len(deferred) == 2 and all(row in original for row in deferred)
    assert lines == original


@pytest.mark.parametrize('text,actor,label', [
    ('ATC UNITS SHALL ENSURE SSR TRANSPONDERS ARE OPERATING BEFORE GRANTING A DEPARTURE CLEARANCE.', 'atc', 'ATC provision'),
    ('GROUND ENGINEERS MUST TEST SSR EQUIPMENT DURING THE SYNTHETIC MAINTENANCE PERIOD.', 'other', 'Other actor duty'),
    ('THE SYNTHETIC TEST TEAM SHALL ENSURE AIRCRAFT MUST TEST SSR EQUIPMENT.', 'other', 'Other actor duty'),
    ('SSR TRANSPONDERS SHALL BE OPERATED AT ALL TIMES.', 'crew', 'ATC duty'),
    ('NAVIGATION AND ANTI-COLLISION LIGHTS SHALL BE DISPLAYED AT ALL TIMES.', 'crew', 'ATC duty'),
])
def test_explicit_source_subject_determines_actor_and_displayed_duty(text, actor, label):
    """LABELLED SYNTHETIC: equipment mentions do not replace an explicit actor."""
    composed = compose_enroute_contact(synthetic_flight(text))
    row = composed['procedures'][0]
    assert row['actor'] == actor
    assert all(action['actor'] == actor for action in row['actions'])
    summary = composed['procedure_lines'][0]['conditions_summary']
    assert summary.startswith(label + ' ·')
    assert not is_call_line(row)
    assert row['latest_actm'] is None
    if actor != 'crew':
        assert 'ATC duty' not in summary


@pytest.mark.parametrize('filename,identity', [
    ('SQ36604082026SIN.pdf', '1A3431/26'),
    ('lido-briefing_SQ_194_16Aug2026_SIN_HAN.pdf', '1A1825/26'),
])
def test_genuine_publication_public_health_reference_not_admitted_as_atc_crew_duty(filename, identity):
    """The original bulletin remains in the app's full-source surface; no duty is invented."""
    source = private_cfp_source(filename)
    flight = parse_lido(extract_pages(source), source.name)
    assert not any(r['notam_id'] == identity for r in flight['notam_procedure_records'])
    assert not any(r['notam_id'] == identity for r in compose_enroute_contact(flight)['procedures'])


@pytest.mark.parametrize('text', [
    'PILOTS SHALL FOLLOW THE PUBLIC HEALTH QUARANTINE PROCEDURES.',
    'AIRCRAFT SHALL ENTER QUARANTINE AREAS ONLY AFTER HEALTH APPROVAL.',
    'PILOTS SHALL FOLLOW PUBLIC HEALTH PROCEDURES IN MANY COUNTRIES.',
    'AIRCRAFT SHALL ENTER QUARANTINE AREAS IN SOME COUNTRIES.',
    'AIRCRAFT SHALL ENTER QUARANTINE AREAS WITHIN THE SYNTHETIC FIR.',
])
def test_labelled_synthetic_non_operating_action_target_stays_source_only(text):
    from app.odss.enroute_contact import procedure_kind
    assert procedure_kind(text) is None


def test_labelled_synthetic_assigned_flight_level_is_a_crew_control_duty():
    row = compose_enroute_contact(synthetic_flight('PILOTS SHALL MAINTAIN THE ASSIGNED FLIGHT LEVEL.'))['procedures'][0]
    assert row['kind'] == 'atc_duty' and row['actor'] == 'crew'
    assert not is_call_line(row)


def test_labelled_synthetic_passive_equipment_keeps_its_explicit_other_agent():
    composed = compose_enroute_contact(synthetic_flight('SSR TRANSPONDERS SHALL BE OPERATED BY GROUND ENGINEERS DURING THE SYNTHETIC MAINTENANCE PERIOD.'))
    row = composed['procedures'][0]
    assert row['actor'] == 'other'
    assert all(action['actor'] == 'other' for action in row['actions'])
    assert composed['procedure_lines'][0]['conditions_summary'].startswith('Other actor duty ·')
    assert not is_call_line(row)


def test_labelled_synthetic_crew_code_instruction_does_not_inherit_the_assigner():
    row = compose_enroute_contact(synthetic_flight('FLIGHTS SHALL CONTINUE TO SQUAWK THE SSR CODE ASSIGNED BY THE ATS UNIT.'))['procedures'][0]
    assert row['actor'] == 'crew'


@pytest.mark.parametrize('filename,sha256,identity,page', [
    ('SQ02325072026JFK.pdf', '45c781ab4a8644f92e4cde7c13da8d7ec13cd4b4cc9b0bb827011b9dbabfc016', '1G193/26', 109),
    ('SQ02325072026JFK.pdf', '45c781ab4a8644f92e4cde7c13da8d7ec13cd4b4cc9b0bb827011b9dbabfc016', '1G219/26', 109),
    ('lido-briefing_SQ_304_12Jul2026_SIN_BRU.pdf', 'ffb63085badc026e1db590b289be80590d551a58b6a699a1c8d1c4f79ac9baef', 'SX8/13', 78),
    ('SQ30316072026BRU 81.pdf', '887d96b5a01ab42e841ca9a61ff4547f6e16facbf24695fb62d63b282c2a4177', '1M2411/26', 74),
    ('lido-briefing_SQ_24_15Aug2026_SIN_JFK.pdf', 'ef773ec3cc808f2269522ae608750e4bd1cdab33a17603842c3fd7837815e240', '1A664/26', 92),
    ('lido-briefing_SQ_24_15Aug2026_SIN_JFK.pdf', 'ef773ec3cc808f2269522ae608750e4bd1cdab33a17603842c3fd7837815e240', '1A1973/26', 94),
])
def test_genuine_qualified_aircraft_atc_duty_reaches_first_layer(filename, sha256, identity, page):
    import hashlib
    source = private_cfp_source(filename)
    assert hashlib.sha256(source.read_bytes()).hexdigest() == sha256
    parsed = parse_lido(extract_pages(source), source.name)
    record = next((row for row in parsed['notam_procedure_records'] if row['notam_id'] == identity and row['source_page'] == page), None)
    assert record, 'full-source reference alone does not present a typed operating duty'
    composed = compose_enroute_contact(parsed)
    row = next((row for row in composed['procedures'] if row['notam_id'] == identity and row['source_page'] == page), None)
    assert row and row['kind'] == 'atc_duty'
    assert not is_call_line(row) and row['latest_actm'] is None
    assert all(action['sentence'] in record['text'] for action in row['actions'])
    if identity == '1G193/26':
        assert row['instruction'] == record['text'], 'joined exception population remains complete'
    if identity == '1M2411/26':
        assert any('LF-R20' in condition['text'] and 'AVORD' in condition['text'] for condition in row['conditions'])
    assert not row['printed_details']['frequencies']


@pytest.mark.parametrize('filename,identities', [
    ('SQ30316072026BRU 81.pdf', {'1A1599/26': 73, '1B578/26': 72, '1R10/26': 72}),
    ('SQ36604082026SIN.pdf', {'1E1741/26': 98}),
])
def test_other_genuine_six_page_pdfs_keep_untimed_outage_identities_and_truthful_deferral(tmp_path, filename, identities):
    import json
    from app.analysis import run_odss_analysis
    from app.odss.combined_brief import render_combined_briefing
    source = private_cfp_source(filename)
    result = run_odss_analysis(source, tmp_path / 'analysis', tmp_path / 'reports', 1)
    payload = json.loads(Path(result['analysis_path']).read_text())
    original = deepcopy(payload['flight']['notam_procedure_records'])
    target = tmp_path / 'Flight-Briefing.pdf'
    render_combined_briefing(payload['flight'], payload['findings'], payload.get('view', {}).get('warnings') or [], target,
                            source_pdf_path=str(source), weather_charts=payload.get('weather_charts') or {})
    assert payload['flight']['notam_procedure_records'] == original
    with fitz.open(target) as document:
        assert len(document) == 6
        text = ' '.join(' '.join(page.get_text().split()) for page in document)
    for identity, page in identities.items():
        assert identity in text and f'p{page}' in text
    assert 'source-held ATC/communications notices' in text and 'route/time unresolved' in text
    assert 'further rows on the dashboard' in text
    assert 'FPL' in text and 'NOTAM' in text
    import re
    card = text.split('FIR / COMMUNICATION', 1)[1].split('FIR crossings (OFP ACTM)', 1)[0]
    held_lines = compose_enroute_contact(payload['flight'])['procedure_lines']
    printed_rows = re.split(r'\+\d+ further rows on the dashboard', card, maxsplit=1)[0]
    visible = sum(any(identity in printed_rows for identity in line['notam_ids']) for line in held_lines)
    deferred = re.search(r'\+(\d+) further rows on the dashboard', card)
    assert deferred and int(deferred.group(1)) == len(held_lines) - visible
    if 'SQ366' in filename:
        assert '1G216/26' in text and '125.2MHZ' in text and 'not later than ACTM 05:25' in text

import hashlib

import pytest

from app.odss.enroute_contact import compose_enroute_contact, is_call_line
from app.odss.parser import extract_pages, parse_lido
from tests.atc_test_inputs import load_enroute_fixture, private_cfp_source

REPORTING = 'ALL PILOTS PROMPTLY REP TO ATC OF SUCH INTERFERENCE WITH APPROPRIATE DETAILS.'
CONTINUATION = 'DRG FREQ INTERFERENCE, TAKE NECESSARY MEASURES FOR SAFE AND EFFICIENT CONTINUATION OF FLT NAV AND IN CASE OF NAVIGATIONAL DIFFICULTY, NOTIFY ATC FOR ASSISTANCE.'
CASES = [('SQ304-SIN-BRU', 90), ('SQ366-SIN-FCO', 86), ('SQ303-BRU-SIN', 88),
         ('SQ23-JFK-SIN', 110), ('SQ322-SIN-LHR', 70), ('SQ352-SIN-CPH', 77)]


def synthetic(text):
    return {'departure': 'WSSS', 'destination': 'VHHH', 'scheduled_departure_utc': '2026-06-01T01:00:00Z',
            'route_waypoints': [{'name': 'ZZAA', 'fir_boundary': 'ZZAA', 'actm_minutes': 60, 'source_page': 1}],
            'notam_procedure_records': [{'notam_id': 'SYNTHETIC/26', 'validity': '01-JAN-26 0000 - 31-DEC-26 2359',
            'heading': 'ZZAA SYNTHETIC FIR', 'heading_kind': 'fir', 'fir': 'ZZAA', 'source_page': 2, 'text': text}]}


def no_invented_values(row, model):
    assert row['latest_actm'] is None and row['printed_details']['lead'] is None
    assert not row['printed_details']['frequencies'] and not model['required_calls']


@pytest.mark.parametrize('name,page', CASES)
def test_genuine_explicit_abbreviated_pilot_report_retains_its_unproved_event(name, page):
    fixture = load_enroute_fixture(name)
    source = private_cfp_source(fixture['source']['file'])
    assert hashlib.sha256(source.read_bytes()).hexdigest() == fixture['source']['sha256']
    held = next(r for r in fixture['flight']['notam_procedure_records'] if r['notam_id'] == 'SX9/26')
    assert held['source_page'] == page and f'. {REPORTING} {CONTINUATION}' in held['text']
    model = compose_enroute_contact(fixture['flight'], fixture['findings'])
    row = next(r for r in model['procedures'] if r['notam_id'] == held['notam_id'] and r['source_page'] == page)
    assert row['instruction'] == REPORTING and row['actor'] == 'crew'
    assert row['instruction_effect'] == 'instruction' and row['applicability_state'] == 'conditions_unresolved'
    assert [a['sentence'] for a in row['actions']] == [REPORTING, CONTINUATION]
    assert all(a['actor'] == 'crew' and a['applicability_state'] == 'conditions_unresolved' for a in row['actions'])
    assert any(c['text'] == 'report trigger: SUCH INTERFERENCE' and c['result'] == 'unresolved' for c in row['actions'][0]['conditions'])
    assert any(c['text'].startswith('reporting context: ') and '100NM AROUND' in c['text'] and c['result'] == 'unresolved' for c in row['actions'][0]['conditions'])
    assert any(c['text'] == 'DRG FREQ INTERFERENCE' and c['result'] == 'unresolved' for c in row['actions'][1]['conditions'])
    assert any('IN CASE OF NAVIGATIONAL DIFFICULTY' in c['text'] and c['result'] == 'unresolved' for c in row['actions'][1]['conditions'])
    assert row['validity'] == held['validity']
    line = next(l for l in model['procedure_lines'] if l['fir'] == row['fir'] and held['notam_id'] in l['notam_ids'])
    assert line['actor'] == 'crew' and page in line['source_pages']
    assert 'Actor unresolved' not in line['conditions_summary'] and 'Other actor duty' not in line['conditions_summary']
    assert 'reporting condition: SUCH INTERFERENCE: not evaluable from the OFP' in line['conditions_summary']
    no_invented_values(row, model)


def test_genuine_sq24_july_inform_atc_is_qualified_by_any_adverse_impact():
    source = private_cfp_source('SQ02422072026SIN.pdf')
    assert hashlib.sha256(source.read_bytes()).hexdigest() == '3ab4209fb201479cd30719376141dd23181562c523037b8315ca2466bffc7527'
    flight = parse_lido(extract_pages(source), source.name)
    held = next(r for r in flight['notam_procedure_records'] if r['notam_id'] == '1G2346/26')
    assert held['source_page'] == 90 and held['heading'] == 'CZYZ TORONTO FIR'
    assert held['text'].endswith('GNSS SIGNAL MAY BE PERIODICALLY INTERRUPTED. INFORM ATC OF ANY ADVERSE IMPACT.')
    model = compose_enroute_contact(flight)
    row = next(r for r in model['procedures'] if r['notam_id'] == held['notam_id'])
    assert row['instruction'] == 'INFORM ATC OF ANY ADVERSE IMPACT.' and row['actor'] == 'crew'
    assert row['applicability_state'] == 'conditions_unresolved'
    assert any(c['text'] == 'report trigger: ANY ADVERSE IMPACT' and c['result'] == 'unresolved' for c in row['conditions'])
    assert any(c['text'].startswith('reporting context: DAILY 0400-1059') and 'RADIUS 228NM' in c['text'] and 'FL400-UNL' in c['text'] and c['result'] == 'unresolved' for c in row['conditions'])
    no_invented_values(row, model)


def test_genuine_epww_crew_reporting_and_provider_status_references_remain_unchanged():
    fixture = load_enroute_fixture('SQ352-SIN-CPH')
    source = private_cfp_source(fixture['source']['file'])
    assert hashlib.sha256(source.read_bytes()).hexdigest() == fixture['source']['sha256']
    row = next(r for r in compose_enroute_contact(fixture['flight'], fixture['findings'])['procedures'] if r['notam_id'] == '1C576/26')
    assert row == next(r for r in fixture['enroute_contact']['procedures'] if r['notam_id'] == '1C576/26')
    assert row['actor'] == 'crew' and row['applicability_state'] == 'conditions_unresolved'
    assert any(c['text'] == 'report trigger: GNSS JAMMING' and c['result'] == 'unresolved' for c in row['conditions'])
    for text in ['ANCHORAGE ARTCC AUTOMATION USES TWO DIFFERENT CPDLC LOGON ADDRESSES.',
                 'COM CPDLC FULL SER ROUTE ADVISORY AND HOLD MSG AVBL ON KUSA']:
        reference = compose_enroute_contact(synthetic(text))['procedures'][0]
        assert reference['actor'] != 'crew' and not is_call_line(reference)


@pytest.mark.parametrize('subject,manner,verb', [('PILOTS', '', 'REP'), ('PILOTS', 'PROMPTLY ', 'REPORT'),
                                             ('CREWS', 'IMMEDIATELY ', 'INFORM'), ('ACFT CREWS', 'PROMPTLY ', 'NOTIFY')])
def test_labelled_direct_reporting_subject(subject, manner, verb):
    text = f'ALL {subject} {manner}{verb} TO ATC OF SUCH INTERFERENCE.'
    model = compose_enroute_contact(synthetic(text))
    row = model['procedures'][0]
    assert row['instruction'] == text and row['actor'] == 'crew'
    assert row['instruction_effect'] == 'instruction' and row['applicability_state'] == 'conditions_unresolved'
    assert any(c['text'] == 'report trigger: SUCH INTERFERENCE' and c['result'] == 'unresolved' for c in row['conditions'])
    no_invented_values(row, model)


@pytest.mark.parametrize('text', ['INFORM ATC OF ANY ADVERSE IMPACT.', 'REP TO ATC OF SUCH INTERFERENCE.'])
def test_labelled_reporting_imperative_retains_own_event(text):
    row = compose_enroute_contact(synthetic(text))['procedures'][0]
    assert row['actor'] == 'crew' and row['applicability_state'] == 'conditions_unresolved'


@pytest.mark.parametrize('text,actor', [
    ('ATC UNITS SHALL INFORM PILOTS TO REP TO ATC OF SUCH INTERFERENCE.', 'atc'),
    ('GROUND ENGINEERS MUST ASK PILOTS TO REP TO ATC OF SUCH INTERFERENCE.', 'other'),
    ('ATC UNITS PROMPTLY REP TO ATC OF SUCH INTERFERENCE.', 'unresolved'),
    ('PILOTS WITH UNPROVEN EQUIPMENT PROMPTLY REP TO ATC OF SUCH INTERFERENCE.', 'unresolved'),
])
def test_labelled_other_or_unparsed_subject_cannot_borrow_pilot_report(text, actor):
    model = compose_enroute_contact(synthetic(text))
    row = model['procedures'][0]
    assert row['actor'] == actor and not is_call_line(row)
    assert row['applicability_state'] == 'conditions_unresolved'
    no_invented_values(row, model)


@pytest.mark.parametrize('text,effect', [('PILOTS MAY REP TO ATC OF SUCH INTERFERENCE.', 'permission'),
                                      ('PILOTS MUST NOT REP TO ATC OF SUCH INTERFERENCE.', 'prohibited'),
                                      ('PILOTS ARE NOT REQUIRED TO INFORM ATC OF ANY ADVERSE IMPACT.', 'not_required')])
def test_labelled_explicit_modal_still_governs_report(text, effect):
    row = compose_enroute_contact(synthetic(text))['procedures'][0]
    assert row['actor'] == 'crew' and row['instruction_effect'] == effect
    assert row['applicability_state'] == 'conditions_unresolved' and not is_call_line(row)


def test_labelled_unconditional_position_instruction_does_not_acquire_event_or_deadline():
    model = compose_enroute_contact(synthetic('INFORM ATC OF YOUR POSITION.'))
    row = model['procedures'][0]
    assert row['actor'] == 'crew' and row['applicability_state'] == 'conditions_held'
    assert not any(c['text'].startswith('report trigger:') for c in row['conditions'])
    no_invented_values(row, model)


@pytest.mark.parametrize('date,action,actor,effect', [
    ('ON 01 MAY', 'ALL PILOTS PROMPTLY REP TO ATC OF SUCH INTERFERENCE.', 'crew', 'instruction'),
    ('ON 31 DEC 26', 'AIR CREWS IMMEDIATELY INFORM ATC OF ANY ADVERSE IMPACT.', 'crew', 'instruction'),
    ('ON 1 JAN 2027', 'ACFT CREWS REP TO ATC OF SUCH INTERFERENCE.', 'crew', 'instruction'),
    ('ON 15 OCT', 'REP TO ATC OF SUCH INTERFERENCE.', 'crew', 'instruction'),
    ('ON 01 MAY', 'ATC UNITS SHALL INFORM PILOTS TO REP TO ATC OF SUCH INTERFERENCE.', 'atc', 'instruction'),
    ('ON 01 MAY', 'GROUND ENGINEERS MUST ASK PILOTS TO REP TO ATC OF SUCH INTERFERENCE.', 'other', 'instruction'),
    ('ON 01 MAY', 'CPDLC MESSAGES SHALL BE SENT BY GROUND ENGINEERS TO ATC.', 'other', 'instruction'),
    ('ON 01 MAY', 'PILOTS MAY REP TO ATC OF SUCH INTERFERENCE.', 'crew', 'permission'),
    ('ON 01 MAY', 'PILOTS MUST NOT REP TO ATC OF SUCH INTERFERENCE.', 'crew', 'prohibited'),
    ('ON 01 MAY', 'PILOTS MAY NOT BE ABLE TO REP TO ATC OF SUCH INTERFERENCE.', 'crew', 'capability'),
])
def test_labelled_literal_date_keeps_own_unresolved_condition_and_actor_effect(date, action, actor, effect):
    text = f'{date}, {action}'
    model = compose_enroute_contact(synthetic(text))
    row = model['procedures'][0]
    assert row['instruction'] == text and row['actor'] == actor and row['instruction_effect'] == effect
    assert row['applicability_state'] == 'conditions_unresolved'
    assert any(c['kind'] == 'qualifier' and c['text'] == date and c['result'] == 'unresolved' for c in row['conditions'])
    if 'SUCH INTERFERENCE' in action or 'ANY ADVERSE IMPACT' in action:
        assert any(c['text'].startswith('report trigger: ') and c['result'] == 'unresolved' for c in row['conditions'])
    if actor != 'crew' or effect != 'instruction' or 'NOT BE ABLE' in action:
        assert not is_call_line(row)
    no_invented_values(row, model)


@pytest.mark.parametrize('prefix', ['ON 00 MAY,', 'ON 32 MAY,', 'ON 01 MAYBE,', 'ON 01 MAY'])
def test_labelled_malformed_date_syntax_cannot_promote_unparsed_subject(prefix):
    text = f'{prefix} ALL PILOTS PROMPTLY REP TO ATC OF SUCH INTERFERENCE.'
    model = compose_enroute_contact(synthetic(text))
    row = model['procedures'][0]
    assert row['instruction'] == text and row['actor'] != 'crew'
    assert row['applicability_state'] == 'conditions_unresolved' and not is_call_line(row)
    no_invented_values(row, model)


@pytest.mark.parametrize('agent,actor', [('GROUND ENGINEERS', 'other'), ('ATC UNITS', 'atc')])
def test_labelled_undated_direct_passive_sent_by_retains_actual_actor(agent, actor):
    text = f'CPDLC MESSAGES SHALL BE SENT BY {agent} TO ATC.'
    model = compose_enroute_contact(synthetic(text))
    row = model['procedures'][0]
    assert row['instruction'] == text and row['actor'] == actor and not is_call_line(row)
    no_invented_values(row, model)


def test_labelled_dated_crew_code_use_keeps_subordinate_assigned_by_atc_provider():
    text = 'ON 01 MAY, PILOTS SHALL USE THE SSR CODE ASSIGNED BY ATC.'
    model = compose_enroute_contact(synthetic(text))
    row = model['procedures'][0]
    assert row['instruction'] == text and row['actor'] == 'crew' and row['kind'] == 'atc_duty'
    assert row['instruction_effect'] == 'instruction' and row['applicability_state'] == 'conditions_unresolved'
    assert any(c['text'] == 'ON 01 MAY' and c['result'] == 'unresolved' for c in row['conditions'])
    assert not is_call_line(row)
    no_invented_values(row, model)

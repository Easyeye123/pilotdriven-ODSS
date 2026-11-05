import hashlib

import pytest

from app.odss.enroute_contact import compose_enroute_contact, is_call_line, procedure_kind, sentences
from tests.atc_test_inputs import load_enroute_fixture, private_cfp_source

ASSISTANCE = 'ATC UNITS UPON REQ WILL PROVIDE NAV ASSISTANCE TO ACFT (BY USING RADAR VECTORING).'
CASES = [
    ('SQ303-BRU-SIN', 76, '887d96b5a01ab42e841ca9a61ff4547f6e16facbf24695fb62d63b282c2a4177'),
    ('SQ304-SIN-BRU', 97, 'ffb63085badc026e1db590b289be80590d551a58b6a699a1c8d1c4f79ac9baef'),
    ('SQ322-SIN-LHR', 77, 'f2a722c0f8cfc743cdbdde38270853b40783e12c27c5b3328d3e9e550beaa56f'),
    ('SQ352-SIN-CPH', 87, '2162330ae3b544b6af770cdc14ebd3fa657db69d1d7fc302adf00fd77d76adf1'),
]


def synthetic(text):
    return {'departure': 'WSSS', 'destination': 'VHHH', 'scheduled_departure_utc': '2026-06-01T01:00:00Z',
            'route_waypoints': [{'name': 'ZZAA', 'fir_boundary': 'ZZAA', 'actm_minutes': 60, 'source_page': 1}],
            'notam_procedure_records': [{'notam_id': 'SYNTHETIC/26', 'validity': '01-JAN-26 0000 - 31-DEC-26 2359',
            'heading': 'ZZAA SYNTHETIC FIR', 'heading_kind': 'fir', 'fir': 'ZZAA', 'source_page': 2, 'text': text}]}


@pytest.mark.parametrize('name,page,sha256', CASES)
def test_genuine_crew_reporting_and_atc_assistance_keep_separate_actors(name, page, sha256):
    fixture = load_enroute_fixture(name)
    source = private_cfp_source(fixture['source']['file'])
    assert fixture['source']['sha256'] == sha256
    assert hashlib.sha256(source.read_bytes()).hexdigest() == sha256
    held = next(r for r in fixture['flight']['notam_procedure_records'] if r['notam_id'] == 'SX2/25')
    assert held['source_page'] == page and held['heading'] == 'LZBB BRATISLAVA FIR'
    assert 'ACFT CREWS ARE REQ TO INFORM THE APPROPRIATE ATC UNIT UPON DETECTION OF GNSS INTERFERENCE' in held['text']
    assert held['text'].endswith(ASSISTANCE)
    assert sentences(held['text'])[-1] == ASSISTANCE
    assert procedure_kind(ASSISTANCE) is None
    composed = compose_enroute_contact(fixture['flight'], fixture['findings'])
    row = next(r for r in composed['procedures'] if r['notam_id'] == held['notam_id'])
    assert row['actor'] == 'crew' and len(row['actions']) == 1
    action = row['actions'][0]
    assert action['actor'] == 'crew' and action['sentence'] == sentences(held['text'])[0]
    assert action['instruction_effect'] == 'instruction'
    assert action['applicability_state'] == 'conditions_unresolved'
    assert any(c['text'] == 'report trigger: GNSS INTERFERENCE' and c['result'] == 'unresolved' for c in action['conditions'])
    assert row['source_page'] == page and row['validity'] == held['validity']
    assert row['latest_actm'] is None and not row['printed_details']['frequencies']
    assert row['printed_details']['lead'] is None
    line = next(r for r in composed['procedure_lines'] if r['fir'] == row['fir'] and held['notam_id'] in r['notam_ids'])
    assert line['actor'] == 'crew' and page in line['source_pages']
    assert 'Other actor' not in line['conditions_summary'] and 'ATC provision' not in line['conditions_summary']
    assert 'reporting condition: GNSS INTERFERENCE: not evaluable from the OFP' in line['conditions_summary']


@pytest.mark.parametrize('aircraft', ['ACFT', 'AIRCRAFT', 'AFCT'])
@pytest.mark.parametrize('crew', ['CREW', 'CREWS'])
def test_labelled_compound_crew_is_qualified_reporting_subject(aircraft, crew):
    text = f'GNSS - INTERFERENCE {aircraft} {crew} ARE REQ TO INFORM ATC UPON DETECTION OF GNSS INTERFERENCE.'
    composed = compose_enroute_contact(synthetic(text))
    row = composed['procedures'][0]
    assert row['instruction'] == text and row['actor'] == 'crew' and row['actions'][0]['actor'] == 'crew'
    assert row['instruction_effect'] == 'instruction' and row['applicability_state'] == 'conditions_unresolved'
    assert any(c['text'] == 'report trigger: GNSS INTERFERENCE' and c['result'] == 'unresolved' for c in row['conditions'])
    assert row['latest_actm'] is None and not row['printed_details']['frequencies']
    assert row['printed_details']['lead'] is None and not composed['required_calls']


@pytest.mark.parametrize('subject,actor,label', [
    ('ATC UNITS', 'atc', 'ATC provision'),
    ('GROUND ENGINEERS', 'other', 'Other actor duty'),
    ('AIRPORT OPERATIONS STAFF', 'other', 'Other actor duty'),
])
def test_labelled_other_actor_mentioning_crews_does_not_transfer_its_duty(subject, actor, label):
    text = f'{subject} SHALL INFORM ACFT CREWS TO CONTACT ATC UPON DETECTION OF GNSS INTERFERENCE.'
    composed = compose_enroute_contact(synthetic(text))
    row = composed['procedures'][0]
    assert row['instruction'] == text and row['actor'] == actor and row['actions'][0]['actor'] == actor
    assert not is_call_line(row) and not composed['required_calls']
    assert composed['procedure_lines'][0]['conditions_summary'].startswith(f'{label} · ')


def test_labelled_separate_crew_and_provider_sentences_cannot_borrow_actors():
    reporting = 'AIRCRAFT CREWS SHALL REPORT GNSS INTERFERENCE TO ATC.'
    provider = 'ATC UNITS SHALL INFORM ACFT CREWS TO CONTACT ATC.'
    row = compose_enroute_contact(synthetic(f'{reporting} {provider}'))['procedures'][0]
    assert [(a['sentence'], a['actor']) for a in row['actions']] == [(reporting, 'crew'), (provider, 'atc')]
    assert row['actions'][0]['applicability_state'] == 'conditions_unresolved'
    assert not is_call_line(row['actions'][1])

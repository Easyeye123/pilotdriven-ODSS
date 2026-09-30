import json
from pathlib import Path

import pytest

from app.odss.enroute_contact import compose_enroute_contact, is_call_line
from app.odss.operational_format import compact_conditions_summary

APP = Path(__file__).resolve().parents[3] / 'pd-code-e-helpyou-20260921'
FIXTURE = json.loads((APP / 'tests/fixtures/enroute-contact/SQ24-SIN-JFK-15AUG.json').read_text())
PERMISSION = 'ACFT WI VHF COVERAGE MAY MAKE POSITION REPORTS VIA CPDLC COMMUNICATIONS.'


def synthetic(text):
    return {'departure': 'WSSS', 'destination': 'VHHH', 'scheduled_departure_utc': '2026-06-01T01:00:00Z',
            'route_waypoints': [{'name': 'ZZAA', 'fir_boundary': 'ZZAA', 'actm_minutes': 60, 'source_page': 1}],
            'notam_procedure_records': [{'notam_id': 'SYNTHETIC/26', 'validity': '01-JAN-26 0000 - 31-DEC-26 2359',
            'heading': 'ZZAA SYNTHETIC FIR', 'heading_kind': 'fir', 'fir': 'ZZAA', 'source_page': 2, 'text': text}]}


def test_genuine_paza_permission_retains_unproved_coverage_and_printed_may():
    assert FIXTURE['source']['sha256'] == 'ef773ec3cc808f2269522ae608750e4bd1cdab33a17603842c3fd7837815e240'
    held = next(r for r in FIXTURE['flight']['notam_procedure_records'] if r['notam_id'] == '1A44/24')
    assert held['source_page'] == 84 and PERMISSION in held['text']
    row = next(r for r in compose_enroute_contact(FIXTURE['flight'])['procedures'] if r['notam_id'] == held['notam_id'])
    action = next(a for a in row['actions'] if a['sentence'] == PERMISSION)
    assert action['actor'] == 'crew' and action['instruction_effect'] == 'permission'
    assert not is_call_line(action)
    assert action['applicability_state'] == 'conditions_unresolved'
    assert any(c['text'] == 'WI VHF COVERAGE' and c['result'] == 'unresolved' for c in action['conditions'])
    assert row['source_page'] == held['source_page']


@pytest.mark.parametrize('qualifier', ['WI VHF COVERAGE', 'WITHIN VHF COVERAGE', 'OUTSIDE VHF COVERAGE'])
def test_labelled_optional_logon_preserves_qualifier_without_call_deadline(qualifier):
    text = f'ACFT {qualifier} MAY LOGON TO SYNTHETIC ATSU 10 MIN BEFORE ENTRY.'
    composed = compose_enroute_contact(synthetic(text))
    row = composed['procedures'][0]
    assert row['instruction'] == text and row['actor'] == 'crew'
    assert row['instruction_effect'] == 'permission' and row['applicability_state'] == 'conditions_unresolved'
    assert any(c['text'] == qualifier and c['result'] == 'unresolved' for c in row['conditions'])
    assert row['latest_actm'] is None and not is_call_line(row) and not composed['required_calls']
    summary = composed['procedure_lines'][0]['conditions_summary']
    assert summary.startswith('Communications permission · ')
    assert compact_conditions_summary(summary, 0).startswith('Communications permission · ')


def test_genuine_paza_abbreviated_departure_and_logon_event_remain_unproved():
    text = 'ACFT DEP ALASKAN AP ARE REQUESTED TO LOGON AFTER DEP BUT BEFORE CLIMBING ABV FL180.'
    held = next(r for r in FIXTURE['flight']['notam_procedure_records'] if r['notam_id'] == '1A44/24')
    assert text in held['text']
    row = next(r for r in compose_enroute_contact(FIXTURE['flight'])['procedures'] if r['notam_id'] == held['notam_id'])
    action = next(a for a in row['actions'] if a['sentence'] == text)
    assert action['actor'] == 'crew' and action['instruction_effect'] == 'instruction'
    assert action['applicability_state'] == 'conditions_unresolved'
    assert any(c['text'] == 'DEP ALASKAN AP' and c['result'] == 'unresolved' for c in action['conditions'])
    assert any(c['text'] == 'AFTER DEP BUT BEFORE CLIMBING ABV FL180' and c['result'] == 'unresolved' for c in action['conditions'])
    assert row['latest_actm'] is None


def test_labelled_abbreviated_departure_and_event_do_not_borrow_a_fir_clock():
    for population in ['DEP ALASKAN AP', 'DEP SYNTHETIC AIRPORTS', 'DEPARTING SYNTHETIC AIRPORTS']:
        text = f'ACFT {population} ARE REQUESTED TO LOGON AFTER DEP BUT BEFORE CLIMBING ABV FL180.'
        composed = compose_enroute_contact(synthetic(text))
        row = composed['procedures'][0]
        assert row['actor'] == 'crew' and row['applicability_state'] == 'conditions_unresolved'
        assert any(c['text'] == population and c['result'] == 'unresolved' for c in row['conditions'])
        assert any(c['text'] == 'AFTER DEP BUT BEFORE CLIMBING ABV FL180' and c['result'] == 'unresolved' for c in row['conditions'])
        assert row['latest_actm'] is None and not composed['required_calls']


def test_labelled_unrecognised_subject_does_not_consume_unaccounted_restriction():
    row = compose_enroute_contact(synthetic('ACFT ONLY WI VHF COVERAGE SHALL MAKE POSITION REPORTS VIA CPDLC COMMUNICATIONS.'))['procedures'][0]
    assert row['applicability_state'] == 'conditions_unresolved'
    assert any('WI VHF COVERAGE' in c['text'] and c['result'] == 'unresolved' for c in row['conditions'])


def test_labelled_may_not_service_uncertainty_other_actor_and_month_stay_distinct():
    row = compose_enroute_contact(synthetic('ACFT WI VHF COVERAGE MAY NOT LOGON TO SYNTHETIC ATSU.'))['procedures'][0]
    assert row['instruction_effect'] == 'prohibited' and not is_call_line(row)
    row = compose_enroute_contact(synthetic('CPDLC MAY BE UN-AVBL WI VHF COVERAGE.'))['procedures'][0]
    assert row['instruction_effect'] == 'availability' and row['actor'] == 'service'
    row = compose_enroute_contact(synthetic('CPDLC SERVICES MAY NOT BE AVAILABLE.'))['procedures'][0]
    assert row['instruction_effect'] == 'availability' and row['actor'] == 'service' and not is_call_line(row)
    composed = compose_enroute_contact(synthetic('GROUND ENGINEERS MAY TEST CPDLC EQUIPMENT.'))
    row = composed['procedures'][0]
    assert row['actor'] == 'other' and row['instruction_effect'] == 'permission' and not is_call_line(row)
    assert composed['procedure_lines'][0]['conditions_summary'].startswith('Other actor permission · ')
    row = compose_enroute_contact(synthetic('PILOTS SHALL LOGON TO SYNTHETIC ATSU ON 01 MAY.'))['procedures'][0]
    assert row['instruction_effect'] == 'instruction'


def test_labelled_nonvoice_may_and_may_not_stay_distinct():
    for text, effect in [('PILOTS MAY SQUAWK A2000.', 'permission'), ('PILOTS MAY NOT SQUAWK A2000.', 'prohibited')]:
        row = compose_enroute_contact(synthetic(text))['procedures'][0]
        assert row['kind'] == 'atc_duty' and row['actor'] == 'crew'
        assert row['instruction_effect'] == effect and not is_call_line(row)
        assert row['latest_actm'] is None and not row['printed_details']['frequencies']


def test_labelled_possible_inability_is_capability_not_an_act_prohibition():
    for text in ['PILOTS MAY NOT BE ABLE TO SQUAWK A2000.', 'PILOTS MAY BE UNABLE TO SQUAWK A2000.']:
        composed = compose_enroute_contact(synthetic(text))
        row = composed['procedures'][0]
        assert row['instruction'] == text and row['actor'] == 'crew'
        assert row['instruction_effect'] == 'capability'
        assert row['applicability_state'] == 'conditions_unresolved'
        assert any(c['text'] == text and c['result'] == 'unresolved' for c in row['conditions'])
        summary = composed['procedure_lines'][0]['conditions_summary']
        assert summary.startswith('Capability unresolved · ')
        assert compact_conditions_summary(summary, 0).startswith('Capability unresolved · ')
        assert not is_call_line(row) and row['latest_actm'] is None
        assert not row['printed_details']['frequencies'] and not composed['required_calls']
    row = compose_enroute_contact(synthetic('PILOTS MAY NOT SQUAWK A2000.'))['procedures'][0]
    assert row['instruction_effect'] == 'prohibited'


def test_labelled_subordinate_or_mixed_may_does_not_erase_shall():
    for text in ['ACFT WHICH MAY LOGON TO CPDLC SHALL MONITOR ATC ON 121.5MHZ.',
                 'PILOTS MAY MONITOR ATC BUT SHALL REPORT VIA CPDLC.']:
        row = compose_enroute_contact(synthetic(text))['procedures'][0]
        assert row['instruction'] == text and row['instruction_effect'] == 'instruction'
        assert row['applicability_state'] == 'conditions_unresolved'
        assert any(c['text'] == text and c['result'] == 'unresolved' for c in row['conditions'])
        assert not is_call_line(row) and row['latest_actm'] is None
    row = compose_enroute_contact(synthetic('PILOTS SHALL MONITOR ATC BUT MAY REPORT VIA CPDLC.'))['procedures'][0]
    assert row['instruction_effect'] == 'instruction'


def test_labelled_leading_and_trailing_calendar_may_never_create_mixed_modal_restriction():
    for text in ['ON 01 MAY PILOTS SHALL LOGON TO SYNTHETIC ATSU.',
                 'PILOTS SHALL LOGON TO SYNTHETIC ATSU ON 01 MAY.', 'ACFT DEPARTING ON 01 MAY SHALL LOGON TO SYNTHETIC ATSU.']:
        row = compose_enroute_contact(synthetic(text))['procedures'][0]
        assert row['instruction_effect'] == 'instruction'
        assert not any(c.get('note') == 'permission and obligation clause scope unresolved' for c in row['conditions'])

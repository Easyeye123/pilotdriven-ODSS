"""ATC-CLEARANCE-FAMILY review, actor of an excepted statement (1 Oct 2026, ITEM1 production QA of release 444, SQ24 Aug).

The genuine SQ24 (15 Aug) OFP prints the Bedminster TFR 1A664/26 under "KZNY A0664/26" (pp92-93). Its first held action
reads "EXC AS SPECIFIED BLW AND/OR UNLESS AUTH BY ATC IN CONSULTATION WITH THE AIR TFC SECURITY COORDINATOR VIA THE
DOMESTIC EVENTS NETWORK (DEN): A. ALL ACFT OPS WI THE 10NM RADIUS AREA(S) ... ARE PROHIBITED EXC FOR: ..." and release
444 labelled it an ATC provision: the actor reader took "BY ATC" from the authorisation exception as the statement's
agent. The generic repair, in both languages: an agent printed inside a circumstance or exception is not the
statement's actor; an exception closed by a colon leads its statement as a circumstance does; "ACFT OPS" is the
aircraft-operations subject "ACFT OPERATIONS" already is. Limits, populations, exceptions, the unknown owner and timing
stay unresolved, and the emergency coordination stays its own qualified statement. ATC as the real agent stays ATC.
"""
import hashlib

import pytest

from app.odss.enroute_contact import compose_enroute_contact, is_call_line
from app.odss.parser import extract_pages, parse_lido
from tests.atc_test_inputs import private_cfp_source

SQ24 = ("lido-briefing_SQ_24_15Aug2026_SIN_JFK.pdf", "ef773ec3cc808f2269522ae608750e4bd1cdab33a17603842c3fd7837815e240")
EXCEPTION = ("EXC AS SPECIFIED BLW AND/OR UNLESS AUTH BY ATC IN CONSULTATION WITH THE AIR TFC SECURITY COORDINATOR VIA THE "
             "DOMESTIC EVENTS NETWORK (DEN)")
INNER_CORE = "WI THE 10NM RADIUS AREA(S) LISTED ABV, KNOWN AS THE INNER CORE(S)"
COORDINATION = ("ALL EMERGENCY / LIFE SAVING FLT(MEDICAL / LAW ENFORCEMENT / FIREFIGHTING) OPS MUST COORDINATE WITH ATC PRIOR "
                "TO THEIR DEP AT 215-492-4123/1985 TO AVOID POTENTIAL DELAYS.")


def synthetic(text):
    return {'departure': 'WSSS', 'destination': 'VHHH', 'scheduled_departure_utc': '2026-06-01T01:00:00Z',
            'route_waypoints': [{'name': 'ZZAA', 'fir_boundary': 'ZZAA', 'actm_minutes': 60, 'source_page': 1}],
            'notam_procedure_records': [{'notam_id': 'SYNTHETIC/26', 'validity': '01-JAN-26 0000 - 31-DEC-26 2359',
            'heading': 'ZZAA SYNTHETIC FIR', 'heading_kind': 'fir', 'fir': 'ZZAA', 'source_page': 2, 'text': text}]}


def test_genuine_excepted_aircraft_operations_prohibition_is_the_crews_with_every_qualification_unresolved():
    source = private_cfp_source(SQ24[0])
    assert hashlib.sha256(source.read_bytes()).hexdigest() == SQ24[1]
    flight = parse_lido(extract_pages(source), SQ24[0])
    record = next(r for r in flight['notam_procedure_records'] if r['notam_id'] == '1A664/26')
    assert (record['heading'], record['heading_kind'], record['source_page']) == ('KZNY A0664/26', 'topic', 92)
    row = next(r for r in compose_enroute_contact(flight, [])['procedures'] if r['notam_id'] == '1A664/26')
    prohibition, coordination = row['actions']
    assert prohibition['sentence'].startswith(f'{EXCEPTION}: A. ALL ACFT OPS {INNER_CORE}, ARE PROHIBITED EXC FOR: APPROVED LAW ENFORCEMENT')
    # The aircraft-operations prohibition is the crew's; ATC appears only in its authorisation exception.
    assert (prohibition['actor'], prohibition['instruction_effect']) == ('crew', 'prohibited')
    for expected in ({'kind': 'qualifier', 'text': EXCEPTION, 'result': 'unresolved'},
                     {'kind': 'qualifier', 'text': INNER_CORE, 'result': 'unresolved'},
                     {'kind': 'restriction', 'text': 'EXC FOR: APPROVED LAW ENFORCEMENT', 'result': 'unresolved'},
                     {'kind': 'qualifier', 'text': 'source airspace limits, population and exceptions', 'result': 'unresolved'},
                     {'kind': 'association', 'text': 'owning FIR not established: printed under KZNY A0664/26', 'result': 'unresolved'}):
        assert expected in prohibition['conditions']
    assert next(c for c in prohibition['conditions'] if c['kind'] == 'validity')['result'] == 'unresolved'
    assert prohibition['applicability_state'] == 'conditions_unresolved'
    # The emergency coordination stays its own qualified statement.
    assert coordination['sentence'] == COORDINATION
    assert (coordination['actor'], coordination['instruction_effect']) == ('crew', 'instruction')
    assert any(c['kind'] == 'population' and c['result'] == 'unresolved' for c in coordination['conditions'])
    assert row['fir'] == '' and row['actm'] is None and row['latest_actm'] is None and not is_call_line(row)
    assert row['printed_details'] == {'frequencies': [], 'lead': None, 'interval': None, 'addresses': []}


@pytest.mark.parametrize('text,actor,effect,qualifications', [
    ('EXC AS SPECIFIED BLW AND/OR UNLESS AUTH BY ATC: A. ALL ACFT OPS WI THE SYNTHETIC AREA SHALL SQUAWK 7777.', 'crew', 'instruction',
     ['EXC AS SPECIFIED BLW AND/OR UNLESS AUTH BY ATC', 'WI THE SYNTHETIC AREA']),
    ('EXC AS AUTH BY SYNTHETIC ATC: ALL ACFT OPS WI THE SYNTHETIC AREA ARE PROHIBITED FROM ENTERING THE SYNTHETIC AIRSPACE.', 'crew', 'prohibited',
     ['EXC AS AUTH BY SYNTHETIC ATC', 'WI THE SYNTHETIC AREA']),
    ('UNLESS AUTHORIZED BY ATC, ALL ACFT OPS WI THE SYNTHETIC AREA SHALL SQUAWK 7777.', 'crew', 'instruction',
     ['UNLESS AUTHORIZED BY ATC', 'WI THE SYNTHETIC AREA']),
    ('ALL ACFT OPS WI THE SYNTHETIC AREA SHALL SQUAWK 7777 UNLESS OTHERWISE AUTHORIZED BY ATC.', 'crew', 'instruction',
     ['UNLESS OTHERWISE AUTHORIZED BY ATC', 'WI THE SYNTHETIC AREA']),
    ('ALL ACFT OPS WI THE SYNTHETIC AREA SHALL SQUAWK 7777.', 'crew', 'instruction', ['WI THE SYNTHETIC AREA']),
    ('THE TRANSPONDER CODE SHALL BE ASSIGNED BY ATC.', 'atc', 'instruction', []),
])
def test_labelled_an_agent_inside_an_exception_is_not_the_statements_actor(text, actor, effect, qualifications):
    row = compose_enroute_contact(synthetic(text))['procedures'][0]
    assert (row['actor'], row['instruction_effect']) == (actor, effect)
    texts = [c['text'] for c in row['conditions'] if c['result'] == 'unresolved']
    assert all(q in texts for q in qualifications)
    assert not is_call_line(row) and row['latest_actm'] is None

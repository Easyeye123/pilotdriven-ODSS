"""ATC-CLEARANCE-FAMILY (1 Oct 2026, ITEM1 production QA of release 444).

The genuine SQ23 OFP prints CO188/02 under LTAA ANKARA FIR on p106: climb and descent clearances issued by Ercan Control
while aircraft are in Nicosia airspace, "DO NOT ACCEPT THESE CLEARANCES AND IF CONTENTION EXISTS ,SEEK CLARIFICATION
FROM NICOSIA CONTROL", a Jeppesen reference and the company annotation "AP FOR RHC AUTH-MPSD 777". The raw FIR source
disclosure held it; the structured ATC record did not, because procedure_kind enumerated contact / call / report verbs
and the parser held only notices it admitted. The same gap dropped the SQ605 / SQ606 NON-RNAV radar-vector requests to
DAEGU / INCHEON ACC. The generic repair, in both languages:
  admission  a request, clarification or confirmation addressed to an ATC unit, and the refusal or acceptance of an ATC
             clearance or ATC instruction, are communications with ATC on positive ATC evidence only: an ATC authority
             by name, a call sign whose name the notice or heading prints as airspace, an ATC clearance type, or a
             referent whose antecedent is one of those; maintenance units / clearances / instructions (on any medium),
             terrain clearance, flow-unit and phone queries are not; an act inside a qualifying clause qualifies; a
             negated act (MAY NOT, WILL NOT ...) is a prohibition, never a positive call;
  boundary   a stop printed without a following space ends a sentence (AIRSPACE.DO, CONTROL.REF) except inside a dotted
             address; a crew directive coordinated with a conditional instruction, and an unpunctuated list item opening
             its own crew request, are separate statements with their own effect and conditions;
  context    statements of one printed sentence that refers back to its notice's clearances hold that notice's text
             before and after, verbatim and unresolved: no annotation is decoded, no aircraft applicability asserted;
  values     a navigation aid's own frequency is never a printed communication value.
No flight, notice identity or answer is special-cased: the originals below are evidence, the synthetic texts are labelled.
"""
import hashlib

import pytest

from app.odss.enroute_contact import compose_enroute_contact, is_call_line, procedure_kind, sentences
from app.odss.parser import extract_pages, parse_lido
from tests.atc_test_inputs import private_cfp_source

PROVIDER = ("CO188/02-F/L CHANGES IN NICOSIA FIR ON OCCASION,CLIMB AND DESCENT CLEARANCES ARE ISSUED BY ERCAN CONTROL "
            "WHILST A/C ARE IN NICOSIA AIRSPACE.")
REFUSAL = "DO NOT ACCEPT THESE CLEARANCES"
CLARIFICATION = "IF CONTENTION EXISTS ,SEEK CLARIFICATION FROM NICOSIA CONTROL."
FOOTER = "REF PGS SIA 2-1 AND 2-2 UNDER ENRTE SECTION OF THE JEPP REF MANUAL AP FOR RHC AUTH-MPSD 777"
CO188_BODY = f"{PROVIDER}{REFUSAL} AND {CLARIFICATION}{FOOTER}"
CO188_ORIGINALS = [
    ("SQ02325072026JFK.pdf", "45c781ab4a8644f92e4cde7c13da8d7ec13cd4b4cc9b0bb827011b9dbabfc016", 106),
    ("SQ30316072026BRU 81.pdf", "887d96b5a01ab42e841ca9a61ff4547f6e16facbf24695fb62d63b282c2a4177", 83),
    ("SQ36507082026FCO.pdf", "1be9a94eb5e5dffb25bd02aec61fc3a1adf9b13953bec27ee43345fdf5a02d4b", 66),
    ("SQ36604082026SIN.pdf", "a5090c7d2473e0cef81ec320c846f6d44885ed6ed0ff54ec320a898ae913edc3", 90),
    ("lido-briefing_SQ_304_12Jul2026_SIN_BRU.pdf", "ffb63085badc026e1db590b289be80590d551a58b6a699a1c8d1c4f79ac9baef", 93),
    ("lido-briefing_SQ_314_15Aug2026_SIN_LGW.pdf", "11e92fadc1c7874a2f950d3c48cbc6281974ce91d48222329608538545754efa", 95),
    ("lido-briefing_SQ_322_16Aug2026_SIN_LHR.pdf", "f2a722c0f8cfc743cdbdde38270853b40783e12c27c5b3328d3e9e550beaa56f", 74),
    ("lido-briefing_SQ_326_16Aug2026_SIN_FRA.pdf", "d7b35300044ca86fe2045cff0a21bc5dffcdeaf5c522b786f2b2dc741ac68ef6", 60),
    ("lido-briefing_SQ_352_15Aug2026_SIN_CPH.pdf", "2162330ae3b544b6af770cdc14ebd3fa657db69d1d7fc302adf00fd77d76adf1", 80),
]
SQ605 = ("SQ60508092026ICN.pdf", "b3e6b7917734e061570ece7701564e153264dd33562fcd347a0d1feb0bafd24e")
SQ606 = ("SQ60606092026SIN.pdf", "eb48aa102321295fffcd78561d673a30c078f6638e4bb4a2a0ee766461661ba7")
ACC_REQUESTS = [
    (SQ605, "1Z624/26", 60, "SOT SONGTAN",
     "3. NON-RNAV ACFT REQUEST RADAR VECTOR TO DAEGU / INCHEON ACC BEFORE FLYING ON THE AIRWAYS WITHIN THE SOT COVERAGE",
     "BEFORE FLYING ON THE AIRWAYS WITHIN THE SOT COVERAGE"),
    (SQ606, "1Z624/26", 72, "SOT SONGTAN",
     "3. NON-RNAV ACFT REQUEST RADAR VECTOR TO DAEGU / INCHEON ACC BEFORE FLYING ON THE AIRWAYS WITHIN THE SOT COVERAGE",
     "BEFORE FLYING ON THE AIRWAYS WITHIN THE SOT COVERAGE"),
    (SQ606, "SX62/26", 75, "PSN BUSAN",
     "C. NON-RNAV ACFT REQ RADAR VECTOR TO DAEGU/INCHEON ACC BEFORE FLYING ON THE AWY WI THE PSN COVERAGE.",
     "BEFORE FLYING ON THE AWY WI THE PSN COVERAGE"),
    (SQ606, "SX40/26", 75, "PSN BUSAN",
     "C. NON-RNAV ACFT REQ RADAR VECTOR TO DAEGU / INCHEON ACC BFR FLY ON THE AWY WI THE PSN COVERAGE.",
     "BFR FLY ON THE AWY WI THE PSN COVERAGE"),
]

_FLIGHTS: dict = {}


def genuine(filename, sha256):
    if filename not in _FLIGHTS:
        source = private_cfp_source(filename)
        assert hashlib.sha256(source.read_bytes()).hexdigest() == sha256
        flight = parse_lido(extract_pages(source), filename)
        _FLIGHTS[filename] = (flight, compose_enroute_contact(flight, []))
    return _FLIGHTS[filename]


def synthetic(text, heading='ZZAA SYNTHETIC FIR'):
    return {'departure': 'WSSS', 'destination': 'VHHH', 'scheduled_departure_utc': '2026-06-01T01:00:00Z',
            'route_waypoints': [{'name': 'ZZAA', 'fir_boundary': 'ZZAA', 'actm_minutes': 60, 'source_page': 1}],
            'notam_procedure_records': [{'notam_id': 'SYNTHETIC/26', 'validity': '01-JAN-26 0000 - 31-DEC-26 2359',
            'heading': heading, 'heading_kind': 'fir', 'fir': 'ZZAA', 'source_page': 2, 'text': text}]}


def texts(conditions):
    return [c['text'] for c in conditions]


# ---------------------------------------------------------------- CO188/02 on every genuine original that prints it


@pytest.mark.parametrize('filename,sha256,page', CO188_ORIGINALS)
def test_genuine_crew_clearance_refusal_and_contention_clarification_are_held_qualified(filename, sha256, page):
    flight, model = genuine(filename, sha256)
    record = next(r for r in flight['notam_procedure_records'] if r['notam_id'] == 'CO188/02')
    # The parser holds the whole notice under its own printed owner and page; nothing is moved to Nicosia (LCCC).
    assert record['text'] == CO188_BODY
    assert (record['heading'], record['heading_kind'], record['fir']) == ('LTAA ANKARA FIR', 'fir', 'LTAA')
    assert record['source_page'] == page and record['validity'] == '13-DEC-02 0229 - UFN'
    row = next(r for r in model['procedures'] if r['notam_id'] == 'CO188/02')
    assert row['fir'] == 'LTAA' and row['association'] == 'fir_heading' and row['source_page'] == page
    assert row['actm'] == next(c['actm'] for c in model['crossings'] if c['fir'] == 'LTAA')
    # The provider statement is no crew action; the refusal and the clarification are two statements.
    assert [a['sentence'] for a in row['actions']] == [REFUSAL, CLARIFICATION]
    refusal, clarification = row['actions']
    assert (refusal['actor'], refusal['instruction_effect'], refusal['kind']) == ('crew', 'prohibited', 'voice_contact')
    assert (clarification['actor'], clarification['instruction_effect']) == ('crew', 'instruction')
    assert {'kind': 'qualifier', 'text': 'IF CONTENTION EXISTS', 'result': 'unresolved'} in clarification['conditions']
    assert not any('CONTENTION' in text for text in texts(refusal['conditions']))
    for action in row['actions']:
        # Ercan's clearances while in Nicosia airspace, the reference and the company annotation stay with both
        # statements, verbatim and unresolved; the annotation is not decoded into any aircraft applicability.
        assert {'kind': 'qualifier', 'text': f'clearance context: {PROVIDER}', 'result': 'unresolved'} in action['conditions']
        assert {'kind': 'qualifier', 'text': f'further notice text: {FOOTER}', 'result': 'unresolved'} in action['conditions']
        assert next(c for c in action['conditions'] if c['kind'] == 'validity')['text'] == '13-DEC-02 0229 - UFN'
        assert action['applicability_state'] == 'conditions_unresolved'
        assert all(c['result'] != 'not_met' for c in action['conditions'])
        assert not any('A350' in text or 'AIRCRAFT TYPE' in text for text in texts(action['conditions']))
        assert action['printed_details'] == {'frequencies': [], 'lead': None, 'interval': None, 'addresses': []}
    # The refusal governs the row; it is never presented as a call, a deadline or a frequency.
    assert row['instruction'] == REFUSAL and row['actor'] == 'crew' and row['instruction_effect'] == 'prohibited'
    assert not is_call_line(row) and row['latest_actm'] is None and row['next_fir'] is None
    assert not row['printed_details']['frequencies'] and row['printed_details']['lead'] is None
    line = next(l for l in model['procedure_lines'] if 'CO188/02' in l['notam_ids'])
    assert line['further_actions'] == 1 and page in line['source_pages']
    assert line['conditions_summary'].startswith('Communication prohibition · validity 13-DEC-02 0229 - UFN')
    assert f'further notice text: {FOOTER}: not evaluable from the OFP' in line['conditions_summary']
    assert 'ATC provision' not in line['conditions_summary'] and 'Other actor' not in line['conditions_summary']
    assert line['conditions_summary'].endswith('conditions unresolved')


# ---------------------------------------------------------------- the radar-vector requests to an ACC


@pytest.mark.parametrize('original,identity,page,heading,printed_request,before_flight', ACC_REQUESTS)
def test_genuine_non_rnav_requests_to_an_acc_are_crew_requests_with_unproved_population(original, identity, page, heading,
                                                                                         printed_request, before_flight):
    flight, model = genuine(*original)
    record = next(r for r in flight['notam_procedure_records'] if r['notam_id'] == identity and r['source_page'] == page)
    assert (record['heading'], record['heading_kind'], record['fir']) == (heading, 'topic', None)
    assert printed_request in record['text']
    row = next(r for r in model['procedures'] if r['notam_id'] == identity and r['source_page'] == page)
    # A navaid / topic heading is no FIR owner; the ACC recipient does not become one.
    assert row['fir'] == '' and row['association'] == 'unresolved' and row['actm'] is None
    assert {'kind': 'association', 'text': f'owning FIR not established: printed under {heading}', 'result': 'unresolved'} in row['conditions']
    action = next(a for a in row['actions'] if a['sentence'] == printed_request)
    assert (action['actor'], action['instruction_effect'], action['kind']) == ('crew', 'instruction', 'voice_contact')
    assert {'kind': 'population', 'text': 'NON-RNAV', 'result': 'unresolved'} in action['conditions']
    assert {'kind': 'restriction', 'text': before_flight, 'result': 'unresolved'} in action['conditions']
    assert action['applicability_state'] == 'conditions_unresolved'
    # No ACC channel, lead or call time is printed: the VORTAC's own 116.900MHZ is its outage identity, not a channel.
    for statement in [row, *row['actions']]:
        assert statement['printed_details']['frequencies'] == [] and statement['printed_details']['lead'] is None
    assert row['latest_actm'] is None
    # The provider's radar service and the expected vectors stay what they are, never crew calls.
    assert not any(a['actor'] == 'crew' and ('RADAR SER WILL BE PROVIDED' in a['sentence'] or a['sentence'].startswith('SID '))
                   for a in row['actions'])


def test_genuine_navaid_frequency_is_not_a_printed_communication_value():
    flight, model = genuine("SQ02325072026JFK.pdf", CO188_ORIGINALS[0][1])
    trang = next(r for r in model['procedures'] if r['notam_id'] == 'SX12/25')
    assert 'TRANG DVOR/DME (TRN) FREQ 116.6 MHZ, CH113X' in next(r['text'] for r in flight['notam_procedure_records'] if r['notam_id'] == 'SX12/25')
    assert trang['printed_details']['frequencies'] == []
    # A communication frequency table keeps every printed channel (positive control on the same original).
    kabul = next(r for r in model['procedures'] if r['notam_id'] == 'SX33/26')
    assert '128.350 MHZ' in kabul['actions'][0]['printed_details']['frequencies']
    tiba = next(r for r in model['procedures'] if r['notam_id'] == '1G216/26')
    assert tiba['printed_details']['frequencies'] == ['125.2MHZ']


def test_genuine_permission_to_request_vectors_does_not_make_an_equipment_duty_a_call():
    flight, model = genuine('lido-briefing_SQ_194_16Aug2026_SIN_HAN.pdf', '83873638b9b09ccbae228cafb9493c52aa6cc46b9631e4ad75d321d7d0f9dd75')
    row = next(r for r in model['procedures'] if r['notam_id'] == 'SX54/24')
    assert row['instruction'] == '3. ALL ACFT SHALL BE EQUIPPED WITH A FUNCTIONAL SURVEILLANCE TRANSPONDER.'
    assert row['kind'] == 'atc_duty' and not is_call_line(row)
    permission = next(a for a in row['actions'] if a['sentence'] == '2. ACFT MAY REQ RADAR VECTORING OR SUGGESTION FM ATC.')
    assert (permission['actor'], permission['instruction_effect'], permission['kind']) == ('crew', 'permission', 'voice_contact')


def test_genuine_coordinated_doubt_clause_qualifies_only_its_own_statement():
    flight, model = genuine("SQ36604082026SIN.pdf", CO188_ORIGINALS[3][1])
    row = next(r for r in model['procedures'] if r['notam_id'] == '1A582/26')
    disregard, verify = row['actions']
    assert disregard['sentence'] == 'PILOTS SHALL DISREGARD ANY NON-STANDARD CALLS'
    assert verify['sentence'] == 'IF IN DOUBT, VERIFY THE CALL AND REPORT TIME, LOCATION AND FL OF THE OCCURRENCE TO ATC UNIT IN CTC.'
    assert not any('IF IN DOUBT' in text for text in texts(disregard['conditions']))
    assert {'kind': 'qualifier', 'text': 'IF IN DOUBT', 'result': 'unresolved'} in verify['conditions']
    for action in row['actions']:
        assert action['actor'] == 'crew'
        assert {'kind': 'qualifier', 'text': 'report trigger: UNAUTHORIZED RADIO TRANSMISSIONS', 'result': 'unresolved'} in action['conditions']


# ---------------------------------------------------------------- labelled synthetic wording variants and controls


@pytest.mark.parametrize('text,heading,effect', [
    ('PILOTS SHALL NOT ACCEPT DIRECT ROUTING CLEARANCES FROM ERCAN CONTROL.', 'ZZAA SYNTHETIC FIR', 'prohibited'),
    ('PILOTS MAY NOT ACCEPT CLEARANCES FROM SYNTHETIC ACC.', 'ZZAA SYNTHETIC FIR', 'prohibited'),
    ('PILOTS WILL NOT ACCEPT CLEARANCES FROM SYNTHETIC ACC.', 'ZZAA SYNTHETIC FIR', 'prohibited'),
    ('PILOTS ARE NOT TO REQUEST DIRECT ROUTING FROM SYNTHETIC ACC.', 'ZZAA SYNTHETIC FIR', 'prohibited'),
    ('NEVER ACCEPT LEVEL CLEARANCES ISSUED ON AN UNPUBLISHED FREQUENCY.', 'ZZAA SYNTHETIC FIR', 'prohibited'),
    ('IF UNABLE, DO NOT ACCEPT CLEARANCES FROM SYNTHETIC ACC.', 'ZZAA SYNTHETIC FIR', 'prohibited'),
    ('PILOTS WHO OPERATE HERE SHALL NOT ACCEPT CLEARANCES FROM SYNTHETIC ACC.', 'ZZAA SYNTHETIC FIR', 'prohibited'),
    ('PILOTS MAY ACCEPT CLEARANCES FROM SYNTHETIC ACC.', 'ZZAA SYNTHETIC FIR', 'permission'),
    ('PILOTS MAY NOT BE ABLE TO ACCEPT CLEARANCES FROM SYNTHETIC ACC.', 'ZZAA SYNTHETIC FIR', 'capability'),
    ('PILOTS ARE NOT REQUIRED TO OBTAIN CLEARANCE FROM SYNTHETIC ACC.', 'ZZAA SYNTHETIC FIR', 'not_required'),
    ('IF IN DOUBT, SEEK CLARIFICATION FROM NICOSIA CONTROL.', 'LCCC NICOSIA FIR', 'instruction'),
    ('ACFT SHALL OBTAIN CLEARANCE FROM BAKU ACC BEFORE ENTERING THE RESTRICTED AREA.', 'ZZAA SYNTHETIC FIR', 'instruction'),
    ('AIRCRAFT WHICH INTEND TO ENTER SHALL OBTAIN CLEARANCE FROM SYNTHETIC ACC.', 'ZZAA SYNTHETIC FIR', 'instruction'),
    ('CONFIRM THE ASSIGNED LEVEL WITH ANKARA CONTROL.', 'LTAA ANKARA FIR', 'instruction'),
    ('PILOTS SHOULD VERIFY ANY DIRECT ROUTING WITH THE RELEVANT ACC.', 'ZZAA SYNTHETIC FIR', 'instruction'),
    ('IGNORE THESE INSTRUCTIONS FROM SYNTHETIC ATC.', 'ZZAA SYNTHETIC FIR', 'instruction'),
    ('IGNORE ATC INSTRUCTIONS TRANSMITTED ON THE COMPANY FREQUENCY.', 'ZZAA SYNTHETIC FIR', 'instruction'),
    ('DISREGARD ANY INSTRUCTION ISSUED BY AN UNAUTHORISED ATC STATION.', 'ZZAA SYNTHETIC FIR', 'instruction'),
    ('PILOTS WHO OPERATE HERE MAY NOT ACCEPT CLEARANCES FROM SYNTHETIC ACC.', 'ZZAA SYNTHETIC FIR', 'prohibited'),
    ('PILOTS WHO OPERATE HERE ARE NOT TO REQUEST DIRECT ROUTING FROM SYNTHETIC ACC.', 'ZZAA SYNTHETIC FIR', 'prohibited'),
    ('IF PILOTS ARE IN DOUBT THEY SHALL SEEK CLARIFICATION FROM SYNTHETIC ACC.', 'ZZAA SYNTHETIC FIR', 'instruction'),
    ('WHEN ENTERING THE FIR PILOTS SHALL REQUEST CLEARANCE FROM SYNTHETIC ACC.', 'ZZAA SYNTHETIC FIR', 'instruction'),
    ('REFUSE ANY ATC INSTRUCTIONS FROM UNIDENTIFIED STATIONS.', 'ZZAA SYNTHETIC FIR', 'instruction'),
    ('ACCEPT CLEARANCES ONLY FROM NICOSIA CONTROL.', 'LCCC NICOSIA FIR', 'instruction'),
])
def test_labelled_clearance_and_clarification_wording_is_a_qualified_crew_statement(text, heading, effect):
    assert procedure_kind(text, f'{heading} {text}') == 'voice_contact'
    model = compose_enroute_contact(synthetic(text, heading))
    row = model['procedures'][0]
    assert row['instruction'] == text and row['instruction_effect'] == effect
    # A printed refusal is never turned into a positive crew action; only a positive instruction is a call row.
    assert row['actor'] in (('crew',) if effect != 'prohibited' else ('crew', 'unresolved'))
    assert row['latest_actm'] is None and not row['printed_details']['frequencies'] and row['printed_details']['lead'] is None
    assert is_call_line(row) == (effect == 'instruction')


def test_labelled_call_sign_is_atc_only_where_the_source_names_its_airspace():
    text = 'IF IN DOUBT, SEEK CLARIFICATION FROM NICOSIA CONTROL.'
    assert procedure_kind(text, f'ZZAA SYNTHETIC FIR {text}') is None
    assert not compose_enroute_contact(synthetic(text))['procedures']
    assert procedure_kind(text, f'ZZAA SYNTHETIC FIR CHANGES IN NICOSIA FIR. {text}') == 'voice_contact'


def test_labelled_contention_clause_stays_unresolved_and_prints_no_invented_value():
    row = compose_enroute_contact(synthetic('IF IN DOUBT, SEEK CLARIFICATION FROM NICOSIA CONTROL.', 'LCCC NICOSIA FIR'))['procedures'][0]
    assert {'kind': 'qualifier', 'text': 'IF IN DOUBT', 'result': 'unresolved'} in row['conditions']
    assert row['applicability_state'] == 'conditions_unresolved'


@pytest.mark.parametrize('text', [
    'ACFT THAT CANNOT OBTAIN CLEARANCE FROM SYNTHETIC ACC SHALL REQUEST RADAR VECTOR FROM SYNTHETIC ACC.',
    'ACFT WHICH MAY NOT ACCEPT CLEARANCES SHALL REQUEST RADAR VECTOR FROM SYNTHETIC ACC.',
])
def test_labelled_qualifying_clause_act_qualifies_the_main_request(text):
    row = compose_enroute_contact(synthetic(text))['procedures'][0]
    assert row['actor'] == 'crew' and row['instruction_effect'] == 'instruction'
    assert row['applicability_state'] == 'conditions_unresolved'


def test_labelled_unmodalled_population_request_keeps_its_crew_actor_and_unproved_navigation_specification():
    row = compose_enroute_contact(synthetic('NON-RNAV ACFT REQ RADAR VECTOR TO DAEGU/INCHEON ACC.'))['procedures'][0]
    assert row['actor'] == 'crew' and row['instruction_effect'] == 'instruction'
    assert {'kind': 'population', 'text': 'NON-RNAV', 'result': 'unresolved'} in row['conditions']
    assert row['applicability_state'] == 'conditions_unresolved'


def test_labelled_unknown_annotation_after_a_referential_refusal_is_quoted_not_decoded():
    text = 'CLIMB CLEARANCES ARE ISSUED BY SYNTH CONTROL. DO NOT ACCEPT THESE CLEARANCES. AP FOR XYZ AUTH-ABC 777'
    row = compose_enroute_contact(synthetic(text))['procedures'][0]
    assert row['instruction'] == 'DO NOT ACCEPT THESE CLEARANCES.' and row['instruction_effect'] == 'prohibited'
    assert {'kind': 'qualifier', 'text': 'clearance context: CLIMB CLEARANCES ARE ISSUED BY SYNTH CONTROL.', 'result': 'unresolved'} in row['conditions']
    assert {'kind': 'qualifier', 'text': 'further notice text: AP FOR XYZ AUTH-ABC 777', 'result': 'unresolved'} in row['conditions']
    # The crossing is held and the validity covers it; the unknown annotation still never resolves either way.
    assert row['applicability_state'] == 'conditions_unresolved' and all(c['result'] != 'not_met' for c in row['conditions'])


@pytest.mark.parametrize('text', [
    'IGNORE MAINTENANCE INSTRUCTIONS.',
    'DO NOT ACCEPT THESE MAINTENANCE INSTRUCTIONS.',
    'GROUND ENGINEERS MUST IGNORE MAINTENANCE INSTRUCTIONS.',
    'IGNORE THESE INSTRUCTIONS FROM THE MAINTENANCE UNIT.',
    'IGNORE MAINTENANCE UNIT INSTRUCTIONS.',
    'SEEK APPROVAL FROM THE MAINTENANCE UNIT.',
    'GROUND ENGINEERS MUST IGNORE THESE INSTRUCTIONS FROM THE MAINTENANCE UNIT.',
    'SEEK APPROVAL FROM MAINTENANCE CONTROL.',
    'IGNORE THESE INSTRUCTIONS FROM THE ENGINEERING UNIT.',
    'SEEK APPROVAL FROM THE TECHNICAL CONTROL.',
    'SEEK ADVICE FROM THE PASSENGER INFORMATION DESK.',
    'IGNORE THESE MAINTENANCE INSTRUCTIONS TRANSMITTED ON THE COMPANY FREQUENCY.',
    'DISREGARD ANY INSTRUCTION ISSUED ON THE AFFECTED FREQUENCY.',
    'DO NOT ACCEPT MAINTENANCE CLEARANCES.',
    'DO NOT ACCEPT THESE CLEARANCES.',
    'ACFT THAT CANNOT OBTAIN CLEARANCE FROM SYNTHETIC ACC SHALL HOLD.',
    'ACFT THAT ARE UNABLE TO OBTAIN CLEARANCE FROM SYNTHETIC ACC SHALL HOLD.',
    'IF PILOTS CANNOT OBTAIN CLEARANCE FROM SYNTHETIC ACC THEY SHALL HOLD.',
    'WHEN UNABLE TO OBTAIN CLEARANCE FROM SYNTHETIC ACC, HOLD AT THE BOUNDARY.',
    'SEEK ADVICE FROM THE AIRPORT OPERATOR.',
    'OBTAIN PERMISSION FROM THE AIRPORT AUTHORITY BEFORE PUSHBACK.',
    'B. AUS WHO ARE UNCERTAIN WHETHER THEIR FLT SHOULD BE EXEMPTED SHOULD CTC TAIPEI ATFMU FOR CLARIFICATION.',
    'RMK: FOR QUERY, CONTACT TAIPEI ATFMU TEL +886-3-3841090.',
    'PILOTS ARE RESPONSIBLE AT ALL TIMES FOR TERRAIN CLEARANCE.',
    'DO NOT ACCEPT REDUCED TERRAIN CLEARANCE.',
    'IT IS CLARIFIED THAT PAKISTAN AIRSPACE IS SAFE FOR ALL TYPES OF ACFT OPS.',
    'RMK/ALL TRAFFIC ON THE AFFECTED ATS ROUTES WILL BE SUBJECT TO ATC CLEARANCE.',
    'CFM USE OF AWY R474 IS POSSIBLE. PLS IGNORE AX322/98 AIP RESTRICTION',
    PROVIDER,
    'ON REQUEST FROM ATC, FLIGHTS WILL BE RE-ROUTED VIA M770.',
    'B. RADAR SER WILL BE PROVIDED BY GIMHAE APP.',
    'IFR ACFT UNDER ATC JURISDICTION SHOULD ANTICIPATE CLEARANCE AROUND THE NOTAMED AREAS.',
])
def test_labelled_non_atc_and_provider_statements_are_not_admitted(text):
    assert procedure_kind(text) is None
    assert not compose_enroute_contact(synthetic(text))['procedures']


@pytest.mark.parametrize('text,actor,effect', [
    ('THE ACC SHALL OBTAIN APPROVAL FROM THE ADJACENT ACC.', 'atc', 'instruction'),
    ('GROUND ENGINEERS MUST DISREGARD ATC INSTRUCTIONS RECEIVED ON THE COMPANY FREQUENCY.', 'other', 'instruction'),
    ('ACFT MAY REQ RADAR VECTORING FM ATC.', 'crew', 'permission'),
])
def test_labelled_provider_other_actor_and_permission_are_never_crew_calls(text, actor, effect):
    row = compose_enroute_contact(synthetic(text))['procedures'][0]
    assert (row['actor'], row['instruction_effect']) == (actor, effect)
    assert not is_call_line(row)


@pytest.mark.parametrize('text,expected', [
    ('A/C ARE IN NICOSIA AIRSPACE.DO NOT ACCEPT THESE CLEARANCES.', ['A/C ARE IN NICOSIA AIRSPACE.', 'DO NOT ACCEPT THESE CLEARANCES.']),
    ('SEEK CLARIFICATION FROM NICOSIA CONTROL.REF PGS SIA 2-1', ['SEEK CLARIFICATION FROM NICOSIA CONTROL.', 'REF PGS SIA 2-1']),
    ('REFER TO WWW.TSA.GOV FOR INFORMATION.', None),
    ('REFER TO JATSC.CO.ID FOR INFORMATION.', None),
    ('SEE FAA.GOV FOR DETAILS.', None),
    ('EMAIL OPS@EXAMPLE.SG FOR INFORMATION.', None),
    ('CONTACT 9-ATO-NCRCC(AT)FAA.GOV OR (866) 598-9522.', None),
    ('DETAILS AT HTTPS://TFR.FAA.GOV/ OR HTTPS://WWW.1800WXBRIEF.COM. IF QUESTIONS REMAIN, CONTACT FSS.',
     ['DETAILS AT HTTPS://TFR.FAA.GOV/ OR HTTPS://WWW.1800WXBRIEF.COM.', 'IF QUESTIONS REMAIN, CONTACT FSS.']),
    ('REFER TO WWW.TSA.GOV.', None),
    ('CONTACT SYNTHETIC ACC ON 121.500MHZ.', None),
    ('WAIT 5 MIN.THEN CONTACT SYNTHETIC ACC.', None),
])
def test_labelled_adjacent_stop_boundaries_keep_addresses_decimals_and_abbreviations_whole(text, expected):
    assert sentences(text) == (expected or [text])

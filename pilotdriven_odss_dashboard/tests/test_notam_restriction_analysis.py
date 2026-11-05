"""A5: source-derived NOTAM analysis must survive both publication surfaces.

The fixture is the verbatim B1 airport corpus, deduplicated by text/kind/timing/role.
No source text or safety classification is altered to make these tests pass.
"""
import gzip
import json
from pathlib import Path
import re

import pytest

from app.odss.engines import _notam_operational_summary
from app.odss.briefing import _compact_notam_family, _compact_notam_text

FIXTURE = Path(__file__).parent / 'fixtures/notam_restriction_source_corpus.json.gz'
ROWS = json.loads(gzip.decompress(FIXTURE.read_bytes()))['rows']
GENERIC = re.compile(r'restriction applies during the applicable', re.I)


def summary(text, kind='runway_approach_restriction', **kwargs):
    return _notam_operational_summary(text, kind, 'destination', **kwargs)


@pytest.mark.parametrize(('source', 'kind', 'expected'), [
    # C1: this notice says the whole of itself in one clause, so publishing all
    # of it reproduces the record and the concise PDF gate refuses the page.
    # The downgrade and what it downgrades to are kept; the parenthetical
    # explanation is dropped behind the ellipsis.
    ('ILS RWY 36C DOWNGRADED TO I/C1/1 (SUPPORTS CAT I OPERATIONS).',
     'runway_approach_restriction', 'ILS RWY 36C downgraded to I/C1/1 …'),
    ('TXL P7 BEHIND ACFT STAND E20 CLSD',
     'taxiway_restriction', 'TXL P7 behind aircraft stand E20 closed.'),
    ('RWY 34C ALS U/S', 'runway_approach_restriction', 'RWY 34C ALS unserviceable.'),
])
def test_real_source_shapes_publish_the_restriction(source, kind, expected):
    assert any(row['text'] == source for row in ROWS), 'Source case must remain in the real corpus'
    held = summary(source, kind)
    assert held == expected
    item = {'summary':held, 'pertinence_kind':kind, 'item_e_text':source}
    assert _compact_notam_text(item, _compact_notam_family(item), dashboard=True, role='destination', planned_runways=set(), reference_time=None) == held


def test_coordinate_defined_area_preserves_its_filed_position():
    row = next(row for row in ROWS if '135526.22N1003713.11E' in row['text'])
    held = summary(row['text'])
    assert held.startswith('Temporarily restricted area active radius 0.5NM centre 135526.22N1003713.11E')
    assert not GENERIC.search(held)


def test_hong_kong_reminder_states_the_restriction_and_marks_omitted_statement():
    row = next(row for row in ROWS if row['location']=='VHHH' and row['notam_id']=='AX31/24')
    held = summary(row['text'])
    assert 'headings to intercept the ILS RWY 25R is not allowed.' in held
    assert 'This NOTAM has further content; open the full NOTAM.' in held
    assert not GENERIC.search(held)


def test_corpus_never_publishes_the_refused_generic_template():
    assert len(ROWS) >= 700
    bad = [(row['location'],row['notam_id']) for row in ROWS
           if GENERIC.search(_notam_operational_summary(row['text'],row['kind'],row['role'],row['applicability']))]
    assert not bad, f'{len(bad)} records still publish a template the dashboard refuses: {bad[:10]}'


def test_timing_review_does_not_turn_into_an_active_restriction():
    held = summary('RWY 25L CLSD', applicability='review')
    assert 'could not be resolved' in held
    assert 'review required' not in held  # R2: the state stands alone


def test_closed_condition_is_never_detached_from_the_head_that_qualifies_it():
    source = 'PROC MAY BE SUSPENDED UNDER THE FLW COND: ADVERSE WEATHER COND; SINGLE PMS IN USE; AIRSPACE ACTIVITIES; RWY OR TWY CLOSURE.'
    held = summary(source)
    assert not held.startswith('RWY OR TWY closure')
    assert 'conditions' in held or 'COND:' in held


@pytest.mark.parametrize(('notam_id','operational'), [
    ('A3807/26', 'aircraft taxiing is not permitted'),
    ('A9894/26', 'I-RXZ ILS or GLIDESLOPE out of service'),
])
def test_explicit_restriction_outranks_reference_nil_and_disregarded_note(notam_id, operational):
    row = next(row for row in ROWS if row['notam_id'] == notam_id)
    held = summary(row['text'])
    assert operational.lower() in held.lower()
    assert not held.startswith(('Refer to AIP', 'Disregard note'))


def test_hong_kong_omission_does_not_claim_an_exact_restriction_count():
    row = next(row for row in ROWS if row['notam_id'] == 'AX32/24')
    held = summary(row['text'])
    assert 'This NOTAM has further content; open the full NOTAM.' in held
    assert not re.search(r'\d+ further (restriction|statement)', held)


def test_plain_filed_closure_outranks_conditional_suspension_list():
    from app.odss.notam_restriction_line import derive_notam_restriction_line
    source = 'RWY 02L CLSD. PROC MAY BE SUSPENDED UNDER THE FLW COND: ADVERSE WEATHER; RWY OR TWY CLOSURE.'
    assert derive_notam_restriction_line(source)['text'].startswith('RWY 02L closed.')


def test_source_decoder_keeps_conditions_and_single_letter_designators():
    from app.odss.notam_restriction_line import derive_notam_restriction_line
    source = 'PROC MAY BE SUSPENDED UNDER THE FLW COND: ADVERSE WEATHER COND; SINGLE PMS IN USE; AIRSPACE ACTIVITIES; RWY OR TWY CLOSURE.'
    line = derive_notam_restriction_line(source)['text']
    assert line.startswith('Procedure may be suspended under the following COND:')
    assert not line.startswith('RWY OR TWY closure')
    line = derive_notam_restriction_line('TWY A CLSD; RWY 02L CLSD DUE WIP AT: NORTHERN END.')['text']
    assert line.startswith('RWY 02L closed due to work in progress at: northern end.')
    line = derive_notam_restriction_line('TWY A AND B CLSD TO CAT C ACFT.')['text']
    assert 'TWY A and B closed to CAT C aircraft.' == line


def test_source_decoder_cannot_hide_unclassified_remainder_or_invent_a_count():
    from app.odss.notam_restriction_line import derive_notam_restriction_line
    source = 'RWY 02L CLSD. ILS SIGNALS BLW 50 FT HAT ARE NOT DEFINED AND THUS ARE NOT ASSURED.'
    line = derive_notam_restriction_line(source)['text']
    assert line == 'RWY 02L closed. This NOTAM has further content; open the full NOTAM.'
    assert derive_notam_restriction_line('RWY 02L CLSD.')['text'] == 'RWY 02L closed.'


def test_python_and_js_decoders_match_every_real_source_when_app_is_available():
    import os
    import shutil
    import subprocess
    from app.odss.notam_restriction_line import derive_notam_restriction_line
    from tests.cross_runtime import js_derivation_module
    module = js_derivation_module(Path(__file__))
    if module is None:
        pytest.skip('Cross-repo JS differential needs PILOTDRIVEN_APP_ROOT and Node; semantic tests still run')
    script = "import {deriveNotamRestrictionLine} from " + json.dumps(module.as_uri()) + ";import fs from 'node:fs';process.stdout.write(JSON.stringify(JSON.parse(fs.readFileSync(0,'utf8')).map(deriveNotamRestrictionLine)));"
    result = subprocess.run(['node', '--input-type=module', '-e', script], input=json.dumps([row['text'] for row in ROWS]), text=True, capture_output=True, check=True)
    expected = json.loads(result.stdout)
    # C1: both runtimes carry the copy guard, so a differential that compared
    # nothing would hide a runtime publishing a copy the other refuses.
    assert len(expected) == len(ROWS) >= 1300, f'differential compared {len(expected)} vectors'
    mismatches = [(row['location'], row['notam_id']) for row, js in zip(ROWS, expected, strict=True) if derive_notam_restriction_line(row['text']) != js]
    assert not mismatches


def test_compact_builder_cannot_overwrite_kord_outage_with_old_faa_note():
    row = next(row for row in ROWS if row['notam_id'] == 'A9894/26')
    held = summary(row['text'])
    item = {'summary':held, 'pertinence_kind':row['kind'], 'item_e_text':row['text']}
    compact = _compact_notam_text(item, _compact_notam_family(item), dashboard=True,
                                  role='destination', planned_runways=set(), reference_time=None)
    assert compact == held
    assert 'out of service' in compact
    assert not compact.startswith('RNAV (GPS) RWY 22R: DISREGARD')


def test_enumerated_procedure_suspension_publishes_the_declaration_not_a_raw_list():
    row=next(row for row in ROWS if row['notam_id']=='A2623/26' and 'COMMUNICATION FAILURE' in row['text'])
    line=summary(row['text'])
    assert 'communication failure procedures are temporarily suspended.' in line
    assert 'This NOTAM has further content; open the full NOTAM.' in line
    assert 'ARR-08' not in line and '15 may 2025' not in line.lower()

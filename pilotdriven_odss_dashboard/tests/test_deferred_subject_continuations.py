"""R12.2/.3: complete source-held defect descriptions cannot vanish behind paperwork."""
import copy
import json
from pathlib import Path
import re

import pytest

from app.odss.analysed_briefing_content import deferred_consequence_rows
from app.odss.deferred_dispatch import build_deferred_dispatch_gates

FIXTURE = json.loads((Path(__file__).parent / 'fixtures/deferred_subject_continuations.json').read_text())
FLIGHTS = {row['flight']:row['deferred_items'] for row in FIXTURE['flights']}


def rows_for(key):
    return deferred_consequence_rows({'deferred_dispatch_gates':build_deferred_dispatch_gates(FLIGHTS[key])})


@pytest.mark.parametrize(('flight','index','parts'), [
    ('SQ214', 0, ("Can't feed waste",)),
    ('SQ214', 4, ('Both VCRU (101HW & 103HW) removed as per MAF 23224',)),
    ('SQ297', 1, ('fixed seal with 2.5CM torn',)),
    ('SQ297', 2, ('all galley chillers working intermittent',)),
    ('SQ882-10Sep', 0, ('air chiller not cold',)),
    ('SQ882-10Sep', 4, ('slat #6 lower seal found deteriorated',)),
    ('SQ366', 1, ('potable water ice protection', 'INOP')),
    ('SQ605', 2, ('waste container door', 'latch missing')),
])
def test_real_description_continuation_names_the_defect(flight,index,parts):
    # Source-item ownership, not matching an arbitrary other gate's text.
    matching = [row for row in rows_for(flight) if index in row['source_item_indices']]
    assert matching
    subjects = ' '.join(row['subject'] for row in matching)
    assert subjects, f'{flight} item {index} became a content-free paperwork label'
    for part in parts:
        assert part.lower() in subjects.lower(), subjects


def test_recovered_lower_seal_does_not_borrow_the_next_declarations_subject():
    subjects = ' '.join(row['subject'] for row in rows_for('SQ882-10Sep') if 4 in row['source_item_indices'])
    assert 'deteriorated' in subjects.lower()
    assert '572HB' not in subjects
    assert 'VCRU #3' not in subjects
    assert 'FF CDL' not in subjects


def test_reconstruction_never_mutates_the_held_source_or_adds_unknown_tokens():
    for flight, items in FLIGHTS.items():
        before = copy.deepcopy(items)
        rows = rows_for(flight)
        assert items == before
        for row in rows:
            sources = ' '.join(' '.join(str(items[index].get(field) or '') for field in ['description','company_remark'])
                               for index in row['source_item_indices'])
            known = set(re.findall(r'[A-Z0-9]+', sources.upper()))
            words = set(re.findall(r'[A-Z0-9]+', row['subject'].upper()))
            assert words <= known, (flight,row['subject'],words-known)


@pytest.mark.parametrize('source', [
    {'description':'MAINT ENTRY: LH WING, SLAT #6 LOWER SEAL FOUND'},
    {'description':'MAINT ENTRY: LH WING, SLAT #6 LOWER SEAL FOUND',
     'source_text':'OTHER ITEM: GALLEY CHILLER INOP'},
    {'description':'FOUND LH SEAL WITH', 'source_text':'FOUND LH SEAL WITH'},
    {'description':'MAINT ENTRY', 'source_text':'MAINT ENTRYISH OTHER TEXT'},
    {'description':'FOUND LH SEAL WITH', 'source_text':'FOUND LH SEAL WITH FF CDL 57-16 ANOTHER SEAL TORN'},
    {'description':'Found LH seal with', 'source_text':'Found LH seal with ff cdl 57-16 another seal torn'},
])
def test_missing_unbound_or_still_incomplete_continuation_stays_unresolved(source):
    from app.odss.analysed_briefing_content import deferred_source_subject
    assert deferred_source_subject(source, 'CDL 27-06') == ''

"""Plain reporting-condition publication; no source/semantic or guard change."""
from __future__ import annotations

import copy
import json
import os
import re
from pathlib import Path

import pytest

from app.odss.enroute_contact import compose_enroute_contact, condition_phrase

ROOT = Path(__file__).resolve().parents[1]
APP = Path(os.environ.get('PILOTDRIVEN_APP_ROOT') or ROOT.parent.parent / 'pd-code-e-helpyou-20260921')


@pytest.mark.parametrize('event', ['VOLCANIC ASH', 'GNSS JAMMING', 'GNSS INTERFERENCE'])
def test_generated_reporting_qualifier_publishes_plain_wording_without_changing_identity(event):
    condition = {'kind': 'qualifier', 'text': f'report trigger: {event}', 'result': 'unresolved'}
    held = copy.deepcopy(condition)
    phrase = condition_phrase(condition)
    assert phrase == f'reporting condition: {event}: not evaluable from the OFP'
    assert not re.search(r'\bTrigger\s*:', phrase, re.I)
    assert condition == held


def test_ordinary_qualifiers_and_literal_trigger_words_remain_unchanged():
    for text in ['IN CASE OF NO CONTACT', 'REPORT ANY OBSERVED TRIGGER EVENT', 'THE SOURCE WORD TRIGGER IS RETAINED']:
        assert condition_phrase({'kind': 'qualifier', 'text': text, 'result': 'unresolved'}) == f'{text}: not evaluable from the OFP'
    assert condition_phrase({'kind': 'restriction', 'text': 'report trigger: LITERAL SOURCE', 'result': 'unresolved'}) == \
        'report trigger: LITERAL SOURCE: not evaluable from the OFP'


@pytest.mark.parametrize('name', ['SQ882-SIN-HKG-10SEP', 'SQ366-SIN-FCO', 'SQ23-JFK-SIN'])
def test_genuine_reporting_rows_preserve_source_conditions_and_values_with_plain_labels(name):
    fixture = json.loads((APP / 'tests/fixtures/enroute-contact' / f'{name}.json').read_text())
    contact = compose_enroute_contact(fixture['flight'], fixture.get('findings') or [], {})
    reporting = [row for row in contact['procedures'] if any(
        condition['kind'] == 'qualifier' and condition['text'].startswith('report trigger: ')
        for condition in row['conditions'])]
    assert reporting, name
    for row in reporting:
        assert row['applicability_state'] == 'conditions_unresolved'
        line = next(line for line in contact['procedure_lines'] if row['notam_id'] in line['notam_ids'])
        for condition in row['conditions']:
            if condition['kind'] == 'qualifier' and condition['text'].startswith('report trigger: '):
                event = condition['text'][len('report trigger: '):]
                assert f'reporting condition: {event}: not evaluable from the OFP' in line['conditions_summary']
        assert not re.search(r'\bTrigger\s*:', line['conditions_summary'], re.I)
    def without_display_summary(value):
        value = copy.deepcopy(value)
        for line in value['procedure_lines']:
            del line['conditions_summary']
        return value
    assert without_display_summary(contact) == without_display_summary(fixture['enroute_contact'])

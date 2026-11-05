"""R12 guard: a real defect can be a subject, never an instruction-block waiver."""
import copy
import json
import re
from pathlib import Path

import pytest

from app.odss.analysed_briefing_content import deferred_consequence_rows
from app.odss.concise_pdf_gate import _bound_defect_subject_is_published
from app.odss.deferred_dispatch import build_deferred_dispatch_gates


def held():
    fixture = json.loads((Path(__file__).parent/'fixtures/deferred_subject_continuations.json').read_text())
    items = next(f['deferred_items'] for f in fixture['flights'] if f['flight']=='SQ605')
    view = {'deferred_dispatch_gates':build_deferred_dispatch_gates(items)}
    view['deferred_pdf_analysis'] = deferred_consequence_rows(view)
    item = items[2]
    row = next(row for row in view['deferred_pdf_analysis'] if row['source_item_indices']==[2])
    effect=' '.join(row['consequences'])
    subject=row['subject'].rstrip(' .;')
    page=f'{subject} {effect} SOURCE Uploaded OFP deferred declaration CC MEL 25-35-02B'
    return item,view,page


def test_real_sq605_defect_is_allowed_in_subject_position_with_retained_effect():
    item,view,page=held()
    assert _bound_defect_subject_is_published(page,1,item,2,view)
    row=next(row for row in view['deferred_pdf_analysis'] if row['source_item_indices']==[2])
    assert _bound_defect_subject_is_published(row['text'],2,item,2,view)


@pytest.mark.parametrize('mutation', ['uppercase','repeat','no-consequence','wrong-position','wrong-page','wrong-item','wrong-binding','wrong-source'])
def test_raw_copy_and_unbound_subjects_never_gain_an_exception(mutation):
    item,view,page=held(); index=2; page_index=1
    raw=item['company_remark']
    if mutation=='uppercase':page=page.upper()
    if mutation=='repeat':page+=' '+raw.lower()
    if mutation=='no-consequence':
        row=next(row for row in view['deferred_pdf_analysis'] if row['source_item_indices']==[2])
        page=row['subject'].rstrip(' .;')+' SOURCE Uploaded OFP deferred declaration CC MEL 25-35-02B'
    if mutation=='wrong-position':page=raw.lower()+' unrelated text '+re.sub(re.escape(raw),'',page,flags=re.I)
    if mutation=='wrong-page':page_index=4
    if mutation=='wrong-item':index=1
    if mutation=='wrong-source':
        next(segment for gate in view['deferred_dispatch_gates'] for segment in gate['source_segments'] if segment['source_item_index']==2)['source_item_index']=99
    if mutation=='wrong-binding':
        next(row for row in view['deferred_pdf_analysis'] if row['source_item_indices']==[2])['source_item_indices']=[99]
    assert not _bound_defect_subject_is_published(page,page_index,item,index,view)


@pytest.mark.parametrize('extra', ['\nSECOND LINE','; CHECK BEFORE FLIGHT',' TO UPLIFT DRY ICE',' X PERFORMANCE [P]',' REFER MEL 25-35-02B'])
def test_form_action_and_manual_instructions_are_not_defect_only_remarks(extra):
    item,view,page=held(); item=copy.deepcopy(item)
    item['company_remark']+=extra
    # Keep all producer/source bindings consistent, so only the independent
    # clause/content checks can reject this instruction masquerading as a subject.
    raw=item['company_remark']
    segment=next(segment for gate in view['deferred_dispatch_gates'] for segment in gate['source_segments'] if segment['source_item_index']==2)
    segment['restriction']=raw
    segment['source_text']=item['description']+' '+raw
    row=next(row for row in view['deferred_pdf_analysis'] if row['source_item_indices']==[2])
    row['subject']=raw.capitalize()
    page=row['subject']+' '+' '.join(row['consequences'])+' SOURCE Uploaded OFP deferred declaration CC MEL 25-35-02B'
    assert not _bound_defect_subject_is_published(page,1,item,2,view)


@pytest.mark.parametrize('instruction', [
    'CABIN FAN MUST BE DEACTIVATED WHEN EMERGENCY CONTROL POWER SUPPLY IS INOP',
    'CABIN FAN SHALL BE DEACTIVATED WHEN EMERGENCY CONTROL POWER SUPPLY IS INOP',
    'REMOVE CABIN FAN IF EMERGENCY CONTROL POWER SUPPLY IS INOP',
    'SWITCH OFF CABIN FAN WHEN EMERGENCY CONTROL POWER SUPPLY IS INOP',
    'ENSURE AFT GALLEY DOOR IS SECURED IF LATCH MISSING',
    'CABIN FAN MAY BE USED UNLESS CONTROL POWER SUPPLY IS INOP',
    'CABIN FAN REQUIRES ISOLATION WHILE CONTROL POWER SUPPLY IS INOP',
])
def test_bound_instruction_ending_with_a_defect_is_not_a_defect_subject(instruction):
    item, view, _ = held()
    item = copy.deepcopy(item)
    item['company_remark'] = instruction
    segment = next(segment for gate in view['deferred_dispatch_gates']
                   for segment in gate['source_segments'] if segment['source_item_index'] == 2)
    segment['restriction'] = instruction
    segment['source_text'] = item['description'] + ' ' + instruction
    row = next(row for row in view['deferred_pdf_analysis'] if row['source_item_indices'] == [2])
    row['subject'] = instruction.capitalize()
    page = (row['subject'] + ' ' + ' '.join(row['consequences'])
            + ' SOURCE Uploaded OFP deferred declaration CC MEL 25-35-02B')
    assert not _bound_defect_subject_is_published(page, 1, item, 2, view)

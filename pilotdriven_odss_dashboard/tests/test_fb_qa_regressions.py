"""Source-derived and synthetic regressions for the 8 September briefing QA."""
from datetime import datetime, timezone
import pytest
from app.odss.enrichment import _parse_airport_notams
from app.odss.engines import _schedule_overlaps, notam_dashboard_line, _notam_operational_summary
from app.odss.pilot_briefing import notam_pertinence


def utc(day, hour, minute=0, month=8):
    return datetime(2026, month, day, hour, minute, tzinfo=timezone.utc)


@pytest.mark.parametrize('schedule', [
    '07 1700-2230, 08 1900-2230, 09-20 1700-2230',
    '07 1600-1700 2230-2330, 08 2230-2330, 09-20 1600-1700 2230-2330',
])
def test_numbered_day_schedule_is_retained_from_item_e(schedule):
    records = _parse_airport_notams('TEST', f'T123/26 VALID: 07-AUG-26 1600 - 20-AUG-26 2330\n{schedule}\nRWY 06/24 CLSD', utc(16,9))
    assert records[0]['schedule'] == schedule
    assert records[0]['schedule_review'] is False


@pytest.mark.parametrize('schedule, start, end, expected', [
    ('07 1700-2230, 08 1900-2230, 09-20 1700-2230', utc(16,12,2), utc(16,14,22), False),
    ('07 1700-2230, 08 1900-2230, 09-20 1700-2230', utc(16,18), utc(16,19), True),
    ('07 1700-2230, 08 1900-2230, 09-20 1700-2230', utc(8,17), utc(8,18), False),
    ('AUG 09-20 2230-0230', utc(17,1), utc(17,2), True),
    ('AUG 09-20 2230-0230', utc(21,1), utc(21,2), True),
    ('AUG 09-20 2230-0230', utc(22,1), utc(22,2), False),
    ('DAILY 1000-1100; ON REQUEST 1200-1300', utc(16,10), utc(16,13), None),
    ('AUG 00-33 1000-1100', utc(16,10), utc(16,11), None),
    ('15 2200-0330, 16 17 18 19 2130-0330', utc(16,22), utc(16,23), True),
    ('15 2200-0330, 16 17 18 19 2130-0330', utc(16,21), utc(16,21,29), False),
    ('15, 16 2200-0330, 17, 18 2130-0330', utc(18,22), utc(18,23), True),
    ('13 0600-14 1500, 16 17 0600-1500', utc(16,9), utc(16,10), None),
])
def test_complete_schedule_is_evaluated_before_publishing_overlap(schedule,start,end,expected):
    assert _schedule_overlaps(schedule,start,end) is expected


@pytest.mark.parametrize('text', [
    'FOLLOW THE GREENS PROCEDURE IS NOT AVAILABLE ON RUNWAYS AND RAPID EXIT TAXIWAYS. WHEN APPROACHING PARKING STANDS, FOLLOW THE LEAD-IN LINE MARKINGS TO THE PARKING STAND.',
    'SIMUL INDEPENDENT PARL APCH. PROC MAY BE SUSPENDED UNDER THE FLW COND: ADVERSE WEATHER; RWY OR TWY CLOSURE.',
    'ILS RWY 25 AVBL. SID PROCEDURE SUSPENDED.',
    'STAND A1 NOT CLOSED.',
    'APRON OPEN. TAXI GUIDANCE NOT AVAILABLE.',
    'ILS RWY 25 MAY BE SUSPENDED IF ADVERSE WEATHER OCCURS.',
])
def test_procedural_conditional_or_neighbouring_state_is_not_a_closure(text):
    _,kind=notam_pertinence(text)
    assert kind not in {'airport_closure','runway_closure','taxiway_closure','apron_stand_closure','approach_navaid_closure'}
    summary=_notam_operational_summary(text,kind,'destination')
    assert ' closed ' not in summary.lower()
    assert 'unavailable during' not in summary.lower()


@pytest.mark.parametrize('text,kind', [
    ('STAND A1 CLSD DUE WIP.', 'apron_stand_closure'),
    ('ILS RWY 25 U/S DUE TECH REASON.', 'approach_navaid_closure'),
    ('RWY 06/24 CLSD DUE RUBBER DEPOSIT REMOVAL.', 'runway_closure'),
])
def test_explicit_outages_remain_classified(text,kind):
    assert notam_pertinence(text)[1] == kind


@pytest.mark.parametrize('text,expected', [
    ('ILS/DME CH38X, DME PART U/S DUE TO TECH REASON','DME PART unserviceable.'),
    ('VOR/DME CH100X, DME PART U/S','DME PART unserviceable.'),
    ('ILS RWY 25 AVBL, DME PART U/S','DME PART unserviceable.'),
    ('ILS/DME CH38X, DME PART NOT U/S',''),
    ('ILS-LOC, GP, DME FOR RWY 25L U/S', 'ILS-LOC, GP, DME RWY 25L unserviceable.'),
    ('VOR/DME CH80X, VOR-PART U/S', 'VOR PART unserviceable.'),
])
def test_compact_line_retains_component_subject(text,expected):
    assert notam_dashboard_line(text,'approach_navaid_closure') == expected


@pytest.mark.parametrize("text", [
    "ILS RWY 25 U/S, DME AVBL.",
    "ILS RWY 25 U/S, PROC MAY BE SUSPENDED UNDER ADVERSE WEATHER.",
])
def test_a_separate_available_or_conditional_state_does_not_erase_a_real_outage(text):
    assert notam_pertinence(text)[1] == "approach_navaid_closure"


def test_monthless_schedule_does_not_guess_across_validity_months():
    assert _schedule_overlaps("09-20 1700-2230", utc(16,18), utc(16,19), valid_from=utc(7,17), valid_to=utc(20,23,month=9)) is None


@pytest.mark.parametrize('text, expected', [
    ('JFK TWY HB LGT BTN TERMINAL 4 RAMP AND TWY B U/S', 'taxiway_restriction'),
    ('TWY KG CLR BAR LGT AT TERMINAL 4 RAMP U/S', 'taxiway_restriction'),
    ('APN CTL THREE PRI FREQ 121.35MHZ U/S DUE TO TECHNICAL ISSUE.', 'other_operational'),
    ('TWY N2 BEHIND ACFT STANDS 507 AND 508 CLSD DUE WIP', 'taxiway_closure'),
    ('FLW TXL CLSD: 1) TXL N4 BEHIND ACFT STAND 603', 'taxiway_closure'),
    ('CRANE WILL OPR WHEN NORTHERN RUNWAY 09L/27R IS CLOSED.', 'obstacle'),
    ('ACFT PRKG PSN BAYS 270 AND 271 ARE NOW CLSD.', 'apron_stand_closure'),
    ('RWY 22L CAT II/III OPS NOT AVBL DUE TO WIP.', 'approach_navaid_closure'),
    ('ILS LOC FREQ 110.3MHZ U/S.', 'approach_navaid_closure'),
    ('FOLLOW THE GREENS SER NOT AVBL ON RWY AND RAPID EXIT TWY. PILOTS SHALL FOLLOW ATC VERBAL TURN INSTRUCTIONS.', 'other_operational'),
])
def test_exact_source_neighbouring_subject_regressions(text, expected):
    assert notam_pertinence(text)[1] == expected

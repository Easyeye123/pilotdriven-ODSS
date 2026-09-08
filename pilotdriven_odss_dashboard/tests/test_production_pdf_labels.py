"""Current production time labels and fixed-page navigation."""
import fitz
from generate_visual_samples import sample_findings, sample_flight
from app.odss.combined_brief import render_combined_briefing
from app.odss.timing import build_timing_view


def render(tmp_path, *, atot=None):
    flight = sample_flight()
    findings = [f for f in sample_findings() if f['engine'] != 'depressurisation']
    if atot:
        flight['actual_takeoff_utc'] = atot
        flight['timing_view'] = build_timing_view(flight, findings, atot)
    output = tmp_path / 'briefing.pdf'
    render_combined_briefing(flight, findings, [], output)
    return output


def test_scheduled_arrival_does_not_become_calculated_eta(tmp_path):
    with fitz.open(render(tmp_path)) as doc:
        first = ' '.join(doc[0].get_text().split())
        assert 'SCHED ARR 2240Z' in first
        assert 'TARGET ARRIVAL NOT CALCULATED' in first
        assert 'TARGET ARRIVAL 2240Z' not in first


def test_atot_derived_target_stays_distinct_from_schedule(tmp_path):
    with fitz.open(render(tmp_path, atot='2026-07-16T09:52:00+00:00')) as doc:
        first = ' '.join(doc[0].get_text().split())
        assert 'ATOT 0952Z' in first
        assert 'TARGET ARRIVAL 2159Z' in first
        assert 'SCHED ARR 2240Z' in first
        assert 'ATOT + OFP ACTM' in first


def test_master_links_point_to_current_detail_owners(tmp_path):
    with fitz.open(render(tmp_path)) as doc:
        destinations = {link.get('page') for link in doc[0].get_links()}
        assert {2, 4, 6, 8} <= destinations
        assert doc[5].get_text().count('DEPARTURE SURFACE') == 1
        assert doc[6].get_text().count('DESTINATION SURFACE') == 1
        assert 'REVIEW RECORD AND RELEASE CONDITIONS' in doc[8].get_text()

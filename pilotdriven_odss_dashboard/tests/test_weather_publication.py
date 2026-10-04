"""Publication must distinguish excluded weather, missing evidence and NON-EDTO."""
from copy import deepcopy

import fitz
import pytest

from generate_visual_samples import sample_flight, sample_findings
from app.odss.combined_brief import render_combined_briefing
from app.odss.concise_pdf_gate import (MAX_BRIEFING_PAGES, WEATHER_PAGE,
                                       normalized)
from app.odss.weather_publication import edto_window_lines, sigmet_lines, volcanic_ash_lines


def test_five_expired_sigmets_and_six_ash_results_fit_one_weather_page():
    from app.odss.briefing import build_briefing_view
    from app.odss.operational_format import build_sections
    flight = sample_flight()
    flight.update(scheduled_departure_utc='2026-09-08T14:50:00Z', scheduled_arrival_utc='2026-09-08T21:00:00Z')
    view = build_briefing_view(flight, [], [])
    view['hazards']['sigmet_cards'] = [
        {'fir': 'RJJJ', 'sigmet_id': f'C{i:02d}', 'phenomenon': 'EMBD TS', 'route_intersection': 'outside',
         'valid_from': '081018', 'valid_to': f'0814{i:02d}',
         'screening': f'The filed route does not intersect the polygon. Closest deterministic screening distance is approximately {236+i} NM northeast. NOT PROMOTED.'}
        for i in range(5)]
    view['vaa']['cfp_advisories'] = [
        {'volcano': f'VOLCANO {i}', 'advisory_kind': 'VA_SIGMET',
         'derived': 'Closest 300 NM between AAA and BBB; route passes after the advisory validity ended at 1300Z.'} for i in range(6)]
    sections = build_sections(flight, view, [])
    assert sum(len(pages) for pages in sections.values()) == MAX_BRIEFING_PAGES
    page = sections['weather'][0]
    body = ' '.join(line for box in page.boxes for _, items in box.rows for line, *_ in items)
    for i in range(5):
        assert f'C{i:02d}' in body and f'{236+i} NM' in body and f'{50-i} min' in body
    for i in range(6):
        assert f'VOLCANO {i}' in body
    assert body.count('successor SIGMET') == 1


def test_physical_pdf_explains_non_edto_excluded_sigmet_and_unassessed_ash(tmp_path):
    flight = sample_flight()
    flight.update(scheduled_departure_utc='2026-09-08T14:50:00Z',
                  scheduled_arrival_utc='2026-09-08T21:00:00Z', actual_takeoff_utc=None)
    flight['edto'] = {'assessment': {'status': 'verified_not_applicable', 'evidence': [
        {'source': 'uploaded_company_cfp', 'source_page': 1,
         'reason_code': 'explicit_edto_not_applicable_declaration'}]}}
    flight['weather'] = [r for r in flight.get('weather', []) if r.get('record_type') != 'SIGMET'] + [
        {'record_type': 'SIGMET', 'location': 'RJJJ', 'text':
         'WS SIGMET C03 VALID 081018/081418 RJTD- RJJJ FUKUOKA FIR EMBD TS OBS '
         'WI N5000 E16000 - N5100 E16000 - N5100 E16100 - N5000 E16000 TOP FL510 MOV NNE 10KT='}]
    flight['direct_vaa_source_review'] = {'source_status': 'partial', 'applicability_status': 'not_assessed',
        'responsible_centre_receipts': [{'centre': 'DARWIN', 'reached': True}, {'centre': 'TOKYO', 'reached': True}],
        'official_advisories': [{'volcano': 'TEST A'}, {'volcano': 'TEST B'}]}
    original = deepcopy(flight)
    findings = [f for f in sample_findings() if f['engine'] != 'depressurisation']
    path = tmp_path / 'briefing.pdf'
    render_combined_briefing(flight, findings, [], path)
    with fitz.open(path) as doc:
        weather = normalized(doc[WEATHER_PAGE].get_text())
        assert 'NOT APPLICABLE THIS FLIGHT IS NON EDTO' in weather
        assert 'OUTSIDE FILED ROUTE' in weather and 'RJJJ C03' in weather
        assert 'EXPIRED BEFORE SCHEDULED DEPARTURE 08SEP 1450Z' in weather
        assert 'C03 08SEP 1018 1418Z 32 MIN' in weather
        assert 'SUCCESSOR SIGMET COVERAGE' in weather
        # VOLCANIC-CHECK-436: the live sources print as the composed check - every responsible centre named with its
        # reach, the advisories held and that their route applicability is not assessed.
        assert 'RESPONSIBLE VAACS DARWIN TOKYO ALL REACHED' in weather
        assert '2 ADVISORIES HELD ROUTE APPLICABILITY NOT ASSESSED' in weather
        assert len(doc) == MAX_BRIEFING_PAGES
    assert flight == original


@pytest.mark.parametrize('edto', [
    {}, {'assessment': {'status': 'verified_not_applicable'}},
    {'assessment': {'status': 'verified_not_applicable', 'evidence': [
        {'source': 'cfp', 'reason_code': 'explicit_edto_not_applicable_declaration'}]},
     'airports': [{'airport': 'WSSS'}]},
])
def test_empty_or_conflicting_edto_never_becomes_non_edto(edto):
    line = ' '.join(edto_window_lines({'edto': edto}, {}))
    assert 'NON-EDTO' not in line and 'unresolved' in line


def test_applicable_edto_preserves_windows_and_names_missing_windows():
    flight = {'edto': {'assessment': {'status': 'affected', 'evidence': [
        {'source': 'cfp', 'reason_code': 'edto_sector_present'}]},
        'sectors': [{'number': 1, 'entry_actm_minutes': 60, 'exit_actm_minutes': 90}]}}
    row = {'airport': 'WSSS', 'runway': '20R', 'approach': 'ILS', 'minima': '200/550', 'period': '11JUL 1030-1230Z'}
    view = {'edto': {'airports': [row]}}
    assert edto_window_lines(flight, view) == ['WSSS/20R: ILS 200/550; 11JUL 1030-1230Z.']
    assert 'EDTO applies, but' in edto_window_lines(flight, {})[0]


def test_sigmet_keeps_intersections_and_unreadable_polygons_without_raw_text():
    cards = [
        {'fir': 'WSSS', 'sigmet_id': '1', 'phenomenon': 'EMBD TS', 'route_intersection': 'intersects', 'text': 'RAW SOURCE MUST STAY IN APP',
         'screening': "The polygon crosses the route about ACTM 01:00-01:10 / 1030-1040Z inside the product's validity. PROMOTED - review required."},
        {'fir': 'WSSS', 'sigmet_id': '2', 'disposition': 'REVIEW REQUIRED',
         'screening': 'No readable polygon in the OFP record - deterministic screening unavailable; review the original SIGMET.'},
    ]
    result = ' '.join(sigmet_lines({}, {'hazards': {'sigmet_cards': cards}}))
    assert 'WSSS/1 (EMBD TS): Route crossing 1030-1040Z within validity.' in result
    assert 'WSSS/2' in result and 'route applicability unresolved' in result
    assert 'review required' not in result.lower() and 'RAW SOURCE' not in result


@pytest.mark.parametrize('departure,valid_from,valid_to,expected', [
    ('2026-09-01T00:30:00Z', '312000', '312359', '31 min'),
    ('2026-09-08T14:50:00Z', '081018', '081450', None),
    ('2026-09-08T14:50:00Z', '081500', '081600', None),
    ('2026-09-08T14:50:00Z', '081418', '081018', None),
    (None, '081018', '081418', None),
])
def test_sigmet_expiry_uses_valid_source_utc_and_handles_month_rollover(departure, valid_from, valid_to, expected):
    card = {'fir': 'RJJJ', 'sigmet_id': 'C03', 'valid_from': valid_from, 'valid_to': valid_to,
            'screening': 'The filed route does not intersect the polygon. NOT PROMOTED.'}
    result = ' '.join(sigmet_lines({'scheduled_departure_utc': departure}, {'hazards': {'sigmet_cards': [card]}}))
    if expected:
        assert expected in result and 'Expired before scheduled departure' in result
    else:
        assert 'expired' not in result


def test_empty_weather_is_unknown_and_direct_advisories_are_not_hazard_matches():
    flight = {'scheduled_departure_utc': '2026-07-11T10:30:00Z', 'scheduled_arrival_utc': '2026-07-11T12:30:00Z'}
    assert 'does not establish that no SIGMET applies' in sigmet_lines(flight, {})[0]
    assert 'does not establish that the route is ash-free' in volcanic_ash_lines(flight, {})[0]
    flight['direct_vaa_source_review'] = {'source_status': 'partial', 'applicability_status': 'not_assessed',
        'official_advisory_count': 999, 'official_advisories': [{'volcano': 'TEST'}]}
    lines = volcanic_ash_lines(flight, {'vaa': {'cfp_advisories': [{'volcano': 'SOURCE', 'advisory_kind': 'VA_SIGMET', 'derived': 'Outside route.'}]}})
    assert lines[0] == 'SOURCE: Outside route.'
    assert '1 direct VAAC advisory' in lines[1] and 'has not been assessed' in lines[1]
    assert 'partial' in lines[2] and '999' not in str(lines)


def test_live_matched_weather_is_preserved_but_monitoring_and_later_weather_are_not_promoted():
    flight = {'scheduled_departure_utc': '2026-07-11T10:30:00Z', 'scheduled_arrival_utc': '2026-07-11T12:30:00Z'}
    properties = {'hazard_state': 'affecting', 'valid_from_utc': '2026-07-11T10:00:00Z',
                  'valid_to_utc': '2026-07-11T13:00:00Z'}
    features = [{'id': 'ASH-1', 'properties': dict(properties, hazard='volcanic_ash')},
                {'id': 'TS-1', 'properties': dict(properties, hazard='TS', hazard_code='TS')},
                {'id': 'MONITOR', 'properties': dict(properties, hazard='volcanic_ash', hazard_state='monitoring')},
                {'id': 'LATER', 'properties': dict(properties, hazard='TS', valid_from_utc='2026-07-12T10:00:00Z', valid_to_utc='2026-07-12T13:00:00Z')}]
    view = {'route_map': {'hazard_features': features}}
    ash, sigmet = ' '.join(volcanic_ash_lines(flight, view)), ' '.join(sigmet_lines(flight, view))
    assert 'ASH-1: ash intersects the filed route/time/level' in ash
    assert 'TS-1: TS intersects the filed route/time/level' in sigmet
    assert 'MONITOR' not in ash and 'LATER' not in sigmet
    assert 'No flight-specific' not in ash + sigmet


@pytest.mark.parametrize('page_index,code', [
    (WEATHER_PAGE, 'EDTO_WINDOW_PARITY'), (WEATHER_PAGE, 'SIGMET_SCREENING_PARITY'),
    (WEATHER_PAGE, 'ASH_ASSESSMENT_PARITY'),
])
def test_gate_rejects_missing_weather_and_edto_text(tmp_path, page_index, code):
    from app.odss.briefing import build_briefing_view
    from app.odss.concise_pdf_gate import check_concise_pdf
    flight = sample_flight()
    path = tmp_path / 'briefing.pdf'
    render_combined_briefing(flight, [], [], path)
    view = build_briefing_view(flight, [], [])
    with fitz.open(path) as doc:
        page = doc[page_index]
        page.add_redact_annot(page.rect)
        page.apply_redactions()
        changed = tmp_path / 'changed.pdf'
        doc.save(changed)
    result = check_concise_pdf(changed, flight=flight, view=view)
    assert not result['valid']
    assert code in {v['code'] for v in result['violations']}


@pytest.mark.parametrize('ending,expected', [
    ("inside the product's validity. PROMOTED - review required.", 'within validity.'),
    (', but the product expires 135 minutes before the earliest possible crossing. NOT PROMOTED.', '; expires 135 min before earliest bound.'),
    (', but the product only becomes valid 81 minutes after the latest possible crossing. NOT PROMOTED.', '; starts 81 min after latest bound.'),
])
def test_concise_sigmet_retains_utc_leg_bounds_and_time_exclusion(ending, expected):
    card = {'fir': 'WSSS', 'sigmet_id': '1', 'phenomenon': 'EMBD TS', 'route_intersection': 'intersects',
            'screening': 'The polygon crosses the route within filed leg bounds ACTM 01:35-02:07 / 1030-1102Z ' + ending}
    line = sigmet_lines({}, {'hazards': {'sigmet_cards': [card]}})[0]
    assert 'WSSS/1 (EMBD TS): Crossing leg bounds 1030-1102Z' in line
    assert expected in line
    assert 'ACTM' not in line

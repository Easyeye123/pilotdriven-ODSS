from copy import deepcopy

from test_engine_regressions import _flight
from app.odss.engines import analyse
from app.odss.parser import _parse_performance


def test_inline_plan_qnh_and_wind_are_kept_from_performance_source():
    result = _parse_performance(
        'RKSI RWY 33R STD RATING: FULL Thrust\n'
        'PLAN TEMP P025 PLAN QNH 1010 PLAN WIND VRB012 WIND COMP M12\n'
    )
    assert result['qnh_hpa'] == 1010
    assert result['wind'] == 'VRB012'
    assert _parse_performance('PLAN QNH1010')['qnh_hpa'] == 1010
    for token in ('16/008','130/08','35012','VRB005'):
        assert _parse_performance('PLAN WIND ' + token + ' WIND COMP P01')['wind'] == token
    assert _parse_performance('PLAN QNH PLAN WIND WIND COMP M12')['qnh_hpa'] is None
    assert _parse_performance('PLAN QNH PLAN WIND WIND COMP M12')['wind'] is None


def _forecast(records):
    flight = _flight()
    flight.update(departure='RKSI', destination='WSSS',
                  scheduled_departure_utc='2026-09-08T14:50:00+00:00',
                  scheduled_arrival_utc='2026-09-08T21:00:00+00:00',
                  actual_takeoff_utc=None, weather=deepcopy(records))
    findings, _ = analyse(flight)
    row = next(f for f in findings if f['engine'] == 'weather'
               and f['data'].get('location') == 'RKSI'
               and f['data'].get('forecast_source'))
    return row['data'], flight['audit_evidence']['weather']


OFP = {'location':'RKSI', 'record_type':'TAF', 'source_page':25,
       'text':'FT 081100 0812/0918 33007KT CAVOK BECMG 0814/0816 07008KT 9999 SCT040='}
LATER = {'location':'RKSI', 'record_type':'TAF', 'provider':'noaa-awc-data-api',
         'text':'TAF RKSI 081700Z 0818/1000 01004KT 9999 FEW040='}


def test_covering_ofp_forecast_is_not_replaced_by_later_noncovering_provider():
    for records in ([OFP, LATER], [LATER, OFP]):
        result, audit = _forecast(records)
        assert result['forecast_source']['raw_text'] == OFP['text']
        assert result['forecast_source']['pages'] == [25]
        assert 'wind 330' in result['applicable_conditions']
        assert 'wind 70' in result['applicable_conditions']
        assert len(audit['records']) == 2  # Unselected evidence remains in the app.


def test_latest_issued_covering_bulletin_wins_independent_of_input_order():
    amended = {**OFP, 'source_page':None, 'provider':'noaa-awc-data-api',
               'text':'TAF AMD RKSI 081200Z 0812/0918 35009KT 9999 SCT020='}
    for records in ([amended, OFP], [OFP, amended]):
        result, _ = _forecast(records)
        assert result['forecast_source']['raw_text'] == amended['text']


def test_noncovering_only_forecast_keeps_the_coverage_gap():
    result, _ = _forecast([LATER])
    assert result['window_status'] == 'review_required'
    assert result['forecast_source']['raw_text'] == LATER['text']

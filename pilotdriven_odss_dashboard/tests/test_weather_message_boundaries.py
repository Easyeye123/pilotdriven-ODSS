from datetime import datetime, timezone

from app.odss.enrichment import _parse_station_weather, enrich_weather
from app.odss.weather_timing import summarize_taf_for_window


def test_inline_footer_after_message_terminator_is_excluded() -> None:
    records = _parse_station_weather('FMMI',
        'SA 251400 12008KT 080V160 9999 FEW023 23/07 Q1024 WS ALL RWY\n'
        'NOSIG= SIA 481/25Aug26/FAOR-WSSS Reg:9VSMA OFP:19/0/1 Page 14 of 64\n'
        'SA 251330 10007KT 070V170 9999 FEW023 23/06 Q1023 NOSIG=')
    assert len(records) == 2
    assert records[0]['text'] == (
        'SA 251400 12008KT 080V160 9999 FEW023 23/07 Q1024 WS ALL RWY NOSIG=')
    assert records[1]['text'].endswith('Q1023 NOSIG=')


def test_wrapped_taf_does_not_absorb_following_non_weather_lines() -> None:
    records = _parse_station_weather('WIDD',
        'FT 160530 1606/1706 14008KT 7000 SCT014\n'
        'TEMPO 1606/1608 TS FEW013CB=\nNIL\nAIRPORTLIST ENDED')
    assert records == [{'location': 'WIDD', 'record_type': 'TAF', 'text':
        'FT 160530 1606/1706 14008KT 7000 SCT014 TEMPO 1606/1608 TS FEW013CB='}]


def test_page_break_preserves_unterminated_forecast_continuation_and_source_page() -> None:
    flight = {'departure': 'WSSS', 'destination': 'VTBS', 'alternates': [],
        'edto': {'airports': []}, 'weather': []}
    enrich_weather(flight, [
        'AIRPORT WX LIST\nDESTINATION AIRPORT:\nVTBS/BKK BANGKOK\n'
        'FT 110500 1106/1212 16008KT 9999 SCT020\n'
        'TEMPO 1109/1112 4000 TSRA SCT015CB ABC 999/11Jul26/WSSS-VTBS Reg:9VAAA OFP:1/0/1\n'
        'Page 7 of 20',
        'AIRPORT WX LIST\nFM111200 27015G25KT 9999 SCT020\n'
        'RMK NXT FCST BY 111100Z=\nAIRPORTLIST ENDED'])
    assert len(flight['weather']) == 1
    assert flight['weather'][0]['text'] == (
        'FT 110500 1106/1212 16008KT 9999 SCT020 TEMPO 1109/1112 4000 TSRA SCT015CB '
        'FM111200 27015G25KT 9999 SCT020 RMK NXT FCST BY 111100Z=')
    assert flight['weather'][0]['source_page'] == 1


def test_unterminated_message_ends_at_list_or_other_weather_heading() -> None:
    for boundary in ('AIRPORTLIST ENDED', 'Space Weather Advisory:', 'SIGMETs:'):
        records = _parse_station_weather('WSSS',
            f'FT 110500 1106/1212 16008KT CAVOK\n{boundary}\nNIL')
        assert records[0]['text'] == 'FT 110500 1106/1212 16008KT CAVOK'


def test_explicit_nil_and_unterminated_messages_are_retained_without_invented_tokens() -> None:
    records = _parse_station_weather('WSSS',
        'SA 111000 NIL=\nFC 110500 1106/1115 NIL=\nFT 110500 1106/1212 16008KT CAVOK')
    assert [r['text'] for r in records] == [
        'SA 111000 NIL=', 'FC 110500 1106/1115 NIL=', 'FT 110500 1106/1212 16008KT CAVOK']


def test_ambiguous_short_source_line_does_not_guess_a_page() -> None:
    start = 'FT 110500 1106/1212 16008KT CAVOK'
    records = _parse_station_weather('WSSS',
        start + '\nFM111200 27015G25KT 9999 SCT020\nRMK NXT FCST BY 111100Z=',
        source_pages=[start, start, 'FM111200 27015G25KT 9999 SCT020\nRMK NXT FCST BY 111100Z='])
    assert records[0]['source_page'] is None


def test_short_older_flight_footer_is_removed_without_losing_wrapped_remarks() -> None:
    records = _parse_station_weather('KBOS',
        'SA 212335 13009KT 2SM RA BR FEW007 SCT023 OVC055 19/18 A2973\n'
        'SIA 24/22Jul26/SIN-JFK\nPage 21 of 126\nRMK AO2 RAB29 P0001 T01890183=')
    assert records[0]['text'] == (
        'SA 212335 13009KT 2SM RA BR FEW007 SCT023 OVC055 19/18 A2973 RMK AO2 RAB29 P0001 T01890183=')


def test_same_line_products_remain_distinct() -> None:
    records = _parse_station_weather('WSSS',
        'SA 111000 16008KT CAVOK= FT 110500 1106/1212 16008KT CAVOK= Page 7 of 20')
    assert [r['text'] for r in records] == [
        'SA 111000 16008KT CAVOK=', 'FT 110500 1106/1212 16008KT CAVOK=']


def test_identical_complete_weather_on_multiple_pages_does_not_guess_a_page() -> None:
    text = 'FT 110500 1106/1212 16008KT CAVOK='
    records = _parse_station_weather('WSSS', text, source_pages=[text, text])
    assert records[0]['source_page'] is None


def test_removing_source_list_coverage_annotation_does_not_claim_forecast_covers_arrival() -> None:
    records = _parse_station_weather('WSSS',
        'FT 110500 1106/1110 16008KT CAVOK=\nPeriod not completely covered')
    assert records[0]['text'] == 'FT 110500 1106/1110 16008KT CAVOK='
    summary = summarize_taf_for_window(records[0]['text'],
        datetime(2026, 7, 11, 10, 0, tzinfo=timezone.utc),
        datetime(2026, 7, 11, 11, 0, tzinfo=timezone.utc))
    assert summary['status'] == 'review_required'


def test_repeated_weather_unavailable_uses_own_station_header_for_source_page() -> None:
    text = 'FT WX NOT AVAILABLE'
    pages = ['VTBS/BKK BANGKOK\n' + text, 'WSSS/SIN SINGAPORE CHANGI\n' + text]
    records = _parse_station_weather('WSSS', text, source_pages=pages)
    assert records[0]['source_page'] == 2

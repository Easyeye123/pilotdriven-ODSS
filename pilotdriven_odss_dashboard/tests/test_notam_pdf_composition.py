"""Production NOTAMs are analysed once; original evidence stays in the app."""
import fitz

from app.odss.combined_brief import render_combined_briefing
from app.odss.concise_pdf_gate import check_concise_pdf
from generate_visual_samples import sample_flight, sample_findings


def test_many_source_records_become_grouped_consequences_without_raw_appendix(tmp_path, monkeypatch):
    from app.odss import briefing as briefing_module
    real_build = briefing_module.build_briefing_view
    records = [{
        'notam_id': f'A{8100+i}/26', 'severity': 'critical',
        'approach_affected': True, 'stateAtReference': 'active_at_reference',
        'referenceAt': '2026-07-16T09:45:00Z',
        'item_e_text': f'DME PART U/S. SOURCE MAINTENANCE RECORD {i} END-EVIDENCE-{i}.',
        'source_page': 20+i, 'applicability': 'active',
    } for i in range(18)]

    def view(*args, **kwargs):
        result = real_build(*args, **kwargs)
        for panel in result['airport_operational_panels']:
            panel['selected_notams'] = records if panel['icao'] == 'EBBR' else []
        return result

    monkeypatch.setattr(briefing_module, 'build_briefing_view', view)
    flight = sample_flight()
    flight['notams'] = [{'notam_id': r['notam_id'], 'text': r['item_e_text']} for r in records]
    findings = [f for f in sample_findings() if f['engine'] != 'depressurisation']
    output = tmp_path / 'operational.pdf'
    render_combined_briefing(flight, findings, [], output)
    with fitz.open(output) as pdf:
        assert len(pdf) == 9
        text = ' '.join(p.get_text() for p in pdf)
        assert 'SOURCE MAINTENANCE RECORD' not in text
        assert 'END-EVIDENCE' not in text
        assert 'DME' in pdf[5].get_text()
        for record in records:
            assert pdf[5].get_text().count(record['notam_id']) == 1
    assert check_concise_pdf(output, flight=flight)['valid']

from app.odss.engines import _notam_operational_summary
from app.odss.pilot_briefing import notam_pertinence
from app.odss.briefing import _compact_notam_family
from app.odss.combined_brief import _audit_rev3_v8_compact_notam_family


def test_removed_aids_on_retired_taxiways_do_not_inherit_the_runway_in_the_heading():
    source = ('PAVED AREAS ADJ TO CENTRE RWY 01/19. THE FORMER TWY K2 AND THE SECTION OF TWY M BTN TWY P AND TWY Q HAD BEEN DECOMMISSIONED. '
              'THE ASSOCIATED VISUAL AIDS OF THE DECOMMISSIONED TWY, INCLUDING TWY CL LGT, HAVE BEEN MASKED OFF AND DISMANTLED.')
    rank, kind = notam_pertinence(source)
    assert (rank, kind) == (4, 'surface_identity_review')
    result = _notam_operational_summary(source, kind, 'destination')
    assert 'former taxiway K2 and section of taxiway M between taxiway P and taxiway Q' in result
    assert 'Current pavement identity and availability are unverified' in result
    assert '01/19' not in result
    assert 'Lighting affecting' not in result
    record = {'pertinence_kind': kind, 'item_e_text': source}
    assert _compact_notam_family(record) == 'other'
    assert _audit_rev3_v8_compact_notam_family(record) == 'other'


def test_no_retired_pavement_inference_from_conditional_negated_future_or_unrelated_aids():
    for clause in ('IF TWY K2 IS DECOMMISSIONED', 'TWY K2 HAS NOT BEEN DECOMMISSIONED', 'TWY K2 WILL BE DECOMMISSIONED', 'LIGHTS AT TWY K2 HAVE BEEN DECOMMISSIONED'):
        source = clause + '. THE ASSOCIATED VISUAL AIDS OF THE DECOMMISSIONED TWY INCLUDE CL LGT.'
        assert notam_pertinence(source)[1] != 'surface_identity_review'
        result = _notam_operational_summary(source, 'runway_lighting_restriction', 'destination')
        assert 'identifies' not in result
    assert 'Lighting affecting' in _notam_operational_summary('RWY 01/19 EDGE LGT U/S', 'runway_lighting_restriction', 'destination')

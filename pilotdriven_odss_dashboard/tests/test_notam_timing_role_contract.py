import pytest

from tests.notam_timing_role_contract import ODSS_ROLE, operational_role


@pytest.mark.parametrize("icao", ["QAAA", "QBBB", "QCCC"])
@pytest.mark.parametrize("other_role", [[], ["enroute"], ["edto_suitable"]])
def test_adequate_listing_without_a_flight_selection_is_informational(icao, other_role):
    assert operational_role("edto_adequate", icao, ["edto_adequate", *other_role], ["QDDD"]) == "informational"


@pytest.mark.parametrize("primary", ["edto", "edto_suitable", "edto_adequate"])
@pytest.mark.parametrize("source", ["app", "odss", "both"])
def test_selected_edto_never_falls_back_to_an_informational_assessment(primary, source):
    # The expectation comes from the flight selection, never whichever role rows survived analysis.
    roles = [primary, "edto"] if source in {"app", "both"} else [primary]
    selected = ["QAAA"] if source in {"odss", "both"} else []
    expected = operational_role(primary, "QAAA", roles, selected)
    assert expected == "EDTO"
    corrupted_assessments = [{"role": "informational", "stateAtReference": "active_at_reference"}]
    assert not any(row["role"] == expected for row in corrupted_assessments)


@pytest.mark.parametrize("primary", ["departure", "destination", "destination_alternate", "fuel_enroute", "enroute"])
def test_other_roles_keep_their_own_contract(primary):
    assert operational_role(primary, "QAAA", [primary], []) == ODSS_ROLE[primary]

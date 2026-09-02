"""Boss 02 Sep 2026 21:22: what he reads first is "instrument approaches being
affected such as ILS or VOR not working, or on test or unserviceable" — so a
navaid line must name the aid and its state, never "restriction applies"."""

from app.odss.engines import _notam_operational_summary
from app.odss.pilot_briefing import notam_pertinence


def _summary(text: str, role: str = "destination") -> str:
    _, kind = notam_pertinence(text)
    return _notam_operational_summary(text, kind, role)


def test_ils_on_test_names_the_aid_runway_and_state():
    text = "ILS CAT I RWY 06 ON TEST, DO NOT USE (AWAITING FLTCK VERIFICATION)."
    assert _summary(text) == (
        "ILS CAT I RWY 06 on test, do not use during the applicable destination window."
    )


def test_unserviceable_vor_dme_names_the_aid_and_identifier():
    text = "DVOR/DME 'MNL' U/S DUE MAINT."
    summary = _summary(text)
    assert summary.startswith("DVOR/DME MNL unserviceable")
    assert "restriction applies" not in summary.lower()


def test_ils_not_available_keeps_the_unavailable_line():
    assert _summary("ILS RWY 20R NOT AVBL.", "departure") == (
        "ILS RWY 20R unavailable during the applicable departure window."
    )


def test_runway_work_without_an_aid_keeps_the_generic_line():
    assert _summary("RWY 22 WIP CONST EAST SIDE.") == (
        "Rwy 22 restriction applies during the applicable destination window."
    )


def test_faa_procedure_notice_names_the_procedure_and_its_note():
    text = (
        "IAP LOS ANGELES INTL, LOS ANGELES, CA. ILS OR LOC RWY 7R, AMDT 8A... "
        "AUTO-PILOT COUPLED APPROACH NA BELOW 800."
    )
    assert _summary(text) == (
        "ILS OR LOC RWY 7R: AUTO-PILOT COUPLED APPROACH NA BELOW 800 during the applicable destination window."
    )


def test_faa_cat_ii_minima_notice_keeps_the_procedure_and_the_rvr_note():
    text = (
        "IAP LOS ANGELES INTL, LOS ANGELES, CA. ILS OR LOC RWY 24R, AMDT 26C... "
        "ILS RWY 24R (CAT II-III), AMDT 26C... S-ILS 24R CAT II RVR 1200. CAT II NOTE: RVR 1000 "
        "AUTHORIZED WITH SPECIFIC OPSPEC, MSPEC, OR LOA APPROVAL AND USE OF AUTOLAND OR HUD TO TOUCHDOWN."
    )
    summary = _summary(text)
    assert summary.startswith("ILS RWY 24R (CAT II-III): S-ILS 24R CAT II RVR 1200")
    assert "restriction applies" not in summary.lower()


def test_an_ats_route_notice_is_not_an_approach_or_runway_restriction():
    text = (
        "FLIGHTS DEPARTING WSSS ON ATS ROUTE N571: ATC MAY ASSIGN FL280 NO-PDC TO TWO SUCCESSIVE "
        "RNP 2/RNP 4-APPROVED AIRCRAFT OPERATING ON ATS ROUTE N571 WITH 5-MINUTE LONGITUDINAL SEPARATION."
    )
    _, kind = notam_pertinence(text)
    assert kind not in {"runway_approach_restriction", "approach_navaid_closure", "runway_closure"}


def test_faa_procedure_notice_with_an_ofp_prefix_still_names_the_procedure():
    text = (
        "EST LAX IAP LOS ANGELES INTL, LOS ANGELES, CA. ILS OR LOC RWY 7R, AMDT 8A... "
        "AUTO-PILOT COUPLED APPROACH NA BELOW 800."
    )
    assert _summary(text) == (
        "ILS OR LOC RWY 7R: AUTO-PILOT COUPLED APPROACH NA BELOW 800 during the applicable destination window."
    )

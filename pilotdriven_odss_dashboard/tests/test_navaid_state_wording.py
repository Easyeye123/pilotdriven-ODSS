"""Boss 02 Sep 2026 21:22: what he reads first is "instrument approaches being
affected such as ILS or VOR not working, or on test or unserviceable" — so the
dashboard line for a navaid record names the aid and its state, never
"restriction applies". A5 now holds the source-derived summary for both
surfaces; the old dashboard helper remains available for older saved packs."""

from app.odss.engines import _notam_operational_summary, notam_dashboard_line
from app.odss.pilot_briefing import notam_pertinence


def _line(text: str) -> str:
    _, kind = notam_pertinence(text)
    return notam_dashboard_line(text, kind)


def test_ils_on_test_names_the_aid_runway_and_state():
    assert _line("ILS CAT I RWY 06 ON TEST, DO NOT USE (AWAITING FLTCK VERIFICATION).") == (
        "ILS CAT I RWY 06 on test, do not use."
    )


def test_unserviceable_vor_dme_names_the_aid_and_identifier():
    assert _line("DVOR/DME 'MNL' U/S DUE MAINT.") == "DVOR/DME MNL unserviceable."


def test_not_available_and_plain_runway_work_have_no_dashboard_line():
    assert _line("ILS RWY 20R NOT AVBL.") == ""
    assert _line("RWY 22 WIP CONST EAST SIDE.") == ""


def test_faa_procedure_notice_names_the_procedure_and_its_note():
    text = (
        "IAP LOS ANGELES INTL, LOS ANGELES, CA. ILS OR LOC RWY 7R, AMDT 8A... "
        "AUTO-PILOT COUPLED APPROACH NA BELOW 800."
    )
    assert _line(text) == "ILS OR LOC RWY 7R: AUTO-PILOT COUPLED APPROACH NA BELOW 800."


def test_faa_cat_ii_minima_notice_keeps_the_procedure_and_the_rvr_note():
    text = (
        "IAP LOS ANGELES INTL, LOS ANGELES, CA. ILS OR LOC RWY 24R, AMDT 26C... "
        "ILS RWY 24R (CAT II-III), AMDT 26C... S-ILS 24R CAT II RVR 1200. CAT II NOTE: RVR 1000 "
        "AUTHORIZED WITH SPECIFIC OPSPEC, MSPEC, OR LOA APPROVAL AND USE OF AUTOLAND OR HUD TO TOUCHDOWN."
    )
    assert _line(text) == "ILS RWY 24R (CAT II-III): S-ILS 24R CAT II RVR 1200."


def test_faa_procedure_notice_with_an_ofp_prefix_still_names_the_procedure():
    text = (
        "EST LAX IAP LOS ANGELES INTL, LOS ANGELES, CA. ILS OR LOC RWY 7R, AMDT 8A... "
        "AUTO-PILOT COUPLED APPROACH NA BELOW 800."
    )
    assert _line(text) == "ILS OR LOC RWY 7R: AUTO-PILOT COUPLED APPROACH NA BELOW 800."


def test_a_negated_or_neighbouring_state_never_binds_to_the_aid():
    assert _line("ILS RWY 20C NOT U/S.") == ""
    assert _line("ILS RWY 25 AVBL. PAPI RWY 25 U/S.") == ""


def test_new_pdf_summary_states_the_source_restriction_for_both_surfaces():
    text = "ILS CAT I RWY 06 ON TEST, DO NOT USE (AWAITING FLTCK VERIFICATION)."
    _, kind = notam_pertinence(text)
    held = _notam_operational_summary(text, kind, "destination")
    # C1: the whole notice is one clause, so publishing all of it reproduces the
    # record and the concise PDF gate refuses the page. Both surfaces keep the
    # filed state; the parenthetical reason sits behind the ellipsis.
    assert held == "ILS CAT I RWY 06 on test, do not use …"
    from app.odss.briefing import _compact_notam_text
    item = {"item_e_text":text, "summary":held, "pertinence_kind":kind}
    common = dict(role="destination", planned_runways=set(), reference_time=None)
    assert _compact_notam_text(item, "approach_navaid", **common) == held
    assert _compact_notam_text(item, "approach_navaid", dashboard=True, **common) == held


def test_old_saved_template_keeps_the_legacy_dashboard_fallback():
    from datetime import datetime, timezone

    from app.odss.briefing import _compact_notam_text

    item = {
        "notam_id": "B4105/26",
        "pertinence_kind": "runway_approach_restriction",
        "item_e_text": "ILS CAT I RWY 06 ON TEST, DO NOT USE (AWAITING FLTCK VERIFICATION).",
        "summary": "Rwy 06 restriction applies during the applicable destination window.",
    }
    common = dict(role="destination", planned_runways=set(), reference_time=datetime(2026, 8, 21, 4, 45, tzinfo=timezone.utc))
    assert _compact_notam_text(item, "approach_navaid", dashboard=True, **common) == "ILS CAT I RWY 06 on test, do not use."
    assert _compact_notam_text(item, "approach_navaid", **common) == item["summary"]

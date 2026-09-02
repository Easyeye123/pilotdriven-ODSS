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

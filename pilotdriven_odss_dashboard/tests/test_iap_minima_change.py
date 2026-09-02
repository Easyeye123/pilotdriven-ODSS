"""FAA IAP minima-change notices are approach facts, not obstacle noise.

A US "IAP ... DA/HAT ... CRANE" notice changes published approach minima.
Classifying it as an obstacle hides it behind the crane/obstacle filter even
though it is the kind of fact a crew must see before an approach briefing.
A plain crane notice with no procedure and no minima stays an obstacle.
"""

from __future__ import annotations

from app.odss.briefing import _compact_notam_family
from app.odss.engines import (
    _instrument_approach_affected,
    _notam_operational_summary,
)
from app.odss.pilot_briefing import notam_pertinence


PHNL = (
    "IAP DANIEL K INOUYE INTL, HONOLULU, HI. RNAV (GPS) RWY 26L, ORIG-B. "
    "RNP 0.15 DA 710/HAT 388 ALL CATS. "
    "TEMPORARY CRANE 220 MSL 2669FT NW OF HNL AIRPORT (2026-ASO-1234-OE)"
)


def test_iap_minima_change_is_an_approach_kind_not_an_obstacle() -> None:
    rank, kind = notam_pertinence(PHNL, "Obstacle")
    assert kind == "approach_minima_change" and rank == 2


def test_iap_minima_change_is_approach_affected_and_summarised() -> None:
    assert _instrument_approach_affected(PHNL, "Obstacle") is True
    assert _notam_operational_summary(PHNL, "approach_minima_change", "EDTO") == (
        "RNAV (GPS) RWY 26L minima changed (DA 710/HAT 388) by a temporary "
        "crane during the applicable EDTO window."
    )


def test_plain_crane_stays_an_obstacle() -> None:
    rank, kind = notam_pertinence("CRANE 260 MSL 1NM N OF AD", "Obstacle")
    assert kind == "obstacle"
    assert rank == 8


def test_iap_minima_change_reads_as_its_own_approach_minima_signal() -> None:
    """A changed minimum is not an outage, so it must not share that slot.

    The compact card shows one notice per family. Filing a minima change
    under ``approach_navaid`` let it evict a real ILS/GP outage from the
    card; its own family lets both facts appear, outage first.
    """

    assert _compact_notam_family({
        "pertinence_kind": "approach_minima_change",
        "item_e_text": PHNL,
    }) == "approach_minima"


def test_iap_minima_change_summary_reports_the_role_window() -> None:
    """The phase wording follows the same role vocabulary as every kind."""

    assert _notam_operational_summary(
        PHNL,
        "approach_minima_change",
        "destination alternate",
    ) == (
        "RNAV (GPS) RWY 26L minima changed (DA 710/HAT 388) by a temporary "
        "crane during the applicable alternate window."
    )


def test_ils_minima_change_without_a_crane_omits_the_crane_cause() -> None:
    text = (
        "IAP SEATTLE-TACOMA INTL, SEATTLE, WA. ILS RWY 16R, AMDT 12. "
        "S-ILS 16R DA 480/HAT 200 ALL CATS."
    )
    rank, kind = notam_pertinence(text, "Instrument Approach Procedure")
    assert (rank, kind) == (2, "approach_minima_change")
    assert _notam_operational_summary(text, kind, "destination") == (
        "ILS RWY 16R minima changed (DA 480/HAT 200) during the applicable "
        "destination window."
    )


def test_combined_ils_or_loc_chart_keeps_its_published_procedure_title() -> None:
    """Never print an ILS decision altitude under a bare LOC heading.

    US charts are republished as one "ILS OR LOC RWY nn" procedure. Naming
    only the LOC half while quoting the S-ILS DA would tell a crew the
    localiser approach has a decision altitude it does not have.
    """

    text = (
        "IAP OAKLAND SAN FRANCISCO BAY, OAKLAND, CA. ILS OR LOC RWY 28R, "
        "AMDT 38... S-ILS 28R DA 257/HAT 250 ALL CATS."
    )
    _, kind = notam_pertinence(text, "Approach Procedure")
    assert kind == "approach_minima_change"
    assert _notam_operational_summary(text, kind, "destination") == (
        "ILS OR LOC RWY 28R minima changed (DA 257/HAT 250) during the "
        "applicable destination window."
    )


def test_obstacle_notice_naming_an_iap_without_minima_stays_an_obstacle() -> None:
    """The rule needs a procedure AND published minima, not the word IAP."""

    text = (
        "IAP DANIEL K INOUYE INTL, HONOLULU, HI. "
        "TEMPORARY CRANE 220 MSL 2669FT NW OF HNL AIRPORT (2026-ASO-1234-OE)"
    )
    _, kind = notam_pertinence(text, "Obstacle")
    assert kind == "obstacle"


IAP_CATEGORY_ONLY = "RNAV (GPS) RWY 26L, AMDT 2. LPV DA 710/HAT 388 ALL CATS."


def test_category_only_iap_token_still_reads_as_a_minima_change() -> None:
    """All three decisions must search the same string.

    A source block heading can supply the `IAP` category while item E names
    only the procedure and its minima. The kind, the approach flag and the
    printed sentence have to agree about that record, or the digest calls it
    critical while the briefing calls it a generic restriction.
    """

    rank, kind = notam_pertinence(IAP_CATEGORY_ONLY, "IAP")
    assert (rank, kind) == (2, "approach_minima_change")
    assert _instrument_approach_affected(IAP_CATEGORY_ONLY, "IAP") is True
    assert _notam_operational_summary(
        IAP_CATEGORY_ONLY,
        kind,
        "destination",
        category="IAP",
    ) == (
        "RNAV (GPS) RWY 26L minima changed (DA 710/HAT 388) during the "
        "applicable destination window."
    )


def test_minima_change_summary_never_falls_through_to_the_generic_line() -> None:
    """The branch returns for its own kind whatever the wording holds."""

    summary = _notam_operational_summary(
        "PUBLISHED MINIMA REVISED, SEE CHART.",
        "approach_minima_change",
        "departure",
    )
    assert "minima" in summary.lower()
    assert "Operational airport restriction requires review" not in summary
    assert summary.endswith("during the applicable departure window.")

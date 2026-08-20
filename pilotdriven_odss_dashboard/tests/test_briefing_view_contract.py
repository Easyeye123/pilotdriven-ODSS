from __future__ import annotations

from app.odss.briefing import build_briefing_view
from app.odss.parser import parse_lido


LOG_PAGE_HIGH = (
    "ALPHA        01.25 0.27 ... ... ... ... ... ..... 486  005  02.4 ...\n"
    "S08 20.2 E107 49.7 117*0225 410 ... 164 M01 05041 495 1530 023.1 ...\n"
    " \n"
    "BRAVO        02.10 0.20 ... ... ... ... ... ..... 486  004  01.7 ...\n"
    "S12 44.0 E109 50.5 042 0160 410 ... 164 M01 07059 489 1755 025.5 ...\n"
)
LOG_PAGE_LOW = (
    "ALPHA        01.25 0.27 ... ... ... ... ... ..... 486  005  02.4 ...\n"
    "S08 20.2 E107 49.7 056 0225 410 ... 164 M01 05041 495 1530 023.1 ...\n"
    " \n"
    "BRAVO        02.10 0.20 ... ... ... ... ... ..... 486  004  01.7 ...\n"
    "S12 44.0 E109 50.5 042 0160 410 ... 164 M01 07059 489 1755 025.5 ...\n"
)


def _flight(log_page: str) -> dict:
    page1 = (
        "SUMMARY STANDARD CFP\n"
        "9VAAA SQ999 SIN/BKK ETD 0250 01AUG26\n"
        "SCHED DEP 0250 UTC SCHED ARR 0520 UTC\n"
        "RTE NO 001            A350-941 MH  CAPT TESTA B C\n"
        "WSSS/20C\n"
        "DCT ALPHA DCT BRAVO\n"
        "VTBS/19L\n"
        "GND  MILES    900\n"
        "AIR  MILES    930\n"
        "BURNOFF 02.00 010000\n"
        "TAXI FUEL 001000\n"
        "FLT PLAN REQMT 03.00 015000\n"
        "FUEL IN TANKS 04.00 020000\n"
        "PZFW 180000\n"
        "PTOW 200000\n"
        "PLWT 190000\n"
    )
    pages = [page1, "", "", "", "", "", log_page]
    return parse_lido(pages, "briefing-view-contract.pdf")


def test_terrain_key_is_engine_backed_and_always_present() -> None:
    high = build_briefing_view(_flight(LOG_PAGE_HIGH), [], [])
    assert high["terrain"]["events"], "a >100* waypoint must produce a terrain event"
    assert "No strict MSA" not in high["terrain"]["summary"]

    low = build_briefing_view(_flight(LOG_PAGE_LOW), [], [])
    assert low["terrain"]["events"] == []
    assert low["terrain"]["summary"] == "No strict MSA >100* window detected"


def test_terrain_summary_and_events_can_never_disagree() -> None:
    view = build_briefing_view(_flight(LOG_PAGE_HIGH), [], [])
    has_events = bool(view["terrain"]["events"])
    says_none = "No strict MSA" in view["terrain"]["summary"]
    assert has_events != says_none


def test_airport_panels_carry_raw_metar_and_taf() -> None:
    flight = _flight(LOG_PAGE_LOW)
    flight["weather"] = [
        {"location": "WSSS", "record_type": "METAR", "text": "SA 172000 11007KT 9999 FEW018", "source_page": 14},
        {"location": "WSSS", "record_type": "TAF", "text": "FT 171700 1718/1900 14008KT 9999", "source_page": 14},
        {"location": "VTBS", "record_type": "METAR", "text": "SA 172000 AUTO 05006KT 9999", "source_page": 15},
    ]
    view = build_briefing_view(flight, [], [])

    assert view["departure"]["weather"]["metar"] == "SA 172000 11007KT 9999 FEW018"
    assert view["departure"]["weather"]["taf"] == "FT 171700 1718/1900 14008KT 9999"
    assert view["destination"]["weather"]["metar"] == "SA 172000 AUTO 05006KT 9999"
    assert view["destination"]["weather"]["taf"] is None


def test_airport_panels_without_records_stay_honest() -> None:
    flight = _flight(LOG_PAGE_LOW)
    flight["weather"] = []
    view = build_briefing_view(flight, [], [])

    assert view["departure"]["weather"]["metar"] is None
    assert view["departure"]["weather"]["taf"] is None


def test_metrics_carry_the_captain() -> None:
    view = build_briefing_view(_flight(LOG_PAGE_LOW), [], [])
    assert view["metrics"]["captain"] == "TESTA B C"


def test_edto_operational_rows_are_part_of_the_view() -> None:
    view = build_briefing_view(_flight(LOG_PAGE_LOW), [], [])
    rows = view["edto"]["operational_rows"]
    assert rows and rows[0]["label"] == "CLASSIFICATION"
    labels = [row["label"] for row in rows]
    assert "GATE" in labels and "FUEL" in labels
    assert all(isinstance(row["value"], str) and row["value"] for row in rows)


def test_va_sigmet_records_become_named_deduped_advisories() -> None:
    flight = _flight(LOG_PAGE_LOW)
    record = {
        "location": "WIIF",
        "record_type": "VA_SIGMET",
        "text": "WIIF JAKARTA FIR WV SIGMET 08 VALID 172009/180208 WIII- WIIF JAKARTA FIR VA ERUPTION MT KRAKATAU PSN S0606 E10525 VA CLD OBS AT 1930Z WI S0614 E10534 - S0623 E10451 SFC/FL070 MOV NW 10KT NC=",
        "source_page": 13,
    }
    flight["weather"] = [dict(record), dict(record)]
    view = build_briefing_view(flight, [], [])
    advisories = view["vaa"]["cfp_advisories"]
    assert len(advisories) == 1, "identical wx-list reprints collapse to one advisory"
    assert advisories[0]["name"] == "VOLCANIC ASH · MT KRAKATAU · WIIF WV SIGMET 08"
    assert advisories[0]["valid_from"] == "172009" and advisories[0]["valid_to"] == "180208"


def test_va_polygon_screening_derives_closest_approach() -> None:
    flight = _flight(LOG_PAGE_LOW)
    flight["weather"] = [{
        "location": "WIIF",
        "record_type": "VA_SIGMET",
        "text": (
            "WIIF JAKARTA FIR WV SIGMET 08 VALID 172009/180208 VA ERUPTION "
            "MT KRAKATAU PSN S0606 E10525 VA CLD OBS AT 1930Z WI "
            "S0720 E10749 - S0720 E10849 - S0620 E10800 SFC/FL070 MOV NW 10KT NC="
        ),
        "source_page": 13,
    }]
    view = build_briefing_view(flight, [], [])
    derived = view["vaa"]["cfp_advisories"][0]["derived"]
    # Nearest polygon point sits 60 NM north of ALPHA (S08 20.2 E107 49.7):
    # the screening says so with the passage time (ALPHA ACTM 01:25 after the
    # 0250Z departure), the layer, and the no-official-VAAC caveat verbatim.
    # The SIGMET's validity day is nowhere near this synthetic flight date,
    # so no expiry comparison may be printed.
    assert derived.startswith("Closest approach 60 NM near ALPHA; route passes ~0415Z; ash layer SFC/FL070;")
    assert "expiry" not in derived and "validity (to" not in derived
    assert "official VAAC confirmation unavailable" in derived


def test_va_screening_compares_passage_time_with_sigmet_validity() -> None:
    flight = _flight(LOG_PAGE_LOW)
    polygon = "WI S0720 E10749 - S0720 E10849 - S0620 E10800 SFC/FL070"
    # Passage is ~0415Z on 01 Aug (ALPHA ACTM 01:25 after 0250Z departure).
    for valid, expected in (
        ("010300/010500", "inside the SIGMET's validity (to 0500Z)"),
        ("010200/010355", "20 min after the SIGMET's 0355Z expiry"),
    ):
        flight["weather"] = [{
            "location": "WIIF", "record_type": "VA_SIGMET",
            "text": f"WIIF JAKARTA FIR WV SIGMET 08 VALID {valid} VA ERUPTION MT KRAKATAU {polygon}",
        }]
        view = build_briefing_view(flight, [], [])
        derived = view["vaa"]["cfp_advisories"][0]["derived"]
        assert expected in derived, derived


def test_va_caveat_reflects_a_held_official_advisory() -> None:
    flight = _flight(LOG_PAGE_LOW)
    flight["weather"] = [{
        "location": "WIIF", "record_type": "VA_SIGMET",
        "text": (
            "WIIF JAKARTA FIR WV SIGMET 08 VALID 010300/010500 VA ERUPTION "
            "MT KRAKATAU WI S0720 E10749 - S0720 E10849 - S0620 E10800 SFC/FL070"
        ),
    }]
    flight["vaa_review"] = {"direct_vaac_snapshot": {"advisories": [{
        "volcano": "KRAKATAU 262000", "vaac": "DARWIN", "centre": "DARWIN",
        "advisory_number": "2026/116", "issued_at_utc": "2026-08-01T08:00:00+00:00",
        "remarks": "CURRENT SATELLITE IMAGERY INDICATES VA HAS NOW DISSIPATED. ADVISORY TERMINATED.",
    }]}}
    view = build_briefing_view(flight, [], [])
    derived = view["vaa"]["cfp_advisories"][0]["derived"]
    assert "official VAAC confirmation unavailable" not in derived
    assert (
        "official DARWIN advisory 2026/116 (01/0800Z) reports the ash dissipated"
        in derived
    ), derived

    # A held advisory for a DIFFERENT volcano changes nothing: the honest
    # caveat stays, and the manifest may still say DARWIN reached.
    flight["vaa_review"]["direct_vaac_snapshot"]["advisories"][0]["volcano"] = "SEMERU 263300"
    view = build_briefing_view(flight, [], [])
    assert "official VAAC confirmation unavailable" in view["vaa"]["cfp_advisories"][0]["derived"]


def test_va_advisory_without_readable_polygon_has_no_derived_line() -> None:
    flight = _flight(LOG_PAGE_LOW)
    flight["weather"] = [{
        "location": "WIIF",
        "record_type": "VA_SIGMET",
        # Two-point "polygon": unreadable as an area, so no distance may be
        # invented - the card shows only the named advisory.
        "text": "WIIF JAKARTA FIR WV SIGMET 08 VALID 172009/180208 VA ERUPTION MT KRAKATAU WI S0614 E10534 - S0623 E10451 SFC/FL070",
        "source_page": 13,
    }]
    view = build_briefing_view(flight, [], [])
    assert view["vaa"]["cfp_advisories"][0]["derived"] is None


def test_sigmet_cards_split_merged_records_and_carry_verdict_reasons() -> None:
    flight = _flight(LOG_PAGE_LOW)
    # One CFP FIR block printing two SIGMETs, exactly as Lido does. ALPHA is
    # S08 20.2 E107 49.7; the first polygon contains it, the second sits far
    # south of the whole route.
    flight["weather"] = [{
        "location": "YMMM", "record_type": "SIGMET",
        "text": (
            "YMMM MELBOURNE FIR WS SIGMET A01 VALID 010100/010200 YMMC- "
            "YMMM MELBOURNE FIR SEV ICE FCST WI S0700 E10600 - S0700 E10900 - "
            "S0930 E10900 - S0930 E10600 8000FT/FL210 MOV E 50KT NC= "
            "WS SIGMET B02 VALID 010300/010700 YMMC- YMMM MELBOURNE FIR SEV TURB "
            "FCST WI S4900 E08300 - S4400 E09500 - S5000 E11800 FL140/250 MOV E 35KT NC="
        ),
    }]
    view = build_briefing_view(flight, [], [])
    cards = {card["sigmet_id"]: card for card in view["hazards"]["sigmet_cards"]}
    assert set(cards) == {"A01", "B02"}

    # A01 contains ALPHA (ACTM 01:25 -> passes 0415Z) but expired 0200Z:
    # crossing window printed, expiry gap named, NOT PROMOTED.
    a01 = cards["A01"]
    assert a01["layer"] == "8000FT/FL210" and a01["phenomenon"] == "SEV ICE"
    assert a01["disposition"] == "NOT PROMOTED"
    assert "crosses the route" in a01["screening"] and "expires" in a01["screening"]

    # B02 never touches the route: distance + bearing, NOT PROMOTED.
    b02 = cards["B02"]
    assert b02["layer"] == "FL140/250"
    assert b02["disposition"] == "NOT PROMOTED"
    assert "does not intersect" in b02["screening"] and "NM south" in b02["screening"]


def test_sigmet_inside_validity_is_promoted_and_no_polygon_is_review() -> None:
    flight = _flight(LOG_PAGE_LOW)
    flight["weather"] = [{
        "location": "WSJC", "record_type": "SIGMET",
        # Valid 0100-0800Z, ALPHA crossing ~0415Z -> inside validity.
        "text": (
            "WSJC SINGAPORE FIR WS SIGMET C03 VALID 010100/010800 WSSS- "
            "WSJC SINGAPORE FIR EMBD TS FCST WI S0700 E10600 - S0700 E10900 - "
            "S0930 E10900 - S0930 E10600 TOP FL450 MOV W 10KT NC="
        ),
    }, {
        "location": "WIIF", "record_type": "SIGMET",
        "text": "WIIF JAKARTA FIR WS SIGMET D04 VALID 010100/010800 WIII- WIIF JAKARTA FIR SEV TURB FCST ENTIRE FIR FL200/380 MOV E 5KT NC=",
    }]
    view = build_briefing_view(flight, [], [])
    cards = {card["sigmet_id"]: card for card in view["hazards"]["sigmet_cards"]}
    assert cards["C03"]["disposition"] == "PROMOTED"
    assert "inside the product's validity" in cards["C03"]["screening"]
    # ENTIRE FIR carries no polygon: screening honestly unavailable.
    assert cards["D04"]["disposition"] == "REVIEW REQUIRED"
    assert "review the original SIGMET" in cards["D04"]["screening"]


def test_coverage_ledger_marks_absent_sections_unavailable() -> None:
    flight = _flight(LOG_PAGE_LOW)
    view = build_briefing_view(flight, [], [])
    ledger = {row["label"]: row["status"] for row in view["hazards"]["coverage_ledger"]}
    assert ledger == {"AIRMET": "unavailable", "TC SIGMET": "unavailable", "VA SIGMET": "unavailable"}
    flight["weather"] = [{
        "location": "WIIF", "record_type": "VA_SIGMET",
        "text": "WIIF JAKARTA FIR WV SIGMET 08 VALID 010300/010500 VA ERUPTION MT KRAKATAU WI S0720 E10749 - S0720 E10849 - S0620 E10800 SFC/FL070",
    }]
    view = build_briefing_view(flight, [], [])
    ledger = {row["label"]: row["status"] for row in view["hazards"]["coverage_ledger"]}
    assert ledger["VA SIGMET"] == "held"


def test_vaac_reach_is_composed_in_the_view_for_every_surface() -> None:
    # The tally and per-centre strings were once arithmetic inside the PDF
    # renderer, so the dashboard never showed them (deploy #20 comparison).
    flight = _flight(LOG_PAGE_LOW)
    flight["vaa_review"] = {
        "status": "review_required",
        "vaac_centre_ledger": [
            {"centre": "Anchorage", "status": "available"},
            {"centre": "Darwin", "status": "partial"},
            {"centre": "Tokyo", "status": "available"},
            {"centre": "London", "status": "unavailable"},
            {"centre": "Wellington", "status": "not_mounted"},
        ],
    }
    view = build_briefing_view(flight, [], [])
    reach = view["hazards"]["vaac_reach"]
    assert reach["summary"] == "3/5 reached"
    assert reach["centres"][0] == {"centre": "ANCHORAGE", "status": "reached"}
    assert reach["centres"][1] == {"centre": "DARWIN", "status": "partial"}
    assert reach["centres"][4] == {"centre": "WELLINGTON", "status": "not mounted"}

    flight["vaa_review"] = {}
    view = build_briefing_view(flight, [], [])
    # No direct-feed ledger held: the tally states the full responsible set.
    assert view["hazards"]["vaac_reach"] == {"summary": "0/9 reached", "centres": []}


def test_no_va_records_mean_no_advisories() -> None:
    flight = _flight(LOG_PAGE_LOW)
    flight["weather"] = []
    view = build_briefing_view(flight, [], [])
    assert view["vaa"]["cfp_advisories"] == []

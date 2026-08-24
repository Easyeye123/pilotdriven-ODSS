from __future__ import annotations

from app.odss.briefing import (
    _fir_boundary_summary,
    _intam_operational_priority_rows,
    _intam_review_queue,
    build_briefing_view,
)


def _intam_records() -> list[dict]:
    return [
        {
            "priority": 1,
            "category": "AIRPORT",
            "identity": "ALL FLEETS-8919",
            "headline": "RPLL - OVERSHOOTING OF PARKING POSITION.",
            "body_text": (
                "ENSURE THAT THE TAXI SPEED IS REDUCED APPROPRIATELY AND BE "
                "READY TO REACT TO THE MARSHALLER INSTRUCTION PROMPTLY."
            ),
            "source_page": 39,
        },
        {
            "priority": 1,
            "category": "OPS",
            "identity": "A350-822",
            "headline": (
                "EFF ANOMALY - ABSENT SIGN/SIGNED BUTTON FROM FLYSMART "
                "ELECTRONIC FLIGHT FOLDER APPLICATION"
            ),
            "body_text": (
                "CONTINUE TO SIGN THE OFP ON PILOTSIGN, AS PER SOP, TO "
                "INDICATE ACCEPTANCE."
            ),
            "source_page": 41,
        },
        {
            "priority": 1,
            "category": "SAFETY",
            "identity": "ALL FLEETS-9116",
            "headline": (
                "GNSS/GPS RADIO FREQUENCY INTERFERENCE (RFI) & REPORTING - "
                "REVISED 03 JUL 2026"
            ),
            "body_text": (
                "FLIGHTS OPERATING IN THE FOLLOWING FIRS HAVE REPORTED "
                "GNSS/GPS RADIO FREQUENCY INTERFERENCE: "
                "12. WSJC - SINGAPORE (S. CHINA SEA)"
            ),
            "source_page": 44,
        },
    ]


def _notam_procedure_records() -> list[dict]:
    return [
        {
            "notam_id": "1A1891/26",
            "validity": "04-JUN-26 0000 - 02-SEP-26 2359",
            "heading": "WIIF JAKARTA FIR",
            "source_page": 32,
            "text": (
                "ADS-C/CPDLC OPERATIONAL LIMITED TRIAL WILL BE INITIATED AS "
                "REQUESTED BY ATC. AFN LOGON PROCESS WILL BE INITIATED BY "
                "THE PILOT. THE AFN LOGON ADDRESS FOR JAKARTA FIR IS WIIF."
            ),
            "applicability": "not_inferred",
        }
    ]


def test_operational_priority_rows_are_source_held_and_traceable() -> None:
    rows = _intam_operational_priority_rows(
        _intam_records(),
        _notam_procedure_records(),
    )

    assert rows == [
        {
            "key": "jakarta_cpdlc_trial",
            "title": "JAKARTA ADS-C / CPDLC TRIAL",
            "summary": (
                "The limited trial is initiated at ATC request; the pilot "
                "initiates AFN logon; the Jakarta FIR AFN address is WIIF."
            ),
            "source_type": "NOTAM PROCEDURE",
            "source_identity": "1A1891/26",
            "source_page": 32,
            "source_reference": "CFP p32 / 1A1891/26",
            "status": "source-held; relevance not inferred",
            "relevance_inferred": False,
            "applicability_inferred": False,
        },
        {
            "key": "rpll_parking_overshoot",
            "title": "RPLL PARKING OVERSHOOT",
            "summary": (
                "Reduce taxi speed appropriately and be ready to respond "
                "promptly to the marshaller."
            ),
            "source_type": "INTAM",
            "source_identity": "ALL FLEETS-8919",
            "source_page": 39,
            "source_reference": "CFP p39 / ALL FLEETS-8919",
            "status": "source-held; relevance not inferred",
            "relevance_inferred": False,
            "applicability_inferred": False,
        },
        {
            "key": "flysmart_pilotsign",
            "title": "FLYSMART / PILOTSIGN",
            "summary": (
                "The FlySmart sign/signed button is absent; continue signing "
                "the OFP in PilotSign per the source SOP."
            ),
            "source_type": "INTAM",
            "source_identity": "A350-822",
            "source_page": 41,
            "source_reference": "CFP p41 / A350-822",
            "status": "source-held; relevance not inferred",
            "relevance_inferred": False,
            "applicability_inferred": False,
        },
        {
            "key": "gnss_rfi_wsjc_south_china_sea",
            "title": "GNSS RFI / WSJC SOUTH CHINA SEA",
            "summary": (
                "The source bulletin lists WSJC (Singapore FIR, South China "
                "Sea) among FIRs reporting GNSS/GPS interference."
            ),
            "source_type": "INTAM",
            "source_identity": "ALL FLEETS-9116",
            "source_page": 44,
            "source_reference": "CFP p44 / ALL FLEETS-9116",
            "status": "source-held; relevance not inferred",
            "relevance_inferred": False,
            "applicability_inferred": False,
        },
    ]


def test_operational_priority_rows_do_not_invent_missing_source_actions() -> None:
    intam_records = _intam_records()
    intam_records[0]["body_text"] = "PARKING POSITION BULLETIN."
    intam_records[1].pop("source_page")
    intam_records[2]["body_text"] = "GNSS RFI REPORTING BULLETIN."
    procedures = _notam_procedure_records()
    procedures[0]["text"] = "ADS-C/CPDLC TRIAL."

    assert _intam_operational_priority_rows(intam_records, procedures) == []


def test_briefing_view_exposes_priority_rows_without_mutating_review_queue() -> None:
    intam_records = _intam_records()
    procedure_records = _notam_procedure_records()
    flight = {
        "document_id": "sq910-source.pdf",
        "flight_number": "SQ910",
        "flight_date": "2026-08-21",
        "departure": "WSSS",
        "destination": "RPLL",
        "route_waypoints": [
            {
                "name": "-WIIF",
                "fir_boundary": "WIIF",
                "actm_minutes": 3,
                "source_page": 7,
            }
        ],
        "intam_records": intam_records,
        "notam_procedure_records": procedure_records,
    }

    view = build_briefing_view(flight, [], [])

    assert [row["key"] for row in view["intam"]["operational_priority_rows"]] == [
        "jakarta_cpdlc_trial",
        "rpll_parking_overshoot",
        "flysmart_pilotsign",
        "gnss_rfi_wsjc_south_china_sea",
    ]
    assert view["intam"]["review_queue"] == _intam_review_queue(intam_records)
    assert view["intam"]["procedure_record_count"] == 1
    assert view["intam"]["procedure_source_pages"] == [32]
    assert view["intam"]["procedure_records"] == procedure_records
    assert view["intam"]["procedure_records"][0]["text"].startswith(
        "ADS-C/CPDLC OPERATIONAL LIMITED TRIAL"
    )
    assert "Jakarta CPDLC/AFN procedure is source-held separately" in view[
        "fir_boundary_summary"
    ]
    assert "frequency/lead are unavailable" in view["fir_boundary_summary"]
    assert "applicability is not inferred" in view["fir_boundary_summary"]
    assert "Contact procedure/frequency unavailable" not in view[
        "fir_boundary_summary"
    ]


def test_fir_summary_keeps_the_procedure_gap_when_no_source_record_is_held() -> None:
    rows = [
        {
            "event": "WIIF FIR boundary",
            "actm": "+00:03",
            "source_page": 7,
        }
    ]

    assert _fir_boundary_summary(rows, []) == (
        "WIIF +00:03 (CFP p7). Contact procedure/frequency unavailable; no "
        "lead or frequency is inferred."
    )

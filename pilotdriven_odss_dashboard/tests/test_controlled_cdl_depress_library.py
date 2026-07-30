from __future__ import annotations

from datetime import timezone
import io
import json
import sys
from types import SimpleNamespace

import pytest

from app.odss import engines
from app.odss import controlled_library
from app.odss.controlled_library import (
    aircraft_effectivity_tokens,
    load_depress_profiles,
    select_cdl_variants,
)
from app.odss.engines import analyse, detect_terrain_events, match_profiles
from app.odss.parser import _parse_deferred_items

UTC = timezone.utc


def _flight(route_waypoints: list[dict] | None = None) -> dict:
    return {
        "document_id": "test.pdf",
        "flight_number": "SQ24",
        "flight_date": "22JUL26",
        "aircraft_type": "A350-941",
        "registration": "9V-SGE",
        "departure": "WSSS",
        "destination": "KJFK",
        "departure_runway": "20C",
        "destination_runway": "22L",
        "scheduled_departure_utc": "2026-07-22T04:10:00+00:00",
        "scheduled_arrival_utc": "2026-07-22T22:50:00+00:00",
        "route_text": "",
        "route_waypoints": route_waypoints or [],
        "planned_level_profile": None,
        "cost_index": 70,
        "edto_rvsm": "EDTO/RVSM",
        "bobcat": None,
        "deferred_items": [],
        "alternates": [],
        "performance": {},
        "fuel": {
            "trip_fuel_kg": 106_345,
            "contingency_fuel_kg": 1_031,
            "alternate_fuel_kg": 2_119,
            "alternate_holding_fuel_kg": 2_174,
            "taxi_fuel_kg": 600,
            "flight_plan_required_fuel_kg": 112_269,
            "excess_fuel_kg": 6_100,
            "fuel_in_tanks_kg": 118_369,
            "planned_destination_fuel_kg": 11_424,
        },
        "masses": {
            "planned_zfw_kg": 162_231,
            "planned_takeoff_weight_kg": 280_000,
            "planned_landing_weight_kg": 173_655,
        },
        "edto": {
            "entry_actm_minutes": None,
            "exit_actm_minutes": None,
            "etp_actm_minutes": [],
            "airports": [],
        },
        "notams": [],
        "weather": [],
    }


def _wp(
    name: str,
    actm: int,
    msa: int,
    airway: str | None,
    *,
    star: bool = False,
) -> dict:
    return {
        "name": name,
        "actm_minutes": actm,
        "fir_boundary": None,
        "latitude": None,
        "longitude": None,
        "msa_hundreds_ft": msa,
        "msa_asterisk": star,
        "vws": None,
        "airway_in": airway,
    }


def test_page1_parser_recognises_upper_block_cdl_reference() -> None:
    page1 = "\n".join(
        (
            "SUMMARY EDTO CFP",
            "AA CDL 28-01",
            "FUEL JETTISON TUBES MISSING",
            "BOTH TUBES REMOVED",
            "PLAN 32/0/1",
            "RTE NO 123 A350-941",
        )
    )
    assert _parse_deferred_items(page1) == [
        {
            "reference": "28-01",
            "description": "FUEL JETTISON TUBES MISSING",
            "item_type": "CDL",
            "company_remark": "BOTH TUBES REMOVED",
        }
    ]


def test_aircraft_series_effectivity_tokens() -> None:
    assert aircraft_effectivity_tokens("9V-SGE", "A350-941") == {"A350941", "ULR"}
    assert aircraft_effectivity_tokens("9V-SMA", "A350-941") == {"A350941", "LH"}
    assert aircraft_effectivity_tokens("9V-SHA", "A350-941") == {"A350941", "MH"}


def test_cdl_variant_selection_is_registration_specific() -> None:
    record = {
        "variants": [
            {"applicable_registrations": ["9V-SGE"], "component": "ULR VARIANT"},
            {"applicable_registrations": ["9V-SMA"], "component": "LH VARIANT"},
        ]
    }
    assert [item["component"] for item in select_cdl_variants(record, "9VSGE")] == [
        "ULR VARIANT"
    ]
    assert select_cdl_variants(record, "9V-SHA") == []


def test_controlled_cdl_finding_includes_penalties_and_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    record = {
        "reference": "28-01",
        "title": "Fuel Jettison Tube",
        "source_pages": [241],
        "variants": [
            {
                "quantity_installed": "2",
                "component": "FUEL JETTISON TUBE",
                "applicable_registrations": ["9V-SGE"],
                "dispatch_conditions": "All may be missing provided that the jettison system is deactivated.",
                "limitations": None,
                "notes": ["May be combined with any other item listed in CDL-28 chapter."],
                "maintenance_references": ["A350-A-28-31-XX-00ZZZ-560Z-A"],
                "mel_references": ["MEL/MI-28-31"],
                "takeoff_approach_penalty_kg_values": [60],
                "enroute_penalty_kg_values": [],
                "fuel_penalty_percent_values": [],
            }
        ],
    }
    monkeypatch.setattr(engines, "CDL_REFERENCES", {"28-01": record})
    monkeypatch.setattr(
        engines,
        "CDL_LIBRARY_METADATA",
        {"title": "SIA A350 Fleet CDL", "issue_date": "2026-05-05", "status": "controlled-index-loaded"},
    )
    flight = _flight()
    flight["deferred_items"] = [
        {
            "item_type": "CDL",
            "reference": "28-01",
            "description": "FUEL JETTISON TUBES MISSING",
            "company_remark": "BOTH TUBES REMOVED",
        }
    ]
    findings, _ = analyse(flight)
    result = next(item for item in findings if item["engine"] == "cdl")
    assert result["data"]["source_pages"] == [241]
    assert result["data"]["takeoff_approach_penalty_kg_values"] == [60]
    assert any("jettison system is deactivated" in detail for detail in result["details"])


def test_exact_100_star_is_a_boundary_not_high_msa() -> None:
    """v1.3 strict trigger: only MSA strictly above 100 (10,000 ft) qualifies.

    An exact ``100*`` row is a boundary - it never starts an exposure, and it
    terminates an active one (the approved SQ352 example: exact 100* at LUSAL
    terminates the ALUVO event).
    """
    waypoints = [
        _wp("BEFORE", 1, 90, "DCT"),
        _wp("STAR100", 2, 100, "DCT", star=True),
        _wp("DROP", 3, 90, "DCT"),
    ]
    assert detect_terrain_events(waypoints) == []

    terminating = [
        _wp("HIGH", 1, 130, "DCT", star=True),
        _wp("STAR100", 2, 100, "DCT", star=True),
        _wp("AFTER", 3, 120, "DCT", star=True),
    ]
    events = detect_terrain_events(terminating)
    assert [
        (event["first_high"]["name"], (event.get("drop") or {}).get("name"))
        for event in events
    ] == [("HIGH", "STAR100"), ("AFTER", None)]


def test_same_profile_can_cover_two_separate_terrain_events(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    waypoints = [
        _wp("START", 0, 90, "DCT"),
        _wp("HIGH1", 10, 120, "DCT", star=True),
        _wp("MIDDLE", 20, 90, "DCT"),
        _wp("HIGH2", 30, 130, "DCT", star=True),
        _wp("END", 40, 90, "DCT"),
    ]
    monkeypatch.setattr(
        engines,
        "DEPRESS_PROFILES",
        [
            {
                "chart": "GEN-1",
                "from": "START",
                "to": "END",
                "from_aliases": ["START"],
                "to_aliases": ["END"],
                "airways": [],
                "critical": "MIDDLE",
                "critical_aliases": ["MIDDLE"],
                "effectivity": ["ALL"],
            }
        ],
    )

    events = detect_terrain_events(waypoints)
    matches = match_profiles(
        {
            "aircraft_type": "A350-941",
            "registration": "9V-SGE",
            "route_waypoints": waypoints,
        },
        events,
    )

    assert len(events) == 2
    assert len(matches) == 2
    assert [item["terrain_event_id"] for item in matches] == [
        events[0]["terrain_event_id"],
        events[1]["terrain_event_id"],
    ]
    assert [item["profile"]["chart"] for item in matches] == ["GEN-1", "GEN-1"]


def test_airway_alternatives_and_upper_airway_prefix_match_generically(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    waypoints = [
        _wp("TEMEL", 0, 90, "DCT"),
        _wp("HIGH", 10, 150, "UW71", star=True),
        _wp("REBLO", 20, 140, "UR317", star=True),
        _wp("MID", 30, 130, "M11", star=True),
        _wp("RASAM", 40, 110, "N199", star=True),
        _wp("DROP", 50, 90, "N199"),
    ]
    monkeypatch.setattr(
        engines,
        "DEPRESS_PROFILES",
        [
            {
                "chart": "8-7",
                "from": "TEMEL",
                "to": "RASAM",
                "from_aliases": ["TEMEL"],
                "to_aliases": ["RASAM"],
                "airways": ["N199", "M11", "UM11/UR317", "UW71"],
                "critical": "REBLO",
                "critical_aliases": ["REBLO"],
                "effectivity": ["LH", "ULR"],
            }
        ],
    )

    matches = match_profiles(
        {
            "aircraft_type": "A350-941",
            "registration": "9V-SGE",
            "route_waypoints": waypoints,
        },
        detect_terrain_events(waypoints),
    )

    assert [item["profile"]["chart"] for item in matches] == ["8-7"]
    assert matches[0]["coverage_complete"] is True


def test_local_controlled_index_is_validated_and_hashed(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "profiles.json"
    path.write_text(
        json.dumps(
            {
                "document": {
                    "title": "Controlled partial issue",
                    "issue_date": "2026-06-12",
                    "coverage_scope": "partial_issue",
                    "source_document_sha256": "source-hash",
                    "tenant_id": "tenant-a",
                    "governance_state": "approved",
                    "is_current": True,
                },
                "profiles": [
                    {
                        "chart": "GEN-1",
                        "from": "START",
                        "to": "END",
                        "airways": ["DCT"],
                        "critical": "HIGH",
                        "effectivity": ["ALL"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv(controlled_library.DEPRESS_INDEX_ENV, str(path))
    monkeypatch.delenv(controlled_library.DEPRESS_INDEX_S3_ENV, raising=False)
    monkeypatch.setenv(controlled_library.TENANT_ID_ENV, "tenant-a")

    profiles = controlled_library.load_depress_profiles()

    assert [item["chart"] for item in profiles] == ["GEN-1"]
    assert controlled_library.DEPRESS_LIBRARY_METADATA["status"] == (
        "controlled-index-loaded"
    )
    assert controlled_library.DEPRESS_LIBRARY_METADATA["profile_count"] == 1
    assert controlled_library.DEPRESS_LIBRARY_METADATA["coverage_scope"] == (
        "partial_issue"
    )
    assert controlled_library.DEPRESS_LIBRARY_METADATA["tenant_id"] == "tenant-a"
    assert len(controlled_library.DEPRESS_LIBRARY_METADATA["index_sha256"]) == 64
    monkeypatch.delenv(controlled_library.DEPRESS_INDEX_ENV)
    controlled_library.load_depress_profiles()


def test_missing_controlled_index_has_no_built_in_profile_answers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(controlled_library.DEPRESS_INDEX_ENV, raising=False)
    monkeypatch.delenv(controlled_library.DEPRESS_INDEX_S3_ENV, raising=False)
    monkeypatch.delenv(controlled_library.TENANT_ID_ENV, raising=False)

    assert controlled_library.load_depress_profiles() == []
    assert controlled_library.DEPRESS_LIBRARY_METADATA["status"] == (
        "controlled-source-not-mounted"
    )
    assert controlled_library.DEPRESS_LIBRARY_METADATA["coverage_scope"] == "unavailable"
    assert controlled_library.DEPRESS_LIBRARY_METADATA["profile_count"] == 0


def test_empty_configured_controlled_index_fails_closed(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "empty-profiles.json"
    path.write_text(
        json.dumps({"document": {}, "profiles": []}),
        encoding="utf-8",
    )
    monkeypatch.setenv(controlled_library.DEPRESS_INDEX_ENV, str(path))
    monkeypatch.delenv(controlled_library.DEPRESS_INDEX_S3_ENV, raising=False)
    monkeypatch.setenv(controlled_library.TENANT_ID_ENV, "tenant-a")

    with pytest.raises(ValueError, match="non-empty list"):
        controlled_library.load_depress_profiles()


def test_configured_profile_index_requires_explicit_tenant(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "profiles.json"
    path.write_text(
        json.dumps(
            {
                "document": {
                    "tenant_id": "tenant-a",
                    "governance_state": "approved",
                    "is_current": True,
                },
                "profiles": [
                    {
                        "chart": "GEN-1",
                        "from": "START",
                        "to": "END",
                        "critical": "HIGH",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv(controlled_library.DEPRESS_INDEX_ENV, str(path))
    monkeypatch.delenv(controlled_library.DEPRESS_INDEX_S3_ENV, raising=False)
    monkeypatch.delenv(controlled_library.TENANT_ID_ENV, raising=False)

    with pytest.raises(ValueError, match="ODSS_TENANT_ID is required"):
        controlled_library.load_depress_profiles()


@pytest.mark.parametrize(
    ("document_update", "message"),
    (
        ({"tenant_id": "tenant-b"}, "tenant does not match"),
        ({"governance_state": "draft"}, "not approved"),
        ({"is_current": False}, "not current"),
    ),
)
def test_local_profile_index_enforces_governance_and_tenant(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
    document_update: dict,
    message: str,
) -> None:
    document = {
        "tenant_id": "tenant-a",
        "governance_state": "approved",
        "is_current": True,
    }
    document.update(document_update)
    path = tmp_path / "profiles.json"
    path.write_text(
        json.dumps(
            {
                "document": document,
                "profiles": [
                    {
                        "chart": "GEN-1",
                        "from": "START",
                        "to": "END",
                        "critical": "HIGH",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv(controlled_library.DEPRESS_INDEX_ENV, str(path))
    monkeypatch.delenv(controlled_library.DEPRESS_INDEX_S3_ENV, raising=False)
    monkeypatch.setenv(controlled_library.TENANT_ID_ENV, "tenant-a")

    with pytest.raises(ValueError, match=message):
        controlled_library.load_depress_profiles()


def test_s3_profile_index_loads_only_for_matching_approved_tenant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = json.dumps(
        {
            "document": {
                "tenant_id": "tenant-a",
                "governance_state": "approved",
                "is_current": True,
                "coverage_scope": "partial_issue",
            },
            "profiles": [
                {
                    "chart": "GEN-1",
                    "from": "START",
                    "to": "END",
                    "critical": "HIGH",
                }
            ],
        }
    ).encode("utf-8")

    class Body(io.BytesIO):
        closed_by_loader = False

        def close(self) -> None:
            self.closed_by_loader = True
            super().close()

    body = Body(payload)

    def get_object(**kwargs):
        assert kwargs == {
            "Bucket": "private-bucket",
            "Key": "tenant-a/profiles.json",
        }
        return {"Body": body, "ContentLength": len(payload)}

    fake_client = SimpleNamespace(get_object=get_object)
    monkeypatch.setitem(
        sys.modules,
        "boto3",
        SimpleNamespace(client=lambda _: fake_client),
    )
    monkeypatch.delenv(controlled_library.DEPRESS_INDEX_ENV, raising=False)
    monkeypatch.setenv(
        controlled_library.DEPRESS_INDEX_S3_ENV,
        "s3://private-bucket/tenant-a/profiles.json",
    )
    monkeypatch.setenv(controlled_library.TENANT_ID_ENV, "tenant-a")

    profiles = controlled_library.load_depress_profiles()

    assert [item["chart"] for item in profiles] == ["GEN-1"]
    assert controlled_library.DEPRESS_LIBRARY_METADATA["status"] == (
        "controlled-index-loaded"
    )
    assert controlled_library.DEPRESS_LIBRARY_METADATA["source"] == (
        "tenant-private-s3"
    )
    assert controlled_library.DEPRESS_LIBRARY_METADATA["tenant_id"] == "tenant-a"
    assert body.closed_by_loader is True
    monkeypatch.delenv(controlled_library.DEPRESS_INDEX_S3_ENV)
    controlled_library.load_depress_profiles()


def test_s3_profile_index_is_bounded_and_body_is_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Body(io.BytesIO):
        closed_by_loader = False

        def close(self) -> None:
            self.closed_by_loader = True
            super().close()

    body = Body(b"{}")
    fake_client = SimpleNamespace(
        get_object=lambda **_: {
            "Body": body,
            "ContentLength": controlled_library.MAX_DEPRESS_INDEX_BYTES + 1,
        }
    )
    monkeypatch.setitem(
        sys.modules,
        "boto3",
        SimpleNamespace(client=lambda _: fake_client),
    )
    monkeypatch.delenv(controlled_library.DEPRESS_INDEX_ENV, raising=False)
    monkeypatch.setenv(
        controlled_library.DEPRESS_INDEX_S3_ENV,
        "s3://private-bucket/tenant-a/profiles.json",
    )
    monkeypatch.setenv(controlled_library.TENANT_ID_ENV, "tenant-a")

    with pytest.raises(ValueError, match="exceeds the size limit"):
        controlled_library.load_depress_profiles()

    assert body.closed_by_loader is True


def test_local_profile_index_rejects_oversize_file(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "oversize-profiles.json"
    path.write_bytes(b"x" * (controlled_library.MAX_DEPRESS_INDEX_BYTES + 1))
    monkeypatch.setenv(controlled_library.DEPRESS_INDEX_ENV, str(path))
    monkeypatch.delenv(controlled_library.DEPRESS_INDEX_S3_ENV, raising=False)
    monkeypatch.setenv(controlled_library.TENANT_ID_ENV, "tenant-a")

    with pytest.raises(ValueError, match="exceeds the size limit"):
        controlled_library.load_depress_profiles()


def test_s3_profile_index_read_limit_rejects_unreported_oversize_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Body(io.BytesIO):
        read_amount: int | None = None
        closed_by_loader = False

        def read(self, amount: int = -1) -> bytes:
            self.read_amount = amount
            return super().read(amount)

        def close(self) -> None:
            self.closed_by_loader = True
            super().close()

    body = Body(b"x" * (controlled_library.MAX_DEPRESS_INDEX_BYTES + 1))
    fake_client = SimpleNamespace(
        get_object=lambda **_: {
            "Body": body,
        }
    )
    monkeypatch.setitem(
        sys.modules,
        "boto3",
        SimpleNamespace(client=lambda _: fake_client),
    )
    monkeypatch.delenv(controlled_library.DEPRESS_INDEX_ENV, raising=False)
    monkeypatch.setenv(
        controlled_library.DEPRESS_INDEX_S3_ENV,
        "s3://private-bucket/tenant-a/profiles.json",
    )
    monkeypatch.setenv(controlled_library.TENANT_ID_ENV, "tenant-a")

    with pytest.raises(ValueError, match="exceeds the size limit"):
        controlled_library.load_depress_profiles()

    assert body.read_amount == controlled_library.MAX_DEPRESS_INDEX_BYTES + 1
    assert body.closed_by_loader is True


def test_fallback_profile_candidate_remains_review_required(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    waypoints = [
        _wp("START", 0, 90, "DCT"),
        _wp("HIGH", 10, 120, "DCT", star=True),
        _wp("END", 20, 90, "DCT"),
    ]
    monkeypatch.setattr(
        engines,
        "DEPRESS_PROFILES",
        [
            {
                "chart": "GEN-1",
                "from": "START",
                "to": "HIGH",
                "from_aliases": ["START"],
                "to_aliases": ["HIGH"],
                "airways": ["DCT"],
                "critical": "HIGH",
                "critical_aliases": ["HIGH"],
                "effectivity": ["ALL"],
            }
        ],
    )
    monkeypatch.setattr(
        engines,
        "DEPRESS_LIBRARY_METADATA",
        {
            "title": "Controlled profile library",
            "issue_date": "2026-01-01",
            "status": "controlled-source-not-mounted",
        },
    )
    flight = _flight(waypoints)

    findings, _ = analyse(flight)
    profile = next(
        item for item in findings if item["engine"] == "depressurisation"
    )

    assert profile["severity"] == "unknown"
    assert profile["data"]["terrain_event_id"].startswith("terrain:")
    assert "controlled profile index unavailable" in profile["summary"].lower()


def test_missing_controlled_profile_index_is_explicit_when_no_candidate_matches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    waypoints = [
        _wp("START", 0, 90, "DCT"),
        _wp("HIGH", 10, 120, "DCT", star=True),
        _wp("END", 20, 90, "DCT"),
    ]
    monkeypatch.setattr(engines, "DEPRESS_PROFILES", [])
    monkeypatch.setattr(
        engines,
        "DEPRESS_LIBRARY_METADATA",
        {
            "title": "Controlled profile library",
            "issue_date": "2026-01-01",
            "status": "controlled-source-not-mounted",
        },
    )

    findings, _ = analyse(_flight(waypoints))
    results = [
        item for item in findings if item["engine"] == "depressurisation"
    ]
    result = next(
        item
        for item in results
        if item["data"].get("terrain_event_id") == "terrain:HIGH@10-HIGH@10"
    )

    assert result["severity"] == "unknown"
    assert result["summary"] == (
        "No exact profile confirmed because the controlled profile index is "
        "unavailable - manual review required."
    )
    assert result["data"]["confirmed"] is False
    assert result["data"]["coverage_complete"] is False
    assert result["data"]["controlled_index_loaded"] is False
    assert result["data"]["reference_status"] == "unavailable"
    assert result["data"]["first_high_waypoint"] == "HIGH"
    assert result["data"]["last_high_waypoint"] == "HIGH"
    assert result["data"]["profile_context_start_waypoint"] == "START"
    assert result["data"]["threshold_drop_waypoint"] == "END"
    assert result["data"]["start_actm_minutes"] == 10
    assert result["data"]["end_actm_minutes"] == 20
    global_result = next(
        item
        for item in results
        if not item["data"].get("terrain_event_id")
    )
    assert global_result["data"]["reference_status"] == (
        "controlled-source-not-mounted"
    )
    assert global_result["data"]["terrain_event_ids"] == [
        "terrain:HIGH@10-HIGH@10"
    ]


def test_loaded_partial_index_emits_one_unmatched_result_per_terrain_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    waypoints = [
        _wp("START", 0, 90, "DCT"),
        _wp("HIGH1", 10, 120, "DCT", star=True),
        _wp("MIDDLE", 20, 90, "DCT"),
        _wp("HIGH2", 30, 130, "DCT", star=True),
        _wp("END", 40, 90, "DCT"),
    ]
    monkeypatch.setattr(
        engines,
        "DEPRESS_PROFILES",
        [
            {
                "chart": "GEN-1",
                "from": "START",
                "to": "HIGH1",
                "from_aliases": ["START"],
                "to_aliases": ["HIGH1"],
                "airways": ["DCT"],
                "critical": "HIGH1",
                "critical_aliases": ["HIGH1"],
                "effectivity": ["ALL"],
            }
        ],
    )
    monkeypatch.setattr(
        engines,
        "DEPRESS_LIBRARY_METADATA",
        {
            "title": "Controlled partial profile library",
            "issue_date": "2026-06-12",
            "status": "controlled-index-loaded",
            "coverage_scope": "partial_issue",
        },
    )

    events = detect_terrain_events(waypoints)
    findings, _ = analyse(_flight(waypoints))
    profile_findings = [
        item for item in findings if item["engine"] == "depressurisation"
    ]
    unmatched = [
        item
        for item in profile_findings
        if item["data"].get("confirmed") is False
    ]

    assert any(
        item["data"].get("terrain_event_id") == events[0]["terrain_event_id"]
        and item["data"].get("chart_number") == "GEN-1"
        for item in profile_findings
    )
    assert [item["data"]["terrain_event_id"] for item in unmatched] == [
        events[1]["terrain_event_id"]
    ]
    assert unmatched[0]["summary"] == (
        "No exact profile confirmed from controlled partial issue - "
        "manual review required."
    )
    data = unmatched[0]["data"]
    assert data["confirmed"] is False
    assert data["coverage_complete"] is False
    assert data["reference_status"] == "partial"
    assert data["controlled_library_status"] == "controlled-index-loaded"
    assert data["controlled_index_loaded"] is True
    assert data["coverage_scope"] == "partial_issue"
    assert data["candidate_chart_numbers"] == []
    assert data["start_actm_minutes"] == 30
    assert data["end_actm_minutes"] == 40
    assert data["profile_context_start_waypoint"] == "MIDDLE"
    assert data["first_high_waypoint"] == "HIGH2"
    assert data["last_high_waypoint"] == "HIGH2"
    assert data["threshold_drop_waypoint"] == "END"


def test_sq24_high_msa_uses_minimal_profile_chain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    waypoints = [
        _wp("HAMND", 682, 72, "A590"),
        _wp("TED", 698, 129, "DCT", star=True),
        _wp("GKN", 714, 157, "J511", star=True),
        _wp("ORT", 726, 190, "J124", star=True),
        _wp("63N40", 732, 76, "DCT"),
        _wp("63N30", 764, 111, "DCT", star=True),
        _wp("62N20", 797, 111, "DCT", star=True),
        _wp("59N10", 837, 48, "DCT"),
    ]
    monkeypatch.setattr(
        engines,
        "DEPRESS_PROFILES",
        [
            {
                "chart": "11-4",
                "from": "HAMND",
                "to": "TED",
                "from_aliases": ["HAMND"],
                "to_aliases": ["TED"],
                "airways": ["DCT"],
                "critical": "HAMND",
                "critical_aliases": ["HAMND"],
                "effectivity": ["A350-941", "ULR"],
            },
            {
                "chart": "11-37",
                "from": "TED",
                "to": "62N20",
                "from_aliases": ["TED"],
                "to_aliases": ["62N20", "62N120W"],
                "airways": ["J511", "J124", "DCT"],
                "critical": "ORT",
                "critical_aliases": ["ORT"],
                "effectivity": ["A350-941", "ULR"],
            },
        ],
    )
    events = detect_terrain_events(waypoints)
    matches = match_profiles(
        {
            "aircraft_type": "A350-941",
            "registration": "9V-SGE",
            "route_waypoints": waypoints,
        },
        events,
    )
    # v1.3: coverage is judged against the actual exposure legs (first to
    # last high waypoint). The approach leg before TED is route context, so
    # the minimal chain is 11-37 alone for each exposure window; 11-4 would
    # be a redundant chart and must not be added.
    assert [item["profile"]["chart"] for item in matches] == [
        "11-37",
        "11-37",
    ]
    assert len({item["terrain_event_id"] for item in matches}) == 2
    assert all(item["coverage_complete"] for item in matches)

from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
from datetime import datetime
import re
from typing import Any, Iterable


_FILENAME_RE = re.compile(r"^[A-Z0-9]+_[0-9]{2}[A-Z]{3}[0-9]{4}_Flight_Briefing\.pdf$")
_PROHIBITED_TERMS = (
    "level 1",
    "level 2",
    "pertinent brief",
    "pertinent briefing",
    "evidence level",
    "evidence brief",
)
_REQUIRED_RELEASE_CHECKS = (
    "airport_card_geometry",
    "decision_gate_links",
    "source_crops",
    "fact_deduplication",
    "hazard_completeness",
    "source_link_integrity",
    "visual_preflight",
)
_REQUIRED_HAZARD_FIELDS = (
    "product_type",
    "issuer",
    "issue_time_utc",
    "valid_from_utc",
    "valid_to_utc",
    "phenomenon",
    "observation_status",
    "intensity",
    "position",
    "vertical_extent",
    "movement",
    "trend",
    "route_relationship",
    "time_relationship",
    "level_relationship",
    "operational_consequence",
    "classification",
    "reason_codes",
    "source_id",
)
_ALLOWED_HAZARD_CLASSIFICATIONS = {
    "SIGNIFICANT",
    "RELEVANT",
    "MONITOR",
    "NOT_PROMOTED",
}
_REQUIRED_SOURCE_CROP_FIELDS = (
    "category",
    "source_document",
    "source_revision_or_effective_date",
    "source_reference",
    "source_page",
    "crop_box",
    "embedded",
    "link_target",
)
_CORE_PAGE1_ITEMS = (
    "flight_identity",
    "route_and_runway",
    "schedule_and_block_time",
    "aircraft_type_and_registration",
    "distance_and_cruise_component",
    "burnoff_and_statistical_contingency",
    "preferred_alternate_and_weather",
    "planned_masses",
    "flight_plan_requirement",
    "fuel_in_tanks",
    "excess_fuel_and_allocation",
)


class FlightBriefingPublicationError(RuntimeError):
    """Raised when a combined Flight Briefing fails a mandatory release gate."""

    def __init__(self, violations: list[dict[str, str]]):
        super().__init__(
            "Flight Briefing publication gate failed: "
            + "; ".join(item["message"] for item in violations)
        )
        self.violations = violations


def _text(value: Any) -> str:
    return str(value or "").strip()


def _normalised_category(value: Any) -> str:
    return re.sub(r"\s+", " ", _text(value).upper().replace("_", "/")).strip()


def _violation(
    violations: list[dict[str, str]],
    code: str,
    location: str,
    message: str,
) -> None:
    violations.append({"code": code, "location": location, "message": message})


def _parse_flight_date(value: Any) -> datetime:
    text = _text(value).upper().replace("/", " ").replace("-", " ")
    text = " ".join(text.split())
    for pattern in ("%d %b %Y", "%d%b%Y", "%Y %m %d", "%d %m %Y"):
        try:
            return datetime.strptime(text, pattern)
        except ValueError:
            continue
    raise ValueError(f"Unsupported flight date: {value!r}")


def build_flight_briefing_filename(flight: dict[str, Any]) -> str:
    """Return the current-facing mobile-readable Flight Briefing filename."""
    flight_number = re.sub(r"[^A-Z0-9]", "", _text(flight.get("flight_number")).upper())
    if not flight_number:
        raise ValueError("flight_number is required for the Flight Briefing filename")
    date_token = _parse_flight_date(flight.get("flight_date")).strftime("%d%b%Y").upper()
    return f"{flight_number}_{date_token}_Flight_Briefing.pdf"


def _stable_finding_id(finding: dict[str, Any]) -> str:
    explicit = _text(finding.get("finding_id") or finding.get("id"))
    if explicit:
        return explicit
    data = finding.get("data") or {}
    source = _text(data.get("source_id") or finding.get("source_id"))
    return "|".join(
        part
        for part in (
            _text(finding.get("engine")).casefold(),
            _text(finding.get("title")).casefold(),
            source.casefold(),
        )
        if part
    )


def deduplicate_findings_for_combined_report(
    findings: Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Keep one primary finding while merging source/detail support.

    The function never changes deterministic values. It only prevents the same
    finding from being published as multiple primary statements in the combined
    report. Source IDs and additional evidence are retained on the first record.
    """
    deduplicated: list[dict[str, Any]] = []
    by_id: dict[str, dict[str, Any]] = {}
    for source_finding in findings:
        finding = deepcopy(source_finding)
        finding_id = _stable_finding_id(finding)
        if not finding_id:
            deduplicated.append(finding)
            continue
        existing = by_id.get(finding_id)
        if existing is None:
            finding["finding_id"] = finding_id
            finding["duplicate_count"] = 0
            finding["source_ids"] = list(
                dict.fromkeys(
                    _text(value)
                    for value in (
                        finding.get("source_ids")
                        or [
                            (finding.get("data") or {}).get("source_id"),
                            finding.get("source_id"),
                        ]
                    )
                    if _text(value)
                )
            )
            by_id[finding_id] = finding
            deduplicated.append(finding)
            continue

        existing["duplicate_count"] = int(existing.get("duplicate_count") or 0) + 1
        details = list(existing.get("details") or [])
        details.extend(
            detail
            for detail in (finding.get("details") or [])
            if detail not in details
        )
        existing["details"] = details
        source_ids = list(existing.get("source_ids") or [])
        for source_id in (
            list(finding.get("source_ids") or [])
            + [
                (finding.get("data") or {}).get("source_id"),
                finding.get("source_id"),
            ]
        ):
            value = _text(source_id)
            if value and value not in source_ids:
                source_ids.append(value)
        existing["source_ids"] = source_ids
    return deduplicated


def applicable_decision_gate_categories(
    flight: dict[str, Any],
    findings: Iterable[dict[str, Any]],
) -> set[str]:
    engines = {_text(item.get("engine")).casefold() for item in findings}
    categories: set[str] = set()
    if "bobcat" in engines or flight.get("bobcat"):
        categories.add("BOBCAT")
    edto = flight.get("edto") or {}
    if "edto" in engines or edto.get("entry_actm_minutes") is not None:
        categories.add("EDTO")
    if engines.intersection({"mel", "cdl", "cddl"}):
        categories.add("MEL/CDL")
    if engines.intersection({"terrain", "depressurisation", "vws"}):
        categories.add("TERRAIN/DEPRESS")
    if engines.intersection({"weather", "vaa", "tropical_cyclone", "hazard"}):
        categories.add("SIGMET/HAZARDS")
    if "notam" in engines or flight.get("departure") or flight.get("destination"):
        categories.add("AIRPORTS")
    if "performance" in engines:
        categories.add("PERFORMANCE/FUEL")
    if "communications" in engines:
        categories.add("FIR/COMMUNICATIONS")
    return categories


def required_source_crop_categories(
    flight: dict[str, Any],
    findings: Iterable[dict[str, Any]],
) -> set[str]:
    findings_list = list(findings)
    engines = {_text(item.get("engine")).casefold() for item in findings_list}
    required: set[str] = set()
    if engines.intersection({"mel", "cdl", "cddl"}):
        required.add("MEL/CDL")
    edto = flight.get("edto") or {}
    if "edto" in engines or edto.get("entry_actm_minutes") is not None:
        required.add("EDTO")
    if any(
        item.get("engine") == "depressurisation"
        and _text((item.get("data") or {}).get("chart_number"))
        for item in findings_list
    ):
        required.add("DEPRESSURISATION")
    return required


def build_combined_report_plan(
    flight: dict[str, Any],
    findings: Iterable[dict[str, Any]],
) -> dict[str, Any]:
    """Build the deterministic section and evidence-destination plan.

    This is a renderer contract, not an aviation calculation. Findings are
    deduplicated without changing their values or applicability.
    """
    prepared = deduplicate_findings_for_combined_report(findings)
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for finding in prepared:
        grouped[_text(finding.get("engine")).casefold()].append(finding)

    section_plan = [
        {"id": "flight_overview", "title": "FLIGHT BRIEFING", "engines": ["page1"]},
        {"id": "evidence_performance_fuel", "title": "PERFORMANCE / FUEL", "engines": ["performance"]},
        {"id": "evidence_mel_cdl", "title": "MEL / CDL / CDDL", "engines": ["mel", "cdl", "cddl"]},
        {"id": "evidence_airports", "title": "AIRPORTS / NOTAM", "engines": ["notam"]},
        {"id": "evidence_edto", "title": "EDTO / ALTERNATES", "engines": ["edto"]},
        {"id": "evidence_communications", "title": "BOBCAT / FIR COMMUNICATIONS", "engines": ["bobcat", "communications", "actual_timing"]},
        {"id": "evidence_hazards", "title": "OPERATIONAL HAZARD ASSESSMENT", "engines": ["weather", "vaa", "tropical_cyclone", "hazard"]},
        {"id": "evidence_terrain_depressurisation", "title": "HIGH TERRAIN / DEPRESSURISATION", "engines": ["terrain", "vws", "depressurisation"]},
        {"id": "source_crops", "title": "AUTHORITATIVE SOURCE CROPS", "engines": []},
    ]

    sections: list[dict[str, Any]] = []
    for section in section_plan:
        section_findings = [
            item
            for engine in section["engines"]
            for item in grouped.get(engine, [])
        ]
        if section["id"] not in {"flight_overview", "source_crops"} and not section_findings:
            continue
        sections.append({**section, "findings": section_findings})

    return {
        "protocol_version": "1.3.0",
        "filename": build_flight_briefing_filename(flight),
        "sections": sections,
        "evidence_destinations": [section["id"] for section in sections],
        "decision_gate_categories": sorted(
            applicable_decision_gate_categories(flight, prepared)
        ),
        "required_source_crop_categories": sorted(
            required_source_crop_categories(flight, prepared)
        ),
        "findings": prepared,
    }


def _collect_user_facing_text(manifest: dict[str, Any]) -> list[str]:
    report = manifest.get("report") or {}
    values: list[str] = [
        _text(report.get("title")),
        _text(report.get("filename")),
    ]
    values.extend(_text(value) for value in (report.get("section_titles") or []))
    values.extend(_text(value) for value in (report.get("user_facing_text") or []))
    values.extend(_text(item.get("label")) for item in (manifest.get("decision_gates") or []))
    return [value for value in values if value]


def _numeric(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _crop_box_valid(value: Any) -> bool:
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        return False
    numbers = [_numeric(item) for item in value]
    if any(item is None for item in numbers):
        return False
    x0, y0, x1, y1 = (float(item) for item in numbers if item is not None)
    return x1 > x0 and y1 > y0


def _matched_profile_numbers(findings: Iterable[dict[str, Any]]) -> set[str]:
    return {
        _text((item.get("data") or {}).get("chart_number"))
        for item in findings
        if item.get("engine") == "depressurisation"
        and _text((item.get("data") or {}).get("chart_number"))
    }


def validate_flight_briefing_publication(
    flight: dict[str, Any],
    findings: Iterable[dict[str, Any]],
    manifest: dict[str, Any],
) -> list[dict[str, str]]:
    """Validate the v1.3 combined Flight Briefing publication contract.

    The gate validates presentation, source and evidence integrity. It does not
    recalculate any aviation value.
    """
    findings_list = list(findings)
    violations: list[dict[str, str]] = []
    report = manifest.get("report") or {}
    layout = manifest.get("layout") or {}
    page1 = layout.get("page1") or {}

    if _text(manifest.get("protocol_version")) != "1.3.0":
        _violation(
            violations,
            "PROTOCOL_VERSION_INVALID",
            "protocol_version",
            "The combined Flight Briefing must use publication protocol 1.3.0.",
        )

    if _text(report.get("mode")).casefold() != "combined":
        _violation(
            violations,
            "REPORT_MODE_NOT_COMBINED",
            "report.mode",
            "The primary pilot-facing report must be one combined Flight Briefing.",
        )

    filename = _text(report.get("filename"))
    if not _FILENAME_RE.fullmatch(filename):
        _violation(
            violations,
            "FLIGHT_BRIEFING_FILENAME_INVALID",
            "report.filename",
            "Filename must be <FLIGHT>_<DDMMMYYYY>_Flight_Briefing.pdf.",
        )
    else:
        try:
            expected_filename = build_flight_briefing_filename(flight)
        except ValueError as exc:
            _violation(
                violations,
                "FLIGHT_IDENTITY_INCOMPLETE",
                "flight",
                str(exc),
            )
        else:
            if filename != expected_filename:
                _violation(
                    violations,
                    "FLIGHT_BRIEFING_FILENAME_MISMATCH",
                    "report.filename",
                    f"Expected {expected_filename}; received {filename}.",
                )

    for value in _collect_user_facing_text(manifest):
        lower = value.casefold()
        for term in _PROHIBITED_TERMS:
            if term in lower:
                _violation(
                    violations,
                    "PROHIBITED_REPORT_TERMINOLOGY",
                    "report.user_facing_text",
                    f"Remove prohibited current-facing term: {term}.",
                )

    if report.get("full_cfp_appended") is not False:
        _violation(
            violations,
            "FULL_CFP_APPENDED",
            "report.full_cfp_appended",
            "The complete CFP must not be appended to the Flight Briefing.",
        )
    if report.get("full_cfp_embedded") is True:
        _violation(
            violations,
            "FULL_CFP_EMBEDDED",
            "report.full_cfp_embedded",
            "The complete CFP must not be embedded in the Flight Briefing.",
        )
    attachments = report.get("embedded_files") or []
    if any(
        _text(item.get("type") if isinstance(item, dict) else item).casefold()
        in {"cfp", "full_cfp", "lido_cfp"}
        for item in attachments
    ):
        _violation(
            violations,
            "FULL_CFP_ATTACHMENT_PRESENT",
            "report.embedded_files",
            "The complete CFP must not be attached to the primary report.",
        )

    if _text(page1.get("information_side")).casefold() != "left":
        _violation(
            violations,
            "PAGE1_INFORMATION_SIDE_INVALID",
            "layout.page1.information_side",
            "Page 1 operational information must be on the left.",
        )
    if _text(page1.get("map_side")).casefold() != "right":
        _violation(
            violations,
            "PAGE1_MAP_SIDE_INVALID",
            "layout.page1.map_side",
            "The whole-flight route map must be on the right.",
        )

    cards = page1.get("airport_cards") or []
    cards_by_role = {
        _text(card.get("role")).casefold(): card
        for card in cards
        if isinstance(card, dict)
    }
    for role in ("departure", "destination", "alternate"):
        if role not in cards_by_role:
            _violation(
                violations,
                "AIRPORT_CARD_MISSING",
                f"layout.page1.airport_cards.{role}",
                f"Page 1 requires an equal-size {role} card.",
            )
    selected_cards = [cards_by_role[role] for role in ("departure", "destination", "alternate") if role in cards_by_role]
    if len(selected_cards) == 3:
        widths = [_numeric(card.get("width")) for card in selected_cards]
        heights = [_numeric(card.get("height")) for card in selected_cards]
        if any(value is None for value in widths + heights):
            _violation(
                violations,
                "AIRPORT_CARD_GEOMETRY_MISSING",
                "layout.page1.airport_cards",
                "Airport card width and height must be recorded.",
            )
        else:
            numeric_widths = [float(value) for value in widths if value is not None]
            numeric_heights = [float(value) for value in heights if value is not None]
            if max(numeric_widths) - min(numeric_widths) > 0.5 or max(numeric_heights) - min(numeric_heights) > 0.5:
                _violation(
                    violations,
                    "AIRPORT_CARD_GEOMETRY_UNEQUAL",
                    "layout.page1.airport_cards",
                    "Departure, Destination and Alternate cards must have equal dimensions.",
                )
        horizontal = {_text(card.get("horizontal_alignment")).casefold() for card in selected_cards}
        vertical = {_text(card.get("vertical_alignment")).casefold() for card in selected_cards}
        if len(horizontal) != 1 or "" in horizontal:
            _violation(
                violations,
                "AIRPORT_CARD_HORIZONTAL_ALIGNMENT_INCONSISTENT",
                "layout.page1.airport_cards",
                "Airport cards must use one consistent horizontal text alignment.",
            )
        if vertical != {"middle"}:
            _violation(
                violations,
                "AIRPORT_CARD_VERTICAL_ALIGNMENT_INVALID",
                "layout.page1.airport_cards",
                "Airport card text blocks must be vertically middle-aligned.",
            )

    font_scale = _numeric(layout.get("detail_font_scale"))
    if font_scale is None or font_scale < 1.2:
        _violation(
            violations,
            "DETAIL_FONT_SCALE_TOO_SMALL",
            "layout.detail_font_scale",
            "Detailed content must be enlarged by at least 20 percent.",
        )
    for field in ("minimum_detail_font_pt", "minimum_numeric_font_pt"):
        value = _numeric(layout.get(field))
        if value is None or value < 8.4:
            _violation(
                violations,
                "MINIMUM_FONT_SIZE_TOO_SMALL",
                f"layout.{field}",
                f"{field} must be at least 8.4 pt.",
            )

    if int(layout.get("text_overlap_count") or 0) != 0:
        _violation(
            violations,
            "TEXT_OVERLAP_DETECTED",
            "layout.text_overlap_count",
            "Any detected text overlap blocks publication.",
        )
    if int(layout.get("clipped_text_count") or 0) != 0:
        _violation(
            violations,
            "TEXT_CLIPPING_DETECTED",
            "layout.clipped_text_count",
            "Any clipped text blocks publication.",
        )

    logo = page1.get("logo") or {}
    if logo.get("uses_x_mark") is not False:
        _violation(
            violations,
            "PILOTDRIVEN_X_LOGO_PROHIBITED",
            "layout.page1.logo.uses_x_mark",
            "The PilotDriven logo must not use an X or crossed-line mark.",
        )
    if not _text(logo.get("asset_id")) or not _text(logo.get("asset_hash")):
        _violation(
            violations,
            "PILOTDRIVEN_LOGO_PROVENANCE_MISSING",
            "layout.page1.logo",
            "The approved logo asset ID and hash are required.",
        )

    page1_items = manifest.get("page1_critical_items") or {}
    required_page1_items = set(_CORE_PAGE1_ITEMS)
    engines = {_text(item.get("engine")).casefold() for item in findings_list}
    if engines.intersection({"mel", "cdl", "cddl"}):
        required_page1_items.add("mel_cdl_cddl")
    if flight.get("bobcat") or "bobcat" in engines:
        required_page1_items.add("flow_allocation_when_present")
    for item in sorted(required_page1_items):
        if page1_items.get(item) is not True:
            _violation(
                violations,
                "PAGE1_CRITICAL_ITEM_MISSING",
                f"page1_critical_items.{item}",
                f"Page 1 critical-item coverage is incomplete: {item}.",
            )

    evidence_destinations = {
        _text(value) for value in (manifest.get("evidence_destinations") or []) if _text(value)
    }
    gates = manifest.get("decision_gates") or []
    gate_by_category = {
        _normalised_category(item.get("category")): item
        for item in gates
        if isinstance(item, dict)
    }
    for gate in gates:
        label = _text(gate.get("label"))
        if re.search(r"\bTECH\b", label, flags=re.IGNORECASE):
            _violation(
                violations,
                "TECH_LABEL_PROHIBITED",
                "decision_gates.label",
                "Use MEL/CDL instead of TECH.",
            )
    for category in sorted(applicable_decision_gate_categories(flight, findings_list)):
        gate = gate_by_category.get(category)
        if gate is None:
            _violation(
                violations,
                "DECISION_GATE_MISSING",
                f"decision_gates.{category}",
                f"Missing applicable Page 1 decision gate: {category}.",
            )
            continue
        target = _text(gate.get("target"))
        if not target or gate.get("link_resolves") is not True or target not in evidence_destinations:
            _violation(
                violations,
                "DECISION_GATE_LINK_INVALID",
                f"decision_gates.{category}.target",
                f"Decision gate {category} must resolve to its evidence destination.",
            )

    crops = manifest.get("source_crops") or []
    crops_by_category: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for index, crop in enumerate(crops):
        if not isinstance(crop, dict):
            _violation(
                violations,
                "SOURCE_CROP_INVALID",
                f"source_crops[{index}]",
                "Each source crop must be a structured record.",
            )
            continue
        category = _normalised_category(crop.get("category"))
        crops_by_category[category].append(crop)
        for field in _REQUIRED_SOURCE_CROP_FIELDS:
            if field == "embedded":
                if crop.get(field) is not True:
                    _violation(
                        violations,
                        "SOURCE_CROP_NOT_EMBEDDED",
                        f"source_crops[{index}].{field}",
                        f"Source crop {category or index} must be embedded.",
                    )
            elif field == "crop_box":
                if not _crop_box_valid(crop.get(field)):
                    _violation(
                        violations,
                        "SOURCE_CROP_BOX_INVALID",
                        f"source_crops[{index}].crop_box",
                        "Source crop box must contain four ordered numeric coordinates.",
                    )
            elif not _text(crop.get(field)):
                _violation(
                    violations,
                    "SOURCE_CROP_PROVENANCE_INCOMPLETE",
                    f"source_crops[{index}].{field}",
                    f"Source crop {category or index} requires {field}.",
                )
        target = _text(crop.get("link_target"))
        if target and target not in evidence_destinations:
            _violation(
                violations,
                "SOURCE_CROP_LINK_TARGET_MISSING",
                f"source_crops[{index}].link_target",
                f"Source crop target {target} is not a report destination.",
            )

    for category in sorted(required_source_crop_categories(flight, findings_list)):
        if not crops_by_category.get(category):
            _violation(
                violations,
                "REQUIRED_SOURCE_CROP_MISSING",
                f"source_crops.{category}",
                f"A cropped authoritative {category} source section is required.",
            )

    matched_profiles = _matched_profile_numbers(findings_list)
    profile_artifacts = {
        _text(item.get("chart_number")): item
        for item in (flight.get("depressurisation_profile_charts") or [])
        if isinstance(item, dict) and _text(item.get("chart_number"))
    }
    for chart_number in sorted(matched_profiles):
        artifact = profile_artifacts.get(chart_number)
        if artifact is None:
            _violation(
                violations,
                "DEPRESSURISATION_PROFILE_ARTIFACT_MISSING",
                f"depressurisation_profile_charts.{chart_number}",
                f"Matched profile {chart_number} has no registered chart artifact.",
            )
            continue
        for field in (
            "route_airway_match_verified",
            "aircraft_effectivity_verified",
            "chart_image_validated",
            "combined_analysis_chart_embedded",
            "combined_cropped_source_chart_embedded",
        ):
            if artifact.get(field) is not True:
                _violation(
                    violations,
                    "DEPRESSURISATION_PROFILE_VALIDATION_INCOMPLETE",
                    f"depressurisation_profile_charts.{chart_number}.{field}",
                    f"Matched profile {chart_number} requires {field}=true.",
                )
        for field in ("source_document", "source_revision", "source_page", "source_link", "crop_box"):
            if field == "crop_box":
                valid = _crop_box_valid(artifact.get(field))
            else:
                valid = bool(_text(artifact.get(field)))
            if not valid:
                _violation(
                    violations,
                    "DEPRESSURISATION_PROFILE_SOURCE_INCOMPLETE",
                    f"depressurisation_profile_charts.{chart_number}.{field}",
                    f"Matched profile {chart_number} requires {field}.",
                )

    fact_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for index, fact in enumerate(manifest.get("facts") or []):
        if not isinstance(fact, dict) or not _text(fact.get("fact_id")):
            _violation(
                violations,
                "FACT_ID_MISSING",
                f"facts[{index}]",
                "Every tracked material fact requires a stable fact_id.",
            )
            continue
        fact_groups[_text(fact.get("fact_id"))].append(fact)
    for fact_id, records in fact_groups.items():
        primary_records = [record for record in records if record.get("primary") is True]
        if len(primary_records) != 1:
            _violation(
                violations,
                "FACT_PRIMARY_LOCATION_INVALID",
                f"facts.{fact_id}",
                f"Fact {fact_id} must have exactly one primary display location.",
            )
        for record in records:
            if not _text(record.get("location")):
                _violation(
                    violations,
                    "FACT_LOCATION_MISSING",
                    f"facts.{fact_id}.location",
                    f"Fact {fact_id} requires a report location.",
                )

    hazard = manifest.get("hazard_assessment") or {}
    if hazard.get("nil_inference") is not False:
        _violation(
            violations,
            "HAZARD_NIL_INFERENCE_INVALID",
            "hazard_assessment.nil_inference",
            "Missing hazard coverage must never be interpreted as NIL.",
        )
    reviewed = hazard.get("products_reviewed") or []
    gaps = hazard.get("coverage_gaps") or []
    hazard_findings = hazard.get("findings") or []
    if not reviewed and not gaps:
        _violation(
            violations,
            "HAZARD_COVERAGE_MANIFEST_EMPTY",
            "hazard_assessment",
            "Every CFP requires reviewed products or explicit coverage gaps.",
        )
    for index, gap in enumerate(gaps):
        if not isinstance(gap, dict) or not _text(gap.get("product_class")) or not _text(gap.get("reason")):
            _violation(
                violations,
                "HAZARD_COVERAGE_GAP_INCOMPLETE",
                f"hazard_assessment.coverage_gaps[{index}]",
                "Coverage gaps require product_class and reason.",
            )
        if isinstance(gap, dict) and gap.get("interpreted_as_nil") is not False:
            _violation(
                violations,
                "HAZARD_COVERAGE_GAP_INTERPRETED_AS_NIL",
                f"hazard_assessment.coverage_gaps[{index}].interpreted_as_nil",
                "A coverage gap must explicitly record interpreted_as_nil=false.",
            )
    for index, finding in enumerate(hazard_findings):
        if not isinstance(finding, dict):
            _violation(
                violations,
                "HAZARD_FINDING_INVALID",
                f"hazard_assessment.findings[{index}]",
                "Hazard findings must be structured records.",
            )
            continue
        for field in _REQUIRED_HAZARD_FIELDS:
            value = finding.get(field)
            if field == "reason_codes":
                valid = isinstance(value, list) and bool(value)
            else:
                valid = bool(_text(value)) if not isinstance(value, (dict, list)) else bool(value)
            if not valid:
                _violation(
                    violations,
                    "HAZARD_FINDING_FIELD_MISSING",
                    f"hazard_assessment.findings[{index}].{field}",
                    f"Hazard finding requires {field}.",
                )
        classification = _text(finding.get("classification")).upper()
        if classification not in _ALLOWED_HAZARD_CLASSIFICATIONS:
            _violation(
                violations,
                "HAZARD_CLASSIFICATION_INVALID",
                f"hazard_assessment.findings[{index}].classification",
                "Coverage gaps are separate; findings must use a supported hazard classification.",
            )

    release_checks = manifest.get("release_checks") or {}
    for check in _REQUIRED_RELEASE_CHECKS:
        if release_checks.get(check) is not True:
            _violation(
                violations,
                "RELEASE_CHECK_NOT_PASSED",
                f"release_checks.{check}",
                f"Mandatory release check not passed: {check}.",
            )

    if violations:
        raise FlightBriefingPublicationError(violations)
    return []


__all__ = [
    "FlightBriefingPublicationError",
    "applicable_decision_gate_categories",
    "build_combined_report_plan",
    "build_flight_briefing_filename",
    "deduplicate_findings_for_combined_report",
    "required_source_crop_categories",
    "validate_flight_briefing_publication",
]

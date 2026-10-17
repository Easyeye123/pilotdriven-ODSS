from __future__ import annotations

import os
import re
from datetime import datetime, timedelta, timezone
from typing import Any

from .constants import (
    COMMUNICATION_RULES,
    MEL_REFERENCES,
    REFERENCE_LIBRARY_METADATA,
    edto_sectors,
    format_actm,
    format_kg,
)

from .controlled_library import (
    CDL_LIBRARY_METADATA,
    CDL_REFERENCES,
    DEPRESS_LIBRARY_METADATA,
    DEPRESS_PROFILES,
    normalized_registration,
    resolve_aircraft_effectivity,
    aircraft_effectivity_tokens,
    select_cdl_variants,
)
from .deferred_dispatch import (
    deferred_item_type_for_display,
    deferred_reference_for_display,
    deferred_source_declaration_for_display,
)
from .pilot_briefing import (
    _IAP_COMPETING_PROCEDURE,
    concise_weather_finding,
    iap_minima_changes,
    notam_pertinence,
    retired_taxiway_lighting_summary,
    notam_sort_key,
    pilot_notam_key,
)
from .runway_closure_schedule import reconcile_runway_closure_findings
from .notam_timing import (
    NOTAM_TIMING_RULES,
    decide_notice_timing,
    notice_timing_input,
    parse_schedule_field,
    schedule_occurrences,
    shared_station_window,
)
from .airport_taxi_consequences import (
    bounded_taxiway_extents,
    is_prose_word,
    taxiway_closure_items,
    taxiway_designation_scope,
)
from .notam_restriction_line import (
    FIXED_MARKER_SENTENCES,
    derive_notam_restriction_line,
)
from .reviewed_publications import reviewed_publication_for_notam
from .report_facts import required_operational_reference_times
from .weather_timing import select_taf_for_window, summarize_metar_for_window, summarize_taf_for_window

_INSTRUMENT_APPROACH_ADVERSE = re.compile(
    r"\b(?:U/S|UNSERVICEAB(?:LE|ILITY)|NOT\s+(?:AVBL|AVAILABLE|"
    r"AUTHORI[ZS]ED|MONITORED)|CLSD|CLOSED|SUSPENDED|INOP(?:ERATIVE)?|"
    r"OUT\s+OF\s+(?:SERVICE|SVC)|UNRELIABLE|INTERRUPT(?:S|ED|ING|ION|IONS)?|"
    r"INTRP|"
    r"OSCILLAT(?:E|ES|ED|ING|ION|IONS)|DEGRAD(?:ED|ATION)|DOWNGRADED|"
    r"NOT\s+OPERATIONAL|WITHDRAWN|UNUSABLE|UNAVAILABLE|UNREL|NA|"
    r"DO\s+NOT\s+USE|SHOULD\s+NOT\s+BE\s+FLOWN)\b"
)
_INSTRUMENT_APPROACH_AVAILABLE = re.compile(
    r"(?<!NOT )\b(?:AVBL|AVAILABLE|SERVICEABLE|OPERATIONAL)\b|"
    r"\bIN\s+SERVICE\b"
)
_APPROACH_RUNWAY_REFERENCE = (
    r"(?:RWY|RUNWAY)\s*\d{1,2}[LCR]?(?:/\d{1,2}[LCR]?)?"
)
_APPROACH_CATEGORY_QUALIFIER = (
    r"CAT\s*(?:I{1,3}|[123])(?:\s*/\s*(?:I{1,3}|[123]))*"
)
_APPROACH_EQUIPMENT_COMPONENT = (
    r"(?:ILS|LOC(?:ALIZER|ALISER)?|LLZ|GP|GLIDE\s*(?:PATH|SLOPE)|"
    r"GLIDEPATH|GLIDESLOPE|GLS|GBAS)"
)
_APPROACH_EQUIPMENT_NAME = (
    rf"(?:{_APPROACH_EQUIPMENT_COMPONENT}"
    rf"(?:\s*(?:/|\s)\s*{_APPROACH_EQUIPMENT_COMPONENT})*|"
    r"(?:ILS|LOC(?:ALIZER|ALISER)?|LLZ)\s*(?:/|\s)\s*DME)"
)
_APPROACH_EQUIPMENT_IDENT = (
    r"(?:['\"][A-Z]{2,5}['\"]|"
    rf"(?!{_INSTRUMENT_APPROACH_ADVERSE.pattern})"
    rf"(?!{_INSTRUMENT_APPROACH_AVAILABLE.pattern})"
    r"(?!RWY\s*\d|RUNWAY\s*\d|CAT\b|FREQ\b|FREQUENCY\b|BC\b|"
    r"ILS\b|LOC(?:ALIZER|ALISER)?\b|LLZ\b|GP\b|GLIDE\b|GLS\b|GBAS\b|"
    r"DME\b|VOR\b|NDB\b|RNAV\b|RNP\b|PAPI\b|"
    r"IM\b|MM\b|OM\b|"
    r"LGT(?:S)?\b|LIGHT(?:S|ING)?\b|CRANES?\b|OBST(?:ACLES?)?\b)"
    r"(?!NOT\b)"
    r"[A-Z]{2,5}\b)"
)
_APPROACH_PREFIX_IDENT = (
    r"(?:['\"][A-Z]{2,5}['\"]|"
    r"I[A-Z]{2,4}(?=\s+(?:FREQ(?:UENCY)?\b|\d|RWY\b|RUNWAY\b|CAT\b))|"
    r"[A-Z]{2}(?=\s+(?:FREQ(?:UENCY)?\b|\d)))"
)
_APPROACH_FREQUENCY = (
    r"(?:(?:FREQ(?:UENCY)?\s*)?\d{2,3}(?:\.\d{1,3})?(?:\s*MHZ)?)"
)
_APPROACH_TECHNICAL_DETAIL = (
    rf"(?:LOC(?:ALIZER|ALISER)?|LLZ|GP|GLIDE\s*(?:PATH|SLOPE)|DME)"
    rf"(?:\s+(?:IDENT\s+)?{_APPROACH_EQUIPMENT_IDENT})?"
    rf"(?:\s+{_APPROACH_FREQUENCY})?"
    r"(?:\s+CH\d{1,3}[XY]?)?"
)
_APPROACH_TECHNICAL_COMPOSITION = (
    rf"\(\s*{_APPROACH_TECHNICAL_DETAIL}"
    rf"(?:\s*,\s*{_APPROACH_TECHNICAL_DETAIL}){{1,4}}\s*\)"
)
_INSTRUMENT_APPROACH_MARKER = re.compile(
    rf"\b(?:"
    rf"ILS(?:\s+{_APPROACH_RUNWAY_REFERENCE})?\s*(?:/|\s)\s*"
    rf"(?:IM|MM|OM)(?:\s+{_APPROACH_RUNWAY_REFERENCE})?|"
    rf"(?:IM|MM|OM)\s*\(\s*ILS"
    rf"(?:\s+{_APPROACH_EQUIPMENT_IDENT})?\s*\)"
    rf"(?:\s+{_APPROACH_RUNWAY_REFERENCE})?|"
    rf"I-[A-Z]{{2,5}}\s+(?:INNER|MIDDLE|OUTER)\s+MARKER|"
    rf"ILS(?:\s+{_APPROACH_RUNWAY_REFERENCE})?\s+"
    rf"(?:INNER|MIDDLE|OUTER)\s+MARKER|"
    rf"(?:INNER|MIDDLE|OUTER)\s+MARKER\s*\(\s*ILS"
    rf"(?:\s+I-[A-Z]{{2,5}})?\s*\)(?:\s+{_APPROACH_RUNWAY_REFERENCE})?|"
    rf"(?:INNER|MIDDLE|OUTER)\s+MARKER"
    rf"(?:\s+{_APPROACH_RUNWAY_REFERENCE})?"
    rf")(?=\s|$)(?:\s+{_APPROACH_FREQUENCY})?"
)
_DIRECT_INSTRUMENT_APPROACH_EQUIPMENT = re.compile(
    rf"\b{_APPROACH_EQUIPMENT_NAME}"
    r"(?![A-Z0-9])"
    rf"(?:\s+{_APPROACH_PREFIX_IDENT})?"
    rf"(?:\s+{_APPROACH_FREQUENCY})?"
    r"(?:\s+[XYZ])?"
    rf"(?:\s+{_APPROACH_CATEGORY_QUALIFIER})?"
    rf"(?:\s+(?:FOR\s+)?{_APPROACH_RUNWAY_REFERENCE}"
    rf"(?:\s*(?:AND|/)\s*{_APPROACH_RUNWAY_REFERENCE})?)?"
    rf"(?:\s+{_APPROACH_CATEGORY_QUALIFIER})?"
    rf"(?:\s+{_APPROACH_FREQUENCY})?"
    rf"(?:\s+(?:IDENT\s+{_APPROACH_EQUIPMENT_IDENT}|I[A-Z]{{2,4}})"
    r"(?=\s+(?:FREQ(?:UENCY)?\b|\d|\()))?"
    rf"(?:\s+{_APPROACH_FREQUENCY})?"
    rf"(?:\s*{_APPROACH_TECHNICAL_COMPOSITION})?"
    r"(?:\s+(?:GP|BC))?"
)
_EXPLICIT_INSTRUMENT_APPROACH_PROCEDURE = re.compile(
    r"\b(?:APCH|APPROACH)(?!\s+(?:LGT(?:S)?|LIGHT(?:S|ING)?))\b|\bIAP\b"
)
_RNAV_INSTRUMENT_APPROACH_PROCEDURE = re.compile(
    r"(?:\b(?:RNAV|RNP)(?:\s*\([A-Z0-9 ]+\))?(?:\s+AR)?\s+"
    r"(?:[XYZ]\s+)?(?:APCH|APPROACH|IAP|RWY(?:\s*\d{1,2}[LCR]?)?)\b|"
    r"\b(?:APCH|APPROACH|IAP)\s+(?:RNAV|RNP)\b)"
)
_NAMED_INSTRUMENT_APPROACH_PROCEDURE = re.compile(
    r"\b(?:IAC\s+(?:(?:ILS|LOC|VOR|NDB|RNAV|RNP)\s*/\s*)*"
    r"(?:ILS|LOC|VOR|NDB|RNAV|RNP)\s+PROCEDURES?|"
    r"(?:ILS|LOC|VOR|NDB|RNAV|RNP)\s+"
    rf"{_APPROACH_RUNWAY_REFERENCE}\s+PROC(?:EDURE)?S?)\b"
)
_NUMBERED_IAC_APPROACH_PROCEDURE = re.compile(
    rf"\bIAC\s+[A-Z0-9-]+\s+(?:ILS|LOC|VOR|NDB|RNAV|RNP)"
    r"(?:\s*\([A-Z0-9 ]+\))?(?:\s+[WXYZ])?\s+"
    rf"{_APPROACH_RUNWAY_REFERENCE}"
    rf"(?:\s+{_APPROACH_CATEGORY_QUALIFIER})?"
    r"(?:\s+DATED\s+\d{2}\s+[A-Z]{3}\s+\d{4})?\b"
)
_IAC_APPROACH_PROCEDURE_LIST = re.compile(
    r"\bIAC(?:-[A-Z0-9]+)?\b"
    r"(?:(?!\b(?:SID|STAR)\b).){0,600}"
    r"\b(?:ILS|LOC|VOR|NDB|RNAV|RNP)\b"
    r"(?:(?!\b(?:SID|STAR)\b).){0,600}\bPROCEDURES?\b"
)
_LPV_APPROACH_PROCEDURE = re.compile(
    rf"\bLPV\s+APCH(?:\s+RNP)?(?:\s+[XYZ])?\s+"
    rf"{_APPROACH_RUNWAY_REFERENCE}\b"
)
_ILS_LOC_APPROACH_PROCEDURE = re.compile(
    rf"\b(?:ILS\s+(?:AND|OR)\s+LOC|LOC\s+(?:AND|OR)\s+ILS)\s+"
    rf"APCH(?:\s+{_APPROACH_RUNWAY_REFERENCE})?(?:\s+TEMPO(?:RARY)?)?\b"
)
_PUBLISHED_ILS_LOC_PROCEDURE = re.compile(
    rf"\bPROC(?:EDURE)?\s+(?:ILS\s+(?:AND|OR)\s+LOC|"
    rf"LOC\s+(?:AND|OR)\s+ILS)\s+{_APPROACH_RUNWAY_REFERENCE}"
    rf"(?:\s+TEMPO(?:RARY)?)?\b"
)
_ILS_FINAL_DME_READING = re.compile(
    rf"\b(?:[A-Z]{{2,5}}\s+)?DME\s+READINGS?\s+ON\s+"
    rf"(?:ILS/LOC|LOC/ILS)\s+{_APPROACH_RUNWAY_REFERENCE}\s+FINAL\b"
)
_ILS_CATEGORY_PROCEDURE = re.compile(
    rf"\b(?:PROC(?:EDURE)?\s+)?ILS\s+{_APPROACH_RUNWAY_REFERENCE}\s+"
    r"CAT\s+(?:I{1,3}|[123])(?:\s+AND\s+(?:I{1,3}|[123]))?"
    r"(?:\s+PROC(?:EDURE)?)?\b"
)
_ILS_SPECIAL_AUTH_CATEGORY = re.compile(
    rf"\bILS\s+{_APPROACH_RUNWAY_REFERENCE}\s+SPECIAL\s+AUTH\s+"
    rf"{_APPROACH_CATEGORY_QUALIFIER}\b"
)
_IAP_PUBLICATION_ADVERSE = re.compile(
    rf"\bIAP\b(?:(?!\b{_IAP_COMPETING_PROCEDURE}\b).){{0,650}}"
    r"\b(?:ILS|LOC|VOR|NDB|RNAV|RNP)\b"
    rf"(?:(?!\b{_IAP_COMPETING_PROCEDURE}\b).){{0,650}}"
    r"\b(?:PROCEDURE\s+NA|"
    r"S-(?:ILS|LOC)\s+(?:RWY\s*)?\d{1,2}[LCR]?\s+CAT\s+"
    r"(?:I{1,3}|[123])(?:\s+AND\s+(?:I{1,3}|[123]))?\s+NA)\b"
)
_IAP_CLAUSE_SUSPENSION = re.compile(
    rf"\bIAP\b(?:(?!\b{_IAP_COMPETING_PROCEDURE}\b).){{0,500}}"
    r"\b(?:ILS|LOC|VOR|NDB|RNAV|RNP)\b"
    rf"(?:(?!\b{_IAP_COMPETING_PROCEDURE}\b).){{0,350}}"
    r"(?<!NOT\s)\b(?:SUSPENDED|WITHDRAWN)\b"
)
_CATEGORY_APPROACH_OPERATIONS = re.compile(
    rf"\b(?:{_APPROACH_RUNWAY_REFERENCE}\s+"
    rf"{_APPROACH_CATEGORY_QUALIFIER}\s+(?:OPS|OPERATIONS)|"
    rf"{_APPROACH_CATEGORY_QUALIFIER}\s+(?:OPS|OPERATIONS)\s+"
    rf"{_APPROACH_RUNWAY_REFERENCE}|"
    rf"{_APPROACH_CATEGORY_QUALIFIER}\s+(?:OPS|OPERATIONS))\b"
)
_CONVENTIONAL_APPROACH_NAVAID = re.compile(
    r"\b(?:VOR(?:/DME)?|NDB|DME)\b"
    rf"(?:\s+{_APPROACH_RUNWAY_REFERENCE}|"
    rf"\s+(?!(?:RWY|RUNWAY|NOT)\b)"
    rf"(?!{_INSTRUMENT_APPROACH_ADVERSE.pattern})"
    rf"(?!{_INSTRUMENT_APPROACH_AVAILABLE.pattern})"
    r"(?:['\"][A-Z]{2,12}(?:/[A-Z]{2,12})?['\"]|"
    r"[A-Z]{2,12}(?:/[A-Z]{2,12})?\b))?"
    r"(?:\s+(?:\d{2,4}(?:\.\d{1,3})?\s*(?:KHZ|MHZ)|CH\d{1,3}[XY]?))?"
)
_APPROACH_PROCEDURE_CATEGORY = re.compile(
    r"(?:\b(?:APPROACH|APCH)\s+PROCEDURE\b|\bIAP\b)"
)
_PAPI = re.compile(r"\bPAPI\b")
_PAPI_OPERATIONAL_SUBJECT = re.compile(
    rf"\bPAPI(?:\s+(?:LEFT|RIGHT)\s+SIDE)?"
    rf"(?:\s+{_APPROACH_RUNWAY_REFERENCE})?\b"
)
_APPROACH_LIGHT_AVAILABLE = re.compile(r"\b(?:AVBL|AVAILABLE)\b")
_APPROACH_RESTORATION_OTHER_SUBJECT = re.compile(
    r"\b(?:PAPI|(?:APCH|APPROACH)\s+(?:LGT(?:S)?|LIGHT(?:S|ING)?)|"
    r"(?:TWY|TAXIWAY)(?:\s+[A-Z0-9-]+)?|"
    r"(?:RWY|RUNWAY)(?:\s*\d{1,2}[LCR]?)?"
    r"(?:\s+LIGHT(?:S|ING)?)?)\b"
)
_APPROACH_BINDING_TOKEN = re.compile(r"[A-Z0-9]+(?:/[A-Z0-9]+)?")
_APPROACH_BINDING_SURFACE_SUBJECT = re.compile(
    r"\b(?:TWY|TAXIWAY|APRON|STAND|PAPI|LGT(?:S)?|LIGHT(?:S|ING)?|"
    r"CRANES?|OBST(?:ACLES?)?)\b"
)
_RNAV_OR_RNP = re.compile(r"\b(?:RNAV|RNP)\b")
_APPROACH_NON_ADVERSE_ACTIVITY = re.compile(
    r"\b(?:FLIGHT\s+CHECK|CALIBRAT(?:E|ED|ING|ION)|"
    r"SIGNAL\s+MONITOR(?:ED|ING)?|TEST(?:ED|ING)?)\b"
)
_APPROACH_RESTORATION = re.compile(
    r"\b(?:CANCELLED|CANCELED|REVOKED|RESTORED)\b|"
    r"\b(?:NOW|THEN)\s+(?:AVBL|AVAILABLE|OPERATIONAL|SERVICEABLE)\b|"
    r"\b(?:RESTORED|RETURNED)\s+TO\s+SERVICE\b"
)
_APPROACH_RESTORATION_CONNECTOR = re.compile(
    r"^\s*[,.;:\-]?\s*(?:(?:THIS\s+)?(?:CONDITION|NOTICE|NOTAM)"
    r"(?:\s+(?:IS|HEREBY))?|(?:HAS|HAVE)\s+BEEN|"
    r"UNTIL\s+\d{4}(?:UTC|Z)?)?\s*[,.;:\-]?\s*$"
)
_NEGATED_RESTORATION_PREFIX = re.compile(
    r"\bNOT(?:\s+(?:YET|CURRENTLY))?\s*$"
)
_NO_APPROACH_OPERATIONS = re.compile(
    r"\bNO\s+(?:INSTRUMENT\s+)?(?:APCH(?:ES)?|APPROACH(?:ES)?)\b"
    r".{0,120}\b(?:TAKE\s+PLACE|PERMITTED|AUTHORI[ZS]ED|ALLOWED)\b"
)


def _conditional_instrument_approach_impact(text: str) -> bool:
    """True when the adverse approach state depends on an unresolved WHEN.

    The impact remains critical evidence, but it must be presented as a
    condition review rather than an unconditional active outage.
    """

    normalized = " ".join(str(text or "").upper().split())
    for adverse in _NO_APPROACH_OPERATIONS.finditer(normalized):
        if re.match(r"\s+WHEN\b", normalized[adverse.end():]):
            return True
    return False
_APPROACH_MINIMA_RAISED = re.compile(
    r"\b(?:LPV|LNAV(?:/VNAV)?|RNP|RNAV)\s+MINIMA\s+"
    r"(?:SHALL\s+BE\s+)?(?:RAISED|INCREASED)\b"
    r"(?:\s+TO\s+(?:LPV|LNAV(?:/VNAV)?|RNP|RNAV)\s+MINIMA)?"
)
_FORWARD_APPROACH_STATE_BINDING = re.compile(
    rf"^\s*(?:{_APPROACH_CATEGORY_QUALIFIER}\s+)?"
    rf"(?:{_APPROACH_RUNWAY_REFERENCE}"
    rf"(?:\s*(?:AND|/)\s*{_APPROACH_RUNWAY_REFERENCE})?\s*)?"
    rf"(?:{_APPROACH_CATEGORY_QUALIFIER}\s*)?"
    r"(?:(?:PROC(?:EDURE)?S?|OPS|OPERATIONS)\s*)?"
    r"(?:COMPLETELY\s+)?"
    r"(?:(?:IS|ARE|MAY|WILL|CAN)(?:\s+BE)?|"
    r"HAS\s+BEEN|HAVE\s+BEEN|SUBJ(?:ECT)?\s+TO)?\s*[,/:\-]?\s*$"
)
_REVERSE_APPROACH_STATE_BINDING = re.compile(
    r"^\s*(?:(?:OF|IN|FOR|AFFECTING)\s*)?$"
)
_NEGATED_ADVERSE_PREFIX = re.compile(
    r"(?:\bWITHOUT|\bNO|\bNOT)(?:\s+[A-Z0-9/-]+){0,5}\s*$"
)
_MAX_APPROACH_BINDING_TOKENS = 12


def finding(
    engine: str,
    severity: str,
    title: str,
    summary: str,
    details: list[str] | None = None,
    data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "rule_id": f"{engine.upper()}-AUTO",
        "engine": engine,
        "severity": severity,
        "title": title,
        "summary": summary,
        "details": details or [],
        "data": data or {},
    }


def _cfp_source_reference(
    flight: dict[str, Any],
    pages: list[int | None],
    section: str,
) -> dict[str, Any]:
    return {
        "source_type": "uploaded_cfp",
        "document_title": flight.get("document_id") or "Uploaded OFP",
        "display_title": "Uploaded company OFP",
        "pages": sorted(
            {
                int(page)
                for page in pages
                if isinstance(page, int) and page > 0
            }
        ),
        "section": section,
    }


def _weather_source_reference(
    flight: dict[str, Any],
    record: dict[str, Any],
) -> dict[str, Any]:
    page = record.get("source_page")
    if isinstance(page, int) and page > 0:
        return _cfp_source_reference(
            flight,
            [page],
            "Airport weather list",
        )
    return {
        "source_type": record.get("source") or "official_weather",
        "provider": record.get("provider"),
        "display_title": (
            "NOAA Aviation Weather Center"
            if record.get("provider") == "noaa-awc-data-api"
            else None
        ),
        "source_url": record.get("source_url"),
        "retrieved_at_utc": record.get("retrieved_at_utc"),
        "observed_at_utc": record.get("observed_at_utc"),
        "issued_at_utc": record.get("issue_time_utc"),
        "valid_from_utc": record.get("valid_from_utc"),
        "valid_to_utc": record.get("valid_to_utc"),
    }


def _alternate_row_not_read_finding(row: dict[str, Any]) -> tuple[dict[str, Any], str]:
    """A row printed in an alternate table that the parser did not read: a stated review, never an absence."""
    edto = row.get("table") == "edto_alternates"
    # QA512: the FUEL ENROUTE AIRPORT station row is held the same way when it does not read.
    fuel_enroute = row.get("table") == "fuel_enroute_airports"
    airport = str(row.get("airport") or "").strip().upper() or None
    page = row.get("source_page")
    where = f"OFP p{int(page)}" if isinstance(page, int) and not isinstance(page, bool) else "The OFP"
    kind = "EDTO alternate" if edto else "fuel-enroute airport" if fuel_enroute else "planned alternate"
    analysis = (
        "EDTO checked-period" if edto else "fuel-enroute NOTAM or weather" if fuel_enroute else "NOTAM, weather or fuel"
    )
    printed = str(row.get("text") or "").strip()
    # QA512: a row held for a cell that breaks a table-cell rule names that cell.
    fields = [str(field) for field in row.get("invalid_fields") or [] if str(field).strip()]
    invalid = f" ({', '.join(fields)} not valid)" if fields else ""
    # QA504-01: a line inside the table whose airport cannot be read is held as printed; no airport is named for it.
    summary = (
        f'{where} prints {kind} {airport}, but its row was not read{invalid}: "{printed}". '
        f"{airport} has no {analysis} analysis here; read it from the OFP."
        if airport
        else f'{where} prints a line in its {kind} table that was not read{invalid}: "{printed}". '
        f"The {kind} it belongs to has no {analysis} analysis here; read it from the OFP."
    )
    return finding(
        "edto" if edto else "qa",
        "warning",
        "EDTO alternate row not read" if edto
        else "Fuel-enroute airport row not read" if fuel_enroute
        else "Planned alternate row not read",
        summary,
        [str(row.get("reason") or "").strip()] if row.get("reason") else [],
        {
            "airport": airport,
            "table": row.get("table"),
            "source_page": page,
            "text": row.get("text"),
            "source_references": [{
                "source_type": "uploaded_cfp",
                "pages": [int(page)] if isinstance(page, int) and not isinstance(page, bool) else [],
                "section": (
                    "EDTO ENROUTE ALTN AIRPORTS" if edto
                    else "FUEL ENROUTE AIRPORT" if fuel_enroute
                    else "FLT PLANNING ALTN SUMMARY"
                ),
            }],
        },
    ), summary


def _official_weather_review_finding(
    review: dict[str, Any],
) -> dict[str, Any] | None:
    """Surface official-source gaps as weather, never as an invisible ledger."""
    if review.get("status") == "complete":
        return None
    reason_codes = list(review.get("reason_codes") or ["coverage_not_confirmed"])
    human_reasons = {
        "source_disabled": "The official public METAR/TAF connector is disabled.",
        "unsupported_source": "The configured weather source is not approved by this connector.",
        "airport_identifiers_unavailable": "The airport identifiers needed for the public weather lookup are unavailable.",
        "source_unavailable": "The official public METAR/TAF source was unavailable.",
        "source_stale": "The official public METAR/TAF receipt expired and was not used.",
        "essential_forecast_missing": "A departure or destination TAF is missing.",
        "station_product_missing": "One or more requested station products are missing.",
        "essential_forecast_window_not_covered": "A departure or destination TAF does not cover the operating window.",
        "forecast_window_not_covered": "A requested station TAF does not cover its operating window.",
        "coverage_not_confirmed": "Official public weather coverage was not confirmed.",
    }
    products = review.get("products") or {}
    references: list[dict[str, Any]] = []
    for product_name in ("METAR", "TAF"):
        product = products.get(product_name) or {}
        if not product:
            continue
        references.append({
            "source_type": "official_weather",
            "provider": review.get("provider"),
            "display_title": "NOAA Aviation Weather Center",
            "section": product_name,
            "source_url": product.get("source_url"),
            "retrieved_at_utc": product.get("retrieved_at_utc"),
            "valid_from_utc": product.get("effective_start_utc"),
            "valid_to_utc": product.get("effective_end_utc"),
            "availability_status": "source-incomplete",
        })
    return finding(
        "weather",
        "unknown",
        "Official weather coverage incomplete",
        "Official public METAR/TAF coverage is incomplete.",
        [
            *(human_reasons.get(code, code.replace("_", " ").capitalize() + ".") for code in reason_codes),
            "Missing, expired or non-covering weather is not a no-significant-weather result.",
        ],
        {
            "phase": "Flight",
            "location": "",
            "utc_window": "Official source coverage check",
            "mechanism": "; ".join(human_reasons.get(code, code.replace("_", " ")) for code in reason_codes),
            "flight_effect": "Flight effect not assessed: official public weather coverage is incomplete.",
            "window_status": "review_required",
            "window_status_text": "Official public weather coverage is incomplete.",
            "provider": review.get("provider"),
            "reason_codes": reason_codes,
            "source_references": references,
        },
    )


# Hazard reviews share one deterministic route x time x flight-level evaluator,
# so they also share one finding shape. Only the wording differs.
_HAZARD_REVIEWS = (
    {
        "review_key": "sigmet_review",
        "engine": "sigmet",
        "affected_title": "SIGMET affects the planned route",
        "review_title": "SIGMET coverage incomplete",
        "review_summary": (
            "The official source could not fully cover the flight window."
        ),
        "record_phrase": "SIGMET",
        "cfp_phrase": "SIGMET",
        "negative_claim": "no SIGMET",
        "unresolved_warning": "SIGMET applicability remains unresolved.",
    },
    {
        "review_key": "vaa_review",
        "engine": "vaa",
        "affected_title": "Volcanic ash affects the planned route",
        "review_title": "Volcanic ash applicability unresolved",
        # R2 residual (24 Sep 2026): a state, not "confirm that ..." prose.
        "review_summary": (
            "The official sources do not establish that volcanic ash "
            "is not applicable to the route."
        ),
        "record_phrase": "volcanic-ash",
        "cfp_phrase": "volcanic-ash",
        "negative_claim": "no volcanic ash",
        "unresolved_warning": "Volcanic ash applicability remains unresolved.",
    },
    {
        "review_key": "tropical_cyclone_review",
        "engine": "tropical_cyclone",
        "affected_title": "Tropical cyclone affects the planned route",
        "review_title": "Tropical cyclone applicability unresolved",
        "review_summary": (
            "The official sources do not establish that a tropical "
            "cyclone is not applicable to the route."
        ),
        "record_phrase": "tropical-cyclone",
        "cfp_phrase": "tropical-cyclone",
        "negative_claim": "no tropical cyclone",
        "unresolved_warning": "Tropical cyclone applicability remains unresolved.",
    },
)


def _hazard_review_findings(
    review: dict[str, Any],
    hazard: dict[str, str],
) -> tuple[list[dict[str, Any]], list[str]]:
    """Build findings for one hazard review without interpreting the hazard."""
    track_context = (
        review.get("track_context") or {}
        if hazard["engine"] == "tropical_cyclone"
        else {}
    )

    def source_references() -> list[dict[str, Any]]:
        snapshot = review.get("source_snapshot") or {}
        provider = review.get("provider") or snapshot.get("provider")
        if not provider:
            return []
        return [{
            "source_type": "official_advisory",
            "provider": provider,
            "retrieved_at_utc": (
                review.get("retrieved_at_utc")
                or snapshot.get("retrieved_at_utc")
            ),
            "valid_from_utc": (
                snapshot.get("effective_start_utc")
                or snapshot.get("coverage_start_utc")
            ),
            "valid_to_utc": (
                snapshot.get("effective_end_utc")
                or snapshot.get("coverage_end_utc")
            ),
            "availability_status": (
                "source-incomplete"
                if review.get("status") == "review_required"
                else "available"
            ),
        }]

    def track_details() -> list[str]:
        details: list[str] = []
        # QA516: every tracked cyclone is described (the details stopped at three, with no count).
        for cyclone in track_context.get("cyclones") or []:
            movement = cyclone.get("movement") or {}
            closest = cyclone.get("closest_route_screening") or {}
            if movement:
                details.append(
                    f"{cyclone.get('name') or cyclone.get('cyclone_id') or 'Cyclone'} "
                    f"centre movement: {movement.get('bearing_degrees')}° at "
                    f"{movement.get('speed_knots')} kt, based on official timed positions."
                )
            if closest:
                details.append(
                    f"Centre-track screening: {closest.get('distance_nm')} NM from "
                    f"{closest.get('route_from')}-{closest.get('route_to')} at "
                    f"{closest.get('time_utc')}; deterministic interpolation, not an official "
                    "hazard boundary."
                )
        if track_context.get("status") == "review_required":
            details.append(
                "Official tropical-cyclone centre-track context was unavailable; "
                "review the responsible meteorological authority."
            )
        return details

    status = review.get("status")
    if status == "affected":
        matches = review.get("matches") or []
        first_match = matches[0] if matches else {}
        details = [
            (
                f"{item.get('hazard_code') or 'SIGMET'} "
                f"{item.get('advisory_id')}: {item.get('route_from')}-"
                f"{item.get('route_to')} at FL{item.get('planned_flight_level')}, "
                f"{item.get('segment_start_utc')} to {item.get('segment_end_utc')}."
            )
            for item in matches[:8]
        ]
        details.append(
            "Boundary contact is treated as an intersection; verify the "
            "original advisory and dispatch guidance."
        )
        details.extend(track_details())
        return [finding(
            hazard["engine"],
            "critical",
            hazard["affected_title"],
            f"{len(matches)} route/time/flight-level intersection(s) verified.",
            details,
            {
                "status": "affected",
                "start_actm_minutes": first_match.get("start_actm_minutes"),
                "match_count": len(matches),
                "provider": review.get("provider"),
                "reason_codes": review.get("reason_codes") or [],
                "source_references": source_references(),
            },
        )], []

    if status != "review_required":
        return [], []
    if review.get("clean_current_feed_no_match"):
        return [], []

    reason_codes = review.get("reason_codes") or []
    human_reasons = {
        "source_unavailable": "The official live source was unavailable.",
        "source_stale": "The source snapshot did not meet the configured freshness limit.",
        "source_records_incomplete": (
            f"Some official {hazard['record_phrase']} records could not be read "
            "completely."
        ),
        "coverage_not_complete_for_flight": (
            "Official-source coverage is incomplete for the flight window."
        ),
        "cfp_weather_data_unavailable": (
            f"The OFP states that {hazard['cfp_phrase']} weather data is unavailable."
        ),
        "route_geometry_unavailable": "The OFP route geometry is incomplete.",
        "route_timing_unavailable": "The route timing anchor is unavailable.",
        "flight_level_unavailable": "The planned flight level could not be resolved.",
        "flight_level_change_unresolved": "A planned level-change waypoint could not be matched to the route.",
        "advisory_geometry_invalid": "An advisory geometry could not be evaluated safely.",
        "direct_vaac_advisory_source_not_mounted": (
            "The responsible VAAC advisory and VAG source is not mounted."
        ),
        "direct_vaac_advisory_source_unavailable": (
            "The configured responsible VAAC advisory source was unavailable."
        ),
        "direct_vaac_coverage_partial": (
            "The checked VAAC source does not cover every responsible VAAC for "
            "the route."
        ),
        "direct_tca_advisory_source_not_mounted": (
            "The responsible tropical-cyclone advisory and wind-field source is "
            "not mounted."
        ),
    }
    details = [human_reasons.get(code, code.replace("_", " ").capitalize() + ".") for code in reason_codes]
    details.append(
        f"Incomplete coverage is not a '{hazard['negative_claim']}' result; "
        "complete the advisory review."
    )
    details.extend(track_details())
    return [finding(
        hazard["engine"],
        "unknown",
        hazard["review_title"],
        hazard["review_summary"],
        details,
        {
            "status": "review_required",
            "provider": review.get("provider"),
            "reason_codes": reason_codes,
            "source_references": source_references(),
        },
    )], [hazard["unresolved_warning"]]


def _switch_state(value: bool | None) -> str:
    if value is True:
        return "ON"
    if value is False:
        return "OFF"
    return "not parsed"


def _reference_library_is_approved() -> bool:
    return str(REFERENCE_LIBRARY_METADATA.get("status") or "").lower() in {
        "approved",
        "approved-current",
        "current-approved",
    }


def _schedule_overlaps(
    schedule: str, window_start: datetime, window_end: datetime,
    *, valid_from: datetime | None = None, valid_to: datetime | None = None,
) -> bool | None:
    """Whether an Item D schedule has an occurrence overlapping the window; None when it cannot be read.

    ITEM 3 (14 Oct 2026): the grammar is the shared one in notam_timing_rules.json - the app reads every Item D
    by the same rules - so this is a view of that reader, kept for callers that only need overlap.
    """
    anchor_start, anchor_end = valid_from or window_start, valid_to or window_end
    validity = {"startsAt": anchor_start.isoformat(), "endsAt": anchor_end.isoformat(), "endKind": "explicit"}
    entries, error = parse_schedule_field(schedule, validity)
    if error:
        return None
    start_ms, end_ms = window_start.timestamp() * 1000, window_end.timestamp() * 1000
    occurrences = schedule_occurrences(entries, anchor_start.timestamp() * 1000,
                                       anchor_end.timestamp() * 1000 if valid_to is not None else float("inf"),
                                       start_ms, end_ms)
    return any(occurrence_start < end_ms and start_ms < occurrence_end for occurrence_start, occurrence_end in occurrences)


def _notam_role_window(
    flight: dict[str, Any],
    location: str,
    alternate_airports: set[str],
    edto_periods: dict[str, tuple[datetime, datetime]],
    fuel_enroute_airports: set[str] | None = None,
    source_role: str | None = None,
) -> tuple[str, datetime, datetime]:
    departure_utc, arrival_utc = required_operational_reference_times(flight)
    # ITEM 3 (14 Oct 2026): the departure and destination windows are the shared ones (notam_timing_rules.json,
    # +/-2h, the operator default the app has used since 25 Jul). The one-hour departure window and the per-service
    # environment overrides let the card and the PDF text leave out a closure the chart and the PDF map drew.
    if location == flight["departure"]:
        return ("departure", *shared_station_window("departure", departure_utc))
    if location == flight["destination"]:
        return ("destination", *shared_station_window("destination", arrival_utc))
    arrival_margin = timedelta(minutes=NOTAM_TIMING_RULES["stationWindows"]["destination"]["afterMinutes"])
    is_fuel_enroute = (
        source_role == "fuel_enroute_airport"
        or location in (fuel_enroute_airports or set())
    )
    windows: list[tuple[datetime, datetime]] = []
    if is_fuel_enroute:
        windows.append((departure_utc, arrival_utc))
    if location in alternate_airports:
        windows.append((
            arrival_utc - arrival_margin,
            arrival_utc + arrival_margin,
        ))
    if location in edto_periods:
        windows.append(edto_periods[location])
    if windows:
        role = (
            "fuel enroute airport"
            if is_fuel_enroute
            else "destination alternate"
            if location in alternate_airports
            else "EDTO"
        )
        return (
            role,
            min(window[0] for window in windows),
            max(window[1] for window in windows),
        )
    return "informational", departure_utc, arrival_utc



def _notam_role_windows(
    flight: dict[str, Any], location: str, alternate_airports: set[str],
    fuel_enroute_airports: set[str], source_role: str,
) -> list[tuple[str, datetime, datetime]]:
    """Keep each governed use separate; a gap between uses is not a use."""
    if location in {flight["departure"], flight["destination"]}:
        return [_notam_role_window(flight, location, set(), {})]
    windows = []
    if source_role == "fuel_enroute_airport" or location in fuel_enroute_airports:
        windows.append(_notam_role_window(flight, location, set(), {}, {location}))
    if location in alternate_airports:
        windows.append(_notam_role_window(flight, location, {location}, {}))
    for airport in flight["edto"]["airports"]:
        if airport["airport"] == location:
            window = ("EDTO", datetime.fromisoformat(airport["period_start_utc"]), datetime.fromisoformat(airport["period_end_utc"]))
            if window not in windows:
                windows.append(window)
    return windows or [_notam_role_window(flight, location, set(), {})]


def _assess_notam_window(
    record: dict[str, Any], flight: dict[str, Any], role: str,
    start: datetime, end: datetime, valid_from: datetime, valid_to: datetime,
) -> dict[str, Any]:
    """One role's assessment of a station notice: the shared decision (notam_timing.py), in this service's words.

    ITEM 3 (14 Oct 2026): the app decides the same record by the same rules for the dashboard chart, the PDF map
    marks and its NOTAM records, so the card and the PDF text cannot say "active" where the map says "review".
    ``valid_from``/``valid_to`` are kept in the signature for callers; the decision reads the record itself.
    """
    reference = _notam_reference_at(flight, role, start)
    decision = decide_notice_timing(notice_timing_input(record), {
        "startsAt": start.isoformat(), "endsAt": end.isoformat(), "referenceAt": reference.isoformat()})
    status = decision["status"]
    schedule = decision["schedule"]
    result = {
        "role": role, "window_start_utc": start.isoformat(), "window_end_utc": end.isoformat(),
        "window_label": _utc_window_label(start, end),
        "referenceAt": reference.isoformat(), "stateAtReference": decision["stateAtReference"],
        "minutesDelta": decision["minutesDelta"], "referenceInterval": decision["referenceInterval"],
        "applicability": "active", "validity_status": "overlaps_flight_window",
        "schedule_status": "overlaps_flight_window" if schedule else "not_applicable",
    }
    if status == "review":
        unreadable_validity = notice_timing_input(record)["validity"] is None
        result.update(
            applicability="review",
            validity_status="review_required" if unreadable_validity else "overlaps_flight_window",
            schedule_status="not_applicable" if unreadable_validity else "review_required",
            timing_review_reason=decision.get("reason"),
        )
    elif status == "outside_window" and decision["outsideBy"] == "validity":
        result.update(applicability="outside_time_window", validity_status="outside_time_window")
    elif status == "outside_window":
        result.update(applicability="outside_schedule", schedule_status="outside_schedule")
    return result

def _utc_window_label(window_start: datetime, window_end: datetime) -> str:
    start = window_start.astimezone(timezone.utc)
    end = window_end.astimezone(timezone.utc)
    if start.date() == end.date():
        return f"{start:%d %b %H%MZ}-{end:%H%MZ}".upper()
    return f"{start:%d %b %H%MZ}-{end:%d %b %H%MZ}".upper()


def _notam_reference_at(
    flight: dict[str, Any],
    role: str,
    window_start: datetime,
) -> datetime:
    departure_utc, arrival_utc = required_operational_reference_times(flight)
    if role == "departure":
        return departure_utc
    if role in {"destination", "destination alternate"}:
        return arrival_utc
    # EDTO windows use sector entry as their operational reference. Enroute
    # informational records use the beginning of the checked flight window.
    return window_start


def _weather_role_window(
    flight: dict[str, Any],
    location: str,
    alternate_airports: set[str],
    edto_periods: dict[str, tuple[datetime, datetime]],
    fuel_enroute_airports: set[str] | None = None,
    source_role: str | None = None,
) -> tuple[str, datetime, datetime]:
    departure_utc, arrival_utc = required_operational_reference_times(flight)
    preference = _weather_window_preference(flight)
    before = timedelta(minutes=preference["before_minutes"])
    after = timedelta(minutes=preference["after_minutes"])
    if location == flight["departure"]:
        return "Departure", departure_utc - before, departure_utc + after
    if location == flight["destination"]:
        return "Destination", arrival_utc - before, arrival_utc + after
    is_fuel_enroute = (
        source_role == "fuel_enroute_airport"
        or location in (fuel_enroute_airports or set())
    )
    windows: list[tuple[datetime, datetime]] = []
    if is_fuel_enroute:
        windows.append((departure_utc, arrival_utc))
    if location in alternate_airports:
        windows.append((arrival_utc - before, arrival_utc + after))
    if location in edto_periods:
        windows.append(edto_periods[location])
    if windows:
        phase = (
            "Fuel enroute airport"
            if is_fuel_enroute
            else "Destination alternate"
            if location in alternate_airports
            else "EDTO"
        )
        return (
            phase,
            min(window[0] for window in windows),
            max(window[1] for window in windows),
        )
    return "Enroute", departure_utc, arrival_utc


def _compact_taxiway_identifiers(identifiers: list[str]) -> list[str]:
    """Compress a published taxiway list without inventing missing members."""

    ordered_prefixes: list[str] = []
    bare: set[str] = set()
    numbers: dict[str, set[int]] = {}
    for identifier in identifiers:
        match = re.fullmatch(r"([A-Z])(\d{1,2})?", identifier)
        if not match:
            continue
        prefix, number = match.groups()
        if prefix not in ordered_prefixes:
            ordered_prefixes.append(prefix)
        if number is None:
            bare.add(prefix)
        else:
            numbers.setdefault(prefix, set()).add(int(number))

    compact: list[str] = []
    for prefix in ordered_prefixes:
        if prefix in bare:
            compact.append(prefix)
        values = sorted(numbers.get(prefix, set()))
        start = end = None
        for value in [*values, None]:
            if value is not None and start is None:
                start = end = value
                continue
            if value is not None and end is not None and value == end + 1:
                end = value
                continue
            if start is not None and end is not None:
                compact.append(
                    f"{prefix}{start}-{prefix}{end}"
                    if end > start
                    else f"{prefix}{start}"
                )
            start = end = value
    return compact


def _associated_taxiway_subject(upper: str) -> str | None:
    """Summarise a tabulated associated-taxiway closure from its actual list."""

    if not re.search(
        r"\bCLOSURE\s+OF\s+(?:TWY|TAXIWAY)\s+ASSOCIATED\s+WITH\s+(?:RWY|RUNWAY)\s*\d{1,2}[LCR]?/\d{1,2}[LCR]?\b",
        upper,
    ):
        return None
    listed = re.search(
        r"\bTWY\s+CLOSURE\s+PERIOD:.*?\b\d{4}UTC\s+"
        r"(?P<list>TWY\s+.+?)(?:\s+ALL\s+MARKINGS|\Z)",
        upper,
    )
    if not listed:
        runway = re.search(r"\b(?:RWY|RUNWAY)\s*(\d{1,2}[LCR]?/\d{1,2}[LCR]?)", upper)
        return f"listed TWYs associated with RWY {runway.group(1)}" if runway else None

    list_text = listed.group("list")
    between = re.search(
        r"\bTWY\s+([A-Z]\d{0,2})\s+BTN\s+TWY\s+([A-Z]\d{0,2})\s+([A-Z]\d{0,2})\b",
        list_text,
    )
    between_label = None
    if between:
        between_label = (
            f"{between.group(1)} between {between.group(2)} and {between.group(3)}"
        )
        list_text = f"{list_text[:between.start()]} {list_text[between.end():]}"

    identifiers: list[str] = []
    for group in re.findall(r"\bTWY\s+(.+?)(?=\s+TWY\s+|\Z)", list_text):
        identifiers.extend(re.findall(r"\b[A-Z](?:\d{1,2})?\b", group))
    compact = _compact_taxiway_identifiers(identifiers)
    if between_label:
        compact.append(between_label)
    if not compact:
        return None
    if len(compact) == 1:
        joined = compact[0]
    else:
        joined = f"{', '.join(compact[:-1])}, and {compact[-1]}"
    return f"TWYs {joined}"


# "CAT II/III OPS", "CAT 3 OPR" - the operations category a notice limits.
# Kept in the source's own numerals so no reader has to guess which categories
# the notice meant.
_APPROACH_CATEGORY_OPS = re.compile(
    r"\bCAT\s*(?P<category>(?:I{1,3}|[123])[A-C]?(?:\s*/\s*(?:I{1,3}|[123])[A-C]?)*)"
    r"\s+(?:OPS|OPR|OPERATIONS?)\b",
    re.I,
)


def _approach_category_operations(upper: str) -> str | None:
    """`CAT II/III` when the notice limits a category's operations."""
    match = _APPROACH_CATEGORY_OPS.search(upper)
    if not match:
        return None
    category = re.sub(r"\s*/\s*", "/", match.group("category").strip().upper())
    return f"CAT {category}"


# A taxiway closure names its places whole - the shared grammar in
# ``airport_taxi_consequences`` - and says what else it closes.
#
# SQ352 15 Aug 2026, EKCH A1383/26, real OFP page 36:
#
#     FOLLOWING TWY ARE CLSD DUE TO WIP:
#     TWY B BTN TWY Y AND RWY 12/30.
#     TWY Y BTN TWY B AND DEICING PLATFORM B.
#     TWY Z BTN TWY D AND DEICING PLATFORM B.
#
# The first reader here took one identifier as the end point and published
# "TWY B BETWEEN Y AND RWY" (independent live QA of release 392). Its repair
# then accepted any one word as an end point: VAAH A1134/26 became "TWY P
# between C and RAPID" (RAPID EXIT TWY R5) and KJFK A3912/26 "TWY A4 between A
# and TERMINAL 5" (TERMINAL 5 RAMP) - independent replay, 22 Sep 2026. And its
# start point had to be a taxiway, so an extent starting at a runway, a ramp,
# a taxilane or a directional taxiway was not seen at all and the fallback
# below published the partial closure as the WHOLE taxiway (WSSS A2510/26,
# "TWY Q BTN TXL Q3 AND TWY P7", became "TWY Q closed").


def _further_taxiway_extents(text: str) -> int:
    """Bounded extents this notice states beyond the first."""
    return max(0, len(bounded_taxiway_extents(text)) - 1)


def _further_closed_taxiway_items(text: str) -> str:
    """The sentence saying what else this notice closes, or "".

    The subject names one extent. A notice listing three and publishing one,
    with nothing saying so, reads as though the other two do not exist - and
    that holds for a whole taxiway or a stand-access segment listed beside the
    extents as much as for another extent. A count is stated only when every
    listed element was read.
    """
    items, exact = taxiway_closure_items(text)
    further = len(items) - 1
    if further < 1:
        return ""
    if not exact:
        return "This notice states further closed taxiway items"
    if all(form == "extent" for form, _ in items):
        return f"This notice states {further} further closed taxiway extent(s)"
    return f"This notice states {further} further closed taxiway item(s)"


def _named_taxiway_closure_items(text: str, subject: str) -> tuple[str, str] | None:
    """ITEM 4, VRMM SX5/26 (9 Oct 2026): what the card states when it would otherwise say "part of".

    David, 7 Oct: "The NOTAMS for VRMM was not highlighted at all ... You check the wordings". The card read "PART OF
    TWY C closed ... Its bounds could not be read completely" while the notice states the side and length and four
    more closed taxiways. Only a subject this reader could not bound is replaced, and only when every listed item was
    read: the first item's own scope becomes the subject and the further items are named when each is a whole
    taxiway, otherwise counted as before.
    """
    if not subject.startswith("part of "):
        return None
    items, exact = taxiway_closure_items(text)
    if not exact or not items or items[0][0] != "partial" or items[0][1].startswith("part of "):
        return None
    if items[0][1].split(" ")[:2] != subject[len("part of "):].split(" ")[:2]:
        return None
    further = items[1:]
    if not further:
        return items[0][1], ""
    kinds = {label.split(" ", 1)[0] for _, label in further}
    if all(form == "surface" for form, _ in further) and len(kinds) == 1:
        refs = [label.split(" ", 1)[1] for _, label in further]
        named = refs[0] if len(refs) == 1 else f"{', '.join(refs[:-1])} and {refs[-1]}"
        verb = "is" if len(refs) == 1 else "are"
        return items[0][1], f"{kinds.pop()} {named} {verb} also closed"
    return items[0][1], f"This notice states {len(further)} further closed taxiway item(s)"


def taxiway_closure_stated_scopes(text: str) -> list[str]:
    """The closed taxiway scopes a taxiway-closure card states, for the PDF consequence to state the same (ITEM 4).

    Codex production QA of release 460 (F3-R460): Gatwick's SX67/25 "TAXIWAY TANGO CLOSED NORTH OF TAXIWAY JULIET" was
    on the chart, the card and the PDF map, while the PDF's consequence panel held it unresolved - its taxi reader skips
    a scope that follows the verb. Malé's SX5/26 was held the same way. This returns the card's own reading: every
    named item where the card names them, else the card's one bounded subject. A subject the card could not bound
    ("part of"), a fallback subject, or further items the card can only count, give nothing - the PDF keeps saying the
    consequence is not established rather than understating it.
    """
    upper = " ".join(text.upper().split())
    subject, source = _taxiway_subject(upper)
    if _named_taxiway_closure_items(text, subject):
        return [label for _, label in taxiway_closure_items(text)[0]]
    if source == "fallback" or subject.startswith("part of ") or _further_closed_taxiway_items(text):
        return []
    return [subject]


def _taxiway_subject(upper: str, *, closure: bool = True) -> tuple[str, str]:
    """A taxiway notice's subject, and which reader named it.

    ``extent`` and ``designation`` subjects name one item of what may be a
    list; ``compound`` and ``table`` subjects already name every item. The
    partial-closure guard is for closures: a lighting or marking restriction
    on TWY F4 is not "part of TWY F4".
    """
    compound = re.search(
        r"\b(?:TWY|TAXIWAY)\s+(?P<closed>[A-Z0-9][A-Z0-9/-]*)\s+AND\s+"
        r"(?:THE\s+)?JUNCTION\s+OF\s+(?:TWY|TAXIWAY)\s+(?P=closed)[,\s]+"
        r"(?:TWY|TAXIWAY)\s+(?P<left>[A-Z0-9][A-Z0-9/-]*)\s+AND\s+"
        r"(?:TWY|TAXIWAY)\s+(?P<right>[A-Z0-9][A-Z0-9/-]*)\b",
        upper,
    )
    if compound:
        return (
            f"TWY {compound.group('closed')} and "
            f"{compound.group('closed')}/{compound.group('left')}/{compound.group('right')} junction",
            "compound",
        )
    associated = _associated_taxiway_subject(upper)
    if associated:
        return associated, "table"
    extents = bounded_taxiway_extents(upper)
    if extents and (closure or extents[0].complete):
        return extents[0].subject(), "extent"
    invalid_identifiers = {
        "AND",
        "ASSOCIATED",
        "CLSD",
        "CLOSED",
        "CLOSURE",
        "INDICATOR",
        "IS",
        "LIGHT",
        "LIGHTS",
        "MARKINGS",
        "PAVEMENT",
        "WILL",
        "WITH",
    }
    # 10 Oct 2026, genuine SQ437 WSSS SX168/26 "TEMPO CLOSURE OF TXL N4 BEHIND ACFT STAND 604 ...": the card read "PART
    # OF TWY GUIDANCE closed" - only TWY was looked for, and "TWY GUIDANCE SIGNS WILL BE MASKED OUT" made a taxiway of a
    # word. A taxilane is a designation too, and a plain word after TWY is never a name.
    for match in re.finditer(
        r"\b(?P<kind>TWY|TAXIWAY|TXL|TAXILANE)\s+(?P<identifier>[A-Z][A-Z0-9/-]*)\b",
        upper,
    ):
        identifier = match.group("identifier")
        if identifier in invalid_identifiers or is_prose_word(identifier):
            continue
        surface = "TXL" if match.group("kind") in {"TXL", "TAXILANE"} else "TWY"
        # A designation qualified by anything but its closure, a list
        # sibling or the end of its statement is a PARTIAL closure: its
        # own scope when this can read it, "part of" when it cannot, and
        # never the whole taxiway.
        partial = taxiway_designation_scope(upper, match.end(), surface, identifier) if closure else None
        if closure and partial is None:
            # WSSS SX83/24: a header list ("TEMPO CLOSURE OF TXL R1, R2, R3 ...") names what its details narrow ("TXL
            # R1 BEHIND ACFT STAND E5"). A later mention of the same designation that states a scope this can read
            # wins: a list header never widens a closure to the whole taxiway. A later mention whose qualifier is not
            # read ("JET BLAST TOWARDS TWY W1" after "TWY W1 CLSD", EBBR SX38/26) says nothing about the closure.
            for later in re.finditer(
                rf"\b(?:{match.group('kind')})\s+{re.escape(identifier)}\b", upper[match.end():],
            ):
                stated = taxiway_designation_scope(upper, match.end() + later.end(), surface, identifier)
                if stated and not stated.startswith("part of "):
                    partial = stated
                    break
        return partial or f"{surface} {identifier}", "designation"
    phonetic = re.search(r"\b([A-Z]{2,})\s+TWY\b", upper)
    turnoffs = re.search(
        r"\bHIGH-SPEED\s+TURN-OFFS?\s+([A-Z]\d{1,2})\s+AND\s+([A-Z]\d{1,2})\b",
        upper,
    )
    if phonetic and turnoffs:
        return (
            f"{phonetic.group(1).title()} TWY segment and "
            f"{turnoffs.group(1)}/{turnoffs.group(2)} high-speed turn-offs",
            "fallback",
        )
    if phonetic:
        return f"{phonetic.group(1).title()} TWY segment", "fallback"
    if turnoffs:
        return f"{turnoffs.group(1)}/{turnoffs.group(2)} high-speed turn-offs", "fallback"
    return "taxiway operational area", "fallback"


def _notam_subject(text: str, kind: str) -> str:
    upper = " ".join(text.upper().split())
    runway_pattern = r"(?:RWY|RUNWAY)\s*\d{1,2}[LCR]?(?:/\d{1,2}[LCR]?)?"
    taxiway_pattern = r"(?:TWY|TAXIWAY)\s+[A-Z0-9][A-Z0-9/-]*"
    closure_pattern = r"(?:CLSD|CLOSED|NOT\s+AVBL|NOT\s+AVAILABLE|SUSPENDED)"
    if kind == "runway_closure":
        match = (
            re.search(
                rf"\b({runway_pattern})\s+(?:WILL\s+BE\s+|IS\s+)?{closure_pattern}\b",
                upper,
            )
            or re.search(rf"\bCLOSURE\s+OF\s+({runway_pattern})\b", upper)
        )
        return match.group(1).replace("RUNWAY", "RWY") if match else "runway"
    if kind in {"runway_approach_restriction", "runway_lighting_restriction"}:
        match = re.search(rf"\b{runway_pattern}\b", upper)
        return match.group(0).replace("RUNWAY", "RWY") if match else "runway"
    if kind == "approach_navaid_closure":
        bound_subject = _bound_unavailable_approach_subject(upper)
        if bound_subject:
            return bound_subject
        # A category-limited operation is not an aid outage, and it is not the
        # whole approach either. SQ352 15 Aug 2026, EKCH A1312/26, real OFP
        # page 36: "RWY 22L CAT II/III OPS NOT AVBL DUE TO WIP." names no
        # system token, so this fell through to the literal "approach/navaid"
        # and published a broader subject than the notice states, dropping the
        # category entirely (independent live QA of release 392). Say what the
        # source says - the category, and that it is the operations that are
        # unavailable. Nothing here implies another category is available.
        category = _approach_category_operations(upper)
        if category:
            runway_named = re.search(r"\b(?:RWY|RUNWAY)\s+\d{1,2}[LCR]?\b", upper)
            scope = runway_named.group(0).replace("RUNWAY", "RWY") if runway_named else ""
            return f"{scope} {category} operations".strip()
        system = re.search(
            r"\b(?:ILS|LOC|LOCALIZER|GLIDE\s*PATH|GLIDESLOPE|DME|VOR|NDB|RNP|PAPI)\b",
            upper,
        )
        runway = re.search(r"\b(?:RWY|RUNWAY)\s+\d{1,2}[LCR]?\b", upper)
        parts = [
            system.group(0).replace("LOCALIZER", "LOC").replace("RUNWAY", "RWY")
            if system
            else "approach/navaid",
            runway.group(0).replace("RUNWAY", "RWY") if runway else "",
        ]
        return " ".join(part for part in parts if part)
    if kind in {"taxiway_closure", "taxiway_restriction"}:
        return _taxiway_subject(upper, closure=kind == "taxiway_closure")[0]
    if kind == "apron_stand_closure":
        match = re.search(
            r"\b(?:ACFT\s+STAND|STAND|APRON|APN|RAMP|GATE)\s+[A-Z0-9][A-Z0-9/-]*\b",
            upper,
        )
        return match.group(0).replace("APN", "APRON") if match else "apron or stand"
    return ""


def _approach_lights_reported_available(text: str) -> bool:
    """Accept only a same-clause, directly bound approach-light state."""

    normalized = " ".join(text.upper().split())
    for clause in re.split(r"(?:\.(?=\s|$)|;|\r?\n)+", normalized):
        subject = re.search(r"\b(?:APCH|APPROACH)\s+(?:LGT|LIGHTS?)\b", clause)
        if subject is None:
            continue
        for available in _APPROACH_LIGHT_AVAILABLE.finditer(
            clause,
            subject.end(),
        ):
            between = clause[subject.end():available.start()]
            if re.fullmatch(
                r"\s*(?:FOR\s+)?(?:RWY|RUNWAY)\s+\d{1,2}[LCR]?\s*",
                between,
            ):
                return True
    return False


_NAVAID_SUBJECT = re.compile(
    r"\b((?:ILS|LOC|LLZ|LOCALI[ZS]ER|GP|GS|GLIDE ?PATH|DVOR|VOR|DME|NDB|TACAN|RNAV|RNP|GLS|GBAS|LPV)"
    r"(?:/(?:DME|GP|LOC|NDB|VOR))?"
    r"(?:\s+(?:CAT\s+I{1,3}|\(GPS\)|[XYZ]))*)"
    r"(?:\s*'([A-Z]{2,4})')?"
    r"(?:\s*(?:RWY|RUNWAY)\s*(\d{2}[LCR]?))?"
)


_FAA_PROCEDURE_TITLE = re.compile(r"^(?P<title>.+?),\s*(?:AMDT|ORIG|CHG)\b.*$")


def _faa_procedure_line(upper: str) -> tuple[str, str]:
    """(procedure, note) for an FAA "IAP ..." notice; ("", "") for anything else.

    The notice lists one or more procedure titles with their amendment, each
    ended by "...", then the chart note. The last title and the first sentence
    of the note make the line; the note is bounded so it stays one line.
    """
    # OFP station packages may prefix the FAA text ("EST LAX IAP …"); the
    # notice starts at its IAP token.
    match = re.search(r"\bIAP\s+[^.]*\.\s*(?P<body>.+)$", upper)
    if not match:
        return "", ""
    parts = [part.strip(" ,") for part in re.split(r"\.{3}\s*", match.group("body")) if part.strip(" ,")]
    titles: list[str] = []
    notes: list[str] = []
    for part in parts:
        title = _FAA_PROCEDURE_TITLE.match(part)
        if title:
            titles.append(" ".join(title.group("title").split()))
        else:
            notes.append(part)
    if not titles or not notes:
        return "", ""
    note = re.split(r"\.\s+", notes[-1].strip())[0].rstrip(".").strip()
    if len(note) > 100:
        note = note[:97].rstrip() + "…"
    return titles[-1], note


def _navaid_clause(upper: str) -> tuple[str, str]:
    """The aid and the state a single clause states about it.

    The aid must open the clause and the state must sit in the same clause, so
    "ILS RWY 25 AVBL. PAPI RWY 25 U/S" never reads as an ILS outage and a
    negated "NOT U/S" never reads as unserviceable.
    """
    # A named PART or a preceding availability assertion starts a new
    # component clause. A coordinated list (ILS-LOC, GP, DME) stays together.
    separated = re.sub(r",\s*(?=(?:ILS|LOC|GP|GS|DVOR|VOR|DME|NDB)[ -]+PART\b)", ";", upper)
    separated = re.sub(r"\b(AVBL|AVAILABLE|U/S|UNSERVICEABLE)\s*,\s*(?=(?:ILS|LOC|GP|GS|DVOR|VOR|DME|NDB)\b)", r"\1;", separated)
    for clause in re.split(r"[.;]\s*", separated):
        clause = clause.strip(" ,")
        if not clause:
            continue
        state = _navaid_state_phrase(clause)
        if not state:
            continue
        aid = _navaid_subject(clause)
        if aid:
            return aid, state
    return "", ""


def _navaid_subject(clause: str) -> str:
    """The aid as the clause names it — "ILS CAT I RWY 06", "DVOR/DME MNL" — only when the aid opens the clause."""
    coordinated = re.match(r"^((?:ILS-LOC|ILS|LOC|GP|GS|DME|VOR|NDB)(?:,\s*(?:ILS-LOC|ILS|LOC|GP|GS|DME|VOR|NDB))+)(?:\s+FOR)?(?:\s+(RWY\s+\d{2}[LCR]?(?:\s+AND\s+RWY\s+\d{2}[LCR]?)?))?\s+(?:U/S|UNSERVICEABLE)\b", clause)
    if coordinated:
        return re.sub(r",\s*", ", ", coordinated.group(1)) + (f" {coordinated.group(2)}" if coordinated.group(2) else "")
    match = _NAVAID_SUBJECT.match(clause)
    if not match:
        return ""
    aid = " ".join(match.group(1).replace("LOCALIZER", "LOC").replace("LOCALISER", "LOC").split())
    parts = [aid]
    if re.match(r"[ -]+PART\b", clause[match.end():]):
        parts.append("PART")
    if match.group(2):
        parts.append(match.group(2))
    if match.group(3):
        parts.append(f"RWY {match.group(3)}")
    return " ".join(parts)


def _navaid_state_phrase(upper: str) -> str:
    """The state the record states, in the boss's words; empty when it states none."""
    if re.search(r"(?<!NOT )\bON\s+TEST\b", upper):
        return "on test, do not use" if re.search(r"\bDO\s+NOT\s+USE\b", upper) else "on test"
    if re.search(r"(?<!NOT )(?:\bU/S\b|\bUNSERVICEABLE\b|\bUNSERVICEABILITY\b)", upper):
        return "unserviceable"
    return ""


def notam_dashboard_line(text: str, kind: str) -> str:
    """The boss's own reading of an approach-aid record, for the dashboard card.

    Boss 02 Sep 2026: "instrument approaches being affected such as ILS or VOR
    not working, or on test or unserviceable". Names the aid, the runway and
    its state ("ILS CAT I RWY 06 on test, do not use."), or the FAA procedure
    and its note ("ILS OR LOC RWY 7R: AUTO-PILOT COUPLED APPROACH NA BELOW
    800."). Empty when the record states neither. The PDF keeps its own
    summary; this line exists for the dashboard's compact text only, so the
    approved REV3 reference is untouched.
    """
    if kind not in {"approach_navaid_closure", "runway_approach_restriction"}:
        return ""
    upper = " ".join(str(text or "").upper().split())
    aid, state = _navaid_clause(upper)
    if aid and state:
        return f"{aid} {state}."
    procedure, note = _faa_procedure_line(upper)
    if procedure and note:
        return f"{procedure}: {note}."
    return ""


RUNWAY_NOT_CLOSED_NOTE = "The runway is not reported closed by this notice."


def _with_runway_not_closed_note(line: str) -> str:
    """Keep the boss's obstacle qualifier ahead of the derivation's markers.

    An obstacle notice that names a runway must say the runway is not reported
    closed by it (16 Aug 2026 follow-up). The derived line can end with a fixed
    marker sentence saying what it omitted; the qualifier belongs to the
    statement, so it goes before that marker rather than after it.
    """
    body = line
    markers: list[str] = []
    trimmed = True
    while trimmed:
        trimmed = False
        for sentence in FIXED_MARKER_SENTENCES:
            if body.endswith(sentence):
                markers.insert(0, sentence)
                body = body[: -len(sentence)].rstrip()
                trimmed = True
    return " ".join(part for part in (body, RUNWAY_NOT_CLOSED_NOTE, *markers) if part)


def obstacle_restriction_line(text: str) -> str:
    """The published line for an obstacle notice: C1's derivation, plus the
    boss's runway qualifier when the notice names a runway.

    C2 round 2. This was inline in ``_notam_operational_summary``'s obstacle
    branch, which runs at ANALYSIS time only. Download PDF renders a stored
    analysis without re-analysing it, so a flight already in storage needs the
    same line derivable at RENDER time. Sharing one function is what makes a
    stale pack and a fresh one publish the same sentence, rather than two
    implementations that agree until one of them is edited.
    """
    line = derive_notam_restriction_line(text)["text"]
    if re.search(r"\b(?:RWY|RUNWAY)\s+\d{1,2}", " ".join(str(text or "").upper().split())):
        line = _with_runway_not_closed_note(line)
    return line


def _notam_operational_summary(
    text: str,
    kind: str,
    role: str,
    applicability: str = "active",
    *,
    category: str = "",
) -> str:
    upper = " ".join(text.upper().split())
    if kind == "taxiway_restriction" and "CONSTRUCTION SURVEY LASER" in upper:
        taxilanes: list[str] = []
        for group in re.findall(r"\bTAXILANE\s+((?:[A-Z]\d+(?:,\s*|\s+AND\s+)?)+)", upper):
            for identifier in re.findall(r"\b[A-Z]\d+\b", group):
                if identifier not in taxilanes:
                    taxilanes.append(identifier)
        locations = "/".join(taxilanes) if taxilanes else "the published taxilanes"
        phase = role.replace("destination alternate", "alternate").replace("informational", "flight")
        return (
            f"Construction survey lasers near taxilanes {locations} require "
            f"operational review during the applicable {phase} window."
        )
    if kind == "taxiway_restriction" and re.search(r"\bPROC(?:EDURE)?\b", upper) and re.search(r"\bTAXI(?:ING)?\b", upper):
        return "Published taxi procedure; instructions, clearance limits and conditions are stated in item E."
    subject = _notam_subject(text, kind)
    phase = role.replace("destination alternate", "alternate").replace("informational", "flight")
    if applicability == "review":
        return (
            f"Published {subject or 'airport'} restriction could not be resolved "
            f"for the applicable {phase} window."
        )
    if _NO_APPROACH_OPERATIONS.search(upper):
        runway = re.search(_APPROACH_RUNWAY_REFERENCE, upper)
        runway_label = (
            runway.group(0).replace("RUNWAY", "RWY")
            if runway
            else "the named runway"
        )
        return (
            f"Instrument approaches to or from {runway_label} are prohibited "
            "only under the exact condition stated in item E; that condition "
            f"is not evaluated for the applicable {phase} window."
        )
    if _APPROACH_MINIMA_RAISED.search(upper):
        return (
            "LPV minima are raised to the stated LNAV/VNAV minima for the "
            f"named RNP approaches during the applicable {phase} window."
        )
    if kind not in {"airport_closure", "runway_closure", "taxiway_closure", "apron_stand_closure", "approach_navaid_closure"} and re.search(
        r"\bPROC(?:EDURE)?S?\s+MAY\s+BE\s+SUSPENDED\b", upper,
    ):
        return (
            "Published procedure may be suspended under the conditions stated in item E; "
            f"those conditions are not evaluated for the applicable {phase} window."
        )
    if kind == "airport_closure":
        return f"Entire airport closed or unavailable during the applicable {phase} window."
    if kind == "approach_minima_change":
        changes = iap_minima_changes(text, category)
        cause = " by a temporary crane" if "CRANE" in upper else ""
        if changes:
            clauses = [
                f"{procedure} minima changed ({minima})"
                for procedure, minima in changes
            ]
            named = (
                clauses[0]
                if len(clauses) == 1
                else f"{', '.join(clauses[:-1])} and {clauses[-1]}"
            )
            return f"{named}{cause} during the applicable {phase} window."
        # The kind owns this sentence: never fall through to the generic
        # restriction line, which would contradict the record's own rank.
        return (
            f"Published approach minima changed{cause} (procedure and minima as "
            f"stated in item E) during the applicable {phase} window."
        )
    if kind == "runway_closure":
        return f"{subject.title()} closed or unavailable during the applicable {phase} window."
    if kind == "approach_navaid_closure":
        return f"{subject} unavailable during the applicable {phase} window."
    if kind == "runway_approach_restriction":
        return derive_notam_restriction_line(text)["text"]
    if kind == "surface_identity_review":
        return retired_taxiway_lighting_summary(text) or "Pavement identity and availability are unverified."
    if kind == "runway_lighting_restriction":
        sequence_flashing_lights = re.search(
            r"\bSEQUENCE(?:D)?\s+(?:FLASHING|FLG)\s+(?:LGT|LIGHTS?)\b",
            upper,
        )
        approach_lights_available = _approach_lights_reported_available(upper)
        if sequence_flashing_lights and approach_lights_available:
            return (
                f"Sequence flashing lights for {subject.upper()} are unserviceable; "
                "approach lights are reported available by this notice during the "
                f"applicable {phase} window."
            )
        return f"Lighting affecting {subject.upper()} is unavailable during the applicable {phase} window."
    if kind == "taxiway_closure":
        named = _named_taxiway_closure_items(text, subject)
        if named:
            scope, further_named = named
            tail = f" {further_named}; the full record is held with the airport's notices." if further_named else ""
            return f"{scope.upper()} closed during the applicable {phase} window.{tail}"
        notes = []
        if subject.startswith("part of "):
            notes.append("Its bounds could not be read completely from the notice")
        source = _taxiway_subject(upper)[1]
        further = _further_closed_taxiway_items(text) if source in {"extent", "designation"} else ""
        if further:
            notes.append(further if not notes else further[0].lower() + further[1:])
        remaining = (
            " " + "; ".join(notes) + "; the full record is held with the airport's notices."
            if notes else ""
        )
        return f"{subject.upper()} closed during the applicable {phase} window.{remaining}"
    if kind == "taxiway_restriction":
        return derive_notam_restriction_line(text)["text"]
    if kind == "apron_stand_closure":
        return f"{subject.upper()} closed during the applicable {phase} window."
    if kind == "obstacle":
        # C2, 18 Sep 2026. This branch used to publish a fixed sentence
        # ("Obstacle or crane affects the ... airport environment; assess
        # against expected runway and approach use.") that states nothing the
        # notice says. The dashboard refuses that template as content-free and
        # derives a line from the source instead, so the two surfaces disagreed
        # on all four RKSI records of SQ606-SIN-ICN-06SEP. The derivation is
        # C1's: source-bound, copy-guarded, and it abstains in its own words
        # rather than inventing one.
        #
        # The boss's own rule survives the change: an obstacle notice that
        # names a runway must still say the runway is not reported closed, so
        # an obstacle is never skim-read as a closure (16 Aug 2026 follow-up;
        # the conditional-crane regression "CRANE WILL ONLY OPERATE WHEN RWY
        # 09L/27R IS CLSD"). The note goes before the derivation's own trailing
        # marker sentence so the line still ends by saying what it omitted.
        # Shared with the render-time repair of a pack analysed before C2
        # (``briefing._republishable_finding``), so storage age cannot change
        # what an obstacle notice publishes.
        return obstacle_restriction_line(text)
    # R2 residual (24 Sep 2026): the unresolved state, never "requires review".
    return f"Operational airport restriction is unresolved for the applicable {phase} window."


def _text_between(
    clause: str,
    left: re.Match[str],
    right: re.Match[str],
) -> str:
    if left.end() <= right.start():
        return clause[left.end():right.start()]
    if right.end() <= left.start():
        return clause[right.end():left.start()]
    return ""


def _binding_token_gap(
    clause: str,
    left: re.Match[str],
    right: re.Match[str],
) -> int:
    return len(_APPROACH_BINDING_TOKEN.findall(_text_between(clause, left, right)))


def _adverse_is_negated(clause: str, adverse: re.Match[str]) -> bool:
    return bool(_NEGATED_ADVERSE_PREFIX.search(clause[:adverse.start()]))


def _adverse_is_restored_before_another_subject(
    clause: str,
    adverse: re.Match[str],
) -> bool:
    """Bind a restoration to the adverse subject immediately before it."""

    for restoration in _APPROACH_RESTORATION.finditer(
        clause,
        adverse.end(),
    ):
        if _NEGATED_RESTORATION_PREFIX.search(
            clause[:restoration.start()]
        ):
            continue
        if _APPROACH_RESTORATION_CONNECTOR.fullmatch(
            clause[adverse.end():restoration.start()]
        ):
            return True
    return False


def _special_approach_state_is_restored(
    clause: str,
    subject: re.Match[str],
) -> bool:
    """Bind a cancellation/restoration to one prohibition or minima rule."""

    for restoration in _APPROACH_RESTORATION.finditer(
        clause,
        subject.end(),
    ):
        if _NEGATED_RESTORATION_PREFIX.search(
            clause[:restoration.start()]
        ):
            continue
        between = clause[subject.end():restoration.start()]
        if _APPROACH_RESTORATION_CONNECTOR.fullmatch(between):
            return True
    return False


def _binding_has_competing_subject(
    clause: str,
    subject: re.Match[str],
    state: re.Match[str],
) -> bool:
    between = _text_between(clause, subject, state)
    if _APPROACH_BINDING_SURFACE_SUBJECT.search(between):
        return True
    if (
        _APPROACH_NON_ADVERSE_ACTIVITY.search(between)
        and not re.fullmatch(r"DO\s+NOT\s+USE", state.group(0))
    ):
        return True
    return any(
        pattern.search(between)
        for pattern in (
            _DIRECT_INSTRUMENT_APPROACH_EQUIPMENT,
            _CONVENTIONAL_APPROACH_NAVAID,
            _INSTRUMENT_APPROACH_MARKER,
            _EXPLICIT_INSTRUMENT_APPROACH_PROCEDURE,
            _RNAV_OR_RNP,
            _NAMED_INSTRUMENT_APPROACH_PROCEDURE,
            _CATEGORY_APPROACH_OPERATIONS,
        )
    )


def _subject_state_are_bound(
    clause: str,
    subject: re.Match[str],
    state: re.Match[str],
) -> bool:
    """Accept only a bounded approach subject plus its own adverse state."""
    if _binding_has_competing_subject(clause, subject, state):
        return False
    between = _text_between(clause, subject, state)
    if subject.end() <= state.start():
        if (
            re.fullmatch(r"DO\s+NOT\s+USE", state.group(0))
            and re.fullmatch(r"\s*ON\s+TEST\s*,?\s*", between)
        ):
            return True
        return bool(_FORWARD_APPROACH_STATE_BINDING.fullmatch(between))
    return bool(_REVERSE_APPROACH_STATE_BINDING.fullmatch(between))


def _subject_adverse_pair(
    clause: str,
    subject_pattern: re.Pattern[str],
) -> tuple[re.Match[str], re.Match[str]] | None:
    adverse_states = [
        match
        for match in _INSTRUMENT_APPROACH_ADVERSE.finditer(clause)
        if not _adverse_is_negated(clause, match)
    ]
    available_states = list(
        _INSTRUMENT_APPROACH_AVAILABLE.finditer(clause)
    )
    for subject in subject_pattern.finditer(clause):
        for adverse in adverse_states:
            if subject.start() < adverse.end() and adverse.start() < subject.end():
                continue
            adverse_gap = _binding_token_gap(clause, subject, adverse)
            if adverse_gap > _MAX_APPROACH_BINDING_TOKENS:
                continue
            if not _subject_state_are_bound(clause, subject, adverse):
                continue
            if _adverse_is_restored_before_another_subject(clause, adverse):
                continue
            if any(
                subject.end() <= available.start() <= adverse.start()
                and _binding_token_gap(clause, subject, available) <= adverse_gap
                and _subject_state_are_bound(clause, subject, available)
                for available in available_states
            ):
                continue
            return subject, adverse
    return None


def _subject_has_adverse_state(
    clause: str,
    subject_pattern: re.Pattern[str],
) -> bool:
    return _subject_adverse_pair(clause, subject_pattern) is not None


def _instrument_marker_adverse_pair(
    clause: str,
) -> tuple[re.Match[str], re.Match[str]] | None:
    """Bind an ILS marker state without borrowing a surface identifier."""

    pair = _subject_adverse_pair(clause, _INSTRUMENT_APPROACH_MARKER)
    if pair is None:
        return None
    subject, _ = pair
    surface_owner = re.search(
        r"\b(?:TWY|TAXIWAY|STAND|APRON|INTERSECTION)"
        r"(?:\s+[A-Z0-9-]+)?\s*$",
        clause[:subject.start()],
    )
    return None if surface_owner else pair


def _bound_unavailable_approach_subject(text: str) -> str | None:
    """Return the exact adverse subject without borrowing an available one."""

    normalized = " ".join(str(text or "").upper().split())
    clauses = [
        clause.strip()
        for clause in re.split(r"(?:\.(?=\s|$)|;|\r?\n)+", normalized)
        if clause.strip()
    ]
    for clause in clauses:
        pairs = [
            pair
            for subject_pattern in (
                _DIRECT_INSTRUMENT_APPROACH_EQUIPMENT,
                _CONVENTIONAL_APPROACH_NAVAID,
                _PAPI_OPERATIONAL_SUBJECT,
                _RNAV_OR_RNP,
                _EXPLICIT_INSTRUMENT_APPROACH_PROCEDURE,
            )
            if (pair := _subject_adverse_pair(clause, subject_pattern))
        ]
        if marker_pair := _instrument_marker_adverse_pair(clause):
            pairs.append(marker_pair)
        if not pairs:
            continue
        subject, adverse = min(pairs, key=lambda pair: pair[0].start())
        label = subject.group(0)
        if not re.search(rf"\b{_APPROACH_RUNWAY_REFERENCE}\b", label):
            runway = re.search(
                rf"\b{_APPROACH_RUNWAY_REFERENCE}\b",
                _text_between(clause, subject, adverse),
            )
            if runway is None and label.startswith("PAPI"):
                runway = re.search(
                    rf"\b{_APPROACH_RUNWAY_REFERENCE}\s*$",
                    clause[:subject.start()],
                )
            if runway:
                label = f"{label} {runway.group(0)}"
        return (
            label.replace("LOCALIZER", "LOC")
            .replace("RUNWAY", "RWY")
            .strip()
        )
    return None


def _instrument_approach_affected(text: str, category: str) -> bool:
    """Require explicit adverse instrument-approach evidence.

    The older pertinence taxonomy intentionally groups general navaid and
    visual-aid outages for pilot review.  This stricter gate is only for the
    machine-readable ``approach_affected`` flag and critical severity: a bare
    VOR/NDB/DME outage needs an explicit approach-procedure binding, while a
    PAPI outage alone remains a visual-aid warning.
    """

    category_text = " ".join(str(category or "").upper().split())
    category_is_approach_procedure = bool(
        _APPROACH_PROCEDURE_CATEGORY.search(category_text)
    )
    normalized_text = " ".join(str(text or "").upper().split())
    normalized_text = re.sub(
        r"\bINSTRUMENT\s+LANDING\s+SYSTEM\s*\(ILS\)",
        "ILS",
        normalized_text,
    )
    normalized_text = re.sub(r"\bG\.P\.?\b", "GP", normalized_text)
    normalized_text = re.sub(
        r"\bON\s+TEST\.\s+DO\s+NOT\s+USE\b",
        "ON TEST DO NOT USE",
        normalized_text,
    )
    normalized_text = re.sub(r"\.{2,}", " ", normalized_text)
    iap_publication_adverse = _IAP_PUBLICATION_ADVERSE.search(normalized_text)
    if (
        iap_publication_adverse
        and not _special_approach_state_is_restored(
            normalized_text,
            iap_publication_adverse,
        )
    ):
        return True
    if iap_publication_adverse:
        normalized_text = (
            normalized_text[:iap_publication_adverse.start()]
            + " "
            + normalized_text[iap_publication_adverse.end():]
        )
    if iap_minima_changes(text, category):
        # Republished DA/MDA for a named procedure changes the approach the
        # crew will fly, whatever the underlying cause. This reads the record
        # as received - category included, nothing excised - so it can never
        # disagree with the kind the same record was given.
        return True
    clauses = [
        " ".join(clause.upper().split())
        for clause in re.split(
            r"(?:\.(?=\s|$)|;|\r?\n)+",
            normalized_text,
        )
        if clause.strip()
    ]
    for clause in clauses:
        iap_clause_suspension = _IAP_CLAUSE_SUSPENSION.search(clause)
        if (
            iap_clause_suspension
            and not _INSTRUMENT_APPROACH_AVAILABLE.search(
                iap_clause_suspension.group(0)
            )
            and not _special_approach_state_is_restored(
                clause,
                iap_clause_suspension,
            )
        ):
            return True
        for special_pattern in (
            _NO_APPROACH_OPERATIONS,
            _APPROACH_MINIMA_RAISED,
        ):
            for special in special_pattern.finditer(clause):
                if not _special_approach_state_is_restored(
                    clause,
                    special,
                ):
                    return True
        if not _INSTRUMENT_APPROACH_ADVERSE.search(clause):
            continue
        if _subject_has_adverse_state(
            clause,
            _DIRECT_INSTRUMENT_APPROACH_EQUIPMENT,
        ):
            return True
        if _instrument_marker_adverse_pair(clause):
            return True
        for exact_procedure_pattern in (
            _LPV_APPROACH_PROCEDURE,
            _ILS_LOC_APPROACH_PROCEDURE,
            _PUBLISHED_ILS_LOC_PROCEDURE,
            _ILS_FINAL_DME_READING,
            _IAC_APPROACH_PROCEDURE_LIST,
            _ILS_CATEGORY_PROCEDURE,
            _ILS_SPECIAL_AUTH_CATEGORY,
        ):
            if _subject_has_adverse_state(
                clause,
                exact_procedure_pattern,
            ):
                return True

        for named_procedure_pattern in (
            _NAMED_INSTRUMENT_APPROACH_PROCEDURE,
            _NUMBERED_IAC_APPROACH_PROCEDURE,
            _CATEGORY_APPROACH_OPERATIONS,
        ):
            if (
                category_is_approach_procedure
                and _subject_has_adverse_state(
                    clause,
                    named_procedure_pattern,
                )
            ):
                return True

        explicit_procedure = bool(
            _EXPLICIT_INSTRUMENT_APPROACH_PROCEDURE.search(clause)
        )
        if _subject_has_adverse_state(
            clause,
            _RNAV_INSTRUMENT_APPROACH_PROCEDURE,
        ):
            return True
        if (
            _subject_has_adverse_state(
                clause,
                _CONVENTIONAL_APPROACH_NAVAID,
            )
            and (explicit_procedure or category_is_approach_procedure)
        ):
            return True
        if (
            explicit_procedure
            and not _PAPI.search(clause)
            and _subject_has_adverse_state(
                clause,
                _EXPLICIT_INSTRUMENT_APPROACH_PROCEDURE,
            )
        ):
            return True
    return False


def taxiway_operational_details(text: str, kind: str) -> list[str]:
    """Structure bounded visual-aid facts explicitly present in taxiway text."""

    if kind not in {"taxiway_closure", "taxiway_restriction"}:
        return []
    raw = " ".join(str(text or "").upper().split())
    clauses = [
        clause.strip()
        for clause in re.split(r"(?<=[.!?])\s+", raw)
        if clause.strip()
    ]

    def clause_matches(*patterns: str) -> bool:
        closed_taxiway = (
            r"(?:\b(?:CLSD|CLOSED)\s+(?:TWY|TAXIWAY)\b|"
            r"\b(?:TWY|TAXIWAY)(?:\s+[A-Z0-9/-]+)?\s+"
            r"(?:CLSD|CLOSED)\b)"
        )
        return any(
            re.search(closed_taxiway, clause)
            and all(re.search(pattern, clause) for pattern in patterns)
            for clause in clauses
        )

    details: list[str] = []
    if clause_matches(
        r"\bMARKINGS?\b",
        r"\bLEAD(?:ING)?\b",
        r"\bINTO\b",
        r"\bREMOV(?:E|ED|AL)?\b",
    ):
        details.append("lead_in_markings_removed")
    if clause_matches(
        r"\bMARKERBOARDS?\b",
        r"\b(?:CLSD|CLOSED)\s+MARKINGS?\b",
        r"\bYELLOW\s+CROSS(?:ES)?\b",
        r"\bDEMARCATE\b",
    ):
        details.append("markerboards_yellow_cross")
    if clause_matches(
        r"\bUNSERVICEABILITY\s+MARKERS?\b",
        r"\bFIXED\s+RED\s+(?:LGT|LGTS|LIGHT|LIGHTS)\b",
        r"\b(?:LGTD|LIT|LIGHTED)\b",
        r"\b(?:NGT|NIGHT)\b",
        r"\bLOW\s+VIS(?:IBILITY|\s+COND(?:ITIONS?)?)?\b",
    ):
        details.append("marker_red_lights")
    if clause_matches(
        r"\b(?:TWY\s+CL\s+LGT|TAXIWAY\s+(?:CENTRELINE|CENTERLINE)\s+LIGHTS?)\b",
        r"\bLEAD(?:ING)?\b",
        r"\bINTO\b",
        r"\b(?:WI|WITHIN)\b",
        r"\bNOT\s+(?:BE\s+)?IN\s+USE\b",
    ):
        details.append("centreline_lights_out")
    return details


def _configured_window_minutes(name: str, default: int) -> int:
    raw = os.environ.get(name, str(default)).strip()
    try:
        minutes = int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be a whole number of minutes.") from exc
    if not 0 <= minutes <= 720:
        raise ValueError(f"{name} must be between 0 and 720 minutes.")
    return minutes


def _weather_window_preference(flight: dict[str, Any]) -> dict[str, Any]:
    raw = flight.get("weather_window_preference")
    supplied = raw if isinstance(raw, dict) else {}

    def selected(key: str, environment_name: str) -> int:
        value = supplied.get(key)
        if value is None:
            return _configured_window_minutes(environment_name, 60)
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(f"weather_window_preference.{key} must be whole minutes.")
        if not 0 <= value <= 720:
            raise ValueError(
                f"weather_window_preference.{key} must be between 0 and 720 minutes."
            )
        return value

    normalized = {
        "before_minutes": selected(
            "before_minutes",
            "ODSS_WEATHER_WINDOW_BEFORE_MINUTES",
        ),
        "after_minutes": selected(
            "after_minutes",
            "ODSS_WEATHER_WINDOW_AFTER_MINUTES",
        ),
        "basis": "scheduled_phase_reference",
    }
    flight["weather_window_preference"] = normalized
    return normalized


def _profile_applies_to_aircraft(
    profile: dict[str, Any],
    registration: str | None,
    aircraft_type: str | None,
) -> bool:
    effectivity = {
        re.sub(r"[^A-Z0-9]", "", str(value).upper())
        for value in profile.get("effectivity", [])
        if value
    }
    if not effectivity or "ALL" in effectivity:
        return True
    return bool(effectivity & aircraft_effectivity_tokens(registration, aircraft_type))


def terrain_event_identity(event: dict[str, Any]) -> str:
    """Return a stable, human-auditable identity for one MSA exposure window."""

    first = event.get("first_high") or {}
    last = event.get("last_high") or first

    def anchor(point: dict[str, Any]) -> str:
        name = str(point.get("name") or "UNKNOWN").lstrip("-").upper()
        actm = point.get("actm_minutes")
        return f"{name}@{actm if actm is not None else 'NA'}"

    return f"terrain:{anchor(first)}-{anchor(last)}"


def _terrain_event(
    *,
    preceding: dict[str, Any] | None,
    active: list[dict[str, Any]],
    drop: dict[str, Any] | None,
) -> dict[str, Any]:
    event = {
        "preceding": preceding,
        "first_high": active[0],
        "last_high": active[-1],
        "drop": drop,
        "maximum": max(active, key=lambda w: w.get("msa_hundreds_ft") or -1),
    }
    event["terrain_event_id"] = terrain_event_identity(event)
    return event


def detect_terrain_events(waypoints: list[dict[str, Any]]) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    active: list[dict[str, Any]] = []
    preceding = None
    last_msa = None
    for waypoint in waypoints:
        msa = waypoint.get("msa_hundreds_ft")
        if msa is None:
            continue
        # Strict v1.3 trigger: only MSA strictly above 10,000 ft qualifies.
        # An exact 100* value is a boundary row - it terminates an active
        # exposure (becoming its drop point) and never starts one.
        if msa > 100:
            if not active:
                preceding = last_msa
            active.append(waypoint)
        elif active:
            events.append(
                _terrain_event(
                    preceding=preceding,
                    active=active,
                    drop=waypoint,
                )
            )
            active = []
            preceding = None
        last_msa = waypoint
    if active:
        events.append(
            _terrain_event(
                preceding=preceding,
                active=active,
                drop=None,
            )
        )
    return events


def detect_vws_events(waypoints: list[dict[str, Any]]) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    active: list[dict[str, Any]] = []
    for waypoint in waypoints:
        vws = waypoint.get("vws")
        if vws is None:
            if active and not waypoint.get("fir_boundary"):
                events.append({
                    "first_high": active[0],
                    "last_high": active[-1],
                    "drop": waypoint,
                    "maximum": max(active, key=lambda w: w.get("vws") or -1),
                })
                active = []
            continue
        if vws > 4:
            active.append(waypoint)
        elif active:
            events.append({
                "first_high": active[0],
                "last_high": active[-1],
                "drop": waypoint,
                "maximum": max(active, key=lambda w: w.get("vws") or -1),
            })
            active = []
    if active:
        events.append({
            "first_high": active[0],
            "last_high": active[-1],
            "drop": None,
            "maximum": max(active, key=lambda w: w.get("vws") or -1),
        })
    return events


def _subsequence(sequence: list[str], candidate: list[str]) -> bool:
    if not candidate:
        return True

    def aliases(value: str) -> set[str]:
        values: set[str] = set()
        for part in str(value or "").upper().replace(" ", "").split("/"):
            if not part:
                continue
            values.add(part)
            if re.fullmatch(r"U[A-Z]{1,2}\d+", part):
                values.add(part[1:])
        return values

    position = 0
    for item in sequence:
        if aliases(item) & aliases(candidate[position]):
            position += 1
            if position == len(candidate):
                return True
    return False


def _route_waypoint_name(waypoint: dict[str, Any]) -> str:
    return str(waypoint.get("name") or "").lstrip("-").upper()


def _profile_aliases(profile: dict[str, Any], field: str) -> set[str]:
    fallback = str(profile.get(field) or "").upper()
    return {
        str(value).lstrip("-").upper()
        for value in profile.get(f"{field}_aliases", [fallback])
        if value
    }


def _route_airways_between(
    waypoints: list[dict[str, Any]],
    start_index: int,
    end_index: int,
) -> list[str]:
    return [
        str(waypoints[index].get("airway_in") or "").upper()
        for index in range(start_index + 1, end_index + 1)
        if waypoints[index].get("airway_in")
    ]


def _profile_route_spans(
    profile: dict[str, Any],
    waypoints: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    names = [_route_waypoint_name(item) for item in waypoints]
    from_aliases = _profile_aliases(profile, "from")
    to_aliases = _profile_aliases(profile, "to")
    published_airways = [str(value).upper() for value in profile.get("airways", [])]
    spans: list[dict[str, Any]] = []
    for from_index, name in enumerate(names):
        if name not in from_aliases:
            continue
        for to_index, to_name in enumerate(names):
            if to_name not in to_aliases or to_index == from_index:
                continue
            if from_index < to_index:
                start_index, end_index = from_index, to_index
                expected_airways = published_airways
                direction = "forward"
            else:
                start_index, end_index = to_index, from_index
                expected_airways = list(reversed(published_airways))
                direction = "reverse"
            route_airways = _route_airways_between(waypoints, start_index, end_index)
            if expected_airways:
                candidate_orders = [
                    expected_airways,
                    list(reversed(expected_airways)),
                ]
                matched_order = next(
                    (
                        order
                        for order in candidate_orders
                        if _subsequence(route_airways, order)
                    ),
                    None,
                )
                if matched_order is None:
                    continue
                expected_airways = matched_order
            spans.append(
                {
                    "start_index": start_index,
                    "end_index": end_index,
                    "route_start": names[start_index],
                    "route_end": names[end_index],
                    "airways": expected_airways,
                    "route_airways": route_airways,
                    "direction": direction,
                    "match_class": "published-route",
                }
            )
    return spans


def _airway_alias_tokens(values: list[Any]) -> set[str]:
    tokens: set[str] = set()
    for value in values:
        for part in str(value or "").upper().replace(" ", "").split("/"):
            if not part:
                continue
            tokens.add(part)
            if re.fullmatch(r"U[A-Z]{1,2}\d+", part):
                tokens.add(part[1:])
    return tokens


def _corridor_spans(
    profile: dict[str, Any],
    waypoints: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Single-endpoint subsegment coverage along the chart's published corridor.

    A chart whose route shares only one endpoint with the filed route still
    protects the filed legs that run between the chart's own published points
    (from, critical point, to) on the chart's published airways. The span is
    bounded by the outermost chart points that are filed waypoints, so a chart
    never extends past its own corridor onto same-named airway legs elsewhere
    (the approved v1.3 example: chart 8-5 covers MATAL-TEMEL on SQ352 but must
    not reach the separate ALUVO exposure east of its critical point, and
    chart 8-7 is not promoted because its published leg adjacent to the shared
    endpoint is a different airway than the filed leg).
    """
    names = [_route_waypoint_name(item) for item in waypoints]
    from_aliases = _profile_aliases(profile, "from")
    to_aliases = _profile_aliases(profile, "to")
    critical_aliases = _profile_aliases(profile, "critical")
    has_from = any(name in from_aliases for name in names)
    has_to = any(name in to_aliases for name in names)
    if has_from and has_to:
        # Both endpoints filed: the published-route span logic owns this chart.
        return []
    airway_tokens = _airway_alias_tokens(profile.get("airways", []))
    if not airway_tokens:
        return []
    ordered_groups: list[set[str]] = [from_aliases, critical_aliases, to_aliases]
    filed_points: list[tuple[int, int]] = []
    for chart_position, aliases in enumerate(ordered_groups):
        for index, name in enumerate(names):
            if name and name in aliases:
                filed_points.append((index, chart_position))
    if len({position for _, position in filed_points}) < 2:
        return []
    filed_points.sort()
    chart_positions = [position for _, position in filed_points]
    ascending = all(a <= b for a, b in zip(chart_positions, chart_positions[1:]))
    descending = all(a >= b for a, b in zip(chart_positions, chart_positions[1:]))
    if not ascending and not descending:
        return []
    start_index = filed_points[0][0]
    end_index = filed_points[-1][0]
    if end_index <= start_index:
        return []
    route_airways: list[str] = []
    for index in range(start_index + 1, end_index + 1):
        airway = waypoints[index].get("airway_in")
        if not airway:
            # FIR-boundary annotation rows carry no leg of their own.
            continue
        if not (_airway_alias_tokens([airway]) & airway_tokens):
            return []
        route_airways.append(str(airway).upper())
    if not route_airways:
        return []
    return [
        {
            "start_index": start_index,
            "end_index": end_index,
            "route_start": names[start_index],
            "route_end": names[end_index],
            "airways": [str(value).upper() for value in profile.get("airways", [])],
            "route_airways": route_airways,
            "direction": "forward" if ascending else "reverse",
            "match_class": "corridor-subsegment",
        }
    ]


def effectivity_conflict(flight: dict[str, Any]) -> dict[str, Any] | None:
    """
    Report an unresolved airframe variant that is withholding approved charts.

    A registration series the fleet register does not describe resolves to no
    variant token, and every variant-scoped profile in the index is then
    excluded. That is not an empty index and must not be reported as one: the
    reference protocol requires an effectivity conflict to be shown instead of a
    generic entry being selected. The variant is never guessed to fill the gap.
    """
    registration = flight.get("registration")
    tokens, resolved = resolve_aircraft_effectivity(
        registration,
        flight.get("aircraft_type"),
    )
    if resolved:
        return None
    withheld = [
        profile
        for profile in DEPRESS_PROFILES
        if not _profile_applies_to_aircraft(
            profile,
            registration,
            flight.get("aircraft_type"),
        )
    ]
    if not withheld:
        return None
    variants = sorted({
        str(value).upper()
        for profile in withheld
        for value in profile.get("effectivity", [])
        if value
    })
    # Shown to a human, so the tail is displayed as the OFP wrote it when that
    # already carries a separator. normalized_registration only knows how to
    # punctuate one national format and would flatten the others.
    stated = str(registration or "").strip().upper()
    return {
        "registration": stated if "-" in stated else (normalized_registration(registration) or stated),
        "aircraft_type": flight.get("aircraft_type"),
        "resolved_tokens": sorted(tokens),
        "withheld_profile_count": len(withheld),
        "index_profile_count": len(DEPRESS_PROFILES),
        "withheld_variants": variants,
    }


def match_profiles(
    flight: dict[str, Any],
    terrain_events: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    waypoints = flight["route_waypoints"]
    matches: list[dict[str, Any]] = []
    for event in terrain_events:
        # Coverage is judged against the actual exposure legs (first to last
        # high waypoint); the preceding point is route context only (v1.3).
        event_start_index = waypoints.index(event["first_high"])
        event_end_index = waypoints.index(event["last_high"])
        required_edges = set(range(event_start_index, event_end_index))
        if not required_edges:
            required_edges = {event_start_index}

        candidate_by_chart: dict[str, dict[str, Any]] = {}
        for profile in DEPRESS_PROFILES:
            if not _profile_applies_to_aircraft(
                profile,
                flight.get("registration"),
                flight.get("aircraft_type"),
            ):
                continue
            for span in (
                _profile_route_spans(profile, waypoints)
                + _corridor_spans(profile, waypoints)
            ):
                if event_end_index == event_start_index:
                    covered = (
                        {event_start_index}
                        if span["start_index"] <= event_start_index <= span["end_index"]
                        else set()
                    )
                else:
                    covered = set(
                        range(
                            max(span["start_index"], event_start_index),
                            min(span["end_index"], event_end_index),
                        )
                    )
                if not covered:
                    continue
                candidate = {
                    **span,
                    "event": event,
                    "profile": profile,
                    "covered_edges": covered,
                }
                chart = str(profile.get("chart") or "")
                current = candidate_by_chart.get(chart)

                def _score(item: dict[str, Any]) -> tuple[int, int, int]:
                    class_rank = (
                        1 if item.get("match_class") == "published-route" else 0
                    )
                    return (
                        class_rank,
                        len(item["covered_edges"]),
                        -(item["end_index"] - item["start_index"]),
                    )

                if current is None or _score(candidate) > _score(current):
                    candidate_by_chart[chart] = candidate

        uncovered = set(required_edges)
        available = list(candidate_by_chart.values())
        selected: list[dict[str, Any]] = []
        while uncovered:
            useful = [
                (len(item["covered_edges"] & uncovered), item)
                for item in available
            ]
            useful = [entry for entry in useful if entry[0] > 0]
            if not useful:
                break
            _, best = max(
                useful,
                key=lambda entry: (
                    entry[0],
                    1 if entry[1].get("match_class") == "published-route" else 0,
                    len(entry[1]["covered_edges"]),
                    entry[1]["end_index"] - entry[1]["start_index"],
                    str(entry[1]["profile"].get("chart") or ""),
                ),
            )
            selected.append(best)
            uncovered -= best["covered_edges"]
            available = [item for item in available if item is not best]

        coverage_complete = not uncovered
        selected.sort(key=lambda item: (item["start_index"], item["end_index"]))
        for item in selected:
            matches.append(
                {
                    "event": event,
                    "terrain_event_id": event["terrain_event_id"],
                    "profile": item["profile"],
                    "names": [
                        _route_waypoint_name(value)
                        for value in waypoints[item["start_index"] : item["end_index"] + 1]
                    ],
                    "airways": item["airways"],
                    "route_start": item["route_start"],
                    "route_end": item["route_end"],
                    "direction": item["direction"],
                    "match_class": item.get("match_class", "published-route"),
                    "coverage_complete": coverage_complete,
                    "uncovered_edge_count": len(uncovered),
                    "start_index": item["start_index"],
                    "end_index": item["end_index"],
                }
            )

    deduplicated: dict[tuple[str, str, int, int], dict[str, Any]] = {}
    for match in matches:
        key = (
            match["terrain_event_id"],
            str(match["profile"]["chart"]),
            match["start_index"],
            match["end_index"],
        )
        current = deduplicated.get(key)
        if current is None or match["event"]["first_high"]["actm_minutes"] < current["event"]["first_high"]["actm_minutes"]:
            deduplicated[key] = match

    candidates = list(deduplicated.values())
    pruned = [
        candidate
        for candidate in candidates
        if not any(
            other is not candidate
            and other["terrain_event_id"] == candidate["terrain_event_id"]
            and other["start_index"] <= candidate["start_index"]
            and other["end_index"] >= candidate["end_index"]
            and (
                other["start_index"] < candidate["start_index"]
                or other["end_index"] > candidate["end_index"]
            )
            for other in candidates
        )
    ]
    return sorted(
        pruned,
        key=lambda item: (
            item["event"]["first_high"]["actm_minutes"],
            item["start_index"],
        ),
    )



def analyse(flight: dict[str, Any]) -> tuple[list[dict[str, Any]], list[str]]:
    findings: list[dict[str, Any]] = []
    warnings: list[str] = []
    fuel = flight["fuel"]
    masses = flight["masses"]
    performance = flight["performance"]
    _weather_window_preference(flight)

    findings.append(finding(
        "page1",
        "information",
        "OFP Page 1 organised control summary",
        f"{flight['flight_number']} {flight['departure']}-{flight['destination']}",
        [
            f"{flight['departure']}/{flight.get('departure_runway') or '-'} to "
            f"{flight['destination']}/{flight.get('destination_runway') or '-' }.",
            f"Scheduled departure {flight['scheduled_departure_utc']}; "
            f"arrival {flight['scheduled_arrival_utc']}.",
            f"Level profile: {flight.get('planned_level_profile') or 'not parsed'}.",
            f"Fuel required {format_kg(fuel['flight_plan_required_fuel_kg'])}; "
            f"tanks {format_kg(fuel['fuel_in_tanks_kg'])}; "
            f"trip {format_kg(fuel['trip_fuel_kg'])}.",
            f"PZFW {format_kg(masses['planned_zfw_kg'])}; "
            f"PTOW {format_kg(masses['planned_takeoff_weight_kg'])}; "
            f"PLWT {format_kg(masses['planned_landing_weight_kg'])}.",
        ],
        {
            "source_references": [
                _cfp_source_reference(
                    flight,
                    [flight.get("source_evidence", {}).get("page1")],
                    "Flight summary",
                )
            ],
        },
    ))

    if flight.get("bobcat"):
        allocation = flight["bobcat"]
        waypoint = next(
            (w for w in flight["route_waypoints"] if w["name"].upper() == allocation["waypoint"].upper()),
            None,
        )
        ctot = datetime.fromisoformat(allocation["ctot_utc"])
        cto = datetime.fromisoformat(allocation["cto_utc"])
        if cto < ctot:
            cto += timedelta(days=1)
        predicted = ctot + timedelta(minutes=waypoint["actm_minutes"]) if waypoint else None
        difference = round((predicted - cto).total_seconds() / 60) if predicted else None
        # The allocation itself belongs in the summary, not only in the evidence
        # list: the reports render a finding's summary line, so a bare delta left
        # the crossing time, level and CTOT out of the printed brief entirely.
        # Every value here is read from the OFP or computed from it.
        findings.append(finding(
            "bobcat",
            "critical" if difference not in (None, 0) else "warning" if difference is None else "information",
            "BOBCAT timing reconciliation",
            (
                f"{allocation['waypoint']} FL{allocation['flight_level']}: "
                f"CTOT {ctot:%H%MZ} + ACTM {format_actm(waypoint['actm_minutes'])} "
                f"= {predicted:%H%MZ} against allocated CTO {cto:%H%MZ} "
                f"({difference:+d} min)."
                if difference is not None
                else (
                    f"{allocation['waypoint']} FL{allocation['flight_level']}: "
                    f"allocated CTOT {ctot:%H%MZ}, CTO {cto:%H%MZ}; "
                    "OFP waypoint ACTM not found, so no crossing time is computed."
                )
            ),
            [
                f"Allocation CTOT {ctot:%H%MZ}; CTO {cto:%H%MZ}; FL{allocation['flight_level']}.",
                f"OFP waypoint ACTM {format_actm(waypoint['actm_minutes']) if waypoint else 'not found'}.",
                "Treat the allocated CTO as controlling and recheck if take-off, route, level or speed changes.",
            ],
            {
                "difference_minutes": difference,
                "source_references": [
                    _cfp_source_reference(
                        flight,
                        [
                            flight.get("source_evidence", {}).get("page1"),
                            (waypoint or {}).get("source_page"),
                        ],
                        "BOBCAT allocation and route timing",
                    )
                ],
            },
        ))

    for item in flight["deferred_items"]:
        if item["item_type"] in {"UNCLASSIFIED", "IFEDDL", "IN", "EN"}:
            # The OFP's own vocabulary names the block (boss, 21 Aug 2026:
            # "UNCLASSIFIED" never reaches the pilot). The exact printed text
            # is the whole held fact; no remedy or instruction is inferred.
            declaration = deferred_source_declaration_for_display(
                item.get("source_declaration")
            ) or " ".join(
                value
                for value in (
                    deferred_item_type_for_display(item.get("item_type")),
                    deferred_reference_for_display(item.get("reference")),
                )
                if value
            )
            kind_sentence = {
                "IFEDDL": (
                    "IFE deferred defect list declaration carried verbatim from OFP page 1; "
                    "no remedy or dispatch instruction is inferred."
                ),
                "IN": (
                    "Engineering information notice carried verbatim from OFP page 1; "
                    "no remedy or dispatch instruction is inferred beyond the printed text."
                ),
                # "GG EN A35MEN-21-28871" (SQ882 10 Sep 2026). An engineering
                # notice is not a configuration deviation: it has no CDL
                # reference to be "missing".
                "EN": (
                    "Engineering notice carried verbatim from OFP page 1; "
                    "no remedy or dispatch instruction is inferred beyond the printed text."
                ),
            }.get(item["item_type"], (
                "OFP deferred declaration is unresolved; acronym meaning is not "
                "inferred and no MEL, CDL or CDDL classification is asserted."
            ))
            details = [item.get("description") or "No following OFP text parsed."]
            if item.get("company_remark"):
                details.append(item["company_remark"])
            findings.append(finding(
                "deferred_declaration",
                "unknown",
                declaration,
                kind_sentence,
                details,
                {
                    "classification": item["item_type"].lower(),
                    "deferred_entry_id": item.get("deferred_entry_id"),
                    "classification_status": item.get("classification_status"),
                    "classification_reason": item.get("classification_reason"),
                    "governed_match_status": item.get("governed_match_status"),
                    "source_identifier": item.get("source_identifier"),
                    "source_group_tokens": list(item.get("source_group_tokens") or []),
                    "source_page": item.get("source_page"),
                    "source_line_start": item.get("source_line_start"),
                    "source_line_end": item.get("source_line_end"),
                    "source_lines": list(item.get("source_lines") or []),
                    "source_references": [
                        _cfp_source_reference(
                            flight,
                            [flight.get("source_evidence", {}).get("page1")],
                            "Deferred declaration",
                        )
                    ],
                },
            ))
        elif item["item_type"] == "MEL":
            reference = MEL_REFERENCES.get(item["reference"])
            if reference and _reference_library_is_approved():
                details = [
                    f"Repair interval {reference.get('repair_interval')}; "
                    f"installed {reference.get('installed')}; required {reference.get('required')}.",
                    f"Placard {'required' if reference.get('placard_required') else 'not required/none stated'}; "
                    f"operational procedure {'required' if reference.get('operational_procedure_required') else 'not stated'}.",
                    *reference.get("terms", []),
                ]
                if item.get("company_remark"):
                    details.append(f"Company remark: {item['company_remark']}.")
                findings.append(finding(
                    "mel",
                    "warning",
                    f"MEL {item['reference']} - {item['description']}",
                    "Candidate local-library match; not the approved MEL.",
                    details,
                    {
                        "reference_library_version": REFERENCE_LIBRARY_METADATA["version"],
                        "reference_status": REFERENCE_LIBRARY_METADATA["status"],
                    },
                ))
            else:
                details = [item["description"]]
                if item.get("company_remark"):
                    details.append(f"Company remark: {item['company_remark']}.")
                findings.append(finding(
                    "mel",
                    "unknown",
                    f"MEL {item['reference']} requires approved source review",
                    "Current approved MEL evidence is unavailable.",
                    details,
                    {
                        "reference_status": REFERENCE_LIBRARY_METADATA["status"],
                        "source_references": [
                            _cfp_source_reference(
                                flight,
                                [flight.get("source_evidence", {}).get("page1")],
                                "Deferred item declaration",
                            )
                        ],
                    },
                ))
        elif item["item_type"] == "CDL":
            reference_key = str(item.get("reference") or "").upper()
            record = CDL_REFERENCES.get(reference_key)
            if record is None:
                mounted = CDL_LIBRARY_METADATA.get("status") != "controlled-source-not-mounted"
                findings.append(finding(
                    "cdl",
                    "unknown",
                    f"CDL {reference_key} not resolved",
                    (
                        "Reference not found in the mounted controlled CDL index."
                        if mounted
                        else "The private controlled CDL index is not mounted."
                    ),
                    [
                        item.get("description") or "No Page 1 description parsed.",
                        item.get("company_remark") or "No Page 1 company remark parsed.",
                    ],
                    {
                        "controlled_document": CDL_LIBRARY_METADATA.get("title"),
                        "controlled_issue_date": CDL_LIBRARY_METADATA.get("issue_date"),
                        "reference_status": CDL_LIBRARY_METADATA.get("status"),
                    },
                ))
                continue

            variants = select_cdl_variants(record, flight.get("registration"))
            if not variants:
                findings.append(finding(
                    "cdl",
                    "critical",
                    f"CDL {reference_key} effectivity conflict",
                    f"No controlled variant applies to registration {flight.get('registration') or 'not parsed'}.",
                    [record.get("title") or "Title not available."],
                    {
                        "source_pages": record.get("source_pages", []),
                        "controlled_issue_date": CDL_LIBRARY_METADATA.get("issue_date"),
                    },
                ))
                continue

            details = [
                f"Page 1: {item.get('description') or 'description not parsed'}.",
            ]
            if item.get("company_remark"):
                details.append(f"Company remark: {item['company_remark']}.")
            takeoff_penalties: list[int] = []
            enroute_penalties: list[int] = []
            fuel_penalties: list[float] = []
            for number, variant in enumerate(variants, start=1):
                label = variant.get("component") or record.get("title") or reference_key
                quantity = variant.get("quantity_installed")
                details.append(
                    f"Applicable variant {number}: {label}"
                    + (f"; quantity installed {quantity}." if quantity is not None else ".")
                )
                for field, prefix in (
                    ("dispatch_conditions", "Dispatch"),
                    ("limitations", "Limitation"),
                ):
                    if variant.get(field):
                        details.append(f"{prefix}: {variant[field]}")
                details.extend(f"Note: {value}" for value in variant.get("notes", []) if value)
                if variant.get("maintenance_references"):
                    details.append(
                        "Maintenance reference: "
                        + ", ".join(variant["maintenance_references"])
                        + "."
                    )
                if variant.get("mel_references"):
                    details.append(
                        "MEL interface: " + ", ".join(variant["mel_references"]) + "."
                    )
                takeoff_penalties.extend(variant.get("takeoff_approach_penalty_kg_values", []))
                enroute_penalties.extend(variant.get("enroute_penalty_kg_values", []))
                fuel_penalties.extend(variant.get("fuel_penalty_percent_values", []))

            takeoff_penalties = list(dict.fromkeys(takeoff_penalties))
            enroute_penalties = list(dict.fromkeys(enroute_penalties))
            fuel_penalties = list(dict.fromkeys(fuel_penalties))
            if takeoff_penalties:
                details.append(
                    "Published take-off/approach penalty value(s): "
                    + ", ".join(f"{value:,} kg" for value in takeoff_penalties)
                    + "."
                )
            if enroute_penalties:
                details.append(
                    "Published enroute penalty value(s): "
                    + ", ".join(f"{value:,} kg" for value in enroute_penalties)
                    + "."
                )
            if fuel_penalties:
                details.append(
                    "Published fuel increase value(s): "
                    + ", ".join(f"{value:g}%" for value in fuel_penalties)
                    + "."
                )
            details.append(
                f"Controlled source issue {CDL_LIBRARY_METADATA.get('issue_date')}; "
                f"page(s) {', '.join(str(value) for value in record.get('source_pages', [])) or 'not indexed'}."
            )
            findings.append(finding(
                "cdl",
                "warning",
                f"CDL {reference_key} - {record.get('title') or item.get('description') or 'item'}",
                "Controlled registration-specific CDL match.",
                details,
                {
                    "reference": reference_key,
                    "source_pages": record.get("source_pages", []),
                    "controlled_document": CDL_LIBRARY_METADATA.get("title"),
                    "controlled_issue_date": CDL_LIBRARY_METADATA.get("issue_date"),
                    "reference_status": CDL_LIBRARY_METADATA.get("status"),
                    "takeoff_approach_penalty_kg_values": takeoff_penalties,
                    "enroute_penalty_kg_values": enroute_penalties,
                    "fuel_penalty_percent_values": fuel_penalties,
                    "applicable_variant_count": len(variants),
                },
            ))
        else:
            findings.append(finding(
                "cddl",
                "unknown",
                f"{item['item_type']} {item['reference']} not verified",
                "The approved configuration-deviation reference is missing.",
                [item["description"], item.get("company_remark") or "No company remark parsed."],
            ))

    candidates = [
        x for x in (
            performance.get("obstacle_rtow_kg"),
            performance.get("landing_rtow_kg"),
            performance.get("structural_rtow_kg"),
        )
        if x is not None
    ]
    controlling = performance.get("controlling_rtow_kg") or (min(candidates) if candidates else None)
    margin = controlling - masses["planned_takeoff_weight_kg"] if controlling is not None else None
    findings.append(finding(
        "performance",
        "warning" if margin is not None and margin < 5000 else "information",
        "Take-off performance summary",
        f"Conditional RTOW margin {format_kg(margin)}.",
        [
            f"Runway {performance.get('runway') or 'not parsed'}; "
            f"condition {performance.get('runway_condition') or 'not parsed'}; "
            f"thrust {performance.get('thrust_setting') or 'not parsed'}; "
            f"flaps {performance.get('flap_setting') if performance.get('flap_setting') is not None else 'not parsed'}.",
            f"Temperature {performance.get('temperature_c')} C; QNH {performance.get('qnh_hpa')} hPa; "
            f"wind {performance.get('wind')}.",
            f"Packs {_switch_state(performance.get('packs_on'))}; "
            f"anti-ice {_switch_state(performance.get('anti_ice_on'))}; "
            f"EOSID {performance.get('eosid') or 'not parsed'}.",
            f"Obstacle RTOW {format_kg(performance.get('obstacle_rtow_kg'))}; "
            f"landing RTOW {format_kg(performance.get('landing_rtow_kg'))}; "
            f"structural RTOW {format_kg(performance.get('structural_rtow_kg'))}.",
            f"Controlling RTOW {format_kg(controlling)}; "
            f"PTOW {format_kg(masses['planned_takeoff_weight_kg'])}; margin {format_kg(margin)}.",
            "The margin is conditional on every stated input and applicable MEL/CDL effect.",
        ],
        {
            "controlling_rtow_kg": controlling,
            "margin_kg": margin,
            "source_references": [
                _cfp_source_reference(
                    flight,
                    list(
                        flight.get("source_evidence", {}).get(
                            "performance_pages",
                            [],
                        )
                    ),
                    "Performance and mass data",
                )
            ],
        },
    ))

    for hazard in _HAZARD_REVIEWS:
        hazard_findings, hazard_warnings = _hazard_review_findings(
            flight.get(hazard["review_key"]) or {},
            hazard,
        )
        findings.extend(hazard_findings)
        warnings.extend(hazard_warnings)

    official_weather_gap = (
        _official_weather_review_finding(flight["official_weather_review"])
        if isinstance(flight.get("official_weather_review"), dict)
        else None
    )
    if official_weather_gap is not None:
        findings.append(official_weather_gap)
        warnings.append(
            "Official public METAR/TAF coverage is incomplete."
        )

    for unread_row in flight.get("alternates_unread") or []:
        if isinstance(unread_row, dict):
            unread_finding, unread_warning = _alternate_row_not_read_finding(unread_row)
            findings.append(unread_finding)
            warnings.append(unread_warning)

    alternate_airports = {a["airport"] for a in flight["alternates"]}
    fuel_enroute_airports = {
        str(item.get("airport") or "").upper()
        for item in flight.get("fuel_enroute_airports") or []
        if str(item.get("airport") or "").strip()
    }
    edto_airports = {a["airport"] for a in flight["edto"]["airports"]}
    edto_periods: dict[str, tuple[datetime, datetime]] = {}
    for airport in flight["edto"]["airports"]:
        starts_at = datetime.fromisoformat(airport["period_start_utc"])
        ends_at = datetime.fromisoformat(airport["period_end_utc"])
        current = edto_periods.get(airport["airport"])
        edto_periods[airport["airport"]] = (
            min(starts_at, current[0]) if current else starts_at,
            max(ends_at, current[1]) if current else ends_at,
        )
    audit_evidence = flight.setdefault("audit_evidence", {})

    weather_audit_records: list[dict[str, Any]] = []
    weather_groups: dict[tuple[str, str, str], dict[str, Any]] = {}
    for record in flight["weather"]:
        location = record["location"]
        phase, window_start, window_end = _weather_role_window(
            flight,
            location,
            alternate_airports,
            edto_periods,
            fuel_enroute_airports,
            str(record.get("source_role") or "") or None,
        )
        raw_text = str(record["text"])
        upper = raw_text.upper()
        significant = bool(
            record.get("record_type") == "SIGMET"
            or re.search(
                r"\b(?:TS|TSRA|VCTS|CB|BKN00\d|OVC00\d|G\d{2,3}KT|"
                r"LLWS|WS|FZRA|FZDZ|SN|BLSN|SEV\s+TURB|SEV\s+ICE)\b",
                upper,
            )
        )
        record_type = str(record.get("record_type") or "weather")
        taf_summary = (
            summarize_taf_for_window(raw_text, window_start, window_end)
            if record_type == "TAF"
            else None
        )
        observed_at = None
        if record.get("observed_at_utc"):
            try:
                observed_at = datetime.fromisoformat(
                    str(record["observed_at_utc"]).replace("Z", "+00:00")
                )
            except ValueError:
                observed_at = None
        metar_summary = (
            summarize_metar_for_window(
                raw_text,
                window_start,
                window_end,
                observed_at=observed_at,
            )
            if record_type == "METAR"
            else None
        )
        evidence_ref = f"weather:{len(weather_audit_records)}"
        weather_audit_records.append({
            "evidence_ref": evidence_ref,
            "source": record.get("source") or "uploaded_cfp",
            "provider": record.get("provider"),
            "location": location,
            "record_type": record_type,
            "raw_text": raw_text,
            "raw_sha256": record.get("raw_sha256"),
            "observed_at_utc": record.get("observed_at_utc"),
            "issue_time_utc": record.get("issue_time_utc"),
            "valid_from_utc": record.get("valid_from_utc"),
            "valid_to_utc": record.get("valid_to_utc"),
            "retrieved_at_utc": record.get("retrieved_at_utc"),
            "source_page": record.get("source_page"),
            "source_role": record.get("source_role"),
            "phase": phase,
            "window_start_utc": window_start.isoformat(),
            "window_end_utc": window_end.isoformat(),
            "selected_for_pilot": (
                phase != "Enroute"
                or significant
                or bool(taf_summary and taf_summary["status"] != "no_significant_overlap")
                or bool(
                    metar_summary
                    and metar_summary["status"] not in {
                        "outside_window",
                        "no_significant_observation",
                    }
                )
            ),
            **(
                {"window_status": taf_summary["status"]}
                if taf_summary
                else {"window_status": metar_summary["status"]}
                if metar_summary
                else {}
            ),
        })
        if (
            phase == "Enroute"
            and not significant
            and taf_summary is None
            and (
                metar_summary is None
                or metar_summary["status"] == "outside_window"
            )
        ):
            continue

        window_label = _utc_window_label(window_start, window_end)
        key = (phase, location, window_label)
        group = weather_groups.setdefault(key, {
            "phase": phase,
            "location": location,
            "utc_window": window_label,
            "window_start": window_start,
            "window_end": window_end,
            "mechanisms": [],
            "taf_summaries": [],
            "taf_sources": [],
            "taf_evidence_refs": [],
            "metar_summaries": [],
            "metar_sources": [],
            "metar_evidence_refs": [],
            "fallback_evidence_refs": [],
            "record_types": [],
            "audit_evidence_refs": [],
            "source_references": [],
            "warning": False,
        })
        source_reference = _weather_source_reference(flight, record)
        if source_reference not in group["source_references"]:
            group["source_references"].append(source_reference)
        if taf_summary:
            group["taf_summaries"].append(taf_summary)
            group["taf_sources"].append({
                **source_reference,
                "raw_text": raw_text,
                "issued_at_utc": taf_summary.get("issued_at_utc") or record.get("issue_time_utc"),
                "valid_from_utc": taf_summary.get("valid_from_utc"),
                "valid_to_utc": taf_summary.get("valid_to_utc"),
            })
            group["taf_evidence_refs"].append(evidence_ref)
        elif metar_summary:
            group["metar_summaries"].append(metar_summary)
            # The observation is a source like a TAF is: a station assessed
            # from a METAR alone publishes which record it was built from
            # (B4 fix round 1, 17 Sep 2026 - the dashboard's Weather block
            # read "Forecast source details unavailable" for exactly this
            # path).
            group["metar_sources"].append({
                **source_reference,
                "record_type": str(record_type or "METAR").upper(),
                "raw_text": raw_text,
                "observed_at_utc": metar_summary.get("observed_at_utc") or record.get("observed_at_utc"),
            })
            group["metar_evidence_refs"].append(evidence_ref)
        else:
            group["fallback_evidence_refs"].append(evidence_ref)
            prepared = concise_weather_finding(finding(
                "weather",
                "warning" if significant else "information",
                f"{phase} weather - {location}",
                "",
                data={
                    "phase": phase,
                    "utc_window": window_label,
                    "raw_text": raw_text,
                },
            ))
            mechanism = str(prepared["data"]["mechanism"])
            for mechanism_part in (
                part.strip()
                for part in mechanism.split(",")
                if part.strip()
            ):
                if mechanism_part not in group["mechanisms"]:
                    group["mechanisms"].append(mechanism_part)
        if record_type not in group["record_types"]:
            group["record_types"].append(record_type)
        group["audit_evidence_refs"].append(evidence_ref)
        group["warning"] = bool(
            group["warning"]
            or significant
            or bool(taf_summary and taf_summary["status"] != "no_significant_overlap")
            or bool(metar_summary and metar_summary["status"] == "pertinent")
        )

    for group in weather_groups.values():
        taf_index = select_taf_for_window(group["taf_summaries"], group["window_start"], group["window_end"])
        taf_summary = group["taf_summaries"][taf_index] if taf_index is not None else None
        if taf_summary:
            status = taf_summary["status"]
            data = {
                "forecast_source": group["taf_sources"][taf_index],
                "phase": group["phase"],
                "location": group["location"],
                "utc_window": group["utc_window"],
                "mechanism": taf_summary["mechanism"],
                "applicable_conditions": taf_summary["applicable_conditions"],
                "applicable_groups": list(taf_summary.get("applicable_groups") or []),
                "timing": taf_summary["timing"],
                "window_status": status,
                "window_status_text": taf_summary["window_status_text"],
                "record_types": group["record_types"],
                "audit_evidence_refs": group["audit_evidence_refs"],
                "source_references": group["source_references"],
            }
            nearby_observation = next(
                (
                    item
                    for item in reversed(group["metar_summaries"])
                    if item["status"] != "outside_window"
                ),
                None,
            )
            if nearby_observation:
                data.update({
                    "observed_conditions": nearby_observation["applicable_conditions"],
                    "observation_time_utc": nearby_observation["observed_at_utc"],
                    "observation_status": nearby_observation["status"],
                })
            if status == "no_significant_overlap":
                data["flight_effect"] = (
                    "No adverse flight effect is indicated for this window by the "
                    "selected TAF."
                )
            elif status == "review_required":
                data["flight_effect"] = (
                    "Forecast coverage is incomplete for this flight phase."
                )
            severity = "information" if status == "no_significant_overlap" else "warning"
        elif group["metar_summaries"]:
            metar_summary = group["metar_summaries"][-1]
            data = {
                # The basis of a METAR-only assessment is published like a
                # TAF source; the publishing surfaces name it as an
                # observation, never as a forecast with a validity.
                "forecast_source": group["metar_sources"][-1],
                "phase": group["phase"],
                "location": group["location"],
                "utc_window": group["utc_window"],
                "mechanism": metar_summary["mechanism"],
                "applicable_conditions": metar_summary["applicable_conditions"],
                "applicable_groups": list(metar_summary.get("applicable_groups") or []),
                "timing": metar_summary["timing"],
                "window_status": metar_summary["status"],
                "window_status_text": metar_summary["window_status_text"],
                "record_types": group["record_types"],
                "audit_evidence_refs": group["audit_evidence_refs"],
                "source_references": group["source_references"],
                "observation_time_utc": metar_summary["observed_at_utc"],
            }
            if metar_summary["status"] == "outside_window":
                data["flight_effect"] = (
                    "This observation is not used to characterize the later flight window."
                )
                severity = "unknown"
            elif metar_summary["status"] == "no_significant_observation":
                data["flight_effect"] = (
                    "No adverse effect is indicated by this nearby observation."
                )
                severity = "information"
            else:
                severity = "warning"
        else:
            mechanisms = list(group["mechanisms"])
            if len(mechanisms) > 1:
                mechanisms = [
                    item
                    for item in mechanisms
                    if item != "no adverse mechanism identified in the parsed station record"
                ]
            data = {
                "phase": group["phase"],
                "location": group["location"],
                "utc_window": group["utc_window"],
                "mechanism": ", ".join(mechanisms),
                "record_types": group["record_types"],
                "audit_evidence_refs": group["audit_evidence_refs"],
                "source_references": group["source_references"],
            }
            severity = "warning" if group["warning"] else "information"
        prepared = concise_weather_finding(finding(
            "weather",
            severity,
            f"{group['phase']} weather - {group['location']}",
            "",
            data=data,
        ))
        findings.append(prepared)

    pilot_weather_evidence_refs = {
        evidence_ref
        for group in weather_groups.values()
        for evidence_ref in (
            group["taf_evidence_refs"]
            if group["taf_summaries"]
            else group["metar_evidence_refs"]
            if group["metar_summaries"]
            else group["fallback_evidence_refs"]
        )
    }
    for audit_record in weather_audit_records:
        audit_record["selected_for_pilot"] = (
            audit_record["evidence_ref"] in pilot_weather_evidence_refs
        )

    audit_evidence["weather"] = {
        "source_record_count": len(flight["weather"]),
        "pilot_facing_group_count": len(weather_groups),
        "records": weather_audit_records,
    }

    notam_audit_records: list[dict[str, Any]] = []
    applicable_notams: list[dict[str, Any]] = []
    for record in flight["notams"]:
        location = record["location"]
        valid_from = datetime.fromisoformat(record["valid_from_utc"])
        valid_to = (
            datetime.fromisoformat(record["valid_to_utc"])
            if record.get("valid_to_utc")
            else datetime.max.replace(tzinfo=timezone.utc)
        )
        role_applicability = [
            _assess_notam_window(record, flight, role, start, end, valid_from, valid_to)
            for role, start, end in _notam_role_windows(
                flight, location, alternate_airports, fuel_enroute_airports,
                str(record.get("source_role") or ""),
            )
        ]
        relevant = [row for row in role_applicability if row["applicability"] in {"active", "review"}]
        assessed = next((row for row in relevant if row["applicability"] == "active"), relevant[0] if relevant else role_applicability[0])
        role = assessed["role"]
        window_start = datetime.fromisoformat(assessed["window_start_utc"])
        window_end = datetime.fromisoformat(assessed["window_end_utc"])
        reference_at = datetime.fromisoformat(assessed["referenceAt"])
        state_at_reference, minutes_delta = assessed["stateAtReference"], assessed["minutesDelta"]
        evidence_ref = f"notam:{len(notam_audit_records)}"
        audit_record = {
            "evidence_ref": evidence_ref,
            "source": "uploaded_cfp",
            "notam_id": record["notam_id"],
            "location": location,
            "category": record["category"],
            "raw_text": record["text"],
            "valid_from_utc": record["valid_from_utc"],
            "valid_to_utc": record.get("valid_to_utc"),
            "schedule": record.get("schedule"),
            "source_page": record.get("source_page"),
            "source_role": record.get("source_role"),
            "role": role,
            "window_start_utc": window_start.isoformat(),
            "window_end_utc": window_end.isoformat(),
            "stateAtReference": state_at_reference,
            "referenceAt": reference_at.isoformat(),
            "minutesDelta": minutes_delta,
            "referenceInterval": assessed.get("referenceInterval"),
            "pilot_status": "pending",
        }
        notam_audit_records.append(audit_record)
        audit_record["role_applicability"] = role_applicability
        audit_record["validity_status"] = assessed["validity_status"]
        audit_record["schedule_status"] = assessed["schedule_status"]
        if not relevant:
            audit_record["pilot_status"] = assessed["applicability"]
            continue
        applicability = assessed["applicability"]
        validity_status = assessed["validity_status"]
        schedule_status = assessed["schedule_status"]
        schedule = record.get("schedule")
        if applicability == "review":
            warnings.append(f"{record['notam_id']}: B/C validity or schedule could not be resolved.")
        approach_affected = _instrument_approach_affected(
            str(record["text"]),
            str(record["category"]),
        )
        approach_condition_review = bool(
            approach_affected
            and _conditional_instrument_approach_impact(str(record["text"]))
        )
        pertinence_rank, pertinence_kind = notam_pertinence(
            str(record["text"]),
            str(record["category"]),
        )
        severity = (
            "critical"
            if approach_affected
            else "information"
            if int(record.get("priority_score") or 0) == 0
            and applicability == "active"
            else "critical"
            if role in {"departure", "destination"} and pertinence_rank <= 1
            else "warning"
        )
        operational_details = taxiway_operational_details(
            str(record["text"]),
            pertinence_kind,
        )
        reviewed_publication = (
            reviewed_publication_for_notam(location, record["notam_id"])
            if operational_details
            else None
        )
        details = [
            *([f"Schedule: {schedule}."] if schedule else []),
            f"Applicable {role} UTC window: {_utc_window_label(window_start, window_end)}.",
            *(["Applicability not resolved."] if applicability == "review" else []),
        ]
        applicable_notams.append(finding(
            "notam",
            severity,
            f"{role.title()} NOTAM {record['notam_id']}",
            _notam_operational_summary(
                str(record["text"]),
                pertinence_kind,
                role,
                applicability,
                category=str(record["category"]),
            ),
            details,
            {
                "role": role,
                "role_applicability": role_applicability,
                "source_role": record.get("source_role"),
                "location": location,
                "notam_id": record["notam_id"],
                "category": record["category"],
                "priority_score": record.get("priority_score", 0),
                "pertinence_rank": pertinence_rank,
                "pertinence_kind": pertinence_kind,
                "approach_affected": approach_affected,
                "approach_condition_review": approach_condition_review,
                "applicability": applicability,
                "validity_status": validity_status,
                "schedule_status": schedule_status,
                "schedule": schedule,
                "valid_from_utc": record["valid_from_utc"],
                "valid_to_utc": record.get("valid_to_utc"),
                "source_page": record.get("source_page"),
                "window_start_utc": window_start.isoformat(),
                "window_end_utc": window_end.isoformat(),
                "stateAtReference": state_at_reference,
                "referenceAt": reference_at.isoformat(),
                "minutesDelta": minutes_delta,
                "referenceInterval": assessed.get("referenceInterval"),
                "raw_text": record["text"],
                "operational_details": operational_details,
                **(
                    {"reviewed_publication": reviewed_publication}
                    if reviewed_publication
                    else {}
                ),
                "audit_evidence_ref": evidence_ref,
                "source_references": [
                    _cfp_source_reference(
                        flight,
                        [record.get("source_page")],
                        "NOTAM package",
                    )
                ],
            },
        ))

    # One assessment per notice (production audit, 19 Sep 2026). Where a notice
    # prints dated runway-closure regimes that can be evaluated at its own
    # reference time, that statement IS its summary - the same function
    # publication applies to an analysis stored by an older build, so a fresh
    # pack and a saved one cannot describe the notice differently.
    applicable_notams = reconcile_runway_closure_findings(applicable_notams, flight)

    unique_applicable_notams: list[dict[str, Any]] = []
    priority_view_notams: list[dict[str, Any]] = []
    seen_notams: dict[tuple[str, ...], dict[str, Any]] = {}
    for item in sorted(applicable_notams, key=notam_sort_key):
        data = item.get("data") or {}
        audit_index = int(str(data["audit_evidence_ref"]).split(":", 1)[1])
        audit_record = notam_audit_records[audit_index]
        semantic_key = pilot_notam_key(item)
        if semantic_key is not None and semantic_key in seen_notams:
            original = seen_notams[semantic_key]
            audit_record["pilot_status"] = "semantic_duplicate"
            audit_record["duplicate_of_notam_id"] = original["data"]["notam_id"]
            continue
        if semantic_key is not None:
            seen_notams[semantic_key] = item
        unique_applicable_notams.append(item)
        if len(priority_view_notams) < 24:
            audit_record["pilot_status"] = "selected"
            priority_view_notams.append(item)
        else:
            # Keep the complete deterministic result available to Level 2 and
            # the API.  Level 1 remains deliberately bounded through
            # prepare_pilot_findings(); "level2_only" is not hidden audit data.
            audit_record["pilot_status"] = "level2_only"
    findings.extend(unique_applicable_notams)
    audit_evidence["notam"] = {
        "source_record_count": len(flight["notams"]),
        "time_applicable_count": len(applicable_notams),
        "pilot_facing_count": len(unique_applicable_notams),
        "priority_view_count": len(priority_view_notams),
        "level2_only_count": sum(
            item["pilot_status"] == "level2_only"
            for item in notam_audit_records
        ),
        "semantic_duplicate_count": sum(
            item["pilot_status"] == "semantic_duplicate"
            for item in notam_audit_records
        ),
        "audit_only_count": sum(
            item["pilot_status"] in {
                "outside_time_window",
                "outside_schedule",
                "semantic_duplicate",
            }
            for item in notam_audit_records
        ),
        "records": notam_audit_records,
    }

    waypoint_by_boundary = {
        w["fir_boundary"]: w
        for w in flight["route_waypoints"]
        if w.get("fir_boundary")
    }
    if _reference_library_is_approved():
        for rule in COMMUNICATION_RULES:
            waypoint = waypoint_by_boundary.get(rule["boundary"])
            if not waypoint:
                continue
            action_time = waypoint["actm_minutes"] - rule["lead"]
            details = [
                f"Boundary ACTM {format_actm(waypoint['actm_minutes'])}; lead {rule['lead']} min.",
                f"Action: {rule['action']}.",
            ]
            if rule.get("frequency"):
                details.append(
                    f"Frequency {rule['frequency']} MHz"
                    + (f"; backup {rule['backup']} MHz." if rule.get("backup") else ".")
                )
            if rule.get("notes"):
                details.append(rule["notes"])
            findings.append(finding(
                "communications",
                "warning",
                f"Early ATC/FIR action before {rule['boundary']}",
                f"ACTM {format_actm(action_time)} - {rule['agency']}.",
                details,
                {
                    "action_actm_minutes": action_time,
                    "reference_library_version": REFERENCE_LIBRARY_METADATA["version"],
                    "reference_status": REFERENCE_LIBRARY_METADATA["status"],
                },
            ))
    elif waypoint_by_boundary:
        boundary_names = sorted(waypoint_by_boundary)
        findings.append(finding(
            "communications",
            "unknown",
            "No approved FIR communication reference",
            "No approved communications reference library is held; early-contact instructions are read from the OFP's own FIR notices.",
            [
                f"OFP route crosses {len(boundary_names)} FIR boundary or boundaries.",
                # ATC-ABSENCE-WORDING (4 Oct 2026): an unapproved library is not the absence of the source's own values.
                "Early ATC / FIR calls lists the instructions identified in the OFP's FIR notices with their printed "
                "frequencies and lead times; the full FIR NOTAM source records keep the other notices. Lead times and "
                "frequencies are not inferred from crossing times.",
            ],
            {
                "reference_status": REFERENCE_LIBRARY_METADATA["status"],
                "source_references": [
                    _cfp_source_reference(
                        flight,
                        [
                            waypoint.get("source_page")
                            for waypoint in waypoint_by_boundary.values()
                        ],
                        "Route FIR boundaries",
                    )
                ],
            },
        ))

    terrain_events = detect_terrain_events(flight["route_waypoints"])
    for index, event in enumerate(terrain_events, start=1):
        end_wp = event["drop"] or event["last_high"]
        maximum = event["maximum"]
        max_msa = maximum["msa_hundreds_ft"]
        findings.append(finding(
            "terrain",
            "warning",
            f"High-MSA event {index}",
            f"ACTM {format_actm(event['first_high']['actm_minutes'])}-"
            f"{format_actm(end_wp['actm_minutes'])}, max {max_msa}*.",
            [
                f"First high-MSA waypoint {event['first_high']['name']}; "
                f"last high-MSA waypoint {event['last_high']['name']}.",
                f"Threshold drop at {event['drop']['name'] if event['drop'] else 'end of route data'}.",
                f"Maximum {max_msa}* ({max_msa * 100:,} ft) at {maximum['name']}, "
                f"ACTM {format_actm(maximum['actm_minutes'])}.",
                *(
                    [f"Profile matching context begins at {event['preceding']['name']}."]
                    if event.get("preceding") else []
                ),
            ],
            {
                "terrain_event_id": event["terrain_event_id"],
                "start_actm_minutes": event["first_high"]["actm_minutes"],
                "end_actm_minutes": end_wp["actm_minutes"],
                "maximum_msa_hundreds_ft": max_msa,
                "source_references": [
                    _cfp_source_reference(
                        flight,
                        [
                            waypoint.get("source_page")
                            for waypoint in (
                                event.get("preceding"),
                                event.get("first_high"),
                                event.get("last_high"),
                                event.get("maximum"),
                                event.get("drop"),
                            )
                            if waypoint
                        ],
                        "Route MSA data",
                    )
                ],
            },
        ))

    for index, event in enumerate(detect_vws_events(flight["route_waypoints"]), start=1):
        end_wp = event["drop"] or event["last_high"]
        maximum = event["maximum"]
        findings.append(finding(
            "vws",
            "warning",
            f"VWS event {index}",
            f"ACTM {format_actm(event['first_high']['actm_minutes'])}-"
            f"{format_actm(end_wp['actm_minutes'])}, maximum {maximum['vws']:03d}.",
            [
                f"First qualifying waypoint {event['first_high']['name']}.",
                f"Last qualifying waypoint {event['last_high']['name']}.",
                f"Maximum at {maximum['name']}, ACTM {format_actm(maximum['actm_minutes'])}.",
                "Threshold is strictly greater than 4.",
            ],
            {
                "start_actm_minutes": event["first_high"]["actm_minutes"],
                "source_references": [
                    _cfp_source_reference(
                        flight,
                        [
                            waypoint.get("source_page")
                            for waypoint in (
                                event.get("first_high"),
                                event.get("last_high"),
                                event.get("maximum"),
                                event.get("drop"),
                            )
                            if waypoint
                        ],
                        "Route wind data",
                    )
                ],
            },
        ))

    matches = sorted(
        match_profiles(flight, terrain_events),
        key=lambda x: (x["event"]["first_high"]["actm_minutes"], x["start_index"]),
    )
    depress_source_loaded = (
        DEPRESS_LIBRARY_METADATA.get("status") == "controlled-index-loaded"
    )
    for index, match in enumerate(matches, start=1):
        event = match["event"]
        profile = match["profile"]
        route_start = match["route_start"]
        route_end = match["route_end"]
        critical = profile["critical"]
        critical_aliases = _profile_aliases(profile, "critical")
        critical_wp = next(
            (
                waypoint
                for waypoint in flight["route_waypoints"]
                if _route_waypoint_name(waypoint) in critical_aliases
            ),
            None,
        )
        maximum = event["maximum"]
        end_wp = event["drop"] or event["last_high"]
        details = [
            f"High-MSA event ACTM {format_actm(event['first_high']['actm_minutes'])}-"
            f"{format_actm(end_wp['actm_minutes'])}.",
            f"Maximum MSA {maximum['msa_hundreds_ft']}* "
            f"({maximum['msa_hundreds_ft'] * 100:,} ft) at {maximum['name']}.",
            f"Published chart route {profile['from']}-{profile['to']}; "
            f"airways {', '.join(profile['airways']) or 'none listed'}.",
            f"Critical point {critical}"
            + (
                f", OFP ACTM {format_actm(critical_wp['actm_minutes'])}."
                if critical_wp
                else "; ACTM not found."
            ),
            f"Controlled profile issue {DEPRESS_LIBRARY_METADATA.get('issue_date')}; "
            f"effective {profile.get('effective_date') or 'not indexed'}.",
        ]
        if profile.get("chart_page"):
            details.append(f"Controlled chart page {profile['chart_page']}.")
        if not match["coverage_complete"]:
            details.append(
                f"Coverage incomplete: {match['uncovered_edge_count']} event route leg(s) remain unmatched."
            )
        if not depress_source_loaded:
            details.append(
                "Controlled profile index is not mounted; this repository-safe "
                "candidate requires review against the approved current source."
            )
        findings.append(finding(
            "depressurisation",
            (
                "warning"
                if match["coverage_complete"] and depress_source_loaded
                else "unknown"
            ),
            f"Profile {index} - {route_start} to {route_end} "
            f"({' / '.join(match['airways']) or 'airway not identified'})",
            (
                f"Proposed depressurisation chart {profile['chart']}; "
                f"critical point {critical}."
                if depress_source_loaded
                else (
                    f"Candidate chart {profile['chart']}; controlled profile "
                    "index unavailable."
                )
            ),
            details,
            {
                "chart_number": profile["chart"],
                "critical_point": critical,
                "terrain_event_id": match["terrain_event_id"],
                "start_actm_minutes": event["first_high"]["actm_minutes"],
                "route_start": route_start,
                "route_end": route_end,
                "coverage_complete": match["coverage_complete"],
                "controlled_issue_date": DEPRESS_LIBRARY_METADATA.get("issue_date"),
                "reference_status": DEPRESS_LIBRARY_METADATA.get("status"),
                "chart_page": profile.get("chart_page"),
                "source_references": [
                    _cfp_source_reference(
                        flight,
                        [
                            waypoint.get("source_page")
                            for waypoint in (
                                event.get("preceding"),
                                event.get("first_high"),
                                event.get("last_high"),
                                event.get("maximum"),
                                event.get("drop"),
                            )
                            if waypoint
                        ],
                        "Route MSA data",
                    ),
                    {
                        "source_type": "controlled_document",
                        "document_title": DEPRESS_LIBRARY_METADATA.get("title"),
                        "revision": DEPRESS_LIBRARY_METADATA.get("issue_date"),
                        "pages": (
                            [profile.get("chart_page")]
                            if profile.get("chart_page")
                            else []
                        ),
                        "section": f"Profile {profile['chart']}",
                        "availability_status": DEPRESS_LIBRARY_METADATA.get("status"),
                    },
                ],
            },
        ))

    matches_by_event: dict[str, list[dict[str, Any]]] = {}
    for match in matches:
        matches_by_event.setdefault(match["terrain_event_id"], []).append(match)
    coverage_scope = str(
        DEPRESS_LIBRARY_METADATA.get("coverage_scope") or "not stated"
    )
    for event in terrain_events:
        event_id = event["terrain_event_id"]
        event_matches = matches_by_event.get(event_id, [])
        exact_profile_confirmed = bool(
            depress_source_loaded
            and any(match["coverage_complete"] for match in event_matches)
        )
        if exact_profile_confirmed:
            continue

        first_high = event["first_high"]
        last_high = event["last_high"]
        threshold_drop = event.get("drop")
        context_start = event.get("preceding") or first_high
        event_end = threshold_drop or last_high
        candidate_charts = sorted(
            {
                str(match["profile"].get("chart") or "")
                for match in event_matches
                if match["profile"].get("chart")
            }
        )
        reference_status = "partial" if depress_source_loaded else "unavailable"
        summary = (
            "No exact profile confirmed from controlled partial issue."
            if depress_source_loaded and coverage_scope == "partial_issue"
            else (
                "No exact profile confirmed from controlled index."
                if depress_source_loaded
                else (
                    "No exact profile confirmed because the controlled profile "
                    "index is unavailable."
                )
            )
        )
        details = [
            f"High-MSA event ACTM {format_actm(first_high['actm_minutes'])}-"
            f"{format_actm(event_end['actm_minutes'])}.",
            f"Validated exposure boundary {first_high['name']}-{last_high['name']}; "
            f"profile matching context begins at {context_start['name']}.",
        ]
        if candidate_charts:
            details.append(
                "Candidate chart coverage is incomplete: "
                f"{', '.join(candidate_charts)}."
            )
        details.append(
            (
                f"Controlled profile coverage scope is {coverage_scope}; no "
                "complete endpoint, airway and effectivity match was found."
                if depress_source_loaded
                else "The approved controlled profile index is not mounted."
            )
        )
        findings.append(finding(
            "depressurisation",
            "unknown",
            f"Profile unresolved - {first_high['name']} to {last_high['name']}",
            summary,
            details,
            {
                "terrain_event_id": event_id,
                "confirmed": False,
                "coverage_complete": False,
                "reference_status": reference_status,
                "controlled_library_status": DEPRESS_LIBRARY_METADATA.get("status"),
                "controlled_index_loaded": depress_source_loaded,
                "coverage_scope": coverage_scope,
                "candidate_chart_numbers": candidate_charts,
                "start_actm_minutes": first_high["actm_minutes"],
                "end_actm_minutes": event_end["actm_minutes"],
                "profile_context_start_waypoint": context_start["name"],
                "first_high_waypoint": first_high["name"],
                "last_high_waypoint": last_high["name"],
                "threshold_drop_waypoint": (
                    threshold_drop["name"] if threshold_drop else None
                ),
                "source_references": [
                    _cfp_source_reference(
                        flight,
                        [
                            waypoint.get("source_page")
                            for waypoint in (
                                event.get("preceding"),
                                first_high,
                                last_high,
                                event.get("maximum"),
                                threshold_drop,
                            )
                            if waypoint
                        ],
                        "Route MSA data",
                    ),
                    {
                        "source_type": "controlled_document",
                        "document_title": DEPRESS_LIBRARY_METADATA.get("title"),
                        "revision": DEPRESS_LIBRARY_METADATA.get("issue_date"),
                        "pages": [],
                        "section": "Depressurisation profile index",
                        "availability_status": DEPRESS_LIBRARY_METADATA.get("status"),
                        "coverage_scope": coverage_scope,
                    },
                ],
            },
        ))

    if terrain_events and not matches:
        findings.append(finding(
            "depressurisation",
            "unknown",
            "High terrain detected but no profile matched",
            "No controlled profile is confirmed; manual chart-index review is required.",
            [
                (
                    "The approved controlled profile index is loaded, but no "
                    "complete applicable match was found."
                    if depress_source_loaded
                    else "The approved controlled profile index is not mounted."
                )
            ],
            {
                "reference_status": DEPRESS_LIBRARY_METADATA.get("status"),
                "controlled_index_loaded": depress_source_loaded,
                "terrain_event_ids": [
                    event["terrain_event_id"]
                    for event in terrain_events
                ],
            },
        ))

    edto = flight["edto"]
    sectors = edto_sectors(edto)
    if sectors:
        sector_summary = "; ".join(
            f"S{sector.get('number', index)} "
            f"{format_actm(sector.get('entry_actm_minutes'))}-"
            f"{format_actm(sector.get('exit_actm_minutes'))}"
            for index, sector in enumerate(sectors, start=1)
        )
        details = []
        for index, sector in enumerate(sectors, start=1):
            number = sector.get("number", index)
            line = (
                f"Sector {number}: entry ACTM "
                f"{format_actm(sector.get('entry_actm_minutes'))}; exit ACTM "
                f"{format_actm(sector.get('exit_actm_minutes'))}."
            )
            if sector.get("etp_actm_minutes"):
                line += (
                    " ETP ACTM "
                    + ", ".join(
                        format_actm(value)
                        for value in sector["etp_actm_minutes"]
                    )
                    + "."
                )
            details.append(line)
        details.extend(
            f"{a['airport']} checked {datetime.fromisoformat(a['period_start_utc']):%H%MZ}-"
            f"{datetime.fromisoformat(a['period_end_utc']):%H%MZ}, RWY {a['runway']} "
            f"{a['approach']}, minima {a['minima']}."
            for a in edto["airports"]
        )
        findings.append(finding(
            "edto",
            "information",
            "EDTO checked-period summary",
            f"ACTM {sector_summary}.",
            details,
            {
                "start_actm_minutes": sectors[0]["entry_actm_minutes"],
                "sectors": [
                    {
                        "number": sector.get("number", index),
                        "entry_actm_minutes": sector.get("entry_actm_minutes"),
                        "exit_actm_minutes": sector.get("exit_actm_minutes"),
                        "etp_actm_minutes": list(
                            sector.get("etp_actm_minutes") or []
                        ),
                    }
                    for index, sector in enumerate(sectors, start=1)
                ],
                "source_references": [
                    _cfp_source_reference(
                        flight,
                        [flight.get("source_evidence", {}).get("edto_page")],
                        "EDTO information",
                    )
                ],
            },
        ))

    timeline_items: list[tuple[int, str, str]] = []
    for item in findings:
        if item["engine"] in {"vaa", "communications", "terrain", "vws", "depressurisation", "edto"}:
            data = item.get("data", {})
            actm = data.get("action_actm_minutes")
            if actm is None:
                actm = data.get("start_actm_minutes")
            if actm is not None:
                timeline_items.append((actm, item["title"], item["summary"]))
    if flight.get("bobcat"):
        waypoint = next(
            (w for w in flight["route_waypoints"] if w["name"] == flight["bobcat"]["waypoint"]),
            None,
        )
        if waypoint:
            timeline_items.append((
                waypoint["actm_minutes"],
                f"BOBCAT {waypoint['name']}",
                f"FL{flight['bobcat']['flight_level']} CTO "
                f"{datetime.fromisoformat(flight['bobcat']['cto_utc']):%H%MZ}.",
            ))
    timeline_items.sort(key=lambda x: x[0])
    findings.append(finding(
        "timeline",
        "information",
        "Route-critical ACTM timeline",
        f"{len(timeline_items)} ordered operational events.",
        [f"ACTM {format_actm(a)} - {b}: {c}" for a, b, c in timeline_items[:24]],
    ))

    calculated_destination = (
        fuel["fuel_in_tanks_kg"] - fuel["taxi_fuel_kg"] - fuel["trip_fuel_kg"]
    )
    difference = calculated_destination - fuel["planned_destination_fuel_kg"]
    findings.append(finding(
        "qa",
        "information" if difference == 0 else "warning",
        "Destination fuel reconciliation",
        f"Calculated {format_kg(calculated_destination)}; "
        f"stated {format_kg(fuel['planned_destination_fuel_kg'])}; "
        f"difference {difference:+,} kg.",
    ))
    findings.append(finding(
        "qa",
        "information",
        "MSA 100* threshold handling",
        "A starred MSA qualifies; without an asterisk only numeric values strictly above 100 qualify.",
    ))
    return findings, warnings

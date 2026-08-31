from __future__ import annotations

import re
from typing import Any


_SEVERITY_RANK = {"information": 0, "unknown": 1, "warning": 2, "critical": 3}
_ROLE_RANK = {
    "departure": 0,
    "destination": 1,
    "destination alternate": 2,
    "EDTO": 3,
    "informational": 4,
}
_CLOSURE_WORD = r"(?:CLSD|CLOSED|NOT\s+AVBL|NOT\s+AVAILABLE|SUSPENDED)"
_UNAVAILABLE_WORD = (
    rf"(?:{_CLOSURE_WORD}|U/S|UNSERVICEABLE|UNSERVICEABILITY|WITHDRAWN)"
)
_NEGATED_UNAVAILABLE_PREFIX = re.compile(
    r"(?:\bWITHOUT|\bNO|\bNOT)(?:\s+[A-Z0-9/-]+){0,5}\s*$"
)
_RUNWAY_ID = r"(?:RWY|RUNWAY)\s+\d{1,2}[LCR]?(?:/\d{1,2}[LCR]?)?"
_TAXIWAY_ID = r"(?:TWY|TAXIWAY)\s+[A-Z0-9][A-Z0-9/-]*"
_APPROACH_SYSTEM = (
    r"(?:(?:APPROACH|APCH)(?!\s+(?:LGT(?:S)?|LIGHT(?:S|ING)?))|"
    r"ILS|LOC|LOCALIZER|GLIDE\s*PATH|GLIDESLOPE|"
    r"DME|VOR|NDB|RNP|PAPI|OCA|OCH|MINIMA)"
)
_LIGHTING = (
    r"(?:LGT|LIGHT|LIGHTS|LIGHTING|RCLL|RTHL|RTZL|RENL|HIRL|MIRL|LIRL|"
    r"TKOF\s+HOLD\s+LGT|LEAD\s+(?:ON|OFF)\s+LGT)"
)
_PREFIXED_NOTAM_REFERENCE = re.compile(
    r"(?<![A-Z0-9])\d+(?P<reference>[A-Z]{1,3}\d{2,5}/\d{2})\b",
    re.IGNORECASE,
)
_APPLICABLE_WINDOW_SUFFIX = re.compile(
    r"\s+during the applicable "
    r"(?:departure|destination|alternate|EDTO|flight) window\.?$",
    re.IGNORECASE,
)


def normalize_notam_references(value: Any) -> str:
    """Remove parser-added numeric prefixes from pilot-facing NOTAM IDs."""

    return _PREFIXED_NOTAM_REFERENCE.sub(
        lambda match: match.group("reference"),
        str(value or ""),
    )


def _canonical_notam_identity(value: Any) -> str:
    """Return one pilot-facing identity for parser-indexed NOTAM labels."""

    normalized = normalize_notam_references(value).strip().upper()
    return normalized if re.fullmatch(r"[A-Z]{1,3}\d{2,5}/\d{2}", normalized) else ""


def pilot_notam_condition(value: Any) -> str:
    """Keep the condition separate from its reference-time applicability."""

    normalized = normalize_notam_references(value)
    return _APPLICABLE_WINDOW_SUFFIX.sub(".", normalized)


def notam_pertinence(text: str, category: str = "") -> tuple[int, str]:
    """Return a stable pilot-facing rank and label for an applicable NOTAM.

    Lower ranks are more pertinent.  The ordering intentionally puts complete
    airport/runway/approach-system unavailability ahead of ground-movement
    restrictions, and ground-movement restrictions ahead of obstacles.
    """

    upper = f"{category} {text}".upper()
    unavailable = any(
        not _NEGATED_UNAVAILABLE_PREFIX.search(upper[:match.start()])
        for match in re.finditer(rf"\b{_UNAVAILABLE_WORD}\b", upper)
    )
    runway_match = re.search(rf"\b{_RUNWAY_ID}\b", upper)
    taxiway_match = re.search(rf"\b{_TAXIWAY_ID}\b", upper)
    runway = bool(runway_match)
    approach = bool(
        re.search(rf"\b{_APPROACH_SYSTEM}\b", upper)
    )
    taxiway = bool(taxiway_match or re.search(r"\b(?:TAXILANE|STOP\s*BAR)\b", upper))
    lighting = bool(re.search(rf"\b{_LIGHTING}\b", upper))
    lighting_runway = bool(
        runway
        or (
            lighting
            and re.search(
                r"\b(?:RWY|RUNWAY)\s*\d{1,2}[LCR]?(?:/\d{1,2}[LCR]?)?\b",
                upper,
            )
        )
    )
    obstacle = bool(re.search(r"\b(?:OBST|OBSTACLES?|CRANES?|POLES?)\b", upper))

    airport_closure = bool(
        re.search(
            rf"\b(?:AD(?:\s+AP)?|AIRPORT|AERODROME)\s+(?:IS\s+|WILL\s+BE\s+)?{_CLOSURE_WORD}\b",
            upper,
        )
    )
    direct_runway_closure = re.search(
        rf"\b{_RUNWAY_ID}\s+(?:WILL\s+BE\s+|IS\s+)?{_CLOSURE_WORD}\b",
        upper,
    )
    runway_is_other_subject_qualifier = bool(
        direct_runway_closure
        and re.search(
            r"\b(?:APCH\s+LGT|APPROACH\s+LIGHTS?|PAPI|SFL|"
            r"SEQUENCE(?:D)?\s+(?:FLASHING|FLG)\s+(?:LGT|LIGHTS?)|"
            r"LGT|LIGHTS?)\s+(?:FOR\s+)?$",
            upper[:direct_runway_closure.start()],
        )
    )
    runway_state_is_subordinate_condition = bool(
        direct_runway_closure
        and re.search(
            r"\b(?:ONLY\s+)?WHEN\s*$",
            upper[:direct_runway_closure.start()],
        )
    )
    runway_closure = bool(
        (
            direct_runway_closure
            and not runway_is_other_subject_qualifier
            and not runway_state_is_subordinate_condition
        )
        or re.search(rf"\bCLOSURE\s+OF\s+{_RUNWAY_ID}\b", upper)
    )
    taxiway_closure = bool(
        re.search(
            rf"\b{_TAXIWAY_ID}\s+(?:WILL\s+BE\s+|IS\s+)?{_CLOSURE_WORD}\b",
            upper,
        )
        or re.search(rf"\bCLOSURE\s+OF\s+{_TAXIWAY_ID}\b", upper)
        or (
            taxiway_match
            and (not runway_match or taxiway_match.start() < runway_match.start())
            and re.search(rf"\b{_CLOSURE_WORD}\b", upper[taxiway_match.start():])
        )
    )
    stand_or_apron = bool(
        re.search(r"\b(?:ACFT\s+STAND|STAND|APRON|APN|RAMP|GATE)\b", upper)
    )
    stand_or_apron_closure = bool(
        stand_or_apron
        and re.search(rf"\b(?:CLOSURE|{_CLOSURE_WORD})\b", upper)
    )
    primary_taxiway = bool(
        taxiway_match
        and (not runway_match or taxiway_match.start() < runway_match.start())
    )

    if stand_or_apron_closure:
        return 5, "apron_stand_closure"
    if airport_closure:
        return 0, "airport_closure"
    if unavailable and approach:
        return 2, "approach_navaid_closure"
    if taxiway_closure and primary_taxiway:
        return 4, "taxiway_closure"
    if runway_closure:
        return 1, "runway_closure"
    if unavailable and taxiway and lighting and primary_taxiway:
        return 6, "taxiway_restriction"
    if unavailable and lighting and (
        lighting_runway
        or re.search(
            r"\b(?:(?:APCH|APPROACH)\s+(?:LGT|LIGHT(?:S|ING)?)|"
            r"SEQUENCE(?:D)?\s+(?:FLASHING|FLG)\s+(?:LGT|LIGHTS?))\b",
            upper,
        )
    ):
        return 3, "runway_lighting_restriction"
    if obstacle:
        return 8, "obstacle"
    if runway or approach:
        return 3, "runway_approach_restriction"
    if taxiway_closure:
        return 4, "taxiway_closure"
    if taxiway:
        return 6, "taxiway_restriction"
    return 7, "other_operational"


def _canonical_notam_text(value: str) -> str:
    upper = value.upper()
    replacements = (
        (r"\bRUNWAY\b", "RWY"),
        (r"\bTAXIWAY\b", "TWY"),
        (r"\bCLOSED\b", "CLSD"),
        (r"\bUNSERVICEABLE\b", "U/S"),
        (r"\bNOT AVAILABLE\b", "NOT AVBL"),
    )
    for pattern, replacement in replacements:
        upper = re.sub(pattern, replacement, upper)
    upper = re.sub(r"\b[A-Z0-9]+/\d{2}\b", " ", upper)
    upper = re.sub(r"[^A-Z0-9/]+", " ", upper)
    return " ".join(upper.split())


def semantic_notam_key(item: dict[str, Any]) -> tuple[str, ...] | None:
    """Build a semantic duplicate key without collapsing distinct schedules.

    Older/tests-only findings may not carry raw evidence.  Those are kept
    separate rather than guessed to be duplicates.
    """

    data = item.get("data") or {}
    raw_text = str(data.get("raw_text") or "").strip()
    if not raw_text:
        return None
    return (
        str(data.get("role") or "informational"),
        str(data.get("location") or ""),
        str(data.get("pertinence_kind") or ""),
        _canonical_notam_text(raw_text),
        _canonical_notam_text(str(data.get("schedule") or "")),
        str(data.get("valid_from_utc") or ""),
        str(data.get("valid_to_utc") or ""),
    )


def pilot_notam_key(item: dict[str, Any]) -> tuple[str, ...] | None:
    """Build the operational duplicate key used only for the pilot view.

    The immutable audit keeps every source record.  Once records have passed
    the existing time and schedule checks, multiple notices with the same
    operational subject, phase and checked window collapse to one concise
    pilot-facing finding.
    """

    data = item.get("data") or {}
    if not str(data.get("raw_text") or "").strip():
        return None
    if str(data.get("pertinence_kind") or "") not in {
        "runway_lighting_restriction",
        "taxiway_restriction",
        "apron_stand_closure",
    }:
        return semantic_notam_key(item)
    return (
        str(data.get("role") or "informational"),
        str(data.get("location") or ""),
        str(data.get("pertinence_kind") or ""),
        str(data.get("applicability") or ""),
        str(data.get("window_start_utc") or ""),
        str(data.get("window_end_utc") or ""),
        _canonical_notam_text(str(item.get("summary") or "")),
    )


def notam_sort_key(item: dict[str, Any]) -> tuple[int, int, int, int, int, int, str]:
    data = item.get("data") or {}
    rank = data.get("pertinence_rank")
    if rank is None:
        rank, _ = notam_pertinence(
            f"{item.get('title', '')} {item.get('summary', '')}",
            str(data.get("category") or ""),
        )
    role = str(data.get("role") or "informational")
    # Departure and destination records must not compete on equal terms with
    # alternates, EDTO stations and informational locations.  The previous
    # global rank-first order could fill the 24-item pilot view with alternate
    # runway records before a departure taxiway closure was reached.
    primary_airport_band = 0 if role in {"departure", "destination"} else 1
    printed_notam_id = str(data.get("notam_id") or "").strip().upper()
    canonical_notam_id = _canonical_notam_identity(printed_notam_id)
    parser_prefix_penalty = int(
        bool(canonical_notam_id) and canonical_notam_id != printed_notam_id
    )
    return (
        primary_airport_band,
        int(rank),
        _ROLE_RANK.get(role, 5),
        -_SEVERITY_RANK.get(str(item.get("severity") or "information"), 0),
        -int(data.get("priority_score") or 0),
        parser_prefix_penalty,
        str(item.get("title") or ""),
    )


def select_pertinent_notams(
    findings: list[dict[str, Any]],
    *,
    limit: int,
) -> list[dict[str, Any]]:
    """Deduplicate, rank, and bound pilot-facing NOTAM findings."""

    ordered = sorted(findings, key=notam_sort_key)
    selected: list[dict[str, Any]] = []
    seen: set[tuple[str, ...]] = set()
    seen_notam_ids: set[tuple[str, str, str]] = set()
    for item in ordered:
        data = item.get("data") or {}
        canonical_notam_id = _canonical_notam_identity(data.get("notam_id"))
        notam_identity = (
            str(data.get("role") or "informational"),
            str(data.get("location") or "").upper(),
            canonical_notam_id,
        )
        if canonical_notam_id and notam_identity in seen_notam_ids:
            continue
        key = pilot_notam_key(item)
        if key is not None and key in seen:
            continue
        if canonical_notam_id:
            seen_notam_ids.add(notam_identity)
        if key is not None:
            seen.add(key)
        selected.append(item)
        if len(selected) >= limit:
            break
    return selected


def _weather_mechanism_from_text(text: str) -> str:
    upper = text.upper()
    mechanisms: list[str] = []
    checks = (
        (r"\b(?:TS|TSRA|VCTS|CB)\b", "convection / thunderstorms"),
        (r"\b(?:LLWS|WS)\b", "wind shear"),
        (r"\bG\d{2,3}KT\b", "gusty surface wind"),
        (r"\b(?:BKN|OVC)00\d\b", "low ceiling"),
        (r"\b(?:FG|BR)\b|(?<!\d)(?:0[0-4]\d{2})(?!\d)", "reduced visibility"),
        (r"\b(?:FZRA|FZDZ|SN|BLSN)\b", "freezing or winter precipitation"),
        (r"\b(?:SEV|MOD)\s+(?:TURB|ICE)\b", "turbulence or icing"),
    )
    for pattern, label in checks:
        if re.search(pattern, upper) and label not in mechanisms:
            mechanisms.append(label)
    if mechanisms:
        return ", ".join(mechanisms)
    if "CAVOK" in upper or "NOSIG" in upper:
        return "no adverse mechanism identified in the parsed station record"
    return "weather condition requires operational interpretation"


def _weather_effect(phase: str, mechanism: str) -> str:
    lower = mechanism.lower()
    if "no adverse mechanism" in lower:
        return "No adverse weather mechanism was identified in the parsed station record."
    if "requires operational interpretation" in lower:
        return (
            "Flight-specific operational effect is not stated by the source; "
            "review required."
        )
    return (
        "Flight-specific operational effect is not stated by the source; "
        "review required."
    )


def concise_weather_finding(item: dict[str, Any]) -> dict[str, Any]:
    """Return a copy whose pilot-facing text is operational, never raw OPMET."""

    copied = dict(item)
    data = dict(item.get("data") or {})
    phase = str(data.get("phase") or "Enroute")
    window = str(data.get("utc_window") or "UTC window not resolved")
    mechanism = str(data.get("mechanism") or "").strip()
    if not mechanism:
        mechanism = _weather_mechanism_from_text(
            str(data.get("raw_text") or item.get("summary") or "")
        )
    effect = str(data.get("flight_effect") or "").strip() or _weather_effect(
        phase,
        mechanism,
    )
    window_status = str(data.get("window_status") or "").strip()
    window_status_text = str(data.get("window_status_text") or "").strip()
    applicable_conditions = str(data.get("applicable_conditions") or "").strip()
    observed_conditions = str(data.get("observed_conditions") or "").strip()
    observation_time = str(data.get("observation_time_utc") or "").strip()
    timing = str(data.get("timing") or "").strip()
    if window_status_text:
        copied["summary"] = " ".join(
            part
            for part in (
                f"{phase}; {window}: {window_status_text}",
                (
                    f"Applicable conditions: {applicable_conditions}."
                    if applicable_conditions
                    else ""
                ),
                f"Timing: {timing}" if timing else "",
                (
                    f"Nearby observation: {observed_conditions} at {observation_time}."
                    if observed_conditions and observation_time
                    else ""
                ),
                f"Flight effect: {effect}",
            )
            if part
        )
    else:
        copied["summary"] = f"{phase}; {window}: {mechanism}. {effect}"
    copied["details"] = [
        f"Phase: {phase}.",
        f"UTC window: {window}.",
        *(
            [f"Applicable conditions: {applicable_conditions}."]
            if applicable_conditions
            else []
        ),
        *([f"Timing: {timing}"] if timing else []),
        *(
            [f"Nearby observation: {observed_conditions} at {observation_time}."]
            if observed_conditions and observation_time
            else []
        ),
        f"Operational mechanism: {mechanism}.",
        f"Flight effect: {effect}",
        *(
            [f"Window status: {window_status_text}"]
            if window_status_text
            else []
        ),
    ]
    data.update(
        {
            "phase": phase,
            "utc_window": window,
            "mechanism": mechanism,
            "flight_effect": effect,
        }
    )
    copied["data"] = data
    return copied


def select_concise_weather(
    findings: list[dict[str, Any]],
    *,
    limit: int = 12,
) -> list[dict[str, Any]]:
    """Collapse repeated OPMET records into unique operational weather effects."""

    selected: list[dict[str, Any]] = []
    seen: set[tuple[str, ...]] = set()
    for original in findings:
        item = concise_weather_finding(original)
        data = item.get("data") or {}
        key = (
            str(data.get("phase") or ""),
            str(data.get("location") or ""),
            str(data.get("utc_window") or ""),
            str(data.get("mechanism") or ""),
            str(data.get("flight_effect") or ""),
        )
        if key in seen:
            continue
        seen.add(key)
        selected.append(item)
        if len(selected) >= limit:
            break
    return selected


def prepare_pilot_findings(
    findings: list[dict[str, Any]],
    *,
    notam_limit: int,
) -> list[dict[str, Any]]:
    """Prepare a bounded pilot-facing view while leaving audit findings intact."""

    notams = select_pertinent_notams(
        [item for item in findings if item.get("engine") == "notam"],
        limit=notam_limit,
    )
    selected_notam_ids = {id(item) for item in notams}
    weather = select_concise_weather(
        [item for item in findings if item.get("engine") == "weather"],
    )
    weather_added = False
    prepared: list[dict[str, Any]] = []
    for item in findings:
        if item.get("engine") == "notam":
            if id(item) in selected_notam_ids:
                prepared.append(item)
            continue
        if item.get("engine") == "weather":
            if not weather_added:
                prepared.extend(weather)
                weather_added = True
            continue
        prepared.append(item)
    return prepared


__all__ = [
    "concise_weather_finding",
    "notam_pertinence",
    "notam_sort_key",
    "pilot_notam_key",
    "prepare_pilot_findings",
    "select_concise_weather",
    "select_pertinent_notams",
    "semantic_notam_key",
]

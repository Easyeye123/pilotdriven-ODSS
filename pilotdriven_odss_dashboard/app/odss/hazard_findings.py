from __future__ import annotations

from typing import Any

from .constants import format_actm


_HAZARD_LABELS = {
    "embedded_thunderstorm": "Embedded thunderstorms",
    "obscured_thunderstorm": "Obscured thunderstorms",
    "frequent_thunderstorm": "Frequent thunderstorms",
    "squall_line_thunderstorm": "Squall-line thunderstorms",
    "severe_thunderstorm": "Severe thunderstorms",
    "tropical_cyclone": "Tropical cyclone",
    "volcanic_ash": "Volcanic ash",
    "severe_turbulence": "Severe turbulence",
    "severe_clear_air_turbulence": "Severe clear-air turbulence",
    "severe_icing": "Severe icing",
    "severe_mountain_wave": "Severe mountain wave",
    "heavy_duststorm": "Heavy duststorm",
    "heavy_sandstorm": "Heavy sandstorm",
    "radioactive_cloud": "Radioactive cloud",
}


def _finding(
    engine: str,
    severity: str,
    title: str,
    summary: str,
    details: list[str] | None = None,
    data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "rule_id": "HAZARD-GATE-1.0",
        "engine": engine,
        "severity": severity,
        "title": title,
        "summary": summary,
        "details": details or [],
        "data": data or {},
    }


def _segment_text(segment: dict[str, Any]) -> str:
    start = segment.get("start_actm_minutes")
    end = segment.get("end_actm_minutes")
    actm = (
        f"ACTM {format_actm(int(start))}-{format_actm(int(end))}"
        if start is not None and end is not None
        else f"{segment.get('segment_start_utc') or segment.get('start_utc') or '--'} to "
        f"{segment.get('segment_end_utc') or segment.get('end_utc') or '--'}"
    )
    route_from = segment.get("from") or segment.get("route_from") or "--"
    route_to = segment.get("to") or segment.get("route_to") or "--"
    level = segment.get("planned_flight_level")
    return f"{route_from}-{route_to}, {actm}" + (f", FL{level}" if level is not None else "")


def apply_hazard_gate_to_findings(
    flight: dict[str, Any],
    findings: list[dict[str, Any]],
    warnings: list[str],
) -> tuple[list[dict[str, Any]], list[str]]:
    """Replace legacy weather promotion with the deterministic hazard gate.

    Raw station weather and source SIGMET text remain Level 2 evidence.  They do
    not become Level 1 alerts merely because they contain strings such as CB,
    TS, gusts, CAVOK or a named synoptic feature.
    """
    assessment = flight.get("operational_hazard_assessment")
    if not isinstance(assessment, dict):
        return findings, warnings

    output: list[dict[str, Any]] = []
    for original in findings:
        engine = original.get("engine")
        # VA and TC are represented once through the combined gate.  This also
        # collapses several unavailable-source messages into one coverage item.
        if engine in {"vaa", "tropical_cyclone"}:
            continue
        if engine == "weather":
            evidence = dict(original)
            evidence["engine"] = "weather_evidence"
            evidence["severity"] = "information"
            data = dict(evidence.get("data") or {})
            data.update(
                suppress_level1=True,
                evidence_only=True,
                promotion_authority="operational_hazard_assessment",
            )
            evidence["data"] = data
            output.append(evidence)
            continue
        output.append(original)

    for item in assessment.get("promoted") or []:
        hazard_type = str(item.get("hazard_type") or "meteorological_hazard")
        label = _HAZARD_LABELS.get(hazard_type, hazard_type.replace("_", " ").title())
        segments = item.get("route_segments") or []
        segment_details = [_segment_text(segment) for segment in segments[:6]]
        output.append(_finding(
            "weather",
            "warning",
            f"{label} meets the highlight gate",
            (
                "Authoritative source, flight-window, route and planned-level "
                "applicability were verified."
            ),
            [
                *segment_details,
                f"Authority: {item.get('authority') or 'not identified'}.",
                f"Product: {item.get('hazard_id') or '--'}.",
                "Highlight colour is amber. Red is reserved for a separately verified limit violation or unavailable avoidance margin.",
            ],
            {
                "hazard_gate": True,
                "hazard_type": hazard_type,
                "hazard_id": item.get("hazard_id"),
                "highlight_colour": "amber",
                "start_actm_minutes": (
                    (segments[0] or {}).get("start_actm_minutes")
                    if segments else None
                ),
                "decision_supported": "Review the verified hazard at the identified route/time/level window.",
                "reason_codes": item.get("reason_codes") or [],
            },
        ))

    monitor = assessment.get("monitor") or []
    if monitor:
        output.append(_finding(
            "hazards",
            "information",
            "Meteorological items retained for Level 2 monitoring",
            f"{len(monitor)} item(s) did not meet the Level 1 highlight gate.",
            [
                f"{item.get('hazard_id') or '--'}: {', '.join(item.get('reason_codes') or ['review required'])}."
                for item in monitor[:20]
            ],
            {
                "suppress_level1": True,
                "monitor_count": len(monitor),
                "decision_supported": "Preserve evidence without overstating operational significance.",
            },
        ))

    suppressed = assessment.get("suppressed") or []
    if suppressed:
        output.append(_finding(
            "hazards",
            "information",
            "Meteorological products suppressed by applicability checks",
            f"{len(suppressed)} product(s) were not promoted.",
            [
                f"{item.get('hazard_id') or '--'}: {', '.join(item.get('reason_codes') or ['not applicable'])}."
                for item in suppressed[:30]
            ],
            {
                "suppress_level1": True,
                "suppressed_count": len(suppressed),
                "decision_supported": "Show why a source product was excluded from the pertinent brief.",
            },
        ))

    gaps = assessment.get("coverage_gaps") or []
    if gaps:
        output.append(_finding(
            "hazards",
            "information",
            "Meteorological hazard coverage incomplete",
            (
                "No missing source has been interpreted as NIL, and no coverage "
                "gap has been presented as an active hazard."
            ),
            [str(item.get("label") or item.get("code") or "Coverage incomplete") for item in gaps],
            {
                "suppress_level1": True,
                "coverage_gap": True,
                "coverage_gap_count": len(gaps),
                "decision_supported": "Identify which hazard classes still require an authoritative source check.",
            },
        ))

    if not (assessment.get("promoted") or []):
        output.append(_finding(
            "hazards",
            "information",
            "No significant meteorological hazard promoted",
            str(assessment.get("level2_statement") or "No significant hazard met the deterministic highlight gate."),
            [
                f"Monitored: {(assessment.get('counts') or {}).get('monitor', 0)}.",
                f"Suppressed as not applicable: {(assessment.get('counts') or {}).get('suppressed', 0)}.",
                f"Coverage gaps: {(assessment.get('counts') or {}).get('coverage_gaps', 0)}.",
            ],
            {
                "suppress_level1": True,
                "no_significant_hazard": True,
                "decision_supported": "Avoid an alert when no product meets the highlight constraints.",
            },
        ))

    return output, warnings


__all__ = ["apply_hazard_gate_to_findings"]

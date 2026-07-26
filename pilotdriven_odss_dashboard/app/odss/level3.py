from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from ..database import (
    get_or_create_policy_snapshot,
    get_policy_snapshot,
    list_level3_answers,
    record_audit_event,
)
from .finding_ids import assign_finding_ids
from .policy_index import policy_snapshot_from_env
from .report_quality import assert_report_quality


PILOT_DECISION_STATEMENT = (
    "Pilot remains the final authority. Level 3 presents only applicable cited "
    "policy support; it does not issue an operational verdict or instruction."
)
_ACTIONABLE_SEVERITIES = {"critical", "warning", "unknown", "caution", "review"}
_MARGIN_ENGINES = {"performance", "weather", "edto", "notam"}
_LEDGER_LABELS = {
    "normalized-flight-input": "Flight input",
    "approved-policy-library": "Approved company policy",
    "finding-policy-coverage": "Pertinent ODSS findings",
    "weather-coverage": "Weather and advisory coverage",
    "licensed-chart-minima": "Approach chart and minima",
    "margin-source-validation": "Proposed policy-based margins",
    "margin-inputs": "Policy-based margins",
}
_LEDGER_REVIEW_ACTIONS = {
    "normalized-flight-input": "Correct the missing flight identity before using Level 3.",
    "approved-policy-library": (
        "Review the pertinent Level 2 findings against the current approved "
        "company manuals; no policy-based option is presented."
    ),
    "finding-policy-coverage": (
        "Review the uncovered pertinent findings against current approved "
        "company policy."
    ),
    "weather-coverage": (
        "Confirm current official weather and advisory coverage for the "
        "applicable flight window."
    ),
    "licensed-chart-minima": (
        "Use current approved charts and minima; no numeric approach margin "
        "has been calculated."
    ),
    "margin-source-validation": (
        "Withhold the proposed margin until every normalized input and "
        "approved source limit is available."
    ),
    "margin-inputs": (
        "Do not use a policy-based margin until normalized inputs and current "
        "approved limit sources are available."
    ),
}


def _text(value: Any) -> str:
    return " ".join(str(value or "").split())


def _pdf_text(value: Any) -> str:
    """Escape controlled or pilot-entered text before ReportLab parses markup."""

    return escape(_text(value))


def _set(value: Any) -> set[str]:
    if isinstance(value, list):
        return {_text(item).casefold() for item in value if _text(item)}
    if value is None:
        return set()
    text = _text(value)
    return {text.casefold()} if text else set()


def _finding_facets(finding: dict[str, Any], flight: dict[str, Any]) -> dict[str, set[str]]:
    data = finding.get("data") if isinstance(finding.get("data"), dict) else {}
    airports: set[str] = set()
    for key in (
        "airport",
        "airport_icao",
        "icao",
        "station",
        "departure",
        "destination",
        "alternate",
    ):
        airports.update(_set(data.get(key)))
    phases = _set(data.get("phase"))
    phases.update(_set(data.get("role")))
    return {
        "engines": _set(finding.get("engine")),
        "rule_ids": _set(finding.get("rule_id")),
        "severities": _set(finding.get("severity")),
        "phases": phases,
        "airports": airports,
        "aircraft_types": _set(flight.get("aircraft_type") or flight.get("aircraft")),
        "registrations": _set(flight.get("registration")),
    }


def _clause_matches(
    clause: dict[str, Any],
    finding: dict[str, Any],
    flight: dict[str, Any],
) -> bool:
    facets = _finding_facets(finding, flight)
    expected = clause.get("facets") if isinstance(clause.get("facets"), dict) else {}
    for key, values in expected.items():
        required = _set(values)
        if required and not (required & facets.get(key, set())):
            return False
    return True


def _actionable_findings(findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        item
        for item in findings
        if _text(item.get("severity")).casefold() in _ACTIONABLE_SEVERITIES
    ]


def _question_id(finding_id: str, clause_id: str) -> str:
    digest = hashlib.sha256(f"{finding_id}\n{clause_id}".encode("utf-8")).hexdigest()[:16]
    return f"L3-Q-{digest}"


def _answer_map(rows: list[Any]) -> dict[str, dict[str, Any]]:
    return {
        str(row["question_id"]): {
            "state": row["answer_state"],
            "answer": row["answer_text"],
            "answered_by": row["answered_by"],
            "answered_at_utc": row["answered_at"],
            "pilot_entered": True,
            "validated": False,
        }
        for row in rows
    }


def _timeline_points(
    analysis: dict[str, Any],
    policy_joined_finding_ids: set[str],
) -> list[dict[str, Any]]:
    """Return only explicitly linked Level 3 decision points.

    The generic ODSS timing stream is part of Level 2. Reprinting it here would
    duplicate the route log, so a Level 3 timeline point must explicitly trace
    to a finding that has an applicable approved policy join.
    """

    level3_inputs = (
        analysis.get("level3_inputs")
        if isinstance(analysis.get("level3_inputs"), dict)
        else {}
    )
    events = level3_inputs.get("timeline_points")
    result = []
    for event in events if isinstance(events, list) else []:
        if not isinstance(event, dict):
            continue
        finding_ids = {
            _text(value)
            for value in event.get("finding_ids") or []
            if _text(value)
        }
        if not finding_ids or not (finding_ids & policy_joined_finding_ids):
            continue
        result.append({
            "label": _text(
                event.get("label")
                or event.get("event")
                or event.get("name")
                or event.get("type")
            ),
            "utc": (
                event.get("actual_utc")
                or event.get("utc_iso")
                or event.get("utc")
                or event.get("utc_display")
            ),
            "actm_minutes": event.get("actm_minutes"),
            "source": "deterministic-odss-timing",
            "finding_ids": sorted(finding_ids & policy_joined_finding_ids),
        })
    return [item for item in result if item["label"]][:20]


def _weather_coverage_gaps(analysis: dict[str, Any]) -> list[str]:
    """Return fail-closed gaps from normalized and known weather-source state."""

    gaps: list[str] = []
    level3_inputs = (
        analysis.get("level3_inputs")
        if isinstance(analysis.get("level3_inputs"), dict)
        else {}
    )
    normalized = level3_inputs.get("weather_coverage")
    normalized_status = (
        _text(normalized.get("status")).casefold()
        if isinstance(normalized, dict)
        else ""
    )
    if normalized_status != "complete":
        gaps.append("Complete official weather-source coverage has not been confirmed.")

    flight = analysis.get("flight") if isinstance(analysis.get("flight"), dict) else {}
    for key, label in (
        ("vaa_review", "Volcanic-ash"),
        ("tropical_cyclone_review", "Tropical-cyclone"),
    ):
        review = flight.get(key)
        if not isinstance(review, dict):
            continue
        coverage = _text(review.get("coverage_status")).casefold()
        status = _text(review.get("status")).casefold()
        reason_codes = {
            _text(value).casefold()
            for value in review.get("reason_codes") or []
            if _text(value)
        }
        if (
            coverage not in {"complete", "full"}
            or status in {"", "not_assessed", "partial", "review_required", "unavailable", "unknown"}
            or "source_disabled" in reason_codes
        ):
            coverage_text = {
                "global_current_active_sigmet": (
                    "limited to the current global active SIGMET feed"
                ),
                "not_assessed": "not assessed",
                "review_required": "incomplete and requires review",
                "source_disabled": "disabled",
            }.get(
                coverage or status,
                (coverage or status or "unavailable").replace("_", " "),
            )
            gaps.append(
                f"{label} official-source coverage is {coverage_text}."
            )
    return gaps


def _build_margins(
    analysis: dict[str, Any],
    eligible_clauses_by_id: dict[str, dict[str, Any]],
    documents_by_id: dict[str, dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    source = (analysis.get("level3_inputs") or {}).get("margins") or []
    margins: list[dict[str, Any]] = []
    gaps: list[dict[str, Any]] = []
    for index, item in enumerate(source if isinstance(source, list) else []):
        if not isinstance(item, dict):
            gaps.append({
                "key": f"margin-{index + 1}",
                "status": "review_required",
                "reason": "A normalized margin input is malformed.",
            })
            continue
        clause_id = _text(item.get("source_clause_id"))
        try:
            actual = float(item["actual"])
            limit = float(item["limit"])
        except (KeyError, TypeError, ValueError):
            gaps.append({
                "key": _text(item.get("margin_id")) or f"margin-{index + 1}",
                "status": "review_required",
                "reason": "A numeric actual value and limit are both required.",
            })
            continue
        clause = eligible_clauses_by_id.get(clause_id)
        if clause is None:
            gaps.append({
                "key": _text(item.get("margin_id")) or f"margin-{index + 1}",
                "status": "review_required",
                "reason": "The current approved source clause for this limit is not mounted.",
            })
            continue
        document = documents_by_id.get(_text(clause.get("document_id")))
        if document is None:
            gaps.append({
                "key": _text(item.get("margin_id")) or f"margin-{index + 1}",
                "status": "review_required",
                "reason": "The approved source document for this limit is unavailable.",
            })
            continue
        direction = _text(item.get("direction")) or "maximum"
        if direction not in {"maximum", "minimum"}:
            gaps.append({
                "key": _text(item.get("margin_id")) or f"margin-{index + 1}",
                "status": "review_required",
                "reason": "Margin direction must be maximum or minimum.",
            })
            continue
        margin = limit - actual if direction == "maximum" else actual - limit
        margins.append({
            "margin_id": _text(item.get("margin_id")) or f"M-{index + 1}",
            "label": _text(item.get("label")) or "Operational margin",
            "actual": actual,
            "limit": limit,
            "margin": margin,
            "unit": _text(item.get("unit")) or "unit",
            "direction": direction,
            "source_clause_id": clause_id,
            "finding_ids": [
                _text(value)
                for value in (item.get("finding_ids") or [])
                if _text(value)
            ],
            "source": {
                "document_title": _text(document.get("title")),
                "revision": _text(document.get("revision")),
                "effective_date": _text(document.get("effective_date")),
                "section": _text(clause.get("section")),
                "page": str(clause.get("page")),
                "source_sha256": _text(document.get("source_sha256")),
            },
            "state": "calculated-from-normalized-approved-sources",
        })
    return margins, gaps


def build_level3_artifact(
    *,
    analysis_id: str,
    analysis: dict[str, Any],
    snapshot: dict[str, Any],
    snapshot_id: str,
    snapshot_sha256: str,
    answers: list[Any] | None = None,
    generated_at_utc: str | None = None,
) -> dict[str, Any]:
    """Build a deterministic policy join. It never asks an LLM for a verdict."""

    findings = analysis.get("findings") if isinstance(analysis.get("findings"), list) else []
    assign_finding_ids(findings)
    flight = analysis.get("flight") if isinstance(analysis.get("flight"), dict) else {}
    documents = snapshot.get("documents") if isinstance(snapshot.get("documents"), list) else []
    clauses = snapshot.get("clauses") if isinstance(snapshot.get("clauses"), list) else []
    documents_by_id = {
        _text(item.get("document_id")): item
        for item in documents
        if isinstance(item, dict) and _text(item.get("document_id"))
    }
    eligible_clauses = [
        item
        for item in clauses
        if isinstance(item, dict) and _text(item.get("document_id")) in documents_by_id
    ]
    answers_by_id = _answer_map(answers or [])
    digest_rows: list[dict[str, Any]] = []
    cards: list[dict[str, Any]] = []
    questions: list[dict[str, Any]] = []
    uncovered: list[str] = []
    actionable_findings = _actionable_findings(findings)
    policy_joined_finding_ids: set[str] = set()
    policy_joined_clause_ids: set[str] = set()

    for finding in actionable_findings:
        finding_id = _text(finding.get("finding_id"))
        matches = [
            clause
            for clause in eligible_clauses
            if _clause_matches(clause, finding, flight)
        ]
        policy_refs = []
        options: list[str] = []
        for clause in matches:
            document = documents_by_id[_text(clause.get("document_id"))]
            row = {
                "finding_id": finding_id,
                "finding_title": _text(finding.get("title")) or "Operational finding",
                "clause_id": _text(clause.get("clause_id")),
                "document_id": _text(document.get("document_id")),
                "document_title": _text(document.get("title")),
                "document_type": _text(document.get("document_type")),
                "revision": _text(document.get("revision")),
                "effective_date": _text(document.get("effective_date")),
                "section": _text(clause.get("section")),
                "page": str(clause.get("page")),
                "exact_support": _text(clause.get("exact_support")),
                "applicability_reason": _text(clause.get("applicability_reason")),
                "decision_frame": _text(clause.get("decision_frame")),
                "source_sha256": _text(document.get("source_sha256")),
            }
            digest_rows.append(row)
            policy_refs.append({
                "clause_id": row["clause_id"],
                "document_id": row["document_id"],
                "document_title": row["document_title"],
                "revision": row["revision"],
                "effective_date": row["effective_date"],
                "section": row["section"],
                "page": row["page"],
            })
            for option in clause.get("applicable_options") or []:
                text = _text(option)
                if text and text not in options:
                    options.append(text)
            ambiguity = clause.get("ambiguity_question")
            if isinstance(ambiguity, dict):
                question_id = _question_id(finding_id, row["clause_id"])
                saved = answers_by_id.get(question_id)
                questions.append({
                    "question_id": question_id,
                    "finding_id": finding_id,
                    "clause_id": row["clause_id"],
                    "prompt": _text(ambiguity.get("prompt")),
                    "options": [_text(item) for item in ambiguity.get("options") or []],
                    "state": saved["state"].upper() if saved else "OPEN",
                    "answer": saved,
                    "non_leading": True,
                })
        if not matches:
            uncovered.append(finding_id)
            continue
        policy_joined_finding_ids.add(finding_id)
        policy_joined_clause_ids.update(
            _text(item.get("clause_id"))
            for item in matches
            if _text(item.get("clause_id"))
        )
        card_questions = [
            item["question_id"]
            for item in questions
            if item["finding_id"] == finding_id
        ]
        cards.append({
            "finding_ids": [finding_id],
            "threat_label": _text(finding.get("title")) or "Operational finding",
            "operational_context": (
                _text(finding.get("summary"))
                or "See the linked deterministic Level 2 finding."
            ),
            "decision_point": (
                _text(matches[0].get("decision_frame"))
            ),
            "applicable_options": options,
            "policy_refs": policy_refs,
            "question_ids": card_questions,
            "state": "OPEN",
            "pilot_decision_statement": PILOT_DECISION_STATEMENT,
        })

    ledger: list[dict[str, Any]] = []
    identity_complete = all(
        _text(flight.get(key))
        for key in ("flight_number", "flight_date", "departure", "destination")
    )
    ledger.append({
        "key": "normalized-flight-input",
        "status": "complete" if identity_complete else "review_required",
        "reason": (
            "Core normalized flight identity is present."
            if identity_complete
            else "One or more core normalized flight identity fields are missing."
        ),
    })
    policy_ready = (
        snapshot.get("state") == "ready"
        and bool(documents)
        and bool(eligible_clauses)
    )
    ledger.append({
        "key": "approved-policy-library",
        "status": "complete" if policy_ready else "review_required",
        "reason": (
            "A current approved private policy snapshot is mounted."
            if policy_ready
            else _text(snapshot.get("reason")) or "Approved company policy is unavailable."
        ),
    })
    ledger.append({
        "key": "finding-policy-coverage",
        "status": "complete" if not uncovered and policy_ready else "review_required",
        "reason": (
            "Every pertinent Level 2 finding has an applicable approved clause."
            if not uncovered and policy_ready
            else (
                f"{len(uncovered)} of {len(actionable_findings)} pertinent "
                "Level 2 finding(s) have no applicable approved policy clause."
            )
        ),
    })

    weather_finding_gap = any(
        item.get("engine") in {"weather", "vaa", "tropical_cyclone"}
        and (
            _text(item.get("severity")).casefold() == "unknown"
            or (item.get("data") or {}).get("status") == "review_required"
        )
        for item in findings
    )
    weather_gaps = _weather_coverage_gaps(analysis)
    if weather_finding_gap:
        weather_gaps.append("A pertinent weather item remains review required.")
    ledger.append({
        "key": "weather-coverage",
        "status": "review_required" if weather_gaps else "complete",
        "reason": (
            " ".join(weather_gaps)
            if weather_gaps
            else "Complete official weather-source coverage is confirmed."
        ),
    })

    minima_needed = any(
        item.get("engine") in {"weather", "notam"}
        and any(
            token in f"{item.get('title', '')} {item.get('summary', '')}".casefold()
            for token in ("approach", "minima", "visibility", "ils", "runway")
        )
        for item in findings
    )
    minima_available = any(
        _text(item.get("document_type")).casefold() in {"licensed_minima", "chart_minima"}
        for item in documents
    )
    ledger.append({
        "key": "licensed-chart-minima",
        "status": (
            "complete"
            if not minima_needed or minima_available
            else "review_required"
        ),
        "reason": (
            "No weather-to-minima calculation is required by the current findings."
            if not minima_needed
            else (
                "A current approved minima source is mounted."
                if minima_available
                else "Licensed/current chart minima are not mounted; numeric approach margin is unavailable."
            )
        ),
    })

    eligible_clauses_by_id = {
        _text(item.get("clause_id")): item
        for item in eligible_clauses
        if _text(item.get("clause_id")) in policy_joined_clause_ids
    }
    margins, margin_gaps = _build_margins(
        analysis,
        eligible_clauses_by_id,
        documents_by_id,
    )
    margin_relevant = any(item.get("engine") in _MARGIN_ENGINES for item in findings)
    if margin_gaps:
        unique_reasons = sorted({_text(item.get("reason")) for item in margin_gaps})
        ledger.append({
            "key": "margin-source-validation",
            "status": "review_required",
            "reason": (
                f"{len(margin_gaps)} proposed margin input(s) were withheld. "
                + " ".join(unique_reasons)
            ),
        })
    ledger.append({
        "key": "margin-inputs",
        "status": (
            "complete"
            if margins or not margin_relevant
            else "review_required"
        ),
        "reason": (
            f"{len(margins)} margin(s) calculated from normalized values and approved clauses."
            if margins
            else (
                "No margin-bearing finding is present."
                if not margin_relevant
                else "Required verified values or approved limit sources are unavailable; no margin was invented."
            )
        ),
    })

    status = (
        "COMPLETE"
        if all(item["status"] == "complete" for item in ledger)
        else "PARTIAL"
    )
    revisions = [
        {
            "document_id": _text(item.get("document_id")),
            "title": _text(item.get("title")),
            "revision": _text(item.get("revision")),
            "effective_date": _text(item.get("effective_date")),
            "source_sha256": _text(item.get("source_sha256")),
        }
        for item in documents
    ]
    applicable_policy_available = bool(policy_joined_finding_ids)
    presentation_mode = (
        "policy-backed"
        if applicable_policy_available
        else (
            "compact-partial-ledger"
            if status == "PARTIAL"
            else "compact-no-open-decisions"
        )
    )
    return {
        "schema_version": "1.1",
        "artifact_type": "odss-level-3-policy-aware-briefing",
        "analysis_id": analysis_id,
        "generated_at_utc": generated_at_utc or datetime.now(timezone.utc).isoformat(),
        "status": status,
        "decision_authority": "pilot",
        "pilot_decision_statement": PILOT_DECISION_STATEMENT,
        "generation": {
            "method": "deterministic-policy-join",
            "llm_operational_verdict": False,
            "browser_calculations": False,
        },
        "decision_summary": {
            "flight": {
                "flight_number": flight.get("flight_number"),
                "flight_date": flight.get("flight_date"),
                "departure": flight.get("departure"),
                "destination": flight.get("destination"),
                "aircraft": flight.get("aircraft_type") or flight.get("aircraft"),
                "registration": flight.get("registration"),
            },
            "open_decision_count": sum(item["state"] == "OPEN" for item in cards),
            "policy_revision_set": revisions,
            "completeness": status,
            "presentation_mode": presentation_mode,
        },
        "policy_snapshot": {
            "snapshot_id": snapshot_id,
            "snapshot_sha256": snapshot_sha256,
            "state": snapshot.get("state"),
            "source_index_sha256": snapshot.get("source_sha256"),
            "immutable": True,
        },
        "policy_digest": digest_rows,
        "threat_cards": cards,
        "margins": margins,
        "timeline_points": _timeline_points(
            analysis,
            policy_joined_finding_ids,
        ),
        "completeness_ledger": ledger,
        "pilot_questions": questions,
        "audit_trace": {
            "actionable_finding_count": len(actionable_findings),
            "policy_joined_finding_ids": sorted(policy_joined_finding_ids),
            "policy_joined_clause_ids": sorted(policy_joined_clause_ids),
            "uncovered_finding_ids": sorted(uncovered),
            "margin_gaps": margin_gaps,
            "raw_evidence_location": "canonical-level-2-analysis",
        },
    }


def _render_level3_pdf(artifact: dict[str, Any], destination: Path) -> None:
    styles = getSampleStyleSheet()
    title = ParagraphStyle(
        "L3Title",
        parent=styles["Title"],
        fontName="Helvetica-Bold",
        fontSize=17,
        leading=20,
        alignment=TA_CENTER,
        textColor=colors.HexColor("#0B2742"),
        spaceAfter=8,
    )
    heading = ParagraphStyle(
        "L3Heading",
        parent=styles["Heading2"],
        fontName="Helvetica-Bold",
        fontSize=10,
        leading=12,
        textColor=colors.HexColor("#0B4F6C"),
        spaceBefore=6,
        spaceAfter=4,
    )
    body = ParagraphStyle(
        "L3Body",
        parent=styles["BodyText"],
        fontSize=7.5,
        leading=9.5,
        spaceAfter=3,
    )
    small = ParagraphStyle("L3Small", parent=body, fontSize=6.5, leading=8)
    document = SimpleDocTemplate(
        str(destination),
        pagesize=landscape(A4),
        leftMargin=12 * mm,
        rightMargin=12 * mm,
        topMargin=10 * mm,
        bottomMargin=10 * mm,
        title="ODSS Level 3 Policy-Aware Briefing",
        author="PilotDriven ODSS",
    )

    def ledger_table(*, compact_partial: bool = False) -> Table:
        items = list(artifact["completeness_ledger"])
        if compact_partial:
            items = [item for item in items if item["status"] == "review_required"]
            rows = [[
                "Pertinent review item",
                "Missing source or unresolved coverage",
                "Pilot review required",
            ]]
            for item in items:
                key = str(item["key"])
                rows.append([
                    Paragraph(_pdf_text(_LEDGER_LABELS.get(key, "Operational support")), small),
                    Paragraph(_pdf_text(item["reason"]), small),
                    Paragraph(
                        _pdf_text(
                            _LEDGER_REVIEW_ACTIONS.get(
                                key,
                                "Review this unresolved item using the current approved source.",
                            )
                        ),
                        small,
                    ),
                ])
            col_widths = [48 * mm, 125 * mm, 91 * mm]
        else:
            rows = [["Review item", "State", "Reason"]]
            for item in items:
                key = str(item["key"])
                rows.append([
                    Paragraph(_pdf_text(_LEDGER_LABELS.get(key, "Operational support")), small),
                    Paragraph(_pdf_text(item["status"].upper().replace("_", " ")), small),
                    Paragraph(_pdf_text(item["reason"]), small),
                ])
            col_widths = [55 * mm, 38 * mm, 171 * mm]
        return Table(
            rows,
            repeatRows=1,
            colWidths=col_widths,
            style=[
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0B2742")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#A8BAC8")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
            ],
        )

    story = [
        Paragraph("ODSS Level 3 - Policy-Aware Briefing", title),
        Paragraph(artifact["pilot_decision_statement"], body),
        Spacer(1, 3 * mm),
        Paragraph("A. Briefing summary", heading),
    ]
    summary = artifact["decision_summary"]
    flight = summary["flight"]
    review_gate_count = sum(
        item.get("status") != "complete"
        for item in artifact["completeness_ledger"]
    )
    story.append(Table(
        [
            ["Flight", "Route", "State", "Review gates", "Policy revisions"],
            [
                f"{flight.get('flight_number') or '-'} / {flight.get('flight_date') or '-'}",
                f"{flight.get('departure') or '-'} to {flight.get('destination') or '-'}",
                artifact["status"],
                str(review_gate_count),
                str(len(summary["policy_revision_set"])),
            ],
        ],
        colWidths=[45 * mm, 45 * mm, 28 * mm, 32 * mm, 35 * mm],
        style=[
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0B2742")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTNAME", (0, 1), (-1, 1), "Helvetica"),
            ("FONTSIZE", (0, 0), (-1, -1), 7),
            ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#A8BAC8")),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
        ],
    ))

    presentation_mode = summary.get("presentation_mode") or "policy-backed"
    if presentation_mode != "policy-backed":
        if presentation_mode == "compact-partial-ledger":
            story.append(Paragraph("Policy support unavailable - review required", heading))
            story.append(Paragraph(
                "No current approved company-policy clause could be applied to the "
                "pertinent briefing findings. Level 3 remains PARTIAL and does not invent "
                "options, margins or an operational conclusion.",
                body,
            ))
        else:
            story.append(Paragraph("No policy-backed open decision", heading))
            story.append(Paragraph(
                "No actionable deterministic finding required a policy-backed "
                "decision card for this analysis.",
                body,
            ))
        story.append(Paragraph("B. Review-required completeness", heading))
        story.append(ledger_table(compact_partial=True))
        story.append(Paragraph(
            f"Generated {_pdf_text(artifact['generated_at_utc'])}",
            small,
        ))
        document.build(story)
        assert_report_quality(
            destination,
            level=3,
            level3_status=artifact["status"],
        )
        return

    revision_text = "; ".join(
        (
            f"{_pdf_text(item.get('title') or 'Controlled document')} / "
            f"{_pdf_text(item.get('revision'))} / effective "
            f"{_pdf_text(item.get('effective_date'))}"
        )
        for item in summary["policy_revision_set"]
    )
    story.append(Paragraph(
        f"<b>Policy revision set:</b> {revision_text or 'None'}",
        body,
    ))
    story.append(Paragraph("B. Applicable policy digest", heading))
    digest = artifact["policy_digest"]
    if digest:
        rows = [[
            "Threat",
            "Document / revision",
            "Section / page",
            "Exact support",
            "Applicability",
        ]]
        for item in digest:
            rows.append([
                Paragraph(_pdf_text(item["finding_title"]), small),
                Paragraph(
                    f"{_pdf_text(item['document_title'])}<br/>"
                    f"{_pdf_text(item['revision'])} / effective "
                    f"{_pdf_text(item['effective_date'])}",
                    small,
                ),
                Paragraph(
                    f"{_pdf_text(item['section'])} / p.{_pdf_text(item['page'])}",
                    small,
                ),
                Paragraph(_pdf_text(item["exact_support"]), small),
                Paragraph(_pdf_text(item["applicability_reason"]), small),
            ])
        story.append(Table(
            rows,
            repeatRows=1,
            colWidths=[42 * mm, 51 * mm, 42 * mm, 76 * mm, 53 * mm],
            style=[
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#DCEAF2")),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#A8BAC8")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("FONTSIZE", (0, 0), (-1, -1), 6.5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
            ],
        ))

    story.append(Paragraph("C. Policy-supported review items", heading))
    for card in artifact["threat_cards"]:
        refs = "; ".join(
            (
                f"{_pdf_text(item.get('document_title'))}, "
                f"{_pdf_text(item.get('revision'))}, effective "
                f"{_pdf_text(item.get('effective_date'))}, "
                f"{_pdf_text(item.get('section'))}, p.{_pdf_text(item.get('page'))}"
            )
            for item in card["policy_refs"]
        )
        options = (
            "; ".join(_pdf_text(item) for item in card["applicable_options"])
            or "No operator options are stated by the cited clause."
        )
        story.append(Table(
            [[
                Paragraph(
                    f"<b>{_pdf_text(card['threat_label'])}</b>",
                    body,
                ),
                Paragraph(
                    f"{_pdf_text(card['operational_context'])}<br/>"
                    f"<b>Policy context:</b> {_pdf_text(card['decision_point'])}<br/>"
                    f"<b>Available options:</b> {options}<br/>"
                    f"<b>Cited policy:</b> {refs}",
                    body,
                ),
                Paragraph("<b>Pilot retains final authority.</b>", small),
            ]],
            colWidths=[58 * mm, 140 * mm, 66 * mm],
            style=[
                ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#D08A00")),
                ("BACKGROUND", (0, 0), (0, 0), colors.HexColor("#FFF4D6")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
            ],
        ))
        story.append(Spacer(1, 2 * mm))

    story.append(Paragraph("D. Margin-to-limit analysis", heading))
    if artifact["margins"]:
        for margin in artifact["margins"]:
            source = margin["source"]
            story.append(Paragraph(
                f"<b>{_pdf_text(margin['label'])}:</b> {margin['margin']:+g} "
                f"{_pdf_text(margin['unit'])} "
                f"(actual {margin['actual']:g}; limit {margin['limit']:g}). "
                f"Source: {_pdf_text(source['document_title'])}, "
                f"{_pdf_text(source['revision'])}, effective "
                f"{_pdf_text(source['effective_date'])}, "
                f"{_pdf_text(source['section'])}, p.{_pdf_text(source['page'])}.",
                body,
            ))
    else:
        story.append(Paragraph(
            "No numeric margin is published without both normalized values and a current approved limit source.",
            body,
        ))

    story.append(Paragraph("E. Relevant timeline points", heading))
    if artifact["timeline_points"]:
        for point in artifact["timeline_points"]:
            story.append(Paragraph(
                f"{_pdf_text(point.get('utc') or 'UTC unresolved')} / "
                f"{_pdf_text(point['label'])}",
                body,
            ))
    else:
        story.append(Paragraph("No normalized deterministic timeline points are available.", body))

    story.append(Paragraph("F. Review-required completeness", heading))
    story.append(ledger_table())
    story.append(Paragraph("G. Scoped pilot questions", heading))
    if artifact["pilot_questions"]:
        for question in artifact["pilot_questions"]:
            story.append(Paragraph(
                f"<b>{_pdf_text(question['state'])}</b> - "
                f"{_pdf_text(question['prompt'])} Options: "
                f"{_pdf_text(', '.join(question['options']))}.",
                body,
            ))
    else:
        story.append(Paragraph(
            "No approved clause produced a genuine ambiguity question.",
            body,
        ))
    document.build(story)
    assert_report_quality(
        destination,
        level=3,
        level3_status=artifact["status"],
    )


def _snapshot_for_analysis(
    *,
    tenant_id: str,
    analysis_id: str,
    analysis: dict[str, Any],
) -> tuple[Any, dict[str, Any]]:
    row = get_policy_snapshot(tenant_id, analysis_id)
    if row is None:
        snapshot = policy_snapshot_from_env(
            tenant_id=tenant_id,
            flight_date=(analysis.get("flight") or {}).get("flight_date"),
        )
        row = get_or_create_policy_snapshot(
            tenant_id=tenant_id,
            analysis_id=analysis_id,
            snapshot=snapshot,
        )
    return row, json.loads(row["snapshot_json"])


def generate_level3_artifacts(
    *,
    tenant_id: str,
    actor_id: str,
    analysis_id: str,
    analysis_path: Path,
    result_dir: Path,
    report_dir: Path,
) -> dict[str, Any]:
    analysis = json.loads(analysis_path.read_text(encoding="utf-8"))
    snapshot_row, snapshot = _snapshot_for_analysis(
        tenant_id=tenant_id,
        analysis_id=analysis_id,
        analysis=analysis,
    )
    artifact = build_level3_artifact(
        analysis_id=analysis_id,
        analysis=analysis,
        snapshot=snapshot,
        snapshot_id=str(snapshot_row["id"]),
        snapshot_sha256=str(snapshot_row["snapshot_sha256"]),
        answers=list_level3_answers(tenant_id, analysis_id),
    )
    result_dir.mkdir(parents=True, exist_ok=True)
    report_dir.mkdir(parents=True, exist_ok=True)
    stem = analysis_path.stem.removesuffix("_analysis")
    json_path = result_dir / f"{stem}_level_3.json"
    pdf_path = report_dir / f"{stem}_level_3.pdf"
    json_temp = json_path.with_suffix(".json.tmp")
    pdf_temp = pdf_path.with_suffix(".pdf.tmp")
    published = False
    try:
        json_temp.write_text(json.dumps(artifact, indent=2), encoding="utf-8")
        _render_level3_pdf(artifact, pdf_temp)
        json_temp.replace(json_path)
        pdf_temp.replace(pdf_path)
        published = True
    finally:
        json_temp.unlink(missing_ok=True)
        pdf_temp.unlink(missing_ok=True)
        if not published:
            json_path.unlink(missing_ok=True)
            pdf_path.unlink(missing_ok=True)
    record_audit_event(
        tenant_id=tenant_id,
        actor_id=actor_id,
        action="level3.generated",
        resource_type="analysis",
        resource_id=analysis_id,
        details={
            "status": artifact["status"],
            "policy_snapshot_id": snapshot_row["id"],
            "policy_snapshot_sha256": snapshot_row["snapshot_sha256"],
            "question_count": len(artifact["pilot_questions"]),
        },
    )
    return {
        "artifact": artifact,
        "level3_json": str(json_path),
        "level3_report": str(pdf_path),
        "level3_status": artifact["status"],
    }


__all__ = [
    "PILOT_DECISION_STATEMENT",
    "build_level3_artifact",
    "generate_level3_artifacts",
]

"""Level 1 page 3: the v1.3 DEPRESSURISATION PROFILE ANALYSIS page.

Layout contract (approved reference v1.3):

- summary strip: strict windows / approved matches / unmatched / effectivity
- one analysis card per approved profile match, drawing the corridor
  schematic from the governed index extraction plus the flight's actual
  exposure, and
- an UNMATCHED EXPOSURES panel that never substitutes a nearby or generic
  chart.

Every number shown is computed from the parsed CFP or the approved
controlled index; nothing is invented at render time.
"""

from __future__ import annotations

from typing import Any

from reportlab.pdfbase import pdfmetrics

from . import brief_theme as theme
from .constants import format_actm
from .controlled_library import aircraft_effectivity_tokens, normalized_registration
from . import engines
from .engines import detect_terrain_events
from .report_facts import actm_utc_clock


def _actm_utc(flight: dict[str, Any], actm_minutes: Any) -> str | None:
    """Return UTC only from an actual ATOT/ATA-derived timing anchor."""
    clock = actm_utc_clock(flight, actm_minutes)
    if not clock:
        return None
    # Dense profile panels already identify the flight date elsewhere.
    return clock.rsplit(" ", 1)[-1]


def _profile_by_chart(chart_number: str) -> dict[str, Any] | None:
    # Read through the engines module so a runtime index reload (or a test
    # replacing the mounted profile list) is always honoured.
    for profile in engines.DEPRESS_PROFILES:
        if str(profile.get("chart") or "") == chart_number:
            return profile
    return None


def _effectivity_label(flight: dict[str, Any]) -> str:
    tokens = aircraft_effectivity_tokens(
        flight.get("registration"), flight.get("aircraft_type")
    )
    for series in ("LH", "ULR", "MH"):
        if series in tokens:
            return series
    return "-"


def _matched_event_findings(
    findings: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Return every complete controlled match, including repeated charts.

    One approved profile can legitimately cover more than one distinct
    high-terrain exposure window. Event-level consumers (for example the
    Level 2 match matrix) must retain every match; profile-level consumers
    can deduplicate the result separately.
    """
    return [
        finding
        for finding in findings
        if finding.get("engine") == "depressurisation"
        and bool((finding.get("data") or {}).get("chart_number"))
        and bool((finding.get("data") or {}).get("coverage_complete"))
        and (finding.get("data") or {}).get("reference_status")
        == "controlled-index-loaded"
    ]


def _matched_findings(findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return one representative finding per approved profile chart."""
    seen: set[str] = set()
    result = []
    for finding in _matched_event_findings(findings):
        data = finding.get("data") or {}
        chart = str(data.get("chart_number") or "")
        if chart in seen:
            continue
        seen.add(chart)
        result.append(finding)
    return result


def _unresolved_findings(findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        finding
        for finding in findings
        if finding.get("engine") == "depressurisation"
        and not (finding.get("data") or {}).get("chart_number")
    ]


def _event_for_id(events: list[dict[str, Any]], event_id: Any) -> dict[str, Any] | None:
    for event in events:
        if event.get("terrain_event_id") == event_id:
            return event
    return None


def _terr_ref(events: list[dict[str, Any]], event: dict[str, Any] | None) -> str:
    if event is None:
        return "TERR-??"
    ordered = sorted(
        events, key=lambda item: item["first_high"].get("actm_minutes") or 0
    )
    for index, item in enumerate(ordered, start=1):
        if item is event:
            return f"TERR-{index:02d}"
    return "TERR-??"


def _filed_segment(flight: dict[str, Any], event: dict[str, Any]) -> str:
    """``RODAR-M11-MATAL`` style description of the filed legs at the event."""
    waypoints = flight.get("route_waypoints") or []
    try:
        start = waypoints.index(event.get("preceding") or event["first_high"])
        end = waypoints.index(event["last_high"])
    except (ValueError, KeyError):
        return "-"
    start_name = str(waypoints[start].get("name") or "")
    end_name = str(waypoints[end].get("name") or "")
    airways: list[str] = []
    for index in range(start + 1, end + 1):
        airway = str(waypoints[index].get("airway_in") or "")
        if airway and airway not in airways:
            airways.append(airway)
    middle = "-".join(airways)
    if middle:
        return f"{start_name}-{middle}-{end_name}"
    return f"{start_name}-{end_name}" if start_name or end_name else "-"


def _exposure_line(flight: dict[str, Any], event: dict[str, Any]) -> str:
    first = event["first_high"]
    last = event["last_high"]
    drop = event.get("drop")
    line = (
        f"{first.get('name')} {format_actm(first.get('actm_minutes'))} -> "
        f"{last.get('name')} {format_actm(last.get('actm_minutes'))}"
    )
    if drop:
        line += (
            f"; drop {drop.get('name')} "
            f"{int(drop.get('msa_hundreds_ft') or 0):03d} "
            f"at {format_actm(drop.get('actm_minutes'))}"
        )
    return line


def _max_cp_line(
    flight: dict[str, Any],
    event: dict[str, Any],
    critical_name: str,
) -> str:
    maximum = event.get("maximum") or {}
    critical_wp = next(
        (
            waypoint
            for waypoint in flight.get("route_waypoints") or []
            if str(waypoint.get("name") or "").upper() == critical_name.upper()
        ),
        None,
    )
    line = (
        f"{int(maximum.get('msa_hundreds_ft') or 0)}* "
        f"{maximum.get('name')} {format_actm(maximum.get('actm_minutes'))}"
    )
    if critical_wp:
        line += f" | CP {critical_name} {format_actm(critical_wp.get('actm_minutes'))}"
        utc_clock = _actm_utc(flight, critical_wp.get("actm_minutes"))
        if utc_clock:
            line += f" / {utc_clock}"
    else:
        line += f" | CP {critical_name}"
    return line


def _corridor_line(profile: dict[str, Any]) -> str:
    """``TEMEL - UM11, M11, T916, N161 - LEKBA | CP MATAL`` corridor summary."""
    airways = ", ".join(str(value) for value in profile.get("airways") or [])
    line = f"{profile.get('from')} - {airways} - {profile.get('to')}"
    return f"{line} | CP {profile.get('critical')}"


def _draw_card(
    canvas: Any,
    flight: dict[str, Any],
    finding: dict[str, Any],
    related_findings: list[dict[str, Any]],
    events: list[dict[str, Any]],
    x: float,
    y: float,
    width: float,
    height: float,
) -> None:
    data = finding.get("data") or {}
    chart = str(data.get("chart_number") or "")
    profile = _profile_by_chart(chart) or {}
    event = _event_for_id(events, data.get("terrain_event_id"))
    related_events: list[dict[str, Any]] = []
    seen_event_ids: set[str] = set()
    for related_finding in related_findings:
        related_data = related_finding.get("data") or {}
        related_event = _event_for_id(
            events,
            related_data.get("terrain_event_id"),
        )
        if related_event is None:
            continue
        event_id = str(related_event.get("terrain_event_id") or "")
        if event_id in seen_event_ids:
            continue
        seen_event_ids.add(event_id)
        related_events.append(related_event)
    if not related_events and event is not None:
        related_events.append(event)

    canvas.setFillColor(theme.PANEL)
    canvas.roundRect(x, y, width, height, 5, stroke=0, fill=1)

    pad = 10
    top = y + height - 16
    canvas.setFillColor(theme.BLUE)
    canvas.setFont(theme.SANS_BOLD, 11)
    canvas.drawString(x + pad, top, f"PROFILE {chart}")
    canvas.setFillColor(theme.MUTED)
    canvas.setFont(theme.SANS, 5.6)
    canvas.drawRightString(
        x + width - pad,
        top + 2,
        f"Attachment {chart} | eff {profile.get('effective_date') or 'not indexed'} | "
        + "/".join(profile.get("effectivity") or []) ,
    )
    canvas.setFillColor(theme.TEXT)
    canvas.setFont(theme.SANS_BOLD, 6.2)
    canvas.drawString(x + pad, top - 11, _corridor_line(profile))

    # Schematic: plateau - CP peak - plateau with the flight direction arrow.
    schematic = profile.get("schematic") or {}
    diagram_top = top - 22
    diagram_bottom = y + 58
    diagram_height = diagram_top - diagram_bottom
    diagram_left = x + pad + 14
    diagram_right = x + width - pad - 14
    span = diagram_right - diagram_left
    critical_name = str(profile.get("critical") or data.get("critical_point") or "")
    plateau_y = diagram_bottom + diagram_height * 0.35
    peak_y = diagram_bottom + diagram_height * 0.86
    center_x = diagram_left + span * 0.5

    canvas.setStrokeColor(theme.TEXT)
    canvas.setLineWidth(1.1)
    canvas.line(diagram_left, plateau_y, center_x - 16, plateau_y)
    canvas.line(center_x - 16, plateau_y, center_x, peak_y)
    canvas.line(center_x, peak_y, center_x + 16, plateau_y)
    canvas.line(center_x + 16, plateau_y, diagram_right, plateau_y)

    # Endpoints and critical point.
    from_name = str(profile.get("from") or data.get("route_end") or "")
    to_name = str(profile.get("to") or "")
    canvas.setFillColor(theme.TEXT)
    for point_x, name in ((diagram_left, from_name), (diagram_right, to_name)):
        canvas.circle(point_x, plateau_y, 1.6, stroke=0, fill=1)
        canvas.setFont(theme.SANS_BOLD, 6.0)
        canvas.drawCentredString(point_x, plateau_y - 12, name)
    canvas.setFillColor(theme.GREEN)
    canvas.setFont(theme.SANS_BOLD, 6.4)
    canvas.drawCentredString(center_x, peak_y + 12, f"CP {critical_name}")
    _draw_star(canvas, center_x, peak_y + 3.5, 4.0)
    canvas.setStrokeColor(theme.MUTED)
    canvas.setLineWidth(0.6)
    canvas.setDash(2, 2)
    canvas.line(center_x, diagram_bottom + 4, center_x, peak_y)
    canvas.setDash()

    altitudes = [
        value
        for value in (schematic.get("level_off_altitudes") or [])
        if value != "10,000 ft"
    ]
    canvas.setFillColor(theme.MUTED)
    canvas.setFont(theme.SANS, 5.6)
    if altitudes:
        canvas.drawCentredString(
            (diagram_left + center_x) / 2,
            plateau_y + 5,
            altitudes[-1],
        )
        canvas.drawCentredString(
            (center_x + diagram_right) / 2,
            plateau_y + 5,
            altitudes[0],
        )

    # Flight direction annotation, offset from the CP label.
    if event is not None:
        from .brief_theme import display_flight_number as _dfn
        direction = (
            f"{_dfn(flight)} direction "
            f"{event['first_high'].get('name')} -> {event['last_high'].get('name')}"
        )
        canvas.setFillColor(theme.BLUE)
        canvas.setFont(theme.SANS, 5.4)
        canvas.drawCentredString(
            (diagram_left + center_x) / 2, diagram_top + 4, direction
        )
        arrow_y = diagram_top + 5.5
        canvas.setStrokeColor(theme.BLUE)
        canvas.setLineWidth(0.8)
        arrow_left = diagram_left + 4
        text_width = pdfmetrics.stringWidth(direction, theme.SANS, 5.4)
        arrow_start = (diagram_left + center_x) / 2 - text_width / 2 - 6
        if arrow_start > arrow_left + 8:
            canvas.line(arrow_left, arrow_y, arrow_start, arrow_y)
            canvas.line(arrow_left, arrow_y, arrow_left + 4, arrow_y + 2)
            canvas.line(arrow_left, arrow_y, arrow_left + 4, arrow_y - 2)

    # Fact rows.
    rows: list[tuple[str, str, Any]] = []
    for index, related_event in enumerate(related_events[:2], start=1):
        rows.append(
            (
                (
                    "ACTUAL EXPOSURE"
                    if len(related_events) == 1
                    else f"EXPOSURE {index}"
                ),
                (
                    f"{_terr_ref(events, related_event)} | "
                    f"{_exposure_line(flight, related_event)}"
                ),
                theme.TEXT,
            )
        )
    if related_events:
        maximum_event = max(
            related_events,
            key=lambda item: int(
                (item.get("maximum") or {}).get("msa_hundreds_ft") or -1
            ),
        )
        rows.append(
            (
                "MAX / CP",
                _max_cp_line(flight, maximum_event, critical_name),
                theme.TEXT,
            )
        )
    coverage = (
        "FULL route-profile match"
        if data.get("route_start") == profile.get("from")
        or data.get("route_start") == profile.get("to")
        else f"FULL {data.get('route_start')}-{data.get('route_end')} subsegment match"
    )
    if not data.get("coverage_complete"):
        coverage = "PARTIAL coverage - review required"
    rows.append(
        (
            "COVERAGE",
            (
                f"{len(related_events)} window"
                f"{'s' if len(related_events) != 1 else ''}; "
            )
            + f"{coverage}; {normalized_registration(flight.get('registration'))} "
            f"effectivity = {_effectivity_label(flight)}",
            theme.GREEN,
        )
    )
    row_y = y + 44
    for label, value, colour in rows:
        canvas.setFillColor(theme.MUTED)
        canvas.setFont(theme.SANS, 5.4)
        canvas.drawString(x + pad, row_y, label)
        canvas.setFillColor(colour)
        canvas.setFont(theme.SANS_BOLD if colour is theme.GREEN else theme.SANS, 5.8)
        canvas.drawString(x + pad + 72, row_y, value[:110])
        row_y -= 12


def _draw_star(canvas: Any, x: float, y: float, radius: float) -> None:
    import math

    path = canvas.beginPath()
    for index in range(10):
        angle = math.pi / 2 + index * math.pi / 5
        r = radius if index % 2 == 0 else radius * 0.4
        px, py = x + r * math.cos(angle), y + r * math.sin(angle)
        if index == 0:
            path.moveTo(px, py)
        else:
            path.lineTo(px, py)
    path.close()
    canvas.setFillColor(theme.GREEN)
    canvas.drawPath(path, stroke=0, fill=1)


def draw_depressurisation_analysis(
    canvas: Any,
    flight: dict[str, Any],
    findings: list[dict[str, Any]],
    width: float,
    height: float,
    *,
    issue_date: str | None = None,
    page_number: int = 3,
    page_count: int = 3,
) -> None:
    theme.register_fonts()
    canvas.setFillColor(theme.PAGE_BG)
    canvas.rect(0, 0, width, height, stroke=0, fill=1)

    margin = 24.0
    top = theme.draw_header(
        canvas,
        flight,
        width=width,
        height=height,
        pill_text="LEVEL 1 - DEPRESSURISATION",
    )

    canvas.setFillColor(theme.TEXT)
    canvas.setFont(theme.SANS_BOLD, 16)
    canvas.drawString(margin, top - 14, "DEPRESSURISATION PROFILE ANALYSIS")
    canvas.setFillColor(theme.MUTED)
    canvas.setFont(theme.SANS, 5.8)
    canvas.drawRightString(
        width - margin,
        top - 12,
        (
            f"Approved A350 profile set {issue_date or 'not stated'} | "
            "actual exposure and chart coverage shown separately"
        ),
    )

    events = detect_terrain_events(flight.get("route_waypoints") or [])
    matched = _matched_findings(findings)
    matched_events = _matched_event_findings(findings)
    unresolved = _unresolved_findings(findings)

    # Summary strip.
    strip_y = top - 52
    strip_h = 26.0
    canvas.setFillColor(theme.PANEL)
    canvas.roundRect(margin, strip_y, width - 2 * margin, strip_h, 4, stroke=0, fill=1)
    cells = [
        (str(len(events)), "STRICT MSA >100* WINDOWS", theme.AMBER),
        (str(len(matched)), "APPROVED PROFILE MATCHES", theme.BLUE),
        (str(len(unresolved)), "UNMATCHED EXPOSURES", theme.RED),
        (
            _effectivity_label(flight),
            f"{normalized_registration(flight.get('registration'))} EFFECTIVITY",
            theme.BLUE,
        ),
    ]
    cell_width = (width - 2 * margin) / len(cells)
    for index, (value, label, colour) in enumerate(cells):
        cx = margin + index * cell_width
        canvas.setFillColor(colour)
        canvas.setFont(theme.SANS_BOLD, 12.5)
        canvas.drawString(cx + 14, strip_y + 9, value)
        canvas.setFillColor(theme.MUTED)
        canvas.setFont(theme.SANS, 5.6)
        canvas.drawString(
            cx + 14 + pdfmetrics.stringWidth(value, theme.SANS_BOLD, 12.5) + 10,
            strip_y + 11,
            label,
        )
        if index:
            canvas.setStrokeColor(theme.LINE)
            canvas.setLineWidth(0.6)
            canvas.line(cx, strip_y + 4, cx, strip_y + strip_h - 4)

    # Profile analysis cards.
    cards_top = strip_y - 10
    card_height = 250.0 if matched and not unresolved else 172.0
    card_y = cards_top - card_height
    if matched:
        gap = 10.0
        card_width = (width - 2 * margin - gap * (len(matched[:2]) - 1)) / len(
            matched[:2]
        )
        for index, finding in enumerate(matched[:2]):
            _draw_card(
                canvas,
                flight,
                finding,
                [
                    event_finding
                    for event_finding in matched_events
                    if str(
                        (event_finding.get("data") or {}).get("chart_number")
                        or ""
                    )
                    == str((finding.get("data") or {}).get("chart_number") or "")
                ],
                events,
                margin + index * (card_width + gap),
                card_y,
                card_width,
                card_height,
            )
    else:
        canvas.setFillColor(theme.PANEL)
        canvas.roundRect(
            margin, card_y, width - 2 * margin, card_height, 5, stroke=0, fill=1
        )
        canvas.setFillColor(theme.MUTED)
        canvas.setFont(theme.SANS_BOLD, 8)
        canvas.drawCentredString(
            width / 2,
            card_y + card_height / 2,
            "No approved profile match in the mounted controlled index.",
        )

    # Unmatched exposures panel, sized to its content.
    panel_top = card_y - 10
    entry_rows = max(1, (len(unresolved[:4]) + 1) // 2)
    panel_height = 34 + entry_rows * 50 + 40 if unresolved else 72
    panel_bottom = max(40.0, panel_top - panel_height)
    canvas.setFillColor(theme.PANEL)
    canvas.roundRect(
        margin,
        panel_bottom,
        width - 2 * margin,
        panel_top - panel_bottom,
        5,
        stroke=0,
        fill=1,
    )
    pad = 12
    text_y = panel_top - 16
    canvas.setFillColor(theme.RED if unresolved else theme.GREEN)
    canvas.setFont(theme.SANS_BOLD, 8.6)
    canvas.drawString(
        margin + pad,
        text_y,
        (
            "UNMATCHED EXPOSURES - NO APPROVED CHART SUBSTITUTED"
            if unresolved
            else "ALL HIGH-TERRAIN EXPOSURE WINDOWS COVERED"
        ),
    )
    text_y -= 14
    column_width = (width - 2 * margin - 3 * pad) / 2
    column_positions = [margin + pad, margin + 2 * pad + column_width]
    for index, finding in enumerate(unresolved[:4]):
        data = finding.get("data") or {}
        event = _event_for_id(events, data.get("terrain_event_id"))
        column_x = column_positions[index % 2]
        entry_y = text_y - (index // 2) * 46
        maximum = (event or {}).get("maximum") or {}
        title = (
            f"{_terr_ref(events, event)} | "
            f"{(event or {}).get('first_high', {}).get('name', '?')}"
        )
        if maximum:
            title += f" {int(maximum.get('msa_hundreds_ft') or 0)}*"
        canvas.setFillColor(theme.AMBER)
        canvas.setFont(theme.SANS_BOLD, 6.6)
        canvas.drawString(column_x, entry_y, title)
        lines = []
        if event is not None:
            first = event["first_high"]
            end = event.get("drop") or event["last_high"]
            exposure = (
                f"{format_actm(first.get('actm_minutes'))}-"
                f"{format_actm(end.get('actm_minutes'))}"
            )
            start_utc = _actm_utc(flight, first.get("actm_minutes"))
            end_utc = _actm_utc(flight, end.get("actm_minutes"))
            if start_utc and end_utc:
                exposure += f" / {start_utc}-{end_utc}"
            lines.append(exposure)
            lines.append(
                f"Filed leg: {_filed_segment(flight, event)}. "
                "No exact chart match in mounted index."
            )
        lines.append(
            "Status remains manual profile-index review; "
            "no generic terrain chart inserted."
        )
        canvas.setFillColor(theme.MUTED)
        canvas.setFont(theme.SANS, 5.4)
        line_y = entry_y - 9
        for line in lines:
            canvas.drawString(column_x, line_y, line[:118])
            line_y -= 8
    if not unresolved:
        profile_refs = ", ".join(
            f"PROFILE {(finding.get('data') or {}).get('chart_number')}"
            for finding in matched
        )
        event_refs = ", ".join(
            _terr_ref(
                events,
                _event_for_id(
                    events,
                    (finding.get("data") or {}).get("terrain_event_id"),
                ),
            )
            for finding in matched_events
        )
        canvas.setFillColor(theme.MUTED)
        canvas.setFont(theme.SANS, 5.8)
        canvas.drawString(
            margin + pad,
            text_y,
            (
                f"{event_refs or 'All detected windows'} covered by "
                f"{profile_refs or 'the approved profile set'}; "
                "no nearby or generic chart substituted."
            )[:180],
        )

    # Method + source pointer.
    canvas.setFillColor(theme.BLUE)
    canvas.setFont(theme.SANS_BOLD, 5.8)
    canvas.drawString(margin + pad, panel_bottom + 22, "METHOD")
    canvas.setFillColor(theme.MUTED)
    canvas.setFont(theme.SANS, 5.6)
    canvas.drawString(
        margin + pad + 44,
        panel_bottom + 22,
        (
            "A350 Depressurization Profiles P2: identify >10,000 ft region, "
            "verify route/airways and aircraft effectivity."
        ),
    )
    canvas.setFillColor(theme.GREEN)
    canvas.setFont(theme.SANS_BOLD, 6.0)
    canvas.drawString(
        margin + pad,
        panel_bottom + 10,
        "FULL AUTHORITATIVE SOURCE CHARTS: LEVEL 2 SOURCE-CHART PAGES",
    )
    button_x = width - margin - pad
    for finding in reversed(matched[:2]):
        chart = str((finding.get("data") or {}).get("chart_number") or "")
        label = f"OPEN PROFILE {chart}"
        button_width = pdfmetrics.stringWidth(label, theme.SANS_BOLD, 6.2) + 26
        button_x -= button_width
        canvas.setStrokeColor(theme.BLUE)
        canvas.setLineWidth(0.9)
        canvas.setFillColor(theme.PAGE_BG)
        canvas.roundRect(button_x, panel_bottom + 8, button_width, 16, 8, stroke=1, fill=1)
        canvas.setFillColor(theme.TEXT)
        canvas.setFont(theme.SANS_BOLD, 6.2)
        canvas.drawCentredString(
            button_x + button_width / 2, panel_bottom + 13.5, label
        )
        button_x -= 10

    # Chips + footer.
    chips: list[str] = []
    pages = sorted(
        {
            waypoint.get("source_page")
            for event in events
            for waypoint in (
                event.get("first_high"),
                event.get("last_high"),
                event.get("maximum"),
            )
            if waypoint and waypoint.get("source_page")
        }
    )
    if pages:
        chips.append(
            "CFP P" + "-".join(str(page) for page in (pages[0], pages[-1]))
            if len(pages) > 1
            else f"CFP P{pages[0]}"
        )
    for finding in matched[:2]:
        chart = str((finding.get("data") or {}).get("chart_number") or "")
        if chart:
            chips.append(f"PROFILE {chart}")
    theme.draw_source_chips(canvas, chips, width=width)
    theme.draw_footer(
        canvas,
        flight,
        width=width,
        page_number=page_number,
        page_count=page_count,
    )

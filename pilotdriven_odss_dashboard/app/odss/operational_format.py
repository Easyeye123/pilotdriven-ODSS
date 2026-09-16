"""Six-page Flight Briefing composition in David's reference format.

9 Sep 2026: "This format from beginning has always been this. Get this right,
and then we talk about tweaking from this." His references
(SQ910_21AUG2026, SQ481_25AUG2026 REV5, SQ38_28AUG2026) are six landscape
pages - OVERVIEW, DECISION ANALYSIS, PERFORMANCE / FUEL / TECH,
AIRPORTS / ALTERNATES, WEATHER / ROUTE HAZARDS, ENROUTE / INTAM / ASSURANCE -
each carrying the navigation ribbon and the footer triplet.

This module projects the existing governed briefing view into that format. It
does not analyse weather, infer aircraft limitations, or import facts from a
reference flight. Cards fail closed on capacity overflow: text is never
truncated to fit and body type never drops below the published readable
floor.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
import re
from typing import Any

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.pdfbase.pdfmetrics import stringWidth

from .analysed_briefing_content import (cyclone_content, deferred_item_label,
                                        release_condition_groups)
from .analysed_briefing_map import (build_publication_map, draw_publication_map,
                                    publication_key_entries)
from .constants import format_actm
from .page_one_weather import forecast_source_line, page_one_metar_field, page_one_taf_field
from .weather_publication import edto_window_lines, sigmet_lines, volcanic_ash_lines

SIZE = landscape(A4)
MARGIN = 28.0
GAP = 11.0
TOP = 494.0
BOTTOM = 40.0
# Readable floor for every published glyph is 8.9pt; the body ladder never
# goes below 9.0 and a page that still does not fit fails closed.
BODY = 9.6
LEADING = 11.6
BODY_LADDER = ((9.6, 11.6), (9.3, 11.2), (9.0, 10.8), (9.0, 10.3))
LABEL = 9.0
CARD_TITLE = 11.0
BG = colors.HexColor("#061321")
PANEL = colors.HexColor("#102237")
BORDER = colors.HexColor("#315269")
WHITE = colors.HexColor("#F2F5FA")
MUTED = colors.HexColor("#B1C0CD")
# Taxiways on the airport figure: a tone under the runways' MUTED so weight
# and tone separate the two, but never a hairline (9 Sep 2026, "no taxiways").
TAXIWAY = colors.HexColor("#8DA2B6")
APRON = colors.HexColor("#64748B")
CYAN = colors.HexColor("#50D5EF")
GREEN = colors.HexColor("#42D6A3")
AMBER = colors.HexColor("#FFBC38")
RED = colors.HexColor("#FF5267")
VIOLET = colors.HexColor("#B48CF2")
CREW_REVIEW = "BRIEFING FOR CREW REVIEW - CURRENT SOURCE VERIFICATION REQUIRED"
FOOTER_DISCLAIMER = "UTC · NOT FOR NAVIGATION"


def text(value: Any, missing: str = "Not held") -> str:
    return str(value).strip() if value is not None and str(value).strip() else missing


# A TAF change group starts at one of these markers and runs to the next one.
# Only the source text between them is ever published; nothing is paraphrased.
_TAF_CHANGE_MARKER = re.compile(
    r"\b(?:PROB(?:30|40)(?:\s+TEMPO)?|TEMPO|BECMG|FM\d{6})\b",
    re.IGNORECASE,
)


def taf_tempo_field(taf: Any) -> str:
    """David's page-1 destination field, verbatim from the source TAF.

    His reference briefing labels the destination weather field ``TAF TEMPO``
    and prints the TAF's temporary group under it; ours printed a bare ``TAF``
    with the whole forecast. Binding rule 7 - where his reference and our
    output disagree, his reference wins - so the label is his and the value has
    to match the label.

    An absent TEMPO is named, never published as fair weather: "coverage gap is
    not NIL" applies to a forecast group exactly as it does to a screening
    result.
    """
    body = " ".join(str(taf or "").split())
    if not body:
        return text(None)
    starts = [match.start() for match in _TAF_CHANGE_MARKER.finditer(body)]
    groups = []
    for index, start in enumerate(starts):
        end = starts[index + 1] if index + 1 < len(starts) else len(body)
        segment = body[start:end].strip().rstrip("=").strip()
        if segment.upper().startswith(("TEMPO", "PROB")):
            groups.append(segment)
    if groups:
        return " ".join(groups)
    return (
        "No TEMPO group in the source TAF; the forecast groups for the "
        "arrival window are on the WEATHER page."
    )


def kg(value: Any) -> str:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return f"{value:,.0f} kg"
    return "Not held"


def clock(value: Any) -> str:
    value = text(value)
    return value + "Z" if len(value) == 4 and value.isdigit() else value


def utc_label(value: Any) -> str:
    from datetime import datetime
    try:
        stamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return stamp.strftime("%d%b %H%MZ").upper() if stamp.tzinfo else "not held"
    except (ValueError, TypeError):
        return "not held"


def unique(values: list[Any]) -> list[str]:
    return list(dict.fromkeys(str(v).strip() for v in values if v is not None and str(v).strip()))


def wrap(value: str, width: float, *, font: str = "Helvetica", size: float = BODY) -> list[str]:
    """Wrap without ellipsis, including unbroken source tokens."""
    lines: list[str] = []
    for paragraph in str(value).splitlines() or [""]:
        line = ""
        for word in paragraph.split():
            candidate = f"{line} {word}".strip()
            if stringWidth(candidate, font, size) <= width:
                line = candidate
                continue
            if line:
                lines.append(line)
                line = ""
            while stringWidth(word, font, size) > width:
                end = len(word) - 1
                while end > 1 and stringWidth(word[:end], font, size) > width:
                    end -= 1
                lines.append(word[:end])
                word = word[end:]
            line = word
        lines.append(line)
    return lines


# Registry suffixes that repeat on nearly every name and cost header width.
_NAME_NOISE = {"INTERNATIONAL", "AIRPORT", "REGIONAL", "MUNICIPAL", "FIELD"}


def airport_short_name(icao: Any) -> str:
    """Registry name without its repeated suffix words; ICAO stays beside it."""
    words = [word for word in airport_name(icao).split() if word not in _NAME_NOISE]
    return " ".join(words) or airport_name(icao)


def airport_name(icao: Any) -> str:
    """Airport name from the pinned offline registry; never inferred."""
    from .brief_theme import _airport_local_registry
    entry = _airport_local_registry().get(str(icao or "").upper()) or {}
    name = str(entry.get("name") or "").strip()
    return name.upper() if name else "NAME NOT HELD"


@dataclass
class Card:
    title: str
    paragraphs: list[str] = field(default_factory=list)
    accent: Any = field(default_factory=lambda: CYAN)
    target: str | None = None
    left_aligned: bool = True
    top_aligned: bool = True
    paragraph_gap: float = 0
    width_weight: float = 1
    kind: str = "text"
    payload: Any = None
    tag: str | None = None


@dataclass
class CardBox:
    card: Card
    x: float
    y: float
    width: float
    height: float
    rows: list[tuple[float, list[tuple]]] = field(default_factory=list)


@dataclass
class Page:
    title: str
    bookmark: str
    ribbon_index: int = 0
    assurance: str = ""
    aliases: tuple[str, ...] = ()
    boxes: list[CardBox] = field(default_factory=list)
    body: float = BODY
    leading: float = LEADING


def title_layout(card: Card, width: float) -> tuple[float, list[str]]:
    """Fit the card title beside its provenance tag before wrapping it."""
    reserved = stringWidth(card.tag, "Helvetica-Bold", LABEL) + 12 if card.tag else 0
    available = width - 20 - reserved
    size = CARD_TITLE
    while size > 9.0 and stringWidth(card.title, "Helvetica-Bold", size) > available:
        size -= 0.25
    return size, wrap(card.title, available, font="Helvetica-Bold", size=size)


def head_height(card: Card, width: float) -> float:
    if not card.title:
        return 0.0
    size, lines = title_layout(card, width)
    return len(lines) * (size + 2.5) + 5.0


def card_rows(card: Card, width: float, body: float, leading: float) -> list[tuple[float, list[tuple]]]:
    """One entry per baseline: (gap_before, [(text, font, size, colour, align)]).

    ``align`` is ``left``/``right``/``centre`` inside the card's inner box.
    """
    inner = width - 28
    rows: list[tuple[float, list[tuple]]] = []

    def para(value, font="Helvetica", size=None, colour=WHITE, gap=0.0, align="left"):
        size = body if size is None else size
        for index, line in enumerate(wrap(str(value), inner, font=font, size=size)):
            rows.append(((gap if index == 0 else 0.0), [(line, font, size, colour, align)]))

    if card.kind == "station":
        icao, name, blocks = card.payload
        rows.append((0.0, [(str(icao), "Helvetica-Bold", 13.0, card.accent, "left")]))
        para(name, size=body, colour=MUTED, gap=2.0)
        for label, values in blocks:
            single = values[0] if len(values) == 1 else None
            if single is not None and (stringWidth(label, "Helvetica-Bold", LABEL)
                                       + stringWidth(str(single), "Helvetica", body) + 8) <= inner:
                rows.append((4.0, [(label, "Helvetica-Bold", LABEL, card.accent, "left"),
                                   (str(single), "Helvetica", body, WHITE, "offset")]))
                continue
            para(label, font="Helvetica-Bold", size=LABEL, colour=card.accent, gap=4.0)
            for value in values:
                para(value, colour=WHITE)
        return rows
    if card.kind == "tile":
        for label, value in card.payload or []:
            label_width = stringWidth(str(label), "Helvetica-Bold", LABEL)
            value_width = stringWidth(str(value), "Helvetica-Bold", body)
            if label_width + value_width + 8 <= inner:
                rows.append((2.0, [(str(label), "Helvetica-Bold", LABEL, MUTED, "left"),
                                   (str(value), "Helvetica-Bold", body, WHITE, "right")]))
            else:
                para(label, font="Helvetica-Bold", size=LABEL, colour=MUTED, gap=2.0)
                para(value, font="Helvetica-Bold", colour=WHITE)
        for note in card.paragraphs:
            para(note, colour=MUTED, gap=5.0)
        return rows
    if card.kind == "strip":
        status, detail = card.payload
        rows.append((0.0, [(str(status), "Helvetica-Bold", body, card.accent, "centre")]))
        for line in detail:
            para(line, colour=MUTED, gap=1.0, align="centre")
        return rows
    if card.kind == "finding":
        pill, headline, summary, source = card.payload
        # The headline is wrapped once, at the width it is drawn beside the
        # severity pill: a second measurement would drop or repeat words.
        indent = stringWidth(pill, "Helvetica-Bold", LABEL) + 20
        headline_lines = wrap(str(headline), inner - indent, font="Helvetica-Bold", size=body)
        rows.append((0.0, [(pill, "Helvetica-Bold", LABEL, BG, "pill"),
                           (headline_lines[0] if headline_lines else "",
                            "Helvetica-Bold", body, WHITE, "pill-text")]))
        for line in headline_lines[1:]:
            rows.append((0.0, [(line, "Helvetica-Bold", body, WHITE, "left")]))
        para(summary, colour=MUTED, gap=4.0)
        para(source, size=LABEL, colour=card.accent, gap=3.0, align="right")
        return rows
    for index, paragraph in enumerate(card.paragraphs):
        para(paragraph, colour=WHITE, gap=card.paragraph_gap if index else 0.0)
    return rows


def rows_height(rows, leading: float) -> float:
    return sum(gap + leading for gap, _ in rows)


# The least a drawn figure is given inside an airport column: A1's figure band
# floor, below which the field is a thumbnail.
STACK_FIGURE_MIN = 104.0
# A row height that asks ``plan_page`` for every point the measured rows
# leave: the minimum is its own content, the preferred exceeds any page.
TAKES_REMAINING_HEIGHT = (0.0, 9_999.0)


def card_height(card: Card, width: float, body: float, leading: float) -> float:
    if card.kind in {"map", "figure", "timeline"}:
        return 0.0
    if card.kind == "stack":
        # An airport column: its measured cards plus the figure floor.
        children = list(card.payload or [])
        return sum(STACK_FIGURE_MIN if child.kind == "figure" else card_height(child, width, body, leading)
                   for child in children) + GAP * max(0, len(children) - 1)
    rows = card_rows(card, width, body, leading)
    # 6pt above the title and 4pt of clearance under the last baseline.
    return head_height(card, width) + rows_height(rows, leading) + 10.0


def stack_boxes(card: Card, x: float, top: float, width: float, height: float,
                body: float, leading: float) -> list["CardBox"]:
    """Lay one airport column out top-down: measured cards keep their measured
    height; the figure takes whatever the column has left (never below its
    floor, which ``card_height`` already reserved)."""
    children = list(card.payload or [])
    measured = {index: card_height(child, width, body, leading)
                for index, child in enumerate(children) if child.kind != "figure"}
    figures = [index for index, child in enumerate(children) if child.kind == "figure"]
    remaining = height - sum(measured.values()) - GAP * max(0, len(children) - 1)
    boxes = []
    for index, child in enumerate(children):
        child_height = measured.get(index, remaining / len(figures) if figures else 0.0)
        box = CardBox(child, x, top - child_height, width, child_height)
        if child.kind not in {"map", "figure", "timeline"}:
            box.rows = card_rows(child, width, body, leading)
        boxes.append(box)
        top -= child_height + GAP
    return boxes


def row_widths(cards: list[Card], full_width: float) -> list[float]:
    usable = full_width - GAP * (len(cards) - 1)
    total = sum(card.width_weight for card in cards)
    return [usable * card.width_weight / total for card in cards]


def plan_page(title: str, bookmark: str, rows: list[tuple[Any, list[Card]]], *,
              ribbon_index: int = 0, assurance: str = "", aliases: tuple[str, ...] = (),
              body: float = BODY, leading: float = LEADING) -> list[Page]:
    """Fit the reference grid at a readable size; never spill source text.

    A row height may be a fixed number, ``None`` (measured from its content)
    or ``(minimum, preferred)`` for a drawn figure that may be compressed to
    give measured text the room it needs. Slack is shared out so the page
    reads as a full page rather than a short column.
    """
    full_width = SIZE[0] - 2 * MARGIN
    page = Page(title, bookmark, ribbon_index=ribbon_index, assurance=assurance,
                aliases=aliases, body=body, leading=leading)
    budget = TOP - BOTTOM - GAP * (len(rows) - 1)
    lows: list[float] = []
    highs: list[float] = []
    for height, cards in rows:
        widths = row_widths(cards, full_width)
        needed = max([card_height(card, width, body, leading)
                      for card, width in zip(cards, widths)] or [0.0])
        if height is None:
            lows.append(needed)
            highs.append(needed)
        elif isinstance(height, tuple):
            lows.append(max(height[0], needed))
            highs.append(max(height[1], needed))
        else:
            if needed > height + 0.01:
                raise ValueError(
                    f"Concise PDF capacity exceeded in {title}: {needed:.0f}pt of "
                    f"content in a {height:.0f}pt row. No source continuation is permitted.")
            lows.append(float(height))
            highs.append(float(height))
    if sum(lows) > budget + 0.01:
        raise ValueError(
            f"Concise PDF capacity exceeded in {title}: {sum(lows):.0f}pt of content "
            f"in {budget:.0f}pt of page. No source continuation is permitted.")
    heights = list(lows)
    slack = budget - sum(heights)
    wanted = sum(high - low for low, high in zip(lows, highs))
    if wanted > 0:
        share = min(1.0, slack / wanted)
        heights = [low + (high - low) * share for low, high in zip(lows, highs)]
        slack = budget - sum(heights)
    if slack > 0 and heights:
        heights = [height + slack / len(heights) for height in heights]
    top = TOP
    for (_, cards), height in zip(rows, heights):
        widths = row_widths(cards, full_width)
        x = MARGIN
        for card, width in zip(cards, widths):
            if card.kind == "stack":
                page.boxes.extend(stack_boxes(card, x, top, width, height, body, leading))
                x += width + GAP
                continue
            box = CardBox(card, x, top - height, width, height)
            if card.kind not in {"map", "figure", "timeline"}:
                box.rows = card_rows(card, width, body, leading)
            page.boxes.append(box)
            x += width + GAP
        top -= height + GAP
    return [page]


def plan_page_flexible(title, bookmark, rows_for, *, variants=(0,), **kwargs) -> list[Page]:
    """Try each grid variant on the readable body ladder before failing closed.

    Column width, not type size, is the first lever: a dense source-bound card
    is given more of the row before the body steps down, and the body never
    steps below the published readable floor.
    """
    last: ValueError | None = None
    for variant in variants:
        for body, leading in BODY_LADDER:
            try:
                return plan_page(title, bookmark, rows_for(body, leading, variant),
                                 body=body, leading=leading, **kwargs)
            except ValueError as exc:
                last = exc
    raise last


def draw_chrome(canvas, flight: dict[str, Any], view: dict[str, Any], page: Page,
                number: int, count: int) -> None:
    from .concise_pdf_gate import NAV_RIBBON
    width, height = SIZE
    identity = view.get("flight_identity") or {}
    canvas.setFillColor(BG)
    canvas.rect(0, 0, width, height, fill=1, stroke=0)

    canvas.setFillColor(CYAN)
    canvas.setFont("Helvetica-Bold", 12.5)
    canvas.drawString(MARGIN, height - 24, "PILOTDRIVEN")
    canvas.setFillColor(MUTED)
    canvas.setFont("Helvetica", LABEL)
    canvas.drawString(MARGIN, height - 37, FOOTER_DISCLAIMER)

    canvas.setFillColor(WHITE)
    canvas.setFont("Helvetica-Bold", 15)
    canvas.drawString(MARGIN + 150, height - 24, text(view.get("flight_number")))
    canvas.setFont("Helvetica", 10)
    canvas.drawString(MARGIN + 150, height - 37, text(view.get("route_label")))
    canvas.setFillColor(MUTED)
    canvas.setFont("Helvetica", LABEL)
    names = (f"{airport_short_name(flight.get('departure'))} to "
             f"{airport_short_name(flight.get('destination'))}")
    if stringWidth(names, "Helvetica", LABEL) <= 268:
        canvas.drawString(MARGIN + 150, height - 48, names)

    canvas.setFillColor(WHITE)
    canvas.setFont("Helvetica-Bold", 10.5)
    canvas.drawString(MARGIN + 430, height - 24, text(view.get("flight_date")))
    # The schedule, the filed plan and the ATOT-derived target all stay on the
    # page: a calculated arrival is never printed as if it were the schedule.
    actual = identity.get("actual_takeoff_hhmm")
    schedule = " | ".join((
        f"ETD {clock(identity.get('etd_hhmm'))}",
        f"STA {clock(identity.get('scheduled_eta_hhmm'))}",
        f"SCHED {text(identity.get('block'))}",
        f"FPL EET {text((view.get('metrics') or {}).get('eet'))}"))
    clocks = " | ".join((
        f"CI{text(identity.get('cost_index'))}", text(identity.get("rules")),
        f"ATOT {clock(actual)}" if actual else "ATOT not entered",
        f"TARGET ARRIVAL {clock(identity.get('eta_hhmm'))}" if actual
        else "TARGET ARRIVAL NOT CALCULATED"))
    available = width - MARGIN - (MARGIN + 430)
    lines: list[str] = []
    for part in schedule.split(" | ") + clocks.split(" | "):
        joined = f"{lines[-1]} | {part}" if lines else part
        if lines and stringWidth(joined, "Helvetica", LABEL) <= available:
            lines[-1] = joined
        else:
            lines.append(part)
    if len(lines) > 2 or any(stringWidth(line, "Helvetica", LABEL) > available for line in lines):
        raise ValueError("Flight identity header exceeds the readable width: " + " | ".join(lines))
    canvas.setFont("Helvetica", LABEL)
    for index, line in enumerate(lines):
        canvas.setFillColor(WHITE if index == 0 else MUTED)
        canvas.drawString(MARGIN + 430, height - 37 - index * 11, line)
    canvas.setFillColor(WHITE)
    canvas.setFont("Helvetica", LABEL)
    canvas.drawRightString(width - MARGIN, height - 24, " | ".join((
        text(identity.get("aircraft_type")), text(identity.get("registration")),
        f"OFP {text(identity.get('ofp'), 'unavailable')}")))

    # Navigation ribbon: the reference underlines the active section.
    ribbon_y = height - 66
    x = MARGIN
    for index, item in enumerate(NAV_RIBBON):
        active = index == page.ribbon_index
        canvas.setFont("Helvetica-Bold" if active else "Helvetica", 9.5)
        canvas.setFillColor(WHITE if active else MUTED)
        canvas.drawString(x, ribbon_y, item)
        item_width = stringWidth(item, "Helvetica-Bold" if active else "Helvetica", 9.5)
        if active:
            canvas.setStrokeColor(CYAN)
            canvas.setLineWidth(1.6)
            canvas.line(x, ribbon_y - 4.5, x + item_width, ribbon_y - 4.5)
        x += item_width + 10
        if index < len(NAV_RIBBON) - 1:
            canvas.setFillColor(BORDER)
            canvas.setFont("Helvetica", 9.5)
            canvas.drawString(x, ribbon_y, "·")
            x += 10
    canvas.setFillColor(MUTED)
    canvas.setFont("Helvetica", 9.5)
    canvas.drawRightString(width - MARGIN, ribbon_y,
                           f"FLIGHT BRIEFING | PAGE {number} OF {count}")
    canvas.setStrokeColor(BORDER)
    canvas.setLineWidth(0.6)
    canvas.line(MARGIN, ribbon_y - 11, width - MARGIN, ribbon_y - 11)

    canvas.setFillColor(WHITE)
    size = 12.5
    while size > 9.6 and stringWidth(page.title, "Helvetica-Bold", size) > 430:
        size -= 0.25
    canvas.setFont("Helvetica-Bold", size)
    canvas.drawString(MARGIN, height - 93, page.title)
    canvas.setFillColor(AMBER)
    canvas.setFont("Helvetica-Bold", LABEL)
    canvas.drawRightString(width - MARGIN, height - 93, CREW_REVIEW)

    canvas.setStrokeColor(BORDER)
    canvas.line(MARGIN, 30, width - MARGIN, 30)
    left = " | ".join((
        text(view.get("flight_number")), text(view.get("flight_date")),
        f"{text(flight.get('departure'))}-{text(flight.get('destination'))}",
        f"{text(identity.get('aircraft_type'))} {text(identity.get('registration'))}",
        f"OFP {text(identity.get('ofp'), 'unavailable')}"))
    right = f"Page {number} of {count}"
    centre = page.assurance
    canvas.setFont("Helvetica", LABEL)
    left_width = stringWidth(left, "Helvetica", LABEL)
    centre_width = stringWidth(centre, "Helvetica", LABEL)
    right_width = stringWidth(right, "Helvetica", LABEL)
    if left_width + centre_width + right_width + 24 > width - 2 * MARGIN:
        raise ValueError(f"Footer triplet exceeds the readable page width on page {number}")
    start = MARGIN + left_width + 12
    end = width - MARGIN - right_width - 12
    centre_x = width / 2 - centre_width / 2
    if centre_x < start or centre_x + centre_width > end:
        centre_x = start + (end - start - centre_width) / 2
    canvas.setFillColor(MUTED)
    canvas.drawString(MARGIN, 19, left)
    canvas.setFillColor(CYAN)
    canvas.drawString(centre_x, 19, centre)
    canvas.setFillColor(MUTED)
    canvas.drawRightString(width - MARGIN, 19, right)
    canvas.linkRect("Return to overview", "sec_overview",
                    (width - 150, 10, width - MARGIN, 28), relative=0, thickness=0)


def draw_severity_pill(canvas, x, y, label, accent) -> float:
    label_width = stringWidth(label, "Helvetica-Bold", LABEL)
    canvas.setFillColor(accent)
    canvas.roundRect(x, y - 3, label_width + 12, LABEL + 6, 3, fill=1, stroke=0)
    canvas.setFillColor(BG)
    canvas.setFont("Helvetica-Bold", LABEL)
    canvas.drawString(x + 6, y, label)
    return label_width + 12


def draw_decision_timeline(canvas, entries, x, y, width, height) -> None:
    """Dots for DEP, waypoints, ETP, TOD and arrival, annotated and staggered."""
    if not entries:
        canvas.setFillColor(MUTED)
        canvas.setFont("Helvetica", LABEL)
        canvas.drawString(x, y + height / 2, "No route anchor is held in the OFP for a decision timeline.")
        return
    rail = y + height / 2
    canvas.setStrokeColor(BORDER)
    canvas.setLineWidth(1.0)
    canvas.line(x, rail, x + width, rail)
    step = width / max(1, len(entries) - 1) if len(entries) > 1 else 0
    for index, entry in enumerate(entries):
        cx = x + (index * step if len(entries) > 1 else width / 2)
        accent = {"DEP": GREEN}.get(str(entry.get("label")), CYAN)
        above = index % 2 == 0
        canvas.setFillColor(accent)
        canvas.circle(cx, rail, 3.4, stroke=0, fill=1)
        label = str(entry.get("label") or "")
        sub = str(entry.get("sub") or "")
        when = " · ".join(part for part in (str(entry.get("time") or "--"), sub) if part)
        lines = [(label, "Helvetica-Bold", accent), (when, "Helvetica", MUTED)]
        widest = max(stringWidth(value, font, LABEL) for value, font, _ in lines)
        if widest > 2 * step - 6 and len(entries) > 1:
            raise ValueError("Decision timeline labels exceed the readable step width")
        baseline = rail + 9 if above else rail - 9 - LABEL
        for value, font, colour in lines:
            if baseline > y + height - LABEL or baseline < y:
                raise ValueError("Decision timeline annotation exceeds its panel")
            value_width = stringWidth(value, font, LABEL)
            canvas.setFillColor(colour)
            canvas.setFont(font, LABEL)
            canvas.drawString(min(max(x, cx - value_width / 2), x + width - value_width),
                              baseline, value)
            baseline += 10.5 if above else -10.5


def draw_page(canvas, flight, view, page: Page, number: int, count: int) -> None:
    draw_chrome(canvas, flight, view, page, number, count)
    canvas.bookmarkPage(page.bookmark, fit="XYZ", left=0, top=SIZE[1], zoom=0)
    # Evidence destinations named by the engine keep resolving after the
    # nine-page sections were folded into six.
    for alias in page.aliases:
        canvas.bookmarkPage(alias, fit="XYZ", left=0, top=SIZE[1], zoom=0)
    canvas.addOutlineEntry(page.title, page.bookmark, level=0)
    for box in page.boxes:
        card = box.card
        canvas.setFillColor(PANEL)
        canvas.setStrokeColor(BORDER)
        canvas.roundRect(box.x, box.y, box.width, box.height, 6, stroke=1, fill=1)
        if card.target:
            canvas.linkRect(f"Open {card.title} detail", card.target,
                            (box.x, box.y, box.x + box.width, box.y + box.height),
                            relative=0, thickness=0)
        top = box.y + box.height - 6
        if card.title:
            size, title_lines = title_layout(card, box.width)
            canvas.setFont("Helvetica-Bold", size)
            canvas.setFillColor(card.accent)
            baseline = top - size
            for line in title_lines:
                canvas.drawString(box.x + 14, baseline, line)
                baseline -= size + 2.5
            if card.tag:
                canvas.setFont("Helvetica-Bold", LABEL)
                canvas.setFillColor(MUTED)
                canvas.drawRightString(box.x + box.width - 14, top - size, card.tag)
            top = baseline + size - 5.0
        if card.kind == "map":
            draw_publication_map(canvas, card.payload, box.x + 6, box.y + 6,
                                 box.width - 12, top - box.y - 6, show_key=False)
            continue
        if card.kind == "figure":
            overlay, planned_runway, *rest = card.payload
            draw_airport_figure(canvas, overlay, box.x + 6, box.y + 6, box.width - 12,
                                top - box.y - 6, planned_runway=planned_runway,
                                index_entry=rest[0] if rest else None)
            continue
        if card.kind == "timeline":
            draw_decision_timeline(canvas, card.payload, box.x + 22, box.y + 8,
                                   box.width - 44, top - box.y - 10)
            continue
        inner_left = box.x + 14
        inner_right = box.x + box.width - 14
        baseline = top - page.leading
        for gap, items in box.rows:
            baseline -= gap
            if baseline < box.y + 3.99:
                raise ValueError(f"Card body exceeds measured capacity: {card.title}")
            pill_x = inner_left
            cursor_x = inner_left
            for value, font, size, colour, align in items:
                if align == "pill":
                    pill_x = inner_left + draw_severity_pill(canvas, inner_left, baseline,
                                                             value, card.accent) + 8
                    cursor_x = pill_x
                    continue
                canvas.setFont(font, size)
                canvas.setFillColor(colour)
                if align == "offset":
                    canvas.drawString(cursor_x, baseline, value)
                elif align == "right":
                    canvas.drawRightString(inner_right, baseline, value)
                elif align == "centre":
                    canvas.drawCentredString(box.x + box.width / 2, baseline, value)
                elif align == "pill-text":
                    canvas.drawString(pill_x, baseline, value)
                else:
                    canvas.drawString(inner_left, baseline, value)
                    cursor_x = inner_left + stringWidth(value, font, size) + 6
            baseline -= page.leading


def analysed_airport_overlay(overlay, analysis):
    """Bind evaluated runway consequences to existing, supplied geometry only."""
    from copy import deepcopy
    result = deepcopy(overlay) if overlay else None
    if result is None:
        return None
    features = (result.get("featureCollection") or {}).get("features") or []
    for effect in analysis.get("surface_effects") or []:
        runways = set(effect.get("runways") or [])
        feature_ids = [f.get("id") for f in features
                       if (f.get("properties") or {}).get("aeroway") == "runway"
                       and set(str((f.get("properties") or {}).get("ref") or "").split("/")) & runways]
        if feature_ids:
            # The evaluated schedule replaces this source's coarse mark for
            # these runway features. Other notices remain independent, so an
            # overlapping active restriction still takes precedence.
            retained = []
            for mark in result.get("mapped") or []:
                if (mark.get("notamNumber") == effect["notam_id"] and mark.get("entityType") == "runway"
                        and mark.get("markClass") in {"closure", "scheduled"}):
                    remaining = [fid for fid in mark.get("featureIds") or [] if fid not in feature_ids]
                    if remaining:
                        retained.append({**mark, "featureIds": remaining})
                else:
                    retained.append(mark)
            result["mapped"] = retained
            result.setdefault("mapped", []).append({
                **effect, "notamNumber": effect["notam_id"], "entityType": "runway",
                "entityRef": "/".join(effect["runways"]), "featureIds": feature_ids,
            })
    return result


def surface_figure_gap(overlay, index_entry=None) -> tuple[str, str]:
    """The fallback headline and a reason naming which source is missing.

    9 Sep 2026, "WSSS DEPARTURE SURFACE": one centred sentence in an empty
    panel - "This doesn't work?". The reason is read from what the app
    published: its overlay, or - when it published none - its airport index
    entry, which records whether the OFP station package the overlay is
    built from was held at all. Nothing about the airport is guessed.
    """
    headline = "Airport surface geometry is not held in this analysis."
    if not overlay:
        entry = index_entry if isinstance(index_entry, dict) else {}
        status = str(entry.get("stationStatus") or "").strip().lower()
        if status in {"unavailable", "error"}:
            source = str(entry.get("sourceLabel") or "uploaded OFP station package").strip()
            return headline, (
                f"Missing source: the app's airport index records the OFP station package "
                f"for this airport as {status} ({source}), so no surface overlay was "
                "requested for it.")
        if status == "held":
            return headline, (
                "Missing source: the OFP station package is held, but the app's surface "
                "lookup published no overlay for this airport in this analysis (the lookup "
                "failed or was refused; the app's analysis warnings carry the reason).")
        return headline, (
            "Missing source: no OpenStreetMap surface overlay was published for "
            "this airport by the app's surface lookup for this analysis.")
    features = (overlay.get("featureCollection") or {}).get("features") or []
    if not features:
        stood_in = (overlay.get("source") or {}).get("stale") is True
        return headline, (
            "Missing source: the OpenStreetMap extract held no report-eligible "
            "runway, taxiway or apron geometry for this airport (nothing verified "
            "inside the exact aerodrome boundary), so no figure bounds were published"
            + (" (a cached extract stood in for a failed refresh)." if stood_in else "."))
    return headline, (
        "Missing source: the published overlay carries geometry but no figure bounds.")


def surface_outline_gap(overlay) -> str | None:
    """Why a drawn figure has no field outline, read from the contract.

    17 Sep 2026 review: with the legend honest, a figure drawn from an
    extract that predates the outline (report scope 1, stood in for a failed
    refresh) simply lost its dashed outline and its caption, and nothing on
    the page said why. The app states the extract's report scope and whether
    it was a cached copy under ``source``; the reason is read from those and
    never guessed. ``None`` when an outline was published.
    """
    boundary = (overlay or {}).get("aerodromeBoundary") or {}
    if any(isinstance(ring, list) and len(ring) >= 4 for ring in boundary.get("outer") or []):
        return None
    source = (overlay or {}).get("source") or {}
    scope = source.get("reportScopeVersion")
    stale = source.get("stale") is True
    if not isinstance(scope, int) or isinstance(scope, bool):
        return "no field outline published"
    if scope < 2:
        return ("no field outline: cached extract predates it; refresh failed" if stale
                else "no field outline: the extract predates it")
    return "no field outline: none established from OpenStreetMap"


def scale_bar_metres(points_per_metre: float, max_points: float) -> int:
    """The longest round ground distance whose bar fits in ``max_points``."""
    for metres in (10_000, 5_000, 2_500, 2_000, 1_000, 500, 250, 200, 100, 50, 20, 10):
        if metres * points_per_metre <= max_points:
            return metres
    return 10


def draw_airport_figure(canvas, overlay, x, y, width, height, *, planned_runway=None,
                        index_entry=None) -> None:
    """Draw supplied geometry only; a scheduled/unknown mark is not a closure.

    9 Sep 2026: "This is also rubbish generated" - three bare runway lines, no
    taxiways, no apron, no scale. The figure strokes the exact aerodrome
    boundary the app computes, fills apron polygons as areas, strokes the
    taxiways at a readable weight, and carries a scale bar and a north arrow.
    Nothing is inferred: every stroke is a supplied feature, the outline is
    the published boundary, and the legend names only what was drawn.
    """
    import math
    from reportlab.pdfgen.canvas import FILL_EVEN_ODD
    from .surface_overlays import surface_mark_presentation

    overlay = overlay or {}
    bounds = overlay.get("bounds") or {}
    if not all(isinstance(bounds.get(k), (int, float)) for k in ("west", "south", "east", "north")):
        # Left-aligned at the top of the panel like a paragraph, with the
        # reason under it: "Even the alignment is centred .. it is not what's asked".
        headline, reason = surface_figure_gap(overlay, index_entry)
        canvas.setFillColor(WHITE)
        canvas.setFont("Helvetica", BODY)
        canvas.drawString(x + 6, y + height - 14, headline)
        canvas.setFillColor(MUTED)
        canvas.setFont("Helvetica", LABEL)
        baseline = y + height - 14 - LEADING
        for line in wrap(reason, width - 12, size=LABEL):
            canvas.drawString(x + 6, baseline, line)
            baseline -= LABEL + 2.5
        return
    marks = {}
    for mark in overlay.get("mapped") or []:
        presentation = surface_mark_presentation(mark)
        # Navaid failures do not become runway or taxiway road closures.
        if presentation in {"closure", "scheduled", "shortening"}:
            for feature_id in mark.get("featureIds") or []:
                # Partial extents must not paint the whole supplied way red.
                state = presentation if mark.get("scope") == "whole_entity" else "scheduled"
                priority = {None: 0, "scheduled": 1, "shortening": 2, "closure": 3}
                if priority[state] > priority[marks.get(feature_id)]:
                    marks[feature_id] = state
    west, south, east, north = (bounds[k] for k in ("west", "south", "east", "north"))
    if east <= west or north <= south:
        raise ValueError("Airport figure bounds are invalid")
    boundary = overlay.get("aerodromeBoundary") or {}
    rings = [ring for ring in [*(boundary.get("outer") or []), *(boundary.get("inner") or [])]
             if isinstance(ring, list) and len(ring) >= 4]
    # An outline the app could not publish is explained in a caption line
    # under the geometry; the geometry strip gives up that line's height.
    outline_gap = None if rings else surface_outline_gap(overlay)
    floor = 11 if outline_gap else 0
    if rings:
        # The figure is fitted to the whole field the outline encloses, not
        # only to the extract's own bounds, so the outline is never clipped.
        lons = [point[0] for ring in rings for point in ring]
        lats = [point[1] for ring in rings for point in ring]
        pad_x = (max(lons) - min(lons)) * 0.02
        pad_y = (max(lats) - min(lats)) * 0.02
        west, east = min(west, min(lons) - pad_x), max(east, max(lons) + pad_x)
        south, north = min(south, min(lats) - pad_y), max(north, max(lats) + pad_y)
    longitude_factor = max(0.01, math.cos(math.radians((south + north) / 2)))
    dx, dy = (east - west) * longitude_factor, north - south
    scale = min((width - 50) / dx, (height - 45 - floor) / dy)
    def point(coordinate):
        return (x + (width - dx * scale) / 2 + (coordinate[0] - west) * longitude_factor * scale,
                y + 28 + floor + (height - 45 - floor - dy * scale) / 2 + (coordinate[1] - south) * scale)

    # Chrome first, so runway labels are placed around it: the north arrow in
    # the right margin column and the scale bar in the top strip.
    occupied = []
    arrow_x, arrow_top = x + width - 13, y + height - 1
    canvas.setFillColor(WHITE)
    canvas.setStrokeColor(WHITE)
    canvas.setFont("Helvetica-Bold", 9)
    canvas.drawCentredString(arrow_x, arrow_top - 9, "N")
    head = canvas.beginPath()
    head.moveTo(arrow_x, arrow_top - 14)
    head.lineTo(arrow_x - 4, arrow_top - 22)
    head.lineTo(arrow_x + 4, arrow_top - 22)
    head.close()
    canvas.drawPath(head, stroke=0, fill=1)
    canvas.setLineWidth(1.2)
    canvas.line(arrow_x, arrow_top - 22, arrow_x, arrow_top - 33)
    occupied.append((arrow_x - 9, arrow_top - 35, arrow_x + 9, arrow_top + 1))

    points_per_metre = scale / 111_320.0
    metres = scale_bar_metres(points_per_metre, width * 0.28)
    bar_length = metres * points_per_metre
    bar_x, bar_y = x + 3, y + height - 8
    bar = canvas.beginPath()
    bar.moveTo(bar_x, bar_y - 2.5)
    bar.lineTo(bar_x, bar_y + 2.5)
    bar.moveTo(bar_x, bar_y)
    bar.lineTo(bar_x + bar_length, bar_y)
    bar.moveTo(bar_x + bar_length, bar_y - 2.5)
    bar.lineTo(bar_x + bar_length, bar_y + 2.5)
    canvas.drawPath(bar, stroke=1, fill=0)
    scale_label = f"{metres / 1000:g} km" if metres >= 1000 else f"{metres} m"
    canvas.setFont("Helvetica", 9)
    canvas.drawString(bar_x + bar_length + 6, bar_y - 3.2, scale_label)
    occupied.append((bar_x - 2, bar_y - 6, bar_x + bar_length + 8 + stringWidth(scale_label, "Helvetica", 9),
                     bar_y + 6))

    if rings:
        canvas.saveState()
        canvas.setStrokeColor(colors.HexColor("#6B8AA6"))
        canvas.setLineWidth(0.9)
        canvas.setDash(4, 3)
        for ring in rings:
            path = canvas.beginPath()
            path.moveTo(*point(ring[0]))
            for coordinate in ring[1:]:
                path.lineTo(*point(coordinate))
            path.close()
            canvas.drawPath(path, stroke=1, fill=0)
        canvas.restoreState()

    def draw_order(feature):
        geometry = feature.get("geometry") or {}
        aeroway = (feature.get("properties") or {}).get("aeroway")
        return 0 if geometry.get("type") == "Polygon" else 2 if aeroway == "runway" else 1

    labels = {}
    shaded = False
    for feature in sorted((overlay.get("featureCollection") or {}).get("features") or [], key=draw_order):
        prop = feature.get("properties") or {}
        geometry = feature.get("geometry") or {}
        polygon = geometry.get("type") == "Polygon"
        lines = [geometry.get("coordinates") or []] if geometry.get("type") == "LineString" else geometry.get("coordinates") or []
        mark = marks.get(prop.get("featureId") or feature.get("id"))
        planned = bool(planned_runway and str(planned_runway) in str(prop.get("ref") or "").split("/"))
        runway = prop.get("aeroway") == "runway"
        colour = RED if mark == "closure" else AMBER if mark else CYAN if planned else MUTED if runway else TAXIWAY
        rings_drawn = [ring for ring in lines if len(ring) >= 4] if polygon else []
        if rings_drawn:
            # An apron or stand area is pavement, drawn as a translucent area
            # with its outline; a marked one takes the mark's colour. A ring
            # with fewer than four vertices encloses nothing and is left out.
            path = canvas.beginPath()
            for ring in rings_drawn:
                path.moveTo(*point(ring[0]))
                for coordinate in ring[1:]:
                    path.lineTo(*point(coordinate))
                path.close()
            canvas.setStrokeColor(colour if mark else APRON)
            canvas.setLineWidth(3.2 if mark else 0.6)
            canvas.setFillColor(colour if mark else APRON)
            canvas.setFillAlpha(0.35 if mark else 0.3)
            canvas.drawPath(path, stroke=1, fill=1, fillMode=FILL_EVEN_ODD)
            canvas.setFillAlpha(1)
            shaded = True
        for line in lines:
            if len(line) < 2:
                continue
            if not polygon:
                # Runways 2.4 pt, marked pavement 3.2 pt (the width the state
                # gate reads back), taxiways 1.3 pt: visible on an iPad photo
                # of the page, still lighter than a runway.
                canvas.setStrokeColor(colour)
                canvas.setLineWidth(3.2 if mark else 2.4 if runway else 1.3)
                path = canvas.beginPath()
                path.moveTo(*point(line[0]))
                for coordinate in line[1:]:
                    path.lineTo(*point(coordinate))
                canvas.drawPath(path, stroke=1, fill=0)
            if prop.get("ref") and (prop.get("aeroway") == "runway" or mark):
                # OSM can split one runway into several ways. Label its
                # longest held segment once, with measured collision checks.
                length = sum(math.dist(point(a), point(b)) for a, b in zip(line, line[1:]))
                ref = str(prop["ref"])
                if length > labels.get(ref, (0,))[0]:
                    first, last = point(line[0]), point(line[-1])
                    labels[ref] = (length, ((first[0] + last[0]) / 2, (first[1] + last[1]) / 2), colour)
    for ref, (_, (lx, ly), colour) in sorted(labels.items()):
        label_width = stringWidth(ref, "Helvetica-Bold", 9)
        for ox, oy in ((0, 9), (0, 23), (35, 9), (-35, 9), (0, -17), (55, 23), (-55, 23)):
            px, py = lx + ox, ly + oy
            box = (px - label_width / 2 - 2, py - 3, px + label_width / 2 + 2, py + 10)
            if box[0] < x or box[2] > x + width or box[1] < y + 25 + floor or box[3] > y + height:
                continue
            if any(box[0] < b[2] and box[2] > b[0] and box[1] < b[3] and box[3] > b[1] for b in occupied):
                continue
            # A padded opaque plate prevents runway/taxiway strokes crossing
            # the glyphs. Labels retain leaders to their measured positions.
            canvas.setStrokeColor(colour)
            canvas.setLineWidth(.5)
            canvas.line(lx, ly, px, py + 3)
            canvas.setFillColor(BG)
            canvas.roundRect(box[0], box[1], box[2]-box[0], box[3]-box[1], 2, fill=1, stroke=0)
            canvas.setFillColor(colour)
            canvas.setFont("Helvetica-Bold", 9)
            canvas.drawCentredString(px, py, ref)
            occupied.append(box)
            break
        else:
            raise ValueError(f"Airport figure has no readable label position for {ref}")
    # The legend is a claim about the figure: it names the outline and the
    # shaded areas only when they were drawn (an overlay without a published
    # boundary or apron polygons has neither); the scale bar always is.
    legend = []
    if rings:
        legend.append("dashed: aerodrome boundary")
    if shaded:
        legend.append("shaded: apron / stand area")
    legend.append("bar: ground distance")
    canvas.setFont("Helvetica", 9)
    canvas.setFillColor(MUTED)
    if outline_gap:
        canvas.drawString(x, y + 26, outline_gap)
    canvas.drawString(x, y + 15, " · ".join(legend))
    canvas.drawString(x, y + 4, "OSM reference · cyan: planned · red: unavailable · amber: scheduled/partial")

def fitted_lines(values: list[str], width: float, body: float, budget: int,
                 pointer: str) -> list[str]:
    """Take whole source lines while they fit; never cut one in half."""
    kept: list[str] = []
    used = 0
    for value in values:
        needed = len(wrap(value, width - 28, size=body))
        if used + needed > budget:
            kept.append(pointer)
            break
        kept.append(value)
        used += needed
    return kept


def split_card(card: Card, columns: int = 2) -> list[Card]:
    """Share one card's paragraphs across columns; nothing is dropped.

    A long source-bound list reads better in two columns than in one tall
    narrow one, and it keeps the page inside the reference's six pages.
    """
    paragraphs = list(card.paragraphs)
    if len(paragraphs) < columns * 2:
        return [card]
    size = -(-len(paragraphs) // columns)
    parts = []
    for index in range(columns):
        chunk = paragraphs[index * size:(index + 1) * size]
        if not chunk:
            continue
        parts.append(replace(
            card, paragraphs=chunk,
            title=card.title if index == 0 else f"{card.title} (CONT)",
            tag=card.tag if index == 0 else None))
    return parts


def grid_rows(cards: dict, grid, gap: float) -> list[tuple[Any, list[Card]]]:
    """Build one candidate row layout; a ``key*2`` entry splits that card."""
    rows = []
    for row in grid:
        built: list[Card] = []
        for key, weight in row:
            name, _, columns = key.partition("*")
            card = cards[name](gap, weight)
            built.extend(split_card(card, int(columns)) if columns else [card])
        rows.append((None, built))
    return rows


SEVERITY_PILLS = {
    "critical": ("MAJOR", RED),
    "warning": ("MODERATE", AMBER),
    "unknown": ("REVIEW", VIOLET),
    "information": ("INFO", CYAN),
}


def deferred_gate_value(row: dict[str, Any]) -> str:
    """Name the declaration kind, or its gate, without repeating the title."""
    kinds = "/".join(row.get("item_types") or [])
    title = text(row.get("title"), "")
    if len(kinds) >= 3 and not title.upper().startswith(kinds.upper()):
        return kinds
    status = str(row.get("status") or "")
    return "CONFIRM" if "confirmation" in status else (kinds or "HELD")


def severity_pill(value: Any) -> tuple[str, Any]:
    return SEVERITY_PILLS.get(str(value or "information").lower(), ("INFO", CYAN))


def build_sections(flight, view, findings, references=None) -> dict[str, list[Page]]:
    """David's six reference pages; every published fact keeps an owner."""
    from .airport_pdf_analysis import airport_pdf_analysis, alternate_pdf_analysis
    from .combined_brief import _operational_coverage_receipt, _route_anchor_entries

    identity = view.get("flight_identity") or {}
    one = view.get("page_one") or {}
    fuel = view.get("fuel_summary") or {}
    fuel_rows = fuel.get("rows") or {}
    masses = fuel.get("masses_kg") or {}
    perf = view.get("performance_publication") or {}
    inputs = perf.get("inputs") or {}
    terrain = view.get("terrain") or {}
    vws = terrain.get("vws_review") or {}
    receipt = _operational_coverage_receipt(flight, view, findings, references)
    airport_analysis = airport_pdf_analysis(flight, view.get("airport_operational_panels") or [])
    alternate_analysis = alternate_pdf_analysis(flight, view.get("airport_operational_panels") or [])
    amount = lambda key: kg((fuel_rows.get(key) or {}).get("fuel_kg"))
    states = {r["key"]: r["state"] for r in receipt["rows"]}
    sections: dict[str, list[Page]] = {}
    route_map = build_publication_map(flight, view)

    vws_summary = f"{int(vws.get('event_count') or 0)} event(s) at the analysed {text(vws.get('threshold'))} threshold. Maximum {text(vws.get('maximum_display'))} at {text(vws.get('maximum_waypoint'))}, ACTM {text(vws.get('maximum_actm_display'))}."
    terrain_summary = f"{len(terrain.get('events') or [])} high-MSA event(s); controlled-profile status is in the closing review record."
    deferred = [row["text"] for row in view["deferred_pdf_analysis"]]

    # ---------------------------------------------------------------- page 1
    def station(role: str, accent, extra: list[tuple[str, list[str]]]) -> Card:
        station_view = view.get(role) or {}
        weather = station_view.get("weather") or {}
        analysed = next((a for a in airport_analysis if a["role"] == role), {"lines": []})
        pertinent = [line["text"] for line in analysed["lines"]]
        blocks = [("PLAN", [f"RWY {text(flight.get(f'{role}_runway'))} / "
                            f"{text(one.get('sid' if role == 'departure' else 'star'))}"])]
        blocks += extra
        # His page 1 prints the held record in its reference form - METAR
        # 11004KT 9999 FEW018, TAF 16008KT 9999 FEW015/SCT020 - not the OFP
        # record envelope (SA 201900 ... NOSIG=). One rule for both surfaces:
        # page_one_weather.py here, page1-weather.mjs on the dashboard,
        # pinned to each other by tests/fixtures/page1-weather-vectors.json.
        blocks.append(("METAR", [page_one_metar_field(weather.get("metar"), "WEATHER page")]))
        # His reference column is PLAN / SCHEDULE / METAR / TAF / PERTINENT at
        # departure and PLAN / EET / SCHED / METAR / TAF TEMPO / PERTINENT at
        # destination. The arrival field is the TAF's temporary group, so the
        # label and the value beneath it say the same thing.
        blocks.append(
            ("TAF TEMPO", [taf_tempo_field(weather.get("taf"))])
            if role == "destination"
            else ("TAF", [page_one_taf_field(weather.get("taf"), "WEATHER page")])
        )
        # The nine-page ARRIVAL SURFACE card counted the analysed consequences
        # for the arrival. The count stays published, and now also says where
        # the ones that do not fit this column are printed in full.
        counted = (f"{len(pertinent)} analysed surface/approach consequence(s). "
                   "Full analysis: AIRPORTS page.")
        kept = fitted_lines(pertinent, 180, BODY, 4, counted)
        if kept and kept[-1] != counted:
            kept.append(counted)
        blocks.append(("PERTINENT", kept
                       or ["No analysed constraint is held for the planned movement.",
                           counted]))
        return Card("DEPARTURE" if role == "departure" else "DESTINATION", [], accent,
                    tag="CFP P1", kind="station", width_weight=1.25,
                    payload=(text(station_view.get("icao")),
                             airport_short_name(station_view.get("icao")), blocks),
                    target="sec_airports")

    tiles = [
        Card("PERFORMANCE", [f"{text(inputs.get('runway_condition'))} RWY {text(inputs.get('runway'))}; "
                             f"EOSID {text(inputs.get('eosid'))}."],
             CYAN, "sec_performance", tag="CFP P1", kind="tile", payload=[
                 ("PTOW", kg(masses.get("ptow"))), ("RTOW", kg(perf.get("selected_rtow_kg"))),
                 ("MARGIN", kg(perf.get("margin_kg"))), ("PLWT", kg(masses.get("plwt"))),
                 ("FLAPS", text(inputs.get("flap_setting")))]),
        Card("FUEL", [f"Arithmetic {text(fuel.get('state'))}."],
             GREEN, "sec_performance", tag="CFP P1", kind="tile", payload=[
                 ("BLOCK", amount("fuel_in_tanks")), ("FPL REQ", amount("flt_plan_reqmt")),
                 ("EXCESS", amount("excess_fuel")), ("BURNOFF", amount("burnoff")),
                 ("TAXI", kg(fuel.get("taxi_fuel_kg")))]),
        Card("TECH STATUS", [f"{len(deferred)} consequence(s) on PERF / FUEL / TECH."],
             AMBER, "sec_performance", tag="CFP P1", kind="tile",
             payload=[(deferred_item_label(row.get("title")), deferred_gate_value(row))
                      for row in view.get("deferred_dispatch_gates") or []][:5]
             or [("DEFERRED", "None parsed")]),
        Card("WEATHER / HAZARDS", ["No data is a gap, not NIL."],
             VIOLET, "sec_hazard", tag="CFP P1", kind="tile", payload=[
                 ("SIGMET", "HELD" if (view.get("hazards") or {}).get("sigmet_cards") else "NO DATA"),
                 ("VA", "HELD" if ((view.get("vaa") or {}).get("cfp_advisories")) else "NO DATA"),
                 ("TC", "HELD" if cyclone_content(flight)["time_matched"] else "NO DATA"),
                 ("PLOTTED", str(len(route_map.get("publication_events") or []))),
                 ("VWS MAX", text(vws.get("maximum_display")))]),
        Card("ALTN / ROUTE", [f"{text(one.get('ground_distance_nm'))} NM filed."],
             RED, "sec_airports", tag="CFP P1", kind="tile", payload=[
                 ("PRIMARY", f"{text((one.get('alternates') or [{}])[0].get('airport'))}/{text((one.get('alternates') or [{}])[0].get('runway'))}"),
                 ("APPROACH", text((one.get("alternates") or [{}])[0].get("approach"))),
                 ("DIST", f"{text((one.get('alternates') or [{}])[0].get('distance_nm'))} NM"),
                 ("ALTN FUEL", amount("altn_fuel")), ("ALTN HOLD", amount("altn_hold"))]),
    ]
    gate_by_label = {str(row.get("label")): row for row in view.get("release_gates") or []}
    strip = []
    for heading, label in (("RELEASE", "PERFORMANCE"), ("BEFORE PUSH", "STATUS"),
                           ("ROUTE", "ROUTE"), ("ARRIVAL", "AIRPORTS"), ("WEATHER", "WEATHER")):
        gate = gate_by_label.get(label) or {}
        status = str(gate.get("status") or "NOT HELD")
        accent = {"CRITICAL": RED, "OPEN": AMBER, "WARNING": AMBER, "REVIEW": VIOLET}.get(status, GREEN)
        strip.append(Card(heading, [], accent, gate.get("target"), kind="strip",
                          payload=(status, [])))

    overview_grids = ((1.25, 2.05), (1.45, 1.65), (1.65, 1.25))

    def schedule_field() -> str:
        """His SCHEDULE: ``0050Z / 0850 LT`` - the UTC clock and the local one.

        The local clock is the analysis's own published value (one registry
        for both surfaces), else resolved here from the same registry; a
        station it does not hold prints "LT not held", never a guessed offset.
        """
        from .brief_theme import local_clock_label
        utc_clock = clock(identity.get("etd_hhmm"))
        if not re.fullmatch(r"\d{4}Z", utc_clock):
            return text(None)
        schedule = ((view.get("overview") or {}).get("departure") or {}).get("schedule") or {}
        local = (
            text(schedule.get("display_local"), "")
            or local_clock_label(flight.get("departure"), flight.get("scheduled_departure_utc"))
            or "LT not held"
        )
        return f"{utc_clock} / {local}"

    def overview_rows(body, leading, variant=0):
        station_weight, map_weight = overview_grids[variant]
        return [
            (None, [replace(station("departure", CYAN, [("SCHEDULE", [schedule_field()])]),
                            width_weight=station_weight),
                    Card("CFP ROUTE - PERTINENT DECISION GATES", [], CYAN, tag="SCHEMATIC",
                         kind="map", payload=route_map, width_weight=map_weight),
                    replace(station("destination", RED, [("EET / SCHED", [f"{text((view.get('metrics') or {}).get('eet'))} / {clock(identity.get('scheduled_eta_hhmm'))}"])]),
                            width_weight=station_weight)]),
            (None, tiles),
            ((44.0, 52.0), strip),
        ]
    sections["overview"] = plan_page_flexible(
        "OVERVIEW", "sec_overview", overview_rows, ribbon_index=0, aliases=("sec_route", "sec_summary"),
        variants=tuple(range(len(overview_grids))),
        assurance="CFP P1 PRIORITISED | SOURCE FACTS + LABELLED ANALYSIS | AI AUTHORITY: NONE")

    # ---------------------------------------------------------------- page 2
    decision = list(view.get("decision_findings") or [])
    finding_cards = []
    for item in decision:
        pill, accent = severity_pill(item.get("severity"))
        finding_cards.append(Card("", [], accent, item.get("target"), kind="finding", payload=(
            pill, str(item.get("title") or "Review item"),
            str(item.get("summary") or "Review required."),
            "SOURCE · " + str(item.get("source_reference") or "Uploaded OFP"))))
    if not finding_cards:
        finding_cards = [Card("NO RANKED FINDING", [
            "The analysis holds no ranked decision finding for this flight. Source coverage "
            "conditions remain on the ENROUTE / INTAM / ASSURANCE page."], CYAN)]
    anchors = _route_anchor_entries(flight, view)

    def analysis_rows(body, leading, variant=0):
        rows: list[tuple[Any, list[Card]]] = []
        for index in range(0, len(finding_cards), 2):
            rows.append((None, finding_cards[index:index + 2]))
        rows.append(((106.0, 132.0), [Card(
            "FLIGHT-PHASE DECISION TIMELINE", [], CYAN, kind="timeline", payload=anchors,
            tag=text(identity.get("timeline_basis"), "OFP ACTM"))]))
        return rows
    sections["analysis"] = plan_page_flexible(
        "DECISION ANALYSIS", "sec_analysis", analysis_rows, ribbon_index=1, aliases=("sec_time",),
        assurance="SEVERITY REVIEW | DIRECT SOURCE FACTS + EXPLICIT INFERENCES")

    # ---------------------------------------------------------------- page 3
    switch = lambda key: "ON" if inputs.get(key) is True else "OFF" if inputs.get(key) is False else "not held"
    rtow = [f"RWY {text(inputs.get('runway'))} · {text(inputs.get('runway_condition'))} · FLAPS {text(inputs.get('flap_setting'))}",
            f"PACKS {switch('packs_on')} · ANTI-ICE {switch('anti_ice_on')}",
            f"TEMP {text(inputs.get('temperature_c'))} C · QNH {text(inputs.get('qnh_hpa'))} · WIND {text(inputs.get('wind'))}",
            *[f"{r.get('label')} {kg(r.get('limit_kg'))}" for r in perf.get("candidate_limits") or []],
            f"Selected RTOW {kg(perf.get('selected_rtow_kg'))}",
            f"RTOW - PTOW: {kg(perf.get('margin_kg'))} · MLGW {kg(inputs.get('maximum_landing_weight_kg'))}",
            f"MAX FUEL AVAILABLE {kg(inputs.get('maximum_fuel_available_kg'))}"]
    fuel_lines = [f"{label} {amount(key)}" for key, label in (("burnoff", "BURNOFF"), ("stat_cont", "STAT CONT"), ("altn_fuel", "ALTN FUEL"), ("altn_hold", "ALTN HOLD"))]
    for key, label in (("dest_hold_top_up", "DEST HOLD TOP-UP"), ("edto_top_up", "EDTO TOP-UP")):
        if (fuel_rows.get(key) or {}).get("fuel_kg"):
            fuel_lines.append(f"{label} {amount(key)}")
    fuel_lines += [f"TAXI FUEL {kg(fuel.get('taxi_fuel_kg'))}", f"FLT PLAN REQMT {amount('flt_plan_reqmt')}",
                   f"FUEL IN TANKS {amount('fuel_in_tanks')}", f"Arithmetic: {text(fuel.get('state'))}"]
    derived = fuel.get("derived_fuel_kg") or {}
    fuel_lines += [f"Tanks - taxi: {kg(derived.get('takeoff'))}",
                   f"Less burnoff: {kg(derived.get('landing'))} at destination."]
    if fuel.get("tanker_return_sector_req_kg") is not None:
        fuel_lines.append(f"Return-sector requirement: {kg(fuel['tanker_return_sector_req_kg'])}.")
    mass_checks = {c.get('name'): c.get('passed') for c in fuel.get('checks') or []}
    mass_equations = [f"PZFW {kg(masses.get('pzfw'))} + tanks {amount('fuel_in_tanks')} - taxi {kg(fuel.get('taxi_fuel_kg'))}",
                      f"PTOW {kg(masses.get('ptow'))}",
                      f"PLWT {kg(masses.get('plwt'))} · burnoff {amount('burnoff')}",
                      "Mass identities: " + ("verified" if all(mass_checks.get(k) is True for k in ('mass_landing_identity', 'mass_takeoff_identity')) else "not reconciled")]
    sensitivity = perf.get("planning_sensitivity") or {}
    margins = [f"ZFW +1,000 kg: ADD {kg(sensitivity.get('zfw_change_burn_add_kg_per_1000'))}",
               f"ZFW -1,000 kg: LESS {kg(sensitivity.get('zfw_change_burn_less_kg_per_1000'))}"]
    for row in fuel.get("excess_breakdown") or []:
        if row.get("fuel_kg") or str(row.get("label")).upper() == "MEL":
            margins.append(f"{text(row.get('label'))}: {kg(row.get('fuel_kg'))}")
    lower = sensitivity.get("lower_cruise_sensitivity") or {}
    if lower:
        margins.append(f"Cruise -{text(lower.get('offset_ft'))} ft: ADD {kg(lower.get('burn_add_kg'))}; TIME {text(lower.get('time_display'))}.")

    def performance_rows(body, leading, variant=0):
        return [
            (None, [Card("TAKE-OFF / LANDING PERFORMANCE", rtow, CYAN, tag="CFP P1", width_weight=1.0),
                    Card("FUEL PLAN / MASS CHAIN", fuel_lines, GREEN, tag="CFP P1", width_weight=1.0),
                    Card("TECHNICAL STATUS", deferred or ["No supported deferred declaration was parsed from OFP page 1."],
                         AMBER, tag="CFP P1", width_weight=1.35, paragraph_gap=2.0)]),
            (None, [Card("RECONCILIATION / SOURCE CONTROL", mass_equations + margins, CYAN,
                         tag="CALCULATED", width_weight=1.6),
                    Card("CONTROL", [f"EOSID: {text(inputs.get('eosid'))}",
                                     "Destination fuel arithmetic is not discretionary holding fuel. Protect alternate fuel and reserves under controlled policy."],
                         AMBER, width_weight=1.0, paragraph_gap=2.0)]),
        ]
    sections["performance"] = plan_page_flexible(
        "PERFORMANCE, FUEL AND TECHNICAL STATUS", "sec_performance", performance_rows,
        ribbon_index=2, aliases=("sec_mel_cdl", "sec_status"), assurance="ARITHMETIC RECONCILED | SOURCE LINES CARRY THEIR OWN EXCEPTIONS")

    # ---------------------------------------------------------------- page 4
    figures, airport_cards = [], []
    # The app's airport index says whether each airport's OFP station package
    # was held; a figure with no overlay names that as its missing source.
    surface_index = {str(entry.get("icao") or "").strip().upper(): entry
                     for entry in (view.get("airport_surface_index") or []) if isinstance(entry, dict)}
    for analysed in airport_analysis:
        role = analysed["role"]
        overlay = next((o for o in view.get("surface_overlays") or []
                        if o.get("icao") == analysed["icao"] and o.get("role") == role), None)
        overlay = analysed_airport_overlay(overlay, analysed)
        figures.append(Card(f"{text(analysed['icao'])} {role.upper()} SURFACE", [],
                            CYAN if role == "departure" else RED, tag="OSM", kind="figure",
                            payload=(overlay, flight.get(f"{role}_runway"),
                                     surface_index.get(str(analysed.get("icao") or "").strip().upper()))))
        airport_cards.append(Card(
            f"{text(analysed['icao'])} {role.upper()} · PLANNED RWY {text(analysed['planned_runway'])}",
            [r["text"] for r in analysed["lines"]]
            or ["No supported closure consequence was established for the planned movement. No gate, exit or taxi route is inferred."],
            CYAN if role == "departure" else RED, f"sec_{role}", paragraph_gap=2.0))
    alternate_lines = []
    for row in view.get("alternate_assessment_rows") or []:
        analysis = next((p for p in alternate_analysis if p["icao"] == row.get("airport")), {"lines": []})
        alternate_lines.append(f"{text(row.get('airport'))}/{text(row.get('runway'))} {str(row.get('role') or 'alternate').upper()} · {text(row.get('approach'))} · MIN {text(row.get('minima'))} · {text(row.get('distance_nm'))} NM / {text(row.get('time_minutes'))} min / {kg(row.get('fuel_kg'))}.")
        alternate_lines.extend(r["text"] for r in analysis["lines"])

    # His reference page 4 is a DEPARTURE AIRPORT column beside a DESTINATION
    # AIRPORT column, the alternate matrix under both. Each column here is the
    # airport's figure over its consequences, and the column row takes every
    # point of height the measured alternates row leaves - so the figure is
    # sized by the page, not by a fixed band (9 Sep 2026: a 145 x 105 pt VHHH
    # thumbnail in a 375 pt card, "This is also rubbish generated").
    columns = [Card("", kind="stack", payload=[figure, card])
               for figure, card in zip(figures, airport_cards)]

    def airport_rows(body, leading, variant=0):
        airport_row = (
            [(TAKES_REMAINING_HEIGHT, columns)] if columns else [
                ((104.0, 158.0), [Card("AIRPORT SURFACE", ["No airport figure is held."], CYAN)]),
                (None, [Card("AIRPORTS", ["No airport analysis is held."], CYAN)]),
            ])
        return [
            *airport_row,
            (None, [Card("ALTERNATE PLANS / FLIGHT-WINDOW CONSEQUENCES",
                         alternate_lines or ["No alternate rows are held."], AMBER,
                         tag="CFP P2", paragraph_gap=2.0)]),
        ]
    sections["airports"] = plan_page_flexible(
        "AIRPORTS / ALTERNATES", "sec_airports", airport_rows, ribbon_index=3, aliases=("sec_departure", "sec_destination", "sec_alternates"),
        assurance="AIRPORT / ALTERNATE APPLICABILITY | FLIGHT-TIME CONSEQUENCES ONLY")

    # ---------------------------------------------------------------- page 5
    terminal = []
    for role in ("departure", "destination"):
        station_view = view.get(role) or {}
        terminal.append(f"{text(station_view.get('icao'))} METAR: {text((station_view.get('weather') or {}).get('metar'))}")
        forecast = ((view.get("overview") or {}).get(role) or {}).get("forecast_at_reference") or {}
        conditions = forecast.get("applicable_conditions")
        if conditions:
            terminal.append(f"{text(station_view.get('icao'))} forecast {text(forecast.get('utc_window'))}: {conditions}")
        source = forecast.get("forecast_source") or {}
        if source:
            # A forecast source prints its issue/validity; an observation
            # basis prints its observation time, never an invented validity.
            terminal.append(forecast_source_line(source))
        elif conditions:
            terminal.append("Forecast source, issue and validity times are not held.")
    tc_lines = cyclone_content(flight)["lines"]
    hazard_lines = ["Plotted positions are on the OVERVIEW route map where they fall inside its frame."]
    hazard_lines += [value for value, _ in publication_key_entries(route_map)]
    edto = view.get("edto") or {}
    route_clocks = [f"S{r.get('number')}: {text(r.get('entry_name'))} {text(r.get('entry'))} / {text(r.get('exit_name'))} {text(r.get('exit'))}; ETP ACTM {', '.join(r.get('etps') or []) or 'not held'}." for r in edto.get("sectors") or []]
    for r in flight.get("flight_planning_etps") or []:
        route_clocks.append(f"{text(r.get('label'))} {text(r.get('from'))}/{text(r.get('to'))}: {text(r.get('distance_nm'))} NM; EET {text(r.get('eet_token'))}.")

    weather_cards = {
        "terminal": lambda gap, weight: Card("TERMINAL WEATHER", terminal, CYAN, tag="CFP WX",
                                             width_weight=weight, paragraph_gap=gap),
        "sigmet": lambda gap, weight: Card("SIGMET", sigmet_lines(flight, view), AMBER,
                                           width_weight=weight, paragraph_gap=gap),
        "cyclone": lambda gap, weight: Card("TROPICAL CYCLONE", tc_lines
                                            or ["No governed route-specific cyclone consequence was established from the held sources."],
                                            AMBER, width_weight=weight, paragraph_gap=gap),
        "ash": lambda gap, weight: Card("VOLCANIC ASH", volcanic_ash_lines(flight, view), AMBER,
                                        width_weight=weight, paragraph_gap=gap),
        "key": lambda gap, weight: Card("FLIGHT HAZARD KEY", hazard_lines, VIOLET,
                                        width_weight=weight, paragraph_gap=gap),
        "clocks": lambda gap, weight: Card("ROUTE / EDTO CLOCKS", route_clocks
                                           or [text(identity.get("rules")), "No EDTO or additional planning ETP is held."],
                                           CYAN, width_weight=weight, paragraph_gap=gap),
        "edto": lambda gap, weight: Card("EDTO AIRPORT WINDOWS", edto_window_lines(flight, view),
                                         AMBER, width_weight=weight, paragraph_gap=gap),
    }
    # A long-haul package can hold a dozen screened hazards: give the loaded
    # card the full row before the body steps down. Nothing is dropped.
    weather_grids = (
        ((("terminal", 1.25), ("sigmet", 1.0)), (("cyclone", 1.0), ("ash", 1.0)),
         (("key", 1.4), ("clocks", 1.0), ("edto", 1.0)), 2.0),
        ((("terminal", 1.0), ("sigmet", 1.4)), (("key", 1.0),),
         (("cyclone", 1.0), ("ash", 1.4), ("clocks", 0.8), ("edto", 0.8)), 2.0),
        ((("terminal", 1.0), ("sigmet", 1.0), ("cyclone", 1.0)), (("key", 1.0),),
         (("ash", 1.4), ("clocks", 1.0), ("edto", 1.0)), 2.0),
        ((("terminal", 1.0),), (("sigmet", 1.0), ("key", 1.6)),
         (("cyclone", 1.0), ("ash", 1.0), ("clocks", 1.0), ("edto", 1.0)), 2.0),
        ((("terminal", 1.0), ("sigmet", 1.0)), (("key*2", 1.0),),
         (("cyclone", 1.0), ("ash", 1.0), ("clocks", 1.0), ("edto", 1.0)), 2.0),
        ((("terminal*2", 1.0),), (("sigmet", 1.0), ("key", 1.0)),
         (("cyclone", 1.0), ("ash", 1.0), ("clocks", 1.0), ("edto", 1.0)), 2.0),
        ((("terminal", 1.0), ("sigmet", 1.0)), (("key*2", 1.0),),
         (("edto", 1.0), ("ash", 1.0)), (("cyclone", 1.0), ("clocks", 1.0)), 2.0),
        ((("terminal", 1.0), ("sigmet", 1.4)), (("key", 1.0),),
         (("cyclone", 1.0), ("ash", 1.4), ("clocks", 0.8), ("edto", 0.8)), 0.0),
        ((("terminal", 1.0), ("sigmet", 1.0)), (("key*2", 1.0),),
         (("edto", 1.0), ("ash", 1.0)), (("cyclone", 1.0), ("clocks", 1.0)), 0.0),
    )

    def weather_rows(body, leading, variant=0):
        *grid, gap = weather_grids[variant]
        return grid_rows(weather_cards, grid, gap)
    sections["weather"] = plan_page_flexible(
        "WEATHER / ROUTE HAZARDS", "sec_hazard", weather_rows, ribbon_index=4,
        aliases=("sec_hazards", "sec_weather"), variants=tuple(range(len(weather_grids))),
        assurance="WEATHER SOURCE REVIEW | COVERAGE GAPS ARE NOT NIL | LIVE PRODUCTS CONTROL")

    # ---------------------------------------------------------------- page 6
    terrain_lines = []
    for event in terrain.get("events") or []:
        first, last, maximum, drop = (event.get(k) or {} for k in ("first_high", "last_high", "maximum", "drop"))
        msa = maximum.get("msa_hundreds_ft")
        span = (text(first.get('name')) if first.get('name') == last.get('name')
                else f"{text(first.get('name'))}-{text(last.get('name'))}")
        terrain_lines.append(f"{span}: max {int(msa) * 100:,} ft at {text(maximum.get('name'))}; next threshold drop {text(drop.get('name'))}." if msa is not None else "A terrain event is held without a resolved maximum.")
    vws_events = [f"{text(f.get('title'))}: {text(f.get('summary'))}" for f in findings if f.get("engine") == "vws"]
    # The nine-page briefing published the threshold summary on page 1 and the
    # events on the terrain page. ``vws_events or [vws_summary]`` published one
    # or the other; both are source-bound, so both are published here.
    enroute_lines = [vws_summary, *vws_events]
    enroute_lines += terrain_lines or [text(terrain.get("summary"))]
    enroute_lines.append(terrain_summary)
    interpretation = [
        "OFP samples describe the printed waypoint values; they do not establish continuous conditions "
        "between every waypoint. OFP VWS is not a CAT measurement. Missing samples do not demonstrate "
        "continuous low VWS.",
        f"OFP VWS: {text(vws.get('maximum_display'))} maximum. "
        f"WAFS/SIGWX evidence: {'held' if states['wafs_sigwx'] in {'HELD', 'FOUND'} else 'not established'}. "
        f"AIREP/PIREP retrieval: {'held' if states['airep_pirep'] in {'HELD', 'FOUND'} else 'not established'}. "
        "Use the source-held event positions to distinguish turbulence sampling from terrain exposure; "
        "neither establishes a controlled escape procedure.",
    ]
    checks = {row["key"]: row for row in receipt["rows"]}
    completed = [f"{label}: {success if checks[key]['state'] == 'HELD' else 'incomplete'}."
                 for key, label, success in (("ofp_parse", "Flight / aircraft identity", "recorded"),
                                             ("flight_timing", "Scheduled departure / arrival UTC", "recorded"),
                                             ("fuel_performance", "Fuel arithmetic / performance", "verified"))]
    edto_result = {"NOT APPLICABLE": "not applicable", "HELD": "assessment recorded"}.get(checks["edto"]["state"], "assessment incomplete")
    completed.append(f"EDTO: {edto_result}.")
    from .governed_deferred_extract import governed_deferred_extracts
    extracts = governed_deferred_extracts(view.get("deferred_source_items"), references)
    conditions = release_condition_groups(flight, view, receipt, airport_analysis, alternate_analysis, extracts)
    source_lines = [f"OFP {text(identity.get('ofp'))} · {text(view.get('flight_number'))} · {text(view.get('flight_date'))}",
                    f"Generated {text(view.get('generated_at_display'))}."]
    unavailable = [text(row.get("source")) for row in view.get("source_assurance") or []
                   if str(row.get("status") or "").upper() != "HELD"]
    source_lines.append("SOURCE ASSURANCE: "
                        + (", ".join(unavailable) + " not held." if unavailable
                           else "every listed source record is held."))
    source_lines.append("Source checks and full NOTAMs: app / Show full NOTAM.")
    notes = [str(n.get("note_text")) for n in flight.get("personal_notes") or [] if (n.get("include_level1") or n.get("include_level2")) and n.get("note_text")]
    if notes:
        conditions["technical"].append("PILOT NOTES: " + " / ".join(notes))
    has_conditions = any(conditions.values())
    # The card is titled PUBLICATION STATE; the sentence must not repeat the
    # label. With no numbered condition anywhere, this line carries the 1.
    publication_state = ("Conditional briefing; the unresolved assessments above prevent an "
                         "automated release conclusion.")
    if not has_conditions:
        publication_state = ("1. No unresolved automated source condition; crew operational "
                             "release remains separate.")
    # The nine-page RELEASE CONDITIONS card carried this caveat on page 1. Page
    # 1 is now the reference overview, so the caveat moves to the page that
    # owns the release record; it is a safety statement, not chrome.
    release_state = [publication_state,
                     "Current weather, airport surface state and operative aircraft "
                     "limitations must be confirmed before use."]

    # Enroute review, the airport/weather conditions and the closing record all
    # share one page. Whichever block a flight has loaded gets the wide column
    # first; type size steps down only after that, and no condition is dropped.
    closing_cards = {
        "enroute": lambda gap, weight: Card("OFP VWS, CAT AND TERRAIN", enroute_lines + interpretation,
                                            AMBER, "sec_terrain", width_weight=weight, paragraph_gap=gap),
        "review": lambda gap, weight: Card("SOURCE / CALCULATION REVIEW", completed, CYAN,
                                           width_weight=weight, paragraph_gap=gap),
        "airports": lambda gap, weight: Card("AIRPORT ASSESSMENTS", conditions["operations"]
                                             or ["No unresolved airport assessment is recorded."],
                                             AMBER, width_weight=weight, paragraph_gap=gap),
        "weather": lambda gap, weight: Card("WEATHER COVERAGE", conditions["weather"]
                                            or ["No unresolved weather-source condition is recorded."],
                                            AMBER, width_weight=weight, paragraph_gap=gap),
        "control": lambda gap, weight: Card("SOURCE CONTROL", source_lines, CYAN,
                                            width_weight=weight, paragraph_gap=gap),
        "remaining": lambda gap, weight: Card("REMAINING RELEASE INPUTS", conditions["technical"]
                                              or ["No unresolved aircraft/route source condition is recorded."],
                                              AMBER, width_weight=weight, paragraph_gap=gap),
        "state": lambda gap, weight: Card("PUBLICATION STATE", release_state, CYAN,
                                          width_weight=weight, paragraph_gap=gap),
    }
    closing_grids = (
        ((("enroute", 1.9), ("review", 1.0)), (("airports", 1.9), ("weather", 1.0)),
         (("control", 1.2), ("remaining", 1.0), ("state", 0.9)), 2.0),
        ((("enroute", 1.9), ("review", 1.0)), (("airports", 1.0), ("weather", 1.0), ("control", 1.0)),
         (("remaining", 2.2), ("state", 1.0)), 2.0),
        ((("enroute", 1.0), ("review", 1.0)), (("airports", 2.6), ("weather", 1.0)),
         (("control", 1.0), ("remaining", 1.0), ("state", 0.8)), 2.0),
        ((("enroute", 2.6), ("review", 1.0)), (("airports", 1.0), ("weather", 1.6)),
         (("control", 1.0), ("remaining", 1.0), ("state", 0.8)), 2.0),
        ((("enroute", 1.9), ("review", 1.0)), (("airports", 1.0), ("weather", 1.0), ("state", 0.8)),
         (("remaining", 1.6), ("control", 1.0)), 2.0),
        ((("enroute", 1.9), ("review", 1.0)), (("airports", 1.0), ("weather", 1.0), ("control", 1.0)),
         (("remaining", 2.2), ("state", 1.0)), 0.0),
    )

    def assurance_rows(body, leading, variant=0):
        *grid, gap = closing_grids[variant]
        return grid_rows(closing_cards, grid, gap)
    sections["assurance"] = plan_page_flexible(
        "ENROUTE / INTAM / ASSURANCE", "sec_coverage", assurance_rows, ribbon_index=5,
        aliases=("sec_enroute", "sec_terrain", "sec_intam"),
        variants=tuple(range(len(closing_grids))),
        assurance="TWO-PASS REVIEW TARGET | SOURCE TRACEABILITY | COMMAND AUTHORITY UNCHANGED")
    return sections


def render_analysed_briefing(flight, findings, warnings, path, *, weather_charts=None, company_briefing_references=None) -> None:
    from pathlib import Path
    from reportlab.pdfgen import canvas as pdf_canvas
    from .briefing import build_briefing_view
    from .airport_pdf_analysis import airport_pdf_analysis, alternate_pdf_analysis
    from .concise_pdf_gate import check_concise_pdf, PUBLICATION_FORMAT
    from .profile_chart_gate import validate_depressurisation_profile_charts, DepressurisationProfileChartPublicationError

    profile_violations = validate_depressurisation_profile_charts(flight, findings, 2)
    if profile_violations:
        raise DepressurisationProfileChartPublicationError(profile_violations)
    view = build_briefing_view(flight, findings, warnings, timing_view=flight.get("timing_view"), weather_charts=weather_charts)
    sections = build_sections(flight, view, findings, company_briefing_references)
    order = ("overview", "analysis", "performance", "airports", "weather", "assurance")
    pages = [page for key in order for page in sections[key]]
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    canvas = pdf_canvas.Canvas(str(target), pagesize=SIZE)
    canvas.setTitle(f"Flight Briefing {text(view.get('flight_number'))} {text(view.get('flight_date'))}")
    canvas.setSubject(PUBLICATION_FORMAT)
    for number, page in enumerate(pages, 1):
        draw_page(canvas, flight, view, page, number, len(pages))
        canvas.showPage()
    canvas.save()
    closing_lines = [" ".join(line for _, items in box.rows for line, *_ in items)
                     for page in sections["assurance"] for box in page.boxes]
    result = check_concise_pdf(target, flight=flight, view=view, airport_analysis=airport_pdf_analysis(flight, view.get("airport_operational_panels") or []), alternate_analysis=alternate_pdf_analysis(flight, view.get("airport_operational_panels") or []), closing_lines=closing_lines)
    if not result["valid"]:
        target.unlink(missing_ok=True)
        raise ValueError("Concise briefing publication failed: " + "; ".join(v["message"] for v in result["violations"]))

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
# Every string is measured and drawn in its one printable form (pdf_printable: a character outside the faces'
# repertoire prints as [U+XXXX], never as a notdef glyph read back as a look-alike letter).
from .pdf_printable import PrintableCanvas, hard_break, printable, string_width as stringWidth

from .analysed_briefing_content import (cyclone_content, deferred_item_label,
                                        excess_fuel_chain_label,
                                        excess_fuel_tile_label,
                                        release_condition_groups,
                                        tanker_only_excess)
from .analysed_briefing_map import (build_publication_map, draw_publication_map,
                                    publication_key_entries)
from .constants import format_actm
from .vws_maxima import review_maximum_entries, vws_maximum_listing
from .source_status import source_status_met, source_status_words
from .fuel_rows import contingency_label
from .page_one_weather import page_one_taf_field_continued, forecast_source_line, page_one_metar_field, page_one_taf_field, weather_page_taf_field
from .enroute_contact import (compose_enroute_contact, crossing_sequence_limited, early_call_sentence, has_printed_values,
                              is_call_line, named_early_call, primary_procedure_line, printed_values, untimed_call_pointer)
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


FUEL_STATE_LABELS = {"verified": "verified", "review_required": "not verified", "unverified": "not verified"}


def fuel_state_label(state: Any) -> str:
    """The page-1 fuel arithmetic state in words. The parser publishes
    `verified` (every row reconciles) or `review_required` (a discrepancy);
    24 Sep 2026's production QA of release 414 found the code printed raw
    ("Arithmetic review_required.") - a reminder in R2's sense. The state
    stays what it is; the PDF says it the way the dashboard does ("did not
    verify against its own arithmetic")."""
    code = str(state or "").strip().lower()
    if not code:
        return "not held"
    return FUEL_STATE_LABELS.get(code, code.replace("_", " ").replace("-", " "))


def vws_threshold_sentence(vws: dict[str, Any]) -> str:
    """Page 6's VWS threshold sentence. Every waypoint at the maximum is named (item #9), in route order, the
    first ``VWS_MAXIMUM_PRINT_LIMIT`` printed and the rest counted; a single maximum prints as it always has."""
    entries = review_maximum_entries(vws)
    head = (f"{int(vws.get('event_count') or 0)} event(s) at the analysed {text(vws.get('threshold'))} threshold. "
            f"Maximum {text(vws.get('maximum_display'))} at ")
    if len(entries) <= 1:
        return (head + f"{text(vws.get('maximum_waypoint'))}, ACTM {text(vws.get('maximum_actm_display'))}.")
    listing = vws_maximum_listing(
        entries, lambda entry: f"{text(entry.get('waypoint'))}, ACTM {text(entry.get('actm_display'))}",
        text(vws.get("maximum_display")), separator="; ")
    return head + f"{len(entries)} waypoints: {listing}."


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


def signed_kg(value: Any) -> str:
    """A page-1 tile mass that carries its own sign, as his reference does.

    David's page-1 tiles print the margin and a tanker carry signed -
    ``MARGIN +11,376 KG`` and ``TANKER +18,847 KG`` in his SQ910_21AUG2026
    reference, ``RTOW - PTOW +8,581 KG`` in SQ481 REV5, ``Margin +3,299 kg`` in
    SQ38 - and so does our own dashboard (``web/src/lib/overview-cards.ts``
    ``signedKg``). Only the six-page download printed them bare. The parity
    oracle normalises ``+`` away, so no gate saw the difference; C2 round 3
    closes it, and the app's ``checkPageOneTileValueFormat`` reads the raw
    page-1 layout text so the release gate can now see it.

    Note what is NOT signed: his page-3 fuel chain states ``TANKER EXCESS
    18,847 KG``, so the chain row stays bare. The sign is a tile convention.
    """
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return f"{'+' if value >= 0 else '-'}{abs(value):,.0f} kg"
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
    """Wrap without ellipsis, including unbroken source tokens. The lines are the value's printable form (a
    character outside the faces' repertoire is its [U+XXXX] escape); a token wider than the line is cut where it cuts
    neither an escape nor a run of letters or digits (pdf_printable.hard_break)."""
    lines: list[str] = []
    for paragraph in printable(value).splitlines() or [""]:
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
                end = hard_break(word, end)
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


@dataclass(frozen=True)
class LinkLine:
    """A card line that is also an external link (the durable governed-source
    landing): drawn as visible text with a URI annotation over every wrapped
    line, so the link is where the words are."""

    text: str
    uri: str


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
        gap = card.paragraph_gap if index else 0.0
        if isinstance(paragraph, LinkLine):
            for line_index, line in enumerate(wrap(paragraph.text, inner, font="Helvetica-Bold", size=body)):
                rows.append(((gap if line_index == 0 else 0.0),
                             [(line, "Helvetica-Bold", body, CYAN, "link", paragraph.uri)]))
            continue
        para(paragraph, colour=WHITE, gap=gap)
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
    if card.kind == "map" and card.title and len(title_layout(card, width)[1]) > 1:
        # David's page-1 header row is DEPARTURE / the centre panel's title /
        # DESTINATION, each one span (reference_conformance OVERVIEW_ROUTE_PANEL).
        # A grid that narrows the map until "CFP ROUTE - PERTINENT DECISION
        # GATES" wraps breaks that row, so it is refused at plan time and
        # plan_page_flexible moves to the next grid, size or deferral step.
        raise ValueError("Route panel title exceeds its column width; page 1 keeps the reference header row")
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


def balanced_row_widths(cards: list[Card], full_width: float, body: float,
                        leading: float) -> list[float]:
    """Give spare width to the taller of two text cards, measuring both.

    Fixed grid weights can refuse a page while the adjacent column has room.
    Search around the height crossover without changing paragraphs, fonts or
    padding. Title wrapping/font steps make height slightly non-monotonic, so
    retain the best *measured* candidate, including the original geometry.
    This is a bounded improvement, not a claim of a globally optimal packing.
    Figures and other row structures keep their declared geometry.
    """
    widths = row_widths(cards, full_width)
    if len(cards) != 2 or any(card.kind != "text" for card in cards):
        return widths
    usable = full_width - GAP
    minima = [max(56.0, 20 + CARD_TITLE +
                  (stringWidth(card.tag, "Helvetica-Bold", LABEL) + 12 if card.tag else 0))
              for card in cards]
    low, high = minima[0], usable - minima[1]
    if low >= high:
        return widths
    candidates = []

    def measure(left):
        heights = [card_height(card, width, body, leading)
                   for card, width in zip(cards, (left, usable - left))]
        candidates.append((max(heights), sum(heights), abs(left - widths[0]), left))
        return heights

    measure(widths[0])
    while high - low > 0.01:
        middle = (low + high) / 2
        left_height, right_height = measure(middle)
        if left_height > right_height:
            low = middle
        else:
            high = middle
    left = min(candidates)[-1]
    return [left, usable - left]


# The page-6 FIR / COMMUNICATION card quotes each row's conditions; its deferral
# ladder may cut them (operational section builder, FIR_STEPS).
_VALIDITY_CLAUSE = re.compile(r"validity .+: (?:covers this crossing|outside this crossing|not evaluable) \(at [^)]*\)")


# VOLCANIC-CHECK-436: the checklist rows in plain words (R2: codes print as
# words), in the receipt's own order, grouped by what the check found.
CHECKLIST_WORDS = {
    "ofp_parse": "OFP parse", "flight_timing": "flight timing", "mel_cdl": "MEL/CDL",
    "fuel_performance": "fuel/performance", "airports_alternates": "airports/alternates", "edto": "EDTO",
    "airport_notam": "airport NOTAMs", "airport_intelligence": "Airport Notes", "enroute_notam": "FIR NOTAMs",
    "atc_fir_calls": "early ATC/FIR calls", "metar_taf": "METAR/TAF", "sigmet": "SIGMET",
    "vaa_vaac": "volcanic ash", "tropical_cyclone": "tropical cyclone", "vws": "VWS",
    "depressurisation_profile": "depressurisation profile", "wafs_sigwx": "WAFS/SIGWX",
    "airep_pirep": "AIREP/PIREP", "governed_references": "manual references",
}
CHECKLIST_GROUPS = (
    ("CHECKED", "checked", frozenset({"FOUND", "HELD", "CHECKED · NO MATCH", "CHECKED · NO TRIGGER", "NOT APPLICABLE"})),
    ("UNRESOLVED", "unresolved", frozenset({"UNRESOLVED"})),
    ("SOURCE UNAVAILABLE", "source unavailable", frozenset({"UNAVAILABLE"})),
    ("NOT QUERIED", "not queried", frozenset({"NOT QUERIED"})),
)


CHECKLIST_MODES = ("whole", "open", "counts")


def checklist_lines(rows: list[dict[str, Any]], mode: str = "whole") -> list[str]:
    """Every checklist row, grouped by result; a state outside the vocabulary is never folded into CHECKED.

    ``mode`` is the page's own capacity step, taken before any FIR / COMMUNICATION row is deferred: "whole" names every
    item under its result; "open" prints the counts and names every item that is NOT complete; "counts" prints the
    counts only. Every item is always named, with its detail, on the dashboard, and the unresolved ones are numbered in
    this page's conditions."""
    grouped: dict[str, list[str]] = {title: [] for title, _, _ in CHECKLIST_GROUPS}
    for row in rows:
        title = next((title for title, _, states in CHECKLIST_GROUPS if row.get("state") in states), "UNRESOLVED")
        grouped[title].append(CHECKLIST_WORDS.get(str(row.get("key")), text(row.get("label")).lower()))
    counts = " · ".join(f"{len(grouped[title])} {word}" for title, word, _ in CHECKLIST_GROUPS if grouped[title])
    if mode == "whole":
        return [f"PD CHECKS ({len(rows)}): {counts}.",
                *(f"{title}: {', '.join(grouped[title])}." for title, _, _ in CHECKLIST_GROUPS if grouped[title])]
    if mode == "counts":
        return [f"PD CHECKS ({len(rows)}): {counts}; each item is named on the dashboard."]
    open_items = "; ".join(f"{', '.join(grouped[title])} ({word})" for title, word, _ in CHECKLIST_GROUPS[1:] if grouped[title])
    return [f"PD CHECKS ({len(rows)}): {counts}; the checked items are named on the dashboard.",
            *([f"Open: {open_items}."] if open_items else [])]


def source_assurance_line(entries: list[dict[str, Any]]) -> str:
    """The page-6 source line. It used to name only the OFP's sources, so "every listed source record is held" printed
    while the live VA SIGMET feed and every responsible VAAC were unreached; each source is listed with its own state.

    ITEM2-VOLCANIC: each status prints in its own words from the one vocabulary (source_status.py). A reached feed whose
    answer was not current printed "not reached", and any status outside a four-word table printed "not held"."""
    grouped: dict[str, list[str]] = {}
    for row in entries:
        if source_status_met(row.get("status")):
            continue
        grouped.setdefault(source_status_words(row.get("status")), []).append(text(row.get("source")))
    if not grouped:
        return "SOURCE ASSURANCE: every listed source is held or reached."
    return "SOURCE ASSURANCE: " + "; ".join(f"{', '.join(names)} {word}" for word, names in grouped.items()) + "."


def compact_conditions_summary(summary: Any, limit: int | None = 72) -> str:
    """A row's conditions summary ("clause · clause · state") at one step of the page-6 ladder.

    Each quoted source clause is cut to a whole-word prefix of `limit` characters; the dashboard row carries every
    clause in full. The validity clause is never cut (release-432 QA, O2): its window, whether it covers the crossing
    and the timing basis it was evaluated at (scheduled departure or ATOT + ACTM) are the row's timing, not a quote.
    At limit 0 - the ladder's last resort - the other clauses are counted, not printed; the validity clause, an
    ATC-provision label and the state always print. `limit` None keeps every clause whole.
    """
    parts = str(summary or "").split(" · ")
    if limit is None:
        return " · ".join(parts)
    if limit == 0:
        *clauses, state = parts
        kept = [part for part in clauses if part in ("ATC provision", "Other actor duty", "Other actor permission", "Other actor capability unresolved", "Capability unresolved", "Actor unresolved", "ATC duty", "ATC permission", "ATC restriction", "ATC service availability", "No ATC duty", "Communications permission", "Communications availability", "No call requirement", "Communication prohibition") or _VALIDITY_CLAUSE.fullmatch(part)]
        counted = len(clauses) - len(kept)
        return " · ".join(kept + ([f"+{counted} further condition(s) on the dashboard"] if counted else []) + [state])
    compacted = []
    for part in parts:
        if len(part) > limit and not _VALIDITY_CLAUSE.fullmatch(part):
            cut = part[:limit - 1]
            space = cut.rfind(" ")
            part = (cut[:space] if space > limit // 2 - 6 else cut).rstrip(" ,;:") + "…"
        compacted.append(part)
    return " · ".join(compacted)


def _untimed_status_key(line: dict) -> tuple:
    summary = re.sub(r"source FIR [A-Z]{4};", "source FIR;", line["conditions_summary"])
    return (line["text"], summary, line.get("further_actions", 0))


def _compact_untimed_availability_lines(lines: list[dict]) -> list[dict]:
    """Quote identical untimed status once, retaining each FIR, notice and page.

    Only the source FIR label may differ. Full validity/conditions and further
    action counts must agree; source-held objects remain untouched.
    """
    rendered = []
    groups = {}
    for line in lines:
        if line.get("instruction_effect") != "availability" or line.get("actm"):
            rendered.append(line)
            continue
        key = _untimed_status_key(line)
        group = groups.get(key)
        if group is None:
            group = {**line, "notam_ids": list(line["notam_ids"]), "source_pages": list(line["source_pages"])}
            groups[key] = group
            rendered.append(group)
        else:
            original_fir = group["fir"]
            group["fir"] = "/".join(dict.fromkeys([*original_fir.split("/"), line["fir"]]))
            group["conditions_summary"] = group["conditions_summary"].replace(f"source FIR {original_fir};", f"source FIR {group['fir']};")
            group["notam_ids"] = list(dict.fromkeys([*group["notam_ids"], *line["notam_ids"]]))
            group["source_pages"] = sorted(set([*group["source_pages"], *line["source_pages"]]))
    return rendered


def _first_untimed_status_lines(lines: list[dict]) -> list[dict]:
    """Final capacity step: first printed untimed status, including identical
    quotations. Physical source-page order is evidence order, not operating
    priority. Other whole rows stay held and are explicitly identified."""
    untimed = [line for line in lines if line.get("instruction_effect") == "availability" and not line.get("actm")]
    if not untimed:
        return []
    ordered = sorted(untimed, key=lambda line: min(line.get("source_pages") or [10 ** 6]))
    first_key = _untimed_status_key(ordered[0])
    return [line for line in untimed if _untimed_status_key(line) == first_key]


def _primary_and_next_valued_call(lines: list[dict], primary: dict | None) -> list[dict]:
    """Bounded capacity attempt in existing action order, before primary-only.

    A second row must be a qualifying crew contact with printed values at
    another FIR; one whose printed conditions are held comes first
    (ATC-PDF-PRIORITY). A failed source condition or another actor cannot
    consume that slot. Selection never changes a held row or its applicability.
    """
    candidates = [line for line in lines if line is not primary and
                  is_call_line(line) and has_printed_values(line) and
                  (not primary or line["fir"] != primary["fir"])]
    next_call = next((line for line in candidates if line.get("applicability_state") == "conditions_held"),
                     candidates[0] if candidates else None)
    return [line for line in lines if line is primary or line is next_call]


def plan_page(title: str, bookmark: str, rows: list[tuple[Any, list[Card]]], *,
              ribbon_index: int = 0, assurance: str = "", aliases: tuple[str, ...] = (),
              body: float = BODY, leading: float = LEADING,
              balance_columns: bool = False) -> list[Page]:
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
    measured_widths: list[list[float]] = []
    for height, cards in rows:
        widths = (balanced_row_widths(cards, full_width, body, leading) if balance_columns
                  else row_widths(cards, full_width))
        measured_widths.append(widths)
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
    for (_, cards), height, widths in zip(rows, heights, measured_widths):
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


def plan_page_flexible(title, bookmark, rows_for, *, variants=(0,), steps=None,
                       balance_columns: bool = False, **kwargs) -> list[Page]:
    """Try each grid variant on the readable body ladder before failing closed.

    Column width, not type size, is the first lever: a dense source-bound card
    is given more of the row before the body steps down, and the body never
    steps below the published readable floor. ``steps``, when given, is an
    outermost content-deferral ladder the page owner interprets (page 1: how
    many trailing TAF change groups go to the WEATHER page); step 0 is the
    whole content and is exhausted across every grid and size first. When
    enabled, measured column balancing is tried after the original layouts
    and before advancing to any content-deferral step.
    """
    last: ValueError | None = None
    for step in (steps if steps is not None else (None,)):
        for balance in ((False, True) if balance_columns else (False,)):
            for variant in variants:
                for body, leading in BODY_LADDER:
                    try:
                        rows = rows_for(body, leading, variant) if step is None else rows_for(body, leading, variant, step)
                        return plan_page(title, bookmark, rows, body=body, leading=leading,
                                         balance_columns=balance, **kwargs)
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
    # David, 22 Sep 2026 13:38-13:40: state the general reminder ONCE, on the
    # front page, and stop repeating review/cross-check/confirmation wording
    # through the briefing. This banner used to be drawn on every page - six
    # identical copies in a six-page briefing, 168 across the held corpus. The
    # statement itself is unchanged; only its repetition is gone.
    if number == 1:
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
            for value, font, size, colour, align, *link in items:
                if align == "link":
                    canvas.setFont(font, size)
                    canvas.setFillColor(colour)
                    canvas.drawString(inner_left, baseline, value)
                    canvas.linkURL(
                        link[0],
                        (inner_left - 1, baseline - 2.5,
                         inner_left + stringWidth(value, font, size) + 1, baseline + size),
                        relative=0, thickness=0,
                    )
                    continue
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


# The seven label offsets release 422 tried, in order (kept first so every figure that fitted before is drawn as before).
FIGURE_LABEL_OFFSETS = ((0, 9), (0, 23), (35, 9), (-35, 9), (0, -17), (55, 23), (-55, 23))
FIGURE_LABEL_RINGS = (30, 45, 60, 80)
FIGURE_LABEL_FACES = (9, 8, 7)


def _label_box(px, py, label_width):
    return (px - label_width / 2 - 2, py - 3, px + label_width / 2 + 2, py + 10)


def _figure_label_candidates(anchors, label_width_of):
    """Every place a label may sit, in preference order: the seven fixed offsets at the pavement's midpoint, then
    rings around it, then the same around other points along the pavement, then the same at smaller faces."""
    import math
    for size in FIGURE_LABEL_FACES:
        label_width = label_width_of(size)
        for anchor_index, (ax, ay) in enumerate(anchors):
            offsets = list(FIGURE_LABEL_OFFSETS)
            for radius in FIGURE_LABEL_RINGS:
                offsets.extend((radius * math.cos(math.radians(a)), radius * math.sin(math.radians(a))) for a in range(0, 360, 30))
            for ox, oy in offsets:
                px, py = ax + ox, ay + oy
                yield size, label_width, px, py, _label_box(px, py, label_width)


def place_figure_labels(labels, occupied, x, y, width, height, figure_floor):
    """Measured label placement for an airport figure.

    `labels` maps a ref to (length, midpoint, colour, projected points of its longest way). Returns the placed
    labels [(ref, midpoint, colour, (px, py, size, box))] and the keyed ones [(ref, (marker point, colour))] whose
    plate found no readable place: they are numbered on the figure and named in a key under it. `occupied` gains
    every box placed. Runway refs sort before taxiway refs, so runways keep the first choice of place.
    """
    import math
    placements, keyed = [], []
    for ref, (_, (lx, ly), colour, points) in sorted(labels.items()):
        along = [points[0], points[-1]]
        if len(points) >= 2:
            # Quarter and three-quarter points of the way, for a plate that cannot sit at its middle.
            total = sum(math.dist(a, b) for a, b in zip(points, points[1:])) or 1.0
            for fraction in (0.25, 0.75):
                target, run = fraction * total, 0.0
                for a, b in zip(points, points[1:]):
                    seg = math.dist(a, b)
                    if run + seg >= target and seg:
                        t = (target - run) / seg
                        along.append((a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t))
                        break
                    run += seg
        anchors = [(lx, ly), *along]
        placed = None
        for size, label_width, px, py, box in _figure_label_candidates(anchors, lambda size: stringWidth(ref, "Helvetica-Bold", size)):
            if box[0] < x or box[2] > x + width or box[1] < figure_floor or box[3] > y + height:
                continue
            if any(box[0] < b[2] and box[2] > b[0] and box[1] < b[3] and box[3] > b[1] for b in occupied):
                continue
            placed = (px, py, size, box)
            break
        if placed is not None:
            occupied.append(placed[3])
            placements.append((ref, (lx, ly), colour, placed))
            continue
        # No readable plate anywhere near this pavement: number the mark itself and name it in the key.
        marker = None
        for mx, my in anchors:
            box = (mx - 5.5, my - 5.5, mx + 5.5, my + 5.5)
            if box[0] < x or box[2] > x + width or box[1] < figure_floor or box[3] > y + height:
                continue
            if any(box[0] < b[2] and box[2] > b[0] and box[1] < b[3] and box[3] > b[1] for b in occupied):
                continue
            marker = (mx, my)
            occupied.append(box)
            break
        if marker is None:
            raise ValueError(f"Airport figure has no readable label position for {ref}")
        keyed.append((ref, (marker, colour)))
    return placements, keyed


def figure_label_key_lines(keyed, width):
    """The key under a figure, "1 VV · 2 KE", wrapped to the figure's width at the key face; None when it cannot fit."""
    entries = [f"{number} {ref}" for number, (ref, _) in enumerate(keyed, start=1)]
    lines, current = [], ""
    for entry in entries:
        candidate = f"{current} · {entry}" if current else entry
        if stringWidth(candidate, "Helvetica", 8) <= width:
            current = candidate
        else:
            if current:
                lines.append(current)
            current = entry
    if current:
        lines.append(current)
    return lines if len(lines) <= 2 and all(stringWidth(line, "Helvetica", 8) <= width for line in lines) else None


def draw_airport_figure(canvas, overlay, x, y, width, height, *, planned_runway=None,
                        index_entry=None) -> None:
    """Draw supplied geometry only; a scheduled/unknown mark is not a closure.

    9 Sep 2026: "This is also rubbish generated" - three bare runway lines, no
    taxiways, no apron, no scale. The figure strokes the exact aerodrome
    boundary the app computes, fills apron polygons as areas, strokes the
    taxiways at a readable weight, and carries a scale bar and a north arrow.
    Nothing is inferred: every stroke is a supplied feature, the outline is
    the published boundary, and the legend names only what was drawn.

    Labels (release-422 independent QA, F3): every runway and every marked
    pavement is named by a measured search - the seven offsets of before first,
    so a figure that fitted before is drawn exactly as before; then wider
    rings, other points along the pavement and smaller faces; and when the
    pavement is too crowded for a plate beside it, the mark is numbered on the
    figure and named in a key under it. The figure is laid out once more with
    the key's line(s) when a key is needed. No mark is dropped, no name is
    silently left out, and a figure that cannot carry even its key fails
    closed with the reason.
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
    features = sorted((overlay.get("featureCollection") or {}).get("features") or [], key=lambda feature: (
        0 if (feature.get("geometry") or {}).get("type") == "Polygon"
        else 2 if (feature.get("properties") or {}).get("aeroway") == "runway" else 1))

    def layout(floor):
        """Everything the figure's geometry decides for a caption strip of `floor` extra points: the projection,
        the chrome the labels must avoid, the label anchors and their measured places."""
        scale = min((width - 50) / dx, (height - 45 - floor) / dy)

        def point(coordinate):
            return (x + (width - dx * scale) / 2 + (coordinate[0] - west) * longitude_factor * scale,
                    y + 28 + floor + (height - 45 - floor - dy * scale) / 2 + (coordinate[1] - south) * scale)

        arrow_x, arrow_top = x + width - 13, y + height - 1
        points_per_metre = scale / 111_320.0
        metres = scale_bar_metres(points_per_metre, width * 0.28)
        bar_length = metres * points_per_metre
        bar_x, bar_y = x + 3, y + height - 8
        scale_label = f"{metres / 1000:g} km" if metres >= 1000 else f"{metres} m"
        occupied = [(arrow_x - 9, arrow_top - 35, arrow_x + 9, arrow_top + 1),
                    (bar_x - 2, bar_y - 6, bar_x + bar_length + 8 + stringWidth(scale_label, "Helvetica", 9), bar_y + 6)]
        labels = {}
        for feature in features:
            prop = feature.get("properties") or {}
            geometry = feature.get("geometry") or {}
            if geometry.get("type") == "Polygon":
                continue
            lines = [geometry.get("coordinates") or []] if geometry.get("type") == "LineString" else geometry.get("coordinates") or []
            mark = marks.get(prop.get("featureId") or feature.get("id"))
            planned = bool(planned_runway and str(planned_runway) in str(prop.get("ref") or "").split("/"))
            runway = prop.get("aeroway") == "runway"
            colour = RED if mark == "closure" else AMBER if mark else CYAN if planned else MUTED if runway else TAXIWAY
            if not (prop.get("ref") and (runway or mark)):
                continue
            for line in lines:
                if len(line) < 2:
                    continue
                # OSM can split one runway into several ways. Label its
                # longest held segment once, with measured collision checks.
                length = sum(math.dist(point(a), point(b)) for a, b in zip(line, line[1:]))
                ref = str(prop["ref"])
                if length > labels.get(ref, (0,))[0]:
                    first, last = point(line[0]), point(line[-1])
                    labels[ref] = (length, ((first[0] + last[0]) / 2, (first[1] + last[1]) / 2), colour, [point(c) for c in line])
        placements, keyed = place_figure_labels(labels, occupied, x, y, width, height, y + 25 + floor)
        return {"scale": scale, "point": point, "arrow": (arrow_x, arrow_top), "bar": (bar_x, bar_y, bar_length, scale_label),
                "placements": placements, "keyed": keyed}

    floor = 11 if outline_gap else 0
    plan = layout(floor)
    key_lines = []
    if plan["keyed"]:
        key_lines = figure_label_key_lines(plan["keyed"], width)
        if key_lines is None:
            raise ValueError("Airport figure label key does not fit: " + ", ".join(ref for ref, _ in plan["keyed"]))
        # The key takes caption lines from the geometry strip; lay the figure out once more for them.
        floor += 11 * len(key_lines)
        plan = layout(floor)
        if plan["keyed"] and figure_label_key_lines(plan["keyed"], width) is None:
            raise ValueError("Airport figure label key does not fit: " + ", ".join(ref for ref, _ in plan["keyed"]))
        key_lines = figure_label_key_lines(plan["keyed"], width) or []
    point = plan["point"]
    scale = plan["scale"]

    # Chrome first, so runway labels are placed around it: the north arrow in
    # the right margin column and the scale bar in the top strip.
    arrow_x, arrow_top = plan["arrow"]
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

    bar_x, bar_y, bar_length, scale_label = plan["bar"]
    bar = canvas.beginPath()
    bar.moveTo(bar_x, bar_y - 2.5)
    bar.lineTo(bar_x, bar_y + 2.5)
    bar.moveTo(bar_x, bar_y)
    bar.lineTo(bar_x + bar_length, bar_y)
    bar.moveTo(bar_x + bar_length, bar_y - 2.5)
    bar.lineTo(bar_x + bar_length, bar_y + 2.5)
    canvas.drawPath(bar, stroke=1, fill=0)
    canvas.setFont("Helvetica", 9)
    canvas.drawString(bar_x + bar_length + 6, bar_y - 3.2, scale_label)

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

    shaded = False
    for feature in features:
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
            if len(line) < 2 or polygon:
                continue
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
    for ref, (lx, ly), colour, (px, py, size, box) in plan["placements"]:
        # A padded opaque plate prevents runway/taxiway strokes crossing
        # the glyphs. Labels retain leaders to their measured positions.
        canvas.setStrokeColor(colour)
        canvas.setLineWidth(.5)
        canvas.line(lx, ly, px, py + 3)
        canvas.setFillColor(BG)
        canvas.roundRect(box[0], box[1], box[2]-box[0], box[3]-box[1], 2, fill=1, stroke=0)
        canvas.setFillColor(colour)
        canvas.setFont("Helvetica-Bold", size)
        canvas.drawCentredString(px, py, ref)
    for number, (ref, ((mx, my), colour)) in enumerate(plan["keyed"], start=1):
        canvas.setFillColor(colour)
        canvas.circle(mx, my, 5.2, stroke=0, fill=1)
        canvas.setFillColor(WHITE)
        canvas.setFont("Helvetica-Bold", 7)
        canvas.drawCentredString(mx, my - 2.5, str(number))
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
        canvas.drawString(x, y + 26 + 11 * len(key_lines), outline_gap)
    for index, line in enumerate(key_lines):
        canvas.setFont("Helvetica", 8)
        canvas.drawString(x, y + 26 + 11 * (len(key_lines) - 1 - index), line)
    canvas.setFont("Helvetica", 9)
    canvas.drawString(x, y + 15, " · ".join(legend))
    canvas.drawString(x, y + 4, "OSM reference · cyan: planned · red: unavailable · amber: scheduled/partial")


# The page-1 station column's PERTINENT field: the width it is fitted to, the
# lines it gives the other restrictions, and the hard cap for the ones it must
# always name.
PAGE_ONE_PERTINENT_WIDTH = 180
PAGE_ONE_PERTINENT_BUDGET = 6
PAGE_ONE_PERTINENT_MANDATORY_CAP = 9


def _unresolved_on_planned_runway(analysed: dict[str, Any]) -> dict[str, Any] | None:
    """What page 1 says of held notices on the planned runway it cannot reduce.

    SQ303 16 Jul 2026, WSSS SX120/25: the published closure schedules for RWY
    02L/20R could not be resolved for the arrival on planned RWY 20R; page 1
    counted it among "1 held notice(s)" and never said the planned runway was
    involved. The words name the planned runway and which part is unresolved -
    the notice's timing or its effect - never a closure or an outage.
    """
    planned = str(analysed.get("planned_runway") or "").strip()
    held = [item for item in analysed.get("unresolved_detail") or [] if item.get("names_planned")]
    if not planned or not held:
        return None
    moment = {"departure": "departure", "destination": "arrival"}.get(str(analysed.get("role")), "the reference time")
    parts = list(dict.fromkeys(f"timing at {moment}" if item.get("reason") == "timing" else "effect" for item in held))
    notices = "1 held notice" if len(held) == 1 else f"{len(held)} held notices"
    text = f"Planned RWY {planned}: {notices} unresolved ({', '.join(parts)})."
    return {"text": text, "tier": 1, "notam_ids": [str(item.get("notam_id")) for item in held], "source": "unresolved"}


def page_one_pertinent(analysed: dict[str, Any]) -> dict[str, Any]:
    """The page-1 PERTINENT statement for one station, decided once.

    Independent QA of release 394 read different numbers under the same words
    on the two surfaces: SQ303 EBBR/WSSS 10/9 "analysed surface/approach
    consequence(s)" on the dashboard against 2/2 on page 1, SQ352 WSSS/EKCH
    11/6 against 2/1. The count is now decided here and both surfaces print it.

    The first repair named the analysis's full consequence sentences while
    they fitted four lines, and three of the four reviewed stations named
    nothing: every first sentence was longer than the column. SQ352 EKCH lost
    "RWY 22L CAT II/III operations unavailable" - the planned runway - which
    the card had named in release 394 (independent candidate review, 22 Sep
    2026). Page 1 now names each consequence in its short form (``brief``,
    decided by the analysis from the same parts as the full sentence; the
    AIRPORTS page keeps the sentence and its NOTAM IDs), most relevant first:
    the airport, then the planned runway - including a held notice on it that
    could not be reduced - then other runways, other approach aids, taxiways.
    The first two are always named; the rest while they fit.
    """
    lines = [line for line in analysed.get("lines") or [] if str(line.get("text") or "").strip()]
    items = [{"text": str(line.get("brief") or "").strip(), "tier": int(line.get("relevance", 3)),
              "notam_ids": [str(notice) for notice in line.get("notam_ids") or []], "source": "analysed"}
             for line in lines if str(line.get("brief") or "").strip()]
    on_planned = _unresolved_on_planned_runway(analysed)
    if on_planned:
        items.append(on_planned)
    items.sort(key=lambda item: item["tier"])
    named: list[str] = []
    used = 0
    stopped = False
    for item in items:
        needed = len(wrap(item["text"], PAGE_ONE_PERTINENT_WIDTH - 28, size=BODY))
        mandatory = item["tier"] <= 1
        limit = PAGE_ONE_PERTINENT_MANDATORY_CAP if mandatory else PAGE_ONE_PERTINENT_BUDGET
        # Never name a lesser restriction in place of one that did not fit.
        item["named"] = not stopped and used + needed <= limit
        if item["named"]:
            named.append(item["text"])
            used += needed
        elif not mandatory:
            stopped = True
    unresolved = [str(item) for item in analysed.get("unresolved_ids") or []]
    return {
        "role": analysed.get("role"),
        "icao": analysed.get("icao"),
        "planned_runway": analysed.get("planned_runway"),
        "named_lines": named,
        "items": items,
        "analysed_count": len(lines),
        "unresolved_ids": unresolved,
        "unresolved_count": len(unresolved),
    }


def page_one_pertinent_lines(field: dict[str, Any], pointer: str) -> list[str]:
    """The field's words: the named restrictions, then what was and was not reduced.

    ``pointer`` is the one surface-specific part - where the full analysis is
    on that surface. The numbers and every other word are the same on both.
    """
    analysed = int(field.get("analysed_count") or 0)
    unresolved = int(field.get("unresolved_count") or 0)
    counted = f"{analysed} analysed surface/approach consequence(s)"
    named = [str(line) for line in field.get("named_lines") or []]
    # Nothing held and nothing publishable are different facts (SQ352 EKCH,
    # release 392): a station whose notices could not be reduced must never read
    # as one that holds none.
    if analysed or unresolved or named:
        held = f"; {unresolved} pertinent held notice(s) not reduced" if unresolved else ""
        return [*named, f"{counted}{held}. {pointer}"]
    return ["No analysed constraint is held for the planned movement.", f"{counted}. {pointer}"]


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
    return kinds or "HELD"


def deferred_status_lines(flight, rows) -> list[Any]:
    """TECHNICAL STATUS: each analysed declaration, then a link per cited item.

    QA496-01 (Codex, production release 496, 13 Oct 2026): the six-page
    publication pilots download printed "MEL 25-20-50A" as text only - every
    governed-source link lived in the older reference layout. Every MEL, CDL
    and CDDL item the OFP cites with an item number now carries the durable
    signed-in landing link (combined_brief.governed_deferred_source_target).
    The link names the item, never a page or a document: at the tap the
    landing applies the app's one rule to the current approved library and
    opens the page the dashboard offers, or says plainly that the library
    holds no such item - with a way back. A PDF cannot go stale on a page.
    """
    from .combined_brief import governed_deferred_source_target

    items = [item for item in (flight.get("deferred_items") or []) if isinstance(item, dict)]
    lines: list[Any] = []
    for row in rows:
        lines.append(row["text"])
        linked: set[tuple[str, str]] = set()
        for index in row.get("source_item_indices") or []:
            if not isinstance(index, int) or not 0 <= index < len(items):
                continue
            item = items[index]
            uri = governed_deferred_source_target(flight, item)
            key = (str(item.get("item_type") or "").strip().upper(),
                   str(item.get("reference") or "").strip().upper())
            if not uri or key in linked:
                continue
            linked.add(key)
            lines.append(LinkLine(f"OPEN APPROVED {key[0]} {key[1]} >", uri))
    return lines


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
    # Late airport evidence and governed references can follow the initial
    # analysis. Both endpoint and PDF project from these complete held inputs,
    # never from the checklist cached before those inputs were published.
    receipt = _operational_coverage_receipt(flight, view, findings, references)
    airport_analysis = airport_pdf_analysis(flight, view.get("airport_operational_panels") or [])
    alternate_analysis = alternate_pdf_analysis(flight, view.get("airport_operational_panels") or [])
    amount = lambda key: kg((fuel_rows.get(key) or {}).get("fuel_kg"))
    signed_amount = lambda key: signed_kg((fuel_rows.get(key) or {}).get("fuel_kg"))
    states = {r["key"]: r["state"] for r in receipt["rows"]}
    sections: dict[str, list[Page]] = {}
    route_map = build_publication_map(flight, view)

    vws_summary = vws_threshold_sentence(vws)
    terrain_summary = f"{len(terrain.get('events') or [])} high-MSA event(s); controlled-profile status is in the closing record."
    deferred = deferred_status_lines(flight, view["deferred_pdf_analysis"])

    # ---------------------------------------------------------------- page 1
    def station(role: str, accent, extra: list[tuple[str, list[str]]], taf_drop: int = 0) -> Card:
        station_view = view.get(role) or {}
        weather = station_view.get("weather") or {}
        analysed = next((a for a in airport_analysis if a["role"] == role),
                        {"lines": [], "unresolved_ids": []})
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
        # destination. 23 Sep 2026, 20:22: "You need to give the full METAR /
        # TAF for WSSS and EGKK" - his current instruction outranks the form,
        # so both columns print the whole held TAF under a TAF label (a label
        # has to match the value beneath it). The deviation from his file is
        # declared in tests/boss_reference_format_manifest.json
        # (contract_extensions.overview_column_field_overrides).
        # ``taf_drop`` > 0 only when every full-record layout of page 1 has
        # failed its capacity (plan_page_flexible steps): the largest whole-
        # group prefix, marked, with the whole record on the WEATHER page.
        blocks.append(("TAF", [page_one_taf_field_continued(weather.get("taf"), taf_drop)
                               if taf_drop else page_one_taf_field(weather.get("taf"), "WEATHER page")]))
        # The nine-page ARRIVAL SURFACE card counted the analysed consequences
        # for the arrival. The count stays published, beside the held notices
        # this analysis could not reduce, as the one statement the dashboard
        # station card prints too (``page_one_pertinent``; independent QA of
        # release 394 read 10/9 there against 2/2 here for SQ303).
        blocks.append(("PERTINENT", page_one_pertinent_lines(
            page_one_pertinent(analysed), "Full analysis: AIRPORTS page.",
        )))
        # Keep both source-held station identifiers, as on the dashboard and
        # David's reference. Do not make the release gate waive a lost IATA.
        station_icao = text(station_view.get("icao"))
        station_iata = str(flight.get(f"{role}_iata") or "").strip()
        station_identity = f"{station_iata} / {station_icao}" if station_iata else station_icao
        return Card("DEPARTURE" if role == "departure" else "DESTINATION", [], accent,
                    tag="CFP P1", kind="station", width_weight=1.25,
                    payload=(station_identity,
                             airport_short_name(station_view.get("icao")), blocks),
                    target="sec_airports")

    weather_tile_payload = [
        ("SIGMET", "HELD" if (view.get("hazards") or {}).get("sigmet_cards") else "NO DATA"),
        # VOLCANIC-CHECK-436: the tile read "HELD" from a volcano NOTAM alone and
        # "NO DATA" beside a feed VA SIGMET crossing the route. It now prints the
        # composed check: AFFECTING / HELD (VA SIGMET or VAAC advisory) / NOTICE
        # (volcano notices only) / NO DATA.
        ("VA", text(((view.get("vaa") or {}).get("check") or {}).get("tile"))
               if ((view.get("vaa") or {}).get("check") or {}).get("tile")
               else ("HELD" if ((view.get("vaa") or {}).get("cfp_advisories")) else "NO DATA")),
        ("TC", "HELD" if cyclone_content(flight)["time_matched"] else "NO DATA"),
        ("PLOTTED", str(len(route_map.get("publication_events") or []))),
        ("VWS MAX", text(vws.get("maximum_display")))]
    # R2 (David, 22 Sep 2026): the tile states the coverage it holds; "No data
    # is a gap, not NIL" was a principle sentence repeated on every briefing.
    weather_tile_line = ("Coverage incomplete."
                         if any(value == "NO DATA" for _, value in weather_tile_payload)
                         else "Products held.")
    tiles = [
        Card("PERFORMANCE", [f"{text(inputs.get('runway_condition'))} RWY {text(inputs.get('runway'))}; "
                             f"EOSID {text(inputs.get('eosid'))}."],
             CYAN, "sec_performance", tag="CFP P1", kind="tile", payload=[
                 ("PTOW", kg(masses.get("ptow"))), ("RTOW", kg(perf.get("selected_rtow_kg"))),
                 # His tile signs the margin: MARGIN +11,376 KG. So does the
                 # dashboard card (overview-cards.ts `signedKg(margin)`).
                 ("MARGIN", signed_kg(perf.get("margin_kg"))), ("PLWT", kg(masses.get("plwt"))),
                 ("FLAPS", text(inputs.get("flap_setting")))]),
        # His reference FUEL tile reads TANKER when the whole carried excess is
        # tankering, EXCESS otherwise, on the dashboard's own rule - and signs
        # the value when it says TANKER (`TANKER +18,847 KG`), exactly as the
        # dashboard card does (`tanker ? signedKg(excess) : kg(excess)`).
        Card("FUEL", [f"Arithmetic {fuel_state_label(fuel.get('state'))}."],
             GREEN, "sec_performance", tag="CFP P1", kind="tile", payload=[
                 ("BLOCK", amount("fuel_in_tanks")), ("FPL REQ", amount("flt_plan_reqmt")),
                 (excess_fuel_tile_label(fuel),
                  (signed_amount if tanker_only_excess(fuel) else amount)("excess_fuel")),
                 ("BURNOFF", amount("burnoff")),
                 ("TAXI", kg(fuel.get("taxi_fuel_kg")))]),
        Card("TECH STATUS", [f"{len(view['deferred_pdf_analysis'])} consequence(s) on PERF / FUEL / TECH."],
             AMBER, "sec_performance", tag="CFP P1", kind="tile",
             payload=[(deferred_item_label(row.get("title")), deferred_gate_value(row))
                      for row in view.get("deferred_dispatch_gates") or []][:5]
             or [("DEFERRED", "None parsed")]),
        Card("WEATHER / HAZARDS", [weather_tile_line],
             VIOLET, "sec_hazard", tag="CFP P1", kind="tile", payload=weather_tile_payload),
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

    def overview_rows(body, leading, variant=0, step=0):
        station_weight, map_weight = overview_grids[variant]
        return [
            (None, [replace(station("departure", CYAN, [("SCHEDULE", [schedule_field()])], taf_drop=step),
                            width_weight=station_weight),
                    Card("CFP ROUTE - PERTINENT DECISION GATES", [], CYAN, tag="SCHEMATIC",
                         kind="map", payload=route_map, width_weight=map_weight),
                    replace(station("destination", RED, [("EET / SCHED", [f"{text((view.get('metrics') or {}).get('eet'))} / {clock(identity.get('scheduled_eta_hhmm'))}"])], taf_drop=step),
                            width_weight=station_weight)]),
            (None, tiles),
            ((44.0, 52.0), strip),
        ]
    # 23 Sep 2026: page 1 prints the full METAR / TAF records. Every grid and
    # type size is tried with the whole records first; only when none fits the
    # physical page does a step defer the last change group(s) of the TAFs to
    # the WEATHER page behind an explicit marker - at most as many groups as
    # the longer TAF holds, so a step can never cut into the base period.
    from .page_one_weather import page_one_taf_change_groups
    deferrable = max(len(page_one_taf_change_groups(((view.get(role) or {}).get("weather") or {}).get("taf"))[1])
                     for role in ("departure", "destination"))
    sections["overview"] = plan_page_flexible(
        "OVERVIEW", "sec_overview", overview_rows, ribbon_index=0, aliases=("sec_route", "sec_summary"),
        variants=tuple(range(len(overview_grids))), steps=tuple(range(deferrable + 1)),
        assurance="CFP P1 PRIORITISED | SOURCE FACTS + LABELLED ANALYSIS | AI AUTHORITY: NONE")

    # ---------------------------------------------------------------- page 2
    decision = list(view.get("decision_findings") or [])
    finding_cards = []
    for item in decision:
        pill, accent = severity_pill(item.get("severity"))
        finding_cards.append(Card("", [], accent, item.get("target"), kind="finding", payload=(
            pill, str(item.get("title") or "Review item"),
            str(item.get("summary") or "Not assessed."),
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
            # One quantity, one format. His SQ481 REV5 prints this same row as
            # `RTOW - PTOW +8,581 KG`; the page-1 tile above states it signed.
            f"RTOW - PTOW: {signed_kg(perf.get('margin_kg'))} · MLGW {kg(inputs.get('maximum_landing_weight_kg'))}",
            f"MAX FUEL AVAILABLE {kg(inputs.get('maximum_fuel_available_kg'))}"]
    fuel_lines = [f"{label} {amount(key)}" for key, label in (("burnoff", "BURNOFF"), ("stat_cont", contingency_label(fuel_rows)), ("altn_fuel", "ALTN FUEL"), ("altn_hold", "ALTN HOLD"))]
    for key, label in (("dest_hold_top_up", "DEST HOLD TOP-UP"), ("edto_top_up", "EDTO TOP-UP")):
        if (fuel_rows.get(key) or {}).get("fuel_kg"):
            fuel_lines.append(f"{label} {amount(key)}")
    # His reference page-3 chain runs FPL REQUIREMENT -> TANKER EXCESS -> FUEL
    # IN TANKS, and the excess closes that arithmetic (tanks - requirement).
    # Until C2 the chain skipped it entirely and only the TANKER/MEL allocation
    # appeared, under RECONCILIATION, so the downloaded PDF never stated the
    # carried excess as one contiguous row.
    fuel_lines += [f"TAXI FUEL {kg(fuel.get('taxi_fuel_kg'))}", f"FLT PLAN REQMT {amount('flt_plan_reqmt')}",
                   f"{excess_fuel_chain_label(fuel)} {amount('excess_fuel')}",
                   f"FUEL IN TANKS {amount('fuel_in_tanks')}", f"Arithmetic: {fuel_state_label(fuel.get('state'))}"]
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

    # The dispatcher's general page-1 remarks belong to the mass chain, not to
    # whichever declaration happened to be printed above them (SQ24 15 Aug).
    from .analysed_briefing_content import held_page1_remarks, page1_remark_consequences
    margins += page1_remark_consequences(held_page1_remarks(flight), fuel)

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
    # One group of lines per alternate row (its plan line and its consequences), so a page that cannot hold every row
    # defers whole trailing rows and states how many (QA516: a display limit shows what it leaves out, never drops it).
    alternate_groups = []
    for row in view.get("alternate_assessment_rows") or []:
        analysis = next((p for p in alternate_analysis if p["icao"] == row.get("airport")), {"lines": []})
        if (row.get("assessment") or {}).get("row_not_read"):
            # A printed alternate row the parser did not read: its review, never an empty plan line.
            alternate_groups.append([f"{text(row.get('airport'))} {str(row.get('role') or 'alternate').upper()} · {row['assessment']['text']}"])
            continue
        alternate_groups.append([
            f"{text(row.get('airport'))}/{text(row.get('runway'))} {str(row.get('role') or 'alternate').upper()} · {text(row.get('approach'))} · MIN {text(row.get('minima'))} · {text(row.get('distance_nm'))} NM / {text(row.get('time_minutes'))} min / {kg(row.get('fuel_kg'))}.",
            *(r["text"] for r in analysis["lines"]),
        ])

    def alternate_lines_keeping(keep: int) -> list[str]:
        lines = [line for group in alternate_groups[:keep] for line in group]
        if keep < len(alternate_groups):
            lines.append(f"+{len(alternate_groups) - keep} further alternate row(s) on the dashboard.")
        return lines

    alternate_lines = alternate_lines_keeping(len(alternate_groups))

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
    # Every alternate row is printed when the page holds them all (every held original does). Only when it cannot are
    # whole trailing rows left to the dashboard, with their stated count - never cut silently, never a failed page.
    keep = len(alternate_groups)
    while True:
        try:
            sections["airports"] = plan_page_flexible(
                "AIRPORTS / ALTERNATES", "sec_airports", airport_rows, ribbon_index=3,
                aliases=("sec_departure", "sec_destination", "sec_alternates"),
                assurance="AIRPORT / ALTERNATE APPLICABILITY | FLIGHT-TIME CONSEQUENCES ONLY")
            break
        except ValueError:
            if keep == 0:
                raise
            keep -= 1
            alternate_lines = alternate_lines_keeping(keep)

    # ---------------------------------------------------------------- page 5
    from .page_one_weather import page_one_taf_change_groups
    terminal: list[str] = []
    terminal_tafs: list[tuple[int, str, Any]] = []
    for role in ("departure", "destination"):
        station_view = view.get(role) or {}
        terminal.append(f"{text(station_view.get('icao'))} METAR: {text((station_view.get('weather') or {}).get('metar'))}")
        # 23 Sep 2026: the whole TAF here as well, so a page-1 column that had
        # to defer its last change groups points at a page that holds them.
        terminal_tafs.append((len(terminal), text(station_view.get("icao")), (station_view.get("weather") or {}).get("taf")))
        terminal.append(f"{text(station_view.get('icao'))} TAF: {text((station_view.get('weather') or {}).get('taf'))}")
        forecast = ((view.get("overview") or {}).get(role) or {}).get("forecast_at_reference") or {}
        conditions = forecast.get("applicable_conditions")
        # 23 Sep 2026 (T3): "Do NOT decipher. Your user is a pilot." The page
        # prints the coded groups the assessment used; an assessment that
        # published no groups says so rather than decoding.
        groups = [str(group).strip() for group in (forecast.get("applicable_groups") or []) if str(group).strip()]
        coded = " ".join(groups) or ("coded groups not published by this analysis" if conditions else "")
        source = forecast.get("forecast_source") or {}
        if coded:
            if str(source.get("record_type") or "").upper() in {"METAR", "SPECI"}:
                # The checked flight window is not an observation validity.
                terminal.append(f"{text(station_view.get('icao'))} observation used: {coded}")
            else:
                terminal.append(f"{text(station_view.get('icao'))} forecast {text(forecast.get('utc_window'))}: {coded}")
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

    # F5 of the release-420 independent QA (24 Sep 2026): a production
    # analysis (live weather beside the OFP's own) put page 5 two points over
    # its budget on a fresh SQ24, and this page had no deferral: it tried its
    # grids and sizes and failed closed, so the whole six-page briefing
    # answered 500 and could not be saved. Like page 6, it now defers WHOLE
    # units to the dashboard - never a cut line, never a stale PDF - and says
    # so on the page, in this order: the planning ETP / EDTO clock rows
    # first, then the EDTO airport windows, then the SIGMET rows; each is a
    # dashboard-held record and the concise gate verifies that exactly the
    # stated number of trailing rows is deferred. The plotted-hazard key is
    # never deferred: its words and the SIGMET verdicts are two statements of
    # one screening on one page. Step 0 is the whole content; it is exhausted
    # across every grid and size before any unit is deferred.
    # VOLCANIC-CHECK-436: the volcanic card names every responsible VAAC and its
    # reach. Before any SIGMET, EDTO or clock row is deferred, the page first
    # prints those facts as counts ("VAACs 0/4 reached, 9 route points
    # unsettled"), then - beside held OFP records - leaves them to page 6's
    # source line and checklist, which state every unreached, partial or
    # unqueried source. Operational rows keep their place; nothing reads clear.
    WEATHER_DEFER_LADDER = (
        {"edto": None, "sigmet": None, "clocks": None, "ash": "whole"},
        {"edto": None, "sigmet": None, "clocks": None, "ash": "compact"},
        {"edto": None, "sigmet": None, "clocks": None, "ash": "omit"},
        {"edto": None, "sigmet": None, "clocks": 6, "ash": "omit"},
        {"edto": 6, "sigmet": None, "clocks": 6, "ash": "omit"},
        {"edto": 6, "sigmet": 6, "clocks": 6, "ash": "omit"},
        {"edto": 3, "sigmet": 3, "clocks": 3, "ash": "omit"},
        {"edto": 2, "sigmet": 2, "clocks": 1, "ash": "omit"},
    )
    # F8 of Codex's QA of releases 468-474 (10 Oct 2026): a TAF longer than the
    # page can hold beside its other content (a labelled synthetic KJFK TAF of
    # 12+ FM groups on SQ24) failed every rung above and the whole PDF aborted.
    # The six-page format admits no continuation page, so - only after every rung
    # above, at every grid and readable size - the page keeps each TAF's
    # largest whole-group prefix and defers its trailing groups to the dashboard,
    # which always prints the whole record, one group at a time from whichever
    # TAF prints more groups, and says so on the line (weather_page_taf_field).
    taf_group_counts = [len(page_one_taf_change_groups(record)[1]) for _, _, record in terminal_tafs]
    taf_deferrals: list[tuple[int, ...]] = []
    deferral = [0] * len(terminal_tafs)
    for _ in range(sum(taf_group_counts)):
        printed = [count - dropped for count, dropped in zip(taf_group_counts, deferral)]
        widest = max(range(len(printed)), key=lambda index: (printed[index], index))
        deferral[widest] += 1
        taf_deferrals.append(tuple(deferral))
    WEATHER_DEFER_LADDER = (*WEATHER_DEFER_LADDER, *({**WEATHER_DEFER_LADDER[-1], "taf": drops} for drops in taf_deferrals))

    def terminal_lines(drops: tuple[int, ...] | None) -> list[str]:
        if not drops:
            return terminal
        lines = list(terminal)
        for (at, icao, record), drop in zip(terminal_tafs, drops):
            lines[at] = f"{icao} TAF: {weather_page_taf_field(record, drop)}"
        return lines
    full_sigmet = sigmet_lines(flight, view)
    full_edto = edto_window_lines(flight, view)

    def deferred(lines, keep, unit):
        if keep is None or len(lines) <= keep:
            return list(lines)
        return [*lines[:keep], f"+{len(lines) - keep} further {unit} on the dashboard."]

    def weather_cards(step: int) -> dict:
        keep = WEATHER_DEFER_LADDER[step]
        key_lines = list(hazard_lines)
        printed_terminal = terminal_lines(keep.get("taf"))
        return {
            "terminal": lambda gap, weight: Card("TERMINAL WEATHER", printed_terminal, CYAN, tag="CFP WX",
                                                 width_weight=weight, paragraph_gap=gap),
            "sigmet": lambda gap, weight: Card("SIGMET", deferred(full_sigmet, keep["sigmet"], "SIGMET row(s)"), AMBER,
                                               width_weight=weight, paragraph_gap=gap),
            "cyclone": lambda gap, weight: Card("TROPICAL CYCLONE", tc_lines
                                                or ["No governed route-specific cyclone consequence was established from the held sources."],
                                                AMBER, width_weight=weight, paragraph_gap=gap),
            "ash": lambda gap, weight: Card("VOLCANIC ASH", volcanic_ash_lines(flight, view, keep["ash"]), AMBER,
                                            width_weight=weight, paragraph_gap=gap),
            "key": lambda gap, weight: Card("FLIGHT HAZARD KEY", key_lines, VIOLET,
                                            width_weight=weight, paragraph_gap=gap),
            "clocks": lambda gap, weight: Card("ROUTE / EDTO CLOCKS", deferred(route_clocks, keep["clocks"], "route / EDTO clock row(s)")
                                               or [text(identity.get("rules")), "No EDTO or additional planning ETP is held."],
                                               CYAN, width_weight=weight, paragraph_gap=gap),
            "edto": lambda gap, weight: Card("EDTO AIRPORT WINDOWS", deferred(full_edto, keep["edto"], "EDTO airport window(s)"),
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

    def weather_rows(body, leading, variant=0, step=0):
        *grid, gap = weather_grids[variant]
        return grid_rows(weather_cards(step), grid, gap)
    sections["weather"] = plan_page_flexible(
        "WEATHER / ROUTE HAZARDS", "sec_hazard", weather_rows, ribbon_index=4,
        aliases=("sec_hazards", "sec_weather"), variants=tuple(range(len(weather_grids))),
        steps=range(len(WEATHER_DEFER_LADDER)),
        balance_columns=True,
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
    # 24 Sep 2026 (ATC-FIR-BOBCAT-416): David's FIR / COMMUNICATION column
    # returns to this page, which long-haul flights already filled (SQ366:
    # 420 of 432 pt). Every source fact stays; the room comes from printing
    # the VWS event sentences and the terrain event sentences verbatim but
    # packed into one paragraph each, and from dropping the two generic
    # interpretation sentences (not flight facts; one was an instruction).
    enroute_lines = [vws_summary]
    if vws_events:
        enroute_lines.append(" ".join(vws_events))
    enroute_lines.append(" ".join(terrain_lines) if terrain_lines else text(terrain.get("summary")))
    enroute_lines.append(terrain_summary)
    # Codex QA of release 468: SQ023's restored 5350N VWS 005 event took the line that held its Karachi call row
    # (SX33/26). The ladder's last content step before a FIR row is deferred prints the same VWS events packed - every
    # event's ACTM span and maximum, without the repeated words - never fewer events.
    packed = [re.fullmatch(r"ACTM (\S+), maximum (\d{3})\.", text(f.get("summary"))) for f in findings if f.get("engine") == "vws"]
    enroute_lines_packed = list(enroute_lines)
    if vws_events and all(packed):
        enroute_lines_packed[1] = "VWS events (ACTM, maximum): " + "; ".join(f"{m.group(1)} {m.group(2)}" for m in packed) + "."
    # The WAFS/SIGWX and AIREP/PIREP corroboration states print in the WEATHER
    # COVERAGE conditions on this page; the card no longer repeats them.
    interpretation: list[str] = []
    checks = {row["key"]: row for row in receipt["rows"]}
    # David, 24 Sep 2026 06:51: "I asked you to make sure the AI goes thru the
    # checklist of items it must perform for each flight. That list has
    # disappeared?" The card printed four of the checklist's rows since the
    # 9 Sep cleanup. It prints every row now, grouped by what the check found,
    # in plain words; each row's detail stays on the dashboard and on the page
    # that owns it, and the unresolved ones are numbered in the conditions.

    from .governed_deferred_extract import governed_deferred_extracts
    extracts = governed_deferred_extracts(view.get("deferred_source_items"), references)
    conditions = release_condition_groups(flight, view, receipt, airport_analysis, alternate_analysis, extracts)
    source_lines = [f"OFP {text(identity.get('ofp'))} · {text(view.get('flight_number'))} · {text(view.get('flight_date'))}",
                    f"Generated {text(view.get('generated_at_display'))}."]
    source_lines.append(source_assurance_line(view.get("source_assurance") or []))
    source_lines.append("Source checks and full NOTAMs: app / Show full NOTAM.")
    # A capacity step of this page (VOLCANIC-CHECK-436): the source line now
    # names every live volcanic source with its state, so a full page (a saved
    # SQ366 pack held by an older extraction) keeps the identity and the source
    # line, one line each, and leaves the app pointer, before a FIR row goes.
    source_lines_compact = [f"OFP {text(identity.get('ofp'))} · {text(view.get('flight_number'))} · {text(view.get('flight_date'))}"
                            f" · generated {text(view.get('generated_at_display'))}.", source_lines[2]]
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
    # R2 (David, 22 Sep 2026): the general statement is printed once, on page
    # 1; the closing card states the publication state and nothing generic.
    release_state = [publication_state]

    # FIR / COMMUNICATION - David's own page-6 column (his SQ910 reference:
    # "+00:02  WIIF entry. CPDLC limited trial: pilot initiates AFN logon only
    # when requested by ATC; address WIIF.", provenance "FPL p12 / NOTAM p32").
    # Dropped by the 9 Sep cleanup; restored 24 Sep 2026 (ATC-FIR-BOBCAT-416)
    # from the one composed record the dashboard prints (enroute_contact.py):
    # the early-call state, each source-held procedure in his row format, the
    # BOBCAT allocation with its CTOT + ACTM reconciliation (an engineering
    # placement in his column - the boss did not name the PDF), and the FIR
    # crossing ACTM line in his 27 Jul format. Nothing inferred.
    enroute_contact = view.get("enroute_contact") or compose_enroute_contact(flight, findings)
    fir_state = text(enroute_contact.get("state_sentence"))
    fir_calls = [f"+{call['actm']} {call['title']}. {call['summary']}" for call in enroute_contact.get("required_calls") or []]
    all_procedure_lines = list(enroute_contact.get("procedure_lines") or [])
    # ATC-EARLY-CALLS (25 Oct 2026, David on SQ301: "the early ATC call content is missing still"). Every early call
    # with a call time derived from the OFP entry ACTM and its printed lead prints at every step of this card, first and
    # in the order it falls due; generic communications notices (CPDLC not available, limited radio coverage, ATS not
    # provided) take whatever room is left and defer to the dashboard first. An early call with no derivable time stays
    # among the other rows and is named by identity whenever it defers. A record held before the composition listed
    # early calls has none here, so its page prints exactly as it did.
    timed_calls = [call for call in enroute_contact.get("early_calls") or [] if call.get("call_window")]

    def call_line(call):
        return next((line for line in all_procedure_lines if line["fir"] == call["fir"] and line["notam_ids"] == call["notam_ids"]
                     and line["text"] == call["text"]), None)

    early_lines = [call_line(call) for call in timed_calls]
    if any(line is None for line in early_lines):
        raise ValueError("FIR / COMMUNICATION early call does not resolve to its composed row")
    procedure_lines = [line for line in all_procedure_lines if not any(line is early for early in early_lines)]
    untimed_calls = {(call["fir"], tuple(call["notam_ids"])): call for call in enroute_contact.get("early_calls") or []
                     if not call.get("call_window")}

    def compact_summary(line, limit: int = 72) -> str:
        return compact_conditions_summary(line.get("conditions_summary"), limit)

    def fir_row(line, compact: bool = False, limit: int = 72) -> str:
        # ATC-RADIO-SOURCE-418 (24 Sep 2026): the row prints the notice's own
        # instruction sentence, the values it prints (frequency, lead,
        # interval, the next FIR, the latest ACTM a printed lead gives) and
        # the result of each printed condition against this OFP - never a
        # blanket "not held" over a source that holds them. Rule v3 (the 420
        # review): the further action sentences of the notice are counted
        # here and printed on the dashboard; at the ladder's later steps the
        # quoted condition clauses are cut to a prefix, the dashboard holds
        # them whole.
        pages = ", ".join(f"p{page}" for page in line["source_pages"]) or "page not held"
        head = f"+{line['actm']} {line['fir']} entry." if line["actm"] else f"{line['fir'] or 'FIR not derived'} (source held; route/time unresolved)."
        values = printed_values(line)
        if compact:
            # Quote source values once. Derived deadlines/next-boundary
            # values still print; a repeated frequency/lead adds no evidence.
            values = [value for value in values if value not in line["text"]]
        printed = f" Printed: {' · '.join(values)}." if values else ""
        further = line.get("further_actions") or 0
        more = (f" +{further} more on the dashboard." if compact else
                f" +{further} further source statement(s) of this notice on the dashboard.") if further else ""
        source_summary = line["conditions_summary"]
        if compact and not line.get("actm") and line.get("fir") and line.get("instruction_effect") == "availability":
            # The compact head states the source FIR and unresolved route/time.
            # Do not repeat the same association clause in the conditions.
            source_summary = " · ".join(part for part in source_summary.split(" · ") if not re.fullmatch(
                r"source FIR [A-Z]{4}(?:/[A-Z]{4})*; route association and crossing time unresolved", part))
        summary = compact_conditions_summary(source_summary, limit) if compact else source_summary
        if compact and line.get("instruction_effect") == "availability":
            # The source sentence already carries the status/frequency. Keep
            # it once, retain the whole validity clause and final condition
            # state, and count the other clauses using the existing ladder.
            head = f"+{line['actm']} {line['fir']}." if line["actm"] else f"Source FIR {line['fir']}; route/time unresolved." if line.get("fir") else "FIR association/time unresolved."
            summary = summary.replace("Communications availability · ", "").replace("ATC service availability · ", "").replace("validity ", "valid ")
            summary = summary.replace(": not evaluable (at no FIR crossing time held)", " (time unresolved)")
            return f"{head} {line['text']} NOTAM {', '.join(line['notam_ids'])}, OFP {pages}; {summary}.{more}"
        return (f"{head} {line['text']}{printed} "
                f"NOTAM {', '.join(line['notam_ids'])}, OFP {pages}; {summary}.{more}")

    def early_row(call, line, compact: bool = False, limit: int = 72, quote: bool = True, tight: bool = False) -> str:
        # The early-call sentence (when, what, to whom, on what, the printed lead, the entry), then - while the page
        # holds it - the notice's own instruction verbatim, its identity, page and every printed condition's outcome.
        pages = ", ".join(f"p{page}" for page in line["source_pages"]) or "page not held"
        summary = compact_conditions_summary(line["conditions_summary"], limit) if compact else line["conditions_summary"]
        if tight:
            # The validity window, its outcome and its timing basis stay whole; the counted clauses and the state read as one.
            summary = re.sub(r"^validity ", "valid ", summary)
            summary = re.sub(r"\+(\d+) further condition\(s\) on the dashboard · (conditions held|conditions unresolved|not applicable)$",
                             r"\2 (+\1 on the dashboard)", summary)
        further = line.get("further_actions") or 0
        more = (f" +{further} more on the dashboard." if compact else
                f" +{further} further source statement(s) of this notice on the dashboard.") if further else ""
        quoted = f" {line['text']}" if quote else ""
        return (f"{early_call_sentence(call, compact=tight)}{quoted} NOTAM {', '.join(line['notam_ids'])}, OFP {pages}; "
                f"{summary}.{more}")

    def untimed_call_pointers(lines) -> list[str]:
        return [untimed_call_pointer(untimed_calls[(line.get("fir") or "", tuple(line["notam_ids"]))])
                for line in lines if (line.get("fir") or "", tuple(line["notam_ids"])) in untimed_calls]

    def identities(lines, compact: bool = False) -> str:
        # An early call whose time is not derived is named by identity, never only counted (ATC-EARLY-CALLS).
        named = untimed_call_pointers(lines)
        lines = [line for line in lines if (line.get("fir") or "", tuple(line["notam_ids"])) not in untimed_calls]
        grouped: dict[str, list[str]] = {}
        for line in lines:
            grouped.setdefault(line["fir"] or "FIR not derived", []).extend(line["notam_ids"])
        if compact:
            return "; ".join([*named, ", ".join(f"{fir} {len(ids)}" for fir, ids in grouped.items())] if grouped else named)
        return "; ".join([*named, *(f"{fir} {', '.join(ids)}" for fir, ids in grouped.items())])

    # The card defers whole rows only, and says so: every step keeps the
    # state, the BOBCAT sentence, the primary row (the first call row with
    # printed values - the row parity binds on both surfaces) and at least
    # eight crossing pairs; every row is always on the dashboard.
    # Try all rows, then calls, then one valued crew call per FIR. Before
    # primary-only, try those valued calls with untimed statuses and then
    # the primary plus the next qualifying valued call at another FIR.
    # Each row budget tries whole clauses, source prefixes, then counted
    # clause deferral; the dashboard carries every clause in full. Validity,
    # timing basis and final state always print (release-432 QA, O2).
    #   step: (rows, crossing pairs, clause prefix or None for whole clauses)
    FIR_STEPS = (
        ("all", 24, None), ("all", 12, None), ("calls", 8, None), ("valued_per_fir", 8, None),
        ("valued_per_fir", 8, 72), ("valued_per_fir", 8, 44), ("valued_per_fir", 8, 24), ("valued_per_fir", 8, 0),
        # Before dropping valued crew contacts, try deferring timed service
        # rows, then whole untimed statuses with their own ID/page pointers.
        ("valued_per_fir_untimed", 8, 72), ("valued_per_fir_untimed", 8, 44),
        ("valued_per_fir_untimed", 8, 24), ("valued_per_fir_untimed", 8, 0),
        ("valued_per_fir_source_status", 8, 72), ("valued_per_fir_source_status", 8, 44),
        ("valued_per_fir_source_status", 8, 24), ("valued_per_fir_source_status", 8, 0),
        # If one valued row per FIR still exceeds the fixed page, retain the
        # mandatory primary plus the next valued crew contact at another FIR
        # in the existing action-time order before trying primary-only.
        ("primary_plus_source_status", 8, 72), ("primary_plus_source_status", 8, 44),
        ("primary_plus_source_status", 8, 24), ("primary_plus_source_status", 8, 0),
        ("primary", 8, None), ("primary", 8, 72), ("primary", 8, 44), ("primary", 8, 24), ("primary", 8, 0),
        # Only after all availability rows have been tried at every existing
        # readable layout: whole timed rows may defer to the dashboard. An
        # untimed FIR status still prints; a missing boundary must not erase
        # departure/near-departure service evidence.
        ("primary_untimed", 8, 72), ("primary_untimed", 8, 24), ("primary_untimed", 8, 0),
        # Multiple distinct untimed statuses can also exceed six pages. Only
        # after every whole-quotation step: retain the first printed status
        # and identify each deferred untimed notice by FIR/ID/source page.
        ("primary_source_status", 8, 24), ("primary_source_status", 8, 0),
        # ATC-EARLY-CALLS: the early calls (or, with none, the primary row) alone, every other row named or counted;
        # last, the early calls without the verbatim instruction (each keeps its time, unit, frequencies, lead, entry,
        # identity, page and state - the dashboard row quotes it).
        ("early_only", 8, 24), ("early_only", 8, 0), ("early_unquoted", 8, 0),
        # Only if the page still cannot hold every early call in that form: the last ones in time order are named by
        # their call time, FIR, identity and page on one line (the dashboard holds them whole) - never dropped unnamed.
        *((f"early_named_{kept}", 8, 0) for kept in range(len(timed_calls) - 1, -1, -1)),
    )
    EARLY_STEPS = ("early_only", "early_unquoted", *(f"early_named_{kept}" for kept in range(len(timed_calls))))

    def fir_card(gap, weight, step=0):
        # With early calls held, they are the rows every step prints; the primary-row duty is theirs.
        primary = None if timed_calls else primary_procedure_line(procedure_lines)
        rows_kind, pairs, clause_limit = FIR_STEPS[step]
        compact = clause_limit is not None
        if rows_kind in EARLY_STEPS and not timed_calls:
            rows_kind = "primary"
        if rows_kind == "all":
            shown = list(procedure_lines)
        elif rows_kind == "calls":
            shown = [line for line in procedure_lines if line is primary or is_call_line(line)]
        elif rows_kind.startswith("valued_per_fir"):
            # One valued crew call per FIR, the FIR's held one first (ATC-PDF-PRIORITY).
            valued = [line for line in procedure_lines if is_call_line(line) and has_printed_values(line)]
            chosen: dict[str, dict] = {}
            for line in valued:
                current = chosen.get(line["fir"])
                if current is None or (current.get("applicability_state") != "conditions_held"
                                       and line.get("applicability_state") == "conditions_held"):
                    chosen[line["fir"]] = line
            shown = [line for line in procedure_lines if line is primary or
                     (any(line is pick for pick in chosen.values()) and not (primary and line["fir"] == primary["fir"]))]
        elif rows_kind == "primary_plus_source_status":
            shown = _primary_and_next_valued_call(procedure_lines, primary)
        elif rows_kind in EARLY_STEPS:
            shown = []
        else:
            shown = [primary] if primary else []
        # Service status matters independently of a crew call. Try all full
        # availability quotations at the existing layout steps. Only the
        # untimed steps may defer timed rows; source-status steps identify
        # each deferred untimed row as well. No held row changes.
        if rows_kind.endswith("source_status"):
            shown = [line for line in procedure_lines if line in shown or line in _first_untimed_status_lines(procedure_lines)]
        elif rows_kind in EARLY_STEPS:
            pass
        else:
            shown = [line for line in procedure_lines if line in shown or
                     (line.get("instruction_effect") == "availability" and (not rows_kind.endswith("untimed") or not line.get("actm")))]
        deferred = [line for line in procedure_lines if line not in shown]
        rendered_shown = _compact_untimed_availability_lines(shown) if compact else shown
        state_line = fir_state
        if compact and enroute_contact.get("procedures") and not fir_calls:
            state_line = enroute_contact.get("compact_state_sentence")
            if not state_line:
                # A record held before the composition carried its compact sentence: the sentence that page printed.
                counts = {state: sum(row["applicability_state"] == state for row in enroute_contact["procedures"])
                          for state in ("conditions_held", "conditions_unresolved", "not_applicable")}
                state_line = (f"No approved early-call rule held. {len(enroute_contact['procedures'])} source-held ATC/communications notices: "
                              f"{counts['conditions_held']} conditions met, {counts['conditions_unresolved']} unresolved, "
                              f"{counts['not_applicable']} not applicable.")
                if not (enroute_contact.get("extraction") or {}).get("current"):
                    state_line += " Held extraction predates the current parser; update re-reads the OFP."
        limit = 72 if clause_limit is None else clause_limit
        tight = rows_kind == "early_unquoted" or rows_kind.startswith("early_named_")
        kept_calls = int(rows_kind.rsplit("_", 1)[1]) if rows_kind.startswith("early_named_") else len(timed_calls)
        named_calls = [named_early_call(call) for call in timed_calls[kept_calls:]]
        # At the tight steps the slot sentence closes the state paragraph instead of taking a line of its own.
        slot_line = text(enroute_contact.get("slot_sentence"))
        lines = [state_line + (f" {slot_line}" if tight else ""), *fir_calls,
                 *(early_row(call, line, compact, limit, quote=not tight, tight=tight)
                   for call, line in list(zip(timed_calls, early_lines))[:kept_calls]),
                 *([f"Further early calls, whole on the dashboard: {'; '.join(named_calls)}."] if named_calls else []),
                 *(fir_row(line, compact, limit) for line in rendered_shown)]
        if deferred:
            if rows_kind.endswith("source_status") or rows_kind in EARLY_STEPS:
                # Every deferred untimed service status keeps its FIR, identity and page; an early call without a
                # derived time is named; other rows are counted by FIR.
                untimed = [line for line in deferred if not line.get("actm") and line.get("instruction_effect") == "availability"]
                others = [line for line in deferred if line not in untimed]
                pointers = "; ".join(f"{line['fir'] or 'FIR unresolved'} {','.join(line['notam_ids'])} ({','.join(f'p{p}' for p in line['source_pages']) or 'page not held'})" for line in untimed)
                details = "; ".join(part for part in (pointers, identities(others, True)) if part)
                lines.append(f"+{len(deferred)} further rows on the dashboard ({details}).")
            else:
                lines.append(f"Further rows on the dashboard: {identities(deferred, compact)}." if not compact
                             else f"+{len(deferred)} further rows on the dashboard ({identities(deferred, compact)}).")
        if not tight:
            lines.append(slot_line)
        crossing_line = crossing_sequence_limited(enroute_contact.get("crossings") or [], pairs, compact)
        lines.append("FIR crossings (OFP ACTM): " + (crossing_line or "no boundary row held."))
        return Card("FIR / COMMUNICATION", lines, CYAN, "sec_enroute", width_weight=weight, paragraph_gap=gap,
                    tag=text(enroute_contact.get("provenance")))

    # Enroute review, the airport/weather conditions and the closing record all
    # share one page. Whichever block a flight has loaded gets the wide column
    # first; type size steps down only after that, and no condition is dropped.
    closing_cards = {
        "fir": fir_card,
        "enroute": lambda gap, weight, packed=False: Card("OFP VWS, CAT AND TERRAIN",
                                                          (enroute_lines_packed if packed else enroute_lines) + interpretation,
                                                          AMBER, "sec_terrain", width_weight=weight, paragraph_gap=gap),
        "review": lambda gap, weight, mode="whole": Card(
            "SOURCE / CALCULATION REVIEW", checklist_lines(receipt["rows"], mode), CYAN,
            width_weight=weight, paragraph_gap=gap),
        "airports": lambda gap, weight: Card("AIRPORT ASSESSMENTS", conditions["operations"]
                                             or ["No unresolved airport assessment is recorded."],
                                             AMBER, width_weight=weight, paragraph_gap=gap),
        "weather": lambda gap, weight: Card("WEATHER COVERAGE", conditions["weather"]
                                            or ["No unresolved weather-source condition is recorded."],
                                            AMBER, width_weight=weight, paragraph_gap=gap),
        "control": lambda gap, weight, compact=False: Card("SOURCE CONTROL", source_lines_compact if compact else source_lines, CYAN,
                                                           width_weight=weight, paragraph_gap=gap),
        "remaining": lambda gap, weight: Card("REMAINING RELEASE INPUTS", conditions["technical"]
                                              or ["No unresolved aircraft/route source condition is recorded."],
                                              AMBER, width_weight=weight, paragraph_gap=gap),
        "state": lambda gap, weight: Card("PUBLICATION STATE", release_state, CYAN,
                                          width_weight=weight, paragraph_gap=gap),
    }
    closing_grids = (
        ((("enroute", 1.9), ("review", 1.0)), (("fir", 1.0),), (("airports", 1.9), ("weather", 1.0)),
         (("control", 1.2), ("remaining", 1.0), ("state", 0.9)), 2.0),
        ((("enroute", 1.0),), (("fir", 1.0),), (("airports", 1.9), ("weather", 1.0)),
         (("review", 1.0), ("control", 1.2), ("remaining", 1.0), ("state", 0.9)), 2.0),
        ((("enroute", 1.6), ("review", 0.7), ("state", 0.7)), (("fir", 1.0),), (("airports", 1.9), ("weather", 1.0)),
         (("control", 1.2), ("remaining", 1.0)), 2.0),
        ((("enroute", 1.9), ("review", 1.0)), (("fir", 1.0),), (("airports", 1.0), ("weather", 1.0), ("state", 0.8)),
         (("control", 1.0), ("remaining", 1.6)), 2.0),
        ((("enroute", 1.6), ("review", 0.7), ("state", 0.7)), (("fir", 1.0),), (("airports", 1.9), ("weather", 1.0)),
         (("control", 1.2), ("remaining", 1.0)), 0.0),
        ((("enroute", 1.9), ("review", 1.0)), (("fir", 1.0),), (("airports", 1.0), ("weather", 1.0), ("control", 1.0)),
         (("remaining", 2.2), ("state", 1.0)), 0.0),
    )

    # One content ladder for the page: at every FIR / COMMUNICATION step the
    # checklist is tried whole, then with the open items only, then as counts,
    # before the next FIR row is deferred - David's FIR column keeps priority.
    # The source card's compact form (identity and generation time on one line,
    # the app pointer left out) is the last content given up before the next
    # FIR row is deferred.
    ASSURANCE_STEPS = tuple((fir_step, mode, compact, packed) for fir_step in range(len(FIR_STEPS))
                            for mode, compact, packed in ((CHECKLIST_MODES[0], False, False), (CHECKLIST_MODES[1], False, False),
                                                          (CHECKLIST_MODES[2], False, False), (CHECKLIST_MODES[2], True, False),
                                                          (CHECKLIST_MODES[2], True, True)))

    def assurance_rows(body, leading, variant=0, step=0):
        *grid, gap = closing_grids[variant]
        fir_step, mode, control_compact, vws_packed = ASSURANCE_STEPS[step]
        rows = []
        for row in grid:
            built = []
            for key, weight in row:
                if key == "fir":
                    built.append(closing_cards[key](gap, weight, fir_step))
                elif key == "review":
                    built.append(closing_cards[key](gap, weight, mode))
                elif key == "control":
                    built.append(closing_cards[key](gap, weight, control_compact))
                elif key == "enroute":
                    built.append(closing_cards[key](gap, weight, vws_packed))
                else:
                    built.append(closing_cards[key](gap, weight))
            rows.append((None, built))
        return rows
    sections["assurance"] = plan_page_flexible(
        "ENROUTE / INTAM / ASSURANCE", "sec_coverage", assurance_rows, ribbon_index=5,
        aliases=("sec_enroute", "sec_terrain", "sec_intam"),
        variants=tuple(range(len(closing_grids))), steps=range(len(ASSURANCE_STEPS)),
        assurance="TWO-PASS REVIEW TARGET | SOURCE TRACEABILITY | COMMAND AUTHORITY UNCHANGED")
    return sections


def render_analysed_briefing(flight, findings, warnings, path, *, weather_charts=None, company_briefing_references=None) -> None:
    from pathlib import Path
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
    canvas = PrintableCanvas(str(target), pagesize=SIZE)
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

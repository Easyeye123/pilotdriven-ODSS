"""Conformance of the published download to David's own reference briefings.

9 Sep 2026, 21:22:46 - 21:22:52::

    "So you have to check and make sure the memory losses and standard
    established does not degenerate."
    "How do you ensure that???"

The answer that existed on 15 Sep 2026 was the REV3 raster gate. That gate
replays ``include_audit_appendix=True`` - the internal lossless composition no
production download ever calls - for one flight, against a reference minted
from *our own* render. It cannot notice the publication drifting away from his
format, because his format is not one of its inputs.

This module makes his file the input. ``extract_reference_structure`` reads the
structure out of the reference PDFs he sent on 9 Sep 2026 and
``check_reference_conformance`` reads the same structure back out of a candidate
briefing rendered through the production Download PDF path. Every assertion the
checker makes is a value that was lifted from his document, not typed in from
ours; the few structural floors that cannot be lifted from a single file are
declared separately as ``contract_extensions`` so they can never be mistaken for
his ruling.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
import re
from typing import Any, Iterable, Sequence

import fitz

from .concise_pdf_gate import normalized


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MANIFEST = ROOT / "tests" / "boss_reference_format_manifest.json"
MANIFEST_GATE = "boss-reference-format-conformance"
MANIFEST_SCHEMA_VERSION = 1

PAGE_MARKER_RE = re.compile(r"FLIGHT\s+BRIEFING\s*\|\s*PAGE\s+(\d+)\s+OF\s+(\d+)", re.I)
FOOTER_PAGE_RE = re.compile(r"^PAGE\s+(\d+)\s+OF\s+(\d+)$", re.I)
TIME_TOKEN_RE = re.compile(r"\b\d{4}Z\b|\b\d{2}[:.]\d{2}\b|\bFL\d{3}\b")
SEPARATORS = {"", "·", "|", "-", "–", "—", "•", "/"}

# Row grouping tolerance in points. Reference and candidate both draw a row's
# labels and their provenance tags a couple of points apart.
ROW_TOLERANCE = 3.0
# A tile heading sits on the same visual line as its provenance tag; a tile's
# first data label is the next line down. Both renders keep the heading inside
# this window and the first data label outside it.
TILE_HEADING_WINDOW = (-8.0, 6.0)


class ReferenceConformanceError(ValueError):
    """The reference structure or the candidate cannot be read."""


@dataclass(frozen=True)
class Span:
    text: str
    x0: float
    y0: float
    x1: float
    y1: float
    size: float
    bold: bool

    @property
    def folded(self) -> str:
        return normalized(self.text)

    @property
    def centre(self) -> float:
        return (self.x0 + self.x1) / 2


def page_spans(page) -> list[Span]:
    out: list[Span] = []
    for block in page.get_text("dict")["blocks"]:
        for line in block.get("lines", []):
            for span in line["spans"]:
                text = span["text"].strip()
                if not text:
                    continue
                x0, y0, x1, y1 = span["bbox"]
                out.append(
                    Span(
                        text=text,
                        x0=float(x0),
                        y0=float(y0),
                        x1=float(x1),
                        y1=float(y1),
                        size=float(span["size"]),
                        bold="bold" in str(span.get("font", "")).lower(),
                    )
                )
    out.sort(key=lambda span: (round(span.y0, 1), span.x0))
    return out


def rows(spans: Iterable[Span], tolerance: float = ROW_TOLERANCE) -> list[list[Span]]:
    grouped: list[list[Span]] = []
    for span in sorted(spans, key=lambda item: (item.y0, item.x0)):
        if grouped and abs(span.y0 - grouped[-1][0].y0) <= tolerance:
            grouped[-1].append(span)
        else:
            grouped.append([span])
    for row in grouped:
        row.sort(key=lambda item: item.x0)
    return grouped


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _head_word(label: str) -> str:
    folded = normalized(label)
    return folded.split(" ")[0] if folded else ""


def _is_word_label(text: str) -> str | bool:
    """A section or field label: capitals and separators, never a data value."""
    stripped = " ".join(str(text).split())
    return bool(stripped) and stripped == stripped.upper() and not re.search(r"\d", stripped)


def _is_label_strip(row: Sequence[Span], cells: int, width: float) -> bool:
    """The page-1 release strip: one word label per cell, across the page.

    Every other five-cell row on page 1 carries a source value, so it holds a
    digit; and the tile rows never reach across the page the way the strip does.
    """
    bold = [span for span in row if span.bold]
    if len(bold) != cells or not all(_is_word_label(span.text) for span in bold):
        return False
    return (bold[-1].x1 - bold[0].x0) >= 0.6 * width


def _clusters(values: Sequence[float], tolerance: float) -> list[list[float]]:
    out: list[list[float]] = []
    for value in sorted(values):
        if out and value - out[-1][-1] <= tolerance:
            out[-1].append(value)
        else:
            out.append([value])
    return out


# ---------------------------------------------------------------------------
# Extraction - reads David's reference briefing
# ---------------------------------------------------------------------------


def _ribbon_row(spans: Sequence[Span], height: float) -> list[Span] | None:
    """The navigation ribbon row: the strip of section names under the masthead."""
    for row in rows(spans):
        if not (0.07 * height < row[0].y0 < 0.22 * height):
            continue
        items = [
            span
            for span in row
            if span.text.strip() not in SEPARATORS
            and not PAGE_MARKER_RE.search(span.text)
        ]
        if len(items) < 5:
            continue
        if any(item.folded != normalized(item.text) or item.text != item.text.upper() for item in items):
            continue
        return items
    return None


def _page_marker(page) -> tuple[int, int] | None:
    match = PAGE_MARKER_RE.search(" ".join(page.get_text().split()))
    return (int(match.group(1)), int(match.group(2))) if match else None


def _masthead_banner(spans: Sequence[Span], width: float, height: float) -> str | None:
    """The section name printed in the masthead of a continuation page."""
    candidates = [
        span
        for span in spans
        if span.y0 < 0.10 * height
        and span.x0 > 0.75 * width
        and not PAGE_MARKER_RE.search(span.text)
        and span.text == span.text.upper()
        and re.search(r"[A-Z]", span.text)
    ]
    return candidates[0].text.strip() if len(candidates) == 1 else None


def _body_heading(spans: Sequence[Span], width: float, height: float) -> str | None:
    band = [
        span
        for span in spans
        if 0.10 * height < span.y0 < 0.20 * height and span.x0 < 0.15 * width
    ]
    if not band:
        return None
    largest = max(band, key=lambda span: span.size)
    return largest.text.strip()


def _footer_parts(spans: Sequence[Span], height: float) -> tuple[Span | None, Span | None, Span | None]:
    """Identity, assurance and page label from the footer band.

    The band, not a row: in his large-text render the centre assurance line no
    longer fits beside the identity and drops onto its own line. A footer check
    that only ever reads one row would call that a missing footer.
    """
    band = [span for span in spans if span.y0 > height - 45]
    page = next(
        (span for span in band if FOOTER_PAGE_RE.match(" ".join(span.text.split()))),
        None,
    )
    identity = next(
        (span for span in band if re.search(r"OFP\s+\d+/\d+/\d+", span.text)), None
    )
    assurance = next(
        (
            span
            for span in band
            if span is not page
            and span is not identity
            and "|" in span.text
            and span.text == span.text.upper()
        ),
        None,
    )
    return identity, assurance, page


def _extract_overview(page, spans: Sequence[Span], width: float) -> dict[str, Any]:
    header_rows = [
        row
        for row in rows(spans)
        if len([span for span in row if span.bold]) == 3
        and normalized(row[0].text).startswith("DEPARTURE")
    ]
    if not header_rows:
        raise ReferenceConformanceError("Reference page 1 has no DEPARTURE / ROUTE / DESTINATION header row")
    header = [span for span in header_rows[0] if span.bold]
    departure, route_panel, destination = header

    # The provenance tag is the one page-1 label that is type scale, not format:
    # his large-text render abbreviates "CFP P1" to "P1" to keep the tile width.
    tag_text = ""
    tag_row: list[Span] = []
    for candidate_tag in ("CFP P1", "P1"):
        for row in rows(spans):
            tagged = [span for span in row if span.folded == candidate_tag]
            if len(tagged) >= 5:
                tag_text, tag_row = candidate_tag, tagged
                break
        if tag_row:
            break
    if not tag_row:
        raise ReferenceConformanceError("Reference page 1 has no provenance-tagged tile row")
    tile_top = tag_row[0].y0 + TILE_HEADING_WINDOW[0]
    tile_bottom = tag_row[0].y0 + TILE_HEADING_WINDOW[1]
    headings = [
        span
        for span in spans
        if tile_top <= span.y0 <= tile_bottom and span.folded != tag_text and span.bold
    ]
    headings.sort(key=lambda span: span.x0)
    if len(headings) != len(tag_row):
        raise ReferenceConformanceError(
            f"Reference page 1 has {len(headings)} tile headings for {len(tag_row)} provenance tags"
        )
    tiles: list[str] = []
    for index, heading in enumerate(headings):
        right = tag_row[index].x0
        continuation = [
            span
            for span in spans
            if abs(span.x0 - heading.x0) <= 1.5
            and heading.y0 < span.y0 <= heading.y0 + 16
            and span.bold
            and span.x1 <= right + 1.5
        ]
        text = " ".join([heading.text.strip()] + [span.text.strip() for span in continuation])
        tiles.append(" ".join(text.split()))

    strip_rows = [
        row
        for row in rows(spans)
        if row[0].y0 > tag_row[0].y0 + 20 and _is_label_strip(row, len(tag_row), width)
    ]
    if not strip_rows:
        raise ReferenceConformanceError("Reference page 1 has no release / before push / route strip")
    strip = [span.text.strip() for span in strip_rows[0] if span.bold]

    def column_fields(anchor: float) -> list[str]:
        band = [
            span
            for span in spans
            if abs(span.x0 - anchor) <= 2.0
            and header[0].y0 < span.y0 < tile_top
            and span.bold
            and _is_word_label(span.text)
        ]
        band.sort(key=lambda span: span.y0)
        if not band:
            return []
        sizes = sorted(span.size for span in band)
        median = sizes[len(sizes) // 2]
        # The ICAO sits at the head of the column in display type. Field labels
        # share one size; anything markedly larger is the airport, not a field.
        return [
            " ".join(span.text.split())
            for span in band
            if span.size <= median * 1.3
        ]

    panel_left = departure.x1
    panel_right = destination.x0
    drawings = [
        drawing
        for drawing in page.get_drawings()
        if drawing["rect"].x0 >= panel_left - 10 and drawing["rect"].x1 <= panel_right + 10
    ]

    return {
        "columns": [departure.text.strip(), destination.text.strip()],
        "column_fields": {
            "departure": column_fields(departure.x0),
            "destination": column_fields(destination.x0),
        },
        "route_panel": " ".join(route_panel.text.split()),
        "tile_provenance_tag": tag_text,
        "tiles": tiles,
        "strip": strip,
        "route_panel_reference_drawing_count": len(drawings),
    }


def _extract_analysis(spans: Sequence[Span], width: float, destination: str) -> dict[str, Any]:
    pills = [
        span
        for span in spans
        if span.bold
        and re.fullmatch(r"[A-Z]{4,9}", span.text.strip())
        and span.text.strip() in {"MAJOR", "MODERATE", "MINOR", "INFO", "REVIEW"}
    ]
    if not pills:
        raise ReferenceConformanceError("Reference page 2 has no severity pills")
    columns = _clusters([pill.x0 for pill in pills], tolerance=0.1 * width)

    heading = next(
        (span for span in spans if "DECISION TIMELINE" in span.folded),
        None,
    )
    if heading is None:
        raise ReferenceConformanceError("Reference page 2 has no flight-phase decision timeline")
    below = [span for span in spans if span.y0 > heading.y0 + 4]
    stop_labels = [span for span in below if span.bold]
    if not stop_labels:
        raise ReferenceConformanceError("Reference timeline has no labelled stops")
    stop_rows = rows(stop_labels)
    # The first dot on his axis is the departure. Our engine can put an earlier
    # gate in front of it when the source holds one (a pre-departure expiry),
    # so what is pinned is that the departure dot is on the axis, not that
    # nothing may precede it - a gate that demanded that would push evidenced
    # content off the page.
    departure_stop = stop_rows[0][0].text.strip()
    terminal = max(stop_labels, key=lambda span: span.x0).text.strip()

    return {
        "severity_pill_vocabulary": sorted({pill.text.strip() for pill in pills}),
        "grid_columns": len(columns),
        "timeline_heading": " ".join(heading.text.split()),
        "timeline_departure_stop": departure_stop,
        "timeline_terminal_stop_is_destination": normalized(terminal) == normalized(destination),
        "timeline_reference_stop_count": len(stop_labels),
    }


def extract_reference_structure(path: Path) -> dict[str, Any]:
    """Read the publication structure out of one of David's reference PDFs."""
    path = Path(path)
    with fitz.open(path) as document:
        page_count = len(document)
        if page_count == 0:
            raise ReferenceConformanceError(f"{path.name} holds no pages")
        width = float(document[0].rect.width)
        height = float(document[0].rect.height)

        ribbon_pages: list[int] = []
        ribbon: list[str] = []
        active_by_page: dict[int, str] = {}
        pages: list[dict[str, Any]] = []
        footer_identity: str | None = None

        for index, page in enumerate(document):
            spans = page_spans(page)
            row = _ribbon_row(spans, height)
            if row is not None:
                items = [" ".join(span.text.split()) for span in row]
                if not ribbon:
                    ribbon = items
                elif items != ribbon:
                    raise ReferenceConformanceError(
                        f"{path.name} page {index + 1} ribbon differs from page 1"
                    )
                ribbon_pages.append(index + 1)
                emphasised = [span for span in row if span.bold]
                if len(emphasised) == 1:
                    active_by_page[index + 1] = " ".join(emphasised[0].text.split())

            marker = _page_marker(page)
            if marker is None:
                raise ReferenceConformanceError(
                    f"{path.name} page {index + 1} has no FLIGHT BRIEFING page marker"
                )
            if marker != (index + 1, page_count):
                raise ReferenceConformanceError(
                    f"{path.name} page {index + 1} marker reads {marker}"
                )

            titles: list[str] = []
            banner = _masthead_banner(spans, width, height)
            if banner:
                titles.append(" ".join(banner.split()))
                heading = _body_heading(spans, width, height)
                if heading:
                    titles.append(" ".join(heading.split()).upper())
            elif index + 1 in active_by_page:
                titles.append(active_by_page[index + 1])

            identity, assurance, page_label = _footer_parts(spans, height)
            if identity is None or assurance is None or page_label is None:
                raise ReferenceConformanceError(
                    f"{path.name} page {index + 1} has no identity / assurance / page footer"
                )
            if footer_identity is None:
                footer_identity = " ".join(identity.text.split())

            pages.append(
                {
                    "page_number": index + 1,
                    "titles": titles,
                    "footer_assurance_lead": " ".join(
                        assurance.text.split("|")[0].split()
                    ),
                }
            )

        if not ribbon:
            raise ReferenceConformanceError(f"{path.name} has no navigation ribbon")

        overview_page = document[0]
        overview = _extract_overview(overview_page, page_spans(overview_page), width)

        identity_fields = [part.strip() for part in (footer_identity or "").split("|")]
        route_field = next(
            (field for field in identity_fields if re.fullmatch(r"[A-Z]{4}-[A-Z]{4}", field)),
            None,
        )
        if route_field is None:
            raise ReferenceConformanceError(
                f"{path.name} footer identity has no <dep>-<dest> field"
            )
        destination = route_field.split("-")[1]

        analysis_spans = page_spans(document[1])
        analysis = _extract_analysis(analysis_spans, width, destination)

    return {
        "page_count": page_count,
        "page_size_points": [round(width, 3), round(height, 3)],
        "nav_ribbon": ribbon,
        "nav_ribbon_reference_pages": ribbon_pages,
        "page_marker_template": "FLIGHT BRIEFING | PAGE {page} OF {count}",
        "footer_identity_field_count": len(identity_fields),
        "footer_identity_tail_pattern": r"OFP \d+/\d+/\d+",
        "footer_page_template": "Page {page} of {count}",
        "pages": pages,
        "overview": overview,
        "analysis": analysis,
    }


def load_manifest(path: Path = DEFAULT_MANIFEST) -> dict[str, Any]:
    """Read and validate the pinned reference-structure manifest."""
    import json

    path = Path(path)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ReferenceConformanceError(f"Cannot read {path.name}: {exc}") from exc
    if payload.get("schema_version") != MANIFEST_SCHEMA_VERSION:
        raise ReferenceConformanceError(
            f"{path.name} schema_version must be {MANIFEST_SCHEMA_VERSION}"
        )
    if payload.get("gate") != MANIFEST_GATE:
        raise ReferenceConformanceError(f"{path.name} is not the {MANIFEST_GATE} manifest")
    structure = payload.get("reference_structure")
    if not isinstance(structure, dict) or not structure.get("pages"):
        raise ReferenceConformanceError(f"{path.name} holds no reference structure")
    if len(structure["pages"]) != int(structure["page_count"]):
        raise ReferenceConformanceError(
            f"{path.name} page_count disagrees with its own page list"
        )
    minted = payload.get("minted_from")
    if not isinstance(minted, list) or not minted:
        raise ReferenceConformanceError(
            f"{path.name} does not name the reference files it was minted from"
        )
    for entry in minted:
        digest = entry.get("sha256")
        if not isinstance(digest, str) or len(digest) != 64:
            raise ReferenceConformanceError(
                f"{path.name} has an invalid reference digest for {entry.get('filename')}"
            )
    return payload


# ---------------------------------------------------------------------------
# Checking - reads the production download back
# ---------------------------------------------------------------------------


def _violation(code: str, message: str) -> dict[str, str]:
    return {"code": code, "message": message}


def _ribbon_items(row: Sequence[Span]) -> list[Span]:
    return [
        span
        for span in row
        if span.text.strip() not in SEPARATORS and not PAGE_MARKER_RE.search(span.text)
    ]


def _find_ribbon(spans: Sequence[Span], height: float, expected: Sequence[str]) -> list[Span] | None:
    folded = [normalized(item) for item in expected]
    for row in rows(spans):
        if not (0.05 * height < row[0].y0 < 0.25 * height):
            continue
        items = _ribbon_items(row)
        if [span.folded for span in items] == folded:
            return items
    return None


def _check_overview(page, spans: Sequence[Span], structure: dict[str, Any],
                    extensions: dict[str, Any]) -> list[dict[str, str]]:
    overview = structure["overview"]
    folded_page = normalized(page.get_text())
    violations: list[dict[str, str]] = []

    tag_folded = normalized(overview["tile_provenance_tag"])
    header = None
    for row in rows(spans):
        # The provenance tags share this row; they are not column headings.
        bold = [span for span in row if span.bold and span.folded != tag_folded]
        texts = [span.folded for span in bold]
        if (
            len(bold) >= 3
            and texts[0] == normalized(overview["columns"][0])
            and texts[-1] == normalized(overview["columns"][1])
        ):
            header = bold
            break
    if header is None:
        violations.append(
            _violation(
                "OVERVIEW_COLUMNS",
                "Page 1 does not lead with the reference "
                f"{overview['columns'][0]} / route / {overview['columns'][1]} header row.",
            )
        )
        return violations

    departure, destination = header[0], header[-1]
    route_panel = [span for span in header[1:-1]
                   if span.folded == normalized(overview["route_panel"])]
    if not route_panel:
        violations.append(
            _violation(
                "OVERVIEW_ROUTE_PANEL",
                f"Page 1 centre panel is not the reference '{overview['route_panel']}'.",
            )
        )

    for role, anchor in (("departure", departure), ("destination", destination)):
        expected = overview["column_fields"][role]
        if not expected:
            continue
        found: list[tuple[float, str]] = []
        for label in expected:
            head = _head_word(label)
            hits = [
                span
                for span in spans
                if abs(span.x0 - anchor.x0) <= 2.5
                and span.y0 > anchor.y0
                and span.folded.split(" ")[:1] == [head]
            ]
            if hits:
                found.append((min(hit.y0 for hit in hits), head))
        if len(found) != len(expected):
            missing = sorted(
                {_head_word(label) for label in expected} - {head for _, head in found}
            )
            violations.append(
                _violation(
                    "OVERVIEW_COLUMN_FIELDS",
                    f"Page 1 {role} column is missing reference field(s) {', '.join(missing)}.",
                )
            )
        elif [head for _, head in sorted(found)] != [_head_word(label) for label in expected]:
            violations.append(
                _violation(
                    "OVERVIEW_COLUMN_FIELDS",
                    f"Page 1 {role} column prints the reference fields out of order.",
                )
            )

    # Both of his renders are the reference: the large-text one abbreviates the
    # tag to hold the tile width, so either spelling is his format.
    tags = [
        normalized(item)
        for item in (
            overview.get("tile_provenance_tag_variants")
            or [overview["tile_provenance_tag"]]
        )
    ]
    tag_rows = [
        (tag, row)
        for tag in tags
        for row in rows(spans)
        if len([span for span in row if span.folded == tag]) == len(overview["tiles"])
    ]
    if not tag_rows:
        violations.append(
            _violation(
                "OVERVIEW_TILE_TAGS",
                f"Page 1 does not carry {len(overview['tiles'])} "
                f"{overview['tile_provenance_tag']} tile provenance tags on one row.",
            )
        )
    else:
        tag, row = tag_rows[0]
        tag_row = [span for span in row if span.folded == tag]
        top = tag_row[0].y0 + TILE_HEADING_WINDOW[0]
        bottom = tag_row[0].y0 + TILE_HEADING_WINDOW[1]
        anchors: list[float] = []
        for label in overview["tiles"]:
            head = _head_word(label)
            hits = [
                span
                for span in spans
                if top <= span.y0 <= bottom and span.folded.split(" ")[:1] == [head]
            ]
            if normalized(label) not in folded_page or not hits:
                violations.append(
                    _violation(
                        "OVERVIEW_TILES",
                        f"Page 1 does not publish the reference tile '{label}'.",
                    )
                )
                anchors.append(float("nan"))
            else:
                anchors.append(min(hit.x0 for hit in hits))
        ordered = [value for value in anchors if value == value]
        if len(ordered) == len(anchors) and ordered != sorted(ordered):
            violations.append(
                _violation(
                    "OVERVIEW_TILES",
                    "Page 1 tiles are not in the reference order "
                    + " / ".join(overview["tiles"])
                    + ".",
                )
            )

    strip = overview["strip"]
    strip_rows = [
        row
        for row in rows(spans)
        if [span.folded for span in row if span.bold] == [normalized(item) for item in strip]
    ]
    if not strip_rows:
        violations.append(
            _violation(
                "OVERVIEW_STRIP",
                "Page 1 does not carry the reference strip " + " / ".join(strip) + ".",
            )
        )

    floor = int(extensions.get("overview_route_panel_minimum_drawings", 0))
    if floor:
        panel = [
            drawing
            for drawing in page.get_drawings()
            if drawing["rect"].x0 >= departure.x1 - 10
            and drawing["rect"].x1 <= destination.x0 + 10
        ]
        if len(panel) < floor:
            violations.append(
                _violation(
                    "OVERVIEW_ROUTE_PANEL",
                    "Page 1 centre panel draws no route schematic "
                    f"({len(panel)} vector operations, floor {floor}).",
                )
            )
    return violations


def _check_analysis(spans: Sequence[Span], structure: dict[str, Any], width: float,
                    destination: str, extensions: dict[str, Any]) -> list[dict[str, str]]:
    analysis = structure["analysis"]
    violations: list[dict[str, str]] = []

    vocabulary = set(analysis["severity_pill_vocabulary"])
    pills = [span for span in spans if span.bold and span.text.strip() in vocabulary]
    if not pills:
        violations.append(
            _violation(
                "ANALYSIS_SEVERITY_PILL",
                "Page 2 publishes no "
                + " / ".join(sorted(vocabulary))
                + " severity pill for the evidenced findings.",
            )
        )
    else:
        columns = _clusters([pill.x0 for pill in pills], tolerance=0.1 * width)
        if len(pills) >= analysis["grid_columns"] and len(columns) != analysis["grid_columns"]:
            violations.append(
                _violation(
                    "ANALYSIS_GRID_COLUMNS",
                    f"Page 2 finding cards form {len(columns)} column(s); the reference "
                    f"grid has {analysis['grid_columns']}.",
                )
            )

    heading = next(
        (span for span in spans if span.folded == normalized(analysis["timeline_heading"])),
        None,
    )
    if heading is None:
        violations.append(
            _violation(
                "ANALYSIS_TIMELINE",
                f"Page 2 has no '{analysis['timeline_heading']}'.",
            )
        )
        return violations

    below = [span for span in spans if span.y0 > heading.y0 + 4]
    stops = [span for span in below if span.bold]
    stop_rows = rows(stops)
    floor = int(extensions.get("analysis_timeline_minimum_stops", 3))
    if len(stops) < floor:
        violations.append(
            _violation(
                "ANALYSIS_TIMELINE_STOPS",
                f"The decision timeline carries {len(stops)} labelled stop(s); "
                f"the structural floor is {floor}.",
            )
        )
    departure_stop = analysis["timeline_departure_stop"]
    if not any(normalized(stop.text) == normalized(departure_stop) for stop in stops):
        violations.append(
            _violation(
                "ANALYSIS_TIMELINE_STOPS",
                f"The decision timeline carries no {departure_stop} dot.",
            )
        )
    if analysis["timeline_terminal_stop_is_destination"] and stops:
        terminal = max(stops, key=lambda span: span.x0)
        if normalized(terminal.text) != normalized(destination):
            violations.append(
                _violation(
                    "ANALYSIS_TIMELINE_STOPS",
                    "The decision timeline does not end at the destination "
                    f"{destination}; it ends at {terminal.text.strip()}.",
                )
            )
    annotated = 0
    for row in stop_rows:
        annotations = [
            span
            for span in below
            if span not in stops and abs(span.y0 - row[0].y0) <= 16
        ]
        annotated += sum(1 for span in annotations if TIME_TOKEN_RE.search(span.text))
        if len(annotations) < len(row):
            violations.append(
                _violation(
                    "ANALYSIS_TIMELINE_STOPS",
                    "A decision-timeline row prints "
                    f"{len(row)} stop(s) but {len(annotations)} annotation(s); every dot "
                    "on his axis carries its own note.",
                )
            )
    # His axis annotates the dots with level and time. Individual dots may carry
    # a note instead (CPDLC trial, GNSS RFI), so the level/time evidence is
    # required of the timeline, not of every dot.
    if stops and not annotated:
        violations.append(
            _violation(
                "ANALYSIS_TIMELINE_STOPS",
                "The decision timeline publishes no level or time against any stop.",
            )
        )
    return violations


def check_reference_conformance(
    candidate: Path,
    *,
    structure: dict[str, Any],
    contract_extensions: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Read a rendered download back and compare it with David's structure."""
    candidate = Path(candidate)
    extensions = dict(contract_extensions or {})
    violations: list[dict[str, str]] = []
    expected_pages = int(structure["page_count"])
    ribbon = list(structure["nav_ribbon"])
    destination = ""

    with fitz.open(candidate) as document:
        if len(document) != expected_pages:
            violations.append(
                _violation(
                    "PAGE_COUNT",
                    f"The download publishes {len(document)} page(s); David's reference "
                    f"format is {expected_pages}.",
                )
            )
        page_spans_cache = [page_spans(page) for page in document]
        height = float(document[0].rect.height) if len(document) else 0.0
        width = float(document[0].rect.width) if len(document) else 0.0

        for index, page in enumerate(document):
            spans = page_spans_cache[index]
            folded = normalized(page.get_text())
            number = index + 1

            marker = structure["page_marker_template"].format(
                page=number, count=expected_pages
            )
            if normalized(marker) not in folded:
                violations.append(
                    _violation("PAGE_MARKER", f"Page {number} is missing '{marker}'.")
                )

            if index < len(structure["pages"]):
                titles = structure["pages"][index]["titles"]
                if titles and not any(normalized(title) in folded for title in titles):
                    violations.append(
                        _violation(
                            "PAGE_TITLE",
                            f"Page {number} is not titled "
                            + " or ".join(f"'{title}'" for title in titles)
                            + ".",
                        )
                    )
                lead = structure["pages"][index]["footer_assurance_lead"]
                if lead and normalized(lead) not in folded:
                    violations.append(
                        _violation(
                            "FOOTER_ASSURANCE",
                            f"Page {number} footer does not carry the reference assurance "
                            f"lead '{lead}'.",
                        )
                    )

            required_ribbon = (
                number in set(structure["nav_ribbon_reference_pages"])
                or bool(extensions.get("nav_ribbon_on_every_page"))
            )
            if required_ribbon:
                found = _find_ribbon(spans, height, ribbon)
                if found is None:
                    violations.append(
                        _violation(
                            "NAV_RIBBON",
                            f"Page {number} does not carry the reference navigation ribbon "
                            + " · ".join(ribbon)
                            + ".",
                        )
                    )
                elif extensions.get("nav_ribbon_active_item_tracks_page"):
                    emphasised = [item for item in found if item.bold]
                    if len(emphasised) != 1:
                        violations.append(
                            _violation(
                                "NAV_RIBBON_ACTIVE",
                                f"Page {number} emphasises {len(emphasised)} ribbon items; "
                                "exactly one is active in the reference.",
                            )
                        )
                    elif found.index(emphasised[0]) != index:
                        violations.append(
                            _violation(
                                "NAV_RIBBON_ACTIVE",
                                f"Page {number} underlines ribbon item "
                                f"'{emphasised[0].text.strip()}' instead of '{ribbon[index]}'.",
                            )
                        )

            identity, _assurance, page_span = _footer_parts(spans, height)
            if identity is None or page_span is None:
                violations.append(
                    _violation(
                        "FOOTER_IDENTITY",
                        f"Page {number} has no footer identity and page label.",
                    )
                )
                continue
            identity_text = " ".join(identity.text.split())
            fields = [part.strip() for part in identity_text.split("|")]
            if len(fields) != int(structure["footer_identity_field_count"]):
                violations.append(
                    _violation(
                        "FOOTER_IDENTITY",
                        f"Page {number} footer identity has {len(fields)} field(s); the "
                        f"reference prints {structure['footer_identity_field_count']}.",
                    )
                )
            if not re.search(structure["footer_identity_tail_pattern"], identity_text):
                violations.append(
                    _violation(
                        "FOOTER_IDENTITY",
                        f"Page {number} footer identity does not end with the reference "
                        "OFP triplet.",
                    )
                )
            route_field = next(
                (field for field in fields if re.fullmatch(r"[A-Z]{4}-[A-Z]{4}", field)), None
            )
            if route_field and not destination:
                destination = route_field.split("-")[1]

            page_label = structure["footer_page_template"].format(
                page=number, count=expected_pages
            )
            if normalized(page_label) not in normalized(page_span.text):
                violations.append(
                    _violation(
                        "FOOTER_PAGE",
                        f"Page {number} footer does not end with '{page_label}'.",
                    )
                )

        if len(document) >= 1:
            violations.extend(
                _check_overview(document[0], page_spans_cache[0], structure, extensions)
            )
        if len(document) >= 2:
            violations.extend(
                _check_analysis(
                    page_spans_cache[1], structure, width, destination or "", extensions
                )
            )

    return {
        "valid": not violations,
        "candidate": str(candidate),
        "page_count": expected_pages,
        "violations": violations,
    }

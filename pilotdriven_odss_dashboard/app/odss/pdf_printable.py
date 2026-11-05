"""One printable form for every line the six-page Flight Briefing prints (17 Oct 2026, release-516 QA repair).

Codex's SYNTHETIC-QA516-UNICODE OFP got no pilot PDF. QA516 rightly held its EDTO row "YPDN １９４６-2327 ..." (a
full-width clock is not a clock) and page 5 printed the review with the row's raw text, but the briefing's faces are
reportlab's standard Helvetica / Helvetica-Bold (Symbol substitutes for arrows and Greek). A character outside them is
drawn as ZapfDingbats' notdef glyph, a filled square that text extraction reads back as "I": the page printed
"YPDN IIII-2327", the publication gate folded the expected line to "YPDN 2327", the two did not match and the whole
briefing was refused. The same row printed "IIII" on pages 2 and 4 without a check noticing - a held character turned
into a look-alike letter. Any held raw row (destination, EDTO, fuel-enroute, an unread slot allocation, any other
held line) can carry such characters.

The repair is one canonical printable form, used by the renderer AND by the publication check:

* The repertoire (``pdf_printable_repertoire.json``) is every character the briefing's faces draw with a real glyph
  AND that text extraction returns unchanged. It is measured, not assumed: tests/test_pdf_printable_20261017.py
  re-derives it from reportlab and PyMuPDF and requires the file to equal it.
* Every other character prints as a visible escape of its code point, ``[U+FF11]``. Nothing held is dropped, merged
  or replaced by a look-alike; a line break stays a line break. ASCII is untouched, so a genuine OFP prints exactly
  what it printed before.
* The renderer measures and draws only ``printable`` text (``wrap``, ``string_width`` and ``PrintableCanvas``); the
  gate folds ``printable`` text (``concise_pdf_gate.normalized``), so it compares the form the page prints.
* The dashboard is not touched: the analysis view keeps the exact raw text.

The app's mirror of the gate's word folding uses the same repertoire (web/src/lib/pdf-printable.mjs; both suites pin
the same digest of the code-point ranges).
"""
from __future__ import annotations

from functools import lru_cache
import json
import re
from pathlib import Path
from typing import Any

from reportlab.pdfbase import pdfmetrics
from reportlab.pdfgen.canvas import Canvas
from reportlab.pdfgen.textobject import PDFTextObject

REPERTOIRE_FILE = Path(__file__).with_name("pdf_printable_repertoire.json")
LINE_BREAK = "\n"


@lru_cache(maxsize=1)
def _rules() -> dict[str, Any]:
    return json.loads(REPERTOIRE_FILE.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def repertoire() -> frozenset[str]:
    """Every character the six-page briefing prints as itself."""
    return frozenset(chr(code) for first, last in _rules()["codePoints"] for code in range(first, last + 1))


def escape(character: str) -> str:
    """The visible form of a character outside the repertoire: its code point, ``[U+FF11]``."""
    return f"[U+{ord(character):04X}]"


def printable(value: Any) -> str:
    """The canonical printable form: repertoire characters and line breaks as themselves, every other character as
    its escape. Idempotent, and the identity on text that is already printable (every genuine OFP)."""
    text = str(value)
    held = repertoire()
    if all(character in held or character == LINE_BREAK for character in text):
        return text
    return "".join(character if character in held or character == LINE_BREAK else escape(character)
                   for character in text)


def string_width(text: Any, font: str, size: float) -> float:
    """The width the renderer draws: the printable form's."""
    return pdfmetrics.stringWidth(printable(text), font, size)


_ESCAPE = re.compile(r"\[U\+[0-9A-F]{4,6}\]")
_GATE_WORD_CHARACTER = re.compile(r"[A-Za-z0-9]")


def hard_break(word: str, end: int) -> int:
    """Where a word too wide for its line is cut, at or before ``end``: never inside an escape (one printed unit) and
    never inside a run of letters or digits, which the publication gate reads as one word - a cut there would read as
    two ("2327" printed "2" / "327"). The word is cut at the last place that is neither; only a word with no such place
    before ``end`` is cut at ``end`` (as before). Found by the printable mutation sweep: a held EDTO row
    "QAAA 19[U+1F468][U+200D][U+2708][U+FE0F]46-2327 ..." was cut inside "2327" and the gate refused the briefing."""
    escapes = [match.span() for match in _ESCAPE.finditer(word)]
    for cut in range(min(end, len(word) - 1), 0, -1):
        if any(start < cut < stop for start, stop in escapes):
            continue
        if _GATE_WORD_CHARACTER.match(word[cut - 1]) and _GATE_WORD_CHARACTER.match(word[cut]):
            continue
        return cut
    return end


FACES = ("Helvetica", "Helvetica-Bold")


def measured_repertoire_ranges(faces: tuple[str, ...] = FACES) -> list[list[int]]:
    """Measure the repertoire: draw every graphic code point (a letter, digit, punctuation or symbol, or the space;
    never a control, format, combining, private-use or other spacing character) that reportlab gives a glyph in each
    face (its own encoding or a substitution face) between two markers, read the page back with PyMuPDF (the gate's
    reader), and keep a character only when every face returns it unchanged. Returns inclusive code-point ranges."""
    import io
    import unicodedata

    import fitz
    from reportlab.lib.rl_accel import unicode2T1

    kept: set[int] | None = None
    for face in faces:
        font = pdfmetrics.getFont(face)
        fonts = [font] + font.substitutionFonts
        candidates = []
        for code in range(0x10000):
            if code != 0x20 and unicodedata.category(chr(code))[0] not in "LNPS":
                continue  # not a graphic character: it has no printed form of its own
            drawn, data = unicode2T1(chr(code), fonts)[0]
            if drawn is font._notdefFont and data == font._notdefChar:
                continue  # no glyph: reportlab draws the notdef
            candidates.append(code)
        buffer = io.BytesIO()
        canvas = Canvas(buffer)
        placed: dict[tuple[int, int], int] = {}
        page, y = 0, 800
        for code in candidates:
            canvas.setFont(face, 8)
            canvas.drawString(40, y, f"X{chr(code)}X")
            placed[(page, y)] = code
            y -= 10
            if y < 40:
                canvas.showPage()
                page, y = page + 1, 800
        canvas.save()
        read: dict[tuple[int, int], list[str]] = {}
        with fitz.open(stream=buffer.getvalue(), filetype="pdf") as document:
            for number, sheet in enumerate(document):
                height = sheet.rect.height
                for block in sheet.get_text("rawdict")["blocks"]:
                    for line in block.get("lines", []):
                        for span in line["spans"]:
                            for char in span["chars"]:
                                read.setdefault((number, round(height - char["origin"][1])), []).append(char["c"])
        round_trip = {code for key, code in placed.items() if "".join(read.get(key, [])) == f"X{chr(code)}X"}
        kept = round_trip if kept is None else kept & round_trip
    ranges: list[list[int]] = []
    for code in sorted(kept or ()):
        if ranges and ranges[-1][1] == code - 1:
            ranges[-1][1] = code
        else:
            ranges.append([code, code])
    return ranges


class PrintableTextObject(PDFTextObject):
    """A text object that formats only printable text: the last point before glyphs are chosen."""

    def _formatText(self, text):
        return super()._formatText(printable(text))


class PrintableCanvas(Canvas):
    """The six-page briefing's canvas: every string is measured and drawn in its printable form, whichever module
    draws it, so no character can reach a page as a notdef or a look-alike glyph."""

    def beginText(self, x=0, y=0, direction=None):
        return PrintableTextObject(self, x, y, direction=direction)

    def stringWidth(self, text, fontName=None, fontSize=None):
        return super().stringWidth(printable(text), fontName, fontSize)

    def drawString(self, x, y, text, *args, **kwargs):
        return super().drawString(x, y, printable(text), *args, **kwargs)

    def drawRightString(self, x, y, text, *args, **kwargs):
        return super().drawRightString(x, y, printable(text), *args, **kwargs)

    def drawCentredString(self, x, y, text, *args, **kwargs):
        return super().drawCentredString(x, y, printable(text), *args, **kwargs)

    def drawAlignedString(self, x, y, text, *args, **kwargs):
        return super().drawAlignedString(x, y, printable(text), *args, **kwargs)

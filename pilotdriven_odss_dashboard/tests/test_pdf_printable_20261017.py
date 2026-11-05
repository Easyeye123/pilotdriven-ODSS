"""Every held raw line prints in ONE canonical printable form, and the briefing publishes (17 Oct 2026).

Found while integrating QA514 + QA516 on release 516 (output/pd-int514-516-20261017/): Codex's
SYNTHETIC-QA516-UNICODE OFP got no pilot PDF - "Concise briefing publication failed: Page 5 omits a source-bound
assessment: YPDN · REVIEW - ... "YPDN １９４６-2327 29 CAT1DME 409FT/1600M" ...". QA516 rightly held the EDTO row (a
full-width clock is not a clock) and page 5 printed its review with the row's raw text. The briefing's faces are
reportlab's standard Helvetica / Helvetica-Bold (Symbol substitutes for arrows and Greek); a character outside them is
drawn as ZapfDingbats' notdef glyph, which PyMuPDF reads back as "I". The page said "YPDN IIII-2327", the gate folded
the expected line to "YPDN 2327" (its folding dropped every non-ASCII character), the two differed and the whole
briefing was refused - the QA512-01 class, one held row denying the pilot the whole output. Pages 2 and 4 printed the
destination row's "０３９６" as "IIII" with no check noticing. Any held raw row can carry such characters.

The repair (app/odss/pdf_printable.py): one canonical printable form, used by the renderer AND the check. A character
the faces draw with a real glyph and extraction returns unchanged prints as itself (the measured repertoire, which
this file re-derives); every other character prints as its code point, ``[U+FF11]``. The renderer wraps, measures and
draws only that form (PrintableCanvas), the gate folds that form, and the analysis view - the dashboard - keeps the
exact raw text.

The mutation covers every held-raw line type the parser holds: a destination-alternate row, a line of that table whose
airport is not read, an EDTO-alternate row, a line of that table whose airport is not read, a FUEL ENROUTE AIRPORT
station row, a line of that section whose airport is not read, and a slot-control allocation printed but not read. Each
is a LABELLED SYNTHETIC line (synthetic identities "Q" + three letters; SQ322's printed allocation form with an
impossible CTO) added to text extracted from a genuine original (SQ279 SIN-ADL; SQ605 ICN-SIN for its FUEL ENROUTE
AIRPORT section), and each is mutated with every sequence of five classes - non-ASCII decimal digits, zero-width
characters, combining marks, right-to-left characters and emoji - at three places in the line. For each mutation:
the PDF publishes six pages; on every page where the ASCII baseline prints the held line, the mutated page prints it
in canonical form, as often; the view and findings hold the exact raw text, never an escape; and with the held
line's own review set aside, every page is word for word the baseline's.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import io
import json
import os
from pathlib import Path
import random
import re
import tempfile

import fitz
import pytest
from reportlab.pdfbase import pdfmetrics

from app.odss.briefing import build_briefing_view
from app.odss.combined_brief import render_combined_briefing
from app.odss.concise_pdf_gate import normalized
from app.odss.engines import analyse
from app.odss.notam_restriction_line import _gate_words
from app.odss.operational_format import wrap
from app.odss.parser import extract_pages, parse_lido
from app.odss.pdf_printable import (REPERTOIRE_FILE, PrintableCanvas, escape, hard_break, measured_repertoire_ranges,
                                    printable, repertoire, string_width)

ROOT = Path(__file__).resolve().parents[1]
SQ279 = "lido-briefing_SQ_279_15Aug2026_SIN_ADL.pdf"
SQ605 = "SQ60508092026ICN.pdf"
# The same digest is pinned by the app's tests/pdf-printable-20261017.test.mjs over its own copy of the ranges.
CODE_POINTS_SHA256 = "c7ec35f0e5f74e007d64bd9924f10695f6bc2c0dc8fe97d38bc1ce8e316f482c"

# Five classes of character a held row can carry that the faces cannot print as themselves.
CLASSES: dict[str, tuple[str, ...]] = {
    "non_ascii_digits": ("０３", "٣", "۳", "३", "৩", "๓", "\U0001d7d1"),
    "zero_width": ("​", "‌", "‍", "⁠", "﻿"),
    "combining_marks": ("é", "̈", "⃝", "̲"),
    "rtl": ("אב", "ال", "‏", "‮", "⁧ג⁩"),
    "emoji": ("\U0001f600", "✈️", "✈", "\U0001f1f8\U0001f1ec", "\U0001f468‍✈️",
              "1️⃣"),
}
SEQUENCES = [(name, sequence) for name, values in CLASSES.items() for sequence in values]
# Every sequence of every class in one line, over its three places.
LONGEST = "\U0001f468\u200d\u2708\ufe0f"  # the pilot emoji: four escapes, the widest single sequence
STRESS = ("".join(CLASSES["non_ascii_digits"]) + "".join(CLASSES["zero_width"]),
          "".join(CLASSES["combining_marks"]) + "".join(CLASSES["rtl"]), "".join(CLASSES["emoji"]))


def _corpus() -> Path:
    configured = os.environ.get("PILOTDRIVEN_PRIVATE_CFP_CORPUS_DIR")
    corpus = Path(configured) if configured else ROOT.parent / "private_cfp_corpus"
    if not corpus.is_dir():
        if configured:
            raise FileNotFoundError(f"Configured PILOTDRIVEN_PRIVATE_CFP_CORPUS_DIR is missing: {corpus}")
        pytest.skip("the private CFP corpus is not available")
    return corpus


_PAGES: dict[str, list[str]] = {}


def _pages(name: str) -> list[str]:
    if name not in _PAGES:
        path = _corpus() / name
        if not path.is_file():
            pytest.skip(f"private source {name} not available")
        _PAGES[name] = extract_pages(path)
    return _PAGES[name]


# ------------------------------------------------------------------------------------------ the repertoire, measured

def test_the_repertoire_file_is_the_measured_repertoire() -> None:
    """The file is what reportlab draws with a real glyph and PyMuPDF reads back unchanged - never an assumption."""
    held = json.loads(REPERTOIRE_FILE.read_text(encoding="utf-8"))
    assert held["codePoints"] == measured_repertoire_ranges()
    assert held["lineBreak"] == "\n"


def test_both_runtimes_hold_the_same_repertoire() -> None:
    held = json.loads(REPERTOIRE_FILE.read_text(encoding="utf-8"))["codePoints"]
    digest = hashlib.sha256(json.dumps(held, separators=(",", ":")).encode()).hexdigest()
    assert digest == CODE_POINTS_SHA256, "copy the ranges to the app's web/src/lib/pdf-printable.mjs and re-pin both suites"


def test_what_a_genuine_briefing_prints_is_in_the_repertoire() -> None:
    """ASCII and the three non-ASCII characters every genuine render prints (middle dot, arrow, ellipsis) print as
    themselves; the notdef stand-in and the replacement character never do."""
    assert {chr(code) for code in range(0x20, 0x7F)} <= repertoire()
    assert {"·", "→", "…"} <= repertoire()
    assert not {"■", "�", " ", "­", "\t", "\r"} & repertoire()


# ------------------------------------------------------------------------------------------- the canonical function

@pytest.mark.parametrize("raw,printed", [
    ("YPDN １９４６-2327 29 CAT1DME 409FT/1600M", "YPDN [U+FF11][U+FF19][U+FF14][U+FF16]-2327 29 CAT1DME 409FT/1600M"),
    ("YMML/34 700FT/2500M ０３９６ 330", "YMML/34 700FT/2500M [U+FF10][U+FF13][U+FF19][U+FF16] 330"),
    ("A​B⁠C﻿", "A[U+200B]B[U+2060]C[U+FEFF]"),
    ("Café ̈", "Cafe[U+0301] [U+0308]"),
    ("אב ‮RWY", "[U+05D0][U+05D1] [U+202E]RWY"),
    ("\U0001f600 ✈️ \U0001f1f8\U0001f1ec", "[U+1F600] [U+2708][U+FE0F] [U+1F1F8][U+1F1EC]"),
    ("٣\U0001d7d1", "[U+0663][U+1D7D1]"),
    ("NBSP TAB\tCR\r", "NBSP[U+00A0]TAB[U+0009]CR[U+000D]"),
    ("two\nlines", "two\nlines"),
    ("SQ910 · WSSS → RPLL …", "SQ910 · WSSS → RPLL …"),
    ("Café ÆØÅ – ™ ≤ ΑΒΓ", "Café ÆØÅ – ™ ≤ ΑΒΓ"),
    ("Δ Ω μ", "[U+0394] [U+03A9] [U+03BC]"),  # Symbol prints them, extraction returns look-alikes
])
def test_the_printable_form(raw: str, printed: str) -> None:
    assert printable(raw) == printed
    assert printable(printed) == printed


def test_printable_is_idempotent_and_the_identity_on_printable_text() -> None:
    rng = random.Random(20261017)
    alphabet = sorted(repertoire()) + ["\n"] + [s for _, s in SEQUENCES] + [" ", "\t", "\x00", "\ud800", "\U0010fffd"]
    for _ in range(2000):
        text = "".join(rng.choice(alphabet) for _ in range(rng.randint(0, 40)))
        once = printable(text)
        assert printable(once) == once
        assert all(ch in repertoire() or ch == "\n" for ch in once)
        clean = "".join(ch for ch in text if ch in repertoire() or ch == "\n")
        assert printable(clean) == clean


def test_nothing_is_dropped_every_escape_names_its_character() -> None:
    for _, sequence in SEQUENCES:
        printed = printable(f"X{sequence}X")
        expected = "X" + "".join(ch if ch in repertoire() else escape(ch) for ch in sequence) + "X"
        assert printed == expected
        assert re.sub(r"\[U\+([0-9A-F]{4,6})\]", lambda m: chr(int(m.group(1), 16)), printed) == f"X{sequence}X"


def test_the_gate_and_the_copy_guard_fold_the_printable_form() -> None:
    assert normalized("YPDN １９４６-2327") == "YPDN U FF11 U FF19 U FF14 U FF16 2327"
    assert normalized("YPDN [U+FF11][U+FF19][U+FF14][U+FF16]-2327") == normalized("YPDN １９４６-2327")
    for _, sequence in SEQUENCES:
        text = f"RWY 02L{sequence} CLSD DUE WIP"
        assert _gate_words(text) == normalized(text).split()
        assert normalized(printable(text)) == normalized(text)


def test_layout_measures_and_wraps_the_printable_form_and_never_cuts_an_escape() -> None:
    raw = "YPDN " + "１" * 30 + "-2327"
    assert string_width(raw, "Helvetica", 9) == pdfmetrics.stringWidth(printable(raw), "Helvetica", 9)
    lines = wrap(raw, 90, size=9)
    assert "".join(lines).replace(" ", "") == printable(raw).replace(" ", "")
    for line in lines:
        assert not re.search(r"\[U\+[0-9A-F]*$|^[0-9A-F]*\]", line), lines
        assert pdfmetrics.stringWidth(line, "Helvetica", 9) <= 90


def test_a_word_too_wide_for_its_line_is_cut_only_between_the_gates_words() -> None:
    """The printable mutation sweep found it: a held EDTO row "QAAA 19<pilot emoji>46-2327 ..." printed as one token
    "19[U+1F468][U+200D][U+2708][U+FE0F]46-2327" wider than page 5's card; the wrap cut it inside "2327", the page read
    "2" / "327", the gate (which reads a run of letters or digits as one word) did not find the line and refused the
    briefing. A cut never splits an escape or a letter/digit run while the word has another place to cut."""
    token = "19[U+1F468][U+200D][U+2708][U+FE0F]46-2327"
    assert hard_break(token, len(token) - 3) == token.index("2327")
    assert hard_break(token, 6) == 2 and hard_break(token, 12) == 11
    assert hard_break("ABCDEFGHIJ", 5) == 5, "a single letter/digit run wider than the line is still cut"
    rng, checked = random.Random(20261017), 0
    pieces = [s for _, s in SEQUENCES] + ["0396", "2327", "409FT", "-", "/", "CAT1DME", ".", "QAAA", "1600M", "(", ")"]
    for _ in range(3000):
        raw = " ".join("".join(rng.choice(pieces) for _ in range(rng.randint(1, 6))) for _ in range(rng.randint(1, 4)))
        width = rng.choice((60, 75, 90, 120))
        lines = wrap(raw, width, font="Helvetica-Bold", size=9)
        runs = re.findall(r"[A-Za-z0-9]+|\[U\+[0-9A-F]+\]", printable(raw))
        if all(pdfmetrics.stringWidth(run, "Helvetica-Bold", 9) <= width for run in runs):
            checked += 1
            assert normalized("\n".join(lines)) == normalized(raw), (raw, width, lines)
        assert "".join(lines).replace(" ", "") == printable(raw).replace(" ", "")
        for line in lines:
            assert not re.search(r"\[U\+[0-9A-F]*$|^[0-9A-F]*\]", line), lines
    assert checked > 2000, checked  # words whose every letter/digit run fits the line: the gate reads them whole


def test_the_canvas_draws_every_string_in_its_printable_form_and_never_a_notdef() -> None:
    strings = [f"{name} {sequence} end" for name, sequence in SEQUENCES] + ["plain ASCII · → …"]
    buffer = io.BytesIO()
    canvas = PrintableCanvas(buffer)
    y = 800
    for index, value in enumerate(strings):
        draw = (canvas.drawString, canvas.drawRightString, canvas.drawCentredString)[index % 3]
        canvas.setFont("Helvetica-Bold" if index % 2 else "Helvetica", 9)
        draw(300, y, value)
        y -= 14
    text = canvas.beginText(40, y)
    text.textLines([f"textobject {sequence}" for _, sequence in SEQUENCES[::5]])
    canvas.drawText(text)
    canvas.save()
    with fitz.open(stream=buffer.getvalue(), filetype="pdf") as document:
        page = document[0]
        assert {font[3] for font in page.get_fonts()} <= {"Helvetica", "Helvetica-Bold", "Symbol"}
        printed = page.get_text().splitlines()
    assert printed == [printable(value) for value in strings] + [printable(f"textobject {sequence}")
                                                                  for _, sequence in SEQUENCES[::5]]


# --------------------------------------------------------------------------- the mutation over every held-raw line type

@dataclass(frozen=True)
class HeldLine:
    """One held-raw line type: a LABELLED SYNTHETIC line in a genuine original, and three insertion places in it."""

    source: str
    table: str | None  # None: the slot-control allocation
    airport: str | None
    line: str
    places: tuple[int, int, int]

    def pages(self, line: str) -> list[str]:
        pages = _pages(self.source)
        if self.table == "destination_alternates":
            out = [re.sub(r"(?m)^YMML/34[^\n]*$", lambda m: m.group() + "\n" + line, page) for page in pages]
        elif self.table == "edto_alternates":
            out = [re.sub(r"(?m)^YPDN     1946-2327[^\n]*$", lambda m: m.group() + "\n" + line, page) for page in pages]
        elif self.table == "fuel_enroute_airports":
            out = [re.sub(r"(?m)(^FUEL ENROUTE AIRPORT\n=+\n \nVVTS /SGN[^\n]*\n-+\n)",
                          lambda m: m.group(1) + line + "\n------------------------------\n", page) for page in pages]
        else:  # page 1's REMARKS, where SQ322 and SQ352 print their allocations
            out = [pages[0].replace("REMARKS:\n", f"REMARKS:\n{line}\n", 1), *pages[1:]]
        assert out != pages, "the anchor in the genuine original moved"
        return out


def _at(line: str, anchor: str, offset: int) -> int:
    return line.index(anchor) + offset


_DEST = "QAAA/99              700FT/2500M  0396  330 P007  0105 05817"
_DEST_LINE = "Q1AA/99              700FT/2500M  0396  330 P007  0105 05817"
_EDTO = "QAAA     1946-2327          99         CAT1DME          409FT/1600M"
_EDTO_LINE = "QA1A     1946-2327          29         CAT1DME          409FT/1600M"
_FUEL = "QAAA /HKT   SYNTHETIC QA516 STATION"
_FUEL_LINE = "QA9A /HKT   SYNTHETIC QA516 STATION"
# SQ322 16 Aug's printed allocation form, with an impossible CTO, on a waypoint of SQ279's own route.
_SLOT = "* BOBCAT ALLOCATION: WPT-ATNAR | FL-390 | CTO-2460 | CTOT-1527 *"
HELD_LINES = {
    "destination_row": HeldLine(SQ279, "destination_alternates", "QAAA", _DEST,
                                (_at(_DEST, "700FT", 3), _at(_DEST, "0396", 2), len(_DEST))),
    "destination_line_airport_not_read": HeldLine(SQ279, "destination_alternates", None, _DEST_LINE,
                                                  (2, _at(_DEST_LINE, "0396", 2), len(_DEST_LINE))),
    "edto_row": HeldLine(SQ279, "edto_alternates", "QAAA", _EDTO,
                         (_at(_EDTO, "1946", 2), _at(_EDTO, "409FT", 3), len(_EDTO))),
    "edto_line_airport_not_read": HeldLine(SQ279, "edto_alternates", None, _EDTO_LINE,
                                           (2, _at(_EDTO_LINE, "409FT", 3), len(_EDTO_LINE))),
    "fuel_enroute_row": HeldLine(SQ605, "fuel_enroute_airports", "QAAA", _FUEL,
                                 (_at(_FUEL, "/HKT", 3), _at(_FUEL, "SYNTHETIC", 4), len(_FUEL))),
    "fuel_enroute_line_airport_not_read": HeldLine(SQ605, "fuel_enroute_airports", None, _FUEL_LINE,
                                                   (2, _at(_FUEL_LINE, "SYNTHETIC", 4), len(_FUEL_LINE))),
    "slot_allocation": HeldLine(SQ279, None, None, _SLOT,
                                (_at(_SLOT, "ATNAR", 3), _at(_SLOT, "CTOT-1527", 7), len(_SLOT))),
}


def insert(line: str, places: tuple[int, ...], sequences: tuple[str, ...]) -> str:
    for place, sequence in sorted(zip(places, sequences), reverse=True):
        line = line[:place] + sequence + line[place:]
    return line


def _held(flight: dict, kind: HeldLine) -> list[dict]:
    if kind.table is None:
        unread = flight.get("slot_allocation_unread")
        return [unread] if unread else []
    return [row for row in flight["alternates_unread"] if row["table"] == kind.table]


def _strings(value, path=()):
    if isinstance(value, dict):
        for key, item in value.items():
            yield from _strings(item, (*path, key))
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            yield from _strings(item, (*path, index))
    elif isinstance(value, str):
        yield path, value


_GENERATED = re.compile(r"generated\d{1,2}[A-Z]{3}\d{4}\d{4}Z", re.IGNORECASE)


def _flat(text: str) -> str:
    """Page text without layout whitespace (a wrap may break a line anywhere) or the minute it was generated."""
    return _GENERATED.sub("generated", "".join(text.split()))


@dataclass
class Publication:
    raw: str
    held: list[dict]
    pages: list[str]
    dashboard: list[tuple[tuple, str]]


def publish(kind: HeldLine, line: str) -> Publication:
    flight = parse_lido(kind.pages(line), "SYNTHETIC-PDF-PRINTABLE-NOT-A-REAL-FLIGHT.pdf")
    held = _held(flight, kind)
    findings, warnings = analyse(flight)
    view = build_briefing_view(flight, findings, warnings, None, None, include_dashboard_only_panels=True)
    with tempfile.TemporaryDirectory() as scratch:
        pdf = Path(scratch) / "six-pages.pdf"
        render_combined_briefing(flight, findings, warnings, pdf, source_pdf_path=None)  # raises if the gate refuses
        with fitz.open(pdf) as document:
            pages = [page.get_text() for page in document]
            assert all(font[3] != "ZapfDingbats" for page in document for font in page.get_fonts())
    return Publication(" ".join(line.split()), held, pages,
                       list(_strings({"view": view, "findings": findings, "warnings": warnings})))


_BASELINES: dict[str, Publication] = {}


def baseline(name: str) -> Publication:
    if name not in _BASELINES:
        kind = HELD_LINES[name]
        _BASELINES[name] = publish(kind, kind.line)
    return _BASELINES[name]


HELD = "<HELD>"
# The parenthetical a review puts right before the quoted held text - "(runway not valid)", "(IATA code not valid)",
# "(CTO 2460 is not a UTC clock time)" - is read from the held text itself, so it is the held line's own words.
_HELD_NOTE = re.compile(r"\([^()]*\)(?=:" + re.escape(HELD) + ")")
_REASON_CELL = re.compile(r"cell\"[^\"]*\"")
_DEFERRAL = re.compile(r"\+\d+further[^.]*?onthedashboard\.")


def _rest(page: str, quote: str) -> str:
    """The page with the held line's own words set aside (its quoted raw text, the note or reason its review reads from
    that text, a reason quoting one of its cells); everything else on the page must not move."""
    flat = _flat(page).replace(_flat(quote), HELD)
    return _REASON_CELL.sub('cell"<CELL>"', _HELD_NOTE.sub("", flat))


def _moved(page: str, old: str) -> str:
    """The first word-level difference, for the failure message."""
    import difflib
    a, b = old.replace(HELD, f" {HELD} ").split(), page.replace(HELD, f" {HELD} ").split()
    a, b = re.findall(r".{1,60}", "".join(a)), re.findall(r".{1,60}", "".join(b))
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if tag != "equal":
            return f"-[{''.join(a[max(0, i1 - 1):i2 + 1])}] +[{''.join(b[max(0, j1 - 1):j2 + 1])}]"
    return ""


def check_mutation(name: str, sequences: tuple[str, ...], *, capacity_may_move: bool = False) -> Publication:
    """``capacity_may_move``: a held line hundreds of characters longer than its baseline may exceed its card, and the
    page then does what it does for any line that does not fit - prints the line or states it among "+N further ...
    on the dashboard", and may print another card in its compact form. Pages that do not hold the line still must
    not move."""
    kind = HELD_LINES[name]
    base = baseline(name)
    line = insert(kind.line, kind.places, sequences)
    assert line != kind.line
    published = publish(kind, line)
    # The parser holds the row with its exact raw text, as the baseline's (one row of this type, same airport).
    assert [row["text"] for row in base.held] == [base.raw]
    assert [row["text"] for row in published.held] == [published.raw], (name, sequences)
    if kind.table is not None:
        assert [row["airport"] for row in published.held] == [row["airport"] for row in base.held] == [kind.airport]
    # The PDF published six pages; the held line is printed in its canonical form wherever the baseline prints it.
    assert len(published.pages) == len(base.pages) == 6
    base_quote, quote = f'"{base.raw}"', f'"{printable(published.raw)}"'
    where = [_flat(page).count(_flat(base_quote)) for page in base.pages]
    assert sum(where) >= 1, f"{name}: the baseline does not print its held line"
    printed = [_flat(page).count(_flat(quote)) for page in published.pages]
    if capacity_may_move:
        for page, count, expected in zip(published.pages, printed, where):
            assert count == expected or (count < expected and _DEFERRAL.search(_flat(page))), (name, printed, where)
    else:
        assert printed == where, (name, sequences, printed, where)
    # The dashboard (analysis view, findings, warnings) keeps the exact raw text, wherever the baseline holds its own.
    base_paths = {path for path, text in base.dashboard if base.raw in text}
    paths = {path for path, text in published.dashboard if published.raw in text}
    assert base_paths and paths == base_paths, (name, sequences)
    assert not any("[U+" in text for _, text in published.dashboard)
    # Nothing else on any page moved.
    for number, (page, old, count) in enumerate(zip(published.pages, base.pages, where), start=1):
        if capacity_may_move and count:
            continue
        rest, rest_old = _rest(page, quote), _rest(old, base_quote)
        if rest != rest_old:
            pytest.fail(f"{name} {sequences!r}: page {number} changed beyond the held line: {_moved(rest, rest_old)}")
    return published


def _triples() -> list[tuple[str, tuple[str, str, str]]]:
    """Every sequence of every class, three at a time (one per place); a class's last triple wraps to its start."""
    out = []
    for label, values in CLASSES.items():
        for start in range(0, len(values), 3):
            out.append((label, tuple(values[(start + offset) % len(values)] for offset in range(3))))
    return out


TRIPLES = _triples()


@pytest.mark.parametrize("label,sequences", TRIPLES, ids=[f"{label}-{index}" for index, (label, _) in enumerate(TRIPLES)])
@pytest.mark.parametrize("name", list(HELD_LINES))
def test_a_held_line_with_unprintable_characters_publishes_in_canonical_form(name: str, label: str,
                                                                           sequences: tuple[str, str, str]) -> None:
    """Three sequences of one class at the three places of the held line (inside the first value cell, or inside the
    airport cell that is not read; inside a later value; at the end). Each sequence alone at each place, and each at
    all three, are output/pd-int514-516-20261017/scripts/printable_mutation_sweep.py."""
    check_mutation(name, sequences)


@pytest.mark.parametrize("place", [0, 1, 2])
@pytest.mark.parametrize("name", list(HELD_LINES))
def test_the_widest_sequence_at_each_place_alone(name: str, place: int) -> None:
    """The sweep's finding as a test: the widest sequence alone at each place (inside "1946" made the EDTO row's token
    too wide for its card, and its cut used to fall inside "2327")."""
    check_mutation(name, tuple(LONGEST if index == place else "" for index in range(3)))


@pytest.mark.parametrize("name", list(HELD_LINES))
def test_every_class_at_once_in_one_held_line(name: str) -> None:
    """Every sequence of every class in one line (38 escapes over the three places: the printed line is 271 characters
    longer than its raw text). It still publishes, prints in canonical form or says what it leaves to the dashboard,
    and the dashboard holds it."""
    check_mutation(name, STRESS, capacity_may_move=True)


@pytest.mark.skipif(not os.environ.get("PILOTDRIVEN_APP_ROOT"), reason="PILOTDRIVEN_APP_ROOT (the app's cfp.mjs) is not set")
def test_the_app_parse_holds_every_mutated_row_with_the_same_raw_text() -> None:
    """The dashboard's own parse (the app's parseCfpPages) holds each mutated table row exactly as ODSS holds it -
    table, airport and the raw text character for character (the slot allocation is composed from the ODSS view)."""
    import subprocess

    app = Path(os.environ["PILOTDRIVEN_APP_ROOT"])
    cases = {name: kind.pages(insert(kind.line, kind.places, STRESS))
             for name, kind in HELD_LINES.items() if kind.table is not None}
    script = ("import fs from 'node:fs';import {parseCfpPages} from './cfp.mjs';"
              "const cases=JSON.parse(fs.readFileSync(process.argv[1],'utf8'));const out={};"
              "for(const [name,pages] of Object.entries(cases)){const p=parseCfpPages(pages.map((text,i)=>({pageNumber:i+1,text})),"
              "{fileName:'SYNTHETIC-PDF-PRINTABLE-'+name+'.pdf'}).pertinent;out[name]=p.alternatesUnread.map(r=>[r.table,r.icao,r.text]);}"
              "process.stdout.write(JSON.stringify(out));")
    with tempfile.TemporaryDirectory() as scratch:
        request = Path(scratch) / "cases.json"
        request.write_text(json.dumps(cases))
        result = subprocess.run(["node", "--input-type=module", "-e", script, str(request)], cwd=app,
                                capture_output=True, text=True, timeout=600)
    assert result.returncode == 0, result.stderr
    app_rows = json.loads(result.stdout)
    for name, pages in cases.items():
        flight = parse_lido(pages, "SYNTHETIC-PDF-PRINTABLE-NOT-A-REAL-FLIGHT.pdf")
        odss = [[row["table"], row["airport"], row["text"]] for row in flight["alternates_unread"]]
        assert any(text != printable(text) for _, _, text in odss), name
        assert app_rows[name] == odss, name


# ------------------------------------------------------------------------------------- Codex's own reproducer, whole

def test_codex_qa516_unicode_ofp_publishes_six_pages_with_its_held_rows_in_canonical_form() -> None:
    """SYNTHETIC-QA516-UNICODE (Codex, output/pd-516-codex-qa-20261017/evidence/): the genuine SQ279 with full-width
    digits in the YMML destination row and the YPDN EDTO row. Both rows are held; the briefing publishes; pages 2 and
    4 print the destination row and page 5 the EDTO row, each in canonical form, and no page prints a notdef."""
    destination = "YMML/34              700FT/2500M  ０３９６  330 P007  0105 05817"
    edto = "YPDN     １９４６-2327          29         CAT1DME          409FT/1600M"
    pages = [re.sub(r"(?m)^YPDN     1946-2327[^\n]*$", edto, re.sub(r"(?m)^YMML/34[^\n]*$", destination, page))
             for page in _pages(SQ279)]
    flight = parse_lido(pages, "SYNTHETIC-QA516-UNICODE-NOT-A-REAL-FLIGHT.pdf")
    assert [(row["table"], row["airport"], row["text"]) for row in flight["alternates_unread"]] == [
        ("destination_alternates", "YMML", " ".join(destination.split())),
        ("edto_alternates", "YPDN", " ".join(edto.split()))]
    findings, warnings = analyse(flight)
    with tempfile.TemporaryDirectory() as scratch:
        pdf = Path(scratch) / "six-pages.pdf"
        render_combined_briefing(flight, findings, warnings, pdf, source_pdf_path=None)
        with fitz.open(pdf) as document:
            assert document.page_count == 6
            assert all(font[3] != "ZapfDingbats" for page in document for font in page.get_fonts())
            text = [" ".join(page.get_text().split()) for page in document]
    held_destination = '"YMML/34 700FT/2500M [U+FF10][U+FF13][U+FF19][U+FF16] 330 P007 0105 05817"'
    held_edto = '"YPDN [U+FF11][U+FF19][U+FF14][U+FF16]-2327 29 CAT1DME 409FT/1600M"'
    assert [index + 1 for index, page in enumerate(text) if held_destination in page] == [2, 4]
    assert [index + 1 for index, page in enumerate(text) if held_edto in page] == [5]
    assert "YMML ALTERNATE · REVIEW - OFP p1 prints this alternate, but its row was not read: " + held_destination in text[3]
    assert "YPDN · REVIEW - OFP p9 prints this EDTO alternate, but its row was not read: " + held_edto in text[4]
    assert not any("IIII" in page for page in text)

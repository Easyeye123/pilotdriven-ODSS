"""Build the plain-English lexicon the published briefing cases source text with.

Provenance
----------
Source: ``/usr/share/dict/web2`` - Webster's Second International, whose 1934
copyright has lapsed (see ``/usr/share/dict/README``). It ships with macOS and
the BSDs. The generated artefact is checked in, so the service never depends on
the file being present at build or run time.

Why the artefact starts at three letters but is only consulted at five
---------------------------------------------------------------------
An operational abbreviation that has to survive publication (MEL, NEF, ECP,
ILS, CAT, TCAS, GPU, IRS, EGT, EFB, AOG, VHF, INOP, ACRFT, REQ) is almost
always two to four letters, and Webster's contains archaic entries that collide
with several of them (``mel``, ``nef``, ``elt``, ``ife``, ``oxy``, ``pa``,
``atis``, ``eta``, ``tod``). Words of five letters and longer collide with no
aviation acronym we can find, so a dictionary is safe there; the two-to-four
letter band is served instead by the hand-checked ``SHORT_PLAIN_WORDS`` set in
``app/odss/plain_english.py``, which is a *safe list*: a word missing from it
merely stays in the source's own capitals.

Three- and four-letter head words are still written to the artefact, because a
longer word stems onto them ("CLOGGED" -> "clog", "SEALS" -> "seal"). The
lookup never consults the artefact for a whole token of fewer than five
letters, so they cannot re-open the collision the band exists to close.

Usage: python scripts/build_plain_english_lexicon.py [source] [destination]
"""
from __future__ import annotations

import gzip
import sys
from pathlib import Path

# Words of five letters or more that are ordinary English but are reserved in
# operational text for something else, so they must never be lowercased.
RESERVED = frozenset({
    # NATO phonetic alphabet - a letter, not the English word.
    "alpha", "bravo", "delta", "india", "juliet", "juliett", "kilo", "lima",
    "mike", "oscar", "papa", "quebec", "romeo", "sierra", "tango", "uniform",
    "victor", "whiskey", "whisky", "xray", "yankee", "zulu",
    # Procedure and product names spelled as English words.
    "star",      # Standard Terminal Arrival Route
    "notam", "sigmet", "airmet", "intam", "metar", "speci", "volmet",
    "atis", "awos", "asos", "pirep", "selcal", "satcom", "squawk",
    # Short abbreviations Webster's also happens to hold.
    "abn", "acn", "alt", "apu", "arm", "aux", "cat", "cms", "com", "dme",
    "ecp", "efb", "egt", "elt", "emer", "eng", "eta", "etd", "fap", "fwd",
    "gpu", "ife", "ils", "inop", "irs", "lav", "map", "mel", "met", "nef",
    "oxy", "pan", "pax", "pls", "qty", "req", "rev", "rwy", "sid", "taf",
    "tod", "vhf", "wac", "wrt", "maint", "acft", "svce",
})

MINIMUM_LENGTH = 3


def build(source: Path) -> list[str]:
    words = set()
    for line in source.read_text(encoding="utf-8", errors="ignore").splitlines():
        word = line.strip()
        if not word.isalpha() or not word.islower():
            continue
        if len(word) < MINIMUM_LENGTH or word in RESERVED:
            continue
        words.add(word)
    return sorted(words)


def main() -> int:
    source = Path(sys.argv[1] if len(sys.argv) > 1 else "/usr/share/dict/web2")
    destination = Path(
        sys.argv[2]
        if len(sys.argv) > 2
        else Path(__file__).resolve().parents[1] / "app" / "odss" / "plain_english_words.txt.gz"
    )
    words = build(source)
    payload = ("\n".join(words) + "\n").encode("utf-8")
    destination.write_bytes(gzip.compress(payload, 9, mtime=0))
    print(f"{len(words)} words -> {destination} ({destination.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

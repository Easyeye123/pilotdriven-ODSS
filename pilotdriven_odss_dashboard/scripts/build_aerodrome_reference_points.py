"""Build the governed aerodrome reference table from the operator's own LIDO aerodrome records.

Route maps draw an aerodrome only at the reference point this table holds for its ICAO code (QA496-03, item 11).
LIDO prints each flight's destination aerodrome as the last navlog row, named with its ICAO code, with the
coordinates of the operator's navigation-database aerodrome record ("WSSS ... / N01 21.6 E103 59.4"). This script
transcribes those records from the held OFP corpus, pins every value to the source file (SHA-256), page and printed
text, and refuses an aerodrome whose held records disagree. A reviewer adds an aerodrome by adding a held OFP that
lands there and re-running the script; nothing is typed in by hand.

The table is not derived from the flight being drawn: at run time an aerodrome is looked up by its ICAO code, and a
code the table does not hold is reported as not drawn.

Usage:
    python scripts/build_aerodrome_reference_points.py [--corpus DIR] [--output PATH] [--check]
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys

import fitz

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.odss.parser import parse_lido  # noqa: E402
DEFAULT_CORPUS = ROOT.parent / "private_cfp_corpus"
DEFAULT_OUTPUT = ROOT / "app" / "odss" / "aerodrome_reference_points.json"
_HEADER = re.compile(r"^POSN\s+FREQ\s+ACTM\b")
_ROW = re.compile(r"^(?P<name>[A-Z]{4})\s+(?:\d{3}(?:\.\d+)?\s+)?\d{2}\.\d{2}\b")
_COORDINATE = re.compile(
    r"^(?P<lat_h>[NS])(?P<lat_d>\d{2}) (?P<lat_m>\d{2}\.\d) (?P<lon_h>[EW])(?P<lon_d>\d{3}) (?P<lon_m>\d{2}\.\d)\b"
)


def _decimal(hemisphere: str, degrees: str, minutes: str) -> float:
    value = int(degrees) + float(minutes) / 60
    return round(-value if hemisphere in {"S", "W"} else value, 6)


def destination_record(path: Path) -> dict | None:
    """The destination aerodrome row the OFP prints at the end of its navlog, with page and printed text."""
    document = fitz.open(str(path))
    try:
        pages = [page.get_text("text") for page in document]
    finally:
        document.close()
    # The OFP's destination identity comes from its page-1 plan, as the analysis reads it.
    destination = str(parse_lido(pages, path.name).get("destination") or "").upper()
    if not re.fullmatch(r"[A-Z]{4}", destination):
        return None
    started = False
    owner: tuple[str, int] | None = None
    for page_number, text in enumerate(pages, start=1):
        for raw in text.splitlines():
            line = raw.strip()
            if _HEADER.match(line):
                started = True
                continue
            if not started:
                continue
            row = _ROW.match(line)
            if row:
                owner = (row["name"], page_number) if row["name"] == destination else None
                continue
            coordinate = _COORDINATE.match(line)
            if coordinate and owner:
                printed = coordinate.group(0)
                return {
                    "icao": destination,
                    "latitude": _decimal(coordinate["lat_h"], coordinate["lat_d"], coordinate["lat_m"]),
                    "longitude": _decimal(coordinate["lon_h"], coordinate["lon_d"], coordinate["lon_m"]),
                    "source": {
                        "kind": "lido_ofp_destination_aerodrome_record",
                        "file": path.name,
                        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                        "page": owner[1],
                        "printed": f"{destination} {printed}",
                    },
                }
    return None


def build(corpus: Path) -> dict:
    records: dict[str, list[dict]] = {}
    for path in sorted(corpus.glob("*.pdf")):
        record = destination_record(path)
        if record:
            records.setdefault(record["icao"], []).append(record)
    aerodromes = {}
    for icao, held in sorted(records.items()):
        positions = {(item["latitude"], item["longitude"]) for item in held}
        if len(positions) != 1:
            raise SystemExit(f"{icao}: held OFP records disagree: {sorted(positions)}")
        latitude, longitude = positions.pop()
        aerodromes[icao] = {
            "latitude": latitude,
            "longitude": longitude,
            "sources": [item["source"] for item in held],
        }
    return {
        "schema_version": 1,
        "description": (
            "Governed aerodrome reference points for route maps. Each value is the operator's LIDO aerodrome "
            "record as printed on the destination row of a held OFP (0.1-minute resolution), pinned to its source "
            "file, SHA-256, page and printed text. Built by scripts/build_aerodrome_reference_points.py; "
            "tests cross-check every value against the State AIP aerodrome reference point."
        ),
        "aerodromes": aerodromes,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--check", action="store_true", help="fail if the committed table differs from the corpus")
    arguments = parser.parse_args()
    table = build(arguments.corpus)
    text = json.dumps(table, indent=1, sort_keys=True) + "\n"
    if arguments.check:
        current = arguments.output.read_text(encoding="utf-8") if arguments.output.is_file() else ""
        if current != text:
            print(f"{arguments.output} is not what the held corpus records", file=sys.stderr)
            return 1
        print(f"{arguments.output} matches the held corpus ({len(table['aerodromes'])} aerodromes)")
        return 0
    arguments.output.write_text(text, encoding="utf-8")
    print(f"wrote {len(table['aerodromes'])} aerodromes to {arguments.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

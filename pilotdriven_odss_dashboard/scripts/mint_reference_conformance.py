"""Mint the pinned publication structure from David's own reference briefings.

He sent them on 9 Sep 2026 at 21:17 and ruled "This format from beginning has
always been this. Get this right, and then we talk about tweaking from this."

The briefings themselves are operational documents and are kept outside git,
beside the private CFP corpus. What is committed is the *structure* read out of
them, together with the SHA-256 of each file it was read from, so the release
gate can prove the pinned structure still belongs to his document.

Usage::

    python scripts/mint_reference_conformance.py \
        --reference-dir ../output/pd-boss-09sep-review/reference \
        --output tests/boss_reference_format_manifest.json
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.odss.reference_conformance import (  # noqa: E402
    MANIFEST_GATE,
    MANIFEST_SCHEMA_VERSION,
    ReferenceConformanceError,
    extract_reference_structure,
    sha256_file,
)

# His 21:17 message carried four files. Only the two SQ910 renders are the
# six-page format he then walked through screenshot by screenshot ("Page 1 is
# good", the green circle on page 2); SQ481 REV5 (12 pages) and SQ38 (9 pages)
# are older shapes he did not point at. The dark/large-text variant is included
# because it proves which facts are the format and which are type scale.
PRIMARY = "SQ910_21AUG2026_Flight_Briefing.pdf"
CORROBORATING = ("SQ910_21AUG2026_DARK_LARGE_TEXT.pdf",)

# Declared separately from his structure. These are floors this codebase adds;
# a single document cannot evidence a minimum, and the A1 brief requires the
# ribbon on every page where his reference prints it on page 1 only.
CONTRACT_EXTENSIONS = {
    "nav_ribbon_on_every_page": True,
    "nav_ribbon_active_item_tracks_page": True,
    "analysis_timeline_minimum_stops": 3,
    "overview_route_panel_minimum_drawings": 20,
    "_why": {
        "nav_ribbon_on_every_page": (
            "His reference prints the ribbon on page 1 and the active section name in "
            "the masthead of pages 2-6. The 9 Sep fix round required the ribbon on "
            "every page, which is a superset of his file, so it is declared here "
            "rather than claimed as his ruling."
        ),
        "nav_ribbon_active_item_tracks_page": (
            "Derived in spirit from page 1, where exactly one ribbon item is "
            "emphasised; applied per page because the ribbon is now on every page."
        ),
        "analysis_timeline_minimum_stops": (
            "His timeline holds nine stops, but the count is flight-specific. Three "
            "is the structural floor: departure, at least one enroute gate, arrival."
        ),
        "overview_route_panel_minimum_drawings": (
            "His centre panel is a drawn schematic, not prose. One document cannot "
            "evidence a minimum vector count; 20 is the floor that separates a drawn "
            "route from an empty panel."
        ),
    },
}


def mint(reference_dir: Path) -> dict:
    primary_path = reference_dir / PRIMARY
    if not primary_path.is_file():
        raise ReferenceConformanceError(
            f"David's primary reference {PRIMARY} is not in {reference_dir}"
        )
    structure = extract_reference_structure(primary_path)
    minted_from = [
        {"filename": PRIMARY, "sha256": sha256_file(primary_path), "role": "primary"}
    ]
    tag_variants = {structure["overview"]["tile_provenance_tag"]}
    for name in CORROBORATING:
        path = reference_dir / name
        if not path.is_file():
            raise ReferenceConformanceError(
                f"Corroborating reference {name} is not in {reference_dir}"
            )
        other = extract_reference_structure(path)
        differences = [
            key
            for key in ("page_count", "nav_ribbon", "pages", "overview", "analysis")
            if _format_facts(other[key]) != _format_facts(structure[key])
        ]
        if differences:
            raise ReferenceConformanceError(
                f"{name} disagrees with {PRIMARY} on {', '.join(differences)}; "
                "the structure cannot be pinned until the disagreement is resolved"
            )
        tag_variants.add(other["overview"]["tile_provenance_tag"])
        minted_from.append(
            {"filename": name, "sha256": sha256_file(path), "role": "corroborating"}
        )
    structure["overview"]["tile_provenance_tag_variants"] = sorted(tag_variants)

    return {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "gate": MANIFEST_GATE,
        "provenance": (
            "Structure read out of David Chan's own reference Flight Briefings, sent "
            "9 Sep 2026 21:17 SGT with 'This format from beginning has always been "
            "this. Get this right, and then we talk about tweaking from this.' "
            "Re-mint with scripts/mint_reference_conformance.py; never hand-edit to "
            "match what we happen to render."
        ),
        "minted_from": minted_from,
        "reference_structure": structure,
        "contract_extensions": CONTRACT_EXTENSIONS,
    }


# Facts that his two renders of the SAME briefing legitimately disagree on, and
# why. Everything not listed here must match between them or the mint refuses.
TYPE_SCALE_FACTS = {
    # "CFP P1" is abbreviated to "P1" in the large-text render to hold the tile.
    "tile_provenance_tag",
    # Vector operation and stop counts are per-render and per-flight.
    "route_panel_reference_drawing_count",
    "timeline_reference_stop_count",
}


def _format_facts(value):
    """Drop the per-file values that are type scale or flight content."""
    if isinstance(value, dict):
        return {
            key: _format_facts(item)
            for key, item in value.items()
            if key not in TYPE_SCALE_FACTS
        }
    if isinstance(value, list):
        return [_format_facts(item) for item in value]
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=ROOT / "tests" / "boss_reference_format_manifest.json")
    args = parser.parse_args()
    try:
        manifest = mint(args.reference_dir)
    except (OSError, ReferenceConformanceError) as exc:
        print(f"Cannot mint the reference structure: {exc}", file=sys.stderr)
        return 1
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"Minted {args.output} from {len(manifest['minted_from'])} reference file(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

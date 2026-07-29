from __future__ import annotations

import importlib.util
from pathlib import Path


_SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "build_depress_profile_index.py"
)
_SPEC = importlib.util.spec_from_file_location("depress_profile_index_builder", _SCRIPT)
assert _SPEC and _SPEC.loader
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)


def test_effective_pages_parser_handles_wrapped_route_airway_and_deleted_row() -> None:
    text = "\n".join(
        (
            "                                  N199, M11, UM11/UR317,",
            "   8-7       TEMEL - RASAM                                  REBLO            24 NOV 2022       LH, ULR",
            "                                  UW71",
            "             63N140W -",
            "   11-3                           DCT                     63N140W          13 NOV 2020       LH, ULR",
            "             62N120W",
            "   50-8      DELETED               DELETED                       DELETED          12 JUN 2026",
        )
    )

    parsed = _MODULE.parse_effective_pages(text)

    assert parsed["deleted_count"] == 1
    assert len(parsed["rows"]) == 3
    assert parsed["profiles"][0] == {
        "chart": "8-7",
        "from": "TEMEL",
        "to": "RASAM",
        "from_aliases": ["TEMEL"],
        "to_aliases": ["RASAM"],
        "airways": ["N199", "M11", "UM11/UR317", "UW71"],
        "critical": "REBLO",
        "critical_aliases": ["REBLO"],
        "effective_date": "24 NOV 2022",
        "effectivity": ["LH", "ULR"],
        "chart_page": 22,
    }
    assert parsed["profiles"][1]["from"] == "63N140W"
    assert parsed["profiles"][1]["to"] == "62N120W"
    assert parsed["profiles"][1]["airways"] == ["DCT"]

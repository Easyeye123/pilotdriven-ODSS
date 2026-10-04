from __future__ import annotations

import ast
import re
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ODSS_SOURCE = PROJECT_ROOT / "app" / "odss"
PRESENTATION_MODULES = (
    "brief_theme.py",
    "briefing.py",
    "combined_brief.py",
    "depress_analysis_page.py",
    "depress_matrix_page.py",
    "engines.py",
    "flight_briefing_publication.py",
    "operational_brief.py",
    "pertinent_brief.py",
    "report_facts.py",
    "report_quality.py",
    "reporting.py",
    "surface_overlays.py",
    "timing.py",
    "visual_reporting.py",
    "weather_timing.py",
)
LEGACY_PRODUCT_TERM = re.compile(r"\bCFPs?\b")
RAW_SOURCE_HEADINGS = {
    "SUMMARY STANDARD CFP",
    "SUMMARY NON EDTO CFP",
    "SUMMARY EDTO CFP",
}


def _string_constants(path: Path) -> list[tuple[int, str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return [
        (node.lineno, node.value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    ]


def test_generated_presentation_language_uses_ofp_not_cfp() -> None:
    hits: list[str] = []
    for module_name in PRESENTATION_MODULES:
        module_path = ODSS_SOURCE / module_name
        for line_number, value in _string_constants(module_path):
            if LEGACY_PRODUCT_TERM.search(value) and value not in RAW_SOURCE_HEADINGS:
                hits.append(f"{module_name}:{line_number}: {value!r}")

    static_map = PROJECT_ROOT / "app" / "static" / "odss-maplibre-v06.js"
    for line_number, line in enumerate(
        static_map.read_text(encoding="utf-8").splitlines(),
        start=1,
    ):
        if LEGACY_PRODUCT_TERM.search(line):
            hits.append(f"odss-maplibre-v06.js:{line_number}: {line.strip()!r}")

    assert hits == [], "Retired pilot-facing CFP labels:\n" + "\n".join(hits)


def test_parser_errors_say_ofp_while_source_detection_stays_compatible() -> None:
    parser_path = ODSS_SOURCE / "parser.py"
    tree = ast.parse(parser_path.read_text(encoding="utf-8"), filename=str(parser_path))
    hits: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Raise) or not isinstance(node.exc, ast.Call):
            continue
        if not isinstance(node.exc.func, ast.Name) or node.exc.func.id != "ValueError":
            continue
        rendered = ast.unparse(node.exc)
        if LEGACY_PRODUCT_TERM.search(rendered):
            hits.append(f"parser.py:{node.lineno}: {rendered}")

    source = parser_path.read_text(encoding="utf-8")
    assert hits == [], "Retired CFP wording in user-facing parser errors:\n" + "\n".join(hits)
    assert "SUMMARY(?:\\s+STANDARD)?\\s+CFP" in source
    assert "SUMMARY\\s+(STANDARD|NON\\s+EDTO|EDTO)\\s+CFP" in source

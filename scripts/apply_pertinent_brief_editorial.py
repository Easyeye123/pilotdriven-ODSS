from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)


root = Path("pilotdriven_odss_dashboard")

reporting_path = root / "app/odss/reporting.py"
reporting = reporting_path.read_text(encoding="utf-8")
reporting = replace_once(
    reporting,
    "from .visual_reporting import PAGE_SIZE, render_level1_visual, visual_cover_flowable\n",
    "from .pertinent_brief import render_level1_visual\n"
    "from .visual_reporting import PAGE_SIZE, visual_cover_flowable\n",
    "reporting import",
)
reporting_path.write_text(reporting, encoding="utf-8")

briefing_path = root / "app/odss/briefing.py"
briefing = briefing_path.read_text(encoding="utf-8")
briefing = replace_once(
    briefing,
    '"destination": "#4db8ff",',
    '"destination": "#7c4dff",',
    "SVG destination colour",
)
briefing = replace_once(
    briefing,
    '"destination": colors.HexColor("#4DB8FF"),',
    '"destination": colors.HexColor("#7C4DFF"),',
    "PDF destination colour",
)
briefing_path.write_text(briefing, encoding="utf-8")

pertinent_path = root / "app/odss/pertinent_brief.py"
pertinent = pertinent_path.read_text(encoding="utf-8")
pertinent = replace_once(
    pertinent,
    '    top = _draw_page_title(canvas, briefing, width, height, "OPERATIONAL DETAIL", 2)\n',
    '    top = _draw_page_title(\n'
    '        canvas,\n'
    '        briefing,\n'
    '        width,\n'
    '        height,\n'
    '        f"{briefing[\'flight_number\']} - OPERATIONAL DETAIL",\n'
    '        2,\n'
    '    )\n',
    "operational detail title",
)
pertinent = replace_once(
    pertinent,
    '    top = _draw_page_title(canvas, briefing, width, height, "ROUTE / CONTINGENCY", 3)\n',
    '    top = _draw_page_title(\n'
    '        canvas,\n'
    '        briefing,\n'
    '        width,\n'
    '        height,\n'
    '        f"{briefing[\'flight_number\']} - ROUTE / CONTINGENCY",\n'
    '        3,\n'
    '    )\n',
    "route detail title",
)
pertinent_path.write_text(pertinent, encoding="utf-8")

tests_path = root / "tests/test_reporting_regressions.py"
tests = tests_path.read_text(encoding="utf-8")
tests = replace_once(
    tests,
    "from app.odss.reporting import render_pdf, report_sections\n",
    "from app.odss.pertinent_brief import CATEGORY_COLOURS\n"
    "from app.odss.reporting import render_pdf, report_sections\n",
    "test import",
)
tests = replace_once(
    tests,
    '    assert "REVIEW REQUIRED" in first\n'
    '    assert "BRIEFING COMPLETE" not in first\n',
    '    assert "REVIEW REQUIRED" not in first\n'
    '    assert "BRIEFING COMPLETE" not in first\n'
    '    assert "Decision support only" not in first\n'
    '    assert "Decision support only" not in second\n'
    '    assert "Decision support only" not in third\n',
    "Level 1 status assertions",
)
tests = replace_once(
    tests,
    '    assert "MEL / CDL / CDDL" in second\n'
    '    assert "PERFORMANCE / FUEL" in second\n'
    '    assert "WEATHER / PERTINENT NOTAM" in second\n'
    '    assert "SQ304 - ROUTE / CONTINGENCY" in third\n'
    '    assert "FIR / COMMUNICATIONS" in third\n'
    '    assert "TERRAIN MSA / VWS" in third\n'
    '    assert "DEPRESSURISATION PROFILES" in third\n'
    '    assert "High terrain detected but no profile matched" in third\n'
    '    assert "Manual chart-index review is required" in third\n'
    '    assert "ACTM / CALCULATED UTC TIMELINE" in third\n',
    '    assert "MEL / CDL / CDDL" not in second\n'
    '    assert "PERFORMANCE / FUEL" not in second\n'
    '    assert "WEATHER / PERTINENT NOTAM" in second\n'
    '    assert "SQ304 - ROUTE / CONTINGENCY" in third\n'
    '    assert "FIR / COMMUNICATIONS" not in third\n'
    '    assert "TERRAIN MSA / VWS" in third\n'
    '    assert "DEPRESSURISATION PROFILES" in third\n'
    '    assert "High terrain detected but no profile matched" in third\n'
    '    assert "Manual chart-index review is required" in third\n'
    '    assert "ACTM / CALCULATED UTC" not in third\n',
    "floating section assertions",
)

append = r'''


def test_pilot_brief_category_colours_are_distinct_and_stable() -> None:
    assert CATEGORY_COLOURS == {
        "departure": "#2F80ED",
        "destination": "#7C4DFF",
        "edto": "#2EAD74",
        "weather": "#D99116",
        "communications": "#0F8B8D",
        "terrain": "#D97706",
        "critical": "#C62828",
        "neutral": "#64748B",
    }
    assert CATEGORY_COLOURS["departure"] != CATEGORY_COLOURS["destination"]


def test_level1_integrates_volcanic_ash_without_source_gate_page(
    tmp_path: Path,
) -> None:
    path = tmp_path / "level_1_vaa.pdf"
    flight = _flight()
    flight["vaa_review"] = {
        "status": "affected",
        "provider": "Anchorage VAAC",
        "retrieved_at_utc": "2026-07-22T07:00:00+00:00",
        "matches": [],
        "hazard_features": [],
    }
    findings = [
        {
            "engine": "vaa",
            "severity": "critical",
            "title": "Sheveluch volcanic ash proximity",
            "summary": "Time-matched route screening requires operational action.",
            "details": [
                "Closest route sector TED-GKN at 1551Z.",
                "PANC EDTO suitability requires the latest advisory.",
            ],
            "data": {},
        }
    ]

    render_pdf(flight, findings, [], 1, path)

    reader = PdfReader(path)
    assert len(reader.pages) == 3
    text = "\n".join((page.extract_text() or "") for page in reader.pages)
    assert "ENROUTE WEATHER / VAAC" in text
    assert "Sheveluch volcanic ash proximity" in text
    assert "SOURCE / PROVENANCE" not in text
    assert "MANUAL REVIEW REQUIRED" not in text
'''
if "def test_pilot_brief_category_colours_are_distinct_and_stable" not in tests:
    tests = tests.rstrip() + append + "\n"
tests_path.write_text(tests, encoding="utf-8")

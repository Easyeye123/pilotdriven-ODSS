from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one match, found {count}")
    return text.replace(old, new, 1)


root = Path("pilotdriven_odss_dashboard")

renderer_path = root / "app/odss/pertinent_brief.py"
renderer = renderer_path.read_text(encoding="utf-8")
renderer = replace_once(
    renderer,
    '''def _note_lines(flight: dict[str, Any], placements: set[str]) -> list[str]:
    return [
        f"Personal note: {' '.join(str(note.get('note_text') or '').split())}"
        for note in (flight.get("personal_notes") or [])
        if note.get("placement") in placements and note.get("include_level1")
    ]
''',
    '''def _note_lines(flight: dict[str, Any], placements: set[str]) -> list[str]:
    lines = [
        f"Personal note: {' '.join(str(note.get('note_text') or '').split())}"
        for note in (flight.get("personal_notes") or [])
        if note.get("placement") in placements and note.get("include_level1")
    ]
    if lines:
        lines.append("Pilot-entered content; not ODSS-validated.")
    return lines
''',
    "personal-note identification",
)
renderer = replace_once(
    renderer,
    '''    edto_bobcat = grouped.get("edto", []) + grouped.get("bobcat", [])
    vaa_weather = grouped.get("vaa", []) + [
''',
    '''    edto_bobcat = grouped.get("edto", []) + grouped.get("bobcat", [])
    edto_view = briefing.get("edto") or {}
    edto_summary_lines: list[str] = []
    if edto_view.get("entry") != "--.--" or edto_view.get("exit") != "--.--":
        edto_summary_lines.append(
            f"EDTO ACTM {edto_view.get('entry') or '--.--'} - {edto_view.get('exit') or '--.--'}"
        )
    if edto_view.get("etps"):
        edto_summary_lines.append("ETP: " + ", ".join(edto_view["etps"]))
    edto_summary_lines.extend(
        f"{item['airport']} | {item['period']} | RWY {item['runway']} {item['approach']}"
        for item in edto_view.get("airports", [])[:4]
    )
    edto_bobcat_lines = (
        _finding_lines(edto_bobcat, finding_limit=6, detail_limit=2)
        + edto_summary_lines
    )
    vaa_weather = grouped.get("vaa", []) + [
''',
    "EDTO structured summary",
)
renderer = replace_once(
    renderer,
    '''            {"title": "EDTO / BOBCAT", "lines": _finding_lines(edto_bobcat, finding_limit=6, detail_limit=2), "accent": _EDTO},
''',
    '''            {"title": "EDTO / BOBCAT", "lines": edto_bobcat_lines, "accent": _EDTO},
''',
    "EDTO panel lines",
)
renderer_path.write_text(renderer, encoding="utf-8")

vaa_tests_path = root / "tests/test_vaa.py"
vaa_tests = vaa_tests_path.read_text(encoding="utf-8")
vaa_tests = replace_once(
    vaa_tests,
    '''@pytest.mark.parametrize("status", ["review_required", "affected"])
def test_level1_adds_conditional_vaa_page(status: str, tmp_path: Path) -> None:
    flight = _flight()
    review = evaluate_vaa(
        flight,
        _snapshot([_advisory()])
        if status == "affected"
        else _snapshot([], coverage_status="global_current_active_sigmet"),
    )
    assert review["status"] == status
    flight["vaa_review"] = review
    path = tmp_path / f"{status}.pdf"

    render_pdf(flight, [_vaa_finding(status)], [], 1, path)
    reader = PdfReader(path)
    page4 = reader.pages[3].extract_text() or ""

    assert len(reader.pages) == 4
    assert "VOLCANIC ASH ADVISORY REVIEW" in page4
    assert ("ROUTE AFFECTED" if status == "affected" else "MANUAL REVIEW REQUIRED") in page4
    assert "authority.example" in page4
    if status == "affected":
        assert "22 JUL 0400Z-22 JUL 0600Z" in page4
''',
    '''@pytest.mark.parametrize("status", ["review_required", "affected"])
def test_level1_integrates_conditional_vaa_on_route_page(
    status: str,
    tmp_path: Path,
) -> None:
    flight = _flight()
    review = evaluate_vaa(
        flight,
        _snapshot([_advisory()])
        if status == "affected"
        else _snapshot([], coverage_status="global_current_active_sigmet"),
    )
    assert review["status"] == status
    flight["vaa_review"] = review
    path = tmp_path / f"{status}.pdf"

    render_pdf(flight, [_vaa_finding(status)], [], 1, path)
    reader = PdfReader(path)
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    page3 = reader.pages[2].extract_text() or ""

    assert len(reader.pages) == 3
    assert "ENROUTE WEATHER / VAAC" in page3
    assert (
        "Volcanic ash affects the planned route"
        if status == "affected"
        else "Volcanic ash review required"
    ) in page3
    assert "VOLCANIC ASH ADVISORY REVIEW" not in text
    assert "SOURCE / PROVENANCE" not in text
    assert "MANUAL REVIEW REQUIRED" not in text
''',
    "three-page VAA regression",
)
vaa_tests_path.write_text(vaa_tests, encoding="utf-8")

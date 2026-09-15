"""The release gate that answers "How do you ensure that???".

9 Sep 2026, 21:22:46 - 21:22:52, David Chan::

    "So you have to check and make sure the memory losses and standard
    established does not degenerate."
    "How do you ensure that???"

The answer in place on 15 Sep 2026 was the SQ214 REV3 raster gate. It replays
``include_audit_appendix=True`` - the internal lossless composition that no
production download calls - for one flight, from a frozen analysis capture,
against a reference minted from *our own* render. Every value it compares is
ours. The published download could drift entirely away from his format and that
gate would still print "passed".

These tests pin the other end. The structure comes out of his own reference
briefings; the candidate comes out of the exact call ``app/main.py`` makes when
a pilot presses Download PDF; and a deliberately drifted render has to be
rejected, one named violation per kind of drift.
"""
from __future__ import annotations

import json
from pathlib import Path

import fitz
import pytest

from app.odss import reference_conformance as conformance
from app.odss.concise_pdf_gate import NAV_RIBBON, PAGE_TITLES, normalized


ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT.parent / "private_cfp_corpus"
MANIFEST_PATH = ROOT / "tests" / "boss_reference_format_manifest.json"
# The reference briefings themselves are operational documents and live outside
# git beside the corpus. Point PILOTDRIVEN_BOSS_REFERENCE_DIR at them, or leave
# the review folder where the 9 Sep round put them.
# Checked out directly (…/pilotdriven-ODSS/pilotdriven_odss_dashboard) and from
# a worktree (…/.work/<name>/pilotdriven_odss_dashboard) the review folder sits
# at a different depth, so both are tried before the tests give up and skip.
REFERENCE_DIRS = tuple(
    parent / "output" / "pd-boss-09sep-review" / "reference"
    for parent in ROOT.parents[1:4]
) + (ROOT.parent / "boss_reference_briefings",)

# The flights this round is about: his reference flight, the flight he said had
# "degenerated to somewhat much simpler and less user friendly", and the saved
# pack he drove on video the same evening.
CONFORMANCE_CASES = {
    "SQ910": "SQ91021082026SIN.pdf",
    "SQ605": "SQ60508092026ICN.pdf",
    "SQ882": "lido-briefing_SQ_882_09Sep2026_SIN_HKG.pdf",
}
DRIFT_CASE = "SQ910"


def reference_dir() -> Path | None:
    import os

    override = os.environ.get("PILOTDRIVEN_BOSS_REFERENCE_DIR")
    candidates = [Path(override)] if override else []
    candidates.extend(REFERENCE_DIRS)
    for candidate in candidates:
        if (candidate / "SQ910_21AUG2026_Flight_Briefing.pdf").is_file():
            return candidate
    return None


@pytest.fixture(scope="session")
def manifest() -> dict:
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


_RENDERED: dict[str, Path] = {}


def production_download(flight_key: str, tmp_path_factory) -> Path:
    """Render through the exact call the Download PDF button makes."""
    if flight_key in _RENDERED:
        return _RENDERED[flight_key]
    source = CORPUS / CONFORMANCE_CASES[flight_key]
    if not source.is_file():
        pytest.skip(f"private CFP corpus file {CONFORMANCE_CASES[flight_key]} is not available")
    from app.analysis import run_odss_analysis
    from app.odss.combined_brief import render_combined_briefing

    root = tmp_path_factory.mktemp(f"conformance-{flight_key}")
    result = run_odss_analysis(source, root / "analysis", root / "reports", 1)
    payload = json.loads(Path(result["analysis_path"]).read_text(encoding="utf-8"))
    candidate = root / f"{flight_key}_Flight_Briefing.pdf"
    render_combined_briefing(
        payload["flight"],
        payload["findings"],
        payload.get("view", {}).get("warnings") or [],
        candidate,
        source_pdf_path=str(source),
        weather_charts=payload.get("weather_charts") or {},
    )
    _RENDERED[flight_key] = candidate
    return candidate


@pytest.fixture(scope="session", params=sorted(CONFORMANCE_CASES))
def download(request, tmp_path_factory) -> Path:
    return production_download(request.param, tmp_path_factory)


@pytest.fixture(scope="session")
def drift_source(tmp_path_factory) -> Path:
    return production_download(DRIFT_CASE, tmp_path_factory)


def check(candidate: Path, manifest: dict) -> dict:
    return conformance.check_reference_conformance(
        candidate,
        structure=manifest["reference_structure"],
        contract_extensions=manifest.get("contract_extensions") or {},
    )


def codes(result: dict) -> list[str]:
    return [violation["code"] for violation in result["violations"]]


# ---------------------------------------------------------------------------
# The structure is his, not ours
# ---------------------------------------------------------------------------


def test_the_pinned_structure_names_the_files_it_came_from(manifest):
    assert manifest["gate"] == conformance.MANIFEST_GATE
    assert manifest["schema_version"] == conformance.MANIFEST_SCHEMA_VERSION
    minted = manifest["minted_from"]
    assert [entry["role"] for entry in minted][:1] == ["primary"]
    assert minted[0]["filename"] == "SQ910_21AUG2026_Flight_Briefing.pdf"
    for entry in minted:
        assert len(entry["sha256"]) == 64
    # Every declared extension says, in the manifest itself, why it is ours.
    extensions = manifest["contract_extensions"]
    for key in extensions:
        if key.startswith("_"):
            continue
        assert key in extensions["_why"], f"{key} is asserted without saying whose rule it is"


def test_the_pinned_structure_is_still_his_file():
    """Re-derive it from his PDF; a hand-edited manifest fails here."""
    directory = reference_dir()
    if directory is None:
        pytest.skip("David's reference briefings are not available in this checkout")
    from scripts.check_reference_conformance import (
        load_manifest,
        verify_against_reference_files,
    )

    checked = verify_against_reference_files(load_manifest(MANIFEST_PATH), directory)
    assert [entry["filename"] for entry in checked] == [
        "SQ910_21AUG2026_Flight_Briefing.pdf",
        "SQ910_21AUG2026_DARK_LARGE_TEXT.pdf",
    ]


def test_the_gate_accepts_his_own_reference_briefing(manifest):
    """The decisive property: his file passes the gate that guards ours.

    A gate pinned to our render cannot make this assertion at all.
    """
    directory = reference_dir()
    if directory is None:
        pytest.skip("David's reference briefings are not available in this checkout")
    for name in (
        "SQ910_21AUG2026_Flight_Briefing.pdf",
        "SQ910_21AUG2026_DARK_LARGE_TEXT.pdf",
    ):
        result = conformance.check_reference_conformance(
            directory / name, structure=manifest["reference_structure"],
            # His own file predates the ribbon-on-every-page requirement.
            contract_extensions={},
        )
        assert result["valid"], (name, result["violations"])


def test_the_gate_rejects_the_shapes_he_moved_off(manifest):
    """SQ38 is nine pages and SQ481 REV5 is twelve; six is the format."""
    directory = reference_dir()
    if directory is None:
        pytest.skip("David's reference briefings are not available in this checkout")
    for name in ("SQ38_28AUG2026_Flight_Briefing.pdf", "SQ481_25AUG2026_REV5.pdf"):
        result = conformance.check_reference_conformance(
            directory / name, structure=manifest["reference_structure"],
            contract_extensions={},
        )
        assert not result["valid"]
        assert "PAGE_COUNT" in codes(result)


def test_our_publication_constants_still_spell_his_sections(manifest):
    """The one drift no gate built on our own constants can see.

    ``PAGE_TITLES`` and ``NAV_RIBBON`` are what the existing publication check
    compares against. Rename a section there and that check keeps passing.
    Here they have to agree with the structure read out of his document.
    """
    structure = manifest["reference_structure"]
    assert list(NAV_RIBBON) == structure["nav_ribbon"]
    assert len(PAGE_TITLES) == structure["page_count"]
    for index, title in enumerate(PAGE_TITLES):
        allowed = {normalized(item) for item in structure["pages"][index]["titles"]}
        assert normalized(title) in allowed, (
            f"page {index + 1} is published as {title!r}, which is not one of "
            f"David's own titles for that page: {sorted(allowed)}"
        )


# ---------------------------------------------------------------------------
# The production download conforms
# ---------------------------------------------------------------------------


def test_the_production_download_matches_his_format(download, manifest):
    result = check(download, manifest)
    assert result["valid"], result["violations"]


def test_the_download_publishes_his_whole_column_field_labels(download, manifest):
    """His destination column reads TAF TEMPO; a bare TAF is drift, not a synonym.

    Fix round 1 finding: the column check only ever compared the first word of
    each of his labels, so ``TAF TEMPO`` shrinking to ``TAF`` was accepted and
    the gate published ``valid=True`` over a live disagreement with his file.
    Binding rule 7 - the reference wins - so the label is pinned whole, here
    against the real production render.
    """
    expected = manifest["reference_structure"]["overview"]["column_fields"]
    with fitz.open(download) as document:
        spans = conformance.page_spans(document[0])
    published = {span.folded for span in spans}
    missing = {
        role: [label for label in labels if conformance.normalized(label) not in published]
        for role, labels in expected.items()
    }
    assert not any(missing.values()), (
        f"page 1 does not print David's whole field label(s): {missing}"
    )


def test_the_gate_reads_the_download_the_button_renders(monkeypatch, tmp_path):
    """Never the audit composition: he does not download that artefact."""
    from scripts import check_reference_conformance as gate

    calls = []

    def fake_analysis(source, analysis_dir, report_dir, flight_id):
        Path(analysis_dir).mkdir(parents=True, exist_ok=True)
        path = Path(analysis_dir) / "analysis.json"
        path.write_text(json.dumps({"flight": {}, "findings": [], "view": {"warnings": []}}))
        return {"analysis_path": str(path)}

    def fake_render(flight, findings, warnings, candidate, **kwargs):
        calls.append(kwargs)
        Path(candidate).write_bytes(b"%PDF-1.4 rendered")

    import app.analysis
    import app.odss.combined_brief

    monkeypatch.setattr(app.analysis, "run_odss_analysis", fake_analysis)
    monkeypatch.setattr(app.odss.combined_brief, "render_combined_briefing", fake_render)
    source = tmp_path / "source.pdf"
    source.write_bytes(b"%PDF-1.4 source")
    gate.render_production_download(source, tmp_path / "work", "CASE")
    assert len(calls) == 1
    assert calls[0].get("include_audit_appendix") in (None, False)
    assert "include_audit_appendix" not in calls[0]


# ---------------------------------------------------------------------------
# Drift is rejected - one named violation per kind of degeneration
# ---------------------------------------------------------------------------


def _raw_spans(page) -> list[dict]:
    return [
        span
        for block in page.get_text("dict")["blocks"]
        for line in block.get("lines", [])
        for span in line["spans"]
        if span["text"].strip()
    ]


def _erase(page, spans) -> None:
    for span in spans:
        page.add_redact_annot(fitz.Rect(span["bbox"]))
    page.apply_redactions()


def _drifted(source: Path, tmp_path: Path, name: str, mutate) -> Path:
    target = tmp_path / f"{name}.pdf"
    with fitz.open(source) as document:
        mutate(document)
        document.save(target)
    return target


def _remove_a_page(document) -> None:
    document.delete_page(3)


def _rename_the_decision_page(document) -> None:
    page = document[1]
    title = [
        span
        for span in _raw_spans(page)
        if normalized(span["text"]) == normalized("DECISION ANALYSIS")
    ]
    origin = title[0]["origin"]
    size = title[0]["size"]
    _erase(page, title)
    page.insert_text(origin, "FLIGHT SUMMARY", fontsize=size, fontname="hebo")


def _drop_the_ribbon(document) -> None:
    page = document[2]
    wanted = {normalized(item) for item in NAV_RIBBON}
    _erase(page, [span for span in _raw_spans(page) if normalized(span["text"]) in wanted])


def _misplace_the_active_ribbon_item(document) -> None:
    page = document[2]
    target = [
        span
        for span in _raw_spans(page)
        if normalized(span["text"]) == normalized(NAV_RIBBON[4]) and span["size"] < 11
    ]
    origin, size = target[0]["origin"], target[0]["size"]
    _erase(page, target[:1])
    page.insert_text(origin, NAV_RIBBON[4], fontsize=size, fontname="hebo")


def _shrink_a_column_field_to_its_first_word(label: str):
    """A page-1 column field loses everything after its first word.

    This is the exact degeneration the first-word comparison accepted: the
    label still *starts* with the reference word, so a head-word check cannot
    see it. Nothing is removed from the page, only shortened. Both of the
    reference labels that carry a second word are exercised - his
    ``TAF TEMPO`` shrinking to ``TAF`` is the one that was live in our render,
    and ``EET / SCHED`` shrinking to ``EET`` is the same mechanism on the other
    multi-word field.
    """

    def mutate(document) -> None:
        page = document[0]
        wanted = normalized(label)
        targets = sorted(
            (span for span in _raw_spans(page) if normalized(span["text"]) == wanted),
            key=lambda span: span["bbox"][0],
            reverse=True,
        )
        if not targets:
            # The render already publishes a shrunken label, which is the drift
            # itself: leave the page alone and require the gate to reject it as
            # it stands. test_the_download_publishes_his_whole_column_field_labels
            # is the test that names that case directly.
            return
        origin, size = targets[0]["origin"], targets[0]["size"]
        _erase(page, targets[:1])
        page.insert_text(origin, wanted.split(" ")[0], fontsize=size, fontname="hebo")

    return mutate


def _erase_on_page_one(matcher):
    def mutate(document) -> None:
        page = document[0]
        _erase(page, [span for span in _raw_spans(page) if matcher(span)])

    return mutate


def _erase_on_page_two(matcher):
    def mutate(document) -> None:
        page = document[1]
        _erase(page, [span for span in _raw_spans(page) if matcher(span)])

    return mutate


DRIFTS = {
    "a-page-removed": (_remove_a_page, "PAGE_COUNT"),
    "a-section-renamed": (_rename_the_decision_page, "PAGE_TITLE"),
    "the-ribbon-dropped": (_drop_the_ribbon, "NAV_RIBBON"),
    "the-wrong-ribbon-item-active": (_misplace_the_active_ribbon_item, "NAV_RIBBON_ACTIVE"),
    "a-page-1-tile-gone": (
        _erase_on_page_one(lambda span: normalized(span["text"]) == "TECH STATUS"),
        "OVERVIEW_TILES",
    ),
    "the-tile-provenance-tags-gone": (
        _erase_on_page_one(lambda span: normalized(span["text"]) == "CFP P1"),
        "OVERVIEW_TILE_TAGS",
    ),
    "the-release-strip-gone": (
        _erase_on_page_one(
            lambda span: normalized(span["text"]) in {"RELEASE", "BEFORE PUSH", "ARRIVAL"}
        ),
        "OVERVIEW_STRIP",
    ),
    "a-taf-tempo-field-shrunk-to-its-first-word": (
        _shrink_a_column_field_to_its_first_word("TAF TEMPO"),
        "OVERVIEW_COLUMN_FIELDS",
    ),
    "an-eet-sched-field-shrunk-to-its-first-word": (
        _shrink_a_column_field_to_its_first_word("EET / SCHED"),
        "OVERVIEW_COLUMN_FIELDS",
    ),
    "a-destination-column-field-gone": (
        _erase_on_page_one(
            lambda span: normalized(span["text"]) == "EET SCHED"
        ),
        "OVERVIEW_COLUMN_FIELDS",
    ),
    "the-route-panel-heading-gone": (
        _erase_on_page_one(
            lambda span: normalized(span["text"])
            == normalized("CFP ROUTE - PERTINENT DECISION GATES")
        ),
        "OVERVIEW_ROUTE_PANEL",
    ),
    "the-severity-pills-gone": (
        _erase_on_page_two(lambda span: span["text"].strip() in {"MAJOR", "MODERATE"}),
        "ANALYSIS_SEVERITY_PILL",
    ),
    "the-decision-timeline-gone": (
        _erase_on_page_two(
            lambda span: normalized(span["text"]) == normalized("FLIGHT-PHASE DECISION TIMELINE")
        ),
        "ANALYSIS_TIMELINE",
    ),
}


@pytest.mark.parametrize("name", sorted(DRIFTS))
def test_the_gate_fails_on_a_drifted_render(name, drift_source, manifest, tmp_path):
    mutate, expected = DRIFTS[name]
    candidate = _drifted(drift_source, tmp_path, name, mutate)
    result = check(candidate, manifest)
    assert not result["valid"], f"{name} was accepted"
    assert expected in codes(result), (name, codes(result))


def test_the_gate_fails_when_the_footer_identity_is_dropped(drift_source, manifest, tmp_path):
    def mutate(document) -> None:
        for page in document:
            height = page.rect.height
            _erase(
                page,
                [
                    span
                    for span in _raw_spans(page)
                    if span["bbox"][1] > height - 45 and "OFP" in span["text"]
                ],
            )

    candidate = _drifted(drift_source, tmp_path, "footer-identity", mutate)
    result = check(candidate, manifest)
    assert not result["valid"]
    assert "FOOTER_IDENTITY" in codes(result)


def test_the_gate_fails_when_a_page_loses_its_assurance_lead(drift_source, manifest, tmp_path):
    lead = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    target = lead["reference_structure"]["pages"][1]["footer_assurance_lead"]

    def mutate(document) -> None:
        page = document[1]
        _erase(
            page,
            [span for span in _raw_spans(page) if normalized(target) in normalized(span["text"])],
        )

    candidate = _drifted(drift_source, tmp_path, "assurance-lead", mutate)
    result = check(candidate, manifest)
    assert not result["valid"]
    assert "FOOTER_ASSURANCE" in codes(result)


def test_an_unmodified_render_is_still_accepted_after_the_drift_round(drift_source, manifest):
    """Guards the drift helpers themselves: they must not poison the source."""
    assert check(drift_source, manifest)["valid"]

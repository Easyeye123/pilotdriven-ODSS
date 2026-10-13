"""QA496-01: the Flight Briefing PDF pilots download links every cited MEL/CDL/CDDL item.

Codex's independent production QA of release 496 (13 Oct 2026) downloaded
four fresh Flight Briefings (SQ223, SQ303, SQ23, B787 SQ279): six pages, 28
internal page jumps, zero external links. SQ223 page 3 names MEL 25-20-50A
with no link while the dashboard opens approved p. 771. Since 8 Sep 2026
(a3c86fa) pilots download the analysed six-page publication
(operational_format.render_analysed_briefing); the durable governed-source
link (combined_brief.governed_deferred_source_target) was printed only by the
older reference/audit layout, and every link check ran on that layout. So
these tests read the ACTUAL generated six-page PDF's link annotations.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import fitz
import pytest

from app.analysis import run_odss_analysis
from app.odss.combined_brief import render_combined_briefing
from app.odss.concise_pdf_gate import MAX_BRIEFING_PAGES
from app.odss.governed_deferred_extract import normalize_governed_deferred_reference_payload

CORPUS = Path(__file__).resolve().parents[2] / "private_cfp_corpus"
GOVERNED = {"MEL", "CDL", "CDDL"}
ROUTE = "governed-deferred-reference"
HANDLE_A = "ref-696ec718b88f2571c9316b9267136253557953ce"  # opaque revision handle shape
HANDLE_B = "ref-2222222222222222222222222222222222222222"
MEL_TITLE = "A350 Minimum Equipment List — SIA A350 Fleet"
A350 = {"scope": "specified", "fleet": None, "aircraft": "A350-900", "status": "confirmed"}


@pytest.fixture(autouse=True)
def _no_live_sources(monkeypatch):
    for name in ("ODSS_VA_SIGMET_SOURCE", "ODSS_SIGMET_SOURCE", "ODSS_OPMET_SOURCE",
                 "ODSS_TC_TRACK_SOURCE", "ODSS_TC_SIGMET_SOURCE", "ODSS_ADWX_SOURCE",
                 "ODSS_WEATHER_CHART_AI"):
        monkeypatch.setenv(name, "disabled")
    monkeypatch.delenv("PILOTDRIVEN_PUBLIC_ORIGIN", raising=False)
    monkeypatch.delenv("PILOTDRIVEN_PUBLIC_ORIGINS", raising=False)


def _analyse(tmp_path: Path, name: str) -> dict:
    source = CORPUS / name
    if not source.is_file():
        pytest.skip("the private OFP corpus is not available")
    result = run_odss_analysis(source, tmp_path / "analysis", tmp_path / "legacy", 1)
    payload = json.loads(Path(result["analysis_path"]).read_text(encoding="utf-8"))
    payload["source"] = str(source)
    return payload


def _render(tmp_path: Path, payload: dict, references=None, name: str = "briefing.pdf", public_origin=None) -> Path:
    target = tmp_path / name
    render_combined_briefing(
        payload["flight"], payload["findings"], payload.get("view", {}).get("warnings") or [],
        target, source_pdf_path=payload["source"],
        weather_charts=payload.get("weather_charts") or {},
        company_briefing_references=references,
        public_origin=public_origin,
    )
    return target


def _governed_links(pdf: Path) -> list[dict]:
    rows = []
    with fitz.open(pdf) as document:
        assert document.page_count == MAX_BRIEFING_PAGES
        for page in document:
            for link in page.get_links():
                uri = str(link.get("uri") or "")
                if not uri:
                    continue
                fragment, _, query = urlsplit(uri).fragment.partition("?")
                assert fragment == f"/{ROUTE}", f"unexpected external link {uri}"
                params = {key: values[0] for key, values in parse_qs(query).items()}
                parts = urlsplit(uri)
                rows.append({**params, "uri": uri, "origin": f"{parts.scheme}://{parts.netloc}", "pdf_page": page.number + 1,
                             "text": " ".join(page.get_textbox(link["from"]).split())})
    return rows


def _cited(flight: dict) -> list[tuple[str, str]]:
    return list(dict.fromkeys(
        (str(item.get("item_type") or "").upper(), str(item.get("reference") or "").upper())
        for item in flight.get("deferred_items") or []
        if str(item.get("item_type") or "").upper() in GOVERNED and item.get("reference")
    ))


def _passage(page: int, section: str, excerpt: str, handle: str = HANDLE_A, version: str = "Revision 39 · issued 18 Nov 2025") -> dict:
    return {
        "excerpt": excerpt,
        "citation": {
            "sourceClass": "company_manual", "documentTitle": MEL_TITLE, "version": version,
            "effectiveDate": "2025-11-18", "page": str(page), "section": section,
            "applicability": dict(A350), "sourceId": handle,
            "safeTarget": f"/api/help-you/references/{handle}/open?revision=Revision+39&effectiveDate=2025-11-18&page={page}",
        },
    }


@pytest.mark.parametrize("name", [
    "lido-briefing_SQ_223_16Aug2026_SIN_PER.pdf",    # David's SQ223: MEL 25-20-50A twice
    "SQ30316072026BRU 81.pdf",                       # MEL 44-15-02A on two approved pages, MEL + CDL
    "lido-briefing_SQ_882_10Sep2026_SIN_HKG.pdf",    # seven declarations, six governed
    "lido-briefing_SQ_279_15Aug2026_SIN_ADL.pdf",    # B787: no approved MEL in the library
    "SQ02325072026JFK.pdf",                          # no deferred item at all
])
def test_the_downloaded_six_page_pdf_links_every_cited_governed_item(tmp_path, name):
    payload = _analyse(tmp_path, name)
    links = _governed_links(_render(tmp_path, payload))
    cited = _cited(payload["flight"])
    linked = {(row["type"], row["reference"]) for row in links}
    assert set(cited) == linked, f"{name}: cited {cited}, linked {sorted(linked)}"
    for row in links:
        # Linked from the TECHNICAL STATUS card, as visible link text, on the
        # canonical apex when no requesting origin is stated.
        assert row["origin"] == "https://pilotdriven.com", row
        assert row["pdf_page"] == 3, row
        assert f"{row['type']} {row['reference']}" in row["text"], row
        assert row["flightNumber"] == payload["flight"]["flight_number"]
        assert row["sourcePage"] == "1"
        # The link names the item; the signed-in landing resolves the current
        # approved page at the tap.
        assert "page" not in row and "source" not in row, row


def test_the_printed_link_names_the_item_never_a_page_or_document_the_pdf_held(tmp_path):
    """A PDF cannot be corrected once issued. It names the item; the signed-in
    landing applies the one current rule (document first, then page) at the
    tap, so the PDF opens the page the dashboard offers and two approved
    documents fail closed there - whatever this publication held."""
    payload = _analyse(tmp_path, "SQ30316072026BRU 81.pdf")
    references = {"status": "available", "references": [
        _passage(1995, "44-15 Handsets", "MEL OPERATIONAL PROCEDURES\n44-15-02A Cabin Handset"),
        _passage(1320, "44-15 Handsets", "MEL ITEMS\n44-15-02A Handset", handle=HANDLE_B, version="Revision 40"),
    ]}
    for held in (references, {"status": "unavailable", "references": []}, None):
        links = {(row["type"], row["reference"]): row for row in _governed_links(_render(tmp_path, payload, held))}
        assert set(links) == {("MEL", "44-15-02A"), ("MEL", "21-60-11A"), ("CDL", "57-23"), ("MEL", "25-22-01A")}
        for row in links.values():
            assert "page" not in row and "source" not in row, row
            assert row["text"] == f"OPEN APPROVED {row['type']} {row['reference']} >", row


def test_an_item_the_library_does_not_hold_still_links_to_the_current_answer(tmp_path):
    # B787 SQ279: the library holds no B787 MEL. The landing says so, with a
    # way back (app tests/governed-deferred-link-corpus.test.mjs), and opens
    # the item if one is approved later.
    payload = _analyse(tmp_path, "lido-briefing_SQ_279_15Aug2026_SIN_ADL.pdf")
    links = _governed_links(_render(tmp_path, payload, {"status": "unavailable", "references": []}))
    assert [(row["type"], row["reference"]) for row in links] == [("MEL", "50-20-01")]


BRIDGE = r"""
import fs from 'node:fs'
import path from 'node:path'
import zlib from 'node:zlib'
const appRoot = process.env.PILOTDRIVEN_APP_ROOT
const [mode, inputPath] = process.argv.slice(2)
const input = JSON.parse(fs.readFileSync(inputPath, 'utf8'))
const gdr = await import(path.join(appRoot, 'web/src/lib/governed-deferred-reference.mjs'))
const fixture = JSON.parse(zlib.gunzipSync(fs.readFileSync(path.join(appRoot, 'tests/fixtures/governed-deferred-link-corpus.json.gz'))).toString('utf8'))
const dashboard = (file) => fixture.cases.find((entry) => entry.file === file)?.dashboard || null
if (mode === 'publish') {
  const { createServer } = await import(path.join(appRoot, 'web/node_modules/vite/dist/node/index.js'))
  const server = await createServer({ root: path.join(appRoot, 'web'), logLevel: 'error', server: { middlewareMode: true, hmr: false }, appType: 'custom', optimizeDeps: { noDiscovery: true, include: [] } })
  const bridge = await server.ssrLoadModule('/src/lib/governed-deferred-candidate-bridge.ts')
  const review = await import(path.join(appRoot, 'deferred-item-review.mjs'))
  const out = {}
  for (const entry of input) {
    const answer = dashboard(entry.file)
    out[entry.file] = answer ? bridge.buildOdssGovernedDeferredPublication({ flight: entry.flight }, answer, {
      fleet: review.fleetVariantForRegistration(entry.flight.registration), aircraft: entry.flight.aircraft_type,
    }) : null
  }
  await server.close()
  process.stdout.write(JSON.stringify(out))
} else {
  // The library answer the landing gets for a link depends on the item and
  // the aircraft applicability only; flight number and route do not select it.
  const answers = new Map()
  for (const [key, answer] of Object.entries(fixture.reduced)) {
    const manifest = JSON.parse(key)
    const defect = manifest.pertinent.defects[0]
    answers.set(JSON.stringify([defect.type, defect.reference, manifest.flight.aircraftType]), answer)
  }
  const out = input.map((entry) => {
    const route = gdr.governedDeferredReferenceRoute(new URL(entry.uri).hash)
    if (route?.status !== 'valid') return { ...entry, route: route?.status || null }
    const answer = answers.get(JSON.stringify([route.request.type, route.request.reference, route.request.aircraftType]))
    if (!answer) return { ...entry, route: 'valid', missingAnswer: true }
    const outcome = gdr.resolveGovernedDeferredTarget(route.request, answer)
    const button = gdr.resolveGovernedDeferredTarget({ type: route.request.type, reference: route.request.reference }, dashboard(entry.file))
    const held = gdr.governedDeferredReferences({ type: route.request.type, reference: route.request.reference }, answer).some((reference) => reference.citation?.safeTarget)
    const page = (reference) => reference ? String(reference.citation.page) : null
    return { ...entry, route: 'valid', held, status: outcome.status, opened: page(outcome.reference), dashboard: button.status, dashboardPage: page(button.reference) }
  })
  process.stdout.write(JSON.stringify(out))
}
"""


def _bridge(tmp_path: Path, mode: str, payload) -> object:
    script = tmp_path / "bridge.mjs"
    script.write_text(BRIDGE, encoding="utf-8")
    data = tmp_path / f"{mode}.json"
    data.write_text(json.dumps(payload), encoding="utf-8")
    completed = subprocess.run(["node", str(script), mode, str(data)], capture_output=True, text=True, timeout=600,
                               env={**os.environ})
    assert completed.returncode == 0, completed.stderr[-2000:]
    return json.loads(completed.stdout)


def test_every_held_ofp_pdf_link_opens_its_approved_page_or_says_it_is_not_available(tmp_path):
    """Corpus-wide over all 30 held OFPs, in the actual generated six-page PDF.

    The governed publication each PDF holds is built by the app's own binder
    from the library answers frozen read-only from the live governed index
    (app tests/fixtures/governed-deferred-link-corpus.json.gz), stored through
    ODSS's own normaliser, rendered, and every printed link is resolved by the
    app's landing rule against the same frozen library.
    """
    app_root = os.environ.get("PILOTDRIVEN_APP_ROOT")
    if not app_root:
        pytest.skip("PILOTDRIVEN_APP_ROOT is not set")
    fixture = Path(app_root) / "tests" / "fixtures" / "governed-deferred-link-corpus.json.gz"
    if not fixture.is_file() or shutil.which("node") is None:
        pytest.skip("the app's frozen governed-library answers or node are not available")
    names = sorted(path.name for path in CORPUS.glob("*.pdf")) if CORPUS.is_dir() else []
    if len(names) != 30:
        pytest.skip("the 30-OFP private corpus is not available")

    analysed = {}
    for index, name in enumerate(names):
        analysed[name] = _analyse(tmp_path / f"a{index}", name)
    publications = _bridge(tmp_path, "publish", [
        {"file": name, "flight": payload["flight"]} for name, payload in analysed.items()
    ])
    pending = []
    for index, (name, payload) in enumerate(analysed.items()):
        publication = publications.get(name)
        stored = None
        if publication:
            stored = (publication if publication["status"] == "unavailable"
                      else normalize_governed_deferred_reference_payload(
                          payload["flight"].get("deferred_items") or [], publication, flight=payload["flight"]))
        # The origin each PDF was requested from (apex and www alternate):
        # every printed link returns the pilot there (14 Oct 2026).
        requested = ("https://pilotdriven.com", "https://www.pilotdriven.com")[index % 2]
        links = _governed_links(_render(tmp_path, payload, stored, name=f"b{index}.pdf", public_origin=requested))
        cited = set(_cited(payload["flight"]))
        assert {(row["type"], row["reference"]) for row in links} == cited, name
        assert {row["origin"] for row in links} <= {requested}, name
        pending += [{"file": name, "uri": row["uri"], "text": row["text"]} for row in links]
    resolved = _bridge(tmp_path, "resolve", pending)
    assert len(resolved) >= 40
    failures = []
    for row in resolved:
        if row.get("route") != "valid" or row.get("missingAnswer"):
            failures.append((row["file"], row["uri"], "unparsed or no frozen answer"))
        elif row["held"] and row["status"] != "open":
            failures.append((row["file"], row["uri"], f"held but landed {row['status']}"))
        elif not row["held"] and row["status"] != "unavailable":
            failures.append((row["file"], row["uri"], f"not held but landed {row['status']}"))
        elif row["status"] == "open" and row["dashboard"] == "open" and row["opened"] != row["dashboardPage"]:
            failures.append((row["file"], row["uri"], f"PDF opens p.{row['opened']}, dashboard p.{row['dashboardPage']}"))
    assert not failures, failures

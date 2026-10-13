"""A Flight Briefing PDF's governed links return the pilot to the origin it came from.

The deployment serves the same app at https://pilotdriven.com (the stack's
CustomDomainName, canonical) and https://www.pilotdriven.com with no redirect,
and device-saved packs (IndexedDB) are per origin. Until 14 Oct 2026 every
printed MEL/CDL link went to www (combined_brief.governed_deferred_source_target,
PILOTDRIVEN_PUBLIC_ORIGIN unset in infrastructure), so a pilot who downloaded
from pilotdriven.com, tapped a link and pressed Back to Flight Briefing landed
in a www session without the flights saved on the device.

The app server passes the requesting origin only when it is one of this
deployment's own public origins (X-PilotDriven-Public-Origin, behind the
service token); ODSS checks it again against the same allowlist and the https
host shape, and otherwise falls back to the canonical apex - never www, never
an arbitrary host.
"""
from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlsplit

import fitz
import pytest

import app.odss.combined_brief as cb
from tests.test_service_api_v06 import _authorization, service_app  # noqa: F401 - the service fixture

CORPUS = Path(__file__).resolve().parents[2] / "private_cfp_corpus"
SQ223 = CORPUS / "lido-briefing_SQ_223_16Aug2026_SIN_PER.pdf"
APEX = "https://pilotdriven.com"
WWW = "https://www.pilotdriven.com"
ITEM = {"item_type": "MEL", "reference": "25-20-50A"}
FLIGHT = {"flight_number": "SQ223", "registration": "9VSHS", "aircraft_type": "A350-941", "departure": "WSSS", "destination": "YPPH"}


@pytest.fixture(autouse=True)
def _no_live_sources_or_configured_origin(monkeypatch):
    for name in ("ODSS_VA_SIGMET_SOURCE", "ODSS_SIGMET_SOURCE", "ODSS_OPMET_SOURCE", "ODSS_TC_TRACK_SOURCE",
                 "ODSS_TC_SIGMET_SOURCE", "ODSS_ADWX_SOURCE", "ODSS_WEATHER_CHART_AI"):
        monkeypatch.setenv(name, "disabled")
    monkeypatch.delenv("PILOTDRIVEN_PUBLIC_ORIGIN", raising=False)
    monkeypatch.delenv("PILOTDRIVEN_PUBLIC_ORIGINS", raising=False)


def _origins(pdf_bytes_or_path) -> set[str]:
    document = fitz.open(stream=pdf_bytes_or_path, filetype="pdf") if isinstance(pdf_bytes_or_path, bytes) else fitz.open(pdf_bytes_or_path)
    with document:
        uris = [link["uri"] for page in document for link in page.get_links() if link.get("uri")]
    assert uris, "the briefing must print its governed links"
    for uri in uris:
        assert "/#/governed-deferred-reference?" in uri, uri
    return {f"{urlsplit(uri).scheme}://{urlsplit(uri).netloc}" for uri in uris}


def test_without_a_requesting_origin_the_link_goes_to_the_canonical_apex_not_www():
    assert cb.governed_deferred_source_target(FLIGHT, ITEM).startswith(f"{APEX}/#/governed-deferred-reference?")


def test_only_this_deployments_own_https_origins_are_accepted():
    assert cb.CANONICAL_PUBLIC_ORIGIN == APEX
    validated_public_origin = cb.validated_public_origin
    assert validated_public_origin(APEX) == APEX
    assert validated_public_origin(WWW) == WWW
    assert validated_public_origin(f"{WWW}/") == WWW, "a trailing slash is the same origin"
    for spoofed in ("https://evil.example", "http://pilotdriven.com", "https://pilotdriven.com.evil.example",
                    "https://pilotdriven.com@evil.example", "javascript:alert(1)", "https://pilotdriven.com/#/x",
                    "", None, "https://PILOTDRIVEN.COM:443/path"):
        assert validated_public_origin(spoofed) is None, spoofed
    assert cb.governed_deferred_source_target(FLIGHT, ITEM, public_origin="https://evil.example").startswith(f"{APEX}/#/")


def test_a_configured_origin_joins_the_allowlist(monkeypatch):
    monkeypatch.setenv("PILOTDRIVEN_PUBLIC_ORIGINS", "https://d2odw760tjs774.cloudfront.net, https://, not-a-url")
    assert cb.validated_public_origin("https://d2odw760tjs774.cloudfront.net") == "https://d2odw760tjs774.cloudfront.net"
    assert cb.validated_public_origin("https://other.cloudfront.net") is None


def test_the_six_page_render_prints_links_on_the_origin_it_was_asked_for(tmp_path):
    if not SQ223.is_file():
        pytest.skip("the private OFP corpus is not available")
    from app.analysis import run_odss_analysis

    result = run_odss_analysis(SQ223, tmp_path / "analysis", tmp_path / "legacy", 1)
    payload = json.loads(Path(result["analysis_path"]).read_text(encoding="utf-8"))
    for origin, expected in ((APEX, APEX), (WWW, WWW), ("https://evil.example", APEX), (None, APEX)):
        target = tmp_path / f"{expected.split('//')[1]}-{bool(origin)}.pdf"
        cb.render_combined_briefing(payload["flight"], payload["findings"], payload.get("view", {}).get("warnings") or [],
                                 target, source_pdf_path=str(SQ223), weather_charts=payload.get("weather_charts") or {},
                                 public_origin=origin)
        assert _origins(target) == {expected}, origin


def test_the_service_renders_the_pdf_for_the_requesting_origin_and_caches_each_apart(service_app):  # noqa: F811
    if not SQ223.is_file():
        pytest.skip("the private OFP corpus is not available")
    created = service_app.post("/v1/analyses", headers=_authorization(),
                               files={"file": (SQ223.name, SQ223.read_bytes(), "application/pdf")})
    assert created.status_code in (200, 201), created.text
    analysis_id = created.json()["analysis_id"]
    url = f"/v1/analyses/{analysis_id}/reports/combined"

    def fetched(origin: str | None) -> set[str]:
        headers = _authorization()
        if origin is not None:
            headers["X-PilotDriven-Public-Origin"] = origin
        response = service_app.get(url, headers=headers)
        assert response.status_code == 200, response.text
        return _origins(response.content)

    assert fetched(APEX) == {APEX}
    assert fetched(WWW) == {WWW}, "www must not be served the apex PDF from the cache"
    assert fetched(APEX) == {APEX}, "and the apex must not be served the www PDF"
    assert fetched("https://evil.example") == {APEX}, "an unknown origin falls back to the canonical apex"
    assert fetched(None) == {APEX}

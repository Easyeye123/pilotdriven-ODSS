"""SAVED-PACK-PUBLICATION-FRESHNESS-422 (independent production QA of release 422, 24 Sep 2026, F2).

Release 422 changed what the briefing publishes (rule v3, the older-extraction
statement, the page-5/6 ladders) but kept release 420's publication rules token
(v68). A pack saved on 420 reopened on 422 as "under the rules in service": the
service served its stored view as stored, its stored PDF was handed back, and
the dashboard - composed by the current reader - contradicted both. The
contract now: the token is minted together with the composition it publishes
(a manifest pins it on both sides); and an analysis whose held extraction
predates the parser in service is rebuilt under the current rules like one
stored under older rules, so the served view says what the composition says.
"""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path

import pytest

from app.odss.combined_brief import COMBINED_BRIEFING_PUBLICATION_FORMAT, COMBINED_BRIEFING_SCHEMA_VERSION
from app.odss.enroute_contact import ENROUTE_CONTACT_RULE
from app.odss.extraction_rules import EXTRACTION_RULES
from app.odss.flight_briefing_publication import current_rules_briefing
from tests.test_saved_pack_current_rules_view import stored  # noqa: F401 - the module fixture

MANIFEST = json.loads((Path(__file__).resolve().parent / "fixtures" / "publication_rules_manifest.json").read_text())


def test_the_publication_rules_token_is_minted_together_with_the_composition_it_publishes() -> None:
    assert COMBINED_BRIEFING_SCHEMA_VERSION == MANIFEST["publication_rules"]
    assert ENROUTE_CONTACT_RULE == MANIFEST["enroute_contact_rule"]
    assert EXTRACTION_RULES == MANIFEST["extraction_rules"]
    assert COMBINED_BRIEFING_PUBLICATION_FORMAT == MANIFEST["publication_format"]


def test_the_app_pins_the_same_manifest() -> None:
    app_root = os.environ.get("PILOTDRIVEN_APP_ROOT")
    if not app_root:
        pytest.skip("PILOTDRIVEN_APP_ROOT not set")
    app_manifest = json.loads((Path(app_root) / "tests" / "fixtures" / "publication-rules-manifest.json").read_text())
    assert {k: v for k, v in app_manifest.items() if k != "minted"} == {k: v for k, v in MANIFEST.items() if k != "minted"}


def test_an_analysis_extracted_by_an_earlier_parser_is_rebuilt_even_under_the_current_token(stored) -> None:  # noqa: F811
    old, source = stored
    older = copy.deepcopy(old)
    older["view"]["briefing"]["publication_rules"] = COMBINED_BRIEFING_SCHEMA_VERSION
    older["flight"]["extraction_rules"] = "2026-09-01-an-earlier-parser-v0"
    before = copy.deepcopy(older)

    result = current_rules_briefing(older, source)

    assert older == before, "the held analysis is never rewritten"
    assert result["rebuilt_from_held_analysis"] is True
    assert result["briefing"]["publication_rules"] == COMBINED_BRIEFING_SCHEMA_VERSION
    assert result["flight"]["extraction_rules"] == "2026-09-01-an-earlier-parser-v0", "the stamp is what the parser held, never rewritten"
    sentence = result["briefing"]["enroute_contact"]["state_sentence"]
    assert sentence.startswith("Held extraction predates the current parser"), sentence


def test_an_analysis_under_the_current_token_and_the_current_parser_is_served_as_stored(stored) -> None:  # noqa: F811
    old, source = stored
    current = copy.deepcopy(old)
    current["view"]["briefing"]["publication_rules"] = COMBINED_BRIEFING_SCHEMA_VERSION
    current["flight"]["extraction_rules"] = EXTRACTION_RULES
    result = current_rules_briefing(current, source)
    assert result["rebuilt_from_held_analysis"] is False
    assert result["briefing"] is current["view"]["briefing"]

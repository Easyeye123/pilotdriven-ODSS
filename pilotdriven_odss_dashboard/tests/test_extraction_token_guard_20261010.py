"""F9 of Codex's independent QA of release 468 (10 Oct 2026): a parser change ships with a new extraction token.

Releases 468 and 470 changed what the parser holds (ETP scenario rows, ARINC lat/long fix names, the MSA column, a log's
first page) and reminted the corpus identities under the unchanged extraction v7 and publication v82, so a pack saved
before them reopened as current: the saved SQ437 kept "PART OF TWY GUIDANCE" with no older-extraction notice. The corpus
manifest now records the token its identities were minted under, the mint refuses a moved identity under that same
token, and a pack held under the 470 tokens reopens as an older extraction.
"""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

from app.odss.combined_brief import COMBINED_BRIEFING_SCHEMA_VERSION
from app.odss.extraction_rules import EXTRACTION_RULES
from app.odss.flight_briefing_publication import current_rules_briefing
from tests.test_saved_pack_current_rules_view import stored  # noqa: F401 - the module fixture

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from mint_corpus_case import unchanged_token_refusal  # noqa: E402

RELEASE_470_EXTRACTION = "2026-10-01-atc-clearance-family-v7"
RELEASE_470_PUBLICATION = "2026-10-04-atc-absence-wording-v82"


def test_the_corpus_identities_were_minted_under_the_extraction_token_in_service() -> None:
    manifest = json.loads((ROOT / "tests" / "private_cfp_corpus_manifest.json").read_text(encoding="utf-8"))
    assert manifest["extraction_rules"] == EXTRACTION_RULES


def test_a_remint_that_moves_an_identity_under_the_same_token_is_refused() -> None:
    refusal = unchanged_token_refusal(EXTRACTION_RULES, EXTRACTION_RULES, ["SQ437-MLE-SIN-08OCT", "SQ24-SIN-JFK-15AUG"])
    assert refusal and "SQ437-MLE-SIN-08OCT, SQ24-SIN-JFK-15AUG" in refusal and "nothing was written" in refusal
    assert unchanged_token_refusal(RELEASE_470_EXTRACTION, EXTRACTION_RULES, ["SQ437-MLE-SIN-08OCT"]) is None
    assert unchanged_token_refusal(None, EXTRACTION_RULES, ["SQ437-MLE-SIN-08OCT"]) is None
    assert unchanged_token_refusal(EXTRACTION_RULES, EXTRACTION_RULES, []) is None


def test_the_release_470_tokens_are_superseded() -> None:
    assert EXTRACTION_RULES != RELEASE_470_EXTRACTION
    assert COMBINED_BRIEFING_SCHEMA_VERSION != RELEASE_470_PUBLICATION


def test_a_pack_saved_under_release_470_reopens_as_an_older_extraction(stored) -> None:  # noqa: F811
    old, source = stored
    saved = copy.deepcopy(old)
    saved["view"]["briefing"]["publication_rules"] = RELEASE_470_PUBLICATION
    saved["flight"]["extraction_rules"] = RELEASE_470_EXTRACTION
    before = copy.deepcopy(saved)

    result = current_rules_briefing(saved, source)

    assert saved == before, "the held analysis is never rewritten"
    assert result["rebuilt_from_held_analysis"] is True
    assert result["briefing"]["publication_rules"] == COMBINED_BRIEFING_SCHEMA_VERSION
    assert result["flight"]["extraction_rules"] == RELEASE_470_EXTRACTION, "the stamp is what the parser held"
    assert result["briefing"]["enroute_contact"]["extraction"] == {"rules": RELEASE_470_EXTRACTION, "current": False}
    sentence = result["briefing"]["enroute_contact"]["state_sentence"]
    assert sentence.startswith("Held extraction predates the current parser"), sentence

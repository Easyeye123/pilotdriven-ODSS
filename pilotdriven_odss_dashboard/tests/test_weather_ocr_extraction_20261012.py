"""A recognition change must never restamp a held v9 analysis as current."""
import copy

from app.odss.extraction_rules import EXTRACTION_RULES
from app.odss.flight_briefing_publication import current_rules_briefing
from tests.test_saved_pack_current_rules_view import stored  # noqa: F401

OLD_TOKEN = "2026-10-10-contingency-label-v9"
# The current token; v10 (weather OCR) was superseded by v11 (item 3, LIDO Item D and validity, 14 Oct 2026) and v11
# by v12 (QA500, Item D read whole and checked against the free text, 15 Oct 2026), v12 by v13 (every printed
# alternate row read, 15 Oct 2026), v13 by v14 (with QA502: one detector for schedule language anywhere in the
# body, 15 Oct 2026), v14 by v15 (QA504-01: alternate tables bounded and every line accounted, 15 Oct 2026) and v15
# by v16 (QA504 integrated with QA506: temporal content accounted for, fail closed, 15 Oct 2026) and v16 by v17
# (QA508-01: an alternate table ends only at the layout's structure; EDTO rows recovered by name, 15 Oct 2026) and
# v17 by v18 (QA510: temporal content found by shape, durations benign only as notice lead times, 16 Oct 2026) and
# v18 by v19 (QA512: a table cell is promoted only when it is semantically valid, 16 Oct 2026) and
# v19 by v21 (QA514 + QA516 on release 516, 17 Oct 2026: every digit accounted for; accounting never truncated) and
# v21 by v22 (QA518, 18 Oct 2026: governance read on the syntactic text; an unread temporal qualification is a review).
NEW_TOKEN = "2026-10-18-syntactic-governance-v22"


def test_new_analysis_has_new_weather_extraction_stamp(stored):  # noqa: F811
    assert EXTRACTION_RULES == NEW_TOKEN
    analysis, _ = stored
    assert analysis["flight"]["extraction_rules"] == NEW_TOKEN


def test_reopening_v9_preserves_analysis_chart_and_timing(stored):  # noqa: F811
    old, source = stored
    saved = copy.deepcopy(old)
    saved["flight"]["extraction_rules"] = OLD_TOKEN
    saved["flight"]["destination"] = "WSSS"
    saved["flight"]["scheduled_arrival_utc"] = "2026-07-11T10:30:00Z"
    saved["weather_charts"] = {"charts": [{"page_number": 49, "kind": "unclassified", "verified": False}]}
    before = copy.deepcopy(saved)
    result = current_rules_briefing(saved, source)
    assert saved == before
    assert result["flight"]["extraction_rules"] == OLD_TOKEN
    assert result["flight"]["scheduled_arrival_utc"] == "2026-07-11T10:30:00Z"
    assert result["briefing"]["enroute_contact"]["extraction"] == {"rules": OLD_TOKEN, "current": False}
    assert result["briefing"]["enroute_contact"]["state_sentence"].startswith("Held extraction predates the current parser")

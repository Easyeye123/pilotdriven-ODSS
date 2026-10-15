"""QA506 (Codex's re-QA of release 506, 15 Oct 2026): the adversarial schedule-language corpus, in this runtime.

The third round in which an enumerated schedule-language detector missed phrasings ("TWY Y CLSD WEF 1800 UTC" active
all day; "H24" beside "DLY 1800-2000" excluded; "WEF 01 SEP 2026" on an August notice accepted; "ON SUN BETWEEN HR
1800-2000" borrowing Monday's hours). The detector is inverted (notam_timing_rules.json scheduleField): temporal content
is found broadly, stated benign classes are masked first, and every temporal token must sit in a statement read whole
and proven equal on its own to Item D (or the whole validity) - else a review.

The corpus (tests/fixtures/notam-timing-adversarial-qa506.json.gz, LABELLED SYNTHETIC) states every phrase's relation
to Item D by construction. The app runs the same corpus (tests/notam-timing-adversarial-qa506-20261015.test.mjs) and
pins the same fixture, counts and digest: both runtimes reach the same decision on every case.
"""
from __future__ import annotations

import gzip
import hashlib
import json
from pathlib import Path

from app.odss.notam_timing import decide_notice_timing, read_lido_schedule_field, read_lido_validity

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "notam-timing-adversarial-qa506.json.gz"
FIXTURE_SHA256 = "0c01d2a35eec06ca2fdd2d5813315a1e04834e7f3125f0c1f0cb1353e07d88f0"
DECISIONS = 436248
CONSERVATIVE_REVIEWS = 384
DECISION_DIGEST = "56a2007ae9584eaf8715207d0d3c46e18c8f8d4205aadacd0ac24f78e43c8eff"
KEYS = ("status", "stateAtReference", "minutesDelta", "outsideBy")


def _place(subject: str, position: str, text: str) -> list[str]:
    words = text.split(" ")
    mid = max(1, len(words) // 2)
    return {
        "after": [f"{subject} {text}."],
        "before": [f"{text} {subject}."],
        "ownline": [f"{subject}.", f"{text}."],
        "wrapped": [f"{subject} " + " ".join(words[:mid]), " ".join(words[mid:]) + "."],
        "bracket": [f"{subject} ({text})."],
        "comma": [f"{subject}, {text}."],
    }[position]


def test_adversarial_every_temporal_phrasing_is_the_canonical_decision_or_a_review_and_nothing_unread_is_active() -> None:
    raw = FIXTURE.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == FIXTURE_SHA256, "the app evaluates the same corpus bytes"
    fixture = json.loads(gzip.decompress(raw).decode("utf-8"))
    digest = hashlib.sha256()
    failures: list[str] = []
    decisions = conservative = 0
    canonical: dict[str, dict] = {}
    for d, v, family, relation, text in fixture["phrases"]:
        validity = read_lido_validity(fixture["validities"][v])
        key = f"{d}|{v}"
        if key not in canonical:
            canonical[key] = read_lido_schedule_field([*fixture["itemD"][d], f"{fixture['subject']}."], validity)
        canon = canonical[key]
        for position in fixture["positions"]:
            lines = [*fixture["itemD"][d], *_place(fixture["subject"], position, text)]
            read = read_lido_schedule_field(lines, validity)
            for reference, window in fixture["windows"].items():
                decisions += 1
                got = decide_notice_timing({"validity": validity, "schedule": read["field"], "review": read["review"]}, window)
                expected = decide_notice_timing({"validity": validity, "schedule": canon["field"], "review": canon["review"]}, window)
                digest.update((json.dumps([got[k] for k in KEYS], separators=(",", ":")) + "\n").encode("utf-8"))
                if expected["status"] == "outside_window" and expected["outsideBy"] == "validity":
                    ok = got["status"] == "outside_window" and got["outsideBy"] == "validity"
                elif relation in ("differs", "unreadable"):
                    ok = got["status"] == "review"
                else:
                    same = all(got[k] == expected[k] for k in KEYS)
                    ok = same or got["status"] == "review"
                    if ok and not same:
                        conservative += 1
                if not ok and len(failures) < 25:
                    failures.append(f"{d} {v} {reference} {family}/{relation} {position} {lines}: {got['status']}")
    print(f"adversarial: {decisions} decisions, {conservative} conservative reviews, digest {digest.hexdigest()}")
    assert failures == []
    assert decisions == DECISIONS
    assert conservative == CONSERVATIVE_REVIEWS, "equal phrasings read as a review are counted and pinned"
    assert digest.hexdigest() == DECISION_DIGEST, "the app pins the same digest: both runtimes decide every case the same"

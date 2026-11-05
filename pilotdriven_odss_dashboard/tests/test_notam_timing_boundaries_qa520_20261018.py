"""Preregistered operand-boundary cases, byte-identical to the app fixture.

No record IDs or airport-name list: vary identifiers, places and finite clauses;
unresolved time conditions and unknown modifiers must still require review.
"""
import gzip
import hashlib
import json
from pathlib import Path

from app.odss.notam_timing import explain_timing_ledger, read_lido_schedule_field, read_lido_validity


def test_operand_boundaries_preserve_all_timing_obligations():
    raw = gzip.decompress((Path(__file__).parent / "fixtures/notam-timing-boundaries-qa520.json.gz").read_bytes())
    assert hashlib.sha256(raw).hexdigest() == "73ac488d992d5c520f9a1f0c51418f4a07723b7c38dcf77ad005f0474a0b52e4"
    fixture = json.loads(raw)
    assert len(fixture["cases"]) == 2666
    validity = read_lido_validity(fixture["validity"])
    failures = []
    for case in fixture["cases"]:
        for text in (case["text"], case["text"].replace("(", "[").replace(")", "]"), case["text"].replace(" FROM ", " FROM\n")):
            lines = text.split("\n")
            read = read_lido_schedule_field(lines, validity, fixture["gazetteer"])
            proof = explain_timing_ledger(lines, validity, fixture["gazetteer"])
            if (bool(read.get("review")) != case["review"] or
                    (not read.get("review") and any(row["status"] == "undischarged" for row in proof["ledger"]))):
                failures.append({"text": text, "expectedReview": case["review"], "read": read, "ledger": proof["ledger"]})
    assert not failures, failures[:8]

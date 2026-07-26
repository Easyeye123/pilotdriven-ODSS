from __future__ import annotations

from collections import defaultdict
import hashlib
import json
import re
from typing import Any


_VOLATILE_KEYS = {
    "generated_at",
    "generated_at_utc",
    "retrieved_at",
    "retrieved_at_utc",
    "updated_at",
    "timestamp",
}


def _stable_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): _stable_value(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
            if str(key).casefold() not in _VOLATILE_KEYS
        }
    if isinstance(value, list):
        return [_stable_value(item) for item in value]
    if isinstance(value, tuple):
        return [_stable_value(item) for item in value]
    return value


def assign_finding_ids(findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Attach deterministic, unique Level 2 IDs without changing finding logic."""

    occurrences: dict[str, int] = defaultdict(int)
    for finding in findings:
        identity = {
            "engine": finding.get("engine"),
            "rule_id": finding.get("rule_id"),
            "title": finding.get("title"),
            "data": _stable_value(finding.get("data") or {}),
        }
        canonical = json.dumps(
            identity,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        )
        occurrences[canonical] += 1
        digest_input = f"{canonical}\n{occurrences[canonical]}".encode("utf-8")
        digest = hashlib.sha256(digest_input).hexdigest()[:16]
        engine = re.sub(
            r"[^A-Z0-9]+",
            "-",
            str(finding.get("engine") or "FINDING").upper(),
        ).strip("-")[:24]
        finding["finding_id"] = f"L2-{engine or 'FINDING'}-{digest}"
    return findings


__all__ = ["assign_finding_ids"]

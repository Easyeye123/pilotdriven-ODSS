from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

CDL_INDEX_ENV = "ODSS_CDL_INDEX_PATH"
DEPRESS_INDEX_ENV = "ODSS_DEPRESS_PROFILE_INDEX_PATH"

CDL_LIBRARY_METADATA: dict[str, Any] = {
    "title": "SIA A350 Fleet Configuration Deviation List",
    "issue_date": "2026-05-05",
    "status": "controlled-source-not-mounted",
    "environment_variable": CDL_INDEX_ENV,
}

DEPRESS_LIBRARY_METADATA: dict[str, Any] = {
    "title": "A350 Depressurization Profiles",
    "issue_date": "2026-06-12",
    "status": "controlled-source-not-mounted",
    "environment_variable": DEPRESS_INDEX_ENV,
}

# Regression-safe subset only. Production must mount the complete private index
# through ODSS_DEPRESS_PROFILE_INDEX_PATH. No proprietary chart body text is
# embedded in the public repository.
_FALLBACK_DEPRESS_PROFILES: list[dict[str, Any]] = [
    {
        "chart": "10-4",
        "from": "RANAH",
        "to": "HILAL",
        "from_aliases": ["RANAH"],
        "to_aliases": ["HILAL"],
        "airways": ["L750", "G202"],
        "critical": "DUDEG",
        "critical_aliases": ["DUDEG"],
        "effectivity": ["A350-941", "LH", "ULR"],
        "effective_date": "29 OCT 2024",
    },
    {
        "chart": "8-5",
        "from": "TEMEL",
        "to": "LEKBA",
        "from_aliases": ["TEMEL"],
        "to_aliases": ["LEKBA"],
        "airways": ["UM11", "M11", "T916", "N161"],
        "critical": "MATAL",
        "critical_aliases": ["MATAL"],
        "effectivity": ["A350-941", "LH", "ULR"],
        "effective_date": "12 JUN 2026",
    },
    {
        "chart": "7-1",
        "from": "HILAL",
        "to": "NONIB",
        "from_aliases": ["HILAL"],
        "to_aliases": ["NONIB"],
        "airways": ["G202", "G325", "L509"],
        "critical": "HILAL",
        "critical_aliases": ["HILAL"],
        "effectivity": ["A350-941", "LH", "ULR"],
        "effective_date": "13 OCT 2025",
    },
    {
        "chart": "11-3",
        "from": "63N140W",
        "to": "62N120W",
        "from_aliases": ["63N140W", "63N40"],
        "to_aliases": ["62N120W", "62N20"],
        "airways": ["DCT"],
        "critical": "63N140W",
        "critical_aliases": ["63N140W", "63N40"],
        "effectivity": ["A350-941", "LH", "ULR"],
        "effective_date": "13 NOV 2020",
        "chart_page": 286,
    },
    {
        "chart": "11-4",
        "from": "HAMND",
        "to": "TED",
        "from_aliases": ["HAMND"],
        "to_aliases": ["TED"],
        "airways": ["DCT"],
        "critical": "HAMND",
        "critical_aliases": ["HAMND"],
        "effectivity": ["A350-941", "LH", "ULR"],
        "effective_date": "16 AUG 2018",
        "chart_page": 287,
    },
    {
        "chart": "11-37",
        "from": "TED",
        "to": "62N20",
        "from_aliases": ["TED"],
        "to_aliases": ["62N20", "62N120W"],
        "airways": ["J511", "J124", "DCT"],
        "critical": "ORT",
        "critical_aliases": ["ORT"],
        "effectivity": ["A350-941", "LH", "ULR"],
        "effective_date": "29 OCT 2024",
        "chart_page": 320,
    },
]


def _load_index(path_value: str | None) -> dict[str, Any] | None:
    if not path_value:
        return None
    path = Path(path_value).expanduser()
    if not path.is_file():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Controlled reference index must be a JSON object: {path}")
    return payload


def normalized_registration(value: str | None) -> str:
    raw = re.sub(r"[^A-Z0-9]", "", (value or "").upper())
    if raw.startswith("9V") and len(raw) == 5:
        return f"9V-{raw[2:]}"
    return raw


def aircraft_effectivity_tokens(
    registration: str | None,
    aircraft_type: str | None,
) -> set[str]:
    reg = normalized_registration(registration)
    tokens = {re.sub(r"[^A-Z0-9]", "", (aircraft_type or "").upper())}
    if reg.startswith("9V-SG"):
        tokens.add("ULR")
    elif reg.startswith("9V-SM"):
        tokens.add("LH")
    elif reg.startswith("9V-SH"):
        tokens.add("MH")
    tokens.discard("")
    return tokens


def _normalise_profile(profile: dict[str, Any]) -> dict[str, Any]:
    value = dict(profile)
    value["chart"] = str(value.get("chart") or "").upper()
    value["from"] = str(value.get("from") or "").upper()
    value["to"] = str(value.get("to") or "").upper()
    value["critical"] = str(value.get("critical") or "").upper()
    value["airways"] = [str(item).upper() for item in value.get("airways", [])]
    value["effectivity"] = [str(item).upper() for item in value.get("effectivity", [])]
    value["from_aliases"] = [
        str(item).upper() for item in value.get("from_aliases", [value["from"]])
    ]
    value["to_aliases"] = [
        str(item).upper() for item in value.get("to_aliases", [value["to"]])
    ]
    value["critical_aliases"] = [
        str(item).upper()
        for item in value.get("critical_aliases", [value["critical"]])
    ]
    return value


def load_depress_profiles() -> list[dict[str, Any]]:
    index = _load_index(os.environ.get(DEPRESS_INDEX_ENV))
    if index:
        document = index.get("document") or {}
        DEPRESS_LIBRARY_METADATA.update(
            {
                "title": document.get("title") or DEPRESS_LIBRARY_METADATA["title"],
                "issue_date": document.get("issue_date")
                or DEPRESS_LIBRARY_METADATA["issue_date"],
                "status": document.get("status") or "controlled-index-loaded",
                "sha256": document.get("sha256"),
                "source_path": os.environ.get(DEPRESS_INDEX_ENV),
            }
        )
        profiles = index.get("profiles") or []
        if not isinstance(profiles, list):
            raise ValueError("Depressurization profile index 'profiles' must be a list")
        return [_normalise_profile(item) for item in profiles if isinstance(item, dict)]
    return [_normalise_profile(item) for item in _FALLBACK_DEPRESS_PROFILES]


def load_cdl_references() -> dict[str, dict[str, Any]]:
    index = _load_index(os.environ.get(CDL_INDEX_ENV))
    if not index:
        return {}
    document = index.get("document") or {}
    CDL_LIBRARY_METADATA.update(
        {
            "title": document.get("title") or CDL_LIBRARY_METADATA["title"],
            "issue_date": document.get("issue_date")
            or CDL_LIBRARY_METADATA["issue_date"],
            "status": document.get("status") or "controlled-index-loaded",
            "sha256": document.get("sha256"),
            "source_path": os.environ.get(CDL_INDEX_ENV),
        }
    )
    records = index.get("items") or []
    if not isinstance(records, list):
        raise ValueError("CDL index 'items' must be a list")
    return {
        str(item.get("reference") or "").upper(): item
        for item in records
        if isinstance(item, dict) and item.get("reference")
    }


def select_cdl_variants(
    record: dict[str, Any],
    registration: str | None,
) -> list[dict[str, Any]]:
    variants = [item for item in record.get("variants", []) if isinstance(item, dict)]
    if not variants:
        return []
    reg = normalized_registration(registration)
    exact = [
        item
        for item in variants
        if reg
        and reg
        in {
            normalized_registration(str(value))
            for value in item.get("applicable_registrations", [])
        }
    ]
    if exact:
        return exact
    generic = [item for item in variants if not item.get("applicable_registrations")]
    return generic


CDL_REFERENCES = load_cdl_references()
DEPRESS_PROFILES = load_depress_profiles()

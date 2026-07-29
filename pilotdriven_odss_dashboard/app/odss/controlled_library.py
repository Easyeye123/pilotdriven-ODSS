from __future__ import annotations

import json
import hashlib
import os
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

CDL_INDEX_ENV = "ODSS_CDL_INDEX_PATH"
DEPRESS_INDEX_ENV = "ODSS_DEPRESS_PROFILE_INDEX_PATH"
DEPRESS_INDEX_S3_ENV = "ODSS_DEPRESS_PROFILE_INDEX_S3_URI"
TENANT_ID_ENV = "ODSS_TENANT_ID"
MAX_DEPRESS_INDEX_BYTES = 5 * 1024 * 1024

CDL_LIBRARY_METADATA: dict[str, Any] = {
    "title": "A350 Fleet Configuration Deviation List",
    "issue_date": "not stated",
    "status": "controlled-source-not-mounted",
    "environment_variable": CDL_INDEX_ENV,
}

DEPRESS_LIBRARY_METADATA: dict[str, Any] = {
    "title": "A350 Depressurization Profiles",
    "issue_date": "not stated",
    "status": "controlled-source-not-mounted",
    "environment_variable": DEPRESS_INDEX_ENV,
}


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


def _load_depress_index() -> tuple[dict[str, Any], str, str, str] | None:
    path_value = os.environ.get(DEPRESS_INDEX_ENV)
    s3_uri = os.environ.get(DEPRESS_INDEX_S3_ENV)
    if path_value and s3_uri:
        raise ValueError(
            f"Configure only one of {DEPRESS_INDEX_ENV} or {DEPRESS_INDEX_S3_ENV}"
        )
    if not path_value and not s3_uri:
        return None

    configured_tenant = str(os.environ.get(TENANT_ID_ENV) or "").strip()
    if not configured_tenant:
        raise ValueError(
            f"{TENANT_ID_ENV} is required when a controlled profile index is configured"
        )

    if path_value:
        path = Path(path_value).expanduser()
        if not path.is_file():
            raise ValueError(f"Configured depressurization index is missing: {path}")
        if path.stat().st_size > MAX_DEPRESS_INDEX_BYTES:
            raise ValueError("Controlled depressurization index exceeds the size limit")
        raw = path.read_bytes()
        source = "private-file"
    else:
        parsed = urlparse(str(s3_uri))
        if parsed.scheme != "s3" or not parsed.netloc or not parsed.path.lstrip("/"):
            raise ValueError(
                f"{DEPRESS_INDEX_S3_ENV} must be a complete s3://bucket/key URI"
            )
        try:
            import boto3
        except ImportError as exc:  # pragma: no cover - deployment dependency gate
            raise RuntimeError(
                "boto3 is required when a private S3 profile index is configured"
            ) from exc
        response = boto3.client("s3").get_object(
            Bucket=parsed.netloc,
            Key=parsed.path.lstrip("/"),
        )
        body = response.get("Body")
        if body is None or not callable(getattr(body, "read", None)):
            raise ValueError("Controlled depressurization index response has no body")
        content_length = response.get("ContentLength")
        if (
            isinstance(content_length, int)
            and content_length > MAX_DEPRESS_INDEX_BYTES
        ):
            close = getattr(body, "close", None)
            if callable(close):
                close()
            raise ValueError("Controlled depressurization index exceeds the size limit")
        try:
            raw = body.read(MAX_DEPRESS_INDEX_BYTES + 1)
        finally:
            close = getattr(body, "close", None)
            if callable(close):
                close()
        source = "tenant-private-s3"

    if not isinstance(raw, (bytes, bytearray)):
        raise ValueError("Controlled depressurization index body must be bytes")
    raw = bytes(raw)
    if len(raw) > MAX_DEPRESS_INDEX_BYTES:
        raise ValueError("Controlled depressurization index exceeds the size limit")
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("Controlled depressurization index is not valid UTF-8 JSON") from exc
    if not isinstance(payload, dict):
        raise ValueError("Controlled depressurization index must be a JSON object")
    return payload, source, hashlib.sha256(raw).hexdigest(), configured_tenant


def _validated_depress_profiles(
    index: dict[str, Any],
    *,
    configured_tenant: str,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    document = index.get("document")
    profiles = index.get("profiles")
    if not isinstance(document, dict):
        raise ValueError("Depressurization index 'document' must be an object")
    if not isinstance(profiles, list) or not profiles:
        raise ValueError("Depressurization index 'profiles' must be a non-empty list")
    invalid = [
        item
        for item in profiles
        if not isinstance(item, dict)
        or not item.get("chart")
        or not item.get("from")
        or not item.get("to")
        or not item.get("critical")
    ]
    if invalid:
        raise ValueError(
            "Every depressurization profile requires chart, from, to and critical"
        )

    tenant_id = str(document.get("tenant_id") or "").strip()
    if tenant_id != configured_tenant:
        raise ValueError("Controlled profile index tenant does not match ODSS tenant")
    if document.get("governance_state") != "approved":
        raise ValueError("Controlled profile index is not approved")
    if document.get("is_current") is not True:
        raise ValueError("Controlled profile index is not current")
    return document, profiles


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
    loaded = _load_depress_index()
    if loaded:
        index, source, index_sha256, configured_tenant = loaded
        document, profiles = _validated_depress_profiles(
            index,
            configured_tenant=configured_tenant,
        )
        DEPRESS_LIBRARY_METADATA.clear()
        DEPRESS_LIBRARY_METADATA.update(
            {
                "title": document.get("title") or "A350 Depressurization Profiles",
                "issue_date": document.get("issue_date") or "not stated",
                "status": "controlled-index-loaded",
                "source_document_sha256": document.get("source_document_sha256")
                or document.get("sha256"),
                "index_sha256": index_sha256,
                "source": source,
                "tenant_id": configured_tenant,
                "coverage_scope": document.get("coverage_scope") or "not stated",
                "profile_count": len(profiles),
            }
        )
        return [_normalise_profile(item) for item in profiles if isinstance(item, dict)]
    DEPRESS_LIBRARY_METADATA.clear()
    DEPRESS_LIBRARY_METADATA.update(
        {
            "title": "A350 Depressurization Profiles",
            "issue_date": "not stated",
            "status": "controlled-source-not-mounted",
            "environment_variable": DEPRESS_INDEX_ENV,
            "s3_environment_variable": DEPRESS_INDEX_S3_ENV,
            "coverage_scope": "unavailable",
            "profile_count": 0,
        }
    )
    return []


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

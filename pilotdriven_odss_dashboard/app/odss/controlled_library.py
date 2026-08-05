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
DEPRESS_CHART_DIR_ENV = "ODSS_DEPRESS_CHART_DIR"
FLEET_EFFECTIVITY_ENV = "ODSS_FLEET_EFFECTIVITY_PATH"
TENANT_ID_ENV = "ODSS_TENANT_ID"
MAX_DEPRESS_INDEX_BYTES = 5 * 1024 * 1024
MAX_DEPRESS_CHART_BYTES = 8 * 1024 * 1024

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


# Which airframe variant a registration series belongs to is operator data, not
# engine logic, so it lives in a fleet register file rather than in Python. The
# shipped default describes the fleets this deployment already carries charts
# for; another airline is added by pointing FLEET_EFFECTIVITY_ENV at its own
# register alongside its own chart index, with no code change.
#
# A series may hold more than one variant. Aircraft in one registration series
# are commonly certified for several configurations, and a chart tagged for any
# one of them applies. A series absent from the register is never guessed: it
# resolves to no variant, and the caller reports an effectivity conflict.
DEFAULT_FLEET_REGISTER = Path(__file__).resolve().parent / "fleet" / "default-fleet-effectivity.json"


def _variant_tokens(value: Any) -> list[str]:
    """Accept a single variant or a list of them, as the register schema allows."""
    values = value if isinstance(value, list) else [value]
    return [
        token
        for token in (
            re.sub(r"[^A-Z0-9]", "", str(item).upper())
            for item in values
            if item
        )
        if token
    ]


def _read_fleet_register(path: Path) -> dict[str, list[str]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    series = payload.get("registration_series") if isinstance(payload, dict) else None
    if not isinstance(series, dict):
        raise ValueError(
            f"A fleet effectivity register must hold a registration_series object: {path}"
        )
    resolved: dict[str, list[str]] = {}
    for prefix, variants in series.items():
        tokens = _variant_tokens(variants)
        # Prefixes are compacted the same way registrations are, so a register
        # may write them with or without the national hyphen and any country's
        # registration format works without the engine knowing the format.
        key = re.sub(r"[^A-Z0-9]", "", str(prefix).upper())
        if key and tokens:
            resolved[key] = tokens
    return resolved


def _fleet_series() -> dict[str, list[str]]:
    """The shipped register, overlaid by a mounted one when configured."""
    series: dict[str, list[str]] = {}
    if DEFAULT_FLEET_REGISTER.is_file():
        series.update(_read_fleet_register(DEFAULT_FLEET_REGISTER))
    path_value = os.environ.get(FLEET_EFFECTIVITY_ENV)
    if path_value:
        path = Path(path_value).expanduser()
        if not path.is_file():
            raise ValueError(f"Configured fleet effectivity register is missing: {path}")
        series.update(_read_fleet_register(path))
    return series


def resolve_aircraft_effectivity(
    registration: str | None,
    aircraft_type: str | None,
) -> tuple[set[str], bool]:
    """
    Effectivity tokens for a tail, and whether its variant was resolved.

    The second value is what separates "this aircraft is not covered by the
    chart" from "we do not know which variant this aircraft is". Only the first
    is a real absence of coverage; the second is an effectivity conflict and the
    reference protocol requires it to be shown as one rather than reported as an
    empty index.
    """
    reg = re.sub(r"[^A-Z0-9]", "", str(registration or "").upper())
    tokens = {re.sub(r"[^A-Z0-9]", "", (aircraft_type or "").upper())}
    tokens.discard("")
    series = _fleet_series()
    # Longest prefix wins, so a register can describe a sub-series more
    # precisely than the broader entry it sits inside.
    variants = next(
        (
            series[prefix]
            for prefix in sorted(series, key=len, reverse=True)
            if reg.startswith(prefix)
        ),
        None,
    )
    if variants:
        tokens.update(variants)
    return tokens, variants is not None


def aircraft_effectivity_tokens(
    registration: str | None,
    aircraft_type: str | None,
) -> set[str]:
    tokens, _ = resolve_aircraft_effectivity(registration, aircraft_type)
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


class ProfileChartUnavailableError(RuntimeError):
    """Raised when a matched profile's chart artifact cannot be served.

    The publication gate treats this as fail-closed: a report naming the
    profile must not be released without the embedded chart.
    """


def load_profile_chart_bytes(profile: dict[str, Any]) -> bytes:
    """Fetch and verify the single-page chart artifact for a matched profile.

    The artifact must be pinned in the approved index (``chart_artifact_key``
    + ``chart_sha256``). It is served from ``ODSS_DEPRESS_CHART_DIR`` or from
    the same private S3 prefix as the mounted index; the bytes must match the
    pinned hash exactly.
    """
    chart = str(profile.get("chart") or "")
    artifact_key = str(profile.get("chart_artifact_key") or "").strip()
    pinned_sha256 = str(profile.get("chart_sha256") or "").strip().lower()
    if not artifact_key or not pinned_sha256:
        raise ProfileChartUnavailableError(
            f"Profile {chart or 'unknown'} has no pinned chart artifact in the "
            "approved index"
        )
    if ".." in artifact_key or artifact_key.startswith(("/", "s3:")):
        raise ProfileChartUnavailableError(
            f"Profile {chart} chart artifact key is not a safe relative key"
        )

    chart_dir = os.environ.get(DEPRESS_CHART_DIR_ENV)
    index_s3_uri = os.environ.get(DEPRESS_INDEX_S3_ENV)
    if chart_dir:
        path = Path(chart_dir).expanduser() / Path(artifact_key).name
        if not path.is_file():
            raise ProfileChartUnavailableError(
                f"Profile {chart} chart artifact is missing: {path}"
            )
        if path.stat().st_size > MAX_DEPRESS_CHART_BYTES:
            raise ProfileChartUnavailableError(
                f"Profile {chart} chart artifact exceeds the size limit"
            )
        raw = path.read_bytes()
    elif index_s3_uri:
        parsed = urlparse(str(index_s3_uri))
        key_prefix = parsed.path.lstrip("/").rsplit("/", 1)[0]
        artifact_s3_key = f"{key_prefix}/{artifact_key}" if key_prefix else artifact_key
        try:
            import boto3
        except ImportError as exc:  # pragma: no cover - deployment dependency gate
            raise ProfileChartUnavailableError(
                "boto3 is required to fetch private chart artifacts"
            ) from exc
        try:
            response = boto3.client("s3").get_object(
                Bucket=parsed.netloc,
                Key=artifact_s3_key,
            )
        except Exception as exc:
            raise ProfileChartUnavailableError(
                f"Profile {chart} chart artifact could not be fetched from "
                "private storage"
            ) from exc
        body = response.get("Body")
        if body is None or not callable(getattr(body, "read", None)):
            raise ProfileChartUnavailableError(
                f"Profile {chart} chart artifact response has no body"
            )
        try:
            raw = body.read(MAX_DEPRESS_CHART_BYTES + 1)
        finally:
            close = getattr(body, "close", None)
            if callable(close):
                close()
        if not isinstance(raw, (bytes, bytearray)):
            raise ProfileChartUnavailableError(
                f"Profile {chart} chart artifact body must be bytes"
            )
        raw = bytes(raw)
        if len(raw) > MAX_DEPRESS_CHART_BYTES:
            raise ProfileChartUnavailableError(
                f"Profile {chart} chart artifact exceeds the size limit"
            )
    else:
        raise ProfileChartUnavailableError(
            f"No chart artifact source is configured; set {DEPRESS_CHART_DIR_ENV} "
            f"or mount the index via {DEPRESS_INDEX_S3_ENV}"
        )

    digest = hashlib.sha256(raw).hexdigest()
    if digest != pinned_sha256:
        raise ProfileChartUnavailableError(
            f"Profile {chart} chart artifact hash does not match the approved index"
        )
    return raw


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

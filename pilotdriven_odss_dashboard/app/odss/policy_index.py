from __future__ import annotations

from datetime import date, datetime, timezone
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator


class ControlledDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_id: str = Field(min_length=1, max_length=128)
    title: str = Field(min_length=1, max_length=500)
    document_type: str = Field(min_length=1, max_length=80)
    revision: str = Field(min_length=1, max_length=200)
    effective_date: date
    source_sha256: str = Field(pattern=r"^[0-9a-fA-F]{64}$")
    status: Literal["approved"]
    current: Literal[True]
    approved_by: str = Field(min_length=1, max_length=128)
    approved_at_utc: datetime


class DecisionFacets(BaseModel):
    model_config = ConfigDict(extra="forbid")

    engines: list[str] = Field(min_length=1)
    rule_ids: list[str] = Field(default_factory=list)
    severities: list[str] = Field(default_factory=list)
    phases: list[str] = Field(default_factory=list)
    airports: list[str] = Field(default_factory=list)
    aircraft_types: list[str] = Field(default_factory=list)
    registrations: list[str] = Field(default_factory=list)


class AmbiguityQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prompt: str = Field(min_length=1, max_length=500)
    options: list[str] = Field(min_length=2, max_length=8)

    @model_validator(mode="after")
    def unique_options(self):
        normalized = [item.strip() for item in self.options]
        if any(not item for item in normalized) or len(set(normalized)) != len(normalized):
            raise ValueError("Ambiguity question options must be non-empty and unique.")
        self.options = normalized
        return self


class ControlledClause(BaseModel):
    model_config = ConfigDict(extra="forbid")

    clause_id: str = Field(min_length=1, max_length=160)
    document_id: str = Field(min_length=1, max_length=128)
    section: str = Field(min_length=1, max_length=300)
    page: str | int
    exact_support: str = Field(min_length=1, max_length=1500)
    applicability_reason: str = Field(min_length=1, max_length=500)
    decision_frame: str = Field(min_length=1, max_length=500)
    applicable_options: list[str] = Field(default_factory=list, max_length=12)
    facets: DecisionFacets
    ambiguity_question: AmbiguityQuestion | None = None


class ControlledPolicyIndex(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.1"]
    tenant_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$")
    generated_at_utc: datetime
    documents: list[ControlledDocument]
    clauses: list[ControlledClause]

    @model_validator(mode="after")
    def coherent_references(self):
        document_ids = [item.document_id for item in self.documents]
        if len(document_ids) != len(set(document_ids)):
            raise ValueError("Controlled document IDs must be unique.")
        clause_ids = [item.clause_id for item in self.clauses]
        if len(clause_ids) != len(set(clause_ids)):
            raise ValueError("Controlled clause IDs must be unique.")
        known = set(document_ids)
        missing = sorted({item.document_id for item in self.clauses} - known)
        if missing:
            raise ValueError(f"Controlled clauses reference unknown documents: {missing}")
        return self


def _flight_date(value: str | None) -> date:
    text = str(value or "").strip().upper()
    for pattern in ("%d%b%y", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, pattern).date()
        except ValueError:
            continue
    return datetime.now(timezone.utc).date()


def _document_payload(document: ControlledDocument) -> dict[str, Any]:
    return {
        "document_id": document.document_id,
        "title": document.title,
        "document_type": document.document_type,
        "revision": document.revision,
        "effective_date": document.effective_date.isoformat(),
        "source_sha256": document.source_sha256.lower(),
        "status": document.status,
        "current": document.current,
        "approved_by": document.approved_by,
        "approved_at_utc": document.approved_at_utc.astimezone(timezone.utc).isoformat(),
    }


def _clause_payload(clause: ControlledClause) -> dict[str, Any]:
    return clause.model_dump(mode="json")


def policy_snapshot_from_env(
    *,
    tenant_id: str,
    flight_date: str | None,
) -> dict[str, Any]:
    """Load one private, approved tenant index and return a snapshot-safe payload."""

    configured_path = os.getenv("ODSS_LEVEL3_POLICY_INDEX_PATH", "").strip()
    configured_dir = os.getenv("ODSS_LEVEL3_POLICY_INDEX_DIR", "").strip()
    if configured_path:
        path = Path(configured_path)
    elif configured_dir:
        path = Path(configured_dir) / f"{tenant_id}.json"
    else:
        return {
            "schema_version": "1.1",
            "tenant_id": tenant_id,
            "state": "unavailable",
            "reason": "No approved operator policy index is mounted.",
            "source_path": None,
            "source_sha256": None,
            "documents": [],
            "clauses": [],
        }

    try:
        raw = path.read_bytes()
        payload = json.loads(raw)
        index = ControlledPolicyIndex.model_validate(payload)
        if index.tenant_id != tenant_id:
            raise ValueError("The mounted policy index belongs to another tenant.")
        as_of = _flight_date(flight_date)
        documents = [
            item
            for item in index.documents
            if item.effective_date <= as_of
        ]
        document_ids = {item.document_id for item in documents}
        clauses = [item for item in index.clauses if item.document_id in document_ids]
        return {
            "schema_version": "1.1",
            "tenant_id": tenant_id,
            "state": "ready" if documents else "unavailable",
            "reason": None if documents else "No current approved policy document is effective for this flight.",
            "source_path": str(path.resolve()),
            "source_sha256": hashlib.sha256(raw).hexdigest(),
            "generated_at_utc": index.generated_at_utc.astimezone(timezone.utc).isoformat(),
            "documents": [_document_payload(item) for item in documents],
            "clauses": [_clause_payload(item) for item in clauses],
        }
    except (OSError, json.JSONDecodeError, ValidationError, ValueError) as exc:
        return {
            "schema_version": "1.1",
            "tenant_id": tenant_id,
            "state": "invalid",
            "reason": f"Mounted policy index failed closed: {type(exc).__name__}.",
            "source_path": str(path),
            "source_sha256": None,
            "documents": [],
            "clauses": [],
        }


def snapshot_sha256(snapshot: dict[str, Any]) -> str:
    payload = json.dumps(
        snapshot,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


__all__ = [
    "ControlledPolicyIndex",
    "policy_snapshot_from_env",
    "snapshot_sha256",
]

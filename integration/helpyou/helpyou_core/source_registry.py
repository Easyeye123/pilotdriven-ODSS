"""Metadata-only registry for private Helpyou source bundles.

The registry records authority, currency and permitted use without placing
proprietary manuals or flight plans in the GitHub repository.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import json
from pathlib import Path
from typing import Any, Mapping


class SourceRegistryError(ValueError):
    """Raised when a source bundle violates Helpyou evidence boundaries."""


class SourceRole(str, Enum):
    CONTROLLED_OPERATIONAL = "controlled_operational"
    CONTROLLED_OPERATOR_GUIDANCE = "controlled_operator_guidance"
    REGULATORY = "regulatory"
    SUPPORTING_SYNTHESIS = "supporting_synthesis"
    COGNITIVE_FOUNDATION = "cognitive_foundation"
    ADVERSARIAL_INPUT = "adversarial_input"


class CurrencyStatus(str, Enum):
    CURRENT_FOR_BUNDLE = "current_for_bundle"
    CURRENCY_CHECK_REQUIRED = "currency_check_required"
    HISTORICAL_CONTEXT_ONLY = "historical_context_only"
    NOT_APPLICABLE = "not_applicable"


@dataclass(frozen=True)
class SourceRecord:
    source_id: str
    title: str
    role: SourceRole
    controlling: bool
    revision: str | None = None
    issue_date: str | None = None
    currency_status: CurrencyStatus = CurrencyStatus.NOT_APPLICABLE
    authority_scope: tuple[str, ...] = ()
    permitted_uses: tuple[str, ...] = ()
    prohibited_uses: tuple[str, ...] = ()
    private_storage_required: bool = False
    raw_content_in_repository: bool = False
    notes: tuple[str, ...] = ()

    def validate(self) -> None:
        if not self.source_id.strip() or not self.title.strip():
            raise SourceRegistryError("Every source requires a stable ID and title.")
        if self.issue_date is not None:
            parts = self.issue_date.split(".")
            if len(parts) != 3 or any(not part.isdigit() for part in parts):
                raise SourceRegistryError(
                    f"{self.source_id}: issue_date must use DD.MM.YY."
                )
        if self.private_storage_required and self.raw_content_in_repository:
            raise SourceRegistryError(
                f"{self.source_id}: private source bytes must not be committed."
            )
        if self.role in {
            SourceRole.SUPPORTING_SYNTHESIS,
            SourceRole.COGNITIVE_FOUNDATION,
            SourceRole.ADVERSARIAL_INPUT,
        } and self.controlling:
            raise SourceRegistryError(
                f"{self.source_id}: supporting or cognitive material cannot be controlling."
            )
        if self.controlling and self.currency_status not in {
            CurrencyStatus.CURRENT_FOR_BUNDLE,
            CurrencyStatus.CURRENCY_CHECK_REQUIRED,
        }:
            raise SourceRegistryError(
                f"{self.source_id}: controlling material requires an explicit currency state."
            )


@dataclass(frozen=True)
class SourceManifest:
    bundle_id: str
    bundle_date: str
    raw_files_committed: bool
    sources: tuple[SourceRecord, ...]
    required_missing_sources: tuple[str, ...] = ()
    review_notes: tuple[str, ...] = ()

    def validate(self) -> None:
        if not self.bundle_id.strip():
            raise SourceRegistryError("Source bundle requires an ID.")
        if self.raw_files_committed:
            raise SourceRegistryError(
                "Helpyou source manifests may not declare private raw manuals committed."
            )
        ids = [item.source_id for item in self.sources]
        if len(ids) != len(set(ids)):
            raise SourceRegistryError("Source IDs must be unique within a bundle.")
        for source in self.sources:
            source.validate()
        primary_fcom = [
            item
            for item in self.sources
            if item.source_id == "SIA-A350-FCOM-REV20"
            and item.role is SourceRole.CONTROLLED_OPERATIONAL
            and item.currency_status is CurrencyStatus.CURRENT_FOR_BUNDLE
        ]
        if len(primary_fcom) != 1:
            raise SourceRegistryError(
                "The SQ23 Rev20 bundle requires one current primary FCOM record."
            )

    @property
    def controlling_sources(self) -> tuple[SourceRecord, ...]:
        return tuple(item for item in self.sources if item.controlling)

    @property
    def supporting_only_sources(self) -> tuple[SourceRecord, ...]:
        return tuple(item for item in self.sources if not item.controlling)


def _strings(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    return tuple(str(item) for item in value)


def _record(data: Mapping[str, Any]) -> SourceRecord:
    return SourceRecord(
        source_id=str(data["source_id"]),
        title=str(data["title"]),
        role=SourceRole(str(data["role"])),
        controlling=bool(data.get("controlling", False)),
        revision=data.get("revision"),
        issue_date=data.get("issue_date"),
        currency_status=CurrencyStatus(
            str(data.get("currency_status", CurrencyStatus.NOT_APPLICABLE.value))
        ),
        authority_scope=_strings(data.get("authority_scope")),
        permitted_uses=_strings(data.get("permitted_uses")),
        prohibited_uses=_strings(data.get("prohibited_uses")),
        private_storage_required=bool(data.get("private_storage_required", False)),
        raw_content_in_repository=bool(data.get("raw_content_in_repository", False)),
        notes=_strings(data.get("notes")),
    )


def manifest_from_mapping(data: Mapping[str, Any]) -> SourceManifest:
    manifest = SourceManifest(
        bundle_id=str(data["bundle_id"]),
        bundle_date=str(data["bundle_date"]),
        raw_files_committed=bool(data.get("raw_files_committed", False)),
        sources=tuple(_record(item) for item in data.get("sources", ())),
        required_missing_sources=_strings(data.get("required_missing_sources")),
        review_notes=_strings(data.get("review_notes")),
    )
    manifest.validate()
    return manifest


def load_manifest(path: str | Path) -> SourceManifest:
    file_path = Path(path)
    with file_path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise SourceRegistryError("Source manifest root must be a JSON object.")
    return manifest_from_mapping(data)

"""Common governance metadata for official public-source snapshots.

The product connectors deliberately remain responsible for fetching and
normalising their own source data.  This module only gives every snapshot the
same auditable time/completeness contract and prevents callers from treating an
expired cache entry as current evidence.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from typing import Any


def _utc(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    else:
        text = str(value or "").strip()
        if not text:
            return None
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _iso(value: datetime | None) -> str | None:
    return value.astimezone(timezone.utc).isoformat() if value else None


def _inferred_completeness(snapshot: dict[str, Any]) -> str:
    status = str(snapshot.get("status") or "").strip().lower()
    if status == "available":
        if snapshot.get("parse_warnings") or snapshot.get("errors"):
            return "partial"
        return "complete_for_declared_scope"
    if status == "partial":
        return "partial"
    if status in {"unavailable", "disabled", "not_assessed"}:
        return "unavailable"
    return "unknown"


def govern_snapshot(
    snapshot: dict[str, Any],
    *,
    now: datetime | None = None,
    refresh_after_seconds: float,
    expires_after_seconds: float,
    scope: str,
    effective_start_utc: Any = None,
    effective_end_utc: Any = None,
    completeness_status: str | None = None,
) -> dict[str, Any]:
    """Return a copy with a normalized cache/effectivity ledger.

    ``complete_for_declared_scope`` means the connector completed the bounded
    source request it declares in ``snapshot_scope``.  It never means global or
    full-flight coverage unless that scope explicitly says so.
    """
    result = deepcopy(snapshot)
    checked_at = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    retrieved_at = _utc(result.get("retrieved_at_utc"))
    refresh_seconds = max(1.0, float(refresh_after_seconds))
    expiry_seconds = max(refresh_seconds, float(expires_after_seconds))
    refresh_after = (
        retrieved_at + timedelta(seconds=refresh_seconds)
        if retrieved_at
        else None
    )
    expires_at = (
        retrieved_at + timedelta(seconds=expiry_seconds)
        if retrieved_at
        else None
    )
    effective_start = _utc(effective_start_utc)
    effective_end = _utc(effective_end_utc)
    result.update({
        "snapshot_scope": str(scope or "").strip() or "unspecified",
        "effective_start_utc": _iso(effective_start),
        "effective_end_utc": _iso(effective_end),
        "refresh_after_utc": _iso(refresh_after),
        "expires_at_utc": _iso(expires_at),
        "completeness_status": (
            str(completeness_status).strip()
            if completeness_status
            else _inferred_completeness(result)
        ),
        "cache_reused": False,
    })
    if retrieved_at is None:
        result["reuse_status"] = "not_reusable"
        result["reuse_reason"] = "retrieval_time_missing"
    elif expires_at is not None and checked_at > expires_at:
        result["reuse_status"] = "not_reusable"
        result["reuse_reason"] = "snapshot_expired"
    else:
        result["reuse_status"] = "reusable"
        result["reuse_reason"] = None
    return result


def reusable_snapshot(
    snapshot: dict[str, Any],
    *,
    now: datetime | None = None,
) -> tuple[bool, str | None]:
    checked_at = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    retrieved_at = _utc(snapshot.get("retrieved_at_utc"))
    expires_at = _utc(snapshot.get("expires_at_utc"))
    if retrieved_at is None:
        return False, "retrieval_time_missing"
    if expires_at is None:
        return False, "expiry_missing"
    if checked_at > expires_at:
        return False, "snapshot_expired"
    if str(snapshot.get("status") or "").lower() in {
        "unavailable",
        "disabled",
        "not_assessed",
    }:
        return False, "source_unavailable"
    return True, None


def mark_snapshot_reused(
    snapshot: dict[str, Any],
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    result = deepcopy(snapshot)
    reusable, reason = reusable_snapshot(result, now=now)
    result["cache_reused"] = reusable
    result["reuse_status"] = "reusable" if reusable else "not_reusable"
    result["reuse_reason"] = reason
    result["reuse_checked_at_utc"] = _iso(
        (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    )
    return result


__all__ = [
    "govern_snapshot",
    "mark_snapshot_reused",
    "reusable_snapshot",
]

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.odss.snapshot_governance import (
    govern_snapshot,
    mark_snapshot_reused,
    reusable_snapshot,
)


UTC = timezone.utc


def test_available_snapshot_has_normalized_effectivity_and_cache_ledger() -> None:
    retrieved = datetime(2026, 7, 27, 1, 0, tzinfo=UTC)
    snapshot = govern_snapshot(
        {
            "status": "available",
            "provider": "official-test-source",
            "retrieved_at_utc": retrieved.isoformat(),
            "errors": [],
        },
        now=retrieved,
        refresh_after_seconds=60,
        expires_after_seconds=300,
        scope="bounded_test_feed",
        effective_start_utc=retrieved - timedelta(hours=1),
        effective_end_utc=retrieved + timedelta(hours=6),
    )

    assert snapshot["snapshot_scope"] == "bounded_test_feed"
    assert snapshot["effective_start_utc"] == "2026-07-27T00:00:00+00:00"
    assert snapshot["effective_end_utc"] == "2026-07-27T07:00:00+00:00"
    assert snapshot["refresh_after_utc"] == "2026-07-27T01:01:00+00:00"
    assert snapshot["expires_at_utc"] == "2026-07-27T01:05:00+00:00"
    assert snapshot["completeness_status"] == "complete_for_declared_scope"
    assert reusable_snapshot(
        snapshot,
        now=retrieved + timedelta(minutes=4),
    ) == (True, None)


def test_partial_snapshot_stays_partial_when_reused() -> None:
    retrieved = datetime(2026, 7, 27, 1, 0, tzinfo=UTC)
    snapshot = govern_snapshot(
        {
            "status": "partial",
            "provider": "official-test-source",
            "retrieved_at_utc": retrieved.isoformat(),
            "errors": [{"record": "unavailable"}],
        },
        now=retrieved,
        refresh_after_seconds=60,
        expires_after_seconds=300,
        scope="bounded_test_feed",
    )

    reused = mark_snapshot_reused(
        snapshot,
        now=retrieved + timedelta(minutes=2),
    )
    assert reused["cache_reused"] is True
    assert reused["completeness_status"] == "partial"
    assert reused["reuse_status"] == "reusable"


def test_expired_or_unavailable_snapshot_is_never_reusable() -> None:
    retrieved = datetime(2026, 7, 27, 1, 0, tzinfo=UTC)
    expired = govern_snapshot(
        {
            "status": "available",
            "retrieved_at_utc": retrieved.isoformat(),
        },
        now=retrieved,
        refresh_after_seconds=60,
        expires_after_seconds=120,
        scope="bounded_test_feed",
    )
    assert reusable_snapshot(
        expired,
        now=retrieved + timedelta(minutes=3),
    ) == (False, "snapshot_expired")

    unavailable = govern_snapshot(
        {
            "status": "unavailable",
            "retrieved_at_utc": retrieved.isoformat(),
        },
        now=retrieved,
        refresh_after_seconds=60,
        expires_after_seconds=120,
        scope="bounded_test_feed",
    )
    assert unavailable["completeness_status"] == "unavailable"
    assert reusable_snapshot(
        unavailable,
        now=retrieved + timedelta(seconds=30),
    ) == (False, "source_unavailable")

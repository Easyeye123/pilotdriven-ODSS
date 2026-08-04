"""Canonical PilotDriven product terminology.

The public product name is Flight Briefing. The legacy ODSS token may remain only
inside compatibility-sensitive technical identifiers and immutable history.
"""

from __future__ import annotations


PUBLIC_PRODUCT_NAME = "Flight Briefing"
LEGACY_TECHNICAL_TOKEN = "ODSS"
MIGRATION_LABEL = "Flight Briefing (formerly ODSS)"


def public_product_name() -> str:
    """Return the permanent pilot-facing name."""

    return PUBLIC_PRODUCT_NAME


def migration_label(*, required: bool = False) -> str:
    """Return a one-time migration label only when compatibility context requires it."""

    return MIGRATION_LABEL if required else PUBLIC_PRODUCT_NAME

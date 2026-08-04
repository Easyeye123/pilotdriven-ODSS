from __future__ import annotations

import unittest

from helpyou_core.terminology import (
    LEGACY_TECHNICAL_TOKEN,
    MIGRATION_LABEL,
    PUBLIC_PRODUCT_NAME,
    migration_label,
    public_product_name,
)


class FlightBriefingTerminologyTests(unittest.TestCase):
    def test_public_name_is_permanent_flight_briefing(self) -> None:
        self.assertEqual(PUBLIC_PRODUCT_NAME, "Flight Briefing")
        self.assertEqual(public_product_name(), "Flight Briefing")

    def test_no_fb_abbreviation_is_defined(self) -> None:
        self.assertNotEqual(PUBLIC_PRODUCT_NAME, "FB")
        self.assertNotIn("FB", {PUBLIC_PRODUCT_NAME, MIGRATION_LABEL})

    def test_legacy_token_is_technical_only(self) -> None:
        self.assertEqual(LEGACY_TECHNICAL_TOKEN, "ODSS")
        self.assertEqual(migration_label(), "Flight Briefing")
        self.assertEqual(migration_label(required=True), "Flight Briefing (formerly ODSS)")


if __name__ == "__main__":
    unittest.main()

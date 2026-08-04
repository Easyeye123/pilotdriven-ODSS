from __future__ import annotations

from datetime import datetime, timezone
import json
import unittest
from pathlib import Path

from helpyou_core.live_weather_policy import (
    WeatherEvidence,
    WeatherPolicyError,
    WeatherProduct,
    assert_claim_supported,
    load_weather_registry,
    preferred_provider_order,
    registry_from_mapping,
)


ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "fixtures" / "live_weather_source_registry.json"


class LiveWeatherPolicyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.registry = load_weather_registry(REGISTRY)

    def test_odss_owns_live_weather_and_helpyou_cannot_fetch(self) -> None:
        self.assertEqual(self.registry.owner, "ODSS")
        self.assertFalse(self.registry.helpyou_direct_network_fetch_permitted)

    def test_required_official_providers_and_products_are_registered(self) -> None:
        self.assertEqual(
            {item.provider_id for item in self.registry.providers},
            {"NOAA_AWC", "JMA", "BOM", "HKO"},
        )
        for provider in self.registry.providers:
            self.assertEqual(
                {item.product for item in provider.products},
                set(WeatherProduct),
            )

    def test_noaa_api_is_machine_source_for_global_opmet(self) -> None:
        noaa = self.registry.provider("NOAA_AWC")
        self.assertIn("/api/data/metar", noaa.capability(WeatherProduct.METAR).source)
        self.assertIn("/api/data/taf", noaa.capability(WeatherProduct.TAF).source)
        self.assertIn("/api/data/isigmet", noaa.capability(WeatherProduct.SIGMET).source)

    def test_issuing_authority_precedes_noaa_fallback(self) -> None:
        self.assertEqual(
            preferred_provider_order(
                self.registry, WeatherProduct.SIGMET, fir="RJJJ"
            ),
            ("JMA", "NOAA_AWC"),
        )
        self.assertEqual(
            preferred_provider_order(
                self.registry, WeatherProduct.SIGMET, fir="YMMM"
            ),
            ("BOM", "NOAA_AWC"),
        )
        self.assertEqual(
            preferred_provider_order(
                self.registry, WeatherProduct.SIGMET, fir="VHHK"
            ),
            ("HKO", "NOAA_AWC"),
        )

    def test_aerodrome_source_order_is_region_specific(self) -> None:
        self.assertEqual(
            preferred_provider_order(
                self.registry, WeatherProduct.TAF, aerodrome="RJAA"
            ),
            ("JMA", "NOAA_AWC"),
        )
        self.assertEqual(
            preferred_provider_order(
                self.registry, WeatherProduct.METAR, aerodrome="YSSY"
            ),
            ("BOM", "NOAA_AWC"),
        )
        self.assertEqual(
            preferred_provider_order(
                self.registry, WeatherProduct.METAR, aerodrome="VHHH"
            ),
            ("HKO", "NOAA_AWC"),
        )

    def test_satellite_is_supporting_only_for_every_provider(self) -> None:
        for provider in self.registry.providers:
            capability = provider.capability(WeatherProduct.SATELLITE)
            self.assertTrue(capability.supporting_only)
            self.assertNotIn("airport_minima", capability.allowed_claims)
            self.assertNotIn("official_sigmet", capability.allowed_claims)

    def test_satellite_cannot_support_sigmet_claim(self) -> None:
        with self.assertRaises(WeatherPolicyError):
            assert_claim_supported(
                self.registry,
                "JMA",
                WeatherProduct.SATELLITE,
                "official_sigmet",
            )

    def test_taf_requires_validity_interval(self) -> None:
        record = WeatherEvidence(
            product=WeatherProduct.TAF,
            provider_id="NOAA_AWC",
            source_url=self.registry.provider("NOAA_AWC")
            .capability(WeatherProduct.TAF)
            .source,
            station_or_fir="CYQX",
            raw_payload="TAF CYQX ...",
            issued_at=datetime(2026, 8, 4, 0, 0, tzinfo=timezone.utc),
            retrieved_at=datetime(2026, 8, 4, 0, 1, tzinfo=timezone.utc),
        )
        with self.assertRaises(WeatherPolicyError):
            record.validate(self.registry)

    def test_historical_replay_cannot_be_labelled_live(self) -> None:
        record = WeatherEvidence(
            product=WeatherProduct.METAR,
            provider_id="NOAA_AWC",
            source_url=self.registry.provider("NOAA_AWC")
            .capability(WeatherProduct.METAR)
            .source,
            station_or_fir="EINN",
            raw_payload="METAR EINN ...",
            issued_at=datetime(2026, 7, 25, 8, 0, tzinfo=timezone.utc),
            retrieved_at=datetime(2026, 8, 4, 0, 0, tzinfo=timezone.utc),
            historical_replay=True,
            labelled_live=True,
        )
        with self.assertRaises(WeatherPolicyError):
            record.validate(self.registry)

    def test_bom_access_warning_is_preserved(self) -> None:
        notes = " ".join(self.registry.provider("BOM").notes)
        self.assertIn("Airservices Australia", notes)
        self.assertIn("approved briefing channel", notes)

    def test_conflict_and_temporal_controls_cannot_be_disabled(self) -> None:
        data = json.loads(REGISTRY.read_text(encoding="utf-8"))
        data["policy"]["do_not_silently_merge_conflicts"] = False
        with self.assertRaises(WeatherPolicyError):
            registry_from_mapping(data)


if __name__ == "__main__":
    unittest.main()

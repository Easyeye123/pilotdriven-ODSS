from __future__ import annotations

from dataclasses import dataclass
import os
from urllib.parse import quote


@dataclass(frozen=True, slots=True)
class MapSettings:
    """Runtime configuration for the ODSS v0.6 map layer.

    API keys are deliberately read from the environment. They must never be
    embedded in the analysis JSON or committed to source control.
    """

    provider: str = "aws-location"
    aws_region: str = "ap-southeast-2"
    aws_location_api_key: str | None = None
    aws_location_server_api_key: str | None = None
    style: str = "Hybrid"
    language: str = "en"
    fallback: str = "static"
    screenshot_timeout_seconds: int = 30
    print_base_url: str = "http://127.0.0.1:8000"

    @classmethod
    def from_env(cls) -> "MapSettings":
        timeout_text = os.getenv("ODSS_MAP_SCREENSHOT_TIMEOUT_SECONDS", "30")
        try:
            timeout = int(timeout_text)
        except ValueError as exc:
            raise ValueError(
                "ODSS_MAP_SCREENSHOT_TIMEOUT_SECONDS must be an integer"
            ) from exc
        if timeout < 1 or timeout > 180:
            raise ValueError(
                "ODSS_MAP_SCREENSHOT_TIMEOUT_SECONDS must be between 1 and 180"
            )

        settings = cls(
            provider=os.getenv("ODSS_MAP_PROVIDER", "aws-location").strip(),
            aws_region=os.getenv("AWS_REGION", "ap-southeast-2").strip(),
            aws_location_api_key=(
                os.getenv("AWS_LOCATION_API_KEY", "").strip() or None
            ),
            aws_location_server_api_key=(
                os.getenv("AWS_LOCATION_SERVER_API_KEY", "").strip() or None
            ),
            style=os.getenv("ODSS_MAP_STYLE", "Hybrid").strip(),
            language=os.getenv("ODSS_MAP_LANGUAGE", "en").strip(),
            fallback=os.getenv("ODSS_MAP_FALLBACK", "static").strip(),
            screenshot_timeout_seconds=timeout,
            print_base_url=os.getenv(
                "ODSS_MAP_PRINT_BASE_URL", "http://127.0.0.1:8000"
            ).rstrip("/"),
        )
        settings.validate()
        return settings

    def validate(self) -> None:
        if self.provider not in {"aws-location", "schematic"}:
            raise ValueError(
                "ODSS_MAP_PROVIDER must be aws-location or schematic"
            )
        if self.style not in {
            "Standard",
            "Monochrome",
            "Hybrid",
            "Satellite",
        }:
            raise ValueError(
                "ODSS_MAP_STYLE must be Standard, Monochrome, Hybrid or Satellite"
            )
        if self.fallback not in {"static", "schematic", "none"}:
            raise ValueError(
                "ODSS_MAP_FALLBACK must be static, schematic or none"
            )
        if not self.aws_region:
            raise ValueError("AWS_REGION is required")
        if not self.language:
            raise ValueError("ODSS_MAP_LANGUAGE is required")
        if self.aws_region in {"ap-southeast-1", "ap-southeast-5"} and (
            self.style in {"Hybrid", "Satellite"} or self.fallback == "static"
        ):
            raise ValueError(
                "Hybrid/Satellite maps are unavailable in AWS GrabMaps regions "
                "ap-southeast-1 and ap-southeast-5; use ap-southeast-2 for the "
                "accepted Hybrid/static architecture"
            )

    @property
    def style_descriptor_url(self) -> str | None:
        """MapLibre-compatible Amazon Location Maps V2 style URL."""
        if self.provider != "aws-location" or not self.aws_location_api_key:
            return None
        return (
            f"https://maps.geo.{self.aws_region}.amazonaws.com/"
            f"v2/styles/{quote(self.style)}/descriptor"
            f"?key={quote(self.aws_location_api_key)}"
        )

    @property
    def static_map_endpoint(self) -> str:
        """Base URL for the Amazon Location Maps V2 GetStaticMap API."""
        return (
            f"https://maps.geo.{self.aws_region}.amazonaws.com/v2/static/map@2x"
        )

    @property
    def static_map_api_key(self) -> str | None:
        """Server-only static-map key, with the legacy single-key fallback."""
        return self.aws_location_server_api_key or self.aws_location_api_key

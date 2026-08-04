"""Official live-weather source governance for CFP-grounded Helpyou scenarios.

ODSS owns all network acquisition, temporal/geospatial validation and immutable
weather snapshots. Helpyou consumes the snapshot and must not fetch or reinterpret
live weather independently.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
import json
from pathlib import Path
from typing import Any, Mapping


class WeatherPolicyError(ValueError):
    """Raised when live-weather source or evidence boundaries are violated."""


class WeatherProduct(str, Enum):
    METAR = "METAR"
    TAF = "TAF"
    SIGMET = "SIGMET"
    SATELLITE = "SATELLITE"


class AccessMode(str, Enum):
    API = "API"
    OFFICIAL_WEB_ADAPTER = "OFFICIAL_WEB_ADAPTER"
    OFFICIAL_WEB_LAYER = "OFFICIAL_WEB_LAYER"
    OFFICIAL_IMAGE = "OFFICIAL_IMAGE"


class ProviderRole(str, Enum):
    GLOBAL_AGGREGATOR_AND_US_ISSUER = "global_aggregator_and_us_issuer"
    ISSUING_AUTHORITY = "issuing_authority"
    ISSUING_AUTHORITY_AND_REGIONAL_MONITOR = (
        "issuing_authority_and_regional_monitor"
    )


_FORBIDDEN_SUPPORTING_ONLY_CLAIMS = {
    "official_sigmet",
    "raw_observation",
    "raw_forecast",
    "airport_minima",
    "runway_suitability",
    "landing_performance",
}


@dataclass(frozen=True)
class ProductCapability:
    product: WeatherProduct
    access_mode: AccessMode
    source: str
    coverage: str
    issuing_authority: bool
    supporting_only: bool
    allowed_claims: tuple[str, ...]

    def validate(self) -> None:
        if not self.source.startswith("https://"):
            raise WeatherPolicyError(
                f"{self.product.value}: official source must use HTTPS."
            )
        if not self.coverage.strip():
            raise WeatherPolicyError(
                f"{self.product.value}: coverage must be stated."
            )
        if not self.allowed_claims:
            raise WeatherPolicyError(
                f"{self.product.value}: at least one allowed claim is required."
            )
        if self.supporting_only:
            forbidden = _FORBIDDEN_SUPPORTING_ONLY_CLAIMS.intersection(
                self.allowed_claims
            )
            if forbidden:
                raise WeatherPolicyError(
                    f"{self.product.value}: supporting-only product cannot support "
                    f"operational claims {sorted(forbidden)}."
                )
        if self.product is WeatherProduct.SATELLITE and not self.supporting_only:
            raise WeatherPolicyError(
                "Satellite imagery must remain supporting evidence only."
            )


@dataclass(frozen=True)
class WeatherProvider:
    provider_id: str
    name: str
    official_domains: tuple[str, ...]
    provider_role: ProviderRole
    products: tuple[ProductCapability, ...]
    notes: tuple[str, ...] = ()

    def validate(self) -> None:
        if not self.provider_id.strip() or not self.name.strip():
            raise WeatherPolicyError("Every provider requires a stable ID and name.")
        if not self.official_domains:
            raise WeatherPolicyError(
                f"{self.provider_id}: at least one official domain is required."
            )
        products = [item.product for item in self.products]
        if len(products) != len(set(products)):
            raise WeatherPolicyError(
                f"{self.provider_id}: product capabilities must be unique."
            )
        for capability in self.products:
            capability.validate()
            host_allowed = any(
                domain in capability.source for domain in self.official_domains
            )
            if not host_allowed:
                raise WeatherPolicyError(
                    f"{self.provider_id}: source is outside registered official domains."
                )

    def capability(self, product: WeatherProduct) -> ProductCapability:
        for item in self.products:
            if item.product is product:
                return item
        raise WeatherPolicyError(
            f"{self.provider_id}: {product.value} is not registered."
        )


@dataclass(frozen=True)
class WeatherSourceRegistry:
    registry_id: str
    registry_date: str
    owner: str
    helpyou_direct_network_fetch_permitted: bool
    policy: Mapping[str, bool]
    regional_authority: Mapping[str, str]
    providers: tuple[WeatherProvider, ...]

    def validate(self) -> None:
        if self.owner != "ODSS":
            raise WeatherPolicyError("ODSS must own live-weather acquisition.")
        if self.helpyou_direct_network_fetch_permitted:
            raise WeatherPolicyError(
                "Helpyou Chat must not fetch live weather independently of ODSS."
            )
        required_policy = {
            "issuing_authority_first",
            "preserve_raw_and_decoded_payloads",
            "preserve_issue_validity_and_retrieval_times",
            "do_not_silently_merge_conflicts",
            "satellite_is_supporting_evidence_only",
            "taf_must_cover_projected_arrival",
            "sigmet_must_intersect_route_and_valid_time",
            "historical_replay_must_not_be_labelled_live",
        }
        missing = sorted(
            key for key in required_policy if self.policy.get(key) is not True
        )
        if missing:
            raise WeatherPolicyError(
                f"Weather policy invariants missing or disabled: {missing}."
            )
        ids = [item.provider_id for item in self.providers]
        if len(ids) != len(set(ids)):
            raise WeatherPolicyError("Weather provider IDs must be unique.")
        if set(ids) != {"NOAA_AWC", "JMA", "BOM", "HKO"}:
            raise WeatherPolicyError(
                "Registry must contain NOAA_AWC, JMA, BOM and HKO."
            )
        for provider in self.providers:
            provider.validate()
            registered = {item.product for item in provider.products}
            if registered != set(WeatherProduct):
                raise WeatherPolicyError(
                    f"{provider.provider_id}: all four weather products are required."
                )
        provider_ids = set(ids)
        unknown = sorted(
            provider_id
            for provider_id in self.regional_authority.values()
            if provider_id not in provider_ids
        )
        if unknown:
            raise WeatherPolicyError(
                f"Regional authority map contains unknown providers: {unknown}."
            )
        for local_id in ("JMA", "BOM", "HKO"):
            provider = self.provider(local_id)
            if not provider.capability(WeatherProduct.SIGMET).issuing_authority:
                raise WeatherPolicyError(
                    f"{local_id}: local SIGMET capability must be issuing authority."
                )
        for provider in self.providers:
            if not provider.capability(WeatherProduct.SATELLITE).supporting_only:
                raise WeatherPolicyError(
                    f"{provider.provider_id}: satellite must be supporting only."
                )

    def provider(self, provider_id: str) -> WeatherProvider:
        for item in self.providers:
            if item.provider_id == provider_id:
                return item
        raise WeatherPolicyError(f"Unknown weather provider: {provider_id}.")


@dataclass(frozen=True)
class WeatherEvidence:
    product: WeatherProduct
    provider_id: str
    source_url: str
    station_or_fir: str
    raw_payload: str
    issued_at: datetime
    retrieved_at: datetime
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    historical_replay: bool = False
    labelled_live: bool = True

    def validate(self, registry: WeatherSourceRegistry) -> None:
        provider = registry.provider(self.provider_id)
        capability = provider.capability(self.product)
        if self.source_url != capability.source:
            raise WeatherPolicyError(
                f"{self.provider_id}: evidence source does not match registry."
            )
        if not self.station_or_fir.strip() or not self.raw_payload.strip():
            raise WeatherPolicyError(
                "Weather evidence requires scope and preserved raw payload/reference."
            )
        for label, value in (
            ("issued_at", self.issued_at),
            ("retrieved_at", self.retrieved_at),
        ):
            if value.tzinfo is None or value.utcoffset() is None:
                raise WeatherPolicyError(f"{label} must be timezone-aware.")
        if self.retrieved_at < self.issued_at:
            raise WeatherPolicyError(
                "Weather retrieval time cannot precede the product issue time."
            )
        if self.product in {WeatherProduct.TAF, WeatherProduct.SIGMET}:
            if self.valid_from is None or self.valid_to is None:
                raise WeatherPolicyError(
                    f"{self.product.value} requires an explicit validity interval."
                )
            if self.valid_from.tzinfo is None or self.valid_to.tzinfo is None:
                raise WeatherPolicyError(
                    f"{self.product.value} validity must be timezone-aware."
                )
            if self.valid_to <= self.valid_from:
                raise WeatherPolicyError(
                    f"{self.product.value} validity interval is invalid."
                )
        if self.historical_replay and self.labelled_live:
            raise WeatherPolicyError(
                "Historical replay weather must not be labelled as live."
            )


def _strings(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    return tuple(str(item) for item in value)


def _capability(data: Mapping[str, Any]) -> ProductCapability:
    return ProductCapability(
        product=WeatherProduct(str(data["product"])),
        access_mode=AccessMode(str(data["access_mode"])),
        source=str(data["source"]),
        coverage=str(data["coverage"]),
        issuing_authority=bool(data.get("issuing_authority", False)),
        supporting_only=bool(data.get("supporting_only", False)),
        allowed_claims=_strings(data.get("allowed_claims")),
    )


def _provider(data: Mapping[str, Any]) -> WeatherProvider:
    return WeatherProvider(
        provider_id=str(data["provider_id"]),
        name=str(data["name"]),
        official_domains=_strings(data.get("official_domains")),
        provider_role=ProviderRole(str(data["provider_role"])),
        products=tuple(_capability(item) for item in data.get("products", ())),
        notes=_strings(data.get("notes")),
    )


def registry_from_mapping(data: Mapping[str, Any]) -> WeatherSourceRegistry:
    registry = WeatherSourceRegistry(
        registry_id=str(data["registry_id"]),
        registry_date=str(data["registry_date"]),
        owner=str(data["owner"]),
        helpyou_direct_network_fetch_permitted=bool(
            data.get("helpyou_direct_network_fetch_permitted", False)
        ),
        policy=dict(data.get("policy", {})),
        regional_authority=dict(data.get("regional_authority", {})),
        providers=tuple(_provider(item) for item in data.get("providers", ())),
    )
    registry.validate()
    return registry


def load_weather_registry(path: str | Path) -> WeatherSourceRegistry:
    file_path = Path(path)
    with file_path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise WeatherPolicyError("Weather registry root must be a JSON object.")
    return registry_from_mapping(data)


def preferred_provider_order(
    registry: WeatherSourceRegistry,
    product: WeatherProduct,
    *,
    fir: str | None = None,
    aerodrome: str | None = None,
) -> tuple[str, ...]:
    """Return issuing authority first, with NOAA as global machine fallback.

    The caller remains responsible for FIR/aerodrome mapping beyond the explicitly
    registered regions. This function does not infer operational suitability.
    """

    local_id: str | None = None
    if fir:
        local_id = registry.regional_authority.get(fir.upper())
    if local_id is None and aerodrome:
        code = aerodrome.upper()
        if code.startswith(("RJ", "RO")):
            local_id = "JMA"
        elif code.startswith("Y"):
            local_id = "BOM"
        elif code == "VHHH":
            local_id = "HKO"
        elif code.startswith(("K", "P")):
            local_id = "NOAA_AWC"
    if local_id is None:
        return ("NOAA_AWC",)
    if local_id == "NOAA_AWC":
        return ("NOAA_AWC",)
    registry.provider(local_id).capability(product)
    return (local_id, "NOAA_AWC")


def assert_claim_supported(
    registry: WeatherSourceRegistry,
    provider_id: str,
    product: WeatherProduct,
    claim: str,
) -> None:
    capability = registry.provider(provider_id).capability(product)
    if claim not in capability.allowed_claims:
        raise WeatherPolicyError(
            f"{provider_id} {product.value} cannot support claim '{claim}'."
        )

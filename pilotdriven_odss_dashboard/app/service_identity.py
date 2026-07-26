from __future__ import annotations

from dataclasses import dataclass
import re

from fastapi import HTTPException, Request


_TENANT_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$")
_IDENTITY_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@+-]{0,127}$")
_OPTIONAL_CONTEXT_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@+-]{0,127}$")


@dataclass(frozen=True, slots=True)
class ServiceIdentity:
    """Trusted PilotDriven identity attached by the authenticated server proxy."""

    tenant_id: str
    user_id: str
    workspace_id: str | None = None
    flight_id: str | None = None
    request_id: str | None = None


def _required_header(request: Request, name: str, pattern: re.Pattern[str]) -> str:
    value = request.headers.get(name, "").strip()
    if not value or not pattern.fullmatch(value):
        raise HTTPException(
            status_code=400,
            detail=f"Trusted {name} context is required.",
        )
    return value


def _optional_header(request: Request, name: str) -> str | None:
    value = request.headers.get(name, "").strip()
    if not value:
        return None
    if not _OPTIONAL_CONTEXT_PATTERN.fullmatch(value):
        raise HTTPException(status_code=400, detail=f"Trusted {name} context is invalid.")
    return value


def service_identity_from_request(request: Request) -> ServiceIdentity:
    """Validate the service-to-service identity after bearer authentication."""

    return ServiceIdentity(
        tenant_id=_required_header(
            request,
            "x-pilotdriven-tenant-id",
            _TENANT_PATTERN,
        ),
        user_id=_required_header(
            request,
            "x-pilotdriven-user-id",
            _IDENTITY_PATTERN,
        ),
        workspace_id=_optional_header(request, "x-pilotdriven-workspace-id"),
        flight_id=_optional_header(request, "x-pilotdriven-flight-id"),
        request_id=_optional_header(request, "x-pilotdriven-request-id"),
    )


def request_service_identity(request: Request) -> ServiceIdentity:
    identity = getattr(request.state, "service_identity", None)
    if not isinstance(identity, ServiceIdentity):
        raise HTTPException(status_code=401, detail="Trusted service identity is unavailable.")
    return identity

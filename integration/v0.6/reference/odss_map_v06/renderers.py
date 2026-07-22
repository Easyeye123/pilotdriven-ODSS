from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from .contract import MapContract


class MapRenderError(RuntimeError):
    """Raised when a map renderer cannot produce a usable artifact."""


_SECRET_QUERY_VALUE = re.compile(r"([?&](?:key|token)=)[^&\s\"']+", re.IGNORECASE)


def _safe_error_text(exc: Exception) -> str:
    """Keep renderer diagnostics without persisting URL credentials."""
    return _SECRET_QUERY_VALUE.sub(r"\1[redacted]", str(exc))


@dataclass(slots=True)
class MapRenderResult:
    provider: str
    mode: str
    content: bytes
    media_type: str
    label: str
    warnings: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def write(self, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(self.content)
        return path


class MapRenderer(Protocol):
    name: str

    async def interactive_config(
        self,
        contract: MapContract,
    ) -> dict[str, Any]:
        ...

    async def render_snapshot(
        self,
        contract: MapContract,
        *,
        width: int,
        height: int,
    ) -> MapRenderResult:
        ...


class RendererChain:
    """Run the primary renderer, then explicit fallbacks in order."""

    def __init__(self, *renderers: MapRenderer):
        if not renderers:
            raise ValueError("At least one renderer is required")
        self._renderers = renderers

    async def render_snapshot(
        self,
        contract: MapContract,
        *,
        width: int,
        height: int,
    ) -> MapRenderResult:
        failures: list[str] = []
        for renderer in self._renderers:
            try:
                result = await renderer.render_snapshot(
                    contract,
                    width=width,
                    height=height,
                )
                result.warnings[:0] = failures
                return result
            except Exception as exc:
                failures.append(
                    f"{renderer.name} unavailable: {type(exc).__name__}: "
                    f"{_safe_error_text(exc)}"
                )
        raise MapRenderError("; ".join(failures))

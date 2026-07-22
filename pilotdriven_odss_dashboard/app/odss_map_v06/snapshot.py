from __future__ import annotations

import asyncio
from urllib.parse import quote, urlsplit

from playwright.async_api import TimeoutError as PlaywrightTimeoutError
from playwright.async_api import async_playwright

from .config import MapSettings
from .contract import MapContract
from .renderers import MapRenderError, MapRenderResult


async def _close_quietly(resource) -> None:
    """Bound Playwright cleanup so a captured map is not lost on shutdown."""
    try:
        await asyncio.wait_for(resource.close(), timeout=5)
    except Exception:
        pass


def _chromium_launch_args() -> list[str]:
    """Enable deterministic WebGL rendering on GPU-less Linux workers.

    Chromium 138 removed automatic SwiftShader fallback for WebGL. MapLibre
    therefore needs the explicit opt-in when the report worker has no GPU, as
    is normal for a Render container. Interactive desktop browsers continue to
    use their regular hardware-backed WebGL path.
    """
    return [
        "--disable-dev-shm-usage",
        "--font-render-hinting=none",
        "--use-gl=angle",
        "--use-angle=swiftshader-webgl",
        "--enable-unsafe-swiftshader",
    ]


def _request_headers_for_url(
    request_url: str,
    request_headers: dict[str, str],
    settings: MapSettings,
) -> dict[str, str]:
    """Attach the service bearer only to the internal print origin.

    A browser-context-wide Authorization header also reaches Amazon Location
    tile requests, turning them into failing cross-origin requests and leaking
    an internal credential outside ODSS.
    """
    headers = dict(request_headers)
    headers.pop("authorization", None)
    target = urlsplit(request_url)
    internal = urlsplit(settings.print_base_url)
    if (
        settings.service_token
        and target.scheme == internal.scheme
        and target.netloc == internal.netloc
    ):
        headers["authorization"] = f"Bearer {settings.service_token}"
    return headers


class PlaywrightMapSnapshotRenderer:
    """Capture the same MapLibre map used by the web dashboard."""

    name = "aws-location-hybrid-playwright"

    def __init__(self, settings: MapSettings):
        self.settings = settings

    async def interactive_config(
        self,
        contract: MapContract,
    ) -> dict:
        style_url = self.settings.style_descriptor_url
        if not style_url:
            raise MapRenderError("AWS Location API key is not configured")
        return {
            "provider": self.name,
            "style_url": style_url,
            "contract_route_hash": contract.route_hash,
        }

    async def render_snapshot(
        self,
        contract: MapContract,
        *,
        width: int,
        height: int,
    ) -> MapRenderResult:
        if not self.settings.aws_location_api_key:
            raise MapRenderError("AWS Location API key is not configured")
        if not self.settings.service_token:
            raise MapRenderError("ODSS service token is not configured for print capture")

        viewport_width = max(800, int(width))
        viewport_height = max(450, int(height))
        timeout_ms = self.settings.screenshot_timeout_seconds * 1_000
        settle_timeout_ms = max(1_000, min(15_000, timeout_ms // 2))
        target = (
            f"{self.settings.print_base_url}/render/maps/"
            f"{quote(str(contract.metadata.get('analysis_id') or contract.route_hash))}"
            f"?route_hash={quote(contract.route_hash)}"
        )
        capture_stage = "Chromium startup"

        try:
            async with async_playwright() as playwright:
                capture_stage = "Chromium startup"
                browser = await playwright.chromium.launch(
                    headless=True,
                    args=_chromium_launch_args(),
                )
                try:
                    capture_stage = "browser context setup"
                    context = await browser.new_context(
                        viewport={
                            "width": viewport_width,
                            "height": viewport_height,
                        },
                        # Keep the server-side framebuffer at the requested
                        # 1600x900. A 2x framebuffer is four times the pixels
                        # and can exhaust the free Render worker while adding
                        # no useful detail at the PDF's physical map size.
                        device_scale_factor=1,
                    )
                    try:
                        async def authorize_internal_request(route, request):
                            await route.continue_(
                                headers=_request_headers_for_url(
                                    request.url,
                                    request.headers,
                                    self.settings,
                                )
                            )

                        capture_stage = "internal request authorization"
                        await context.route("**/*", authorize_internal_request)
                        capture_stage = "print page creation"
                        page = await context.new_page()
                        capture_stage = "print page navigation"
                        try:
                            await page.goto(
                                target,
                                wait_until="domcontentloaded",
                                timeout=timeout_ms,
                            )
                        except PlaywrightTimeoutError as exc:
                            raise MapRenderError(
                                "Print page navigation did not reach DOMContentLoaded"
                            ) from exc
                        capture_stage = "MapLibre readiness"
                        try:
                            await page.wait_for_function(
                                """(settleTimeoutMs) => {
                                  if (window.__ODSS_MAP_READY__ === true) {
                                    window.__ODSS_MAP_CAPTURE_REASON__ = 'map-ready';
                                    return true;
                                  }
                                  if (window.__ODSS_MAP_ERROR__) return true;
                                  const map = window.__ODSS_MAP_INSTANCE__;
                                  if (!map) return false;
                                  try {
                                    const loaded = map.isStyleLoaded()
                                      && (typeof map.areTilesLoaded !== 'function' || map.areTilesLoaded());
                                    if (loaded) {
                                      window.__ODSS_MAP_CAPTURE_REASON__ = 'tiles-loaded';
                                      return true;
                                    }
                                    const layersReadyAt = Number(window.__ODSS_MAP_LAYERS_READY_AT__ || 0);
                                    const settled = layersReadyAt > 0
                                      && Date.now() - layersReadyAt >= settleTimeoutMs;
                                    if (settled) window.__ODSS_MAP_CAPTURE_REASON__ = 'bounded-settle';
                                    return settled;
                                  } catch (_) {
                                    return false;
                                  }
                                }""",
                                arg=settle_timeout_ms,
                                timeout=timeout_ms,
                            )
                        except PlaywrightTimeoutError as exc:
                            state = await page.evaluate(
                                """() => {
                                  const map = window.__ODSS_MAP_INSTANCE__;
                                  const result = {
                                    ready: window.__ODSS_MAP_READY__ === true,
                                    error: Boolean(window.__ODSS_MAP_ERROR__),
                                    hasMap: Boolean(map),
                                    styleLoaded: false,
                                    tilesLoaded: false,
                                  };
                                  if (!map) return result;
                                  try { result.styleLoaded = map.isStyleLoaded(); } catch (_) {}
                                  try {
                                    result.tilesLoaded = typeof map.areTilesLoaded !== 'function'
                                      || map.areTilesLoaded();
                                  } catch (_) {}
                                  return result;
                                }"""
                            )
                            raise MapRenderError(
                                "MapLibre print map did not become ready before timeout "
                                f"(map={bool(state.get('hasMap'))}; "
                                f"style={bool(state.get('styleLoaded'))}; "
                                f"tiles={bool(state.get('tilesLoaded'))}; "
                                f"ready={bool(state.get('ready'))}; "
                                f"error={bool(state.get('error'))})"
                            ) from exc
                        capture_stage = "MapLibre error check"
                        page_error = await page.evaluate("window.__ODSS_MAP_ERROR__")
                        if page_error:
                            raise MapRenderError(f"MapLibre print page failed: {page_error}")
                        capture_stage = "MapLibre state verification"
                        capture_state = await page.evaluate(
                            """() => {
                              const map = window.__ODSS_MAP_INSTANCE__;
                              const result = {
                                reason: window.__ODSS_MAP_CAPTURE_REASON__ || null,
                                styleLoaded: false,
                                tilesLoaded: false,
                              };
                              if (!map) return result;
                              try { result.styleLoaded = map.isStyleLoaded(); } catch (_) {}
                              try {
                                result.tilesLoaded = typeof map.areTilesLoaded !== 'function'
                                  || map.areTilesLoaded();
                              } catch (_) {}
                              return result;
                            }"""
                        )
                        capture_readiness = capture_state.get("reason") or "verified-state"
                        capture_stage = "route hash verification"
                        rendered_hash = await page.get_attribute("html", "data-route-hash")
                        if rendered_hash != contract.route_hash:
                            raise MapRenderError("Rendered map route hash does not match the contract")
                        capture_stage = "font and frame settling"
                        await page.evaluate(
                            """async () => {
                              if (document.fonts) {
                                await Promise.race([
                                  document.fonts.ready,
                                  new Promise((resolve) => setTimeout(resolve, 2000)),
                                ]);
                              }
                              await new Promise((resolve) => requestAnimationFrame(
                                () => requestAnimationFrame(resolve),
                              ));
                            }"""
                        )
                        capture_stage = "print map bounds"
                        clip = await page.evaluate(
                            """() => {
                              const element = document.getElementById('odss-print-map');
                              if (!element) return null;
                              const bounds = element.getBoundingClientRect();
                              if (bounds.width <= 0 || bounds.height <= 0) return null;
                              return {
                                x: bounds.x,
                                y: bounds.y,
                                width: bounds.width,
                                height: bounds.height,
                              };
                            }"""
                        )
                        if not clip:
                            raise MapRenderError("Print map has no visible capture bounds")
                        capture_stage = "direct print-map screenshot"
                        try:
                            image = await page.screenshot(
                                type="png",
                                clip=clip,
                                animations="disabled",
                                caret="hide",
                                timeout=min(30_000, timeout_ms),
                            )
                        except PlaywrightTimeoutError as exc:
                            raise MapRenderError(
                                "Direct print-map screenshot did not complete"
                            ) from exc
                    finally:
                        await _close_quietly(context)
                finally:
                    await _close_quietly(browser)
        except PlaywrightTimeoutError as exc:
            raise MapRenderError(
                f"MapLibre print map timed out during {capture_stage}"
            ) from exc
        except Exception as exc:
            raise MapRenderError(
                f"Playwright map capture failed: {type(exc).__name__}: {exc}"
            ) from exc

        return MapRenderResult(
            provider=self.name,
            mode="primary",
            content=image,
            media_type="image/png",
            label="Amazon Location Hybrid",
            warnings=list(contract.warnings),
            metadata={
                "route_hash": contract.route_hash,
                "style": self.settings.style,
                "width": viewport_width,
                "height": viewport_height,
                "capture_readiness": capture_readiness,
            },
        )

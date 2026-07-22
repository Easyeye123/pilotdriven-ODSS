from __future__ import annotations

from urllib.parse import quote

from playwright.async_api import TimeoutError as PlaywrightTimeoutError
from playwright.async_api import async_playwright

from .config import MapSettings
from .contract import MapContract
from .renderers import MapRenderError, MapRenderResult


def _chromium_launch_args() -> list[str]:
    """Enable deterministic WebGL rendering on GPU-less Linux workers."""
    return [
        "--disable-dev-shm-usage",
        "--font-render-hinting=none",
        "--use-gl=angle",
        "--use-angle=swiftshader-webgl",
        "--enable-unsafe-swiftshader",
    ]


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

        viewport_width = max(800, int(width))
        viewport_height = max(450, int(height))
        target = (
            f"{self.settings.print_base_url}/render/maps/"
            f"{quote(str(contract.metadata.get('analysis_id') or contract.route_hash))}"
            f"?route_hash={quote(contract.route_hash)}"
        )

        try:
            async with async_playwright() as playwright:
                browser = await playwright.chromium.launch(
                    headless=True,
                    args=_chromium_launch_args(),
                )
                context = await browser.new_context(
                    viewport={
                        "width": viewport_width,
                        "height": viewport_height,
                    },
                    device_scale_factor=2,
                )
                page = await context.new_page()
                await page.goto(
                    target,
                    wait_until="domcontentloaded",
                    timeout=self.settings.screenshot_timeout_seconds * 1000,
                )
                try:
                    await page.wait_for_function(
                        """() => {
                          if (window.__ODSS_MAP_READY__ === true || window.__ODSS_MAP_ERROR__) {
                            return true;
                          }
                          const map = window.__ODSS_MAP_INSTANCE__;
                          if (!map) return false;
                          try {
                            return map.isStyleLoaded()
                              && (typeof map.areTilesLoaded !== 'function' || map.areTilesLoaded());
                          } catch (_) {
                            return false;
                          }
                        }""",
                        timeout=self.settings.screenshot_timeout_seconds * 1000,
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
                page_error = await page.evaluate("window.__ODSS_MAP_ERROR__")
                if page_error:
                    raise MapRenderError(f"MapLibre print page failed: {page_error}")
                rendered_hash = await page.get_attribute("html", "data-route-hash")
                if rendered_hash != contract.route_hash:
                    raise MapRenderError("Rendered map route hash does not match the contract")
                locator = page.locator("#odss-print-map")
                image = await locator.screenshot(type="png")
                await context.close()
                await browser.close()
        except PlaywrightTimeoutError as exc:
            raise MapRenderError(
                "MapLibre print map did not become ready before timeout"
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
            },
        )

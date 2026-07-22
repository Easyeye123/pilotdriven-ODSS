from __future__ import annotations

import asyncio
from pathlib import Path
import sys

from playwright.async_api import async_playwright

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.odss_map_v06.snapshot import _chromium_launch_args


async def main() -> None:
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(
            headless=True,
            args=_chromium_launch_args(),
        )
        try:
            page = await browser.new_page()
            available = await page.evaluate(
                """() => {
                  const canvas = document.createElement('canvas');
                  return Boolean(canvas.getContext('webgl2'));
                }"""
            )
            if not available:
                raise RuntimeError("Chromium WebGL2 is unavailable")
            print("Chromium WebGL2 smoke check passed")
        finally:
            await browser.close()


if __name__ == "__main__":
    asyncio.run(main())

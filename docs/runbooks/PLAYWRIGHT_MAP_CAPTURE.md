# Playwright map-capture runbook

## Installation

```bash
python -m pip install -r integration/v0.6/reference/requirements-map.txt
python -m playwright install chromium
```

For a Linux container, install the documented Playwright browser dependencies or use the official Playwright base image in a dedicated report worker.

## Print endpoint

The internal endpoint must render only the map and required attribution:

```text
GET /render/maps/{analysis_id}?route_hash=<hash>
```

The route hash prevents a stale report job from capturing a newer route.

## Ready signal

The print page sets:

```javascript
window.__ODSS_MAP_READY__ = true;
```

only after the MapLibre map reaches the expected idle state and the route/marker layers exist.

## Capture sequence

```python
async with async_playwright() as playwright:
    browser = await playwright.chromium.launch(headless=True)
    page = await browser.new_page(
        viewport={"width": 2200, "height": 1100},
        device_scale_factor=2,
    )
    await page.goto(print_url, wait_until="domcontentloaded")
    await page.wait_for_function(
        "window.__ODSS_MAP_READY__ === true",
        timeout=30_000,
    )
    image = await page.locator("#odss-print-map").screenshot(type="png")
```

## Output metadata

Store:

- analysis ID;
- route hash;
- map contract version;
- provider;
- style;
- viewport;
- device scale factor;
- generated UTC;
- warnings/fallback reason.

## Timeout handling

On timeout or browser failure:

1. log the primary failure;
2. call Amazon Location static fallback;
3. if that fails, render schematic fallback;
4. display the fallback label in the PDF;
5. retain all errors in analysis/report metadata.

## Container recommendations

- run report capture in a worker, not the API request thread;
- cap concurrent Chromium processes;
- use `/dev/shm` appropriately;
- apply egress controls;
- set CPU/memory limits;
- cache generated map images by route hash/style where permitted;
- never cache across tenants without a tenant-safe key.

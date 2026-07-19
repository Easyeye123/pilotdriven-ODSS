# ODSS v0.6 — Phases 1 to 7 implementation and handoff plan

This document is the controlling phase-by-phase plan for moving the current ODSS v0.5 schematic briefing into the final realistic-map standard and then integrating it into `pilotdriven.com`.

## Phase 1 — Freeze and preserve the v0.5 baseline

### Objective

Preserve a known-working schematic implementation before introducing network mapping and browser capture.

### Completed baseline

The repository branch:

```text
archive/odss-v0.5-schematic-baseline
```

points to the v0.5 visual route briefing implementation.

### Actions

1. Keep the v0.5 parser, deterministic engines and schematic route renderer unchanged on the archive branch.
2. Do not visually refine the schematic renderer further.
3. Retain the renderer in `main` as the final offline fallback.
4. Record the baseline route hash and sample outputs for SQ303 and SQ304.
5. Ensure no generated CFP, PDF, database or API-key file is committed.

### Deliverables

- frozen archive branch;
- v0.5 changelog and visual samples;
- fallback label: `Schematic route display — basemap unavailable`;
- regression test proving the fallback still renders.

### Exit criteria

- existing dashboard tests pass;
- Level 1 and Level 2 schematic outputs remain downloadable;
- the fallback can be invoked without an AWS key or internet connection.

---

## Phase 2 — Build the canonical map-data contract

### Objective

Create the stable integration boundary between ODSS and every map/presentation client.

### Data flow

```text
Lido CFP
  -> parser
  -> normalized flight JSON
  -> deterministic findings
  -> map contract
  -> dashboard / PDF / PilotDriven
```

### Required outputs

- route GeoJSON;
- marker GeoJSON;
- WGS-84 bounds;
- stable route hash;
- marker roles;
- label priorities;
- ACTM;
- calculated UTC, when a timing anchor exists;
- source-page evidence;
- warnings;
- fallback capability.

### Source code

```text
integration/v0.6/reference/odss_map_v06/
  config.py
  contract.py
  geojson.py
  labels.py
```

### Route contract rules

1. Preserve the exact CFP waypoint order.
2. Use only coordinate-bearing route entries.
3. Do not replace ACTM with UTC.
4. Split a route at the antimeridian when necessary.
5. Include every point in the underlying model even when its label is hidden.
6. Keep operational significance server-side.
7. Never include API keys in the contract or analysis JSON.

### Marker-role priority

| Role | Priority |
|---|---:|
| Departure / destination | 100 |
| BOBCAT | 95 |
| Kabul entry / exit | 90 |
| Early contact | 85 |
| EDTO entry / ETP / exit | 80 |
| Depressurisation critical | 75 |
| Maximum MSA | 70 |
| TOC / TOD | 60 |
| FIR boundary | 50 |
| Orientation waypoint | 20 |
| Normal route point | 0 |

### Exit criteria

- route hash is deterministic;
- SQ303 and SQ304 route order matches the CFP;
- no data crosses between analyses;
- contract passes Pydantic validation;
- secrets are absent from JSON.

---

## Phase 3 — Implement the renderer abstraction

### Objective

Make the primary and fallback map providers interchangeable without changing ODSS analysis logic.

### Source code

```text
integration/v0.6/reference/odss_map_v06/
  renderers.py
  aws_location.py
  snapshot.py
  schematic.py
```

### Interfaces

```python
class MapRenderer(Protocol):
    async def interactive_config(self, contract: MapContract) -> dict:
        ...

    async def render_snapshot(
        self,
        contract: MapContract,
        *,
        width: int,
        height: int,
    ) -> MapRenderResult:
        ...
```

### Renderer chain

```text
Playwright Amazon Location Hybrid
        ↓ failure
Amazon Location Static Satellite
        ↓ failure
ODSS schematic SVG
```

### Process

1. ODSS builds one `MapContract`.
2. The primary renderer consumes that contract.
3. A renderer failure is captured as a warning.
4. The chain attempts the next renderer.
5. The result contains provider, mode, label, media type and route hash.
6. The PDF and dashboard display the result label.

### Exit criteria

- provider changes do not alter route or marker data;
- failure is controlled and visible;
- every result records its route hash and render mode.

---

## Phase 4 — Add the live Amazon Location / MapLibre dashboard map

### Objective

Replace the primary schematic dashboard view with a geographically realistic interactive map.

### AWS setup

1. Choose an AWS region supported by Maps V2.
2. Create an Amazon Location API key.
3. Restrict it to the minimum `geo-maps:*` actions and Maps V2 resource.
4. Add permitted website origins/referrers.
5. Store the key in local environment configuration or Secrets Manager.
6. Use the Hybrid style descriptor:

```text
https://maps.geo.<region>.amazonaws.com/v2/styles/Hybrid/descriptor?key=<key>
```

### Browser source

```text
integration/v0.6/reference/static/odss-maplibre-v06.js
integration/v0.6/reference/static/odss-maplibre-v06.css
integration/v0.6/reference/templates/map_print_v06.html
```

### Dashboard map layers

1. Amazon Location Hybrid basemap.
2. Optional FIR-boundary overlay.
3. EDTO overlays.
4. Route halo.
5. Route line.
6. Route/critical markers.
7. Collision-aware labels.
8. attribution and `not for navigation`.

### Interaction

- fit route bounds;
- zoom controls;
- reset view;
- scale control;
- optional overlay toggles;
- no operational recalculation in JavaScript.

### PilotDriven integration

The future PilotDriven frontend fetches:

```text
GET /v1/analyses/{id}/map-contract
GET /v1/analyses/{id}/map-config
GET /v1/analyses/{id}/route.geojson
GET /v1/analyses/{id}/markers.geojson
```

### Exit criteria

- route starts/ends at the correct airports;
- map uses actual CFP coordinates;
- route/marker hash matches the analysis;
- attribution is visible;
- no material label overlap;
- the map is explicitly not for navigation.

---

## Phase 5 — Compact and standardise Page 1

### Objective

Use nearly all A4 landscape space without sacrificing readability.

### Fixed composition

| Band | Approximate height |
|---|---:|
| Header/status | 5–6% |
| Flight metric and mass/fuel strips | 9–11% |
| Departure/map/destination | 52–55% |
| Exceptions | 6–8% |
| Communications/EDTO/weather/tools | 22–25% |
| Footer/navigation | 4–5% |

### Main region

```text
Departure panel |       realistic map       | Destination panel
      16%       |             68%           |       16%
```

### Page 1 rules

- no full NOTAM paragraphs;
- maximum four visible airport categories per side;
- no duplicate MSA/VWS/EDTO/BOBCAT summaries;
- six to twelve priority labels only;
- PZFW, PLDW and PTOW visible in integer kg;
- map occupies at least half the usable page area;
- no large empty cards;
- concise Page 2/Page 3 links;
- body text normally no smaller than about 7.5–8 pt;
- alert meaning is not colour-only.

### Level 1 pages

1. realistic visual route briefing;
2. operational and airport detail;
3. route and contingency detail.

### Level 2

Starts with the same realistic visual Page 1, then retains every expanded deterministic finding and warning.

### Exit criteria

- Page 1 occupancy exceeds 90%, excluding internal padding;
- no clipping at normal print scale;
- all internal PDF links work;
- SQ303 and SQ304 visual regression images pass.

---

## Phase 6 — Implement Playwright PDF map capture

### Objective

Embed the same MapLibre Hybrid map into PDF output rather than maintaining a second map design.

### Internal endpoint

```text
GET /render/maps/{analysis_id}?route_hash=<hash>
```

### Ready protocol

The print page sets:

```javascript
window.__ODSS_MAP_READY__ = true
```

only after:

- style load;
- route source load;
- marker source load;
- label layout;
- route-bound camera fit;
- at least two map-idle events.

### Capture process

1. Report worker requests map snapshot.
2. Playwright starts headless Chromium.
3. Fixed viewport and device scale factor are applied.
4. The print endpoint is opened.
5. Worker waits for the ready flag.
6. `#odss-print-map` is captured as PNG.
7. Image is stored with route hash, provider, style and timestamp.
8. Image is embedded in Page 1 of both reports.
9. Map attribution and fallback label remain visible.

### Installation

```bash
python -m pip install -r integration/v0.6/reference/requirements-map.txt
python -m playwright install chromium
```

### Exit criteria

- the screenshot is complete, not partially tiled;
- dashboard and PDF share route hash/style;
- timeout triggers the static fallback;
- screenshot metadata is retained in the report evidence bundle.

---

## Phase 7 — Implement and test the fallback hierarchy

### Objective

Keep reporting available when the primary network or browser renderer fails.

### Primary

```text
Amazon Location Hybrid + MapLibre + Playwright
```

Label:

```text
Amazon Location Hybrid
```

### Fallback 1

```text
Amazon Location GetStaticMap + Satellite/Standard
```

Label:

```text
Static map fallback — Hybrid print rendering unavailable
```

Constraints:

- static API maximum dimensions are respected;
- route/selected markers are passed through GeoJSON overlay;
- overlay length is checked;
- Hybrid is not requested from the static API.

### Fallback 2

```text
ODSS schematic route renderer
```

Label:

```text
Schematic route display — basemap unavailable
```

### Failure rules

- never leave a blank map;
- never hide the downgrade;
- never replace the route data;
- include provider/error warnings in JSON and PDF;
- preserve map attribution where applicable.

### Exit criteria

Test all three modes:

1. primary available;
2. API key present but Playwright unavailable;
3. no map network/API key.

The same route hash must appear in every mode.

---

## Final handoff to pilotdriven.com

Once Phases 1–7 pass:

1. Freeze the ODSS service contract.
2. Expose versioned analysis and map endpoints.
3. Copy or package the reference map client into the PilotDriven repository.
4. Replace Jinja layout with PilotDriven React/Next.js components.
5. Keep all operational decisions in ODSS.
6. Reuse PilotDriven authentication, storage, navigation and tenancy.
7. Run SQ303 and SQ304 golden tests after integration.
8. Perform security, performance and operational SME review.

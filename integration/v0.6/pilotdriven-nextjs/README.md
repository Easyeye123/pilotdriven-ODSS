# PilotDriven Next.js map reference

This directory contains the reference client component for the final PilotDriven application.

## Install

```bash
npm install maplibre-gl
```

Copy or adapt:

```text
components/OdssRouteMap.tsx
lib/odss-types.ts
```

Do not copy operational rules into the frontend.

## Use

```tsx
import { OdssRouteMap } from "@/components/OdssRouteMap";

<OdssRouteMap
  analysisId={analysis.id}
  apiBaseUrl={process.env.NEXT_PUBLIC_ODSS_API_URL}
/>
```

The component requests:

```text
GET /v1/analyses/{id}/map-contract
GET /v1/analyses/{id}/map-config
```

## Suggested layout

The PilotDriven Page 1 briefing should use a dense landscape composition:

- top flight/status bar;
- metric strip;
- PZFW/PLDW/PTOW/fuel strip;
- departure card;
- large map;
- destination card;
- compact exceptions;
- communications, EDTO, weather and tools panels;
- Level 1 Page 2/Page 3 navigation.

The map should occupy approximately 68% of the main departure/map/destination row.

## Security

- Retrieve map configuration from an authenticated ODSS/PilotDriven backend.
- The Amazon Location web API key must be referrer-restricted and limited to map-read actions.
- Never place unrestricted AWS credentials in the browser.
- Do not expose local file paths or source-document URLs in the map contract.
- Keep tenant and analysis authorization on every API endpoint.

## Authority boundary

This component renders data. It does not calculate:

- NOTAM applicability;
- BOBCAT;
- ATOT/ACTM timings;
- early FIR calls;
- EDTO;
- terrain or VWS;
- depressurisation profiles;
- MEL/CDL/CDDL implications.

Those remain ODSS server responsibilities.

## Fallback

When `map-config` does not contain `style_url`, PilotDriven should display the server-provided static or schematic artifact and show its fallback label. Never leave a blank map and never silently present a schematic map as a realistic basemap.

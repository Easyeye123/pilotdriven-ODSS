# PilotDriven React integration

`OdssSurfaceMap.tsx` renders only the ODSS `SURFACE_MAP_CONTRACT_V1`.

The component:

- does not parse NOTAM text;
- does not determine time applicability;
- does not resolve taxiway intersections;
- does not evaluate aircraft code;
- does not invent geometry;
- renders base surface GeoJSON, closure/restriction lines and ODSS-provided X markers;
- suppresses inactive or unaffected overlays using the contract's `display` property;
- keeps source attribution visible.

Install `maplibre-gl` in the PilotDriven web application and pass the existing Amazon Location Hybrid style descriptor URL as `styleUrl`.

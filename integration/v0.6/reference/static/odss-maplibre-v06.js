(() => {
  "use strict";

  const bootstrap = window.ODSS_MAP_BOOTSTRAP;
  window.__ODSS_MAP_READY__ = false;
  window.__ODSS_MAP_ERROR__ = null;

  if (!bootstrap || !window.maplibregl) {
    window.__ODSS_MAP_ERROR__ = "MapLibre bootstrap unavailable";
    return;
  }

  const selectedLabels = new Set(bootstrap.priorityLabels || []);
  const map = new maplibregl.Map({
    container: "odss-map",
    style: bootstrap.styleUrl,
    attributionControl: true,
    interactive: !bootstrap.printMode,
    fadeDuration: 0,
    preserveDrawingBuffer: Boolean(bootstrap.printMode),
  });

  if (!bootstrap.printMode) {
    map.addControl(new maplibregl.NavigationControl(), "top-right");
    map.addControl(new maplibregl.ScaleControl({
      maxWidth: 110,
      unit: "nautical"
    }), "bottom-left");
  }

  map.on("load", () => {
    try {
      map.addSource("odss-route", {
        type: "geojson",
        data: bootstrap.route,
      });
      map.addSource("odss-markers", {
        type: "geojson",
        data: bootstrap.markers,
      });
      map.addSource("odss-hazards", {
        type: "geojson",
        data: bootstrap.hazards || {type: "FeatureCollection", features: []},
      });

      map.addLayer({
        id: "odss-hazard-fill",
        type: "fill",
        source: "odss-hazards",
        paint: {
          "fill-color": "#ff6b6b",
          "fill-opacity": 0.30,
        },
      });
      map.addLayer({
        id: "odss-hazard-outline",
        type: "line",
        source: "odss-hazards",
        paint: {
          "line-color": "#ffb84d",
          "line-width": 2.5,
          "line-opacity": 0.95,
        },
      });

      map.addLayer({
        id: "odss-route-halo",
        type: "line",
        source: "odss-route",
        paint: {
          "line-color": "#07111f",
          "line-width": 7,
          "line-opacity": 0.80,
        },
      });
      map.addLayer({
        id: "odss-route-line",
        type: "line",
        source: "odss-route",
        paint: {
          "line-color": "#f4faff",
          "line-width": 3.5,
          "line-opacity": 0.96,
        },
      });
      map.addLayer({
        id: "odss-route-points",
        type: "circle",
        source: "odss-markers",
        paint: {
          "circle-radius": [
            "match",
            ["get", "role"],
            "departure", 7,
            "destination", 7,
            "bobcat", 6,
            "kabul", 6,
            "terrain_critical", 5,
            "depressurisation_critical", 5,
            3.4
          ],
          "circle-color": [
            "match",
            ["get", "role"],
            "departure", "#4DB8FF",
            "destination", "#4DB8FF",
            "bobcat", "#FFB84D",
            "kabul", "#FF6B6B",
            "early_contact", "#B38CFF",
            "edto_entry", "#55D6BE",
            "edto_etp", "#55D6BE",
            "edto_exit", "#55D6BE",
            "terrain_critical", "#FF7F66",
            "depressurisation_critical", "#FF7F66",
            "#DCEEFF"
          ],
          "circle-stroke-color": "#07111f",
          "circle-stroke-width": 1.8,
        },
      });
      map.addLayer({
        id: "odss-route-labels",
        type: "symbol",
        source: "odss-markers",
        filter: [
          "in",
          ["get", "name"],
          ["literal", Array.from(selectedLabels)]
        ],
        layout: {
          "text-field": ["get", "name"],
          "text-size": bootstrap.printMode ? 12 : 13,
          "text-offset": [0.65, -0.65],
          "text-anchor": "left",
          "text-allow-overlap": false,
          "text-ignore-placement": false,
          "symbol-sort-key": ["-", 1000, ["get", "priority"]],
        },
        paint: {
          "text-color": "#E8F2FF",
          "text-halo-color": "#07111F",
          "text-halo-width": 1.8,
          "text-halo-blur": 0.4,
        },
      });

      const bounds = bootstrap.bounds;
      map.fitBounds(
        [[bounds.west, bounds.south], [bounds.east, bounds.north]],
        {
          padding: bootstrap.printMode ? 58 : 42,
          duration: 0,
          linear: true,
        }
      );
    } catch (error) {
      window.__ODSS_MAP_ERROR__ = String(error);
    }
  });

  let idleCount = 0;
  map.on("idle", () => {
    if (window.__ODSS_MAP_ERROR__) return;
    idleCount += 1;
    if (idleCount >= 2 && map.isStyleLoaded()) {
      document.documentElement.dataset.routeHash = bootstrap.routeHash;
      window.__ODSS_MAP_READY__ = true;
    }
  });

  map.on("error", (event) => {
    const message = event && event.error
      ? event.error.message
      : "MapLibre rendering error";
    window.__ODSS_MAP_ERROR__ = message;
  });
})();

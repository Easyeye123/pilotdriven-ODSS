(() => {
  "use strict";

  const ROLE_COLOURS = {
    departure: "#68DCFF",
    destination: "#68DCFF",
    bobcat: "#FFB84D",
    kabul: "#FF6B6B",
    early_contact: "#B38CFF",
    edto_entry: "#55D6BE",
    edto_etp: "#55D6BE",
    edto_exit: "#55D6BE",
    terrain_critical: "#FF6B6B",
    depressurisation_critical: "#FF7F66",
    toc: "#DCEEFF",
    tod: "#DCEEFF",
    fir: "#B38CFF",
    route: "#DCEEFF",
  };

  const ROLE_RADIUS = [
    "match", ["get", "role"],
    "departure", 7,
    "destination", 7,
    "bobcat", 6.5,
    "kabul", 6.5,
    "early_contact", 5.5,
    "edto_entry", 5.5,
    "edto_etp", 5.5,
    "edto_exit", 5.5,
    "terrain_critical", 5.8,
    "depressurisation_critical", 5.8,
    "toc", 4.5,
    "tod", 4.5,
    "fir", 4,
    3.2,
  ];

  const ROLE_COLOUR_EXPRESSION = [
    "match", ["get", "role"],
    ...Object.entries(ROLE_COLOURS).flatMap(([role, colour]) => [role, colour]),
    "#DCEEFF",
  ];

  function normalizeConfig(source) {
    const config = {
      styleUrl: source.styleUrl || source.style_url,
      route: source.route,
      markers: source.markers,
      hazards: source.hazards || {type: "FeatureCollection", features: []},
      bounds: source.bounds,
      priorityLabels: source.priorityLabels || source.priority_labels || [],
      routeHash: source.routeHash || source.route_hash,
      printMode: Boolean(source.printMode || source.print_mode),
      readinessTimeoutMs: Number(source.readinessTimeoutMs || source.readiness_timeout_ms),
      attribution: source.attribution || [],
    };
    const geometry = window.ODSS_MAP_GEOMETRY;
    config.cameraBounds = geometry
      ? geometry.presentationBounds(config.markers, config.bounds)
      : config.bounds;
    config.renderWorldCopies = geometry
      ? geometry.requiresWorldCopies(config.cameraBounds)
      : false;
    return config;
  }

  function addOperationalLayers(map, config) {
    const geometry = window.ODSS_MAP_GEOMETRY;
    const labelMarkers = geometry && geometry.priorityLabelCollection
      ? geometry.priorityLabelCollection(config.markers, config.priorityLabels)
      : config.markers;
    map.addSource("odss-route", {type: "geojson", data: config.route});
    map.addSource("odss-markers", {type: "geojson", data: config.markers});
    map.addSource("odss-labels", {type: "geojson", data: labelMarkers});
    map.addSource("odss-hazards", {type: "geojson", data: config.hazards});

    map.addLayer({
      id: "odss-hazard-fill",
      type: "fill",
      source: "odss-hazards",
      paint: {
        "fill-color": "#FF5364",
        "fill-opacity": 0.25,
      },
    });
    map.addLayer({
      id: "odss-hazard-outline",
      type: "line",
      source: "odss-hazards",
      layout: {"line-cap": "round", "line-join": "round"},
      paint: {
        "line-color": "#FFD166",
        "line-width": 2.8,
        "line-opacity": 0.98,
        "line-dasharray": [2, 1.25],
      },
    });
    map.addLayer({
      id: "odss-hazard-label",
      type: "symbol",
      source: "odss-hazards",
      layout: {
        "text-field": "VOLCANIC ASH",
        "text-size": config.printMode ? 11 : 10,
        "text-letter-spacing": 0.12,
        "text-allow-overlap": false,
      },
      paint: {
        "text-color": "#FFE6A7",
        "text-halo-color": "#42151A",
        "text-halo-width": 1.7,
      },
    });

    map.addLayer({
      id: "odss-route-shadow",
      type: "line",
      source: "odss-route",
      layout: {"line-cap": "round", "line-join": "round"},
      paint: {
        "line-color": "#020912",
        "line-width": config.printMode ? 11 : 10,
        "line-opacity": 0.82,
      },
    });
    map.addLayer({
      id: "odss-route-glow",
      type: "line",
      source: "odss-route",
      layout: {"line-cap": "round", "line-join": "round"},
      paint: {
        "line-color": "#35CFFF",
        "line-width": config.printMode ? 7 : 6.5,
        "line-opacity": 0.42,
        "line-blur": 2.2,
      },
    });
    map.addLayer({
      id: "odss-route-line",
      type: "line",
      source: "odss-route",
      layout: {"line-cap": "round", "line-join": "round"},
      paint: {
        "line-color": "#BFEFFF",
        "line-width": config.printMode ? 3.4 : 3.1,
        "line-opacity": 0.98,
      },
    });

    map.addLayer({
      id: "odss-event-glow",
      type: "circle",
      source: "odss-markers",
      filter: ["!=", ["get", "role"], "route"],
      paint: {
        "circle-radius": ["+", ROLE_RADIUS, 4],
        "circle-color": ROLE_COLOUR_EXPRESSION,
        "circle-opacity": 0.18,
        "circle-blur": 0.35,
      },
    });
    map.addLayer({
      id: "odss-route-points",
      type: "circle",
      source: "odss-markers",
      paint: {
        "circle-radius": ROLE_RADIUS,
        "circle-color": ROLE_COLOUR_EXPRESSION,
        "circle-opacity": 0.98,
        "circle-stroke-color": "#06111F",
        "circle-stroke-width": 2,
      },
    });
    map.addLayer({
      id: "odss-route-labels",
      type: "symbol",
      source: "odss-labels",
      filter: [
        "!", ["in", ["get", "role"], ["literal", ["departure", "destination"]]],
      ],
      layout: {
        "text-field": ["get", "name"],
        "text-size": config.printMode ? 15 : 11.5,
        "text-variable-anchor": ["top-right", "bottom-right", "top-left", "bottom-left"],
        "text-radial-offset": config.printMode ? 0.85 : 0.72,
        "text-letter-spacing": 0.025,
        "text-allow-overlap": false,
        "text-ignore-placement": false,
        "symbol-sort-key": ["-", 1000, ["coalesce", ["get", "priority"], 0]],
      },
      paint: {
        "text-color": ROLE_COLOUR_EXPRESSION,
        "text-halo-color": "#06111F",
        "text-halo-width": 1.9,
        "text-halo-blur": 0.45,
      },
    });
    [
      {id: "departure", anchor: "bottom-left", offset: [0.65, -0.45]},
      {id: "destination", anchor: "bottom-right", offset: [-0.65, -0.45]},
    ].forEach((terminal) => {
      map.addLayer({
        id: `odss-${terminal.id}-label`,
        type: "symbol",
        source: "odss-labels",
        filter: ["==", ["get", "role"], terminal.id],
        layout: {
          "text-field": ["get", "name"],
          "text-size": config.printMode ? 20 : 14,
          "text-anchor": terminal.anchor,
          "text-offset": terminal.offset,
          "text-letter-spacing": 0.055,
          "text-allow-overlap": true,
          "text-ignore-placement": false,
        },
        paint: {
          "text-color": "#EAFBFF",
          "text-halo-color": "#03101D",
          "text-halo-width": config.printMode ? 2.8 : 2.2,
          "text-halo-blur": 0.5,
        },
      });
    });
  }

  function fitOperationalBounds(map, config) {
    const bounds = config.cameraBounds || config.bounds;
    if (!bounds) return;
    const values = [bounds.west, bounds.south, bounds.east, bounds.north];
    if (!values.every(Number.isFinite)) return;
    map.fitBounds(
      [[bounds.west, bounds.south], [bounds.east, bounds.north]],
      {
        padding: config.printMode
          ? {top: 62, right: 58, bottom: 58, left: 58}
          : {top: 76, right: 48, bottom: 64, left: 48},
        duration: 0,
        linear: true,
        maxZoom: 8.5,
      },
    );
  }

  function createOperationalMap(container, config, callbacks) {
    const mapOptions = {
      container,
      style: config.styleUrl,
      attributionControl: true,
      interactive: !config.printMode,
      cooperativeGestures: !config.printMode,
      fadeDuration: 0,
      preserveDrawingBuffer: config.printMode,
      renderWorldCopies: config.renderWorldCopies,
      validateStyle: false,
    };
    if (config.printMode) mapOptions.projection = {type: "mercator"};
    const map = new window.maplibregl.Map(mapOptions);

    if (!config.printMode) {
      map.addControl(new window.maplibregl.NavigationControl({showCompass: false}), "top-right");
      map.addControl(new window.maplibregl.ScaleControl({maxWidth: 105, unit: "nautical"}), "bottom-left");
    }

    let layersReady = false;
    let ready = false;
    let finishing = false;
    let idleCount = 0;
    let lastError = null;
    const configuredTimeout = Number.isFinite(config.readinessTimeoutMs)
      ? config.readinessTimeoutMs
      : (config.printMode ? 30000 : 18000);
    const readinessTimeoutMs = Math.max(1000, Math.min(configuredTimeout, 175000));
    let readinessPoll = null;
    const clearReadinessTimers = () => {
      window.clearTimeout(timeout);
      if (readinessPoll !== null) window.clearInterval(readinessPoll);
    };
    const signalReady = () => {
      if (ready || finishing) return;
      finishing = true;
      Promise.resolve(document.fonts ? document.fonts.ready : undefined)
        .then(() => new Promise((resolve) => {
          requestAnimationFrame(() => requestAnimationFrame(resolve));
        }))
        .then(() => {
          if (ready) return;
          ready = true;
          clearReadinessTimers();
          callbacks.onReady(map);
        })
        .catch((error) => {
          lastError = error;
          clearReadinessTimers();
          callbacks.onError(error);
        });
    };
    const timeout = window.setTimeout(() => {
      if (ready) return;
      clearReadinessTimers();
      if (lastError) {
        callbacks.onError(lastError);
        return;
      }
      const styleLoaded = map.isStyleLoaded();
      const tilesLoaded = typeof map.areTilesLoaded === "function" && map.areTilesLoaded();
      callbacks.onError(new Error(
        `Map readiness timeout (layers=${layersReady}; style=${styleLoaded}; tiles=${tilesLoaded})`,
      ));
    }, readinessTimeoutMs);
    readinessPoll = window.setInterval(() => {
      if (
        layersReady
        && !ready
        && map.isStyleLoaded()
        && typeof map.areTilesLoaded === "function"
        && map.areTilesLoaded()
      ) {
        signalReady();
      }
    }, 250);

    map.on("load", () => {
      try {
        if (config.printMode) map.setProjection({type: "mercator"});
        addOperationalLayers(map, config);
        fitOperationalBounds(map, config);
        layersReady = true;
        if (callbacks.onLayersReady) callbacks.onLayersReady(map);
      } catch (error) {
        lastError = error;
        clearReadinessTimers();
        callbacks.onError(error);
      }
    });

    map.on("idle", () => {
      if (!layersReady || ready || !map.isStyleLoaded()) return;
      idleCount += 1;
      // One MapLibre `idle` event already means all requested tiles are loaded
      // and no camera transition is running. A second event is not guaranteed
      // without another render transition, so waiting for it can deadlock the
      // headless PDF capture until the readiness timeout.
      if (idleCount < 1) return;
      signalReady();
    });

    map.on("error", (event) => {
      lastError = event && event.error ? event.error : new Error("Map rendering error");
      if (config.printMode && !ready) {
        clearReadinessTimers();
        callbacks.onError(lastError);
      } else if (ready && callbacks.onWarning) {
        callbacks.onWarning();
      }
    });

    return map;
  }

  function appendDefinition(list, label, value) {
    if (value === null || value === undefined || value === "") return;
    const term = document.createElement("dt");
    term.textContent = label;
    const detail = document.createElement("dd");
    detail.textContent = String(value);
    list.append(term, detail);
  }

  function roleLabel(role) {
    return String(role || "route").replaceAll("_", " ");
  }

  function pointDetails(properties) {
    const card = document.createElement("div");
    const title = document.createElement("strong");
    title.textContent = properties.name || properties.source_name || "Route point";
    card.append(title);
    const list = document.createElement("dl");
    appendDefinition(list, "Role", roleLabel(properties.role));
    appendDefinition(
      list,
      "ACTM",
      properties.actm_minutes !== null
        && properties.actm_minutes !== undefined
        && Number.isFinite(Number(properties.actm_minutes))
        ? `${properties.actm_minutes} min`
        : null,
    );
    appendDefinition(list, "Airway", properties.airway_in);
    appendDefinition(list, "FIR", properties.fir_boundary);
    appendDefinition(
      list,
      "MSA",
      properties.msa_hundreds_ft !== null && properties.msa_hundreds_ft !== undefined
        ? `${properties.msa_hundreds_ft}00 ft`
        : null,
    );
    appendDefinition(list, "VWS", properties.vws);
    appendDefinition(list, "Source", properties.source_page ? `CFP page ${properties.source_page}` : null);
    card.append(list);
    return card;
  }

  function installWorkspaceInteractions(map, shell) {
    const pointCard = shell.querySelector("[data-odss-map-point-card]");
    let popup = null;

    map.on("mouseenter", "odss-route-points", (event) => {
      map.getCanvas().style.cursor = "pointer";
      const feature = event.features && event.features[0];
      if (!feature || !pointCard) return;
      pointCard.replaceChildren(...pointDetails(feature.properties || {}).childNodes);
      pointCard.hidden = false;
    });
    map.on("mouseleave", "odss-route-points", () => {
      map.getCanvas().style.cursor = "";
      if (pointCard) pointCard.hidden = true;
    });
    map.on("click", "odss-route-points", (event) => {
      const feature = event.features && event.features[0];
      if (!feature) return;
      if (popup) popup.remove();
      popup = new window.maplibregl.Popup({closeButton: true, closeOnClick: true, offset: 10})
        .setLngLat(feature.geometry.coordinates)
        .setDOMContent(pointDetails(feature.properties || {}))
        .addTo(map);
    });
  }

  async function showWorkspaceFallback(shell, reason) {
    if (shell.dataset.fallbackLoading === "true") return;
    shell.dataset.fallbackLoading = "true";
    shell.classList.remove("is-loading", "is-primary");
    shell.classList.add("is-fallback");
    const mode = shell.querySelector("[data-odss-map-mode]");
    const message = shell.querySelector("[data-odss-map-message]");
    const fallback = shell.querySelector("[data-odss-map-fallback]");
    const reset = shell.querySelector("[data-odss-map-reset]");
    if (mode) mode.textContent = "Schematic fallback";
    if (message) message.textContent = reason || "Realistic basemap unavailable; showing the offline CFP route.";
    if (reset) reset.hidden = true;

    const fallbackUrl = shell.dataset.fallbackUrl;
    if (!fallbackUrl || !fallback) return;
    try {
      const response = await fetch(fallbackUrl, {
        credentials: "same-origin",
        cache: "no-store",
        headers: {Accept: "image/avif,image/webp,image/svg+xml,image/*,*/*;q=0.8"},
      });
      if (!response.ok) return;
      const expectedHash = shell.dataset.routeHash;
      const renderedHash = response.headers.get("x-odss-route-hash");
      if (expectedHash && renderedHash !== expectedHash) return;
      const renderMode = response.headers.get("x-odss-map-mode") || "schematic-fallback";
      if (mode) {
        mode.textContent = renderMode === "static-fallback" ? "Static fallback" : "Schematic fallback";
      }
      if (renderMode !== "static-fallback") return;

      const blob = await response.blob();
      const objectUrl = URL.createObjectURL(blob);
      const image = new Image();
      image.alt = "Static satellite route map fallback";
      image.decoding = "async";
      image.onload = () => {
        fallback.replaceChildren(image);
        URL.revokeObjectURL(objectUrl);
      };
      image.onerror = () => URL.revokeObjectURL(objectUrl);
      image.src = objectUrl;
    } catch (_) {
      // The inline offline route remains visible and labelled.
    }
  }

  async function initWorkspaceMap(shell) {
    const container = shell.querySelector("[data-odss-map-canvas]");
    const mode = shell.querySelector("[data-odss-map-mode]");
    const message = shell.querySelector("[data-odss-map-message]");
    const reset = shell.querySelector("[data-odss-map-reset]");
    if (!container || !window.maplibregl) {
      await showWorkspaceFallback(shell, "Interactive map support unavailable; showing the offline CFP route.");
      return;
    }

    shell.classList.add("is-loading");
    if (mode) mode.textContent = "Loading Hybrid";
    try {
      const response = await fetch(shell.dataset.configUrl, {
        credentials: "same-origin",
        cache: "no-store",
        headers: {Accept: "application/json"},
      });
      if (!response.ok) throw new Error("Map configuration unavailable");
      const payload = await response.json();
      const config = normalizeConfig(payload);
      const expectedHash = shell.dataset.routeHash;
      if (expectedHash && config.routeHash !== expectedHash) {
        throw new Error("Canonical route version changed");
      }
      if (!config.styleUrl || !config.route || !config.markers || !config.bounds) {
        await showWorkspaceFallback(shell, "Approved basemap configuration is unavailable; showing the offline CFP route.");
        return;
      }

      let failed = false;
      const fail = async () => {
        if (failed) return;
        failed = true;
        if (shell._odssMap) {
          try { shell._odssMap.remove(); } catch (_) { /* no-op */ }
          shell._odssMap = null;
        }
        await showWorkspaceFallback(shell, "Realistic basemap did not load; showing the offline CFP route.");
      };
      const map = createOperationalMap(container, config, {
        onLayersReady: (loadedMap) => installWorkspaceInteractions(loadedMap, shell),
        onReady: (loadedMap) => {
          if (failed) return;
          shell.classList.remove("is-loading", "is-fallback");
          shell.classList.add("is-primary");
          shell.dataset.mapMode = "primary";
          if (mode) mode.textContent = "Amazon Hybrid";
          if (message) message.textContent = "";
          if (reset) {
            reset.hidden = false;
            reset.onclick = () => fitOperationalBounds(loadedMap, config);
          }
        },
        onError: fail,
        onWarning: () => {
          shell.classList.add("has-map-warning");
          if (message) message.textContent = "Some basemap tiles are unavailable; route data remains visible.";
        },
      });
      shell._odssMap = map;
    } catch (_) {
      await showWorkspaceFallback(shell, "Map configuration could not be loaded; showing the offline CFP route.");
    }
  }

  function initPrintMap(bootstrap) {
    window.__ODSS_MAP_READY__ = false;
    window.__ODSS_MAP_ERROR__ = null;
    const container = document.getElementById("odss-map");
    if (!container || !window.maplibregl || !bootstrap) {
      window.__ODSS_MAP_ERROR__ = "MapLibre bootstrap unavailable";
      return;
    }
    const config = normalizeConfig(bootstrap);
    const map = createOperationalMap(container, config, {
      onLayersReady: () => {
        document.documentElement.dataset.routeHash = config.routeHash;
        window.__ODSS_MAP_LAYERS_READY_AT__ = Date.now();
      },
      onReady: () => {
        document.documentElement.dataset.routeHash = config.routeHash;
        window.__ODSS_MAP_READY__ = true;
      },
      onError: (error) => {
        window.__ODSS_MAP_ERROR__ = error && error.message
          ? String(error.message)
          : "MapLibre rendering error";
      },
    });
    window.__ODSS_MAP_INSTANCE__ = map;
  }

  const printBootstrap = window.ODSS_MAP_BOOTSTRAP;
  if (printBootstrap) initPrintMap(printBootstrap);
  document.querySelectorAll("[data-odss-map-workspace]").forEach((shell) => {
    initWorkspaceMap(shell);
  });
})();

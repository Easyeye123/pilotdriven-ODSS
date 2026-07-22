(function (root, factory) {
  "use strict";
  const geometry = factory();
  if (typeof module === "object" && module.exports) module.exports = geometry;
  root.ODSS_MAP_GEOMETRY = geometry;
}(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  function orderedCoordinates(markers) {
    const features = markers && Array.isArray(markers.features) ? markers.features : [];
    return features
      .map((feature) => feature && feature.geometry && feature.geometry.coordinates)
      .filter((coordinates) => (
        Array.isArray(coordinates)
        && coordinates.length >= 2
        && Number.isFinite(Number(coordinates[0]))
        && Number.isFinite(Number(coordinates[1]))
      ))
      .map((coordinates) => [Number(coordinates[0]), Number(coordinates[1])]);
  }

  function unwrapLongitude(longitude, previous) {
    let value = longitude;
    while (value - previous > 180) value -= 360;
    while (value - previous < -180) value += 360;
    return value;
  }

  function presentationBounds(markers, fallback) {
    const coordinates = orderedCoordinates(markers);
    if (!coordinates.length) return fallback || null;
    const longitudes = [];
    const latitudes = [];
    let previous = null;
    coordinates.forEach(([rawLongitude, latitude]) => {
      const longitude = previous === null
        ? rawLongitude
        : unwrapLongitude(rawLongitude, previous);
      longitudes.push(longitude);
      latitudes.push(latitude);
      previous = longitude;
    });
    let west = Math.min(...longitudes);
    let east = Math.max(...longitudes);
    let south = Math.min(...latitudes);
    let north = Math.max(...latitudes);
    if (east - west < 0.1) {
      west -= 0.5;
      east += 0.5;
    }
    if (north - south < 0.1) {
      south -= 0.5;
      north += 0.5;
    }
    return {west, south, east, north};
  }

  function requiresWorldCopies(bounds) {
    return Boolean(bounds && (bounds.west < -180 || bounds.east > 180));
  }

  function priorityLabelCollection(markers, priorityLabels) {
    const features = markers && Array.isArray(markers.features) ? markers.features : [];
    const selectedNames = new Set(
      (Array.isArray(priorityLabels) ? priorityLabels : [])
        .map((name) => String(name || "").trim().toLocaleUpperCase())
        .filter(Boolean),
    );
    const labelsByName = new Map();
    features.forEach((feature) => {
      const properties = feature && feature.properties ? feature.properties : {};
      const name = String(properties.name || "").trim();
      const normalizedName = name.toLocaleUpperCase();
      if (!name || !selectedNames.has(normalizedName)) return;
      const role = String(properties.role || "route");
      const terminalBonus = role === "departure" || role === "destination" ? 1000 : 0;
      const score = terminalBonus + Number(properties.priority || 0);
      const current = labelsByName.get(normalizedName);
      if (!current || score > current.score) labelsByName.set(normalizedName, {feature, score});
    });
    return {
      type: "FeatureCollection",
      features: Array.from(labelsByName.values(), (item) => item.feature),
    };
  }

  return {presentationBounds, priorityLabelCollection, requiresWorldCopies};
}));

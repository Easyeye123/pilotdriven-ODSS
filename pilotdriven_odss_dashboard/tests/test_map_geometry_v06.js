"use strict";

const assert = require("node:assert/strict");
const test = require("node:test");
const geometry = require("../app/static/odss-map-geometry-v06.js");

test("Pacific camera bounds unwrap the ordered route across the date line", () => {
  const markers = {
    type: "FeatureCollection",
    features: [170, -175, -150].map((longitude, index) => ({
      type: "Feature",
      id: `wp-${index}`,
      geometry: {type: "Point", coordinates: [longitude, 10 + index]},
      properties: {name: `P${index}`},
    })),
  };

  const bounds = geometry.presentationBounds(markers, null);

  assert.equal(bounds.west, 170);
  assert.equal(bounds.east, 210);
  assert.equal(bounds.east - bounds.west, 40);
  assert.equal(geometry.requiresWorldCopies(bounds), true);
  assert.deepEqual(
    markers.features.map((feature) => feature.geometry.coordinates[0]),
    [170, -175, -150],
  );
});

test("ordinary routes retain an ordinary non-wrapped camera", () => {
  const markers = {
    type: "FeatureCollection",
    features: [103, 120, 145].map((longitude, index) => ({
      geometry: {type: "Point", coordinates: [longitude, index]},
    })),
  };

  const bounds = geometry.presentationBounds(markers, null);

  assert.equal(bounds.east - bounds.west, 42);
  assert.equal(geometry.requiresWorldCopies(bounds), false);
});

test("priority labels are unique and keep the terminal marker", () => {
  const markers = {
    type: "FeatureCollection",
    features: [
      {geometry: {type: "Point", coordinates: [103, 1]}, properties: {name: "WSSS", role: "departure", priority: 100}},
      {geometry: {type: "Point", coordinates: [139, 35]}, properties: {name: "RJJJ", role: "fir", priority: 50}},
      {geometry: {type: "Point", coordinates: [140, 36]}, properties: {name: "RJJJ", role: "fir", priority: 50}},
      {geometry: {type: "Point", coordinates: [-73, 40]}, properties: {name: "KJFK", role: "destination", priority: 100}},
    ],
  };

  const labels = geometry.priorityLabelCollection(markers, ["WSSS", "RJJJ", "RJJJ", "KJFK"]);

  assert.deepEqual(labels.features.map((feature) => feature.properties.name), ["WSSS", "RJJJ", "KJFK"]);
  assert.equal(labels.features[0].properties.role, "departure");
  assert.equal(labels.features[2].properties.role, "destination");
});

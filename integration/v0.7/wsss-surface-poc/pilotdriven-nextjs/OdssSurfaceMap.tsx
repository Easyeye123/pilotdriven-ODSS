'use client';

import 'maplibre-gl/dist/maplibre-gl.css';
import maplibregl, { GeoJSONSource, Map as MapLibreMap, Popup } from 'maplibre-gl';
import { useEffect, useRef } from 'react';

import type { OdssSurfaceMapContract } from './surface-types';

type Props = {
  contract: OdssSurfaceMapContract;
  styleUrl: string;
  className?: string;
  onSelectFinding?: (notamId: string | null, surfaceRef: string | null) => void;
};

function buildClosureX(size = 72): ImageData {
  const canvas = document.createElement('canvas');
  canvas.width = size;
  canvas.height = size;
  const context = canvas.getContext('2d');
  if (!context) throw new Error('Canvas 2D context is unavailable');
  context.clearRect(0, 0, size, size);
  context.lineCap = 'round';
  context.strokeStyle = '#ff3f4b';
  context.lineWidth = 14;
  context.beginPath();
  context.moveTo(14, 14);
  context.lineTo(size - 14, size - 14);
  context.moveTo(size - 14, 14);
  context.lineTo(14, size - 14);
  context.stroke();
  context.strokeStyle = '#ffffff';
  context.lineWidth = 3;
  context.stroke();
  return context.getImageData(0, 0, size, size);
}

function addLayers(map: MapLibreMap, contract: OdssSurfaceMapContract): void {
  if (!map.hasImage('odss-closure-x')) {
    map.addImage('odss-closure-x', buildClosureX(), { pixelRatio: 2 });
  }
  map.addSource('odss-airport-surface', {
    type: 'geojson',
    data: contract.surface_geojson ?? { type: 'FeatureCollection', features: [] },
  });
  map.addSource('odss-surface-overlays', {
    type: 'geojson',
    data: contract.notam_overlays_geojson,
  });
  map.addLayer({
    id: 'odss-runways',
    type: 'line',
    source: 'odss-airport-surface',
    filter: ['==', ['get', 'aeroway'], 'runway'],
    paint: { 'line-color': '#26313b', 'line-width': 16, 'line-opacity': 0.9 },
  });
  map.addLayer({
    id: 'odss-taxiways',
    type: 'line',
    source: 'odss-airport-surface',
    filter: ['==', ['get', 'aeroway'], 'taxiway'],
    paint: { 'line-color': '#f4c347', 'line-width': 5, 'line-opacity': 0.85 },
  });
  map.addLayer({
    id: 'odss-taxilanes',
    type: 'line',
    source: 'odss-airport-surface',
    filter: ['==', ['get', 'aeroway'], 'taxilane'],
    paint: { 'line-color': '#7fc8ff', 'line-width': 3, 'line-opacity': 0.75 },
  });
  map.addLayer({
    id: 'odss-surface-labels',
    type: 'symbol',
    source: 'odss-airport-surface',
    filter: ['all', ['has', 'ref'], ['in', ['get', 'aeroway'], ['literal', ['taxiway', 'taxilane', 'runway']]]],
    layout: {
      'symbol-placement': 'line',
      'text-field': ['get', 'ref'],
      'text-size': 12,
      'text-allow-overlap': false,
    },
    paint: { 'text-color': '#0a1520', 'text-halo-color': '#ffffff', 'text-halo-width': 2 },
  });
  map.addLayer({
    id: 'odss-surface-overlay-lines',
    type: 'line',
    source: 'odss-surface-overlays',
    filter: ['==', ['get', 'symbol'], 'surface-overlay-line'],
    paint: {
      'line-color': ['case', ['==', ['get', 'operational_state'], 'closed'], '#ff3f4b', '#f2a93b'],
      'line-width': 10,
      'line-opacity': ['case', ['boolean', ['get', 'display'], true], 0.96, 0.18],
    },
  });
  map.addLayer({
    id: 'odss-included-junctions',
    type: 'circle',
    source: 'odss-surface-overlays',
    filter: ['==', ['get', 'symbol'], 'included-junction'],
    paint: {
      'circle-radius': 8,
      'circle-color': '#ff3f4b',
      'circle-stroke-width': 3,
      'circle-stroke-color': '#ffffff',
    },
  });
  map.addLayer({
    id: 'odss-closure-x',
    type: 'symbol',
    source: 'odss-surface-overlays',
    filter: ['==', ['get', 'symbol'], 'closure-x'],
    layout: { 'icon-image': 'odss-closure-x', 'icon-size': 0.65, 'icon-allow-overlap': true },
    paint: { 'icon-opacity': ['case', ['boolean', ['get', 'display'], true], 1, 0.2] },
  });
}

export function OdssSurfaceMap({ contract, styleUrl, className, onSelectFinding }: Props) {
  const host = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<MapLibreMap | null>(null);

  useEffect(() => {
    if (!host.current) return;
    const map = new maplibregl.Map({
      container: host.current,
      style: styleUrl,
      attributionControl: true,
      center: [
        (contract.geometry_source.bbox.west + contract.geometry_source.bbox.east) / 2,
        (contract.geometry_source.bbox.south + contract.geometry_source.bbox.north) / 2,
      ],
      zoom: 13,
    });
    mapRef.current = map;
    map.addControl(new maplibregl.NavigationControl(), 'top-right');
    map.on('load', () => {
      addLayers(map, contract);
      const { west, south, east, north } = contract.geometry_source.bbox;
      map.fitBounds([[west, south], [east, north]], { padding: 40, duration: 0 });
      ['odss-surface-overlay-lines', 'odss-included-junctions', 'odss-closure-x'].forEach((layerId) => {
        map.on('click', layerId, (event) => {
          const feature = event.features?.[0];
          if (!feature) return;
          const properties = feature.properties as Record<string, unknown>;
          const notamId = typeof properties.notam_id === 'string' ? properties.notam_id : null;
          const surfaceRef = typeof properties.surface_ref === 'string' ? properties.surface_ref : null;
          onSelectFinding?.(notamId, surfaceRef);
          new Popup()
            .setLngLat(event.lngLat)
            .setHTML(
              `<strong>${notamId ?? 'NOTAM'} · ${surfaceRef ?? ''}</strong><br>` +
                `${String(properties.operational_state ?? '')}<br>` +
                `Confidence: ${String(properties.match_confidence ?? '')}<br>` +
                `${String(properties.match_method ?? '')}`,
            )
            .addTo(map);
        });
      });
    });
    return () => {
      mapRef.current = null;
      map.remove();
    };
  }, [contract, styleUrl, onSelectFinding]);

  return (
    <div className={className} style={{ position: 'relative', minHeight: 520 }}>
      <div ref={host} style={{ position: 'absolute', inset: 0 }} />
      <div
        style={{
          position: 'absolute',
          left: 12,
          bottom: 12,
          zIndex: 1,
          padding: '7px 10px',
          borderRadius: 8,
          background: 'rgba(7,17,27,.88)',
          color: '#eef6fb',
          fontSize: 12,
        }}
      >
        {contract.geometry_source.attribution} · briefing orientation — not for navigation
      </div>
    </div>
  );
}

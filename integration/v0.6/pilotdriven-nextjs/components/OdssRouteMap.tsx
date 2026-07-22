"use client";

import "maplibre-gl/dist/maplibre-gl.css";

import maplibregl, { LngLatBoundsLike, Map } from "maplibre-gl";
import { useEffect, useRef, useState } from "react";

import type {
  OdssMapConfig,
  OdssMapContract,
} from "../lib/odss-types";

type Props = {
  analysisId: string;
  apiBaseUrl?: string;
  className?: string;
};

export function OdssRouteMap({
  analysisId,
  apiBaseUrl = "",
  className = "",
}: Props) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<Map | null>(null);
  const [warning, setWarning] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function mount() {
      if (!containerRef.current) return;

      const [contractResponse, configResponse] = await Promise.all([
        fetch(`${apiBaseUrl}/v1/analyses/${analysisId}/map-contract`, {
          credentials: "include",
          cache: "no-store",
        }),
        fetch(`${apiBaseUrl}/v1/analyses/${analysisId}/map-config`, {
          credentials: "include",
          cache: "no-store",
        }),
      ]);

      if (!contractResponse.ok || !configResponse.ok) {
        throw new Error("ODSS map contract is unavailable");
      }

      const contract =
        (await contractResponse.json()) as OdssMapContract;
      const config = (await configResponse.json()) as OdssMapConfig;

      if (!config.style_url) {
        setWarning(
          config.warnings?.join(" ") ??
            "Realistic map unavailable; use the ODSS fallback."
        );
        return;
      }
      if (cancelled || !containerRef.current) return;

      const map = new maplibregl.Map({
        container: containerRef.current,
        style: config.style_url,
        attributionControl: true,
        fadeDuration: 0,
      });
      mapRef.current = map;

      map.addControl(new maplibregl.NavigationControl(), "top-right");
      map.addControl(
        new maplibregl.ScaleControl({
          maxWidth: 120,
          unit: "nautical",
        }),
        "bottom-left"
      );

      map.on("load", () => {
        map.addSource("odss-route", {
          type: "geojson",
          data: contract.route_geojson as never,
        });
        map.addSource("odss-markers", {
          type: "geojson",
          data: contract.markers_geojson as never,
        });
        map.addSource("odss-hazards", {
          type: "geojson",
          data: contract.hazards_geojson as never,
        });

        map.addLayer({
          id: "odss-hazard-fill",
          type: "fill",
          source: "odss-hazards",
          paint: {
            "fill-color": "#ff6b6b",
            "fill-opacity": 0.3,
          },
        });
        map.addLayer({
          id: "odss-hazard-outline",
          type: "line",
          source: "odss-hazards",
          paint: {
            "line-color": "#ffb84d",
            "line-width": 2.5,
          },
        });

        map.addLayer({
          id: "odss-route-halo",
          type: "line",
          source: "odss-route",
          paint: {
            "line-color": "#07111f",
            "line-width": 7,
            "line-opacity": 0.8,
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
              "departure",
              7,
              "destination",
              7,
              "bobcat",
              6,
              "kabul",
              6,
              "terrain_critical",
              5,
              "depressurisation_critical",
              5,
              3.5,
            ],
            "circle-color": [
              "match",
              ["get", "role"],
              "departure",
              "#4DB8FF",
              "destination",
              "#4DB8FF",
              "bobcat",
              "#FFB84D",
              "kabul",
              "#FF6B6B",
              "early_contact",
              "#B38CFF",
              "edto_entry",
              "#55D6BE",
              "edto_etp",
              "#55D6BE",
              "edto_exit",
              "#55D6BE",
              "terrain_critical",
              "#FF7F66",
              "depressurisation_critical",
              "#FF7F66",
              "#DCEEFF",
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
            ["literal", contract.priority_labels],
          ],
          layout: {
            "text-field": ["get", "name"],
            "text-size": 13,
            "text-offset": [0.65, -0.65],
            "text-anchor": "left",
            "text-allow-overlap": false,
            "symbol-sort-key": ["-", 1000, ["get", "priority"]],
          },
          paint: {
            "text-color": "#e8f2ff",
            "text-halo-color": "#07111f",
            "text-halo-width": 1.8,
          },
        });

        const bounds: LngLatBoundsLike = [
          [contract.bounds.west, contract.bounds.south],
          [contract.bounds.east, contract.bounds.north],
        ];
        map.fitBounds(bounds, {
          padding: 42,
          duration: 0,
        });
      });
    }

    mount().catch((error: unknown) => {
      if (!cancelled) {
        setWarning(
          error instanceof Error
            ? error.message
            : "Unable to load ODSS route map"
        );
      }
    });

    return () => {
      cancelled = true;
      mapRef.current?.remove();
      mapRef.current = null;
    };
  }, [analysisId, apiBaseUrl]);

  return (
    <section className={`odss-route-map ${className}`}>
      <div ref={containerRef} className="h-full min-h-[420px] w-full" />
      <div className="pointer-events-none absolute bottom-2 left-2 rounded bg-slate-950/80 px-2 py-1 text-xs text-slate-200">
        Briefing orientation — not for navigation
      </div>
      {warning ? (
        <div className="absolute inset-x-3 top-3 rounded border border-amber-400/60 bg-slate-950/90 p-3 text-sm text-amber-100">
          {warning}
        </div>
      ) : null}
    </section>
  );
}

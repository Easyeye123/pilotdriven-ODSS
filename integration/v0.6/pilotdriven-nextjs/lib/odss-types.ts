export type GeoJsonFeatureCollection = {
  type: "FeatureCollection";
  features: Array<{
    type: "Feature";
    id?: string;
    geometry: {
      type: string;
      coordinates: unknown;
    };
    properties: Record<string, unknown>;
  }>;
};

export type OdssMapBounds = {
  west: number;
  south: number;
  east: number;
  north: number;
};

export type OdssMapContract = {
  schema_version: "1.0" | "1.1";
  provider: string;
  style: string;
  route_hash: string;
  route_geojson: GeoJsonFeatureCollection;
  markers_geojson: GeoJsonFeatureCollection;
  hazards_geojson: GeoJsonFeatureCollection;
  bounds: OdssMapBounds;
  priority_labels: string[];
  attribution: string[];
  warnings: string[];
  fallback: {
    static_available: boolean;
    schematic_available: boolean;
  };
  metadata: Record<string, unknown>;
};

export type OdssMapConfig = {
  provider: string;
  style_url?: string;
  route_hash: string;
  warnings?: string[];
  fallback?: {
    static_available: boolean;
    schematic_available: boolean;
  };
};

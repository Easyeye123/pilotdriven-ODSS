export type GeoJsonFeatureCollection = {
  type: 'FeatureCollection';
  features: Array<{
    type: 'Feature';
    id?: string | number;
    geometry: Record<string, unknown>;
    properties: Record<string, unknown> | null;
  }>;
};

export type SurfaceFinding = {
  notam_id: string | null;
  airport: string;
  applicability: 'active' | 'inactive' | 'schedule_review' | 'unknown';
  affects_selected_aircraft: boolean | null;
  confidence: 'high' | 'medium' | 'low' | 'unmapped';
  match_method: string;
  reason: string;
  mapped: boolean;
  clause: {
    raw: string;
    target_ref: string;
    target_kind: 'taxiway' | 'taxilane' | 'runway';
    operation: 'closed' | 'restricted' | 'information';
    method: string;
  };
};

export type OdssSurfaceMapContract = {
  schema_version: '1.0';
  airport: string;
  briefing_time_utc: string | null;
  geometry_source: {
    provider: string;
    dataset_timestamp: string | null;
    snapshot_generated_at_utc: string;
    attribution: string;
    licence: string;
    airport_review_state: string;
    bbox: { west: number; south: number; east: number; north: number };
  };
  surface_geojson: GeoJsonFeatureCollection | null;
  notam_overlays_geojson: GeoJsonFeatureCollection;
  findings: SurfaceFinding[];
  unmapped_items: SurfaceFinding[];
  warnings: string[];
  not_for_navigation: true;
};

from __future__ import annotations

import json
import math
from collections import defaultdict
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import networkx as nx
from pyproj import Transformer
from shapely.geometry import LineString, MultiLineString, Point
from shapely.ops import linemerge, transform, unary_union

from .models import Coordinate, SurfacePoint, SurfaceSnapshot, SurfaceWay

_ALLOWED_WAYS = {"taxiway", "taxilane", "runway", "apron"}
_ALLOWED_POINTS = {"holding_position", "parking_position"}
_TO_METRES = Transformer.from_crs("EPSG:4326", "EPSG:32648", always_xy=True).transform
_TO_LONLAT = Transformer.from_crs("EPSG:32648", "EPSG:4326", always_xy=True).transform


def normalize_ref(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = "".join(str(value).upper().strip().split())
    normalized = normalized.replace("–", "-").replace("—", "-")
    return normalized or None


def _tags(element: dict[str, Any]) -> dict[str, str]:
    return {str(key): str(value) for key, value in dict(element.get("tags") or {}).items()}


def normalise_overpass_payload(
    payload: dict[str, Any],
    *,
    airport: str = "WSSS",
    bbox: tuple[float, float, float, float] = (1.315, 103.965, 1.385, 104.020),
) -> dict[str, Any]:
    """Convert an Overpass `out body geom` payload to a stable bounded snapshot."""
    ways: list[dict[str, Any]] = []
    points: list[dict[str, Any]] = []
    for element in payload.get("elements", []):
        tags = _tags(element)
        aeroway = tags.get("aeroway")
        if element.get("type") == "way" and aeroway in _ALLOWED_WAYS:
            geometry = element.get("geometry") or []
            node_ids = element.get("nodes") or []
            if len(geometry) < 2:
                continue
            if len(node_ids) != len(geometry):
                node_ids = [f"way-{element.get('id')}-{index}" for index in range(len(geometry))]
            ways.append(
                {
                    "osm_id": int(element["id"]),
                    "aeroway": aeroway,
                    "ref": normalize_ref(tags.get("ref") or tags.get("name")),
                    "node_ids": node_ids,
                    "coordinates": [[float(node["lon"]), float(node["lat"])] for node in geometry],
                    "tags": tags,
                }
            )
        elif element.get("type") == "node" and aeroway in _ALLOWED_POINTS:
            points.append(
                {
                    "osm_id": int(element["id"]),
                    "aeroway": aeroway,
                    "ref": normalize_ref(tags.get("ref") or tags.get("name")),
                    "coordinate": [float(element["lon"]), float(element["lat"])],
                    "tags": tags,
                }
            )
    source_timestamp = (payload.get("osm3s") or {}).get("timestamp_osm_base")
    return {
        "schema_version": "1.0",
        "airport": airport,
        "source": "openstreetmap-overpass",
        "source_timestamp": source_timestamp,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "bbox": list(bbox),
        "attribution": "© OpenStreetMap contributors",
        "licence": "ODbL-1.0",
        "ways": sorted(ways, key=lambda item: (item["aeroway"], item.get("ref") or "", item["osm_id"])),
        "points": sorted(points, key=lambda item: (item["aeroway"], item.get("ref") or "", item["osm_id"])),
    }


def load_snapshot(path: str | Path) -> SurfaceSnapshot:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if "elements" in raw:
        raw = normalise_overpass_payload(raw)
    ways = tuple(
        SurfaceWay(
            osm_id=int(item["osm_id"]),
            aeroway=str(item["aeroway"]),
            ref=normalize_ref(item.get("ref")),
            node_ids=tuple(item["node_ids"]),
            coordinates=tuple((float(coord[0]), float(coord[1])) for coord in item["coordinates"]),
            tags={str(k): str(v) for k, v in dict(item.get("tags") or {}).items()},
        )
        for item in raw.get("ways", [])
    )
    points = tuple(
        SurfacePoint(
            osm_id=int(item["osm_id"]),
            aeroway=str(item["aeroway"]),
            ref=normalize_ref(item.get("ref")),
            coordinate=(float(item["coordinate"][0]), float(item["coordinate"][1])),
            tags={str(k): str(v) for k, v in dict(item.get("tags") or {}).items()},
        )
        for item in raw.get("points", [])
    )
    bbox = tuple(float(value) for value in raw.get("bbox", (1.315, 103.965, 1.385, 104.020)))
    if len(bbox) != 4:
        raise ValueError("Surface snapshot bbox must contain four numbers")
    return SurfaceSnapshot(
        airport=str(raw.get("airport") or "WSSS").upper(),
        source=str(raw.get("source") or "openstreetmap-overpass"),
        source_timestamp=raw.get("source_timestamp"),
        generated_at_utc=str(raw.get("generated_at_utc") or datetime.now(timezone.utc).isoformat()),
        bbox=(bbox[0], bbox[1], bbox[2], bbox[3]),
        ways=ways,
        points=points,
        attribution=str(raw.get("attribution") or "© OpenStreetMap contributors"),
        licence=str(raw.get("licence") or "ODbL-1.0"),
    )


def write_snapshot(snapshot: SurfaceSnapshot, path: str | Path) -> None:
    payload = asdict(snapshot)
    payload["schema_version"] = "1.0"
    Path(path).write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _segment_length_m(a: Coordinate, b: Coordinate) -> float:
    ax, ay = _TO_METRES(*a)
    bx, by = _TO_METRES(*b)
    return math.hypot(bx - ax, by - ay)


class SurfaceGraph:
    """Connected airport-surface graph built from a versioned OSM snapshot."""

    def __init__(self, snapshot: SurfaceSnapshot):
        self.snapshot = snapshot
        self.graph = nx.MultiGraph()
        self.ways_by_ref: dict[str, list[SurfaceWay]] = defaultdict(list)
        self.points_by_ref: dict[str, list[SurfacePoint]] = defaultdict(list)
        self._way_by_id: dict[int, SurfaceWay] = {way.osm_id: way for way in snapshot.ways}
        for way in snapshot.ways:
            if way.ref:
                self.ways_by_ref[way.ref].append(way)
            for index, (node_id, coordinate) in enumerate(zip(way.node_ids, way.coordinates)):
                self.graph.add_node(node_id, lon=coordinate[0], lat=coordinate[1])
                if index == 0:
                    continue
                previous_id = way.node_ids[index - 1]
                previous_coordinate = way.coordinates[index - 1]
                self.graph.add_edge(
                    previous_id,
                    node_id,
                    key=f"{way.osm_id}:{index - 1}",
                    way_id=way.osm_id,
                    aeroway=way.aeroway,
                    ref=way.ref,
                    length_m=_segment_length_m(previous_coordinate, coordinate),
                )
        for point in snapshot.points:
            if point.ref:
                self.points_by_ref[point.ref].append(point)

    @property
    def available_refs(self) -> list[str]:
        return sorted(self.ways_by_ref)

    @property
    def coverage(self) -> dict[str, Any]:
        counts = defaultdict(int)
        referenced = defaultdict(set)
        for way in self.snapshot.ways:
            counts[way.aeroway] += 1
            if way.ref:
                referenced[way.aeroway].add(way.ref)
        point_counts = defaultdict(int)
        for point in self.snapshot.points:
            point_counts[point.aeroway] += 1
        return {
            "way_count": len(self.snapshot.ways),
            "point_count": len(self.snapshot.points),
            "ways_by_aeroway": dict(sorted(counts.items())),
            "points_by_aeroway": dict(sorted(point_counts.items())),
            "refs_by_aeroway": {key: sorted(values) for key, values in sorted(referenced.items())},
        }

    def coordinate(self, node_id: int | str) -> Coordinate:
        node = self.graph.nodes[node_id]
        return float(node["lon"]), float(node["lat"])

    def ways_for_ref(self, ref: str) -> list[SurfaceWay]:
        return list(self.ways_by_ref.get(normalize_ref(ref) or "", []))

    def edges_for_ref(self, ref: str) -> list[tuple[int | str, int | str, str, dict[str, Any]]]:
        target = normalize_ref(ref)
        result = []
        for u, v, key, data in self.graph.edges(keys=True, data=True):
            if data.get("ref") == target:
                result.append((u, v, key, data))
        return result

    def ref_subgraph(self, ref: str) -> nx.Graph:
        graph = nx.Graph()
        for u, v, _key, data in self.edges_for_ref(ref):
            graph.add_node(u, **self.graph.nodes[u])
            graph.add_node(v, **self.graph.nodes[v])
            current = graph.get_edge_data(u, v)
            if current is None or float(data["length_m"]) < float(current["length_m"]):
                graph.add_edge(u, v, **data)
        return graph

    def intersection_nodes(self, target_ref: str, other_ref: str) -> list[int | str]:
        target = normalize_ref(target_ref)
        other = normalize_ref(other_ref)
        found = []
        for node_id in self.graph.nodes:
            refs = {
                data.get("ref")
                for *_rest, data in self.graph.edges(node_id, keys=False, data=True)
                if data.get("ref")
            }
            if target in refs and other in refs:
                found.append(node_id)
        return found

    def whole_ref_geometry(self, ref: str):
        lines = [LineString(way.coordinates) for way in self.ways_for_ref(ref) if len(way.coordinates) >= 2]
        if not lines:
            return None
        if len(lines) == 1:
            return lines[0]
        unioned = unary_union(lines)
        if isinstance(unioned, LineString):
            return unioned
        return linemerge(unioned)

    def source_ids_for_ref(self, ref: str) -> list[int]:
        return sorted({way.osm_id for way in self.ways_for_ref(ref)})

    def path_between_refs(self, target_ref: str, start_ref: str, end_ref: str) -> dict[str, Any] | None:
        target_graph = self.ref_subgraph(target_ref)
        if target_graph.number_of_edges() == 0:
            return None
        starts = [node for node in self.intersection_nodes(target_ref, start_ref) if node in target_graph]
        ends = [node for node in self.intersection_nodes(target_ref, end_ref) if node in target_graph]
        candidates: list[tuple[float, list[int | str], int | str, int | str]] = []
        for start in starts:
            for end in ends:
                if start == end:
                    continue
                try:
                    path = nx.shortest_path(target_graph, start, end, weight="length_m")
                    length = nx.path_weight(target_graph, path, weight="length_m")
                except (nx.NetworkXNoPath, nx.NodeNotFound):
                    continue
                candidates.append((float(length), path, start, end))
        if not candidates:
            return None
        candidates.sort(key=lambda item: item[0])
        length, path, start, end = candidates[0]
        return {
            "coordinates": [self.coordinate(node_id) for node_id in path],
            "length_m": length,
            "start_node": start,
            "end_node": end,
            "candidate_count": len(candidates),
            "start_candidate_count": len(starts),
            "end_candidate_count": len(ends),
            "source_osm_ids": self.source_ids_for_ref(target_ref),
        }

    def stand_coordinate(self, stand_ref: str) -> Coordinate | None:
        points = self.points_by_ref.get(normalize_ref(stand_ref) or "", [])
        if not points:
            return None
        return points[0].coordinate

    def project_stand_range(
        self,
        target_ref: str,
        stand_start: str,
        stand_end: str | None = None,
        *,
        half_window_m: float = 80.0,
    ) -> dict[str, Any] | None:
        geometry = self.whole_ref_geometry(target_ref)
        if geometry is None:
            return None
        components = list(geometry.geoms) if isinstance(geometry, MultiLineString) else [geometry]
        start_coord = self.stand_coordinate(stand_start)
        end_coord = self.stand_coordinate(stand_end) if stand_end else None
        if start_coord is None or (stand_end and end_coord is None):
            return None
        start_point_m = transform(_TO_METRES, Point(start_coord))
        end_point_m = transform(_TO_METRES, Point(end_coord)) if end_coord else None
        best = None
        for line in components:
            line_m = transform(_TO_METRES, line)
            start_distance = line_m.project(start_point_m)
            start_error = line_m.interpolate(start_distance).distance(start_point_m)
            if end_point_m is None:
                score = start_error
                lo = max(0.0, start_distance - half_window_m)
                hi = min(line_m.length, start_distance + half_window_m)
            else:
                end_distance = line_m.project(end_point_m)
                end_error = line_m.interpolate(end_distance).distance(end_point_m)
                score = start_error + end_error
                lo, hi = sorted((start_distance, end_distance))
            if best is None or score < best[0]:
                best = (score, line_m, lo, hi, start_error, None if end_point_m is None else end_error)
        if best is None:
            return None
        score, line_m, lo, hi, start_error, end_error = best
        if hi - lo < 1.0:
            hi = min(line_m.length, lo + max(2.0, half_window_m))
        segment_m = _substring(line_m, lo, hi)
        segment = transform(_TO_LONLAT, segment_m)
        coords = list(segment.coords)
        return {
            "coordinates": [(float(x), float(y)) for x, y in coords],
            "length_m": float(segment_m.length),
            "projection_error_m": float(start_error + (end_error or 0.0)),
            "source_osm_ids": self.source_ids_for_ref(target_ref),
        }

    def base_geojson(self) -> dict[str, Any]:
        features = []
        for way in self.snapshot.ways:
            if len(way.coordinates) < 2:
                continue
            features.append(
                {
                    "type": "Feature",
                    "id": f"osm-way-{way.osm_id}",
                    "geometry": {"type": "LineString", "coordinates": [list(coord) for coord in way.coordinates]},
                    "properties": {
                        "osm_id": way.osm_id,
                        "aeroway": way.aeroway,
                        "ref": way.ref,
                        "surface": way.tags.get("surface"),
                        "source": "openstreetmap",
                        "not_for_navigation": True,
                    },
                }
            )
        for point in self.snapshot.points:
            features.append(
                {
                    "type": "Feature",
                    "id": f"osm-node-{point.osm_id}",
                    "geometry": {"type": "Point", "coordinates": list(point.coordinate)},
                    "properties": {
                        "osm_id": point.osm_id,
                        "aeroway": point.aeroway,
                        "ref": point.ref,
                        "source": "openstreetmap",
                        "not_for_navigation": True,
                    },
                }
            )
        return {"type": "FeatureCollection", "features": features}


def _substring(line: LineString, start_distance: float, end_distance: float) -> LineString:
    """Return a metric substring without requiring Shapely 2's substring helper."""
    if start_distance <= 0 and end_distance >= line.length:
        return line
    start = max(0.0, min(float(start_distance), line.length))
    end = max(start, min(float(end_distance), line.length))
    coordinates = list(line.coords)
    result = [line.interpolate(start).coords[0]]
    travelled = 0.0
    for a, b in zip(coordinates, coordinates[1:]):
        segment_length = math.dist(a, b)
        next_travelled = travelled + segment_length
        if next_travelled > start and travelled < end:
            if travelled >= start:
                result.append(a)
            if next_travelled <= end:
                result.append(b)
        travelled = next_travelled
        if travelled >= end:
            break
    endpoint = line.interpolate(end).coords[0]
    if not result or result[-1] != endpoint:
        result.append(endpoint)
    deduplicated = [result[0]]
    for coordinate in result[1:]:
        if coordinate != deduplicated[-1]:
            deduplicated.append(coordinate)
    if len(deduplicated) == 1:
        deduplicated.append(deduplicated[0])
    return LineString(deduplicated)

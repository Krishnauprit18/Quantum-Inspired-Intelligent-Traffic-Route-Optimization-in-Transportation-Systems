"""Build a :class:`RoadGraph` from an edge list, a GeoJSON of LineStrings, a raw ``.osm``
XML file, or a synthetic grid (for demos / §14 "synthetic large instance").

``.osm`` XML (Overpass / JOSM export) is parsed with the standard library — no ``pyrosm`` /
``osmium`` needed. Binary ``.pbf`` is out of scope; convert it to XML or GeoJSON first.

Input files are size-capped before parsing (``max_bytes``). ``xml.etree.ElementTree`` on
current CPython (expat >= 2.4.1) is not vulnerable to entity-expansion attacks; if you must
parse XML from a fully untrusted source, install ``defusedxml`` and swap the parser.
"""

from __future__ import annotations

import json
import math
import xml.etree.ElementTree as ET
from collections.abc import Iterable, Mapping
from pathlib import Path

import numpy as np

from quantroute.roadgraph.graph import RoadGraph, RoadGraphError

# free-flow speed (km/h) by OSM ``highway`` class
ROAD_CLASS_SPEED_KPH: dict[str, float] = {
    "motorway": 100.0,
    "trunk": 80.0,
    "primary": 60.0,
    "secondary": 50.0,
    "tertiary": 40.0,
    "unclassified": 40.0,
    "residential": 30.0,
    "living_street": 15.0,
    "service": 20.0,
}
_DEFAULT_SPEED_KPH = 30.0

_MAX_NODES = 2_000_000
_MAX_EDGES = 6_000_000
_DEFAULT_MAX_BYTES = 256 * 1024 * 1024


def _read_capped(path: str | Path, max_bytes: int) -> str:
    p = Path(path).expanduser()
    if not p.is_file():
        raise RoadGraphError(f"not a file: {p}")
    size = p.stat().st_size
    if size > max_bytes:
        raise RoadGraphError(f"{p.name} is {size} bytes, over the {max_bytes}-byte limit")
    return p.read_text(encoding="utf-8", errors="strict")


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance between two lat/lon points, in metres."""
    r = 6_371_000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _speed_for(road_class: str, maxspeed: float | None) -> float:
    if maxspeed and maxspeed > 0:
        return maxspeed
    return ROAD_CLASS_SPEED_KPH.get(road_class, _DEFAULT_SPEED_KPH)


class _Builder:
    """Accumulates nodes and directed edges, then freezes into a RoadGraph."""

    def __init__(self) -> None:
        self._node_xy: dict[int, tuple[float, float]] = {}
        self._src: list[int] = []
        self._dst: list[int] = []
        self._len: list[float] = []
        self._free: list[float] = []
        self._cls: list[str] = []

    def add_node(self, node_id: int, x: float, y: float) -> None:
        self._node_xy.setdefault(int(node_id), (float(x), float(y)))
        if len(self._node_xy) > _MAX_NODES:
            raise RoadGraphError(f"too many nodes (> {_MAX_NODES})")

    def add_edge(
        self, u: int, v: int, length_m: float, free_flow_s: float, road_class: str, *, both: bool
    ) -> None:
        if u not in self._node_xy or v not in self._node_xy:
            raise RoadGraphError(f"edge {u}->{v} references an unknown node")
        pairs = [(u, v), (v, u)] if both else [(u, v)]
        for a, b in pairs:
            self._src.append(int(a))
            self._dst.append(int(b))
            self._len.append(float(length_m))
            self._free.append(float(free_flow_s))
            self._cls.append(str(road_class))
        if len(self._src) > _MAX_EDGES:
            raise RoadGraphError(f"too many edges (> {_MAX_EDGES})")

    def build(self) -> RoadGraph:
        if not self._src:
            raise RoadGraphError("no edges were produced")
        node_ids = np.array(sorted(self._node_xy), dtype=np.int64)
        idx = {int(nid): i for i, nid in enumerate(node_ids)}
        node_xy = np.array([self._node_xy[int(nid)] for nid in node_ids], dtype=np.float64)
        return RoadGraph(
            node_ids=node_ids,
            node_xy=node_xy,
            edge_src_idx=np.array([idx[s] for s in self._src], dtype=np.int64),
            edge_dst_idx=np.array([idx[d] for d in self._dst], dtype=np.int64),
            edge_len_m=np.array(self._len, dtype=np.float64),
            edge_free_flow_s=np.array(self._free, dtype=np.float64),
            edge_class=self._cls,
        )


def from_edges(
    nodes: Mapping[int, tuple[float, float]],
    edges: Iterable[Mapping],
) -> RoadGraph:
    """``nodes`` maps id -> (x, y). Each edge is a mapping with ``u``, ``v`` and either
    ``free_flow_s`` or (``length_m`` + optional ``road_class`` / ``speed_kph``); set
    ``oneway: true`` to skip the reverse direction.
    """
    b = _Builder()
    for nid, (x, y) in nodes.items():
        b.add_node(int(nid), x, y)
    for raw in edges:
        u, v = int(raw["u"]), int(raw["v"])
        road_class = str(raw.get("road_class", "residential"))
        length_m = float(raw.get("length_m") or _euclidean(nodes[u], nodes[v]))
        if "free_flow_s" in raw and raw["free_flow_s"]:
            free_flow_s = float(raw["free_flow_s"])
        else:
            speed = _speed_for(road_class, raw.get("speed_kph"))
            free_flow_s = length_m / (speed / 3.6)
        b.add_edge(u, v, length_m, free_flow_s, road_class, both=not bool(raw.get("oneway")))
    return b.build()


def from_geojson(source: str | Path | dict, *, max_bytes: int = _DEFAULT_MAX_BYTES) -> RoadGraph:
    """A GeoJSON ``FeatureCollection`` of ``LineString`` features. Coordinates are
    ``[lon, lat]``; properties may carry ``highway`` and ``oneway`` and ``maxspeed``.
    Nodes are de-duplicated by rounded coordinate.
    """
    obj = source if isinstance(source, dict) else json.loads(_read_capped(source, max_bytes))
    feats = obj.get("features") if isinstance(obj, dict) else None
    if not feats:
        raise RoadGraphError("GeoJSON has no features")

    b = _Builder()
    coord_id: dict[tuple[float, float], int] = {}

    def node_for(lon: float, lat: float) -> int:
        key = (round(lon, 7), round(lat, 7))
        if key not in coord_id:
            nid = len(coord_id) + 1
            coord_id[key] = nid
            b.add_node(nid, lon, lat)
        return coord_id[key]

    for feat in feats:
        geom = (feat or {}).get("geometry") or {}
        if geom.get("type") != "LineString":
            continue
        props = feat.get("properties") or {}
        road_class = str(props.get("highway", "residential"))
        oneway = str(props.get("oneway", "")).lower() in ("yes", "true", "1")
        maxspeed = _parse_maxspeed(props.get("maxspeed"))
        coords = geom.get("coordinates") or []
        for (lon1, lat1), (lon2, lat2) in zip(coords, coords[1:]):
            u = node_for(lon1, lat1)
            v = node_for(lon2, lat2)
            if u == v:
                continue
            length_m = haversine_m(lat1, lon1, lat2, lon2)
            free_flow_s = length_m / (_speed_for(road_class, maxspeed) / 3.6)
            b.add_edge(u, v, length_m, free_flow_s, road_class, both=not oneway)
    return b.build()


def from_osm_xml(source: str | Path, *, max_bytes: int = _DEFAULT_MAX_BYTES) -> RoadGraph:
    """A raw OpenStreetMap XML file (Overpass API / JOSM export). Only ways with a
    ``highway`` tag become edges; node coordinates come from ``<node lat lon>``.
    """
    root = ET.fromstring(_read_capped(source, max_bytes))

    coords: dict[int, tuple[float, float]] = {}
    for nd in root.iter("node"):
        try:
            coords[int(nd.attrib["id"])] = (float(nd.attrib["lon"]), float(nd.attrib["lat"]))
        except (KeyError, ValueError):
            continue

    b = _Builder()
    used_nodes: set[int] = set()
    ways: list[tuple[list[int], str, bool, float | None]] = []
    for way in root.iter("way"):
        refs = [int(nd.attrib["ref"]) for nd in way.iter("nd") if "ref" in nd.attrib]
        tags = {t.attrib.get("k"): t.attrib.get("v") for t in way.iter("tag")}
        if "highway" not in tags or len(refs) < 2:
            continue
        oneway = str(tags.get("oneway", "")).lower() in ("yes", "true", "1")
        ways.append((refs, str(tags["highway"]), oneway, _parse_maxspeed(tags.get("maxspeed"))))
        used_nodes.update(refs)

    for nid in used_nodes:
        if nid in coords:
            lon, lat = coords[nid]
            b.add_node(nid, lon, lat)

    for refs, road_class, oneway, maxspeed in ways:
        for u, v in zip(refs, refs[1:]):
            if u not in coords or v not in coords or u == v:
                continue
            (lon1, lat1), (lon2, lat2) = coords[u], coords[v]
            length_m = haversine_m(lat1, lon1, lat2, lon2)
            free_flow_s = length_m / (_speed_for(road_class, maxspeed) / 3.6)
            b.add_edge(u, v, length_m, free_flow_s, road_class, both=not oneway)
    return b.build()


def grid_city(rows: int, cols: int, *, spacing_m: float = 120.0, arterial_every: int = 4) -> RoadGraph:
    """A synthetic Manhattan-style grid: node ``r*cols + c`` at ``(c, r) * spacing``.
    Every ``arterial_every``-th row/column is a faster "arterial" road.
    """
    if rows < 2 or cols < 2:
        raise RoadGraphError("grid_city needs rows >= 2 and cols >= 2")
    nodes: dict[int, tuple[float, float]] = {}
    for r in range(rows):
        for c in range(cols):
            nodes[r * cols + c] = (c * spacing_m, r * spacing_m)

    edges: list[dict] = []
    for r in range(rows):
        for c in range(cols):
            here = r * cols + c
            for dr, dc, along_row in ((0, 1, True), (1, 0, False)):
                nr, nc = r + dr, c + dc
                if nr >= rows or nc >= cols:
                    continue
                arterial = (c % arterial_every == 0) if along_row else (r % arterial_every == 0)
                edges.append(
                    {
                        "u": here,
                        "v": nr * cols + nc,
                        "length_m": spacing_m,
                        "road_class": "secondary" if arterial else "residential",
                    }
                )
    return from_edges(nodes, edges)


# -- small helpers -------------------------------------------------


def _euclidean(a: tuple[float, float], b: tuple[float, float]) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _parse_maxspeed(value) -> float | None:
    if value is None:
        return None
    try:
        token = str(value).split()[0]
        return float(token)
    except (ValueError, IndexError):
        return None

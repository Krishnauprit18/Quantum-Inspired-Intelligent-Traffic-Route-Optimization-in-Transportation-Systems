"""Road-network model (PDF Deliverable 1, system-design.html §8.1 / §8.2 / §9).

RoadGraph          directed weighted graph + Dijkstra / many-to-many / shortest_path
WeightEpoch        immutable per-edge travel-time snapshot
WeightModel        turns speed / congestion observations into new epochs
RoadGraphMatrix    a CostMatrix backed by the graph — drops into the solver unchanged

loaders: from_edges, from_geojson, from_osm_xml, grid_city
"""

from quantroute.roadgraph.graph import Path, RoadGraph, RoadGraphError
from quantroute.roadgraph.loaders import (
    ROAD_CLASS_SPEED_KPH,
    from_edges,
    from_geojson,
    from_osm_xml,
    grid_city,
    haversine_m,
)
from quantroute.roadgraph.matrix import RoadGraphMatrix
from quantroute.roadgraph.osm import (
    PRESET_CITIES,
    build_overpass_query,
    fetch_osm_city,
    load_city_roadgraph,
)
from quantroute.roadgraph.traffic_stream import (
    SUMOOutputParser,
    TrafficProbe,
    TrafficStreamSimulator,
)
from quantroute.roadgraph.weights import WeightEpoch, WeightModel

__all__ = [
    "RoadGraph",
    "RoadGraphError",
    "Path",
    "WeightEpoch",
    "WeightModel",
    "RoadGraphMatrix",
    "from_edges",
    "from_geojson",
    "from_osm_xml",
    "grid_city",
    "haversine_m",
    "ROAD_CLASS_SPEED_KPH",
    "PRESET_CITIES",
    "build_overpass_query",
    "fetch_osm_city",
    "load_city_roadgraph",
    "TrafficProbe",
    "TrafficStreamSimulator",
    "SUMOOutputParser",
]

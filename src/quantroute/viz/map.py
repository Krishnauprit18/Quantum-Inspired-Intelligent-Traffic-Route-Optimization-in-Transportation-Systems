"""Turn a solved :class:`~quantroute.routes.Routes` into a GeoJSON of route polylines and
render it as a standalone Leaflet HTML page or a PNG.

If a :class:`~quantroute.roadgraph.RoadGraph` is supplied, each leg is expanded to the real
road path (via ``shortest_path``); otherwise legs are straight lines between stops.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path

from quantroute.routes import Routes

ROUTE_COLORS = [
    "#2563eb",
    "#dc2626",
    "#059669",
    "#d97706",
    "#7c3aed",
    "#0891b2",
    "#db2777",
    "#65a30d",
    "#ea580c",
    "#4f46e5",
]


def routes_to_geojson(
    routes: Routes,
    coords: Mapping[int, tuple[float, float]],
    depot_node: int,
    *,
    stop_node: Mapping[str, int],
    road_graph=None,
    epoch=None,
) -> dict:
    """FeatureCollection: one LineString per non-empty route, plus depot / stop points.

    ``coords`` maps node id -> (x, y) (x = longitude / easting, y = latitude / northing).
    ``stop_node`` maps each stop id to its graph node id.
    """
    features: list[dict] = []

    features.append(_point(coords[depot_node], {"role": "depot", "node": int(depot_node)}, "depot"))

    for ri, route in enumerate(r for r in routes if r.stop_ids):
        color = ROUTE_COLORS[ri % len(ROUTE_COLORS)]
        seq_nodes = [
            int(depot_node),
            *(int(stop_node[sid]) for sid in route.stop_ids),
            int(depot_node),
        ]
        line = _expand(seq_nodes, coords, road_graph, epoch)
        features.append(
            {
                "type": "Feature",
                "properties": {
                    "role": "route",
                    "vehicle": route.vehicle_id,
                    "stops": list(route.stop_ids),
                    "color": color,
                },
                "geometry": {"type": "LineString", "coordinates": line},
            }
        )
        for sid in route.stop_ids:
            node = int(stop_node[sid])
            features.append(
                _point(
                    coords[node],
                    {"role": "stop", "id": sid, "vehicle": route.vehicle_id, "color": color},
                    "stop",
                )
            )

    return {"type": "FeatureCollection", "features": features}


# --------------------------------------------------------------------- HTML


_HTML = """<!doctype html><html><head><meta charset="utf-8">
<title>__TITLE__</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style>html,body{margin:0;height:100%}#map{height:100%}
.legend{background:#fff;padding:8px 10px;font:13px system-ui;border-radius:6px;box-shadow:0 1px 4px rgba(0,0,0,.3)}
.legend b{display:inline-block;width:12px;height:12px;border-radius:2px;margin-right:6px;vertical-align:middle}</style>
</head><body><div id="map"></div><script>
const FC = __GEOJSON__;
const GEO = __GEOGRAPHIC__;
const map = L.map('map', GEO ? {} : {crs: L.CRS.Simple, minZoom: -5});
if (GEO) L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png',
  {maxZoom: 19, attribution: '&copy; OpenStreetMap'}).addTo(map);
const layer = L.geoJSON(FC, {
  style: f => ({color: f.properties.color || '#333', weight: 4, opacity: .8}),
  pointToLayer: (f, ll) => f.properties.role === 'depot'
    ? L.marker(ll)
    : L.circleMarker(ll, {radius: 5, color: '#111', weight: 1, fillColor: f.properties.color || '#888', fillOpacity: 1}),
  onEachFeature: (f, l) => {
    const p = f.properties;
    if (p.role === 'route') l.bindPopup('vehicle <b>' + p.vehicle + '</b><br>' + p.stops.join(' → '));
    else if (p.role === 'stop') l.bindPopup('stop <b>' + p.id + '</b> (vehicle ' + p.vehicle + ')');
    else l.bindPopup('depot');
  }
}).addTo(map);
map.fitBounds(layer.getBounds(), {padding: [30, 30]});
const routes = FC.features.filter(f => f.properties.role === 'route');
if (routes.length) {
  const lg = L.control({position: 'bottomright'});
  lg.onAdd = () => { const d = L.DomUtil.create('div', 'legend');
    d.innerHTML = '<div><b style="background:#000"></b>depot</div>' +
      routes.map(r => '<div><b style="background:' + r.properties.color + '"></b>' + r.properties.vehicle + '</div>').join('');
    return d; };
  lg.addTo(map);
}
</script></body></html>"""


def render_map_html(
    feature_collection: dict, *, title: str = "quantroute", geographic: bool | None = None
) -> str:
    if geographic is None:
        geographic = _looks_geographic(feature_collection)
    return (
        _HTML.replace("__TITLE__", _escape(title))
        .replace("__GEOJSON__", json.dumps(feature_collection))
        .replace("__GEOGRAPHIC__", "true" if geographic else "false")
    )


# --------------------------------------------------------------------- PNG


def render_map_png(feature_collection: dict, out, *, title: str = "quantroute"):
    """Render to ``out`` — a path (str / Path) or an open binary file object."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(8, 8))
    for feat in feature_collection["features"]:
        geom = feat["geometry"]
        props = feat["properties"]
        if geom["type"] == "LineString":
            xs, ys = zip(*geom["coordinates"], strict=False)
            ax.plot(xs, ys, "-", color=props.get("color", "#333"), lw=2, label=props.get("vehicle"))
        elif props.get("role") == "depot":
            x, y = geom["coordinates"]
            ax.plot(x, y, "s", color="black", markersize=10, zorder=5)
        else:
            x, y = geom["coordinates"]
            ax.plot(
                x,
                y,
                "o",
                color=props.get("color", "#888"),
                markersize=6,
                mec="black",
                mew=0.5,
                zorder=4,
            )

    ax.set_aspect("equal", adjustable="datalim")
    ax.set_title(title)
    handles, labels = ax.get_legend_handles_labels()
    if labels:
        ax.legend(handles, labels, fontsize=9, loc="best")
    fig.tight_layout()
    target = str(out) if isinstance(out, str | Path) else out
    fig.savefig(target, dpi=130, format="png")
    plt.close(fig)
    return out


# --------------------------------------------------------------------- helpers


def _expand(seq_nodes, coords, road_graph, epoch) -> list[list[float]]:
    if road_graph is None or epoch is None:
        return [list(coords[n]) for n in seq_nodes]
    line: list[list[float]] = []
    for a, b in zip(seq_nodes, seq_nodes[1:], strict=False):
        path = road_graph.shortest_path(a, b, epoch.travel_time_s)
        pts = [list(coords[n]) for n in path.nodes]
        line.extend(pts if not line else pts[1:])
    return line


def _point(xy: tuple[float, float], props: dict, role: str) -> dict:
    return {
        "type": "Feature",
        "properties": {**props, "role": role},
        "geometry": {"type": "Point", "coordinates": [float(xy[0]), float(xy[1])]},
    }


def _looks_geographic(fc: dict) -> bool:
    """Geographic iff every point is within lon/lat bounds AND at least one coordinate has
    a fractional part — planar demo grids use whole metres, real lat/lon almost never do.
    Pass ``geographic=`` to :func:`render_map_html` to override.
    """
    seen_fraction = False
    for feat in fc["features"]:
        coords = feat["geometry"]["coordinates"]
        pts = coords if feat["geometry"]["type"] == "LineString" else [coords]
        for x, y in pts:
            if not (-180.0 <= x <= 180.0 and -90.0 <= y <= 90.0):
                return False
            if x != int(x) or y != int(y):
                seen_fraction = True
    return seen_fraction


def _escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

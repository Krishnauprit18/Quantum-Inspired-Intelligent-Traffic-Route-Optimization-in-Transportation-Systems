"""Piece 12 tests: route -> GeoJSON and the HTML / PNG map renderers."""

import json

import pytest

from quantroute.roadgraph import WeightModel, grid_city
from quantroute.routes import Route, Routes
from quantroute.viz import render_map_html, render_map_png, routes_to_geojson

COORDS = {0: (0.0, 0.0), 1: (10.0, 0.0), 2: (20.0, 0.0), 3: (0.0, 10.0)}
ROUTES = Routes((Route("v1", ("c1", "c2")), Route("v2", ("c3",)), Route("v3", ())))
STOP_NODE = {"c1": 1, "c2": 2, "c3": 3}


def test_routes_to_geojson_shape():
    fc = routes_to_geojson(ROUTES, COORDS, 0, stop_node=STOP_NODE)
    assert fc["type"] == "FeatureCollection"
    roles = [f["properties"]["role"] for f in fc["features"]]
    assert roles.count("depot") == 1
    assert roles.count("route") == 2  # empty v3 is skipped
    assert roles.count("stop") == 3
    line = next(f for f in fc["features"] if f["properties"]["role"] == "route")
    # depot -> c1 -> c2 -> depot
    assert line["geometry"]["coordinates"] == [[0, 0], [10, 0], [20, 0], [0, 0]]


def test_geojson_uses_real_road_path_when_graph_given():
    g = grid_city(4, 4, spacing_m=100.0)
    ep = WeightModel(g).free_flow_epoch()
    routes = Routes((Route("v1", ("s3", "s15")),))
    fc = routes_to_geojson(
        routes, g.coordinates(), 0, stop_node={"s3": 3, "s15": 15}, road_graph=g, epoch=ep
    )
    line = next(f for f in fc["features"] if f["properties"]["role"] == "route")
    # a real path 0 -> 3 -> 15 -> 0 through the grid has more than 4 vertices
    assert len(line["geometry"]["coordinates"]) > 4


def test_render_map_html_is_self_describing():
    fc = routes_to_geojson(ROUTES, COORDS, 0, stop_node=STOP_NODE)
    html = render_map_html(fc, title="my routes")
    assert "leaflet" in html.lower()
    assert "my routes" in html
    assert "__GEOJSON__" not in html and "__GEOGRAPHIC__" not in html
    assert json.dumps(fc) in html
    assert "false" in html  # planar coords -> not geographic


def test_render_map_html_detects_geographic_coords():
    coords = {0: (73.85, 18.52), 1: (73.86, 18.52), 2: (73.86, 18.53)}
    fc = routes_to_geojson(
        Routes((Route("v1", ("c1", "c2")),)), coords, 0, stop_node={"c1": 1, "c2": 2}
    )
    assert "true" in render_map_html(fc)  # lat/lon -> geographic


def test_render_map_png(tmp_path):
    pytest.importorskip("matplotlib")
    fc = routes_to_geojson(ROUTES, COORDS, 0, stop_node=STOP_NODE)
    out = tmp_path / "map.png"
    render_map_png(fc, out, title="png map")
    assert out.is_file() and out.stat().st_size > 1000

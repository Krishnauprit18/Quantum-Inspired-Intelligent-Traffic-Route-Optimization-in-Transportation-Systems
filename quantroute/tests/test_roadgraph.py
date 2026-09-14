"""Piece 10 tests: RoadGraph, RoadGraphMatrix, loaders, and end-to-end on a road network."""

import numpy as np
import pytest

from quantroute import (
    ConstraintSet,
    Depot,
    FitnessEvaluator,
    GreedyRepair,
    ProblemSpec,
    QPSOConfig,
    QPSOOptimizer,
    RandomKeyGiantTour,
    SearchProblem,
    Stop,
    TerminationCriteria,
    Vehicle,
)
from quantroute.roadgraph import (
    RoadGraphError,
    RoadGraphMatrix,
    WeightModel,
    from_edges,
    from_geojson,
    from_osm_xml,
    grid_city,
)


def line_graph():
    """0 ->1 ->2 ->3 with a slow shortcut 0 ->2."""
    nodes = {0: (0, 0), 1: (1, 0), 2: (2, 0), 3: (3, 0)}
    edges = [
        {"u": 0, "v": 1, "free_flow_s": 1.0, "length_m": 10.0, "oneway": True},
        {"u": 1, "v": 2, "free_flow_s": 1.0, "length_m": 10.0, "oneway": True},
        {"u": 2, "v": 3, "free_flow_s": 1.0, "length_m": 10.0, "oneway": True},
        {"u": 0, "v": 2, "free_flow_s": 5.0, "length_m": 40.0, "oneway": True},
    ]
    return from_edges(nodes, edges)


# -- graph -------------------------------------------------------------


def test_dijkstra_prefers_the_fast_route():
    g = line_graph()
    ff = WeightModel(g).free_flow_epoch().travel_time_s
    path = g.shortest_path(0, 3, ff)
    assert path.nodes == (0, 1, 2, 3)
    assert path.travel_time_s == 3.0
    assert path.distance_m == 30.0


def test_many_to_many_shapes_and_values():
    g = line_graph()
    ff = WeightModel(g).free_flow_epoch().travel_time_s
    tm, dm = g.many_to_many([0, 1], [2, 3], ff)
    assert tm.shape == (2, 2)
    assert tm[0, 0] == 2.0 and tm[0, 1] == 3.0  # 0->2, 0->3
    assert tm[1, 1] == 2.0  # 1->3
    assert dm[0, 1] == 30.0


def test_oneway_edges_are_directed():
    g = line_graph()
    ff = WeightModel(g).free_flow_epoch().travel_time_s
    with pytest.raises(RoadGraphError, match="no path"):
        g.shortest_path(3, 0, ff)


def test_unknown_node_raises():
    g = line_graph()
    ff = WeightModel(g).free_flow_epoch().travel_time_s
    with pytest.raises(RoadGraphError, match="not in the graph"):
        g.shortest_path(0, 99, ff)


# -- RoadGraphMatrix -------------------------------------------------


def test_matrix_is_a_costmatrix_and_has_shortest_path():
    from quantroute import CostMatrix

    g = grid_city(4, 4)
    ep = WeightModel(g).free_flow_epoch()
    m = RoadGraphMatrix(g, [0, 5, 10, 15], ep)
    assert isinstance(m, CostMatrix)
    assert m.nodes == (0, 5, 10, 15)
    assert m.travel_time(0, 15) > 0
    assert m.travel_time(0, 5) == m.travel_time(5, 0)  # grid is symmetric
    p = m.shortest_path(0, 15)
    assert p.nodes[0] == 0 and p.nodes[-1] == 15
    assert p.travel_time_s == pytest.approx(m.travel_time(0, 15))


def test_matrix_rejects_disconnected_nodes():
    nodes = {0: (0, 0), 1: (1, 0), 2: (99, 99)}  # node 2 is isolated
    g = from_edges(nodes, [{"u": 0, "v": 1, "free_flow_s": 1.0, "length_m": 1.0}])
    ep = WeightModel(g).free_flow_epoch()
    with pytest.raises(RoadGraphError, match="not connected"):
        RoadGraphMatrix(g, [0, 1, 2], ep)


def test_with_epoch_recomputes_after_a_weight_change():
    g = grid_city(5, 5)
    wm = WeightModel(g, smoothing=1.0)
    base = RoadGraphMatrix(g, [0, 12, 24], wm.free_flow_epoch())
    t_before = base.travel_time(0, 24)

    # slow every edge to 4x
    slow = wm.update(congestion_factor={e: 4.0 for e in range(g.num_edges)})
    congested = base.with_epoch(slow)
    assert congested.travel_time(0, 24) > t_before * 2


# -- loaders ------------------------------------------------------


def test_from_geojson_dedups_shared_coordinates():
    obj = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {"highway": "primary"},
                "geometry": {"type": "LineString", "coordinates": [[0, 0], [0.001, 0]]},
            },
            {
                "type": "Feature",
                "properties": {"highway": "residential", "oneway": "yes"},
                "geometry": {"type": "LineString", "coordinates": [[0.001, 0], [0.001, 0.001]]},
            },
        ],
    }
    g = from_geojson(obj)
    assert g.num_nodes == 3  # the shared [0.001, 0] coordinate is one node
    assert g.num_edges == 3  # primary both ways (2) + residential oneway (1)


def test_from_osm_xml(tmp_path):
    xml = """<?xml version='1.0'?>
    <osm version="0.6">
      <node id="1" lat="0.0" lon="0.0"/>
      <node id="2" lat="0.0" lon="0.001"/>
      <node id="3" lat="0.001" lon="0.001"/>
      <node id="9" lat="5.0" lon="5.0"/>
      <way id="100">
        <nd ref="1"/><nd ref="2"/><nd ref="3"/>
        <tag k="highway" v="residential"/>
      </way>
      <way id="200">
        <nd ref="1"/><nd ref="9"/>
        <tag k="building" v="yes"/>
      </way>
    </osm>"""
    p = tmp_path / "sample.osm"
    p.write_text(xml, encoding="utf-8")
    g = from_osm_xml(p)
    assert g.num_nodes == 3  # node 9 belongs only to a non-highway way -> excluded
    assert g.num_edges == 4  # 2 segments x both directions


# -- end to end: the whole solver on a road graph -----------------


def _road_problem(congestion_epoch=None):
    g = grid_city(6, 6, spacing_m=100.0)
    wm = WeightModel(g, smoothing=1.0)
    epoch = congestion_epoch or wm.free_flow_epoch()
    depot, stops = 0, [8, 10, 15, 21, 28, 33]
    matrix = RoadGraphMatrix(g, [depot, *stops], epoch)
    spec = ProblemSpec(
        name="grid-city",
        depots=(Depot("depot", node=depot),),
        stops=tuple(Stop(f"s{n}", node=n, demand=10.0) for n in stops),
        vehicles=tuple(Vehicle(f"v{i}", capacity=40.0, start_depot="depot") for i in range(3)),
        constraints=ConstraintSet(enforce_time_windows=False),
    )
    enc = RandomKeyGiantTour(spec, matrix)
    ev = FitnessEvaluator(spec, matrix, enc, repair=GreedyRepair(spec, matrix))
    return g, wm, SearchProblem(spec, matrix, enc, ev), spec


def test_qpso_runs_on_a_road_graph():
    _, _, problem, spec = _road_problem()
    res = QPSOOptimizer(QPSOConfig(swarm_size=20, max_iterations=80, seed=1)).solve(
        problem, termination=TerminationCriteria(max_iterations=80)
    )
    assert res.feasible
    ok, why = res.routes.covers(spec)
    assert ok, why
    assert res.best_cost > 0


def test_congestion_makes_the_optimum_worse():
    g, wm, free_problem, _ = _road_problem()
    free_res = QPSOOptimizer(QPSOConfig(swarm_size=20, max_iterations=100, seed=2)).solve(
        free_problem, termination=TerminationCriteria(max_iterations=100)
    )

    jam = wm.update(congestion_factor={e: 3.0 for e in range(g.num_edges)})
    _, _, jam_problem, _ = _road_problem(congestion_epoch=jam)
    jam_res = QPSOOptimizer(QPSOConfig(swarm_size=20, max_iterations=100, seed=2)).solve(
        jam_problem, termination=TerminationCriteria(max_iterations=100)
    )

    assert jam_res.feasible
    assert jam_res.best_cost > free_res.best_cost * 1.5  # slower roads -> costlier routes

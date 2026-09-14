"""Piece 10 tests: WeightEpoch immutability and the WeightModel update mechanism."""

import numpy as np
import pytest

from quantroute.roadgraph import WeightModel, from_edges


def small_graph():
    nodes = {0: (0, 0), 1: (100, 0), 2: (200, 0)}
    edges = [
        {"u": 0, "v": 1, "length_m": 100.0, "road_class": "residential"},  # 30 kph -> 12 s
        {"u": 1, "v": 2, "length_m": 100.0, "road_class": "residential"},
    ]
    return from_edges(nodes, edges)  # 4 directed edges


def test_free_flow_epoch_is_epoch_zero_and_read_only():
    g = small_graph()
    ep = WeightModel(g).free_flow_epoch()
    assert ep.epoch_id == 0 and ep.source == "free_flow"
    assert np.allclose(ep.travel_time_s, g.edge_free_flow_s)
    with pytest.raises(ValueError):
        ep.travel_time_s[0] = 1.0


def test_update_blends_and_bumps_epoch_id():
    g = small_graph()
    wm = WeightModel(g, smoothing=0.5)
    ff = wm.free_flow_epoch().travel_time_s[0]

    ep1 = wm.update(congestion_factor={0: 3.0})
    assert ep1.epoch_id == 1
    # blend: 0.5*ff + 0.5*(3*ff) = 2*ff
    assert ep1.travel_time_s[0] == pytest.approx(2.0 * ff)
    # untouched edges unchanged
    assert ep1.travel_time_s[1] == pytest.approx(g.edge_free_flow_s[1])

    ep2 = wm.update(congestion_factor={0: 3.0})
    assert ep2.epoch_id == 2
    assert ep2.travel_time_s[0] > ep1.travel_time_s[0]  # EWMA keeps rising toward 3*ff


def test_speeds_and_never_faster_than_free_flow():
    g = small_graph()
    wm = WeightModel(g, smoothing=1.0)
    ff = g.edge_free_flow_s[0]

    slow = wm.update(edge_speeds_kph={0: 15.0})  # half the 30 kph default -> double time
    assert slow.travel_time_s[0] == pytest.approx(2.0 * ff)

    fast = wm.update(edge_speeds_kph={0: 200.0})  # absurdly fast
    assert fast.travel_time_s[0] == pytest.approx(ff)  # floored at free-flow


def test_unobserved_factor_applies_to_the_rest():
    g = small_graph()
    wm = WeightModel(g, smoothing=1.0)
    ep = wm.update(congestion_factor={0: 2.0}, unobserved_factor=1.5)
    assert ep.travel_time_s[0] == pytest.approx(2.0 * g.edge_free_flow_s[0])
    assert ep.travel_time_s[1] == pytest.approx(1.5 * g.edge_free_flow_s[1])


def test_validation():
    g = small_graph()
    with pytest.raises(ValueError):
        WeightModel(g, smoothing=0.0)
    wm = WeightModel(g)
    with pytest.raises(ValueError):
        wm.update(edge_speeds_kph={0: 0.0})
    with pytest.raises(ValueError):
        wm.update(congestion_factor={99: 2.0})  # edge id out of range


def test_staleness_helpers():
    g = small_graph()
    ep = WeightModel(g).free_flow_epoch()
    now = ep.created_at + 120.0
    assert ep.age_s(now) == pytest.approx(120.0)
    assert ep.is_stale(60.0, now)
    assert not ep.is_stale(300.0, now)

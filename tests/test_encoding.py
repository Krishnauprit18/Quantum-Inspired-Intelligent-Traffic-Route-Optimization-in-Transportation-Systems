"""Piece 3 tests: random-key giant tour + capacity-aware Prins split."""

from pathlib import Path

import numpy as np
import pytest

from quantroute import (
    ConstraintSet,
    Depot,
    Encoding,
    Objective,
    ProblemSpec,
    RandomKeyGiantTour,
    Stop,
    Vehicle,
    euclidean_matrix_2d,
)
from quantroute.io import parse_vrp

DATA = Path(__file__).parent.parent / "data" / "instances"
TOY = DATA / "toy-n5-k2.vrp"


def toy_encoding() -> RandomKeyGiantTour:
    inst = parse_vrp(TOY)
    return RandomKeyGiantTour(inst.spec, inst.matrix)


def test_protocol_surface():
    enc = toy_encoding()
    assert isinstance(enc, Encoding)
    assert enc.dimension == 4
    assert enc.bounds() == (0.0, 1.0)
    v = enc.random(np.random.default_rng(0))
    assert v.shape == (4,)
    assert np.all((v >= 0.0) & (v < 1.0))


def test_random_is_deterministic_per_seed():
    enc = toy_encoding()
    a = enc.random(np.random.default_rng(42))
    b = enc.random(np.random.default_rng(42))
    assert np.array_equal(a, b)


def test_giant_tour_follows_key_order_and_is_stable():
    enc = toy_encoding()
    # stops are c2, c3, c4, c5 in spec order
    assert enc.giant_tour(np.array([0.1, 0.2, 0.3, 0.4])) == ("c2", "c3", "c4", "c5")
    assert enc.giant_tour(np.array([0.9, 0.1, 0.5, 0.3])) == ("c3", "c5", "c4", "c2")
    # all-equal keys -> original order preserved (stable sort)
    assert enc.giant_tour(np.array([0.5, 0.5, 0.5, 0.5])) == ("c2", "c3", "c4", "c5")


def test_split_reaches_known_optimum_on_toy():
    enc = toy_encoding()
    inst = parse_vrp(TOY)
    decoded = enc.decode_detailed(np.array([0.1, 0.2, 0.3, 0.4]))

    assert decoded.feasible is True
    assert decoded.cost == 80.0  # == toy best-known
    assert decoded.cost == inst.best_known

    ok, why = decoded.routes.covers(inst.spec)
    assert ok, why
    seqs = {r.vehicle_id: r.stop_ids for r in decoded.routes}
    assert seqs == {"v1": ("c2", "c3"), "v2": ("c4", "c5")}


def test_decoded_cost_matches_manual_route_walk():
    enc = toy_encoding()
    inst = parse_vrp(TOY)
    m = inst.matrix
    decoded = enc.decode_detailed(np.array([0.4, 0.1, 0.7, 0.2]))

    manual = 0.0
    for r in decoded.routes:
        nodes = [inst.depot_node]
        nodes += [int(s[1:]) for s in r.stop_ids]  # stop id "cN" -> node N
        nodes.append(inst.depot_node)
        manual += m.route_time(nodes)
    assert decoded.cost == pytest.approx(manual)


def test_every_random_decode_covers_all_stops():
    enc = toy_encoding()
    inst = parse_vrp(TOY)
    rng = np.random.default_rng(7)
    for _ in range(50):
        routes = enc.decode(enc.random(rng))
        ok, why = routes.covers(inst.spec)
        assert ok, why
        assert len(routes) == 2  # exactly k vehicle slots, some may be empty


def _spec_cap(cap, demands, k, coords=None):
    n = len(demands)
    coords = coords or [(i + 1, 0) for i in range(n)]
    stops = tuple(Stop(id=f"c{i}", node=i + 1, demand=d) for i, d in enumerate(demands))
    depot = Depot(id="depot", node=0)
    vehicles = tuple(Vehicle(id=f"v{i + 1}", capacity=cap, start_depot="depot") for i in range(k))
    spec = ProblemSpec(
        name="cap-test",
        depots=(depot,),
        stops=stops,
        vehicles=vehicles,
        constraints=ConstraintSet(),
    )
    xs = [0] + [c[0] for c in coords]
    ys = [0] + [c[1] for c in coords]
    matrix = euclidean_matrix_2d([0, *range(1, n + 1)], xs=xs, ys=ys)
    return spec, matrix


def test_infeasible_ordering_is_flagged_not_hidden():
    # cap 10, three stops of demand 6, only 2 vehicles: no valid split exists
    spec, matrix = _spec_cap(cap=10, demands=[6, 6, 6], k=2)
    enc = RandomKeyGiantTour(spec, matrix)
    decoded = enc.decode_detailed(np.array([0.1, 0.2, 0.3]))

    assert decoded.feasible is False
    ok, _ = decoded.routes.covers(spec)  # still visits every stop exactly once (FR-7)
    assert ok
    assert len(decoded.routes) == 2


def test_split_leaves_vehicles_idle_when_that_is_cheaper():
    # cap huge, 3 nearby stops, 3 vehicles -> one route is best (fewer depot trips)
    spec, matrix = _spec_cap(cap=1000, demands=[1, 1, 1], k=3, coords=[(1, 0), (2, 0), (3, 0)])
    enc = RandomKeyGiantTour(spec, matrix)
    decoded = enc.decode_detailed(np.array([0.1, 0.2, 0.3]))
    assert decoded.feasible is True
    non_empty = [r for r in decoded.routes if r.stop_ids]
    assert len(non_empty) == 1
    assert decoded.cost == 6.0  # 0->1->2->3->0 = 1+1+1+3


def test_key_validation():
    enc = toy_encoding()
    with pytest.raises(ValueError, match="expected 4 keys"):
        enc.decode(np.array([0.1, 0.2]))
    with pytest.raises(ValueError, match="non-finite"):
        enc.decode(np.array([0.1, np.nan, 0.3, 0.4]))


def test_makespan_objective_supported():
    inst = parse_vrp(TOY)
    spec = ProblemSpec(
        name=inst.spec.name,
        depots=inst.spec.depots,
        stops=inst.spec.stops,
        vehicles=inst.spec.vehicles,
        objective=Objective.MIN_MAKESPAN,
    )
    enc = RandomKeyGiantTour(spec, inst.matrix)
    decoded = enc.decode_detailed(np.array([0.1, 0.2, 0.3, 0.4]))
    assert decoded.feasible is True
    # In toy: v1 takes (c2, c3)=40.0, v2 takes (c4, c5)=40.0 -> max is 40.0
    assert decoded.cost == 40.0


def test_multi_depot_instances_supported():
    d1 = Depot("d1", 0)
    d2 = Depot("d2", 10)
    stops = (Stop("c1", node=1, demand=5.0), Stop("c2", node=9, demand=5.0))
    vehicles = (
        Vehicle("v1", capacity=10.0, start_depot="d1", end_depot="d1"),
        Vehicle("v2", capacity=10.0, start_depot="d2", end_depot="d2"),
    )
    spec = ProblemSpec(
        name="two-depot",
        depots=(d1, d2),
        stops=stops,
        vehicles=vehicles,
    )
    matrix = euclidean_matrix_2d([0, 1, 9, 10], [0, 1, 9, 10], [0, 0, 0, 0])
    enc = RandomKeyGiantTour(spec, matrix)
    decoded = enc.decode_detailed(np.array([0.1, 0.2]))
    assert decoded.feasible is True
    routes = tuple(decoded.routes)
    assert routes[0].vehicle_id == "v1"
    assert routes[0].stop_ids == ("c1",)
    assert routes[1].vehicle_id == "v2"
    assert routes[1].stop_ids == ("c2",)
    # v1: 0->1->0 = 2, v2: 10->9->10 = 2 -> total = 4
    assert decoded.cost == 4.0


def test_heterogeneous_fleet_supported():
    d1 = Depot("d1", 0)
    stops = (Stop("c1", node=1, demand=10.0), Stop("c2", node=2, demand=20.0))
    vehicles = (
        Vehicle("v1", capacity=15.0, start_depot="d1"),
        Vehicle("v2", capacity=25.0, start_depot="d1"),
    )
    spec = ProblemSpec(
        name="hetero",
        depots=(d1,),
        stops=stops,
        vehicles=vehicles,
    )
    matrix = euclidean_matrix_2d([0, 1, 2], [0, 1, 2], [0, 0, 0])
    enc = RandomKeyGiantTour(spec, matrix)
    decoded = enc.decode_detailed(np.array([0.1, 0.2]))
    assert decoded.feasible is True
    routes = tuple(decoded.routes)
    # v1 has cap 15 -> can only take c1 (demand 10)
    # v2 has cap 25 -> takes c2 (demand 20)
    assert routes[0].stop_ids == ("c1",)
    assert routes[1].stop_ids == ("c2",)


def test_invalid_depot_reference_raises():
    d1 = Depot("d1", 0)
    stops = (Stop("c1", node=1, demand=1.0),)
    vehicles = (Vehicle("v1", capacity=10.0, start_depot="unknown_depot"),)
    with pytest.raises(ValueError, match="unknown start_depot"):
        ProblemSpec("bad-depot", depots=(d1,), stops=stops, vehicles=vehicles)


def test_instance_arrays_are_read_only():
    enc = toy_encoding()
    with pytest.raises(ValueError):
        enc._demand[0] = 999.0
    with pytest.raises(ValueError):
        enc._stop_nodes[0] = 0


def test_missing_node_in_matrix_raises():
    spec, _ = _spec_cap(cap=10, demands=[1, 1], k=1)
    bad_matrix = euclidean_matrix_2d([0, 1], [0, 1], [0, 0])  # missing node 2
    with pytest.raises(ValueError, match="missing"):
        RandomKeyGiantTour(spec, bad_matrix)


def test_distance_objective_uses_distance_channel():
    spec, matrix = _spec_cap(cap=1000, demands=[1, 1], k=1, coords=[(3, 4), (6, 8)])
    spec = ProblemSpec(
        name=spec.name,
        depots=spec.depots,
        stops=spec.stops,
        vehicles=spec.vehicles,
        objective=Objective.MIN_DISTANCE,
    )
    enc = RandomKeyGiantTour(spec, matrix)
    decoded = enc.decode_detailed(np.array([0.1, 0.2]))
    # 0->(3,4)=5, (3,4)->(6,8)=5, (6,8)->0=10  => 20
    assert decoded.cost == 20.0

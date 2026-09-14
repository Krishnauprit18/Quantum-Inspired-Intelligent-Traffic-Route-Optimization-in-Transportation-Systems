"""Piece 4 tests: GreedyRepair fixes capacity, never loses a stop, tidies time windows."""

import numpy as np

from quantroute import (
    ConstraintSet,
    ConstraintValidator,
    Depot,
    GreedyRepair,
    ProblemSpec,
    RandomKeyGiantTour,
    RepairOperator,
    Route,
    Routes,
    Stop,
    Vehicle,
    euclidean_matrix_2d,
)


def build(*, demands, caps, coords, constraints=None):
    n = len(demands)
    stops = tuple(Stop(id=f"c{i}", node=i + 1, demand=demands[i]) for i in range(n))
    vehicles = tuple(Vehicle(id=f"v{j + 1}", capacity=caps[j], start_depot="depot") for j in range(len(caps)))
    spec = ProblemSpec(
        name="rp",
        depots=(Depot("depot", 0),),
        stops=stops,
        vehicles=vehicles,
        constraints=constraints or ConstraintSet(),
    )
    xs = [0.0] + [c[0] for c in coords]
    ys = [0.0] + [c[1] for c in coords]
    return spec, euclidean_matrix_2d([0, *range(1, n + 1)], xs=xs, ys=ys)


def loads(spec, matrix, routes):
    return [rm.load for rm in ConstraintValidator(spec, matrix).evaluate(routes).routes]


def test_is_repairoperator():
    spec, matrix = build(demands=[1], caps=[10], coords=[(1, 0)])
    assert isinstance(GreedyRepair(spec, matrix), RepairOperator)


def test_moves_stops_until_capacity_is_respected():
    spec, matrix = build(demands=[8, 8, 8, 8], caps=[20, 20], coords=[(1, 0), (2, 0), (3, 0), (4, 0)])
    broken = Routes.from_lists({"v1": ["c0", "c1", "c2", "c3"], "v2": []})
    fixed = GreedyRepair(spec, matrix).repair(broken)

    assert all(ld <= 20 + 1e-9 for ld in loads(spec, matrix, fixed))
    ok, why = fixed.covers(spec)
    assert ok, why


def test_repair_is_total_on_genuinely_infeasible_input():
    # 4 stops of demand 15, two vehicles of 20 -> no feasible assignment exists
    spec, matrix = build(demands=[15, 15, 15, 15], caps=[20, 20], coords=[(1, 0), (2, 0), (3, 0), (4, 0)])
    broken = Routes.from_lists({"v1": ["c0", "c1", "c2", "c3"], "v2": []})
    fixed = GreedyRepair(spec, matrix).repair(broken)  # must not raise
    ok, why = fixed.covers(spec)
    assert ok, why


def test_reassigns_stops_from_unknown_vehicle_route():
    spec, matrix = build(demands=[1, 1, 1], caps=[10, 10], coords=[(1, 0), (2, 0), (3, 0)])
    messy = Routes((Route("ghost", ("c0",)), Route("v1", ("c1",)), Route("v2", ("c2",))))
    fixed = GreedyRepair(spec, matrix).repair(messy)
    assert {r.vehicle_id for r in fixed} == {"v1", "v2"}
    ok, why = fixed.covers(spec)
    assert ok, why


def test_time_window_tidy_orders_by_due_date():
    spec, matrix = build(
        demands=[1, 1],
        caps=[10],
        coords=[(5, 0), (10, 0)],
        constraints=ConstraintSet(enforce_time_windows=True),
    )
    spec = ProblemSpec(
        name=spec.name,
        depots=spec.depots,
        stops=(
            Stop("c0", node=1, demand=1, tw_close_s=100.0),
            Stop("c1", node=2, demand=1, tw_close_s=10.0),
        ),
        vehicles=spec.vehicles,
        constraints=ConstraintSet(enforce_time_windows=True),
    )
    fixed = GreedyRepair(spec, matrix).repair(Routes.from_lists({"v1": ["c0", "c1"]}))
    assert next(iter(fixed)).stop_ids == ("c1", "c0")  # earlier due date first


def test_fuzz_repair_never_drops_or_duplicates():
    spec, matrix = build(
        demands=[6, 7, 5, 9, 8, 4],
        caps=[15, 15],  # tight: total 39 > 30, many decodes infeasible
        coords=[(1, 1), (2, 5), (5, 2), (4, 4), (6, 1), (3, 3)],
    )
    enc = RandomKeyGiantTour(spec, matrix)
    rep = GreedyRepair(spec, matrix)
    rng = np.random.default_rng(2024)
    for _ in range(40):
        routes = rep.repair(enc.decode(enc.random(rng)))
        ok, why = routes.covers(spec)
        assert ok, why


def test_repair_leaves_feasible_solution_untouched():
    spec, matrix = build(demands=[10, 10, 10, 10], caps=[30, 30], coords=[(10, 0), (20, 0), (0, 10), (0, 20)])
    good = Routes.from_lists({"v1": ["c0", "c1"], "v2": ["c2", "c3"]})
    fixed = GreedyRepair(spec, matrix).repair(good)
    assert {r.vehicle_id: r.stop_ids for r in fixed} == {"v1": ("c0", "c1"), "v2": ("c2", "c3")}

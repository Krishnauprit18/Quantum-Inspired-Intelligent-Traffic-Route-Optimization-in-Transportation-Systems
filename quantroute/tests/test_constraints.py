"""Piece 4 tests: ConstraintValidator measures routes and flags every breach."""

import pytest

from quantroute import (
    ConstraintSet,
    ConstraintValidator,
    Depot,
    ProblemSpec,
    Route,
    Routes,
    Stop,
    Vehicle,
    euclidean_matrix_2d,
)


def build(*, demands, caps, coords, constraints=None):
    """depot at origin (node 0); stop i -> node i+1 at coords[i]."""
    n = len(demands)
    stops = tuple(Stop(id=f"c{i}", node=i + 1, demand=demands[i]) for i in range(n))
    depot = Depot(id="depot", node=0)
    vehicles = tuple(
        Vehicle(id=f"v{j + 1}", capacity=caps[j], start_depot="depot") for j in range(len(caps))
    )
    spec = ProblemSpec(
        name="cv",
        depots=(depot,),
        stops=stops,
        vehicles=vehicles,
        constraints=constraints or ConstraintSet(),
    )
    xs = [0.0] + [c[0] for c in coords]
    ys = [0.0] + [c[1] for c in coords]
    matrix = euclidean_matrix_2d([0, *range(1, n + 1)], xs=xs, ys=ys)
    return spec, matrix


def test_feasible_solution_measured_cleanly():
    spec, matrix = build(demands=[10, 10, 10, 10], caps=[30, 30], coords=[(10, 0), (20, 0), (0, 10), (0, 20)])
    v = ConstraintValidator(spec, matrix)
    m = v.evaluate(Routes.from_lists({"v1": ["c0", "c1"], "v2": ["c2", "c3"]}))

    assert m.is_feasible
    assert m.violations == ()
    assert m.total_travel_time_s == 80.0
    assert m.vehicles_used == 2
    assert m.makespan_s == 40.0  # each route: 0->10->20->0 = 40, no service time
    assert m.unassigned == () and m.duplicates == ()


def test_capacity_overflow_flagged_with_amount():
    spec, matrix = build(demands=[10, 10], caps=[15, 15], coords=[(10, 0), (20, 0)])
    m = ConstraintValidator(spec, matrix).evaluate(Routes.from_lists({"v1": ["c0", "c1"], "v2": []}))
    assert not m.is_feasible
    cap = [x for x in m.violations if x.kind == "capacity"]
    assert len(cap) == 1 and cap[0].amount == 5.0 and cap[0].vehicle_id == "v1"
    assert m.total_capacity_overflow == 5.0


def test_time_window_lateness_flagged():
    spec, matrix = build(demands=[1], caps=[10], coords=[(10, 0)])
    spec = ProblemSpec(
        name=spec.name,
        depots=spec.depots,
        stops=(Stop("c0", node=1, demand=1, tw_close_s=5.0),),
        vehicles=spec.vehicles,
        constraints=ConstraintSet(enforce_time_windows=True),
    )
    m = ConstraintValidator(spec, matrix).evaluate(Routes.from_lists({"v1": ["c0"]}))
    tw = [x for x in m.violations if x.kind == "time_window"]
    assert len(tw) == 1 and tw[0].amount == 5.0  # arrive at 10, due at 5
    assert m.total_lateness_s == 5.0


def test_no_time_window_means_no_lateness():
    spec, matrix = build(demands=[1], caps=[10], coords=[(10, 0)])
    m = ConstraintValidator(spec, matrix).evaluate(Routes.from_lists({"v1": ["c0"]}))
    assert m.total_lateness_s == 0.0 and m.is_feasible


def test_windows_ignored_entirely_when_not_enforced():
    spec, matrix = build(demands=[1], caps=[10], coords=[(10, 0)])
    spec = ProblemSpec(
        name=spec.name,
        depots=spec.depots,
        stops=(Stop("c0", node=1, demand=1, tw_close_s=1.0),),  # would be very late
        vehicles=spec.vehicles,
        constraints=ConstraintSet(enforce_time_windows=False),
    )
    m = ConstraintValidator(spec, matrix).evaluate(Routes.from_lists({"v1": ["c0"]}))
    assert m.total_lateness_s == 0.0
    assert not any(x.kind == "time_window" for x in m.violations)
    assert m.is_feasible


def test_duration_limit_and_shift_overrun():
    spec, matrix = build(
        demands=[1, 1],
        caps=[10, 10],
        coords=[(10, 0), (20, 0)],
        constraints=ConstraintSet(max_route_seconds=5.0),
    )
    m = ConstraintValidator(spec, matrix).evaluate(Routes.from_lists({"v1": ["c0", "c1"], "v2": []}))
    dur = [x for x in m.violations if x.kind == "duration"]
    assert len(dur) == 1
    assert dur[0].amount == pytest.approx(35.0)  # route lasts 40s, limit 5s

    spec2 = ProblemSpec(
        name="shift",
        depots=spec.depots,
        stops=spec.stops,
        vehicles=(Vehicle("v1", capacity=10, start_depot="depot", shift_end_s=5.0),),
    )
    m2 = ConstraintValidator(spec2, matrix).evaluate(Routes.from_lists({"v1": ["c0", "c1"]}))
    assert any(x.kind == "duration" for x in m2.violations)


def test_unassigned_and_duplicate_stops():
    spec, matrix = build(demands=[1, 1, 1], caps=[10, 10], coords=[(1, 0), (2, 0), (3, 0)])
    v = ConstraintValidator(spec, matrix)

    missing = v.evaluate(Routes.from_lists({"v1": ["c0", "c1"], "v2": []}))
    assert missing.unassigned == ("c2",)
    assert any(x.kind == "unassigned" for x in missing.violations)
    assert not missing.is_feasible

    dupe = v.evaluate(Routes.from_lists({"v1": ["c0", "c1"], "v2": ["c1", "c2"]}))
    assert dupe.duplicates == ("c1",)
    assert any(x.kind == "duplicate" for x in dupe.violations)


def test_unknown_vehicle_and_stop():
    spec, matrix = build(demands=[1, 1], caps=[10], coords=[(1, 0), (2, 0)])
    v = ConstraintValidator(spec, matrix)

    m = v.evaluate(Routes((Route("ghost", ("c0",)), Route("v1", ("c1",)))))
    assert any(x.kind == "unknown_vehicle" and x.vehicle_id == "ghost" for x in m.violations)

    m2 = v.evaluate(Routes((Route("v1", ("c0", "zzz")),)))
    assert any(x.kind == "unknown_stop" for x in m2.violations)
    assert m2.unassigned == ("c1",)  # zzz doesn't satisfy c1


def test_missing_matrix_node_raises():
    spec, _ = build(demands=[1, 1], caps=[10], coords=[(1, 0), (2, 0)])
    thin = euclidean_matrix_2d([0, 1], [0, 1], [0, 0])  # node 2 absent
    with pytest.raises(ValueError, match="missing"):
        ConstraintValidator(spec, thin)

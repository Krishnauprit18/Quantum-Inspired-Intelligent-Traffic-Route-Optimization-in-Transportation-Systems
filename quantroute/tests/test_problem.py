"""Piece 1 tests: the domain model validates instances and rejects bad ones."""

import math

import pytest

from quantroute import (
    ConstraintSet,
    Depot,
    Objective,
    ProblemSpec,
    Route,
    Routes,
    Stop,
    Vehicle,
)


def make_spec(**overrides) -> ProblemSpec:
    kw = dict(
        name="toy",
        depots=(Depot("d1", node=0),),
        stops=(
            Stop("s1", node=1, demand=5),
            Stop("s2", node=2, demand=7),
            Stop("s3", node=3, demand=4),
        ),
        vehicles=(Vehicle("v1", capacity=20, start_depot="d1"),),
    )
    kw.update(overrides)
    return ProblemSpec(**kw)


def test_valid_instance_has_expected_shape():
    spec = make_spec()
    assert spec.dimension() == 3
    assert spec.total_demand == 16
    assert spec.total_capacity == 20
    assert spec.stop_index() == {"s1": 0, "s2": 1, "s3": 2}
    assert spec.objective is Objective.MIN_TRAVEL_TIME
    assert spec.depot_by_id("d1").node == 0


def test_stop_time_window_defaults_and_validation():
    s = Stop("x", node=9)
    assert s.tw_open_s == 0.0 and math.isinf(s.tw_close_s)
    assert not s.has_time_window
    assert Stop("y", node=9, tw_open_s=10, tw_close_s=20).has_time_window
    with pytest.raises(ValueError):
        Stop("bad", node=9, tw_open_s=30, tw_close_s=10)


def test_negative_demand_and_bad_capacity_rejected():
    with pytest.raises(ValueError):
        Stop("s", node=1, demand=-1)
    with pytest.raises(ValueError):
        Vehicle("v", capacity=0, start_depot="d1")


def test_vehicle_unknown_depot_rejected():
    with pytest.raises(ValueError):
        make_spec(vehicles=(Vehicle("v1", capacity=20, start_depot="nope"),))


def test_duplicate_stop_ids_rejected():
    with pytest.raises(ValueError):
        make_spec(
            stops=(
                Stop("s1", node=1, demand=1),
                Stop("s1", node=2, demand=1),
            )
        )


def test_trivial_infeasibility_detected():
    over = make_spec(vehicles=(Vehicle("v1", capacity=10, start_depot="d1"),))
    flag, why = over.is_trivially_infeasible()
    assert flag and "exceeds fleet capacity" in why

    # enough total capacity, but one stop is bigger than any single vehicle
    big_stop = make_spec(
        stops=(Stop("s1", node=1, demand=900),),
        vehicles=(
            Vehicle("v1", capacity=600, start_depot="d1"),
            Vehicle("v2", capacity=600, start_depot="d1"),
        ),
    )
    flag, why = big_stop.is_trivially_infeasible()
    assert flag and "largest vehicle" in why


def test_effective_end_depot_falls_back_to_start():
    assert Vehicle("v", capacity=1, start_depot="d1").effective_end_depot == "d1"
    assert Vehicle("v", capacity=1, start_depot="d1", end_depot="d2").effective_end_depot == "d2"


def test_routes_coverage_check():
    spec = make_spec()
    ok = Routes.from_lists({"v1": ["s1", "s2", "s3"]})
    assert ok.covers(spec) == (True, "")
    assert ok.vehicles_used == 1

    missing = Routes.from_lists({"v1": ["s1", "s2"]})
    good, why = missing.covers(spec)
    assert not good and "never visited" in why

    dupe = Routes((Route("v1", ("s1", "s1", "s2", "s3")),))
    good, why = dupe.covers(spec)
    assert not good and "more than once" in why


def test_non_positive_time_budget_rejected():
    with pytest.raises(ValueError, match="time_budget_ms"):
        make_spec(time_budget_ms=0)
    with pytest.raises(ValueError, match="time_budget_ms"):
        make_spec(time_budget_ms=-5)


def test_constraint_set_defaults():
    c = ConstraintSet()
    assert c.max_route_seconds is None
    assert c.enforce_time_windows is True
    assert c.allow_open_routes is False

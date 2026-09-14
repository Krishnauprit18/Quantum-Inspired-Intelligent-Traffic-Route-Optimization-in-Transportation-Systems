"""Piece 4 tests: FitnessEvaluator prices decode -> repair -> measure."""

from pathlib import Path

import numpy as np
import pytest

from quantroute import (
    ConstraintSet,
    Depot,
    FitnessEvaluator,
    GreedyRepair,
    Objective,
    PenaltyWeights,
    ProblemSpec,
    RandomKeyGiantTour,
    Stop,
    Vehicle,
    euclidean_matrix_2d,
)
from quantroute.io import parse_vrp

TOY = Path(__file__).parent.parent / "data" / "instances" / "toy-n5-k2.vrp"


def toy_eval(**kw):
    inst = parse_vrp(TOY)
    enc = RandomKeyGiantTour(inst.spec, inst.matrix)
    return FitnessEvaluator(inst.spec, inst.matrix, enc, **kw), enc


def test_optimal_decode_scores_base_only():
    ev, _ = toy_eval()
    r = ev.evaluate_one(np.array([0.1, 0.2, 0.3, 0.4]))
    assert r.base_cost == 80.0
    assert r.penalty == 0.0
    assert r.fitness == 80.0
    assert r.feasible is True


def test_cost_batch_shape_and_dtype():
    ev, enc = toy_eval()
    rng = np.random.default_rng(0)
    vs = [enc.random(rng) for _ in range(5)]
    out = ev.cost_batch(vs)
    assert out.shape == (5,)
    assert out.dtype == np.float64
    assert np.all(out >= 80.0)  # 80 is the optimum; nothing can be cheaper


def _infeasible_capacity_case():
    # cap 10, three stops demand 6, k=2 -> split folds into an over-capacity route
    stops = tuple(Stop(f"c{i}", node=i + 1, demand=6) for i in range(3))
    spec = ProblemSpec(
        name="inf",
        depots=(Depot("depot", 0),),
        stops=stops,
        vehicles=(Vehicle("v1", 10, "depot"), Vehicle("v2", 10, "depot")),
        constraints=ConstraintSet(),
    )
    matrix = euclidean_matrix_2d([0, 1, 2, 3], xs=[0, 1, 2, 3], ys=[0, 0, 0, 0])
    return spec, matrix


def test_penalty_scale_ramps_soft_terms_only():
    spec, matrix = _infeasible_capacity_case()
    enc = RandomKeyGiantTour(spec, matrix)
    ev = FitnessEvaluator(spec, matrix, enc)
    v = np.array([0.1, 0.2, 0.3])

    r0 = ev.evaluate_one(v, penalty_scale=0.0)
    r1 = ev.evaluate_one(v, penalty_scale=1.0)
    r2 = ev.evaluate_one(v, penalty_scale=2.0)

    assert r0.penalty == 0.0  # soft penalty scaled away, all stops still covered
    assert r0.fitness == r0.base_cost
    assert r2.penalty > r1.penalty > 0.0
    assert not r1.feasible


def test_repair_removes_penalty_when_a_fix_exists():
    # cap 20, four stops of 8, k=2: a bad vector can overload one route, repair rebalances
    stops = tuple(Stop(f"c{i}", node=i + 1, demand=8) for i in range(4))
    spec = ProblemSpec(
        name="fixable",
        depots=(Depot("depot", 0),),
        stops=stops,
        vehicles=(Vehicle("v1", 20, "depot"), Vehicle("v2", 20, "depot")),
    )
    matrix = euclidean_matrix_2d([0, 1, 2, 3, 4], xs=[0, 1, 2, 3, 4], ys=[0, 0, 0, 0, 0])
    enc = RandomKeyGiantTour(spec, matrix)
    v = np.array([0.9, 0.1, 0.2, 0.3])  # some ordering

    no_repair = FitnessEvaluator(spec, matrix, enc)
    with_repair = FitnessEvaluator(spec, matrix, enc, repair=GreedyRepair(spec, matrix))

    a = with_repair.evaluate_one(v)
    b = no_repair.evaluate_one(v)
    assert a.feasible
    assert a.fitness <= b.fitness


def test_distance_objective_selected():
    inst = parse_vrp(TOY)
    spec = ProblemSpec(
        name=inst.spec.name,
        depots=inst.spec.depots,
        stops=inst.spec.stops,
        vehicles=inst.spec.vehicles,
        objective=Objective.MIN_DISTANCE,
    )
    enc = RandomKeyGiantTour(spec, inst.matrix)
    ev = FitnessEvaluator(spec, inst.matrix, enc)
    assert ev.evaluate_one(np.array([0.1, 0.2, 0.3, 0.4])).base_cost == 80.0


def test_penalty_weights_validation():
    with pytest.raises(ValueError):
        PenaltyWeights(capacity=-1.0)
    with pytest.raises(ValueError):
        PenaltyWeights().ramped(-0.5)
    ramped = PenaltyWeights(capacity=10, time_window=2, duration=3, unassigned=999).ramped(2.0)
    assert (ramped.capacity, ramped.time_window, ramped.duration) == (20, 4, 6)
    assert ramped.unassigned == 999  # structural weight is not ramped

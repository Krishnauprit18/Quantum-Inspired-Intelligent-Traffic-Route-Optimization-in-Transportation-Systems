"""Piece 7 tests: the OR-Tools baseline (skipped when OR-Tools is not installed)."""

from pathlib import Path

import numpy as np
import pytest

from quantroute import (
    ConstraintSet,
    Depot,
    FitnessEvaluator,
    GreedyRepair,
    ProblemSpec,
    RandomKeyGiantTour,
    SearchProblem,
    Stop,
    TerminationCriteria,
    Vehicle,
    euclidean_matrix_2d,
)
from quantroute.io import load_cvrplib
from quantroute.optimizers.ortools_solver import HAS_ORTOOLS, ORToolsConfig, ORToolsOptimizer

TOY = Path(__file__).parent.parent / "data" / "instances" / "toy-n5-k2.vrp"


def toy_problem() -> SearchProblem:
    inst, _ = load_cvrplib(TOY)
    enc = RandomKeyGiantTour(inst.spec, inst.matrix)
    ev = FitnessEvaluator(inst.spec, inst.matrix, enc, repair=GreedyRepair(inst.spec, inst.matrix))
    return SearchProblem(inst.spec, inst.matrix, enc, ev, best_known=inst.best_known)


def test_config_validation():
    with pytest.raises(ValueError):
        ORToolsConfig(first_solution="NONSENSE")
    with pytest.raises(ValueError):
        ORToolsConfig(metaheuristic="NONSENSE")
    with pytest.raises(ValueError):
        ORToolsConfig(cost_scale=0)
    with pytest.raises(ValueError):
        ORToolsConfig(time_limit_s=0)


@pytest.mark.skipif(HAS_ORTOOLS, reason="OR-Tools is installed")
def test_missing_ortools_gives_a_clear_error():
    with pytest.raises(ImportError, match="pip install"):
        ORToolsOptimizer().solve(toy_problem(), termination=TerminationCriteria(max_iterations=1))


@pytest.mark.skipif(not HAS_ORTOOLS, reason="OR-Tools not installed")
def test_ortools_solves_toy_optimally():
    res = ORToolsOptimizer(ORToolsConfig(time_limit_s=2.0)).solve(toy_problem())
    assert res.algorithm == "ortools"
    assert res.feasible
    assert res.best_cost == 80.0  # small instance -> OR-Tools finds the optimum
    ok, why = res.routes.covers(toy_problem().spec)
    assert ok, why
    # the reconstructed random-key vector must decode back to a full cover
    enc = toy_problem().encoding
    rk_ok, _ = enc.decode(res.best_vector).covers(toy_problem().spec)
    assert rk_ok


@pytest.mark.skipif(not HAS_ORTOOLS, reason="OR-Tools not installed")
def test_ortools_time_window_instance_is_rejected():
    inst, _ = load_cvrplib(TOY)
    spec = ProblemSpec(
        name=inst.spec.name,
        depots=inst.spec.depots,
        stops=(Stop("c2", node=2, demand=10, tw_close_s=5.0),) + inst.spec.stops[1:],
        vehicles=inst.spec.vehicles,
        constraints=ConstraintSet(enforce_time_windows=True),
    )
    enc = RandomKeyGiantTour(spec, inst.matrix)
    ev = FitnessEvaluator(spec, inst.matrix, enc)
    with pytest.raises(NotImplementedError, match="time windows"):
        ORToolsOptimizer().solve(SearchProblem(spec, inst.matrix, enc, ev))


@pytest.mark.skipif(not HAS_ORTOOLS, reason="OR-Tools not installed")
def test_ortools_via_factory():
    from quantroute import OptimizerFactory

    opt = OptimizerFactory.from_config({"algorithm": "ortools", "params": {"time_limit_s": 1.0}})
    res = opt.solve(toy_problem())
    assert res.feasible and res.best_cost == 80.0


@pytest.mark.skipif(not HAS_ORTOOLS, reason="OR-Tools not installed")
def test_ortools_reports_a_real_convergence_trace():
    res = ORToolsOptimizer(ORToolsConfig(time_limit_s=2.0)).solve(toy_problem())
    assert len(res.convergence) >= 1
    assert res.iterations == len(res.convergence)
    costs = [rec.incumbent_cost for rec in res.convergence]
    assert costs == sorted(costs, reverse=True)  # improving (non-increasing)
    assert res.convergence[-1].incumbent_cost == res.best_cost  # last point re-scored
    assert res.convergence[-1].elapsed_s <= res.elapsed_s + 1e-6

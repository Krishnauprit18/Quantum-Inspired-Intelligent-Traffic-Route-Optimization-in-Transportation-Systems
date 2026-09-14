"""Piece 11 tests: the GA and ACO baselines (shared driver, random-key encoding)."""

from pathlib import Path

import numpy as np
import pytest

from quantroute import (
    ACOConfig,
    ACOOptimizer,
    FitnessEvaluator,
    GAConfig,
    GAOptimizer,
    GreedyRepair,
    Optimizer,
    OptimizerFactory,
    RandomKeyGiantTour,
    SearchProblem,
    TerminationCriteria,
)
from quantroute.io import load_cvrplib

TOY = Path(__file__).parent.parent / "data" / "instances" / "toy-n5-k2.vrp"


def toy_problem() -> SearchProblem:
    inst, _ = load_cvrplib(TOY)
    enc = RandomKeyGiantTour(inst.spec, inst.matrix)
    ev = FitnessEvaluator(inst.spec, inst.matrix, enc, repair=GreedyRepair(inst.spec, inst.matrix))
    return SearchProblem(inst.spec, inst.matrix, enc, ev, best_known=inst.best_known)


# -- GA -------------------------------------------------------------


def test_ga_solves_toy_to_optimum():
    opt = GAOptimizer(GAConfig(population_size=30, max_iterations=120, seed=1))
    res = opt.solve(toy_problem(), termination=TerminationCriteria(max_iterations=120))
    assert isinstance(opt, Optimizer)
    assert res.algorithm == "ga"
    assert res.feasible and res.best_cost == 80.0
    ok, why = res.routes.covers(toy_problem().spec)
    assert ok, why


def test_ga_is_deterministic_and_monotone():
    term = TerminationCriteria(max_iterations=60)
    a = GAOptimizer(GAConfig(population_size=20, max_iterations=60, seed=7)).solve(toy_problem(), termination=term)
    b = GAOptimizer(GAConfig(population_size=20, max_iterations=60, seed=7)).solve(toy_problem(), termination=term)
    assert np.array_equal(a.best_vector, b.best_vector)
    assert [r.incumbent_cost for r in a.convergence] == [r.incumbent_cost for r in b.convergence]
    costs = [r.incumbent_cost for r in a.convergence]
    assert costs == sorted(costs, reverse=True)


def test_ga_config_validation():
    with pytest.raises(ValueError):
        GAConfig(population_size=3)
    with pytest.raises(ValueError):
        GAConfig(tournament_size=1)
    with pytest.raises(ValueError):
        GAConfig(elite_fraction=0.95)
    with pytest.raises(ValueError):
        GAConfig(mutation_sigma=0.0)


# -- ACO ----------------------------------------------------------


def test_aco_solves_toy_to_optimum():
    opt = ACOOptimizer(ACOConfig(n_ants=20, max_iterations=100, seed=1))
    res = opt.solve(toy_problem(), termination=TerminationCriteria(max_iterations=100))
    assert res.algorithm == "aco"
    assert res.feasible and res.best_cost == 80.0
    ok, why = res.routes.covers(toy_problem().spec)
    assert ok, why


def test_aco_is_deterministic_and_monotone():
    term = TerminationCriteria(max_iterations=60)
    a = ACOOptimizer(ACOConfig(n_ants=16, max_iterations=60, seed=5)).solve(toy_problem(), termination=term)
    b = ACOOptimizer(ACOConfig(n_ants=16, max_iterations=60, seed=5)).solve(toy_problem(), termination=term)
    assert np.array_equal(a.best_vector, b.best_vector)
    costs = [r.incumbent_cost for r in a.convergence]
    assert costs == sorted(costs, reverse=True)


def test_aco_tours_are_valid_permutations():
    opt = ACOOptimizer(ACOConfig(n_ants=8, max_iterations=5, seed=2))
    pop = opt._build_population(np.random.default_rng(2), toy_problem(), None)
    pop.advance(np.random.default_rng(3), 1, 5)
    x = pop.positions
    for row in x:
        order = np.argsort(row)
        assert sorted(order.tolist()) == list(range(len(row)))  # every customer once
        assert np.all((row >= 0.0) & (row <= 1.0))


def test_aco_config_validation():
    with pytest.raises(ValueError):
        ACOConfig(n_ants=1)
    with pytest.raises(ValueError):
        ACOConfig(evaporation=0.0)
    with pytest.raises(ValueError):
        ACOConfig(tau_min=5.0, tau_max=1.0)
    with pytest.raises(ValueError):
        ACOConfig(alpha=-1.0)


# -- factory --------------------------------------------------


def test_factory_knows_all_six_strategies():
    assert set(OptimizerFactory.available()) == {"qpso", "qgpso", "pso", "ga", "aco", "ortools"}


def test_ga_and_aco_via_factory():
    for algo, size_key in (("ga", "population_size"), ("aco", "n_ants")):
        opt = OptimizerFactory.from_config(
            {"algorithm": algo, "params": {size_key: 16, "max_iterations": 60, "seed": 1}}
        )
        res = opt.solve(toy_problem(), termination=TerminationCriteria(max_iterations=60))
        assert res.feasible and res.best_cost == 80.0

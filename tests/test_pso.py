"""Piece 6 tests: the classic PSO baseline over the shared driver."""

from pathlib import Path

import numpy as np
import pytest

from quantroute import (
    CollectingCallback,
    FitnessEvaluator,
    GreedyRepair,
    Optimizer,
    PSOConfig,
    PSOOptimizer,
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


def test_pso_solves_toy_to_optimum():
    opt = PSOOptimizer(PSOConfig(swarm_size=24, max_iterations=150, seed=1))
    res = opt.solve(toy_problem(), termination=TerminationCriteria(max_iterations=150))
    assert isinstance(opt, Optimizer)
    assert res.algorithm == "pso"
    assert res.feasible
    assert res.best_cost == 80.0
    ok, why = res.routes.covers(toy_problem().spec)
    assert ok, why


def test_pso_is_deterministic_for_a_seed():
    term = TerminationCriteria(max_iterations=60)
    a = PSOOptimizer(PSOConfig(swarm_size=16, max_iterations=60, seed=5)).solve(
        toy_problem(), termination=term
    )
    b = PSOOptimizer(PSOConfig(swarm_size=16, max_iterations=60, seed=5)).solve(
        toy_problem(), termination=term
    )
    assert np.array_equal(a.best_vector, b.best_vector)
    assert [r.incumbent_cost for r in a.convergence] == [r.incumbent_cost for r in b.convergence]
    assert a.config_hash == b.config_hash


def test_pso_and_qpso_config_hashes_differ():
    from quantroute import QPSOConfig, QPSOOptimizer

    p = toy_problem()
    term = TerminationCriteria(max_iterations=10)
    pso_h = PSOOptimizer(PSOConfig(seed=1)).solve(p, termination=term).config_hash
    qpso_h = QPSOOptimizer(QPSOConfig(seed=1)).solve(p, termination=term).config_hash
    assert pso_h != qpso_h  # algorithm name is part of the hash


def test_pso_anytime_incumbent_is_monotone():
    cb = CollectingCallback()
    PSOOptimizer(PSOConfig(swarm_size=12, max_iterations=60, seed=3, publish_every=10)).solve(
        toy_problem(), callback=cb, termination=TerminationCriteria(max_iterations=60)
    )
    costs = [c for _, c, _ in cb.records]
    assert costs == sorted(costs, reverse=True)


def test_pso_time_budget_and_stagnation():
    res_t = PSOOptimizer(PSOConfig(swarm_size=8, max_iterations=10_000_000)).solve(
        toy_problem(),
        termination=TerminationCriteria(max_iterations=10_000_000, time_budget_s=0.05),
    )
    assert res_t.stop_reason == "time_budget"

    bare = toy_problem()
    bare = SearchProblem(bare.spec, bare.matrix, bare.encoding, bare.evaluator)  # no best_known
    res_s = PSOOptimizer(PSOConfig(swarm_size=20, max_iterations=5000, seed=2)).solve(
        bare, termination=TerminationCriteria(max_iterations=5000, stagnation_iterations=20)
    )
    assert res_s.stop_reason == "stagnation"


def test_pso_config_validation():
    with pytest.raises(ValueError):
        PSOConfig(swarm_size=1)
    with pytest.raises(ValueError):
        PSOConfig(inertia_min=0.9, inertia_max=0.4)
    with pytest.raises(ValueError):
        PSOConfig(velocity_clamp_fraction=0.0)
    with pytest.raises(ValueError):
        PSOConfig(cognitive=-1.0)


def test_pso_warm_start():
    res = PSOOptimizer(
        PSOConfig(swarm_size=10, max_iterations=3, seed=0, warm_start_fraction=0.5)
    ).solve(
        toy_problem(),
        warm_start=np.array([0.1, 0.2, 0.3, 0.4]),
        termination=TerminationCriteria(max_iterations=3),
    )
    assert res.feasible and res.best_cost == 80.0

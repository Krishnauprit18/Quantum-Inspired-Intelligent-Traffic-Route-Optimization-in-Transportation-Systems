"""Piece 5 tests: Swarm mechanics, the QPSO update rule, termination, determinism."""

from pathlib import Path

import numpy as np
import pytest

from quantroute import (
    CollectingCallback,
    FitnessEvaluator,
    GreedyRepair,
    Optimizer,
    QPSOConfig,
    QPSOOptimizer,
    RandomKeyGiantTour,
    SearchProblem,
    Swarm,
    TerminationCriteria,
)
from quantroute.io import load_cvrplib

TOY = Path(__file__).parent.parent / "data" / "instances" / "toy-n5-k2.vrp"


def toy_problem(**ev_kw) -> SearchProblem:
    inst, sol = load_cvrplib(TOY)
    enc = RandomKeyGiantTour(inst.spec, inst.matrix)
    ev = FitnessEvaluator(inst.spec, inst.matrix, enc, repair=GreedyRepair(inst.spec, inst.matrix), **ev_kw)
    return SearchProblem(inst.spec, inst.matrix, enc, ev, best_known=inst.best_known)


# -- Swarm --------------------------------------------------------------


def test_swarm_updates_personal_and_global_bests():
    s = Swarm(np.array([[0.1, 0.2], [0.9, 0.8], [0.5, 0.5]]))
    s.update_bests(np.array([3.0, 1.0, 2.0]))
    assert s.gbest_cost == 1.0
    assert np.array_equal(s.gbest, [0.9, 0.8])

    s.set_positions(np.array([[0.0, 0.0], [0.7, 0.7], [0.4, 0.4]]))
    s.update_bests(np.array([0.5, 5.0, 2.5]))  # only particle 0 improves
    assert s.gbest_cost == 0.5
    assert np.array_equal(s.gbest, [0.0, 0.0])


def test_swarm_mbest_is_mean_of_personal_bests():
    s = Swarm(np.array([[0.0, 0.0], [1.0, 1.0]]))
    s.update_bests(np.array([1.0, 2.0]))
    assert np.allclose(s.mbest(), [0.5, 0.5])


def test_swarm_rejects_bad_shapes():
    with pytest.raises(ValueError):
        Swarm(np.zeros(4))  # not 2-D
    s = Swarm(np.zeros((3, 2)))
    with pytest.raises(ValueError):
        s.update_bests(np.zeros(2))


def test_swarm_state_is_not_mutable_through_properties():
    s = Swarm(np.array([[0.1, 0.2], [0.3, 0.4]]))
    s.update_bests(np.array([1.0, 2.0]))
    for view in (s.positions, s.pbest, s.gbest):
        with pytest.raises(ValueError):
            view[0] = 9.0


# -- QPSO solve -------------------------------------------------------


def test_solves_toy_to_optimum():
    opt = QPSOOptimizer(QPSOConfig(swarm_size=24, max_iterations=120, seed=1))
    res = opt.solve(
        toy_problem(),
        termination=TerminationCriteria(max_iterations=120),
    )
    assert isinstance(opt, Optimizer)
    assert res.algorithm == "qpso"
    assert res.feasible
    assert res.best_cost == 80.0  # global optimum of the toy instance
    ok, why = res.routes.covers(toy_problem().spec)
    assert ok, why
    assert res.convergence[-1].incumbent_cost == 80.0
    assert res.convergence[0].iteration == 0


def test_run_is_deterministic_for_a_seed():
    term = TerminationCriteria(max_iterations=60)
    a = QPSOOptimizer(QPSOConfig(swarm_size=16, max_iterations=60, seed=7)).solve(toy_problem(), termination=term)
    b = QPSOOptimizer(QPSOConfig(swarm_size=16, max_iterations=60, seed=7)).solve(toy_problem(), termination=term)
    assert np.array_equal(a.best_vector, b.best_vector)
    assert a.best_cost == b.best_cost
    assert [r.incumbent_cost for r in a.convergence] == [r.incumbent_cost for r in b.convergence]
    assert a.config_hash == b.config_hash


def test_different_seed_changes_config_hash():
    p = toy_problem()
    term = TerminationCriteria(max_iterations=10)
    h1 = QPSOOptimizer(QPSOConfig(seed=1)).solve(p, termination=term).config_hash
    h2 = QPSOOptimizer(QPSOConfig(seed=2)).solve(p, termination=term).config_hash
    assert h1 != h2


def test_anytime_callback_receives_incumbents():
    cb = CollectingCallback()
    QPSOOptimizer(QPSOConfig(swarm_size=12, max_iterations=50, seed=3, publish_every=10)).solve(
        toy_problem(), callback=cb, termination=TerminationCriteria(max_iterations=50)
    )
    iters = [it for it, _, _ in cb.records]
    assert iters[0] == 0  # forced publish of the initial incumbent
    assert 10 in iters and 50 in iters
    costs = [c for _, c, _ in cb.records]
    assert costs == sorted(costs, reverse=True)  # incumbent never gets worse


def test_time_budget_stops_the_run():
    res = QPSOOptimizer(QPSOConfig(swarm_size=8, max_iterations=10_000_000, seed=0)).solve(
        toy_problem(),
        termination=TerminationCriteria(max_iterations=10_000_000, time_budget_s=0.05),
    )
    assert res.stop_reason == "time_budget"
    assert res.elapsed_s >= 0.05
    assert res.iterations < 10_000_000


def test_target_gap_stops_the_run():
    res = QPSOOptimizer(QPSOConfig(swarm_size=24, max_iterations=500, seed=1)).solve(
        toy_problem(),
        termination=TerminationCriteria(max_iterations=500, target_gap=0.0),
    )
    assert res.stop_reason == "target_gap"
    assert res.best_cost == 80.0


def test_stagnation_stops_the_run():
    res = QPSOOptimizer(QPSOConfig(swarm_size=24, max_iterations=5000, seed=2)).solve(
        # no best_known -> target_gap cannot fire; stagnation must
        SearchProblem(toy_problem().spec, toy_problem().matrix, toy_problem().encoding, toy_problem().evaluator),
        termination=TerminationCriteria(max_iterations=5000, stagnation_iterations=15),
    )
    assert res.stop_reason == "stagnation"
    assert res.iterations < 5000


def test_warm_start_shape_is_validated():
    opt = QPSOOptimizer(QPSOConfig(swarm_size=8, max_iterations=5))
    with pytest.raises(ValueError, match="warm_start must have shape"):
        opt.solve(toy_problem(), warm_start=np.zeros(3))


def test_warm_start_seeds_the_swarm():
    p = toy_problem()
    # a vector whose giant tour is (c2, c3, c4, c5) -> the optimal split
    good = np.array([0.1, 0.2, 0.3, 0.4])
    res = QPSOOptimizer(QPSOConfig(swarm_size=10, max_iterations=3, seed=0, warm_start_fraction=0.5)).solve(
        p, warm_start=good, termination=TerminationCriteria(max_iterations=3)
    )
    assert res.feasible and res.best_cost == 80.0  # found almost immediately


def test_config_validation():
    with pytest.raises(ValueError):
        QPSOConfig(swarm_size=1)
    with pytest.raises(ValueError):
        QPSOConfig(beta_min=1.5, beta_max=1.0)
    with pytest.raises(ValueError):
        QPSOConfig(u_floor=0.0)
    with pytest.raises(ValueError):
        TerminationCriteria(max_iterations=0)


def test_island_exchange_hook_can_inject_a_better_gbest():
    p = toy_problem()
    # a hand-built vector that decodes to the optimal split -> cost 80 (known optimum)
    great = np.array([0.1, 0.2, 0.3, 0.4])
    great_cost = p.evaluator.evaluate_one(great).fitness
    calls = []

    def exchange(gbest_vec, gbest_cost):
        calls.append(gbest_cost)
        return (great, great_cost)  # always offer the optimum

    res = QPSOOptimizer(QPSOConfig(swarm_size=12, max_iterations=20, seed=0, exchange_every=5)).solve(
        p, termination=TerminationCriteria(max_iterations=20), on_exchange=exchange
    )
    assert calls  # the hook fired
    assert res.best_cost == 80.0


def test_run_result_gap_helper():
    res = QPSOOptimizer(QPSOConfig(swarm_size=20, max_iterations=200, seed=1)).solve(
        toy_problem(), termination=TerminationCriteria(max_iterations=200)
    )
    assert res.gap(80.0) == 0.0
    assert res.gap(40.0) == 1.0

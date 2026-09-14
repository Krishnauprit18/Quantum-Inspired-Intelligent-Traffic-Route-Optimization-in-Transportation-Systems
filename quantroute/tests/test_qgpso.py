"""Piece 7 tests: the quantum rotation-gate optimizer (qgpso, PDF Deliverable 3)."""

import math
from pathlib import Path

import numpy as np
import pytest

from quantroute import (
    CollectingCallback,
    FitnessEvaluator,
    GreedyRepair,
    Optimizer,
    QGPSOConfig,
    QGPSOOptimizer,
    RandomKeyGiantTour,
    SearchProblem,
    TerminationCriteria,
)
from quantroute.io import load_cvrplib
from quantroute.optimizers.qgpso import _angle_of, _shortest_arc

TOY = Path(__file__).parent.parent / "data" / "instances" / "toy-n5-k2.vrp"


def toy_problem() -> SearchProblem:
    inst, _ = load_cvrplib(TOY)
    enc = RandomKeyGiantTour(inst.spec, inst.matrix)
    ev = FitnessEvaluator(inst.spec, inst.matrix, enc, repair=GreedyRepair(inst.spec, inst.matrix))
    return SearchProblem(inst.spec, inst.matrix, enc, ev, best_known=inst.best_known)


def test_angle_helpers():
    # sin^2(theta) round-trips through _angle_of
    x = np.array([0.0, 0.25, 0.5, 0.75, 1.0])
    assert np.allclose(np.sin(_angle_of(x)) ** 2, x)
    # shortest arc wraps correctly
    assert math.isclose(_shortest_arc(np.array([0.1]), np.array([0.2]))[0], 0.1, abs_tol=1e-9)
    d = _shortest_arc(np.array([0.1]), np.array([0.1 + 2 * math.pi]))[0]
    assert abs(d) < 1e-9  # a full turn is zero rotation


def test_qgpso_solves_toy_to_optimum():
    opt = QGPSOOptimizer(QGPSOConfig(population_size=24, max_iterations=200, seed=1))
    res = opt.solve(toy_problem(), termination=TerminationCriteria(max_iterations=200))
    assert isinstance(opt, Optimizer)
    assert res.algorithm == "qgpso"
    assert res.feasible
    assert res.best_cost == 80.0
    ok, why = res.routes.covers(toy_problem().spec)
    assert ok, why


def test_qgpso_positions_stay_in_unit_interval():
    p = toy_problem()
    opt = QGPSOOptimizer(QGPSOConfig(population_size=16, max_iterations=40, seed=2, mutation_rate=0.1))
    pop = opt._build_population(np.random.default_rng(2), p, None)
    for it in range(1, 20):
        pop.advance(np.random.default_rng(it), it, 40)
        x = pop.positions
        assert np.all((x >= 0.0) & (x <= 1.0))


def test_qgpso_deterministic_for_seed():
    term = TerminationCriteria(max_iterations=50)
    a = QGPSOOptimizer(QGPSOConfig(population_size=16, max_iterations=50, seed=9)).solve(toy_problem(), termination=term)
    b = QGPSOOptimizer(QGPSOConfig(population_size=16, max_iterations=50, seed=9)).solve(toy_problem(), termination=term)
    assert np.array_equal(a.best_vector, b.best_vector)
    assert a.config_hash == b.config_hash
    assert [r.incumbent_cost for r in a.convergence] == [r.incumbent_cost for r in b.convergence]


def test_qgpso_anytime_incumbent_monotone():
    cb = CollectingCallback()
    QGPSOOptimizer(QGPSOConfig(population_size=12, max_iterations=60, seed=3, publish_every=10)).solve(
        toy_problem(), callback=cb, termination=TerminationCriteria(max_iterations=60)
    )
    costs = [c for _, c, _ in cb.records]
    assert costs == sorted(costs, reverse=True)


def test_qgpso_config_validation():
    with pytest.raises(ValueError):
        QGPSOConfig(population_size=1)
    with pytest.raises(ValueError):
        QGPSOConfig(delta_theta_max=0.0)
    with pytest.raises(ValueError):
        QGPSOConfig(mutation_rate=1.5)
    with pytest.raises(ValueError):
        QGPSOConfig(inertia_min=0.9, inertia_max=0.4)


def test_qgpso_rejects_non_unit_encoding():
    class WeirdEncoding:
        dimension = 3

        def bounds(self):
            return (-1.0, 1.0)

        def random(self, rng):
            return rng.random(3)

        def decode(self, keys):  # pragma: no cover - not reached
            raise NotImplementedError

    p = toy_problem()
    bad = SearchProblem(p.spec, p.matrix, WeirdEncoding(), p.evaluator)
    with pytest.raises(NotImplementedError, match=r"\[0, 1\] random-key"):
        QGPSOOptimizer(QGPSOConfig(max_iterations=2)).solve(bad, termination=TerminationCriteria(max_iterations=2))

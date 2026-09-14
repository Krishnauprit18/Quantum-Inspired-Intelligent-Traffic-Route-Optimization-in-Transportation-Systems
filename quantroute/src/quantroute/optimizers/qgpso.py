"""Quantum-gate / rotation PSO — the PDF Deliverable-3 "quantum rotation / update rules"
engine (SIH26137).

Where ``qpso`` (system-design.html §9) uses a delta-potential-well draw, this variant keeps
an explicit **Q-bit angle** per dimension and updates it with a **rotation gate**, which is
the wording the problem statement uses.

Representation
--------------
Each dimension carries an angle ``theta``. The Q-bit is ``(alpha, beta) = (cos theta,
sin theta)`` and the *observed* random key is the |1> probability::

    x = sin(theta) ** 2   in [0, 1]

which feeds the same random-key giant-tour encoding as every other strategy.

Rotation-gate update (vectorised over the ``P x D`` population)
--------------------------------------------------------------
    w        = inertia_max - (inertia_max - inertia_min) * it / max_it
    d_pbest  = shortest_signed_arc(theta, theta_of(pbest))
    d_gbest  = shortest_signed_arc(theta, theta_of(gbest))
    d_theta  = clip( w * d_theta_prev
                     + c1 * r1 * d_pbest
                     + c2 * r2 * d_gbest ,  -d_theta_max, +d_theta_max )
    theta    = theta + d_theta                       # the rotation
    # quantum NOT gate: with prob mutation_rate, swap amplitudes  (x -> 1 - x)
    theta[mask] = pi/2 - theta[mask]

``shortest_signed_arc(a, b) = atan2(sin(b - a), cos(b - a))`` is the rotation *direction*
of the gate. The outer loop (decode -> repair -> evaluate -> anytime publish -> terminate)
is the shared driver, so this differs from ``qpso`` / ``pso`` only in the move (FR-8).

Assumes a ``[0, 1]`` random-key encoding (``RandomKeyGiantTour.bounds()``).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from quantroute.optimizers._util import readonly
from quantroute.optimizers.base import SearchProblem
from quantroute.optimizers.driver import (
    DriverConfig,
    Population,
    PopulationOptimizer,
    build_initial_positions,
)

_HALF_PI = math.pi / 2.0


@dataclass(frozen=True, slots=True)
class QGPSOConfig:
    population_size: int = 40
    max_iterations: int = 300
    inertia_max: float = 0.9
    inertia_min: float = 0.4
    cognitive: float = 1.0  # c1 — rotation toward personal best
    social: float = 1.0  # c2 — rotation toward global best
    delta_theta_max: float = 0.05 * math.pi  # max rotation per step (radians)
    mutation_rate: float = 0.02  # per-dimension quantum NOT-gate probability
    seed: int = 0
    publish_every: int = 10
    penalty_scale_start: float = 0.2
    penalty_scale_end: float = 1.0
    warm_start_fraction: float = 0.3
    warm_start_jitter: float = 0.05
    exchange_every: int | None = None

    def __post_init__(self) -> None:
        if self.population_size < 2:
            raise ValueError("population_size must be >= 2")
        if self.max_iterations < 1:
            raise ValueError("max_iterations must be >= 1")
        if not 0.0 <= self.inertia_min <= self.inertia_max:
            raise ValueError("require 0 <= inertia_min <= inertia_max")
        if self.cognitive < 0.0 or self.social < 0.0:
            raise ValueError("cognitive and social coefficients must be >= 0")
        if not 0.0 < self.delta_theta_max <= math.pi:
            raise ValueError("delta_theta_max must be in (0, pi]")
        if not 0.0 <= self.mutation_rate <= 1.0:
            raise ValueError("mutation_rate must be in [0, 1]")
        if self.publish_every < 1:
            raise ValueError("publish_every must be >= 1")
        if not 0.0 <= self.warm_start_fraction <= 1.0:
            raise ValueError("warm_start_fraction must be in [0, 1]")
        if self.warm_start_jitter < 0.0:
            raise ValueError("warm_start_jitter must be >= 0")
        if self.exchange_every is not None and self.exchange_every < 1:
            raise ValueError("exchange_every must be >= 1 when set")


def _shortest_arc(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Signed smallest rotation from angle ``a`` to angle ``b``, in (-pi, pi]."""
    return np.arctan2(np.sin(b - a), np.cos(b - a))


def _angle_of(x: np.ndarray) -> np.ndarray:
    """Canonical angle in [0, pi/2] with ``sin(theta) ** 2 == x``."""
    return np.arcsin(np.sqrt(np.clip(x, 0.0, 1.0)))


class QGPSOPopulation:
    """Population state for quantum-gate PSO: per-dimension angles + their rotation
    momentum, plus personal / global bests kept as observed positions."""

    __slots__ = (
        "_theta",
        "_dtheta",
        "_x",
        "_pbest",
        "_pbest_cost",
        "_gbest",
        "_gbest_cost",
        "_cfg",
    )

    def __init__(self, x0: np.ndarray, cfg: QGPSOConfig) -> None:
        arr = np.array(x0, dtype=np.float64, copy=True)
        if arr.ndim != 2 or arr.shape[0] < 2:
            raise ValueError("initial positions must be a 2-D (P>=2, D) array")
        self._theta = _angle_of(arr)
        self._dtheta = np.zeros_like(arr)
        self._x = np.clip(np.sin(self._theta) ** 2, 0.0, 1.0)
        self._pbest = self._x.copy()
        self._pbest_cost = np.full(arr.shape[0], np.inf, dtype=np.float64)
        self._gbest = self._x[0].copy()
        self._gbest_cost = float("inf")
        self._cfg = cfg

    @property
    def positions(self) -> np.ndarray:
        return readonly(self._x)

    @property
    def gbest_cost(self) -> float:
        return self._gbest_cost

    def register_costs(self, costs: np.ndarray) -> None:
        costs = np.asarray(costs, dtype=np.float64)
        if costs.shape != (self._x.shape[0],):
            raise ValueError(f"expected {self._x.shape[0]} costs, got shape {costs.shape}")
        improved = costs < self._pbest_cost
        if improved.any():
            self._pbest[improved] = self._x[improved]
            self._pbest_cost[improved] = costs[improved]
        best_i = int(np.argmin(self._pbest_cost))
        if self._pbest_cost[best_i] < self._gbest_cost:
            self._gbest_cost = float(self._pbest_cost[best_i])
            self._gbest = self._pbest[best_i].copy()

    def advance(self, rng: np.random.Generator, iteration: int, max_iterations: int) -> None:
        cfg = self._cfg
        p, d = self._theta.shape
        ratio = min(1.0, iteration / max_iterations)
        w = cfg.inertia_max - (cfg.inertia_max - cfg.inertia_min) * ratio

        theta_pbest = _angle_of(self._pbest)
        theta_gbest = _angle_of(self._gbest)

        r1 = rng.random((p, d))
        r2 = rng.random((p, d))
        delta = (
            w * self._dtheta
            + cfg.cognitive * r1 * _shortest_arc(self._theta, theta_pbest)
            + cfg.social * r2 * _shortest_arc(self._theta, theta_gbest)
        )
        np.clip(delta, -cfg.delta_theta_max, cfg.delta_theta_max, out=delta)
        self._dtheta = delta
        self._theta = self._theta + delta

        if cfg.mutation_rate > 0.0:
            mask = rng.random((p, d)) < cfg.mutation_rate
            self._theta[mask] = _HALF_PI - self._theta[mask]

        self._x = np.clip(np.sin(self._theta) ** 2, 0.0, 1.0)

    def global_best(self) -> tuple[np.ndarray, float]:
        return self._gbest.copy(), self._gbest_cost

    def inject_global_best(self, vector: np.ndarray, cost: float) -> None:
        if cost < self._gbest_cost:
            self._gbest = np.clip(np.asarray(vector, dtype=np.float64), 0.0, 1.0)
            self._gbest_cost = float(cost)


class QGPSOOptimizer(PopulationOptimizer):
    """Quantum rotation-gate PSO (PDF SIH26137 Deliverable 3)."""

    name = "qgpso"

    def __init__(self, config: QGPSOConfig | None = None) -> None:
        self._config = config or QGPSOConfig()
        super().__init__(
            DriverConfig(
                seed=self._config.seed,
                max_iterations=self._config.max_iterations,
                publish_every=self._config.publish_every,
                penalty_scale_start=self._config.penalty_scale_start,
                penalty_scale_end=self._config.penalty_scale_end,
                warm_start_fraction=self._config.warm_start_fraction,
                warm_start_jitter=self._config.warm_start_jitter,
                exchange_every=self._config.exchange_every,
            )
        )

    @property
    def config(self) -> QGPSOConfig:
        return self._config

    def _build_population(
        self, rng: np.random.Generator, problem: SearchProblem, warm_start: np.ndarray | None
    ) -> Population:
        lo, hi = problem.encoding.bounds()
        if (lo, hi) != (0.0, 1.0):
            raise NotImplementedError(
                f"qgpso assumes a [0, 1] random-key encoding; this one has bounds {(lo, hi)}"
            )
        x0 = build_initial_positions(
            rng,
            problem.encoding,
            self._config.population_size,
            lo,
            hi,
            warm_start,
            fraction=self._config.warm_start_fraction,
            jitter=self._config.warm_start_jitter,
        )
        return QGPSOPopulation(x0, self._config)

    def _algo_config_for_hash(self) -> dict:
        return {
            k: getattr(self._config, k)
            for k in (
                "population_size",
                "inertia_max",
                "inertia_min",
                "cognitive",
                "social",
                "delta_theta_max",
                "mutation_rate",
            )
        }

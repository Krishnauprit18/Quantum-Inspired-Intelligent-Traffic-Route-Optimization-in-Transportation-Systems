"""Quantum Particle Swarm Optimization (system-design.html §8.3, §9).

QPSO drops PSO's velocity term. Each iteration every particle is redrawn from a
delta-potential-well around a *local attractor* between its own best and the global best;
the well width is set by the swarm's *mean best* (``mbest``) and a single
contraction-expansion coefficient ``beta`` that ramps ``beta_max -> beta_min`` over the run.

Per-iteration move (verbatim from §9, vectorised over the ``P x D`` swarm)::

    mbest = pbest.mean(axis=0)
    beta  = beta_max - (beta_max - beta_min) * it / max_it
    phi   = U(0,1)^{P x D}
    p_att = phi * pbest + (1 - phi) * gbest
    u     = U(0,1)^{P x D}                       # floored away from 0
    L     = 2 * beta * |mbest - x|
    x     = p_att +/- L * ln(1/u)                # fair-coin sign per element
    x     = clip(x, lo, hi)

The outer loop (decode -> repair -> evaluate with a ramping penalty scale -> update bests
-> anytime publish -> termination) lives in :mod:`quantroute.optimizers.driver`, shared with
PSO and later GA / ACO so a benchmark differs *only* in this move (FR-8).

Determinism: given ``seed`` the NumPy ``Generator`` stream and every downstream step are
fixed (§8.3). The move draws ``phi``, ``u`` and the sign coin as three ``P x D`` blocks
(NumPy-idiomatic), so trajectories differ from a naive particle-by-particle port of the §9
pseudocode — both are valid QPSO.
"""

from __future__ import annotations

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


@dataclass(frozen=True, slots=True)
class QPSOConfig:
    swarm_size: int = 40
    max_iterations: int = 300
    beta_max: float = 1.0
    beta_min: float = 0.5
    seed: int = 0
    publish_every: int = 10
    penalty_scale_start: float = 0.2
    penalty_scale_end: float = 1.0
    warm_start_fraction: float = 0.3
    warm_start_jitter: float = 0.05
    u_floor: float = 1e-12
    exchange_every: int | None = None

    def __post_init__(self) -> None:
        if self.swarm_size < 2:
            raise ValueError("swarm_size must be >= 2")
        if self.max_iterations < 1:
            raise ValueError("max_iterations must be >= 1")
        if not 0.0 < self.beta_min <= self.beta_max:
            raise ValueError("require 0 < beta_min <= beta_max")
        if self.publish_every < 1:
            raise ValueError("publish_every must be >= 1")
        if not 0.0 <= self.warm_start_fraction <= 1.0:
            raise ValueError("warm_start_fraction must be in [0, 1]")
        if self.warm_start_jitter < 0.0:
            raise ValueError("warm_start_jitter must be >= 0")
        if not 0.0 < self.u_floor < 1.0:
            raise ValueError("u_floor must be in (0, 1)")
        if self.exchange_every is not None and self.exchange_every < 1:
            raise ValueError("exchange_every must be >= 1 when set")


@dataclass(frozen=True, slots=True)
class Particle:
    """Read-only snapshot of one swarm member (§9). The hot path stays vectorised; this is
    for inspection and island exchange."""

    index: int
    x: np.ndarray
    pbest: np.ndarray
    pbest_cost: float


class Swarm:
    """The ``P x D`` position / personal-best state plus the global best (§9)."""

    __slots__ = ("_x", "_pbest", "_pbest_cost", "_gbest", "_gbest_cost")

    def __init__(self, x0: np.ndarray) -> None:
        arr = np.array(x0, dtype=np.float64, copy=True)
        if arr.ndim != 2 or arr.shape[0] < 2 or arr.shape[1] < 1:
            raise ValueError("initial positions must be a 2-D (P>=2, D>=1) array")
        self._x = arr
        self._pbest = arr.copy()
        self._pbest_cost = np.full(arr.shape[0], np.inf, dtype=np.float64)
        self._gbest = arr[0].copy()
        self._gbest_cost = float("inf")

    @property
    def size(self) -> int:
        return self._x.shape[0]

    @property
    def dimension(self) -> int:
        return self._x.shape[1]

    @property
    def positions(self) -> np.ndarray:
        return readonly(self._x)

    @property
    def pbest(self) -> np.ndarray:
        return readonly(self._pbest)

    @property
    def gbest(self) -> np.ndarray:
        return readonly(self._gbest)

    @property
    def gbest_cost(self) -> float:
        return self._gbest_cost

    def set_positions(self, x: np.ndarray) -> None:
        if x.shape != self._x.shape:
            raise ValueError(f"expected positions of shape {self._x.shape}, got {x.shape}")
        self._x = np.array(x, dtype=np.float64, copy=True)

    def mbest(self) -> np.ndarray:
        """Mean of the personal-best positions (§9)."""
        return self._pbest.mean(axis=0)

    def update_bests(self, costs: np.ndarray) -> None:
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

    def inject_gbest(self, vector: np.ndarray, cost: float) -> None:
        if cost < self._gbest_cost:
            self._gbest = np.array(vector, dtype=np.float64, copy=True)
            self._gbest_cost = float(cost)

    def particle(self, i: int) -> Particle:
        return Particle(
            index=i,
            x=self._x[i].copy(),
            pbest=self._pbest[i].copy(),
            pbest_cost=float(self._pbest_cost[i]),
        )


class QPSOPopulation:
    """:class:`~quantroute.optimizers.driver.Population` adapter — the QPSO move over a
    :class:`Swarm`."""

    __slots__ = ("_swarm", "_cfg", "_lo", "_hi")

    def __init__(self, x0: np.ndarray, cfg: QPSOConfig, lo: float, hi: float) -> None:
        self._swarm = Swarm(x0)
        self._cfg = cfg
        self._lo = lo
        self._hi = hi

    @property
    def swarm(self) -> Swarm:
        return self._swarm

    @property
    def positions(self) -> np.ndarray:
        return self._swarm.positions

    def register_costs(self, costs: np.ndarray) -> None:
        self._swarm.update_bests(costs)

    def advance(self, rng: np.random.Generator, iteration: int, max_iterations: int) -> None:
        s = self._swarm
        cfg = self._cfg
        p, d = s.positions.shape
        mbest = s.mbest()
        ratio = min(1.0, iteration / max_iterations)
        beta = cfg.beta_max - (cfg.beta_max - cfg.beta_min) * ratio

        phi = rng.random((p, d))
        p_att = phi * s.pbest + (1.0 - phi) * s.gbest
        u = np.maximum(rng.random((p, d)), cfg.u_floor)
        length = 2.0 * beta * np.abs(mbest - s.positions)
        sign = np.where(rng.random((p, d)) < 0.5, 1.0, -1.0)

        s.set_positions(np.clip(p_att + sign * length * np.log(1.0 / u), self._lo, self._hi))

    def global_best(self) -> tuple[np.ndarray, float]:
        return self._swarm.gbest.copy(), self._swarm.gbest_cost

    def inject_global_best(self, vector: np.ndarray, cost: float) -> None:
        self._swarm.inject_gbest(vector, cost)


class QPSOOptimizer(PopulationOptimizer):
    name = "qpso"

    def __init__(self, config: QPSOConfig | None = None) -> None:
        self._config = config or QPSOConfig()
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
    def config(self) -> QPSOConfig:
        return self._config

    def _build_population(
        self, rng: np.random.Generator, problem: SearchProblem, warm_start: np.ndarray | None
    ) -> Population:
        lo, hi = problem.encoding.bounds()
        x0 = build_initial_positions(
            rng,
            problem.encoding,
            self._config.swarm_size,
            lo,
            hi,
            warm_start,
            fraction=self._config.warm_start_fraction,
            jitter=self._config.warm_start_jitter,
        )
        return QPSOPopulation(x0, self._config, lo, hi)

    def _algo_config_for_hash(self) -> dict:
        return {
            k: getattr(self._config, k) for k in ("swarm_size", "beta_max", "beta_min", "u_floor")
        }

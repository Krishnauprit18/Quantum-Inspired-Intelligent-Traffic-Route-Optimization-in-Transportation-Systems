"""Classic global-best Particle Swarm Optimization — a benchmark baseline (system-design.html
§9, §14). Same ``Optimizer.solve`` contract and shared outer loop as QPSO; the only
difference is the move, which keeps a velocity term:

    w   = inertia_max - (inertia_max - inertia_min) * it / max_it
    v   = w * v + c1 * r1 * (pbest - x) + c2 * r2 * (gbest - x)
    v   = clip(v, -v_max, +v_max)          # v_max = clamp_fraction * (hi - lo)
    x   = clip(x + v, lo, hi)

Velocities start at zero (particles at rest). ``r1`` and ``r2`` are drawn as ``P x D``
blocks so the RNG stream is reproducible from ``seed``.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from quantroute.optimizers.base import SearchProblem
from quantroute.optimizers.driver import (
    DriverConfig,
    Population,
    PopulationOptimizer,
    build_initial_positions,
)
from quantroute.optimizers._util import readonly


@dataclass(frozen=True, slots=True)
class PSOConfig:
    swarm_size: int = 40
    max_iterations: int = 300
    inertia_max: float = 0.9
    inertia_min: float = 0.4
    cognitive: float = 2.0  # c1 — pull toward personal best
    social: float = 2.0  # c2 — pull toward global best
    velocity_clamp_fraction: float = 0.2  # v_max as a fraction of the coordinate range
    seed: int = 0
    publish_every: int = 10
    penalty_scale_start: float = 0.2
    penalty_scale_end: float = 1.0
    warm_start_fraction: float = 0.3
    warm_start_jitter: float = 0.05
    exchange_every: int | None = None

    def __post_init__(self) -> None:
        if self.swarm_size < 2:
            raise ValueError("swarm_size must be >= 2")
        if self.max_iterations < 1:
            raise ValueError("max_iterations must be >= 1")
        if not 0.0 <= self.inertia_min <= self.inertia_max:
            raise ValueError("require 0 <= inertia_min <= inertia_max")
        if self.cognitive < 0.0 or self.social < 0.0:
            raise ValueError("cognitive and social coefficients must be >= 0")
        if self.velocity_clamp_fraction <= 0.0:
            raise ValueError("velocity_clamp_fraction must be > 0")
        if self.publish_every < 1:
            raise ValueError("publish_every must be >= 1")
        if not 0.0 <= self.warm_start_fraction <= 1.0:
            raise ValueError("warm_start_fraction must be in [0, 1]")
        if self.warm_start_jitter < 0.0:
            raise ValueError("warm_start_jitter must be >= 0")
        if self.exchange_every is not None and self.exchange_every < 1:
            raise ValueError("exchange_every must be >= 1 when set")


class PSOPopulation:
    """Global-best PSO state: positions, velocities, personal and global bests."""

    __slots__ = ("_x", "_v", "_pbest", "_pbest_cost", "_gbest", "_gbest_cost", "_cfg", "_lo", "_hi", "_vmax")

    def __init__(self, x0: np.ndarray, cfg: PSOConfig, lo: float, hi: float) -> None:
        arr = np.array(x0, dtype=np.float64, copy=True)
        if arr.ndim != 2 or arr.shape[0] < 2:
            raise ValueError("initial positions must be a 2-D (P>=2, D) array")
        self._x = arr
        self._v = np.zeros_like(arr)
        self._pbest = arr.copy()
        self._pbest_cost = np.full(arr.shape[0], np.inf, dtype=np.float64)
        self._gbest = arr[0].copy()
        self._gbest_cost = float("inf")
        self._cfg = cfg
        self._lo = lo
        self._hi = hi
        self._vmax = cfg.velocity_clamp_fraction * (hi - lo)

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
        ratio = min(1.0, iteration / max_iterations)
        w = cfg.inertia_max - (cfg.inertia_max - cfg.inertia_min) * ratio
        p, d = self._x.shape

        r1 = rng.random((p, d))
        r2 = rng.random((p, d))
        self._v = (
            w * self._v
            + cfg.cognitive * r1 * (self._pbest - self._x)
            + cfg.social * r2 * (self._gbest - self._x)
        )
        np.clip(self._v, -self._vmax, self._vmax, out=self._v)
        self._x = np.clip(self._x + self._v, self._lo, self._hi)

    def global_best(self) -> tuple[np.ndarray, float]:
        return self._gbest.copy(), self._gbest_cost

    def inject_global_best(self, vector: np.ndarray, cost: float) -> None:
        if cost < self._gbest_cost:
            self._gbest = np.array(vector, dtype=np.float64, copy=True)
            self._gbest_cost = float(cost)


class PSOOptimizer(PopulationOptimizer):
    name = "pso"

    def __init__(self, config: PSOConfig | None = None) -> None:
        self._config = config or PSOConfig()
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
    def config(self) -> PSOConfig:
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
        return PSOPopulation(x0, self._config, lo, hi)

    def _algo_config_for_hash(self) -> dict:
        return {
            k: getattr(self._config, k)
            for k in (
                "swarm_size",
                "inertia_max",
                "inertia_min",
                "cognitive",
                "social",
                "velocity_clamp_fraction",
            )
        }

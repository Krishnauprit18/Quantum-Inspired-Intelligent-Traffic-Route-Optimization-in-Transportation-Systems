"""Genetic Algorithm baseline over the random-key encoding (system-design.html §9, §14).

Individuals are real vectors in ``[0, 1]^D`` — the same representation every strategy uses —
so the shared driver's decode -> split -> repair -> evaluate pipeline scores them and the
comparison stays fair (FR-8). Each generation: keep the elite, then fill the rest by
tournament selection + whole-arithmetic crossover + Gaussian mutation (mutation strength
decays over the run).
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
class GAConfig:
    population_size: int = 60
    max_iterations: int = 300
    elite_fraction: float = 0.1
    tournament_size: int = 3
    crossover_rate: float = 0.9
    mutation_rate: float = 0.15  # per-gene probability
    mutation_sigma: float = 0.1  # Gaussian step (in [0,1] key space)
    seed: int = 0
    publish_every: int = 10
    penalty_scale_start: float = 0.2
    penalty_scale_end: float = 1.0
    warm_start_fraction: float = 0.3
    warm_start_jitter: float = 0.05
    exchange_every: int | None = None

    def __post_init__(self) -> None:
        if self.population_size < 4:
            raise ValueError("population_size must be >= 4")
        if self.max_iterations < 1:
            raise ValueError("max_iterations must be >= 1")
        if not 0.0 <= self.elite_fraction <= 0.9:
            raise ValueError("elite_fraction must be in [0, 0.9]")
        if not 2 <= self.tournament_size <= self.population_size:
            raise ValueError("tournament_size must be in [2, population_size]")
        if not 0.0 <= self.crossover_rate <= 1.0:
            raise ValueError("crossover_rate must be in [0, 1]")
        if not 0.0 <= self.mutation_rate <= 1.0:
            raise ValueError("mutation_rate must be in [0, 1]")
        if self.mutation_sigma <= 0.0:
            raise ValueError("mutation_sigma must be > 0")
        if self.publish_every < 1:
            raise ValueError("publish_every must be >= 1")
        if not 0.0 <= self.warm_start_fraction <= 1.0:
            raise ValueError("warm_start_fraction must be in [0, 1]")
        if self.warm_start_jitter < 0.0:
            raise ValueError("warm_start_jitter must be >= 0")
        if self.exchange_every is not None and self.exchange_every < 1:
            raise ValueError("exchange_every must be >= 1 when set")


class GAPopulation:
    __slots__ = ("_x", "_fitness", "_best", "_best_cost", "_cfg", "_lo", "_hi")

    def __init__(self, x0: np.ndarray, cfg: GAConfig, lo: float, hi: float) -> None:
        arr = np.array(x0, dtype=np.float64, copy=True)
        if arr.ndim != 2 or arr.shape[0] < 4:
            raise ValueError("initial population must be a 2-D (P>=4, D) array")
        self._x = arr
        self._fitness = np.full(arr.shape[0], np.inf, dtype=np.float64)
        self._best = arr[0].copy()
        self._best_cost = float("inf")
        self._cfg = cfg
        self._lo = lo
        self._hi = hi

    @property
    def positions(self) -> np.ndarray:
        return readonly(self._x)

    @property
    def gbest_cost(self) -> float:
        return self._best_cost

    def register_costs(self, costs: np.ndarray) -> None:
        costs = np.asarray(costs, dtype=np.float64)
        if costs.shape != (self._x.shape[0],):
            raise ValueError(f"expected {self._x.shape[0]} costs, got shape {costs.shape}")
        self._fitness = costs.copy()
        best_i = int(np.argmin(costs))
        if costs[best_i] < self._best_cost:
            self._best_cost = float(costs[best_i])
            self._best = self._x[best_i].copy()

    def advance(self, rng: np.random.Generator, iteration: int, max_iterations: int) -> None:
        cfg = self._cfg
        p, d = self._x.shape
        ranked = np.argsort(self._fitness, kind="stable")
        elite_n = max(1, int(round(cfg.elite_fraction * p)))

        nxt = np.empty_like(self._x)
        nxt[:elite_n] = self._x[ranked[:elite_n]]

        sigma = cfg.mutation_sigma * (1.0 - 0.5 * min(1.0, iteration / max_iterations))
        i = elite_n
        while i < p:
            a = self._x[self._tournament(rng)]
            b = self._x[self._tournament(rng)]
            c1, c2 = self._crossover(rng, a, b)
            for child in (c1, c2):
                if i >= p:
                    break
                self._mutate(rng, child, sigma)
                nxt[i] = np.clip(child, self._lo, self._hi)
                i += 1
        self._x = nxt

    def global_best(self) -> tuple[np.ndarray, float]:
        return self._best.copy(), self._best_cost

    def inject_global_best(self, vector: np.ndarray, cost: float) -> None:
        worst_i = int(np.argmax(self._fitness))
        self._x[worst_i] = np.clip(np.asarray(vector, dtype=np.float64), self._lo, self._hi)
        self._fitness[worst_i] = float(cost)
        if cost < self._best_cost:
            self._best_cost = float(cost)
            self._best = self._x[worst_i].copy()

    # -- operators -------------------------------------------------

    def _tournament(self, rng: np.random.Generator) -> int:
        picks = rng.integers(0, self._x.shape[0], size=self._cfg.tournament_size)
        return int(picks[np.argmin(self._fitness[picks])])

    def _crossover(
        self, rng: np.random.Generator, a: np.ndarray, b: np.ndarray
    ) -> tuple[np.ndarray, np.ndarray]:
        if rng.random() >= self._cfg.crossover_rate:
            return a.copy(), b.copy()
        alpha = rng.random(a.shape[0])
        return alpha * a + (1.0 - alpha) * b, (1.0 - alpha) * a + alpha * b

    def _mutate(self, rng: np.random.Generator, child: np.ndarray, sigma: float) -> None:
        mask = rng.random(child.shape[0]) < self._cfg.mutation_rate
        if mask.any():
            child[mask] += rng.normal(0.0, sigma, size=int(mask.sum()))


class GAOptimizer(PopulationOptimizer):
    name = "ga"

    def __init__(self, config: GAConfig | None = None) -> None:
        self._config = config or GAConfig()
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
    def config(self) -> GAConfig:
        return self._config

    def _build_population(
        self, rng: np.random.Generator, problem: SearchProblem, warm_start: np.ndarray | None
    ) -> Population:
        lo, hi = problem.encoding.bounds()
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
        return GAPopulation(x0, self._config, lo, hi)

    def _algo_config_for_hash(self) -> dict:
        return {
            k: getattr(self._config, k)
            for k in (
                "population_size",
                "elite_fraction",
                "tournament_size",
                "crossover_rate",
                "mutation_rate",
                "mutation_sigma",
            )
        }

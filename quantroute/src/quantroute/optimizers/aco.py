"""Ant Colony Optimization baseline (system-design.html §9, §14).

Classic ACO builds a customer ordering edge-by-edge from a pheromone matrix; here that
ordering is converted to a random-key vector (rank order) so the shared driver's
split -> repair -> evaluate pipeline scores it, keeping the comparison fair (FR-8).

Each iteration every ant constructs a tour with probability
``p(j) ~ tau[i][j]^alpha * eta[i][j]^beta`` (``eta = 1 / travel_time``). Pheromone is then
evaporated and reinforced along the iteration-best and global-best tours (elitist,
MMAS-style clamping to ``[tau_min, tau_max]``).
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

_EPS = 1e-9


@dataclass(frozen=True, slots=True)
class ACOConfig:
    n_ants: int = 40
    max_iterations: int = 300
    alpha: float = 1.0  # pheromone weight
    beta: float = 2.0  # heuristic weight
    evaporation: float = 0.1  # rho
    deposit: float = 1.0  # Q
    tau_min: float = 0.01
    tau_max: float = 10.0
    seed: int = 0
    publish_every: int = 10
    penalty_scale_start: float = 0.2
    penalty_scale_end: float = 1.0
    warm_start_fraction: float = 0.3
    warm_start_jitter: float = 0.05
    exchange_every: int | None = None

    def __post_init__(self) -> None:
        if self.n_ants < 2:
            raise ValueError("n_ants must be >= 2")
        if self.max_iterations < 1:
            raise ValueError("max_iterations must be >= 1")
        if self.alpha < 0.0 or self.beta < 0.0:
            raise ValueError("alpha and beta must be >= 0")
        if not 0.0 < self.evaporation <= 1.0:
            raise ValueError("evaporation must be in (0, 1]")
        if self.deposit <= 0.0:
            raise ValueError("deposit must be > 0")
        if not 0.0 < self.tau_min < self.tau_max:
            raise ValueError("require 0 < tau_min < tau_max")
        if self.publish_every < 1:
            raise ValueError("publish_every must be >= 1")
        if not 0.0 <= self.warm_start_fraction <= 1.0:
            raise ValueError("warm_start_fraction must be in [0, 1]")
        if self.warm_start_jitter < 0.0:
            raise ValueError("warm_start_jitter must be >= 0")
        if self.exchange_every is not None and self.exchange_every < 1:
            raise ValueError("exchange_every must be >= 1 when set")


class ACOPopulation:
    __slots__ = (
        "_x",
        "_tau",
        "_eta",
        "_tours",
        "_fitness",
        "_best",
        "_best_cost",
        "_best_tour",
        "_cfg",
        "_n",
    )

    def __init__(self, x0: np.ndarray, dist: np.ndarray, cfg: ACOConfig) -> None:
        arr = np.array(x0, dtype=np.float64, copy=True)
        n = dist.shape[0]
        if arr.ndim != 2 or arr.shape[1] != n or arr.shape[0] < 2:
            raise ValueError("population shape must be (n_ants>=2, n_customers)")

        self._n = n
        self._x = arr
        self._eta = 1.0 / (np.asarray(dist, dtype=np.float64) + _EPS)
        np.fill_diagonal(self._eta, 0.0)
        self._tau = np.full((n, n), cfg.tau_max, dtype=np.float64)
        np.fill_diagonal(self._tau, 0.0)
        self._tours: list[list[int]] = [list(np.argsort(arr[k], kind="stable")) for k in range(arr.shape[0])]
        self._fitness = np.full(arr.shape[0], np.inf, dtype=np.float64)
        self._best = arr[0].copy()
        self._best_cost = float("inf")
        self._best_tour: list[int] | None = None
        self._cfg = cfg

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
            self._best_tour = list(self._tours[best_i])

        cfg = self._cfg
        self._tau *= 1.0 - cfg.evaporation
        depositors = [(self._tours[best_i], float(costs[best_i]))]
        if self._best_tour is not None:
            depositors.append((self._best_tour, self._best_cost))
        for tour, cost in depositors:
            amount = cfg.deposit / max(cost, _EPS)
            for u, v in zip(tour, tour[1:]):
                self._tau[u, v] += amount
                self._tau[v, u] += amount
        np.clip(self._tau, cfg.tau_min, cfg.tau_max, out=self._tau)

    def advance(self, rng: np.random.Generator, iteration: int, max_iterations: int) -> None:
        self._tours = [self._construct(rng) for _ in range(self._x.shape[0])]
        for k, tour in enumerate(self._tours):
            keys = np.empty(self._n, dtype=np.float64)
            for rank, customer in enumerate(tour):
                keys[customer] = (rank + 0.5) / self._n
            self._x[k] = keys

    def global_best(self) -> tuple[np.ndarray, float]:
        return self._best.copy(), self._best_cost

    def inject_global_best(self, vector: np.ndarray, cost: float) -> None:
        if cost < self._best_cost:
            self._best = np.clip(np.asarray(vector, dtype=np.float64), 0.0, 1.0)
            self._best_cost = float(cost)
            self._best_tour = list(np.argsort(self._best, kind="stable"))

    # -- tour construction ---------------------------------------

    def _construct(self, rng: np.random.Generator) -> list[int]:
        n = self._n
        a, b = self._cfg.alpha, self._cfg.beta
        current = int(rng.integers(0, n))
        remaining = list(range(n))
        remaining.remove(current)
        tour = [current]

        while remaining:
            idx = np.fromiter(remaining, dtype=np.int64, count=len(remaining))
            weight = (self._tau[current, idx] ** a) * (self._eta[current, idx] ** b)
            total = float(weight.sum())
            if not np.isfinite(total) or total <= 0.0:
                choice = int(rng.integers(0, len(remaining)))
            else:
                cumulative = np.cumsum(weight)
                choice = int(np.searchsorted(cumulative, rng.random() * cumulative[-1]))
                choice = min(choice, len(remaining) - 1)
            current = remaining.pop(choice)
            tour.append(current)
        return tour


class ACOOptimizer(PopulationOptimizer):
    name = "aco"

    def __init__(self, config: ACOConfig | None = None) -> None:
        self._config = config or ACOConfig()
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
    def config(self) -> ACOConfig:
        return self._config

    def _build_population(
        self, rng: np.random.Generator, problem: SearchProblem, warm_start: np.ndarray | None
    ) -> Population:
        stops = problem.spec.stops
        n = len(stops)
        if n < 2:
            raise ValueError("ACO needs at least 2 stops")
        nodes = [s.node for s in stops]
        m = problem.matrix
        dist = np.zeros((n, n), dtype=np.float64)
        for i in range(n):
            for j in range(n):
                if i != j:
                    dist[i, j] = m.travel_time(nodes[i], nodes[j])

        lo, hi = problem.encoding.bounds()
        x0 = build_initial_positions(
            rng,
            problem.encoding,
            self._config.n_ants,
            lo,
            hi,
            warm_start,
            fraction=self._config.warm_start_fraction,
            jitter=self._config.warm_start_jitter,
        )
        return ACOPopulation(x0, dist, self._config)

    def _algo_config_for_hash(self) -> dict:
        return {
            k: getattr(self._config, k)
            for k in ("n_ants", "alpha", "beta", "evaporation", "deposit", "tau_min", "tau_max")
        }

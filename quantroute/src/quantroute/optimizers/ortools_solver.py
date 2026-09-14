"""Google OR-Tools routing baseline (system-design.html §9, §14; PDF: "benchmarked against
... exact methods").

OR-Tools is an optional dependency (``pip install 'quantroute[ortools]'``). The import is
deferred to :meth:`ORToolsOptimizer.solve` so the class can still be registered in the
:class:`~quantroute.optimizers.factory.OptimizerFactory` when the package is absent.

This wrapper solves the **CVRP** (single depot, per-vehicle capacity). Time windows and
multiple depots raise :class:`NotImplementedError` rather than being silently dropped — they
are a later addition. OR-Tools returns explicit routes; those routes are what
:class:`RunResult` reports and are scored with the shared
:class:`~quantroute.constraints.ConstraintValidator` so the number is comparable to the
metaheuristics. ``best_vector`` is a best-effort random-key reconstruction (rank order of
the visits) so an OR-Tools solution can warm-start a swarm.

The convergence trace is built from an *at-solution* callback, so it records the cost and
wall-clock of every improving solution the search finds (``iteration`` here counts
improvements, not local-search steps).
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import time
from dataclasses import dataclass

import numpy as np

from quantroute.constraints import ConstraintValidator, SolutionMetrics
from quantroute.optimizers.base import (
    AnytimeCallback,
    IterationRecord,
    Optimizer,
    RunResult,
    SearchProblem,
    TerminationCriteria,
)
from quantroute.problem import Objective
from quantroute.routes import Route, Routes

HAS_ORTOOLS = importlib.util.find_spec("ortools") is not None

_FIRST_SOLUTION_STRATEGIES = {
    "PATH_CHEAPEST_ARC",
    "PATH_MOST_CONSTRAINED_ARC",
    "SAVINGS",
    "SWEEP",
    "CHRISTOFIDES",
    "PARALLEL_CHEAPEST_INSERTION",
    "AUTOMATIC",
}
_METAHEURISTICS = {
    "GUIDED_LOCAL_SEARCH",
    "SIMULATED_ANNEALING",
    "TABU_SEARCH",
    "GENERIC_TABU_SEARCH",
    "AUTOMATIC",
    "GREEDY_DESCENT",
}


@dataclass(frozen=True, slots=True)
class ORToolsConfig:
    time_limit_s: float | None = None  # falls back to the instance's time_budget_ms
    first_solution: str = "PATH_CHEAPEST_ARC"
    metaheuristic: str = "GUIDED_LOCAL_SEARCH"
    cost_scale: int = 1000  # travel time -> integer arc cost
    seed: int = 0  # bookkeeping only; OR-Tools is deterministic for a fixed time limit

    def __post_init__(self) -> None:
        if self.time_limit_s is not None and self.time_limit_s <= 0:
            raise ValueError("time_limit_s must be > 0 when set")
        if self.first_solution not in _FIRST_SOLUTION_STRATEGIES:
            raise ValueError(
                f"first_solution must be one of {sorted(_FIRST_SOLUTION_STRATEGIES)}"
            )
        if self.metaheuristic not in _METAHEURISTICS:
            raise ValueError(f"metaheuristic must be one of {sorted(_METAHEURISTICS)}")
        if self.cost_scale < 1:
            raise ValueError("cost_scale must be >= 1")


class ORToolsOptimizer(Optimizer):
    name = "ortools"

    def __init__(self, config: ORToolsConfig | None = None) -> None:
        self._config = config or ORToolsConfig()

    @property
    def config(self) -> ORToolsConfig:
        return self._config

    def solve(
        self,
        problem: SearchProblem,
        *,
        callback: AnytimeCallback | None = None,
        termination: TerminationCriteria | None = None,
        **_ignored,
    ) -> RunResult:
        try:
            from ortools.constraint_solver import pywrapcp, routing_enums_pb2
        except ImportError as exc:  # pragma: no cover - depends on environment
            raise ImportError(
                "the OR-Tools baseline needs OR-Tools: pip install 'quantroute[ortools]'"
            ) from exc

        spec = problem.spec
        matrix = problem.matrix

        if len(spec.depots) != 1:
            raise NotImplementedError("OR-Tools baseline supports a single depot only")
        if any(s.has_time_window for s in spec.stops) and spec.constraints.enforce_time_windows:
            raise NotImplementedError("OR-Tools baseline does not wire time windows yet")

        depot = spec.depots[0]
        for v in spec.vehicles:
            if v.start_depot != depot.id or v.effective_end_depot != depot.id:
                raise NotImplementedError("all vehicles must start and end at the single depot")

        nodes = [depot.node, *(s.node for s in spec.stops)]  # index 0 = depot
        n = len(nodes)
        num_vehicles = len(spec.vehicles)
        scale = self._config.cost_scale

        time_limit_s = (
            (termination.time_budget_s if termination else None)
            or self._config.time_limit_s
            or spec.time_budget_ms / 1000.0
        )

        manager = pywrapcp.RoutingIndexManager(n, num_vehicles, 0)
        routing = pywrapcp.RoutingModel(manager)

        # optimise the same channel the instance objective is scored on
        leg = matrix.distance if spec.objective is Objective.MIN_DISTANCE else matrix.travel_time

        def arc_cost(from_index: int, to_index: int) -> int:
            a = nodes[manager.IndexToNode(from_index)]
            b = nodes[manager.IndexToNode(to_index)]
            return int(round(leg(a, b) * scale))

        transit_idx = routing.RegisterTransitCallback(arc_cost)
        routing.SetArcCostEvaluatorOfAllVehicles(transit_idx)

        demands = [0.0, *(s.demand for s in spec.stops)]

        def demand_cb(from_index: int) -> int:
            return int(round(demands[manager.IndexToNode(from_index)]))

        demand_idx = routing.RegisterUnaryTransitCallback(demand_cb)
        routing.AddDimensionWithVehicleCapacity(
            demand_idx,
            0,
            [int(round(v.capacity)) for v in spec.vehicles],
            True,
            "Capacity",
        )

        params = pywrapcp.DefaultRoutingSearchParameters()
        params.first_solution_strategy = getattr(
            routing_enums_pb2.FirstSolutionStrategy, self._config.first_solution
        )
        params.local_search_metaheuristic = getattr(
            routing_enums_pb2.LocalSearchMetaheuristic, self._config.metaheuristic
        )
        params.time_limit.FromMilliseconds(int(round(time_limit_s * 1000)))
        params.log_search = False

        # The at-solution callback fires on every solution the search visits, including the
        # non-improving ones GLS uses to escape local optima. Keep only genuine
        # improvements so the trace is a monotone incumbent curve, like the metaheuristics'.
        started = time.perf_counter()
        improvements: list[tuple[int, float, float]] = []
        best_so_far = float("inf")

        def _on_solution() -> None:
            nonlocal best_so_far
            current = routing.CostVar().Value() / scale
            if current < best_so_far:
                best_so_far = current
                improvements.append(
                    (len(improvements) + 1, time.perf_counter() - started, current)
                )

        routing.AddAtSolutionCallback(_on_solution)

        assignment = routing.SolveWithParameters(params)
        elapsed = time.perf_counter() - started

        if assignment is None:
            return self._failed_result(problem, elapsed, termination)

        routes = self._extract_routes(routing, manager, assignment, spec)
        metrics = ConstraintValidator(spec, matrix).evaluate(routes)
        best_vector = self._reconstruct_vector(routes, spec)
        base = _base_cost(metrics, spec.objective)

        trace = tuple(IterationRecord(i, t, c) for (i, t, c) in improvements)
        if trace:
            # pin the last point to the authoritative re-scored cost
            last = trace[-1]
            trace = trace[:-1] + (IterationRecord(last.iteration, last.elapsed_s, base),)
        else:
            trace = (IterationRecord(0, elapsed, base),)

        if callback is not None:
            callback.on_incumbent(len(trace), base, np.array(best_vector, copy=True))

        return RunResult(
            algorithm=self.name,
            best_vector=best_vector,
            best_fitness=base,  # OR-Tools returns a feasible assignment; no penalty term
            best_cost=base,
            routes=routes,
            feasible=metrics.is_feasible,
            metrics=metrics,
            cost_breakdown=_breakdown(metrics, base),
            convergence=trace,
            iterations=len(improvements),
            stop_reason="solver_finished",
            elapsed_s=elapsed,
            seed=self._config.seed,
            config_hash=self._config_hash(problem, time_limit_s),
        )

    # -- helpers ---------------------------------------------------

    def _extract_routes(self, routing, manager, assignment, spec) -> Routes:
        out: list[Route] = []
        for v, vehicle in enumerate(spec.vehicles):
            stop_ids: list[str] = []
            index = routing.Start(v)
            while not routing.IsEnd(index):
                node = manager.IndexToNode(index)
                if node != 0:  # skip the depot
                    stop_ids.append(spec.stops[node - 1].id)
                index = assignment.Value(routing.NextVar(index))
            out.append(Route(vehicle.id, tuple(stop_ids)))
        return Routes(tuple(out))

    @staticmethod
    def _reconstruct_vector(routes: Routes, spec) -> np.ndarray:
        idx_of = spec.stop_index()
        n = len(spec.stops)
        vec = np.full(n, 0.5, dtype=np.float64)
        rank = 0
        for route in routes:
            for sid in route.stop_ids:
                if sid in idx_of:
                    vec[idx_of[sid]] = (rank + 0.5) / n
                    rank += 1
        return vec

    def _failed_result(
        self, problem: SearchProblem, elapsed: float, termination: TerminationCriteria | None
    ) -> RunResult:
        spec = problem.spec
        empty = Routes(tuple(Route(v.id, ()) for v in spec.vehicles))
        metrics = ConstraintValidator(spec, problem.matrix).evaluate(empty)
        return RunResult(
            algorithm=self.name,
            best_vector=np.full(len(spec.stops), 0.5, dtype=np.float64),
            best_fitness=float("inf"),
            best_cost=float("inf"),
            routes=empty,
            feasible=False,
            metrics=metrics,
            cost_breakdown=_breakdown(metrics, float("inf")),
            convergence=(IterationRecord(0, elapsed, float("inf")),),
            iterations=0,
            stop_reason="no_solution",
            elapsed_s=elapsed,
            seed=self._config.seed,
            config_hash=self._config_hash(problem, None),
        )

    def _config_hash(self, problem: SearchProblem, time_limit_s: float | None) -> str:
        payload = {
            "algorithm": self.name,
            "algo_config": {
                "first_solution": self._config.first_solution,
                "metaheuristic": self._config.metaheuristic,
                "cost_scale": self._config.cost_scale,
                "seed": self._config.seed,
                "time_limit_s": time_limit_s,
            },
            "instance": {
                "name": problem.spec.name,
                "objective": problem.spec.objective.value,
                "dimension": problem.spec.dimension(),
                "vehicles": len(problem.spec.vehicles),
            },
        }
        blob = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def _base_cost(metrics: SolutionMetrics, objective: Objective) -> float:
    if objective is Objective.MIN_DISTANCE:
        return metrics.total_distance_m
    if objective is Objective.MIN_MAKESPAN:
        return metrics.makespan_s
    return metrics.total_travel_time_s


def _breakdown(metrics: SolutionMetrics, base: float) -> dict[str, float]:
    return {
        "base_cost": base,
        "penalty": 0.0,
        "travel_time_s": metrics.total_travel_time_s,
        "distance_m": metrics.total_distance_m,
        "capacity_overflow": metrics.total_capacity_overflow,
        "lateness_s": metrics.total_lateness_s,
        "duration_overflow_s": metrics.total_duration_overflow_s,
        "vehicles_used": float(metrics.vehicles_used),
    }

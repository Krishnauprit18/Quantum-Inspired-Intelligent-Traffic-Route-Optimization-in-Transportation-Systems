"""Parse and validate a benchmark ``run.yaml`` into a :class:`BenchmarkPlan`.

Config shape::

    name: phase0-cvrp
    instances:
      - data/instances/toy-n5-k2.vrp      # file, or a directory of .vrp files
    algorithms:
      - id: qpso
        params: { swarm_size: 30, max_iterations: 200 }
      - id: ortools
        params: { time_limit_s: 5 }
    seeds: 5                                # int N -> [1..N], or an explicit list
    objective: travel-time                  # travel-time | distance | makespan
    repair: true
    termination: { max_iterations: 200, time_budget_s: null }
    report_target_gap: 0.02                 # "time to within 2% of best-known"
    output_dir: runs/phase0-cvrp

Relative instance paths are resolved against the config file's directory so a plan is
portable. Every algorithm id and its params are validated up front by constructing the
optimizer through the factory.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from quantroute.optimizers import OptimizerFactory
from quantroute.optimizers.base import TerminationCriteria
from quantroute.problem import Objective

_OBJECTIVES = {
    "travel-time": Objective.MIN_TRAVEL_TIME,
    "distance": Objective.MIN_DISTANCE,
    "makespan": Objective.MIN_MAKESPAN,
}
_TERMINATION_KEYS = {
    "max_iterations",
    "time_budget_s",
    "target_gap",
    "stagnation_iterations",
    "min_improvement",
}


@dataclass(frozen=True, slots=True)
class AlgoSpec:
    id: str
    params: dict


@dataclass(frozen=True, slots=True)
class BenchmarkPlan:
    name: str
    instances: tuple[Path, ...]
    algorithms: tuple[AlgoSpec, ...]
    seeds: tuple[int, ...]
    objective: Objective
    repair: bool
    termination: dict
    report_target_gap: float
    output_dir: Path

    @property
    def total_runs(self) -> int:
        return len(self.instances) * len(self.algorithms) * len(self.seeds)

    def termination_criteria(self) -> TerminationCriteria:
        return TerminationCriteria(**self.termination)


class BenchmarkConfigError(ValueError):
    """Raised when a benchmark config is malformed or references something invalid."""


def load_plan(path: str | Path) -> BenchmarkPlan:
    cfg_path = Path(path).expanduser()
    try:
        raw = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise BenchmarkConfigError(f"no such config file: {cfg_path}") from None
    except yaml.YAMLError as exc:
        raise BenchmarkConfigError(f"cannot parse {cfg_path}: {exc}") from None
    if not isinstance(raw, dict):
        raise BenchmarkConfigError("benchmark config must be a mapping")

    base_dir = cfg_path.parent
    name = str(raw.get("name") or cfg_path.stem)

    instances = _resolve_instances(raw.get("instances"), base_dir)
    algorithms = _parse_algorithms(raw.get("algorithms"))
    seeds = _parse_seeds(raw.get("seeds", 1))

    objective_key = str(raw.get("objective", "travel-time"))
    if objective_key not in _OBJECTIVES:
        raise BenchmarkConfigError(
            f"unknown objective {objective_key!r}; choose from {sorted(_OBJECTIVES)}"
        )

    repair = bool(raw.get("repair", True))

    termination = dict(raw.get("termination") or {})
    unknown = set(termination) - _TERMINATION_KEYS
    if unknown:
        raise BenchmarkConfigError(f"unknown termination keys: {sorted(unknown)}")
    try:
        TerminationCriteria(**termination)  # validate ranges now
    except (TypeError, ValueError) as exc:
        raise BenchmarkConfigError(f"invalid termination: {exc}") from None

    report_target_gap = float(raw.get("report_target_gap", 0.02))
    if report_target_gap < 0.0:
        raise BenchmarkConfigError("report_target_gap must be >= 0")

    # like `instances`, a relative output_dir is anchored to the config file's directory
    output_dir = Path(raw.get("output_dir") or f"runs/{name}").expanduser()
    if not output_dir.is_absolute():
        output_dir = (base_dir / output_dir).resolve()

    return BenchmarkPlan(
        name=name,
        instances=instances,
        algorithms=algorithms,
        seeds=seeds,
        objective=_OBJECTIVES[objective_key],
        repair=repair,
        termination=termination,
        report_target_gap=report_target_gap,
        output_dir=output_dir,
    )


def _resolve_instances(spec, base_dir: Path) -> tuple[Path, ...]:
    if not isinstance(spec, list) or not spec:
        raise BenchmarkConfigError("'instances' must be a non-empty list")
    out: list[Path] = []
    for entry in spec:
        p = Path(str(entry)).expanduser()
        if not p.is_absolute():
            p = (base_dir / p).resolve()
        if p.is_dir():
            found = sorted(p.glob("*.vrp"))
            if not found:
                raise BenchmarkConfigError(f"no .vrp files in directory {p}")
            out.extend(found)
        elif p.is_file():
            out.append(p)
        else:
            raise BenchmarkConfigError(f"instance path not found: {p}")
    return tuple(out)


def _parse_algorithms(spec) -> tuple[AlgoSpec, ...]:
    if not isinstance(spec, list) or not spec:
        raise BenchmarkConfigError("'algorithms' must be a non-empty list")
    available = set(OptimizerFactory.available())
    out: list[AlgoSpec] = []
    for entry in spec:
        if not isinstance(entry, dict) or "id" not in entry:
            raise BenchmarkConfigError(f"each algorithm needs an 'id': {entry!r}")
        algo_id = str(entry["id"]).strip().lower()
        if algo_id not in available:
            raise BenchmarkConfigError(
                f"unknown algorithm {algo_id!r}; available: {sorted(available)}"
            )
        params = dict(entry.get("params") or {})
        # validate params by building the optimizer (seed is injected per-run)
        try:
            OptimizerFactory.from_config({"algorithm": algo_id, "params": {**params, "seed": 0}})
        except (ValueError, TypeError, KeyError) as exc:
            raise BenchmarkConfigError(f"bad params for {algo_id!r}: {exc}") from None
        out.append(AlgoSpec(id=algo_id, params=params))
    if len({a.id for a in out}) != len(out):
        raise BenchmarkConfigError("duplicate algorithm ids in the plan")
    return tuple(out)


def _parse_seeds(spec) -> tuple[int, ...]:
    if isinstance(spec, bool):  # guard: bool is an int subclass
        raise BenchmarkConfigError("'seeds' must be an int or a list of ints")
    if isinstance(spec, int):
        if spec < 1:
            raise BenchmarkConfigError("'seeds' count must be >= 1")
        return tuple(range(1, spec + 1))
    if (
        isinstance(spec, list)
        and spec
        and all(isinstance(s, int) and not isinstance(s, bool) for s in spec)
    ):
        if len(set(spec)) != len(spec):
            raise BenchmarkConfigError("duplicate seeds")
        return tuple(spec)
    raise BenchmarkConfigError("'seeds' must be an int N (-> 1..N) or a list of ints")

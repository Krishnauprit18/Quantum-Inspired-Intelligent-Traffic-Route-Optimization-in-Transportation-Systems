"""``OptimizerFactory`` — build an :class:`Optimizer` from a plain config mapping
(system-design.html §9; used by the benchmark harness / ``benchmark/run.yaml``, §14).

The registry keeps ``name -> (optimizer class, config class)``. New strategies (GA, ACO,
OR-Tools) register themselves without touching this file. Config parsing is strict: an
unknown ``params`` key is an error, not silently ignored, and every value is range-checked
by the target config dataclass.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping
from typing import Any

from quantroute.optimizers.aco import ACOConfig, ACOOptimizer
from quantroute.optimizers.base import Optimizer
from quantroute.optimizers.ga import GAConfig, GAOptimizer
from quantroute.optimizers.ortools_solver import ORToolsConfig, ORToolsOptimizer
from quantroute.optimizers.pso import PSOConfig, PSOOptimizer
from quantroute.optimizers.qgpso import QGPSOConfig, QGPSOOptimizer
from quantroute.optimizers.qpso import QPSOConfig, QPSOOptimizer


class OptimizerFactory:
    # Process-wide registry: strategies register on import (bottom of this file) and via
    # `register`. Tests that add a throwaway entry must remove it again.
    _registry: dict[str, tuple[type[Optimizer], type]] = {}

    @classmethod
    def register(cls, name: str, optimizer_cls: type[Optimizer], config_cls: type) -> None:
        key = name.strip().lower()
        if not key:
            raise ValueError("optimizer name must be non-empty")
        if not dataclasses.is_dataclass(config_cls):
            raise TypeError(f"config_cls for {key!r} must be a dataclass")
        cls._registry[key] = (optimizer_cls, config_cls)

    @classmethod
    def available(cls) -> list[str]:
        return sorted(cls._registry)

    @classmethod
    def from_config(cls, config: Mapping[str, Any]) -> Optimizer:
        """``{"algorithm": "qpso", "params": {...}}`` -> a ready ``Optimizer``."""
        if not isinstance(config, Mapping):
            raise TypeError("optimizer config must be a mapping")

        name = config.get("algorithm")
        if not isinstance(name, str) or not name.strip():
            raise ValueError("optimizer config needs a non-empty 'algorithm' string")
        key = name.strip().lower()
        if key not in cls._registry:
            raise KeyError(f"unknown algorithm {name!r}; available: {', '.join(cls.available())}")

        params = config.get("params", {})
        if not isinstance(params, Mapping):
            raise TypeError("'params' must be a mapping when present")

        optimizer_cls, config_cls = cls._registry[key]
        allowed = {f.name for f in dataclasses.fields(config_cls)}
        unknown = set(params) - allowed
        if unknown:
            raise ValueError(
                f"unknown params for {key!r}: {sorted(unknown)}; allowed: {sorted(allowed)}"
            )

        try:
            typed_config = config_cls(**dict(params))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"invalid params for {key!r}: {exc}") from exc

        return optimizer_cls(typed_config)


OptimizerFactory.register("qpso", QPSOOptimizer, QPSOConfig)
OptimizerFactory.register("qgpso", QGPSOOptimizer, QGPSOConfig)
OptimizerFactory.register("pso", PSOOptimizer, PSOConfig)
OptimizerFactory.register("ga", GAOptimizer, GAConfig)
OptimizerFactory.register("aco", ACOOptimizer, ACOConfig)
OptimizerFactory.register("ortools", ORToolsOptimizer, ORToolsConfig)

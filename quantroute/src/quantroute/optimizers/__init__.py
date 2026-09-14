"""Search strategies (system-design.html §9): one ``Optimizer.solve`` contract, many
implementations sharing one outer loop (:mod:`quantroute.optimizers.driver`).

Landed: the interface, the quantum-inspired ``QPSOOptimizer`` and the classic ``PSOOptimizer``
baseline, plus ``OptimizerFactory`` for config-driven construction. GA / ACO / OR-Tools
baselines register into the same factory in later pieces.
"""

from quantroute.optimizers.base import (
    AnytimeCallback,
    CollectingCallback,
    IterationRecord,
    NullCallback,
    Optimizer,
    RunResult,
    SearchProblem,
    TerminationCriteria,
)
from quantroute.optimizers.driver import (
    DriverConfig,
    Population,
    PopulationOptimizer,
    build_initial_positions,
)
from quantroute.optimizers.aco import ACOConfig, ACOOptimizer, ACOPopulation
from quantroute.optimizers.factory import OptimizerFactory
from quantroute.optimizers.ga import GAConfig, GAOptimizer, GAPopulation
from quantroute.optimizers.ortools_solver import ORToolsConfig, ORToolsOptimizer
from quantroute.optimizers.pso import PSOConfig, PSOOptimizer, PSOPopulation
from quantroute.optimizers.qgpso import QGPSOConfig, QGPSOOptimizer, QGPSOPopulation
from quantroute.optimizers.qpso import (
    Particle,
    QPSOConfig,
    QPSOOptimizer,
    QPSOPopulation,
    Swarm,
)

__all__ = [
    # contract
    "Optimizer",
    "SearchProblem",
    "TerminationCriteria",
    "RunResult",
    "IterationRecord",
    "AnytimeCallback",
    "CollectingCallback",
    "NullCallback",
    # shared driver
    "PopulationOptimizer",
    "Population",
    "DriverConfig",
    "build_initial_positions",
    # strategies
    "QPSOOptimizer",
    "QPSOConfig",
    "QPSOPopulation",
    "Swarm",
    "Particle",
    "QGPSOOptimizer",
    "QGPSOConfig",
    "QGPSOPopulation",
    "PSOOptimizer",
    "PSOConfig",
    "PSOPopulation",
    "GAOptimizer",
    "GAConfig",
    "GAPopulation",
    "ACOOptimizer",
    "ACOConfig",
    "ACOPopulation",
    "ORToolsOptimizer",
    "ORToolsConfig",
    # factory
    "OptimizerFactory",
]

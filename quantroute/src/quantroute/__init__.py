"""quantroute — quantum-inspired traffic route optimization core (SIH26137).

Built one reviewed piece at a time against ``../system-design.html`` (§9 class model,
§16 roadmap). Pieces landed so far:

  1. domain model      — problem.py, routes.py
  2. cost matrix + IO  — matrix.py, io/cvrplib.py
  3. encoding          — encoding.py (random-key giant tour + Prins split)
  4. evaluate + repair — constraints.py, repair.py, evaluate.py
  5. QPSO optimizer    — optimizers/ (base, driver, qpso)
  6. PSO baseline + factory — optimizers/pso.py, optimizers/factory.py
  7. qgpso (rotation-gate, PDF Deliverable 3) + OR-Tools baseline — optimizers/qgpso.py, ortools_solver.py
"""

from quantroute.constraints import (
    ConstraintValidator,
    RouteMetrics,
    SolutionMetrics,
    Violation,
)
from quantroute.encoding import Decoded, Encoding, RandomKeyGiantTour
from quantroute.evaluate import FitnessEvaluator, FitnessResult, PenaltyWeights
from quantroute.matrix import CostMatrix, DenseCostMatrix, euclidean_matrix_2d
from quantroute.optimizers import (
    ACOConfig,
    ACOOptimizer,
    AnytimeCallback,
    CollectingCallback,
    GAConfig,
    GAOptimizer,
    IterationRecord,
    NullCallback,
    Optimizer,
    OptimizerFactory,
    ORToolsConfig,
    ORToolsOptimizer,
    Particle,
    PSOConfig,
    PSOOptimizer,
    QGPSOConfig,
    QGPSOOptimizer,
    QPSOConfig,
    QPSOOptimizer,
    RunResult,
    SearchProblem,
    Swarm,
    TerminationCriteria,
)
from quantroute.repair import GreedyRepair, RepairOperator
from quantroute.problem import (
    ConstraintSet,
    Depot,
    Objective,
    ProblemSpec,
    Stop,
    Vehicle,
)
from quantroute.routes import Route, Routes

__all__ = [
    # domain model
    "ConstraintSet",
    "Depot",
    "Objective",
    "ProblemSpec",
    "Stop",
    "Vehicle",
    "Route",
    "Routes",
    # cost matrix
    "CostMatrix",
    "DenseCostMatrix",
    "euclidean_matrix_2d",
    # encoding
    "Encoding",
    "RandomKeyGiantTour",
    "Decoded",
    # constraints / repair / evaluate
    "ConstraintValidator",
    "Violation",
    "RouteMetrics",
    "SolutionMetrics",
    "RepairOperator",
    "GreedyRepair",
    "FitnessEvaluator",
    "FitnessResult",
    "PenaltyWeights",
    # optimizers
    "Optimizer",
    "SearchProblem",
    "TerminationCriteria",
    "RunResult",
    "IterationRecord",
    "AnytimeCallback",
    "CollectingCallback",
    "NullCallback",
    "QPSOOptimizer",
    "QPSOConfig",
    "QGPSOOptimizer",
    "QGPSOConfig",
    "PSOOptimizer",
    "PSOConfig",
    "GAOptimizer",
    "GAConfig",
    "ACOOptimizer",
    "ACOConfig",
    "ORToolsOptimizer",
    "ORToolsConfig",
    "OptimizerFactory",
    "Swarm",
    "Particle",
]

__version__ = "0.0.1"

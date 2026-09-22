"""Benchmark harness (system-design.html §14, PDF Deliverable 5).

Runs a *dataset x algorithm x seed* matrix, collects per-run metrics and convergence
traces, and produces a reproducible comparison: summary statistics, pairwise
Wilcoxon signed-rank tests with Holm-Bonferroni correction, and (optionally) convergence
plots.

Needs the ``benchmark`` extra:  ``pip install 'quantroute[benchmark]'``
(pandas, scipy, pyyaml; matplotlib only for plots).
"""

from quantroute.benchmark.config import AlgoSpec, BenchmarkPlan, load_plan
from quantroute.benchmark.report import write_report
from quantroute.benchmark.runner import RunRecord, run_plan
from quantroute.benchmark.stats import holm_bonferroni, pairwise_vs_baseline, summarize

__all__ = [
    "AlgoSpec",
    "BenchmarkPlan",
    "load_plan",
    "RunRecord",
    "run_plan",
    "summarize",
    "pairwise_vs_baseline",
    "holm_bonferroni",
    "write_report",
]

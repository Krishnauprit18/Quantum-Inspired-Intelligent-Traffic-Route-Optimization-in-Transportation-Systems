"""Aggregate benchmark records and compare algorithms (system-design.html §14).

* :func:`summarize` — per (instance, algorithm): feasibility rate, best / mean / median
  gap, mean wall-clock, median time-to-target.
* :func:`pairwise_vs_baseline` — for each other algorithm, a paired Wilcoxon signed-rank
  test against the baseline on matched (instance, seed) samples, with Holm-Bonferroni
  correction across the family and a rank-biserial effect size.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import stats


def records_to_frame(records) -> pd.DataFrame:
    return pd.DataFrame([r.row() for r in records])


def summarize(df: pd.DataFrame) -> pd.DataFrame:
    grouped = df.groupby(["instance", "algorithm"], as_index=False)
    out = grouped.agg(
        runs=("seed", "count"),
        feasible_rate=("feasible", "mean"),
        best_cost_min=("best_cost", "min"),
        best_cost_mean=("best_cost", "mean"),
        gap_pct_mean=("gap_pct", "mean"),
        gap_pct_median=("gap_pct", "median"),
        gap_pct_std=("gap_pct", "std"),
        elapsed_s_mean=("elapsed_s", "mean"),
        time_to_target_s_median=("time_to_target_s", "median"),
    )
    return out.sort_values(["instance", "gap_pct_mean"], na_position="last").reset_index(drop=True)


def holm_bonferroni(pvals: list[float]) -> list[float]:
    """Holm step-down adjustment. Returns adjusted p-values in the input order."""
    m = len(pvals)
    if m == 0:
        return []
    order = np.argsort(pvals)
    adjusted = np.empty(m, dtype=float)
    running = 0.0
    for rank, idx in enumerate(order):
        running = max(running, (m - rank) * float(pvals[idx]))
        adjusted[idx] = min(running, 1.0)
    return adjusted.tolist()


def pairwise_vs_baseline(
    df: pd.DataFrame,
    baseline: str,
    *,
    metric: str = "gap_pct",
    alpha: float = 0.05,
) -> pd.DataFrame:
    """Compare every other algorithm to ``baseline`` on ``metric`` (lower is better)."""
    if baseline not in set(df["algorithm"]):
        raise ValueError(f"baseline {baseline!r} is not in the results")

    pivot = df.pivot_table(index=["instance", "seed"], columns="algorithm", values=metric)
    if baseline not in pivot.columns:
        raise ValueError(f"baseline {baseline!r} has no {metric} values")

    others = [c for c in pivot.columns if c != baseline]
    rows: list[dict] = []
    raw_p: list[float] = []

    for algo in others:
        pair = pivot[[algo, baseline]].dropna()
        a = pair[algo].to_numpy(dtype=float)
        b = pair[baseline].to_numpy(dtype=float)
        diff = a - b
        n = int(len(diff))

        if n == 0 or np.allclose(diff, 0.0):
            stat, pval, effect = 0.0, 1.0, 0.0
        else:
            stat, pval = stats.wilcoxon(a, b)
            # rank-biserial correlation: (#a<b - #a>b) / n_nonzero
            nz = diff[diff != 0.0]
            effect = float((np.sum(nz < 0) - np.sum(nz > 0)) / len(nz)) if len(nz) else 0.0

        rows.append(
            {
                "algorithm": algo,
                "baseline": baseline,
                "metric": metric,
                "n_pairs": n,
                "median_diff": float(np.median(diff)) if n else float("nan"),
                "win_rate": float(np.mean(a < b)) if n else float("nan"),
                "wilcoxon_stat": float(stat),
                "p_value": float(pval),
                "effect_rank_biserial": effect,
            }
        )
        raw_p.append(float(pval))

    for row, p_adj in zip(rows, holm_bonferroni(raw_p)):
        row["p_holm"] = p_adj
        row["significant"] = bool(p_adj < alpha)

    return pd.DataFrame(rows)

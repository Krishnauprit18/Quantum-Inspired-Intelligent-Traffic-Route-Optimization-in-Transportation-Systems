"""Write a benchmark run to disk: per-run records, per-run convergence traces, a summary
table, pairwise statistics, a human-readable ``report.md`` and (optionally) convergence
plots.
"""

from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

from quantroute.benchmark.config import BenchmarkPlan
from quantroute.benchmark.runner import RunRecord
from quantroute.benchmark.stats import pairwise_vs_baseline, records_to_frame, summarize

# preferred baseline for the pairwise tests, best first
_BASELINE_PREFERENCE = ("ortools", "pso", "qpso")


def _slug(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", text).strip("-") or "x"


def _pick_baseline(records: list[RunRecord]) -> str | None:
    present = {r.algorithm for r in records}
    for name in _BASELINE_PREFERENCE:
        if name in present:
            return name
    return next(iter(sorted(present)), None)


def write_report(
    records: list[RunRecord],
    plan: BenchmarkPlan,
    out_dir: str | Path,
    *,
    plot: bool = True,
) -> Path:
    out = Path(out_dir).expanduser()
    out.mkdir(parents=True, exist_ok=True)
    conv_dir = out / "convergence"
    conv_dir.mkdir(exist_ok=True)

    df = records_to_frame(records)
    df.to_csv(out / "records.csv", index=False)

    for r in records:
        cdf = pd.DataFrame(
            list(r.convergence), columns=["iteration", "elapsed_s", "incumbent_cost"]
        )
        cdf.to_csv(
            conv_dir / f"{_slug(r.instance)}__{_slug(r.algorithm)}__seed{r.seed}.csv",
            index=False,
        )

    summary = summarize(df)
    summary.to_csv(out / "summary.csv", index=False)

    baseline = _pick_baseline(records)
    stats_df = pd.DataFrame()
    if baseline is not None and len({r.algorithm for r in records}) > 1:
        stats_df = pairwise_vs_baseline(df, baseline)
        stats_df.to_csv(out / "stats.csv", index=False)

    (out / "report.md").write_text(
        _render_markdown(plan, records, summary, stats_df, baseline), encoding="utf-8"
    )

    if plot:
        _maybe_plot(records, out)

    return out


def _render_markdown(plan, records, summary, stats_df, baseline) -> str:
    lines: list[str] = []
    lines.append(f"# Benchmark: {plan.name}\n")
    lines.append(
        f"- runs: {len(records)}  "
        f"({len(plan.instances)} instances x {len(plan.algorithms)} algorithms x {len(plan.seeds)} seeds)\n"
        f"- objective: {plan.objective.value}  |  repair: {plan.repair}  |  "
        f"termination: {plan.termination}\n"
    )

    lines.append("\n## Summary (per instance x algorithm)\n")
    lines.append(_df_to_md(summary.round(4)))

    if not stats_df.empty:
        lines.append(f"\n## Pairwise vs `{baseline}` (Wilcoxon signed-rank, Holm-corrected)\n")
        lines.append(
            "`median_diff` and `win_rate` are for the row algorithm relative to the "
            "baseline on `gap_pct` (negative / >0.5 favours the row algorithm).\n"
        )
        lines.append(_df_to_md(stats_df.round(5)))

    feas = pd.DataFrame([r.row() for r in records])["feasible"].mean()
    lines.append(f"\n## Notes\n- overall feasible rate: {feas:.1%}\n")
    lines.append("- convergence traces: `convergence/<instance>__<algo>__seed<n>.csv`\n")
    return "\n".join(lines) + "\n"


def _df_to_md(df: pd.DataFrame) -> str:
    try:
        return df.to_markdown(index=False)
    except ImportError:  # tabulate not installed -> plain CSV block
        return "```\n" + df.to_csv(index=False) + "```"


def _maybe_plot(records: list[RunRecord], out: Path) -> None:
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return

    by_instance: dict[str, list[RunRecord]] = {}
    for r in records:
        by_instance.setdefault(r.instance, []).append(r)

    for instance, recs in by_instance.items():
        fig, ax = plt.subplots(figsize=(7, 4.5))
        algos = sorted({r.algorithm for r in recs})
        for algo in algos:
            traces = [
                pd.DataFrame(
                    list(r.convergence), columns=["iteration", "elapsed_s", "incumbent_cost"]
                )
                for r in recs
                if r.algorithm == algo and r.convergence
            ]
            if not traces:
                continue
            merged = pd.concat(traces).groupby("iteration", as_index=False)["incumbent_cost"].mean()
            ax.plot(merged["iteration"], merged["incumbent_cost"], label=algo)
        ax.set_xlabel("iteration")
        ax.set_ylabel("incumbent cost (mean over seeds)")
        ax.set_title(f"convergence — {instance}")
        ax.legend()
        fig.tight_layout()
        fig.savefig(out / f"convergence_{_slug(instance)}.png", dpi=120)
        plt.close(fig)

"""Piece 9 tests: the benchmark harness (skipped without the benchmark extra)."""

from pathlib import Path

import pytest

pytest.importorskip("pandas")
pytest.importorskip("scipy")

from typer.testing import CliRunner  # noqa: E402

from quantroute.benchmark import load_plan, run_plan, write_report  # noqa: E402
from quantroute.benchmark.config import BenchmarkConfigError  # noqa: E402
from quantroute.benchmark.stats import holm_bonferroni  # noqa: E402
from quantroute.cli import app  # noqa: E402

TOY = Path(__file__).parent.parent / "data" / "instances" / "toy-n5-k2.vrp"
runner = CliRunner()


def _write_plan(tmp_path: Path, *, seeds: int = 4, algos=None) -> Path:
    algos = algos or [
        {"id": "qpso", "params": {"swarm_size": 16, "max_iterations": 40}},
        {"id": "pso", "params": {"swarm_size": 16, "max_iterations": 40}},
    ]
    cfg = {
        "name": "unit",
        "instances": [str(TOY)],
        "algorithms": algos,
        "seeds": seeds,
        "objective": "travel-time",
        "termination": {"max_iterations": 40},
        "output_dir": str(tmp_path / "out"),
    }
    p = tmp_path / "run.yaml"
    import yaml

    p.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    return p


# -- config --------------------------------------------------------------


def test_load_plan_counts_runs(tmp_path):
    plan = load_plan(_write_plan(tmp_path, seeds=5))
    assert plan.total_runs == 1 * 2 * 5
    assert plan.seeds == (1, 2, 3, 4, 5)
    assert [a.id for a in plan.algorithms] == ["qpso", "pso"]


def test_load_plan_rejects_unknown_algorithm(tmp_path):
    with pytest.raises(BenchmarkConfigError, match="unknown algorithm"):
        load_plan(_write_plan(tmp_path, algos=[{"id": "wizardry"}]))


def test_load_plan_rejects_bad_params(tmp_path):
    with pytest.raises(BenchmarkConfigError, match="bad params"):
        load_plan(_write_plan(tmp_path, algos=[{"id": "qpso", "params": {"swarm_size": 1}}]))


def test_load_plan_missing_instance(tmp_path):
    import yaml

    p = tmp_path / "run.yaml"
    p.write_text(
        yaml.safe_dump({"name": "x", "instances": ["nope.vrp"], "algorithms": [{"id": "pso"}]})
    )
    with pytest.raises(BenchmarkConfigError, match="not found"):
        load_plan(p)


# -- stats -------------------------------------------------------------


def test_holm_bonferroni_known_values():
    adj = holm_bonferroni([0.01, 0.04, 0.03])
    # sorted p: 0.01*3=0.03 ; 0.03*2=0.06 ; 0.04*1=0.04 -> monotone -> 0.06
    assert adj[0] == pytest.approx(0.03)
    assert adj[2] == pytest.approx(0.06)
    assert adj[1] == pytest.approx(0.06)  # enforced monotone
    assert holm_bonferroni([]) == []


# -- runner + report -------------------------------------------------


def test_run_plan_and_write_report(tmp_path):
    plan = load_plan(_write_plan(tmp_path, seeds=6))
    records = run_plan(plan)
    assert len(records) == 12
    assert all(r.feasible for r in records)
    assert all(r.best_cost == 80.0 for r in records)  # toy optimum
    assert all(r.gap_pct == 0.0 for r in records)
    assert all(r.time_to_target_s is not None for r in records)

    out = write_report(records, plan, plan.output_dir, plot=False)
    assert (out / "records.csv").is_file()
    assert (out / "summary.csv").is_file()
    assert (out / "stats.csv").is_file()
    assert (out / "report.md").is_file()
    conv = list((out / "convergence").glob("*.csv"))
    assert len(conv) == 12

    import pandas as pd

    summary = pd.read_csv(out / "summary.csv")
    assert len(summary) == 2  # 1 instance x 2 algorithms
    stats = pd.read_csv(out / "stats.csv")
    assert "p_holm" in stats.columns and "significant" in stats.columns

    report = (out / "report.md").read_text()
    assert "Benchmark: unit" in report and "Wilcoxon" in report


def test_run_plan_progress_callback(tmp_path):
    plan = load_plan(_write_plan(tmp_path, seeds=2))
    seen: list[str] = []
    run_plan(plan, progress=lambda done, total, label: seen.append(f"{done}/{total} {label}"))
    assert seen[0].startswith("1/4")
    assert seen[-1].startswith("4/4")


# -- CLI ---------------------------------------------------------------


def test_cli_benchmark_dry_run(tmp_path):
    result = runner.invoke(app, ["benchmark", str(_write_plan(tmp_path, seeds=3)), "--dry-run"])
    assert result.exit_code == 0
    assert "= 6 runs" in result.output
    assert "qpso" in result.output and "pso" in result.output


def test_cli_benchmark_full_run(tmp_path):
    plan_path = _write_plan(tmp_path, seeds=3)
    out = tmp_path / "cli-out"
    result = runner.invoke(app, ["benchmark", str(plan_path), "-o", str(out), "--no-plot"])
    assert result.exit_code == 0
    assert (out / "report.md").is_file()
    assert f"wrote {out}" in result.output

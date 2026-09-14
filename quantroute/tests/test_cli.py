"""Piece 8 tests: the command-line interface."""

import json
from pathlib import Path

from typer.testing import CliRunner

from quantroute.cli import app

runner = CliRunner()
TOY = str(Path(__file__).parent.parent / "data" / "instances" / "toy-n5-k2.vrp")


def test_algorithms_lists_strategies():
    result = runner.invoke(app, ["algorithms"])
    assert result.exit_code == 0
    for name in ("qpso", "qgpso", "pso", "ortools"):
        assert name in result.output


def test_info_prints_instance_stats():
    result = runner.invoke(app, ["info", TOY])
    assert result.exit_code == 0
    assert "toy-n5-k2" in result.output
    assert "stops           4" in result.output
    assert "best known      80" in result.output


def test_info_bad_path_exits_1():
    result = runner.invoke(app, ["info", "nope.vrp"])
    assert result.exit_code == 1
    assert "error:" in result.output


def test_solve_table_output():
    result = runner.invoke(app, ["solve", TOY, "-a", "qpso", "-i", "120", "-s", "1"])
    assert result.exit_code == 0
    assert "best cost       80" in result.output
    assert "feasible        True" in result.output
    assert "gap             0.000%" in result.output
    assert "routes:" in result.output


def test_solve_json_output_is_valid():
    result = runner.invoke(app, ["solve", TOY, "-a", "pso", "-i", "100", "-s", "2", "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["best_cost"] == 80.0
    assert payload["feasible"] is True
    assert payload["algorithm"] == "pso"
    covered = sorted(s for r in payload["routes"] for s in r["stops"])
    assert covered == ["c2", "c3", "c4", "c5"]


def test_solve_exports_convergence_and_routes(tmp_path):
    csv_path = tmp_path / "conv.csv"
    json_path = tmp_path / "routes.json"
    result = runner.invoke(
        app,
        ["solve", TOY, "-a", "qgpso", "-i", "80", "-s", "3",
         "--convergence-csv", str(csv_path), "--routes-json", str(json_path)],
    )
    assert result.exit_code == 0

    lines = csv_path.read_text().strip().splitlines()
    assert lines[0] == "iteration,elapsed_s,incumbent_cost"
    assert len(lines) >= 2

    saved = json.loads(json_path.read_text())
    assert saved["best_cost"] == 80.0
    assert saved["config_hash"]


def test_solve_with_yaml_config(tmp_path):
    cfg = tmp_path / "run.yaml"
    cfg.write_text("algorithm: qpso\nparams:\n  swarm_size: 20\n  max_iterations: 150\n  seed: 1\n")
    result = runner.invoke(app, ["solve", TOY, "--config", str(cfg), "--json"])
    assert result.exit_code == 0
    assert json.loads(result.output)["best_cost"] == 80.0


def test_solve_unknown_algorithm_exits_1():
    result = runner.invoke(app, ["solve", TOY, "-a", "magic"])
    assert result.exit_code == 1
    assert "unknown algorithm" in result.output


def test_solve_unknown_objective_exits_1():
    result = runner.invoke(app, ["solve", TOY, "--objective", "money"])
    assert result.exit_code == 1
    assert "unknown objective" in result.output


def test_solve_ortools_via_cli():
    result = runner.invoke(app, ["solve", TOY, "-a", "ortools", "-t", "2.0", "--json"])
    assert result.exit_code == 0
    assert json.loads(result.output)["best_cost"] == 80.0


def test_solve_no_repair_flag_runs():
    result = runner.invoke(app, ["solve", TOY, "-a", "qpso", "-i", "60", "-s", "1", "--no-repair", "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.output)
    covered = sorted(s for r in payload["routes"] for s in r["stops"])
    assert covered == ["c2", "c3", "c4", "c5"]


def test_solve_time_budget_stops_early():
    result = runner.invoke(
        app, ["solve", TOY, "-a", "pso", "-i", "100000", "-t", "0.05", "--json"]
    )
    assert result.exit_code == 0
    assert json.loads(result.output)["stop_reason"] == "time_budget"

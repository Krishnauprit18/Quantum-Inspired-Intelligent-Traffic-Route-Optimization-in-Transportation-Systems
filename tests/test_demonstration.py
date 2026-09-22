from quantroute.demonstration import (
    ScaleSpec,
    build_urban_scenario,
    evaluate_routes_under_epoch,
    solve_scenario,
)


def test_urban_scenario_has_three_traffic_epochs():
    scale = ScaleSpec("test", 5, 5, 6, 4, 6)
    scenario = build_urban_scenario(scale, seed=3)
    assert set(scenario.epochs) == {"free-flow", "rush-hour", "incident"}
    assert scenario.graph.num_nodes == 25
    assert len(scenario.spec.stops) == 6
    assert scenario.spec.total_capacity >= scenario.spec.total_demand


def test_dynamic_reoptimization_pipeline_runs():
    scale = ScaleSpec("test", 5, 5, 6, 4, 6)
    scenario = build_urban_scenario(scale, seed=2)
    free = solve_scenario(scenario, "free-flow", "qpso", seed=1)
    stale = evaluate_routes_under_epoch(scenario, free.routes, "incident")
    incident = solve_scenario(scenario, "incident", "qpso", seed=1)
    assert free.feasible
    assert incident.feasible
    assert stale > 0
    assert incident.best_cost > 0

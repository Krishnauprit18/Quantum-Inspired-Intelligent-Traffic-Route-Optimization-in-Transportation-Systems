"""Piece 2 tests: the CVRPLIB .vrp / .sol parser."""

from pathlib import Path

import pytest

from quantroute import Objective
from quantroute.io import (
    CVRPLIBParseError,
    load_cvrplib,
    parse_sol,
    parse_vrp,
)

DATA = Path(__file__).parent.parent / "data" / "instances"
TOY = DATA / "toy-n5-k2.vrp"


def test_parse_toy_instance_shape():
    inst = parse_vrp(TOY)
    assert inst.spec.name == "toy-n5-k2"
    assert inst.spec.dimension() == 4  # stops, depot excluded
    assert inst.depot_node == 1
    assert inst.capacity == 30
    assert inst.num_vehicles == 2
    assert inst.num_vehicles_source == "name token -k2"
    assert inst.best_known == 80.0  # from COMMENT "Optimal value: 80"
    assert {s.id for s in inst.spec.stops} == {"c2", "c3", "c4", "c5"}
    assert all(s.demand == 10 for s in inst.spec.stops)
    assert all(v.capacity == 30 for v in inst.spec.vehicles)
    assert inst.spec.objective is Objective.MIN_TRAVEL_TIME


def test_parse_toy_matrix_values():
    inst = parse_vrp(TOY)
    m = inst.matrix
    assert m.travel_time(1, 2) == 10
    assert m.travel_time(2, 3) == 10
    assert m.travel_time(1, 3) == 20
    assert m.travel_time(1, 5) == 20
    assert m.travel_time(2, 1) == m.travel_time(1, 2)  # symmetric


def test_num_vehicles_explicit_override():
    inst = parse_vrp(TOY, num_vehicles=3)
    assert inst.num_vehicles == 3
    assert inst.num_vehicles_source == "explicit argument"
    assert len(inst.spec.vehicles) == 3


def test_num_vehicles_below_capacity_lower_bound_rejected():
    # total demand 40, capacity 30 -> need >= 2
    with pytest.raises(CVRPLIBParseError, match="at least 2"):
        parse_vrp(TOY, num_vehicles=1)


def test_missing_file_raises_filenotfound():
    with pytest.raises(FileNotFoundError):
        parse_vrp(DATA / "does-not-exist.vrp")


def _write(tmp_path: Path, body: str, name: str = "x.vrp") -> Path:
    p = tmp_path / name
    p.write_text(body, encoding="utf-8")
    return p


BASE = """NAME : x-n3-k1
TYPE : CVRP
DIMENSION : 3
EDGE_WEIGHT_TYPE : EUC_2D
CAPACITY : 100
NODE_COORD_SECTION
1 0 0
2 1 0
3 2 0
DEMAND_SECTION
1 0
2 5
3 5
DEPOT_SECTION
1
-1
EOF
"""


def test_valid_minimal_instance(tmp_path):
    inst = parse_vrp(_write(tmp_path, BASE))
    assert inst.num_vehicles == 1
    assert inst.num_vehicles_source == "name token -k1"


def test_unsupported_edge_weight_type(tmp_path):
    body = BASE.replace("EUC_2D", "EXPLICIT")
    with pytest.raises(CVRPLIBParseError, match="EDGE_WEIGHT_TYPE"):
        parse_vrp(_write(tmp_path, body))


def test_unsupported_type(tmp_path):
    body = BASE.replace("TYPE : CVRP", "TYPE : TSP")
    with pytest.raises(CVRPLIBParseError, match="TYPE"):
        parse_vrp(_write(tmp_path, body))


def test_dimension_mismatch_detected(tmp_path):
    body = BASE.replace("DIMENSION : 3", "DIMENSION : 4")
    with pytest.raises(CVRPLIBParseError, match="DIMENSION"):
        parse_vrp(_write(tmp_path, body))


def test_depot_section_not_terminated(tmp_path):
    body = BASE.replace("1\n-1\n", "1\n")
    with pytest.raises(CVRPLIBParseError, match="terminated by -1"):
        parse_vrp(_write(tmp_path, body))


def test_depot_with_demand_rejected(tmp_path):
    body = BASE.replace("1 0\n2 5", "1 7\n2 5")
    with pytest.raises(CVRPLIBParseError, match="non-zero demand"):
        parse_vrp(_write(tmp_path, body))


def test_file_size_limit(tmp_path):
    with pytest.raises(CVRPLIBParseError, match="limit"):
        parse_vrp(_write(tmp_path, BASE), max_bytes=10)


def test_garbage_token_reports_line_number(tmp_path):
    body = BASE.replace("2 1 0", "2 x 0")
    with pytest.raises(CVRPLIBParseError, match=r"line \d+"):
        parse_vrp(_write(tmp_path, body))


def test_nan_and_inf_values_rejected(tmp_path):
    # float() would happily accept these; the parser must not.
    with pytest.raises(CVRPLIBParseError, match="finite"):
        parse_vrp(_write(tmp_path, BASE.replace("2 5\n3 5", "2 nan\n3 5")))
    with pytest.raises(CVRPLIBParseError, match="finite"):
        parse_vrp(_write(tmp_path, BASE.replace("CAPACITY : 100", "CAPACITY : inf")))
    with pytest.raises(CVRPLIBParseError, match="finite"):
        parse_vrp(_write(tmp_path, BASE.replace("2 1 0", "2 1e999 0")))


def test_max_dimension_guard_trips_before_full_parse(tmp_path):
    with pytest.raises(CVRPLIBParseError, match="max_dimension"):
        parse_vrp(_write(tmp_path, BASE), max_dimension=2)


def test_parse_sol_and_load_pairing():
    sol = parse_sol(DATA / "toy-n5-k2.sol")
    assert sol.routes == ((2, 3), (4, 5))
    assert sol.cost == 80.0
    assert sol.num_vehicles == 2

    inst, paired = load_cvrplib(TOY)
    assert paired is not None
    assert paired.cost == 80.0
    assert inst.best_known == 80.0


def test_load_cvrplib_without_sol(tmp_path):
    inst, sol = load_cvrplib(_write(tmp_path, BASE))
    assert sol is None

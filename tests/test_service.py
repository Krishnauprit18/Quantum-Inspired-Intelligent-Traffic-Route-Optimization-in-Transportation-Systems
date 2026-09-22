"""Piece 12 tests: the FastAPI service (skipped without the service extra)."""

import time

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402

from quantroute.service import create_app  # noqa: E402


@pytest.fixture()
def client():
    with TestClient(create_app()) as c:
        yield c


def _inline_solve_body(**over):
    body = {
        "depot_x": 50.0,
        "depot_y": 50.0,
        "stops": [
            {"id": "s1", "x": 10.0, "y": 10.0, "demand": 5},
            {"id": "s2", "x": 90.0, "y": 20.0, "demand": 5},
            {"id": "s3", "x": 20.0, "y": 80.0, "demand": 5},
            {"id": "s4", "x": 80.0, "y": 90.0, "demand": 5},
        ],
        "vehicles": [{"id": "v", "capacity": 40, "count": 2}],
        "algorithm": "qpso",
        "iterations": 60,
        "seed": 1,
    }
    body.update(over)
    return body


def test_health_and_algorithms(client):
    assert client.get("/health").json()["status"] == "ok"
    algos = client.get("/v1/algorithms").json()
    assert {"qpso", "qgpso", "pso", "ga", "aco", "ortools"} <= set(algos)


def test_register_grid_network_and_traffic(client):
    r = client.post("/v1/networks", json={"kind": "grid", "name": "g", "rows": 5, "cols": 5})
    assert r.status_code == 201
    net = r.json()
    assert net["nodes"] == 25 and net["current_epoch"] == 0
    nid = net["network_id"]

    assert client.get(f"/v1/networks/{nid}").json()["network_id"] == nid
    assert [n["network_id"] for n in client.get("/v1/networks").json()] == [nid]

    r = client.post(f"/v1/networks/{nid}/traffic", json={"unobserved_factor": 2.0})
    assert r.status_code == 200 and r.json()["epoch_id"] == 1

    r = client.post(f"/v1/networks/{nid}/traffic", json={})  # nothing to apply
    assert r.status_code == 422


def test_route_on_network(client):
    nid = client.post("/v1/networks", json={"kind": "grid", "rows": 4, "cols": 4}).json()[
        "network_id"
    ]
    r = client.post("/v1/route", json={"network_id": nid, "origin": 0, "destination": 15})
    assert r.status_code == 200
    body = r.json()
    assert body["nodes"][0] == 0 and body["nodes"][-1] == 15
    assert body["travel_time_s"] > 0 and body["distance_m"] > 0


def test_inline_solve_sync_and_map(client):
    r = client.post("/v1/solve", json=_inline_solve_body())
    assert r.status_code == 200
    res = r.json()
    assert res["status"] == "done" and res["feasible"] is True
    covered = sorted(s for leg in res["routes"] for s in leg["stops"])
    assert covered == ["s1", "s2", "s3", "s4"]

    job_id = res["job_id"]
    m = client.get(f"/v1/solve/{job_id}/map")
    assert m.status_code == 200 and "leaflet" in m.text.lower()
    p = client.get(f"/v1/solve/{job_id}/map.png")
    assert p.status_code == 200 and p.headers["content-type"] == "image/png"


def test_solve_on_network(client):
    nid = client.post(
        "/v1/networks", json={"kind": "grid", "rows": 6, "cols": 6, "spacing_m": 100}
    ).json()["network_id"]
    body = {
        "network_id": nid,
        "depot_node": 0,
        "stops": [
            {"id": "a", "node": 8, "demand": 10},
            {"id": "b", "node": 15, "demand": 10},
            {"id": "c", "node": 28, "demand": 10},
        ],
        "vehicles": [{"id": "v", "capacity": 50, "count": 2}],
        "algorithm": "ga",
        "iterations": 50,
        "seed": 2,
    }
    res = client.post("/v1/solve", json=body).json()
    assert res["status"] == "done" and res["feasible"] is True
    assert client.get(f"/v1/solve/{res['job_id']}/map").status_code == 200


def test_async_solve_polls_to_done(client):
    res = client.post("/v1/solve", json=_inline_solve_body(sync=False, iterations=40)).json()
    assert res["status"] in ("queued", "running")
    job_id = res["job_id"]
    for _ in range(100):
        cur = client.get(f"/v1/solve/{job_id}").json()
        if cur["status"] in ("done", "failed"):
            break
        time.sleep(0.05)
    assert cur["status"] == "done" and cur["feasible"] is True


def test_solve_validation_errors(client):
    bad = _inline_solve_body()
    del bad["depot_x"]
    assert client.post("/v1/solve", json=bad).status_code == 422

    assert (
        client.post(
            "/v1/route", json={"network_id": "nope", "origin": 0, "destination": 1}
        ).status_code
        == 404
    )
    assert client.get("/v1/solve/deadbeef").status_code == 404

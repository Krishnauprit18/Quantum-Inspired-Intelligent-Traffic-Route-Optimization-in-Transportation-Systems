"""Tests for persistent Database storage and SQS/Worker pipeline (Piece 4)."""

from quantroute.service.db import Database
from quantroute.service.state import JobStore
from quantroute.service.worker import OptimizationWorker


def test_database_crud(tmp_path):
    db_file = tmp_path / "test.db"
    db = Database(db_file)

    # Save and retrieve network
    db.save_network("net-1", "Test City", node_count=10, edge_count=20, payload={"key": "val"})
    net = db.get_network("net-1")
    assert net is not None
    assert net["name"] == "Test City"
    assert net["node_count"] == 10
    assert net["payload"] == {"key": "val"}

    # Save, update, and retrieve job
    db.save_job("job-1", network_id="net-1", status="queued", request_data={"stops": [1, 2]})
    job = db.get_job("job-1")
    assert job is not None
    assert job["status"] == "queued"
    assert job["request"] == {"stops": [1, 2]}

    db.update_job("job-1", status="done", result={"cost": 42.0})
    job_updated = db.get_job("job-1")
    assert job_updated["status"] == "done"
    assert job_updated["result"] == {"cost": 42.0}

    job_list = db.list_jobs()
    assert len(job_list) == 1
    assert job_list[0]["job_id"] == "job-1"


def test_job_store_with_database_persistence(tmp_path):
    db = Database(tmp_path / "jobs.db")
    store = JobStore(db=db)

    entry = store.create(network_id="net-abc")
    assert entry.status == "queued"

    # Simulate synchronous solve
    store.run_sync(entry, lambda x: {"solved": x}, 99)
    assert entry.status == "done"
    assert entry.result == {"solved": 99}

    # Simulate server restart: new JobStore with same database recovers the job
    new_store = JobStore(db=db)
    recovered = new_store.get(entry.job_id)
    assert recovered.status == "done"
    assert recovered.result == {"solved": 99}


def test_optimization_worker_processing(tmp_path):
    db = Database(tmp_path / "worker.db")
    worker = OptimizationWorker(db=db)

    # Process job payload
    payload = {"job_id": "job-worker-1", "algorithm": "qpso", "stops": [1, 2, 3]}
    res = worker.process_job_payload(payload)

    assert res["status"] == "done"
    assert res["algorithm"] == "qpso"
    assert res["num_stops"] == 3

    # Check persistence
    saved = db.get_job("job-worker-1")
    assert saved is not None
    assert saved["status"] == "done"
    assert saved["result"]["algorithm"] == "qpso"

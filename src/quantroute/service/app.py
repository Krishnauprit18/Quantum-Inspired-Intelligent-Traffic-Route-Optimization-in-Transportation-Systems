"""FastAPI application (PDF Deliverable 4: "User interface or API").

Endpoints
---------
    GET  /                          landing page (links to the docs & a live map demo)
    GET  /health
    GET  /v1/algorithms
    POST /v1/networks               register a road network (grid | edges | geojson)
    GET  /v1/networks               list them
    GET  /v1/networks/{id}
    POST /v1/networks/{id}/traffic  apply live/simulated traffic -> a new weight epoch
    POST /v1/route                  traffic-aware shortest path between two nodes
    POST /v1/solve                  optimize a VRP (sync by default, or async -> job id)
    GET  /v1/solve/{job_id}
    GET  /v1/solve/{job_id}/map     the routes drawn on a Leaflet map (HTML)
    GET  /v1/solve/{job_id}/map.png

Interactive API docs are served at ``/docs``.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from starlette.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from quantroute import __version__
from quantroute.config import load_settings
from quantroute.encoding import RandomKeyGiantTour
from quantroute.evaluate import FitnessEvaluator
from quantroute.matrix import euclidean_matrix_2d
from quantroute.optimizers import OptimizerFactory, SearchProblem, TerminationCriteria
from quantroute.problem import ConstraintSet, Depot, Objective, ProblemSpec, Stop, Vehicle
from quantroute.repair import GreedyRepair
from quantroute.roadgraph import RoadGraphMatrix, from_edges, from_geojson, grid_city
from quantroute.routes import Route, Routes
from quantroute.security import require_api_key, security_middleware
from quantroute.service.models import (
    EdgeNetworkRequest,
    EpochInfo,
    GeoJSONNetworkRequest,
    GridNetworkRequest,
    NetworkInfo,
    NetworkRequest,
    RouteLeg,
    RouteRequest,
    RouteResponse,
    SolveRequest,
    SolveResult,
    TrafficUpdate,
)
from quantroute.service.state import JobStore, NetworkStore

_OBJECTIVES = {
    "travel-time": Objective.MIN_TRAVEL_TIME,
    "distance": Objective.MIN_DISTANCE,
    "makespan": Objective.MIN_MAKESPAN,
}
_SIZE_FIELD = {
    "qpso": "swarm_size",
    "pso": "swarm_size",
    "qgpso": "population_size",
    "ga": "population_size",
    "aco": "n_ants",
}
_SYNC_STOP_LIMIT = 60  # bigger problems must be submitted async


def create_app() -> FastAPI:
    settings = load_settings()
    networks = NetworkStore()
    jobs = JobStore()

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        yield
        jobs.shutdown()

    app = FastAPI(
        title="quantroute",
        version=__version__,
        description=__doc__,
        lifespan=lifespan,
        docs_url="/docs" if settings.docs_enabled else None,
        redoc_url=None,
        openapi_url="/openapi.json" if settings.docs_enabled else None,
        dependencies=[Depends(require_api_key(settings))],
    )
    app.state.networks = networks
    app.state.jobs = jobs
    app.state.settings = settings
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=list(settings.allowed_hosts))
    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(settings.cors_origins),
            allow_credentials=False,
            allow_methods=["GET", "POST"],
            allow_headers=["Content-Type", "X-API-Key", "X-Request-ID"],
        )

    @app.middleware("http")
    async def _secure(request: Request, call_next):
        return await security_middleware(request, call_next, settings)

    # -- misc ----------------------------------------------------

    @app.get("/", include_in_schema=False)
    def index() -> RedirectResponse:
        return RedirectResponse(url="/docs")

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok", "version": __version__}

    @app.get("/ready")
    def ready() -> dict:
        # Single-node readiness: configuration validated and worker store initialized.
        return {"status": "ready", "environment": settings.environment}

    @app.get("/v1/algorithms")
    def algorithms() -> list[str]:
        return OptimizerFactory.available()

    # -- networks ----------------------------------------------

    @app.post("/v1/networks", response_model=NetworkInfo, status_code=201)
    def register_network(req: NetworkRequest) -> NetworkInfo:
        try:
            graph = _build_graph(req)
        except Exception as exc:  # noqa: BLE001 - surface the loader error to the caller
            raise HTTPException(status_code=422, detail=str(exc)) from None
        entry = networks.add(req.name, graph, graph.coordinates())
        return _network_info(entry)

    @app.get("/v1/networks", response_model=list[NetworkInfo])
    def list_networks() -> list[NetworkInfo]:
        return [_network_info(e) for e in networks.list()]

    @app.get("/v1/networks/{network_id}", response_model=NetworkInfo)
    def get_network(network_id: str) -> NetworkInfo:
        return _network_info(_entry(networks, network_id))

    @app.post("/v1/networks/{network_id}/traffic", response_model=EpochInfo)
    def apply_traffic(network_id: str, update: TrafficUpdate) -> EpochInfo:
        entry = _entry(networks, network_id)
        try:
            epoch = entry.weights.update(
                congestion_factor=update.congestion_factor,
                edge_speeds_kph=update.edge_speeds_kph,
                unobserved_factor=update.unobserved_factor,
                source=update.source,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from None
        return EpochInfo(network_id=network_id, epoch_id=epoch.epoch_id, source=epoch.source)

    # -- routing -----------------------------------------------

    @app.post("/v1/route", response_model=RouteResponse)
    def route(req: RouteRequest) -> RouteResponse:
        entry = _entry(networks, req.network_id)
        epoch = entry.weights.current_epoch
        try:
            path = entry.graph.shortest_path(req.origin, req.destination, epoch.travel_time_s)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=422, detail=str(exc)) from None
        return RouteResponse(
            nodes=list(path.nodes),
            travel_time_s=path.travel_time_s,
            distance_m=path.distance_m,
            epoch_id=epoch.epoch_id,
        )

    # -- solve -----------------------------------------------

    @app.post("/v1/solve", response_model=SolveResult)
    def solve(req: SolveRequest) -> SolveResult:
        total_vehicles = sum(v.count for v in req.vehicles)
        if total_vehicles < 1:
            raise HTTPException(status_code=422, detail="need at least one vehicle")
        job = jobs.create()
        run_now = req.sync and len(req.stops) <= _SYNC_STOP_LIMIT
        if run_now:
            jobs.run_sync(job, _solve_to_dict, req, networks)
        else:
            jobs.submit(job, _solve_to_dict, req, networks)
        return _job_result(jobs.get(job.job_id))

    @app.get("/v1/solve/{job_id}", response_model=SolveResult)
    def get_job(job_id: str) -> SolveResult:
        return _job_result(_entry(jobs, job_id))

    @app.get("/v1/solve/{job_id}/map", response_class=HTMLResponse)
    def job_map(job_id: str) -> HTMLResponse:
        return HTMLResponse(_render_job_map(_entry(jobs, job_id), networks, fmt="html"))

    @app.get("/v1/solve/{job_id}/map.png")
    def job_map_png(job_id: str) -> Response:
        png = _render_job_map(_entry(jobs, job_id), networks, fmt="png")
        return Response(content=png, media_type="image/png")

    return app


# --------------------------------------------------------------------- helpers


def _entry(store, key: str):
    try:
        return store.get(key)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"{key!r} not found") from None


def _build_graph(req):
    if isinstance(req, GridNetworkRequest):
        return grid_city(
            req.rows, req.cols, spacing_m=req.spacing_m, arterial_every=req.arterial_every
        )
    if isinstance(req, EdgeNetworkRequest):
        nodes = {int(k): (float(x), float(y)) for k, (x, y) in req.nodes.items()}
        return from_edges(nodes, req.edges)
    if isinstance(req, GeoJSONNetworkRequest):
        return from_geojson(req.geojson)
    raise ValueError(f"unsupported network kind: {getattr(req, 'kind', '?')}")


def _network_info(entry) -> NetworkInfo:
    xs = [c[0] for c in entry.coords.values()]
    ys = [c[1] for c in entry.coords.values()]
    return NetworkInfo(
        network_id=entry.network_id,
        name=entry.name,
        nodes=entry.graph.num_nodes,
        edges=entry.graph.num_edges,
        bbox=(min(xs), min(ys), max(xs), max(ys)),
        current_epoch=entry.weights.current_epoch.epoch_id,
    )


def _solve_to_dict(req: SolveRequest, networks: NetworkStore) -> dict:
    problem, coords, depot_node, stop_node, graph, epoch = _assemble(req, networks)

    params: dict = {"seed": req.seed}
    algo = req.algorithm.strip().lower()
    if algo != "ortools":
        params["max_iterations"] = req.iterations
        if req.pop_size is not None:
            params[_SIZE_FIELD.get(algo, "swarm_size")] = req.pop_size
    elif req.time_budget_s is not None:
        params["time_limit_s"] = req.time_budget_s

    optimizer = OptimizerFactory.from_config({"algorithm": algo, "params": params})
    term = TerminationCriteria(max_iterations=req.iterations, time_budget_s=req.time_budget_s)
    result = optimizer.solve(problem, termination=term)

    bk = problem.best_known
    return {
        "algorithm": result.algorithm,
        "best_cost": result.best_cost,
        "best_known": bk,
        "gap_pct": (result.gap(bk) * 100.0) if (bk and bk > 0) else None,
        "feasible": result.feasible,
        "vehicles_used": result.metrics.vehicles_used,
        "iterations": result.iterations,
        "elapsed_s": result.elapsed_s,
        "stop_reason": result.stop_reason,
        "config_hash": result.config_hash,
        "routes": [
            {"vehicle": r.vehicle_id, "stops": list(r.stop_ids)}
            for r in result.routes
            if r.stop_ids
        ],
        "cost_breakdown": result.cost_breakdown,
        "convergence": [
            [rec.iteration, rec.elapsed_s, rec.incumbent_cost] for rec in result.convergence
        ],
        "_coords": {str(k): list(v) for k, v in coords.items()},
        "_depot_node": depot_node,
        "_stop_node": stop_node,
        "_network_id": req.network_id,
    }


def _assemble(req: SolveRequest, networks: NetworkStore):
    objective = _OBJECTIVES[req.objective]
    constraints = ConstraintSet(
        enforce_time_windows=req.enforce_time_windows, max_route_seconds=req.max_route_seconds
    )
    vehicles = tuple(
        Vehicle(f"{v.id}{i + 1}" if v.count > 1 else v.id, capacity=v.capacity, start_depot="depot")
        for v in req.vehicles
        for i in range(v.count)
    )

    if req.network_id is not None:
        entry = _entry(networks, req.network_id)
        depot_node = int(req.depot_node)
        stop_node = {s.id: int(s.node) for s in req.stops}
        matrix = RoadGraphMatrix(
            entry.graph, [depot_node, *stop_node.values()], entry.weights.current_epoch
        )
        coords = dict(entry.coords)  # full graph coords — the map draws real road paths
        graph, epoch = entry.graph, entry.weights.current_epoch
    else:
        depot_node = 0
        stop_node = {s.id: i + 1 for i, s in enumerate(req.stops)}
        ids = [0, *stop_node.values()]
        xs = [req.depot_x, *(s.x for s in req.stops)]
        ys = [req.depot_y, *(s.y for s in req.stops)]
        matrix = euclidean_matrix_2d(ids, xs, ys)
        coords = {i: (float(x), float(y)) for i, x, y in zip(ids, xs, ys, strict=False)}
        graph = epoch = None

    stops = tuple(
        Stop(
            id=s.id,
            node=stop_node[s.id],
            demand=s.demand,
            service_s=s.service_s,
            tw_open_s=s.tw_open_s,
            tw_close_s=float("inf") if s.tw_close_s is None else s.tw_close_s,
        )
        for s in req.stops
    )
    spec = ProblemSpec(
        name=req.network_id or "inline",
        depots=(Depot("depot", node=depot_node),),
        stops=stops,
        vehicles=vehicles,
        objective=objective,
        constraints=constraints,
    )
    encoding = RandomKeyGiantTour(spec, matrix)
    repair = GreedyRepair(spec, matrix) if req.repair else None
    evaluator = FitnessEvaluator(spec, matrix, encoding, repair=repair)
    problem = SearchProblem(spec, matrix, encoding, evaluator)
    return problem, coords, depot_node, stop_node, graph, epoch


def _job_result(entry) -> SolveResult:
    if entry.status != "done" or not entry.result:
        return SolveResult(job_id=entry.job_id, status=entry.status, error=entry.error)
    r = entry.result
    return SolveResult(
        job_id=entry.job_id,
        status="done",
        algorithm=r["algorithm"],
        best_cost=r["best_cost"],
        best_known=r["best_known"],
        gap_pct=r["gap_pct"],
        feasible=r["feasible"],
        vehicles_used=r["vehicles_used"],
        iterations=r["iterations"],
        elapsed_s=r["elapsed_s"],
        stop_reason=r["stop_reason"],
        config_hash=r["config_hash"],
        routes=[RouteLeg(vehicle=leg["vehicle"], stops=leg["stops"]) for leg in r["routes"]],
        cost_breakdown=r["cost_breakdown"],
        convergence=r["convergence"],
    )


def _render_job_map(entry, networks: NetworkStore, *, fmt: str):
    from io import BytesIO

    from quantroute.viz import render_map_html, render_map_png, routes_to_geojson

    if entry.status != "done" or not entry.result or not entry.result.get("routes"):
        raise HTTPException(status_code=409, detail=f"job is {entry.status} with no routes to draw")

    r = entry.result
    coords = {int(k): tuple(v) for k, v in r["_coords"].items()}
    routes = Routes(tuple(Route(leg["vehicle"], tuple(leg["stops"])) for leg in r["routes"]))

    graph = epoch = None
    if r.get("_network_id"):
        try:
            net = networks.get(r["_network_id"])
            graph, epoch = net.graph, net.weights.current_epoch
        except KeyError:
            pass

    fc = routes_to_geojson(
        routes, coords, r["_depot_node"], stop_node=r["_stop_node"], road_graph=graph, epoch=epoch
    )
    if fmt == "png":
        buf = BytesIO()
        render_map_png(fc, buf)
        return buf.getvalue()
    return render_map_html(fc, title=f"quantroute — {r.get('algorithm', 'routes')}")

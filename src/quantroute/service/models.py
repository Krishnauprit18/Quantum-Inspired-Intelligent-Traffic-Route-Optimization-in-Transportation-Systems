"""Request / response schemas for the HTTP service (pydantic v2)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator

# --------------------------------------------------------------------- networks


class GridNetworkRequest(BaseModel):
    name: str = "grid"
    kind: Literal["grid"] = "grid"
    rows: int = Field(default=8, ge=2, le=200)
    cols: int = Field(default=8, ge=2, le=200)
    spacing_m: float = Field(default=120.0, gt=0)
    arterial_every: int = Field(default=4, ge=2)


class EdgeNetworkRequest(BaseModel):
    name: str = "custom"
    kind: Literal["edges"] = "edges"
    nodes: dict[str, tuple[float, float]]  # node id -> (x, y)
    edges: list[dict]  # {u, v, length_m?, free_flow_s?, road_class?, oneway?}


class GeoJSONNetworkRequest(BaseModel):
    name: str = "geojson"
    kind: Literal["geojson"] = "geojson"
    geojson: dict


NetworkRequest = GridNetworkRequest | EdgeNetworkRequest | GeoJSONNetworkRequest


class NetworkInfo(BaseModel):
    network_id: str
    name: str
    nodes: int
    edges: int
    bbox: tuple[float, float, float, float]  # xmin, ymin, xmax, ymax
    current_epoch: int


class TrafficUpdate(BaseModel):
    """Apply live/simulated traffic to a network — a new weight epoch."""

    congestion_factor: dict[int, float] | None = None  # edge id -> multiplier on free-flow
    edge_speeds_kph: dict[int, float] | None = None
    unobserved_factor: float | None = Field(default=None, gt=0)
    source: str = "api"

    @model_validator(mode="after")
    def _need_something(self) -> TrafficUpdate:
        if not (self.congestion_factor or self.edge_speeds_kph or self.unobserved_factor):
            raise ValueError("provide congestion_factor, edge_speeds_kph, or unobserved_factor")
        return self


class EpochInfo(BaseModel):
    network_id: str
    epoch_id: int
    source: str


# --------------------------------------------------------------------- routing


class RouteRequest(BaseModel):
    network_id: str
    origin: int
    destination: int


class RouteResponse(BaseModel):
    nodes: list[int]
    travel_time_s: float
    distance_m: float
    epoch_id: int


# --------------------------------------------------------------------- solve


class StopSpec(BaseModel):
    id: str
    node: int | None = None  # required when solving on a network
    x: float | None = None  # required for an inline (coordinate) problem
    y: float | None = None
    demand: float = Field(default=0.0, ge=0)
    service_s: float = Field(default=0.0, ge=0)
    tw_open_s: float = Field(default=0.0, ge=0)
    tw_close_s: float | None = None  # None -> no upper bound


class VehicleSpec(BaseModel):
    id: str = "v"
    capacity: float = Field(gt=0)
    count: int = Field(default=1, ge=1, le=1000)


class SolveRequest(BaseModel):
    network_id: str | None = None
    depot_node: int | None = None
    depot_x: float | None = None
    depot_y: float | None = None
    stops: list[StopSpec] = Field(min_length=1)
    vehicles: list[VehicleSpec] = Field(min_length=1)

    algorithm: str = "qpso"
    iterations: int = Field(default=200, ge=1, le=100_000)
    time_budget_s: float | None = Field(default=None, gt=0)
    seed: int = 0
    pop_size: int | None = Field(default=None, ge=2)
    objective: Literal["travel-time", "distance", "makespan"] = "travel-time"
    enforce_time_windows: bool = False
    max_route_seconds: float | None = Field(default=None, gt=0)
    repair: bool = True
    sync: bool = True  # run now and return the result; else return a job id to poll

    @model_validator(mode="after")
    def _consistent(self) -> SolveRequest:
        on_network = self.network_id is not None
        if on_network:
            if self.depot_node is None:
                raise ValueError("depot_node is required when network_id is set")
            if any(s.node is None for s in self.stops):
                raise ValueError("every stop needs a 'node' when solving on a network")
        else:
            if self.depot_x is None or self.depot_y is None:
                raise ValueError("depot_x and depot_y are required for an inline problem")
            if any(s.x is None or s.y is None for s in self.stops):
                raise ValueError("every stop needs x and y for an inline problem")
        return self


class RouteLeg(BaseModel):
    vehicle: str
    stops: list[str]


class SolveResult(BaseModel):
    job_id: str
    status: Literal["queued", "running", "done", "failed"]
    algorithm: str | None = None
    best_cost: float | None = None
    best_known: float | None = None
    gap_pct: float | None = None
    feasible: bool | None = None
    vehicles_used: int | None = None
    iterations: int | None = None
    elapsed_s: float | None = None
    stop_reason: str | None = None
    config_hash: str | None = None
    routes: list[RouteLeg] | None = None
    cost_breakdown: dict[str, float] | None = None
    convergence: list[list[float]] | None = None  # [iteration, elapsed_s, incumbent_cost]
    error: str | None = None

"""Parser for CVRPLIB / TSPLIB capacitated-VRP instances (``.vrp``) and solutions (``.sol``).

Format reference: http://vrp.atd-lab.inf.puc-rio.br/  (Uchoa et al. "X" set, Augerat "A/B/P",
Golden, etc.). Only the capacitated VRP variant with ``EDGE_WEIGHT_TYPE : EUC_2D`` is
supported here — enough for the algorithm-core benchmarks in system-design.html §14.
``EXPLICIT`` weight matrices and time-window (``.vrptw``) instances are future work and are
rejected with a clear message rather than mis-parsed.

Design note — number of vehicles
--------------------------------
The ``.vrp`` file usually does *not* state the fleet size. We resolve it, in order:
  1. an explicit ``num_vehicles`` argument;
  2. a ``VEHICLES`` header line, if present;
  3. the ``-k<N>`` token in the instance name (e.g. ``X-n101-k25``);
  4. otherwise a lower bound, ``ceil(total_demand / capacity)``.
Which rule fired is recorded on ``CvrpInstance.num_vehicles_source`` so results are never
silently based on a guess.

Security / robustness
---------------------
* Input is treated as untrusted text: tokens are parsed only with ``int``/``float`` — no
  ``eval``/``exec``; every failure is re-raised as ``CVRPLIBParseError`` with a line number.
* File size is bounded (``max_bytes``) and instance dimension is bounded (``max_dimension``)
  before any array is allocated.
* Paths are resolved and checked to be regular files.
"""

from __future__ import annotations

import math
import os
import re
from dataclasses import dataclass
from pathlib import Path

from quantroute.matrix import DEFAULT_MAX_NODES, DenseCostMatrix, euclidean_matrix_2d
from quantroute.problem import (
    ConstraintSet,
    Depot,
    Objective,
    ProblemSpec,
    Stop,
    Vehicle,
)

# A .vrp instance is tiny (a few hundred KB at most); anything far larger is suspect.
DEFAULT_MAX_BYTES = 32 * 1024 * 1024
DEFAULT_MAX_DIMENSION = DEFAULT_MAX_NODES

_HEADER_KEYS = {
    "NAME",
    "COMMENT",
    "TYPE",
    "DIMENSION",
    "EDGE_WEIGHT_TYPE",
    "EDGE_WEIGHT_FORMAT",
    "CAPACITY",
    "VEHICLES",
    "DISPLAY_DATA_TYPE",
}
_SECTION_KEYS = {
    "NODE_COORD_SECTION",
    "DEMAND_SECTION",
    "DEPOT_SECTION",
    "EDGE_WEIGHT_SECTION",
    "SERVICE_TIME_SECTION",
    "DEPOT_LOCATION_SECTION",
}
_SUPPORTED_EDGE_WEIGHT_TYPE = "EUC_2D"


class CVRPLIBParseError(ValueError):
    """Raised when a ``.vrp`` / ``.sol`` file is malformed or uses an unsupported feature."""


@dataclass(frozen=True, slots=True)
class CvrpInstance:
    """A parsed instance: the routing problem plus its Euclidean cost matrix."""

    spec: ProblemSpec
    matrix: DenseCostMatrix
    depot_node: int
    capacity: float
    num_vehicles: int
    num_vehicles_source: str
    best_known: float | None
    comment: str
    coords: dict[int, tuple[float, float]]  # node id -> (x, y), for visualization


@dataclass(frozen=True, slots=True)
class SolutionFile:
    """A parsed ``.sol``: one route per line as node ids, plus the reported cost."""

    routes: tuple[tuple[int, ...], ...]
    cost: float | None

    @property
    def num_vehicles(self) -> int:
        return len(self.routes)


# --------------------------------------------------------------------------- helpers


def _resolve_readable_file(path: str | os.PathLike[str], *, max_bytes: int) -> Path:
    p = Path(path).expanduser()
    try:
        p = p.resolve(strict=True)
    except FileNotFoundError:
        raise FileNotFoundError(f"no such file: {path!r}") from None
    # PermissionError and other OSErrors propagate unchanged — they are not "not found".
    if not p.is_file():
        raise CVRPLIBParseError(f"{p} is not a regular file")
    size = p.stat().st_size
    if size > max_bytes:
        raise CVRPLIBParseError(
            f"{p.name} is {size} bytes, over the {max_bytes}-byte limit; "
            "raise max_bytes if this file is genuinely expected to be this large"
        )
    return p


def _read_lines(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8", errors="strict")
    return text.splitlines()


def _to_int(token: str, lineno: int, what: str) -> int:
    try:
        return int(token)
    except ValueError:
        raise CVRPLIBParseError(f"line {lineno}: expected integer for {what}, got {token!r}") from None


def _to_float(token: str, lineno: int, what: str) -> float:
    try:
        return float(token)
    except ValueError:
        raise CVRPLIBParseError(f"line {lineno}: expected number for {what}, got {token!r}") from None


def _to_finite_float(token: str, lineno: int, what: str) -> float:
    """Like :func:`_to_float` but also rejects ``nan`` / ``inf`` (``float()`` accepts both)."""
    value = _to_float(token, lineno, what)
    if not math.isfinite(value):
        raise CVRPLIBParseError(
            f"line {lineno}: {what} must be a finite number, got {token!r}"
        )
    return value


def _extract_best_known(comment: str) -> float | None:
    m = re.search(r"(?:optimal|best)\s+value\s*[:=]?\s*([0-9]+(?:\.[0-9]+)?)", comment, re.IGNORECASE)
    return float(m.group(1)) if m else None


def _vehicles_from_name(name: str) -> int | None:
    m = re.search(r"-k(\d+)", name, re.IGNORECASE)
    return int(m.group(1)) if m else None


# --------------------------------------------------------------------------- .vrp


def parse_vrp(
    path: str | os.PathLike[str],
    *,
    num_vehicles: int | None = None,
    objective: Objective = Objective.MIN_TRAVEL_TIME,
    constraints: ConstraintSet | None = None,
    time_budget_ms: int = 3000,
    max_bytes: int = DEFAULT_MAX_BYTES,
    max_dimension: int = DEFAULT_MAX_DIMENSION,
) -> CvrpInstance:
    """Parse a CVRPLIB ``.vrp`` file into a :class:`CvrpInstance`.

    Parameters mirror :class:`~quantroute.problem.ProblemSpec` fields that the file itself
    does not carry. ``num_vehicles`` overrides the resolution rules described in the module
    docstring.
    """
    p = _resolve_readable_file(path, max_bytes=max_bytes)
    lines = _read_lines(p)

    headers: dict[str, str] = {}
    coords: dict[int, tuple[float, float]] = {}
    demands: dict[int, float] = {}
    depot_nodes: list[int] = []

    section: str | None = None
    depot_section_closed = False

    for lineno, raw in enumerate(lines, start=1):
        line = raw.strip()
        if not line:
            continue

        keyword = line.split(":", 1)[0].strip().upper() if ":" in line else line.upper()

        if keyword == "EOF":
            break
        if keyword in _SECTION_KEYS:
            section = keyword
            continue
        if keyword in _HEADER_KEYS:
            _, _, value = line.partition(":")
            headers[keyword] = value.strip()
            continue

        if section is None:
            raise CVRPLIBParseError(
                f"line {lineno}: unexpected content outside any section: {line!r}"
            )

        tokens = line.split()
        if section == "NODE_COORD_SECTION":
            if len(tokens) < 3:
                raise CVRPLIBParseError(f"line {lineno}: expected 'id x y', got {line!r}")
            node = _to_int(tokens[0], lineno, "node id")
            x = _to_finite_float(tokens[1], lineno, "x")
            y = _to_finite_float(tokens[2], lineno, "y")
            if node in coords:
                raise CVRPLIBParseError(f"line {lineno}: duplicate coordinates for node {node}")
            coords[node] = (x, y)
            if len(coords) > max_dimension:
                raise CVRPLIBParseError(
                    f"NODE_COORD_SECTION has more than max_dimension={max_dimension} nodes"
                )
        elif section == "DEMAND_SECTION":
            if len(tokens) < 2:
                raise CVRPLIBParseError(f"line {lineno}: expected 'id demand', got {line!r}")
            node = _to_int(tokens[0], lineno, "node id")
            demand = _to_finite_float(tokens[1], lineno, "demand")
            if demand < 0:
                raise CVRPLIBParseError(f"line {lineno}: negative demand for node {node}")
            demands[node] = demand
            if len(demands) > max_dimension:
                raise CVRPLIBParseError(
                    f"DEMAND_SECTION has more than max_dimension={max_dimension} nodes"
                )
        elif section == "DEPOT_SECTION":
            for tok in tokens:
                val = _to_int(tok, lineno, "depot id")
                if val == -1:
                    depot_section_closed = True
                    break
                depot_nodes.append(val)
        elif section in ("EDGE_WEIGHT_SECTION", "SERVICE_TIME_SECTION", "DEPOT_LOCATION_SECTION"):
            raise CVRPLIBParseError(
                f"line {lineno}: section {section} is not supported yet"
            )

    _require(headers, "TYPE")
    inst_type = headers["TYPE"].upper()
    if inst_type != "CVRP":
        raise CVRPLIBParseError(f"unsupported instance TYPE {inst_type!r}; only CVRP is handled")

    _require(headers, "EDGE_WEIGHT_TYPE")
    ewt = headers["EDGE_WEIGHT_TYPE"].upper()
    if ewt != _SUPPORTED_EDGE_WEIGHT_TYPE:
        raise CVRPLIBParseError(
            f"unsupported EDGE_WEIGHT_TYPE {ewt!r}; only {_SUPPORTED_EDGE_WEIGHT_TYPE} is handled"
        )

    _require(headers, "DIMENSION")
    dimension = _to_int(headers["DIMENSION"], 0, "DIMENSION")
    if not 2 <= dimension <= max_dimension:
        raise CVRPLIBParseError(
            f"DIMENSION {dimension} outside supported range [2, {max_dimension}]"
        )

    _require(headers, "CAPACITY")
    capacity = _to_finite_float(headers["CAPACITY"], 0, "CAPACITY")
    if capacity <= 0:
        raise CVRPLIBParseError(f"CAPACITY must be > 0, got {capacity}")

    name = headers.get("NAME", p.stem).strip() or p.stem
    comment = headers.get("COMMENT", "").strip()

    # --- structural validation -------------------------------------------------
    if len(coords) != dimension:
        raise CVRPLIBParseError(
            f"NODE_COORD_SECTION has {len(coords)} nodes, DIMENSION says {dimension}"
        )
    if len(demands) != dimension:
        raise CVRPLIBParseError(
            f"DEMAND_SECTION has {len(demands)} nodes, DIMENSION says {dimension}"
        )
    if set(coords) != set(demands):
        raise CVRPLIBParseError("node ids in NODE_COORD_SECTION and DEMAND_SECTION differ")
    if not depot_nodes:
        raise CVRPLIBParseError("DEPOT_SECTION lists no depot")
    if not depot_section_closed:
        raise CVRPLIBParseError("DEPOT_SECTION is not terminated by -1")
    if len(depot_nodes) != 1:
        raise CVRPLIBParseError(
            f"only single-depot CVRP is supported, file lists {len(depot_nodes)} depots"
        )
    depot_node = depot_nodes[0]
    if depot_node not in coords:
        raise CVRPLIBParseError(f"depot node {depot_node} has no coordinates")
    if demands.get(depot_node, 0.0) != 0.0:
        raise CVRPLIBParseError(f"depot node {depot_node} has non-zero demand")

    # --- cost matrix ---------------------------------------------------------
    ordered_nodes = sorted(coords)
    xs = [coords[n][0] for n in ordered_nodes]
    ys = [coords[n][1] for n in ordered_nodes]
    matrix = euclidean_matrix_2d(ordered_nodes, xs, ys, round_to_int=True)

    # --- fleet size --------------------------------------------------------
    total_demand = sum(demands[n] for n in ordered_nodes)
    resolved, source = _resolve_fleet_size(
        explicit=num_vehicles,
        header_value=headers.get("VEHICLES"),
        name=name,
        total_demand=total_demand,
        capacity=capacity,
    )

    # --- build ProblemSpec -------------------------------------------------
    depot = Depot(id="depot", node=depot_node)
    stops = tuple(
        Stop(id=f"c{n}", node=n, demand=demands[n])
        for n in ordered_nodes
        if n != depot_node
    )
    vehicles = tuple(
        Vehicle(id=f"v{i + 1}", capacity=capacity, start_depot="depot")
        for i in range(resolved)
    )
    spec = ProblemSpec(
        name=name,
        depots=(depot,),
        stops=stops,
        vehicles=vehicles,
        objective=objective,
        constraints=constraints or ConstraintSet(),
        time_budget_ms=time_budget_ms,
    )

    return CvrpInstance(
        spec=spec,
        matrix=matrix,
        depot_node=depot_node,
        capacity=capacity,
        num_vehicles=resolved,
        num_vehicles_source=source,
        best_known=_extract_best_known(comment),
        comment=comment,
        coords={int(n): (float(coords[n][0]), float(coords[n][1])) for n in ordered_nodes},
    )


def _require(headers: dict[str, str], key: str) -> None:
    if key not in headers:
        raise CVRPLIBParseError(f"missing required header {key}")


def _resolve_fleet_size(
    *,
    explicit: int | None,
    header_value: str | None,
    name: str,
    total_demand: float,
    capacity: float,
) -> tuple[int, str]:
    lower_bound = max(1, math.ceil(total_demand / capacity))

    if explicit is not None:
        if explicit < lower_bound:
            raise CVRPLIBParseError(
                f"num_vehicles={explicit} cannot serve total demand {total_demand:g} "
                f"with capacity {capacity:g} (need at least {lower_bound})"
            )
        return explicit, "explicit argument"

    if header_value is not None:
        try:
            v = int(header_value)
        except ValueError:
            raise CVRPLIBParseError(f"VEHICLES header is not an integer: {header_value!r}") from None
        if v < lower_bound:
            raise CVRPLIBParseError(
                f"VEHICLES={v} below capacity lower bound {lower_bound}"
            )
        return v, "VEHICLES header"

    from_name = _vehicles_from_name(name)
    if from_name is not None:
        if from_name < lower_bound:
            raise CVRPLIBParseError(
                f"name implies k={from_name} but capacity lower bound is {lower_bound}"
            )
        return from_name, f"name token -k{from_name}"

    return lower_bound, f"capacity lower bound ceil({total_demand:g}/{capacity:g})"


# --------------------------------------------------------------------------- .sol


def parse_sol(
    path: str | os.PathLike[str],
    *,
    max_bytes: int = DEFAULT_MAX_BYTES,
) -> SolutionFile:
    """Parse a CVRPLIB ``.sol`` file (``Route #k: a b c`` lines plus an optional ``Cost``)."""
    p = _resolve_readable_file(path, max_bytes=max_bytes)
    routes: list[tuple[int, ...]] = []
    cost: float | None = None

    for lineno, raw in enumerate(p.read_text(encoding="utf-8", errors="strict").splitlines(), 1):
        line = raw.strip()
        if not line:
            continue
        low = line.lower()
        if low.startswith("route"):
            _, _, rest = line.partition(":")
            if not rest.strip():
                routes.append(())
                continue
            nodes = tuple(_to_int(tok, lineno, "route node") for tok in rest.split())
            routes.append(nodes)
        elif low.startswith("cost"):
            cost = _to_finite_float(line.split()[-1], lineno, "cost")
        # anything else (e.g. a trailing comment) is ignored on purpose

    if not routes:
        raise CVRPLIBParseError(f"{p.name}: no 'Route #k:' lines found")
    return SolutionFile(routes=tuple(routes), cost=cost)


def load_cvrplib(
    vrp_path: str | os.PathLike[str],
    sol_path: str | os.PathLike[str] | None = None,
    **parse_vrp_kwargs,
) -> tuple[CvrpInstance, SolutionFile | None]:
    """Convenience: parse a ``.vrp`` and, if given (or found next to it), its ``.sol``.

    If ``sol_path`` is omitted, a sibling file with the same stem and ``.sol`` suffix is
    used when it exists. A ``.sol`` cost fills in ``best_known`` when the ``.vrp`` comment
    did not carry one.
    """
    instance = parse_vrp(vrp_path, **parse_vrp_kwargs)

    if sol_path is None:
        candidate = Path(vrp_path).expanduser().with_suffix(".sol")
        sol_path = candidate if candidate.is_file() else None

    if sol_path is None:
        return instance, None

    solution = parse_sol(sol_path)
    if instance.best_known is None and solution.cost is not None:
        instance = _with_best_known(instance, solution.cost)
    return instance, solution


def _with_best_known(instance: CvrpInstance, best_known: float) -> CvrpInstance:
    return CvrpInstance(
        spec=instance.spec,
        matrix=instance.matrix,
        depot_node=instance.depot_node,
        capacity=instance.capacity,
        num_vehicles=instance.num_vehicles,
        num_vehicles_source=instance.num_vehicles_source,
        best_known=best_known,
        comment=instance.comment,
        coords=instance.coords,
    )

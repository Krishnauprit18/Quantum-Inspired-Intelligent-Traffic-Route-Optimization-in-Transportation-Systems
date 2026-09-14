"""Instance loaders for quantroute.

Currently: CVRPLIB / TSPLIB ``.vrp`` capacitated-VRP instances and their ``.sol`` files.
Road-network import (OSM -> PostGIS) lands here later as a separate module.
"""

from quantroute.io.cvrplib import (
    CvrpInstance,
    CVRPLIBParseError,
    SolutionFile,
    load_cvrplib,
    parse_sol,
    parse_vrp,
)

__all__ = [
    "CvrpInstance",
    "CVRPLIBParseError",
    "SolutionFile",
    "load_cvrplib",
    "parse_sol",
    "parse_vrp",
]

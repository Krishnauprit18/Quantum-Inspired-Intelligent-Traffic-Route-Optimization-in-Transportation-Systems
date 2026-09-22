"""HTTP service for quantroute (PDF Deliverable 4).

from quantroute.service import create_app
app = create_app()          # an ASGI app; run with `uvicorn` or `quantroute serve`
"""

from quantroute.service.app import create_app

__all__ = ["create_app"]

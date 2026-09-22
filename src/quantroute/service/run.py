"""Uvicorn entrypoint used by the container and local production deployment."""

from __future__ import annotations

import os

import uvicorn


def main() -> None:
    uvicorn.run(
        "quantroute.service:create_app",
        factory=True,
        host=os.getenv("QUANTROUTE_HOST", "127.0.0.1"),
        port=int(os.getenv("QUANTROUTE_PORT", "8000")),
        proxy_headers=True,
        forwarded_allow_ips=os.getenv("QUANTROUTE_FORWARDED_ALLOW_IPS", "127.0.0.1"),
        access_log=True,
    )


if __name__ == "__main__":
    main()

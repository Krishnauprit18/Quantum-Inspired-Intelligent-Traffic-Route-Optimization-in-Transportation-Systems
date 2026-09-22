"""Centralized runtime configuration.

Configuration is environment-driven so secrets never need to live in source control.
The defaults are intentionally developer-friendly. Production mode fails closed when
security-critical settings are missing.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


def _bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _csv(name: str, default: str) -> tuple[str, ...]:
    raw = os.getenv(name, default)
    return tuple(v.strip() for v in raw.split(",") if v.strip())


@dataclass(frozen=True, slots=True)
class Settings:
    environment: str
    api_key: str | None
    auth_enabled: bool
    allowed_hosts: tuple[str, ...]
    cors_origins: tuple[str, ...]
    max_request_bytes: int
    docs_enabled: bool
    log_level: str

    @property
    def production(self) -> bool:
        return self.environment.lower() in {"production", "prod"}

    def validate(self) -> None:
        if self.production:
            if not self.auth_enabled:
                raise RuntimeError("QUANTROUTE_AUTH_ENABLED must be true in production")
            if not self.api_key or len(self.api_key) < 32:
                raise RuntimeError(
                    "QUANTROUTE_API_KEY must be at least 32 characters in production"
                )
            if not self.allowed_hosts or "*" in self.allowed_hosts:
                raise RuntimeError("QUANTROUTE_ALLOWED_HOSTS must be explicit in production")


def load_settings() -> Settings:
    environment = os.getenv("QUANTROUTE_ENV", "development")
    production = environment.lower() in {"production", "prod"}
    settings = Settings(
        environment=environment,
        api_key=os.getenv("QUANTROUTE_API_KEY"),
        auth_enabled=_bool("QUANTROUTE_AUTH_ENABLED", production),
        allowed_hosts=_csv("QUANTROUTE_ALLOWED_HOSTS", "localhost,127.0.0.1,testserver"),
        cors_origins=_csv("QUANTROUTE_CORS_ORIGINS", ""),
        max_request_bytes=int(os.getenv("QUANTROUTE_MAX_REQUEST_BYTES", "2097152")),
        docs_enabled=_bool("QUANTROUTE_DOCS_ENABLED", not production),
        log_level=os.getenv("QUANTROUTE_LOG_LEVEL", "INFO").upper(),
    )
    settings.validate()
    return settings

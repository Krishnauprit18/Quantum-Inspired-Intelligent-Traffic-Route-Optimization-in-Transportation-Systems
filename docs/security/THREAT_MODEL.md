# Quantroute threat model (production foundation)

## Assets
Routing requests/results, road-network data, operational availability, solver configuration, API credentials, and auditability of optimization decisions.

## Trust boundaries
1. Browser/CLI to HTTP API.
2. Reverse proxy / host networking to application process.
3. Application process to future persistence/routing services.
4. Source repository and CI supply chain.

## Primary threats and controls
- **Unauthorized API use:** production fails closed unless API-key authentication is enabled; constant-time comparison; health/readiness remain public.
- **Secret leakage:** environment-only secrets, `.env` ignored, Gitleaks pre-commit/CI.
- **Dependency compromise:** bounded dependency ranges plus `pip-audit`; production builds should additionally pin hashes in a generated lock file before release.
- **Malicious/oversized input:** Pydantic validation and request-size cap.
- **Host-header abuse:** explicit TrustedHost allow-list in production.
- **Browser abuse/clickjacking:** restrictive security headers, CORS disabled unless explicitly configured.
- **Container escape/blast radius:** non-root UID, read-only filesystem, all Linux capabilities dropped, `no-new-privileges`.
- **Stale/insecure debugging surface:** OpenAPI docs disabled by default in production.
- **Non-reproducible optimization:** algorithm, seed, config hash and convergence metadata are retained by solver results.

## Residual risks before field deployment
The current API state store is still single-process/in-memory. Authentication is service-level API-key auth rather than per-user RBAC. TLS termination, durable persistence, centralized audit logging, backup/restore, driver identities, GPS ingestion, and external routing-engine hardening must be completed for a real fleet rollout. A professional penetration test and environment-specific risk assessment remain release gates.

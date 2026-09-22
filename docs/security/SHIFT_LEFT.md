# Shift-left secure engineering policy

This repository treats security controls as build-time requirements rather than a final penetration-test phase.

## Development gates
1. **Design:** threat model and abuse cases updated with every new trust boundary.
2. **Commit:** Ruff + Gitleaks pre-commit hooks.
3. **Pull request:** unit/integration tests, coverage, Bandit SAST, dependency audit, secret scanning.
4. **Build:** minimal non-root container; no embedded secrets; read-only runtime filesystem.
5. **Release:** immutable version/tag, SBOM + image vulnerability scan, signed release artifact where available.
6. **Deploy:** production configuration validation, restricted host binding, disabled docs, strong API key, backup and restore verification.
7. **Operate:** patch cadence, vulnerability triage, incident response and access review.

## Standards mapping
- NIST SP 800-218 SSDF: secure preparation, protected software, well-secured development, vulnerability response.
- OWASP ASVS: authentication, validation, API/session/configuration and error-handling controls used as verification requirements.
- OWASP SAMM: governance, design, implementation, verification and operations maturity model.
- CIS-style container hardening principles: least privilege, non-root execution, dropped capabilities and immutable filesystem.

The standards are used as engineering baselines, not as a claim of formal certification.

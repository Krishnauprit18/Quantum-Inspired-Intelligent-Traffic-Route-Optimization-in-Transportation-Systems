# QuantRoute Jenkins pipeline

This directory contains the Jenkins automation for the local
`production-foundation` branch. Floci supplies local AWS-compatible endpoints;
the learning target is the AWS and DevOps workflow, not the emulator itself.

## Pipeline contract

The pipeline checks out the repository, creates an isolated CI virtual
environment, validates Floci resources, runs quality and security gates, builds
the non-root image, scans source and image, creates two SBOM formats, and
archives evidence. Publishing, signing, Terraform, Helm, approval, deployment,
and smoke tests are guarded by explicit parameters.

Trivy archives the complete HIGH/CRITICAL filesystem and image SARIF reports.
The release gate uses `--ignore-unfixed`, so it fails on actionable
HIGH/CRITICAL findings with an available vendor fix while retaining no-fix
findings for review instead of silently hiding them.

The first safe run uses:

```text
PUBLISH_IMAGE=false
SIGN_PROVENANCE=false
DEPLOY_TO_FLOCI_EKS=false
```

The pipeline polls the configured SCM branch every five minutes. This is the
automatic trigger for a local Jenkins instance; a GitHub webhook can be added
later when Jenkins has a reachable HTTPS URL. Deployment is never automatic:
the deployment parameter must be enabled and the `Deploy` approval must be
accepted after all gates pass.

## Required Jenkins credentials

Create this credential before running the job:

```text
Kind: Username with password
ID: quantroute-floci-aws
Username: test
Password: test
```

These are local Floci-compatible lab values, not real AWS credentials.

Image signing additionally requires:

```text
quantroute-cosign-private-key  Secret file
quantroute-cosign-public-key   Secret file
quantroute-cosign-password     Secret text
```

Never commit those files or their contents.

## Jenkins job

Use **Pipeline script from SCM**:

```text
Repository: https://github.com/Krishnauprit18/Quantum-Inspired-Intelligent-Traffic-Route-Optimization-in-Transportation-Systems.git
Branch: */production-foundation
Script path: Jenkinsfile
```

`seed-job.groovy` requires the Jenkins Job DSL plugin. It is an optional,
repeatable way to create the same pipeline job; it does not replace credential
setup.

For the current single-branch job, configure the SCM branch as
`*/production-foundation`. The first build creates the pipeline trigger from
the `Jenkinsfile`; the next SCM change is then picked up by polling.

## Security boundary

The Jenkins agent currently has Docker socket access so Trivy, Syft, and the
local image build can operate. This is a trusted-agent boundary and must be
isolated in a real shared Jenkins installation. AWS-compatible credentials are
bound only around stages that need them.

## Evidence

The build archives test reports, coverage, Bandit, pip-audit, Gitleaks, Trivy,
SBOM, image reference/digest, deployment, and smoke-test evidence under
`artifacts/`.

## Floci ECR and Cosign behavior

The publish script obtains the repository URI from the ECR control plane and
uses only its registry host for `docker login`. The complete URI is used for
the immutable image tag and is stored with the digest. This is important for
Floci because its ECR repository URI is an AWS-shaped loopback hostname.

The optional local signing stage uses the pinned Cosign container with the
HTTP/insecure-registry flags and disables public transparency-log upload. This
is deliberate for the local Floci lab; a real AWS/TLS pipeline should remove
those flags, use a managed signing key, and enable transparency-log policy.

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

The first safe run uses:

```text
PUBLISH_IMAGE=false
SIGN_PROVENANCE=false
DEPLOY_TO_FLOCI_EKS=false
```

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

## Security boundary

The Jenkins agent currently has Docker socket access so Trivy, Syft, and the
local image build can operate. This is a trusted-agent boundary and must be
isolated in a real shared Jenkins installation. AWS-compatible credentials are
bound only around stages that need them.

## Evidence

The build archives test reports, coverage, Bandit, pip-audit, Gitleaks, Trivy,
SBOM, image reference/digest, deployment, and smoke-test evidence under
`artifacts/`.

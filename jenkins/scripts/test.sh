#!/usr/bin/env bash
set -Eeuo pipefail

CI_VENV="${CI_VENV:-.ci-venv}"
ARTIFACT_DIR="${ARTIFACT_DIR:-artifacts}"
mkdir -p "$ARTIFACT_DIR"

echo '===== RUFF LINT ====='
"$CI_VENV/bin/ruff" check src tests

echo '===== RUFF FORMAT ====='
"$CI_VENV/bin/ruff" format --check src tests

echo '===== PYTEST ====='
"$CI_VENV/bin/pytest" \
    --cov=quantroute \
    --cov-report=term-missing \
    --cov-report=xml:"$ARTIFACT_DIR/coverage.xml" \
    --junitxml="$ARTIFACT_DIR/junit.xml"

echo 'Quality and tests: PASS'

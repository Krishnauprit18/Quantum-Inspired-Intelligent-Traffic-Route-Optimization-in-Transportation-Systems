#!/usr/bin/env bash
set -Eeuo pipefail

BASE_URL="${QUANTROUTE_BASE_URL:-http://127.0.0.1:8000}"
REQUIRE_AUTH_SMOKE="${REQUIRE_AUTH_SMOKE:-true}"

echo '===== HEALTH ====='
curl --fail --silent --show-error "$BASE_URL/health"
printf '\n'

echo '===== READINESS ====='
curl --fail --silent --show-error "$BASE_URL/ready"
printf '\n'

if [[ -n "${QUANTROUTE_API_KEY:-}" ]]; then
    echo '===== AUTHENTICATED API ====='
    curl --fail --silent --show-error \
        -H "X-API-Key: $QUANTROUTE_API_KEY" \
        "$BASE_URL/v1/algorithms"
    printf '\n'
elif [[ "$REQUIRE_AUTH_SMOKE" == 'true' ]]; then
    echo 'Authenticated smoke test cannot run: QUANTROUTE_API_KEY is missing.' >&2
    exit 1
fi

echo 'Smoke test: PASS'

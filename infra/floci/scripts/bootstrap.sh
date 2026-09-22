#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
COMPOSE_FILE="$ROOT_DIR/infra/floci/compose.yaml"

if ! docker info >/dev/null 2>&1; then
  echo "Docker daemon is not accessible for the current user." >&2
  echo "Check Docker socket permissions before continuing." >&2
  exit 1
fi

docker compose -f "$COMPOSE_FILE" config --quiet
docker compose -f "$COMPOSE_FILE" up -d

for attempt in $(seq 1 30); do
  if "$ROOT_DIR/infra/floci/scripts/floci-health.sh" >/dev/null 2>&1; then
    "$ROOT_DIR/infra/floci/scripts/smoke-test.sh"
    exit 0
  fi
  sleep 2
done

echo "Floci did not become healthy within 60 seconds." >&2
docker compose -f "$COMPOSE_FILE" ps >&2 || true
docker compose -f "$COMPOSE_FILE" logs --tail 80 >&2 || true
exit 1

#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
# shellcheck source=/dev/null
source "$ROOT_DIR/infra/floci/scripts/floci-env.sh"

if ! curl --fail --silent --show-error \
  "$AWS_ENDPOINT_URL/_floci/health" >/dev/null; then
  echo "Floci health: FAIL ($AWS_ENDPOINT_URL)" >&2
  exit 1
fi

aws_floci sts get-caller-identity >/dev/null
echo "Floci health: PASS"
echo "AWS endpoint: $AWS_ENDPOINT_URL"
echo "AWS region: $AWS_DEFAULT_REGION"

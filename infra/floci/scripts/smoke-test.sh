#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"

"$ROOT_DIR/infra/floci/scripts/floci-health.sh"
"$ROOT_DIR/infra/floci/init/create-s3.sh"
"$ROOT_DIR/infra/floci/init/create-ecr.sh"
"$ROOT_DIR/infra/floci/init/create-sqs.sh"
"$ROOT_DIR/infra/floci/init/create-iam.sh"
"$ROOT_DIR/infra/floci/init/create-secrets.sh"

echo "D0 smoke tests: PASS"

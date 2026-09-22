#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
# shellcheck source=/dev/null
source "$ROOT_DIR/infra/floci/scripts/floci-env.sh"

if aws_floci ecr describe-repositories \
  --repository-names "$QUANTROUTE_FLOCI_ECR_REPOSITORY" >/dev/null 2>&1; then
  echo "ECR repository already exists: $QUANTROUTE_FLOCI_ECR_REPOSITORY"
else
  aws_floci ecr create-repository \
    --repository-name "$QUANTROUTE_FLOCI_ECR_REPOSITORY" >/dev/null
  echo "Created ECR repository: $QUANTROUTE_FLOCI_ECR_REPOSITORY"
fi

aws_floci ecr describe-repositories \
  --repository-names "$QUANTROUTE_FLOCI_ECR_REPOSITORY" >/dev/null
echo "ECR verification: PASS"

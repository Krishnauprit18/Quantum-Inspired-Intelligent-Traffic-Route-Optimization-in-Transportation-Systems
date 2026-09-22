#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
# shellcheck source=/dev/null
source "$ROOT_DIR/infra/floci/scripts/floci-env.sh"

if aws_floci s3api head-bucket --bucket "$QUANTROUTE_FLOCI_S3_BUCKET" >/dev/null 2>&1; then
  echo "S3 bucket already exists: $QUANTROUTE_FLOCI_S3_BUCKET"
else
  aws_floci s3api create-bucket --bucket "$QUANTROUTE_FLOCI_S3_BUCKET" >/dev/null
  echo "Created S3 bucket: $QUANTROUTE_FLOCI_S3_BUCKET"
fi

aws_floci s3api head-bucket --bucket "$QUANTROUTE_FLOCI_S3_BUCKET" >/dev/null
echo "S3 verification: PASS"

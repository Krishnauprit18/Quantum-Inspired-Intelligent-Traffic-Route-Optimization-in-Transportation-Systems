#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
# shellcheck source=/dev/null
source "$ROOT_DIR/infra/floci/scripts/floci-env.sh"

if aws_floci secretsmanager describe-secret --secret-id "$QUANTROUTE_FLOCI_SECRET" >/dev/null 2>&1; then
  echo "Secret already exists: $QUANTROUTE_FLOCI_SECRET"
else
  secret_value="$(python3 -c 'import secrets; print(secrets.token_hex(24))')"
  aws_floci secretsmanager create-secret \
    --name "$QUANTROUTE_FLOCI_SECRET" \
    --secret-string "{\"local_api_key\":\"$secret_value\"}" >/dev/null
  unset secret_value
  echo "Created local Secrets Manager entry: $QUANTROUTE_FLOCI_SECRET"
fi

aws_floci secretsmanager describe-secret --secret-id "$QUANTROUTE_FLOCI_SECRET" >/dev/null
echo "Secrets Manager verification: PASS"

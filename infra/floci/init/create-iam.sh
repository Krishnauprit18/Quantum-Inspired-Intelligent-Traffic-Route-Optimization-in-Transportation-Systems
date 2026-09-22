#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
# shellcheck source=/dev/null
source "$ROOT_DIR/infra/floci/scripts/floci-env.sh"

trust_policy="$ROOT_DIR/infra/floci/init/worker-trust-policy.json"

if aws_floci iam get-role --role-name "$QUANTROUTE_FLOCI_IAM_ROLE" >/dev/null 2>&1; then
  echo "IAM role already exists: $QUANTROUTE_FLOCI_IAM_ROLE"
else
  aws_floci iam create-role \
    --role-name "$QUANTROUTE_FLOCI_IAM_ROLE" \
    --assume-role-policy-document "file://$trust_policy" >/dev/null
  echo "Created IAM role: $QUANTROUTE_FLOCI_IAM_ROLE"
fi

aws_floci iam get-role --role-name "$QUANTROUTE_FLOCI_IAM_ROLE" >/dev/null
aws_floci sts get-caller-identity >/dev/null
echo "IAM/STS verification: PASS"

#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
# shellcheck source=/dev/null
source "$ROOT_DIR/infra/floci/scripts/floci-env.sh"

get_or_create_queue() {
  local queue_name="$1"
  local queue_url

  if queue_url="$(aws_floci sqs get-queue-url --queue-name "$queue_name" --query QueueUrl --output text 2>/dev/null)"; then
    printf '%s\n' "$queue_url"
    return
  fi

  aws_floci sqs create-queue --queue-name "$queue_name" >/dev/null
  aws_floci sqs get-queue-url --queue-name "$queue_name" --query QueueUrl --output text
}

dlq_url="$(get_or_create_queue "$QUANTROUTE_FLOCI_SQS_DLQ")"
dlq_arn="$(aws_floci sqs get-queue-attributes \
  --queue-url "$dlq_url" \
  --attribute-names QueueArn \
  --query 'Attributes.QueueArn' \
  --output text)"

attributes_file="$(mktemp)"
trap 'rm -f "$attributes_file"' EXIT
printf \
  '{"RedrivePolicy":"{\\"deadLetterTargetArn\\":\\"%s\\",\\"maxReceiveCount\\":\\"3\\"}"}\n' \
  "$dlq_arn" >"$attributes_file"

if aws_floci sqs get-queue-url --queue-name "$QUANTROUTE_FLOCI_SQS_QUEUE" >/dev/null 2>&1; then
  echo "SQS queue already exists: $QUANTROUTE_FLOCI_SQS_QUEUE"
else
  aws_floci sqs create-queue \
    --queue-name "$QUANTROUTE_FLOCI_SQS_QUEUE" \
    --attributes "file://$attributes_file" >/dev/null
  echo "Created SQS queue: $QUANTROUTE_FLOCI_SQS_QUEUE"
fi

aws_floci sqs get-queue-url --queue-name "$QUANTROUTE_FLOCI_SQS_QUEUE" >/dev/null
aws_floci sqs get-queue-url --queue-name "$QUANTROUTE_FLOCI_SQS_DLQ" >/dev/null
echo "SQS verification: PASS"

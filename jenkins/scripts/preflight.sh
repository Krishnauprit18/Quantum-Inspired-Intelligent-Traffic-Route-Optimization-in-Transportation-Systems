#!/usr/bin/env bash
set -Eeuo pipefail

: "${AWS_ENDPOINT_URL:?AWS_ENDPOINT_URL is required}"
: "${AWS_DEFAULT_REGION:?AWS_DEFAULT_REGION is required}"
: "${FLOCI_ECR_REPOSITORY:?FLOCI_ECR_REPOSITORY is required}"
: "${FLOCI_S3_BUCKET:?FLOCI_S3_BUCKET is required}"
: "${FLOCI_SQS_QUEUE:?FLOCI_SQS_QUEUE is required}"

ARTIFACT_DIR="${ARTIFACT_DIR:-artifacts}"
mkdir -p "$ARTIFACT_DIR"

required_commands=(python3 docker aws terraform kubectl helm curl)

echo '===== TOOL CHECK ====='
for command in "${required_commands[@]}"; do
    command -v "$command"
done

echo '===== DOCKER CHECK ====='
docker info >/dev/null

echo '===== FLOCi HEALTH ====='
curl --fail --silent --show-error "$AWS_ENDPOINT_URL/_floci/health" >/dev/null

echo '===== STS CHECK ====='
aws --endpoint-url "$AWS_ENDPOINT_URL" sts get-caller-identity >/dev/null

echo '===== S3 CHECK ====='
aws --endpoint-url "$AWS_ENDPOINT_URL" s3api head-bucket --bucket "$FLOCI_S3_BUCKET"

echo '===== ECR CHECK ====='
aws --endpoint-url "$AWS_ENDPOINT_URL" ecr describe-repositories \
    --repository-names "$FLOCI_ECR_REPOSITORY" \
    --query 'repositories[0].repositoryUri' \
    --output text | tee "$ARTIFACT_DIR/ecr-uri.txt"

echo '===== SQS CHECK ====='
aws --endpoint-url "$AWS_ENDPOINT_URL" sqs get-queue-url \
    --queue-name "$FLOCI_SQS_QUEUE" >/dev/null

echo 'Environment preflight: PASS'

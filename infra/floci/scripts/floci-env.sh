#!/usr/bin/env bash
# Source this file in the current shell. These are local AWS-compatible
# connection settings, not real AWS credentials.

export AWS_ENDPOINT_URL="${AWS_ENDPOINT_URL:-http://127.0.0.1:4566}"
export AWS_DEFAULT_REGION="${AWS_DEFAULT_REGION:-us-east-1}"
export AWS_REGION="${AWS_REGION:-$AWS_DEFAULT_REGION}"
export AWS_ACCESS_KEY_ID="${AWS_ACCESS_KEY_ID:-test}"
export AWS_SECRET_ACCESS_KEY="${AWS_SECRET_ACCESS_KEY:-test}"
export AWS_EC2_METADATA_DISABLED="true"
export AWS_PAGER=""

export QUANTROUTE_FLOCI_ECR_REPOSITORY="${QUANTROUTE_FLOCI_ECR_REPOSITORY:-quantroute/api}"
export QUANTROUTE_FLOCI_S3_BUCKET="${QUANTROUTE_FLOCI_S3_BUCKET:-quantroute-artifacts-local}"
export QUANTROUTE_FLOCI_SQS_QUEUE="${QUANTROUTE_FLOCI_SQS_QUEUE:-quantroute-optimization-jobs}"
export QUANTROUTE_FLOCI_SQS_DLQ="${QUANTROUTE_FLOCI_SQS_DLQ:-quantroute-optimization-jobs-dlq}"
export QUANTROUTE_FLOCI_IAM_ROLE="${QUANTROUTE_FLOCI_IAM_ROLE:-quantroute-local-worker}"
export QUANTROUTE_FLOCI_SECRET="${QUANTROUTE_FLOCI_SECRET:-quantroute/local/application}"

aws_floci() {
  aws --endpoint-url "$AWS_ENDPOINT_URL" "$@"
}

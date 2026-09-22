#!/usr/bin/env bash
set -Eeuo pipefail

: "${AWS_ENDPOINT_URL:?AWS_ENDPOINT_URL is required}"
: "${FLOCI_ECR_REPOSITORY:?FLOCI_ECR_REPOSITORY is required}"
: "${LOCAL_IMAGE:?LOCAL_IMAGE is required}"
: "${SHORT_SHA:?SHORT_SHA is required}"

ARTIFACT_DIR="${ARTIFACT_DIR:-artifacts}"
mkdir -p "$ARTIFACT_DIR"

ecr_uri="$(aws --endpoint-url "$AWS_ENDPOINT_URL" ecr describe-repositories \
    --repository-names "$FLOCI_ECR_REPOSITORY" \
    --query 'repositories[0].repositoryUri' \
    --output text)"

printf '%s\n' "$ecr_uri" > "$ARTIFACT_DIR/ecr-uri.txt"

aws --endpoint-url "$AWS_ENDPOINT_URL" ecr get-login-password \
    | docker login --username AWS --password-stdin "$ecr_uri"

image_ref="$ecr_uri:$SHORT_SHA"
docker tag "$LOCAL_IMAGE" "$image_ref"
docker push "$image_ref"

image_digest="$(aws --endpoint-url "$AWS_ENDPOINT_URL" ecr describe-images \
    --repository-name "$FLOCI_ECR_REPOSITORY" \
    --image-ids imageTag="$SHORT_SHA" \
    --query 'imageDetails[0].imageDigest' \
    --output text)"

printf '%s\n' "$image_digest" > "$ARTIFACT_DIR/image-digest.txt"
printf '%s\n' "$image_ref" > "$ARTIFACT_DIR/image-reference.txt"
printf '%s\n' "$image_ref@$image_digest" > "$ARTIFACT_DIR/immutable-image-reference.txt"

echo "Published: $image_ref"
echo "Digest: $image_digest"

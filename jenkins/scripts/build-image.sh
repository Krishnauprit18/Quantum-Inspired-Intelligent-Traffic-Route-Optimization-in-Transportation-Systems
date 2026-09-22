#!/usr/bin/env bash
set -Eeuo pipefail

: "${LOCAL_IMAGE:?LOCAL_IMAGE is required}"
: "${GIT_SHA:?GIT_SHA is required}"

ARTIFACT_DIR="${ARTIFACT_DIR:-artifacts}"
mkdir -p "$ARTIFACT_DIR"

docker build \
    --pull \
    --label "org.opencontainers.image.title=quantroute" \
    --label "org.opencontainers.image.revision=$GIT_SHA" \
    --label "org.opencontainers.image.source=traffic-route-optimization" \
    --tag "$LOCAL_IMAGE" \
    .

docker image inspect "$LOCAL_IMAGE" --format '{{json .RepoDigests}}' \
    | tee "$ARTIFACT_DIR/local-image-digests.json"

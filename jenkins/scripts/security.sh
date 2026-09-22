#!/usr/bin/env bash
set -Eeuo pipefail

mode="${1:-}"
CI_VENV="${CI_VENV:-.ci-venv}"
ARTIFACT_DIR="${ARTIFACT_DIR:-artifacts}"
WORKSPACE="${WORKSPACE:-$(pwd)}"
mkdir -p "$ARTIFACT_DIR"

case "$mode" in
    python)
        echo '===== BANDIT ====='
        "$CI_VENV/bin/bandit" -c pyproject.toml -r src \
            -f json -o "$ARTIFACT_DIR/bandit.json"

        echo '===== PIP-AUDIT ====='
        "$CI_VENV/bin/pip-audit" \
            --format=json \
            --output="$ARTIFACT_DIR/pip-audit.json"
        ;;

    secrets)
        echo '===== GITLEAKS ====='
        docker run --rm \
            --user "$(id -u):$(id -g)" \
            -v "${WORKSPACE}:/workspace:rw" \
            -w /workspace \
            "$GITLEAKS_IMAGE" \
            detect \
            --source=/workspace \
            --no-banner \
            --redact \
            --report-format sarif \
            --report-path=/workspace/"$ARTIFACT_DIR"/gitleaks.sarif
        ;;

    containers)
        DOCKER_GID="$(stat -c '%g' /var/run/docker.sock)"
        echo '===== TRIVY FILESYSTEM ====='
        docker run --rm \
            --user "$(id -u):$(id -g)" \
            -v "${WORKSPACE}:/workspace:rw" \
            "$TRIVY_IMAGE" \
            fs \
            --scanners vuln,secret,misconfig \
            --skip-dirs /workspace/.ci-venv \
            --severity HIGH,CRITICAL \
            --exit-code 1 \
            --format sarif \
            --output /workspace/"$ARTIFACT_DIR"/trivy-filesystem.sarif \
            /workspace

        echo '===== TRIVY IMAGE ====='
        docker run --rm \
            --user "$(id -u):$(id -g)" \
            --group-add "$DOCKER_GID" \
            -v /var/run/docker.sock:/var/run/docker.sock \
            -v "${WORKSPACE}:/workspace:rw" \
            "$TRIVY_IMAGE" \
            image \
            --severity HIGH,CRITICAL \
            --exit-code 1 \
            --format sarif \
            --output /workspace/"$ARTIFACT_DIR"/trivy-image.sarif \
            "$LOCAL_IMAGE"
        ;;

    sbom)
        DOCKER_GID="$(stat -c '%g' /var/run/docker.sock)"
        echo '===== CYCLONEDX SBOM ====='
        docker run --rm \
            --user "$(id -u):$(id -g)" \
            --group-add "$DOCKER_GID" \
            -v /var/run/docker.sock:/var/run/docker.sock \
            -v "${WORKSPACE}:/workspace:rw" \
            "$SYFT_IMAGE" \
            "docker:$LOCAL_IMAGE" \
            -o cyclonedx-json=/workspace/"$ARTIFACT_DIR"/sbom.cyclonedx.json

        echo '===== SPDX SBOM ====='
        docker run --rm \
            --user "$(id -u):$(id -g)" \
            --group-add "$DOCKER_GID" \
            -v /var/run/docker.sock:/var/run/docker.sock \
            -v "${WORKSPACE}:/workspace:rw" \
            "$SYFT_IMAGE" \
            "docker:$LOCAL_IMAGE" \
            -o spdx-json=/workspace/"$ARTIFACT_DIR"/sbom.spdx.json
        ;;

    sign-image)
        : "${ECR_URI:?ECR_URI is required}"
        : "${IMAGE_DIGEST:?IMAGE_DIGEST is required}"
        : "${COSIGN_PRIVATE_KEY:?COSIGN_PRIVATE_KEY is required}"
        : "${COSIGN_PUBLIC_KEY:?COSIGN_PUBLIC_KEY is required}"
        : "${COSIGN_PASSWORD:?COSIGN_PASSWORD is required}"

        image_ref="${ECR_URI}@${IMAGE_DIGEST}"
        printf '%s\n' "$image_ref" > "$ARTIFACT_DIR/signed-image-reference.txt"

        docker run --rm \
            -e COSIGN_PASSWORD \
            -e COSIGN_INSECURE="${COSIGN_INSECURE:-false}" \
            -v "$COSIGN_PRIVATE_KEY:/keys/cosign.key:ro" \
            "$COSIGN_IMAGE" \
            sign --yes --key /keys/cosign.key "$image_ref"

        docker run --rm \
            -e COSIGN_INSECURE="${COSIGN_INSECURE:-false}" \
            -v "$COSIGN_PUBLIC_KEY:/keys/cosign.pub:ro" \
            "$COSIGN_IMAGE" \
            verify --key /keys/cosign.pub "$image_ref"

        echo 'Image signing and verification: PASS'
        ;;

    *)
        echo "Usage: $0 {python|secrets|containers|sbom|sign-image}" >&2
        exit 2
        ;;
esac

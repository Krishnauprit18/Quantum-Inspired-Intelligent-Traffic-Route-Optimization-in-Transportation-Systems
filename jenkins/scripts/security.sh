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
        trivy_cache_dir="${TRIVY_CACHE_DIR:-${TMPDIR:-/tmp}/quantroute-trivy-cache}"
        mkdir -p "$trivy_cache_dir"
        trivy_runtime_args=(
            --rm
            --user "$(id -u):$(id -g)"
            -e XDG_CACHE_HOME=/tmp/trivy-cache
            -v "${WORKSPACE}:/workspace:rw"
            -v "$trivy_cache_dir:/tmp/trivy-cache:rw"
        )
        trivy_image_args=(
            --rm
            --user "$(id -u):$(id -g)"
            --group-add "$DOCKER_GID"
            -e XDG_CACHE_HOME=/tmp/trivy-cache
            -v /var/run/docker.sock:/var/run/docker.sock
            -v "${WORKSPACE}:/workspace:rw"
            -v "$trivy_cache_dir:/tmp/trivy-cache:rw"
        )
        trivy_fs_scan_args=(
            fs
            --scanners vuln,secret,misconfig
            --skip-dirs /workspace/.ci-venv
            --skip-dirs /workspace/.git
            --skip-dirs /workspace/infra/floci/data
            --skip-dirs /workspace/demo_results
            --skip-dirs /workspace/demo_results_new
            --severity HIGH,CRITICAL
        )

        echo '===== TRIVY FILESYSTEM FULL REPORT ====='
        docker run "${trivy_runtime_args[@]}" \
            "$TRIVY_IMAGE" \
            "${trivy_fs_scan_args[@]}" \
            --format sarif \
            --output /workspace/"$ARTIFACT_DIR"/trivy-filesystem.sarif \
            /workspace

        echo '===== TRIVY FILESYSTEM GATE (FIXABLE FINDINGS) ====='
        docker run "${trivy_runtime_args[@]}" \
            "$TRIVY_IMAGE" \
            "${trivy_fs_scan_args[@]}" \
            --ignore-unfixed \
            --exit-code 1 \
            --format table \
            /workspace

        echo '===== TRIVY IMAGE FULL REPORT ====='
        docker run "${trivy_image_args[@]}" \
            "$TRIVY_IMAGE" \
            image \
            --severity HIGH,CRITICAL \
            --format sarif \
            --output /workspace/"$ARTIFACT_DIR"/trivy-image.sarif \
            "$LOCAL_IMAGE"

        echo '===== TRIVY IMAGE GATE (FIXABLE FINDINGS) ====='
        docker run "${trivy_image_args[@]}" \
            "$TRIVY_IMAGE" \
            image \
            --ignore-unfixed \
            --severity HIGH,CRITICAL \
            --exit-code 1 \
            --format table \
            "$LOCAL_IMAGE"
        ;;

    sbom)
        DOCKER_GID="$(stat -c '%g' /var/run/docker.sock)"
        syft_tmp_dir="$(mktemp -d "${TMPDIR:-/tmp}/quantroute-syft.XXXXXX")"
        trap 'rm -rf "$syft_tmp_dir"' EXIT
        echo '===== CYCLONEDX SBOM ====='
        docker run --rm \
            --user "$(id -u):$(id -g)" \
            --group-add "$DOCKER_GID" \
            -e HOME=/tmp/home \
            -e TMPDIR=/tmp \
            -e XDG_CACHE_HOME=/tmp/cache \
            -v /var/run/docker.sock:/var/run/docker.sock \
            -v "${WORKSPACE}:/workspace:rw" \
            -v "$syft_tmp_dir:/tmp:rw" \
            "$SYFT_IMAGE" \
            "docker:$LOCAL_IMAGE" \
            -o cyclonedx-json=/workspace/"$ARTIFACT_DIR"/sbom.cyclonedx.json

        echo '===== SPDX SBOM ====='
        docker run --rm \
            --user "$(id -u):$(id -g)" \
            --group-add "$DOCKER_GID" \
            -e HOME=/tmp/home \
            -e TMPDIR=/tmp \
            -e XDG_CACHE_HOME=/tmp/cache \
            -v /var/run/docker.sock:/var/run/docker.sock \
            -v "${WORKSPACE}:/workspace:rw" \
            -v "$syft_tmp_dir:/tmp:rw" \
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

        cosign_registry_flags=()
        if [[ "${COSIGN_ALLOW_INSECURE_REGISTRY:-false}" == 'true' ]]; then
            cosign_registry_flags+=(--allow-http-registry --allow-insecure-registry)
        fi
        cosign_tlog_flags=(--tlog-upload=false)
        if [[ "${COSIGN_TLOG_UPLOAD:-false}" == 'true' ]]; then
            cosign_tlog_flags=(--tlog-upload=true)
        fi
        cosign_network_mode="${COSIGN_NETWORK_MODE:-host}"

        docker run --rm \
            --network "$cosign_network_mode" \
            -e COSIGN_PASSWORD \
            -v "$COSIGN_PRIVATE_KEY:/keys/cosign.key:ro" \
            "$COSIGN_IMAGE" \
            sign --yes --key /keys/cosign.key \
            "${cosign_registry_flags[@]}" \
            "${cosign_tlog_flags[@]}" \
            "$image_ref"

        docker run --rm \
            --network "$cosign_network_mode" \
            -v "$COSIGN_PUBLIC_KEY:/keys/cosign.pub:ro" \
            "$COSIGN_IMAGE" \
            verify --key /keys/cosign.pub \
            --offline --insecure-ignore-tlog \
            "${cosign_registry_flags[@]}" \
            "$image_ref"

        echo 'Image signing and verification: PASS'
        ;;

    *)
        echo "Usage: $0 {python|secrets|containers|sbom|sign-image}" >&2
        exit 2
        ;;
esac

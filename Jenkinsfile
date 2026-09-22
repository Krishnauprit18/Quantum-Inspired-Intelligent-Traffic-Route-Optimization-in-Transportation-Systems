pipeline {
    agent any

    options {
        skipDefaultCheckout(true)
        timestamps()
        disableConcurrentBuilds(abortPrevious: true)
        buildDiscarder(
            logRotator(
                numToKeepStr: '20',
                artifactNumToKeepStr: '20'
            )
        )
        timeout(time: 60, unit: 'MINUTES')
    }

    parameters {
        booleanParam(
            name: 'PUBLISH_IMAGE',
            defaultValue: false,
            description: 'Push the immutable image to Floci ECR after all CI and security gates pass.'
        )

        booleanParam(
            name: 'SIGN_PROVENANCE',
            defaultValue: false,
            description: 'Create and verify a Cosign-signed image provenance artifact. Jenkins Cosign credentials are required.'
        )

        booleanParam(
            name: 'DEPLOY_TO_FLOCI_EKS',
            defaultValue: false,
            description: 'Reserved for the later Terraform/Helm/EKS phase. Keep disabled until those files are implemented.'
        )
    }

    environment {
        APP_NAME = 'quantroute'

        AWS_ENDPOINT_URL = 'http://127.0.0.1:4566'
        AWS_DEFAULT_REGION = 'us-east-1'
        AWS_EC2_METADATA_DISABLED = 'true'
        AWS_PAGER = ''

        FLOCI_ECR_REPOSITORY = 'quantroute/api'
        FLOCI_S3_BUCKET = 'quantroute-artifacts-local'
        FLOCI_SQS_QUEUE = 'quantroute-optimization-jobs'

        FLOCI_AWS_CREDENTIALS = credentials('quantroute-floci-aws')

        TRIVY_IMAGE = 'aquasec/trivy@sha256:62b1e65e8869bc4b4c6aa4fa2b21595256c7c2f6018a9d9ad61caf87187c1969'
        SYFT_IMAGE = 'ghcr.io/anchore/syft@sha256:500e2d872ac019436926e8322b4fc1f39441d94d21f6f4046c6ff29b30e8cb02'
        GITLEAKS_IMAGE = 'ghcr.io/gitleaks/gitleaks@sha256:c00b6bd0aeb3071cbcb79009cb16a60dd9e0a7c60e2be9ab65d25e6bc8abbb7f'
        COSIGN_IMAGE = 'ghcr.io/sigstore/cosign/cosign@sha256:b29487e48205d875c324c79583e2806d9d269c0fa299e0861bbec023d8430c8b'
    }

    stages {
        stage('Checkout') {
            steps {
                checkout scm
            }
        }

        stage('Initialize Build') {
            steps {
                sh '''
                    set -eu

                    rm -rf .ci-venv artifacts
                    mkdir -p artifacts

                    python3 -m venv .ci-venv

                    .ci-venv/bin/python -m pip install --upgrade pip
                    .ci-venv/bin/python -m pip install \
                        -e ".[service,ortools,benchmark,dev]"
                '''

                script {
                    env.GIT_SHA = sh(
                        script: 'git rev-parse HEAD',
                        returnStdout: true
                    ).trim()

                    env.SHORT_SHA = sh(
                        script: 'git rev-parse --short=12 HEAD',
                        returnStdout: true
                    ).trim()

                    env.LOCAL_IMAGE = "${env.APP_NAME}:${env.SHORT_SHA}"

                    echo "Git commit: ${env.GIT_SHA}"
                    echo "Local image: ${env.LOCAL_IMAGE}"
                }
            }
        }

        stage('Environment Preflight') {
            steps {
                sh '''
                    set -eu

                    echo "===== TOOL CHECK ====="

                    for command in \
                        python3 \
                        docker \
                        aws \
                        terraform \
                        kubectl \
                        helm \
                        curl
                    do
                        command -v "$command"
                    done

                    echo "===== DOCKER CHECK ====="
                    docker info >/dev/null

                    echo "===== FLOCI HEALTH ====="
                    curl --fail --silent --show-error \
                        "$AWS_ENDPOINT_URL/_floci/health" >/dev/null

                    export AWS_ACCESS_KEY_ID="$FLOCI_AWS_CREDENTIALS_USR"
                    export AWS_SECRET_ACCESS_KEY="$FLOCI_AWS_CREDENTIALS_PSW"

                    echo "===== STS CHECK ====="
                    aws --endpoint-url "$AWS_ENDPOINT_URL" \
                        sts get-caller-identity >/dev/null

                    echo "===== S3 CHECK ====="
                    aws --endpoint-url "$AWS_ENDPOINT_URL" \
                        s3api head-bucket \
                        --bucket "$FLOCI_S3_BUCKET"

                    echo "===== ECR CHECK ====="
                    aws --endpoint-url "$AWS_ENDPOINT_URL" \
                        ecr describe-repositories \
                        --repository-names "$FLOCI_ECR_REPOSITORY" \
                        >/dev/null

                    echo "===== SQS CHECK ====="
                    aws --endpoint-url "$AWS_ENDPOINT_URL" \
                        sqs get-queue-url \
                        --queue-name "$FLOCI_SQS_QUEUE" \
                        >/dev/null

                    echo "Environment preflight: PASS"
                '''
            }
        }

        stage('Quality and Tests') {
            steps {
                sh '''
                    set -eu

                    .ci-venv/bin/ruff check .
                    .ci-venv/bin/ruff format --check .

                    .ci-venv/bin/pytest \
                        --cov=quantroute \
                        --cov-report=term-missing \
                        --cov-report=xml:artifacts/coverage.xml \
                        --junitxml=artifacts/junit.xml
                '''
            }
        }

        stage('Python Security') {
            steps {
                sh '''
                    set -eu

                    .ci-venv/bin/bandit \
                        -c pyproject.toml \
                        -r src \
                        -f json \
                        -o artifacts/bandit.json

                    .ci-venv/bin/pip-audit \
                        --format=json \
                        --output=artifacts/pip-audit.json
                '''
            }
        }

        stage('Secret Scan') {
            steps {
                sh '''
                    set -eu

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
                        --report-path=/workspace/artifacts/gitleaks.sarif
                '''
            }
        }

        stage('Docker Build') {
            steps {
                sh '''
                    set -eu

                    docker build \
                        --pull \
                        --label "org.opencontainers.image.title=quantroute" \
                        --label "org.opencontainers.image.revision=$GIT_SHA" \
                        --label "org.opencontainers.image.source=traffic-route-optimization" \
                        --tag "$LOCAL_IMAGE" \
                        .
                '''
            }
        }

        stage('Container Security Scans') {
            steps {
                sh '''
                    set -eu

                    DOCKER_GID="$(stat -c '%g' /var/run/docker.sock)"

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
                        --output /workspace/artifacts/trivy-filesystem.sarif \
                        /workspace

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
                        --output /workspace/artifacts/trivy-image.sarif \
                        "$LOCAL_IMAGE"
                '''
            }
        }

        stage('SBOM Generation') {
            steps {
                sh '''
                    set -eu

                    DOCKER_GID="$(stat -c '%g' /var/run/docker.sock)"

                    docker run --rm \
                        --user "$(id -u):$(id -g)" \
                        --group-add "$DOCKER_GID" \
                        -v /var/run/docker.sock:/var/run/docker.sock \
                        -v "${WORKSPACE}:/workspace:rw" \
                        "$SYFT_IMAGE" \
                        "docker:$LOCAL_IMAGE" \
                        -o cyclonedx-json=/workspace/artifacts/sbom.cyclonedx.json

                    docker run --rm \
                        --user "$(id -u):$(id -g)" \
                        --group-add "$DOCKER_GID" \
                        -v /var/run/docker.sock:/var/run/docker.sock \
                        -v "${WORKSPACE}:/workspace:rw" \
                        "$SYFT_IMAGE" \
                        "docker:$LOCAL_IMAGE" \
                        -o spdx-json=/workspace/artifacts/sbom.spdx.json
                '''
            }
        }

        stage('Publish Image to Floci ECR') {
            when {
                expression {
                    return params.PUBLISH_IMAGE
                }
            }

            steps {
                script {
                    env.ECR_URI = sh(
                        script: '''
                            set -eu

                            export AWS_ACCESS_KEY_ID="$FLOCI_AWS_CREDENTIALS_USR"
                            export AWS_SECRET_ACCESS_KEY="$FLOCI_AWS_CREDENTIALS_PSW"

                            aws --endpoint-url "$AWS_ENDPOINT_URL" \
                                ecr describe-repositories \
                                --repository-names "$FLOCI_ECR_REPOSITORY" \
                                --query 'repositories[0].repositoryUri' \
                                --output text
                        ''',
                        returnStdout: true
                    ).trim()
                }

                sh '''
                    set -eu

                    export AWS_ACCESS_KEY_ID="$FLOCI_AWS_CREDENTIALS_USR"
                    export AWS_SECRET_ACCESS_KEY="$FLOCI_AWS_CREDENTIALS_PSW"

                    aws --endpoint-url "$AWS_ENDPOINT_URL" \
                        ecr get-login-password \
                        | docker login \
                            --username AWS \
                            --password-stdin "$ECR_URI"

                    docker tag \
                        "$LOCAL_IMAGE" \
                        "$ECR_URI:$SHORT_SHA"

                    docker push \
                        "$ECR_URI:$SHORT_SHA"

                    aws --endpoint-url "$AWS_ENDPOINT_URL" \
                        ecr describe-images \
                        --repository-name "$FLOCI_ECR_REPOSITORY" \
                        --image-ids imageTag="$SHORT_SHA" \
                        --query 'imageDetails[0].imageDigest' \
                        --output text \
                        > artifacts/image-digest.txt

                    printf '%s\\n' "$ECR_URI:$SHORT_SHA" \
                        > artifacts/image-reference.txt
                '''

                script {
                    env.IMAGE_DIGEST = readFile(
                        'artifacts/image-digest.txt'
                    ).trim()

                    echo "Published image digest: ${env.IMAGE_DIGEST}"
                }
            }
        }

        stage('Sign Image Provenance') {
            when {
                expression {
                    return params.PUBLISH_IMAGE && params.SIGN_PROVENANCE
                }
            }

            steps {
                withCredentials([
                    file(
                        credentialsId: 'quantroute-cosign-private-key',
                        variable: 'COSIGN_PRIVATE_KEY'
                    ),
                    file(
                        credentialsId: 'quantroute-cosign-public-key',
                        variable: 'COSIGN_PUBLIC_KEY'
                    ),
                    string(
                        credentialsId: 'quantroute-cosign-password',
                        variable: 'COSIGN_PASSWORD'
                    )
                ]) {
                    sh '''
                        set -eu

                        printf '{"image":"%s","digest":"%s","git_sha":"%s"}\\n' \
                            "$ECR_URI" \
                            "$IMAGE_DIGEST" \
                            "$GIT_SHA" \
                            > artifacts/image-provenance.json

                        docker run --rm \
                            -e COSIGN_PASSWORD \
                            -v "$COSIGN_PRIVATE_KEY:/keys/cosign.key:ro" \
                            -v "${WORKSPACE}:/workspace:rw" \
                            "$COSIGN_IMAGE" \
                            sign-blob \
                            --key /keys/cosign.key \
                            --bundle /workspace/artifacts/image-provenance.bundle \
                            /workspace/artifacts/image-provenance.json

                        docker run --rm \
                            -v "$COSIGN_PUBLIC_KEY:/keys/cosign.pub:ro" \
                            -v "${WORKSPACE}:/workspace:rw" \
                            "$COSIGN_IMAGE" \
                            verify-blob \
                            --key /keys/cosign.pub \
                            --bundle /workspace/artifacts/image-provenance.bundle \
                            /workspace/artifacts/image-provenance.json
                    '''
                }
            }
        }

        stage('Deployment Readiness Gate') {
            when {
                expression {
                    return params.DEPLOY_TO_FLOCI_EKS
                }
            }

            steps {
                sh '''
                    set -eu

                    test -d infra/terraform
                    test -d deploy/helm/quantroute

                    echo "Terraform and Helm deployment inputs detected."
                    echo "Actual EKS deployment will be activated after D2 infrastructure implementation."
                '''
            }
        }
    }

    post {
        always {
            junit(
                testResults: 'artifacts/junit.xml',
                allowEmptyResults: true
            )

            archiveArtifacts(
                artifacts: 'artifacts/**/*',
                allowEmptyArchive: true,
                fingerprint: true
            )
        }

        success {
            echo 'QuantRoute CI pipeline completed successfully.'
        }

        failure {
            echo 'QuantRoute CI pipeline failed. Review the archived artifacts.'
        }

        cleanup {
            sh(
                script: 'docker image rm "$LOCAL_IMAGE" 2>/dev/null || true',
                returnStatus: true
            )
        }
    }
}
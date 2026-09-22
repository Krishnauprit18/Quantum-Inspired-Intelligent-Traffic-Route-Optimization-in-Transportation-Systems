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
            description: 'Sign and verify the published image digest with Cosign. Cosign credentials are required.'
        )
        booleanParam(
            name: 'DEPLOY_TO_FLOCI_EKS',
            defaultValue: false,
            description: 'Run Terraform, Helm, manual approval, deployment and smoke-test stages. Requires D2 infrastructure.'
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
        CI_VENV = '.ci-venv'
        ARTIFACT_DIR = 'artifacts'

        TRIVY_IMAGE = 'aquasec/trivy@sha256:62b1e65e8869bc4b4c6aa4fa2b21595256c7c2f6018a9d9ad61caf87187c1969'
        SYFT_IMAGE = 'ghcr.io/anchore/syft@sha256:500e2e872ac019436926e8322b4fc1f39441d94d21f6f4046c6ff29b30e8cb02'
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
                    set -Eeuo pipefail
                    rm -rf "$CI_VENV" "$ARTIFACT_DIR"
                    mkdir -p "$ARTIFACT_DIR"
                    python3 -m venv "$CI_VENV"
                    "$CI_VENV/bin/python" -m pip install --upgrade pip
                    "$CI_VENV/bin/python" -m pip install -e ".[service,ortools,benchmark,dev]"
                '''
                script {
                    env.GIT_SHA = sh(script: 'git rev-parse HEAD', returnStdout: true).trim()
                    env.SHORT_SHA = sh(script: 'git rev-parse --short=12 HEAD', returnStdout: true).trim()
                    env.LOCAL_IMAGE = "${env.APP_NAME}:${env.SHORT_SHA}"
                    echo "Git commit: ${env.GIT_SHA}"
                    echo "Local image: ${env.LOCAL_IMAGE}"
                }
            }
        }

        stage('Environment Preflight') {
            steps {
                withCredentials([
                    usernamePassword(
                        credentialsId: 'quantroute-floci-aws',
                        usernameVariable: 'FLOCI_AWS_ACCESS_KEY_ID',
                        passwordVariable: 'FLOCI_AWS_SECRET_ACCESS_KEY'
                    )
                ]) {
                    sh '''
                        set -Eeuo pipefail
                        export AWS_ACCESS_KEY_ID="$FLOCI_AWS_ACCESS_KEY_ID"
                        export AWS_SECRET_ACCESS_KEY="$FLOCI_AWS_SECRET_ACCESS_KEY"
                        jenkins/scripts/preflight.sh | tee "$ARTIFACT_DIR/preflight.txt"
                    '''
                }
            }
        }

        stage('Quality and Tests') {
            steps {
                sh 'jenkins/scripts/test.sh | tee "$ARTIFACT_DIR/test.txt"'
            }
        }

        stage('Python Security') {
            steps {
                sh 'jenkins/scripts/security.sh python | tee "$ARTIFACT_DIR/python-security.txt"'
            }
        }

        stage('Secret Scan') {
            steps {
                sh 'jenkins/scripts/security.sh secrets | tee "$ARTIFACT_DIR/secret-scan.txt"'
            }
        }

        stage('Docker Build') {
            steps {
                sh 'jenkins/scripts/build-image.sh | tee "$ARTIFACT_DIR/docker-build.txt"'
            }
        }

        stage('Container Security Scans') {
            steps {
                sh 'jenkins/scripts/security.sh containers | tee "$ARTIFACT_DIR/container-security.txt"'
            }
        }

        stage('SBOM Generation') {
            steps {
                sh 'jenkins/scripts/security.sh sbom | tee "$ARTIFACT_DIR/sbom.txt"'
            }
        }

        stage('Publish Image to Floci ECR') {
            when {
                expression { return params.PUBLISH_IMAGE }
            }
            steps {
                withCredentials([
                    usernamePassword(
                        credentialsId: 'quantroute-floci-aws',
                        usernameVariable: 'FLOCI_AWS_ACCESS_KEY_ID',
                        passwordVariable: 'FLOCI_AWS_SECRET_ACCESS_KEY'
                    )
                ]) {
                    sh '''
                        set -Eeuo pipefail
                        export AWS_ACCESS_KEY_ID="$FLOCI_AWS_ACCESS_KEY_ID"
                        export AWS_SECRET_ACCESS_KEY="$FLOCI_AWS_SECRET_ACCESS_KEY"
                        jenkins/scripts/publish-image.sh | tee "$ARTIFACT_DIR/publish.txt"
                    '''
                }
                script {
                    env.ECR_URI = readFile("${env.ARTIFACT_DIR}/ecr-uri.txt").trim()
                    env.IMAGE_DIGEST = readFile("${env.ARTIFACT_DIR}/image-digest.txt").trim()
                    echo "Published image digest: ${env.IMAGE_DIGEST}"
                }
            }
        }

        stage('Sign Image') {
            when {
                expression { return params.PUBLISH_IMAGE && params.SIGN_PROVENANCE }
            }
            steps {
                withCredentials([
                    file(credentialsId: 'quantroute-cosign-private-key', variable: 'COSIGN_PRIVATE_KEY'),
                    file(credentialsId: 'quantroute-cosign-public-key', variable: 'COSIGN_PUBLIC_KEY'),
                    string(credentialsId: 'quantroute-cosign-password', variable: 'COSIGN_PASSWORD')
                ]) {
                    sh 'jenkins/scripts/security.sh sign-image | tee "$ARTIFACT_DIR/signing.txt"'
                }
            }
        }

        stage('Terraform Validate and Plan') {
            when {
                expression { return params.DEPLOY_TO_FLOCI_EKS }
            }
            steps {
                sh '''
                    set -Eeuo pipefail
                    test -d infra/terraform
                    terraform -chdir=infra/terraform init -backend=false -input=false
                    terraform -chdir=infra/terraform validate
                    terraform -chdir=infra/terraform plan \
                        -input=false \
                        -out="$WORKSPACE/$ARTIFACT_DIR/terraform.tfplan" \
                        | tee "$ARTIFACT_DIR/terraform-plan.txt"
                '''
            }
        }

        stage('Helm Lint') {
            when {
                expression { return params.DEPLOY_TO_FLOCI_EKS }
            }
            steps {
                sh '''
                    set -Eeuo pipefail
                    test -d deploy/helm/quantroute
                    helm lint deploy/helm/quantroute | tee "$ARTIFACT_DIR/helm-lint.txt"
                '''
            }
        }

        stage('Manual Deployment Approval') {
            when {
                expression { return params.DEPLOY_TO_FLOCI_EKS }
            }
            steps {
                input message: 'CI, security, Terraform and Helm gates passed. Deploy to Floci EKS?', ok: 'Deploy'
            }
        }

        stage('Deploy to Floci EKS') {
            when {
                expression { return params.DEPLOY_TO_FLOCI_EKS }
            }
            steps {
                sh '''
                    set -Eeuo pipefail
                    test -f "$ARTIFACT_DIR/terraform.tfplan"
                    terraform -chdir=infra/terraform apply -input=false "$WORKSPACE/$ARTIFACT_DIR/terraform.tfplan" \
                        | tee "$ARTIFACT_DIR/deployment-result.txt"
                    helm upgrade --install quantroute deploy/helm/quantroute \
                        --namespace quantroute --create-namespace \
                        | tee -a "$ARTIFACT_DIR/deployment-result.txt"
                '''
            }
        }

        stage('Smoke Test') {
            when {
                expression { return params.DEPLOY_TO_FLOCI_EKS }
            }
            steps {
                sh 'jenkins/scripts/smoke-test.sh | tee "$ARTIFACT_DIR/smoke-test.txt"'
            }
        }
    }

    post {
        always {
            sh 'mkdir -p "$ARTIFACT_DIR"'
            script {
                if (!fileExists("${env.ARTIFACT_DIR}/deployment-result.txt")) {
                    writeFile file: "${env.ARTIFACT_DIR}/deployment-result.txt", text: 'NOT_RUN: deployment parameter disabled or an earlier gate failed.\n'
                }
                if (!fileExists("${env.ARTIFACT_DIR}/smoke-test.txt")) {
                    writeFile file: "${env.ARTIFACT_DIR}/smoke-test.txt", text: 'NOT_RUN: deployment was not completed.\n'
                }
            }
            junit testResults: "${env.ARTIFACT_DIR}/junit.xml", allowEmptyResults: true
            archiveArtifacts artifacts: "${env.ARTIFACT_DIR}/**/*", allowEmptyArchive: true, fingerprint: true
        }
        success {
            echo 'QuantRoute CI pipeline completed successfully.'
        }
        failure {
            echo 'QuantRoute CI pipeline failed. Review the archived artifacts.'
        }
        cleanup {
            script {
                if (env.LOCAL_IMAGE?.trim()) {
                    sh(script: 'docker image rm "$LOCAL_IMAGE" 2>/dev/null || true', returnStatus: true)
                }
            }
        }
    }
}

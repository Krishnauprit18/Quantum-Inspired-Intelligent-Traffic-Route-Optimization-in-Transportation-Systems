# Local AWS Lab for QuantRoute

This directory uses Floci only as a local AWS-compatible environment. The
learning target is the AWS concept and workflow; Floci avoids AWS account cost
while keeping the AWS CLI and AWS provider interfaces available.

## AWS concepts in this lab

| AWS concept | Local resource | Why QuantRoute needs it |
|---|---|---|
| ECR | Floci ECR repository | Stores immutable API images for deployment |
| S3 | Floci S3 bucket | Stores benchmark and optimization artifacts |
| SQS | Job queue and dead-letter queue | Decouples API requests from workers |
| IAM/STS | Local worker role and caller identity | Demonstrates identity and least-privilege concepts |
| Secrets Manager | Local application secret | Keeps runtime secrets outside source code |
| EKS | Later phase | Runs the API and optimization worker as Kubernetes workloads |

## Connection model

The AWS CLI still uses normal AWS service commands. The only local-specific
part is the endpoint:

```text
http://127.0.0.1:4566
```

`floci-env.sh` exports non-production test credentials because AWS-shaped APIs
expect credentials. They are not real AWS credentials and must not be reused
outside this local lab.

## Start the lab

```bash
source infra/floci/scripts/floci-env.sh
bash infra/floci/scripts/bootstrap.sh
```

The bootstrap script validates Docker access, validates the Compose model,
starts only the QuantRoute Floci container, waits for the health endpoint, and
creates the local AWS resources idempotently.

## Stop the lab

```bash
docker compose -f infra/floci/compose.yaml down
```

The command stops this project's container. It does not stop containers from
other projects.

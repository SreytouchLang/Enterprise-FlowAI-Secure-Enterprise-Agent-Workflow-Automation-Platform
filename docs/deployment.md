# AWS deployment and rollback

The Terraform configuration is deployable source, not a record of deployment. No AWS apply, real provider test, or production identity test is implied by local validation. Applying it creates chargeable resources.

## Provisioned resources

- Two availability zones with public ALB subnets and private application/data subnets.
- NAT egress (one gateway outside production, one per AZ in production), S3 gateway endpoint.
- HTTPS ALB using an existing ACM certificate; HTTP redirects to HTTPS.
- Private ECS Fargate API, worker, frontend, singleton Celery beat scheduler and a separate migration task; deployment circuit breaker and CPU autoscaling.
- RDS PostgreSQL 16 with encrypted storage, mandatory SSL, backups and production Multi-AZ.
- Encrypted, authenticated ElastiCache Redis with TLS, snapshots and production replica/failover.
- Private, encrypted, versioned S3 documents bucket; noncurrent versions expire after 90 days, so adapt this policy to retention/legal-hold requirements before use.
- ECR, distinct task/migration IAM roles, Secrets Manager containers, CloudWatch logs/alarms/dashboard and environment-scoped GitHub OIDC deployment roles.

TLS terminates at the ALB; ALB-to-task traffic is HTTP inside the VPC. Use a service mesh or HTTPS target groups if organizational policy requires encryption on that segment. Alarm resources have no SNS destinations until the operator configures on-call routing. The stack does not deploy the enterprise identity provider or malware scanner.

## Bootstrap prerequisites

Use separate AWS accounts where possible for staging and production. Prepare a private, versioned, encrypted S3 Terraform-state bucket and an existing GitHub OIDC provider. Obtain an ACM certificate in the target region and control the application DNS name. Configure an external Keycloak realm/client with code flow, PKCE S256, the API audience and exact HTTPS callback/logout URIs. Production identities and database memberships must be provisioned explicitly; do not enable synthetic seed users.

Provide a private ClamAV daemon reachable on TCP 3310 from the task security group. Maintain its signatures and capacity; mandatory scanning fails if the scanner is unavailable. The `clamav_host` variable names that existing service.

1. Copy the chosen `environments/*.tfvars.example` to a gitignored `.tfvars`, replace placeholders, and set `TF_VAR_redis_auth_token` to 32–128 random alphanumeric characters through a secure environment. Keep `desired_count=0` during initial bootstrap.
2. Initialize the isolated state backend:

   ```sh
   terraform -chdir=infrastructure/terraform init \
     -backend-config=bucket=YOUR_PRIVATE_STATE_BUCKET \
     -backend-config=key=enterpriseflow/staging/terraform.tfstate \
     -backend-config=region=us-east-1
   terraform -chdir=infrastructure/terraform plan -var-file=environments/staging.tfvars
   ```

3. Review the plan, then apply it when authorized. The ECR repositories and zero-capacity services can exist before application images are pushed. Point DNS at the ALB output.
4. Insert Secrets Manager JSON values out of band, without shell history/log exposure. Terraform deliberately creates no secret versions.

   Runtime secret keys:

   | Key | Value |
   |---|---|
   | `DATABASE_URL` | `postgresql+psycopg://enterpriseflow:URL_ENCODED_RANDOM_PASSWORD@RDS_HOST:5432/enterpriseflow?sslmode=require` |
   | `REDIS_URL` | `rediss://:AUTH_TOKEN@REDIS_HOST:6379/0?ssl_cert_reqs=required` |
   | `SESSION_COOKIE_SECRET` | At least 32 cryptographically random characters |
   | `OPENAI_API_KEY` | Provider key, or empty if exclusively using Anthropic |
   | `ANTHROPIC_API_KEY` | Provider key, or empty if exclusively using OpenAI |

   Migration secret keys: `MIGRATION_DATABASE_URL` using the RDS-managed `platform_migration` password, the same restricted `DATABASE_URL`, and `SESSION_COOKIE_SECRET`. Use the `database_master_secret_arn` output through an authorized secret-management process. Synchronize migration credentials after RDS master rotation. `sslmode=require` encrypts Postgres transport; for hostname validation, package the AWS RDS CA bundle and use `sslmode=verify-full` plus `sslrootcert` in both URLs.

5. Publish immutable API/web images into the corresponding ECR repositories. Start the migration task on private subnets with the task security group. It creates/updates the restricted runtime login with no bypass privileges, grants DML/default privileges, then runs Alembic. Inspect the task exit code and migration CloudWatch logs. Never start API/worker tasks using migration credentials.
6. Set `desired_count` to one for staging or two for production and apply the updated autoscaling minimum. ECS service `desired_count` is ignored after creation because autoscaling manages it; explicitly scale the API/worker/frontend services from zero and the scheduler to exactly one on first deployment (`aws ecs update-service --desired-count ...`) and confirm health. The deploy workflow intentionally preserves existing capacity.
7. Verify `/health/ready`, login/logout, restricted document upload/retrieval, mandatory scan failure, a real provider request, approval/restart and restore procedures before inviting users.

The default provider is OpenAI; when using Anthropic exclusively, add `DEFAULT_LLM_PROVIDER=anthropic` to task environment and review embedding needs. Model rates and spending caps are configuration estimates, not live pricing. Required keys must exist even when their values are empty; ECS secret injection fails if a JSON key is absent.

## GitHub release workflow

CI performs backend/frontend checks, isolated and PostgreSQL integration tests, migration upgrade/downgrade, evaluation, dependency scans, image builds, Compose/Terraform validation and browser checks. CI results are recorded by GitHub; do not treat checked-in YAML as proof that a run passed.

Create `staging` and `production` GitHub environments. Require reviewers for production and restrict deployments to the protected `main` branch. Environment approval is enforced by GitHub configuration, not by a comment in YAML. Do not create long-lived AWS access keys in repository secrets.

Set these environment variables from Terraform outputs:

| GitHub variable | Meaning |
|---|---|
| `AWS_REGION` | Target region |
| `AWS_DEPLOY_ROLE_ARN` | Environment's OIDC deployment role |
| `ECS_CLUSTER` | Cluster name |
| `TASK_FAMILY_PREFIX` | `enterpriseflow-staging` or `enterpriseflow-production` |
| `ECR_API_REPOSITORY` / `ECR_WEB_REPOSITORY` | ECR repository names, without registry host |
| `PRIVATE_SUBNET_IDS` | Two comma-separated private subnet IDs |
| `TASK_SECURITY_GROUP_ID` | Application task security group |

Dispatch **Deploy**, select the environment and supply a full commit SHA. The workflow requires successful main-branch push CI for that SHA, assumes the scoped OIDC role, publishes immutable images, runs migrations first, checks migration exit status, prepares all four task revisions before updating any services, and waits for service stability. Task registration changes only the named application container, preserving sidecar images. ECS service updates are still separate operations; use the recovery procedure below if an update fails partway through. The workflow does not apply Terraform or provision new cloud services. A production environment approval must be configured before using this workflow.

## Rollback and recovery

For an unhealthy deployment, the ECS circuit breaker restores the prior stable task revision. To roll back deliberately, update each service to its recorded previous task-definition ARN and wait for stable services. Images have immutable release SHA tags. Rolling back application code does not undo database migrations: use additive/backward-compatible changes and an expand/contract release process.

If migration fails, the workflow stops before changing running services. Do not automatically downgrade a production schema with live writes. Review the migration, database state and backup first. Restore RDS to a new instance using point-in-time recovery, validate it privately, and update connection secrets only after a reviewed cutover. S3 versioning and Redis snapshots supplement recovery but do not replace a tested application-consistent restore drill. Final database snapshots and deletion protection make teardown deliberate.

## Operating-cost estimate

For planning, reserve **a few hundred USD per month for a continuously running small staging environment**, and **several hundred to over a thousand USD per month for a redundant production baseline**, before heavy AI usage. These are broad budgeting ranges, not quoted AWS prices or a measured bill. Actual cost depends on region, task sizes/counts, RDS and Redis instance choices, two production NAT gateways, ALB hours/traffic, storage/backups, data transfer, CloudWatch ingestion and model token/embedding volume. Idle environments still incur database, cache, NAT and load-balancer costs. Generate a dated estimate in the AWS Pricing Calculator before applying.

Reference the current [Fargate pricing](https://aws.amazon.com/fargate/pricing/), [RDS PostgreSQL pricing](https://aws.amazon.com/rds/postgresql/pricing/), and [VPC/NAT pricing](https://aws.amazon.com/vpc/pricing/) when refining the assumptions. Establish AWS Budgets alerts and explicit application spending caps. This project has not generated an AWS cost measurement.

The scheduler emits periodic recovery jobs and must remain at exactly one task per environment. It is excluded from CPU autoscaling; running multiple Celery beat schedulers can duplicate schedules. Workers still use idempotent jobs and database leases.

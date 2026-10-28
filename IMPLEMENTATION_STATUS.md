# Implementation and verification status

This file records actual progress, not a claim of production deployment.

## Implemented

- Next.js enterprise console with authenticated API proxy, session handling, responsive themes, dashboards, chat SSE, document actions, React Flow editor, approvals, department tools, analytics, audit and settings.
- FastAPI versioned API, normalized SQLAlchemy schema, reversible Alembic migrations, OIDC authorization code/PKCE, encrypted server-side tokens, CSRF, current database memberships and separate platform/data permissions.
- Department/private document ACLs at API/retrieval boundaries plus PostgreSQL RLS for documents, chunks, versions, permissions and embeddings.
- File verification, optional ClamAV (required in production), private S3/local storage, durable ingestion jobs, retries, failure states, extraction, chunking and reindex/delete/version support.
- Authorized hybrid PostgreSQL full-text/pgvector retrieval, source citations, LangGraph metadata checkpoints, provider-specific OpenAI/Anthropic structured and streaming adapters, persisted spend reservations and model usage.
- Decimal invoice validation/approval, HR onboarding/tasks/summaries, legal structured reviews/comparisons, deterministic property provenance/conflict review.
- Versioned allowlisted workflow DAGs, persistent step checkpoints, atomic approval decisions, deadlines and idempotent continuation; long AI/RAG workflows dispatched through durable jobs.
- Synthetic dataset generator, development-only user/data seed, deterministic evaluation runner with optional explicit live-provider evaluation.
- Docker Compose/Keycloak/MinIO, Terraform AWS definitions, CI/deployment workflows, architecture/security/deployment/evaluation and portfolio/interview documentation.

## Latest verification — 2026-10-20

- Backend: 84 unit tests passed; Ruff clean; mypy clean across 26 source files.
- PostgreSQL: all 28 integration tests passed in a disposable database, including RLS, concurrent approvals, restricted-role deletion, and unauthorized finalizer calls. Migration 0005 upgrade/downgrade/upgrade passed. Disposable databases were removed after testing.
- Infrastructure: 14 tests passed for release ordering, sidecar preservation, failure handling, sanitized diagnostics and replacement runtime-role function permissions; Ruff clean. CI/deploy YAML and embedded shell syntax checked.
- Frontend: 26 unit tests, TypeScript, lint and production build passed. All 8 fixture-backed Chromium tests passed again on October 19, including the approval-history regression.
- Deterministic evaluations: 20 invoice PDFs, 10 policy retrieval cases, 10 legal citation cases and 30 property cases passed; results in artifacts/evaluation.json. These are fixture checks, not live model quality measurements.
- Dependency audits: pip-audit and npm production audit reported no known vulnerabilities on October 17.
- Terraform 1.10.5 fmt/validate and Compose config passed. No AWS resources were deployed.
- Prior SQLite migration upgrade/downgrade/upgrade and development seed checks passed.
- Docker: API, frontend and MinIO images built; the full stack starts with health checks, and the real PostgreSQL/MinIO seed completed (10 users, 4 departments, 4 agents, 40 fixture documents). A shared-image tagging race was fixed by building each distinct image once. VM disk exhaustion was resolved by removing verified obsolete project build artifacts while preserving application volumes and unrelated projects. Migration 0005 is applied; running deletion code hashes match tested source.
- Real OIDC initially failed because the realm omitted Keycloak's `basic` client scope and its required subject claim. The realm fixture and existing local client were corrected. Six real-service browser journeys are being rerun; they are not yet marked passing.

## Changes in this continuation

- RAG tuple typing corrected for mypy.
- Workflow permissions and private-source access rechecked around asynchronous nodes, with regressions for membership revocation, account deactivation and share removal during model calls.
- Release preparation registers all task revisions before service updates and preserves sidecars.
- Approval detail view reads the API's decision history and updates its cache after review.
- PostgreSQL document deletion uses a narrowly authorized finalizer; deleted data stays hidden from the runtime role. Replacement runtime roles receive execution permission only for that function.
- Standard Keycloak subject scope restored; signed-token callback tests and token-safe failure diagnostics added.
- Real-service browser suite expanded to six journeys; fixture browser tests now use the production build.
- CI runs a separately seeded Compose journey suite and collects sanitized diagnostics.
- Make targets added for explicit live browser and PostgreSQL checks; development, deployment and security documentation updated.

## External verification limits

- The six real-service browser journeys are not yet marked passing; their latest run remains in progress after the verified database and identity corrections.
- No provider API key is configured; real OpenAI/Anthropic calls, embeddings and provider output quality remain unverified. SDK protocols have isolated mocked transport coverage.
- AWS deployment, production IdP, antivirus and restore validation remain external prerequisites. GitHub CI has not run for these local changes.
- Changes remain local and uncommitted. No GitHub push has occurred in this continuation.

## Exact next tasks

Finish the six real-service browser journeys, fix any failures, and record actual results. Build the final API image containing the updated role bootstrap. Commit and push the verified project to origin/main as requested; remote main was verified at the local initial commit. No provider or AWS success should be claimed without live credentials and verification.

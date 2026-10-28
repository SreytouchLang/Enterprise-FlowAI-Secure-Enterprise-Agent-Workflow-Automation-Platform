# Architecture

EnterpriseFlow uses a modular FastAPI application rather than independent services with duplicated authorization logic. Domain modules own documents, business records, agent execution and workflow state; a common SQLAlchemy unit of work and audit layer connect them. Next.js communicates through a typed, same-origin API client. Models are called only from the backend.

## Request and identity path

OIDC Authorization Code with PKCE establishes identity. The API validates tokens and maintains an HTTP-only browser session; identity-provider subject IDs map to local users. Database department memberships and permissions determine current access. Role-like claims from an external token cannot grant themselves business permissions. Revocation or deactivation must be reflected by the identity provider and local membership checks.

A platform administrator may configure an agent without belonging to that agent's department. This does not grant the administrator document retrieval, original-file download or business conversation access. An auditor receives only explicit audit visibility.

## Document and retrieval path

Uploads pass size/type checks, are stored under opaque server-generated keys, and produce a durable processing record. Workers scan and extract permitted PDF, DOCX and text content, create chunks, and optionally request embeddings. Restricted metadata and original files remain behind API authorization; a bucket path is never a permission credential.

Retrieval filters authorized departments and document access before constructing model context. PostgreSQL pgvector provides semantic similarity when real embeddings are configured. Authorized lexical retrieval can operate without embedding keys. Returned citations refer to actual accessible chunks; citation indices are checked against retrieved chunks. This verifies citation references, not the semantic truth of every generated claim. Source text is untrusted input, including text that resembles system instructions.

PostgreSQL document RLS receives transaction-local actor and department context from the backend. Pool reuse must never preserve another user's context. Runtime roles are `NOSUPERUSER NOBYPASSRLS` and do not own tables. SQLite makes fast local tests possible but cannot prove PostgreSQL RLS behavior.

## Execution and approval path

Agents have provider, model, prompt version, tools, timeouts and spending constraints. LangGraph organizes bounded reasoning and tool execution, while consequences are controlled by deterministic workflow code. Tool schemas constrain input and permissions are enforced again at execution.

Celery accepts durable background work. Workflow graphs containing model extraction or RAG are queued; short deterministic graphs can complete inline. A singleton beat scheduler emits recovery sweeps. Generic workflow DAGs use SQL run/step checkpoints, distinct from the LangGraph checkpoint saver used for agent execution. Claim-token fencing and a bounded node timeout protect against an expired worker lease committing stale progress. Persistent workflow runs and step states support inspection and restart; workers must verify current permissions instead of trusting permissions captured in a stale job. Approval requests bind evidence and target state. Approval decisions are atomic and duplicate submissions cannot execute an action twice. Payments and binding legal execution are outside this product.

## Observability and deployment

Request IDs connect structured API logs, audit records and execution metadata. Usage and cost estimates come from persisted model usage and configured rates. Sensitive prompts, documents and credentials are excluded from ordinary logs. Optional OpenTelemetry export supports a separately managed collector.

Docker Compose provides development Postgres/pgvector, Redis, Keycloak and MinIO. AWS definitions provide private ECS tasks, RDS, ElastiCache, S3, TLS ALB, secrets and CloudWatch. Existing production identity, DNS, certificate, malware scanner and on-call notification destinations are deployment prerequisites. See the deployment guide for bootstrap ordering and limitations.

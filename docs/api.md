# API guide

The live, authoritative contract is the generated OpenAPI document at `/api/openapi.json`; interactive documentation is at `/api/docs`. Business endpoints use `/api/v1`. The frontend's TypeScript client centralizes credentials, CSRF, parsing and errors.

## Authentication

Browser login starts the backend OIDC authorization-code flow. The callback validates code/PKCE/token claims and establishes an HTTP-only session. Mutating requests use the CSRF token expected by the backend; the frontend client handles this. External clients may supply a valid identity-provider Bearer token, but database membership and active-user authorization still apply.

`GET /api/v1/auth/me` returns the current authorized profile; logout invalidates the application session and follows the supported identity-provider logout path. Do not copy tokens into localStorage or embed credentials in URLs. HTTPS is mandatory for staging/production.

## Resources

| Resource | Purpose |
|---|---|
| `/agents` | Authorized agent configuration and execution |
| `/conversations` | Department-scoped message histories and AI interaction |
| `/documents` | Metadata, authorized upload/download, versions, reindex/deletion |
| `/workflows` | Validated workflow definitions, publication and runs |
| `/workflow-runs` | Run state, steps, evidence and resumable approvals |
| `/approvals` | Pending review and atomic approval/rejection |
| `/analytics` | Stored operational activity and model-usage estimates |
| `/audit-events` | Authorized audit history |

Consult live schemas for supported actions and required fields. A resource identifier alone never grants access. Collection filtering/pagination remains subject to department and resource permissions. Cross-department attempts return denial or not-found responses, without revealing confidential metadata.

## Streaming and failures

Streaming uses Server-Sent Events over an authenticated request. Clients must handle server error events and disconnects as well as a final completion event; an HTTP 200 stream opening does not mean the model completed successfully. Missing/unavailable providers return explicit actionable errors. Failed background work remains visible as durable processing or workflow state.

Request correlation IDs connect user-visible errors with sanitized operational logs. Do not log Authorization headers, session cookies, raw uploaded text, retrieved passages or model prompts in client error reporting. API versions and migrations should be reviewed together for compatibility before releases.

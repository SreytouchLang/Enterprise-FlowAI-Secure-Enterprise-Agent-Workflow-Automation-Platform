# ADR 001: backend authority and bounded AI execution

**Status:** accepted.

**Context:** Employees access confidential department information. Models consume untrusted documents and cannot be relied on to decide permissions or financial/legal consequences.

**Decision:** OIDC supplies identity. Database memberships and backend policies supply authorization. Document RLS and a restricted runtime role provide additional protection. Every tool has a schema and explicit permission check. Models operate within bounded workflows; human approval gates consequential record changes. Generic shell, SQL, HTTP, payment and agreement-execution tools are excluded.

**Consequences:** More deterministic code and tests are required than in an unrestricted agent demo. Approval/checkpoint state must be persisted. Adding a new tool means defining its authorization and audit behavior explicitly. A platform administrator does not automatically receive department content permissions.

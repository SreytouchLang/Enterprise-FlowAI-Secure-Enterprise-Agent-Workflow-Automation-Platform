# EnterpriseFlow AI web application

A Next.js App Router client for the FastAPI service. Runtime requests use the same-origin `/api` route handler, including streaming chat and OIDC redirects. This preserves HTTP-only session cookies and avoids embedding a container hostname into the build.

## Development

Use Node.js 22.13 or newer (Node.js 24 LTS is also supported).

```sh
npm ci
API_INTERNAL_URL=http://localhost:8000 npm run dev
```

The default API origin is `http://localhost:8000`. Docker sets `API_INTERNAL_URL=http://backend:8000`. `INTERNAL_API_BASE_URL` is accepted as an alias. The browser never needs an API key or access token; it uses `/api/v1/auth/me` to obtain its current session and CSRF token. The backend remains the authorization boundary.

## Routes

- `/`: live activity overview and department agents.
- `/workspace`: persisted conversations, streaming answers, source citations, and cancellation.
- `/agents`: provider/model, instructions, tools, budgets, and prompt versions.
- `/documents`: upload, access setting, hybrid search, preview, reindex, and deletion.
- `/workflows`: React Flow graph editor, draft/publish, execution input, and polling history.
- `/jobs`: persisted background processing results, retry, and queued cancellation.
- `/approvals`: evidence, comments, approval, and rejection.
- `/departments`: Finance invoices; HR onboarding/templates/summaries; Legal review/comparison; Operations normalization/conflict review.
- `/analytics`, `/audit`, `/notifications`, `/settings`: stored activity, audit export, notifications, provider configuration, identity onboarding, and department memberships.

AI extraction, legal reviews, HR summaries, and property imports enqueue durable jobs. The client polls real worker status, shows processing errors, and makes results recoverable in Background jobs after a browser restart.

Forms and buttons call the backend directly. Missing provider credentials, denied access, and failed requests are shown as errors. No runtime response fixtures or fake metrics are included. Synthetic seeded records are labeled when the backend identifies them. Theme preference is the only value persisted in browser local storage.

## Verification

```sh
npm run typecheck
npm run lint
npm test
npm run build
npx playwright install chromium
npm run test:e2e
```

Vitest covers request credentials and CSRF, provider failure handling, SSE chunk boundaries, graph validation, table filtering and pagination, and access errors. Playwright's `workspace.spec.ts` uses explicit API fixtures to isolate browser behavior; it does not prove external-provider or identity-provider integration. Real-service tests use the separately documented Compose stack. The fixture suite builds and serves the production frontend on port 3100 so navigation does not depend on development-time compilation.

For real-service OIDC, upload/isolation, invoice approval, Operations conflict import, platform administration, visual workflow approval, and missing-provider journeys, start the seeded Compose stack and run:

```sh
LIVE_E2E=true npm run test:e2e
```

This separate suite uses `http://localhost:3000` and the public synthetic development accounts. Override `E2E_BASE_URL`, `E2E_USERNAME`, `E2E_HR_USERNAME`, `E2E_MANAGER_USERNAME`, `E2E_ADMIN_USERNAME`, `E2E_OPERATIONS_USERNAME`, or `E2E_PASSWORD` when using a different development environment. It intentionally requires an unconfigured OpenAI provider to verify the outage path. It creates clearly named synthetic test records and verifies logout between roles. Uploaded isolation documents are deleted by their owner and changed agent configuration is restored. Invoices, properties, workflows, execution records, and their audit history remain because the API has no deletion endpoints for those records. Live traces are disabled to avoid retaining authentication traffic.

The local browser test binary can be installed outside the default cache with `PLAYWRIGHT_BROWSERS_PATH=/private/tmp/enterpriseflow-browsers`; set the same variable when executing the suite.

The project uses accessible Radix dialogs and shadcn-style primitives, Tailwind CSS, TanStack Query, React Hook Form and Zod, Recharts, Lucide icons, and React Flow. Layout supports mobile navigation, dark mode, loading states, empty states, and keyboard interactions.

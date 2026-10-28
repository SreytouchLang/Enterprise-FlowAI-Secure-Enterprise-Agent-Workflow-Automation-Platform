import { expect, test, type Page } from "@playwright/test";
const me = {
  id: "test-user",
  name: "Taylor Test",
  email: "taylor@example.test",
  roles: ["manager"],
  department_ids: ["finance"],
  permissions: [
    "analytics:read",
    "conversations:write",
    "workflows:read",
    "agents:execute",
    "agents:read",
    "agents:manage",
    "documents:read",
    "documents:upload",
    "workflows:manage",
    "approvals:decide",
  ],
  departments: [{ id: "finance", name: "Finance" }],
  csrf_token: "test-csrf-token",
};
const agent = {
  id: "agent-finance",
  name: "Finance assistant",
  department_id: "finance",
  description: "Review finance policies with cited sources.",
  provider: "openai",
  model: "gpt-4.1-mini",
  tools: ["search_documents"],
  system_prompt: "Ground responses in authorized evidence.",
  status: "active",
  max_tokens: 2048,
  budget_usd: "1.00",
  prompt_version: 1,
};
function paged(items: unknown[]) {
  return { items, total: items.length, limit: 100, offset: 0 };
}
async function baseApi(page: Page) {
  await page.route("**/api/v1/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    const results: Record<string, unknown> = {
      "/api/v1/auth/me": me,
      "/api/v1/departments": paged(me.departments),
      "/api/v1/agents": paged([agent]),
      "/api/v1/documents": paged([]),
      "/api/v1/conversations": paged([]),
      "/api/v1/approvals": paged([]),
      "/api/v1/workflows": paged([]),
      "/api/v1/workflow-runs": paged([]),
      "/api/v1/finance/invoices": paged([]),
      "/api/v1/analytics/overview": {
        active_agents: 1,
        workflows_completed: 4,
        pending_approvals: 0,
        documents_processed: 9,
        failed_executions: 1,
        estimated_minutes_saved: 20,
        estimate_method: "Test fixture methodology",
        activity: [],
        departments: [],
        provider_configured: false,
      },
    };
    if (path in results) await route.fulfill({ json: results[path] });
    else
      await route.fulfill({
        status: 404,
        json: { detail: `No test fixture for ${path}` },
      });
  });
}
test("signed-out users are directed to standard SSO", async ({ page }) => {
  await page.route("**/api/v1/auth/me", (route) =>
    route.fulfill({ status: 401, json: { detail: "Authentication required" } }),
  );
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: "Welcome to your workspace" }),
  ).toBeVisible();
  await expect(
    page.getByRole("link", { name: "Continue with SSO" }),
  ).toHaveAttribute("href", "/api/v1/auth/login");
  await expect(
    page.getByRole("navigation", { name: "Main navigation" }),
  ).toHaveCount(0);
});
test("dashboard displays API activity and supports responsive navigation", async ({
  page,
}) => {
  await baseApi(page);
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: "Welcome back, Taylor" }),
  ).toBeVisible();
  await expect(
    page.getByText("Connect an AI provider to get started."),
  ).toBeVisible();
  await page.getByRole("button", { name: "Switch to dark theme" }).click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByRole("button", { name: "Open navigation" }).click();
  await page
    .getByRole("link", { name: "Document center", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "Document center" }),
  ).toBeVisible();
});
test("a streamed answer displays its actual citation", async ({ page }) => {
  await baseApi(page);
  let finished = false;
  await page.route("**/api/v1/conversations", async (route) => {
    if (route.request().method() === "POST") {
      expect(route.request().headers()["x-csrf-token"]).toBe("test-csrf-token");
      await route.fulfill({
        status: 201,
        json: {
          id: "conversation-1",
          agent_id: agent.id,
          title: "Approval policy",
          messages: [],
        },
      });
    } else await route.fulfill({ json: paged([]) });
  });
  const citation = {
    document_id: "policy-1",
    document_name: "Finance policy",
    chunk_id: "chunk-1",
    location: "page 2",
    excerpt: "Invoices over the threshold require manager review.",
  };
  await page.route("**/api/v1/conversations/conversation-1", (route) =>
    route.fulfill({
      json: {
        id: "conversation-1",
        agent_id: agent.id,
        title: "Approval policy",
        messages: finished
          ? [
              {
                id: "answer-1",
                role: "assistant",
                content: "**Manager review** is required.",
                citations: [citation],
              },
            ]
          : [],
      },
    }),
  );
  await page.route(
    "**/api/v1/conversations/conversation-1/messages",
    async (route) => {
      finished = true;
      await route.fulfill({
        contentType: "text/event-stream",
        body: `event: delta\ndata: {"content":"**Manager review** is required."}\n\nevent: done\ndata: ${JSON.stringify({ message_id: "answer-1", citations: [citation] })}\n\n`,
      });
    },
  );
  await page.goto("/workspace");
  await page
    .getByLabel("Message your assistant")
    .fill("What approvals are required?");
  await page.getByRole("button", { name: "Send message" }).click();
  await expect(page.getByText("Manager review is required.")).toBeVisible();
  await expect(page.locator(".markdown-message strong")).toHaveText(
    "Manager review",
  );
  await page.getByRole("button", { name: "1. Finance policy" }).click();
  await expect(page.getByText(citation.excerpt)).toBeVisible();
});
test("approval decisions carry the reviewer comment and CSRF token", async ({
  page,
}) => {
  await baseApi(page);
  const approval = {
    id: "approval-1",
    title: "Review invoice INV-001",
    department_id: "finance",
    resource_type: "invoice",
    resource_id: "invoice-1",
    status: "pending",
    created_at: "2026-10-01T10:00:00Z",
    expires_at: "2027-10-01T10:00:00Z",
    payload: { total: "2500.00", currency: "USD" },
  };
  let approved = false;
  const decision = {
    id: "decision-1",
    decided_by: me.id,
    decision: "approved",
    comment: "Verified against the invoice.",
  };
  const currentApproval = () =>
    approved
      ? { ...approval, status: "approved", decisions: [decision] }
      : { ...approval, decisions: [] };
  await page.route("**/api/v1/approvals?*", (route) =>
    route.fulfill({ json: paged([currentApproval()]) }),
  );
  await page.route("**/api/v1/approvals/approval-1", (route) =>
    route.fulfill({ json: currentApproval() }),
  );
  await page.route("**/api/v1/approvals/approval-1/approve", async (route) => {
    expect(route.request().headers()["x-csrf-token"]).toBe("test-csrf-token");
    expect(route.request().postDataJSON()).toEqual({
      comment: "Verified against the invoice.",
    });
    approved = true;
    await route.fulfill({ json: currentApproval() });
  });
  await page.goto("/approvals");
  await page.getByRole("button", { name: "Review invoice INV-001" }).click();
  await page.getByLabel("Review comment").fill("Verified against the invoice.");
  await page.getByRole("button", { name: "Approve request" }).click();
  await expect(
    page.getByText("Approval recorded. Eligible workflows will resume."),
  ).toBeVisible();
  await expect(page.getByText("No pending approvals")).toBeVisible();
  await page.getByRole("button", { name: /^approved$/i }).click();
  await page.getByRole("button", { name: "Review invoice INV-001" }).click();
  const details = page.getByRole("dialog");
  await expect(
    details.getByRole("heading", { name: "Decision history" }),
  ).toBeVisible();
  await expect(details.locator("pre").last()).toContainText(decision.comment);
  await expect(
    details.getByRole("button", { name: "Approve request" }),
  ).toHaveCount(0);
});
test("workflow editor saves a validated graph and publishes its returned ID", async ({
  page,
}) => {
  await baseApi(page);
  let saved = false;
  let published = false;
  await page.route("**/api/v1/workflows", async (route) => {
    if (route.request().method() !== "POST")
      return route.fulfill({ json: paged([]) });
    const body = route.request().postDataJSON();
    expect(body.definition.nodes.map((n: { type: string }) => n.type)).toEqual([
      "start",
      "approval",
      "end",
    ]);
    expect(body.definition.edges).toHaveLength(2);
    saved = true;
    await route.fulfill({
      status: 201,
      json: {
        ...body,
        id: "workflow-1",
        status: "draft",
        published_version: null,
      },
    });
  });
  await page.route("**/api/v1/workflows/workflow-1/publish", async (route) => {
    published = true;
    await route.fulfill({
      json: { id: "workflow-1", status: "published", published_version: 1 },
    });
  });
  await page.goto("/workflows");
  await page.getByRole("button", { name: "Create workflow" }).click();
  await page.getByLabel("Workflow name").fill("Invoice review");
  await page.getByRole("button", { name: "Publish", exact: true }).click();
  await expect(
    page.getByText("Workflow published and ready to run."),
  ).toBeVisible();
  expect(saved && published).toBe(true);
});
test("unavailable AI provider is shown as an error", async ({ page }) => {
  await baseApi(page);
  await page.route("**/api/v1/conversations", (route) =>
    route.fulfill({ status: 503, json: { detail: "Provider unavailable" } }),
  );
  await page.goto("/workspace");
  await page.getByLabel("Message your assistant").fill("Explain this invoice");
  await page.getByRole("button", { name: "Send message" }).click();
  await expect(page.getByText("Provider unavailable").first()).toBeVisible();
  await expect(
    page.getByText("No response content was received."),
  ).toBeVisible();
});

test("an administrator saves an existing agent with immutable department ownership", async ({
  page,
}) => {
  await baseApi(page);
  let saved = false;
  await page.route("**/api/v1/agents/agent-finance", async (route) => {
    expect(route.request().method()).toBe("PATCH");
    const body = route.request().postDataJSON();
    expect(body.department_id).toBe("finance");
    expect(body.tools).toEqual(["search_documents"]);
    expect(body.max_iterations).toBe(4);
    expect(body).not.toHaveProperty("id");
    saved = true;
    await route.fulfill({ json: { ...agent, ...body, prompt_version: 2 } });
  });
  await page.goto("/agents");
  await page
    .getByRole("button", { name: "Edit Finance assistant", exact: true })
    .click();
  await page
    .getByLabel("System instructions")
    .fill("Answer using authorized evidence and cite every supported claim.");
  await page.getByRole("button", { name: "Save configuration" }).click();
  await expect(page.getByText("Agent configuration updated.")).toBeVisible();
  expect(saved).toBe(true);
});

test("a platform-only administrator sees configuration without business navigation", async ({
  page,
}) => {
  await baseApi(page);
  await page.route("**/api/v1/auth/me", (route) =>
    route.fulfill({
      json: {
        ...me,
        roles: ["platform_admin"],
        departments: [],
        department_ids: [],
        permissions: [
          "platform:admin",
          "agents:read",
          "agents:manage",
          "members:manage",
        ],
      },
    }),
  );
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: "Your AI team" }),
  ).toBeVisible();
  await expect(
    page
      .getByRole("navigation", { name: "Main navigation" })
      .getByRole("link", { name: "Document center" }),
  ).toHaveCount(0);
  await expect(
    page
      .getByRole("navigation", { name: "Main navigation" })
      .getByRole("link", { name: "AI workspace" }),
  ).toHaveCount(0);
  await expect(
    page.getByRole("button", {
      name: "Execution history for Finance assistant",
    }),
  ).toBeDisabled();
  await expect(
    page.getByRole("button", { name: "Edit Finance assistant", exact: true }),
  ).toBeEnabled();
});

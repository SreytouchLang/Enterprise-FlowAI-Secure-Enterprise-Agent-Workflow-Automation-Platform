import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { QueryClient, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { Providers } from "@/components/providers";
import { Shell } from "@/components/shell";
import { Workspace } from "@/components/workspace";
import { api, requestHeaders, setCsrfToken, User } from "@/lib/api";

vi.mock("next/navigation", () => ({
  usePathname: () => "/workspace",
  useRouter: () => ({ replace: vi.fn() }),
}));

const user: User = {
  id: "user-1",
  name: "Finance Employee",
  email: "finance@example.test",
  roles: ["employee"],
  department_ids: ["finance"],
  departments: [{ id: "finance", name: "Finance" }],
  permissions: ["conversations:write", "documents:read"],
  csrf_token: "session-csrf",
};
const originalScrollIntoView = Object.getOwnPropertyDescriptor(
  Element.prototype,
  "scrollIntoView",
);
function response(body: unknown, status = 200) {
  return { ok: status < 400, status, json: async () => body };
}
function CachedDocuments() {
  const documents = useQuery({
    queryKey: ["documents"],
    queryFn: ({ signal }) => api<{ name: string }[]>("/documents", { signal }),
  });
  return documents.data?.map((document) => (
    <p key={document.name}>{document.name}</p>
  ));
}
function observeClient(onClient: (client: QueryClient) => void) {
  function CacheProbe() {
    const client = useQueryClient();
    useEffect(() => onClient(client), [client]);
    return null;
  }
  return <CacheProbe />;
}
afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  setCsrfToken("");
  window.history.replaceState(null, "", window.location.pathname);
  if (originalScrollIntoView)
    Object.defineProperty(
      Element.prototype,
      "scrollIntoView",
      originalScrollIntoView,
    );
  else Reflect.deleteProperty(Element.prototype, "scrollIntoView");
});

describe("expired sessions", () => {
  it("clears local authentication and business data before the sign-out redirect", async () => {
    let client!: QueryClient;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) => {
        if (url === "/api/v1/auth/me") return response(user);
        if (url === "/api/v1/documents")
          return response([{ name: "Confidential invoice" }]);
        if (url === "/api/v1/auth/logout")
          return response({ logout_url: "#signed-out" });
        throw new Error(`Unexpected request: ${url}`);
      }),
    );
    render(
      <Providers>
        {observeClient((value) => {
          client = value;
        })}
        <Shell>
          <CachedDocuments />
        </Shell>
      </Providers>,
    );
    expect(await screen.findByText("Confidential invoice")).toBeVisible();
    fireEvent.click(screen.getByTitle("Sign out"));
    expect(
      await screen.findByRole("link", { name: "Continue with SSO" }),
    ).toBeVisible();
    expect(client.getQueryData(["me"])).toBeNull();
    expect(client.getQueryData(["documents"])).toBeUndefined();
    expect(requestHeaders({}, "POST")).not.toHaveProperty("X-CSRF-Token");
    await waitFor(() => expect(window.location.hash).toBe("#signed-out"));
  });

  it("returns to sign-in and clears cached business data when a cached user refresh receives 401", async () => {
    let client!: QueryClient;
    let expired = false;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) => {
        if (url === "/api/v1/auth/me")
          return expired
            ? response({ detail: "Session expired" }, 401)
            : response(user);
        if (url === "/api/v1/documents")
          return response([{ name: "Confidential invoice" }]);
        throw new Error(`Unexpected request: ${url}`);
      }),
    );
    render(
      <Providers>
        {observeClient((value) => {
          client = value;
        })}
        <Shell>
          <CachedDocuments />
        </Shell>
      </Providers>,
    );
    expect(await screen.findByText("Confidential invoice")).toBeVisible();
    expect(requestHeaders({}, "POST")).toHaveProperty(
      "X-CSRF-Token",
      "session-csrf",
    );
    const pending = vi.fn();
    let finishReport!: (result: { name: string }) => void;
    // Work already in flight must not restore confidential data after sign-out.
    void client
      .fetchQuery({
        queryKey: ["pending-report"],
        queryFn: ({ signal }) =>
          new Promise<{ name: string }>((resolve) => {
            finishReport = resolve;
            signal.addEventListener("abort", pending, { once: true });
          }),
      })
      .catch(() => {});
    expired = true;
    await act(async () => {
      await client.invalidateQueries({ queryKey: ["me"] });
    });
    expect(
      await screen.findByRole("link", { name: "Continue with SSO" }),
    ).toBeVisible();
    expect(screen.queryByText("Confidential invoice")).not.toBeInTheDocument();
    expect(client.getQueryData(["me"])).toBeNull();
    expect(client.getQueryData(["documents"])).toBeUndefined();
    await act(async () => finishReport({ name: "Late confidential report" }));
    expect(client.getQueryData(["pending-report"])).toBeUndefined();
    expect(pending).toHaveBeenCalledOnce();
    expect(requestHeaders({}, "POST")).not.toHaveProperty("X-CSRF-Token");
  });

  it("ends the session when the chat streaming endpoint responds with 401", async () => {
    let client!: QueryClient;
    Object.defineProperty(Element.prototype, "scrollIntoView", {
      configurable: true,
      value: vi.fn(),
    });
    const fetcher = vi.fn(async (url: string, options?: RequestInit) => {
      if (url === "/api/v1/auth/me") return response(user);
      if (url === "/api/v1/agents")
        return response({ items: [{ id: "agent-1", name: "Finance Agent" }] });
      if (url === "/api/v1/conversations")
        return options?.method === "POST"
          ? response({ id: "conversation-1" })
          : response({ items: [] });
      if (url === "/api/v1/conversations/conversation-1")
        return response({ id: "conversation-1", messages: [] });
      if (url === "/api/v1/conversations/conversation-1/messages")
        return response({ detail: "Session expired" }, 401);
      throw new Error(`Unexpected request: ${url}`);
    });
    vi.stubGlobal("fetch", fetcher);
    render(
      <Providers>
        {observeClient((value) => {
          client = value;
        })}
        <Shell>
          <Workspace />
        </Shell>
      </Providers>,
    );
    fireEvent.change(await screen.findByLabelText("Message your assistant"), {
      target: { value: "Review our policy" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Send message" }));
    expect(
      await screen.findByRole("link", { name: "Continue with SSO" }),
    ).toBeVisible();
    expect(client.getQueryData(["me"])).toBeNull();
    expect(client.getQueryData(["agents"])).toBeUndefined();
    expect(client.getQueryData(["conversations"])).toBeUndefined();
    expect(requestHeaders({}, "POST")).not.toHaveProperty("X-CSRF-Token");
    await waitFor(() =>
      expect(fetcher).toHaveBeenCalledWith(
        "/api/v1/conversations/conversation-1/messages",
        expect.objectContaining({ method: "POST" }),
      ),
    );
  });
});

describe("chat cancellation", () => {
  it.each(["stop", "unmount"])(
    "cancels conversation creation on %s and prevents a late response from starting a stream",
    async (action) => {
      Object.defineProperty(Element.prototype, "scrollIntoView", {
        configurable: true,
        value: vi.fn(),
      });
      let creationSignal: AbortSignal | undefined;
      let finishCreation!: (result: ReturnType<typeof response>) => void;
      const fetcher = vi.fn(async (url: string, options?: RequestInit) => {
        if (url === "/api/v1/auth/me") return response(user);
        if (url === "/api/v1/agents")
          return response({
            items: [{ id: "agent-1", name: "Finance Agent" }],
          });
        if (url === "/api/v1/conversations") {
          if (options?.method !== "POST") return response({ items: [] });
          creationSignal = options.signal ?? undefined;
          // A delayed response may already be buffered when cancellation happens.
          return new Promise<ReturnType<typeof response>>((resolve) => {
            finishCreation = resolve;
          });
        }
        throw new Error(`Unexpected request: ${url}`);
      });
      vi.stubGlobal("fetch", fetcher);
      const view = render(
        <Providers>
          <Shell>
            <Workspace />
          </Shell>
        </Providers>,
      );
      fireEvent.change(await screen.findByLabelText("Message your assistant"), {
        target: { value: "Review our policy" },
      });
      fireEvent.click(screen.getByRole("button", { name: "Send message" }));
      await waitFor(() => expect(finishCreation).toBeTypeOf("function"));
      if (action === "stop")
        fireEvent.click(screen.getByRole("button", { name: "Stop response" }));
      else view.unmount();
      expect(creationSignal).toBeDefined();
      expect(creationSignal?.aborted).toBe(true);
      await act(async () => finishCreation(response({ id: "conversation-1" })));
      expect(
        fetcher.mock.calls.some(([url]) =>
          url.startsWith("/api/v1/conversations/conversation-1"),
        ),
      ).toBe(false);
      if (action === "stop") {
        expect(await screen.findByText(/Response stopped/)).toBeVisible();
        expect(screen.getByLabelText("Message your assistant")).toBeEnabled();
      }
    },
  );
});

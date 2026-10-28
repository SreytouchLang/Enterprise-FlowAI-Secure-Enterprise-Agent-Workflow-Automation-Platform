import { describe, it, expect, vi, afterEach } from "vitest";
import {
  api,
  ApiError,
  consumeEvents,
  requestHeaders,
  setCsrfToken,
} from "@/lib/api";
import { ReadableStream } from "node:stream/web";
import { TextEncoder, TextDecoder } from "node:util";
vi.stubGlobal("TextDecoder", TextDecoder);
function stream(parts: string[]) {
  return new ReadableStream({
    start(controller) {
      for (const part of parts)
        controller.enqueue(new TextEncoder().encode(part));
      controller.close();
    },
  }) as unknown as globalThis.ReadableStream<Uint8Array>;
}
afterEach(() => {
  vi.unstubAllGlobals();
  vi.stubGlobal("TextDecoder", TextDecoder);
  setCsrfToken("");
});
describe("secure API client", () => {
  it("attaches CSRF only to mutations and uses credentialed same-origin requests", async () => {
    setCsrfToken("session-csrf");
    const fetcher = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ id: "ok" }),
    });
    vi.stubGlobal("fetch", fetcher);
    await api("/agents", { method: "POST", body: { name: "Finance" } });
    expect(fetcher).toHaveBeenCalledWith(
      "/api/v1/agents",
      expect.objectContaining({
        credentials: "include",
        headers: {
          "Content-Type": "application/json",
          "X-CSRF-Token": "session-csrf",
        },
        method: "POST",
      }),
    );
    expect(requestHeaders(undefined, "GET")).not.toHaveProperty("X-CSRF-Token");
  });
  it("does not turn provider or authorization failure into a success", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: false,
        status: 503,
        json: async () => ({ detail: "Provider unavailable" }),
      }),
    );
    await expect(
      api("/agents/x/execute", { method: "POST", body: {} }),
    ).rejects.toEqual(new ApiError(503, "Provider unavailable"));
  });
  it("does not set multipart content type so the browser supplies its boundary", () => {
    const body = new FormData();
    body.append("department_id", "finance");
    expect(requestHeaders(body, "POST")).not.toHaveProperty("Content-Type");
  });
});
describe("standardized server errors", () => {
  it("includes field-level validation messages", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: false,
        status: 422,
        json: async () => ({
          error: {
            code: "validation_error",
            message: "Request validation failed",
            fields: [
              {
                field: "body.total",
                message: "Send monetary values as decimal strings",
              },
            ],
          },
        }),
      }),
    );
    await expect(
      api("/finance/invoices/manual", { method: "POST", body: {} }),
    ).rejects.toThrow("body.total: Send monetary values as decimal strings");
  });
});

describe("SSE reader", () => {
  it("decodes events split across arbitrary chunks and CRLF boundaries", async () => {
    const events: unknown[] = [];
    await consumeEvents(
      stream([
        "event: del",
        'ta\r\ndata: {"content":"Hello"}\r',
        '\n\r\nevent: done\ndata: {"citations":[]}\n\n',
      ]),
      (e) => events.push(e),
    );
    expect(events).toEqual([
      { event: "delta", data: { content: "Hello" } },
      { event: "done", data: { citations: [] } },
    ]);
  });
  it("preserves multiline event data and final frames", async () => {
    const events: unknown[] = [];
    await consumeEvents(
      stream(['event: done\ndata: {"message_id":\ndata: "saved"}']),
      (e) => events.push(e),
    );
    expect(events).toEqual([{ event: "done", data: { message_id: "saved" } }]);
  });
  it("propagates streamed provider errors to the caller", async () => {
    await expect(
      consumeEvents(
        stream(['event: error\ndata: {"message":"Outage"}\n\n']),
        (e) => {
          if (e.event === "error") throw new Error(String(e.data.message));
        },
      ),
    ).rejects.toThrow("Outage");
  });
  it("cancels an open stream when an event handler rejects a provider error", async () => {
    const cancel = vi.fn();
    const openStream = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(
          new TextEncoder().encode(
            'event: error\ndata: {"message":"Outage"}\n\n',
          ),
        );
      },
      cancel,
    }) as unknown as globalThis.ReadableStream<Uint8Array>;
    await expect(
      consumeEvents(openStream, (event) => {
        throw new Error(String(event.data.message));
      }),
    ).rejects.toThrow("Outage");
    expect(cancel).toHaveBeenCalledWith(new Error("Outage"));
    expect(openStream.locked).toBe(false);
  });
});

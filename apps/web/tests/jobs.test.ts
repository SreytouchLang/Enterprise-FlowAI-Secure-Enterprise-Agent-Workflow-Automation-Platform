import { afterEach, describe, expect, it, vi } from "vitest";
import { businessRequest, waitForJob } from "@/lib/api";
const base = {
  id: "job-1",
  kind: "invoice",
  attempts: 1,
  created_at: "2026-10-14",
  updated_at: "2026-10-14",
};
function response(body: unknown) {
  return { ok: true, status: 200, json: async () => body };
}
afterEach(() => vi.unstubAllGlobals());
describe("durable business jobs", () => {
  it("waits through actual worker states and returns only the persisted completion result", async () => {
    const fetcher = vi
      .fn()
      .mockResolvedValueOnce(response({ job_id: "job-1", status: "queued" }))
      .mockResolvedValueOnce(
        response({ ...base, status: "completed", result: { id: "invoice-1" } }),
      );
    vi.stubGlobal("fetch", fetcher);
    const progress = vi.fn();
    await expect(
      businessRequest(
        "/finance/invoices",
        { document_id: "document-1" },
        progress,
      ),
    ).resolves.toEqual({ id: "invoice-1" });
    expect(fetcher.mock.calls[1][0]).toBe("/api/v1/jobs/job-1");
    expect(progress).toHaveBeenCalledWith(
      expect.objectContaining({ status: "completed" }),
    );
  });
  it("polls retrying jobs instead of misreporting an intermediate error", async () => {
    const fetcher = vi
      .fn()
      .mockResolvedValueOnce(
        response({
          ...base,
          status: "retrying",
          error_code: "temporary",
          result: null,
        }),
      )
      .mockResolvedValueOnce(
        response({ ...base, status: "completed", result: { id: "record-1" } }),
      );
    vi.stubGlobal("fetch", fetcher);
    await expect(
      waitForJob("job-1", { intervalMs: 0, maxPolls: 2 }),
    ).resolves.toEqual({ id: "record-1" });
  });
  it("exposes permanent provider errors without returning a fake record", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        response({
          ...base,
          status: "dead_letter",
          error_code: "provider_not_configured",
          error_message: "OpenAI is not configured.",
          result: null,
        }),
      ),
    );
    await expect(waitForJob("job-1")).rejects.toThrow(
      "OpenAI is not configured.",
    );
  });
  it("preserves synchronous manual invoice results", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(response({ id: "manual-invoice" })),
    );
    await expect(
      businessRequest("/finance/invoices/manual", {}),
    ).resolves.toEqual({ id: "manual-invoice" });
  });
  it("reports a still-running job ID when the polling window expires", async () => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValue(
          response({ ...base, status: "running", result: null }),
        ),
    );
    await expect(waitForJob("job-1", { maxPolls: 1 })).rejects.toThrow(
      "Job job-1 is still processing",
    );
  });
});

"use client";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { CirclePlay, RefreshCw, X } from "lucide-react";
import { useState } from "react";
import {
  api,
  BackgroundJob,
  dateTime,
  human,
  jsonText,
  list,
  Page,
} from "@/lib/api";
import { Badge, Busy, DataTable, ErrorState, Heading, Loading } from "./common";
import { useToast } from "./providers";
import { Button } from "./ui/button";
import { Dialog } from "./ui/dialog";
export function Jobs() {
  const query = useQuery({
    queryKey: ["jobs"],
    queryFn: () => api<Page<BackgroundJob>>("/jobs?limit=100"),
    refetchInterval: 5000,
  });
  const [selected, setSelected] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [confirm, setConfirm] = useState<"retry" | "cancel" | null>(null);
  const toast = useToast();
  const client = useQueryClient();
  const detail = useQuery({
    queryKey: ["job", selected],
    queryFn: () => api<BackgroundJob>(`/jobs/${selected}`),
    enabled: !!selected,
    refetchInterval: 5000,
  });
  async function action() {
    if (!selected || !confirm) return;
    setBusy(true);
    try {
      await api(`/jobs/${selected}/${confirm}`, { method: "POST" });
      toast(
        confirm === "retry"
          ? "Job queued for another attempt."
          : "Job cancelled.",
      );
      setConfirm(null);
      client.invalidateQueries({ queryKey: ["jobs"] });
      client.invalidateQueries({ queryKey: ["job", selected] });
    } catch (e) {
      toast(e instanceof Error ? e.message : "Unable to update job", true);
    } finally {
      setBusy(false);
    }
  }
  const job = detail.data;
  return (
    <>
      <Heading
        title="Background jobs"
        description="Track durable document and department processing, including work submitted before you closed your browser."
        action={
          <Button variant="outline" onClick={() => query.refetch()}>
            <RefreshCw size={15} />
            Refresh
          </Button>
        }
      />
      {query.isPending ? (
        <Loading />
      ) : query.error ? (
        <ErrorState error={query.error} />
      ) : (
        <DataTable
          items={list(query.data)}
          filterKey={(j) => `${j.kind} ${j.id} ${j.status}`}
          onRow={(j) => setSelected(j.id)}
          columns={[
            {
              key: "kind",
              label: "Job",
              render: (j) => (
                <span className="table-primary">
                  <CirclePlay size={17} />
                  {human(j.kind)}
                </span>
              ),
            },
            {
              key: "status",
              label: "Status",
              render: (j) => <Badge value={j.status} />,
            },
            { key: "attempts", label: "Attempts", render: (j) => j.attempts },
            {
              key: "created",
              label: "Submitted",
              render: (j) => dateTime(j.created_at),
            },
            {
              key: "updated",
              label: "Last updated",
              render: (j) => dateTime(j.updated_at),
            },
          ]}
        />
      )}
      <Dialog
        open={!!selected && !confirm}
        onOpenChange={() => setSelected(null)}
        title={job ? human(job.kind) : "Job details"}
        description="The worker persists progress and results. Only your own authorized jobs are visible."
      >
        {detail.isPending ? (
          <Loading />
        ) : detail.error ? (
          <ErrorState error={detail.error} />
        ) : (
          job && (
            <>
              <dl className="detail-grid">
                <div>
                  <dt>Status</dt>
                  <dd>
                    <Badge value={job.status} />
                  </dd>
                </div>
                <div>
                  <dt>Attempts</dt>
                  <dd>{job.attempts}</dd>
                </div>
                <div>
                  <dt>Job ID</dt>
                  <dd>{job.id}</dd>
                </div>
                <div>
                  <dt>Last updated</dt>
                  <dd>{dateTime(job.updated_at)}</dd>
                </div>
              </dl>
              {job.error_code && (
                <div className="error-state" role="alert">
                  <p>{job.error_message || human(job.error_code)}</p>
                </div>
              )}
              {job.status === "completed" ? (
                <>
                  <h3>Completed result</h3>
                  <pre>{jsonText(job.result)}</pre>
                </>
              ) : job.status !== "dead_letter" && job.status !== "cancelled" ? (
                <p className="text-muted">
                  Processing continues in the background. You can close this
                  dialog and return later.
                </p>
              ) : null}
              <div className="form-actions">
                {job.status === "dead_letter" && (
                  <Button onClick={() => setConfirm("retry")}>
                    <RefreshCw size={14} />
                    Retry job
                  </Button>
                )}
                {["queued", "retrying"].includes(job.status) && (
                  <Button
                    variant="outline"
                    onClick={() => setConfirm("cancel")}
                  >
                    <X size={14} />
                    Cancel queued job
                  </Button>
                )}
              </div>
            </>
          )
        )}
      </Dialog>
      <Dialog
        open={!!confirm}
        onOpenChange={() => setConfirm(null)}
        title={
          confirm === "retry" ? "Retry this job?" : "Cancel this queued job?"
        }
        description={
          confirm === "retry"
            ? "The worker will retry this request using your current permissions. Verify that the underlying issue is resolved."
            : "The queued attempt will be cancelled. Work that has already started cannot be cancelled here."
        }
      >
        <div className="form-actions">
          <Button
            variant="outline"
            disabled={busy}
            onClick={() => setConfirm(null)}
          >
            Back
          </Button>
          <Button
            disabled={busy}
            variant={confirm === "cancel" ? "destructive" : "default"}
            onClick={action}
          >
            {busy ? (
              <Busy />
            ) : confirm === "retry" ? (
              "Confirm retry"
            ) : (
              "Confirm cancellation"
            )}
          </Button>
        </div>
      </Dialog>
    </>
  );
}

"use client";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, ShieldCheck, X } from "lucide-react";
import { useState } from "react";
import {
  api,
  Approval,
  dateTime,
  human,
  jsonText,
  list,
  Page,
} from "@/lib/api";
import {
  Badge,
  Busy,
  DataTable,
  ErrorState,
  Field,
  Heading,
  Loading,
} from "./common";
import { Button } from "./ui/button";
import { Dialog } from "./ui/dialog";
import { useToast, useUser } from "./providers";
export function Approvals() {
  const { data: user } = useUser();
  const query = useQuery({
    queryKey: ["approvals"],
    queryFn: () => api<Page<Approval>>("/approvals?limit=100"),
    refetchInterval: 15000,
  });
  const client = useQueryClient();
  const toast = useToast();
  const [selected, setSelected] = useState<Approval | null>(null);
  const [comment, setComment] = useState("");
  const [busy, setBusy] = useState(false);
  const [filter, setFilter] = useState("pending");
  const detail = useQuery({
    queryKey: ["approval", selected?.id],
    queryFn: () => api<Approval>(`/approvals/${selected?.id}`),
    enabled: !!selected,
  });
  async function decide(action: "approve" | "reject") {
    if (!selected) return;
    setBusy(true);
    try {
      const decided = await api<Approval>(
        `/approvals/${selected.id}/${action}`,
        {
          method: "POST",
          body: { comment },
        },
      );
      client.setQueryData(["approval", selected.id], decided);
      toast(
        action === "approve"
          ? "Approval recorded. Eligible workflows will resume."
          : "Rejection recorded.",
      );
      setSelected(null);
      setComment("");
      client.invalidateQueries({ queryKey: ["approvals"] });
      client.invalidateQueries({ queryKey: ["overview"] });
    } catch (e) {
      toast(
        e instanceof Error ? e.message : "Decision could not be recorded",
        true,
      );
    } finally {
      setBusy(false);
    }
  }
  const record = detail.data || selected;
  return (
    <>
      <Heading
        title="Approvals"
        description="Review the evidence, add your judgment, and keep consequential decisions in human hands."
      />
      <div className="tab-list">
        {["pending", "approved", "rejected", "all"].map((status) => (
          <button
            key={status}
            className={filter === status ? "active" : ""}
            onClick={() => setFilter(status)}
          >
            {human(status)}
          </button>
        ))}
      </div>
      {query.isPending ? (
        <Loading />
      ) : query.error ? (
        <ErrorState error={query.error} retry={() => query.refetch()} />
      ) : (
        <DataTable
          items={list(query.data).filter(
            (a) => filter === "all" || a.status === filter,
          )}
          onRow={(a) => {
            setSelected(a);
            setComment("");
          }}
          filterKey={(a) => `${a.title} ${a.resource_type}`}
          emptyTitle={
            filter === "pending"
              ? "No pending approvals"
              : "No matching approvals"
          }
          columns={[
            {
              key: "title",
              label: "Request",
              render: (a) => (
                <span className="table-primary">
                  <ShieldCheck size={17} />
                  {a.title}
                </span>
              ),
            },
            {
              key: "type",
              label: "Resource",
              render: (a) => human(a.resource_type),
            },
            {
              key: "status",
              label: "Status",
              render: (a) => <Badge value={a.status} />,
            },
            {
              key: "date",
              label: "Requested",
              render: (a) => dateTime(a.created_at),
            },
            {
              key: "expires",
              label: "Expires",
              render: (a) => dateTime(a.expires_at),
            },
          ]}
        />
      )}
      <Dialog
        open={!!selected}
        onOpenChange={() => setSelected(null)}
        title={record?.title || "Review request"}
        description="Confirm that this action is appropriate before recording your decision."
      >
        {detail.isPending ? (
          <Loading />
        ) : detail.error ? (
          <ErrorState error={detail.error} />
        ) : (
          record && (
            <>
              <dl className="detail-grid">
                <div>
                  <dt>Status</dt>
                  <dd>
                    <Badge value={record.status} />
                  </dd>
                </div>
                <div>
                  <dt>Expires</dt>
                  <dd>{dateTime(record.expires_at)}</dd>
                </div>
                <div>
                  <dt>Resource</dt>
                  <dd>{human(record.resource_type)}</dd>
                </div>
                <div>
                  <dt>Record ID</dt>
                  <dd>{record.resource_id}</dd>
                </div>
              </dl>
              <h3>Information for review</h3>
              <pre>{jsonText(record.payload)}</pre>
              {record.decisions?.length ? (
                <>
                  <h3>Decision history</h3>
                  <pre>{jsonText(record.decisions)}</pre>
                </>
              ) : null}
              {record.status === "pending" &&
                !user?.permissions.includes("approvals:decide") && (
                  <p className="text-muted">
                    This request is waiting for an authorized reviewer.
                  </p>
                )}
              {record.status === "pending" &&
                user?.permissions.includes("approvals:decide") && (
                  <>
                    <Field
                      label="Review comment"
                      hint="Include the reasoning behind your decision."
                    >
                      <textarea
                        rows={3}
                        value={comment}
                        onChange={(e) => setComment(e.target.value)}
                        maxLength={3000}
                      />
                    </Field>
                    <div className="form-actions">
                      <Button
                        variant="destructive"
                        disabled={busy}
                        onClick={() => decide("reject")}
                      >
                        <X size={15} />
                        Reject
                      </Button>
                      <Button disabled={busy} onClick={() => decide("approve")}>
                        {busy ? (
                          <Busy />
                        ) : (
                          <>
                            <Check size={15} />
                            Approve request
                          </>
                        )}
                      </Button>
                    </div>
                  </>
                )}
            </>
          )
        )}
      </Dialog>
    </>
  );
}

"use client";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Agent, api, dateTime, Item, jsonText, list, Page } from "@/lib/api";
import { Badge, DataTable, ErrorState, Loading } from "./common";
import { Dialog } from "./ui/dialog";
export function AgentHistory({
  agent,
  onClose,
}: {
  agent: Agent | null;
  onClose: () => void;
}) {
  const [trace, setTrace] = useState<Item | null>(null);
  const query = useQuery({
    queryKey: ["agent-executions", agent?.id],
    queryFn: () => api<Page<Item>>(`/agents/${agent?.id}/executions`),
    enabled: !!agent,
  });
  return (
    <Dialog
      open={!!agent}
      onOpenChange={() => {
        setTrace(null);
        onClose();
      }}
      title={`${agent?.name || "Agent"} execution history`}
      description="Execution traces are scoped to your own authorized requests."
    >
      {query.isPending ? (
        <Loading />
      ) : query.error ? (
        <ErrorState error={query.error} />
      ) : (
        <DataTable
          items={list(query.data)}
          onRow={setTrace}
          columns={[
            {
              key: "execution",
              label: "Execution",
              render: (r) => r.id.slice(0, 12),
            },
            {
              key: "status",
              label: "Status",
              render: (r) => <Badge value={r.status} />,
            },
            {
              key: "duration",
              label: "Duration",
              render: (r) => `${String(r.duration_ms)} ms`,
            },
            {
              key: "created",
              label: "Started",
              render: (r) => dateTime(r.created_at),
            },
          ]}
        />
      )}{" "}
      {trace && (
        <div style={{ marginTop: 20 }}>
          <h3>Prompt version {String(trace.prompt_version)}</h3>
          {trace.error_code ? (
            <p className="danger-text">{String(trace.error_code)}</p>
          ) : null}
          <pre>{jsonText(trace.trace)}</pre>
        </div>
      )}
    </Dialog>
  );
}

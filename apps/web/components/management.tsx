"use client";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Bell, Check, Download, RefreshCw, ShieldCheck } from "lucide-react";
import { useState } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import {
  api,
  dateTime,
  human,
  Item,
  jsonText,
  list,
  Overview,
  Page,
} from "@/lib/api";
import {
  Badge,
  DataTable,
  Empty,
  ErrorState,
  Heading,
  Loading,
} from "./common";
import { ActivityChart } from "./dashboard";
import { useToast, useUser } from "./providers";
import { Button } from "./ui/button";
import { Dialog } from "./ui/dialog";
import { Members } from "./members";
import { Evaluation } from "./evaluation";
export function Analytics() {
  const query = useQuery({
    queryKey: ["overview"],
    queryFn: () => api<Overview>("/analytics/overview"),
  });
  const costs = useQuery({
    queryKey: ["costs"],
    queryFn: () => api<Page<Item>>("/analytics/costs"),
  });
  return (
    <>
      <Heading
        title="Analytics"
        description="Understand the activity, reliability, and resource use behind your team’s automation."
        action={
          <Button
            variant="outline"
            onClick={() => {
              query.refetch();
              costs.refetch();
            }}
          >
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
        query.data && (
          <>
            <div className="metric-grid">
              {[
                {
                  label: "Completed workflows",
                  value: query.data.workflows_completed,
                },
                {
                  label: "Failed executions",
                  value: query.data.failed_executions,
                },
                {
                  label: "Documents processed",
                  value: query.data.documents_processed,
                },
                {
                  label: "Estimated minutes saved",
                  value: query.data.estimated_minutes_saved,
                },
              ].map((m) => (
                <div key={m.label} className="metric-card">
                  <div>{m.label}</div>
                  <strong>{m.value.toLocaleString()}</strong>
                  <small>
                    {m.label.includes("Estimated")
                      ? "Modeled estimate, not measured time"
                      : "From stored application activity"}
                  </small>
                </div>
              ))}
            </div>
            <p className="text-muted" style={{ marginBottom: 20 }}>
              Time-saving methodology: {query.data.estimate_method}
            </p>
            <div className="dashboard-grid">
              <section className="panel">
                <div className="panel-heading">
                  <div>
                    <h2>Execution reliability</h2>
                    <p>Completed and failed activity by day</p>
                  </div>
                </div>
                <ActivityChart data={query.data.activity} />
              </section>
              <section className="panel">
                <div className="panel-heading">
                  <div>
                    <h2>Department activity</h2>
                    <p>Executions within your authorized view</p>
                  </div>
                </div>
                {query.data.departments.length ? (
                  <div className="activity-chart">
                    <ResponsiveContainer width="100%" height={250}>
                      <BarChart
                        data={query.data.departments}
                        layout="vertical"
                        margin={{ left: 8, right: 20 }}
                      >
                        <CartesianGrid
                          horizontal={false}
                          stroke="var(--line)"
                        />
                        <XAxis
                          type="number"
                          allowDecimals={false}
                          tick={{ fontSize: 10, fill: "var(--muted)" }}
                        />
                        <YAxis
                          type="category"
                          dataKey="name"
                          width={95}
                          tick={{ fontSize: 10, fill: "var(--muted)" }}
                        />
                        <Tooltip
                          contentStyle={{
                            background: "var(--panel)",
                            border: "1px solid var(--line)",
                            borderRadius: 8,
                            fontSize: 12,
                          }}
                        />
                        <Bar
                          dataKey="executions"
                          fill="#399a87"
                          radius={[0, 4, 4, 0]}
                          barSize={22}
                        />
                      </BarChart>
                    </ResponsiveContainer>
                  </div>
                ) : (
                  <Empty title="No recorded executions" />
                )}
              </section>
            </div>
          </>
        )
      )}
      <div className="section-heading">
        <div>
          <h2>Provider resource use</h2>
          <p>Recorded tokens and estimated provider costs</p>
        </div>
      </div>
      {costs.isPending ? (
        <Loading />
      ) : costs.error ? (
        <ErrorState error={costs.error} />
      ) : (
        <DataTable<Item>
          items={list(costs.data).map((row, i) => ({
            ...row,
            id: row.id || String(i),
          }))}
          columns={[
            {
              key: "model",
              label: "Model",
              render: (r) => String(r.model || r.provider || "—"),
            },
            {
              key: "input",
              label: "Input tokens",
              render: (r) => String(r.input_tokens ?? 0),
            },
            {
              key: "output",
              label: "Output tokens",
              render: (r) => String(r.output_tokens ?? 0),
            },
            {
              key: "cost",
              label: "Estimated cost (USD)",
              render: (r) => String(r.cost_usd ?? r.estimated_cost_usd ?? "0"),
            },
          ]}
          emptyTitle="No provider usage recorded"
        />
      )}
    </>
  );
}
export function Audit() {
  const [selected, setSelected] = useState<Item | null>(null);
  const query = useQuery({
    queryKey: ["audit"],
    queryFn: () => api<Page<Item>>("/audit-events?limit=100"),
  });
  function download() {
    const data = JSON.stringify(list(query.data), null, 2);
    const url = URL.createObjectURL(
      new Blob([data], { type: "application/json" }),
    );
    const link = document.createElement("a");
    link.href = url;
    link.download = "enterpriseflow-audit.json";
    link.click();
    URL.revokeObjectURL(url);
  }
  return (
    <>
      <Heading
        title="Audit log"
        description="A traceable record of access, changes, executions, and human decisions."
        action={
          <Button variant="outline" disabled={!query.data} onClick={download}>
            <Download size={15} />
            Export visible records
          </Button>
        }
      />
      {query.isPending ? (
        <Loading />
      ) : query.error ? (
        <ErrorState error={query.error} retry={() => query.refetch()} />
      ) : (
        <DataTable
          items={list(query.data)}
          onRow={setSelected}
          filterKey={(r) => `${r.action} ${r.actor_id} ${r.resource_type}`}
          columns={[
            { key: "action", label: "Event", render: (r) => human(r.action) },
            {
              key: "actor",
              label: "Actor",
              render: (r) => String(r.actor_name || r.actor_id || "System"),
            },
            {
              key: "resource",
              label: "Resource",
              render: (r) => human(r.resource_type),
            },
            {
              key: "outcome",
              label: "Outcome",
              render: (r) => (
                <Badge
                  value={r.result || r.outcome || r.status || "recorded"}
                />
              ),
            },
            {
              key: "time",
              label: "Timestamp",
              render: (r) => dateTime(r.created_at),
            },
          ]}
        />
      )}
      <Dialog
        open={!!selected}
        onOpenChange={() => setSelected(null)}
        title="Audit event"
        description="Only metadata permitted by your audit scope is returned by the API."
      >
        <pre>{jsonText(selected)}</pre>
      </Dialog>
    </>
  );
}
type SettingsResponse = {
  environment: string;
  providers: { name: string; configured: boolean }[];
  default_provider: string;
  models: unknown;
  security: Record<string, unknown>;
};
export function Settings() {
  const { data: user } = useUser();
  const query = useQuery({
    queryKey: ["settings"],
    queryFn: () => api<SettingsResponse>("/settings"),
  });
  return (
    <>
      <Heading
        title="Settings"
        description="Your account, provider connections, and the controls that protect your workspace."
      />
      <div className="settings-grid">
        <section className="panel content-card">
          <h2>Your account</h2>
          {[
            { name: "Name", value: user?.name },
            { name: "Email", value: user?.email },
            { name: "Roles", value: user?.roles.map(human).join(", ") },
            {
              name: "Departments",
              value:
                user?.departments.map((d) => d.name).join(", ") ||
                "No business department access",
            },
          ].map((r) => (
            <div className="settings-row" key={r.name}>
              <span>{r.name}</span>
              <strong>{r.value}</strong>
            </div>
          ))}
          <p className="text-muted" style={{ marginTop: 17 }}>
            Your identity provider manages account membership and sign-in
            settings.
          </p>
        </section>
        <section className="panel content-card">
          <h2>Provider connections</h2>
          {query.isPending ? (
            <Loading />
          ) : query.error ? (
            <ErrorState error={query.error} />
          ) : (
            query.data && (
              <>
                {query.data.providers.map((provider) => (
                  <div key={provider.name} className="settings-row">
                    <strong>{human(provider.name)}</strong>
                    <Badge
                      value={
                        provider.configured ? "configured" : "not configured"
                      }
                    />
                  </div>
                ))}
                <div className="settings-row">
                  <span>Default provider</span>
                  <strong>{query.data.default_provider}</strong>
                </div>
                <div className="settings-row">
                  <span>Environment</span>
                  <strong>{query.data.environment}</strong>
                </div>
                <p className="text-muted" style={{ marginTop: 17 }}>
                  Credentials are configured in the deployment environment or
                  secret manager. Secret values are never displayed here.
                </p>
              </>
            )
          )}
        </section>
        <section className="panel content-card">
          <h2>Effective permissions</h2>
          <div className="pill-list">
            {user?.permissions.map((p) => (
              <span key={p} className="badge">
                <ShieldCheck size={11} />
                {human(p)}
              </span>
            ))}
          </div>
          <p className="text-muted" style={{ marginTop: 17 }}>
            Every API operation independently verifies your permissions and
            department scope.
          </p>
        </section>
        <section className="panel content-card">
          <h2>Security configuration</h2>
          {query.data ? (
            Object.entries(query.data.security).map(([key, value]) => (
              <div key={key} className="settings-row">
                <span>{human(key)}</span>
                <strong>
                  {typeof value === "boolean"
                    ? value
                      ? "Enabled"
                      : "Disabled"
                    : jsonText(value)}
                </strong>
              </div>
            ))
          ) : (
            <p className="text-muted">
              Security configuration is visible to authorized administrators.
            </p>
          )}
        </section>
      </div>
      <Evaluation />
      <Members />
    </>
  );
}
export function Notifications() {
  const client = useQueryClient();
  const toast = useToast();
  const query = useQuery({
    queryKey: ["notifications"],
    queryFn: () => api<Page<Item>>("/notifications?limit=100"),
    refetchInterval: 30000,
  });
  async function mark(id: string) {
    try {
      await api(`/notifications/${id}/read`, { method: "POST" });
      client.invalidateQueries({ queryKey: ["notifications"] });
    } catch (e) {
      toast(
        e instanceof Error ? e.message : "Unable to update notification",
        true,
      );
    }
  }
  return (
    <>
      <Heading
        title="Notifications"
        description="Keep up with workflow updates and requests that need your attention."
      />
      {query.isPending ? (
        <Loading />
      ) : query.error ? (
        <ErrorState error={query.error} />
      ) : (
        <section className="panel">
          {list(query.data).length ? (
            list(query.data).map((n) => (
              <div className="notification-row" key={n.id}>
                <span className="review-icon">
                  <Bell size={18} />
                </span>
                <div>
                  <h3>{String(n.title || "Workspace update")}</h3>
                  <p>{String(n.message || n.body || "")}</p>
                  <small>{dateTime(n.created_at)}</small>
                </div>
                {!(n.read_at || n.is_read) && (
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => mark(n.id)}
                  >
                    <Check size={13} />
                    Mark read
                  </Button>
                )}
              </div>
            ))
          ) : (
            <Empty
              title="Nothing to catch up on"
              description="Notifications appear when workflows or approval requests need your attention."
            />
          )}
        </section>
      )}
    </>
  );
}

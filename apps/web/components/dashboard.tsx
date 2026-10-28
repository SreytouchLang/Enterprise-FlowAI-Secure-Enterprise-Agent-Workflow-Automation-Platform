"use client";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import {
  ArrowRight,
  ArrowUpRight,
  Bot,
  CheckCheck,
  CircleAlert,
  FileText,
  GitBranch,
  MessageSquare,
  ShieldCheck,
  Sparkles,
} from "lucide-react";
import {
  api,
  Agent,
  Approval,
  list,
  Overview,
  Page,
  dateTime,
} from "@/lib/api";
import { useUser } from "./providers";
import { Badge, Empty, ErrorState, Heading, Loading } from "./common";
import { Button } from "./ui/button";
export function ActivityChart({ data }: { data: Overview["activity"] }) {
  return data.length ? (
    <div
      className="activity-chart"
      role="img"
      aria-label="Completed and failed workflow executions by date"
    >
      <ResponsiveContainer width="100%" height={250}>
        <AreaChart
          data={data}
          margin={{ top: 15, right: 8, left: -20, bottom: 0 }}
        >
          <defs>
            <linearGradient id="completed-fill" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#168374" stopOpacity={0.18} />
              <stop offset="95%" stopColor="#168374" stopOpacity={0} />
            </linearGradient>
          </defs>
          <CartesianGrid
            vertical={false}
            stroke="var(--line)"
            strokeDasharray="4 4"
          />
          <XAxis
            dataKey="date"
            axisLine={false}
            tickLine={false}
            tick={{ fontSize: 11, fill: "var(--muted)" }}
            tickFormatter={(value) => String(value).slice(5)}
          />
          <YAxis
            axisLine={false}
            tickLine={false}
            allowDecimals={false}
            tick={{ fontSize: 11, fill: "var(--muted)" }}
          />
          <Tooltip
            contentStyle={{
              background: "var(--panel)",
              border: "1px solid var(--line)",
              borderRadius: 10,
              fontSize: 12,
            }}
          />
          <Area
            type="monotone"
            dataKey="completed"
            name="Completed"
            stroke="#168374"
            fill="url(#completed-fill)"
            strokeWidth={2.5}
          />
          <Area
            type="monotone"
            dataKey="failed"
            name="Failed"
            stroke="#d98b45"
            fill="transparent"
            strokeWidth={2}
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  ) : (
    <Empty
      title="Your activity starts here"
      description="Execution history will appear as your team runs workflows."
    />
  );
}
export function Dashboard() {
  const { data: user } = useUser();
  const query = useQuery({
    queryKey: ["overview"],
    queryFn: () => api<Overview>("/analytics/overview"),
  });
  const agents = useQuery({
    queryKey: ["agents"],
    queryFn: () => api<Page<Agent>>("/agents"),
  });
  const approvals = useQuery({
    queryKey: ["approvals"],
    queryFn: () => api<Page<Approval>>("/approvals"),
  });
  return (
    <>
      <Heading
        eyebrow="WORKSPACE OVERVIEW"
        title={`Welcome back, ${user?.name?.split(" ")[0] || "there"}`}
        description="A clear view of your agents, your workflows, and what needs you next."
        action={
          <Button asChild>
            <Link href="/workspace">
              <Sparkles size={16} />
              Open AI workspace
              <ArrowUpRight size={15} />
            </Link>
          </Button>
        }
      />
      {query.isPending ? (
        <Loading />
      ) : query.error ? (
        <ErrorState error={query.error} retry={() => query.refetch()} />
      ) : (
        query.data && (
          <>
            <div className="metric-grid">
              {[
                {
                  label: "Active agents",
                  value: query.data.active_agents,
                  icon: Bot,
                  caption: "Available to your team",
                  color: "teal",
                },
                {
                  label: "Completed workflows",
                  value: query.data.workflows_completed,
                  icon: GitBranch,
                  caption: "From recorded executions",
                  color: "blue",
                },
                {
                  label: "Pending approvals",
                  value: query.data.pending_approvals,
                  icon: ShieldCheck,
                  caption: "Waiting for human review",
                  color: "amber",
                },
                {
                  label: "Processed documents",
                  value: query.data.documents_processed,
                  icon: FileText,
                  caption: "In your authorized library",
                  color: "violet",
                },
              ].map((m) => (
                <div className="metric-card" key={m.label}>
                  <div>
                    <span>{m.label}</span>
                    <span className={`metric-icon ${m.color}`}>
                      <m.icon size={18} />
                    </span>
                  </div>
                  <strong>{m.value.toLocaleString()}</strong>
                  <small>{m.caption}</small>
                </div>
              ))}
            </div>
            {!query.data.provider_configured && (
              <div className="notice">
                <CircleAlert size={18} />
                <span>
                  <strong>Connect an AI provider to get started.</strong> An
                  administrator can configure OpenAI or Anthropic credentials in
                  the deployment environment.
                </span>
                <Link href="/settings">
                  View settings
                  <ArrowRight size={14} />
                </Link>
              </div>
            )}
            <div className="dashboard-grid">
              <section className="panel">
                <div className="panel-heading">
                  <div>
                    <h2>Workflow activity</h2>
                    <p>A record of work moving forward</p>
                  </div>
                  <Link className="text-link" href="/analytics">
                    View analytics
                    <ArrowUpRight size={14} />
                  </Link>
                </div>
                <div className="chart-legend">
                  <span>
                    <i />
                    Completed
                  </span>
                  <span>
                    <i className="amber-dot" />
                    Failed
                  </span>
                </div>
                <ActivityChart data={query.data.activity} />
              </section>
              <section className="panel review-panel">
                <div className="panel-heading">
                  <div>
                    <h2>Needs your attention</h2>
                    <p>Human judgment, where it matters</p>
                  </div>
                  <ShieldCheck size={19} />
                </div>
                {approvals.isPending ? (
                  <Loading />
                ) : approvals.error ? (
                  <ErrorState error={approvals.error} />
                ) : list(approvals.data).filter((a) => a.status === "pending")
                    .length ? (
                  <div className="review-list">
                    {list(approvals.data)
                      .filter((a) => a.status === "pending")
                      .slice(0, 3)
                      .map((a) => (
                        <Link
                          key={a.id}
                          href="/approvals"
                          className="review-item"
                        >
                          <span className="review-icon">
                            <FileText size={18} />
                          </span>
                          <div>
                            <strong>{a.title}</strong>
                            <small>{dateTime(a.created_at)}</small>
                            <Badge value={a.status} />
                          </div>
                          <ArrowUpRight size={15} />
                        </Link>
                      ))}
                    <Link className="text-link" href="/approvals">
                      Review all approvals
                      <ArrowRight size={14} />
                    </Link>
                  </div>
                ) : (
                  <Empty
                    title="You’re all caught up"
                    description="Approvals that need your review will appear here."
                  />
                )}
              </section>
            </div>
          </>
        )
      )}
      <div className="section-heading">
        <div>
          <h2>Your AI team</h2>
          <p>Specialized agents. Shared purpose.</p>
        </div>
        <Link href="/agents" className="text-link">
          Manage agents
          <ArrowUpRight size={14} />
        </Link>
      </div>
      {agents.isPending ? (
        <Loading />
      ) : agents.error ? (
        <ErrorState error={agents.error} />
      ) : list(agents.data).length ? (
        <div className="agent-grid">
          {list(agents.data)
            .slice(0, 4)
            .map((a, i) => (
              <Link
                key={a.id}
                href={`/workspace?agent=${a.id}`}
                className="agent-card"
              >
                <div className="agent-card-top">
                  <span className={`agent-avatar agent-color-${i % 4}`}>
                    <Bot size={22} />
                  </span>
                  <Badge value={a.status} />
                </div>
                <h3>{a.name}</h3>
                <p>{a.description}</p>
                <div className="agent-card-footer">
                  <span>
                    {a.provider} · {a.model}
                  </span>
                  <ArrowUpRight size={16} />
                </div>
              </Link>
            ))}
        </div>
      ) : (
        <div className="panel">
          <Empty
            title="Build your AI team"
            description="Configure department agents to give your team focused, permission-aware assistance."
            action={
              <Button asChild variant="outline">
                <Link href="/agents">
                  Manage agents
                  <ArrowRight size={15} />
                </Link>
              </Button>
            }
          />
        </div>
      )}
      <section className="getting-started">
        <div className="getting-started-icon">
          <CheckCheck size={24} />
        </div>
        <div>
          <h3>Make space for meaningful work.</h3>
          <p>
            Bring your knowledge together, automate a process, or ask your AI
            team a question.
          </p>
        </div>
        <div>
          <Button asChild variant="outline">
            <Link href="/documents">
              <FileText size={15} />
              Add knowledge
            </Link>
          </Button>
          <Button asChild variant="outline">
            <Link href="/workspace">
              <MessageSquare size={15} />
              Start a conversation
            </Link>
          </Button>
        </div>
      </section>
    </>
  );
}

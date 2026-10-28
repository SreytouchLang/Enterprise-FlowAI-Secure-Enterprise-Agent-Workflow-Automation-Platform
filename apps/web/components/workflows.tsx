"use client";
import {
  addEdge,
  Background,
  Controls,
  Handle,
  MiniMap,
  Position,
  ReactFlow,
  useEdgesState,
  useNodesState,
  type Connection,
  type Edge,
  type Node,
  type NodeProps,
} from "@xyflow/react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { GitBranch, Play, Plus, Save, Send, Trash2 } from "lucide-react";
import { useCallback, useState } from "react";
import { api, dateTime, human, jsonText, list, Page } from "@/lib/api";
import {
  defaultConfigs,
  defaultDefinition,
  Definition,
  NodeKind,
  nodeKinds,
  validateWorkflow,
  Workflow,
  WorkflowRun,
} from "@/lib/workflow";
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
type EditorNode = Node<
  { label: string; kind: NodeKind; config: Record<string, unknown> },
  "workflow"
>;
function WorkflowNode({ data, selected }: NodeProps<EditorNode>) {
  return (
    <div className={`workflow-node ${selected ? "selected" : ""}`}>
      {data.kind !== "start" && (
        <Handle type="target" position={Position.Left} />
      )}
      <span>
        <GitBranch size={15} />
      </span>
      {data.label}
      {data.kind !== "end" && (
        <Handle type="source" position={Position.Right} />
      )}
    </div>
  );
}
const nodeTypes = { workflow: WorkflowNode };
function toNodes(def: Definition): EditorNode[] {
  return def.nodes.map((n, i) => ({
    id: n.id,
    type: "workflow",
    position: n.position || { x: 50 + i * 230, y: 120 },
    data: { label: human(n.type), kind: n.type, config: n.config },
  }));
}
function toEdges(def: Definition): Edge[] {
  return def.edges.map((e, i) => ({
    id: `${e.source}-${e.target}-${i}`,
    source: e.source,
    target: e.target,
    label: e.branch,
    data: { branch: e.branch },
    animated: false,
  }));
}
export function Workflows() {
  const client = useQueryClient();
  const toast = useToast();
  const { data: user } = useUser();
  const query = useQuery({
    queryKey: ["workflows"],
    queryFn: () => api<Page<Workflow>>("/workflows?limit=100"),
  });
  const runs = useQuery({
    queryKey: ["workflow-runs"],
    queryFn: () => api<Page<WorkflowRun>>("/workflow-runs?limit=100"),
    refetchInterval: 10000,
  });
  const [tab, setTab] = useState("definitions");
  const [editing, setEditing] = useState<Workflow | null>(null);
  const [editor, setEditor] = useState(false);
  const [name, setName] = useState("");
  const [department, setDepartment] = useState("");
  const [nodes, setNodes, onNodesChange] = useNodesState<EditorNode>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [config, setConfig] = useState("{}");
  const [configError, setConfigError] = useState("");
  const [errors, setErrors] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [run, setRun] = useState<Workflow | null>(null);
  const [runInput, setRunInput] = useState("{}");
  const [selectedRun, setSelectedRun] = useState<string | null>(null);
  const runDetail = useQuery({
    queryKey: ["workflow-run", selectedRun],
    queryFn: () => api<WorkflowRun>(`/workflow-runs/${selectedRun}`),
    enabled: !!selectedRun,
    refetchInterval: 5000,
  });
  const onConnect = useCallback(
    (connection: Connection) =>
      setEdges((old) => addEdge({ ...connection, id: `e-${Date.now()}` }, old)),
    [setEdges],
  );
  function open(workflow?: Workflow) {
    const def = workflow?.definition || defaultDefinition;
    setEditing(workflow || null);
    setName(workflow?.name || "New approval workflow");
    setDepartment(workflow?.department_id || user?.departments[0]?.id || "");
    setNodes(toNodes(def));
    setEdges(toEdges(def));
    setSelected(null);
    setErrors([]);
    setConfigError("");
    setEditor(true);
  }
  function add(kind: NodeKind) {
    const id = `${kind}_${Date.now().toString(36)}`;
    setNodes((old) => [
      ...old,
      {
        id,
        type: "workflow",
        position: {
          x: 100 + (old.length % 3) * 220,
          y: 100 + Math.floor(old.length / 3) * 120,
        },
        data: { label: human(kind), kind, config: { ...defaultConfigs[kind] } },
      },
    ]);
    setSelected(id);
    setConfig(JSON.stringify(defaultConfigs[kind], null, 2));
  }
  function updateConfig(value: string) {
    setConfig(value);
    try {
      const parsed = JSON.parse(value);
      if (!parsed || Array.isArray(parsed) || typeof parsed !== "object")
        throw new Error();
      setNodes((old) =>
        old.map((n) =>
          n.id === selected ? { ...n, data: { ...n.data, config: parsed } } : n,
        ),
      );
      setConfigError("");
    } catch {
      setConfigError("Enter a valid JSON object.");
    }
  }
  function definition(): Definition {
    return {
      nodes: nodes.map((n) => ({
        id: n.id,
        type: n.data.kind,
        config: n.data.config,
        position: n.position,
      })),
      edges: edges.map((e) => ({
        source: e.source,
        target: e.target,
        ...(e.data?.branch ? { branch: String(e.data.branch) } : {}),
      })),
    };
  }
  async function save(publish = false) {
    const def = definition();
    const problems = validateWorkflow(def);
    if (!name.trim()) problems.push("Give the workflow a name.");
    if (!department) problems.push("Choose a department.");
    if (configError) problems.push(configError);
    setErrors(problems);
    if (problems.length) return;
    setBusy(true);
    try {
      const saved = await api<Workflow>(
        editing ? `/workflows/${editing.id}` : "/workflows",
        {
          method: editing ? "PATCH" : "POST",
          body: {
            name,
            ...(!editing ? { department_id: department } : {}),
            description: editing?.description || "",
            definition: def,
          },
        },
      );
      setEditing(saved);
      if (publish) {
        await api(`/workflows/${saved.id}/publish`, { method: "POST" });
        toast("Workflow published and ready to run.");
      } else toast("Workflow draft saved.");
      client.invalidateQueries({ queryKey: ["workflows"] });
    } catch (e) {
      toast(e instanceof Error ? e.message : "Unable to save workflow", true);
    } finally {
      setBusy(false);
    }
  }
  async function start() {
    if (!run) return;
    setBusy(true);
    try {
      const input = JSON.parse(runInput);
      if (!input || typeof input !== "object" || Array.isArray(input))
        throw new Error("Run input must be a JSON object.");
      const result = await api<WorkflowRun>(`/workflows/${run.id}/run`, {
        method: "POST",
        body: { input, idempotency_key: crypto.randomUUID() },
      });
      setRun(null);
      setSelectedRun(result.id);
      setTab("executions");
      toast("Workflow execution started.");
      client.invalidateQueries({ queryKey: ["workflow-runs"] });
    } catch (e) {
      toast(e instanceof Error ? e.message : "Unable to run workflow", true);
    } finally {
      setBusy(false);
    }
  }
  const selectedNode = nodes.find((n) => n.id === selected);
  return (
    <>
      <Heading
        title="Workflows"
        description="Turn repeatable work into governed processes, with a clear path from start to finish."
        action={
          <Button
            disabled={!user?.permissions.includes("workflows:manage")}
            onClick={() => open()}
          >
            <Plus size={16} />
            Create workflow
          </Button>
        }
      />
      <div className="tab-list">
        <button
          className={tab === "definitions" ? "active" : ""}
          onClick={() => setTab("definitions")}
        >
          Workflow library
        </button>
        <button
          className={tab === "executions" ? "active" : ""}
          onClick={() => setTab("executions")}
        >
          Execution history
        </button>
      </div>
      {editor && (
        <section className="panel" style={{ marginBottom: 25 }}>
          <div className="workflow-toolbar">
            <div className="inline-actions">
              <input
                aria-label="Workflow name"
                value={name}
                onChange={(e) => setName(e.target.value)}
              />
              <select
                aria-label="Workflow department"
                disabled={!!editing}
                value={department}
                onChange={(e) => setDepartment(e.target.value)}
              >
                {user?.departments.map((d) => (
                  <option key={d.id} value={d.id}>
                    {d.name}
                  </option>
                ))}
              </select>
            </div>
            <div className="inline-actions">
              <Button
                size="sm"
                variant="outline"
                onClick={() => setEditor(false)}
              >
                Close editor
              </Button>
              <Button
                size="sm"
                variant="outline"
                onClick={() => save()}
                disabled={
                  busy || !user?.permissions.includes("workflows:manage")
                }
              >
                <Save size={14} />
                Save draft
              </Button>
              <Button
                size="sm"
                onClick={() => save(true)}
                disabled={
                  busy || !user?.permissions.includes("workflows:manage")
                }
              >
                {busy ? (
                  <Busy />
                ) : (
                  <>
                    <Send size={14} />
                    Publish
                  </>
                )}
              </Button>
            </div>
          </div>
          {errors.length > 0 && (
            <div role="alert" className="error-state" style={{ margin: 15 }}>
              <ul>
                {errors.map((e) => (
                  <li key={e}>{e}</li>
                ))}
              </ul>
            </div>
          )}
          <div className="workflow-layout">
            <aside className="node-palette">
              <h3>Add a step</h3>
              {nodeKinds.map((kind) => (
                <button key={kind} onClick={() => add(kind)}>
                  <Plus size={12} />
                  {human(kind)}
                </button>
              ))}
            </aside>
            <div className="workflow-canvas">
              <ReactFlow
                nodes={nodes}
                edges={edges}
                nodeTypes={nodeTypes}
                onNodesChange={onNodesChange}
                onEdgesChange={onEdgesChange}
                onConnect={onConnect}
                onNodeClick={(_, node) => {
                  setSelected(node.id);
                  setConfig(JSON.stringify(node.data.config, null, 2));
                  setConfigError("");
                }}
                fitView
                deleteKeyCode={["Backspace", "Delete"]}
              >
                <Background gap={20} size={1} />
                <Controls />
                <MiniMap pannable zoomable style={{ width: 110, height: 65 }} />
              </ReactFlow>
            </div>
            <aside className="node-inspector">
              {selectedNode ? (
                <>
                  <h3>{human(selectedNode.data.kind)}</h3>
                  <Field
                    label="Step configuration"
                    error={configError}
                    hint="Only registered step fields are accepted by the server."
                  >
                    <textarea
                      aria-label="Step configuration JSON"
                      value={config}
                      onChange={(e) => updateConfig(e.target.value)}
                      spellCheck={false}
                    />
                  </Field>
                  {selectedNode.data.kind === "condition" &&
                    edges
                      .filter((e) => e.source === selectedNode.id)
                      .map((edge) => (
                        <Field key={edge.id} label={`Branch to ${edge.target}`}>
                          <select
                            value={String(edge.data?.branch || "")}
                            onChange={(e) =>
                              setEdges((old) =>
                                old.map((x) =>
                                  x.id === edge.id
                                    ? {
                                        ...x,
                                        label: e.target.value,
                                        data: {
                                          ...x.data,
                                          branch: e.target.value,
                                        },
                                      }
                                    : x,
                                ),
                              )
                            }
                          >
                            <option value="">Choose branch</option>
                            <option value="true">True</option>
                            <option value="false">False</option>
                          </select>
                        </Field>
                      ))}
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => {
                      setNodes((old) => old.filter((n) => n.id !== selected));
                      setEdges((old) =>
                        old.filter(
                          (e) => e.source !== selected && e.target !== selected,
                        ),
                      );
                      setSelected(null);
                    }}
                  >
                    <Trash2 size={13} />
                    Remove step
                  </Button>
                </>
              ) : (
                <>
                  <h3>Build your process</h3>
                  <p className="text-muted">
                    Add steps from the left. Drag between handles to connect
                    them. Select a step to configure its behavior.
                  </p>
                  <p className="text-muted" style={{ marginTop: 15 }}>
                    Save creates a draft. Publish validates the graph and makes
                    a version available to run.
                  </p>
                </>
              )}
            </aside>
          </div>
        </section>
      )}
      {tab === "definitions" ? (
        query.isPending ? (
          <Loading />
        ) : query.error ? (
          <ErrorState error={query.error} />
        ) : (
          <DataTable
            items={list(query.data)}
            filterKey={(w) => `${w.name} ${w.status}`}
            onRow={(w) => open(w)}
            columns={[
              {
                key: "name",
                label: "Workflow",
                render: (w) => (
                  <span className="table-primary">
                    <GitBranch size={17} />
                    {w.name}
                  </span>
                ),
              },
              {
                key: "status",
                label: "Status",
                render: (w) => <Badge value={w.status} />,
              },
              {
                key: "version",
                label: "Published version",
                render: (w) =>
                  w.published_version ? `v${w.published_version}` : "Draft",
              },
              {
                key: "steps",
                label: "Steps",
                render: (w) => w.definition.nodes.length,
              },
              {
                key: "run",
                label: "Run",
                render: (w) => (
                  <Button
                    size="sm"
                    variant="outline"
                    disabled={!w.published_version}
                    onClick={() => {
                      setRun(w);
                      setRunInput("{}");
                    }}
                  >
                    <Play size={13} />
                    Run workflow
                  </Button>
                ),
              },
            ]}
          />
        )
      ) : runs.isPending ? (
        <Loading />
      ) : runs.error ? (
        <ErrorState error={runs.error} />
      ) : (
        <DataTable
          items={list(runs.data)}
          filterKey={(r) => `${r.id} ${r.status}`}
          onRow={(r) => setSelectedRun(r.id)}
          columns={[
            {
              key: "id",
              label: "Execution",
              render: (r) => (
                <span>
                  {r.id.slice(0, 12)}
                  {r.is_demo && <small> · Seeded demo</small>}
                </span>
              ),
            },
            {
              key: "status",
              label: "Status",
              render: (r) => <Badge value={r.status} />,
            },
            {
              key: "created",
              label: "Started",
              render: (r) => dateTime(r.created_at),
            },
            {
              key: "completed",
              label: "Completed",
              render: (r) => dateTime(r.completed_at),
            },
          ]}
        />
      )}
      <Dialog
        open={!!run}
        onOpenChange={() => setRun(null)}
        title={`Run ${run?.name || "workflow"}`}
        description="Supply the workflow’s input as a JSON object. Consequential steps pause for authorized approval."
      >
        <Field label="Input JSON">
          <textarea
            className="code-editor"
            value={runInput}
            onChange={(e) => setRunInput(e.target.value)}
            spellCheck={false}
          />
        </Field>
        <div className="form-actions">
          <Button variant="outline" onClick={() => setRun(null)}>
            Cancel
          </Button>
          <Button onClick={start} disabled={busy}>
            {busy ? (
              <Busy />
            ) : (
              <>
                <Play size={14} />
                Start execution
              </>
            )}
          </Button>
        </div>
      </Dialog>
      <Dialog
        open={!!selectedRun}
        onOpenChange={() => setSelectedRun(null)}
        title="Execution details"
        description="Status and step results are read from the persisted execution record."
      >
        {runDetail.isPending ? (
          <Loading />
        ) : runDetail.error ? (
          <ErrorState error={runDetail.error} />
        ) : (
          runDetail.data && (
            <>
              <dl className="detail-grid">
                <div>
                  <dt>Status</dt>
                  <dd>
                    <Badge value={runDetail.data.status} />
                  </dd>
                </div>
                <div>
                  <dt>Started</dt>
                  <dd>{dateTime(runDetail.data.created_at)}</dd>
                </div>
              </dl>
              {runDetail.data.error && (
                <p className="danger-text">{runDetail.data.error}</p>
              )}
              <div className="run-timeline">
                {runDetail.data.steps?.map((step) => (
                  <div className="run-step" key={step.id}>
                    <h3>
                      {step.node_id} <Badge value={step.status} />
                    </h3>
                    {step.error && <p className="danger-text">{step.error}</p>}
                    {step.output !== undefined && (
                      <pre>{jsonText(step.output)}</pre>
                    )}
                  </div>
                ))}
              </div>
              <h3>Input</h3>
              <pre>{jsonText(runDetail.data.input)}</pre>
              {runDetail.data.output !== undefined && (
                <>
                  <h3>Output</h3>
                  <pre>{jsonText(runDetail.data.output)}</pre>
                </>
              )}
            </>
          )
        )}
      </Dialog>
    </>
  );
}

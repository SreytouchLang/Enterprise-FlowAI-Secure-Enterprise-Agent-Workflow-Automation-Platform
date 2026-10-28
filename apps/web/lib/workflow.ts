export const nodeKinds = [
  "start",
  "document_input",
  "text_extraction",
  "classification",
  "rag_search",
  "llm_extraction",
  "condition",
  "validation",
  "transform",
  "approval",
  "notification",
  "end",
] as const;
export type NodeKind = (typeof nodeKinds)[number];
export type FlowNode = {
  id: string;
  type: NodeKind;
  config: Record<string, unknown>;
  position?: { x: number; y: number };
};
export type FlowEdge = { source: string; target: string; branch?: string };
export type Definition = { nodes: FlowNode[]; edges: FlowEdge[] };
export type Workflow = {
  id: string;
  name: string;
  description: string;
  department_id: string;
  status: string;
  published_version: number | null;
  definition: Definition;
};
export type WorkflowRun = {
  id: string;
  workflow_id: string;
  status: string;
  created_at: string;
  completed_at?: string;
  error?: string;
  input: unknown;
  output?: unknown;
  steps?: {
    id: string;
    node_id: string;
    node_type: string;
    status: string;
    output?: unknown;
    error?: string;
  }[];
  is_demo?: boolean;
};
export function validateWorkflow(definition: Definition): string[] {
  const errors: string[] = [];
  const nodes = definition.nodes;
  const ids = new Set(nodes.map((n) => n.id));
  if (nodes.length < 2) errors.push("Add a start node and an end node.");
  if (ids.size !== nodes.length)
    errors.push("Every node must have a unique identifier.");
  if (nodes.filter((n) => n.type === "start").length !== 1)
    errors.push("A workflow must contain exactly one start node.");
  if (!nodes.some((n) => n.type === "end"))
    errors.push("Add at least one end node.");
  if (nodes.some((n) => !nodeKinds.includes(n.type)))
    errors.push("The workflow contains an unsupported node type.");
  if (definition.edges.some((e) => !ids.has(e.source) || !ids.has(e.target)))
    errors.push("All connections must reference existing nodes.");
  const visited = new Set<string>();
  const active = new Set<string>();
  let cyclic = false;
  function visit(id: string) {
    if (active.has(id)) {
      cyclic = true;
      return;
    }
    if (visited.has(id)) return;
    active.add(id);
    for (const edge of definition.edges.filter((e) => e.source === id))
      visit(edge.target);
    active.delete(id);
    visited.add(id);
  }
  for (const node of nodes) visit(node.id);
  if (cyclic)
    errors.push("Cycles are not allowed. Use a bounded, directed workflow.");
  const reachable = new Set<string>();
  function reach(id: string) {
    if (reachable.has(id)) return;
    reachable.add(id);
    for (const e of definition.edges.filter((e) => e.source === id))
      reach(e.target);
  }
  const start = nodes.find((n) => n.type === "start");
  if (start) reach(start.id);
  if (nodes.some((n) => !reachable.has(n.id)))
    errors.push("Connect every node to the start node.");
  for (const node of nodes) {
    const outgoing = definition.edges.filter((e) => e.source === node.id);
    if (
      node.type === "condition" &&
      (!outgoing.some((e) => e.branch === "true") ||
        !outgoing.some((e) => e.branch === "false"))
    )
      errors.push(`Condition ${node.id} needs true and false connections.`);
    if (node.type !== "end" && !outgoing.length)
      errors.push(`Connect ${node.id} to a following node.`);
    if (node.type === "end" && outgoing.length)
      errors.push("End nodes cannot have outgoing connections.");
  }
  return [...new Set(errors)];
}
export const defaultDefinition: Definition = {
  nodes: [
    { id: "start", type: "start", config: {}, position: { x: 50, y: 140 } },
    {
      id: "review",
      type: "approval",
      config: { title: "Manager review", expires_hours: 48 },
      position: { x: 290, y: 140 },
    },
    { id: "end", type: "end", config: {}, position: { x: 530, y: 140 } },
  ],
  edges: [
    { source: "start", target: "review" },
    { source: "review", target: "end" },
  ],
};
export const defaultConfigs: Record<NodeKind, Record<string, unknown>> = {
  start: {},
  document_input: { input_field: "document_id" },
  text_extraction: {},
  classification: {
    categories: {
      invoice: ["invoice", "amount due"],
      contract: ["agreement", "parties"],
    },
    fallback: "unclassified",
  },
  rag_search: { query: "Summarize relevant department policies", limit: 5 },
  llm_extraction: { schema: "invoice", provider: "openai" },
  condition: { field: "total", operator: "gt", value: 1000 },
  validation: { schema: "invoice" },
  transform: { assign: {} },
  approval: { title: "Manager review", expires_hours: 48 },
  notification: { title: "Workflow update", message: "Workflow completed" },
  end: {},
};
